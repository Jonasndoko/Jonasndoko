"""Module « Travaux techniques » (réservé à l'Administrateur).

1. Mise à jour des tables : ajouter, modifier, supprimer, désactiver les données (élèves, classes, options, années
   scolaires, niveaux, types de frais, devises, percepteurs...) et annuler un paiement.
2. Sauvegarde   3. Restauration   4. Réinitialisation
6. Données d'essai : 120 élèves fictifs, comptes et opérations de test, supprimables d'un clic.
5. Authentification et mots de passe : état des comptes, code de récupération temporaire (2 minutes) à remettre à un
   utilisateur qui a oublié son mot de passe, déblocage, journal des connexions.
(Les utilisateurs et leurs droits sont dans le module « Gestionnaire d'accès ».)
"""
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import acces
import config
import donnees
import droits
import essai
import migrations
import miseajour
import recuperation
import referentiels as ref
import reinitialisation
import sauvegarde
import security
from calendrier import SelecteurDate
from composants import (Fenetre, ModuleOnglets, afficher_mdp_provisoire, case_a_cocher, confirmer_par_saisie,
                        demander_motif, entete)
from database import lire_iso, maintenant
from ecrans_paiement import creer_arbre, ouvrir_fichier, vider_arbre
from theme import (BLANC, BORDURE, FOND_CLAIR, GRIS, NUIT, ORANGE, ROUGE, VERT, creer_bouton, creer_champ, definir_actif, police,
                   px)


# ================================================================== outils
def formater_taille(octets) -> str:
    if octets < 1024 * 1024:
        return f"{max(1, round(octets / 1024))} Ko"
    return f"{octets / (1024 * 1024):.1f}".replace(".", ",") + " Mo"


def formater_horodatage(texte) -> str:
    try:
        return lire_iso(texte).astimezone().strftime("%d/%m/%Y  %H:%M")
    except (TypeError, ValueError):
        return texte or "—"


def description_contenu(manifeste) -> str:
    c = (manifeste or {}).get("contenu") or {}
    if not c:
        return "—"
    return f"{c.get('eleves', 0)} élève(s), {c.get('paiements', 0)} paiement(s), {c.get('utilisateurs', 0)} compte(s)"


# ================================================================== 1) MISE À JOUR DES TABLES
def afficher_ou_defaut(champ, brut, defauts, modification) -> str:
    if modification:
        return ref.afficher_valeur(champ, brut.get(champ.nom))
    return str(defauts.get(champ.nom, ""))


class FormulaireTable(Fenetre):
    """Formulaire d'ajout / de modification, construit automatiquement d'après les champs de la table."""

    def __init__(self, parent, app, table, cle_pk=None):
        self.app, self.table, self.cle_pk = app, table, cle_pk
        modification = cle_pk is not None
        champs = [c for c in table.champs if not c.auto and not (c.genere and not modification)]
        colonnes = 2 if len(champs) > 6 else 1
        lignes = -(-len(champs) // colonnes)
        a_liste = (not modification) and any(c.multiple for c in champs)        # liste à cocher (ex. classes d'un tarif)
        super().__init__(parent, ("Modifier : " if modification else "Ajouter : ") + table.titre,
                         largeur=470 * colonnes + 60, hauteur=min(820, 200 + 76 * lignes + (170 if a_liste else 0)))
        brut = ref.lire(app.conn, app.session, table.cle, cle_pk) if modification else {}
        defauts = {} if modification else ref.valeurs_par_defaut(table.cle)

        self.widgets = {}                       # nom -> (champ, variable, {libellé: valeur} ou None)
        self.listes = {}                        # nom -> tous les libellés (pour le filtrage à la frappe)
        self.listes_multiples = {}              # nom -> (liste à cocher, {libellé: valeur})
        grille = tk.Frame(self.corps, bg=BLANC)
        grille.pack(fill="both", expand=True)
        for k in range(colonnes):
            grille.grid_columnconfigure(k, weight=1, uniform="champ")
        premier = None
        for i, c in enumerate(champs):
            cellule = tk.Frame(grille, bg=BLANC)
            cellule.grid(row=i % lignes, column=i // lignes, sticky="nwe", padx=(0, px(14)), pady=(0, px(6)))
            fige = modification and c.cle                         # la clé ne change pas après création
            if c.type == "oui_non":
                var = tk.BooleanVar(value=bool(brut.get(c.nom, 0)))
                self.variables.append(var)
                case_a_cocher(cellule, c.libelle, var).pack(anchor="w", pady=(px(18), 0))
                self.widgets[c.nom] = (c, var, None)
                continue
            tk.Label(cellule, text=c.libelle + (" *" if c.obligatoire else ""),
                     font=police(10, gras=True), fg=NUIT, bg=BLANC, anchor="w", justify="left",
                     wraplength=px(440)).pack(anchor="w")
            if c.multiple and not modification:
                association = {libelle: valeur for valeur, libelle in ref.options(app.conn, c.ref)}
                liste = tk.Listbox(cellule, selectmode="multiple", exportselection=False, height=7, font=police(11),
                                   activestyle="none", relief="flat", highlightthickness=1, highlightbackground=BORDURE,
                                   selectbackground=NUIT, selectforeground=BLANC)
                for libelle in association:
                    liste.insert("end", libelle)
                liste.pack(fill="x", pady=(px(3), px(2)))
                outils = tk.Frame(cellule, bg=BLANC)
                outils.pack(anchor="w")
                creer_bouton(outils, "Toutes", lambda l=liste: l.selection_set(0, "end"), style="secondaire",
                             grand=False).pack(side="left")
                creer_bouton(outils, "Aucune", lambda l=liste: l.selection_clear(0, "end"), style="secondaire",
                             grand=False).pack(side="left", padx=px(6))
                self.listes_multiples[c.nom] = (liste, association)
                self.widgets[c.nom] = (c, None, association)
                continue
            if c.type in ("choix", "reference"):
                if c.type == "choix":
                    association = {libelle: valeur for valeur, libelle in c.choix}
                else:
                    association = {libelle: valeur
                                   for valeur, libelle in ref.options(app.conn, c.ref, inclure=brut.get(c.nom))}
                valeur_init = brut.get(c.nom, defauts.get(c.nom))
                libelle_init = next((l for l, v in association.items() if str(v) == str(valeur_init)), "")
                var = self.variable(libelle_init)
                cb = ttk.Combobox(cellule, textvariable=var, values=list(association), font=police(11), width=36,
                                  state="disabled" if fige else ("readonly" if c.type == "choix" else "normal"))
                cb.pack(fill="x", ipady=px(2), pady=(px(3), 0))
                if c.type == "reference" and not fige:
                    self.listes[c.nom] = list(association)
                    cb.bind("<KeyRelease>", lambda e, cb=cb, v=var, n=c.nom: self._filtrer(e, cb, v, n))
                self.widgets[c.nom] = (c, var, association)
                champ_saisie = cb
            elif c.type == "date":
                var = self.variable(afficher_ou_defaut(c, brut, defauts, modification))
                selecteur = SelecteurDate(cellule, var, largeur=30, lecture_seule=fige)
                selecteur.pack(fill="x", pady=(px(3), 0))
                self.widgets[c.nom] = (c, var, None)
                champ_saisie = selecteur.champ
            else:
                var = self.variable(afficher_ou_defaut(c, brut, defauts, modification))
                champ_saisie = creer_champ(cellule, var, lecture_seule=fige, largeur=36)
                champ_saisie.pack(fill="x", ipady=px(5), pady=(px(3), 0))
                self.widgets[c.nom] = (c, var, None)
            if premier is None and not fige:
                premier = champ_saisie

        self.lbl_erreur = tk.Label(self.corps, text="", font=police(10), fg=ROUGE, bg=BLANC, anchor="w", justify="left",
                                   wraplength=px(470 * colonnes))
        self.lbl_erreur.pack(fill="x", pady=(px(4), px(4)))
        bas = tk.Frame(self.corps, bg=BLANC)
        bas.pack(fill="x", side="bottom")
        creer_bouton(bas, "Enregistrer", self._valider, grand=False).pack(side="left")
        creer_bouton(bas, "Annuler", self.destroy, style="secondaire", grand=False).pack(side="left", padx=px(10))
        tk.Label(bas, text="* obligatoire", font=police(9), fg=GRIS, bg=BLANC).pack(side="right")
        if premier is not None:
            premier.focus_set()

    def _filtrer(self, evenement, combo, var, nom):
        """Liste déroulante longue : on tape quelques lettres, elle se réduit."""
        if getattr(evenement, "keysym", "") in ("Up", "Down", "Left", "Right", "Return", "Tab", "Escape"):
            return
        tous = self.listes[nom]
        saisie = donnees.sans_accents(var.get())
        combo.config(values=[l for l in tous if saisie in donnees.sans_accents(l)] if saisie else tous)

    def _valider(self):
        saisie = {}
        for nom, (champ, var, association) in self.widgets.items():
            if nom in self.listes_multiples:
                liste, choix = self.listes_multiples[nom]
                noms = [liste.get(i) for i in liste.curselection()]
                saisie[nom] = [choix[n] for n in noms]
            elif champ.type == "oui_non":
                saisie[nom] = var.get()
            elif association is not None:
                saisie[nom] = association.get(var.get(), var.get())
            else:
                saisie[nom] = var.get()
        try:
            self.resultat = ref.enregistrer(self.app.conn, self.app.session, self.table.cle, saisie, self.cle_pk)
        except (ref.ErreurRef, PermissionError) as erreur:
            self.lbl_erreur.config(text=str(erreur))
            return
        self.destroy()


class PanneauTables(tk.Frame):
    """Gestion des tables de référence : choisir une table à gauche, la mettre à jour à droite."""

    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.table = None
        self.lignes = []                          # lignes affichées (dicts de referentiels.lister)
        self.arbre = None
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---- à gauche : les tables
        gauche = tk.Frame(self, bg=BLANC)
        gauche.grid(row=0, column=0, sticky="ns", padx=(px(24), px(8)), pady=px(14))
        tk.Label(gauche, text="Mise à jour des tables", font=police(16, gras=True, titre=True), fg=NUIT,
                 bg=BLANC).pack(anchor="w")
        tk.Label(gauche, text="Choisissez une table :", font=police(10), fg=GRIS, bg=BLANC).pack(anchor="w", pady=(px(2), px(6)))
        cadre, self.arbre_tables = creer_arbre(gauche, [("titre", "Tables", 250, "w")], hauteur=14)
        cadre.pack(fill="both", expand=True)
        for t in ref.TABLES.values():
            self.arbre_tables.insert("", "end", iid=t.cle, values=(t.titre,))
        self.arbre_tables.bind("<<TreeviewSelect>>", self._choisir_table)
        creer_bouton(gauche, "Structure de la base…", self.ouvrir_structure, style="secondaire", grand=False
                     ).pack(anchor="w", pady=(px(10), 0))
        creer_bouton(gauche, "Menu principal", self.app.afficher_menu, style="secondaire", grand=False
                     ).pack(anchor="w", pady=(px(6), 0))

        # ---- à droite : la table choisie
        droite = tk.Frame(self, bg=BLANC)
        droite.grid(row=0, column=1, sticky="nsew", padx=(px(8), px(24)), pady=px(14))
        self.lbl_titre = tk.Label(droite, text="", font=police(16, gras=True, titre=True), fg=NUIT, bg=BLANC, anchor="w")
        self.lbl_titre.pack(fill="x")
        self.lbl_aide = tk.Label(droite, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w", justify="left",
                                 wraplength=px(860))
        self.lbl_aide.pack(fill="x", pady=(px(2), px(8)))

        barre = tk.Frame(droite, bg=BLANC)
        barre.pack(fill="x")
        self.boutons = {
            "nouveau": creer_bouton(barre, "Ajouter", self.nouveau, grand=False),
            "modifier": creer_bouton(barre, "Modifier", self.modifier, style="secondaire", grand=False),
            "supprimer": creer_bouton(barre, "Supprimer", self.supprimer, style="danger", grand=False),
            "etat": creer_bouton(barre, "Désactiver", self.basculer, style="secondaire", grand=False),
            "annuler": creer_bouton(barre, "Annuler le reçu", self.annuler, style="danger", grand=False),
        }
        for i, b in enumerate(self.boutons.values()):
            b.grid(row=0, column=i, padx=(0, px(8)))
        barre.grid_columnconfigure(9, weight=1)
        tk.Label(barre, text="Rechercher :", font=police(10, gras=True), fg=NUIT, bg=BLANC).grid(
            row=0, column=10, padx=(px(24), px(6)))
        self.var_recherche = tk.StringVar()
        self.champ_recherche = creer_champ(barre, self.var_recherche, largeur=22)
        self.champ_recherche.grid(row=0, column=11, ipady=px(4))
        self.champ_recherche.bind("<KeyRelease>", lambda _e: self.recharger())

        self.zone_liste = tk.Frame(droite, bg=BLANC)
        self.zone_liste.pack(fill="both", expand=True, pady=(px(8), px(4)))
        self.lbl_compte = tk.Label(droite, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_compte.pack(fill="x")
        self.lbl_message = tk.Label(droite, text="", font=police(10, gras=True), fg=GRIS, bg=BLANC, anchor="w",
                                   justify="left", wraplength=px(860))
        self.lbl_message.pack(fill="x", pady=(px(4), 0))

    # --- affichage -------------------------------------------------------
    def au_affichage(self):
        if self.table is None:
            self.arbre_tables.selection_set(next(iter(ref.TABLES)))          # première table
        else:
            self.recharger()

    def _choisir_table(self, _e=None):
        selection = self.arbre_tables.selection()
        if not selection:
            return
        self.table = t = ref.table(selection[0])
        self.var_recherche.set("")
        self.lbl_message.config(text="")
        self.lbl_titre.config(text=t.titre)
        self.lbl_aide.config(text=t.aide)
        for nom, autorise in (("nouveau", t.peut_creer), ("modifier", t.peut_modifier), ("supprimer", t.peut_supprimer),
                              ("etat", t.peut_desactiver), ("annuler", t.peut_annuler)):
            if autorise:
                self.boutons[nom].grid()
            else:
                self.boutons[nom].grid_remove()
        self._construire_liste()
        self.recharger()

    def _construire_liste(self):
        for enfant in self.zone_liste.winfo_children():
            enfant.destroy()
        colonnes = [(f"c{i}", titre, largeur, ancre)
                    for i, (titre, _expr, largeur, ancre, _genre) in enumerate(self.table.colonnes)]
        cadre, self.arbre = creer_arbre(self.zone_liste, colonnes, hauteur=14)
        cadre.pack(fill="both", expand=True)
        self.arbre.tag_configure("inactif", foreground="#98A4C0")
        self.arbre.bind("<<TreeviewSelect>>", lambda _e: self._maj_boutons())

    def recharger(self, choisir=None):
        if self.table is None:
            return
        try:
            liste = ref.lister(self.app.conn, self.app.session, self.table.cle, self.var_recherche.get())
        except PermissionError as erreur:
            messagebox.showwarning("Accès refusé", str(erreur), parent=self)
            return
        self.lignes = liste["lignes"]
        vider_arbre(self.arbre)
        for i, l in enumerate(self.lignes):
            self.arbre.insert("", "end", iid=str(i), tags=(() if l["actif"] in (None, True) else ("inactif",)),
                              values=l["valeurs"])
        n_inactifs = sum(1 for l in self.lignes if l["actif"] is False)
        self.lbl_compte.config(text=f"{len(self.lignes)} élément(s)"
                                    + (f"   •   {n_inactifs} désactivé(s) (en gris)" if n_inactifs else ""))
        if choisir is not None:
            for i, l in enumerate(self.lignes):
                if l["cle"] == tuple(choisir):
                    self.arbre.selection_set(str(i))
                    break
        self._maj_boutons()

    def _ligne_choisie(self):
        selection = self.arbre.selection() if self.arbre is not None else ()
        return self.lignes[int(selection[0])] if selection else None

    def _maj_boutons(self):
        l, t = self._ligne_choisie(), self.table
        definir_actif(self.boutons["nouveau"], t.peut_creer)
        definir_actif(self.boutons["modifier"], bool(l) and t.peut_modifier)
        definir_actif(self.boutons["supprimer"], bool(l) and t.peut_supprimer)
        definir_actif(self.boutons["etat"], bool(l) and t.peut_desactiver)
        definir_actif(self.boutons["annuler"], bool(l) and t.peut_annuler and l["actif"] is True)
        if l and t.peut_desactiver:
            self.boutons["etat"].config(text="Désactiver" if l["actif"] else "Réactiver")

    def _message(self, texte, couleur=VERT):
        self.lbl_message.config(text=texte, fg=couleur)

    @staticmethod
    def _nom(ligne) -> str:
        return " - ".join(v for v in ligne["valeurs"][:2] if v)

    # --- actions ---------------------------------------------------------
    def nouveau(self):
        cle = FormulaireTable(self, self.app, self.table).attendre()
        if cle:
            self.recharger(choisir=cle)
            self._message("Ajouté.")

    def modifier(self):
        l = self._ligne_choisie()
        if not l:
            return
        cle = FormulaireTable(self, self.app, self.table, l["cle"]).attendre()
        if cle:
            self.recharger(choisir=cle)
            self._message("Modifié.")

    def supprimer(self):
        l = self._ligne_choisie()
        if not l or not messagebox.askyesno(
                "Supprimer", f"Supprimer définitivement :\n{self._nom(l)} ?\n\nSi la donnée est utilisée "
                             f"ailleurs, on vous proposera de supprimer aussi les données liées.", parent=self):
            return
        try:
            ref.supprimer(self.app.conn, self.app.session, self.table.cle, l["cle"])
        except ref.ErreurUtilisee as erreur:
            self._supprimer_avec_liees(l, erreur)
            return
        except (ref.ErreurRef, PermissionError) as erreur:
            messagebox.showwarning("Suppression impossible", str(erreur), parent=self)
            return
        self.recharger()
        self._message("Supprimé.")

    def _supprimer_avec_liees(self, l, erreur_initiale):
        """La donnée est utilisée ailleurs : on propose de supprimer aussi ce qui en dépend (sauf s'il y a des reçus)."""
        try:
            apercu = ref.apercu_suppression(self.app.conn, self.app.session, self.table.cle, l["cle"])
            if not apercu["possible"]:
                ref.supprimer_avec_liees(self.app.conn, self.app.session, self.table.cle, l["cle"])   # lève le message expliquant
            liste = "\n".join(f"   -  {titre} : {n}" for titre, n in apercu["liees"])
            if not messagebox.askyesno(
                    "Données liées",
                    f"{self._nom(l)} est utilisée par :\n{liste}\n\nSupprimer cette donnée ET toutes les données liées "
                    f"ci-dessus ?\n\nCette opération est définitive (une sauvegarde préalable est conseillée).",
                    icon="warning", parent=self):
                return
            ref.supprimer_avec_liees(self.app.conn, self.app.session, self.table.cle, l["cle"])
        except (ref.ErreurRef, PermissionError) as erreur:
            messagebox.showwarning("Suppression impossible", str(erreur), parent=self)
            return
        self.recharger()
        self._message("Supprimé, avec les données liées.")

    def basculer(self):
        l = self._ligne_choisie()
        if not l or l["actif"] is None:
            return
        if l["actif"] and not messagebox.askyesno(
                "Désactiver", f"Désactiver :\n{self._nom(l)} ?\n\nElle ne sera plus proposée dans les listes ; "
                              f"l'historique est conservé. Vous pourrez la réactiver.", parent=self):
            return
        try:
            ref.changer_etat(self.app.conn, self.app.session, self.table.cle, l["cle"], not l["actif"])
        except (ref.ErreurRef, PermissionError) as erreur:
            messagebox.showwarning("Opération impossible", str(erreur), parent=self)
            return
        self.recharger(choisir=l["cle"])
        self._message("Désactivé." if l["actif"] else "Réactivé.")

    def annuler(self):
        l = self._ligne_choisie()
        if not l:
            return
        n_recu = l["cle"][0]
        if demander_motif(
                self, "Annuler le reçu",
                f"Annuler le reçu {n_recu} ?\n\nIl ne sera plus compté dans la situation de l'élève ni dans les rapports, "
                f"et ne pourra plus être réimprimé. Cette opération est définitive ; le reçu lui-même n'est pas effacé.",
                lambda motif: ref.annuler_paiement(self.app.conn, self.app.session, n_recu, motif)):
            self.recharger(choisir=l["cle"])
            self._message(f"Reçu {n_recu} annulé.")

    def ouvrir_structure(self):
        FenetreStructure(self, self.app)


# ================================================================== structure de la base (outil secondaire)
class PanneauStructure(tk.Frame):
    def __init__(self, parent, app, fermer):
        super().__init__(parent, bg=BLANC)
        self.app = app
        self.analyse = None
        entete(self, "Structure de la base",
               "Compare les tables de la base à celles que le programme attend. Rien n'est jamais supprimé : les tables "
               "manquantes sont créées, les colonnes manquantes ajoutées. Une sauvegarde de sécurité est faite avant. "
               "Cette mise à jour est aussi faite automatiquement à chaque ouverture du programme.")
        self.lbl_etat = tk.Label(self, text="", font=police(12, gras=True), bg=BLANC, anchor="w", justify="left")
        self.lbl_etat.pack(fill="x")
        cadre, self.arbre = creer_arbre(self, [("table", "Table", 190, "w"), ("etat", "État", 170, "w"),
                                               ("lignes", "Lignes", 80, "e"), ("detail", "Détail", 400, "w")], hauteur=10)
        cadre.pack(fill="both", expand=True, pady=(px(8), px(6)))
        self.arbre.tag_configure("ok", foreground=VERT)
        self.arbre.tag_configure("faire", foreground=ORANGE)
        self.arbre.tag_configure("inconnue", foreground=GRIS)
        self.lbl_faire = tk.Label(self, text="", font=police(10), fg=NUIT, bg=BLANC, anchor="w", justify="left",
                                  wraplength=px(900))
        self.lbl_faire.pack(fill="x", pady=(px(4), px(6)))
        bas = tk.Frame(self, bg=BLANC)
        bas.pack(fill="x")
        self.btn_maj = creer_bouton(bas, "Mettre à jour la structure", self.mettre_a_jour, grand=False)
        self.btn_maj.pack(side="left")
        creer_bouton(bas, "Analyser à nouveau", self.analyser, style="secondaire", grand=False).pack(side="left", padx=px(10))
        creer_bouton(bas, "Vérifier l'intégrité des données", self.verifier, style="secondaire",
                     grand=False).pack(side="left")
        creer_bouton(bas, "Fermer", fermer, style="secondaire", grand=False).pack(side="right")
        self.lbl_resultat = tk.Label(self, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w", justify="left",
                                     wraplength=px(900))
        self.lbl_resultat.pack(fill="x", pady=(px(8), 0))

    def analyser(self):
        try:
            a = migrations.analyse_admin(self.app.conn, self.app.session)
        except PermissionError as erreur:
            messagebox.showwarning("Accès refusé", str(erreur), parent=self)
            return
        self.analyse = a
        vider_arbre(self.arbre)
        for t in a.tables:
            detail = ""
            if t.manquantes:
                detail = "Colonnes à ajouter : " + ", ".join(t.manquantes)
            elif t.en_trop:
                detail = "Colonnes supplémentaires conservées : " + ", ".join(t.en_trop)
            self.arbre.insert("", "end", iid=t.nom, values=(
                t.nom, t.libelle_statut, "" if t.statut == "MANQUANTE" else t.nb_lignes, detail),
                tags=("ok" if t.statut == "OK" else "inconnue" if t.statut == "INCONNUE" else "faire",))
        total = sum(1 for t in a.tables if t.statut != "INCONNUE")
        if a.bloquants:
            self.lbl_etat.config(fg=ROUGE, text="⚠  " + a.bloquants[0])
        elif a.a_faire:
            self.lbl_etat.config(fg=ORANGE, text=f"Mise à jour nécessaire  (structure n° {a.version_actuelle}, "
                                                 f"le programme attend le n° {a.version_cible})")
        else:
            self.lbl_etat.config(fg=VERT, text=f"✔  Les {total} tables sont à jour  (structure n° {a.version_actuelle}).")
        self.lbl_faire.config(text=("À faire :  " + "  •  ".join(a.lignes_a_faire())) if a.a_faire else "")
        definir_actif(self.btn_maj, a.a_faire and not a.bloquants)

    def mettre_a_jour(self):
        if not messagebox.askyesno("Structure de la base",
                                   "Mettre à jour la structure maintenant ?\n\nUne sauvegarde de sécurité sera créée avant.",
                                   parent=self):
            return
        try:
            actions = migrations.mise_a_jour_manuelle(self.app.conn, self.app.session)
        except (migrations.ErreurMiseAJour, PermissionError) as erreur:
            self.lbl_resultat.config(fg=ROUGE, text=str(erreur))
            return
        self.analyser()
        self.lbl_resultat.config(fg=VERT if actions else GRIS,
                                 text=("Mise à jour terminée :\n  •  " + "\n  •  ".join(actions)) if actions
                                 else "Rien à mettre à jour : tout était déjà à jour.")

    def verifier(self):
        try:
            resultats = migrations.controle_integrite(self.app.conn, self.app.session)
        except PermissionError as erreur:
            messagebox.showwarning("Accès refusé", str(erreur), parent=self)
            return
        ok = all(r[1] for r in resultats)
        self.lbl_resultat.config(fg=VERT if ok else ROUGE, text="\n".join(
            f"{'✔' if reussi else '✘'}  {nom} : {detail}" for nom, reussi, detail in resultats))


class FenetreStructure(Fenetre):
    def __init__(self, parent, app):
        super().__init__(parent, "Structure de la base", 980, 640)
        self.panneau = PanneauStructure(self.corps, app, self.destroy)
        self.panneau.pack(fill="both", expand=True)
        self.panneau.analyser()


# ================================================================== 2) SAUVEGARDE
class PanneauSauvegarde(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(24), pady=px(14))
        entete(corps, "Sauvegarde",
               "Crée une copie complète et cohérente de la base (élèves, paiements, comptes, journal), même pendant que "
               "le programme est ouvert. Le fichier obtenu (.csfbak) permet de tout retrouver en cas de panne ou de perte.")
        haut = tk.Frame(corps, bg=BLANC)
        haut.pack(fill="x")
        creer_bouton(haut, "Sauvegarder maintenant", self.sauvegarder_defaut, grand=False).pack(side="left")
        creer_bouton(haut, "Sauvegarder sur une clé USB / un autre dossier…", self.sauvegarder_ailleurs,
                     style="secondaire", grand=False).pack(side="left", padx=px(10))
        tk.Label(corps, text="⚠  Une sauvegarde rangée sur ce même ordinateur ne protège pas contre sa panne, sa perte ou "
                             "son vol : copiez régulièrement une sauvegarde sur une clé USB ou un autre disque. "
                             "Le fichier n'est pas chiffré : conservez-le en lieu sûr.",
                 font=police(10), fg=ORANGE, bg=BLANC, justify="left", anchor="w", wraplength=px(1000)
                 ).pack(fill="x", pady=(px(8), px(4)))
        self.lbl_resultat = tk.Label(corps, text="", font=police(10, gras=True), fg=VERT, bg=BLANC, anchor="w",
                                     justify="left", wraplength=px(1000))
        self.lbl_resultat.pack(fill="x")
        self.lbl_dossier = tk.Label(corps, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_dossier.pack(fill="x", pady=(px(8), px(4)))
        cadre, self.arbre = creer_arbre(corps, [("date", "Date", 170, "w"), ("fichier", "Fichier", 380, "w"),
                                                ("taille", "Taille", 90, "e"), ("contenu", "Contenu", 380, "w")], hauteur=9)
        cadre.pack(fill="both", expand=True)
        bas = tk.Frame(corps, bg=BLANC)
        bas.pack(fill="x", pady=(px(8), 0))
        creer_bouton(bas, "Ouvrir le dossier des sauvegardes", self.ouvrir_dossier, style="secondaire",
                     grand=False).pack(side="left")
        creer_bouton(bas, "Menu principal", self.app.afficher_menu, style="secondaire", grand=False).pack(side="right")

    def au_affichage(self):
        self.lbl_resultat.config(text="")
        self.actualiser()

    def actualiser(self):
        dossier = sauvegarde.dossier_defaut()
        self.lbl_dossier.config(text=f"Dossier des sauvegardes : {dossier}")
        vider_arbre(self.arbre)
        for i, s in enumerate(sauvegarde.lister(dossier)):
            self.arbre.insert("", "end", iid=str(i), values=(formater_horodatage(s["date"]), s["nom"],
                                                              formater_taille(s["taille"]),
                                                              description_contenu(s["manifeste"])))

    def _faire(self, dossier):
        try:
            chemin = sauvegarde.sauvegarder(self.app.conn, self.app.session, dossier)
        except (sauvegarde.ErreurSauvegarde, PermissionError) as erreur:
            self.lbl_resultat.config(fg=ROUGE, text=str(erreur))
            return
        self.lbl_resultat.config(fg=VERT, text=f"✔  Sauvegarde créée : {chemin}")
        self.actualiser()

    def sauvegarder_defaut(self):
        self._faire(None)

    def sauvegarder_ailleurs(self):
        dossier = filedialog.askdirectory(parent=self, title="Choisissez le dossier ou la clé USB de destination")
        if dossier:
            self._faire(dossier)

    def ouvrir_dossier(self):
        try:
            ouvrir_fichier(str(sauvegarde.dossier_defaut()))
        except OSError as erreur:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le dossier : {erreur}", parent=self)


# ================================================================== 3) RESTAURATION
class PanneauRestauration(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.fichier = None
        self.liste = []
        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(24), pady=px(14))
        entete(corps, "Restauration",
               "Remplace TOUTES les données actuelles par celles d'une sauvegarde. Le fichier est d'abord contrôlé "
               "(il est refusé s'il est abîmé ou modifié) et une sauvegarde de sécurité de la base actuelle est faite "
               "juste avant. À la fin, tout le monde doit se reconnecter.")
        cadre, self.arbre = creer_arbre(corps, [("date", "Date", 170, "w"), ("fichier", "Fichier", 380, "w"),
                                                ("taille", "Taille", 90, "e"), ("contenu", "Contenu", 380, "w")], hauteur=7)
        cadre.pack(fill="both", expand=True)
        self.arbre.bind("<<TreeviewSelect>>", self._choisir_dans_liste)
        ligne = tk.Frame(corps, bg=BLANC)
        ligne.pack(fill="x", pady=(px(8), 0))
        creer_bouton(ligne, "Choisir un autre fichier (clé USB…)", self.parcourir, style="secondaire",
                     grand=False).pack(side="left")
        self.lbl_fichier = tk.Label(corps, text="Aucun fichier choisi.", font=police(11, gras=True), fg=GRIS, bg=BLANC,
                                    anchor="w", justify="left", wraplength=px(1000))
        self.lbl_fichier.pack(fill="x", pady=(px(8), 2))
        self.lbl_resume = tk.Label(corps, text="", font=police(10), fg=NUIT, bg=BLANC, anchor="w", justify="left",
                                   wraplength=px(1000))
        self.lbl_resume.pack(fill="x")
        bas = tk.Frame(corps, bg=BLANC)
        bas.pack(fill="x", pady=(px(10), 0))
        self.btn_restaurer = creer_bouton(bas, "Restaurer cette sauvegarde…", self.restaurer, style="danger", grand=False)
        self.btn_restaurer.pack(side="left")
        definir_actif(self.btn_restaurer, False)
        creer_bouton(bas, "Menu principal", self.app.afficher_menu, style="secondaire", grand=False).pack(side="right")

    def au_affichage(self):
        self.fichier = None
        self.lbl_fichier.config(text="Aucun fichier choisi.", fg=GRIS)
        self.lbl_resume.config(text="")
        definir_actif(self.btn_restaurer, False)
        self.liste = sauvegarde.lister(sauvegarde.dossier_defaut())
        vider_arbre(self.arbre)
        for i, s in enumerate(self.liste):
            self.arbre.insert("", "end", iid=str(i), values=(formater_horodatage(s["date"]), s["nom"],
                                                              formater_taille(s["taille"]),
                                                              description_contenu(s["manifeste"])))

    def _choisir_dans_liste(self, _e=None):
        selection = self.arbre.selection()
        if selection:
            self._examiner(self.liste[int(selection[0])]["chemin"])

    def parcourir(self):
        fichier = filedialog.askopenfilename(
            parent=self, title="Choisissez la sauvegarde à restaurer",
            filetypes=[("Sauvegardes du programme", f"*{config.EXTENSION_SAUVEGARDE}"), ("Bases de données", "*.db"),
                       ("Tous les fichiers", "*.*")])
        if fichier:
            for iid in self.arbre.selection():
                self.arbre.selection_remove(iid)
            self._examiner(Path(fichier))

    def _examiner(self, chemin):
        self.fichier = None
        definir_actif(self.btn_restaurer, False)
        self.lbl_fichier.config(text=f"Fichier : {chemin}", fg=NUIT)
        try:
            r = sauvegarde.examiner(chemin)
        except sauvegarde.ErreurSauvegarde as erreur:
            self.lbl_resume.config(fg=ROUGE, text=f"✘  {erreur}")
            return
        lignes = [f"✔  Fichier contrôlé : {r['eleves']} élève(s), {r['paiements']} paiement(s) valide(s), "
                  f"{r['utilisateurs']} compte(s)."]
        if r["date"]:
            lignes.append(f"Sauvegarde faite le {formater_horodatage(r['date'])} (programme version {r['version_programme']}).")
        if not r["controle"]:
            lignes.append("Attention : fichier de base de données brut, sans empreinte de contrôle.")
        if not r["administrateurs"]:
            lignes.append("Attention : cette sauvegarde ne contient aucun compte Administrateur actif ; "
                          "un nouveau compte Administrateur devra être créé après la restauration.")
        self.lbl_resume.config(fg=NUIT, text="\n".join(lignes))
        self.fichier = chemin
        definir_actif(self.btn_restaurer, True)

    def restaurer(self):
        if not self.fichier:
            return
        if not confirmer_par_saisie(
                self, "Restaurer la sauvegarde",
                "Toutes les données actuelles (élèves, paiements, comptes, droits) seront REMPLACÉES par celles de "
                f"ce fichier :\n{self.fichier.name}\n\nLes opérations faites depuis cette sauvegarde seront perdues. "
                "Une sauvegarde de sécurité de la base actuelle est créée avant. Vous serez ensuite déconnecté.",
                "RESTAURER"):
            return
        try:
            resultat = sauvegarde.restaurer(self.app.conn, self.app.session, self.fichier)
        except (sauvegarde.ErreurSauvegarde, PermissionError) as erreur:
            messagebox.showerror("Restauration impossible", str(erreur), parent=self)
            return
        messagebox.showinfo("Restauration terminée",
                            "La base a été restaurée.\n\nSauvegarde de sécurité de l'ancienne base :\n"
                            f"{resultat['securite']}\n\nVous allez devoir vous reconnecter.", parent=self)
        self.app.session_terminee("Restauration terminée. Reconnectez-vous avec un compte de la base restaurée.")


# ================================================================== 4) RÉINITIALISATION
class PanneauReinitialisation(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(24), pady=px(14))
        entete(corps, "Réinitialisation de l'application",
               "Vide toutes les données scolaires (années, niveaux, options, classes, élèves, inscriptions, devises, "
               "types de frais, tarifs et paiements) pour repartir d'une application vide. Une sauvegarde de "
               "sécurité est faite automatiquement juste avant : elle permet de tout retrouver par la Restauration.")
        self.lbl_apercu = tk.Label(corps, text="", font=police(10), fg=NUIT, bg=BLANC, justify="left", anchor="w",
                                   wraplength=px(1000))
        self.lbl_apercu.pack(fill="x", pady=(0, px(10)))
        self.var_comptes = tk.BooleanVar(value=False)
        case_a_cocher(corps, "Supprimer aussi les autres comptes et les rôles créés (seul votre compte Administrateur est gardé)",
                      self.var_comptes).pack(anchor="w")
        tk.Label(corps, text="Votre mot de passe", font=police(10, gras=True), fg=NUIT, bg=BLANC
                 ).pack(anchor="w", pady=(px(14), 0))
        self.var_mdp = tk.StringVar()
        creer_champ(corps, self.var_mdp, masque=True, largeur=30).pack(anchor="w", ipady=px(5), pady=(px(4), 0))
        creer_bouton(corps, "Réinitialiser l'application…", self.reinitialiser, style="danger", grand=False
                     ).pack(anchor="w", pady=(px(14), 0))
        self.lbl_resultat = tk.Label(corps, text="", font=police(10, gras=True), fg=VERT, bg=BLANC, anchor="w",
                                     justify="left", wraplength=px(1000))
        self.lbl_resultat.pack(fill="x", pady=(px(10), 0))
        creer_bouton(corps, "Menu principal", self.app.afficher_menu, style="secondaire", grand=False
                     ).pack(anchor="w", pady=(px(14), 0))

    def au_affichage(self):
        self.var_mdp.set("")
        try:
            donnees_actuelles = reinitialisation.apercu(self.app.conn, self.app.session)
        except PermissionError as erreur:
            self.lbl_apercu.config(text=str(erreur), fg=ROUGE)
            return
        total = sum(donnees_actuelles.values())
        detail = ", ".join(f"{t} : {n}" for t, n in donnees_actuelles.items() if n)
        self.lbl_apercu.config(fg=NUIT, text=(f"Données actuellement enregistrées : {total} ligne(s) ({detail})."
                                              if total else "Les tables scolaires sont déjà vides."))

    def reinitialiser(self):
        mdp = self.var_mdp.get()
        self.var_mdp.set("")
        if not mdp:
            self.lbl_resultat.config(fg=ROUGE, text="Saisissez votre mot de passe.")
            return
        comptes = self.var_comptes.get()
        if not confirmer_par_saisie(self, "Réinitialiser l'application",
                                    "Toutes les données scolaires seront effacées" +
                                    (", ainsi que tous les autres comptes et les rôles créés" if comptes else "") +
                                    ". Cette opération est inscrite dans le journal.", reinitialisation.PHRASE_CONFIRMATION):
            return
        try:
            resultat = reinitialisation.reinitialiser(self.app.conn, self.app.session, mdp,
                                                      reinitialisation.PHRASE_CONFIRMATION, comptes)
        except (reinitialisation.ErreurReinitialisation, sauvegarde.ErreurSauvegarde, PermissionError) as erreur:
            self.lbl_resultat.config(fg=ROUGE, text=str(erreur))
            return
        self.lbl_resultat.config(fg=VERT, text="✔  Application réinitialisée. Sauvegarde de sécurité : "
                                               f"{resultat['securite'].name}")
        self.au_affichage()


# ================================================================== 5) AUTHENTIFICATION ET MOTS DE PASSE
class FenetreCodeRecuperation(Fenetre):
    """Montre le code de récupération UNE SEULE FOIS, avec le compte à rebours. À la fin des 2 minutes le code est
    effacé de l'écran (et il a déjà disparu de la base). Le code n'est volontairement pas copiable : il se dit de
    vive voix à son propriétaire."""

    def __init__(self, parent, compte, code, secondes, annuler):
        super().__init__(parent, "Code de récupération", 540, 430)
        self._fin = time.monotonic() + secondes
        self._id_after = None
        self._annuler = annuler
        tk.Label(self.corps, text="Code de récupération", font=police(15, gras=True, titre=True), fg=NUIT,
                 bg=BLANC).pack(anchor="w")
        tk.Label(self.corps, text=f"{compte['NOM_COMPLET']}  •  identifiant : {compte['LOGIN']}", font=police(10),
                 fg=GRIS, bg=BLANC).pack(anchor="w", pady=(px(2), px(10)))
        tk.Label(self.corps, text="Après avoir vérifié son identité, dites ce code à l'utilisateur. Il le saisit sur l'écran "
                                  "de connexion (« Mot de passe oublié ? »), avec son identifiant, puis choisit son nouveau "
                                  "mot de passe. Ce code ne sera plus jamais affiché.",
                 font=police(10), fg=NUIT, bg=BLANC, justify="left", wraplength=px(480)).pack(anchor="w")
        cadre = tk.Frame(self.corps, bg=FOND_CLAIR, highlightbackground=BORDURE, highlightthickness=1)
        cadre.pack(fill="x", pady=px(16))
        self.lbl_code = tk.Label(cadre, text=recuperation.formater_code(code), font=("Consolas", int(px(30)), "bold"),
                                 fg=NUIT, bg=FOND_CLAIR, pady=px(14))
        self.lbl_code.pack()
        self.lbl_reste = tk.Label(self.corps, text="", font=police(12, gras=True), fg=VERT, bg=BLANC)
        self.lbl_reste.pack(anchor="w")
        self.lbl_info = tk.Label(self.corps, text="", font=police(10), fg=GRIS, bg=BLANC, wraplength=px(480),
                                 justify="left", anchor="w")
        self.lbl_info.pack(fill="x", pady=(px(4), 0))
        bas = tk.Frame(self.corps, bg=BLANC)
        bas.pack(fill="x", side="bottom")
        self.btn_annuler = creer_bouton(bas, "Annuler ce code", self._annuler_code, style="danger", grand=False)
        self.btn_annuler.pack(side="left")
        creer_bouton(bas, "Fermer", self.destroy, style="secondaire", grand=False).pack(side="left", padx=px(10))
        self._tic()

    def destroy(self):
        if self._id_after:
            self.after_cancel(self._id_after)
            self._id_after = None
        super().destroy()

    def _tic(self):
        reste = self._fin - time.monotonic()
        if reste <= 0:
            self.lbl_code.config(text="—  —  —  —", fg=GRIS)
            self.lbl_reste.config(text="Le code a disparu.", fg=ROUGE)
            self.lbl_info.config(text="Les 2 minutes sont écoulées. Générez-en un nouveau si l'utilisateur en a encore besoin.")
            definir_actif(self.btn_annuler, False)
            self._id_after = None
            return
        self.lbl_reste.config(text=f"Ce code disparaît dans  {security.formater_duree(int(reste) + 1)}",
                              fg=ORANGE if reste < 30 else VERT)
        self._id_after = self.after(250, self._tic)

    def _annuler_code(self):
        try:
            self._annuler()
        except (recuperation.ErreurRecuperation, PermissionError) as erreur:
            self.lbl_info.config(text=str(erreur), fg=ROUGE)
            return
        self.resultat = "annule"
        self.destroy()


class PanneauAuthentification(tk.Frame):
    """Gestionnaire d'authentification et des mots de passe (Administrateur) : état des comptes, code de récupération
    temporaire, mot de passe provisoire, déblocage, journal des opérations d'authentification."""

    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.id_courant = None
        self.comptes = {}
        self._codes = {}
        self._id_after = None
        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(24), pady=px(14))
        duree = config.DUREE_CODE_RECUPERATION_SEC
        entete(corps, "Authentification et mots de passe",
               f"Un utilisateur a oublié son mot de passe : choisissez son compte, vérifiez son identité, puis « Générer "
               f"un code de récupération ». Le système fabrique un code que vous lui dites de vive voix ; il disparaît "
               f"après {duree // 60} minute(s) ({duree} secondes), ne sert qu'une fois et est détruit après "
               f"{config.MAX_ESSAIS_CODE} essais faux. L'utilisateur le saisit sur l'écran de connexion (« Mot de passe "
               f"oublié ? ») et choisit lui-même son nouveau mot de passe.")
        tk.Label(corps, font=police(9), fg=GRIS, bg=BLANC, justify="left", anchor="w", wraplength=px(1000), text=(
            f"Règles en vigueur : mot de passe de {config.LONGUEUR_MIN_MDP} à {config.LONGUEUR_MAX_MDP} caractères "
            f"(majuscule, minuscule, chiffre, symbole)  •  blocage du compte après {config.MAX_ECHECS} échecs "
            f"({config.DUREE_BLOCAGE_MIN} min, doublé à chaque blocage, {config.BLOCAGE_MAX_MIN // 60} h au plus)  •  "
            f"session fermée après {config.DELAI_INACTIVITE_MIN} min d'inactivité")).pack(fill="x", pady=(0, px(8)))

        cadre, self.arbre = creer_arbre(corps, [("nom", "Nom complet", 230, "w"), ("login", "Identifiant", 120, "w"),
                                                ("role", "Poste", 150, "w"), ("etat", "État du compte", 190, "w"),
                                                ("code", "Code de récupération", 170, "w"),
                                                ("derniere", "Dernière connexion", 150, "w")], hauteur=7)
        cadre.pack(fill="x")
        self.arbre.tag_configure("inactif", foreground=GRIS)
        self.arbre.tag_configure("bloque", foreground=ROUGE)
        self.arbre.tag_configure("code", foreground=ORANGE)
        self.arbre.bind("<<TreeviewSelect>>", self._selection)

        boutons = tk.Frame(corps, bg=BLANC)
        boutons.pack(fill="x", pady=(px(8), 0))
        self.btn_code = creer_bouton(boutons, "Générer un code de récupération", self.generer, grand=False)
        self.btn_code.pack(side="left")
        self.btn_annuler = creer_bouton(boutons, "Annuler le code", self.annuler_code, style="secondaire", grand=False)
        self.btn_annuler.pack(side="left", padx=px(8))
        self.btn_mdp = creer_bouton(boutons, "Mot de passe provisoire", self.mot_de_passe_provisoire, style="secondaire",
                                    grand=False)
        self.btn_mdp.pack(side="left")
        self.btn_debloquer = creer_bouton(boutons, "Débloquer", self.debloquer, style="secondaire", grand=False)
        self.btn_debloquer.pack(side="left", padx=px(8))
        creer_bouton(boutons, "Actualiser", self.recharger, style="secondaire", grand=False).pack(side="left")
        creer_bouton(boutons, "Menu principal", self.app.afficher_menu, style="secondaire", grand=False).pack(side="right")
        self.lbl_message = tk.Label(corps, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w", justify="left",
                                    wraplength=px(1000))
        self.lbl_message.pack(fill="x", pady=(px(6), px(4)))

        tk.Label(corps, text="Dernières opérations d'authentification", font=police(11, gras=True), fg=NUIT,
                 bg=BLANC).pack(anchor="w")
        cadre_j, self.arbre_journal = creer_arbre(corps, [("date", "Date et heure", 150, "w"), ("login", "Identifiant", 120, "w"),
                                                          ("action", "Opération", 280, "w"), ("detail", "Détail", 420, "w")],
                                                  hauteur=6)
        cadre_j.pack(fill="both", expand=True, pady=(px(4), 0))
        self._maj_boutons()

    # --- cycle de vie ----------------------------------------------------
    def au_affichage(self):
        self.recharger()
        self._relancer_tic()

    def destroy(self):
        if self._id_after:
            self.after_cancel(self._id_after)
            self._id_after = None
        super().destroy()

    def _relancer_tic(self):
        if self._id_after is None:
            self._id_after = self.after(1000, self._tic)

    def _tic(self):
        """Chaque seconde : le compte à rebours des codes en cours. S'arrête quand l'onglet n'est plus affiché."""
        self._id_after = None
        if not self.winfo_ismapped():
            return
        try:
            codes = recuperation.codes_en_cours(self.app.conn, self.app.session)
        except PermissionError:
            return
        disparus = set(self._codes) - set(codes)
        self._codes = codes
        for iid in self.arbre.get_children():
            self.arbre.set(iid, "code", self._texte_code(int(iid)))
        if disparus:
            self._recharger_journal()
            self._maj_boutons()
        self._relancer_tic()

    # --- affichage ---------------------------------------------------------
    def _texte_code(self, id_user) -> str:
        reste = self._codes.get(id_user, 0)
        return f"Valable encore {security.formater_duree(reste)}" if reste > 0 else "—"

    @staticmethod
    def _etat_de(c) -> tuple:
        if not c["ACTIF"]:
            return "Désactivé", "inactif"
        if c["BLOQUE_JUSQUA"] and lire_iso(c["BLOQUE_JUSQUA"]) > maintenant():
            return "Bloqué (trop d'échecs)", "bloque"
        return ("Mot de passe provisoire" if c["DOIT_CHANGER_MDP"] else "Actif"), ""

    def recharger(self, choisir=None):
        conn, session = self.app.conn, self.app.session
        try:
            lignes = acces.lister_utilisateurs(conn, session)
            self._codes = recuperation.codes_en_cours(conn, session)
        except PermissionError as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.comptes = {c["ID_USER"]: c for c in lignes}
        vider_arbre(self.arbre)
        for c in lignes:
            etat, tag = self._etat_de(c)
            tags = [tag] if tag else []
            if self._codes.get(c["ID_USER"]):
                tags.append("code")
            self.arbre.insert("", "end", iid=str(c["ID_USER"]), tags=tuple(tags), values=(
                c["NOM_COMPLET"], c["LOGIN"], droits.libelle_role(conn, c["ROLE"]), etat,
                self._texte_code(c["ID_USER"]), formater_horodatage(c["DERNIERE_CONNEXION"])))
        cible = choisir or self.id_courant
        if cible in self.comptes:
            self.arbre.selection_set(str(cible))
            self.id_courant = cible
        else:
            self.id_courant = None
        self._recharger_journal()
        self._maj_boutons()

    def _recharger_journal(self):
        try:
            lignes = recuperation.journal_authentification(self.app.conn, self.app.session)
        except PermissionError:
            return
        vider_arbre(self.arbre_journal)
        for l in lignes:
            self.arbre_journal.insert("", "end", values=(
                formater_horodatage(l["DATE_HEURE"]), l["LOGIN"] or "—",
                recuperation.LIBELLES_ACTIONS.get(l["ACTION"], l["ACTION"]), l["DETAIL"]))

    def _selection(self, _e=None):
        selection = self.arbre.selection()
        if selection:
            self.id_courant = int(selection[0])
        self._maj_boutons()

    def _maj_boutons(self):
        c = self.comptes.get(self.id_courant)
        soi_meme = bool(c) and c["ID_USER"] == self.app.session.id_user
        definir_actif(self.btn_code, bool(c) and bool(c["ACTIF"]) and not soi_meme)
        definir_actif(self.btn_annuler, bool(c) and self._codes.get(c["ID_USER"], 0) > 0)
        definir_actif(self.btn_mdp, bool(c))
        definir_actif(self.btn_debloquer, bool(c))

    def _message(self, texte, couleur=VERT):
        self.lbl_message.config(text=texte, fg=couleur)

    # --- actions -------------------------------------------------------------
    def generer(self):
        if self.id_courant is None:
            return
        conn, session, id_user = self.app.conn, self.app.session, self.id_courant
        c = self.comptes[id_user]
        if not messagebox.askyesno(
                "Code de récupération",
                f"Générer un code de récupération pour {c['NOM_COMPLET']} ({c['LOGIN']}) ?\n\n"
                "Vérifiez d'abord que c'est bien cette personne qui le demande. Le code s'affiche une seule fois et "
                f"disparaît après {config.DUREE_CODE_RECUPERATION_SEC // 60} minute(s). Un code déjà en cours pour ce "
                "compte sera remplacé.", parent=self):
            return
        try:
            code, secondes = recuperation.generer_code(conn, session, id_user)
        except (recuperation.ErreurRecuperation, PermissionError) as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.recharger(choisir=id_user)
        fen = FenetreCodeRecuperation(self, c, code, secondes,
                                      lambda: recuperation.annuler_code(conn, session, id_user))
        code = None                                           # on ne garde pas le code en mémoire
        fen.attendre()
        self.recharger(choisir=id_user)
        self._message("Code de récupération annulé." if fen.resultat == "annule"
                      else f"Code généré pour {c['NOM_COMPLET']} (il disparaît après "
                           f"{config.DUREE_CODE_RECUPERATION_SEC // 60} minute(s)).")

    def annuler_code(self):
        if self.id_courant is None:
            return
        c = self.comptes[self.id_courant]
        try:
            recuperation.annuler_code(self.app.conn, self.app.session, self.id_courant)
        except (recuperation.ErreurRecuperation, PermissionError) as erreur:
            self._message(str(erreur), ROUGE)
            self.recharger(choisir=self.id_courant)
            return
        self.recharger(choisir=self.id_courant)
        self._message(f"Code de {c['NOM_COMPLET']} annulé.")

    def mot_de_passe_provisoire(self):
        if self.id_courant is None:
            return
        c = self.comptes[self.id_courant]
        if not messagebox.askyesno("Mot de passe provisoire",
                                   f"Donner un nouveau mot de passe provisoire à {c['NOM_COMPLET']} ?\n"
                                   "L'ancien mot de passe cessera de fonctionner et un code de récupération en cours "
                                   "sera détruit.", parent=self):
            return
        try:
            mdp = acces.reinitialiser_mdp(self.app.conn, self.app.session, self.id_courant)
        except (acces.ErreurAcces, PermissionError) as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.recharger(choisir=self.id_courant)
        afficher_mdp_provisoire(self, c["LOGIN"], mdp, "Nouveau mot de passe provisoire")

    def debloquer(self):
        if self.id_courant is None:
            return
        try:
            acces.debloquer(self.app.conn, self.app.session, self.id_courant)
        except (acces.ErreurAcces, PermissionError) as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.recharger(choisir=self.id_courant)
        self._message("Compte débloqué.")


# ================================================================== 6) DONNÉES D'ESSAI
class FenetreComptesEssai(Fenetre):
    """Montre UNE FOIS les comptes d'essai et leurs mots de passe (ils sont aussi dans un fichier)."""

    def __init__(self, parent, resultat):
        super().__init__(parent, "Comptes d'essai", 760, 560)
        tk.Label(self.corps, text="Comptes d'essai créés", font=police(15, gras=True, titre=True), fg=NUIT, bg=BLANC
                 ).pack(anchor="w")
        tk.Label(self.corps, text="Un compte par poste. Connectez-vous avec chacun pour tester ce que voit chaque utilisateur. "
                                  "Ces mots de passe ne seront plus affichés : ils sont enregistrés dans le fichier ci-dessous, "
                                  "qui disparaît avec les données d'essai.", font=police(10), fg=GRIS, bg=BLANC, justify="left",
                 wraplength=px(700)).pack(anchor="w", pady=(px(4), px(10)))
        texte = "\n".join(f"{poste:<26} {login:<22} {mdp}" for login, poste, mdp in
                          [(l, p, m) for l, p, m in resultat["comptes"]])
        zone = tk.Text(self.corps, height=9, font=("Consolas", 10), bg=FOND_CLAIR, fg=NUIT, relief="flat", wrap="none")
        zone.insert("1.0", "Poste                      Identifiant            Mot de passe\n" + "-" * 70 + "\n" + texte)
        zone.config(state="disabled")
        zone.pack(fill="x")
        tk.Label(self.corps, text=f"Fichier : {resultat['fichier']}", font=police(9), fg=GRIS, bg=BLANC, justify="left",
                 wraplength=px(700)).pack(anchor="w", pady=(px(8), 0))
        bas = tk.Frame(self.corps, bg=BLANC)
        bas.pack(fill="x", side="bottom")
        creer_bouton(bas, "Ouvrir le fichier", lambda: ouvrir_fichier(resultat["fichier"]), style="secondaire",
                     grand=False).pack(side="left")
        creer_bouton(bas, "J'ai noté, fermer", self.destroy, grand=False).pack(side="left", padx=px(10))


class PanneauEssai(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(24), pady=px(14))
        entete(corps, "Données d'essai",
               "Pour essayer toute l'application sans toucher aux vraies données : 120 élèves fictifs inscrits dans vos "
               "classes existantes, des frais d'essai (frais scolaire différent selon la classe, tranches libres), un compte "
               "par poste et de vraies opérations (paiements par tranches, annulations, encaissements, consultations). "
               "Tout se retire d'un clic : seules les données d'essai disparaissent. Une sauvegarde de sécurité est faite "
               "avant l'installation et avant la suppression.")
        self.lbl_etat = tk.Label(corps, text="", font=police(10, gras=True), fg=NUIT, bg=BLANC, justify="left", anchor="w",
                                 wraplength=px(1000))
        self.lbl_etat.pack(fill="x", pady=(0, px(10)))

        self.cadre_installer = tk.Frame(corps, bg=BLANC)
        tk.Label(self.cadre_installer, text="Nombre d'élèves d'essai (100 à 600)", font=police(10, gras=True), fg=NUIT,
                 bg=BLANC).pack(anchor="w")
        self.var_nb = tk.StringVar(value=str(essai.NB_DEFAUT))
        creer_champ(self.cadre_installer, self.var_nb, largeur=8).pack(anchor="w", ipady=px(5), pady=(px(4), px(10)))
        creer_bouton(self.cadre_installer, "Installer les données d'essai", self.installer, grand=False).pack(anchor="w")

        self.cadre_supprimer = tk.Frame(corps, bg=BLANC)
        tk.Label(self.cadre_supprimer, text="Votre mot de passe", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        self.var_mdp = tk.StringVar()
        creer_champ(self.cadre_supprimer, self.var_mdp, masque=True, largeur=30).pack(anchor="w", ipady=px(5), pady=(px(4), 0))
        creer_bouton(self.cadre_supprimer, "Supprimer les données d'essai…", self.supprimer, style="danger", grand=False
                     ).pack(anchor="w", pady=(px(14), 0))

        self.lbl_resultat = tk.Label(corps, text="", font=police(10, gras=True), fg=VERT, bg=BLANC, anchor="w",
                                     justify="left", wraplength=px(1000))
        self.lbl_resultat.pack(fill="x", pady=(px(10), 0))
        creer_bouton(corps, "Menu principal", self.app.afficher_menu, style="secondaire", grand=False
                     ).pack(anchor="w", pady=(px(14), 0))

    def au_affichage(self):
        self.var_mdp.set("")
        try:
            a = essai.apercu(self.app.conn, self.app.session)
        except PermissionError as erreur:
            self.lbl_etat.config(text=str(erreur), fg=ROUGE)
            return
        self.cadre_installer.pack_forget()
        self.cadre_supprimer.pack_forget()
        if a["installe"]:
            self.lbl_etat.config(fg=NUIT, text=(f"Données d'essai installées : {a['eleves']} élèves, {a['types']} types de frais, "
                                                f"{a['comptes']} comptes, {a['recus']} reçus, {a['encaissements']} encaissements."))
            self.cadre_supprimer.pack(anchor="w", before=self.lbl_resultat)
        else:
            self.lbl_etat.config(fg=NUIT, text="Aucune donnée d'essai n'est installée.")
            self.cadre_installer.pack(anchor="w", before=self.lbl_resultat)

    def installer(self):
        try:
            nb = int(self.var_nb.get().strip())
        except ValueError:
            self.lbl_resultat.config(fg=ROUGE, text="Saisissez un nombre d'élèves (100 à 600).")
            return
        self.lbl_resultat.config(fg=NUIT, text="Installation en cours, un instant...")
        self.update_idletasks()
        try:
            resultat = essai.installer(self.app.conn, self.app.session, nb)
        except (essai.ErreurEssai, sauvegarde.ErreurSauvegarde, PermissionError, ValueError) as erreur:
            self.lbl_resultat.config(fg=ROUGE, text=str(erreur))
            return
        self.lbl_resultat.config(fg=VERT, text=f"✔  {resultat['eleves']} élèves, {resultat['recus']} reçus et "
                                               f"{resultat['encaissements']} encaissements d'essai installés.")
        self.au_affichage()
        FenetreComptesEssai(self, resultat)

    def supprimer(self):
        mdp = self.var_mdp.get()
        self.var_mdp.set("")
        if not mdp:
            self.lbl_resultat.config(fg=ROUGE, text="Saisissez votre mot de passe.")
            return
        if not confirmer_par_saisie(self, "Supprimer les données d'essai",
                                    "Les élèves, frais, comptes, reçus et encaissements d'essai seront supprimés. "
                                    "Vos vraies données ne sont pas touchées.", essai.PHRASE_SUPPRESSION):
            return
        try:
            r = essai.supprimer(self.app.conn, self.app.session, mdp, essai.PHRASE_SUPPRESSION)
        except (essai.ErreurEssai, sauvegarde.ErreurSauvegarde, PermissionError) as erreur:
            self.lbl_resultat.config(fg=ROUGE, text=str(erreur))
            return
        self.lbl_resultat.config(fg=VERT, text=f"✔  Données d'essai supprimées ({r['élèves']} élèves, {r['reçus']} reçus). "
                                               f"Sauvegarde de sécurité : {r['securite'].name}")
        self.au_affichage()


# ================================================================== 7) MISE À JOUR DU PROGRAMME
class PanneauMiseAJour(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.chemin = None
        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(24), pady=px(14))
        entete(corps, "Mise à jour du programme",
               "Installez une nouvelle version depuis un fichier « .csfupd » (clé USB, dossier réseau ou courriel), sans internet. "
               "Le fichier est contrôlé avant toute modification ; une sauvegarde de la base est faite, la version actuelle est "
               "gardée pour un retour en arrière, et vos données ne sont jamais touchées.")
        self.lbl_version = tk.Label(corps, text="", font=police(10, gras=True), fg=NUIT, bg=BLANC, anchor="w")
        self.lbl_version.pack(fill="x", pady=(0, px(8)))

        ligne = tk.Frame(corps, bg=BLANC)
        ligne.pack(fill="x")
        self.var_fichier = tk.StringVar()
        creer_champ(ligne, self.var_fichier, lecture_seule=True, largeur=60).pack(side="left", ipady=px(5))
        creer_bouton(ligne, "Choisir le fichier…", self.parcourir, style="secondaire", grand=False).pack(side="left", padx=px(8))

        tk.Label(corps, text="Clé de mise à jour (donnée séparément par la personne qui fournit le fichier)",
                 font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w", pady=(px(10), 0))
        self.var_cle = tk.StringVar()
        creer_champ(corps, self.var_cle, masque=True, largeur=30).pack(anchor="w", ipady=px(5), pady=(px(4), 0))
        creer_bouton(corps, "Vérifier le fichier", self.verifier, style="secondaire", grand=False).pack(anchor="w", pady=(px(8), 0))
        self.lbl_info = tk.Label(corps, text="", font=police(10), fg=NUIT, bg=BLANC, anchor="w", justify="left",
                                 wraplength=px(1000))
        self.lbl_info.pack(fill="x", pady=(px(6), 0))

        tk.Label(corps, text="Votre mot de passe", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w", pady=(px(8), 0))
        self.var_mdp = tk.StringVar()
        creer_champ(corps, self.var_mdp, masque=True, largeur=30).pack(anchor="w", ipady=px(5), pady=(px(4), 0))
        self.btn_installer = creer_bouton(corps, "Installer la mise à jour…", self.installer, grand=False)
        self.btn_installer.pack(anchor="w", pady=(px(10), 0))

        tk.Label(corps, text="Versions gardées (retour en arrière)", font=police(10, gras=True), fg=NUIT, bg=BLANC
                 ).pack(anchor="w", pady=(px(14), 0))
        self.liste = tk.Listbox(corps, height=3, font=police(10), exportselection=False)
        self.liste.pack(fill="x", pady=(px(4), 0))
        self.btn_retour = creer_bouton(corps, "Revenir à la version choisie…", self.revenir, style="danger", grand=False)
        self.btn_retour.pack(anchor="w", pady=(px(6), 0))
        self.lbl_resultat = tk.Label(corps, text="", font=police(10, gras=True), fg=VERT, bg=BLANC, anchor="w",
                                     justify="left", wraplength=px(1000))
        self.lbl_resultat.pack(fill="x", pady=(px(8), 0))
        creer_bouton(corps, "Menu principal", self.app.afficher_menu, style="secondaire", grand=False
                     ).pack(anchor="w", pady=(px(10), 0))

    def au_affichage(self):
        self.var_mdp.set("")
        self.var_cle.set("")
        self.lbl_version.config(text=f"Version installée : {config.VERSION}")
        self.archives = miseajour.lister_archives()
        self.liste.delete(0, "end")
        for a in self.archives:
            self.liste.insert("end", f"Version {a['version']}  (gardée le {formater_horodatage(a['date'])})")
        if not self.archives:
            self.liste.insert("end", "Aucune ancienne version gardée pour le moment.")

    def parcourir(self):
        chemin = filedialog.askopenfilename(parent=self, title="Fichier de mise à jour",
                                            filetypes=[("Mise à jour", "*" + miseajour.EXTENSION), ("Tous", "*.*")])
        if chemin:
            self.chemin = chemin
            self.var_fichier.set(chemin)
            self.lbl_info.config(text="")

    def _controler(self):
        if not self.chemin:
            self.lbl_resultat.config(fg=ROUGE, text="Choisissez d'abord le fichier de mise à jour.")
            return None
        try:
            return miseajour.examiner(self.chemin, self.var_cle.get())
        except miseajour.ErreurMiseAJour as erreur:
            self.lbl_info.config(text="")
            self.lbl_resultat.config(fg=ROUGE, text=str(erreur))
            return None

    def verifier(self):
        m = self._controler()
        if m:
            self.lbl_resultat.config(text="")
            self.lbl_info.config(fg=NUIT, text=f"✔  Fichier valide : version {m['version']}, {m['nb_fichiers']} fichiers. "
                                               f"Empreinte {m['empreinte']} (comparez-la avec celle qu'on vous a communiquée).")

    def installer(self):
        m = self._controler()
        mdp = self.var_mdp.get()
        self.var_mdp.set("")
        if not m:
            return
        if not mdp:
            self.lbl_resultat.config(fg=ROUGE, text="Saisissez votre mot de passe.")
            return
        if not messagebox.askyesno("Mettre à jour", f"Installer la version {m['version']} (empreinte {m['empreinte']}) ?\n\n"
                                   "Le programme redémarrera ensuite.", parent=self):
            return
        try:
            r = miseajour.installer(self.app.conn, self.app.session, self.chemin, self.var_cle.get(), mdp)
        except (miseajour.ErreurMiseAJour, sauvegarde.ErreurSauvegarde, PermissionError) as erreur:
            self.lbl_resultat.config(fg=ROUGE, text=str(erreur))
            return
        messagebox.showinfo("Mise à jour installée", f"Version {r['nouvelle']} installée ({r['fichiers']} fichiers).\n"
                            "Le programme va redémarrer.", parent=self)
        self._redemarrer()

    def revenir(self):
        sel = self.liste.curselection()
        if not self.archives or not sel:
            self.lbl_resultat.config(fg=ROUGE, text="Choisissez la version à remettre dans la liste.")
            return
        mdp = self.var_mdp.get()
        self.var_mdp.set("")
        if not mdp:
            self.lbl_resultat.config(fg=ROUGE, text="Saisissez votre mot de passe.")
            return
        choix = self.archives[sel[0]]
        if not messagebox.askyesno("Retour en arrière", f"Revenir à la version {choix['version']} ?\n\n"
                                   "Le programme redémarrera ensuite.", parent=self):
            return
        try:
            r = miseajour.revenir(self.app.conn, self.app.session, choix["nom"], mdp)
        except (miseajour.ErreurMiseAJour, PermissionError) as erreur:
            self.lbl_resultat.config(fg=ROUGE, text=str(erreur))
            return
        messagebox.showinfo("Retour effectué", f"Version {r['nouvelle']} remise en place. Le programme va redémarrer.", parent=self)
        self._redemarrer()

    def _redemarrer(self):
        miseajour.redemarrer()
        self.app.quitter()


# ================================================================== MODULE
class ModuleTravaux(ModuleOnglets):
    TITRE = "Travaux techniques"
    ONGLETS = (("tables", "1   Mise à jour des tables", PanneauTables),
               ("sauvegarde", "2   Sauvegarde", PanneauSauvegarde),
               ("restauration", "3   Restauration", PanneauRestauration),
               ("reinitialisation", "4   Réinitialisation", PanneauReinitialisation),
               ("authentification", "5   Authentification et mots de passe", PanneauAuthentification),
               ("essai", "6   Données d'essai", PanneauEssai),
               ("miseajour", "7   Mise à jour du programme", PanneauMiseAJour))

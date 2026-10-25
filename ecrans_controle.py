"""Module « Contrôle numérique » : 2 onglets.

1. Édition liste des élèves en ordre : l'utilisateur choisit l'année scolaire, la classe
   (et l'option pour les humanités) et le type de frais ; la liste s'affiche aussitôt. Boutons IMPRIMER (PDF) et ANNULER.
2. Contrôle numérique : on saisit le nom ou le matricule de l'élève ; ses informations et son statut
   (EN ORDRE / IMPAYÉ) s'affichent.
"""
import tkinter as tk
from tkinter import messagebox, ttk

import controle
import donnees
from controle import ErreurControle
from ecrans_paiement import ZoneRecherche, creer_arbre, ouvrir_fichier, vider_arbre
from composants import ModuleOnglets
from controle_pdf import TITRE_PIED
from theme import (BLANC, FOND_CLAIR, GRIS, NUIT, ORANGE, ROUGE, VERT, carte, creer_bouton, definir_actif, police, px)

ERREURS = (ErreurControle, PermissionError)
PAS_D_OPTION = "—  (aucune option)"


def _etiquette(parent, texte, colonne):
    tk.Label(parent, text=texte, font=police(10, gras=True), fg=NUIT, bg=BLANC).grid(row=0, column=colonne, sticky="w",
                                                                                      padx=(0, px(12)))


# ================================================================== 1) LISTE DES ÉLÈVES EN ORDRE
class PanneauListe(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.liste = None
        self.types, self.options = {}, {}      # libellé affiché -> code
        self.vars = {k: tk.StringVar() for k in ("annee", "classe", "option", "frais")}

        haut = tk.Frame(self, bg=BLANC)
        haut.pack(fill="x", padx=px(24), pady=(px(14), px(4)))
        for c in range(4):
            haut.grid_columnconfigure(c, weight=1, uniform="choix")
        champs = (("Année scolaire", "annee"), ("Classe", "classe"),
                  ("Option (humanités)", "option"), ("Type de frais", "frais"))
        self.combos = {}
        for c, (texte, cle) in enumerate(champs):
            _etiquette(haut, texte, c)
            cb = ttk.Combobox(haut, textvariable=self.vars[cle], state="readonly", font=police(11))
            cb.grid(row=1, column=c, sticky="we", ipady=px(3), padx=(0, px(12)), pady=(px(3), 0))
            cb.bind("<<ComboboxSelected>>", lambda _e, k=cle: self._choix(k))
            self.combos[cle] = cb

        boutons = tk.Frame(self, bg=BLANC)
        boutons.pack(fill="x", padx=px(24), pady=(px(10), px(4)))
        self.btn_imprimer = creer_bouton(boutons, "IMPRIMER", self.imprimer, grand=False)
        self.btn_imprimer.pack(side="left")
        creer_bouton(boutons, "ANNULER", self.annuler, style="danger", grand=False).pack(side="left", padx=px(8))
        self.lbl_info = tk.Label(boutons, text="", font=police(10, gras=True), fg=GRIS, bg=BLANC, anchor="w",
                                 justify="left", wraplength=px(800))
        self.lbl_info.pack(side="left", padx=px(14))
        definir_actif(self.btn_imprimer, False)

        # la liste, présentée comme sur la feuille imprimée
        self.lbl_titre = tk.Label(self, text="", font=police(14, gras=True, titre=True), fg=NUIT, bg=BLANC,
                                  wraplength=px(1000), justify="center")
        self.lbl_titre.pack(pady=(px(10), 0))
        self.lbl_sous = tk.Label(self, text="", font=police(11, gras=True), fg=NUIT, bg=BLANC)
        self.lbl_sous.pack()
        self.lbl_annee = tk.Label(self, text="", font=police(10), fg=GRIS, bg=BLANC)
        self.lbl_annee.pack(pady=(0, px(6)))

        cadre, self.arbre = creer_arbre(self, [("n", "N°", 70, "center"), ("nom", "NOM, POSTNOM ET PRENOM", 560, "w"),
                                               ("sexe", "SEXE", 90, "center")], hauteur=10)
        cadre.pack(fill="both", expand=True, padx=px(24))

        bas = tk.Frame(self, bg=BLANC)
        bas.pack(fill="x", padx=px(24), pady=(px(8), px(14)))
        self.lbl_total = tk.Label(bas, text="", font=police(10, gras=True), fg=NUIT, bg=BLANC)
        self.lbl_total.pack(side="left")
        tk.Label(bas, text=TITRE_PIED, font=police(12, gras=True)[:2] + ("bold underline",), fg=NUIT,
                 bg=BLANC).pack(side="right", padx=px(8))                 # « Direction des études », souligné

    # --- cycle de vie ------------------------------------------------------
    def au_affichage(self):
        conn = self.app.conn
        annees = controle.liste_annees(conn)
        self.combos["annee"].config(values=annees)
        self.combos["classe"].config(values=controle.liste_classes(conn, self.app.session))
        if not self.vars["annee"].get():
            courante = donnees.annee_courante(conn)
            if courante in annees:
                self.vars["annee"].set(courante)
        self._maj_option()
        self._maj_types()
        self._afficher()

    # --- choix en cascade ----------------------------------------------------
    def _choix(self, cle):
        if cle == "classe":
            self.vars["option"].set("")
            self._maj_option()
        self._afficher()

    def _maj_types(self):
        self.types = {}
        for c, d in controle.liste_types_frais(self.app.conn):
            self.types[d if d not in self.types else f"{d} ({c})"] = c
        self.combos["frais"].config(values=list(self.types))
        if self.vars["frais"].get() not in self.types:
            self.vars["frais"].set("")

    def _maj_option(self):
        classe = self.vars["classe"].get()
        self.options = {d: c for c, d in controle.liste_options(self.app.conn, classe)} if classe else {}
        self.combos["option"].config(values=list(self.options),
                                     state="readonly" if self.options else "disabled")
        if not self.options:
            self.vars["option"].set(PAS_D_OPTION if classe else "")
        elif self.vars["option"].get() not in self.options:
            self.vars["option"].set(next(iter(self.options)) if len(self.options) == 1 else "")

    # --- affichage -----------------------------------------------------------
    def _vider(self, message="", couleur=GRIS):
        vider_arbre(self.arbre)
        self.liste = None
        for lbl in (self.lbl_titre, self.lbl_sous, self.lbl_annee, self.lbl_total):
            lbl.config(text="")
        self.lbl_info.config(text=message, fg=couleur)
        definir_actif(self.btn_imprimer, False)

    def _afficher(self):
        """Affiche la liste dès que tous les choix nécessaires sont faits."""
        v = self.vars
        if not (v["annee"].get() and v["classe"].get() and v["frais"].get()):
            self._vider("Choisissez l'année scolaire, la classe et le type de frais.")
            return
        if self.options and not v["option"].get():
            self._vider("Choisissez l'option.")
            return
        try:
            liste = controle.eleves_en_ordre(
                self.app.conn, self.app.session, v["annee"].get(),
                v["classe"].get(), self.options.get(v["option"].get()), self.types[v["frais"].get()])
        except ERREURS as erreur:
            self._vider(str(erreur), ROUGE)
            return
        self._vider()
        self.liste = liste
        self.lbl_titre.config(text=liste["titre"])
        self.lbl_sous.config(text=controle.ligne_classe_option(liste))
        self.lbl_annee.config(text=f"Année scolaire {liste['annee']}")
        for l in liste["lignes"]:
            self.arbre.insert("", "end", values=(l["n"], l["nom_complet"], l["sexe"]))
        self.lbl_total.config(text=f"{len(liste['lignes'])} élève(s) en ordre sur {liste['nb_inscrits']} inscrit(s)")
        if liste["sans_tarif"]:
            self.lbl_info.config(fg=ORANGE, text="Aucun tarif n'est défini pour ce frais dans cette classe "
                                                 "(Travaux techniques > Tarifs) : personne ne peut être en ordre.")
        elif not liste["nb_inscrits"]:
            self.lbl_info.config(fg=ORANGE, text="Aucun élève inscrit dans cette classe pour cette année.")
        elif not liste["lignes"]:
            self.lbl_info.config(fg=ORANGE, text="Aucun élève en ordre pour ce frais.")
        definir_actif(self.btn_imprimer, bool(liste["lignes"]))
        controle.journaliser_liste(self.app.conn, self.app.session, liste, "LISTE_EN_ORDRE_CONSULTEE")

    def annuler(self):
        """Efface tous les choix et la liste."""
        for cle in ("classe", "option", "frais"):
            self.vars[cle].set("")
        self._maj_option()
        self._maj_types()
        self._vider()

    def imprimer(self):
        if not self.liste:
            return
        try:
            ouvrir_fichier(controle.preparer_liste_pdf(self.app.conn, self.app.session, self.liste))
        except ERREURS as erreur:
            messagebox.showwarning("Impression impossible", str(erreur), parent=self)
        except OSError as erreur:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir la liste : {erreur}", parent=self)



# ================================================================== 2) CONTRÔLE NUMÉRIQUE
class PanneauControle(tk.Frame):
    COULEURS = {controle.EN_ORDRE: VERT, controle.IMPAYE: ROUGE, controle.NON_INSCRIT: ORANGE}

    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app

        self.recherche = ZoneRecherche(self, self.app, self.controler, self.vider)
        self.recherche.pack(fill="x", padx=px(24), pady=(px(14), px(6)))
        self.indication = tk.Label(self, text="Saisissez le nom ou le matricule de l'élève, puis appuyez sur Entrée.",
                                   font=police(12), fg=GRIS, bg=BLANC)
        self.indication.pack(pady=px(30))

        self.detail = tk.Frame(self, bg=BLANC)
        self.v = {k: tk.StringVar() for k in ("matricule", "nom", "sexe", "classe", "option", "annee")}
        haut = tk.Frame(self.detail, bg=BLANC)
        haut.pack(fill="x")
        haut.grid_columnconfigure((0, 1), weight=1, uniform="c")
        c1 = carte(haut, padx=px(18), pady=px(12))
        c1.grid(row=0, column=0, sticky="nsew", padx=(0, px(8)))
        tk.Label(c1, text="Informations de l'élève", font=police(12, gras=True, titre=True), fg=NUIT,
                 bg=BLANC).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, px(8)))
        for i, (cle, lib) in enumerate((("matricule", "Matricule"), ("nom", "Nom complet"), ("sexe", "Sexe"),
                                        ("annee", "Année scolaire"), ("classe", "Classe"), ("option", "Option")), start=1):
            tk.Label(c1, text=lib, font=police(9), fg=GRIS, bg=BLANC).grid(row=i, column=0, sticky="ne",
                                                                          padx=(0, px(10)), pady=px(2))
            tk.Label(c1, textvariable=self.v[cle], font=police(11, gras=True), fg=NUIT, bg=BLANC, anchor="w",
                     justify="left", wraplength=px(380)).grid(row=i, column=1, sticky="nw", pady=px(2))

        self.c2 = tk.Frame(haut, bg=NUIT, highlightthickness=0)
        self.c2.grid(row=0, column=1, sticky="nsew", padx=(px(8), 0))
        tk.Label(self.c2, text="STATUT", font=police(11, gras=True), fg=BLANC, bg=NUIT).pack(pady=(px(14), 0))
        self.lbl_statut = tk.Label(self.c2, text="", font=police(34, gras=True, titre=True), fg=BLANC, bg=NUIT)
        self.lbl_statut.pack(expand=True)
        self.lbl_motif = tk.Label(self.c2, text="", font=police(10, gras=True), fg=BLANC, bg=NUIT, wraplength=px(420),
                                  justify="center")
        self.lbl_motif.pack(pady=(0, px(14)))

        cadre, self.arbre = creer_arbre(self.detail, [("frais", "Type de frais", 300, "w"), ("du", "Montant dû", 130, "e"),
                                                      ("paye", "Montant payé", 130, "e"), ("reste", "Reste à payer", 130, "e"),
                                                      ("statut", "Situation", 100, "w")], hauteur=6)
        cadre.pack(fill="both", expand=True, pady=(px(12), px(6)))
        self.arbre.tag_configure("solde", foreground=VERT)
        self.arbre.tag_configure("partiel", foreground=ORANGE)
        self.arbre.tag_configure("impaye", foreground=ROUGE)
        self.lbl_dette = tk.Label(self.detail, text="", font=police(10, gras=True), fg=ROUGE, bg=BLANC, anchor="w",
                                  justify="left", wraplength=px(1000))
        self.lbl_dette.pack(fill="x")

    def au_affichage(self):
        self.recherche.prendre_focus()

    def vider(self):
        self.detail.pack_forget()
        self.indication.pack(pady=px(30))

    def controler(self, matricule):
        try:
            r = controle.controler_eleve(self.app.conn, self.app.session, matricule)
        except ERREURS as erreur:
            messagebox.showwarning("Contrôle impossible", str(erreur), parent=self)
            return
        v = self.v
        v["matricule"].set(r["matricule"])
        v["nom"].set(r["nom_complet"] + ("   (compte élève désactivé)" if not r["actif"] else ""))
        v["sexe"].set(r["sexe"])
        v["annee"].set(r["annee"] or "—")
        v["classe"].set(r["classe"] or ("Non inscrit pour cette année" if r["annee"] else "—"))
        v["option"].set(r["option"] or "—")
        couleur = self.COULEURS[r["statut"]]
        self.c2.config(bg=couleur)
        for lbl in self.c2.winfo_children():
            lbl.config(bg=couleur)
        self.lbl_statut.config(text=r["statut"])
        self.lbl_motif.config(text={controle.EN_ORDRE: "Aucun frais restant à payer.",
                                    controle.IMPAYE: "Il reste des frais à payer.",
                                    controle.NON_INSCRIT: "Pas d'inscription pour l'année en cours."}[r["statut"]])
        vider_arbre(self.arbre)
        for l in r["lignes"]:
            tag = {"Soldé": "solde", "Partiel": "partiel"}.get(l["statut"], "impaye")
            self.arbre.insert("", "end", tags=(tag,), values=(l["frais"], l["du"], l["paye"],
                                                              l["reste"], l["statut"]))
        if r["dettes"]:
            self.lbl_dette.config(fg=ROUGE, text="Reste à payer :  " + "   ;   ".join(r["dettes"]))
        elif r["sans_frais"]:
            self.lbl_dette.config(fg=ORANGE, text="Aucun frais n'est défini pour cette classe.")
        else:
            self.lbl_dette.config(text="")
        self.indication.pack_forget()
        self.detail.pack(fill="both", expand=True, padx=px(24), pady=(px(6), px(14)))


# ================================================================== MODULE
class ModuleControle(ModuleOnglets):
    TITRE = "Contrôle numérique"
    ONGLETS = (("liste", "1   Edition liste des Etudiants en Ordre", PanneauListe),
               ("controle", "2   Contrôle numérique", PanneauControle))

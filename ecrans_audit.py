"""Module « Traçabilité et audit » : écrans (la logique est dans audit.py).

1. Journal des activités : qui a fait quoi, quand (connexions, consultations, ajouts, modifications, suppressions,
   impressions et exportations). Filtres : période, utilisateur, catégorie, texte. Export CSV (tableur) et PDF.
2. Opérations financières : paiements (N° de reçu, élève, utilisateur qui l'a enregistré), reçus imprimés, annulations,
   encaissements, remises de fonds et écarts. On retrouve par exemple le paiement d'un élève et l'utilisateur qui l'a
   enregistré ; un clic sur une ligne affiche sa fiche complète et toutes les traces du journal.
3. Contrôles : intégrité du journal (chaîne d'empreintes) et concordance entre le journal et les tables financières.
4. Contrôle et audit financier, 5. Recherche et filtrage des traces, 6. Génération des rapports d'audit :
   voir ecrans_audit_financier.py.
"""
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

import argent
import audit
from audit import ErreurAudit
from calendrier import SelecteurDate
from ecrans_paiement import creer_arbre, ouvrir_fichier, vider_arbre
from saisie_date import formater_date, lire_date_texte
from theme import (BLANC, BLEU_PALE, BORDURE, FOND_CLAIR, GRIS, NUIT, NUIT_CLAIR, ORANGE, ROUGE, VERT,
                   actions_barre_module, barre_haute, bouton_menu, creer_bouton, creer_champ, police, px, ZoneAdaptative)

ERREURS = (ErreurAudit, PermissionError)
TOUS_UTILISATEURS = "Tous les utilisateurs"
TOUTES_CATEGORIES = "Toutes les catégories"
TOUTES_OPERATIONS = "Toutes les opérations"


def _etiquette(parent, texte):
    return tk.Label(parent, text=texte, font=police(10, gras=True), fg=NUIT, bg=FOND_CLAIR)


def _lire_jour(variable, nom):
    """Champ date -> date (ou None si vide). Lève ErreurAudit si le texte n'est pas une date."""
    texte = variable.get().strip()
    if not texte:
        return None
    jour = lire_date_texte(texte)
    if jour is None:
        raise ErreurAudit(f"La date « {nom} » est invalide. Écrivez-la ainsi : 08/10/2026")
    return jour


def _liste_utilisateurs(conn, session):
    """({libellé affiché: identifiant}, libellés dans l'ordre)."""
    choix = {TOUS_UTILISATEURS: ""}
    for login, nom in audit.liste_utilisateurs(conn, session):
        choix[f"{login} - {nom}" if nom else login] = login
    return choix


class _Filtres(tk.Frame):
    """Barre de filtres commune : cadre gris clair, deux rangées."""

    def __init__(self, parent):
        super().__init__(parent, bg=FOND_CLAIR, padx=px(12), pady=px(8))
        self.rangee1 = tk.Frame(self, bg=FOND_CLAIR)
        self.rangee1.pack(fill="x")
        self.rangee2 = tk.Frame(self, bg=FOND_CLAIR)
        self.rangee2.pack(fill="x", pady=(px(8), 0))

    def periode(self, parent, var_du, var_au):
        _etiquette(parent, "Du :").pack(side="left")
        SelecteurDate(parent, var_du, largeur=11, bg=FOND_CLAIR).pack(side="left", padx=(px(6), px(8)))
        _etiquette(parent, "au :").pack(side="left")
        SelecteurDate(parent, var_au, largeur=11, bg=FOND_CLAIR).pack(side="left", padx=(px(6), px(16)))

    def liste(self, parent, titre, variable, largeur):
        _etiquette(parent, titre).pack(side="left")
        cb = ttk.Combobox(parent, textvariable=variable, state="readonly", width=largeur, font=police(10))
        cb.pack(side="left", padx=(px(6), px(16)))
        return cb

    def champ(self, parent, titre, variable, largeur, action):
        _etiquette(parent, titre).pack(side="left")
        entree = creer_champ(parent, variable, largeur=largeur)
        entree.pack(side="left", padx=(px(6), px(16)), ipady=px(4))
        entree.bind("<Return>", action)
        return entree


# ================================================================== 1) JOURNAL DES ACTIVITÉS
class PanneauJournal(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.lignes = []
        self.charge = False
        self.utilisateurs, self.categories = {}, {}
        self.vars = {k: tk.StringVar() for k in ("du", "au", "utilisateur", "categorie", "texte")}
        self.var_financier = tk.BooleanVar(value=False)

        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(20), pady=px(10))

        filtres = _Filtres(corps)
        filtres.pack(fill="x")
        filtres.periode(filtres.rangee1, self.vars["du"], self.vars["au"])
        self.cb_utilisateur = filtres.liste(filtres.rangee1, "Utilisateur :", self.vars["utilisateur"], 28)
        self.cb_categorie = filtres.liste(filtres.rangee1, "Catégorie :", self.vars["categorie"], 26)
        filtres.champ(filtres.rangee2, "Texte :", self.vars["texte"], 26, self.rechercher)
        tk.Checkbutton(filtres.rangee2, text="Opérations financières seulement", variable=self.var_financier,
                       bg=FOND_CLAIR, activebackground=FOND_CLAIR, selectcolor=BLANC, font=police(10), fg=NUIT,
                       cursor="hand2", command=self.rechercher).pack(side="left", padx=(0, px(16)))
        creer_bouton(filtres.rangee2, "Rechercher", self.rechercher, grand=False).pack(side="left")
        creer_bouton(filtres.rangee2, "Aujourd'hui", self.aujourdhui, style="secondaire",
                     grand=False).pack(side="left", padx=px(6))
        creer_bouton(filtres.rangee2, "Réinitialiser", self.reinitialiser, style="secondaire",
                     grand=False).pack(side="left")
        creer_bouton(filtres.rangee2, "Imprimer (PDF)", lambda: self.exporter("pdf"), style="secondaire",
                     grand=False).pack(side="right")
        creer_bouton(filtres.rangee2, "Exporter (Excel / CSV)", lambda: self.exporter("csv"), style="secondaire",
                     grand=False).pack(side="right", padx=px(6))

        self.lbl_resume = tk.Label(corps, text="", font=police(10, gras=True), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_resume.pack(fill="x", pady=(px(8), px(4)))
        cadre, self.arbre = creer_arbre(corps, [
            ("date", "Date et heure", 150, "w"), ("qui", "Utilisateur", 190, "w"), ("poste", "Poste", 120, "w"),
            ("categorie", "Catégorie", 170, "w"), ("action", "Action", 290, "w"), ("detail", "Détail", 420, "w")],
            hauteur=14)
        cadre.pack(fill="both", expand=True)
        self.arbre.tag_configure("alerte", foreground=ROUGE)
        self.arbre.tag_configure("financier", background=FOND_CLAIR)
        self.arbre.bind("<<TreeviewSelect>>", self._selection)

        self.var_detail = tk.StringVar(value="Cliquez sur une ligne pour lire son détail complet.")
        tk.Label(corps, textvariable=self.var_detail, font=police(10), fg=NUIT, bg=BLANC, anchor="w", justify="left",
                 wraplength=px(1150)).pack(fill="x", pady=(px(8), 0))
        self.lbl_message = tk.Label(corps, text="", font=police(10, gras=True), fg=ROUGE, bg=BLANC, anchor="w")
        self.lbl_message.pack(fill="x")

    # --- cycle de vie ------------------------------------------------------
    def au_affichage(self):
        self._charger_listes()
        if not self.charge:
            self.rechercher()

    def _charger_listes(self):
        try:
            self.utilisateurs = _liste_utilisateurs(self.app.conn, self.app.session)
        except ERREURS as erreur:
            self.lbl_message.config(text=str(erreur))
            return
        self.cb_utilisateur.config(values=list(self.utilisateurs))
        self.categories = {TOUTES_CATEGORIES: ""}
        self.categories.update({texte: cle for cle, texte in audit.CATEGORIES.items()})
        self.cb_categorie.config(values=list(self.categories))
        if self.vars["utilisateur"].get() not in self.utilisateurs:
            self.vars["utilisateur"].set(TOUS_UTILISATEURS)
        if self.vars["categorie"].get() not in self.categories:
            self.vars["categorie"].set(TOUTES_CATEGORIES)

    # --- actions -------------------------------------------------------------
    def _filtres(self) -> dict:
        return {"du": _lire_jour(self.vars["du"], "du"), "au": _lire_jour(self.vars["au"], "au"),
                "login": self.utilisateurs.get(self.vars["utilisateur"].get(), "") or None,
                "categorie": self.categories.get(self.vars["categorie"].get(), "") or None,
                "texte": self.vars["texte"].get().strip() or None, "financier_seul": self.var_financier.get()}

    def aujourdhui(self):
        jour = formater_date(date.today())
        self.vars["du"].set(jour)
        self.vars["au"].set(jour)
        self.rechercher()

    def reinitialiser(self):
        for cle in ("du", "au", "texte"):
            self.vars[cle].set("")
        self.vars["utilisateur"].set(TOUS_UTILISATEURS)
        self.vars["categorie"].set(TOUTES_CATEGORIES)
        self.var_financier.set(False)
        self.rechercher()

    def rechercher(self, _evenement=None):
        try:
            r = audit.journal(self.app.conn, self.app.session, **self._filtres())
        except ERREURS as erreur:
            self.lbl_message.config(text=str(erreur))
            return
        self.charge = True
        self.lbl_message.config(text="")
        self.lignes = r["lignes"]
        vider_arbre(self.arbre)
        for i, l in enumerate(self.lignes):
            qui = f"{l['login']} - {l['nom']}" if l["nom"] else (l["login"] or "—")
            tags = ("alerte",) if l["action"] in ("CONNEXION_ECHEC", "CONNEXION_REFUSEE_BLOCAGE") else (
                ("financier",) if l["financier"] else ())
            self.arbre.insert("", "end", iid=str(i), tags=tags, values=(
                l["date_txt"], qui, l["poste"] or "—", l["categorie_txt"], l["libelle"], l["detail"]))
        total, montrees = r["total"], len(self.lignes)
        self.lbl_resume.config(text=(f"{total} ligne(s) trouvée(s)" if total else "Aucune ligne trouvée")
                               + (f"  -  les {montrees} plus récentes sont affichées : affinez les filtres ou exportez "
                                  f"pour tout obtenir" if total > montrees else ""))
        self.var_detail.set("Cliquez sur une ligne pour lire son détail complet.")

    def _selection(self, _evenement=None):
        selection = self.arbre.selection()
        if not selection:
            return
        l = self.lignes[int(selection[0])]
        self.var_detail.set(f"{l['date_txt']}  -  {l['login'] or '—'}  -  {l['libelle']}  ({l['action']})"
                            + (f"\n{l['detail']}" if l["detail"] else ""))

    def exporter(self, format_):
        _exporter(self, lambda: audit.exporter_journal(self.app.conn, self.app.session, format_, **self._filtres()))


def _exporter(fenetre, creer_fichier):
    """Crée le fichier (CSV ou PDF) et l'ouvre ; en cas d'échec, explique pourquoi."""
    try:
        chemin = creer_fichier()
    except ERREURS as erreur:
        messagebox.showwarning("Exportation impossible", str(erreur), parent=fenetre)
        return
    except OSError as erreur:
        messagebox.showerror("Erreur", f"Impossible d'écrire le fichier : {erreur}", parent=fenetre)
        return
    try:
        ouvrir_fichier(chemin)
    except OSError:
        messagebox.showinfo("Exportation terminée", f"Le fichier est enregistré ici :\n{chemin}", parent=fenetre)


# ================================================================== 2) OPÉRATIONS FINANCIÈRES
class PanneauFinances(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.operations = []
        self.charge = False
        self.utilisateurs, self.types = {}, {}
        self.vars = {k: tk.StringVar() for k in ("du", "au", "eleve", "recu", "utilisateur", "type")}
        self.var_ecart = tk.BooleanVar(value=False)

        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(20), pady=px(10))

        filtres = _Filtres(corps)
        filtres.pack(fill="x")
        filtres.champ(filtres.rangee1, "Élève (nom ou matricule) :", self.vars["eleve"], 24, self.rechercher)
        filtres.champ(filtres.rangee1, "N° de reçu :", self.vars["recu"], 10, self.rechercher)
        self.cb_utilisateur = filtres.liste(filtres.rangee1, "Utilisateur :", self.vars["utilisateur"], 26)
        self.cb_type = filtres.liste(filtres.rangee1, "Opération :", self.vars["type"], 28)
        filtres.periode(filtres.rangee2, self.vars["du"], self.vars["au"])
        tk.Checkbutton(filtres.rangee2, text="Écarts seulement", variable=self.var_ecart, bg=FOND_CLAIR,
                       activebackground=FOND_CLAIR, selectcolor=BLANC, font=police(10), fg=NUIT, cursor="hand2",
                       command=self.rechercher).pack(side="left", padx=(0, px(16)))
        creer_bouton(filtres.rangee2, "Rechercher", self.rechercher, grand=False).pack(side="left")
        creer_bouton(filtres.rangee2, "Réinitialiser", self.reinitialiser, style="secondaire",
                     grand=False).pack(side="left", padx=px(6))
        creer_bouton(filtres.rangee2, "Imprimer (PDF)", lambda: self.exporter("pdf"), style="secondaire",
                     grand=False).pack(side="right")
        creer_bouton(filtres.rangee2, "Exporter (Excel / CSV)", lambda: self.exporter("csv"), style="secondaire",
                     grand=False).pack(side="right", padx=px(6))

        cadre, self.arbre_totaux = creer_arbre(corps, [
            ("dev", "Devise", 60, "w"), ("pay", "Paiements", 150, "e"), ("ann", "Annulations", 150, "e"),
            ("net", "Net des paiements", 150, "e"), ("enc", "Encaissé", 140, "e"), ("ver", "Versé", 140, "e"),
            ("eca", "Écart (encaissé - versé)", 160, "e")], hauteur=2)
        cadre.pack(fill="x", pady=(px(8), px(4)))
        self.arbre_totaux.tag_configure("ecart", foreground=ORANGE)

        self.lbl_resume = tk.Label(corps, text="", font=police(10, gras=True), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_resume.pack(fill="x", pady=(0, px(4)))
        cadre, self.arbre = creer_arbre(corps, [
            ("date", "Date et heure", 115, "w"), ("type", "Opération", 175, "w"), ("ref", "Référence", 80, "w"),
            ("eleve", "Élève", 190, "w"), ("detail", "Détail", 280, "w"), ("montant", "Montant", 90, "e"),
            ("verse", "Versé", 80, "e"), ("ecart", "Écart", 80, "e"), ("dev", "Devise", 50, "w"),
            ("par", "Fait par", 120, "w"), ("statut", "Statut", 80, "w")], hauteur=9)
        cadre.pack(fill="both", expand=True)
        self.arbre.tag_configure("annule", foreground=GRIS)
        self.arbre.tag_configure("ecart", foreground=ORANGE)
        self.arbre.bind("<<TreeviewSelect>>", self._selection)

        tk.Label(corps, text="Fiche de l'opération sélectionnée et traces du journal", font=police(10, gras=True),
                 fg=NUIT, bg=BLANC, anchor="w").pack(fill="x", pady=(px(8), px(2)))
        zone = tk.Frame(corps, bg=BLANC, highlightbackground=BORDURE, highlightthickness=1)
        zone.pack(fill="x")
        self.texte_fiche = tk.Text(zone, height=8, font=police(10), fg=NUIT, bg=BLANC, relief="flat", wrap="word",
                                   state="disabled", padx=px(8), pady=px(6))
        defil = ttk.Scrollbar(zone, orient="vertical", command=self.texte_fiche.yview)
        self.texte_fiche.configure(yscrollcommand=defil.set)
        self.texte_fiche.pack(side="left", fill="x", expand=True)
        defil.pack(side="right", fill="y")
        self.texte_fiche.tag_configure("titre", font=police(11, gras=True, titre=True))
        self.texte_fiche.tag_configure("gras", font=police(10, gras=True))
        self.texte_fiche.tag_configure("gris", foreground=GRIS)
        self._ecrire_fiche([("gris", "Cliquez sur une opération pour voir qui l'a faite, quand, et toutes ses traces.")])

        self.lbl_message = tk.Label(corps, text="", font=police(10, gras=True), fg=ROUGE, bg=BLANC, anchor="w")
        self.lbl_message.pack(fill="x")

    # --- cycle de vie ------------------------------------------------------
    def au_affichage(self):
        self._charger_listes()
        if not self.charge:
            self.rechercher()

    def _charger_listes(self):
        try:
            self.utilisateurs = _liste_utilisateurs(self.app.conn, self.app.session)
        except ERREURS as erreur:
            self.lbl_message.config(text=str(erreur))
            return
        self.cb_utilisateur.config(values=list(self.utilisateurs))
        self.types = {TOUTES_OPERATIONS: ""}
        self.types.update({texte: cle for cle, texte in audit.TYPES_OPERATION.items()})
        self.cb_type.config(values=list(self.types))
        if self.vars["utilisateur"].get() not in self.utilisateurs:
            self.vars["utilisateur"].set(TOUS_UTILISATEURS)
        if self.vars["type"].get() not in self.types:
            self.vars["type"].set(TOUTES_OPERATIONS)

    # --- actions -------------------------------------------------------------
    def _filtres(self) -> dict:
        return {"du": _lire_jour(self.vars["du"], "du"), "au": _lire_jour(self.vars["au"], "au"),
                "eleve": self.vars["eleve"].get().strip() or None, "n_recu": self.vars["recu"].get().strip() or None,
                "login": self.utilisateurs.get(self.vars["utilisateur"].get(), "") or None,
                "type_op": self.types.get(self.vars["type"].get(), "") or None, "ecart_seul": self.var_ecart.get()}

    def reinitialiser(self):
        for cle in ("du", "au", "eleve", "recu"):
            self.vars[cle].set("")
        self.vars["utilisateur"].set(TOUS_UTILISATEURS)
        self.vars["type"].set(TOUTES_OPERATIONS)
        self.var_ecart.set(False)
        self.rechercher()

    def rechercher(self, _evenement=None):
        try:
            r = audit.historique_financier(self.app.conn, self.app.session, **self._filtres())
        except ERREURS as erreur:
            self.lbl_message.config(text=str(erreur))
            return
        self.charge = True
        self.lbl_message.config(text="")
        self.operations = r["operations"]
        vider_arbre(self.arbre_totaux)
        for t in r["totaux"]:
            f = argent.formater
            self.arbre_totaux.insert("", "end", tags=("ecart",) if t["ecart"] else (), values=(
                t["devise"], f"{f(t['paiements'])}  ({t['paiements_nb']})", f"{f(t['annulations'])}  ({t['annulations_nb']})",
                f(t["net"]), f"{f(t['encaisse'])}  ({t['encaissements_nb']})", f(t["verse"]), f(t["ecart"])))
        vider_arbre(self.arbre)
        for i, o in enumerate(self.operations):
            tags = ("annule",) if o["type"] in ("ANNULATION", "ENC_SUPPRIME") else (("ecart",) if o["ecart"] else ())
            self.arbre.insert("", "end", iid=str(i), tags=tags, values=(
                o["date_txt"], o["type_txt"], o["reference"], o["eleve"] or "—", o["detail"], o["montant_txt"],
                o["verse_txt"], o["ecart_txt"], o["devise"], o["par_login"] or "—", o["statut"]))
        total, montrees = r["total"], len(self.operations)
        self.lbl_resume.config(text=(f"{total} opération(s) trouvée(s)" if total else "Aucune opération trouvée")
                               + (f"  -  les {montrees} plus récentes sont affichées : exportez pour tout obtenir"
                                  if total > montrees else ""))
        self._ecrire_fiche([("gris", "Cliquez sur une opération pour voir qui l'a faite, quand, et toutes ses traces.")])

    def _selection(self, _evenement=None):
        selection = self.arbre.selection()
        if not selection:
            return
        o = self.operations[int(selection[0])]
        if o["reference"] in ("", "ENC-?"):
            self._ecrire_fiche([("gris", o["detail"])])
            return
        try:
            t = audit.trace_operation(self.app.conn, self.app.session, o["reference"])
        except ERREURS as erreur:
            self._ecrire_fiche([("gris", str(erreur))])
            return
        morceaux = [("titre", t["titre"] + "\n")]
        for libelle, valeur in t["champs"]:
            morceaux += [("gras", f"{libelle} : "), ("", f"{valeur}\n")]
        morceaux.append(("gras", "\nTraces du journal\n"))
        if not t["evenements"]:
            morceaux.append(("gris", "Aucune trace au journal pour cette opération.\n"))
        for e in t["evenements"]:
            qui = f"{e['login']} ({e['nom']})" if e["nom"] else (e["login"] or "—")
            morceaux.append(("", f"{e['date_txt']}  -  {qui}  -  {e['libelle']}"
                                 + (f"  -  {e['detail']}" if e["detail"] else "") + "\n"))
        self._ecrire_fiche(morceaux)

    def _ecrire_fiche(self, morceaux):
        t = self.texte_fiche
        t.config(state="normal")
        t.delete("1.0", "end")
        for style, texte in morceaux:
            t.insert("end", texte, style) if style else t.insert("end", texte)
        t.config(state="disabled")

    def exporter(self, format_):
        _exporter(self, lambda: audit.exporter_historique(self.app.conn, self.app.session, format_, **self._filtres()))


# ================================================================== 3) CONTRÔLES
class PanneauControles(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(24), pady=px(16))
        tk.Label(corps, text="Contrôles du journal", font=police(16, gras=True, titre=True), fg=NUIT,
                 bg=BLANC).pack(anchor="w")
        tk.Label(corps, text=("Le journal est en ajout seulement : chaque ligne contient l'empreinte de la précédente, donc "
                              "toute modification ou suppression après coup se voit.\nLa concordance compare le journal et "
                              "les tables financières (reçus, annulations, encaissements) pour repérer ce qui a été fait "
                              "en dehors de l'application."),
                 font=police(10), fg=GRIS, bg=BLANC, justify="left", wraplength=px(1000)).pack(anchor="w", pady=(px(4), px(12)))
        boutons = tk.Frame(corps, bg=BLANC)
        boutons.pack(fill="x")
        creer_bouton(boutons, "Vérifier l'intégrité du journal", self.verifier_journal).pack(side="left")
        creer_bouton(boutons, "Contrôler la concordance", self.verifier_concordance,
                     style="secondaire").pack(side="left", padx=px(10))
        bouton_menu(boutons, self.app).pack(side="right")

        zone = tk.Frame(corps, bg=BLANC, highlightbackground=BORDURE, highlightthickness=1)
        zone.pack(fill="both", expand=True, pady=(px(14), 0))
        self.texte = tk.Text(zone, font=police(11), fg=NUIT, bg=BLANC, relief="flat", wrap="word", state="disabled",
                             padx=px(12), pady=px(10))
        defil = ttk.Scrollbar(zone, orient="vertical", command=self.texte.yview)
        self.texte.configure(yscrollcommand=defil.set)
        self.texte.pack(side="left", fill="both", expand=True)
        defil.pack(side="right", fill="y")
        self.texte.tag_configure("ok", foreground=VERT, font=police(11, gras=True))
        self.texte.tag_configure("erreur", foreground=ROUGE, font=police(11, gras=True))
        self.texte.tag_configure("alerte", foreground=ORANGE, font=police(11, gras=True))
        self.texte.tag_configure("gras", font=police(11, gras=True))
        self.texte.tag_configure("gris", foreground=GRIS)
        self._ecrire([("gris", "Choisissez un contrôle ci-dessus.")])

    def _ecrire(self, morceaux, ajouter=False):
        t = self.texte
        t.config(state="normal")
        if not ajouter:
            t.delete("1.0", "end")
        for style, texte in morceaux:
            t.insert("end", texte, style) if style else t.insert("end", texte)
        t.config(state="disabled")

    def verifier_journal(self):
        try:
            e = audit.controle_journal(self.app.conn, self.app.session)
        except ERREURS as erreur:
            self._ecrire([("erreur", str(erreur))])
            return
        morceaux = [("gras", "Intégrité du journal\n\n")]
        if e["ok"]:
            morceaux.append(("ok", "✔  La chaîne d'empreintes est intacte : aucune ligne n'a été modifiée ni supprimée.\n"))
        else:
            morceaux.append(("erreur", f"✘  ANOMALIE : le journal a été modifié à partir de la ligne {e['anomalie']}.\n"
                                       "Prévenez le responsable : ne restaurez rien avant d'avoir fait une copie du "
                                       "fichier de base de données.\n"))
        morceaux.append(("", f"\nLignes du journal : {e['nb_lignes']}\n"
                             + (f"Période couverte : du {e['debut']} au {e['fin']}\n" if e["nb_lignes"] else "")))
        morceaux.append(("gris", f"Dernière empreinte : {e['derniere_empreinte']}\n"
                                 "Notez-la ou imprimez un rapport : elle prouvera plus tard que le journal n'a pas été "
                                 "réécrit."))
        self._ecrire(morceaux)

    def verifier_concordance(self):
        try:
            anomalies = audit.controle_concordance(self.app.conn, self.app.session)
        except ERREURS as erreur:
            self._ecrire([("erreur", str(erreur))])
            return
        morceaux = [("gras", "Concordance entre le journal et les tables financières\n\n")]
        if not anomalies:
            morceaux.append(("ok", "✔  Tout concorde : chaque reçu, annulation et encaissement a sa trace au journal.\n"))
        else:
            morceaux.append(("alerte", f"⚠  {len(anomalies)} point(s) à vérifier :\n\n"))
            for a in anomalies:
                morceaux.append(("erreur" if a["gravite"] == "ÉLEVÉE" else "alerte", f"[{a['gravite']}]  "))
                morceaux.append(("", a["message"] + "\n"))
            morceaux.append(("gris", "\nUne anomalie n'est pas une preuve de fraude : elle indique où regarder."))
        self._ecrire(morceaux)


# ================================================================== MODULE
class ModuleAudit(tk.Frame):
    ONGLETS = (("journal", "1   Journal des activités"),
               ("finances", "2   Opérations financières"),
               ("controles", "3   Contrôles"),
               ("financier", "4   Contrôle et audit financier"),
               ("recherche", "5   Recherche et filtrage des traces"),
               ("rapports", "6   Génération des rapports d'audit"))

    @staticmethod
    def _classes() -> dict:
        # importés ici : ecrans_audit_financier réutilise des éléments de ce fichier (pas d'import circulaire au chargement)
        from ecrans_audit_financier import PanneauControleFinancier, PanneauRapports, PanneauRecherche
        return {"journal": PanneauJournal, "finances": PanneauFinances, "controles": PanneauControles,
                "financier": PanneauControleFinancier, "recherche": PanneauRecherche, "rapports": PanneauRapports}

    def __init__(self, app, onglet=None):
        super().__init__(app, bg=BLANC)
        self.app = app

        barre = barre_haute(self, "Traçabilité et audit")
        actions_barre_module(barre, app)
        tk.Label(barre, text=f"{app.session.nom_complet}  •  {app.session.libelle_role}", font=police(10),
                 fg=BLEU_PALE, bg=NUIT).pack(side="right", padx=px(8))

        if not audit.peut(app.conn, app.session):
            tk.Label(self, text="Votre compte n'a pas accès à ce module.\nDemandez à l'Administrateur de vous accorder "
                                "le droit « Lecture » (Gestionnaire d'accès > Autorisations).",
                     font=police(13), fg=GRIS, bg=BLANC, justify="center").pack(pady=px(60))
            return
        audit.journaliser_ouverture(app.conn, app.session)

        navigation = tk.Frame(self, bg=FOND_CLAIR)
        navigation.pack(fill="x")
        self.boutons = {}
        for i, (cle, texte) in enumerate(self.ONGLETS):
            navigation.grid_columnconfigure(i, weight=1, uniform="onglet")
            b = tk.Button(navigation, text=texte, command=lambda c=cle: self.afficher_onglet(c), relief="flat", bd=0,
                          highlightthickness=0, font=police(10, gras=True), padx=px(8), pady=px(8), cursor="hand2", wraplength=px(190))
            b.grid(row=0, column=i, sticky="nsew")
            self.boutons[cle] = b
        tk.Frame(self, bg=BORDURE, height=1).pack(fill="x")

        self._adaptative = ZoneAdaptative(self)
        self._adaptative.pack(fill="both", expand=True)
        self.zone = self._adaptative.interieur
        classes = self._classes()
        self.panneaux = {cle: classes[cle](self.zone, self) for cle, _ in self.ONGLETS}
        self.courant = None
        self.afficher_onglet(onglet if onglet in self.panneaux else "journal")

    def afficher_onglet(self, cle):
        for panneau in self.panneaux.values():
            panneau.pack_forget()
        for nom, bouton in self.boutons.items():
            actif = nom == cle
            bouton.config(bg=NUIT if actif else FOND_CLAIR, fg=BLANC if actif else NUIT,
                          activebackground=NUIT_CLAIR if actif else BORDURE,
                          activeforeground=BLANC if actif else NUIT)
        self.courant = self.panneaux[cle]
        self.courant.pack(fill="both", expand=True)
        if hasattr(self.courant, "au_affichage"):
            self.courant.au_affichage()

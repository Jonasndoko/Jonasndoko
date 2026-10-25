"""Module « Gestion du personnel » (écrans ; la logique est dans personnel.py et affectations.py).

Première fonctionnalité : DOSSIER PERSONNEL
  1. Nouvel agent        : enregistrer un agent (identité, coordonnées, matricule, engagement, fonction, statut). Droit Ajout.
  2. Dossier de l'agent  : UN SEUL écran pour un agent choisi dans la liste : consulter et modifier ses informations (droit
                           Modification), joindre / ouvrir / supprimer ses documents numérisés, voir et imprimer sa fiche individuelle.
Deuxième fonctionnalité : FONCTIONS ET AFFECTATIONS (écrans dans ecrans_affectations.py)
  3. Fonctions et services  4. Affectations et historique  5. Liste du personnel (par fonction ou par service)
Troisième fonctionnalité : PRÉSENCE ET ABSENCE (écrans dans ecrans_presences.py)
  6. Pointage du jour  7. Permissions et congés  8. États récapitulatifs (par période)
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import personnel
from ecrans_paiement import ZoneDefilante, creer_arbre, ouvrir_fichier, vider_arbre
from calendrier import SelecteurDate
from personnel import ErreurPersonnel
from theme import (BLANC, BLEU, BLEU_PALE, BORDURE, FOND_CLAIR, GRIS, NUIT, NUIT_CLAIR, ORANGE, ROUGE, VERT,
                   actions_barre_module, barre_haute, bouton_menu, carte, creer_bouton, creer_champ, definir_actif,
                   police, px, ZoneAdaptative)

ERREURS = (ErreurPersonnel, PermissionError)
SEXES = ("Masculin", "Féminin")


def _etiquette(parent, texte, obligatoire=True):
    cadre = tk.Frame(parent, bg=BLANC)
    cadre.pack(anchor="w", fill="x")
    tk.Label(cadre, text=texte, font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
    if obligatoire:
        tk.Label(cadre, text=" *", font=police(10, gras=True), fg=ROUGE, bg=BLANC).pack(side="left")


def _titre(parent, texte):
    tk.Label(parent, text=texte, font=police(12, gras=True, titre=True), fg=NUIT, bg=BLANC).pack(anchor="w", pady=(0, px(4)))


# ================================================================== formulaire d'un agent (partagé par les onglets 1 et 2)
class FormulaireAgent(tk.Frame):
    """Les champs d'un agent. `colonnes` : 3 (onglet large), 2 (volet de l'écran « Dossier de l'agent ») ou 1 (volet étroit)."""
    CLES = ("matricule", "nom", "postnom", "prenom", "sexe", "date_naissance", "adresse", "telephone", "email",
            "date_engagement", "fonction", "statut_pro")

    def __init__(self, parent, colonnes=3):
        super().__init__(parent, bg=BLANC)
        self.vars = {k: tk.StringVar() for k in self.CLES}
        self._entrees, self._listes, self._dates = [], [], []
        self._figee = False
        if colonnes == 3:
            self.grid_columnconfigure((0, 1, 2), weight=1, uniform="col")
            groupes = []
            for i in range(3):
                g = tk.Frame(self, bg=BLANC)
                g.grid(row=0, column=i, sticky="new", padx=(0 if i == 0 else px(10), 0 if i == 2 else px(10)))
                groupes.append(g)
        elif colonnes == 2:
            self.grid_columnconfigure((0, 1), weight=1, uniform="col")
            groupes = [tk.Frame(self, bg=BLANC) for _ in range(3)]
            groupes[0].grid(row=0, column=0, sticky="new", padx=(0, px(10)))
            groupes[1].grid(row=1, column=0, sticky="new", padx=(0, px(10)))
            groupes[2].grid(row=0, column=1, rowspan=2, sticky="new", padx=(px(10), 0))
        else:
            self.grid_columnconfigure(0, weight=1)
            groupes = [tk.Frame(self, bg=BLANC) for _ in range(3)]
            for i, g in enumerate(groupes):
                g.grid(row=i, column=0, sticky="new", pady=(0, px(6)))
        g1, g2, g3 = groupes

        _titre(g1, "Identité")
        self._texte(g1, "nom", "Nom")
        self._texte(g1, "postnom", "Postnom", obligatoire=False)
        self._texte(g1, "prenom", "Prénom", obligatoire=False)
        _etiquette(g1, "Sexe")
        self.cb_sexe = ttk.Combobox(g1, textvariable=self.vars["sexe"], state="readonly", font=police(11), values=SEXES)
        self.cb_sexe.pack(fill="x", ipady=px(2), pady=(px(2), px(6)))
        self._listes.append((self.cb_sexe, "readonly"))
        _etiquette(g1, "Date de naissance (jj/mm/aaaa)")
        self._date(g1, "date_naissance")

        _titre(g2, "Coordonnées")
        self._texte(g2, "adresse", "Adresse")
        self._texte(g2, "telephone", "Téléphone")
        self._texte(g2, "email", "E-mail (Gmail ou autre)", obligatoire=False)

        _titre(g3, "Situation professionnelle")
        _etiquette(g3, "Matricule", obligatoire=False)
        self.champ_matricule = creer_champ(g3, self.vars["matricule"])
        self.champ_matricule.pack(fill="x", ipady=px(3), pady=(px(2), px(0)))
        self.lbl_matricule = tk.Label(g3, text="", font=police(9), fg=GRIS, bg=BLANC, anchor="w", justify="left", wraplength=px(300))
        self.lbl_matricule.pack(fill="x", pady=(0, px(6)))
        _etiquette(g3, "Date d'engagement (jj/mm/aaaa)")
        self._date(g3, "date_engagement")
        _etiquette(g3, "Fonction")
        self.cb_fonction = ttk.Combobox(g3, textvariable=self.vars["fonction"], font=police(11), values=personnel.FONCTIONS)
        self.cb_fonction.pack(fill="x", ipady=px(2), pady=(px(2), px(0)))
        self.lbl_fonction = tk.Label(g3, text="", font=police(9), fg=GRIS, bg=BLANC, anchor="w", justify="left", wraplength=px(300))
        self.lbl_fonction.pack(fill="x", pady=(0, px(6)))
        self._fonction_modifiable = True                                # à la création seulement (voir mode_dossier)
        _etiquette(g3, "Statut professionnel")
        self.cb_statut = ttk.Combobox(g3, textvariable=self.vars["statut_pro"], state="readonly", font=police(11),
                                      values=list(personnel.STATUTS.values()))
        self.cb_statut.pack(fill="x", ipady=px(2), pady=(px(2), px(6)))
        self._listes.append((self.cb_statut, "readonly"))
        tk.Label(g3, text="* champ obligatoire", font=police(9), fg=GRIS, bg=BLANC).pack(anchor="w", pady=(px(4), 0))

    def _texte(self, parent, cle, libelle, obligatoire=True):
        _etiquette(parent, libelle, obligatoire)
        champ = creer_champ(parent, self.vars[cle])
        champ.pack(fill="x", ipady=px(3), pady=(px(2), px(6)))
        self._entrees.append(champ)
        if cle == "nom":
            self.champ_nom = champ

    def _date(self, parent, cle):
        s = SelecteurDate(parent, self.vars[cle])
        s.pack(fill="x", pady=(px(2), px(6)))
        self._dates.append(s)

    # --- contenu -------------------------------------------------------------
    def valeurs(self) -> dict:
        v = {k: self.vars[k].get() for k in self.CLES}
        v["sexe"] = {"Masculin": "M", "Féminin": "F"}.get(v["sexe"], "")
        return v

    def vider(self):
        for v in self.vars.values():
            v.set("")

    def remplir(self, a: dict):
        for cle in ("matricule", "nom", "postnom", "prenom", "date_naissance", "adresse", "telephone", "email",
                    "date_engagement", "fonction"):
            self.vars[cle].set(a[cle])
        self.vars["sexe"].set(a["libelle_sexe"])
        self.vars["statut_pro"].set(a["libelle_statut"])

    def proposer_fonctions(self, fonctions):
        """Fonctions proposées dans la liste (les fonctions actives de l'école ; à défaut, des exemples)."""
        self.cb_fonction.config(values=list(fonctions) or list(personnel.FONCTIONS))

    def mode_creation(self):
        """Le matricule peut être saisi (matricule officiel) ou laissé vide (le système l'attribue). La fonction se choisit
        dans la liste ou se tape : une fonction nouvelle est ajoutée à la liste de l'école."""
        self.champ_matricule.config(state="normal", bg=BLANC)
        self.lbl_matricule.config(text="Laissez vide : le système l'attribue (P0001/26). Tapez-le seulement s'il existe déjà.")
        self._fonction_modifiable = True
        self.lbl_fonction.config(text="Choisissez ou tapez : une fonction nouvelle est ajoutée à la liste. "
                                      "Elle devient la première affectation de l'agent.")

    def mode_dossier(self):
        """Le matricule ne change plus après la création ; la fonction change par une affectation (historique conservé)."""
        self.champ_matricule.config(state="readonly")
        self.lbl_matricule.config(text="Le matricule ne se modifie pas.")
        self._fonction_modifiable = False
        self.lbl_fonction.config(text="Se change dans « Fonctions et affectations » (l'historique est conservé).")

    def figer(self, figee: bool):
        """Consultation seule (compte sans le droit Modification) ou formulaire modifiable."""
        self._figee = figee
        for e in self._entrees:
            e.config(state="readonly" if figee else "normal", bg=FOND_CLAIR if figee else BLANC)
        for liste, etat in self._listes:
            liste.config(state="disabled" if figee else etat)
        self.cb_fonction.config(state="normal" if self._fonction_modifiable and not figee else "disabled")
        for d in self._dates:
            d.champ.config(state="readonly" if figee else "normal", bg=FOND_CLAIR if figee else BLANC)
            d.bouton.config(state="disabled" if figee else "normal")


# ================================================================== sélection d'un agent (écrans « Dossier de l'agent » et « Affectations »)
class SelecteurAgent(tk.Frame):
    """Recherche + liste des agents. `quand_choisi(matricule ou None)` est appelé à chaque sélection."""

    def __init__(self, parent, module, quand_choisi, hauteur=8):
        super().__init__(parent, bg=BLANC)
        self.module, self.app, self.quand_choisi = module, module.app, quand_choisi
        self.var_recherche, self.var_inactifs = tk.StringVar(), tk.IntVar(value=1)
        self._dernier, self._muet = None, False           # dernier agent annoncé ; vrai pendant la reconstruction de la liste
        haut = tk.Frame(self, bg=BLANC)
        haut.pack(fill="x", pady=(0, px(4)))
        tk.Label(haut, text="Rechercher :", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
        champ = creer_champ(haut, self.var_recherche, largeur=18)
        champ.pack(side="left", padx=px(6), ipady=px(3), fill="x", expand=True)
        champ.bind("<Return>", lambda _e: self.actualiser())
        self.var_recherche.trace_add("write", lambda *_a: self.actualiser())
        tk.Checkbutton(self, text="Afficher aussi les agents désactivés", variable=self.var_inactifs, font=police(9), bg=BLANC,
                       fg=NUIT, activebackground=BLANC, selectcolor=BLANC, highlightthickness=0,
                       command=self.actualiser).pack(anchor="w")
        cadre, self.arbre = creer_arbre(self, [("matricule", "Matricule", 85, "center"), ("nom", "Nom complet", 190, "w"),
                                               ("fonction", "Fonction", 120, "w")], hauteur=hauteur)
        cadre.pack(fill="both", expand=True, pady=(px(4), 0))
        self.arbre.tag_configure("inactif", foreground="#8A96B3")
        self.arbre.bind("<<TreeviewSelect>>", lambda _e: self._notifier())
        self.lbl_info = tk.Label(self, text="", font=police(9), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_info.pack(fill="x", pady=(px(3), 0))

    def choisi(self):
        sel = self.arbre.selection()
        return sel[0] if sel else None

    def _notifier(self, forcer=False):
        """Annonce le changement d'agent choisi (une seule fois par changement, sauf si `forcer`)."""
        if self._muet:
            return
        matricule = self.choisi()
        if forcer or matricule != self._dernier:
            self._dernier = matricule
            self.quand_choisi(matricule)

    def actualiser(self, garder=None, forcer=False):
        """Reconstruit la liste. `forcer` : annonce l'agent choisi même s'il n'a pas changé (retour sur l'onglet)."""
        garder = garder or self.choisi() or self.module.matricule_courant
        self._muet = True
        try:
            vider_arbre(self.arbre)
            try:
                agents = personnel.rechercher(self.app.conn, self.app.session, self.var_recherche.get(),
                                              inclure_inactifs=bool(self.var_inactifs.get()))
            except ERREURS as erreur:
                self.lbl_info.config(text=str(erreur), fg=ROUGE)
                agents = []
            for a in agents:
                self.arbre.insert("", "end", iid=a["matricule"], tags=() if a["actif"] else ("inactif",),
                                  values=(a["matricule"], a["nom_complet"], a["fonction"]))
            if agents:
                self.lbl_info.config(text=f"{len(agents)} agent(s)", fg=GRIS)
            elif self.var_recherche.get().strip():
                self.lbl_info.config(text="Aucun agent ne correspond à la recherche.", fg=GRIS)
            else:
                self.lbl_info.config(text="Aucun agent. Enregistrez-en un dans l'onglet « Nouvel agent ».", fg=GRIS)
            if garder and self.arbre.exists(garder):
                self.arbre.selection_set(garder)
                self.arbre.see(garder)
        finally:
            self._muet = False
        self._notifier(forcer)


def _volet_agent(zone, module, quand_choisi, hauteur=8):
    """Place le sélecteur à gauche d'un onglet et retourne (sélecteur, volet droit)."""
    zone.grid_columnconfigure(0, weight=0, minsize=px(430))
    zone.grid_columnconfigure(1, weight=1)
    zone.grid_rowconfigure(0, weight=1)
    sel = SelecteurAgent(zone, module, quand_choisi, hauteur=hauteur)
    sel.grid(row=0, column=0, sticky="nsew", padx=(px(24), px(10)), pady=px(14))
    droite = tk.Frame(zone, bg=BLANC)
    droite.grid(row=0, column=1, sticky="nsew", padx=(px(10), px(24)), pady=px(14))
    return sel, droite


# ================================================================== 1) NOUVEL AGENT
class PanneauNouveau(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        zone = ZoneDefilante(self)
        boite = carte(zone.interieur, padx=px(20), pady=px(12))
        boite.pack(fill="x", padx=px(24), pady=px(12))
        self.formulaire = FormulaireAgent(boite, colonnes=3)
        self.formulaire.pack(fill="x")
        self.formulaire.mode_creation()
        self.lbl_message = tk.Label(self, text="", font=police(11, gras=True), bg=BLANC, anchor="w", justify="left", wraplength=px(1000))
        boutons = tk.Frame(self, bg=BLANC)
        boutons.pack(side="bottom", fill="x", padx=px(24), pady=(0, px(12)))
        self.lbl_message.pack(side="bottom", fill="x", padx=px(26), pady=(px(2), px(4)))
        zone.pack(fill="both", expand=True)
        self.btn_enregistrer = creer_bouton(boutons, "ENREGISTRER", self.enregistrer)
        self.btn_enregistrer.pack(side="left", padx=(0, px(10)))
        creer_bouton(boutons, "ANNULER", self.annuler, style="danger").pack(side="left")
        bouton_menu(boutons, self.app).pack(side="right")

    def au_affichage(self):
        peut = personnel.peut(self.app.conn, self.app.session, "AJOUT")
        definir_actif(self.btn_enregistrer, peut)
        self.formulaire.proposer_fonctions(_fonctions_actives(self.app))
        self.formulaire.figer(not peut)
        self.formulaire.mode_creation()
        self._message("" if peut else "Votre compte n'a pas le droit « Ajout » sur ce module.", ROUGE)
        self.formulaire.champ_nom.focus_set()

    def _message(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    def enregistrer(self):
        try:
            r = personnel.enregistrer_agent(self.app.conn, self.app.session, self.formulaire.valeurs())
        except ERREURS as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.formulaire.vider()
        self.module.matricule_courant = r["matricule"]
        self._message(f"{r['nom_complet']} est enregistré(e) : matricule {r['matricule']}. "
                      f"Ses documents numérisés se joignent dans l'onglet « Documents administratifs ».", VERT)
        if messagebox.askyesno("Fiche individuelle", f"Agent enregistré, matricule {r['matricule']}.\n\n"
                                                    "Imprimer sa fiche individuelle maintenant ?", parent=self):
            _imprimer_fiche(self.app, self, r["matricule"])

    def annuler(self):
        self.formulaire.vider()
        self._message("")
        self.formulaire.champ_nom.focus_set()


def _fonctions_actives(app) -> list:
    """Libellés des fonctions actives de l'école (liste vide si aucune n'est encore définie)."""
    try:
        import affectations
        return [f["libelle"] for f in affectations.liste_referentiel(app.conn, app.session, "FONCTION", inclure_inactifs=False)]
    except ERREURS:
        return []


def _imprimer_fiche(app, parent, matricule):
    try:
        ouvrir_fichier(personnel.preparer_fiche_pdf(app.conn, app.session, matricule))
    except ERREURS as erreur:
        messagebox.showwarning("Impression impossible", str(erreur), parent=parent)
    except OSError as erreur:
        messagebox.showerror("Erreur", f"La fiche est prête mais n'a pas pu s'ouvrir : {erreur}", parent=parent)


# ================================================================== 2) DOSSIER DE L'AGENT (consulter, modifier, documents, fiche)
class PanneauDossier(tk.Frame):
    """Tout le dossier d'un agent sur un seul écran : ses informations (consultation et modification), ses documents
    administratifs numérisés, sa fiche individuelle (affichage et impression)."""

    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.matricule = None
        self.documents = {}
        self.selecteur, droite = _volet_agent(self, module, self.choisir)
        self.lbl_entete = tk.Label(droite, text="", font=police(13, gras=True, titre=True), fg=NUIT, bg=BLANC, anchor="w")
        self.lbl_entete.pack(fill="x")

        # --- barre du bas : toujours visible
        boutons = tk.Frame(droite, bg=BLANC)
        boutons.pack(side="bottom", fill="x", pady=(px(8), 0))
        self.lbl_message = tk.Label(droite, text="", font=police(11, gras=True), bg=BLANC, anchor="w", justify="left", wraplength=px(700))
        self.lbl_message.pack(side="bottom", fill="x", pady=(px(4), 0))
        self.btn_enregistrer = creer_bouton(boutons, "ENREGISTRER LES MODIFICATIONS", self.enregistrer, grand=False)
        self.btn_enregistrer.pack(side="left", padx=(0, px(8)))
        self.btn_annuler = creer_bouton(boutons, "ANNULER", self.recharger, style="secondaire", grand=False)
        self.btn_annuler.pack(side="left", padx=(0, px(8)))
        self.btn_fiche = creer_bouton(boutons, "VOIR / IMPRIMER LA FICHE", self.imprimer_fiche, style="secondaire", grand=False)
        self.btn_fiche.pack(side="left", padx=(0, px(8)))
        self.btn_activite = creer_bouton(boutons, "Désactiver", self.changer_activite, style="danger", grand=False)
        self.btn_activite.pack(side="left")

        # --- contenu : informations puis documents (défile si l'écran est petit)
        zone = ZoneDefilante(droite)
        zone.pack(fill="both", expand=True, pady=(px(6), 0))
        self.formulaire = FormulaireAgent(zone.interieur, colonnes=2)
        self.formulaire.pack(fill="x", padx=(0, px(14)))
        self.formulaire.mode_dossier()

        docs = carte(zone.interieur, padx=px(14), pady=px(10))
        docs.pack(fill="x", padx=(0, px(14)), pady=(px(10), px(6)))
        self.lbl_docs = tk.Label(docs, text="Documents administratifs numérisés", font=police(12, gras=True, titre=True),
                                 fg=NUIT, bg=BLANC, anchor="w")
        self.lbl_docs.pack(fill="x")
        cadre, self.arbre = creer_arbre(docs, [
            ("type", "Type de document", 190, "w"), ("fichier", "Fichier", 220, "w"), ("format", "Format", 60, "center"),
            ("taille", "Taille", 70, "center"), ("date", "Ajouté le", 90, "center")], hauteur=4)
        cadre.pack(fill="x", pady=(px(6), px(6)))
        self.arbre.bind("<Double-1>", lambda _e: self.ouvrir())
        self.arbre.bind("<<TreeviewSelect>>", lambda _e: self._activer())
        ligne = tk.Frame(docs, bg=BLANC)
        ligne.pack(fill="x")
        self.var_type = tk.StringVar(value=personnel.TYPES_DOCUMENT[0])
        self.cb_type = ttk.Combobox(ligne, textvariable=self.var_type, values=personnel.TYPES_DOCUMENT, state="readonly",
                                    width=30, font=police(11))
        self.cb_type.pack(side="left")
        self.btn_ajouter = creer_bouton(ligne, "CHOISIR LE FICHIER ET AJOUTER...", self.ajouter_document, grand=False)
        self.btn_ajouter.pack(side="left", padx=px(8))
        self.btn_ouvrir = creer_bouton(ligne, "OUVRIR", self.ouvrir, style="secondaire", grand=False)
        self.btn_ouvrir.pack(side="left", padx=(px(8), px(6)))
        self.btn_supprimer = creer_bouton(ligne, "SUPPRIMER", self.supprimer_document, style="danger", grand=False)
        self.btn_supprimer.pack(side="left")
        tk.Label(docs, text="PDF, JPEG ou PNG, 5 Mo au plus. Double-clic sur un document pour l'ouvrir.", font=police(9),
                 fg=GRIS, bg=BLANC, anchor="w").pack(fill="x", pady=(px(4), 0))
        self._afficher(None)

    def au_affichage(self):
        self.selecteur.actualiser(self.module.matricule_courant, forcer=True)

    def choisir(self, matricule):
        self.module.matricule_courant = matricule
        self.matricule = matricule
        self.recharger()

    def _message(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    def _droit(self, droit) -> bool:
        return personnel.peut(self.app.conn, self.app.session, droit)

    # --- informations ---------------------------------------------------------
    def _afficher(self, agent):
        peut = self._droit("MODIFICATION")
        self.formulaire.figer(agent is None or not peut)
        for b in (self.btn_enregistrer, self.btn_annuler, self.btn_activite):
            definir_actif(b, agent is not None and peut)
        definir_actif(self.btn_fiche, agent is not None)
        if agent is None:
            self.formulaire.vider()
            self.lbl_entete.config(text="Choisissez un agent dans la liste.")
            self.btn_activite.config(text="Désactiver")
            self._afficher_documents(None)
            return
        self.formulaire.remplir(agent)
        self.lbl_entete.config(text=agent["nom_complet"] + ("" if agent["actif"] else "   (désactivé)"))
        self.btn_activite.config(text="Désactiver" if agent["actif"] else "Réactiver")
        if not peut:
            self._message("Consultation seulement : votre compte n'a pas le droit « Modification » sur ce module.", ORANGE)
        self._afficher_documents(agent)

    def recharger(self):
        self._message("")
        if not self.matricule:
            self._afficher(None)
            return
        try:
            self._afficher(personnel.consulter_dossier(self.app.conn, self.app.session, self.matricule))
        except ERREURS as erreur:
            self._afficher(None)
            self._message(str(erreur), ROUGE)

    def enregistrer(self):
        try:
            champs = personnel.modifier_agent(self.app.conn, self.app.session, self.matricule, self.formulaire.valeurs())
        except ERREURS as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.selecteur.actualiser(self.matricule)
        self._afficher(personnel.charger_agent(self.app.conn, self.app.session, self.matricule))
        self._message("Modifications enregistrées : " + ", ".join(champs) + "." if champs else "Rien n'a changé.", VERT)

    def changer_activite(self):
        try:
            agent = personnel.charger_agent(self.app.conn, self.app.session, self.matricule)
            if agent["actif"] and not messagebox.askyesno(
                    "Désactiver l'agent", f"{agent['nom_complet']} ne fait plus partie du personnel en service ?\n\n"
                                          "Son dossier et ses documents sont conservés ; vous pourrez le réactiver.", parent=self):
                return
            personnel.changer_activite(self.app.conn, self.app.session, self.matricule, not agent["actif"])
        except ERREURS as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.selecteur.actualiser(self.matricule)
        self.recharger()
        self._message("Agent réactivé." if not agent["actif"] else "Agent désactivé : son dossier est conservé.", VERT)

    def imprimer_fiche(self):
        if self.matricule:
            _imprimer_fiche(self.app, self, self.matricule)

    # --- documents ------------------------------------------------------------
    def _afficher_documents(self, agent, garder=None):
        vider_arbre(self.arbre)
        self.documents = {}
        if agent is None:
            self.lbl_docs.config(text="Documents administratifs numérisés")
            self._activer()
            return
        try:
            docs = personnel.liste_documents(self.app.conn, self.app.session, agent["matricule"])
        except ERREURS as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.lbl_docs.config(text=f"Documents administratifs numérisés ({len(docs)})")
        for d in docs:
            self.documents[str(d["id_doc"])] = d
            self.arbre.insert("", "end", iid=str(d["id_doc"]), values=(d["type_doc"], d["nom_fichier"], d["format"],
                                                                     d["taille_txt"], d["date_ajout"]))
        if garder is not None and self.arbre.exists(str(garder)):
            self.arbre.selection_set(str(garder))
        self._activer()

    def _selection(self):
        sel = self.arbre.selection()
        return int(sel[0]) if sel else None

    def _activer(self):
        agent = self.matricule is not None
        peut_ajouter = agent and self._droit("AJOUT")
        definir_actif(self.btn_ajouter, peut_ajouter)
        self.cb_type.config(state="readonly" if peut_ajouter else "disabled")
        definir_actif(self.btn_ouvrir, self._selection() is not None)
        definir_actif(self.btn_supprimer, self._selection() is not None and self._droit("SUPPRESSION"))

    def ajouter_document(self):
        chemin = filedialog.askopenfilename(
            parent=self, title="Choisir le document numérisé",
            filetypes=[("Documents numérisés", "*.pdf *.jpg *.jpeg *.png"), ("Tous les fichiers", "*.*")])
        if not chemin:
            return
        try:
            id_doc = personnel.ajouter_document(self.app.conn, self.app.session, self.matricule, self.var_type.get(), chemin)
        except ERREURS as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.selecteur.actualiser(self.matricule)
        self._afficher_documents(personnel.charger_agent(self.app.conn, self.app.session, self.matricule), garder=id_doc)
        self._message(f"Document « {self.var_type.get()} » ajouté au dossier.", VERT)

    def ouvrir(self):
        id_doc = self._selection()
        if id_doc is None:
            return
        try:
            ouvrir_fichier(personnel.preparer_document(self.app.conn, self.app.session, id_doc))
        except ERREURS as erreur:
            self._message(str(erreur), ROUGE)
        except OSError as erreur:
            self._message(f"Le document n'a pas pu s'ouvrir : {erreur}", ROUGE)

    def supprimer_document(self):
        id_doc = self._selection()
        if id_doc is None:
            return
        d = self.documents[str(id_doc)]
        if not messagebox.askyesno("Supprimer le document", f"Retirer « {d['type_doc']} » ({d['nom_fichier']}) du dossier ?\n\n"
                                                           "Cette opération est inscrite au journal et ne peut pas être annulée.",
                                   icon="warning", parent=self):
            return
        try:
            personnel.supprimer_document(self.app.conn, self.app.session, id_doc)
        except ERREURS as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.selecteur.actualiser(self.matricule)
        self._afficher_documents(personnel.charger_agent(self.app.conn, self.app.session, self.matricule))
        self._message("Document supprimé.", VERT)


# ================================================================== MODULE
def onglets_autorises(conn, session) -> set:
    """Onglets utilisables par ce compte (droits relus dans la base)."""
    if not personnel.peut(conn, session, "LECTURE"):
        return set()
    ouverts = {"dossier", "fonctions", "affectation", "liste", "pointage", "autorisations", "etats"}
    if personnel.peut(conn, session, "AJOUT"):
        ouverts.add("nouveau")
    return ouverts


class ModulePersonnel(tk.Frame):
    """Trois fonctionnalités, chacune avec ses onglets : première ligne = la fonctionnalité, deuxième ligne = ses onglets."""
    FONCTIONNALITES = (
        ("dossier_personnel", "1   Dossier personnel", (("nouveau", "Nouvel agent"), ("dossier", "Dossier de l'agent"))),
        ("fonctions_affectations", "2   Fonctions et affectations",
         (("fonctions", "Fonctions et services"), ("affectation", "Affectations et historique"),
          ("liste", "Liste du personnel"))),
        ("presence_absence", "3   Présence et absence",
         (("pointage", "Pointage du jour"), ("autorisations", "Permissions et congés"), ("etats", "États récapitulatifs"))),
    )

    def __init__(self, app, onglet=None):
        super().__init__(app, bg=BLANC)
        import affectations
        import ecrans_affectations
        import ecrans_presences
        self.app = app
        self.matricule_courant = None                     # l'agent choisi reste sélectionné quand on change d'onglet
        self.autorises = onglets_autorises(app.conn, app.session)
        self.classes = {"nouveau": PanneauNouveau, "dossier": PanneauDossier, "fonctions": ecrans_affectations.PanneauFonctions,
                        "affectation": ecrans_affectations.PanneauAffectation, "liste": ecrans_affectations.PanneauListe,
                        "pointage": ecrans_presences.PanneauPointage, "autorisations": ecrans_presences.PanneauAutorisations,
                        "etats": ecrans_presences.PanneauEtats}
        if self.autorises:
            try:
                affectations.rafraichir_fonctions(app.conn)    # une affectation a pu commencer ou finir avec le temps
            except Exception:
                pass

        barre = barre_haute(self, "Gestion du personnel")
        actions_barre_module(barre, app)
        tk.Label(barre, text=f"{app.session.nom_complet}  •  {app.session.libelle_role}", font=police(10),
                 fg=BLEU_PALE, bg=NUIT).pack(side="right", padx=px(8))

        # ligne 1 : les fonctionnalités
        nav1 = tk.Frame(self, bg=NUIT)
        nav1.pack(fill="x")
        self.boutons_fonct, self.cadres_onglets, self.boutons = {}, {}, {}
        for i, (cle_f, texte_f, _onglets) in enumerate(self.FONCTIONNALITES):
            nav1.grid_columnconfigure(i, weight=1, uniform="fonct")
            b = tk.Button(nav1, text=texte_f, command=lambda c=cle_f: self.afficher_fonctionnalite(c), relief="flat", bd=0,
                          highlightthickness=0, font=police(12, gras=True), padx=px(12), pady=px(10), cursor="hand2")
            b.grid(row=0, column=i, sticky="nsew")
            self.boutons_fonct[cle_f] = b
        # ligne 2 : les onglets de la fonctionnalité affichée
        self.zone_nav = tk.Frame(self, bg=FOND_CLAIR)
        self.zone_nav.pack(fill="x")
        for cle_f, _t, onglets in self.FONCTIONNALITES:
            cadre = tk.Frame(self.zone_nav, bg=FOND_CLAIR)
            for i, (cle, texte) in enumerate(onglets):
                cadre.grid_columnconfigure(i, weight=1, uniform="onglet")
                verrouille = cle not in self.autorises
                b = tk.Button(cadre, text=texte + ("   (réservé)" if verrouille else ""),
                              command=lambda c=cle: self.afficher_onglet(c), relief="flat", bd=0, highlightthickness=0,
                              font=police(11, gras=True), padx=px(12), pady=px(10), cursor="hand2", wraplength=px(300))
                b.grid(row=0, column=i, sticky="nsew")
                self.boutons[cle] = b
            self.cadres_onglets[cle_f] = cadre
        tk.Frame(self, bg=BORDURE, height=1).pack(fill="x")

        self._adaptative = ZoneAdaptative(self)
        self._adaptative.pack(fill="both", expand=True)
        self.zone = self._adaptative.interieur
        self.panneaux = {cle: self.classes[cle](self.zone, self) for cle in self.classes if cle in self.autorises}
        self.courant = None
        self.fonctionnalite = None
        # sans le droit Ajout, on ouvre directement sur la consultation du dossier
        premier = next((c for c in ("nouveau", "dossier") if c in self.panneaux), None)
        if premier:
            self.afficher_onglet(onglet if onglet in self.panneaux else premier)
        else:
            tk.Label(self.zone, text="Votre compte n'a pas accès à ce module.\nDemandez à l'Administrateur de vous accorder "
                                     "le droit « Lecture » (Gestionnaire d'accès > Autorisations).",
                     font=police(13), fg=GRIS, bg=BLANC, justify="center").pack(pady=px(60))

    def _fonctionnalite_de(self, cle_onglet):
        return next(f[0] for f in self.FONCTIONNALITES if any(o[0] == cle_onglet for o in f[2]))

    def afficher_fonctionnalite(self, cle_f):
        """Ouvre le premier onglet utilisable de la fonctionnalité."""
        onglets = next(f[2] for f in self.FONCTIONNALITES if f[0] == cle_f)
        premier = next((c for c, _t in onglets if c in self.panneaux), None)
        if premier:
            self.afficher_onglet(premier)

    def afficher_onglet(self, cle):
        if cle not in self.panneaux:                      # onglet verrouillé : on explique pourquoi, sans bouger
            if cle == "nouveau":
                messagebox.showinfo("Nouvel agent", "Votre compte n'a pas le droit « Ajout » sur ce module.\n"
                                                    "Demandez à l'Administrateur de vous l'accorder "
                                                    "(Gestionnaire d'accès > Autorisations).", parent=self)
            return
        cle_f = self._fonctionnalite_de(cle)
        for c, cadre in self.cadres_onglets.items():
            cadre.pack_forget()
        self.cadres_onglets[cle_f].pack(fill="x")
        for c, b in self.boutons_fonct.items():
            actif = c == cle_f
            b.config(bg=BLEU if actif else NUIT, fg=BLANC if actif else BLEU_PALE,
                     activebackground=BLEU if actif else NUIT_CLAIR, activeforeground=BLANC)
        for panneau in self.panneaux.values():
            panneau.pack_forget()
        for nom, bouton in self.boutons.items():
            actif = nom == cle
            verrouille = nom not in self.panneaux
            bouton.config(bg=NUIT if actif else FOND_CLAIR,
                          fg=BLANC if actif else ("#8A96B3" if verrouille else NUIT),
                          activebackground=NUIT_CLAIR if actif else BORDURE,
                          activeforeground=BLANC if actif else NUIT)
        self.fonctionnalite = cle_f
        self.courant = self.panneaux[cle]
        self.courant.pack(fill="both", expand=True)
        if hasattr(self.courant, "au_affichage"):
            self.courant.au_affichage()

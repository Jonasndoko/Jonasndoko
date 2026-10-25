"""Module « Inscription ».

1. Formulaire d'inscription (première fonctionnalité) : rempli par l'utilisateur concerné (le secrétaire) avec le reçu que le
   candidat a obtenu à la caisse. Le système ne valide pas la candidature d'un candidat qui n'a pas payé.
   Boutons : ENREGISTRER ET IMPRIMER, ANNULER.
2. Liste d'attente : les candidats enregistrés, dans l'ordre d'arrivée, classe par classe ; réimpression de la fiche.
3. Validation et affectation (deuxième fonctionnalité) : note du test d'admission ; si le candidat réussit, son dossier est
   validé, on l'affecte à une classe et il devient élève avec son matricule. Droit « Modification ».
"""
import tkinter as tk
from tkinter import messagebox, ttk

import donnees
import inscription
from calendrier import SelecteurDate
from ecrans_paiement import ZoneDefilante, creer_arbre, ouvrir_fichier, vider_arbre
from inscription import ErreurInscription
from theme import (BLANC, BLEU_PALE, BORDURE, FOND_CLAIR, GRIS, NUIT, NUIT_CLAIR, ORANGE, ROUGE, VERT,
                   actions_barre_module, barre_haute, bouton_menu, carte, creer_bouton, creer_champ, definir_actif,
                   police, px, ZoneAdaptative)

ERREURS = (ErreurInscription, PermissionError)
CHAMPS_TEXTE = ("n_recu", "nom", "postnom", "prenom", "lieu_naissance", "nationalite", "adresse", "telephone",
                "ecole_origine", "pourcent_origine", "nom_tuteur", "tel_tuteur", "adresse_tuteur")


def _etiquette(parent, texte, obligatoire=True):
    cadre = tk.Frame(parent, bg=BLANC)
    cadre.pack(anchor="w", fill="x")
    tk.Label(cadre, text=texte, font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
    if obligatoire:
        tk.Label(cadre, text=" *", font=police(10, gras=True), fg=ROUGE, bg=BLANC).pack(side="left")


# ================================================================== 1) FORMULAIRE
class PanneauFormulaire(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.classes = {}                                    # libellé affiché -> n° de classe
        self.vars = {k: tk.StringVar() for k in CHAMPS_TEXTE + ("sexe", "date_naissance", "classe", "doublant")}

        zone = ZoneDefilante(self)                           # le formulaire défile si l'écran est petit ; les boutons restent visibles

        # --- le paiement d'abord : sans reçu valide, rien n'est enregistré
        bandeau = carte(zone.interieur, padx=px(20), pady=px(10))
        bandeau.pack(fill="x", padx=px(24), pady=(px(12), px(6)))
        ligne = tk.Frame(bandeau, bg=BLANC)
        ligne.pack(fill="x")
        _etiquette(ligne, "N° du reçu de paiement des frais d'inscription")
        self.champ_recu = creer_champ(ligne, self.vars["n_recu"], largeur=14)
        self.champ_recu.pack(side="left", ipady=px(4), padx=px(10))
        self.champ_recu.bind("<Return>", lambda _e: self.verifier_recu())
        creer_bouton(ligne, "VÉRIFIER LE PAIEMENT", self.verifier_recu, style="secondaire", grand=False).pack(side="left")
        self.lbl_recu = tk.Label(bandeau, text="", font=police(10, gras=True), bg=BLANC, anchor="w", justify="left",
                                 wraplength=px(1000))
        self.lbl_recu.pack(fill="x", pady=(px(4), 0))

        # --- trois colonnes : identité, parcours, tuteur
        boite = carte(zone.interieur, padx=px(20), pady=px(8))
        boite.pack(fill="x", padx=px(24), pady=(0, px(6)))
        colonnes = tk.Frame(boite, bg=BLANC)
        colonnes.pack(fill="x")
        colonnes.grid_columnconfigure((0, 1, 2), weight=1, uniform="col")
        c1, c2, c3 = (tk.Frame(colonnes, bg=BLANC) for _ in range(3))
        c1.grid(row=0, column=0, sticky="new", padx=(0, px(14)))
        c2.grid(row=0, column=1, sticky="new", padx=px(7))
        c3.grid(row=0, column=2, sticky="new", padx=(px(14), 0))

        def titre(parent, texte):
            tk.Label(parent, text=texte, font=police(12, gras=True, titre=True), fg=NUIT, bg=BLANC).pack(anchor="w", pady=(0, px(4)))

        def texte(parent, cle, libelle, obligatoire=True):
            _etiquette(parent, libelle, obligatoire)
            champ = creer_champ(parent, self.vars[cle])
            champ.pack(fill="x", ipady=px(3), pady=(px(2), px(6)))
            return champ

        titre(c1, "Identité du candidat")
        self.champ_nom = texte(c1, "nom", "Nom")
        texte(c1, "postnom", "Postnom", obligatoire=False)
        texte(c1, "prenom", "Prénom", obligatoire=False)
        _etiquette(c1, "Sexe")
        self.cb_sexe = ttk.Combobox(c1, textvariable=self.vars["sexe"], state="readonly", font=police(11),
                                    values=("Masculin", "Féminin"))
        self.cb_sexe.pack(fill="x", ipady=px(2), pady=(px(2), px(6)))
        _etiquette(c1, "Date de naissance (jj/mm/aaaa)")
        SelecteurDate(c1, self.vars["date_naissance"]).pack(fill="x", pady=(px(2), px(6)))
        texte(c1, "lieu_naissance", "Lieu de naissance", obligatoire=False)
        texte(c1, "nationalite", "Nationalité", obligatoire=False)
        texte(c1, "adresse", "Adresse")
        texte(c1, "telephone", "Téléphone", obligatoire=False)

        titre(c2, "Parcours scolaire")
        texte(c2, "ecole_origine", "Ancienne école")
        texte(c2, "pourcent_origine", "Pourcentage obtenu (ex. 68 ou 68,5)")
        _etiquette(c2, "Doublant ?")
        cadre_d = tk.Frame(c2, bg=BLANC)
        cadre_d.pack(anchor="w", pady=(px(2), px(8)))
        for valeur in ("Oui", "Non"):
            tk.Radiobutton(cadre_d, text=valeur, value=valeur, variable=self.vars["doublant"], font=police(11), bg=BLANC,
                           fg=NUIT, activebackground=BLANC, selectcolor=BLANC, highlightthickness=0).pack(side="left", padx=(0, px(18)))
        _etiquette(c2, "Classe dans laquelle il veut être inscrit")
        self.cb_classe = ttk.Combobox(c2, textvariable=self.vars["classe"], state="readonly", font=police(11))
        self.cb_classe.pack(fill="x", ipady=px(2), pady=(px(2), px(6)))

        titre(c3, "Tuteur")
        texte(c3, "nom_tuteur", "Nom du tuteur")
        texte(c3, "tel_tuteur", "Téléphone du tuteur")
        texte(c3, "adresse_tuteur", "Adresse du tuteur")
        tk.Label(c3, text="* champ obligatoire", font=police(9), fg=GRIS, bg=BLANC).pack(anchor="w", pady=(px(8), 0))

        boutons = tk.Frame(self, bg=BLANC)
        boutons.pack(side="bottom", fill="x", padx=px(24), pady=(0, px(12)))
        self.lbl_message = tk.Label(self, text="", font=police(11, gras=True), bg=BLANC, anchor="w", justify="left",
                                    wraplength=px(1000))
        self.lbl_message.pack(side="bottom", fill="x", padx=px(26), pady=(px(2), px(4)))
        zone.pack(fill="both", expand=True)
        self.btn_enregistrer = creer_bouton(boutons, "ENREGISTRER ET IMPRIMER", self.enregistrer)
        self.btn_enregistrer.pack(side="left", padx=(0, px(10)))
        creer_bouton(boutons, "ANNULER", self.annuler, style="danger").pack(side="left")
        bouton_menu(boutons, self.app).pack(side="right")

    # --- cycle de vie ------------------------------------------------------
    def au_affichage(self):
        self.preparer()

    def preparer(self):
        for cle in self.vars:
            self.vars[cle].set("")
        self.lbl_recu.config(text="")
        self.classes = {libelle: n for n, libelle in inscription.classes_proposees(self.app.conn, self.app.session)}
        self.cb_classe.config(values=list(self.classes))
        peut_ajouter = inscription.peut(self.app.conn, self.app.session, "AJOUT")
        definir_actif(self.btn_enregistrer, peut_ajouter)
        if not peut_ajouter:
            self._message("Votre compte n'a pas le droit « Ajout » sur ce module : consultation seulement.", ROUGE)
        elif not self.classes:
            self._message("Aucune classe active : l'Administrateur doit en ajouter une (Travaux techniques > Classes).", ORANGE)
        elif not inscription.types_frais_inscription(self.app.conn):
            self._message("Aucun type de frais n'est marqué « Frais d'inscription » : l'Administrateur doit le faire "
                          "(Travaux techniques > Types de frais). Sans cela, aucune candidature ne peut être validée.", ORANGE)
        else:
            self._message("")
        self.champ_recu.focus_set()

    def _message(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    # --- actions -------------------------------------------------------------
    def verifier_recu(self):
        try:
            recu = inscription.verifier_recu_pour_ecran(self.app.conn, self.app.session, self.vars["n_recu"].get())
        except ERREURS as erreur:
            self.lbl_recu.config(text=str(erreur), fg=ROUGE)
            return False
        self.lbl_recu.config(text=f"Paiement confirmé : {recu['type_frais']} - {recu['montant_txt']} {recu['devise']} "
                                  f"(reçu du {recu['date_txt']}, année {recu['annee']}).", fg=VERT)
        return True

    def _saisie(self) -> dict:
        v = {k: self.vars[k].get() for k in CHAMPS_TEXTE + ("date_naissance",)}
        v["sexe"] = {"Masculin": "M", "Féminin": "F"}.get(self.vars["sexe"].get(), "")
        v["doublant"] = {"Oui": True, "Non": False}.get(self.vars["doublant"].get())
        v["n_classe"] = self.classes.get(self.vars["classe"].get())
        return v

    def enregistrer(self):
        try:
            resultat = inscription.enregistrer_candidature(self.app.conn, self.app.session, self._saisie())
        except ERREURS as erreur:
            self._message(str(erreur), ROUGE)
            if self.vars["n_recu"].get().strip():
                self.verifier_recu()                      # montre aussi, sous le numéro, ce qui ne va pas avec le reçu
            return
        self.preparer()
        self._message(f"Candidature {resultat['num_cand']} enregistrée : le candidat est sur la liste d'attente "
                      f"(position {resultat['rang']} dans sa classe).", VERT)
        try:
            ouvrir_fichier(inscription.preparer_fiche_pdf(self.app.conn, self.app.session, resultat["n_cand"]))
        except ERREURS as erreur:
            messagebox.showwarning("Impression impossible", f"La candidature est enregistrée, mais : {erreur}", parent=self)
        except OSError as erreur:
            messagebox.showerror("Erreur", f"La candidature est enregistrée, mais la fiche n'a pas pu s'ouvrir : {erreur}",
                                 parent=self)

    def annuler(self):
        self.preparer()


# ================================================================== 2) LISTE D'ATTENTE
class PanneauListe(tk.Frame):
    TOUTES = "Toutes les classes"

    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.classes, self.candidats = {}, {}
        self.var_classe, self.var_recherche = tk.StringVar(), tk.StringVar()

        haut = tk.Frame(self, bg=BLANC)
        haut.pack(fill="x", padx=px(24), pady=(px(14), px(4)))
        tk.Label(haut, text="Classe :", font=police(11, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
        self.cb_classe = ttk.Combobox(haut, textvariable=self.var_classe, state="readonly", width=34, font=police(11))
        self.cb_classe.pack(side="left", padx=px(8))
        self.cb_classe.bind("<<ComboboxSelected>>", lambda _e: self.actualiser())
        tk.Label(haut, text="Recherche :", font=police(11, gras=True), fg=NUIT, bg=BLANC).pack(side="left", padx=(px(12), 0))
        champ = creer_champ(haut, self.var_recherche, largeur=22)
        champ.pack(side="left", padx=px(8), ipady=px(3))
        champ.bind("<Return>", lambda _e: self.actualiser())
        creer_bouton(haut, "ACTUALISER", self.actualiser, style="secondaire", grand=False).pack(side="left")

        self.lbl_info = tk.Label(self, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_info.pack(fill="x", padx=px(24), pady=(0, px(4)))
        cadre, self.arbre = creer_arbre(self, [
            ("rang", "Rang", 55, "center"), ("num", "Candidature", 105, "center"), ("nom", "Nom complet", 260, "w"),
            ("classe", "Classe souhaitée", 150, "w"), ("ecole", "Ancienne école", 200, "w"), ("pct", "%", 60, "center"),
            ("dbl", "Doublant", 75, "center"), ("recu", "Reçu", 70, "center"), ("date", "Enregistré le", 100, "center")],
            hauteur=6)
        bas = tk.Frame(self, bg=BLANC)
        bas.pack(side="bottom", fill="x", padx=px(24), pady=(px(8), px(14)))
        cadre.pack(fill="both", expand=True, padx=px(24))
        self.btn_fiche = creer_bouton(bas, "IMPRIMER LA FICHE", self.imprimer, grand=False)
        self.btn_fiche.pack(side="left")
        bouton_menu(bas, self.app).pack(side="right")

    def au_affichage(self):
        conn = self.app.conn
        self.classes = {inscription_lbl: n for n, inscription_lbl in inscription.classes_proposees(conn, self.app.session)}
        self.cb_classe.config(values=[self.TOUTES] + list(self.classes))
        if not self.var_classe.get():
            self.var_classe.set(self.TOUTES)
        self.actualiser()

    def actualiser(self):
        vider_arbre(self.arbre)
        self.candidats = {}
        try:
            liste = inscription.liste_attente(self.app.conn, self.app.session,
                                              n_classe=self.classes.get(self.var_classe.get()),
                                              recherche=self.var_recherche.get())
        except ERREURS as erreur:
            self.lbl_info.config(text=str(erreur), fg=ROUGE)
            return
        for c in liste:
            iid = self.arbre.insert("", "end", values=(c["rang"], c["num_cand"], c["nom_complet"], c["classe"],
                                                       c["ecole_origine"], c["pourcent_origine"],
                                                       "Oui" if c["doublant"] else "Non", c["n_recu"], c["date_enreg"]))
            self.candidats[iid] = c["n_cand"]
        annee = donnees.annee_courante(self.app.conn)
        self.lbl_info.config(text=(f"{len(liste)} candidat(s) en attente - année {annee}" if annee else
                                   "Aucune année scolaire n'est définie."), fg=GRIS)
        definir_actif(self.btn_fiche, bool(liste))

    def imprimer(self):
        selection = self.arbre.selection()
        if not selection:
            messagebox.showinfo("Fiche d'inscription", "Cliquez d'abord sur un candidat dans la liste.", parent=self)
            return
        try:
            ouvrir_fichier(inscription.preparer_fiche_pdf(self.app.conn, self.app.session, self.candidats[selection[0]]))
        except ERREURS as erreur:
            messagebox.showwarning("Impression impossible", str(erreur), parent=self)
        except OSError as erreur:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir la fiche : {erreur}", parent=self)


# ================================================================== 3) VALIDATION ET AFFECTATION
class PanneauValidation(tk.Frame):
    TOUS = "Tous les candidats"
    FILTRES = {"À traiter (test ou affectation)": ("A_TESTER", "A_AFFECTER"), "Test à passer": ("A_TESTER",),
               "Réussis, à affecter": ("A_AFFECTER",), "Admis (élèves)": ("ADMIS",), "Refusés": ("REFUSE",),
               TOUS: None}

    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.classes, self.candidats, self.courant = {}, {}, None
        self.var_filtre, self.var_recherche = tk.StringVar(value=next(iter(self.FILTRES))), tk.StringVar()
        self.var_note, self.var_affectation = tk.StringVar(), tk.StringVar()

        haut = tk.Frame(self, bg=BLANC)
        haut.pack(fill="x", padx=px(24), pady=(px(12), px(4)))
        tk.Label(haut, text="Afficher :", font=police(11, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
        cb = ttk.Combobox(haut, textvariable=self.var_filtre, state="readonly", width=30, font=police(11),
                          values=list(self.FILTRES))
        cb.pack(side="left", padx=px(8))
        cb.bind("<<ComboboxSelected>>", lambda _e: self.actualiser())
        tk.Label(haut, text="Recherche :", font=police(11, gras=True), fg=NUIT, bg=BLANC).pack(side="left", padx=(px(12), 0))
        champ = creer_champ(haut, self.var_recherche, largeur=22)
        champ.pack(side="left", padx=px(8), ipady=px(3))
        champ.bind("<Return>", lambda _e: self.actualiser())
        creer_bouton(haut, "ACTUALISER", self.actualiser, style="secondaire", grand=False).pack(side="left")

        self.lbl_info = tk.Label(self, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_info.pack(fill="x", padx=px(24), pady=(0, px(4)))
        cadre, self.arbre = creer_arbre(self, [
            ("num", "Candidature", 100, "center"), ("nom", "Nom complet", 250, "w"), ("souhaitee", "Classe souhaitée", 130, "w"),
            ("note", "Note /100", 80, "center"), ("etape", "Situation", 170, "w"), ("affectee", "Classe d'affectation", 140, "w"),
            ("matricule", "Matricule", 90, "center")], hauteur=5)
        cadre.pack(fill="both", expand=True, padx=px(24))
        self.arbre.bind("<<TreeviewSelect>>", lambda _e: self.selectionner())

        # --- les deux étapes, côte à côte
        bas = tk.Frame(self, bg=BLANC)
        bas.pack(side="bottom", fill="x", padx=px(24), pady=(px(8), px(4)), before=cadre)
        bas.grid_columnconfigure((0, 1), weight=1, uniform="etape")
        e1 = carte(bas, padx=px(16), pady=px(8))
        e1.grid(row=0, column=0, sticky="nsew", padx=(0, px(6)))
        e2 = carte(bas, padx=px(16), pady=px(8))
        e2.grid(row=0, column=1, sticky="nsew", padx=(px(6), 0))

        tk.Label(e1, text="1   Résultat du test d'admission", font=police(12, gras=True, titre=True), fg=NUIT,
                 bg=BLANC).pack(anchor="w")
        ligne = tk.Frame(e1, bg=BLANC)
        ligne.pack(fill="x", pady=(px(6), 0))
        tk.Label(ligne, text="Note (sur 100) :", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
        self.champ_note = creer_champ(ligne, self.var_note, largeur=8)
        self.champ_note.pack(side="left", padx=px(8), ipady=px(3))
        self.champ_note.bind("<Return>", lambda _e: self.enregistrer_test())
        self.btn_test = creer_bouton(ligne, "ENREGISTRER LE RÉSULTAT", self.enregistrer_test, grand=False)
        self.btn_test.pack(side="left")
        tk.Label(e1, text=f"Seuil de réussite : {inscription.seuil_reussite():g} / 100. En dessous, la candidature est refusée.",
                 font=police(9), fg=GRIS, bg=BLANC, anchor="w").pack(fill="x", pady=(px(4), 0))

        tk.Label(e2, text="2   Affectation à une classe", font=police(12, gras=True, titre=True), fg=NUIT,
                 bg=BLANC).pack(anchor="w")
        ligne = tk.Frame(e2, bg=BLANC)
        ligne.pack(fill="x", pady=(px(6), 0))
        tk.Label(ligne, text="Classe :", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
        self.cb_classe = ttk.Combobox(ligne, textvariable=self.var_affectation, state="readonly", width=24, font=police(11))
        self.cb_classe.pack(side="left", padx=px(8))
        self.btn_affecter = creer_bouton(ligne, "VALIDER ET AFFECTER", self.affecter, grand=False)
        self.btn_affecter.pack(side="left")
        tk.Label(e2, text="Le candidat devient élève : matricule et code QR attribués, inscription dans la classe.",
                 font=police(9), fg=GRIS, bg=BLANC, anchor="w").pack(fill="x", pady=(px(4), 0))

        pied = tk.Frame(self, bg=BLANC)
        pied.pack(side="bottom", fill="x", padx=px(24), pady=(px(4), px(12)), before=bas)
        self.lbl_message = tk.Label(pied, text="", font=police(10, gras=True), bg=BLANC, anchor="w", justify="left",
                                    wraplength=px(760))
        self.lbl_message.pack(side="left", fill="x", expand=True)
        bouton_menu(pied, self.app).pack(side="right")
        self.btn_avis = creer_bouton(pied, "IMPRIMER L'AVIS D'ADMISSION", self.imprimer_avis, style="secondaire", grand=False)
        self.btn_avis.pack(side="right", padx=px(8))
        self._boutons_selon_selection()

    def _message(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    def au_affichage(self):
        self.classes = {libelle: n for n, libelle in inscription.classes_proposees(self.app.conn, self.app.session)}
        self.cb_classe.config(values=list(self.classes))
        self.actualiser()

    def _libelle_classe(self, n_classe):
        return next((lbl for lbl, n in self.classes.items() if n == n_classe), "")

    def actualiser(self, garder=None):
        vider_arbre(self.arbre)
        self.candidats, self.courant = {}, None
        etapes = self.FILTRES[self.var_filtre.get()]
        try:
            liste = inscription.liste_validation(self.app.conn, self.app.session, recherche=self.var_recherche.get())
        except ERREURS as erreur:
            self.lbl_info.config(text=str(erreur), fg=ROUGE)
            return
        liste = [c for c in liste if etapes is None or c["etape"] in etapes]
        for c in liste:
            iid = self.arbre.insert("", "end", values=(c["num_cand"], c["nom_complet"], c["classe"], c["note_test"] or "",
                                                       c["libelle_etape"], c["classe_affectee"], c["matricule"] or ""))
            self.candidats[iid] = c
            if garder and c["n_cand"] == garder:
                self.arbre.selection_set(iid)
        annee = donnees.annee_courante(self.app.conn)
        self.lbl_info.config(text=(f"{len(liste)} candidat(s) - année {annee}" if annee else
                                   "Aucune année scolaire n'est définie."), fg=GRIS)
        self._boutons_selon_selection()

    def selectionner(self):
        selection = self.arbre.selection()
        self.courant = self.candidats.get(selection[0]) if selection else None
        c = self.courant
        if c:
            self.var_note.set("")
            self.var_affectation.set(self._libelle_classe(c["n_classe_affectee"] or c["n_classe"]))
        self._boutons_selon_selection()

    def _boutons_selon_selection(self):
        c = self.courant
        definir_actif(self.btn_test, bool(c) and c["etape"] == "A_TESTER")
        definir_actif(self.btn_affecter, bool(c) and c["etape"] == "A_AFFECTER")
        definir_actif(self.btn_avis, bool(c) and c["etape"] == "ADMIS")
        self.champ_note.config(state="normal" if c and c["etape"] == "A_TESTER" else "disabled")
        self.cb_classe.config(state="readonly" if c and c["etape"] == "A_AFFECTER" else "disabled")

    # --- actions -------------------------------------------------------------
    def enregistrer_test(self):
        c = self.courant
        if not c:
            return
        try:
            note = inscription.lire_note_test(self.var_note.get())
        except ERREURS as erreur:
            self._message(str(erreur), ROUGE)
            return
        seuil = inscription.seuil_reussite()
        conclusion = ("DOSSIER VALIDÉ : le candidat pourra être affecté à une classe." if note >= seuil else
                      "ÉCHEC : la candidature sera REFUSÉE (définitif).")
        if not messagebox.askyesno("Résultat du test",
                                   f"{c['nom_complet']} ({c['num_cand']})\nNote : {note:g} / 100  (seuil {seuil:g})\n\n"
                                   f"{conclusion}\n\nUn résultat enregistré ne se modifie plus. Confirmer ?", parent=self):
            return
        try:
            r = inscription.enregistrer_resultat_test(self.app.conn, self.app.session, c["n_cand"], self.var_note.get())
        except ERREURS as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.var_note.set("")
        self.actualiser(garder=c["n_cand"] if r["valide"] else None)
        if r["valide"]:
            self._message(f"{r['num_cand']} : test réussi ({r['note']:g} / 100). Dossier validé : choisissez la classe "
                          f"puis « Valider et affecter ».", VERT)
        else:
            self._message(f"{r['num_cand']} : test échoué ({r['note']:g} / 100). Candidature refusée.", ORANGE)

    def affecter(self):
        c = self.courant
        n_classe = self.classes.get(self.var_affectation.get())
        if not c:
            return
        if not n_classe:
            self._message("Choisissez la classe d'affectation.", ROUGE)
            return
        if not messagebox.askyesno("Affectation",
                                   f"Affecter {c['nom_complet']} ({c['num_cand']}) à la classe « {self.var_affectation.get()} » ?\n\n"
                                   f"Le candidat devient ÉLÈVE : un matricule lui est attribué et il est inscrit dans la classe "
                                   f"pour l'année {c['annee']}.", parent=self):
            return
        try:
            r = inscription.affecter_candidat(self.app.conn, self.app.session, c["n_cand"], n_classe)
        except ERREURS as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.actualiser(garder=c["n_cand"])
        self._message(f"{r['num_cand']} admis : c'est maintenant un élève de « {r['classe']} », matricule {r['matricule']}.", VERT)
        if messagebox.askyesno("Avis d'admission", f"Matricule attribué : {r['matricule']}.\nImprimer l'avis d'admission ?",
                               parent=self):
            self.imprimer_avis()

    def imprimer_avis(self):
        c = self.courant
        if not c or c["etape"] != "ADMIS":
            return
        try:
            ouvrir_fichier(inscription.preparer_avis_admission_pdf(self.app.conn, self.app.session, c["n_cand"]))
        except ERREURS as erreur:
            messagebox.showwarning("Impression impossible", str(erreur), parent=self)
        except OSError as erreur:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir l'avis : {erreur}", parent=self)


# ================================================================== MODULE
def onglets_autorises(conn, session) -> set:
    """Onglets utilisables par ce compte (droits relus dans la base)."""
    if not inscription.peut(conn, session, "LECTURE"):
        return set()
    ouverts = {"liste"}
    if inscription.peut(conn, session, "AJOUT"):
        ouverts.add("formulaire")
    if inscription.peut(conn, session, "MODIFICATION"):
        ouverts.add("validation")
    return ouverts


class ModuleInscription(tk.Frame):
    ONGLETS = (("formulaire", "1   Formulaire d'inscription"),
               ("liste", "2   Liste d'attente"),
               ("validation", "3   Validation et affectation"))
    CLASSES = {"formulaire": PanneauFormulaire, "liste": PanneauListe, "validation": PanneauValidation}

    def __init__(self, app, onglet=None):
        super().__init__(app, bg=BLANC)
        self.app = app
        self.autorises = onglets_autorises(app.conn, app.session)

        barre = barre_haute(self, "Inscription")
        actions_barre_module(barre, app)
        tk.Label(barre, text=f"{app.session.nom_complet}  •  {app.session.libelle_role}", font=police(10),
                 fg=BLEU_PALE, bg=NUIT).pack(side="right", padx=px(8))

        navigation = tk.Frame(self, bg=FOND_CLAIR)
        navigation.pack(fill="x")
        self.boutons = {}
        for i, (cle, texte) in enumerate(self.ONGLETS):
            navigation.grid_columnconfigure(i, weight=1, uniform="onglet")
            verrouille = cle not in self.autorises
            b = tk.Button(navigation, text=texte + ("   (réservé)" if verrouille else ""),
                          command=lambda c=cle: self.afficher_onglet(c), relief="flat", bd=0, highlightthickness=0,
                          font=police(11, gras=True), padx=px(12), pady=px(12), cursor="hand2", wraplength=px(300))
            b.grid(row=0, column=i, sticky="nsew")
            self.boutons[cle] = b
        tk.Frame(self, bg=BORDURE, height=1).pack(fill="x")

        self._adaptative = ZoneAdaptative(self)
        self._adaptative.pack(fill="both", expand=True)
        self.zone = self._adaptative.interieur
        self.panneaux = {cle: self.CLASSES[cle](self.zone, self) for cle, _ in self.ONGLETS if cle in self.autorises}
        self.courant = None
        premier = next((c for c, _ in self.ONGLETS if c in self.panneaux), None)
        if premier:
            self.afficher_onglet(onglet if onglet in self.panneaux else premier)
        else:
            tk.Label(self.zone, text="Votre compte n'a pas accès à ce module.\nDemandez à l'Administrateur de vous accorder "
                                     "le droit « Lecture » (Gestionnaire d'accès > Autorisations).",
                     font=police(13), fg=GRIS, bg=BLANC, justify="center").pack(pady=px(60))

    def afficher_onglet(self, cle):
        if cle not in self.panneaux:                      # onglet verrouillé : on explique pourquoi, sans bouger
            if cle == "formulaire":
                messagebox.showinfo("Formulaire d'inscription",
                                    "Votre compte n'a pas le droit « Ajout » sur ce module.\n"
                                    "Demandez à l'Administrateur de vous l'accorder (Gestionnaire d'accès > Autorisations).",
                                    parent=self)
            elif cle == "validation":
                messagebox.showinfo("Validation et affectation",
                                    "Votre compte n'a pas le droit « Modification » sur ce module.\n"
                                    "Demandez à l'Administrateur de vous l'accorder (Gestionnaire d'accès > Autorisations).",
                                    parent=self)
            return
        for panneau in self.panneaux.values():
            panneau.pack_forget()
        for nom, bouton in self.boutons.items():
            actif = nom == cle
            verrouille = nom not in self.panneaux
            bouton.config(bg=NUIT if actif else FOND_CLAIR,
                          fg=BLANC if actif else ("#8A96B3" if verrouille else NUIT),
                          activebackground=NUIT_CLAIR if actif else BORDURE,
                          activeforeground=BLANC if actif else NUIT)
        self.courant = self.panneaux[cle]
        self.courant.pack(fill="both", expand=True)
        if hasattr(self.courant, "au_affichage"):
            self.courant.au_affichage()

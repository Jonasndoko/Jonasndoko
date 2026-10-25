"""Module « Gestion du personnel » - troisième fonctionnalité : PRÉSENCE ET ABSENCE (écrans ; logique : presences.py).

6. Pointage du jour           : la liste de tous les agents pour un jour : présent, en retard, absent (un ou plusieurs agents à la fois).
7. Permissions et congés      : pour un agent : ses permissions et congés, une nouvelle autorisation, l'annulation d'une autorisation.
8. États récapitulatifs       : par période (semaine, mois, dates libres), pour tout le personnel, une fonction ou un service ;
                                consultation à l'écran et impression (PDF).
"""
import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, simpledialog, ttk

import affectations
import config
import personnel
import presences
from calendrier import SelecteurDate
from composants import Fenetre
from ecrans_paiement import ouvrir_fichier, creer_arbre, vider_arbre
from ecrans_personnel import ERREURS, _etiquette, _volet_agent
from saisie_date import lire_date_texte
from theme import (BLANC, FOND_CLAIR, GRIS, NUIT, ORANGE, ROUGE, VERT, carte, creer_bouton, creer_champ, definir_actif, police,
                   px)

TOUT = "Tout le personnel"
COULEURS = {"PRESENT": ("#E8F3EA", None), "RETARD": ("#FFF4DC", None), "ABSENT": ("#FDECEA", None),
            "PERMISSION": ("#E6EEFB", None), "CONGE": ("#EDE7FB", None), "NON_RENSEIGNE": (BLANC, "#8A96B3")}


def _aujourdhui() -> str:
    return date.today().strftime("%d/%m/%Y")


def _configurer_couleurs(arbre):
    for statut, (fond, texte) in COULEURS.items():
        options = {"background": fond}
        if texte:
            options["foreground"] = texte
        arbre.tag_configure(statut, **options)


# ================================================================== 6) POINTAGE DU JOUR
class PanneauPointage(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.var_jour, self.var_fonction = tk.StringVar(value=_aujourdhui()), tk.StringVar(value=TOUT)
        self.var_heure, self.var_motif = tk.StringVar(), tk.StringVar()
        self.fonctions, self.lignes = {}, {}

        bas = tk.Frame(self, bg=BLANC)
        bas.pack(side="bottom", fill="x", padx=px(24), pady=(px(4), px(12)))
        self.lbl_message = tk.Label(self, text="", font=police(11, gras=True), bg=BLANC, anchor="w", justify="left",
                                    wraplength=px(1000))
        self.lbl_message.pack(side="bottom", fill="x", padx=px(26))

        haut = carte(self, padx=px(16), pady=px(10))
        haut.pack(fill="x", padx=px(24), pady=(px(14), px(6)))
        ligne = tk.Frame(haut, bg=BLANC)
        ligne.pack(fill="x")
        tk.Label(ligne, text="Jour :", font=police(11, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
        creer_bouton(ligne, "◄", lambda: self._decaler(-1), style="secondaire", grand=False).pack(side="left", padx=(px(8), px(4)))
        SelecteurDate(ligne, self.var_jour).pack(side="left")
        creer_bouton(ligne, "►", lambda: self._decaler(1), style="secondaire", grand=False).pack(side="left", padx=(px(4), px(8)))
        creer_bouton(ligne, "Aujourd'hui", lambda: self.var_jour.set(_aujourdhui()), style="secondaire",
                     grand=False).pack(side="left")
        tk.Label(ligne, text="Fonction :", font=police(11, gras=True), fg=NUIT, bg=BLANC).pack(side="left", padx=(px(18), px(6)))
        self.cb_fonction = ttk.Combobox(ligne, textvariable=self.var_fonction, state="readonly", width=24, font=police(11))
        self.cb_fonction.pack(side="left")
        self.cb_fonction.bind("<<ComboboxSelected>>", lambda _e: self.actualiser())
        creer_bouton(ligne, "Jours non travaillés...", self.jours_non_travailles, style="secondaire",
                     grand=False).pack(side="right")
        self.var_jour.trace_add("write", lambda *_a: self._jour_modifie())

        self.lbl_info = tk.Label(self, text="", font=police(10, gras=True), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_info.pack(fill="x", padx=px(26), pady=(0, px(2)))
        cadre, self.arbre = creer_arbre(self, [
            ("matricule", "Matricule", 90, "center"), ("nom", "Nom complet", 260, "w"), ("fonction", "Fonction", 150, "w"),
            ("situation", "Situation", 110, "center"), ("heure", "Arrivée", 110, "center"), ("motif", "Motif / nature", 240, "w")],
            hauteur=9)
        self.arbre.configure(selectmode="extended")
        cadre.pack(fill="both", expand=True, padx=px(24))
        _configurer_couleurs(self.arbre)
        self.arbre.bind("<<TreeviewSelect>>", lambda _e: self._selection_changee())

        form = tk.Frame(bas, bg=BLANC)
        form.pack(fill="x")
        tk.Label(form, text="Heure d'arrivée :", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
        champ = creer_champ(form, self.var_heure, largeur=8)
        champ.pack(side="left", padx=(px(6), px(14)), ipady=px(3))
        tk.Label(form, text="Motif :", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
        creer_champ(form, self.var_motif, largeur=40).pack(side="left", padx=(px(6), 0), ipady=px(3), fill="x", expand=True)
        tk.Label(bas, text=f"Choisissez un ou plusieurs agents dans la liste (Ctrl ou Maj + clic), puis le bouton. "
                           f"« En retard » : écrivez l'heure d'arrivée (ouverture à {config.HEURE_DEBUT_SERVICE}, "
                           f"les minutes de retard se calculent seules).", font=police(9), fg=GRIS, bg=BLANC, anchor="w",
                 justify="left", wraplength=px(1000)).pack(fill="x", pady=(px(4), px(4)))
        boutons = tk.Frame(bas, bg=BLANC)
        boutons.pack(fill="x")
        self.btn_present = creer_bouton(boutons, "PRÉSENT", lambda: self.pointer("PRESENT"), grand=False)
        self.btn_present.pack(side="left", padx=(0, px(6)))
        self.btn_retard = creer_bouton(boutons, "EN RETARD", lambda: self.pointer("RETARD"), grand=False)
        self.btn_retard.pack(side="left", padx=(0, px(6)))
        self.btn_absent = creer_bouton(boutons, "ABSENT", lambda: self.pointer("ABSENT"), grand=False)
        self.btn_absent.pack(side="left", padx=(0, px(14)))
        self.btn_tous = creer_bouton(boutons, "TOUS PRÉSENTS (non renseignés)", self.tous_presents, style="secondaire", grand=False)
        self.btn_tous.pack(side="left", padx=(0, px(6)))
        self.btn_effacer = creer_bouton(boutons, "EFFACER LE POINTAGE", self.effacer, style="danger", grand=False)
        self.btn_effacer.pack(side="left")
        self._activer()

    # ---------------------------------------------------------------- affichage
    def au_affichage(self):
        try:
            self.fonctions = {f["libelle"]: f["id"] for f in affectations.liste_referentiel(
                self.app.conn, self.app.session, "FONCTION", inclure_inactifs=False)}
        except ERREURS:
            self.fonctions = {}
        self.cb_fonction.config(values=[TOUT] + list(self.fonctions))
        if self.var_fonction.get() not in ([TOUT] + list(self.fonctions)):
            self.var_fonction.set(TOUT)
        self.actualiser()

    def message(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    def _decaler(self, n):
        jour = lire_date_texte(self.var_jour.get()) or date.today()
        self.var_jour.set((jour + timedelta(days=n)).strftime("%d/%m/%Y"))

    def _jour_modifie(self):
        if lire_date_texte(self.var_jour.get()) is not None and len(self.var_jour.get().strip()) == 10:
            self.actualiser()

    def _activer(self):
        conn, s = self.app.conn, self.app.session
        for bouton, droit in ((self.btn_present, "AJOUT"), (self.btn_retard, "AJOUT"), (self.btn_absent, "AJOUT"),
                              (self.btn_tous, "AJOUT"), (self.btn_effacer, "SUPPRESSION")):
            definir_actif(bouton, personnel.peut(conn, s, droit))

    def actualiser(self, garder=None):
        garder = garder if garder is not None else set(self.arbre.selection())
        vider_arbre(self.arbre)
        self.lignes = {}
        try:
            f = presences.feuille_du_jour(self.app.conn, self.app.session, self.var_jour.get(),
                                          self.fonctions.get(self.var_fonction.get()))
        except ERREURS as erreur:
            self.lbl_info.config(text=str(erreur), fg=ROUGE)
            return
        for l in f["lignes"]:
            self.lignes[l["matricule"]] = l
            arrivee = ""
            if l["heure"]:
                arrivee = l["heure"] + (f"  (+{l['minutes']} min)" if l["statut"] == "RETARD" else "")
            self.arbre.insert("", "end", iid=l["matricule"], tags=(l["statut"],),
                              values=(l["matricule"], l["nom_complet"], l["fonction"], l["libelle"], arrivee, l["motif"]))
        for m in garder:
            if self.arbre.exists(m):
                self.arbre.selection_add(m)
        r = f["resume"]
        if f["travaille"]:
            self.lbl_info.config(text=f"{f['jour']}  -  {r['PRESENT']} présent(s), {r['RETARD']} en retard, {r['ABSENT']} absent(s), "
                                      f"{r['PERMISSION']} en permission, {r['CONGE']} en congé, {r['NON_RENSEIGNE']} non renseigné(s)",
                                 fg=GRIS)
        else:
            self.lbl_info.config(text=f"{f['jour']}  -  {f['raison']} : aucun pointage possible ce jour-là.", fg=ORANGE)
        if not f["lignes"]:
            self.message("Aucun agent à afficher pour ce jour.", GRIS)
        elif self.lbl_message.cget("text") == "Aucun agent à afficher pour ce jour.":
            self.message("")

    def _selection_changee(self):
        sel = self.arbre.selection()
        if len(sel) == 1:
            l = self.lignes.get(sel[0])
            if l and not l["verrouille"]:
                self.var_heure.set(l["heure"])
                self.var_motif.set(l["motif"] if l["statut"] != "NON_RENSEIGNE" else "")

    # ---------------------------------------------------------------- actions
    def _choisis(self):
        return list(self.arbre.selection())

    def _rapport(self, r, libelle):
        refus = r["refuses"]
        if r["faits"] and not refus:
            self.message(f"{r['faits']} agent(s) : {libelle}.", VERT)
        elif r["faits"]:
            self.message(f"{r['faits']} agent(s) : {libelle}. Refusé(s) : " + " ; ".join(m for _a, m in refus[:3])
                         + (" ..." if len(refus) > 3 else ""), ORANGE)
        else:
            self.message(" ; ".join(m for _a, m in refus[:3]) or "Rien à enregistrer.", ROUGE)
        self.actualiser()

    def pointer(self, statut):
        cibles = self._choisis()
        if not cibles:
            self.message("Choisissez d'abord un ou plusieurs agents dans la liste.")
            return
        try:
            r = presences.pointer_plusieurs(self.app.conn, self.app.session, cibles, self.var_jour.get(), statut,
                                            self.var_heure.get() if statut != "ABSENT" else "", self.var_motif.get())
        except ERREURS as erreur:
            self.message(str(erreur))
            return
        self._rapport(r, {"PRESENT": "présent", "RETARD": "en retard", "ABSENT": "absent"}[statut])

    def tous_presents(self):
        try:
            r = presences.marquer_presents(self.app.conn, self.app.session, self.var_jour.get(),
                                           self.fonctions.get(self.var_fonction.get()))
        except ERREURS as erreur:
            self.message(str(erreur))
            return
        if not r["faits"] and not r["refuses"]:
            self.message("Aucun agent « non renseigné » ce jour-là.", GRIS)
            return
        self._rapport(r, "présent")

    def effacer(self):
        cibles = self._choisis()
        if not cibles:
            self.message("Choisissez d'abord un ou plusieurs agents dans la liste.")
            return
        if not messagebox.askyesno("Effacer le pointage", f"Effacer le pointage de {len(cibles)} agent(s) pour le "
                                   f"{self.var_jour.get()} ? Ils redeviendront « non renseignés ».", parent=self):
            return
        faits, erreurs = 0, []
        for m in cibles:
            try:
                presences.supprimer_pointage(self.app.conn, self.app.session, m, self.var_jour.get())
                faits += 1
            except ERREURS as erreur:
                erreurs.append(str(erreur))
        self.message(f"{faits} pointage(s) effacé(s)." if faits else (erreurs[0] if erreurs else ""), VERT if faits else ROUGE)
        self.actualiser()

    def jours_non_travailles(self):
        FenetreJoursFermes(self, self.app)
        self.actualiser()


# ---------------------------------------------------------------- fenêtre des jours non travaillés
class FenetreJoursFermes(Fenetre):
    def __init__(self, parent, app):
        super().__init__(parent, "Jours non travaillés", largeur=560, hauteur=520)
        self.app = app
        self.var_annee = tk.StringVar(value=str(date.today().year))
        self.var_date, self.var_libelle = tk.StringVar(), tk.StringVar()
        c = self.corps
        tk.Label(c, text="Fêtes et vacances : ces jours ne comptent pas comme jours de travail.\nLe week-end est déjà exclu.",
                 font=police(10), fg=GRIS, bg=BLANC, justify="left", anchor="w").pack(fill="x")
        haut = tk.Frame(c, bg=BLANC)
        haut.pack(fill="x", pady=(px(8), px(4)))
        tk.Label(haut, text="Année :", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
        cb = ttk.Combobox(haut, textvariable=self.var_annee, state="readonly", width=7, font=police(11),
                          values=[str(a) for a in range(date.today().year - 3, date.today().year + 3)])
        cb.pack(side="left", padx=px(6))
        cb.bind("<<ComboboxSelected>>", lambda _e: self.actualiser())
        cadre, self.arbre = creer_arbre(c, [("date", "Date", 100, "center"), ("libelle", "Raison", 340, "w")], hauteur=8)
        cadre.pack(fill="both", expand=True)
        self.lbl_message = tk.Label(c, text="", font=police(10, gras=True), bg=BLANC, anchor="w", justify="left", wraplength=px(480))
        self.lbl_message.pack(side="bottom", fill="x")
        bas = tk.Frame(c, bg=BLANC)
        bas.pack(side="bottom", fill="x", pady=(px(6), px(2)))
        _etiquette(bas, "Date", obligatoire=False)
        SelecteurDate(bas, self.var_date).pack(fill="x", pady=(px(2), px(4)))
        _etiquette(bas, "Raison (ex. Fête de l'indépendance)", obligatoire=False)
        creer_champ(bas, self.var_libelle).pack(fill="x", ipady=px(3), pady=(px(2), px(6)))
        ligne = tk.Frame(bas, bg=BLANC)
        ligne.pack(fill="x")
        self.btn_ajouter = creer_bouton(ligne, "AJOUTER", self.ajouter, grand=False)
        self.btn_ajouter.pack(side="left", padx=(0, px(6)))
        self.btn_retirer = creer_bouton(ligne, "RETIRER LE JOUR CHOISI", self.retirer, style="danger", grand=False)
        self.btn_retirer.pack(side="left", padx=(0, px(6)))
        creer_bouton(ligne, "FERMER", self.destroy, style="secondaire", grand=False).pack(side="right")
        definir_actif(self.btn_ajouter, personnel.peut(app.conn, app.session, "AJOUT"))
        definir_actif(self.btn_retirer, personnel.peut(app.conn, app.session, "SUPPRESSION"))
        self.actualiser()
        self.attendre()

    def message(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    def actualiser(self):
        vider_arbre(self.arbre)
        try:
            for j in presences.liste_jours_fermes(self.app.conn, self.app.session, self.var_annee.get()):
                self.arbre.insert("", "end", iid=j["iso"], values=(j["date"], j["libelle"]))
        except ERREURS as erreur:
            self.message(str(erreur))

    def ajouter(self):
        try:
            presences.ajouter_jour_ferme(self.app.conn, self.app.session, self.var_date.get(), self.var_libelle.get())
        except ERREURS as erreur:
            self.message(str(erreur))
            return
        self.var_date.set("")
        self.var_libelle.set("")
        self.message("Jour ajouté.", VERT)
        self.actualiser()

    def retirer(self):
        sel = self.arbre.selection()
        if not sel:
            self.message("Choisissez un jour dans la liste.")
            return
        try:
            presences.supprimer_jour_ferme(self.app.conn, self.app.session, date.fromisoformat(sel[0]).strftime("%d/%m/%Y"))
        except ERREURS as erreur:
            self.message(str(erreur))
            return
        self.message("Jour retiré.", VERT)
        self.actualiser()


# ================================================================== 7) PERMISSIONS ET CONGÉS
class PanneauAutorisations(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.matricule, self.liste = None, {}
        self.var_type, self.var_nature = tk.StringVar(value="PERMISSION"), tk.StringVar()
        self.var_debut, self.var_fin, self.var_motif = tk.StringVar(value=_aujourdhui()), tk.StringVar(value=_aujourdhui()), tk.StringVar()
        self.selecteur, droite = _volet_agent(self, module, self.choisir)
        self.lbl_entete = tk.Label(droite, text="", font=police(13, gras=True, titre=True), fg=NUIT, bg=BLANC, anchor="w")
        self.lbl_entete.pack(fill="x")
        self.lbl_total = tk.Label(droite, text="", font=police(10, gras=True), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_total.pack(fill="x")

        self.lbl_message = tk.Label(droite, text="", font=police(11, gras=True), bg=BLANC, anchor="w", justify="left", wraplength=px(700))
        self.lbl_message.pack(side="bottom", fill="x", pady=(px(4), 0))
        boutons = tk.Frame(droite, bg=BLANC)
        boutons.pack(side="bottom", fill="x", pady=(px(8), 0))
        self.btn_accorder = creer_bouton(boutons, "ENREGISTRER L'AUTORISATION", self.accorder, grand=False)
        self.btn_accorder.pack(side="left", padx=(0, px(14)))
        self.btn_annuler = creer_bouton(boutons, "ANNULER L'AUTORISATION CHOISIE", self.annuler, style="danger", grand=False)
        self.btn_annuler.pack(side="left")

        cadre, self.arbre = creer_arbre(droite, [
            ("type", "Type", 80, "center"), ("nature", "Nature", 150, "w"), ("debut", "Du", 85, "center"), ("fin", "Au", 85, "center"),
            ("jours", "Jours", 50, "center"), ("statut", "Situation", 80, "center"), ("motif", "Motif", 150, "w")], hauteur=6)
        cadre.pack(fill="both", expand=True, pady=(px(6), px(6)))
        self.arbre.tag_configure("ANNULE", foreground="#8A96B3")
        self.arbre.bind("<<TreeviewSelect>>", lambda _e: self._activer())

        form = carte(droite, padx=px(14), pady=px(10))
        form.pack(fill="x")
        tk.Label(form, text="Nouvelle permission ou nouveau congé", font=police(12, gras=True, titre=True), fg=NUIT, bg=BLANC,
                 anchor="w").pack(fill="x")
        tk.Label(form, text="Les jours de la période ne comptent pas comme absences. Les absences déjà marquées sur ces jours sont régularisées.",
                 font=police(9), fg=GRIS, bg=BLANC, anchor="w", justify="left", wraplength=px(640)).pack(fill="x", pady=(0, px(6)))
        grille = tk.Frame(form, bg=BLANC)
        grille.pack(fill="x")
        grille.grid_columnconfigure((0, 1), weight=1, uniform="g")
        g1, g2 = tk.Frame(grille, bg=BLANC), tk.Frame(grille, bg=BLANC)
        g1.grid(row=0, column=0, sticky="new", padx=(0, px(10)))
        g2.grid(row=0, column=1, sticky="new", padx=(px(10), 0))
        _etiquette(g1, "Type")
        ligne = tk.Frame(g1, bg=BLANC)
        ligne.pack(fill="x", pady=(px(2), px(6)))
        for valeur, texte in presences.TYPES_AUTORISATION.items():
            tk.Radiobutton(ligne, text=texte, value=valeur, variable=self.var_type, command=self._type_change, font=police(11),
                           bg=BLANC, fg=NUIT, activebackground=BLANC, selectcolor=BLANC, highlightthickness=0
                           ).pack(side="left", padx=(0, px(12)))
        _etiquette(g1, "Nature (choisir ou écrire)", obligatoire=False)
        self.cb_nature = ttk.Combobox(g1, textvariable=self.var_nature, font=police(11))
        self.cb_nature.pack(fill="x", ipady=px(2), pady=(px(2), px(6)))
        _etiquette(g1, "Motif (si nécessaire)", obligatoire=False)
        creer_champ(g1, self.var_motif).pack(fill="x", ipady=px(3), pady=(px(2), px(6)))
        _etiquette(g2, "Du (jj/mm/aaaa)")
        SelecteurDate(g2, self.var_debut).pack(fill="x", pady=(px(2), px(6)))
        _etiquette(g2, "Au (jj/mm/aaaa, inclus)")
        SelecteurDate(g2, self.var_fin).pack(fill="x", pady=(px(2), px(6)))
        self._type_change()
        self._afficher_agent(None)

    def au_affichage(self):
        self.selecteur.actualiser(self.module.matricule_courant, forcer=True)

    def message(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    def _type_change(self):
        self.cb_nature.config(values=presences.NATURES[self.var_type.get()])
        self.var_nature.set("")

    def choisir(self, matricule):
        self.module.matricule_courant = matricule
        self.matricule = matricule
        self.message("")
        self.recharger()

    def _afficher_agent(self, agent):
        self.lbl_entete.config(text=f"{agent['nom_complet']}  ({agent['matricule']})" if agent
                               else "Choisissez un agent dans la liste")
        definir_actif(self.btn_accorder, bool(agent) and personnel.peut(self.app.conn, self.app.session, "AJOUT"))
        self._activer()

    def _activer(self):
        sel = self.arbre.selection()
        ok = bool(sel) and self.liste.get(sel[0], {}).get("statut") == "ACCORDE" and personnel.peut(
            self.app.conn, self.app.session, "MODIFICATION")
        definir_actif(self.btn_annuler, ok)

    def recharger(self):
        vider_arbre(self.arbre)
        self.liste = {}
        if not self.matricule:
            self.lbl_total.config(text="")
            self._afficher_agent(None)
            return
        try:
            agent = personnel.charger_agent(self.app.conn, self.app.session, self.matricule)
            d = presences.liste_autorisations(self.app.conn, self.app.session, self.matricule)
        except ERREURS as erreur:
            self.message(str(erreur))
            return
        for a in d["autorisations"]:
            iid = str(a["id"])
            self.liste[iid] = a
            self.arbre.insert("", "end", iid=iid, tags=(a["statut"],), values=(
                a["libelle_type"], a["nature"], a["debut"], a["fin"], a["jours"], a["libelle_statut"],
                a["motif"] if a["statut"] == "ACCORDE" else f"Annulée : {a['motif_annulation']}"))
        j = d["jours_annee"]
        self.lbl_total.config(text=f"En {d['annee']} : {j['PERMISSION']} jour(s) de permission, {j['CONGE']} jour(s) de congé")
        self._afficher_agent(agent)

    def accorder(self):
        if not self.matricule:
            return
        try:
            r = presences.accorder_autorisation(self.app.conn, self.app.session, self.matricule, self.var_type.get(),
                                                self.var_nature.get(), self.var_debut.get(), self.var_fin.get(), self.var_motif.get())
        except ERREURS as erreur:
            self.message(str(erreur))
            return
        texte = f"Autorisation enregistrée : {r['jours']} jour(s) de travail."
        if r["regularisees"]:
            texte += f" {r['regularisees']} absence(s) régularisée(s)."
        self.var_nature.set("")
        self.var_motif.set("")
        self.recharger()
        self.message(texte, VERT)

    def annuler(self):
        sel = self.arbre.selection()
        if not sel:
            return
        a = self.liste[sel[0]]
        motif = simpledialog.askstring("Annuler l'autorisation", f"{a['libelle_type']} du {a['debut']} au {a['fin']}.\n\n"
                                       f"Motif de l'annulation :", parent=self)
        if motif is None:
            return
        try:
            presences.annuler_autorisation(self.app.conn, self.app.session, a["id"], motif)
        except ERREURS as erreur:
            self.message(str(erreur))
            return
        self.recharger()
        self.message("Autorisation annulée : ses jours redeviennent « non renseignés ».", VERT)


# ================================================================== 8) ÉTATS RÉCAPITULATIFS
class PanneauEtats(tk.Frame):
    PORTEES = {"TOUT": "Tout le personnel", "FONCTION": "Par fonction", "SERVICE": "Par service"}

    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        debut, fin = presences.periode_du_mois(date.today())
        self.var_debut, self.var_fin = tk.StringVar(value=debut.strftime("%d/%m/%Y")), tk.StringVar(value=fin.strftime("%d/%m/%Y"))
        self.var_portee, self.var_filtre, self.var_detail = tk.StringVar(value="TOUT"), tk.StringVar(), tk.IntVar(value=1)
        self.choix = {}

        bas = tk.Frame(self, bg=BLANC)
        bas.pack(side="bottom", fill="x", padx=px(24), pady=(px(6), px(12)))
        self.lbl_message = tk.Label(self, text="", font=police(11, gras=True), bg=BLANC, anchor="w", justify="left", wraplength=px(1000))
        self.lbl_message.pack(side="bottom", fill="x", padx=px(26))
        creer_bouton(bas, "CONSULTER", self.consulter, grand=False).pack(side="left", padx=(0, px(8)))
        creer_bouton(bas, "IMPRIMER L'ÉTAT", self.imprimer, style="secondaire", grand=False).pack(side="left", padx=(0, px(12)))
        tk.Checkbutton(bas, text="Avec le détail des retards, absences et congés", variable=self.var_detail, font=police(10), bg=BLANC,
                       fg=NUIT, activebackground=BLANC, selectcolor=BLANC, highlightthickness=0).pack(side="left")

        haut = carte(self, padx=px(16), pady=px(10))
        haut.pack(fill="x", padx=px(24), pady=(px(14), px(6)))
        l1 = tk.Frame(haut, bg=BLANC)
        l1.pack(fill="x")
        tk.Label(l1, text="Période du", font=police(11, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
        SelecteurDate(l1, self.var_debut).pack(side="left", padx=(px(8), px(8)))
        tk.Label(l1, text="au", font=police(11, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
        SelecteurDate(l1, self.var_fin).pack(side="left", padx=(px(8), px(14)))
        for texte, fonction in (("Cette semaine", presences.periode_de_la_semaine), ("Ce mois", presences.periode_du_mois),
                                ("Mois précédent", presences.periode_mois_precedent)):
            creer_bouton(l1, texte, lambda f=fonction: self._periode(f), style="secondaire", grand=False).pack(side="left", padx=(0, px(6)))
        l2 = tk.Frame(haut, bg=BLANC)
        l2.pack(fill="x", pady=(px(8), 0))
        for valeur, texte in self.PORTEES.items():
            tk.Radiobutton(l2, text=texte, value=valeur, variable=self.var_portee, command=self._portee_change, font=police(11),
                           bg=BLANC, fg=NUIT, activebackground=BLANC, selectcolor=BLANC, highlightthickness=0
                           ).pack(side="left", padx=(0, px(12)))
        self.cb_filtre = ttk.Combobox(l2, textvariable=self.var_filtre, state="readonly", width=30, font=police(11))
        self.cb_filtre.pack(side="left")

        self.lbl_info = tk.Label(self, text="", font=police(10, gras=True), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_info.pack(fill="x", padx=px(26), pady=(0, px(2)))
        cadre, self.arbre = creer_arbre(self, [
            ("nom", "Nom complet", 230, "w"), ("jours", "Jours", 50, "center"), ("presents", "Présents", 70, "center"),
            ("retards", "Retards", 65, "center"), ("minutes", "Min.", 55, "center"), ("absents", "Absences", 75, "center"),
            ("perm", "Perm.", 55, "center"), ("conges", "Congés", 60, "center"), ("nr", "Non renseignés", 100, "center"),
            ("taux", "Taux", 60, "center")], hauteur=7)
        cadre.pack(fill="both", expand=True, padx=px(24))
        self.arbre.tag_configure("total", background=FOND_CLAIR, font=police(10, gras=True))
        self.arbre.tag_configure("alerte", foreground=ROUGE)
        tk.Label(self, text="Retards et absences de la période", font=police(11, gras=True), fg=NUIT, bg=BLANC, anchor="w"
                 ).pack(fill="x", padx=px(26), pady=(px(8), 0))
        cadre2, self.detail = creer_arbre(self, [
            ("date", "Date", 85, "center"), ("nom", "Nom complet", 230, "w"), ("situation", "Situation", 90, "center"),
            ("arrivee", "Arrivée", 120, "center"), ("motif", "Motif", 320, "w")], hauteur=5)
        cadre2.pack(fill="both", expand=True, padx=px(24))
        _configurer_couleurs(self.detail)

    def au_affichage(self):
        self._portee_change()

    def message(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    def _periode(self, fonction):
        debut, fin = fonction(date.today())
        self.var_debut.set(debut.strftime("%d/%m/%Y"))
        self.var_fin.set(fin.strftime("%d/%m/%Y"))

    def _portee_change(self):
        portee = self.var_portee.get()
        if portee == "TOUT":
            self.choix = {}
            self.cb_filtre.config(values=[], state="disabled")
            self.var_filtre.set("")
            return
        try:
            liste = affectations.liste_referentiel(self.app.conn, self.app.session, portee)
        except ERREURS as erreur:
            self.message(str(erreur))
            return
        self.choix = {e["libelle"]: e["id"] for e in liste}
        self.cb_filtre.config(values=list(self.choix), state="readonly")
        self.var_filtre.set(next(iter(self.choix), ""))

    def _parametres(self):
        portee = self.var_portee.get()
        if portee == "TOUT":
            return None, None
        return portee, self.choix.get(self.var_filtre.get())

    def consulter(self):
        mode, id_filtre = self._parametres()
        if mode and id_filtre is None:
            self.message("Choisissez une fonction ou un service dans la liste.")
            return
        try:
            e = presences.etat_recapitulatif(self.app.conn, self.app.session, self.var_debut.get(), self.var_fin.get(), mode, id_filtre)
        except ERREURS as erreur:
            self.message(str(erreur))
            return
        self.message("")
        vider_arbre(self.arbre)
        vider_arbre(self.detail)
        for l in e["lignes"]:
            self.arbre.insert("", "end", tags=("alerte",) if l["absents"] else (), values=(
                l["nom_complet"], l["jours"], l["presents"], l["retards"], l["minutes"], l["absents"], l["permissions"], l["conges"],
                l["non_renseignes"], "-" if l["taux"] is None else f"{l['taux']} %"))
        t = e["totaux"]
        if e["lignes"]:
            self.arbre.insert("", "end", tags=("total",), values=(
                "TOTAL", t["jours"], t["presents"], t["retards"], t["minutes"], t["absents"], t["permissions"], t["conges"],
                t["non_renseignes"], "-" if t["taux"] is None else f"{t['taux']} %"))
        for x in e["detail"]:
            self.detail.insert("", "end", tags=(x["statut"],), values=(
                x["jour"], x["nom_complet"], x["libelle"], f"{x['heure']} (+{x['minutes']} min)" if x["statut"] == "RETARD" else "-",
                x["motif"]))
        suite = "  -  la fin de la période n'est pas encore arrivée : seuls les jours écoulés comptent" if e["a_venir"] else ""
        self.lbl_info.config(text=f"Du {e['debut']} au {e['fin']}  -  {e['portee']}  -  {e['jours_travail']} jour(s) de travail écoulé(s), "
                                  f"{len(e['lignes'])} agent(s){suite}")

    def imprimer(self):
        mode, id_filtre = self._parametres()
        if mode and id_filtre is None:
            self.message("Choisissez une fonction ou un service dans la liste.")
            return
        try:
            ouvrir_fichier(presences.preparer_etat_pdf(self.app.conn, self.app.session, self.var_debut.get(), self.var_fin.get(),
                                                       mode, id_filtre, avec_detail=bool(self.var_detail.get())))
        except ERREURS as erreur:
            self.message(str(erreur))
        except OSError as erreur:
            self.message(f"L'état est prêt mais n'a pas pu s'ouvrir : {erreur}")

"""Module « Gestion du personnel » - deuxième fonctionnalité : FONCTIONS ET AFFECTATIONS (écrans ; logique : affectations.py).

3. Fonctions et services      : déterminer la liste des fonctions et des services de l'école (ajouter, renommer, désactiver, supprimer).
4. Affectations et historique : un seul écran pour un agent : sa situation actuelle, l'historique de ses changements de fonction,
                                une nouvelle affectation (fonction, service, responsabilité, dates), la fin ou la correction
                                d'une affectation.
5. Liste du personnel          : par fonction ou par service, à la date choisie ; consultation à l'écran et impression (PDF).
"""
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

import affectations
import personnel
from calendrier import SelecteurDate
from composants import Fenetre
from ecrans_paiement import ZoneDefilante, creer_arbre, ouvrir_fichier, vider_arbre
from ecrans_personnel import ERREURS, SelecteurAgent, _etiquette, _volet_agent
from theme import (BLANC, FOND_CLAIR, GRIS, NUIT, ORANGE, ROUGE, VERT, carte, creer_bouton, creer_champ, definir_actif,
                   police, px)

AUCUN = "(Aucun)"


def _aujourdhui() -> str:
    return date.today().strftime("%d/%m/%Y")


# ================================================================== 3) FONCTIONS ET SERVICES
class ListeReferentiel(tk.Frame):
    """Une liste déterminée par l'école (fonctions ou services) avec ses boutons."""

    def __init__(self, parent, panneau, genre, titre, aide):
        super().__init__(parent, bg=BLANC)
        self.panneau, self.app, self.genre = panneau, panneau.app, genre
        self.elements = {}
        self.var_nom = tk.StringVar()
        tk.Label(self, text=titre, font=police(13, gras=True, titre=True), fg=NUIT, bg=BLANC, anchor="w").pack(fill="x")
        tk.Label(self, text=aide, font=police(9), fg=GRIS, bg=BLANC, anchor="w", justify="left", wraplength=px(420)).pack(fill="x")
        cadre, self.arbre = creer_arbre(self, [("nom", "Nom", 230, "w"), ("agents", "Agents en service", 110, "center"),
                                               ("etat", "État", 80, "center")], hauteur=6)
        cadre.pack(fill="both", expand=True, pady=(px(6), px(6)))
        self.arbre.tag_configure("inactif", foreground="#8A96B3")
        self.arbre.bind("<<TreeviewSelect>>", lambda _e: self._selection_changee())
        _etiquette(self, "Nom (à écrire pour ajouter, ou pour renommer l'élément choisi)", obligatoire=False)
        champ = creer_champ(self, self.var_nom)
        champ.pack(fill="x", ipady=px(3), pady=(px(2), px(6)))
        champ.bind("<Return>", lambda _e: self.ajouter())
        ligne = tk.Frame(self, bg=BLANC)
        ligne.pack(fill="x")
        self.btn_ajouter = creer_bouton(ligne, "AJOUTER", self.ajouter, grand=False)
        self.btn_ajouter.pack(side="left", padx=(0, px(6)))
        self.btn_renommer = creer_bouton(ligne, "RENOMMER", self.renommer, style="secondaire", grand=False)
        self.btn_renommer.pack(side="left", padx=(0, px(6)))
        self.btn_activite = creer_bouton(ligne, "Désactiver", self.changer_activite, style="secondaire", grand=False)
        self.btn_activite.pack(side="left", padx=(0, px(6)))
        self.btn_supprimer = creer_bouton(ligne, "SUPPRIMER", self.supprimer, style="danger", grand=False)
        self.btn_supprimer.pack(side="left")

    def choisi(self):
        sel = self.arbre.selection()
        return self.elements.get(sel[0]) if sel else None

    def actualiser(self, garder=None):
        vider_arbre(self.arbre)
        self.elements = {}
        try:
            liste = affectations.liste_referentiel(self.app.conn, self.app.session, self.genre)
        except ERREURS as erreur:
            self.panneau.message(str(erreur), ROUGE)
            return
        for e in liste:
            iid = str(e["id"])
            self.elements[iid] = e
            self.arbre.insert("", "end", iid=iid, tags=() if e["actif"] else ("inactif",),
                              values=(e["libelle"], e["nb_agents"], "Actif" if e["actif"] else "Désactivé"))
        if garder is not None and self.arbre.exists(str(garder)):
            self.arbre.selection_set(str(garder))
        self._selection_changee()

    def _selection_changee(self):
        e = self.choisi()
        if e:
            self.var_nom.set(e["libelle"])
        conn, session = self.app.conn, self.app.session
        definir_actif(self.btn_ajouter, personnel.peut(conn, session, "AJOUT"))
        definir_actif(self.btn_renommer, bool(e) and personnel.peut(conn, session, "MODIFICATION"))
        definir_actif(self.btn_activite, bool(e) and personnel.peut(conn, session, "MODIFICATION"))
        definir_actif(self.btn_supprimer, bool(e) and personnel.peut(conn, session, "SUPPRESSION"))
        self.btn_activite.config(text="Réactiver" if e and not e["actif"] else "Désactiver")

    def _faire(self, action, succes, garder_id=True):
        e = self.choisi()
        try:
            resultat = action(e)
        except ERREURS as erreur:
            self.panneau.message(str(erreur), ROUGE)
            return
        self.panneau.message(succes(e), VERT)
        self.actualiser(garder=(e["id"] if e and garder_id else resultat if isinstance(resultat, int) else None))

    def ajouter(self):
        nom = self.var_nom.get()
        try:
            id_ = affectations.ajouter_referentiel(self.app.conn, self.app.session, self.genre, nom)
        except ERREURS as erreur:
            self.panneau.message(str(erreur), ROUGE)
            return
        self.var_nom.set("")
        self.panneau.message(f"« {nom.strip()} » ajouté{'e' if self.genre == 'FONCTION' else ''} à la liste.", VERT)
        self.actualiser(garder=id_)

    def renommer(self):
        if self.choisi():
            self._faire(lambda e: affectations.renommer_referentiel(self.app.conn, self.app.session, self.genre, e["id"],
                                                                    self.var_nom.get()),
                        lambda e: f"Renommé{'e' if self.genre == 'FONCTION' else ''} : « {self.var_nom.get().strip()} ».")

    def changer_activite(self):
        e = self.choisi()
        if not e:
            return
        if e["actif"] and not messagebox.askyesno(
                "Désactiver", f"« {e['libelle']} » ne sera plus proposé{'e' if self.genre == 'FONCTION' else ''} pour de nouvelles "
                              f"affectations.\n\nL'historique est conservé ; vous pourrez le réactiver.", parent=self):
            return
        self._faire(lambda e: affectations.changer_activite_referentiel(self.app.conn, self.app.session, self.genre, e["id"],
                                                                        not e["actif"]),
                    lambda e: "Réactivé." if not e["actif"] else "Désactivé : l'historique est conservé.")

    def supprimer(self):
        e = self.choisi()
        if not e:
            return
        if not messagebox.askyesno("Supprimer", f"Supprimer « {e['libelle']} » de la liste ?\n\n"
                                                "Possible seulement s'il n'a jamais été utilisé.", icon="warning", parent=self):
            return
        self._faire(lambda e: affectations.supprimer_referentiel(self.app.conn, self.app.session, self.genre, e["id"]),
                    lambda e: "Supprimé de la liste.", garder_id=False)
        self.var_nom.set("")


class PanneauFonctions(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.lbl_message = tk.Label(self, text="", font=police(11, gras=True), bg=BLANC, anchor="w", justify="left", wraplength=px(1000))
        self.lbl_message.pack(side="bottom", fill="x", padx=px(26), pady=(px(2), px(12)))
        zone = tk.Frame(self, bg=BLANC)
        zone.pack(fill="both", expand=True, padx=px(24), pady=px(14))
        zone.grid_columnconfigure((0, 1), weight=1, uniform="liste")
        zone.grid_rowconfigure(0, weight=1)
        self.fonctions = ListeReferentiel(zone, self, "FONCTION", "Fonctions de l'école",
                                          "Ex. Enseignant, Secrétaire, Préfet des études. Une fonction déjà utilisée ne se supprime pas : "
                                          "on la désactive.")
        self.fonctions.grid(row=0, column=0, sticky="nsew", padx=(0, px(14)))
        self.services = ListeReferentiel(zone, self, "SERVICE", "Services de l'école",
                                         "Ex. Administration, Discipline, Enseignement, Finances. Un service sert à regrouper les agents "
                                         "(liste du personnel par service).")
        self.services.grid(row=0, column=1, sticky="nsew", padx=(px(14), 0))

    def message(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    def au_affichage(self):
        self.message("")
        self.fonctions.actualiser()
        self.services.actualiser()


# ================================================================== 4) AFFECTATIONS ET HISTORIQUE
class DialogueAffectation(Fenetre):
    """Terminer (date de fin + motif) ou corriger (tous les champs) une affectation existante."""

    def __init__(self, parent, app, aff, terminer):
        super().__init__(parent, "Terminer l'affectation" if terminer else "Corriger l'affectation",
                         largeur=520, hauteur=330 if terminer else 640)
        self.app, self.aff, self.terminer = app, aff, terminer
        c = self.corps
        tk.Label(c, text=f"{aff['fonction']}  -  du {aff['date_debut']}" + (f" au {aff['date_fin']}" if aff["date_fin"] else ""),
                 font=police(11, gras=True), fg=NUIT, bg=BLANC, anchor="w", wraplength=px(440), justify="left").pack(fill="x", pady=(0, px(8)))
        self.v_fin, self.v_motif = self.variable(aff["date_fin"] or ""), self.variable(aff["motif"])
        self.v_debut, self.v_resp = self.variable(aff["date_debut"]), self.variable(aff["responsabilite"])
        self.v_fonction, self.v_service = self.variable(aff["fonction"]), self.variable(aff["service"] or AUCUN)
        self.fonctions = {f["libelle"]: f["id"] for f in affectations.liste_referentiel(app.conn, app.session, "FONCTION",
                                                                                        inclure_inactifs=False)}
        self.fonctions.setdefault(aff["fonction"], aff["id_fonction"])
        self.services = {s["libelle"]: s["id"] for s in affectations.liste_referentiel(app.conn, app.session, "SERVICE",
                                                                                       inclure_inactifs=False)}
        if aff["service"]:
            self.services.setdefault(aff["service"], aff["id_service"])
        if not terminer:
            _etiquette(c, "Fonction", obligatoire=False)
            ttk.Combobox(c, textvariable=self.v_fonction, values=list(self.fonctions), state="readonly", font=police(11)
                         ).pack(fill="x", ipady=px(2), pady=(px(2), px(8)))
            _etiquette(c, "Service", obligatoire=False)
            ttk.Combobox(c, textvariable=self.v_service, values=[AUCUN] + list(self.services), state="readonly", font=police(11)
                         ).pack(fill="x", ipady=px(2), pady=(px(2), px(8)))
            self.champ("Responsabilité", self.v_resp)
            _etiquette(c, "Date de début (jj/mm/aaaa)", obligatoire=False)
            SelecteurDate(c, self.v_debut).pack(fill="x", pady=(px(2), px(8)))
        _etiquette(c, "Date de fin (jj/mm/aaaa)" + ("" if terminer else " - vide : sans date de fin"), obligatoire=terminer)
        SelecteurDate(c, self.v_fin).pack(fill="x", pady=(px(2), px(8)))
        self.champ("Motif (facultatif)", self.v_motif)
        self.lbl = tk.Label(c, text="", font=police(10, gras=True), fg=ROUGE, bg=BLANC, anchor="w", justify="left", wraplength=px(440))
        self.lbl.pack(fill="x")
        boutons = tk.Frame(c, bg=BLANC)
        boutons.pack(fill="x", pady=(px(8), 0))
        creer_bouton(boutons, "ENREGISTRER", self.valider, grand=False).pack(side="left")
        creer_bouton(boutons, "ANNULER", self.destroy, style="secondaire", grand=False).pack(side="left", padx=px(8))

    def valider(self):
        try:
            if self.terminer:
                affectations.terminer_affectation(self.app.conn, self.app.session, self.aff["id_aff"], self.v_fin.get(),
                                                  self.v_motif.get())
                self.resultat = "Affectation terminée."
            else:
                champs = affectations.modifier_affectation(self.app.conn, self.app.session, self.aff["id_aff"], {
                    "id_fonction": self.fonctions.get(self.v_fonction.get()),
                    "id_service": self.services.get(self.v_service.get()), "responsabilite": self.v_resp.get(),
                    "date_debut": self.v_debut.get(), "date_fin": self.v_fin.get(), "motif": self.v_motif.get()})
                self.resultat = ("Affectation corrigée : " + ", ".join(champs) + ".") if champs else "Rien n'a changé."
        except ERREURS as erreur:
            self.lbl.config(text=str(erreur))
            return
        self.destroy()


class PanneauAffectation(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.matricule, self.historique, self.fonctions, self.services = None, {}, {}, {}
        self.var_fonction, self.var_service, self.var_resp = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.var_debut, self.var_fin, self.var_motif = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.selecteur, droite = _volet_agent(self, module, self.choisir)
        self.lbl_entete = tk.Label(droite, text="", font=police(13, gras=True, titre=True), fg=NUIT, bg=BLANC, anchor="w")
        self.lbl_entete.pack(fill="x")
        self.lbl_actuelle = tk.Label(droite, text="", font=police(10, gras=True), fg=GRIS, bg=BLANC, anchor="w", justify="left", wraplength=px(700))
        self.lbl_actuelle.pack(fill="x")

        boutons = tk.Frame(droite, bg=BLANC)
        boutons.pack(side="bottom", fill="x", pady=(px(8), 0))
        self.lbl_message = tk.Label(droite, text="", font=police(11, gras=True), bg=BLANC, anchor="w", justify="left", wraplength=px(700))
        self.lbl_message.pack(side="bottom", fill="x", pady=(px(4), 0))
        self.btn_affecter = creer_bouton(boutons, "ENREGISTRER L'AFFECTATION", self.affecter, grand=False)
        self.btn_affecter.pack(side="left", padx=(0, px(8)))
        self.btn_annuler = creer_bouton(boutons, "ANNULER", self.vider_formulaire, style="secondaire", grand=False)
        self.btn_annuler.pack(side="left", padx=(0, px(14)))
        self.btn_terminer = creer_bouton(boutons, "TERMINER L'AFFECTATION CHOISIE", self.terminer, style="secondaire", grand=False)
        self.btn_terminer.pack(side="left", padx=(0, px(8)))
        self.btn_corriger = creer_bouton(boutons, "CORRIGER", self.corriger, style="secondaire", grand=False)
        self.btn_corriger.pack(side="left")

        zone = ZoneDefilante(droite)
        zone.pack(fill="both", expand=True, pady=(px(6), 0))
        hist = tk.Frame(zone.interieur, bg=BLANC)
        hist.pack(fill="x", padx=(0, px(14)))
        tk.Label(hist, text="Historique des changements de fonction", font=police(12, gras=True, titre=True), fg=NUIT, bg=BLANC,
                 anchor="w").pack(fill="x")
        cadre, self.arbre = creer_arbre(hist, [
            ("debut", "Début", 80, "center"), ("fin", "Fin", 80, "center"), ("fonction", "Fonction", 150, "w"),
            ("service", "Service", 110, "w"), ("resp", "Responsabilité", 150, "w"), ("statut", "Situation", 80, "center"),
            ("duree", "Durée", 80, "center")], hauteur=5)
        cadre.pack(fill="x", pady=(px(4), px(4)))
        self.arbre.tag_configure("en_cours", background="#E8F3EA")
        self.arbre.tag_configure("a_venir", foreground=ORANGE)
        self.arbre.bind("<<TreeviewSelect>>", lambda _e: self._activer())
        self.lbl_motif = tk.Label(hist, text="", font=police(9), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_motif.pack(fill="x")

        form = carte(zone.interieur, padx=px(14), pady=px(10))
        form.pack(fill="x", padx=(0, px(14)), pady=(px(8), px(6)))
        tk.Label(form, text="Nouvelle affectation (changement de fonction, de service ou de responsabilité)",
                 font=police(12, gras=True, titre=True), fg=NUIT, bg=BLANC, anchor="w").pack(fill="x")
        tk.Label(form, text="Si l'agent a une affectation sans date de fin, elle se termine automatiquement la veille du nouveau début.",
                 font=police(9), fg=GRIS, bg=BLANC, anchor="w").pack(fill="x", pady=(0, px(6)))
        form.grid_columnconfigure(0, weight=1)
        grille = tk.Frame(form, bg=BLANC)
        grille.pack(fill="x")
        grille.grid_columnconfigure((0, 1), weight=1, uniform="g")
        g1, g2 = tk.Frame(grille, bg=BLANC), tk.Frame(grille, bg=BLANC)
        g1.grid(row=0, column=0, sticky="new", padx=(0, px(10)))
        g2.grid(row=0, column=1, sticky="new", padx=(px(10), 0))
        _etiquette(g1, "Fonction")
        self.cb_fonction = ttk.Combobox(g1, textvariable=self.var_fonction, state="readonly", font=police(11))
        self.cb_fonction.pack(fill="x", ipady=px(2), pady=(px(2), px(6)))
        _etiquette(g1, "Service", obligatoire=False)
        self.cb_service = ttk.Combobox(g1, textvariable=self.var_service, state="readonly", font=police(11))
        self.cb_service.pack(fill="x", ipady=px(2), pady=(px(2), px(6)))
        _etiquette(g1, "Responsabilité (ex. Titulaire de la 3ème A)", obligatoire=False)
        self.champ_resp = creer_champ(g1, self.var_resp)
        self.champ_resp.pack(fill="x", ipady=px(3), pady=(px(2), px(6)))
        _etiquette(g2, "Date de début (jj/mm/aaaa)")
        self.sel_debut = SelecteurDate(g2, self.var_debut)
        self.sel_debut.pack(fill="x", pady=(px(2), px(6)))
        _etiquette(g2, "Date de fin (si nécessaire)", obligatoire=False)
        self.sel_fin = SelecteurDate(g2, self.var_fin)
        self.sel_fin.pack(fill="x", pady=(px(2), px(6)))
        _etiquette(g2, "Motif (ex. Promotion, Mutation)", obligatoire=False)
        self.champ_motif = creer_champ(g2, self.var_motif)
        self.champ_motif.pack(fill="x", ipady=px(3), pady=(px(2), px(6)))
        self._afficher_agent(None)

    def au_affichage(self):
        self._charger_listes()
        self.selecteur.actualiser(self.module.matricule_courant, forcer=True)

    def _charger_listes(self):
        try:
            self.fonctions = {f["libelle"]: f["id"] for f in affectations.liste_referentiel(
                self.app.conn, self.app.session, "FONCTION", inclure_inactifs=False)}
            self.services = {s["libelle"]: s["id"] for s in affectations.liste_referentiel(
                self.app.conn, self.app.session, "SERVICE", inclure_inactifs=False)}
        except ERREURS:
            self.fonctions, self.services = {}, {}
        self.cb_fonction.config(values=list(self.fonctions))
        self.cb_service.config(values=[AUCUN] + list(self.services))

    def choisir(self, matricule):
        self.module.matricule_courant = matricule
        self.matricule = matricule
        self.message("")
        self.vider_formulaire()
        self.recharger()

    def message(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    def vider_formulaire(self):
        self.var_fonction.set("")
        self.var_service.set(AUCUN)
        self.var_resp.set("")
        self.var_debut.set(_aujourdhui())
        self.var_fin.set("")
        self.var_motif.set("")

    def recharger(self, garder=None):
        vider_arbre(self.arbre)
        self.historique = {}
        if not self.matricule:
            self._afficher_agent(None)
            return
        try:
            agent = personnel.charger_agent(self.app.conn, self.app.session, self.matricule)
            historique = affectations.historique_agent(self.app.conn, self.app.session, self.matricule)
        except ERREURS as erreur:
            self.message(str(erreur), ROUGE)
            self._afficher_agent(None)
            return
        for a in historique:
            iid = str(a["id_aff"])
            self.historique[iid] = a
            self.arbre.insert("", "end", iid=iid, tags=(a["statut"].lower(),),
                              values=(a["date_debut"], a["date_fin"] or "-", a["fonction"], a["service"] or "-",
                                      a["responsabilite"] or "-", a["libelle_statut"], a["duree"] or "-"))
        if garder is not None and self.arbre.exists(str(garder)):
            self.arbre.selection_set(str(garder))
        en_cours = next((a for a in historique if a["statut"] == "EN_COURS"), None)
        self._afficher_agent(agent, en_cours)

    def _afficher_agent(self, agent, en_cours=None):
        if agent is None:
            self.lbl_entete.config(text="Choisissez un agent dans la liste.")
            self.lbl_actuelle.config(text="")
        else:
            self.lbl_entete.config(text=agent["nom_complet"] + ("" if agent["actif"] else "   (désactivé)"))
            if en_cours:
                detail = " - ".join(x for x in (en_cours["fonction"], en_cours["service"], en_cours["responsabilite"]) if x)
                self.lbl_actuelle.config(text=f"Situation actuelle : {detail}, depuis le {en_cours['date_debut']}"
                                              + (f" jusqu'au {en_cours['date_fin']}" if en_cours["date_fin"] else ""))
            else:
                self.lbl_actuelle.config(text="Aucune affectation en cours.")
        self._activer()

    def _selection(self):
        sel = self.arbre.selection()
        return self.historique.get(sel[0]) if sel else None

    def _activer(self):
        conn, session = self.app.conn, self.app.session
        agent = self.matricule is not None
        a = self._selection()
        self.lbl_motif.config(text=f"Motif : {a['motif']}" if a and a["motif"] else "")
        peut_ajouter = agent and personnel.peut(conn, session, "AJOUT") and bool(self.fonctions)
        definir_actif(self.btn_affecter, peut_ajouter)
        definir_actif(self.btn_annuler, peut_ajouter)
        peut_modifier = a is not None and personnel.peut(conn, session, "MODIFICATION")
        definir_actif(self.btn_terminer, peut_modifier and not a["date_fin"])
        definir_actif(self.btn_corriger, peut_modifier)
        for w in (self.cb_fonction, self.cb_service):
            w.config(state="readonly" if peut_ajouter else "disabled")
        for w in (self.champ_resp, self.champ_motif):
            w.config(state="normal" if peut_ajouter else "disabled")
        for s in (self.sel_debut, self.sel_fin):
            s.champ.config(state="normal" if peut_ajouter else "disabled")
            s.bouton.config(state="normal" if peut_ajouter else "disabled")
        if agent and not self.fonctions and personnel.peut(conn, session, "AJOUT"):
            self.message("Aucune fonction n'est définie : ajoutez-en dans l'onglet « Fonctions et services ».", ORANGE)

    def affecter(self):
        try:
            r = affectations.affecter(self.app.conn, self.app.session, self.matricule, {
                "id_fonction": self.fonctions.get(self.var_fonction.get()),
                "id_service": self.services.get(self.var_service.get()), "responsabilite": self.var_resp.get(),
                "date_debut": self.var_debut.get(), "date_fin": self.var_fin.get(), "motif": self.var_motif.get()})
        except ERREURS as erreur:
            self.message(str(erreur), ROUGE)
            return
        self.vider_formulaire()
        self.selecteur.actualiser(self.matricule)
        self.recharger(garder=r["id_aff"])
        texte = "Affectation enregistrée."
        if r["terminees"]:
            texte += " L'affectation précédente est terminée : " + r["terminees"][0].split(" | ")[0] + " (fin la veille du nouveau début)."
        self.message(texte, VERT)

    def _dialogue(self, terminer):
        a = self._selection()
        if not a:
            return
        resultat = DialogueAffectation(self, self.app, a, terminer).attendre()
        if resultat:
            self.selecteur.actualiser(self.matricule)
            self.recharger(garder=a["id_aff"])
            self.message(resultat, VERT)

    def terminer(self):
        self._dialogue(True)

    def corriger(self):
        self._dialogue(False)


# ================================================================== 5) LISTE DU PERSONNEL
class PanneauListe(tk.Frame):
    TOUTES = {"FONCTION": "Toutes les fonctions", "SERVICE": "Tous les services"}

    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.var_mode, self.var_filtre, self.var_jour = tk.StringVar(value="FONCTION"), tk.StringVar(), tk.StringVar(value=_aujourdhui())
        self.choix = {}                                       # libellé -> identifiant (fonction ou service)

        bas = tk.Frame(self, bg=BLANC)
        bas.pack(side="bottom", fill="x", padx=px(24), pady=(px(6), px(12)))
        self.lbl_message = tk.Label(self, text="", font=police(11, gras=True), bg=BLANC, anchor="w", justify="left", wraplength=px(1000))
        self.lbl_message.pack(side="bottom", fill="x", padx=px(26))
        self.btn_consulter = creer_bouton(bas, "CONSULTER", self.consulter, grand=False)
        self.btn_consulter.pack(side="left", padx=(0, px(8)))
        self.btn_imprimer = creer_bouton(bas, "IMPRIMER LA LISTE", self.imprimer, style="secondaire", grand=False)
        self.btn_imprimer.pack(side="left")

        haut = carte(self, padx=px(16), pady=px(10))
        haut.pack(fill="x", padx=px(24), pady=(px(14), px(6)))
        ligne = tk.Frame(haut, bg=BLANC)
        ligne.pack(fill="x")
        tk.Label(ligne, text="Liste du personnel :", font=police(11, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
        for valeur, texte in (("FONCTION", "par fonction"), ("SERVICE", "par service")):
            tk.Radiobutton(ligne, text=texte, value=valeur, variable=self.var_mode, command=self._mode_change, font=police(11),
                           bg=BLANC, fg=NUIT, activebackground=BLANC, selectcolor=BLANC, highlightthickness=0
                           ).pack(side="left", padx=(px(12), 0))
        ligne2 = tk.Frame(haut, bg=BLANC)
        ligne2.pack(fill="x", pady=(px(8), 0))
        self.cb_filtre = ttk.Combobox(ligne2, textvariable=self.var_filtre, state="readonly", width=34, font=police(11))
        self.cb_filtre.pack(side="left")
        tk.Label(ligne2, text="Situation au :", font=police(11, gras=True), fg=NUIT, bg=BLANC).pack(side="left", padx=(px(18), px(8)))
        SelecteurDate(ligne2, self.var_jour).pack(side="left")
        self.lbl_info = tk.Label(self, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_info.pack(fill="x", padx=px(26), pady=(0, px(2)))
        cadre, self.arbre = creer_arbre(self, [
            ("nom", "Nom complet", 260, "w"), ("matricule", "Matricule", 90, "center"), ("autre", "Service", 160, "w"),
            ("resp", "Responsabilité", 190, "w"), ("depuis", "Depuis", 90, "center"), ("tel", "Téléphone", 120, "w")], hauteur=6)
        cadre.pack(fill="both", expand=True, padx=px(24))
        self.arbre.tag_configure("groupe", background=FOND_CLAIR, font=police(10, gras=True))

    def au_affichage(self):
        self._mode_change()

    def _mode_change(self):
        mode = self.var_mode.get()
        try:
            liste = affectations.liste_referentiel(self.app.conn, self.app.session, mode)
        except ERREURS as erreur:
            self.lbl_message.config(text=str(erreur), fg=ROUGE)
            return
        self.choix = {e["libelle"]: e["id"] for e in liste}
        self.cb_filtre.config(values=[self.TOUTES[mode]] + list(self.choix))
        self.var_filtre.set(self.TOUTES[mode])
        self.lbl_message.config(text="")
        vider_arbre(self.arbre)
        self.lbl_info.config(text="")

    def _parametres(self):
        mode = self.var_mode.get()
        return mode, self.choix.get(self.var_filtre.get()), self.var_jour.get()

    def consulter(self):
        mode, filtre, jour = self._parametres()
        try:
            liste = affectations.liste_personnel(self.app.conn, self.app.session, mode, filtre, jour)
        except ERREURS as erreur:
            self.lbl_message.config(text=str(erreur), fg=ROUGE)
            return
        self.lbl_message.config(text="")
        self.arbre.heading("autre", text="Service" if mode == "FONCTION" else "Fonction")
        vider_arbre(self.arbre)
        for g in liste["groupes"]:
            self.arbre.insert("", "end", tags=("groupe",), values=(f"{g['libelle']}  ({len(g['agents'])})", "", "", "", "", ""))
            for a in g["agents"]:
                self.arbre.insert("", "end", values=("      " + a["nom_complet"], a["matricule"],
                                                     (a["service"] if mode == "FONCTION" else a["fonction"]) or "-",
                                                     a["responsabilite"] or "-", a["depuis"] or "-", a["telephone"]))
        self.lbl_info.config(text=f"{liste['total']} agent(s) en service au {liste['jour']}"
                                  + (f" - {liste['filtre']}" if liste["filtre"] else ""))

    def imprimer(self):
        mode, filtre, jour = self._parametres()
        try:
            ouvrir_fichier(affectations.preparer_liste_pdf(self.app.conn, self.app.session, mode, filtre, jour))
        except ERREURS as erreur:
            self.lbl_message.config(text=str(erreur), fg=ROUGE)
        except OSError as erreur:
            self.lbl_message.config(text=f"La liste est prête mais n'a pas pu s'ouvrir : {erreur}", fg=ROUGE)

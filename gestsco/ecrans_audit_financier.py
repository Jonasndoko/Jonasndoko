"""Module « Traçabilité et audit » : onglets 4, 5 et 6 (la logique est dans audit_financier.py, audit_recherche.py et
audit_rapports.py).

4. Contrôle et audit financier : paiements et reçus, montants encaissés et remis, annulations et corrections, différences
   entre les opérations enregistrées et les rapports journaliers, anomalies.
5. Recherche et filtrage des traces : par utilisateur, période, module, type d'action, n° de reçu, matricule de l'élève.
6. Rapports d'audit : rapports consultables à l'écran, imprimables (PDF) et exportables (CSV).
"""
import tkinter as tk
from datetime import date
from tkinter import ttk

import argent
import audit
import audit_financier
import audit_rapports
import audit_recherche
from ecrans_audit import ERREURS, TOUS_UTILISATEURS, _exporter, _Filtres, _lire_jour, _liste_utilisateurs
from ecrans_paiement import creer_arbre, vider_arbre
from saisie_date import formater_date
from theme import BLANC, BORDURE, FOND_CLAIR, GRIS, NUIT, ORANGE, ROUGE, VERT, creer_bouton, police, px

TOUS_PERCEPTEURS = "Tous les percepteurs"
TOUTES_DEVISES = "Toutes les devises"
TOUS_MODULES = "Tous les modules"
TOUS_TYPES = "Tous les types d'action"
LIMITE_ECRAN = 300                       # lignes montrées par section dans un rapport affiché (le PDF / CSV contient tout)
COULEURS_TAGS = {"rouge": ROUGE, "orange": ORANGE, "gris": GRIS}
TAG_GRAVITE = {"ÉLEVÉE": "rouge", "MOYENNE": "orange", "FAIBLE": "gris"}
TAG_STATUT = {"Anomalie": "rouge", "Écart": "rouge", "À vérifier": "orange", "Conforme, modifié depuis": "orange",
              "Non comparable": "gris"}


def _regler_tags(arbre):
    for nom, couleur in COULEURS_TAGS.items():
        arbre.tag_configure(nom, foreground=couleur)


def _liste_percepteurs(conn, session) -> dict:
    choix = {TOUS_PERCEPTEURS: None}
    for n_perc, nom in audit_financier.liste_percepteurs(conn, session):
        choix[nom] = n_perc
    return choix


def _liste_devises(conn, session) -> dict:
    choix = {TOUTES_DEVISES: None}
    for code in audit_financier.liste_devises(conn, session):
        choix[code] = code
    return choix


def _f(centimes) -> str:
    return "" if centimes is None else argent.formater(centimes)


# ================================================================== 4) CONTRÔLE ET AUDIT FINANCIER
class PanneauControleFinancier(tk.Frame):
    # clé, titre de l'onglet intérieur, colonnes (clé, titre, largeur, ancrage)
    TABLES = (
        ("anomalies", "Anomalies", [("grav", "Gravité", 80, "w"), ("cat", "Catégorie", 170, "w"),
                                    ("ref", "Référence", 170, "w"), ("date", "Date", 90, "w"),
                                    ("msg", "Constat", 720, "w")]),
        ("paiements", "Paiements et reçus", [
            ("recu", "N° reçu", 70, "w"), ("date", "Date", 120, "w"), ("eleve", "Élève", 250, "w"),
            ("frais", "Frais", 170, "w"), ("montant", "Montant", 90, "e"), ("dev", "Devise", 55, "w"),
            ("perc", "Percepteur", 150, "w"), ("par", "Enregistré par", 190, "w"), ("statut", "Statut", 70, "w"),
            ("verif", "Vérification", 90, "w")]),
        ("caisse", "Encaissé et remis (rapprochement journalier)", [
            ("date", "Date", 85, "w"), ("perc", "Percepteur", 170, "w"), ("dev", "Devise", 55, "w"),
            ("jnb", "Journal : reçus", 90, "e"), ("jtot", "Journal : total", 100, "e"), ("ann", "Annulés", 85, "e"),
            ("rnb", "Rapport : reçus", 95, "e"), ("rtot", "Rapport : total", 100, "e"), ("enc", "Encaissé", 95, "e"),
            ("ver", "Versé", 95, "e"), ("eca", "Écart de remise", 100, "e"), ("dif", "Encaissé - reçus", 100, "e"),
            ("statut", "Statut", 90, "w")]),
        ("annulations", "Annulations", [
            ("recu", "N° reçu", 70, "w"), ("date", "Annulé le", 120, "w"), ("delai", "Délai", 80, "w"),
            ("eleve", "Élève", 240, "w"), ("montant", "Montant", 90, "e"), ("dev", "Devise", 55, "w"),
            ("motif", "Motif", 260, "w"), ("par", "Enregistré par", 180, "w"), ("ann", "Annulé par", 180, "w")]),
        ("corrections", "Corrections", [
            ("date", "Date", 120, "w"), ("nature", "Nature", 230, "w"), ("ref", "Référence", 150, "w"),
            ("par", "Fait par", 110, "w"), ("avant", "Avant", 330, "w"), ("apres", "Après", 330, "w")]),
        ("rapports", "Rapports journaliers imprimés", [
            ("date", "Imprimé le", 120, "w"), ("type", "Rapport", 120, "w"), ("jour", "Journée", 85, "w"),
            ("portee", "Portée", 170, "w"), ("par", "Par", 100, "w"), ("inb", "Reçus imprimés", 100, "e"),
            ("itot", "Total imprimé", 150, "e"), ("anb", "Reçus aujourd'hui", 110, "e"),
            ("atot", "Total aujourd'hui", 150, "e"), ("statut", "Statut", 160, "w")]),
    )

    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.percepteurs, self.devises = {}, {}
        self.details = {cle: [] for cle, _t, _c in self.TABLES}
        self.arbres = {}
        self.vars = {k: tk.StringVar() for k in ("du", "au", "percepteur", "devise")}

        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(20), pady=px(10))
        tk.Label(corps, text="Contrôle et audit financier", font=police(14, gras=True, titre=True), fg=NUIT, bg=BLANC,
                 anchor="w").pack(fill="x")
        tk.Label(corps, text=("Vérifie les paiements et leurs reçus, les montants encaissés et remis, les annulations et "
                              "corrections, et compare les opérations enregistrées aux rapports journaliers. Une anomalie "
                              "n'est pas une preuve de fraude : elle indique où regarder."),
                 font=police(10), fg=GRIS, bg=BLANC, anchor="w", justify="left", wraplength=px(1150)).pack(
            fill="x", pady=(0, px(6)))

        filtres = _Filtres(corps)
        filtres.pack(fill="x")
        filtres.periode(filtres.rangee1, self.vars["du"], self.vars["au"])
        self.cb_percepteur = filtres.liste(filtres.rangee1, "Percepteur :", self.vars["percepteur"], 26)
        self.cb_devise = filtres.liste(filtres.rangee1, "Devise :", self.vars["devise"], 12)
        creer_bouton(filtres.rangee2, "Lancer le contrôle", self.lancer, grand=False).pack(side="left")
        creer_bouton(filtres.rangee2, "Aujourd'hui", self.aujourdhui, style="secondaire",
                     grand=False).pack(side="left", padx=px(6))
        creer_bouton(filtres.rangee2, "Réinitialiser", self.reinitialiser, style="secondaire",
                     grand=False).pack(side="left")
        creer_bouton(filtres.rangee2, "Rapport d'audit...", self.vers_rapport, style="secondaire",
                     grand=False).pack(side="right")

        self.lbl_synthese = tk.Label(corps, text="Choisissez la période puis cliquez sur « Lancer le contrôle ».",
                                     font=police(11, gras=True), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_synthese.pack(fill="x", pady=(px(8), 0))
        self.lbl_journal = tk.Label(corps, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_journal.pack(fill="x", pady=(0, px(4)))

        self.onglets = ttk.Notebook(corps)
        self.onglets.pack(fill="both", expand=True)
        for cle, titre, colonnes in self.TABLES:
            page = tk.Frame(self.onglets, bg=BLANC)
            self.onglets.add(page, text=titre)
            cadre, arbre = creer_arbre(page, colonnes, hauteur=10)
            cadre.pack(fill="both", expand=True, padx=px(4), pady=px(6))
            _regler_tags(arbre)
            arbre.bind("<<TreeviewSelect>>", lambda _e, c=cle: self._selection(c))
            self.arbres[cle] = arbre

        self.var_detail = tk.StringVar(value="Cliquez sur une ligne pour lire le constat complet.")
        tk.Label(corps, textvariable=self.var_detail, font=police(10), fg=NUIT, bg=BLANC, anchor="w", justify="left",
                 wraplength=px(1150)).pack(fill="x", pady=(px(6), 0))
        self.lbl_message = tk.Label(corps, text="", font=police(10, gras=True), fg=ROUGE, bg=BLANC, anchor="w")
        self.lbl_message.pack(fill="x")

    # --- cycle de vie ------------------------------------------------------
    def au_affichage(self):
        try:
            self.percepteurs = _liste_percepteurs(self.app.conn, self.app.session)
            self.devises = _liste_devises(self.app.conn, self.app.session)
        except ERREURS as erreur:
            self.lbl_message.config(text=str(erreur))
            return
        self.cb_percepteur.config(values=list(self.percepteurs))
        self.cb_devise.config(values=list(self.devises))
        if self.vars["percepteur"].get() not in self.percepteurs:
            self.vars["percepteur"].set(TOUS_PERCEPTEURS)
        if self.vars["devise"].get() not in self.devises:
            self.vars["devise"].set(TOUTES_DEVISES)

    def _filtres(self) -> dict:
        return {"du": _lire_jour(self.vars["du"], "du"), "au": _lire_jour(self.vars["au"], "au"),
                "n_perc": self.percepteurs.get(self.vars["percepteur"].get()),
                "devise": self.devises.get(self.vars["devise"].get())}

    def aujourdhui(self):
        jour = formater_date(date.today())
        self.vars["du"].set(jour)
        self.vars["au"].set(jour)
        self.lancer()

    def reinitialiser(self):
        for cle in ("du", "au"):
            self.vars[cle].set("")
        self.vars["percepteur"].set(TOUS_PERCEPTEURS)
        self.vars["devise"].set(TOUTES_DEVISES)

    def vers_rapport(self):
        try:
            f = self._filtres()
        except ERREURS as erreur:
            self.lbl_message.config(text=str(erreur))
            return
        self.module.afficher_onglet("rapports")
        self.module.panneaux["rapports"].reprendre(f["du"], f["au"], self.vars["percepteur"].get(),
                                                   self.vars["devise"].get())

    # --- contrôle ------------------------------------------------------------
    def lancer(self):
        try:
            c = audit_financier.controle_financier(self.app.conn, self.app.session, **self._filtres())
        except ERREURS as erreur:
            self.lbl_message.config(text=str(erreur))
            return
        self.lbl_message.config(text="")
        self._remplir(c)

    def _remplir(self, c):
        nb = c["nb_anomalies"]
        total = sum(nb.values())
        if total:
            self.lbl_synthese.config(
                fg=ROUGE if nb["ÉLEVÉE"] else ORANGE,
                text=f"{total} anomalie(s) : {nb['ÉLEVÉE']} élevée(s), {nb['MOYENNE']} moyenne(s), {nb['FAIBLE']} faible(s)"
                     f"  -  {len(c['paiements'])} reçu(s) et {len(c['rapprochement'])} journée(s) contrôlés")
        else:
            self.lbl_synthese.config(
                fg=VERT, text=f"Aucune anomalie : tout concorde  -  {len(c['paiements'])} reçu(s) et "
                              f"{len(c['rapprochement'])} journée(s) contrôlés")
        e = c["journal"]
        self.lbl_journal.config(
            fg=GRIS if e["ok"] else ROUGE,
            text=(f"Journal : {e['nb_lignes']} ligne(s), chaîne d'empreintes intacte" if e["ok"] else
                  f"JOURNAL MODIFIÉ à partir de la ligne {e['anomalie']} : conclusions à confirmer")
                 + ("  -  les opérations antérieures à la dernière réinitialisation ne sont pas contrôlées"
                    if c["apres_reinitialisation"] else ""))
        lignes = {
            "anomalies": [((a["gravite"], a["categorie"], a["reference"] or "—", a["date_txt"] or "—", a["message"]),
                           TAG_GRAVITE[a["gravite"]],
                           f"[{a['gravite']}] {a['message']}\nPiste de vérification : "
                           f"{audit_rapports.CONSEILS.get(a['code'], audit_rapports.CONSEIL_PAR_DEFAUT)}")
                          for a in c["anomalies"]],
            "paiements": [((p["n_recu"], p["date_txt"], f"{p['matricule']} - {p['eleve']}", p["frais"], p["montant_txt"],
                            p["devise"], p["percepteur"], p["enregistre_par"], p["statut"], p["verification"]),
                           TAG_STATUT.get(p["verification"]) or ("gris" if p["statut"] == "Annulé" else ""),
                           p["remarques"] or f"Reçu {p['n_recu']} : conforme à sa trace au journal "
                                             f"({p['recus_imprimes']} impression(s), {p['duplicatas']} duplicata).")
                          for p in c["paiements"]],
            "caisse": [((g["date_txt"], g["percepteur"], g["devise"], g["journal_nb"], _f(g["journal_total"]),
                         _f(g["annules_total"]), g["recus_nb"], _f(g["recus_total"]), _f(g["encaisse"]), _f(g["verse"]),
                         _f(g["ecart_remise"]), _f(g["diff_recus"]), g["statut"]),
                        TAG_STATUT.get(g["statut"], ""),
                        g["remarques"] or f"{g['date_txt']} - {g['percepteur']} - {g['devise']} : tout concorde "
                                          f"({g['references'] or 'aucun encaissement'}).") for g in c["rapprochement"]],
            "annulations": [((a["n_recu"], a["date_txt"], a["delai"], f"{a['matricule']} - {a['eleve']}", a["montant_txt"],
                              a["devise"], a["motif"], a["enregistre_par"], a["annule_par"]),
                             "orange" if a["remarques"] else "",
                             f"Reçu {a['n_recu']} payé le {a['date_paiement_txt']}, annulé le {a['date_txt']} "
                             f"(délai {a['delai']}). Motif : {a['motif']}." + (f"\n{a['remarques']}" if a["remarques"] else ""))
                            for a in c["annulations"]],
            "corrections": [((x["date_txt"], x["nature"], x["reference"], x["par_login"] or "—", x["avant"], x["apres"]),
                             "", f"{x['nature']} ({x['reference']}) par {x['par_login'] or '—'}\nAvant : {x['avant']}\n"
                                 f"Après : {x['apres']}") for x in c["corrections"]],
            "rapports": [((r["date_txt"], r["type"], r["jour_txt"], r["portee"], r["par_login"] or "—", r["imprime_nb"],
                           r["imprime_total"], "" if r["actuel_nb"] is None else r["actuel_nb"], r["actuel_total"],
                           r["statut"]), TAG_STATUT.get(r["statut"], ""), r["remarques"] or r["statut"])
                          for r in c["rapports"]],
        }
        for i, (cle, titre, _colonnes) in enumerate(self.TABLES):
            arbre = self.arbres[cle]
            vider_arbre(arbre)
            self.details[cle] = []
            for k, (valeurs, tag, detail) in enumerate(lignes[cle]):
                arbre.insert("", "end", iid=str(k), values=valeurs, tags=(tag,) if tag else ())
                self.details[cle].append(detail)
            self.onglets.tab(i, text=f"{titre} ({len(lignes[cle])})")
        self.var_detail.set("Cliquez sur une ligne pour lire le constat complet.")
        self.onglets.select(0)

    def _selection(self, cle):
        selection = self.arbres[cle].selection()
        if selection:
            self.var_detail.set(self.details[cle][int(selection[0])])


# ================================================================== 5) RECHERCHE ET FILTRAGE DES TRACES
class PanneauRecherche(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.lignes = []
        self.charge = False
        self.utilisateurs, self.modules, self.types = {}, {}, {}
        self.vars = {k: tk.StringVar() for k in ("du", "au", "utilisateur", "module", "type", "recu", "eleve", "texte")}

        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(20), pady=px(10))
        tk.Label(corps, text="Recherche et filtrage des traces", font=police(14, gras=True, titre=True), fg=NUIT,
                 bg=BLANC, anchor="w").pack(fill="x", pady=(0, px(6)))
        filtres = _Filtres(corps)
        filtres.pack(fill="x")
        self.rangee3 = tk.Frame(filtres, bg=FOND_CLAIR)
        self.rangee3.pack(fill="x", pady=(px(8), 0))
        self.cb_utilisateur = filtres.liste(filtres.rangee1, "Utilisateur :", self.vars["utilisateur"], 28)
        self.cb_module = filtres.liste(filtres.rangee1, "Module concerné :", self.vars["module"], 28)
        self.cb_type = filtres.liste(filtres.rangee1, "Type d'action :", self.vars["type"], 40)
        self.cb_module.bind("<<ComboboxSelected>>", self._module_choisi)
        filtres.periode(filtres.rangee2, self.vars["du"], self.vars["au"])
        filtres.champ(filtres.rangee2, "N° de reçu :", self.vars["recu"], 10, self.rechercher)
        filtres.champ(filtres.rangee2, "Matricule de l'élève :", self.vars["eleve"], 16, self.rechercher)
        filtres.champ(self.rangee3, "Texte :", self.vars["texte"], 26, self.rechercher)
        creer_bouton(self.rangee3, "Rechercher", self.rechercher, grand=False).pack(side="left")
        creer_bouton(self.rangee3, "Aujourd'hui", self.aujourdhui, style="secondaire",
                     grand=False).pack(side="left", padx=px(6))
        creer_bouton(self.rangee3, "Réinitialiser", self.reinitialiser, style="secondaire",
                     grand=False).pack(side="left")
        creer_bouton(self.rangee3, "Imprimer (PDF)", lambda: self.exporter("pdf"), style="secondaire",
                     grand=False).pack(side="right")
        creer_bouton(self.rangee3, "Exporter (Excel / CSV)", lambda: self.exporter("csv"), style="secondaire",
                     grand=False).pack(side="right", padx=px(6))

        self.lbl_resume = tk.Label(corps, text="", font=police(10, gras=True), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_resume.pack(fill="x", pady=(px(8), px(4)))
        cadre, self.arbre = creer_arbre(corps, [
            ("date", "Date et heure", 140, "w"), ("qui", "Utilisateur", 170, "w"), ("module", "Module", 170, "w"),
            ("action", "Action", 260, "w"), ("recu", "N° reçu", 70, "w"), ("mat", "Matricule", 100, "w"),
            ("detail", "Détail", 380, "w")], hauteur=12)
        cadre.pack(fill="both", expand=True)
        _regler_tags(self.arbre)
        self.arbre.bind("<<TreeviewSelect>>", self._selection)

        tk.Label(corps, text="Détail de la trace sélectionnée (et fiche du reçu s'il y en a un)",
                 font=police(10, gras=True), fg=NUIT, bg=BLANC, anchor="w").pack(fill="x", pady=(px(8), px(2)))
        zone = tk.Frame(corps, bg=BLANC, highlightbackground=BORDURE, highlightthickness=1)
        zone.pack(fill="x")
        self.texte_fiche = tk.Text(zone, height=7, font=police(10), fg=NUIT, bg=BLANC, relief="flat", wrap="word",
                                   state="disabled", padx=px(8), pady=px(6))
        defil = ttk.Scrollbar(zone, orient="vertical", command=self.texte_fiche.yview)
        self.texte_fiche.configure(yscrollcommand=defil.set)
        self.texte_fiche.pack(side="left", fill="x", expand=True)
        defil.pack(side="right", fill="y")
        self.texte_fiche.tag_configure("titre", font=police(11, gras=True, titre=True))
        self.texte_fiche.tag_configure("gras", font=police(10, gras=True))
        self.texte_fiche.tag_configure("gris", foreground=GRIS)
        self._ecrire_fiche([("gris", "Cliquez sur une trace pour la lire en détail.")])
        self.lbl_message = tk.Label(corps, text="", font=police(10, gras=True), fg=ROUGE, bg=BLANC, anchor="w")
        self.lbl_message.pack(fill="x")

    # --- cycle de vie ------------------------------------------------------
    def au_affichage(self):
        try:
            self.utilisateurs = _liste_utilisateurs(self.app.conn, self.app.session)
        except ERREURS as erreur:
            self.lbl_message.config(text=str(erreur))
            return
        self.cb_utilisateur.config(values=list(self.utilisateurs))
        self.modules = {TOUS_MODULES: ""}
        self.modules.update({texte: cle for cle, texte in audit_recherche.MODULES_TRACES.items()})
        self.cb_module.config(values=list(self.modules))
        if self.vars["utilisateur"].get() not in self.utilisateurs:
            self.vars["utilisateur"].set(TOUS_UTILISATEURS)
        if self.vars["module"].get() not in self.modules:
            self.vars["module"].set(TOUS_MODULES)
        self._liste_types()
        if not self.charge:
            self.rechercher()

    def _liste_types(self):
        """Types d'action proposés : ceux du module choisi (tous si aucun module)."""
        module = self.modules.get(self.vars["module"].get(), "")
        self.types = {TOUS_TYPES: ""}
        for code, libelle in audit_recherche.liste_actions():
            if not module or audit_recherche.module_de(code) == module:
                self.types[libelle] = code
        self.cb_type.config(values=list(self.types))
        if self.vars["type"].get() not in self.types:
            self.vars["type"].set(TOUS_TYPES)

    def _module_choisi(self, _evenement=None):
        self._liste_types()

    # --- actions -------------------------------------------------------------
    def _filtres(self) -> dict:
        return {"du": _lire_jour(self.vars["du"], "du"), "au": _lire_jour(self.vars["au"], "au"),
                "login": self.utilisateurs.get(self.vars["utilisateur"].get(), "") or None,
                "module": self.modules.get(self.vars["module"].get(), "") or None,
                "action": self.types.get(self.vars["type"].get(), "") or None,
                "n_recu": self.vars["recu"].get().strip() or None,
                "matricule": self.vars["eleve"].get().strip() or None,
                "texte": self.vars["texte"].get().strip() or None}

    def aujourdhui(self):
        jour = formater_date(date.today())
        self.vars["du"].set(jour)
        self.vars["au"].set(jour)
        self.rechercher()

    def reinitialiser(self):
        for cle in ("du", "au", "recu", "eleve", "texte"):
            self.vars[cle].set("")
        self.vars["utilisateur"].set(TOUS_UTILISATEURS)
        self.vars["module"].set(TOUS_MODULES)
        self._liste_types()
        self.rechercher()

    def rechercher(self, _evenement=None):
        try:
            r = audit_recherche.rechercher_traces(self.app.conn, self.app.session, **self._filtres())
        except ERREURS as erreur:
            self.lbl_message.config(text=str(erreur))
            return
        self.charge = True
        self.lbl_message.config(text="")
        self.lignes = r["lignes"]
        vider_arbre(self.arbre)
        for i, l in enumerate(self.lignes):
            qui = f"{l['login']} - {l['nom']}" if l["nom"] else (l["login"] or "—")
            alerte = l["action"] in ("CONNEXION_ECHEC", "CONNEXION_REFUSEE_BLOCAGE")
            self.arbre.insert("", "end", iid=str(i), tags=("rouge",) if alerte else (), values=(
                l["date_txt"], qui, l["module_txt"], l["libelle"], l["n_recu"] or "", l["matricule"] or "", l["detail"]))
        total, montrees = r["total"], len(self.lignes)
        filtres = audit_recherche.decrire_filtres(r)
        self.lbl_resume.config(
            text=(f"{total} trace(s) trouvée(s)" if total else "Aucune trace trouvée")
                 + (f"  -  filtres : {' ; '.join(filtres)}" if filtres else "")
                 + (f"  -  les {montrees} plus récentes sont affichées : affinez les filtres ou exportez pour tout obtenir"
                    if total > montrees else ""))
        self._ecrire_fiche([("gris", "Cliquez sur une trace pour la lire en détail.")])

    def _selection(self, _evenement=None):
        selection = self.arbre.selection()
        if not selection:
            return
        l = self.lignes[int(selection[0])]
        morceaux = [("titre", f"{l['libelle']}\n"),
                    ("gras", "Quand : "), ("", f"{l['date_txt']}\n"),
                    ("gras", "Utilisateur : "), ("", f"{l['login'] or '—'}" + (f" ({l['nom']})" if l["nom"] else "")
                                                 + (f", {l['poste']}" if l["poste"] else "") + "\n"),
                    ("gras", "Module : "), ("", f"{l['module_txt']}\n")]
        if l["detail"]:
            morceaux += [("gras", "Détail : "), ("", f"{l['detail']}\n")]
        if l["n_recu"]:
            try:
                t = audit.trace_operation(self.app.conn, self.app.session, l["n_recu"])
            except ERREURS as erreur:
                morceaux.append(("gris", f"\n{erreur}\n"))
            else:
                morceaux.append(("gras", f"\n{t['titre']}\n"))
                for libelle, valeur in t["champs"]:
                    morceaux += [("gras", f"{libelle} : "), ("", f"{valeur}\n")]
                morceaux.append(("gras", "Toutes les traces de ce reçu\n"))
                for e in t["evenements"]:
                    qui = f"{e['login']} ({e['nom']})" if e["nom"] else (e["login"] or "—")
                    morceaux.append(("", f"{e['date_txt']}  -  {qui}  -  {e['libelle']}\n"))
        self._ecrire_fiche(morceaux)

    def _ecrire_fiche(self, morceaux):
        t = self.texte_fiche
        t.config(state="normal")
        t.delete("1.0", "end")
        for style, texte in morceaux:
            t.insert("end", texte, style) if style else t.insert("end", texte)
        t.config(state="disabled")

    def exporter(self, format_):
        _exporter(self, lambda: audit_recherche.exporter_traces(self.app.conn, self.app.session, format_,
                                                                **self._filtres()))


# ================================================================== 6) GÉNÉRATION DES RAPPORTS D'AUDIT
class PanneauRapports(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.utilisateurs, self.percepteurs, self.devises = {}, {}, {}
        self.vars = {k: tk.StringVar() for k in ("du", "au", "utilisateur", "percepteur", "devise")}
        self.var_type = tk.StringVar(value="FINANCIER")
        self.var_detail = tk.BooleanVar(value=True)

        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(20), pady=px(10))
        tk.Label(corps, text="Génération des rapports d'audit", font=police(14, gras=True, titre=True), fg=NUIT,
                 bg=BLANC, anchor="w").pack(fill="x", pady=(0, px(6)))

        choix = tk.Frame(corps, bg=FOND_CLAIR, padx=px(12), pady=px(8))
        choix.pack(fill="x")
        for i, (cle, titre) in enumerate(audit_rapports.TYPES_RAPPORT.items()):
            choix.grid_columnconfigure(i, weight=1, uniform="rapport")
            tk.Radiobutton(choix, text=titre, variable=self.var_type, value=cle, bg=FOND_CLAIR,
                           activebackground=FOND_CLAIR, selectcolor=BLANC, font=police(10, gras=True), fg=NUIT,
                           cursor="hand2", anchor="w").grid(row=0, column=i, sticky="w")
            tk.Label(choix, text=audit_rapports.DESCRIPTIONS[cle], font=police(9), fg=GRIS, bg=FOND_CLAIR, anchor="w",
                     justify="left", wraplength=px(270)).grid(row=1, column=i, sticky="nw", padx=(px(22), px(10)))

        filtres = _Filtres(corps)
        filtres.pack(fill="x", pady=(px(6), 0))
        filtres.periode(filtres.rangee1, self.vars["du"], self.vars["au"])
        self.cb_utilisateur = filtres.liste(filtres.rangee1, "Utilisateur :", self.vars["utilisateur"], 26)
        self.cb_percepteur = filtres.liste(filtres.rangee1, "Percepteur :", self.vars["percepteur"], 24)
        self.cb_devise = filtres.liste(filtres.rangee1, "Devise :", self.vars["devise"], 12)
        tk.Checkbutton(filtres.rangee2, text="Inclure le détail de toutes les opérations (rapports général et complet)",
                       variable=self.var_detail, bg=FOND_CLAIR, activebackground=FOND_CLAIR, selectcolor=BLANC,
                       font=police(10), fg=NUIT, cursor="hand2").pack(side="left", padx=(0, px(16)))
        creer_bouton(filtres.rangee2, "Consulter", self.consulter, grand=False).pack(side="left")
        creer_bouton(filtres.rangee2, "Imprimer (PDF)", lambda: self.exporter("pdf"), style="secondaire",
                     grand=False).pack(side="right")
        creer_bouton(filtres.rangee2, "Exporter (Excel / CSV)", lambda: self.exporter("csv"), style="secondaire",
                     grand=False).pack(side="right", padx=px(6))

        self.lbl_message = tk.Label(corps, text="", font=police(10, gras=True), fg=ROUGE, bg=BLANC, anchor="w")
        self.lbl_message.pack(fill="x", pady=(px(4), 0))

        # zone de lecture défilante : le rapport s'y construit section par section
        zone = tk.Frame(corps, bg=BLANC, highlightbackground=BORDURE, highlightthickness=1)
        zone.pack(fill="both", expand=True)
        self.toile = tk.Canvas(zone, bg=BLANC, highlightthickness=0)
        defil = ttk.Scrollbar(zone, orient="vertical", command=self.toile.yview)
        self.toile.configure(yscrollcommand=defil.set)
        defil.pack(side="right", fill="y")
        self.toile.pack(side="left", fill="both", expand=True)
        self.contenu = tk.Frame(self.toile, bg=BLANC)
        self.fenetre = self.toile.create_window((0, 0), window=self.contenu, anchor="nw")
        self.contenu.bind("<Configure>", lambda _e: self.toile.configure(scrollregion=self.toile.bbox("all")))
        self.toile.bind("<Configure>", lambda e: self.toile.itemconfigure(self.fenetre, width=e.width))
        self.toile.bind("<Enter>", lambda _e: self.toile.bind_all("<MouseWheel>", self._molette))
        self.toile.bind("<Leave>", lambda _e: self.toile.unbind_all("<MouseWheel>"))
        self._message_central("Choisissez un rapport, la période et les filtres, puis cliquez sur « Consulter ». "
                              "« Imprimer (PDF) » produit le même rapport, prêt à signer.")

    def _molette(self, evenement):
        self.toile.yview_scroll(-1 if evenement.delta > 0 else 1, "units")

    # --- cycle de vie ------------------------------------------------------
    def au_affichage(self):
        try:
            self.utilisateurs = _liste_utilisateurs(self.app.conn, self.app.session)
            self.percepteurs = _liste_percepteurs(self.app.conn, self.app.session)
            self.devises = _liste_devises(self.app.conn, self.app.session)
        except ERREURS as erreur:
            self.lbl_message.config(text=str(erreur))
            return
        for cb, choix, cle, defaut in ((self.cb_utilisateur, self.utilisateurs, "utilisateur", TOUS_UTILISATEURS),
                                       (self.cb_percepteur, self.percepteurs, "percepteur", TOUS_PERCEPTEURS),
                                       (self.cb_devise, self.devises, "devise", TOUTES_DEVISES)):
            cb.config(values=list(choix))
            if self.vars[cle].get() not in choix:
                self.vars[cle].set(defaut)

    def reprendre(self, du, au, percepteur, devise):
        """Reprend les filtres du contrôle financier (bouton « Rapport d'audit... »)."""
        self.au_affichage()
        self.vars["du"].set(formater_date(du) if du else "")
        self.vars["au"].set(formater_date(au) if au else "")
        if percepteur in self.percepteurs:
            self.vars["percepteur"].set(percepteur)
        if devise in self.devises:
            self.vars["devise"].set(devise)

    def _filtres(self) -> dict:
        return {"type_": self.var_type.get(), "du": _lire_jour(self.vars["du"], "du"),
                "au": _lire_jour(self.vars["au"], "au"),
                "login": self.utilisateurs.get(self.vars["utilisateur"].get(), "") or None,
                "n_perc": self.percepteurs.get(self.vars["percepteur"].get()),
                "devise": self.devises.get(self.vars["devise"].get()), "avec_detail": self.var_detail.get()}

    # --- affichage du rapport ----------------------------------------------------
    def _vider(self):
        for w in self.contenu.winfo_children():
            w.destroy()

    def _message_central(self, texte):
        self._vider()
        tk.Label(self.contenu, text=texte, font=police(11), fg=GRIS, bg=BLANC, justify="left",
                 wraplength=px(1000)).pack(anchor="w", padx=px(16), pady=px(24))

    def consulter(self):
        try:
            d = audit_rapports.generer_rapport(self.app.conn, self.app.session, **self._filtres())
        except ERREURS as erreur:
            self.lbl_message.config(text=str(erreur))
            return
        self.lbl_message.config(text="")
        self._afficher(d)

    def _afficher(self, d):
        self._vider()
        c = self.contenu
        tk.Label(c, text=d["titre"], font=police(15, gras=True, titre=True), fg=NUIT, bg=BLANC, anchor="w").pack(
            fill="x", padx=px(12), pady=(px(10), 0))
        e = d["journal"]
        infos = list(d["filtres"]) + [f"Édité le {d['genere_le']} par {d['genere_par']}",
                                      f"Journal : {e['nb_lignes']} ligne(s), "
                                      + ("chaîne d'empreintes intacte" if e["ok"] else f"ANOMALIE à la ligne {e['anomalie']}")
                                      + f", dernière empreinte {e['derniere_empreinte'][:16]}"]
        if d["reinitialisation"]:
            infos.append("Les opérations antérieures à la dernière réinitialisation de l'application ne sont pas contrôlées.")
        tk.Label(c, text="\n".join(infos), font=police(9), fg=GRIS, bg=BLANC, anchor="w", justify="left").pack(
            fill="x", padx=px(12))
        sections = audit_rapports._sections_avec_resume(d)
        for s in sections:
            self._section(s)
        self.toile.yview_moveto(0)

    def _section(self, s):
        c = self.contenu
        tk.Label(c, text=s["titre"], font=police(12, gras=True, titre=True), fg=NUIT, bg=BLANC, anchor="w").pack(
            fill="x", padx=px(12), pady=(px(14), px(2)))
        for note in s["notes"]:
            tk.Label(c, text=note, font=police(9), fg=GRIS, bg=BLANC, anchor="w", justify="left",
                     wraplength=px(1100)).pack(fill="x", padx=px(12))
        if not s["lignes"]:
            tk.Label(c, text=s.get("vide", "Rien à signaler."), font=police(10, italique=True), fg=GRIS, bg=BLANC,
                     anchor="w").pack(fill="x", padx=px(12), pady=(px(2), 0))
            return
        total_largeur = sum(col[1] for col in s["colonnes"])
        colonnes = [(f"c{i}", col[0], max(40, int(col[1] * 1150 / total_largeur)), "e" if col[2] == "d" else "w")
                    for i, col in enumerate(s["colonnes"])]
        cadre, arbre = creer_arbre(c, colonnes, hauteur=min(len(s["lignes"]), 8))
        cadre.pack(fill="x", padx=px(12), pady=(px(2), 0))
        _regler_tags(arbre)
        for k, ligne in enumerate(s["lignes"][:LIMITE_ECRAN]):
            tag = s["couleurs"][k]
            arbre.insert("", "end", values=ligne, tags=(tag,) if tag else ())
        if len(s["lignes"]) > LIMITE_ECRAN:
            tk.Label(c, text=f"{len(s['lignes'])} ligne(s) : les {LIMITE_ECRAN} premières sont affichées ; le PDF et le "
                             f"CSV contiennent tout.", font=police(9, gras=True), fg=ORANGE, bg=BLANC, anchor="w").pack(
                fill="x", padx=px(12))

    def exporter(self, format_):
        _exporter(self, lambda: audit_rapports.exporter_rapport(self.app.conn, self.app.session, format_=format_,
                                                                **self._filtres()))

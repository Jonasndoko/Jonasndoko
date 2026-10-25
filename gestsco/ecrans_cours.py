"""Direction des études - fonctionnalité : GESTION DES COURS ET DES ENSEIGNANTS (écrans ; logique : cours.py).

1. Années et périodes      : années scolaires (dates, année en cours), semestres et périodes de chaque année.
2. Cours                   : le catalogue des cours, par niveau, option (humanités) et année d'étude.
3. Programme des classes   : pour une année et une classe : ouvrir les cours, régler les heures, attribuer le professeur.
4. Enseignants et classes  : pour un professeur : ses classes et ses cours ; l'associer à une classe ; le désigner TITULAIRE d'une classe
                             (lui seul lance le calcul automatique et les bulletins de cette classe, dans la page web des professeurs).
Deuxième fonctionnalité : PRÉSENCE DES ÉLÈVES (direction de discipline et des études : toutes les classes, lecture seule)
5. Élèves de toutes les classes : pour un jour, la présence de chaque classe et de chaque élève ; récapitulatif d'une période.
"""
import tkinter as tk
from tkinter import messagebox, ttk

import bulletins
import cours
import droits
import notes
import presence_eleves
import sections
import serveur_notes
from calendrier import SelecteurDate
from cours import ErreurCours
from ecrans_paiement import creer_arbre, vider_arbre
from theme import BLANC, FOND_CLAIR, GRIS, NUIT, ROUGE, VERT, carte, creer_bouton, creer_champ, definir_actif, police, px

ERREURS = (ErreurCours, PermissionError, notes.ErreurNotes)
AUCUN = "(aucune)"


def _etiquette(parent, texte):
    return tk.Label(parent, text=texte, font=police(10, gras=True), fg=NUIT, bg=BLANC)


def _titre(parent, texte):
    return tk.Label(parent, text=texte, font=police(12, gras=True, titre=True), fg=NUIT, bg=BLANC)


class _Panneau(tk.Frame):
    """Base : message d'état, accès à la base, droits relus à chaque affichage."""

    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.conn, self.session = self.app.conn, self.app.session
        self.lbl_message = tk.Label(self, text="", font=police(11, gras=True), bg=BLANC, anchor="w", justify="left",
                                    wraplength=px(1000))
        self.lbl_message.pack(side="bottom", fill="x", padx=px(26), pady=(0, px(8)))

    def message(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    def peut(self, droit):
        return cours.peut(self.conn, self.session, droit)

    def executer(self, action, succes=""):
        """Lance action(); affiche l'erreur métier ou le message de réussite. Retourne (réussi, résultat)."""
        try:
            r = action()
        except ERREURS as e:
            self.message(str(e))
            return False, None
        if succes:
            self.message(succes, VERT)
        return True, r

    def annees(self):
        try:
            return cours.lister_annees(self.conn, self.session)
        except ERREURS:
            return []

    def combo_annee(self, parent, commande):
        self.var_annee = tk.StringVar()
        cb = ttk.Combobox(parent, textvariable=self.var_annee, state="readonly", width=12, font=police(11))
        cb.bind("<<ComboboxSelected>>", lambda _e: commande())
        return cb

    def charger_annees(self, cb):
        liste = self.annees()
        cb.config(values=[a["annee"] for a in liste])
        if self.var_annee.get() not in [a["annee"] for a in liste]:
            courante = next((a["annee"] for a in liste if a["en_cours"]), liste[0]["annee"] if liste else "")
            self.var_annee.set(courante)


# ================================================================== 1) ANNÉES, SEMESTRES, PÉRIODES
class PanneauCalendrier(_Panneau):
    def __init__(self, parent, module):
        super().__init__(parent, module)
        self.var_nouvelle, self.var_debut, self.var_fin = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.var_lib, self.var_d, self.var_f = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.annee_choisie = None
        self.var_section = tk.StringVar(value=sections.libelle(sections.SECONDAIRE))     # calendrier de quelle section

        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(24), pady=px(12))
        corps.grid_columnconfigure(0, weight=2, uniform="c")
        corps.grid_columnconfigure(1, weight=3, uniform="c")
        corps.grid_rowconfigure(0, weight=1)

        # ---- gauche : années
        g = carte(corps, padx=px(14), pady=px(12))
        g.grid(row=0, column=0, sticky="nsew", padx=(0, px(8)))
        _titre(g, "Années scolaires").pack(anchor="w")
        cadre, self.arbre_annees = creer_arbre(g, [("annee", "Année", 90, "center"), ("dates", "Du - au", 190, "center"),
                                                   ("etat", "État", 80, "center"), ("sem", "Sem.", 40, "center")], hauteur=6)
        cadre.pack(fill="both", expand=True, pady=(px(6), px(8)))
        self.arbre_annees.bind("<<TreeviewSelect>>", lambda _e: self._annee_selectionnee())
        _etiquette(g, "Année (ex. 2026-2027)").pack(anchor="w")
        creer_champ(g, self.var_nouvelle, largeur=14).pack(anchor="w", ipady=px(3), pady=(px(2), px(4)))
        ligne = tk.Frame(g, bg=BLANC)
        ligne.pack(fill="x")
        for i, (t, v) in enumerate((("Début", self.var_debut), ("Fin", self.var_fin))):
            c = tk.Frame(ligne, bg=BLANC)
            c.pack(side="left", padx=(0, px(8)))
            _etiquette(c, t + " (jj/mm/aaaa)").pack(anchor="w")
            SelecteurDate(c, v, largeur=11).pack(pady=(px(2), 0))
        b = tk.Frame(g, bg=BLANC)
        b.pack(fill="x", pady=(px(8), 0))
        self.btn_creer = creer_bouton(b, "CRÉER L'ANNÉE", self.creer_annee, grand=False)
        self.btn_creer.pack(side="left", padx=(0, px(6)))
        self.btn_dates = creer_bouton(b, "DÉFINIR LES DATES", self.definir_dates, style="secondaire", grand=False)
        self.btn_dates.pack(side="left", padx=(0, px(6)))
        b2 = tk.Frame(g, bg=BLANC)
        b2.pack(fill="x", pady=(px(6), 0))
        self.btn_encours = creer_bouton(b2, "ANNÉE EN COURS", self.en_cours, style="secondaire", grand=False)
        self.btn_encours.pack(side="left", padx=(0, px(6)))
        self.btn_std = creer_bouton(b2, "STRUCTURE STANDARD", self.structure_standard, style="secondaire", grand=False)
        self.btn_std.pack(side="left")
        tk.Label(g, text="« Structure standard » crée le calendrier de la section choisie à droite (secondaire et humanitaire : 2 semestres de "
                         "2 périodes ; primaire : 3 trimestres de 2 périodes) en partageant les dates de l'année ; "
                         "corrigez-les ensuite à droite si besoin.", font=police(9), fg=GRIS, bg=BLANC, justify="left",
                 wraplength=px(430), anchor="w").pack(fill="x", pady=(px(6), 0))

        # ---- droite : semestres et périodes
        d = carte(corps, padx=px(14), pady=px(12))
        d.grid(row=0, column=1, sticky="nsew", padx=(px(8), 0))
        self.lbl_titre_cal = _titre(d, "Semestres et périodes")
        self.lbl_titre_cal.pack(anchor="w")
        ligne_section = tk.Frame(d, bg=BLANC)
        ligne_section.pack(fill="x", pady=(px(4), 0))
        _etiquette(ligne_section, "Calendrier de la section").pack(side="left", padx=(0, px(8)))
        cb_section = ttk.Combobox(ligne_section, textvariable=self.var_section, state="readonly", width=26, font=police(11),
                                  values=[t for _s, t in sections.SECTIONS])
        cb_section.pack(side="left")
        cb_section.bind("<<ComboboxSelected>>", lambda _e: self._section_changee())
        cadre = tk.Frame(d, bg=BLANC)
        cadre.pack(fill="both", expand=True, pady=(px(6), px(8)))
        self.arbre = ttk.Treeview(cadre, columns=("debut", "fin"), height=8, selectmode="browse")
        self.arbre_titre = "Semestre / période"
        self.arbre.heading("#0", text="Semestre / période", anchor="w")
        self.arbre.heading("debut", text="Début")
        self.arbre.heading("fin", text="Fin")
        self.arbre.column("#0", width=px(240))
        for c in ("debut", "fin"):
            self.arbre.column(c, width=px(110), anchor="center")
        self.arbre.pack(fill="both", expand=True)
        self.arbre.bind("<<TreeviewSelect>>", lambda _e: self._element_selectionne())
        ligne = tk.Frame(d, bg=BLANC)
        ligne.pack(fill="x")
        c = tk.Frame(ligne, bg=BLANC)
        c.pack(side="left", padx=(0, px(8)))
        _etiquette(c, "Libellé").pack(anchor="w")
        creer_champ(c, self.var_lib, largeur=18).pack(ipady=px(3), pady=(px(2), 0))
        for t, v in (("Du", self.var_d), ("Au", self.var_f)):
            c = tk.Frame(ligne, bg=BLANC)
            c.pack(side="left", padx=(0, px(8)))
            _etiquette(c, t + " (jj/mm/aaaa)").pack(anchor="w")
            SelecteurDate(c, v, largeur=11).pack(pady=(px(2), 0))
        b = tk.Frame(d, bg=BLANC)
        b.pack(fill="x", pady=(px(8), 0))
        self.btn_add_sem = creer_bouton(b, "AJOUTER UN SEMESTRE", self.ajouter_semestre, grand=False)
        self.btn_add_sem.pack(side="left", padx=(0, px(6)))
        self.btn_add_per = creer_bouton(b, "AJOUTER UNE PÉRIODE", self.ajouter_periode, grand=False)
        self.btn_add_per.pack(side="left", padx=(0, px(6)))
        self.btn_modif = creer_bouton(b, "MODIFIER", self.modifier, style="secondaire", grand=False)
        self.btn_modif.pack(side="left", padx=(0, px(6)))
        self.btn_suppr = creer_bouton(b, "SUPPRIMER", self.supprimer, style="danger", grand=False)
        self.btn_suppr.pack(side="left")
        tk.Label(d, text="Secondaire et humanitaire : 2 semestres de 2 périodes (4 périodes par an). Primaire : 3 trimestres de 2 périodes "
                         "(6 périodes par an). Une période s'ajoute sous le semestre ou trimestre choisi (clic dessus, puis « Ajouter une période »).",
                 font=police(9), fg=GRIS, bg=BLANC, anchor="w", wraplength=px(620), justify="left").pack(fill="x", pady=(px(6), 0))

    # ---------------------------------------------------------------- affichage
    def au_affichage(self):
        self._droits()
        self.recharger()

    def _section(self) -> str:
        """Code de la section dont on regarde le calendrier."""
        return next((s for s, t in sections.SECTIONS if t == self.var_section.get()), sections.SECONDAIRE)

    def _mot(self) -> str:
        return cours.mot_periode_longue(self._section())                     # « trimestre » au primaire, « semestre » ailleurs

    def _section_changee(self):
        mot = self._mot()
        self.btn_add_sem.config(text=f"AJOUTER UN {mot.upper()}")
        self.arbre.heading("#0", text=f"{mot.capitalize()} / période", anchor="w")
        self.var_lib.set("")
        self._afficher_calendrier()

    def _droits(self):
        for b, dr in ((self.btn_creer, "AJOUT"), (self.btn_std, "AJOUT"), (self.btn_add_sem, "AJOUT"), (self.btn_add_per, "AJOUT"),
                      (self.btn_dates, "MODIFICATION"), (self.btn_encours, "MODIFICATION"), (self.btn_modif, "MODIFICATION"),
                      (self.btn_suppr, "SUPPRESSION")):
            definir_actif(b, self.peut(dr))

    def recharger(self, garder=None):
        vider_arbre(self.arbre_annees)
        garder = garder or self.annee_choisie
        liste = self.annees()
        if not garder:
            garder = next((a["annee"] for a in liste if a["en_cours"]), None)
        for a in liste:
            dates = f"{a['debut']} - {a['fin']}" if a["avec_dates"] else "dates à définir"
            self.arbre_annees.insert("", "end", iid=a["annee"], values=(a["annee"], dates, "En cours" if a["en_cours"] else "",
                                                                       a["nb_semestres"]))
        if garder and self.arbre_annees.exists(garder):
            self.arbre_annees.selection_set(garder)
        else:
            self.annee_choisie = None
            self._afficher_calendrier()

    def _annee_selectionnee(self):
        sel = self.arbre_annees.selection()
        self.annee_choisie = sel[0] if sel else None
        self._afficher_calendrier()
        if self.annee_choisie:
            ok, c = self.executer(lambda: cours.calendrier_annee(self.conn, self.session, self.annee_choisie))
            if ok and c["avec_dates"]:
                self.var_debut.set(c["debut"])
                self.var_fin.set(c["fin"])

    def _afficher_calendrier(self):
        for i in self.arbre.get_children():
            self.arbre.delete(i)
        mot = self._mot()
        if not self.annee_choisie:
            self.lbl_titre_cal.config(text=f"{mot.capitalize()}s et périodes")
            return
        self.lbl_titre_cal.config(text=f"{mot.capitalize()}s et périodes de {self.annee_choisie}")
        ok, c = self.executer(lambda: cours.calendrier_annee(self.conn, self.session, self.annee_choisie, self._section()))
        if not ok:
            return
        for s in c["semestres"]:
            self.arbre.insert("", "end", iid=f"S{s['id']}", text=s["libelle"], values=(s["debut"], s["fin"]), open=True)
            for p in s["periodes"]:
                self.arbre.insert(f"S{s['id']}", "end", iid=f"P{p['id']}", text=p["libelle"], values=(p["debut"], p["fin"]))

    def _element_selectionne(self):
        sel = self.arbre.selection()
        if sel:
            self.var_lib.set(self.arbre.item(sel[0], "text"))
            self.var_d.set(self.arbre.set(sel[0], "debut"))
            self.var_f.set(self.arbre.set(sel[0], "fin"))

    # ---------------------------------------------------------------- actions : années
    def creer_annee(self):
        ok, a = self.executer(lambda: cours.creer_annee(self.conn, self.session, self.var_nouvelle.get(), self.var_debut.get(),
                                                        self.var_fin.get()))
        if ok:
            self.message(f"Année {a} créée.", VERT)
            self.var_nouvelle.set("")
            self.recharger(a)

    def _annee_ou_message(self):
        if not self.annee_choisie:
            self.message("Choisissez d'abord une année dans la liste.")
        return self.annee_choisie

    def definir_dates(self):
        a = self._annee_ou_message()
        if a and self.executer(lambda: cours.modifier_dates_annee(self.conn, self.session, a, self.var_debut.get(),
                                                                  self.var_fin.get()), f"Dates de l'année {a} enregistrées.")[0]:
            self.recharger(a)

    def en_cours(self):
        a = self._annee_ou_message()
        if a and self.executer(lambda: cours.definir_annee_en_cours(self.conn, self.session, a), f"{a} est l'année en cours.")[0]:
            self.recharger(a)

    def structure_standard(self):
        a = self._annee_ou_message()
        if a:
            ok, r = self.executer(lambda: cours.generer_structure_standard(self.conn, self.session, a, self._section()))
            if ok:
                self.message(f"Structure créée ({sections.libelle(self._section())}) : {r['semestres']} {self._mot()}s, "
                             f"{r['periodes']} périodes.", VERT)
                self.recharger(a)

    # ---------------------------------------------------------------- actions : semestres, périodes
    def ajouter_semestre(self):
        a = self._annee_ou_message()
        if a and self.executer(lambda: cours.ajouter_semestre(self.conn, self.session, a, self.var_lib.get(), self.var_d.get(),
                                                              self.var_f.get(), self._section()),
                               f"{self._mot().capitalize()} ajouté.")[0]:
            self.recharger(a)

    def _sel(self):
        sel = self.arbre.selection()
        return (sel[0][0], int(sel[0][1:])) if sel else (None, None)

    def ajouter_periode(self):
        a = self._annee_ou_message()
        genre, ident = self._sel()
        if genre == "P":                                   # une période choisie : on ajoute dans son semestre
            ident = int(self.arbre.parent(f"P{ident}")[1:])
        elif genre != "S":
            self.message("Cliquez d'abord sur le semestre qui contiendra la période.")
            return
        if a and self.executer(lambda: cours.ajouter_periode(self.conn, self.session, ident, self.var_lib.get(), self.var_d.get(),
                                                             self.var_f.get()), "Période ajoutée.")[0]:
            self.recharger(a)

    def modifier(self):
        genre, ident = self._sel()
        if not genre:
            self.message("Choisissez un semestre ou une période dans la liste.")
            return
        f = cours.modifier_semestre if genre == "S" else cours.modifier_periode
        if self.executer(lambda: f(self.conn, self.session, ident, self.var_lib.get(), self.var_d.get(), self.var_f.get()),
                         "Modification enregistrée.")[0]:
            self.recharger()

    def supprimer(self):
        genre, ident = self._sel()
        if not genre:
            self.message("Choisissez un semestre ou une période dans la liste.")
            return
        nom = self.arbre.item(f"{genre}{ident}", "text")
        if not messagebox.askyesno("Supprimer", f"Supprimer « {nom} »" + (" et ses périodes" if genre == "S" else "") + " ?", parent=self):
            return
        f = cours.supprimer_semestre if genre == "S" else cours.supprimer_periode
        if self.executer(lambda: f(self.conn, self.session, ident), "Supprimé.")[0]:
            self.recharger()


# ================================================================== 2) COURS
class PanneauCours(_Panneau):
    def __init__(self, parent, module):
        super().__init__(parent, module)
        self.v = {k: tk.StringVar() for k in ("libelle", "niveau", "option", "annee_etude", "heures")}
        self.v["heures"].set("2")
        self.var_filtre, self.var_recherche = tk.StringVar(value="Tous les niveaux"), tk.StringVar()
        self.niveaux, self.lignes, self.courant = [], {}, None

        f = carte(self, padx=px(16), pady=px(10))
        f.pack(fill="x", padx=px(24), pady=(px(12), px(6)))
        _titre(f, "Cours").pack(anchor="w")
        ligne = tk.Frame(f, bg=BLANC)
        ligne.pack(fill="x", pady=(px(4), 0))

        def champ(titre, widget_fabrique):
            c = tk.Frame(ligne, bg=BLANC)
            c.pack(side="left", padx=(0, px(10)))
            _etiquette(c, titre).pack(anchor="w")
            w = widget_fabrique(c)
            w.pack(pady=(px(2), 0))
            return w

        champ("Nom du cours", lambda c: creer_champ(c, self.v["libelle"], largeur=24)).configure()
        self.cb_niveau = champ("Niveau", lambda c: ttk.Combobox(c, textvariable=self.v["niveau"], state="readonly", width=16,
                                                                font=police(11)))
        self.cb_option = champ("Option (humanités)", lambda c: ttk.Combobox(c, textvariable=self.v["option"], state="readonly",
                                                                            width=20, font=police(11)))
        self.cb_annee = champ("Année d'étude", lambda c: ttk.Combobox(c, textvariable=self.v["annee_etude"], state="readonly",
                                                                      width=12, font=police(11)))
        champ("Heures / semaine", lambda c: ttk.Spinbox(c, from_=0, to=cours.HEURES_MAX, textvariable=self.v["heures"], width=6,
                                                        font=police(11)))
        self.cb_niveau.bind("<<ComboboxSelected>>", lambda _e: self._niveau_change())
        b = tk.Frame(f, bg=BLANC)
        b.pack(fill="x", pady=(px(8), 0))
        self.btn_ajouter = creer_bouton(b, "AJOUTER", self.ajouter, grand=False)
        self.btn_ajouter.pack(side="left", padx=(0, px(6)))
        self.btn_modifier = creer_bouton(b, "MODIFIER", self.modifier, style="secondaire", grand=False)
        self.btn_modifier.pack(side="left", padx=(0, px(6)))
        self.btn_activite = creer_bouton(b, "DÉSACTIVER / RÉACTIVER", self.activite, style="secondaire", grand=False)
        self.btn_activite.pack(side="left", padx=(0, px(6)))
        self.btn_suppr = creer_bouton(b, "SUPPRIMER", self.supprimer, style="danger", grand=False)
        self.btn_suppr.pack(side="left", padx=(0, px(6)))
        creer_bouton(b, "NOUVEAU", self.nouveau, style="secondaire", grand=False).pack(side="left")
        tk.Label(f, text="Option et année d'étude sont facultatives : laissées vides, le cours s'applique à tout le niveau.",
                 font=police(9), fg=GRIS, bg=BLANC, anchor="w").pack(fill="x", pady=(px(4), 0))

        filtre = tk.Frame(self, bg=BLANC)
        filtre.pack(fill="x", padx=px(24), pady=(px(4), px(2)))
        _etiquette(filtre, "Niveau :").pack(side="left")
        self.cb_filtre = ttk.Combobox(filtre, textvariable=self.var_filtre, state="readonly", width=22, font=police(11))
        self.cb_filtre.pack(side="left", padx=(px(6), px(14)))
        self.cb_filtre.bind("<<ComboboxSelected>>", lambda _e: self.actualiser())
        _etiquette(filtre, "Rechercher :").pack(side="left")
        creer_champ(filtre, self.var_recherche, largeur=26).pack(side="left", padx=(px(6), 0), ipady=px(3))
        self.var_recherche.trace_add("write", lambda *_a: self.actualiser())
        self.lbl_total = tk.Label(filtre, text="", font=police(10, gras=True), fg=GRIS, bg=BLANC)
        self.lbl_total.pack(side="right")
        cadre, self.arbre = creer_arbre(self, [
            ("cours", "Cours", 240, "w"), ("niveau", "Niveau", 150, "w"), ("option", "Option", 190, "w"),
            ("annee", "Année d'étude", 110, "center"), ("heures", "H/sem.", 70, "center"), ("classes", "Classes", 70, "center"),
            ("etat", "État", 80, "center")], hauteur=9)
        cadre.pack(fill="both", expand=True, padx=px(24), pady=(0, px(6)))
        self.arbre.tag_configure("inactif", foreground="#8A96B3")
        self.arbre.bind("<<TreeviewSelect>>", lambda _e: self._selection())

    def au_affichage(self):
        for b, dr in ((self.btn_ajouter, "AJOUT"), (self.btn_modifier, "MODIFICATION"), (self.btn_activite, "MODIFICATION"),
                      (self.btn_suppr, "SUPPRESSION")):
            definir_actif(b, self.peut(dr))
        ok, c = self.executer(lambda: cours.choix_cours(self.conn, self.session))
        self.niveaux = c["niveaux"] if ok else []
        self.cb_niveau.config(values=[n["libelle"] for n in self.niveaux])
        self.cb_filtre.config(values=["Tous les niveaux"] + [n["libelle"] for n in self.niveaux])
        self.actualiser()

    def _niveau(self, libelle):
        return next((n for n in self.niveaux if n["libelle"] == libelle), None)

    def _niveau_change(self):
        n = self._niveau(self.v["niveau"].get())
        self.cb_option.config(values=[""] + [o["libelle"] for o in n["options"]] if n else [""])
        self.cb_annee.config(values=[""] + list(n["annees_etude"]) if n else [""])
        self.v["option"].set("")
        self.v["annee_etude"].set("")

    def actualiser(self, garder=None):
        n = self._niveau(self.var_filtre.get())
        ok, liste = self.executer(lambda: cours.lister_cours(self.conn, self.session, n["code"] if n else None,
                                                             self.var_recherche.get()))
        vider_arbre(self.arbre)
        self.lignes = {}
        for c in liste if ok else []:
            iid = str(c["id"])
            self.lignes[iid] = c
            self.arbre.insert("", "end", iid=iid, tags=("" if c["actif"] else "inactif",),
                              values=(c["libelle"], c["niveau"], c["option"] or "-", c["annee_etude"] or "-", c["heures"],
                                      c["nb_classes"], "Actif" if c["actif"] else "Désactivé"))
        self.lbl_total.config(text=f"{len(self.lignes)} cours")
        if garder and garder in self.lignes:
            self.arbre.selection_set(garder)

    def _selection(self):
        sel = self.arbre.selection()
        self.courant = self.lignes.get(sel[0]) if sel else None
        c = self.courant
        if not c:
            return
        self.v["libelle"].set(c["libelle"])
        self.v["niveau"].set(c["niveau"])
        self._niveau_change()
        self.v["option"].set(c["option"])
        self.v["annee_etude"].set(c["annee_etude"])
        self.v["heures"].set(str(c["heures"]))

    def _saisie(self):
        n = self._niveau(self.v["niveau"].get())
        o = next((o for o in n["options"] if o["libelle"] == self.v["option"].get()), None) if n else None
        return {"libelle": self.v["libelle"].get(), "code_niveau": n["code"] if n else "", "code_option": o["code"] if o else "",
                "annee_etude": self.v["annee_etude"].get(), "heures_semaine": self.v["heures"].get()}

    def nouveau(self):
        self.arbre.selection_remove(*self.arbre.selection())
        self.courant = None
        self.v["libelle"].set("")
        self.v["heures"].set("2")
        self.message("")

    def ajouter(self):
        ok, i = self.executer(lambda: cours.ajouter_cours(self.conn, self.session, self._saisie()), "Cours enregistré.")
        if ok:
            self.v["libelle"].set("")
            self.actualiser(str(i))

    def _choisi(self):
        if not self.courant:
            self.message("Choisissez d'abord un cours dans la liste.")
        return self.courant

    def modifier(self):
        c = self._choisi()
        if c and self.executer(lambda: cours.modifier_cours(self.conn, self.session, c["id"], self._saisie()),
                               "Modification enregistrée.")[0]:
            self.actualiser(str(c["id"]))

    def activite(self):
        c = self._choisi()
        if c and self.executer(lambda: cours.changer_activite_cours(self.conn, self.session, c["id"], not c["actif"]),
                               "Cours réactivé." if not c["actif"] else "Cours désactivé.")[0]:
            self.actualiser(str(c["id"]))

    def supprimer(self):
        c = self._choisi()
        if c and messagebox.askyesno("Supprimer", f"Supprimer le cours « {c['libelle']} » ?", parent=self):
            if self.executer(lambda: cours.supprimer_cours(self.conn, self.session, c["id"]), "Cours supprimé.")[0]:
                self.courant = None
                self.actualiser()


# ================================================================== 3) PROGRAMME DES CLASSES
class PanneauProgramme(_Panneau):
    def __init__(self, parent, module):
        super().__init__(parent, module)
        self.var_classe, self.var_prof, self.var_ouvrir, self.var_heures = (tk.StringVar() for _ in range(4))
        self.classes, self.profs, self.a_ouvrir, self.lignes = {}, {}, {}, {}

        haut = carte(self, padx=px(16), pady=px(10))
        haut.pack(fill="x", padx=px(24), pady=(px(12), px(6)))
        ligne = tk.Frame(haut, bg=BLANC)
        ligne.pack(fill="x")
        _etiquette(ligne, "Année :").pack(side="left")
        self.cb_annee = self.combo_annee(ligne, self.recharger)
        self.cb_annee.pack(side="left", padx=(px(6), px(16)))
        _etiquette(ligne, "Classe :").pack(side="left")
        self.cb_classe = ttk.Combobox(ligne, textvariable=self.var_classe, state="readonly", width=46, font=police(11))
        self.cb_classe.pack(side="left", padx=(px(6), 0))
        self.cb_classe.bind("<<ComboboxSelected>>", lambda _e: self.recharger())
        self.lbl_info = tk.Label(haut, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_info.pack(fill="x", pady=(px(4), 0))

        cadre, self.arbre = creer_arbre(self, [
            ("cours", "Cours", 260, "w"), ("heures", "H/sem.", 80, "center"), ("matricule", "Matricule", 100, "center"),
            ("prof", "Professeur", 280, "w")], hauteur=9)
        self.arbre.configure(selectmode="extended")
        cadre.pack(fill="both", expand=True, padx=px(24), pady=(0, px(6)))
        self.arbre.tag_configure("sans", background="#FFF4DC")
        self.arbre.bind("<<TreeviewSelect>>", lambda _e: self._selection())

        bas = carte(self, padx=px(16), pady=px(10))
        bas.pack(fill="x", padx=px(24), pady=(0, px(6)))
        l1 = tk.Frame(bas, bg=BLANC)
        l1.pack(fill="x")
        _etiquette(l1, "Ouvrir un cours dans la classe :").pack(side="left")
        self.cb_ouvrir = ttk.Combobox(l1, textvariable=self.var_ouvrir, state="readonly", width=30, font=police(11))
        self.cb_ouvrir.pack(side="left", padx=(px(6), px(8)))
        self.btn_ouvrir = creer_bouton(l1, "OUVRIR", self.ouvrir_un, grand=False)
        self.btn_ouvrir.pack(side="left", padx=(0, px(6)))
        self.btn_tous = creer_bouton(l1, "OUVRIR TOUS LES COURS APPLICABLES", self.ouvrir_tous, style="secondaire", grand=False)
        self.btn_tous.pack(side="left")
        l2 = tk.Frame(bas, bg=BLANC)
        l2.pack(fill="x", pady=(px(8), 0))
        _etiquette(l2, "Professeur :").pack(side="left")
        self.cb_prof = ttk.Combobox(l2, textvariable=self.var_prof, state="readonly", width=46, font=police(11))
        self.cb_prof.pack(side="left", padx=(px(6), px(8)))
        self.btn_attribuer = creer_bouton(l2, "ATTRIBUER AUX COURS CHOISIS", self.attribuer, grand=False)
        self.btn_attribuer.pack(side="left", padx=(0, px(6)))
        self.btn_retirer_prof = creer_bouton(l2, "RETIRER LE PROFESSEUR", self.retirer_prof, style="secondaire", grand=False)
        self.btn_retirer_prof.pack(side="left")
        l3 = tk.Frame(bas, bg=BLANC)
        l3.pack(fill="x", pady=(px(8), 0))
        _etiquette(l3, "Heures / semaine du cours choisi :").pack(side="left")
        ttk.Spinbox(l3, from_=0, to=cours.HEURES_MAX, textvariable=self.var_heures, width=6, font=police(11)).pack(
            side="left", padx=(px(6), px(8)))
        self.btn_heures = creer_bouton(l3, "MODIFIER LES HEURES", self.modifier_heures, style="secondaire", grand=False)
        self.btn_heures.pack(side="left", padx=(0, px(6)))
        self.btn_retirer = creer_bouton(l3, "RETIRER LE COURS DE LA CLASSE", self.retirer_cours, style="danger", grand=False)
        self.btn_retirer.pack(side="left")
        tk.Label(self, text="Cours sur fond jaune = sans professeur. Choisissez plusieurs cours (Ctrl ou Maj + clic) pour attribuer "
                            "le même professeur d'un coup.", font=police(9), fg=GRIS, bg=BLANC, anchor="w").pack(
            fill="x", padx=px(26), pady=(0, px(2)))

    def au_affichage(self):
        for b, dr in ((self.btn_ouvrir, "AJOUT"), (self.btn_tous, "AJOUT"), (self.btn_attribuer, "AJOUT"),
                      (self.btn_retirer_prof, "MODIFICATION"), (self.btn_heures, "MODIFICATION"), (self.btn_retirer, "SUPPRESSION")):
            definir_actif(b, self.peut(dr))
        self.charger_annees(self.cb_annee)
        ok, liste = self.executer(lambda: cours.lister_classes(self.conn, self.session))
        self.classes = {f"{c['designation']}  ({c['niveau']}" + (f" - {c['option']}" if c["option"] else "") + ")": c["n_classe"]
                        for c in (liste if ok else [])}
        self.cb_classe.config(values=list(self.classes))
        if self.var_classe.get() not in self.classes:
            self.var_classe.set(next(iter(self.classes), ""))
        self.recharger()
        self._maj_titulaire()

    def _contexte(self):
        return self.var_annee.get(), self.classes.get(self.var_classe.get())

    def recharger(self):
        annee, classe = self._contexte()
        vider_arbre(self.arbre)
        self.lignes, self.a_ouvrir = {}, {}
        self.cb_ouvrir.config(values=[])
        self.var_ouvrir.set("")
        if not annee or classe is None:
            self.lbl_info.config(text="Créez d'abord une année scolaire et des classes." if not annee else "Aucune classe.")
            return
        ok, p = self.executer(lambda: cours.programme_classe(self.conn, self.session, annee, classe))
        if not ok:
            return
        for l in p["cours"]:
            iid = str(l["id"])
            self.lignes[iid] = l
            self.arbre.insert("", "end", iid=iid, tags=("" if l["matricule"] else "sans",),
                              values=(l["cours"], l["heures"], l["matricule"] or "-", l["professeur"] or "(sans professeur)"))
        self.a_ouvrir = {f"{c['libelle']}  ({c['heures']} h)": c["id_cours"] for c in p["a_ouvrir"]}
        self.cb_ouvrir.config(values=list(self.a_ouvrir))
        sans = sum(1 for l in p["cours"] if not l["matricule"])
        self.lbl_info.config(text=f"{len(p['cours'])} cours ouvert(s) en {annee}, dont {sans} sans professeur  -  "
                                  f"{len(self.a_ouvrir)} cours applicable(s) pas encore ouvert(s)  -  "
                                  f"{sum(l['heures'] for l in p['cours'])} h/semaine au total.")
        ok, profs = self.executer(lambda: cours.lister_professeurs(self.conn, self.session, annee))
        self.profs = {f"{x['nom_complet']}  ({x['matricule']}) - {x['heures']} h": x["matricule"] for x in (profs if ok else [])}
        self.cb_prof.config(values=list(self.profs))
        if self.var_prof.get() not in self.profs:
            self.var_prof.set("")

    def _selection(self):
        sel = self.arbre.selection()
        if len(sel) == 1:
            self.var_heures.set(str(self.lignes[sel[0]]["heures"]))

    def _ids(self):
        ids = [int(i) for i in self.arbre.selection()]
        if not ids:
            self.message("Choisissez au moins un cours dans la liste.")
        return ids

    def ouvrir_un(self):
        annee, classe = self._contexte()
        i = self.a_ouvrir.get(self.var_ouvrir.get())
        if i is None:
            self.message("Choisissez le cours à ouvrir dans la liste déroulante.")
        elif self.executer(lambda: cours.ouvrir_cours(self.conn, self.session, annee, classe, [i]), "Cours ouvert.")[0]:
            self.recharger()

    def ouvrir_tous(self):
        annee, classe = self._contexte()
        ok, n = self.executer(lambda: cours.ouvrir_cours(self.conn, self.session, annee, classe))
        if ok:
            self.message(f"{n} cours ouvert(s)." if n else "Aucun cours à ouvrir : tout est déjà ouvert.", VERT)
            self.recharger()

    def _rapport(self, r):
        txt = f"{r['faits']} cours mis à jour." + (f" {r['inchanges']} déjà attribué(s) à ce professeur." if r["inchanges"] else "")
        self.message(txt, VERT)

    def attribuer(self):
        ids = self._ids()
        m = self.profs.get(self.var_prof.get())
        if ids and not m:
            self.message("Choisissez le professeur dans la liste déroulante.")
        elif ids:
            ok, r = self.executer(lambda: cours.attribuer_professeur(self.conn, self.session, ids, m))
            if ok:
                self._rapport(r)
                self.recharger()

    def retirer_prof(self):
        ids = self._ids()
        if ids:
            ok, r = self.executer(lambda: cours.attribuer_professeur(self.conn, self.session, ids, ""))
            if ok:
                self.message(f"Professeur retiré de {r['faits']} cours.", VERT)
                self.recharger()

    def modifier_heures(self):
        ids = self._ids()
        if len(ids) != 1:
            if ids:
                self.message("Choisissez un seul cours pour changer ses heures.")
        elif self.executer(lambda: cours.modifier_heures(self.conn, self.session, ids[0], self.var_heures.get()),
                           "Heures enregistrées.")[0]:
            self.recharger()

    def retirer_cours(self):
        ids = self._ids()
        if ids and messagebox.askyesno("Retirer", f"Retirer {len(ids)} cours de cette classe ?\n"
                                                  "Les professeurs attribués à ces cours seront détachés.", parent=self):
            for i in ids:
                if not self.executer(lambda i=i: cours.retirer_cours_de_classe(self.conn, self.session, i))[0]:
                    break
            else:
                self.message("Cours retiré(s) de la classe.", VERT)
            self.recharger()


# ================================================================== 4) ENSEIGNANTS ET CLASSES
class PanneauEnseignants(_Panneau):
    def __init__(self, parent, module):
        super().__init__(parent, module)
        self.var_recherche, self.var_classe = tk.StringVar(), tk.StringVar()
        self.var_seuls = tk.BooleanVar(value=False)
        self.classes, self.profs, self.lignes, self.matricule = {}, {}, {}, None

        haut = carte(self, padx=px(16), pady=px(10))
        haut.pack(fill="x", padx=px(24), pady=(px(12), px(6)))
        ligne = tk.Frame(haut, bg=BLANC)
        ligne.pack(fill="x")
        _etiquette(ligne, "Année :").pack(side="left")
        self.cb_annee = self.combo_annee(ligne, lambda: (self.recharger(), self._maj_titulaire()))
        self.cb_annee.pack(side="left", padx=(px(6), px(16)))
        _etiquette(ligne, "Rechercher un agent :").pack(side="left")
        creer_champ(ligne, self.var_recherche, largeur=24).pack(side="left", padx=(px(6), px(12)), ipady=px(3))
        self.var_recherche.trace_add("write", lambda *_a: self.recharger())
        tk.Checkbutton(ligne, text="Seulement ceux qui ont des cours", variable=self.var_seuls, command=self.recharger, bg=BLANC,
                       font=police(10), activebackground=BLANC, fg=NUIT).pack(side="left")

        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(24))
        corps.grid_columnconfigure(0, weight=1, uniform="e")
        corps.grid_columnconfigure(1, weight=1, uniform="e")
        corps.grid_rowconfigure(0, weight=1)
        g = tk.Frame(corps, bg=BLANC)
        g.grid(row=0, column=0, sticky="nsew", padx=(0, px(8)))
        _titre(g, "Agents").pack(anchor="w")
        cadre, self.arbre = creer_arbre(g, [("nom", "Nom complet", 200, "w"), ("fonction", "Fonction", 110, "w"),
                                            ("classes", "Classes", 60, "center"), ("cours", "Cours", 55, "center"),
                                            ("heures", "H/sem.", 60, "center")], hauteur=9)
        cadre.pack(fill="both", expand=True)
        self.arbre.bind("<<TreeviewSelect>>", lambda _e: self._selection())
        d = tk.Frame(corps, bg=BLANC)
        d.grid(row=0, column=1, sticky="nsew", padx=(px(8), 0))
        self.lbl_titre = _titre(d, "Classes et cours du professeur")
        self.lbl_titre.pack(anchor="w")
        cadre, self.arbre_cc = creer_arbre(d, [("classe", "Classe", 130, "w"), ("niveau", "Niveau", 100, "w"),
                                               ("cours", "Cours", 170, "w"), ("heures", "H/sem.", 60, "center")], hauteur=9)
        self.arbre_cc.configure(selectmode="extended")
        cadre.pack(fill="both", expand=True)

        bas = carte(self, padx=px(16), pady=px(10))
        bas.pack(fill="x", padx=px(24), pady=(px(6), px(6)))
        ligne = tk.Frame(bas, bg=BLANC)
        ligne.pack(fill="x")
        _etiquette(ligne, "Associer l'agent choisi à la classe :").pack(side="left")
        self.cb_classe = ttk.Combobox(ligne, textvariable=self.var_classe, state="readonly", width=46, font=police(11))
        self.cb_classe.pack(side="left", padx=(px(6), px(8)))
        self.btn_associer = creer_bouton(ligne, "LUI DONNER LES COURS SANS PROFESSEUR DE CETTE CLASSE", self.associer, grand=False)
        self.btn_associer.pack(side="left")
        l2 = tk.Frame(bas, bg=BLANC)
        l2.pack(fill="x", pady=(px(8), 0))
        self.btn_detacher = creer_bouton(l2, "DÉTACHER LES COURS CHOISIS (à droite)", self.detacher, style="danger", grand=False)
        self.btn_detacher.pack(side="left")
        l3 = tk.Frame(bas, bg=BLANC)
        l3.pack(fill="x", pady=(px(8), 0))
        self.btn_titulaire = creer_bouton(l3, "DÉSIGNER L'AGENT CHOISI TITULAIRE DE LA CLASSE CI-DESSUS", self.designer_titulaire, grand=False)
        self.btn_titulaire.pack(side="left", padx=(0, px(10)))
        self.btn_retirer_tit = creer_bouton(l3, "RETIRER LE TITULAIRE", self.retirer_titulaire, style="danger", grand=False)
        self.btn_retirer_tit.pack(side="left", padx=(0, px(10)))
        self.lbl_titulaire = tk.Label(l3, text="", font=police(10, gras=True), fg=GRIS, bg=BLANC, anchor="w", justify="left")
        self.lbl_titulaire.pack(side="left", fill="x", expand=True)
        self.cb_classe.bind("<<ComboboxSelected>>", lambda _e: self._maj_titulaire())
        tk.Label(bas, text="Un cours précis se donne dans l'onglet « Programme des classes ». Ici, on associe un professeur à une "
                           "classe : il reçoit ses cours encore sans professeur. Le titulaire d'une classe (un seul par classe et par année) est le seul "
                           "professeur qui voit l'onglet « Bulletins » de la page web : calcul des résultats, bulletins, liste des résultats et "
                           "proclamation de sa classe.", font=police(9), fg=GRIS, bg=BLANC, anchor="w",
                 justify="left", wraplength=px(1000)).pack(fill="x", pady=(px(6), 0))

        # ---- saisie des points par les professeurs (page web)
        web = carte(self, padx=px(16), pady=px(10))
        web.pack(fill="x", padx=px(24), pady=(0, px(6)))
        _titre(web, "Saisie des points par les professeurs (ordinateur, tablette, téléphone)").pack(anchor="w")
        lw = tk.Frame(web, bg=BLANC)
        lw.pack(fill="x", pady=(px(4), 0))
        self.btn_compte = creer_bouton(lw, "CRÉER LE COMPTE DE L'AGENT CHOISI", self.creer_compte, grand=False)
        self.btn_compte.pack(side="left", padx=(0, px(10)))
        self.btn_serveur = creer_bouton(lw, "DÉMARRER LE SERVEUR", self.basculer_serveur, style="secondaire", grand=False)
        self.btn_serveur.pack(side="left", padx=(0, px(10)))
        self.lbl_serveur = tk.Label(lw, text="", font=police(10, gras=True), fg=GRIS, bg=BLANC, anchor="w", justify="left")
        self.lbl_serveur.pack(side="left", fill="x", expand=True)

    def au_affichage(self):
        definir_actif(self.btn_associer, self.peut("AJOUT"))
        definir_actif(self.btn_detacher, self.peut("MODIFICATION"))
        definir_actif(self.btn_titulaire, self.peut("MODIFICATION"))
        definir_actif(self.btn_retirer_tit, self.peut("MODIFICATION"))
        definir_actif(self.btn_compte, droits.est_admin(self.conn, self.session))
        self._etat_serveur()
        self.charger_annees(self.cb_annee)
        ok, liste = self.executer(lambda: cours.lister_classes(self.conn, self.session))
        self.classes = {f"{c['designation']}  ({c['niveau']}" + (f" - {c['option']}" if c["option"] else "") + ")": c["n_classe"]
                        for c in (liste if ok else [])}
        self.cb_classe.config(values=list(self.classes))
        if self.var_classe.get() not in self.classes:
            self.var_classe.set(next(iter(self.classes), ""))
        self.recharger()

    def recharger(self, garder=None):
        annee = self.var_annee.get()
        garder = garder or self.matricule
        vider_arbre(self.arbre)
        if not annee:
            return
        ok, liste = self.executer(lambda: cours.lister_professeurs(self.conn, self.session, annee, self.var_recherche.get(),
                                                                   self.var_seuls.get()))
        for p in liste if ok else []:
            self.arbre.insert("", "end", iid=p["matricule"], values=(p["nom_complet"], p["fonction"], p["nb_classes"],
                                                                     p["nb_cours"], p["heures"]))
        if garder and self.arbre.exists(garder):
            self.arbre.selection_set(garder)
        else:
            self.matricule = None
            self._afficher_classes()

    def _selection(self):
        sel = self.arbre.selection()
        self.matricule = sel[0] if sel else None
        self._afficher_classes()

    def _afficher_classes(self):
        vider_arbre(self.arbre_cc)
        self.lignes = {}
        if not self.matricule:
            self.lbl_titre.config(text="Classes et cours du professeur")
            return
        ok, r = self.executer(lambda: cours.classes_du_professeur(self.conn, self.session, self.var_annee.get(), self.matricule))
        if not ok:
            return
        self.lbl_titre.config(text=f"{self.arbre.set(self.matricule, 'nom')} : {r['nb_classes']} classe(s), {r['nb_cours']} cours, "
                                   f"{r['heures']} h/sem.")
        for l in r["lignes"]:
            self.lignes[str(l["id"])] = l
            self.arbre_cc.insert("", "end", iid=str(l["id"]), values=(l["classe"], l["niveau"], l["cours"], l["heures"]))

    def _agent(self):
        if not self.matricule:
            self.message("Choisissez d'abord un agent dans la liste de gauche.")
        return self.matricule

    def associer(self):
        m = self._agent()
        classe = self.classes.get(self.var_classe.get())
        if not m or classe is None:
            return
        annee = self.var_annee.get()

        def action():
            p = cours.programme_classe(self.conn, self.session, annee, classe)
            ids = [l["id"] for l in p["cours"] if not l["matricule"]]
            if not ids:
                raise ErreurCours("Cette classe n'a aucun cours sans professeur pour " + annee + ". Ouvrez d'abord ses cours "
                                  "(onglet « Programme des classes »).")
            return cours.attribuer_professeur(self.conn, self.session, ids, m)
        ok, r = self.executer(action)
        if ok:
            self.message(f"{r['faits']} cours attribué(s) dans {self.var_classe.get().split('  (')[0]}.", VERT)
            self.recharger(m)

    def detacher(self):
        m = self._agent()
        ids = [int(i) for i in self.arbre_cc.selection()]
        if m and not ids:
            self.message("Choisissez les cours à détacher dans la liste de droite.")
        elif m:
            ok, r = self.executer(lambda: cours.attribuer_professeur(self.conn, self.session, ids, ""))
            if ok:
                self.message(f"{r['faits']} cours détaché(s).", VERT)
                self.recharger(m)

    # ---------------------------------------------------------------- titulaire de classe (calcul automatique et bulletins)
    def _maj_titulaire(self):
        classe, annee = self.classes.get(self.var_classe.get()), self.var_annee.get()
        self.lbl_titulaire.config(text="", fg=GRIS)
        if classe is None or not annee:
            return
        ok, liste = self.executer(lambda: bulletins.lister_titulaires(self.conn, self.session, annee))
        if ok:
            t = liste.get(classe)
            self.lbl_titulaire.config(text=f"Titulaire {annee} : {t['nom_complet']}" if t else f"Titulaire {annee} : aucun",
                                      fg=VERT if t else GRIS)

    def designer_titulaire(self):
        m = self._agent()
        classe = self.classes.get(self.var_classe.get())
        if not m or classe is None:
            return
        annee = self.var_annee.get()
        ok, _r = self.executer(lambda: bulletins.designer_titulaire(self.conn, self.session, annee, classe, m))
        if ok:
            self.message(f"{self.arbre.set(m, 'nom')} est titulaire de {self.var_classe.get().split('  (')[0]} pour {annee}. "
                         "Elle (il) verra l'onglet « Bulletins » à sa prochaine connexion à la page web.", VERT)
            self._maj_titulaire()

    def retirer_titulaire(self):
        classe, annee = self.classes.get(self.var_classe.get()), self.var_annee.get()
        if classe is None:
            return
        if not messagebox.askyesno("Retirer le titulaire", f"Retirer le titulaire de {self.var_classe.get().split('  (')[0]} pour {annee} ?\n\n"
                                   "Il ne pourra plus calculer les résultats ni imprimer les bulletins de cette classe.", parent=self):
            return
        ok, _r = self.executer(lambda: bulletins.retirer_titulaire(self.conn, self.session, annee, classe))
        if ok:
            self.message("Titulaire retiré.", VERT)
            self._maj_titulaire()

    # ---------------------------------------------------------------- page web des professeurs
    def creer_compte(self):
        m = self._agent()
        if not m:
            return
        ok, r = self.executer(lambda: notes.creer_compte_professeur(self.conn, self.session, m))
        if ok:
            self.message(f"Compte créé pour {r['nom']}.", VERT)
            messagebox.showinfo("Compte du professeur", f"Compte créé pour {r['nom']}.\n\nIdentifiant : {r['login']}\n"
                                f"Mot de passe provisoire : {r['mdp_temporaire']}\n\nNotez-le et remettez-le au professeur : "
                                "il devra le changer à sa première connexion. Il ne sera plus affiché.", parent=self)

    def _etat_serveur(self):
        srv = getattr(self.app, "serveur_notes", None)
        if srv:
            adresses = serveur_notes.adresses_locales() or ["(adresse de cet ordinateur)"]
            self.lbl_serveur.config(text="En marche. Sur le Wi-Fi de l'école, le professeur ouvre : " +
                                    "   ou   ".join(f"http://{a}:{srv.port}" for a in adresses), fg=VERT)
            self.btn_serveur.config(text="ARRÊTER LE SERVEUR")
        else:
            self.lbl_serveur.config(text="Arrêté. Les professeurs ne peuvent pas se connecter.", fg=GRIS)
            self.btn_serveur.config(text="DÉMARRER LE SERVEUR")

    def basculer_serveur(self):
        srv = getattr(self.app, "serveur_notes", None)
        try:
            if srv:
                srv.arreter()
                self.app.serveur_notes = None
            else:
                self.app.serveur_notes = serveur_notes.Serveur().demarrer()
        except OSError as e:
            self.message(f"Impossible de démarrer le serveur (port déjà utilisé ?) : {e}")
        self._etat_serveur()


# ================================================================== 5) PRÉSENCE DES ÉLÈVES (toutes les classes)
class PanneauPresenceEleves(_Panneau):
    """Lecture seule : le pointage est fait par les professeurs (page web). Règle de la journée : présent seulement s'il a assisté
    à tous les cours pointés ce jour-là."""

    def __init__(self, parent, module):
        super().__init__(parent, module)
        self.var_jour, self.var_debut, self.var_fin = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.classes, self.classe = {}, None

        haut = carte(self, padx=px(16), pady=px(10))
        haut.pack(fill="x", padx=px(24), pady=(px(12), px(6)))
        ligne = tk.Frame(haut, bg=BLANC)
        ligne.pack(fill="x")
        _etiquette(ligne, "Année :").pack(side="left")
        self.cb_annee = self.combo_annee(ligne, self.recharger)
        self.cb_annee.pack(side="left", padx=(px(6), px(16)))
        _etiquette(ligne, "Jour :").pack(side="left")
        creer_bouton(ligne, "◄", lambda: self._decaler(-1), style="secondaire", grand=False).pack(side="left", padx=(px(6), px(4)))
        SelecteurDate(ligne, self.var_jour, largeur=11).pack(side="left")
        creer_bouton(ligne, "►", lambda: self._decaler(1), style="secondaire", grand=False).pack(side="left", padx=(px(4), px(8)))
        creer_bouton(ligne, "Aujourd'hui", self._aujourdhui, style="secondaire", grand=False).pack(side="left")
        self.var_jour.trace_add("write", lambda *_a: self._jour_modifie())
        self.lbl_info = tk.Label(haut, text="", font=police(10, gras=True), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_info.pack(fill="x", pady=(px(4), 0))

        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(24))
        corps.grid_columnconfigure(0, weight=1, uniform="p")
        corps.grid_columnconfigure(1, weight=1, uniform="p")
        corps.grid_rowconfigure(0, weight=1)
        g = tk.Frame(corps, bg=BLANC)
        g.grid(row=0, column=0, sticky="nsew", padx=(0, px(8)))
        _titre(g, "Classes").pack(anchor="w")
        cadre, self.arbre = creer_arbre(g, [("classe", "Classe", 130, "w"), ("eff", "Élèves", 60, "center"),
                                            ("pres", "Présents", 70, "center"), ("abs", "Absents", 70, "center"),
                                            ("nr", "Non renseignés", 100, "center"), ("cours", "Cours pointés", 90, "center")], hauteur=9)
        cadre.pack(fill="both", expand=True)
        self.arbre.tag_configure("total", font=police(10, gras=True))
        self.arbre.bind("<<TreeviewSelect>>", lambda _e: self._classe_choisie())
        d = tk.Frame(corps, bg=BLANC)
        d.grid(row=0, column=1, sticky="nsew", padx=(px(8), 0))
        self.lbl_titre = _titre(d, "Élèves de la classe")
        self.lbl_titre.pack(anchor="w")
        cadre, self.arbre_el = creer_arbre(d, [("nom", "Élève", 190, "w"), ("jour", "Journée", 80, "center"),
                                               ("detail", "Détail (cours)", 220, "w")], hauteur=9)
        cadre.pack(fill="both", expand=True)
        self.arbre_el.tag_configure("P", background="#E8F3EA")
        self.arbre_el.tag_configure("A", background="#FDECEA")
        self.arbre_el.tag_configure("N", foreground="#8A96B3")

        bas = carte(self, padx=px(16), pady=px(10))
        bas.pack(fill="x", padx=px(24), pady=(px(6), px(6)))
        lb = tk.Frame(bas, bg=BLANC)
        lb.pack(fill="x")
        _etiquette(lb, "Récapitulatif de la classe choisie, du").pack(side="left")
        SelecteurDate(lb, self.var_debut, largeur=11).pack(side="left", padx=(px(6), px(6)))
        _etiquette(lb, "au").pack(side="left")
        SelecteurDate(lb, self.var_fin, largeur=11).pack(side="left", padx=(px(6), px(10)))
        creer_bouton(lb, "AFFICHER LE RÉCAPITULATIF", self.recapitulatif, style="secondaire", grand=False).pack(side="left", padx=(0, px(6)))
        creer_bouton(lb, "RETOUR AU JOUR", self._afficher_eleves, style="secondaire", grand=False).pack(side="left")
        tk.Label(bas, text="Journée : un élève est présent seulement s'il est présent à tous les cours pointés ce jour-là ; absent à un seul "
                           "cours, il est absent pour la journée. Le pointage est fait par les professeurs (page web).",
                 font=police(9), fg=GRIS, bg=BLANC, anchor="w", justify="left", wraplength=px(1000)).pack(fill="x", pady=(px(6), 0))

    def annees(self):                      # consultation seule : le droit « Présence des élèves » suffit (pas besoin de la Direction des études)
        try:
            return presence_eleves.lister_annees(self.conn, self.session)
        except ERREURS:
            return []

    def au_affichage(self):
        self.charger_annees(self.cb_annee)
        if not self.var_jour.get():
            self._aujourdhui()
        if not self.var_debut.get():
            self.var_debut.set(self.var_jour.get())
            self.var_fin.set(self.var_jour.get())
        self.recharger()

    def _aujourdhui(self):
        from datetime import date
        self.var_jour.set(date.today().strftime("%d/%m/%Y"))

    def _decaler(self, n):
        from datetime import datetime, timedelta
        try:
            d = datetime.strptime(self.var_jour.get().strip(), "%d/%m/%Y") + timedelta(days=n)
        except ValueError:
            return self.message("Écrivez la date au format jj/mm/aaaa.")
        self.var_jour.set(d.strftime("%d/%m/%Y"))

    def _jour_modifie(self):
        if getattr(self, "_pret", False) and len(self.var_jour.get().strip()) == 10:
            self.recharger()

    def recharger(self):
        self._pret = True
        annee = self.var_annee.get()
        vider_arbre(self.arbre)
        self.classes = {}
        if not annee:
            self.lbl_info.config(text="Aucune année scolaire.")
            return
        ok, r = self.executer(lambda: presence_eleves.classes_du_jour(self.conn, self.session, annee, self.var_jour.get()))
        if not ok:
            self.lbl_info.config(text="")
            return
        self.message("")
        for c in r["classes"]:
            iid = str(c["n_classe"])
            self.classes[iid] = c
            self.arbre.insert("", "end", iid=iid, values=(c["classe"], c["effectif"], c["presents"], c["absents"],
                                                          c["non_renseignes"], c["cours_pointes"]))
        t = r["totaux"]
        self.lbl_info.config(text=f"{r['date']}  -  {t['effectif']} élèves : {t['presents']} présents, {t['absents']} absents, "
                                  f"{t['non_renseignes']} non renseignés.")
        if self.classe in self.classes:
            self.arbre.selection_set(self.classe)
        else:
            self.classe = None
            self._afficher_eleves()

    def _classe_choisie(self):
        sel = self.arbre.selection()
        self.classe = sel[0] if sel else None
        self._afficher_eleves()

    def _afficher_eleves(self):
        vider_arbre(self.arbre_el)
        for col, titre in (("nom", "Élève"), ("jour", "Journée"), ("detail", "Détail (cours)")):
            self.arbre_el.heading(col, text=titre)
        if not self.classe:
            self.lbl_titre.config(text="Élèves de la classe")
            return
        ok, r = self.executer(lambda: presence_eleves.eleves_de_la_classe(self.conn, self.session, self.var_annee.get(),
                                                                          int(self.classe), self.var_jour.get()))
        if not ok:
            return
        self.lbl_titre.config(text=f"{r['classe']} - {r['date']}")
        for i, e in enumerate(r["eleves"]):
            j = e["journee"]
            detail = ", ".join(f"{c['cours']} ({'P' if c['statut'] == 'P' else 'A'})" for c in e["cours"]) or "pas encore pointé"
            self.arbre_el.insert("", "end", iid=f"e{i}", tags=(j or "N",),
                                 values=(e["nom_complet"], {"P": "Présent", "A": "Absent"}.get(j, "-"), detail))

    def recapitulatif(self):
        if not self.classe:
            return self.message("Choisissez d'abord une classe dans la liste de gauche.")
        ok, r = self.executer(lambda: presence_eleves.recapitulatif_classe(self.conn, self.session, self.var_annee.get(), int(self.classe),
                                                                           self.var_debut.get(), self.var_fin.get()))
        if not ok:
            return
        vider_arbre(self.arbre_el)
        for col, titre in (("nom", "Élève"), ("jour", "Jours présent / absent"), ("detail", "Taux de présence")):
            self.arbre_el.heading(col, text=titre)
        self.lbl_titre.config(text=f"{r['classe']} - du {r['debut']} au {r['fin']} ({r['jours_pointes']} jour(s) pointé(s))")
        for i, e in enumerate(r["eleves"]):
            self.arbre_el.insert("", "end", iid=f"r{i}", tags=("" if e["taux"] is None else ("A" if e["jours_absents"] else "P"),),
                                 values=(e["nom_complet"], f"{e['jours_presents']} / {e['jours_absents']}",
                                         "-" if e["taux"] is None else f"{e['taux']} %"))
        self.message("")

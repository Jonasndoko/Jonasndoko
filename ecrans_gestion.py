"""Module « Présence des élèves » (écrans ; la logique est dans presence_eleves.py).

Consultation seule de la présence de toutes les classes (direction de discipline et des études). Le module « Gestion scolaire » n'existe plus :
ses fonctionnalités (années et périodes, cours, programme des classes, enseignants et classes) sont dans la Direction des études (version en ligne).
Même présentation que « Gestion du personnel » : première ligne = la fonctionnalité, deuxième ligne = ses onglets.
"""
import tkinter as tk

import presence_eleves
from theme import (BLANC, BLEU, BLEU_PALE, BORDURE, FOND_CLAIR, GRIS, NUIT, NUIT_CLAIR, actions_barre_module, barre_haute,
                   police, px, ZoneAdaptative)


class ModulePresenceEleves(tk.Frame):
    """Module « Présence des élèves » : consultation seule de la présence aux cours de toutes les classes (pointée par les professeurs).
    Pour le Directeur de discipline et la Directrice des études (droit « Lecture » sur « Présence des élèves »). Ce compte ne voit
    ni les cours, ni les enseignants, ni les points : seulement qui est présent ou absent."""
    TITRE = "Présence des élèves"
    CLE_DROITS = "presence_eleves"
    FONCTIONNALITES = (("presence_eleves", "Présence des élèves", (("presence_classes", "Élèves de toutes les classes"),)),)
    ONGLET_DEFAUT = "presence_classes"

    def __init__(self, app, onglet=None):
        super().__init__(app, bg=BLANC)
        import ecrans_cours
        self.app = app
        self.autorise = self._autorise(app)
        self.classes = self._panneaux(ecrans_cours)
        barre = barre_haute(self, self.TITRE)
        actions_barre_module(barre, app)
        tk.Label(barre, text=f"{app.session.nom_complet}  •  {app.session.libelle_role}", font=police(10),
                 fg=BLEU_PALE, bg=NUIT).pack(side="right", padx=px(8))

        nav1 = tk.Frame(self, bg=NUIT)
        nav1.pack(fill="x")
        self.boutons_fonct, self.cadres_onglets, self.boutons = {}, {}, {}
        for i, (cle_f, texte_f, _o) in enumerate(self.FONCTIONNALITES):
            nav1.grid_columnconfigure(i, weight=1, uniform="fonct")
            b = tk.Button(nav1, text=texte_f, command=lambda c=cle_f: self.afficher_fonctionnalite(c), relief="flat", bd=0,
                          highlightthickness=0, font=police(12, gras=True), padx=px(12), pady=px(10), cursor="hand2")
            b.grid(row=0, column=i, sticky="nsew")
            self.boutons_fonct[cle_f] = b
        self.zone_nav = tk.Frame(self, bg=FOND_CLAIR)
        self.zone_nav.pack(fill="x")
        for cle_f, _t, onglets in self.FONCTIONNALITES:
            cadre = tk.Frame(self.zone_nav, bg=FOND_CLAIR)
            for i, (cle, texte) in enumerate(onglets):
                cadre.grid_columnconfigure(i, weight=1, uniform="onglet")
                b = tk.Button(cadre, text=texte, command=lambda c=cle: self.afficher_onglet(c), relief="flat", bd=0,
                              highlightthickness=0, font=police(11, gras=True), padx=px(12), pady=px(10), cursor="hand2")
                b.grid(row=0, column=i, sticky="nsew")
                self.boutons[cle] = b
            self.cadres_onglets[cle_f] = cadre
        tk.Frame(self, bg=BORDURE, height=1).pack(fill="x")

        self._adaptative = ZoneAdaptative(self)
        self._adaptative.pack(fill="both", expand=True)
        self.zone = self._adaptative.interieur
        self.panneaux = {}
        self.courant = None
        self.fonctionnalite = None
        if self.autorise:
            self.panneaux = {cle: classe(self.zone, self) for cle, classe in self.classes.items()}
            self.afficher_onglet(onglet if onglet in self.panneaux else self.ONGLET_DEFAUT)
        else:
            tk.Label(self.zone, text="Votre compte n'a pas accès à ce module.\nDemandez à l'Administrateur de vous accorder "
                                     "le droit « Lecture » (Gestionnaire d'accès > Autorisations).",
                     font=police(13), fg=GRIS, bg=BLANC, justify="center").pack(pady=px(60))

    def _autorise(self, app):
        return presence_eleves.peut_consulter(app.conn, app.session)

    def _panneaux(self, ecrans_cours):
        return {"presence_classes": ecrans_cours.PanneauPresenceEleves}

    def _fonctionnalite_de(self, cle_onglet):
        return next(f[0] for f in self.FONCTIONNALITES if any(o[0] == cle_onglet for o in f[2]))

    def afficher_fonctionnalite(self, cle_f):
        onglets = next(f[2] for f in self.FONCTIONNALITES if f[0] == cle_f)
        if onglets and onglets[0][0] in self.panneaux:
            self.afficher_onglet(onglets[0][0])

    def afficher_onglet(self, cle):
        if cle not in self.panneaux:
            return
        cle_f = self._fonctionnalite_de(cle)
        for cadre in self.cadres_onglets.values():
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
            bouton.config(bg=NUIT if actif else FOND_CLAIR, fg=BLANC if actif else NUIT,
                          activebackground=NUIT_CLAIR if actif else BORDURE, activeforeground=BLANC if actif else NUIT)
        self.fonctionnalite = cle_f
        self.courant = self.panneaux[cle]
        self.courant.pack(fill="both", expand=True)
        if hasattr(self.courant, "au_affichage"):
            self.courant.au_affichage()


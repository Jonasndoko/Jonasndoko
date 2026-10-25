"""Espaces Études, Discipline, Préfecture et Secrétariat (écrans Windows ; même règles que web_etudes.py). Chacun est un module du menu (config.ESPACES_MODULES).

Quatre sous-menus, chacun avec son droit de Lecture (config.SOUS_MENUS_ETUDES) : Préfecture (Préfet), Direction des études, Direction de
discipline, Secrétariat. Le module ne concerne que la section Secondaire et humanitaire. Un compte ne voit que les sous-menus qui lui sont ouverts ; l'Administrateur les voit tous.
Les fonctionnalités de la Préfecture (les six, du Tableau de bord à la Consultation des études) sont pour l'instant en ligne (web_etudes.py, logique dans
prefecture.py, sans interface graphique : elle servira aussi ici) ; les autres sous-menus attendent encore les leurs.
"""
import tkinter as tk

import config
import modules
from theme import BLANC, BLEU_PALE, FOND_CLAIR, GRIS, NUIT, actions_barre_module, barre_haute, police, px


class ModuleEtudesDiscipline(tk.Frame):
    TITRE = ""

    def __init__(self, app, module_propre, sous=None):
        """module_propre = clé d'un espace de config.ESPACES_MODULES (Espace Études, Espace Discipline) : module à part, qui n'affiche que cet espace."""
        super().__init__(app, bg=BLANC)
        self.app = app
        sous = module_propre
        self.TITRE = config.ESPACES_MODULES[module_propre][1]
        self.ouverts = [(c, t) for c, t in modules.sous_menus_ouverts(app.conn, app.session) if c == module_propre]
        barre = barre_haute(self, self.TITRE)
        actions_barre_module(barre, app)
        tk.Label(barre, text=f"{app.session.nom_complet}  •  {app.session.libelle_role}", font=police(10),
                 fg=BLEU_PALE, bg=NUIT).pack(side="right", padx=px(8))
        self.nav = tk.Frame(self, bg=NUIT)
        self.nav.pack(fill="x")
        self.boutons = {}
        for i, (cle, titre) in enumerate(self.ouverts):
            self.nav.grid_columnconfigure(i, weight=1, uniform="sous")
            b = tk.Button(self.nav, text=titre, command=lambda c=cle: self.afficher_sous_menu(c), relief="flat", bd=0,
                          highlightthickness=0, font=police(12, gras=True), padx=px(12), pady=px(10), cursor="hand2")
            b.grid(row=0, column=i, sticky="nsew")
            self.boutons[cle] = b
        self.zone = tk.Frame(self, bg=BLANC)
        self.zone.pack(fill="both", expand=True, padx=px(28), pady=px(22))
        if self.ouverts:
            self.afficher_sous_menu(sous if sous in self.boutons else self.ouverts[0][0])

    def afficher_sous_menu(self, cle):
        if cle not in [c for c, _t in modules.sous_menus_ouverts(self.app.conn, self.app.session)] or cle not in self.boutons:   # droits relus à chaque clic
            return
        for k, b in self.boutons.items():
            actif = k == cle
            b.config(bg="#1D4ED8" if actif else NUIT, fg=BLANC if actif else "#B7C7EE", activebackground="#1D4ED8", activeforeground=BLANC)
        for w in self.zone.winfo_children():
            w.destroy()
        titre = dict(self.ouverts)[cle]
        tk.Label(self.zone, text=titre, font=police(20, gras=True, titre=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        tk.Label(self.zone, text=config.DESCRIPTIONS_SOUS_MENUS_ETUDES.get(cle, ""), font=police(11), fg=GRIS, bg=BLANC).pack(anchor="w")
        tk.Label(self.zone, text="Ce sous-menu est créé. Ses fonctionnalités seront ajoutées prochainement.", font=police(11),
                 fg=GRIS, bg=BLANC).pack(anchor="w", pady=(px(6), 0))

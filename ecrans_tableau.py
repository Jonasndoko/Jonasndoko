"""Tableau de bord (partie droite de l'écran principal) : voir ecrans_principal.py pour la barre latérale, tableau.py pour
le calcul et graphiques.py pour le dessin des graphiques.

Vue GÉNÉRALE seulement : des comptes (élèves, en règle, pas en règle, personnel) et trois graphiques (camembert,
courbe, barres). Aucun nom, aucun montant. Le chevron du titre plie / déplie tout le tableau ; chaque graphique a le sien.
"""
import tkinter as tk
from tkinter import ttk

import donnees
import graphiques
import tableau
from modules import MODULES
from tableau import ErreurTableau
from theme import (ACCENT_BLEU, ACCENT_ORANGE, ACCENT_VERT, ACCENT_VIOLET, BLANC, BORDURE, FOND_ECRAN, GRIS, NUIT, ROUGE,
                   Chevron, charger_icone, police, px)

ACCES_RAPIDES = ("paiement", "encaissement", "controle", "etudes", "discipline", "prefecture", "secretariat")
SOUS_TITRES = {"paiement": "Saisir un paiement", "encaissement": "Consulter la caisse",
               "controle": "Vérifier les élèves", "etudes": "Horaires, notes et bulletins", "discipline": "Présences, conduite et convocations",
               "prefecture": "Supervision et décisions",
               "secretariat": "Dossiers, inscriptions et bulletins"}


def rejouer(zone: tk.Canvas, primitives):
    """Dessine sur le Canvas les primitives calculées par graphiques.py."""
    zone.delete("all")
    for p in primitives:
        t = p["t"]
        if t == "oval":
            zone.create_oval(*p["b"], fill=p["fill"], outline=p.get("outline") or "", width=p.get("width", 1))
        elif t == "arc":
            zone.create_arc(*p["b"], start=p["start"], extent=p["extent"], fill=p["fill"],
                            outline=p.get("outline") or "", width=2, style="pieslice")
        elif t == "rect":
            zone.create_rectangle(*p["b"], fill=p["fill"], outline="")
        elif t == "poly":
            zone.create_polygon(*p["p"], fill=p["fill"], outline="")
        elif t == "line":
            zone.create_line(*p["p"], fill=p["fill"], width=p.get("width", 1), capstyle="round", joinstyle="round")
        elif t == "text":
            zone.create_text(*p["p"], text=p["s"], font=police(p["size"], gras=p["bold"]), fill=p["fill"],
                             anchor=p["anchor"])


def _carte(parent):
    return tk.Frame(parent, bg=BLANC, highlightbackground=BORDURE, highlightthickness=1)


class _Pastille(tk.Canvas):
    """Carré arrondi coloré portant un pictogramme blanc."""

    def __init__(self, parent, couleur, icone, fond=BLANC, cote=44):
        c = px(cote)
        super().__init__(parent, width=c, height=c, bg=fond, highlightthickness=0, bd=0)
        r = px(10)
        for x, y in ((0, 0), (c - 2 * r, 0), (0, c - 2 * r), (c - 2 * r, c - 2 * r)):
            self.create_oval(x, y, x + 2 * r, y + 2 * r, fill=couleur, outline=couleur)
        self.create_rectangle(r, 0, c - r, c, fill=couleur, outline=couleur)
        self.create_rectangle(0, r, c, c - r, fill=couleur, outline=couleur)
        self._image = charger_icone(icone)
        self.create_image(c / 2, c / 2, image=self._image)


class PanneauTableau(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=FOND_ECRAN)
        self.app = app
        s = app.session
        self._graphiques = {}                  # canvas -> fonction (largeur, hauteur) -> primitives
        self._cartes_graphique = []            # (cadre du graphique, canvas, chevron)
        self.visible = True

        tableau.journaliser_ouverture(app.conn, s)

        # ---- titre, chevron plier / déplier, choix de l'année scolaire
        tete = tk.Frame(self, bg=FOND_ECRAN)
        tete.pack(fill="x")
        self.chevron = Chevron(tete, "bas", NUIT, FOND_ECRAN, self.basculer, taille=28, survol=BORDURE)
        self.chevron.pack(side="left", padx=(0, px(8)))
        titres = tk.Frame(tete, bg=FOND_ECRAN)
        titres.pack(side="left")
        tk.Label(titres, text="Tableau de bord", font=police(22, gras=True, titre=True), fg=NUIT, bg=FOND_ECRAN
                 ).pack(anchor="w")
        tk.Label(titres, text=f"Bienvenue, {s.nom_complet}  •  vue générale de l'établissement", font=police(10),
                 fg=GRIS, bg=FOND_ECRAN).pack(anchor="w")
        droite = tk.Frame(tete, bg=FOND_ECRAN)
        droite.pack(side="right")
        self.lbl_message = tk.Label(droite, text="", font=police(9, gras=True), fg=ROUGE, bg=FOND_ECRAN)
        self.lbl_message.pack(side="left", padx=(0, px(10)))
        tk.Label(droite, text="Année scolaire", font=police(10, gras=True), fg=NUIT, bg=FOND_ECRAN).pack(side="left")
        self.var_annee = tk.StringVar(value=donnees.annee_courante(app.conn) or "")
        liste = ttk.Combobox(droite, textvariable=self.var_annee, values=tableau.liste_annees(app.conn),
                             state="readonly", width=11, font=police(11))
        liste.pack(side="left", padx=(px(8), 0))
        liste.bind("<<ComboboxSelected>>", lambda _e: self.actualiser())

        # ---- corps (plié / déplié par le chevron)
        self.corps = tk.Frame(self, bg=FOND_ECRAN)
        self.corps.pack(fill="both", expand=True, pady=(px(18), 0))
        for c, poids in enumerate((1, 1, 1, 1)):
            self.corps.grid_columnconfigure(c, weight=poids, uniform="k")
        self.corps.grid_rowconfigure(1, weight=1, minsize=px(250))
        self.corps.grid_rowconfigure(2, weight=1, minsize=px(250))

        self.v = {}
        specs = (("inscrits", "Élèves", ACCENT_BLEU, "ico_inscription"),
                 ("regle", "En règle", ACCENT_VERT, "ico_controle"),
                 ("pas_regle", "Pas en règle", ACCENT_ORANGE, "ico_audit"),
                 ("personnel", "Personnel actif", ACCENT_VIOLET, "ico_personnel"))
        for k, (cle, titre, couleur, icone) in enumerate(specs):
            self._carte_chiffre(k, cle, titre, couleur, icone)

        self.c_courbe = self._carte_graphique(1, 0, 3, "Évolution du nombre d'élèves", "courbe")
        self.c_camembert = self._carte_graphique(1, 3, 1, "Situation des élèves", "camembert")
        self.c_barres = self._carte_graphique(2, 0, 3, "Filles et garçons par année scolaire", "barres")
        self._acces_rapides(2, 3)
        self.actualiser()

    # ------------------------------------------------------------------ cartes
    def _carte_chiffre(self, colonne, cle, titre, couleur, icone):
        c = _carte(self.corps)
        c.grid(row=0, column=colonne, sticky="nsew", padx=(0 if colonne == 0 else px(14), 0))
        interieur = tk.Frame(c, bg=BLANC)
        interieur.pack(fill="both", expand=True, padx=px(12), pady=px(12))
        _Pastille(interieur, couleur, icone, cote=40).pack(side="left", anchor="n")
        texte = tk.Frame(interieur, bg=BLANC)
        texte.pack(side="left", padx=(px(10), 0))
        tk.Label(texte, text=titre, font=police(10, gras=True), fg=GRIS, bg=BLANC).pack(anchor="w")
        nombre, note = tk.StringVar(value="0"), tk.StringVar(value="")
        tk.Label(texte, textvariable=nombre, font=police(24, gras=True, titre=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        tk.Label(texte, textvariable=note, font=police(9), fg=couleur, bg=BLANC).pack(anchor="w")
        self.v[cle] = (nombre, note)

    def _carte_graphique(self, ligne, colonne, largeur_cols, titre, cle):
        c = _carte(self.corps)
        c.grid(row=ligne, column=colonne, columnspan=largeur_cols, sticky="nsew",
               padx=(0 if colonne == 0 else px(14), 0), pady=(px(14), 0))
        entete = tk.Frame(c, bg=BLANC)
        entete.pack(fill="x", padx=px(16), pady=(px(12), 0))
        tk.Label(entete, text=titre, font=police(12, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
        zone = tk.Canvas(c, bg=BLANC, highlightthickness=0, width=px(10), height=px(180))
        chev = Chevron(entete, "bas", GRIS, BLANC, lambda: self._plier_carte(zone, chev), taille=22, survol=FOND_ECRAN)
        chev.pack(side="right")
        zone.pack(fill="both", expand=True, padx=px(8), pady=(0, px(8)))
        zone.bind("<Configure>", lambda _e, z=zone: self._dessiner(z))
        self._cartes_graphique.append((c, zone, chev))
        return zone

    def _acces_rapides(self, ligne, colonne):
        c = _carte(self.corps)
        c.grid(row=ligne, column=colonne, sticky="nsew", padx=(px(14), 0), pady=(px(14), 0))
        tk.Label(c, text="Accès rapides", font=police(12, gras=True), fg=NUIT, bg=BLANC
                 ).pack(anchor="w", padx=px(16), pady=(px(12), px(6)))
        ouverts = {m[0]: m for m in MODULES if m[3](self.app.conn, self.app.session)}
        n = 0
        for cle in ACCES_RAPIDES:
            if cle not in ouverts:
                continue
            n += 1
            ligne_acces = tk.Frame(c, bg=BLANC, cursor="hand2", highlightbackground=BORDURE, highlightthickness=1)
            ligne_acces.pack(fill="x", padx=px(14), pady=px(4))
            pastille = _Pastille(ligne_acces, ACCENT_BLEU, f"ico_{cle}", cote=34)
            pastille.pack(side="left", padx=px(8), pady=px(6))
            t = tk.Frame(ligne_acces, bg=BLANC, cursor="hand2")
            t.pack(side="left", fill="x", expand=True)
            l1 = tk.Label(t, text=ouverts[cle][1], font=police(10, gras=True), fg=NUIT, bg=BLANC, anchor="w",
                          cursor="hand2", wraplength=px(150), justify="left")
            l1.pack(anchor="w")
            l2 = tk.Label(t, text=SOUS_TITRES[cle], font=police(8), fg=GRIS, bg=BLANC, anchor="w", cursor="hand2")
            l2.pack(anchor="w")
            for w in (ligne_acces, pastille, t, l1, l2):
                w.bind("<Button-1>", lambda _e, k=cle: self.app.ouvrir_module(k))
        if not n:
            tk.Label(c, text="Aucun module ouvert à votre compte.", font=police(9), fg=GRIS, bg=BLANC
                     ).pack(anchor="w", padx=px(16))

    # ------------------------------------------------------------------ plier / déplier
    def basculer(self):
        """Chevron du titre : cache ou montre tout le tableau (cartes et graphiques)."""
        self.visible = not self.visible
        self.chevron.dessiner("bas" if self.visible else "droite")
        if self.visible:
            self.corps.pack(fill="both", expand=True, pady=(px(18), 0))
        else:
            self.corps.pack_forget()

    def _plier_carte(self, zone, chev):
        if zone.winfo_manager():
            zone.pack_forget()
            chev.dessiner("haut")
        else:
            zone.pack(fill="both", expand=True, padx=px(8), pady=(0, px(8)))
            chev.dessiner("bas")

    # ------------------------------------------------------------------ dessin
    def _dessiner(self, zone):
        largeur, hauteur = zone.winfo_width(), zone.winfo_height()
        dessin = self._graphiques.get(zone)
        if dessin is None or largeur < 60 or hauteur < 60:       # pas encore affiché : <Configure> redessinera
            return
        rejouer(zone, dessin(largeur, hauteur))

    # ------------------------------------------------------------------ actions
    def actualiser(self, _evenement=None):
        try:
            d = tableau.tableau_de_bord(self.app.conn, self.app.session, self.var_annee.get() or None)
            t = tableau.tendances(self.app.conn, self.app.session)
        except (ErreurTableau, PermissionError) as erreur:
            self.lbl_message.config(text=str(erreur))
            return
        self.lbl_message.config(text="")
        e = d["eleves"]
        sans = e["inscrits"] == 0
        self.v["inscrits"][0].set(str(e["inscrits"]))
        self.v["inscrits"][1].set(f"Année {d['annee']}" if d["annee"] else "Aucune année scolaire")
        self.v["regle"][0].set(str(e["en_regle"]))
        self.v["regle"][1].set("" if sans else f"{e['taux_en_regle']} % des élèves")
        self.v["pas_regle"][0].set(str(e["pas_en_regle"]))
        self.v["pas_regle"][1].set("" if sans else f"{100 - e['taux_en_regle']} % des élèves")
        self.v["personnel"][0].set(str(t["personnel"]))
        self.v["personnel"][1].set("Agents en fonction")
        echelle = px(100) / 100
        annees = t["annees"]
        self._graphiques[self.c_camembert] = lambda l, h: graphiques.camembert(
            [("En règle", e["en_regle"], graphiques.MENTHE), ("Pas en règle", e["pas_en_regle"], graphiques.CORAIL)],
            l, h, echelle)
        self._graphiques[self.c_courbe] = lambda l, h: graphiques.courbe(
            [(a["annee"], a["inscrits"]) for a in annees], l, h, echelle)
        self._graphiques[self.c_barres] = lambda l, h: graphiques.barres(
            [(a["annee"], [a["filles"], a["garcons"]]) for a in annees],
            [("Filles", graphiques.VIOLET), ("Garçons", graphiques.BLEU)], l, h, echelle)
        for zone in self._graphiques:
            self._dessiner(zone)

"""Tableau de bord en ligne (page web) : même contenu que dans le logiciel Windows (ecrans_tableau.py).

Le calcul reste dans tableau.py (droits relus à chaque affichage, aucun nom, aucun montant) ; ici on ne fait que la page et
les deux graphiques, dessinés en SVG (camembert, courbe). Les libellés parlent des ÉLÈVES de l'année choisie
(et non des « inscrits »).

Qui le voit : l'Administrateur et les comptes ayant la Lecture sur « Tableau de bord ». Ces comptes y arrivent dès la connexion.
"""
import math
from html import escape

from flask import abort, redirect, render_template, request, url_for
from markupsafe import Markup

import argent
import config
import modules
import tableau
from tableau import ErreurTableau

VERT, ORANGE, BLEU, VIOLET = "#16A34A", "#F59E0B", "#1D4ED8", "#87CEEB"      # bleu et ciel du logo de l'école
ACCES_RAPIDES = ("paiement", "encaissement", "controle", "etudes", "discipline", "prefecture", "secretariat")
SOUS_TITRES = {"paiement": "Saisir un paiement", "encaissement": "Consulter la caisse",
               "controle": "Vérifier les élèves", "etudes": "Horaires, notes et bulletins", "discipline": "Présences, conduite et convocations",
               "prefecture": "Supervision et décisions",
               "secretariat": "Dossiers, inscriptions et bulletins"}


# ------------------------------------------------------------------ graphiques SVG
def _svg(largeur, hauteur, corps, titre) -> Markup:
    return Markup(f'<svg viewBox="0 0 {largeur} {hauteur}" role="img" aria-label="{escape(titre)}" '
                  f'preserveAspectRatio="xMidYMid meet" class="graph">{corps}</svg>')


def _vide(titre) -> Markup:
    return _svg(400, 160, '<text x="200" y="85" text-anchor="middle" class="t pale">Aucune donnée pour le moment</text>', titre)


def _pas(maximum) -> tuple:
    """(pas, sommet) de l'axe vertical : 4 graduations environ, valeurs rondes."""
    maximum = max(maximum, 1)
    brut = maximum / 4
    p = 10 ** max(0, math.floor(math.log10(brut)))
    pas = 10 * p
    for m in (1, 2, 5, 10):
        if brut <= m * p:
            pas = m * p
            break
    return pas, pas * math.ceil(maximum / pas)


def camembert(parts, titre) -> Markup:
    """parts : [(libellé, valeur, couleur)] — anneau + légende."""
    total = sum(v for _, v, _ in parts)
    if total <= 0:
        return _vide(titre)
    cx, cy, r, ep = 110, 90, 78, 34
    corps, angle = [], 0.0
    non_nulles = [p for p in parts if p[1] > 0]
    for lib, v, col in non_nulles:
        deg = 360 * v / total
        if len(non_nulles) == 1:
            corps.append(f'<circle cx="{cx}" cy="{cy}" r="{r - ep / 2}" fill="none" stroke="{col}" stroke-width="{ep}"/>')
        else:
            a0, a1 = math.radians(angle - 90), math.radians(angle + deg - 90)
            ri = r - ep
            x0, y0, x1, y1 = cx + r * math.cos(a0), cy + r * math.sin(a0), cx + r * math.cos(a1), cy + r * math.sin(a1)
            x2, y2, x3, y3 = cx + ri * math.cos(a1), cy + ri * math.sin(a1), cx + ri * math.cos(a0), cy + ri * math.sin(a0)
            g = 1 if deg > 180 else 0
            corps.append(f'<path d="M{x0:.1f},{y0:.1f} A{r},{r} 0 {g} 1 {x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f} '
                         f'A{ri},{ri} 0 {g} 0 {x3:.1f},{y3:.1f} Z" fill="{col}" class="part"/>')
        angle += deg
    corps.append(f'<text x="{cx}" y="{cy + 2}" text-anchor="middle" class="t gros">{total}</text>'
                 f'<text x="{cx}" y="{cy + 20}" text-anchor="middle" class="t pale">élèves</text>')
    y = 208
    for lib, v, col in parts:
        pct = round(100 * v / total)
        corps.append(f'<rect x="40" y="{y - 11}" width="14" height="14" rx="3" fill="{col}"/>'
                     f'<text x="62" y="{y}" class="t">{escape(lib)}</text>'
                     f'<text x="62" y="{y + 17}" class="t pale">{v} ({pct} %)</text>')
        y += 42
    return _svg(220, 300, "".join(corps), titre)


def _axes(maximum, gauche, droite, haut, bas, largeur_totale):
    pas, sommet = _pas(maximum)
    out, v = [], 0
    while v <= sommet:
        y = bas - (bas - haut) * v / sommet
        out.append(f'<line x1="{gauche}" y1="{y:.1f}" x2="{droite}" y2="{y:.1f}" class="grille"/>'
                   f'<text x="{gauche - 6}" y="{y + 4:.1f}" text-anchor="end" class="t pale">{v}</text>')
        v += pas
    return "".join(out), sommet


def courbe(points, titre) -> Markup:
    """points : [(année, valeur)]."""
    if not points or all(v == 0 for _, v in points):
        return _vide(titre)
    L, H, g, d, h, b = 640, 230, 44, 620, 24, 190
    axes, sommet = _axes(max(v for _, v in points), g, d, h, b, L)
    n = len(points)
    xs = [(g + d) / 2] if n == 1 else [g + 24 + (d - g - 48) * i / (n - 1) for i in range(n)]
    ys = [b - (b - h) * v / sommet for _, v in points]
    ligne = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    aire = f"{xs[0]:.1f},{b} {ligne} {xs[-1]:.1f},{b}"
    corps = [axes, f'<polygon points="{aire}" fill="{BLEU}" opacity=".12"/>',
             f'<polyline points="{ligne}" fill="none" stroke="{BLEU}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>']
    for (a, v), x, y in zip(points, xs, ys):
        corps.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{BLEU}" stroke="var(--carte)" stroke-width="2"><title>{escape(a)} : {v}</title></circle>'
                     f'<text x="{x:.1f}" y="{y - 11:.1f}" text-anchor="middle" class="t fort">{v}</text>'
                     f'<text x="{x:.1f}" y="{b + 20}" text-anchor="middle" class="t pale">{escape(a)}</text>')
    return _svg(L, H, "".join(corps), titre)


# ------------------------------------------------------------------ routes
def enregistrer(app, conn, session_courante, connecte, origine_ok=None, en_ligne=()):
    """Ajoute la route /tableau-de-bord à l'application (paramètres venus d'app_web.creer_app)."""

    @app.get("/tableau-de-bord")
    @connecte
    def tableau_de_bord():
        s = session_courante()
        c = conn()
        if not tableau.peut(c, s):
            abort(403)
        annee = (request.args.get("annee") or "").strip() or None
        erreur = None
        try:
            d = tableau.tableau_de_bord(c, s, annee)
        except ErreurTableau as e:                       # année inconnue : on retombe sur l'année en cours
            erreur = str(e)
            d = tableau.tableau_de_bord(c, s)
        t = tableau.tendances(c, s)
        syn = tableau.synthese(c, s, d["annee"])
        tableau.journaliser_ouverture(c, s)
        e = d["eleves"]
        annees = t["annees"]
        ouverts = modules.modules_ouverts(c, s)
        titres = {m[0]: m[1] for m in modules.MODULES}
        return render_template(
            "tableau.html", s=s, tableau_ok=True, actif="tableau", cfg=config, d=d, e=e, personnel=t["personnel"], erreur=erreur,
            camembert=camembert([("En règle", e["en_regle"], VERT), ("Pas en règle", e["pas_en_regle"], ORANGE)],
                                "Situation des élèves"),
            courbe=courbe([(a["annee"], a["inscrits"]) for a in annees], "Évolution du nombre d'élèves"),
            syn=syn, montant=argent.formater,
            rapides=[(k, titres[k], SOUS_TITRES[k]) for k in ACCES_RAPIDES if k in ouverts],
            modules=[(k, titres[k], k in en_ligne) for k in ouverts])

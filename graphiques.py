"""Graphique du tableau de bord (sans interface graphique : testable seul, sans bibliothèque externe).

La fonction calcule le dessin du graphique pour une zone de `largeur` x `hauteur` pixels et retourne une liste de
« primitives » (ovale, secteur, texte) que l'écran rejoue sur un Canvas Tkinter (ecrans_tableau.py).
`e` = échelle de l'écran (theme.px(1)) : espacements et tailles de texte s'y adaptent.

Primitives : {"t": "line",  "p": (x0, y0, x1, y1, ...), "fill", "width"}
             {"t": "poly",  "p": (x0, y0, x1, y1, ...), "fill"}
             {"t": "rect",  "b": (x0, y0, x1, y1), "fill"}
             {"t": "oval",  "b": (x0, y0, x1, y1), "fill", "outline"}
             {"t": "arc",   "b": (x0, y0, x1, y1), "start", "extent", "fill", "outline"}      (angles Tkinter)
             {"t": "text",  "p": (x, y), "s", "size", "bold", "fill", "anchor"}
"""
import math

MENTHE = "#16A34A"          # vert du modèle : en règle
CORAIL = "#F59E0B"          # orange du modèle : pas en règle
BLEU = "#2563EB"
BLEU_TEINTE = "#DCE7FD"
VIOLET = "#7C3AED"
GRILLE = "#E3E8F2"
TEXTE = "#3B4357"
TEXTE_PALE = "#7C869C"
BLANC = "#FFFFFF"


# ------------------------------------------------------------------ outils
def hauteur_texte(taille, e) -> float:
    """Hauteur approximative en pixels d'un texte de `taille` points."""
    return taille * 1.33 * e


def largeur_texte(texte, taille, e, gras=False) -> float:
    return len(texte) * hauteur_texte(taille, e) * (0.60 if gras else 0.55)


def tronquer(texte, largeur_max, taille, e, gras=False) -> str:
    """Raccourcit avec « … » pour que le texte tienne dans `largeur_max` pixels."""
    if largeur_texte(texte, taille, e, gras) <= largeur_max:
        return texte
    n = max(1, int(largeur_max / (hauteur_texte(taille, e) * (0.60 if gras else 0.55))) - 1)
    return texte[:n].rstrip() + "…"


def formater_pourcentage(part, total) -> str:
    return (f"{100 * part / total:.1f}".replace(".", ",") + " %") if total else "0 %"


def vide(largeur, hauteur, message="Aucune donnée pour le moment", e=1.0):
    return [{"t": "text", "p": (largeur / 2, hauteur / 2), "s": message, "size": 10, "bold": False,
             "fill": TEXTE_PALE, "anchor": "center"}]


def _texte(x, y, s, size=9, bold=False, fill=TEXTE, anchor="center"):
    return {"t": "text", "p": (x, y), "s": s, "size": size, "bold": bold, "fill": fill, "anchor": anchor}


def _largeurs_legende(elements, e):
    rayon, gap = 5 * e, 18 * e
    largeurs = [2 * rayon + 6 * e + largeur_texte(t, 9, e, True) for _, t in elements]
    return largeurs, gap, sum(largeurs) + gap * (len(elements) - 1)


def _legende_sur_une_ligne(largeur, elements, e) -> bool:
    return _largeurs_legende(elements, e)[2] <= largeur - 16 * e


def _hauteur_legende(largeur, elements, e) -> float:
    """Place à réserver en bas : une ligne, ou une ligne par élément quand la légende ne tient pas en largeur."""
    return 26 * e if _legende_sur_une_ligne(largeur, elements, e) else (8 + 18 * len(elements)) * e


def _legende(largeur, y, elements, e):
    """Légende centrée : [(couleur, texte)] sur une ligne, ou l'un sous l'autre si la fenêtre est trop étroite
    (`y` = ordonnée de la dernière ligne)."""
    rayon = 5 * e
    largeurs, gap, total = _largeurs_legende(elements, e)
    une_ligne = _legende_sur_une_ligne(largeur, elements, e)
    prims, x, n = [], max(8 * e, (largeur - total) / 2), len(elements)
    for k, ((couleur, texte), w) in enumerate(zip(elements, largeurs)):
        if not une_ligne:                                   # une ligne par élément, chacune centrée
            x = max(8 * e, (largeur - w) / 2)
            ligne_y = y - (n - 1 - k) * 18 * e
        else:
            ligne_y = y
        prims.append({"t": "oval", "b": (x, ligne_y - rayon, x + 2 * rayon, ligne_y + rayon), "fill": couleur,
                      "outline": couleur})
        prims.append(_texte(x + 2 * rayon + 6 * e, ligne_y, texte, 9, True, TEXTE, "w"))
        x += w + gap
    return prims


# ------------------------------------------------------------------ 2) camembert
def camembert(parts, largeur, hauteur, e=1.0):
    """parts : [(libellé, valeur, couleur)]. Pourcentage écrit près de chaque secteur ; légende en bas."""
    total = sum(v for _, v, _ in parts)
    if total <= 0:
        return vide(largeur, hauteur, e=e)
    elements = [(c, f"{l} ({v})") for l, v, c in parts]
    haut_legende = _hauteur_legende(largeur, elements, e)
    marge_x, marge_y = 70 * e, 24 * e
    rayon = min((largeur - 2 * marge_x) / 2, (hauteur - haut_legende - 2 * marge_y) / 2)
    rayon = max(rayon, 20 * e)
    cx, cy = largeur / 2, marge_y + (hauteur - haut_legende - 2 * marge_y) / 2
    boite = (cx - rayon, cy - rayon, cx + rayon, cy + rayon)
    prims, angle = [], 0.0                                  # angle en degrés, sens horaire depuis le haut
    non_nulles = [p for p in parts if p[1] > 0]
    for libelle, valeur, couleur in non_nulles:
        degres = 360 * valeur / total
        if len(non_nulles) == 1:
            prims.append({"t": "oval", "b": boite, "fill": couleur, "outline": BLANC})
        else:
            prims.append({"t": "arc", "b": boite, "start": 90 - (angle + degres), "extent": degres, "fill": couleur,
                          "outline": BLANC})
        milieu = math.radians(angle + degres / 2)
        px_, py_ = cx + (rayon + 10 * e) * math.sin(milieu), cy - (rayon + 10 * e) * math.cos(milieu)
        prims.append(_texte(px_, py_, formater_pourcentage(valeur, total), 9, True, TEXTE,
                            "w" if math.sin(milieu) >= 0 else "e"))
        angle += degres
    prims += _legende(largeur, hauteur - 12 * e, elements, e)
    return prims


# ------------------------------------------------------------------ axes communs (courbe et barres)
def _pas_agreable(maximum) -> tuple:
    """(maximum d'axe, pas) « ronds » : 0-10-20..., 0-50-100..., pour 4 graduations au plus."""
    if maximum <= 0:
        return 4, 1
    brut = maximum / 4
    ordre = 10 ** math.floor(math.log10(brut))
    pas = next(m * ordre for m in (1, 2, 5, 10) if m * ordre >= brut)
    return pas * math.ceil(maximum / pas), pas


def _axes(largeur, hauteur, maximum, e, bas_reserve=0.0):
    """Quadrillage + graduations de l'axe vertical. Retourne (primitives, (x0, y0, x1, y1) zone de tracé, max d'axe)."""
    haut_axe, pas = _pas_agreable(maximum)
    gauche = (14 + 8 * max(len(str(int(haut_axe))), 2)) * e
    zone = (gauche, 16 * e, largeur - 16 * e, hauteur - (30 * e + bas_reserve))
    x0, y0, x1, y1 = zone
    prims, v = [], 0
    while v <= haut_axe + 1e-9:
        y = y1 - (y1 - y0) * v / haut_axe
        prims.append({"t": "line", "p": (x0, y, x1, y), "fill": GRILLE, "width": 1})
        prims.append(_texte(x0 - 8 * e, y, str(int(v)), 9, False, TEXTE_PALE, "e"))
        v += pas
    return prims, zone, haut_axe


# ------------------------------------------------------------------ 3) courbe (évolution)
def courbe(points, largeur, hauteur, e=1.0, couleur=BLEU, teinte=BLEU_TEINTE):
    """points : [(libellé, valeur)] dans l'ordre du temps. Zone sous la courbe teintée, un point par valeur."""
    if not points or max(v for _, v in points) <= 0:
        return vide(largeur, hauteur, e=e)
    prims, (x0, y0, x1, y1), haut = _axes(largeur, hauteur, max(v for _, v in points), e)
    n = len(points)
    pas_x = (x1 - x0) / n
    xs = [x0 + pas_x * (k + 0.5) for k in range(n)]
    ys = [y1 - (y1 - y0) * v / haut for _, v in points]
    if n > 1:
        prims.append({"t": "poly", "p": (xs[0], y1, *[c for xy in zip(xs, ys) for c in xy], xs[-1], y1), "fill": teinte})
        prims.append({"t": "line", "p": tuple(c for xy in zip(xs, ys) for c in xy), "fill": couleur, "width": max(2, round(3 * e))})
    r = 4.5 * e
    for (libelle, valeur), x, y in zip(points, xs, ys):
        prims.append({"t": "oval", "b": (x - r, y - r, x + r, y + r), "fill": BLANC, "outline": couleur, "width": 2})
        prims.append(_texte(x, y - 14 * e, str(valeur), 9, True, TEXTE))
        prims.append(_texte(x, y1 + 16 * e, tronquer(libelle, pas_x - 4 * e, 9, e), 9, False, TEXTE_PALE))
    return prims


# ------------------------------------------------------------------ 4) barres groupées
def barres(groupes, series, largeur, hauteur, e=1.0):
    """groupes : [(libellé, [valeur de chaque série])] ; series : [(nom, couleur)]. Légende en bas."""
    if not groupes or max((max(v) for _, v in groupes), default=0) <= 0:
        return vide(largeur, hauteur, e=e)
    elements = [(c, nom) for nom, c in series]
    reserve = _hauteur_legende(largeur, elements, e) - 10 * e
    prims, (x0, y0, x1, y1), haut = _axes(largeur, hauteur, max(max(v) for _, v in groupes), e, reserve)
    pas_g = (x1 - x0) / len(groupes)
    k = len(series)
    larg_b = min(26 * e, pas_g * 0.7 / k)
    for g, (libelle, valeurs) in enumerate(groupes):
        debut = x0 + pas_g * g + (pas_g - larg_b * k) / 2
        for j, (valeur, (_nom, couleur)) in enumerate(zip(valeurs, series)):
            xa = debut + j * larg_b
            ya = y1 - (y1 - y0) * valeur / haut
            if valeur > 0:
                prims.append({"t": "rect", "b": (xa + 1, ya, xa + larg_b - 1, y1), "fill": couleur})
                prims.append(_texte(xa + larg_b / 2, ya - 9 * e, str(valeur), 8, True, TEXTE))
        prims.append(_texte(x0 + pas_g * (g + 0.5), y1 + 16 * e, tronquer(libelle, pas_g - 4 * e, 9, e), 9, False,
                            TEXTE_PALE))
    prims += _legende(largeur, hauteur - 10 * e, elements, e)
    return prims

"""Bulletin de l'élève du PRIMAIRE (modèle officiel : degré élémentaire, moyen ou terminal), A4 portrait, une page par élève.

Reproduit la feuille officielle : drapeau et armoiries de la RDC, « République Démocratique du Congo / Ministère de l'Enseignement
primaire, secondaire et technique », identité de l'école et de l'élève (avec les cases N° ID, Code, N° Perm.), puis le grand tableau :
3 trimestres de 2 périodes (+ examen), 5 domaines de branches, sous-totaux, maxima généraux, pourcentage, place, nombre d'élèves,
application, conduite, signatures ; décision (passe / double) et signature du chef d'établissement.

Entrée : le dictionnaire produit par bulletins.calculer() (jamais la base). Les points viennent des cours de la classe dont le nom
correspond à une branche du modèle (voir BRANCHES et `correspondance`) ; une branche sans cours correspondant reste vide.
Aucune bibliothèque externe : PDF écrit à la main, polices Times et Helvetica standard.
"""
import math
import re
import unicodedata
from datetime import date

import config
from polices_times import TIMES_GRAS, TIMES_REGULIER
from recu_pdf import NUIT, POLICES, _Contenu, _dimensions_jpeg, _echapper, _num, _octets

LARGEUR, HAUTEUR = 595.28, 841.89
CADRE = (14.0, 14.0, 581.28, 827.89)     # cadre extérieur de la feuille : gauche, haut, droite, bas (comme sur le modèle imprimé)
G, D = 19.0, 576.3                       # bords gauche et droite du tableau (et des blocs d'identité), à 5 pt à l'intérieur du cadre
CENTRE = (CADRE[0] + CADRE[2]) / 2       # axe de la feuille : les lignes de l'en-tête sont centrées dessus
EP_CADRE, EP_BLOC, EP_GRILLE = 1.3, 1.0, 0.7
NOIR = (0, 0, 0)
GRIS_FOND = (0.93, 0.93, 0.93)
ENCRE = (0.05, 0.10, 0.45)               # texte rempli (comme l'écriture sur le modèle)

# ------------------------------------------------------------------ le modèle : domaines, groupes et branches (maximum d'une période)
# (domaine, [(titre du groupe ou None, [(libellé imprimé, maximum d'une période, clés de recherche supplémentaires)])])
BRANCHES = [
    ("DOMAINE DES LANGUES", [
        ("LANGUES CONGOLAISES", [("Gram. & Conj.Exp.", 5, ()), ("Lecture", 5, ("lecture langues congolaises", "lecture congolaises", "lecture congolais")),
                                 ("Orale & Vocab.", 10, ()), ("Orth. & rédaction", 10, ())]),
        ("FRANÇAIS", [("Orthographe", 10, ()), ("Lecture", 10, ("lecture francais", "lecture")), ("Eloc. et récitation", 10, ()),
                      ("Phras. Ecrite & Rédac.", 15, ()), ("Comp. Orale -Vocab.", 15, ()), ("Analyse - Conj. Gram.", 20, ())]),
    ]),
    ("DOMAINE DES MATHEMATIQUES, SCIENCES ET TECHNOLOGIE", [
        (None, [("Anatomie -botanique", 10, ()), ("Formes géométriques", 10, ()), ("Informatique / Techno.(1)", 10, ("informatique", "technologie")),
                ("Mesures des grandeurs", 10, ()), ("Opérations", 10, ()), ("Physique / zoologie", 10, ()), ("Numération", 20, ()),
                ("Problèmes", 20, ())]),
    ]),
    ("DOMAINE DE L'UNIVERS SOCIAL ET ENVIRONNEMENT", [
        (None, [("Education à la vie", 10, ()), ("Ed. civ & morale", 10, ()), ("Ed. santé & env.", 10, ()), ("Géographie", 10, ()),
                ("Histoire", 10, ())]),
    ]),
    ("DOMAINE DES ARTS", [
        (None, [("Art Plastique", 10, ()), ("Art Dramatique", 10, ())]),
    ]),
    ("DOMAINE DU DEVELOPPEMENT PERSONNEL", [
        (None, [("Init. Trav. Prod.", 10, ()), ("Ed. phys. & sportive", 10, ()), ("Religion(1)", 10, ("religion",))]),
    ]),
]

_EXPANSIONS = {"ed": "education", "edu": "education", "gram": "grammaire", "conj": "conjugaison", "exp": "expression", "orth": "orthographe",
               "redac": "redaction", "phras": "phraseologie", "comp": "comprehension", "vocab": "vocabulaire", "eloc": "elocution",
               "civ": "civique", "env": "environnement", "init": "initiation", "trav": "travail", "prod": "productif", "techno": "technologie",
               "phys": "physique", "eps": "education physique sportive"}
_MOTS_VIDES = {"et", "a", "la", "le", "les", "de", "des", "du", "l", "d", "au", "aux", "en", "1"}


def _cle(texte) -> str:
    """Clé de comparaison d'un nom de cours : sans accents ni ponctuation, abréviations développées, mots vides retirés."""
    t = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\(\d\)", " ", t)
    mots = []
    for m in re.findall(r"[a-z0-9]+", t):
        if m in _MOTS_VIDES:
            continue
        mots += _EXPANSIONS.get(m, m).split()
    return " ".join(m for m in mots if m not in _MOTS_VIDES)


def correspondance(calc) -> dict:
    """{(domaine, groupe, libellé): id_cc} : cours de la classe qui correspondent aux branches du modèle (un cours sert une seule branche).
    Une branche sans cours correspondant est absente (son emplacement reste vide)."""
    libres = {_cle(c["libelle"]): c["id_cc"] for c in calc["cours"]}
    pris, res = set(), {}
    for domaine, groupes in BRANCHES:
        for titre, lignes in groupes:
            for libelle, _mx, autres in lignes:
                for cle in [_cle(a) for a in autres if "lecture" in a and titre == "LANGUES CONGOLAISES"] + [_cle(libelle)] + \
                           ([] if titre == "LANGUES CONGOLAISES" else [_cle(a) for a in autres]):
                    if cle in libres and libres[cle] not in pris:
                        res[(domaine, titre, libelle)] = libres[cle]
                        pris.add(libres[cle])
                        break
    return res


def cours_du_modele() -> list:
    """Liste des branches du modèle (libellé, maximum d'une période) : pour créer les cours du primaire avec les bons noms."""
    return [(l.replace("(1)", ""), mx) for _d, gs in BRANCHES for _t, ls in gs for l, mx, _a in ls]


# ------------------------------------------------------------------ colonnes du tableau
def _colonnes():
    """Largeurs relatives relevées sur le bulletin officiel : colonne des branches étroite, colonnes « PTS OBT. » plus larges."""
    cols = [("branche", None, 136.0)]
    for t in range(3):
        if t == 0:
            cols.append(("maxper", None, 42.0))
        cols += [("p", 2 * t, 38.5), ("p", 2 * t + 1, 38.5), ("maxex", t, 42.0), ("ptsex", t, 43.0), ("maxtrim", t, 42.0), ("ptstrim", t, 49.0)]
    cols += [("totmax", None, 46.0), ("totpts", None, 62.0)]
    somme = sum(c[2] for c in cols)
    return [(k, i, w * (D - G) / somme) for k, i, w in cols]


COLS = _colonnes()
X_COL = [G + sum(c[2] for c in COLS[:i]) for i in range(len(COLS) + 1)]
COLS_NOIRES = {"maxper", "maxex", "maxtrim", "totmax"}            # cases noircies des lignes du bas (pas de maximum pour un pourcentage)
HAUT_TABLE_HAUT, HAUT_TABLE_BAS = 210.3, 723.1


# ------------------------------------------------------------------ écriture dans la page
_TAB = {"F1": POLICES["F1"], "F2": POLICES["F2"], "F3": POLICES["F1"], "F4": TIMES_REGULIER, "F5": TIMES_GRAS}


def _largeur(texte, police, taille) -> float:
    t = _TAB[police]
    return sum(t[c - 32] if 32 <= c <= 255 else 556 for c in _octets(texte)) * taille / 1000


def _y(top) -> float:
    return HAUTEUR - top


class _Page(_Contenu):
    def t(self, x, top, texte, police="F4", taille=7, rgb=NOIR):
        self.texte(x, _y(top), texte, police, taille, rgb)

    def tc(self, x1, x2, top, texte, police="F4", taille=7, rgb=NOIR):
        """Texte centré entre x1 et x2, réduit au besoin pour tenir."""
        while taille > 4.5 and _largeur(texte, police, taille) > (x2 - x1) - 1.5:
            taille -= 0.25
        self.texte((x1 + x2) / 2 - _largeur(texte, police, taille) / 2, _y(top), texte, police, taille, rgb)

    def td(self, x_droite, top, texte, police="F4", taille=7, rgb=NOIR):
        self.texte(x_droite - _largeur(texte, police, taille), _y(top), texte, police, taille, rgb)

    def trait(self, x1, top1, x2, top2, ep=EP_GRILLE, rgb=NOIR):
        self.ligne(x1, _y(top1), x2, _y(top2), ep, rgb)

    def cadre(self, x, top, l, h, ep=0.5, rgb=NOIR):
        self.rectangle(x, _y(top + h), l, h, epaisseur=ep, rgb=rgb)

    def plein(self, x, top, l, h, rgb):
        self.fond(x, _y(top + h), l, h, rgb)

    def pointilles(self, x1, x2, top, ep=0.45):
        self.couleur(NOIR, trait=True)
        self.ops.append(f"q [0.6 1.6] 0 d {ep} w {_num(x1)} {_num(_y(top))} m {_num(x2)} {_num(_y(top))} l S Q")

    def cases(self, x, top, n, largeur_case, hauteur, textes=""):
        """Rangée de n cases contiguës (N° ID, Code, N° Perm.), avec un caractère par case."""
        for i in range(n):
            self.cadre(x + i * largeur_case, top, largeur_case, hauteur, 0.6)
            if i < len(textes) and textes[i] != " ":
                self.tc(x + i * largeur_case, x + (i + 1) * largeur_case, top + hauteur * 0.72, textes[i], "F5", 10, ENCRE)


# ------------------------------------------------------------------ drapeau
def _etoile(cx, cy, r):
    pts = []
    for i in range(10):
        a = math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.382
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


def _drapeau(p, x, top, l, h):
    """Drapeau de la RDC (vectoriel) : fond bleu ciel, bande rouge liserée de jaune en diagonale, étoile jaune en haut à gauche."""
    y = _y(top + h)
    BLEU, JAUNE, ROUGE = (0.0, 0.63, 0.87), (0.99, 0.87, 0.0), (0.81, 0.07, 0.15)
    p.ops.append("q")
    p.ops.append(f"{x:.2f} {y:.2f} {l:.2f} {h:.2f} re W n")
    p.fond(x, y, l, h, BLEU)

    def bande(d, couleur):
        p.couleur(couleur)
        p.ops.append(f"{x:.2f} {y - d:.2f} m {x:.2f} {y + d:.2f} l {x + l:.2f} {y + h + d:.2f} l {x + l:.2f} {y + h - d:.2f} l f")
    bande(h * 0.27, JAUNE)
    bande(h * 0.19, ROUGE)
    pts = _etoile(x + l * 0.2, y + h * 0.76, h * 0.2)
    p.couleur(JAUNE)
    p.ops.append(" ".join(f"{px:.2f} {py:.2f} {'m' if i == 0 else 'l'}" for i, (px, py) in enumerate(pts)) + " f")
    p.ops.append("Q")
    p.rectangle(x, y, l, h, epaisseur=0.4, rgb=(0.35, 0.35, 0.4))


# ------------------------------------------------------------------ formats
def _fmt(v) -> str:
    return "" if v is None else str(v).replace(".", ",")


def _rang(r) -> str:
    return "" if not r else ("1er" if r == 1 else f"{r}e")


def _degre(classe) -> str:
    """« DEGRE TERMINAL (5e ANNEE) » d'après le numéro de la classe (1-2 élémentaire, 3-4 moyen, 5-6 terminal)."""
    m = re.search(r"\d", classe.get("annee_etude") or classe.get("designation") or "")
    if not m:
        return ""
    n = int(m.group())
    degre = "DEGRE ELEMENTAIRE" if n <= 2 else "DEGRE MOYEN" if n <= 4 else "DEGRE TERMINAL"
    return f"{degre} ({n}{'re' if n == 1 else 'e'} ANNEE)"


def _cases_de(texte, n):
    return (texte or "").upper()[:n]


# ------------------------------------------------------------------ la page
def _page(calc, eleve, corr, para) -> _Page:
    """`para` : paramètres (identité de l'école)."""
    p = _Page()
    classe = calc["classe"]
    portees = calc["portees"]
    periodes = [x for x in portees if x["type"] == "periode"]
    examens = [x for x in portees if x["type"] == "examen"]
    trims = [x for x in portees if x["type"] == "semestre"]
    annee = next((x for x in portees if x["type"] == "annee"), None)

    # ---- cadre de la feuille et lignes qui séparent l'en-tête, la rangée N° ID, l'identité et le titre (comme sur le modèle imprimé)
    cg, ch, cd, cb = CADRE
    BAS_ENTETE, BAS_ID, BAS_IDENTITE = 75.2, 102.6, 195.0
    p.cadre(cg, ch, cd - cg, cb - ch, EP_CADRE)
    p.trait(cg, BAS_ENTETE, cd, BAS_ENTETE, EP_BLOC)
    p.trait(cg, BAS_ID, cd, BAS_ID, EP_BLOC)

    # ---- en-tête officiel : drapeau à gauche, armoiries à droite, trois lignes centrées sur l'axe de la feuille (même corps de 11 pt)
    _drapeau(p, cg + 3.5, ch + 3.5, 77.5, 54.7)
    ha = 54.0
    p.image(D - 2.5 - ha * 0.856, _y(BAS_ENTETE - 2.7), ha * 0.856, ha)
    for texte, base in (("REPUBLIQUE DEMOCRATIQUE DU CONGO", 29.0), ("MINISTERE DE L'ENSEIGNEMENT PRIMAIRE, SECONDAIRE", 43.0),
                        ("ET TECHNIQUE", 59.0)):
        p.tc(CENTRE - 200, CENTRE + 200, base, texte, "F5", 11)

    # ---- rangée du N° ID : 27 cases
    p.t(50.8, 96.5, "N° ID.", "F5", 11.5)
    p.cases(106.4, 81.2, 27, 14.1, 18.6)

    # ---- identité : bloc encadré, coupé en deux par une ligne verticale
    milieu = G + 0.504 * (D - G)
    p.cadre(G, BAS_ID, D - G, BAS_IDENTITE - BAS_ID, EP_BLOC)
    p.trait(milieu, BAS_ID, milieu, BAS_IDENTITE, EP_BLOC)
    lignes_g = [("PROVINCE", 118.0, para["province"]), ("VILLE", 135.25, para["ville"]), ("COMMUNE / TER. (1)", 152.5, para["commune"]),
                ("ECOLE", 169.75, para["ecole"])]
    fin_g = milieu - 5.5
    for lib, top, val in lignes_g:
        etiq = lib + " :"
        p.t(G + 4, top, etiq, "F5", 8.0)
        fin = G + 4 + _largeur(etiq, "F5", 8.0) + 3
        p.pointilles(fin, fin_g, top + 1.2)
        if val:
            p.t(fin + 3, top - 0.8, val, "F5", 8.5, ENCRE)
    p.t(G + 4, 187.0, "CODE :", "F5", 8.0)
    p.cases(66.9, 177.5, 9, 22.3, 16.5, _cases_de(para["code"], 9))

    el_x = milieu + 6.5
    x_sexe, x_le = 515.0, 493.0
    p.t(el_x, 119.5, "ELEVE :", "F5", 8.0)
    p.pointilles(el_x + 36, x_sexe - 3, 120.7)
    p.t(el_x + 39, 118.7, eleve["nom_complet"], "F5", 8.5, ENCRE)
    p.t(x_sexe, 119.5, "SEXE :", "F5", 8.0)
    p.pointilles(x_sexe + 28, D - 5.5, 120.7)
    p.t(x_sexe + 31, 118.7, eleve["sexe"] or "", "F5", 8.5, ENCRE)
    p.t(el_x, 136.4, "NE(E) A :", "F5", 8.0)
    p.pointilles(el_x + 37, x_le - 2, 137.6)
    p.t(el_x + 40, 135.6, eleve["lieu_naissance"], "F5", 8.5, ENCRE)
    p.t(x_le, 136.4, "LE", "F5", 8.0)
    p.pointilles(x_le + 11, D - 5.5, 137.6)
    p.t(x_le + 14, 135.6, eleve["naissance"] or "", "F5", 8.5, ENCRE)
    p.t(el_x, 152.3, "CLASSE :", "F5", 8.0)
    p.pointilles(el_x + 36, 549.0, 153.5)
    p.t(el_x + 39, 151.5, classe["designation"], "F5", 8.5, ENCRE)
    p.t(el_x, 168.5, "N° PERM. :", "F5", 8.0)
    p.cases(364.8, 160.6, 13, 14.65, 15.3)

    # ---- titre et année scolaire (rangée encadrée)
    HAUT_TITRE = HAUT_TABLE_HAUT
    p.cadre(G, BAS_IDENTITE, D - G, HAUT_TITRE - BAS_IDENTITE, EP_BLOC)
    titre = ("BULLETIN DE L'ELEVE " + _degre(classe)).strip()
    taille_titre = min(10.8, 262.0 / _largeur(titre, "F5", 1))
    p.t(67.4, 206.0, titre, "F5", taille_titre)
    x_an = max(344.5, 67.4 + _largeur(titre, "F5", taille_titre) + 14)
    p.t(x_an, 206.0, "ANNEE SCOLAIRE", "F5", 10)
    x = x_an + _largeur("ANNEE SCOLAIRE", "F5", 10) + 7
    annees = re.findall(r"\d{4}", str(calc["annee"]))
    for an in (annees[:2] + ["", ""])[:2]:                   # « 20__.... 20__.... » : « 20 » imprimé, deux chiffres à l'encre sur les points
        p.t(x, 206.0, "20", "F5", 10)
        x += _largeur("20", "F5", 10)
        p.pointilles(x, x + 30, 207.2)
        p.t(x + 3, 205.2, an[2:], "F5", 10, ENCRE)
        x += 36

    # ---- tableau : en-têtes
    top = HAUT_TABLE_HAUT
    hg, hc = 11.0, 21.8
    haut_entete = hg + hc
    nb_lignes = 48
    rh = (HAUT_TABLE_BAS - top - haut_entete) / nb_lignes
    for i, (k, idx, w) in enumerate(COLS):
        x1, x2 = X_COL[i], X_COL[i + 1]
        p.trait(x1, top if i in (0, 1, 8, 14, 20) else top + hg, x1, top + haut_entete)      # seules les limites des groupes montent jusqu'en haut
    p.trait(D, top, D, top + haut_entete)
    p.trait(G, top, D, top, 1.0)
    p.trait(G, top + haut_entete, D, top + haut_entete, 0.8)

    def groupe(i1, i2, texte):
        p.trait(X_COL[i1], top + hg, X_COL[i2 + 1], top + hg)
        p.tc(X_COL[i1], X_COL[i2 + 1], top + 8, texte, "F5", 6.2)
    groupe(1, 7, "PREMIER TRIMESTRE")
    groupe(8, 13, "DEUXIEME TRIMESTRE")
    groupe(14, 19, "TROISIEME TRIMESTRE")
    groupe(20, 21, "TOTAL")
    p.tc(G, X_COL[1], top + 20, "BRANCHES", "F5", 6.5)
    noms_p = ["1ªP", "2ªP", "3ªP", "4ªP", "5ªP", "6ªP"]
    for i, (k, idx, w) in enumerate(COLS):
        x1, x2 = X_COL[i], X_COL[i + 1]
        if k == "p":
            p.tc(x1, x2, top + hg + 13, noms_p[idx], "F5", 6.2)
        else:
            lignes = {"maxper": ("MAX", "per"), "maxex": ("MAX", "EX."), "ptsex": ("PTS", "OBT."), "maxtrim": ("MAX", "TRIM."),
                      "ptstrim": ("PTS", "OBT."), "totmax": ("MAX", ""), "totpts": ("PTS", "OBT.")}.get(k)
            if lignes:
                p.tc(x1, x2, top + hg + 9, lignes[0], "F5", 5.2)
                if lignes[1]:
                    p.tc(x1, x2, top + hg + 17, lignes[1], "F5", 5.2)
    top += haut_entete

    # ---- tableau : valeurs d'un élève
    def cellule(id_cc, k, idx):
        if id_cc is None:
            return None
        c = eleve["cours"].get(id_cc, {})
        cle = {"p": lambda: periodes[idx]["cle"] if idx < len(periodes) else None,
               "ptsex": lambda: examens[idx]["cle"] if idx < len(examens) else None,
               "ptstrim": lambda: trims[idx]["cle"] if idx < len(trims) else None,
               "totpts": lambda: annee["cle"] if annee else None}.get(k, lambda: None)()
        return c.get(cle, {}).get("obtenu") if cle else None

    def pts_colonnes():
        return [(i, k, idx) for i, (k, idx, _w) in enumerate(COLS) if k in ("p", "ptsex", "ptstrim", "totpts")]

    def maxima(mx, k):
        """Maximum imprimé dans une colonne « max » pour un maximum de période `mx`."""
        return {"maxper": mx, "maxex": 2 * mx, "maxtrim": 4 * mx, "totmax": 12 * mx}.get(k)

    y = top
    totaux = {i: None for i in range(len(COLS))}           # somme des points de toutes les branches, par colonne
    max_gen = {"maxper": 0, "maxex": 0, "maxtrim": 0, "totmax": 0}

    def ligne_h(top_ligne, h, ep=EP_GRILLE):
        p.trait(G, top_ligne, D, top_ligne, ep)

    def verticales(top_ligne, h):
        for xi in X_COL:
            p.trait(xi, top_ligne, xi, top_ligne + h)

    def bandeau(top_ligne, h, texte, gauche=None):
        p.trait(G, top_ligne, G, top_ligne + h)
        p.trait(D, top_ligne, D, top_ligne + h)
        if gauche:
            p.t(G + 3, top_ligne + h - 2.4, gauche, "F5", 6.3)
        if texte:
            p.tc(G, D, top_ligne + h - 2.4, texte, "F5", 6.3)

    def valeur_ligne(top_ligne, h, libelle, mx, vals, gras=False, sup=False):
        verticales(top_ligne, h)
        police = "F5" if gras else "F4"
        etiq = libelle.replace("(1)", "")
        taille = 6.4
        while taille > 4.6 and _largeur(etiq, police, taille) > X_COL[1] - G - 4:
            taille -= 0.2
        p.t(G + 2, top_ligne + h - 2.5, etiq, police, taille)
        if "(1)" in libelle:
            p.t(G + 2 + _largeur(etiq, police, taille) + 0.3, top_ligne + h - 5.2, "(1)", "F4", 4.2)
        for i, (k, idx, _w) in enumerate(COLS):
            if k == "branche":
                continue
            v = vals.get(i)
            if v is None and k in max_gen and mx is not None:
                v = maxima(mx, k)
            if v is not None:
                p.tc(X_COL[i], X_COL[i + 1], top_ligne + h - 2.5, _fmt(v), "F5" if gras else "F4", 6.6)

    def sous_total(top_ligne, h, branches_ligne, ids_lignes):
        """Sous-total d'un groupe : maximum = somme des maxima ; points = somme des points saisis (vide s'il n'y en a aucun)."""
        mx = sum(b[1] for b in branches_ligne)
        vals = {}
        for i, k, idx in pts_colonnes():
            lis = [cellule(idc, k, idx) for idc in ids_lignes]
            lis = [v for v in lis if v is not None]
            if lis:
                vals[i] = round(sum(lis), 2)
                vals[i] = int(vals[i]) if float(vals[i]).is_integer() else vals[i]
        valeur_ligne(top_ligne, h, "Sous-total", mx, vals, gras=True)
        return mx

    for domaine, groupes in BRANCHES:
        premier = True
        for titre_g, lignes in groupes:
            if premier:                                           # bandeau du domaine (et titre du premier groupe sur la même ligne)
                bandeau(y, rh, domaine, titre_g)
                ligne_h(y, rh)
                y += rh
                premier = False
            elif titre_g:
                bandeau(y, rh, None, titre_g)
                ligne_h(y, rh)
                y += rh
            ids = []
            for libelle, mx, _a in lignes:
                id_cc = corr.get((domaine, titre_g, libelle))
                ids.append(id_cc)
                vals = {}
                for i, k, idx in pts_colonnes():
                    v = cellule(id_cc, k, idx)
                    if v is not None:
                        vals[i] = v
                ligne_h(y, rh)
                valeur_ligne(y, rh, libelle, mx, vals)
                for i, v in vals.items():
                    totaux[i] = (totaux[i] or 0) + v
                for k in max_gen:
                    max_gen[k] += maxima(mx, k)
                y += rh
            ligne_h(y, rh)
            sous_total(y, rh, lignes, ids)
            y += rh
    ligne_h(y, rh)
    # ---- maxima généraux : maximum de chaque colonne et points de l'élève (somme des branches affichées)
    vals = {i: (round(v, 2) if v is not None else None) for i, v in totaux.items() if i}
    valeurs = {}
    for i, k, idx in pts_colonnes():
        v = vals.get(i)
        if v is not None:
            valeurs[i] = int(v) if float(v).is_integer() else v
    verticales(y, rh)
    p.t(G + 2, y + rh - 2.5, "Maxima généraux", "F5", 6.4)
    for i, (k, idx, _w) in enumerate(COLS):
        v = max_gen.get(k) if k in max_gen else valeurs.get(i)
        if v is not None:
            p.tc(X_COL[i], X_COL[i + 1], y + rh - 2.5, _fmt(v), "F5", 6.6)
    y += rh
    ligne_h(y, rh, 0.8)

    # ---- lignes du bas : pourcentage, place, nombre d'élèves, application, conduite, signatures
    def portee_de(k, idx):
        if k == "totpts":
            return annee
        liste = {"p": periodes, "ptsex": examens, "ptstrim": trims}.get(k)
        return liste[idx] if liste and idx < len(liste) else None

    bas = [("POURCENTAGE", lambda pe, r: _fmt(r["pct"]) if r["pct"] is not None else ""),
           ("PLACE", lambda pe, r: _rang(r["rang"])),
           ("NBRE D'ELEVES", lambda pe, r: str(calc["stats"][pe["cle"]]["effectif"]) if r["pct"] is not None else ""),
           ("APPLICATION", None),
           ("CONDUITE", lambda pe, r: r.get("conduite", "") if pe["type"] == "periode" else ""),
           ("SIGNAT. DE L'INST.", None), ("SIGNAT. DU RESP.", None)]
    haut_bas = y
    for lib, f in bas:
        verticales(y, rh)
        p.t(G + 2, y + rh - 2.5, lib, "F5", 6.2)
        for i, (k, idx, _w) in enumerate(COLS):
            x1, x2 = X_COL[i], X_COL[i + 1]
            if k in COLS_NOIRES:
                p.plein(x1, y, x2 - x1, rh, NOIR)
            elif f and k in ("p", "ptsex", "ptstrim", "totpts"):
                pe = portee_de(k, idx)
                if pe:
                    r = eleve["portees"][pe["cle"]]
                    txt = f(pe, r)
                    if txt:
                        p.tc(x1, x2, y + rh - 2.5, txt, "F5", 6.4)
        y += rh
        ligne_h(y, rh)
    p.trait(G, haut_bas, G, y, 1.0)
    p.trait(D, haut_bas, D, y, 1.0)
    p.cadre(G, HAUT_TABLE_HAUT, D - G, y - HAUT_TABLE_HAUT, 1.0)

    # ---- décision, signature, notes (positions relevées sur le modèle)
    res = eleve["portees"][annee["cle"]]["reussite"] if annee else None
    X_DEC = 50.3
    L1, L2 = "L'élève passe dans la classe supérieure (1)", "L'élève double la classe (1)"
    p.t(X_DEC, 742.6, L1, "F4", 7.5)
    p.t(X_DEC, 753.0, L2, "F4", 7.5)
    p.t(X_DEC - 7.5, 753.0, "-", "F4", 7.5)
    if res is not None:
        haut = 742.6 if res else 753.0
        bas_ = 753.0 if res else 742.6
        x0 = X_DEC - 14
        p.trait(x0, haut - 3, x0 + 3, haut + 1, 1.2, ENCRE)                     # coche
        p.trait(x0 + 3, haut + 1, x0 + 11, haut - 9, 1.2, ENCRE)
        largeur_barre = _largeur(L2 if res else L1, "F4", 7.5)
        p.trait(X_DEC, bas_ - 2.5, X_DEC + largeur_barre, bas_ - 2.5, 0.8)      # mention inutile : barrée
    lieu = para["lieu"]
    p.t(341, 741.0, "Fait à", "F4", 8)
    p.pointilles(362, 455, 742.5)
    p.t(366, 740.5, lieu, "F4", 8, ENCRE)
    p.t(461.5, 741.0, "le", "F4", 8)
    p.pointilles(472, D - 8, 742.5)
    p.t(476, 740.5, date.today().strftime("%d/%m/%Y"), "F4", 8, ENCRE)
    p.t(401, 757.6, "LE CHEF D'ETABLISSEMENT", "F5", 7.5)
    p.t(416, 774.6, "NOM & SIGNATURE", "F5", 7)
    p.pointilles(416 + _largeur("NOM & SIGNATURE", "F5", 7) + 3, D - 8, 776.1)
    p.t(X_DEC, 793.7, "(1)", "F4", 7)
    p.t(X_DEC + 15.5, 793.7, "Biffer la mention inutile.", "F4", 7)
    p.t(X_DEC, 804.6, "NOTE IMPORTANTE :", "F5", 7)
    p.t(X_DEC + _largeur("NOTE IMPORTANTE :", "F5", 7) + 3, 804.6, "Le bulletin est sans valeur s'il est raturé ou surchargé.", "F4", 7)
    p.t(541.6, 806.8, "IGE/P.S/003", "F5", 5.5, (0.35, 0.35, 0.35))
    return p


# ------------------------------------------------------------------ PDF
def _assembler(contenus, jpeg, titre):
    l_img, h_img, composantes = _dimensions_jpeg(jpeg)
    espace = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}[composantes]
    police = lambda nom: f"<< /Type /Font /Subtype /Type1 /BaseFont /{nom} /Encoding /WinAnsiEncoding >>".encode()
    n = len(contenus)
    kids = " ".join(f"{11 + 2 * i} 0 R" for i in range(n))
    objets = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        police("Helvetica"), police("Helvetica-Bold"), police("Helvetica-Oblique"), police("Times-Roman"), police("Times-Bold"),   # 3 à 7 : F1 à F5
        (f"<< /Type /XObject /Subtype /Image /Width {l_img} /Height {h_img} /ColorSpace {espace} "
         f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg)} >>\nstream\n").encode() + jpeg + b"\nendstream",      # 8 : Im1
        f"<< /Title ({titre}) /Producer (GESTSCO) >>".encode("latin-1"),                                                        # 9 : informations
        b"<< >>",                                                                                                               # 10 : libre
    ]
    for i, contenu in enumerate(contenus):
        objets.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {LARGEUR} {HAUTEUR}] /Contents {12 + 2 * i} 0 R /Resources << /Font << "
                       "/F1 3 0 R /F2 4 0 R /F3 5 0 R /F4 6 0 R /F5 7 0 R >> /XObject << /Im1 8 0 R >> >> >>").encode())
        objets.append(b"<< /Length %d >>\nstream\n" % len(contenu) + contenu + b"\nendstream")
    sortie = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    positions = []
    for numero, corps in enumerate(objets, start=1):
        positions.append(len(sortie))
        sortie += f"{numero} 0 obj\n".encode() + corps + b"\nendobj\n"
    debut_xref = len(sortie)
    sortie += f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n".encode()
    for pos in positions:
        sortie += f"{pos:010d} 00000 n \n".encode()
    sortie += f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R /Info 9 0 R >>\nstartxref\n{debut_xref}\n%%EOF\n".encode()
    return bytes(sortie)


def parametres() -> dict:
    return {"province": config.PROVINCE_BULLETIN, "ville": config.VILLE_BULLETIN, "commune": config.COMMUNE_BULLETIN,
            "ecole": config.NOM_ECOLE, "code": config.CODE_ECOLE_BULLETIN, "lieu": config.VILLE_BULLETIN}


def bulletins(calc, eleves) -> bytes:
    """Un bulletin (une page A4) par élève, sur le modèle officiel du primaire."""
    with open(config.DOSSIER_ASSETS / "armoiries_rdc.jpg", "rb") as f:
        jpeg = f.read()
    corr = correspondance(calc)
    para = parametres()
    pages = [_page(calc, e, corr, para) for e in eleves]
    return _assembler([pg.octets() for pg in pages], jpeg, "Bulletins du primaire")

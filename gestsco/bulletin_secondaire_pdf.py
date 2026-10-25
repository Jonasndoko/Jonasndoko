"""Bulletin de l'élève du SECONDAIRE et des HUMANITÉS (modèle officiel : 7ème, 8ème, 1ère, 2ème, 3ème, 4ème), A4 portrait, une page par élève.

Reproduit la feuille officielle (relevée à la règle sur le modèle imprimé de la 2ème année Humanité Électricité Générale) : drapeau et
armoiries de la RDC, identité de l'école et de l'élève (cases N° ID, Code, N° Perm.), puis le grand tableau :
  - 2 semestres (1ère P, 2e P, EXAM, TOT), total général (T.G.), colonne noire, colonnes de l'examen de repêchage (% et signature) ;
  - les branches rangées par GROUPES DE MAXIMA, chaque groupe précédé de sa ligne « MAXIMA » ;
  - maxima généraux, totaux, pourcentage, place / nombre d'élèves, application, conduite, signature du responsable ;
  - cases du bas : repêchage, décision (passe / double), « Fait à », signatures, note importante, interdiction de reproduire.

Les branches d'une classe sont ses COURS OUVERTS (donc elles changent selon l'année d'étude et l'option) ; le modèle fixe la règle des maxima :
maximum d'une période = 10 x heures par semaine du cours ; examen = 2 x période ; total du semestre = 4 x période ; total général = 8 x période.
Les cours de 100 points par période ou plus (ateliers, laboratoires) n'ont pas d'examen : colonnes EXAM noircies, semestre = 2 x période.

Entrée : le dictionnaire produit par bulletins.calculer() (jamais la base). Aucune bibliothèque externe : PDF écrit à la main, polices
Times et Helvetica standard. Toutes les positions sont relevées en pixels sur l'image du modèle (683 x 956) puis converties en points.
"""
import re
import unicodedata
from datetime import date

import config
from bulletin_primaire_pdf import ENCRE, NOIR, _Page as _PageBase, _cle, _drapeau, _fmt, parametres
from polices_times import TIMES_GRAS, TIMES_REGULIER
from recu_pdf import POLICES, _dimensions_jpeg, _num, _octets

LARGEUR, HAUTEUR = 595.28, 841.89
IMG_L, IMG_H = 683.0, 956.0                     # dimensions (en pixels) de l'image du modèle d'où les positions sont relevées
SX, SY = LARGEUR / IMG_L, HAUTEUR / IMG_H       # pixels -> points
EP = 0.87                                       # un pixel d'épaisseur de trait, en points
DY = 1.5                                        # les ordonnées de base relevées sont celles du bas des capitales : la ligne d'écriture est 1,5 px plus bas

# ------------------------------------------------------------------ géométrie du tableau (pixels de l'image du modèle)
GAUCHE, DROITE = 22.5, 661.0
COL = [GAUCHE, 152.0, 197.0, 237.0, 286.0, 327.5, 366.5, 412.5, 458.5, 499.0, 539.0, 555.0, 586.5, DROITE]
# les 9 colonnes de points : (genre, indice) ; genre P = période, EX = examen, TOT = total du semestre, TG = total général
NUM = [("P", 0), ("P", 1), ("EX", 0), ("TOT", 0), ("P", 2), ("P", 3), ("EX", 1), ("TOT", 1), ("TG", 0)]
X_NUM = [(COL[i + 1], COL[i + 2]) for i in range(9)]
X_BRANCHE = (GAUCHE, COL[1])
X_NOIR = (COL[10], COL[11])                     # colonne noire entre le total général et le repêchage
X_PCT, X_SIGN = (COL[11], COL[12]), (COL[12], COL[13])
HAUT_TABLE, HAUT_CORPS, BAS_TABLE = 232.0, 274.5, 779.5
LIGNES_BAS = 7                                  # maxima généraux, totaux, pourcentage, place, application, conduite, signature
H_MODELE = (BAS_TABLE - HAUT_CORPS) / 34        # hauteur d'une ligne sur le modèle (34 lignes)
MIN_LIGNES = 12                                 # nombre minimal de lignes de branches (groupes compris) sur la feuille
PRATIQUE_MAXIMUM = 100                          # une période d'au moins 100 points : atelier / laboratoire, sans examen

_TAB = {"F1": POLICES["F1"], "F2": POLICES["F2"], "F3": POLICES["F1"], "F4": TIMES_REGULIER, "F5": TIMES_GRAS,
        "F6": TIMES_REGULIER, "F7": TIMES_GRAS}   # F6 = Times italique, F7 = Times gras italique (largeurs voisines du romain)

# ------------------------------------------------------------------ branches : ordre, libellés du modèle
_PRIORITE = ["religion", "education vie", "education civique morale"]
_ETIQUETTES = {
    "education vie": "Education à la vie (1)", "education civique morale": "Ed. civ. & morale",
    "geographie actualites": "Géographie/actualités", "instruments methodes mesures": "Inst.Meth.Mes",
    "technologie mecanique": "Techno mécanique", "technologie electrique": "Techno Electr.",
}


def _largeur(texte, police, taille) -> float:
    t = _TAB[police]
    return sum(t[c - 32] if 32 <= c <= 255 else 556 for c in _octets(texte)) * taille / 1000


def _sans_accents(texte) -> str:
    return unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()


class _Page(_PageBase):
    """Page dont les positions sont données en PIXELS de l'image du modèle (x vers la droite, y vers le bas)."""

    def tx(self, x, base, texte, police="F4", taille=9.4, rgb=NOIR):
        self.texte(x * SX, HAUTEUR - (base + DY) * SY, texte, police, taille, rgb)

    def taille_pour(self, texte, police, x1, x2) -> float:
        return (x2 - x1 + 1.4) * SX / _largeur(texte, police, 1)

    def tfit(self, x1, x2, base, texte, police="F4", rgb=NOIR):
        """Texte de la largeur exacte relevée sur le modèle (la taille s'en déduit)."""
        self.tx(x1, base, texte, police, self.taille_pour(texte, police, x1, x2), rgb)

    def tcen(self, x1, x2, base, texte, police="F4", taille=9.4, rgb=NOIR):
        """Texte centré entre x1 et x2, réduit au besoin pour tenir dans la case."""
        while taille > 3.5 and _largeur(texte, police, taille) > (x2 - x1) * SX - 1.2:
            taille -= 0.2
        self.texte((x1 + x2) / 2 * SX - _largeur(texte, police, taille) / 2, HAUTEUR - (base + DY) * SY, texte, police, taille, rgb)

    def tdroite(self, x2, base, texte, police="F4", taille=7.0, rgb=NOIR):
        self.texte(x2 * SX - _largeur(texte, police, taille), HAUTEUR - (base + DY) * SY, texte, police, taille, rgb)

    def sup(self, x, base, entier, suffixe, police, taille, rgb=NOIR) -> float:
        """« 2ème » : le nombre, puis le suffixe en exposant. Retourne l'abscisse (pixels) de la fin."""
        self.tx(x, base, entier, police, taille, rgb)
        x += _largeur(entier, police, taille) / SX
        pt = taille * 0.58
        self.texte(x * SX, HAUTEUR - (base + DY - taille * 0.36 / SY) * SY, suffixe, police, pt, rgb)
        return x + _largeur(suffixe, police, pt) / SX

    def hl(self, y, x1, x2, ep=1.0):
        self.ligne(x1 * SX, HAUTEUR - y * SY, x2 * SX, HAUTEUR - y * SY, ep * EP, NOIR)

    def vl(self, x, y1, y2, ep=1.0):
        self.ligne(x * SX, HAUTEUR - y1 * SY, x * SX, HAUTEUR - y2 * SY, ep * EP, NOIR)

    def boite(self, x1, y1, x2, y2, ep=1.0):
        self.rectangle(x1 * SX, HAUTEUR - y2 * SY, (x2 - x1) * SX, (y2 - y1) * SY, ep * EP, NOIR)

    def noir(self, x1, y1, x2, y2):
        self.fond(x1 * SX, HAUTEUR - y2 * SY, (x2 - x1) * SX, (y2 - y1) * SY, NOIR)

    def points(self, x1, x2, base, ep=0.75):
        """Ligne de points de conduite (comme les « …… » du modèle)."""
        self.couleur(NOIR, trait=True)
        self.ops.append(f"q [0.55 2.05] 0 d {ep} w {_num(x1 * SX)} {_num(HAUTEUR - base * SY)} m {_num(x2 * SX)} {_num(HAUTEUR - base * SY)} l S Q")

    def cases(self, x1, x2, y1, y2, n, textes="", ep=1.1):
        """Rangée de n cases contiguës, un caractère par case."""
        w = (x2 - x1) / n
        for i in range(n):
            self.boite(x1 + i * w, y1, x1 + (i + 1) * w, y2, ep)
            if i < len(textes) and textes[i] != " ":
                self.tcen(x1 + i * w, x1 + (i + 1) * w, y2 - 3.5, textes[i], "F5", 10, ENCRE)


# ------------------------------------------------------------------ les lignes du tableau
def _libelle(nom) -> str:
    return _ETIQUETTES.get(_cle(nom), nom)


def _maximum_periode(calc, c):
    """Maximum d'une période pour ce cours : celui fixé par le titulaire de la classe (à défaut le maximum standard des périodes). Pour les données
    sans ce renseignement : 10 x heures par semaine, sinon le maximum saisi par le professeur, sinon rien."""
    if c.get("max_periode"):
        m = c["max_periode"]
        return int(m) if float(m).is_integer() else m
    if (c.get("heures") or 0) > 0:
        return 10 * int(c["heures"])
    for e in calc["eleves"]:
        for v in e["cours"].get(c["id_cc"], {}).values():
            if v.get("max"):
                return int(v["max"]) if float(v["max"]).is_integer() else v["max"]
    return None


def lignes_du_tableau(calc) -> list:
    """[('max', m, pratique) | ('br', cours, m, pratique)] : groupes de maxima croissants, chacun précédé de sa ligne « MAXIMA » ;
    dans un groupe, la formation humaine (religion, éducation à la vie, éducation civique) d'abord, puis l'ordre alphabétique."""
    groupes = {}
    for c in calc["cours"]:
        m = _maximum_periode(calc, c)
        groupes.setdefault(m if m is not None else 0, []).append(c)
    lignes = []
    for m in sorted(groupes):
        pratique = m >= PRATIQUE_MAXIMUM
        lignes.append(("max", m, pratique))
        def ordre(c):
            k = _cle(c["libelle"])
            return (_PRIORITE.index(k) if k in _PRIORITE else len(_PRIORITE), _sans_accents(c["libelle"]).lower())
        for c in sorted(groupes[m], key=ordre):
            lignes.append(("br", c, m, pratique))
    while len(lignes) < MIN_LIGNES:                       # classe sans cours (ou presque) : la feuille garde des lignes à remplir à la main
        lignes.append(("vide",))
    return lignes


def maxima_colonnes(m, pratique) -> dict:
    """Maximum imprimé dans chaque colonne pour une branche dont la période vaut m : P = m ; EX = 2m ; TOT = 4m ; TG = 8m (sans examen :
    EX noircie, TOT = 2m, TG = 4m)."""
    if not m:
        return {}
    if pratique:
        return {"P": m, "TOT": 2 * m, "TG": 4 * m}
    return {"P": m, "EX": 2 * m, "TOT": 4 * m, "TG": 8 * m}


def _titre_classe(classe):
    """('2', 'ème', 'ANNEE HUMANITE ELECTRICITE GENERALE') pour « BULLETIN DE LA 2ème ANNEE HUMANITE ELECTRICITE GENERALE »."""
    m = re.search(r"\d", classe.get("annee_etude") or classe.get("designation") or classe.get("niveau") or "")
    option = _sans_accents(classe.get("option") or "").upper().strip()
    if not m:
        return "", "", _sans_accents(classe.get("designation") or "").upper()
    n = int(m.group())
    if n in (7, 8):                                   # 7ème et 8ème : années de base, sans option ni mention « HUMANITE »
        return str(n), "ème", "ANNEE DE BASE"
    return str(n), ("ère" if n == 1 else "ème"), "ANNEE" + (f" HUMANITE {option}" if option else "")


def _portees_colonnes(calc) -> list:
    """Clé de portée de chacune des 9 colonnes de points (None si le calendrier n'a pas cette période) : P1 P2 EX TOT | P3 P4 EX TOT | TG."""
    sem = [x for x in calc["portees"] if x["type"] == "semestre"][:2]
    cles = []
    for i in range(2):
        s = sem[i] if i < len(sem) else None
        per = s["periodes"] if s else []
        cles += [f"P{per[0]}" if len(per) > 0 else None, f"P{per[1]}" if len(per) > 1 else None,
                 "X" + s["cle"][1:] if s and per else None, s["cle"] if s else None]
    annee = next((x for x in calc["portees"] if x["type"] == "annee"), None)
    cles.append(annee["cle"] if annee else None)
    return cles


# ------------------------------------------------------------------ la page
def _page(calc, eleve, para) -> _Page:
    p = _Page()
    classe = calc["classe"]
    cles = _portees_colonnes(calc)
    lignes = lignes_du_tableau(calc)
    n = len(lignes) + LIGNES_BAS
    rh = (BAS_TABLE - HAUT_CORPS) / n                         # les lignes s'étirent ou se resserrent : le tableau garde la hauteur du modèle
    ech = min(1.0, rh / H_MODELE)                              # réduction des caractères quand la classe a beaucoup de lignes
    y_ligne = lambda i: HAUT_CORPS + i * rh

    # ---- cadre de la feuille, lignes de l'en-tête (relevées sur le modèle)
    p.boite(GAUCHE, 34, DROITE, 915.5, 1.7)
    for y in (93.5, 119.0, 133.5, 216.5):
        p.hl(y, GAUCHE, DROITE, 1.4 if y in (93.5, 133.5, 216.5) else 1.0)
    p.vl(327.5, 133.5, 216.5, 1.3)

    # ---- en-tête officiel : drapeau, armoiries, trois lignes
    _drapeau(p, 28 * SX, 38 * SY, 86 * SX, 53 * SY)
    ha = 48.0 * SY
    p.image(611 * SX, HAUTEUR - 86.5 * SY, ha * 0.856, ha)
    p.tfit(213.5, 476, 48.5, "REPUBLIQUE DEMOCRATIQUE DU CONGO", "F5")
    p.tfit(214, 494, 62.5, "MINISTERE DE L'ENSEIGNEMENT PRIMAIRE,", "F5")
    p.tfit(251.5, 433, 76.5, "SECONDAIRE ET TECHNIQUE", "F5")

    # ---- N° ID (27 cases)
    p.tfit(31, 62, 111, "N° ID", "F5")
    p.cases(116.5, 620.5, 99, 115, 27)

    # ---- province, ville, commune, école, code
    p.tfit(31, 89, 130, "PROVINCE", "F5")
    if para["province"]:
        p.tx(98, 130, para["province"], "F5", 9, ENCRE)
    for lib, x2, base, val in (("VILLE :", 66, 154, para["ville"]), ("ECOLE :", 70, 190, para["ecole"])):
        p.tfit(30, x2, base, lib, "F5")
        if val:
            p.tx(x2 + 8, base, val, "F5", 9, ENCRE)
    p.tfit(30, 111, 173, "COMMUNE/TER", "F5")
    p.tx(113.5, 173, "(1)", "F5", 7.4)
    p.tx(127, 173, ":", "F5", 9.4)
    if para["commune"]:
        p.tx(144, 173, para["commune"], "F5", 9, ENCRE)
    p.tfit(30, 63, 207, "CODE :", "F5")
    p.cases(86.5, 273.0, 195, 211, 9, (para["code"] or "").upper()[:9])

    # ---- identité de l'élève (colonne de droite)
    p.tfit(336, 368, 152, "ELEVE :", "F5")
    p.points(374, 590, 151.8)
    p.tx(378, 151.2, eleve["nom_complet"], "F5", 9, ENCRE)
    p.tfit(593, 620, 152, "SEXE :", "F5")
    p.points(623, 636, 151.8)
    p.tx(625, 151.2, eleve["sexe"] or "", "F5", 9, ENCRE)
    p.tfit(336, 381, 170.5, "NE (E) A:", "F5")
    p.points(384, 556, 170.3)
    p.tx(388, 169.7, eleve["lieu_naissance"], "F5", 9, ENCRE)
    p.tfit(558, 572, 170.5, "LE", "F5")
    jj, mm, aaaa = ("", "", "")
    if re.fullmatch(r"\d\d/\d\d/\d{4}", eleve["naissance"] or ""):
        jj, mm, aaaa = (eleve["naissance"].split("/"))
    for (a, b), val in (((575, 601), jj), ((607, 627), mm), ((633, 652), aaaa)):
        p.points(a, b, 170.3)
        if val:
            p.tcen(a, b, 169.7, val, "F5", 7.5, ENCRE)
    p.tx(602.5, 170.5, "/", "F4", 8)
    p.tx(628.5, 170.5, "/", "F4", 8)
    p.tfit(336, 373, 188, "CLASSE :", "F5")
    p.points(380, 590, 187.8)
    p.tx(384, 187.2, classe["designation"], "F5", 9, ENCRE)
    p.tfit(336, 383, 205, "N° PERM :", "F5")
    p.cases(406.0, 637.0, 192, 208, 13)

    # ---- titre et année scolaire
    taille_t = p.taille_pour("BULLETIN DE LA", "F5", 34, 138.5)
    p.tx(34, 229, "BULLETIN DE LA", "F5", taille_t)
    num, suf, reste = _titre_classe(classe)
    x = 147.0
    if num:
        x = p.sup(x, 229, num, suf, "F5", taille_t)
        reste = " " + reste
    largeur_dispo = 470 - x
    taille_r = min(taille_t, largeur_dispo * SX / _largeur(reste, "F5", 1))
    p.tx(x, 229, reste, "F5", taille_r)
    p.tfit(477, 585, 229, "ANNEE SCOLAIRE", "F5")                      # largeur relevée sur le modèle : un espace avant « 20 »
    annees = re.findall(r"\d{4}", str(calc["annee"]))
    for (x20, fin), an in zip(((589.0, 620.0), (627.0, 651.0)), (annees[:2] + ["", ""])[:2]):
        p.tx(x20, 229, "20", "F5", taille_t)
        deb = x20 + _largeur("20", "F5", taille_t) / SX
        p.points(deb + 1, fin, 229)
        if an:
            p.tx(deb + 1.5, 228.2, an[2:], "F5", taille_t, ENCRE)

    # ---- en-tête du tableau
    p.hl(HAUT_TABLE, GAUCHE, DROITE, 1.3)
    for x in (COL[1], COL[5], COL[9]):
        p.vl(x, HAUT_TABLE, HAUT_CORPS)
    for x in (COL[3], COL[4], COL[7], COL[8]):
        p.vl(x, 246, HAUT_CORPS)
    for x in (COL[2], COL[6]):
        p.vl(x, 258, HAUT_CORPS)
    p.hl(246, COL[1], COL[9] + 1)
    p.hl(258, COL[1], COL[3])
    p.hl(258, COL[5], COL[7])
    p.hl(258, X_NOIR[0], DROITE)
    p.vl(X_SIGN[0], 258, HAUT_CORPS)
    p.tfit(189, 293, 242.5, "PREMIER SEMESTRE", "F5")
    p.tfit(363, 465, 242.5, "SECOND  SEMESTRE", "F5")
    p.tfit(160, 231, 255, "TRAV.JOURNAL.", "F5")
    p.tfit(335, 407, 255, "TRAV.JOURNAL.", "F5")
    p.tcen(GAUCHE, COL[1], 262, "BRANCHES", "F2", 9.2)
    p.tfit(578, 638, 243, "EXAMEN DE", "F5")
    p.tfit(576, 641, 255, "REPECHAGE", "F5")
    p.tcen(560, 573, 269.5, "%", "F5", 10)
    p.tfit(605, 644, 267.5, "Sign. Prof.", "F5")
    X_P = {0: 167.0, 1: 211.0, 2: 341.0, 3: 384.0}                           # début des « 1ère P », « 2e P », « 3e P », « 4e P » sur le modèle
    n_p = 0
    for i, (genre, idx) in enumerate(NUM):
        a, b = X_NUM[i]
        if genre == "P":
            etiq = ("1", "ère") if n_p == 0 else (str(n_p + 1), "e")
            fin = p.sup(X_P[n_p], 270, etiq[0], etiq[1], "F5", 7.6)
            p.tx(fin + 1.4, 270, "P", "F5", 7.6)
            n_p += 1
        elif genre == "EX":
            p.tx(245.5 if idx == 0 else 421.5, 268, "EXAM", "F4", 8.8)
        elif genre == "TOT":
            p.tx((293.0 if idx == 0 else 466.5), 268, "TOT", "F4", 8.8)
        else:
            p.tx(507.0, 271, "T.G.", "F4", 8.8)
    p.hl(HAUT_CORPS, GAUCHE, DROITE, 2.0)

    # ---- valeurs de l'élève
    def cellule(id_cc, i):
        cle = cles[i]
        if not cle:
            return None
        return eleve["cours"].get(id_cc, {}).get(cle, {}).get("obtenu")

    totaux, maxima_gen = [None] * 9, [None] * 9

    def ecrire_valeurs(vals, police, taille, base, maxima=False, pratique=False):
        """Un nombre par colonne, centré dans sa case. Sur les lignes « MAXIMA » les chiffres du modèle sont tapés à la main : légèrement à
        droite du centre, et à gauche pour les groupes sans examen et pour le total général."""
        for k, v in enumerate(vals):
            if v is None or v == "":
                continue
            a, b = X_NUM[k]
            txt = v if isinstance(v, str) else _fmt(v)
            dec = 0.0
            if maxima:
                dec = -5.5 if pratique else 1.5
                if k == 8:
                    dec = -6.5 if (pratique or len(txt) <= 2) else 2.5
            p.tcen(a + dec, b + dec, base, txt, police, taille)

    for i, ligne in enumerate(lignes):
        y1, y2 = y_ligne(i), y_ligne(i + 1)
        base = y2 - 3.5 * ech
        if ligne[0] == "vide":
            continue
        if ligne[0] == "max":
            _t, m, pratique = ligne
            p.tx(31, base, "MAXIMA", "F5", 9.7 * ech)
            mx = maxima_colonnes(m, pratique)
            ecrire_valeurs([mx.get(g) for g, _i in NUM], "F5", 9.4 * ech, base, True, pratique)
            p.noir(X_PCT[0], y1, DROITE, y2)
            if pratique:
                for k in (2, 6):
                    p.noir(X_NUM[k][0], y1, X_NUM[k][1], y2)
            continue
        _t, c, m, pratique = ligne
        mx = maxima_colonnes(m, pratique)
        etiq = _libelle(c["libelle"])
        taille = 9.4 * ech
        while taille > 4.6 and _largeur(etiq, "F4", taille) > (X_BRANCHE[1] - X_BRANCHE[0] - 7) * SX:
            taille -= 0.2
        p.tx(31, base, etiq, "F4", taille)
        vals = []
        for k, (g, _i) in enumerate(NUM):
            v = cellule(c["id_cc"], k) if not (pratique and g == "EX") else None
            vals.append(v)
            if v is not None:
                totaux[k] = (totaux[k] or 0) + v
            if g in mx:
                maxima_gen[k] = (maxima_gen[k] or 0) + mx[g]
        ecrire_valeurs(vals, "F4", 9.0 * ech, base)
        if pratique:
            for k in (2, 6):
                p.noir(X_NUM[k][0], y1, X_NUM[k][1], y2)

    # ---- lignes du bas : maxima généraux, totaux, pourcentage, place, application, conduite, signature
    n_corps = len(lignes)
    i_mg = n_corps
    labels = [("MAXIMA GENERAUX", 30, 125), ("TOTAUX", 30, 67), ("POURCENTAGE", 31, 100), ("PLACE/NBRE D'ELEVE", 31, 130),
              ("APPLICATION", 30, 92), ("CONDUITE", 30, 78), ("Signature du responsable", 30, 140)]
    for j, (lib, a, b) in enumerate(labels):
        y2 = y_ligne(i_mg + j + 1)
        taille = p.taille_pour(lib, "F5", a, b) * (1.0 if j < 6 else 1.0)
        p.tx(a, y2 - 5.5 * ech if j < 6 else y2 - 4.5 * ech, lib, "F5", min(taille, 9.4) * ech)
    y_mg, y_tot, y_pct, y_place, y_app, y_cond, y_sig = (y_ligne(i_mg + j) for j in range(7))
    y_fin = y_ligne(n)

    def en_valeurs(j):
        """Valeurs de la ligne bas j (0 = maxima généraux, 1 = totaux) pour les 9 colonnes."""
        if j == 0:
            return maxima_gen
        return [round(v, 2) if v is not None else None for v in totaux]

    def propre(v):
        return int(v) if isinstance(v, float) and v.is_integer() else v
    ecrire_valeurs([propre(v) for v in en_valeurs(0)], "F5", 8.6 * ech, y_tot - 5.5 * ech)
    ecrire_valeurs([propre(v) for v in en_valeurs(1)], "F4", 8.6 * ech, y_pct - 5.5 * ech)
    p.noir(X_PCT[0], y_mg, DROITE, y_tot)

    for k, cle in enumerate(cles):
        a, b = X_NUM[k]
        r = eleve["portees"].get(cle) if cle else None
        if r and r["pct"] is not None:
            p.tcen(a, b, y_place - 5.5 * ech, _fmt(r["pct"]), "F4", 8.6 * ech)
        # place / nombre d'élèves : « 3 / 45 » autour de la barre oblique du modèle
        xm = (a + b) / 2
        p.tcen(xm - 8, xm + 8, y_app - 5.0 * ech, "/", "F6", 9.5 * ech)
        if r and r["rang"]:
            p.tdroite(xm - 2.5, y_app - 5.0 * ech, str(r["rang"]), "F4", 7.2 * ech)
            p.tx(xm + 3.0, y_app - 5.0 * ech, str(calc["stats"][cle]["effectif"]), "F4", 7.2 * ech)
        # conduite (périodes seulement)
        if r and cle.startswith("P") and r.get("conduite"):
            p.tcen(a, b, y_sig - 5.0 * ech, r["conduite"], "F5", 8.0 * ech, ENCRE)

    # zones noires de l'application et de la conduite, colonne noire
    p.noir(COL[3], y_app, COL[5], y_sig)
    p.noir(COL[7], y_app, COL[11], y_sig)
    p.noir(X_NOIR[0], HAUT_TABLE, X_NOIR[1], y_sig)

    # ---- quadrillage du corps du tableau
    for i in range(1, n):
        p.hl(y_ligne(i), GAUCHE, DROITE if i <= n_corps + 1 else COL[11], 1.0)
    fin_vert = {1: y_fin, 2: y_fin, 3: y_fin, 4: y_sig, 5: y_fin, 6: y_fin, 7: y_fin, 8: y_sig, 9: y_sig, 10: y_sig, 11: y_fin, 12: y_mg}
    for i, x in enumerate(COL[1:13], start=1):
        p.vl(x, HAUT_CORPS, fin_vert[i])
    p.vl(GAUCHE, HAUT_TABLE, y_fin, 1.7)
    p.vl(DROITE, HAUT_TABLE, y_fin, 1.7)
    p.hl(y_fin, GAUCHE, DROITE, 1.7)

    # ---- bloc de décision (colonnes de droite, sous les maxima généraux)
    res = eleve["portees"][cles[8]]["reussite"] if cles[8] and cles[8] in eleve["portees"] else None
    f = (y_fin - y_tot) / (BAS_TABLE - 690.5)                                  # le bloc suit la hauteur des 6 dernières lignes
    yb = lambda y_px: y_tot + (y_px - 690.5) * f
    xb = COL[11] + 7.0
    p.tx(xb, yb(705), "- PASSE (1)", "F4", 8.0)
    p.tx(xb, yb(720), "- DOUBLE (1)", "F4", 8.0)
    p.tx(xb, yb(736), "LE", "F4", 7.2)
    p.points(xb + 11, 637, yb(736))
    p.tx(xb, yb(748), "Le Chef d'Etablis.", "F4", 8.0)
    p.tx(xb + 21, yb(758), "Sceau de l'école", "F4", 7.2)
    if res is True:                                                              # « biffer la mention inutile »
        p.hl(yb(720) - 2.3, xb, xb + _largeur("- DOUBLE (1)", "F4", 8.0) / SX, 0.8)
    # ---- cases du bas
    t_rep = p.taille_pour("- L'élève ne pourra passer dans la classe supérieure s'il n'a subi avec succès un examen de repêchage en", "F4", 30, 414)
    p.tx(30, 800, "- L'élève ne pourra passer dans la classe supérieure s'il n'a subi avec succès un examen de repêchage en", "F4", t_rep)
    p.points(420, 622, 800.3)
    p.points(51, 624, 810.3)
    L1, L2 = "- L'élève passe dans la classe supérieure (1)", "- L'élève double la classe (1)"
    p.tx(30, 822, L1, "F4", p.taille_pour(L1, "F4", 30, 190))
    p.tx(30, 832, L2, "F4", p.taille_pour(L2, "F4", 30, 139))
    if res is not None and res is True:
        p.hl(829.3, 30, 139, 0.8)
    p.tx(360, 832, "Fait à", "F4", 7.6)
    p.points(384, 527, 831.6)
    if para["lieu"]:
        p.tx(388, 831, para["lieu"], "F4", 7.6, ENCRE)
    p.tx(531, 832, "le", "F4", 7.6)
    auj = date.today()
    for (a, b), val in (((543, 565), f"{auj.day:02d}"), ((570, 592), f"{auj.month:02d}")):
        p.points(a, b, 832)
        p.tcen(a, b, 831, val, "F4", 7.6, ENCRE)
    p.tx(566.5, 832, "/", "F4", 7.6)
    p.tx(593.5, 832, "/", "F4", 7.6)
    p.tx(597, 832, "20", "F4", 7.6)
    p.points(608, 626, 832)
    p.tcen(608, 626, 831, f"{auj.year % 100:02d}", "F4", 7.6, ENCRE)
    p.tfit(510, 601, 860, "Le chef d'Etablissement", "F5")
    p.tfit(51, 125, 871, "Signature de l'élève", "F5")
    p.tfit(281, 340, 871, "Sceau de l'école", "F5")
    p.tfit(532, 596, 871, "Nom et signature", "F5")
    p.tx(30, 892, "(1)", "F4", 6.4)
    p.tfit(50, 128, 892, "Biffer la mention inutile", "F4")
    p.tfit(30, 257, 902, "Note importante : le bulletin est sans valeur s'il est raturé ou surchargé.", "F4")
    p.tfit(574, 623, 902, "IGE/P.S./1 25", "F6")
    p.tfit(176, 512, 913, "Interdiction formelle de reproduire ce bulletin sous peine des sanctions prévues par la loi", "F7")
    return p


# ------------------------------------------------------------------ PDF
def _assembler(contenus, jpeg, titre):
    l_img, h_img, composantes = _dimensions_jpeg(jpeg)
    espace = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}[composantes]
    police = lambda nom: f"<< /Type /Font /Subtype /Type1 /BaseFont /{nom} /Encoding /WinAnsiEncoding >>".encode()
    n = len(contenus)
    kids = " ".join(f"{13 + 2 * i} 0 R" for i in range(n))
    objets = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        police("Helvetica"), police("Helvetica-Bold"), police("Helvetica-Oblique"), police("Times-Roman"), police("Times-Bold"),
        police("Times-Italic"), police("Times-BoldItalic"),                                                    # 3 à 9 : F1 à F7
        (f"<< /Type /XObject /Subtype /Image /Width {l_img} /Height {h_img} /ColorSpace {espace} "
         f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg)} >>\nstream\n").encode() + jpeg + b"\nendstream",      # 10 : Im1
        f"<< /Title ({titre}) /Producer (GESTSCO) >>".encode("latin-1"),                                        # 11 : informations
        b"<< >>",                                                                                               # 12 : libre
    ]
    for i, contenu in enumerate(contenus):
        objets.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {LARGEUR} {HAUTEUR}] /Contents {14 + 2 * i} 0 R /Resources << /Font << "
                       "/F1 3 0 R /F2 4 0 R /F3 5 0 R /F4 6 0 R /F5 7 0 R /F6 8 0 R /F7 9 0 R >> /XObject << /Im1 10 0 R >> >> >>").encode())
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
    sortie += f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R /Info 11 0 R >>\nstartxref\n{debut_xref}\n%%EOF\n".encode()
    return bytes(sortie)


def bulletins(calc, eleves) -> bytes:
    """Un bulletin (une page A4) par élève, sur le modèle officiel du secondaire et des humanités."""
    with open(config.DOSSIER_ASSETS / "armoiries_rdc.jpg", "rb") as f:
        jpeg = f.read()
    para = parametres()
    pages = [_page(calc, e, para) for e in eleves]
    return _assembler([pg.octets() for pg in pages], jpeg, "Bulletins du secondaire et des humanites")

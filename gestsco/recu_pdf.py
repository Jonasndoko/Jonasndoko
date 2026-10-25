"""Reçu de paiement au format PDF (A6 paysage) - écrit sans bibliothèque externe.

Polices : Helvetica / Helvetica-Bold / Helvetica-Oblique (intégrées à tout lecteur PDF).
Le logo est le JPEG de l'école, inséré tel quel dans le PDF.
"""
import struct

# Largeurs des caractères (codes 32 à 255, encodage Windows-1252), en millièmes de la taille de police
_LARGEURS_REGULIER = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556,
    556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778,
    722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278,
    278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584, 761, 556, 0, 222, 556,
    333, 1000, 556, 556, 333, 1000, 667, 333, 1000, 0, 611, 0, 0, 222, 222, 333, 333, 350, 556, 1000,
    333, 1000, 500, 333, 944, 0, 500, 667, 278, 333, 556, 556, 556, 556, 260, 556, 333, 737, 370, 556,
    584, 333, 737, 333, 400, 584, 333, 333, 333, 556, 537, 278, 333, 333, 365, 556, 834, 834, 834, 611,
    667, 667, 667, 667, 667, 667, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278, 722, 722, 778, 778,
    778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611, 556, 556, 556, 556, 556, 556, 889, 500,
    556, 556, 556, 556, 278, 278, 278, 278, 556, 556, 556, 556, 556, 556, 556, 584, 611, 556, 556, 556,
    556, 500, 556, 500
]
_LARGEURS_GRAS = [
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556,
    556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778,
    722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333,
    278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584, 761, 556, 0, 278, 556,
    500, 1000, 556, 556, 333, 1000, 667, 333, 1000, 0, 611, 0, 0, 278, 278, 500, 500, 350, 556, 1000,
    333, 1000, 556, 333, 944, 0, 500, 667, 278, 333, 556, 556, 556, 556, 280, 556, 333, 737, 370, 556,
    584, 333, 737, 333, 400, 584, 333, 333, 333, 611, 556, 278, 333, 333, 365, 556, 834, 834, 834, 611,
    722, 722, 722, 722, 722, 722, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278, 722, 722, 778, 778,
    778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611, 556, 556, 556, 556, 556, 556, 889, 556,
    556, 556, 556, 556, 278, 278, 278, 278, 611, 611, 611, 611, 611, 611, 611, 584, 611, 611, 611, 611,
    611, 556, 611, 556
]

LARGEUR_PAGE, HAUTEUR_PAGE = 419.53, 297.64          # A6 paysage : 148 x 105 mm, en points
NUIT = (0.047, 0.106, 0.247)
GRIS = (0.35, 0.40, 0.52)
MARGE = 24

POLICES = {"F1": _LARGEURS_REGULIER, "F2": _LARGEURS_GRAS, "F3": _LARGEURS_REGULIER}


def _octets(texte: str) -> bytes:
    return texte.encode("cp1252", errors="replace")


def largeur_texte(texte, police, taille, espacement=0.0) -> float:
    table = POLICES[police]
    total = sum(table[c - 32] if 32 <= c <= 255 else 556 for c in _octets(texte))
    return total * taille / 1000 + espacement * len(texte)


def ajuster(texte, police, taille, largeur_max, taille_min=6.5):
    """Réduit la taille puis tronque (…) pour que le texte tienne dans la largeur disponible."""
    while taille > taille_min and largeur_texte(texte, police, taille) > largeur_max:
        taille -= 0.5
    while len(texte) > 1 and largeur_texte(texte, police, taille) > largeur_max:
        texte = texte[:-2].rstrip() + "…"
    return texte, taille


def _echapper(octets: bytes) -> bytes:
    return octets.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _num(x) -> str:
    return f"{x:.2f}"


class _Contenu:
    def __init__(self):
        self.ops = []

    def couleur(self, rgb, trait=False):
        self.ops.append(f"{rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} {'RG' if trait else 'rg'}")

    def ligne(self, x1, y1, x2, y2, epaisseur=0.6, rgb=NUIT):
        self.couleur(rgb, trait=True)
        self.ops.append(f"{epaisseur} w {_num(x1)} {_num(y1)} m {_num(x2)} {_num(y2)} l S")

    def rectangle(self, x, y, l, h, epaisseur=1.0, rgb=NUIT):
        self.couleur(rgb, trait=True)
        self.ops.append(f"{epaisseur} w {_num(x)} {_num(y)} {_num(l)} {_num(h)} re S")

    def fond(self, x, y, l, h, rgb):
        self.couleur(rgb)
        self.ops.append(f"{_num(x)} {_num(y)} {_num(l)} {_num(h)} re f")

    def texte(self, x, y, texte, police="F1", taille=10, rgb=NUIT, espacement=0.0):
        self.couleur(rgb)
        self.ops.append(f"BT /{police} {taille} Tf {espacement} Tc {_num(x)} {_num(y)} Td "
                        + "(" + _echapper(_octets(texte)).decode("latin-1") + ") Tj ET")

    def texte_centre(self, centre_x, y, texte, police="F1", taille=10, rgb=NUIT, espacement=0.0):
        self.texte(centre_x - largeur_texte(texte, police, taille, espacement) / 2, y, texte, police, taille, rgb, espacement)

    def texte_droite(self, x_droite, y, texte, police="F1", taille=10, rgb=NUIT):
        self.texte(x_droite - largeur_texte(texte, police, taille), y, texte, police, taille, rgb)

    def image(self, x, y, l, h):
        self.ops.append(f"q {_num(l)} 0 0 {_num(h)} {_num(x)} {_num(y)} cm /Im1 Do Q")

    def octets(self) -> bytes:
        return "\n".join(self.ops).encode("latin-1")


def _dimensions_jpeg(donnees: bytes):
    """(largeur, hauteur, composantes) lus dans l'en-tête du JPEG."""
    i = 2
    while i < len(donnees):
        if donnees[i] != 0xFF:
            i += 1
            continue
        marqueur = donnees[i + 1]
        if marqueur in (0xC0, 0xC1, 0xC2):
            hauteur, largeur = struct.unpack(">HH", donnees[i + 5:i + 9])
            return largeur, hauteur, donnees[i + 9]
        i += 2 + struct.unpack(">H", donnees[i + 2:i + 4])[0]
    raise ValueError("JPEG illisible")


def _assembler_pdf(contenu: bytes, jpeg: bytes, largeur=LARGEUR_PAGE, hauteur=HAUTEUR_PAGE,
                   polices=("Helvetica", "Helvetica-Bold", "Helvetica-Oblique"), titre="Recu de paiement") -> bytes:
    largeur_img, hauteur_img, composantes = _dimensions_jpeg(jpeg)
    espace = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}[composantes]
    police = lambda nom: (f"<< /Type /Font /Subtype /Type1 /BaseFont /{nom} /Encoding /WinAnsiEncoding >>").encode()
    objets = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {largeur:.2f} {hauteur:.2f}] /Contents 4 0 R "
         "/Resources << /Font << /F1 5 0 R /F2 6 0 R /F3 7 0 R >> /XObject << /Im1 8 0 R >> >> >>").encode(),
        b"<< /Length %d >>\nstream\n" % len(contenu) + contenu + b"\nendstream",
        police(polices[0]), police(polices[1]), police(polices[2]),
        (f"<< /Type /XObject /Subtype /Image /Width {largeur_img} /Height {hauteur_img} /ColorSpace {espace} "
         f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg)} >>\nstream\n").encode() + jpeg + b"\nendstream",
        (f"<< /Title ({titre}) /Producer (GESTSCO) >>").encode("latin-1", "replace"),
    ]
    sortie = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    positions = []
    for numero, corps in enumerate(objets, start=1):
        positions.append(len(sortie))
        sortie += f"{numero} 0 obj\n".encode() + corps + b"\nendobj\n"
    debut_xref = len(sortie)
    sortie += f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n".encode()
    for pos in positions:
        sortie += f"{pos:010d} 00000 n \n".encode()
    sortie += (f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R /Info 9 0 R >>\nstartxref\n{debut_xref}\n%%EOF\n").encode()
    return bytes(sortie)


# ------------------------------------------------------------------ reçu au format « ticket de caisse »
# Ticket de 80 mm de large (papier des imprimantes thermiques de caisse), hauteur calculée d'après le contenu, police à chasse fixe
# (Courier, intégrée à tout lecteur PDF) : les colonnes s'alignent comme sur un ticket de supermarché.
LARGEUR_TICKET = 226.77            # 80 mm en points
COLONNES = 42                      # caractères par ligne à la taille normale
TAILLE_TICKET = 8.0
_CHASSE = 0.6                      # largeur d'un caractère Courier = 0,6 x la taille
MARGE_BAS_TICKET = 16

# Code 39 : 9 éléments par caractère (barre, espace, barre...), n = étroit, w = large
_CODE39 = {"0": "nnnwwnwnn", "1": "wnnwnnnnw", "2": "nnwwnnnnw", "3": "wnwwnnnnn", "4": "nnnwwnnnw",
           "5": "wnnwwnnnn", "6": "nnwwwnnnn", "7": "nnnwnnwnw", "8": "wnnwnnwnn", "9": "nnwwnnwnn", "*": "nwnnwnwnn"}


def _barres_code39(texte, module=1.15, large=2.5):
    """[(x, largeur)] des barres noires du code-barres Code 39 de `texte` (chiffres), et sa largeur totale."""
    barres, x = [], 0.0
    for i, c in enumerate("*" + texte + "*"):
        for j, e in enumerate(_CODE39[c]):
            l = module * (large if e == "w" else 1)
            if j % 2 == 0:
                barres.append((x, l))
            x += l
        x += module                                   # espace entre deux caractères
    return barres, x - module


def _coupe(texte, colonnes):
    """Découpe un texte en lignes de `colonnes` caractères au plus (aux espaces si possible)."""
    import textwrap
    return textwrap.wrap(" ".join(str(texte).split()), colonnes, break_long_words=True, break_on_hyphens=False) or [""]


def generer_recu_pdf(recu: dict, chemin, chemin_logo, duplicata=False, date_impression=""):
    """Écrit le reçu dans `chemin`, au format ticket de caisse (80 mm). `recu` vient de paiements.charger_recu().
    `duplicata` et `date_impression` sont ignorés : un duplicata est identique à l'original. Le nom du percepteur ne figure pas
    sur le reçu (son numéro reste enregistré dans le système)."""
    import config
    with open(chemin_logo, "rb") as f:
        jpeg = f.read()
    l_img, h_img, _ = _dimensions_jpeg(jpeg)
    L = LARGEUR_TICKET
    marge = (L - COLONNES * TAILLE_TICKET * _CHASSE) / 2
    elements = []                                      # (hauteur, fonction de dessin (contenu, y du haut de la ligne))

    def ligne(texte, gras=False, taille=TAILLE_TICKET, centre=False, couleur=NUIT, police=None):
        h = taille * 1.45
        f = police or ("F2" if gras else "F1")

        def dessiner(p, y):
            x = marge
            if centre:
                x = (L - len(texte) * taille * _CHASSE) / 2
            p.texte(x, y - taille * 1.05, texte, f, taille, couleur)
        elements.append((h, dessiner))

    def lignes(texte, **kw):
        taille = kw.get("taille", TAILLE_TICKET)
        for t in _coupe(texte, int(COLONNES * TAILLE_TICKET / taille)):
            ligne(t, **kw)

    def paire(gauche, droite, gras=False, taille=TAILLE_TICKET):
        """Libellé à gauche, valeur à droite, sur la même ligne (la valeur passe à la ligne suivante si elle ne tient pas)."""
        n = int(COLONNES * TAILLE_TICKET / taille)
        droite = str(droite)
        if len(gauche) + 1 + len(droite) > n:
            lignes(gauche, gras=gras, taille=taille)
            for t in _coupe(droite, n - 2):
                ligne(" " * (n - len(t)) + t, gras=gras, taille=taille)
        else:
            ligne(gauche + " " * (n - len(gauche) - len(droite)) + droite, gras=gras, taille=taille)

    def vide(h=6):
        elements.append((h, None))

    def trait(car="-"):
        ligne(car * COLONNES)

    def image_logo(hauteur=48):
        largeur = hauteur * l_img / h_img
        elements.append((hauteur + 4, lambda p, y: p.image((L - largeur) / 2, y - hauteur, largeur, hauteur)))

    def code_barres(valeur, hauteur=30):
        if not valeur or any(c not in _CODE39 or c == "*" for c in valeur):
            return
        barres, total = _barres_code39(valeur)
        x0 = (L - total) / 2

        def dessiner(p, y):
            p.couleur((0, 0, 0))
            for x, l in barres:
                p.ops.append(f"{_num(x0 + x)} {_num(y - hauteur)} {_num(l)} {_num(hauteur)} re f")
        elements.append((hauteur + 4, dessiner))

    nom_ecole = config.NOM_ECOLE.upper()
    devise = " ".join(config.DEVISE_ECOLE.split())

    # --- en-tête
    vide(4)
    image_logo()
    ligne(nom_ecole, gras=True, taille=11, centre=True)
    ligne(devise, taille=7.5, centre=True)
    vide(4)
    trait("=")
    ligne("REÇU DE PAIEMENT", gras=True, taille=10, centre=True)
    trait("=")

    # --- référence du reçu
    paire("Reçu N°", recu["n_recu"], gras=True)
    paire("Date", f"{recu['date_txt']}  {recu.get('heure_txt', '')}".rstrip())
    trait()

    # --- qui paie
    ligne("CANDIDAT À L'INSCRIPTION" if recu.get("candidat") else "ÉLÈVE", taille=7, couleur=GRIS)
    lignes(recu["nom_complet"].upper(), gras=True)
    if recu.get("matricule"):
        paire("Matricule", recu["matricule"])
    paire("Classe", recu["classe"])
    if recu["option"]:
        paire("Option", recu["option"])
    paire("Année", recu["annee"])
    trait()

    # --- l'article, comme une ligne de ticket de caisse
    paire("DÉSIGNATION", "MONTANT", gras=True)
    trait()
    lignes(recu["type_frais"])
    montant = f"{recu['montant_txt']} {recu['devise']}"
    ligne(" " * (COLONNES - len(montant)) + montant)
    trait()
    tr = recu.get("tranche")
    if tr:                                   # frais payé par tranches : montant payé et reste à payer de la tranche concernée
        paire("Tranche", f"{tr['numero']} sur {tr['nombre']}")
        paire("MONTANT PAYÉ", montant, gras=True, taille=9)
        paire("RESTE À PAYER (tranche)", f"{tr['reste_txt']} {recu['devise']}", gras=True, taille=9)
    else:
        paire("TOTAL", montant, gras=True, taille=11)
    trait("=")
    lignes(recu["motif"], taille=7.5, couleur=GRIS)
    cp = recu.get("code_parent")
    if cp and cp.get("code"):                 # code d'accès de l'application des parents (un seul usage)
        vide(4)
        trait("-")
        ligne("CODE D'ACCÈS PARENTS", gras=True, taille=9, centre=True)
        ligne(cp["code"], gras=True, taille=13, centre=True)
        lignes("Espace parents en ligne : " + (config.url_publique() + "/parents" if config.url_publique()
                                                              else "demandez l'adresse à l'école") + ", puis saisissez ce code.", taille=7, couleur=GRIS)
        lignes("Code personnel : ne le donnez à personne. Il ne sert qu'une fois, pour cet élève.", taille=7, couleur=GRIS)
    vide(8)

    # --- pied : code-barres du numéro de reçu, remerciement
    code_barres(recu["n_recu"])
    ligne(recu["n_recu"], taille=8, centre=True)
    vide(4)
    ligne("MERCI !", gras=True, taille=10, centre=True)
    ligne("Conservez ce reçu comme preuve de paiement.", taille=6.5, centre=True, couleur=GRIS)
    trait("-")

    hauteur = sum(h for h, _ in elements) + MARGE_BAS_TICKET
    p = _Contenu()
    y = hauteur
    for h, dessiner in elements:
        if dessiner:
            dessiner(p, y)
        y -= h

    with open(chemin, "wb") as f:
        f.write(_assembler_pdf(p.octets(), jpeg, largeur=L, hauteur=hauteur,
                               polices=("Courier", "Courier-Bold", "Courier-Oblique")))
    return str(chemin)

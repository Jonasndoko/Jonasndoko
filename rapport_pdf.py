"""Rapport journalier de caisse au format PDF (A4 portrait, plusieurs pages si nécessaire).
Même principe que recu_pdf.py : aucune bibliothèque externe."""

import config
from recu_pdf import GRIS, NUIT, _Contenu, _dimensions_jpeg, ajuster, largeur_texte

LARGEUR, HAUTEUR = 595.28, 841.89
MARGE = 40
BAS = 62                      # limite basse du tableau (pied de page en dessous)
HAUTEUR_LIGNE = 15.5
BLANC = (1, 1, 1)
FOND_CLAIR = (0.93, 0.95, 0.98)
FILET = (0.82, 0.86, 0.93)

# (titre, largeur, alignement)
COLONNES = [("N°", 24, "c"), ("N° Reçu", 69, "g"), ("Nom complet", 150, "g"),
            ("Classe", 112, "g"), ("Option", 90, "g"), ("Montant", 70.28, "d")]


def _positions():
    x, positions = MARGE, []
    for _titre, largeur, _al in COLONNES:
        positions.append(x)
        x += largeur
    return positions


POSITIONS = _positions()
DROITE = LARGEUR - MARGE


def _cellule(p, indice, texte, y, police="F1", taille=8.5, rgb=NUIT):
    _titre, largeur, alignement = COLONNES[indice]
    x = POSITIONS[indice]
    texte, taille = ajuster(str(texte), police, taille, largeur - 8, taille_min=6.5)
    if alignement == "c":
        p.texte_centre(x + largeur / 2, y, texte, police, taille, rgb)
    elif alignement == "d":
        p.texte_droite(x + largeur - 4, y, texte, police, taille, rgb)
    else:
        p.texte(x + 4, y, texte, police, taille, rgb)


class _MiseEnPage:
    def __init__(self, rapport, jpeg_dims):
        self.r = rapport
        self.l_img, self.h_img = jpeg_dims
        self.pages = []
        self.p = None
        self.y = 0

    # --- pages -------------------------------------------------------------
    def nouvelle_page(self):
        self.p = _Contenu()
        self.pages.append(self.p)
        p, r = self.p, self.r
        p.rectangle(MARGE - 14, 24, LARGEUR - 2 * (MARGE - 14), HAUTEUR - 48, 0.8, FILET)
        if len(self.pages) == 1:
            self._entete_complet()
        else:
            p.texte(MARGE, HAUTEUR - 46, config.NOM_ECOLE, "F2", 11)
            p.texte_droite(DROITE, HAUTEUR - 46, "RAPPORT JOURNALIER DE CAISSE", "F2", 11)
            p.texte(MARGE, HAUTEUR - 60, f"Date : {r['date_txt']}   •   {r['etiquette']}",
                    "F1", 8.5, GRIS)
            p.ligne(MARGE, HAUTEUR - 68, DROITE, HAUTEUR - 68, 0.8)
            self.y = HAUTEUR - 84

    def _entete_complet(self):
        p, r = self.p, self.r
        haut = HAUTEUR - 40
        h_logo = 66
        p.image(MARGE, haut - h_logo, h_logo * self.l_img / self.h_img, h_logo)
        p.texte_centre(LARGEUR / 2, haut - 28, config.NOM_ECOLE, "F2", 20)
        p.texte_centre(LARGEUR / 2, haut - 47, "DISCIPLINE - AMOUR - TRAVAIL", "F2", 10, espacement=0.9)
        p.ligne(MARGE, haut - h_logo - 10, DROITE, haut - h_logo - 10, 1.2)
        y = haut - h_logo - 36
        p.texte_centre(LARGEUR / 2, y, "RAPPORT JOURNALIER DE CAISSE", "F2", 15)
        y -= 30
        p.fond(MARGE, y - 28, DROITE - MARGE, 44, FOND_CLAIR)
        p.texte(MARGE + 10, y, "Date du rapport :", "F1", 9, GRIS)
        p.texte(MARGE + 10 + largeur_texte("Date du rapport :", "F1", 9) + 6, y, r["date_txt"], "F2", 11)
        p.texte(MARGE + 10, y - 18, "Percepteur :", "F1", 9, GRIS)
        p.texte(MARGE + 10 + largeur_texte("Percepteur :", "F1", 9) + 6, y - 18,
                r["etiquette_courte"], "F2", 11)
        p.texte_droite(DROITE - 10, y - 18, f"Édité le {r['edite_le']}", "F1", 8, GRIS)
        self.y = y - 52

    def assurer_place(self, hauteur, bas=BAS):
        if self.y - hauteur < bas:
            self.nouvelle_page()
            return True
        return False

    # --- éléments ----------------------------------------------------------
    def titre_groupe(self, texte, suite=False):
        p = self.p
        p.fond(MARGE, self.y - 5, DROITE - MARGE, 19, NUIT)
        p.texte(MARGE + 6, self.y, ("TYPE DE FRAIS :  " + texte.upper()) + ("   (suite)" if suite else ""),
                "F2", 9.5, BLANC)
        self.y -= 22
        p.fond(MARGE, self.y - 4, DROITE - MARGE, HAUTEUR_LIGNE, FOND_CLAIR)
        for i, (titre, _l, _a) in enumerate(COLONNES):
            _cellule(p, i, titre, self.y, "F2", 8.5)
        self.y -= HAUTEUR_LIGNE + 3

    def ligne_donnee(self, numero, l):
        p = self.p
        for i, valeur in enumerate((numero, l["n_recu"], l["nom_complet"], l["classe"], l["option"] or "-",
                                    l["montant_txt"])):
            _cellule(p, i, valeur, self.y, "F2" if i == 5 else "F1")
        p.ligne(MARGE, self.y - 4.5, DROITE, self.y - 4.5, 0.4, FILET)
        self.y -= HAUTEUR_LIGNE

    def totaux(self, libelle, totaux, fort=False):
        from argent import formater
        p = self.p
        for devise, cents in totaux:
            texte = f"{formater(cents)} {devise}"
            p.texte_droite(DROITE - 4, self.y, texte, "F2", 10 if fort else 9, NUIT)
            p.texte_droite(DROITE - 4 - largeur_texte(texte, "F2", 10 if fort else 9) - 12, self.y, libelle,
                           "F2" if fort else "F1", 10 if fort else 9, NUIT)
            self.y -= HAUTEUR_LIGNE + (2 if fort else 0)
            libelle = ""                                   # le libellé n'est écrit qu'à la 1re devise

    def construire(self):
        r = self.r
        self.nouvelle_page()
        for g in r["groupes"]:
            self.assurer_place(22 + HAUTEUR_LIGNE + 3 + 2 * HAUTEUR_LIGNE)
            self.titre_groupe(g["type_frais"])
            for numero, l in enumerate(g["lignes"], start=1):
                if self.assurer_place(HAUTEUR_LIGNE * 2):
                    self.titre_groupe(g["type_frais"], suite=True)
                self.ligne_donnee(numero, l)
            self.assurer_place(HAUTEUR_LIGNE * (len(g["totaux"]) + 1))
            self.y -= 3
            self.totaux(f"Total {g['type_frais']}  ({len(g['lignes'])} reçu(s)) :", sorted(g["totaux"].items()))
            self.y -= 12

        if not self.assurer_place(105 + 17 * len(r["totaux"]) + (14 if r["nb_annules"] else 0), bas=46):
            self.p.ligne(MARGE, self.y + 6, DROITE, self.y + 6, 1.2)      # filet, sauf en haut d'une nouvelle page
        self.y -= 8
        self.totaux(f"TOTAL GÉNÉRAL DE LA JOURNÉE  ({r['nb_recus']} reçu(s)) :", r["totaux"], fort=True)
        if r["nb_annules"]:
            self.p.texte(MARGE, self.y - 4, f"Note : {r['nb_annules']} reçu(s) annulé(s) ce jour, non comptés dans ce rapport.",
                         "F3", 8, GRIS)
            self.y -= 14

        # signature du percepteur
        self.y -= 18
        self.p.texte_droite(DROITE, self.y, f"Le {r['date_txt']}", "F2", 9.5)
        self.p.texte_droite(DROITE, self.y - 14, "Signature Percepteur" if r["n_perc"] else "Signature", "F1", 9)
        self.p.ligne(DROITE - 160, self.y - 46, DROITE, self.y - 46, 0.6, GRIS)
        self.p.texte_droite(DROITE, self.y - 57, r["etiquette_courte"], "F1", 7.5, GRIS)

        total = len(self.pages)
        for i, page in enumerate(self.pages, start=1):
            page.texte_centre(LARGEUR / 2, 32, f"Page {i} / {total}   •   Rapport de caisse du {r['date_txt']}",
                              "F1", 7.5, GRIS)
        return [page.octets() for page in self.pages]


def _assembler(contenus, jpeg, titre="Rapport journalier de caisse"):
    l_img, h_img, composantes = _dimensions_jpeg(jpeg)
    espace = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}[composantes]
    police = lambda nom: f"<< /Type /Font /Subtype /Type1 /BaseFont /{nom} /Encoding /WinAnsiEncoding >>".encode()
    n = len(contenus)
    kids = " ".join(f"{8 + 2 * i} 0 R" for i in range(n))
    objets = [                                                      # numéros 1 à 7
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        police("Helvetica"), police("Helvetica-Bold"), police("Helvetica-Oblique"),
        (f"<< /Type /XObject /Subtype /Image /Width {l_img} /Height {h_img} /ColorSpace {espace} "
         f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg)} >>\nstream\n").encode() + jpeg + b"\nendstream",
        f"<< /Title ({titre}) /Producer (GESTSCO) >>".encode("latin-1"),
    ]
    for i, contenu in enumerate(contenus):
        objets.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {LARGEUR} {HAUTEUR}] /Contents {9 + 2 * i} 0 R "
                       "/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> /XObject << /Im1 6 0 R >> >> >>").encode())
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
    sortie += (f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R /Info 7 0 R >>\nstartxref\n{debut_xref}\n%%EOF\n").encode()
    return bytes(sortie)


def generer_rapport_pdf(rapport: dict, chemin, chemin_logo):
    with open(chemin_logo, "rb") as f:
        jpeg = f.read()
    largeur_img, hauteur_img, _ = _dimensions_jpeg(jpeg)
    contenus = _MiseEnPage(rapport, (largeur_img, hauteur_img)).construire()
    with open(chemin, "wb") as f:
        f.write(_assembler(contenus, jpeg))
    return str(chemin)

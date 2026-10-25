"""Exports du module Traçabilité et audit au format PDF : tableau A4 PAYSAGE, plusieurs pages si nécessaire.
Même principe que rapport_pdf.py : aucune bibliothèque externe."""
import config
from recu_pdf import GRIS, NUIT, _Contenu, _dimensions_jpeg, ajuster, largeur_texte

LARGEUR, HAUTEUR = 841.89, 595.28            # A4 paysage
MARGE = 30
DROITE = LARGEUR - MARGE
HAUT_TABLEAU = HAUTEUR - 36                  # haut de la zone de contenu sur les pages suivantes
BAS = 48                                     # limite basse du tableau (pied de page en dessous)
INTERLIGNE = 9.5
TAILLE = 7.5
MAX_LIGNES_CELLULE = 3                       # une cellule « détail » trop longue est coupée après 3 lignes (…)
BLANC = (1, 1, 1)
FOND_CLAIR = (0.93, 0.95, 0.98)
FILET = (0.82, 0.86, 0.93)


def _decouper(texte, largeur_max, police="F1", taille=TAILLE) -> list:
    """Coupe un texte en lignes qui tiennent dans la largeur (à la limite d'un mot si possible)."""
    mots, lignes, courante = str(texte).split(), [], ""
    for mot in mots:
        essai = f"{courante} {mot}".strip()
        if largeur_texte(essai, police, taille) <= largeur_max:
            courante = essai
            continue
        if courante:
            lignes.append(courante)
        while largeur_texte(mot, police, taille) > largeur_max and len(mot) > 1:     # mot plus long que la cellule
            coupe = len(mot)
            while coupe > 1 and largeur_texte(mot[:coupe], police, taille) > largeur_max:
                coupe -= 1
            lignes.append(mot[:coupe])
            mot = mot[coupe:]
        courante = mot
    if courante:
        lignes.append(courante)
    return lignes or [""]


def _mise_en_page(titre, notes, colonnes, lignes, jpeg_dims):
    """Retourne la liste des pages (_Contenu). Les pieds de page sont ajoutés ensuite (numérotation connue)."""
    echelle = (DROITE - MARGE) / sum(c[1] for c in colonnes)             # les colonnes remplissent toute la largeur
    largeurs = [c[1] * echelle for c in colonnes]
    x_col = [MARGE + sum(largeurs[:i]) for i in range(len(colonnes))]
    pages, etat = [], {"p": None, "y": 0}

    def entete_tableau():
        p = etat["p"]
        p.fond(MARGE, etat["y"] - 4, DROITE - MARGE, 14, NUIT)
        for i, (nom, _l, al) in enumerate(colonnes):
            texte, taille = ajuster(nom, "F2", 8, largeurs[i] - 6, taille_min=6)
            if al == "d":
                p.texte_droite(x_col[i] + largeurs[i] - 3, etat["y"], texte, "F2", taille, BLANC)
            else:
                p.texte(x_col[i] + 3, etat["y"], texte, "F2", taille, BLANC)
        etat["y"] -= 17

    def nouvelle_page():
        p = _Contenu()
        pages.append(p)
        etat["p"] = p
        p.rectangle(MARGE - 12, 24, LARGEUR - 2 * (MARGE - 12), HAUTEUR - 48, 0.8, FILET)
        if len(pages) == 1:
            haut = HAUTEUR - 34
            l_img, h_img = jpeg_dims
            h_logo = 46
            p.image(MARGE, haut - h_logo, h_logo * l_img / h_img, h_logo)
            p.texte_centre(LARGEUR / 2, haut - 18, config.NOM_ECOLE, "F2", 17)
            p.texte_centre(LARGEUR / 2, haut - 34, "DISCIPLINE - AMOUR - TRAVAIL", "F2", 8.5, espacement=0.9)
            p.ligne(MARGE, haut - h_logo - 8, DROITE, haut - h_logo - 8, 1.2)
            y = haut - h_logo - 28
            p.texte_centre(LARGEUR / 2, y, titre.upper(), "F2", 13)
            y -= 16
            for note in notes:
                texte, taille = ajuster(note, "F1", 8.5, DROITE - MARGE, taille_min=6.5)
                p.texte(MARGE, y, texte, "F1", taille, GRIS)
                y -= 11.5
            etat["y"] = y - 6
        else:
            p.texte(MARGE, HAUTEUR - 34, config.NOM_ECOLE, "F2", 10)
            p.texte_droite(DROITE, HAUTEUR - 34, titre, "F2", 9)
            p.ligne(MARGE, HAUTEUR - 40, DROITE, HAUTEUR - 40, 0.8)
            etat["y"] = HAUT_TABLEAU - 12
        entete_tableau()

    nouvelle_page()
    for numero, ligne in enumerate(lignes):
        cellules = []
        for i, valeur in enumerate(ligne):
            morceaux = _decouper(valeur, largeurs[i] - 6)
            if len(morceaux) > MAX_LIGNES_CELLULE:
                morceaux = morceaux[:MAX_LIGNES_CELLULE]
                morceaux[-1] = morceaux[-1].rstrip()[:-1] + "…"
            cellules.append(morceaux)
        hauteur = max(len(c) for c in cellules) * INTERLIGNE + 3
        if etat["y"] - hauteur < BAS:
            nouvelle_page()
        p, y = etat["p"], etat["y"]
        if numero % 2 == 0:
            p.fond(MARGE, y - hauteur + INTERLIGNE - 1.5, DROITE - MARGE, hauteur, FOND_CLAIR)
        for i, morceaux in enumerate(cellules):
            for k, texte in enumerate(morceaux):
                if colonnes[i][2] == "d":
                    p.texte_droite(x_col[i] + largeurs[i] - 3, y - k * INTERLIGNE, texte, "F1", TAILLE)
                else:
                    p.texte(x_col[i] + 3, y - k * INTERLIGNE, texte, "F1", TAILLE)
        etat["y"] -= hauteur
    return pages


def _assembler(contenus, jpeg, titre):
    l_img, h_img, composantes = _dimensions_jpeg(jpeg)
    espace = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}[composantes]
    police = lambda nom: f"<< /Type /Font /Subtype /Type1 /BaseFont /{nom} /Encoding /WinAnsiEncoding >>".encode()
    n = len(contenus)
    kids = " ".join(f"{8 + 2 * i} 0 R" for i in range(n))
    objets = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        police("Helvetica"), police("Helvetica-Bold"), police("Helvetica-Oblique"),
        (f"<< /Type /XObject /Subtype /Image /Width {l_img} /Height {h_img} /ColorSpace {espace} "
         f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg)} >>\nstream\n").encode() + jpeg + b"\nendstream",
        f"<< /Title ({titre.encode('ascii', 'replace').decode()}) /Producer (GESTSCO) >>".encode("latin-1"),
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


def generer(titre, notes, colonnes, lignes, chemin, chemin_logo, pied=""):
    """Écrit le PDF. `colonnes` : [(titre, largeur relative, "g"|"d")] ; `lignes` : liste de listes de textes ;
    `notes` : lignes de texte sous le titre (filtres, totaux) ; `pied` : texte en bas de chaque page."""
    with open(chemin_logo, "rb") as f:
        jpeg = f.read()
    l_img, h_img, _ = _dimensions_jpeg(jpeg)
    pages = _mise_en_page(titre, notes, colonnes, lignes, (l_img, h_img))
    for i, p in enumerate(pages, start=1):
        p.ligne(MARGE, 40, DROITE, 40, 0.6, FILET)
        texte, taille = ajuster(pied, "F3", 7, DROITE - MARGE - 70, taille_min=5.5)
        p.texte(MARGE, 30, texte, "F3", taille, GRIS)
        p.texte_droite(DROITE, 30, f"Page {i} / {len(pages)}", "F1", 7.5, GRIS)
    with open(chemin, "wb") as f:
        f.write(_assembler([p.octets() for p in pages], jpeg, titre))
    return str(chemin)


# ================================================================== rapport d'audit : plusieurs sections (A4 paysage)
ROUGE = (0.70, 0.15, 0.12)
ORANGE = (0.71, 0.33, 0.04)
COULEURS = {"rouge": ROUGE, "orange": ORANGE, "gris": GRIS}


def _mise_en_page_rapport(titre, notes, sections, jpeg_dims, signatures):
    """Pages d'un rapport fait de sections : titre de section, notes, puis un tableau (en-tête répété à chaque page).
    `sections` : [{"titre", "notes": [...], "colonnes": [(titre, largeur, "g"|"d")], "lignes": [[...]],
    "couleurs": [None|"rouge"|"orange"|"gris" par ligne], "vide": texte affiché quand il n'y a aucune ligne}]."""
    pages, etat = [], {"p": None, "y": 0}

    def nouvelle_page():
        p = _Contenu()
        pages.append(p)
        etat["p"] = p
        p.rectangle(MARGE - 12, 24, LARGEUR - 2 * (MARGE - 12), HAUTEUR - 48, 0.8, FILET)
        if len(pages) == 1:
            haut = HAUTEUR - 34
            l_img, h_img = jpeg_dims
            h_logo = 46
            p.image(MARGE, haut - h_logo, h_logo * l_img / h_img, h_logo)
            p.texte_centre(LARGEUR / 2, haut - 18, config.NOM_ECOLE, "F2", 17)
            p.texte_centre(LARGEUR / 2, haut - 34, "DISCIPLINE - AMOUR - TRAVAIL", "F2", 8.5, espacement=0.9)
            p.ligne(MARGE, haut - h_logo - 8, DROITE, haut - h_logo - 8, 1.2)
            y = haut - h_logo - 28
            p.texte_centre(LARGEUR / 2, y, titre.upper(), "F2", 13)
            y -= 16
            for note in notes:
                texte, taille = ajuster(note, "F1", 8.5, DROITE - MARGE, taille_min=6.5)
                p.texte(MARGE, y, texte, "F1", taille, GRIS)
                y -= 11.5
            etat["y"] = y - 8
        else:
            p.texte(MARGE, HAUTEUR - 34, config.NOM_ECOLE, "F2", 10)
            p.texte_droite(DROITE, HAUTEUR - 34, titre, "F2", 9)
            p.ligne(MARGE, HAUTEUR - 40, DROITE, HAUTEUR - 40, 0.8)
            etat["y"] = HAUT_TABLEAU - 24

    def titre_section(texte, suite=False):
        p, y = etat["p"], etat["y"]
        p.texte(MARGE, y, texte + ("  (suite)" if suite else ""), "F2", 10.5)
        p.ligne(MARGE, y - 4, DROITE, y - 4, 0.8, FILET)
        etat["y"] -= 18

    def entete_tableau(colonnes, largeurs, x_col):
        p = etat["p"]
        p.fond(MARGE, etat["y"] - 4, DROITE - MARGE, 14, NUIT)
        for i, (nom, _l, al) in enumerate(colonnes):
            texte, taille = ajuster(nom, "F2", 8, largeurs[i] - 6, taille_min=6)
            if al == "d":
                p.texte_droite(x_col[i] + largeurs[i] - 3, etat["y"], texte, "F2", taille, BLANC)
            else:
                p.texte(x_col[i] + 3, etat["y"], texte, "F2", taille, BLANC)
        etat["y"] -= 17

    nouvelle_page()
    for section in sections:
        colonnes, lignes = section["colonnes"], section["lignes"]
        section_notes = section.get("notes", [])
        besoin = 24 + 11 * len(section_notes) + (17 + 2 * INTERLIGNE if lignes else 16)
        if etat["y"] - besoin < BAS:
            nouvelle_page()
        titre_section(section["titre"])
        for note in section_notes:
            texte, taille = ajuster(note, "F1", 8, DROITE - MARGE, taille_min=6.5)
            etat["p"].texte(MARGE, etat["y"], texte, "F1", taille, GRIS)
            etat["y"] -= 11
        if section_notes:
            etat["y"] -= 4
        if not lignes:
            etat["p"].texte(MARGE, etat["y"] - 2, section.get("vide", "Rien à signaler."), "F3", 8.5, GRIS)
            etat["y"] -= 22
            continue
        echelle = (DROITE - MARGE) / sum(c[1] for c in colonnes)
        largeurs = [c[1] * echelle for c in colonnes]
        x_col = [MARGE + sum(largeurs[:i]) for i in range(len(colonnes))]
        entete_tableau(colonnes, largeurs, x_col)
        couleurs = section.get("couleurs") or [None] * len(lignes)
        for numero, ligne in enumerate(lignes):
            cellules = []
            for i, valeur in enumerate(ligne):
                morceaux = _decouper(valeur, largeurs[i] - 6)
                if len(morceaux) > MAX_LIGNES_CELLULE:
                    morceaux = morceaux[:MAX_LIGNES_CELLULE]
                    morceaux[-1] = morceaux[-1].rstrip()[:-1] + "…"
                cellules.append(morceaux)
            hauteur = max(len(c) for c in cellules) * INTERLIGNE + 3
            if etat["y"] - hauteur < BAS:
                nouvelle_page()
                titre_section(section["titre"], suite=True)
                entete_tableau(colonnes, largeurs, x_col)
            p, y = etat["p"], etat["y"]
            if numero % 2 == 0:
                p.fond(MARGE, y - hauteur + INTERLIGNE - 1.5, DROITE - MARGE, hauteur, FOND_CLAIR)
            rgb = COULEURS.get(couleurs[numero], NUIT)
            for i, morceaux in enumerate(cellules):
                for k, texte in enumerate(morceaux):
                    if colonnes[i][2] == "d":
                        p.texte_droite(x_col[i] + largeurs[i] - 3, y - k * INTERLIGNE, texte, "F1", TAILLE, rgb)
                    else:
                        p.texte(x_col[i] + 3, y - k * INTERLIGNE, texte, "F1", TAILLE, rgb)
            etat["y"] -= hauteur
        etat["y"] -= 10
    if signatures:
        if etat["y"] - 80 < BAS:
            nouvelle_page()
        y = etat["y"] - 14
        largeur_bloc = (DROITE - MARGE) / len(signatures)
        for i, (role, nom) in enumerate(signatures):
            x = MARGE + i * largeur_bloc
            etat["p"].texte(x, y, role, "F2", 8.5)
            if nom:
                etat["p"].texte(x, y - 11, nom, "F1", 8, GRIS)
            etat["p"].ligne(x, y - 46, x + largeur_bloc - 30, y - 46, 0.6, GRIS)
            etat["p"].texte(x, y - 56, "Date et signature", "F3", 7, GRIS)
        etat["y"] = y - 60
    return pages


def generer_rapport(titre, notes, sections, chemin, chemin_logo, pied="", signatures=()):
    """Écrit le PDF d'un rapport d'audit à sections. Retourne le chemin."""
    with open(chemin_logo, "rb") as f:
        jpeg = f.read()
    l_img, h_img, _ = _dimensions_jpeg(jpeg)
    pages = _mise_en_page_rapport(titre, notes, sections, (l_img, h_img), signatures)
    for i, p in enumerate(pages, start=1):
        p.ligne(MARGE, 40, DROITE, 40, 0.6, FILET)
        texte, taille = ajuster(pied, "F3", 7, DROITE - MARGE - 70, taille_min=5.5)
        p.texte(MARGE, 30, texte, "F3", taille, GRIS)
        p.texte_droite(DROITE, 30, f"Page {i} / {len(pages)}", "F1", 7.5, GRIS)
    with open(chemin, "wb") as f:
        f.write(_assembler([p.octets() for p in pages], jpeg, titre))
    return str(chemin)

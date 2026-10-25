"""Carte d'élève au format PDF : format portrait (54 x 85,6 mm, la hauteur dépasse la largeur).

Recto : logo et nom de l'école en haut, photo, puis, juste en dessous, les informations de l'élève.
Verso : QR code de l'élève au milieu de la carte ; en bas, le nom de l'école et sa devise.
Même moteur de dessin que les reçus (recu_pdf.py) : aucune bibliothèque externe.
"""
import config
import qr
from recu_pdf import GRIS, NUIT, _Contenu, _dimensions_jpeg, ajuster, largeur_texte

L, H = 153.07, 242.65                  # carte : 54 x 85,6 mm en points
BLANC = (1, 1, 1)
FILET = (0.82, 0.86, 0.93)
FOND_CLAIR = (0.93, 0.95, 0.98)
A4 = (595.28, 841.89)


def _image(p, nom, x, y, l, h):
    p.ops.append(f"q {l:.2f} 0 0 {h:.2f} {x:.2f} {y:.2f} cm /{nom} Do Q")


def _lignes(texte, largeur, police="F2", taille=6.4, maxi=2):
    """Découpe un texte long en `maxi` lignes au plus (la dernière est abrégée si besoin)."""
    mots, lignes, courante = texte.split(), [], ""
    for m in mots:
        essai = (courante + " " + m).strip()
        if largeur_texte(essai, police, taille) <= largeur or not courante:
            courante = essai
        else:
            lignes.append(courante)
            courante = m
    if courante:
        lignes.append(courante)
    if len(lignes) > maxi:
        lignes = lignes[:maxi - 1] + [" ".join(lignes[maxi - 1:])]
    return [ajuster(l, police, taille, largeur, taille_min=taille) for l in lignes] or [("", taille)]


def recto(p, ox, oy, f, dims_logo, dims_photo):
    p.rectangle(ox, oy, L, H, 0.9, NUIT)
    # --- haut : logo, nom de l'école
    h_logo = 30
    l_logo = h_logo * dims_logo[0] / dims_logo[1]
    _image(p, "Im1", ox + (L - l_logo) / 2, oy + H - 8 - h_logo, l_logo, h_logo)
    y = oy + H - 8 - h_logo - 11
    p.texte_centre(ox + L / 2, y, config.NOM_ECOLE, "F2", 8.6, NUIT)
    p.texte_centre(ox + L / 2, y - 9, "CARTE D'ÉLÈVE", "F2", 6.2, GRIS, espacement=1.2)
    p.ligne(ox + 10, y - 14, ox + L - 10, y - 14, 0.8, NUIT)
    # --- photo (portrait 3 : 4)
    lp, hp = 54, 72
    xp, yp = ox + (L - lp) / 2, y - 14 - 6 - hp
    if dims_photo:
        _image(p, "Im2", xp, yp, lp, hp)
    else:
        p.fond(xp, yp, lp, hp, FOND_CLAIR)
        p.texte_centre(ox + L / 2, yp + hp / 2 - 2, "PHOTO", "F2", 8, GRIS)
    p.rectangle(xp, yp, lp, hp, 0.8, NUIT)
    # --- juste en dessous : les informations
    y = yp - 11
    if largeur_texte(f["nom_complet"].upper(), "F2", 8.2) <= L - 14:          # un nom court tient sur une ligne
        morceaux = [(f["nom_complet"].upper(), 8.2)]
    else:                                                                       # un nom long passe sur 2 lignes
        morceaux = _lignes(f["nom_complet"].upper(), L - 14, "F2", 7.2, maxi=2)
    for k, (texte, taille) in enumerate(morceaux):
        p.texte_centre(ox + L / 2, y - 8.6 * k, texte, "F2", taille, NUIT)
    y -= 8.6 * (len(morceaux) - 1) + 4
    p.ligne(ox + 30, y, ox + L - 30, y, 0.5, FILET)
    y -= 8
    x_lib, x_val = ox + 9, ox + 9 + 38
    largeur_val = L - 9 - 38 - 7
    naissance = f["naissance"] + (f" à {f['lieu_naissance']}" if f["lieu_naissance"] and f["naissance"] else f["lieu_naissance"])
    lignes = [("Matricule", f["matricule"]),
              ("Classe", f["classe"] + (f" - {f['option']}" if f["option"] and f["option"] not in f["classe"] else "")),
              ("Sexe", f["sexe_txt"]), ("Né(e) le", naissance), ("Nationalité", f["nationalite"]),
              ("Adresse", f["adresse"]), ("Année", f["annee"])]
    for libelle, valeur in lignes:
        if libelle == "Adresse":
            morceaux = _lignes(valeur or "-", largeur_val)
        else:
            morceaux = [ajuster(valeur or "-", "F2", 6.4, largeur_val, taille_min=5.2)]
        p.texte(x_lib, y, libelle, "F1", 6.0, GRIS)
        for k, (morceau, taille_m) in enumerate(morceaux):
            p.texte(x_val, y - 8.2 * k, morceau, "F2", taille_m, NUIT)
        y -= 8.2 * len(morceaux) + 0.4


def verso(p, ox, oy, f):
    p.rectangle(ox, oy, L, H, 0.9, NUIT)
    p.texte_centre(ox + L / 2, oy + H - 24, "CARTE D'ÉLÈVE", "F2", 7.4, GRIS, espacement=1.4)
    m = qr.matrice(f["code_qr"])
    n = len(m)
    module = 3.4
    taille = n * module
    x0, y0 = ox + (L - taille) / 2, oy + (H - taille) / 2                   # au milieu de la carte
    marge = module * 2
    p.fond(x0 - marge, y0 - marge, taille + 2 * marge, taille + 2 * marge, BLANC)
    p.couleur(NUIT)
    for i, ligne in enumerate(m):                                           # séries de modules noirs par ligne
        j = 0
        while j < n:
            if ligne[j]:
                k = j
                while k < n and ligne[k]:
                    k += 1
                p.ops.append(f"{x0 + j * module:.2f} {y0 + (n - 1 - i) * module:.2f} {(k - j) * module + 0.05:.2f} "
                             f"{module + 0.05:.2f} re f")
                j = k
            else:
                j += 1
    p.texte_centre(ox + L / 2, y0 - marge - 11, f["matricule"], "F2", 8.2, NUIT)
    # --- bas : nom de l'école et devise
    p.ligne(ox + 12, oy + 42, ox + L - 12, oy + 42, 0.8, NUIT)
    nom, t = ajuster(config.NOM_ECOLE, "F2", 8.6, L - 16)
    p.texte_centre(ox + L / 2, oy + 28, nom, "F2", t, NUIT)
    devise, t = ajuster(" ".join(config.DEVISE_ECOLE.split()), "F1", 6.2, L - 16, taille_min=5)
    p.texte_centre(ox + L / 2, oy + 17, devise, "F1", t, GRIS)


def _assembler(pages, jpeg_logo, jpeg_photo):
    """pages : [(largeur, hauteur, contenu en octets)]. Objets : 1 catalogue, 2 pages, 3-5 polices, 6 logo,
    7 photo (ou image vide), 8 info, puis une paire (page, contenu) par page."""
    def xobjet(jpeg):
        l, h, comp = _dimensions_jpeg(jpeg)
        espace = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}[comp]
        return (f"<< /Type /XObject /Subtype /Image /Width {l} /Height {h} /ColorSpace {espace} /BitsPerComponent 8 "
                f"/Filter /DCTDecode /Length {len(jpeg)} >>\nstream\n").encode() + jpeg + b"\nendstream"

    police = lambda nom: f"<< /Type /Font /Subtype /Type1 /BaseFont /{nom} /Encoding /WinAnsiEncoding >>".encode()
    kids = " ".join(f"{9 + 2 * i} 0 R" for i in range(len(pages)))
    objets = [b"<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
              police("Helvetica"), police("Helvetica-Bold"), police("Helvetica-Oblique"),
              xobjet(jpeg_logo), xobjet(jpeg_photo or jpeg_logo),
              b"<< /Title (Carte d'eleve) /Producer (GESTSCO) >>"]
    for i, (largeur, hauteur, contenu) in enumerate(pages):
        objets.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {largeur:.2f} {hauteur:.2f}] /Contents {10 + 2 * i} 0 R "
                       "/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> /XObject << /Im1 6 0 R /Im2 7 0 R >> >> >>"
                       ).encode())
        objets.append(b"<< /Length %d >>\nstream\n" % len(contenu) + contenu + b"\nendstream")
    sortie, positions = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), []
    for numero, corps in enumerate(objets, start=1):
        positions.append(len(sortie))
        sortie += f"{numero} 0 obj\n".encode() + corps + b"\nendobj\n"
    debut = len(sortie)
    sortie += f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n".encode()
    for pos in positions:
        sortie += f"{pos:010d} 00000 n \n".encode()
    sortie += f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R /Info 8 0 R >>\nstartxref\n{debut}\n%%EOF\n".encode()
    return bytes(sortie)


def generer(f: dict, photo_jpeg, chemin, chemin_logo, a4=True):
    """Écrit le PDF de la carte. `photo_jpeg` : octets du JPEG de l'élève, ou None (cadre « PHOTO » vide)."""
    with open(chemin_logo, "rb") as fichier:
        logo = fichier.read()
    dims_logo = _dimensions_jpeg(logo)[:2]
    dims_photo = _dimensions_jpeg(photo_jpeg)[:2] if photo_jpeg else None
    if a4:
        p = _Contenu()
        ecart = 28
        x0 = (A4[0] - (2 * L + ecart)) / 2
        y0 = A4[1] - 70 - H
        p.texte_centre(A4[0] / 2, A4[1] - 44, f"Carte d'élève  -  {f['nom_complet']}", "F2", 11, NUIT)
        p.texte(x0, y0 - 16, "RECTO", "F2", 8, GRIS)
        p.texte(x0 + L + ecart, y0 - 16, "VERSO", "F2", 8, GRIS)
        p.texte_centre(A4[0] / 2, y0 - 40, "Imprimez à 100 % (taille réelle), découpez suivant le trait, puis collez ou "
                       "plastifiez recto-verso.", "F3", 8, GRIS)
        recto(p, x0, y0, f, dims_logo, dims_photo)
        verso(p, x0 + L + ecart, y0, f)
        pages = [(A4[0], A4[1], p.octets())]
    else:
        r, v = _Contenu(), _Contenu()
        recto(r, 0, 0, f, dims_logo, dims_photo)
        verso(v, 0, 0, f)
        pages = [(L, H, r.octets()), (L, H, v.octets())]
    with open(chemin, "wb") as fichier:
        fichier.write(_assembler(pages, logo, photo_jpeg))
    return str(chemin)

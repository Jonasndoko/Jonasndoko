"""Fiche des points d'un cours, dans une classe, pour une période : PDF A4 portrait (plusieurs pages si besoin).
Même principe que presences_pdf.py : aucune bibliothèque externe. Données : notes.fiche()."""
import config
import notes
from inscription_pdf import MARGE
from rapport_pdf import FILET, FOND_CLAIR, HAUTEUR, LARGEUR, _assembler
from recu_pdf import GRIS, _Contenu, _dimensions_jpeg, ajuster

HAUT_LIGNE = 16
BAS = 96                     # place du pied de page (légende + numéro de page)
DROITE = LARGEUR - MARGE
LARG_N, LARG_TOT, LARG_PCT, LARG_COND = 22, 38, 36, 34


def _colonnes(fiche):
    n = len(fiche["evaluations"])
    largeur_eval = 34 if n <= 6 else max(17, min(34, (DROITE - MARGE - 150 - LARG_N - LARG_TOT - LARG_PCT - LARG_COND) / n))
    nom = DROITE - MARGE - LARG_N - LARG_TOT - LARG_PCT - LARG_COND - n * largeur_eval
    x = MARGE
    positions = {}
    for cle, l in (("n", LARG_N), ("nom", nom)):
        positions[cle] = (x, l)
        x += l
    for ev in fiche["evaluations"]:
        positions[ev["id"]] = (x, largeur_eval)
        x += largeur_eval
    for cle, l in (("tot", LARG_TOT), ("pct", LARG_PCT), ("cond", LARG_COND)):
        positions[cle] = (x, l)
        x += l
    return positions


def _entete_page(fiche, dims_logo):
    p = _Contenu()
    centre = LARGEUR / 2
    p.rectangle(18, 18, LARGEUR - 36, HAUTEUR - 36, epaisseur=1.2)
    hl = 44
    p.image(MARGE - 4, HAUTEUR - 30 - hl, hl * dims_logo[0] / dims_logo[1], hl)
    p.texte_centre(centre, HAUTEUR - 52, config.NOM_ECOLE, "F2", 15)
    p.texte_centre(centre, HAUTEUR - 67, config.DEVISE_ECOLE, "F2", 8.5, espacement=0.8)
    p.ligne(MARGE, HAUTEUR - 82, DROITE, HAUTEUR - 82, 1.0)
    p.texte_centre(centre, HAUTEUR - 102, "RELEVÉ DES POINTS", "F2", 13)
    classe = fiche["classe"] + (f" - {fiche['option']}" if fiche["option"] else "")
    p.texte_centre(centre, HAUTEUR - 119, f"Cours : {fiche['cours']}   -   Classe : {classe}", "F2", 10)
    p.texte_centre(centre, HAUTEUR - 133, f"{fiche['periode']['semestre']}  -  {fiche['periode']['libelle']}  -  Année {fiche['annee']}",
                   "F1", 9.5, GRIS)
    p.texte_centre(centre, HAUTEUR - 146, f"Professeur : {fiche['professeur']}", "F1", 9.5, GRIS)
    return p, HAUTEUR - 170


def generer_fiche_pdf(fiche: dict, chemin, chemin_logo, date_impression=""):
    with open(chemin_logo, "rb") as f:
        jpeg = f.read()
    l_img, h_img, _ = _dimensions_jpeg(jpeg)
    dims = (l_img, h_img)
    pos = _colonnes(fiche)
    pages = []
    p, y = _entete_page(fiche, dims)
    pages.append(p)

    def en_tete():
        nonlocal y
        p.fond(MARGE, y - 16, DROITE - MARGE, 28, FOND_CLAIR)
        p.texte_centre(pos["n"][0] + pos["n"][1] / 2, y - 3, "N°", "F2", 8, GRIS)
        p.texte(pos["nom"][0] + 3, y - 3, "Nom complet", "F2", 8, GRIS)
        for ev in fiche["evaluations"]:
            x, l = pos[ev["id"]]
            p.texte_centre(x + l / 2, y + 3, ev["code"], "F2", 8)
            p.texte_centre(x + l / 2, y - 9, f"/{ev['maximum']}", "F1", 7, GRIS)
        for cle, titre in (("tot", "TOT"), ("pct", "%"), ("cond", "CDT")):
            x, l = pos[cle]
            p.texte_centre(x + l / 2, y - 3, titre, "F2", 8)
        y -= 28

    en_tete()
    if not fiche["eleves"]:
        p.texte_centre(LARGEUR / 2, y - 10, "Aucun élève inscrit dans cette classe.", "F3", 10, GRIS)
    for i, e in enumerate(fiche["eleves"], start=1):
        if y < BAS:
            p, y = _entete_page(fiche, dims)
            pages.append(p)
            en_tete()
        if i % 2 == 0:
            p.fond(MARGE, y - 4, DROITE - MARGE, HAUT_LIGNE, (0.97, 0.98, 1))
        p.texte_centre(pos["n"][0] + pos["n"][1] / 2, y, str(i), "F1", 8.5)
        texte, taille = ajuster(e["nom_complet"], "F2", 8.5, pos["nom"][1] - 6)
        p.texte(pos["nom"][0] + 3, y, texte, "F2", taille)
        for ev in fiche["evaluations"]:
            v = e["points"].get(str(ev["id"]))
            x, l = pos[ev["id"]]
            p.texte_centre(x + l / 2, y, "-" if v is None else str(v), "F1", 8.5)
        x, l = pos["tot"]
        p.texte_centre(x + l / 2, y, f"{e['total']}/{e['sur']}" if e["sur"] else "-", "F2", 8)
        x, l = pos["pct"]
        p.texte_centre(x + l / 2, y, "-" if e["pourcentage"] is None else f"{e['pourcentage']:g}", "F1", 8.5)
        x, l = pos["cond"]
        p.texte_centre(x + l / 2, y, e["conduite"] or "-", "F2", 8.5)
        y -= HAUT_LIGNE

    leg = fiche["legende"]
    ligne1 = "Légende :  " + "  -  ".join(f"{t['sigle']} = {t['libelle'].lower()}" for t in leg["types"]) + "  -  TOT = total des points  -  % = pourcentage"
    ligne2 = "CDT = conduite :  " + "  -  ".join(f"{c['code']} = {c['libelle'].lower()}" for c in leg["conduite"])
    n = len(pages)
    for i, page in enumerate(pages, start=1):
        page.ligne(MARGE, 74, DROITE, 74, 0.5, FILET)
        for k, txt in enumerate((ligne1, ligne2)):
            t, taille = ajuster(txt, "F3", 7.5, DROITE - MARGE)
            page.texte(MARGE, 62 - k * 11, t, "F3", taille, GRIS)
        page.texte(MARGE, 34, f"Imprimé le {date_impression}", "F3", 8, GRIS)
        page.texte_droite(DROITE, 34, f"Page {i} / {n}", "F1", 8, GRIS)
    with open(chemin, "wb") as f:
        f.write(_assembler([pg.octets() for pg in pages], jpeg, titre="Relevé des points"))
    return str(chemin)

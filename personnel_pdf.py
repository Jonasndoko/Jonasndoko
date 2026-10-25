"""Fiche individuelle du personnel au format PDF (A4 portrait, une page).
Même principe que inscription_pdf.py : aucune bibliothèque externe."""
import config
from inscription_pdf import MARGE, _champ, _section
from recu_pdf import GRIS, NUIT, _Contenu, _dimensions_jpeg, ajuster
from rapport_pdf import FILET, FOND_CLAIR, HAUTEUR, LARGEUR, _assembler

MAX_DOCUMENTS_AFFICHES = 8


def _contenu(a: dict, documents: list, dims_logo, date_impression) -> bytes:
    p = _Contenu()
    droite, centre = LARGEUR - MARGE, LARGEUR / 2
    col2 = centre + 10
    p.rectangle(18, 18, LARGEUR - 36, HAUTEUR - 36, epaisseur=1.2)

    hauteur_logo = 62
    p.image(MARGE - 4, HAUTEUR - 34 - hauteur_logo, hauteur_logo * dims_logo[0] / dims_logo[1], hauteur_logo)
    p.texte_centre(centre, HAUTEUR - 62, config.NOM_ECOLE, "F2", 18)
    p.texte_centre(centre, HAUTEUR - 80, "DISCIPLINE - AMOUR - TRAVAIL", "F2", 9.5, espacement=0.8)
    p.ligne(MARGE, HAUTEUR - 106, droite, HAUTEUR - 106, 1.0)
    p.texte_centre(centre, HAUTEUR - 130, "FICHE INDIVIDUELLE DU PERSONNEL", "F2", 15)

    y = HAUTEUR - 164
    pas = 21
    p.fond(MARGE, y - 10, droite - MARGE, 36, FOND_CLAIR)
    p.texte(MARGE + 10, y + 4, "MATRICULE", "F2", 9, GRIS)
    p.texte(MARGE + 10, y - 8, a["matricule"], "F2", 13)
    p.texte(col2, y + 4, "SITUATION DANS L'ÉCOLE", "F2", 9, GRIS)
    p.texte(col2, y - 8, "En service" if a["actif"] else "Plus en service (dossier désactivé)", "F2", 11)
    y -= 46

    y = _section(p, y, "IDENTITÉ")
    _champ(p, MARGE, y, "Nom :", a["nom"], col2 - MARGE - 8)
    _champ(p, col2, y, "Postnom :", a["postnom"], droite - col2)
    y -= pas
    _champ(p, MARGE, y, "Prénom :", a["prenom"], col2 - MARGE - 8)
    _champ(p, col2, y, "Sexe :", a["libelle_sexe"], droite - col2)
    y -= pas
    _champ(p, MARGE, y, "Date de naissance :", a["date_naissance"], droite - MARGE)
    y -= 32

    y = _section(p, y, "COORDONNÉES")
    _champ(p, MARGE, y, "Adresse :", a["adresse"], droite - MARGE)
    y -= pas
    _champ(p, MARGE, y, "Téléphone :", a["telephone"], col2 - MARGE - 8)
    _champ(p, col2, y, "E-mail :", a["email"], droite - col2)
    y -= 32

    y = _section(p, y, "SITUATION PROFESSIONNELLE")
    _champ(p, MARGE, y, "Fonction :", a["fonction"], col2 - MARGE - 8)
    _champ(p, col2, y, "Statut :", a["libelle_statut"], droite - col2)
    y -= pas
    _champ(p, MARGE, y, "Date d'engagement :", a["date_engagement"], droite - MARGE)
    y -= 32

    y = _section(p, y, f"DOCUMENTS ADMINISTRATIFS NUMÉRISÉS ({len(documents)})")
    if not documents:
        p.texte(MARGE + 8, y, "Aucun document numérisé n'est joint à ce dossier.", "F3", 9.5, GRIS)
        y -= pas
    for d in documents[:MAX_DOCUMENTS_AFFICHES]:
        texte, taille = ajuster(f"{d['type_doc']}  -  {d['nom_fichier']}", "F1", 9.5, droite - MARGE - 110)
        p.texte(MARGE + 8, y, "•  " + texte, "F1", taille)
        p.texte_droite(droite, y, f"{d['format']}  {d['date_ajout']}", "F1", 8.5, GRIS)
        y -= 16
    if len(documents) > MAX_DOCUMENTS_AFFICHES:
        p.texte(MARGE + 8, y, f"... et {len(documents) - MAX_DOCUMENTS_AFFICHES} autre(s) document(s) dans le dossier.",
                "F3", 8.5, GRIS)

    y_sig = 150
    p.texte(MARGE, y_sig, "Signature de l'agent", "F1", 9)
    p.ligne(MARGE, y_sig - 36, MARGE + 170, y_sig - 36, 0.6, GRIS)
    p.texte_droite(droite, y_sig, "La Direction", "F1", 9)
    p.ligne(droite - 190, y_sig - 36, droite, y_sig - 36, 0.6, GRIS)

    p.ligne(MARGE, 74, droite, 74, 0.5, FILET)
    p.texte(MARGE, 60, "Document confidentiel : il contient des données personnelles. Ne le laissez pas à la portée de tous.",
            "F3", 8, GRIS)
    enreg = f"Dossier ouvert le {a['date_enreg']} par {a['enregistre_par']}"
    if a["date_modif"]:
        enreg += f"  •  dernière modification le {a['date_modif']}"
    p.texte(MARGE, 46, f"{enreg}  •  imprimé le {date_impression}", "F3", 8, GRIS)
    return p.octets()


def generer_fiche_pdf(agent: dict, documents: list, chemin, chemin_logo, date_impression=""):
    with open(chemin_logo, "rb") as f:
        jpeg = f.read()
    l_img, h_img, _ = _dimensions_jpeg(jpeg)
    contenu = _contenu(agent, documents, (l_img, h_img), date_impression)
    with open(chemin, "wb") as f:
        f.write(_assembler([contenu], jpeg, titre="Fiche individuelle du personnel"))
    return str(chemin)


# ================================================================== liste du personnel par fonction ou par service
HAUT_LIGNE = 15
BAS_LISTE = 70
# (titre, largeur) ; la 4ème colonne est le service (liste par fonction) ou la fonction (liste par service)
LARGEURS = (24, 64, 150, 100, 107, 70)


def _page_liste(liste: dict, dims_logo, premiere: bool) -> tuple:
    p = _Contenu()
    droite, centre = LARGEUR - MARGE, LARGEUR / 2
    p.rectangle(18, 18, LARGEUR - 36, HAUTEUR - 36, epaisseur=1.2)
    hauteur_logo = 44
    p.image(MARGE - 4, HAUTEUR - 30 - hauteur_logo, hauteur_logo * dims_logo[0] / dims_logo[1], hauteur_logo)
    p.texte_centre(centre, HAUTEUR - 52, config.NOM_ECOLE, "F2", 15)
    p.texte_centre(centre, HAUTEUR - 67, "DISCIPLINE - AMOUR - TRAVAIL", "F2", 8.5, espacement=0.8)
    p.ligne(MARGE, HAUTEUR - 82, droite, HAUTEUR - 82, 1.0)
    p.texte_centre(centre, HAUTEUR - 102, liste["titre"].upper(), "F2", 13)
    detail = f"Situation au {liste['jour']}  -  {liste['total']} agent(s)"
    if liste["filtre"]:
        detail = f"{'Fonction' if liste['mode'] == 'FONCTION' else 'Service'} : {liste['filtre']}  -  " + detail
    p.texte_centre(centre, HAUTEUR - 117, detail, "F1", 9.5, GRIS)
    return p, HAUTEUR - 140


def generer_liste_pdf(liste: dict, chemin, chemin_logo, date_impression=""):
    """Liste du personnel groupée (affectations.liste_personnel) : A4 portrait, plusieurs pages si nécessaire."""
    with open(chemin_logo, "rb") as f:
        jpeg = f.read()
    l_img, h_img, _ = _dimensions_jpeg(jpeg)
    dims = (l_img, h_img)
    x, positions = MARGE, []
    for largeur in LARGEURS:
        positions.append(x)
        x += largeur
    par_fonction = liste["mode"] == "FONCTION"
    titres = ("N°", "Matricule", "Nom complet", "Service" if par_fonction else "Fonction", "Responsabilité", "Depuis")
    droite = LARGEUR - MARGE

    pages = []
    p, y = _page_liste(liste, dims, True)
    pages.append(p)

    def nouvelle_page():
        nonlocal p, y
        p, y = _page_liste(liste, dims, False)
        pages.append(p)

    def entete_colonnes():
        nonlocal y
        for titre, x_col in zip(titres, positions):
            p.texte(x_col + 3, y, titre, "F2", 8, GRIS)
        p.ligne(MARGE, y - 4, droite, y - 4, 0.5, FILET)
        y -= HAUT_LIGNE + 1

    if not liste["groupes"]:
        p.texte_centre(LARGEUR / 2, y - 20, "Aucun agent à afficher.", "F3", 10, GRIS)
    for groupe in liste["groupes"]:
        if y - (18 + 2 * HAUT_LIGNE + 20) < BAS_LISTE:
            nouvelle_page()
        p.fond(MARGE, y - 5, droite - MARGE, 18, FOND_CLAIR)
        p.texte(MARGE + 6, y, groupe["libelle"], "F2", 10)
        p.texte_droite(droite - 6, y, f"{len(groupe['agents'])} agent(s)", "F1", 9, GRIS)
        y -= 26
        entete_colonnes()
        for i, a in enumerate(groupe["agents"], start=1):
            if y < BAS_LISTE:
                nouvelle_page()
                p.texte(MARGE + 6, y, groupe["libelle"] + " (suite)", "F2", 9, GRIS)
                y -= 18
                entete_colonnes()
            autre = a["service"] if par_fonction else a["fonction"]
            valeurs = (str(i), a["matricule"], a["nom_complet"], autre or "-", a["responsabilite"] or "-", a["depuis"] or "-")
            for k, (valeur, x_col, largeur) in enumerate(zip(valeurs, positions, LARGEURS)):
                texte, taille = ajuster(valeur, "F2" if k == 2 else "F1", 8.5, largeur - 6)
                p.texte(x_col + 3, y, texte, "F2" if k == 2 else "F1", taille)
            y -= HAUT_LIGNE
        y -= 12

    n = len(pages)
    for i, page in enumerate(pages, start=1):
        page.ligne(MARGE, 52, droite, 52, 0.5, FILET)
        page.texte(MARGE, 38, f"Imprimé le {date_impression}", "F3", 8, GRIS)
        page.texte_droite(droite, 38, f"Page {i} / {n}", "F1", 8, GRIS)
    with open(chemin, "wb") as f:
        f.write(_assembler([pg.octets() for pg in pages], jpeg, titre=liste["titre"]))
    return str(chemin)

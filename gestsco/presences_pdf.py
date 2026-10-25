"""État récapitulatif des présences et absences du personnel au format PDF (A4 portrait, plusieurs pages si nécessaire).
Même principe que personnel_pdf.py : aucune bibliothèque externe. Voir presences.etat_recapitulatif pour les données."""
import config
from inscription_pdf import MARGE
from rapport_pdf import FILET, FOND_CLAIR, HAUTEUR, LARGEUR, _assembler
from recu_pdf import GRIS, _Contenu, _dimensions_jpeg, ajuster

HAUT_LIGNE = 15
BAS = 70
DROITE = LARGEUR - MARGE

# (titre, largeur, centré ?) du tableau par agent
COLONNES = (("N°", 24, True), ("Nom complet", 180, False), ("Prés.", 38, True), ("Ret.", 34, True), ("Min.", 36, True),
            ("Abs.", 36, True), ("Perm.", 38, True), ("Cgé", 34, True), ("N.R.", 34, True), ("Taux", 40, True))
# détail des retards et des absences
COLONNES_DETAIL = (("Date", 58, False), ("Nom complet", 160, False), ("Situation", 62, False), ("Arrivée", 56, False),
                   ("Motif", 171, False))
# permissions et congés de la période
COLONNES_AUT = (("Nom complet", 160, False), ("Type", 58, False), ("Nature", 125, False), ("Du", 58, False), ("Au", 58, False))


def _positions(colonnes):
    x, positions = MARGE, []
    for _t, largeur, _c in colonnes:
        positions.append(x)
        x += largeur
    return positions


def _page(etat: dict, dims_logo) -> tuple:
    p = _Contenu()
    centre = LARGEUR / 2
    p.rectangle(18, 18, LARGEUR - 36, HAUTEUR - 36, epaisseur=1.2)
    hauteur_logo = 44
    p.image(MARGE - 4, HAUTEUR - 30 - hauteur_logo, hauteur_logo * dims_logo[0] / dims_logo[1], hauteur_logo)
    p.texte_centre(centre, HAUTEUR - 52, config.NOM_ECOLE, "F2", 15)
    p.texte_centre(centre, HAUTEUR - 67, config.DEVISE_ECOLE, "F2", 8.5, espacement=0.8)
    p.ligne(MARGE, HAUTEUR - 82, DROITE, HAUTEUR - 82, 1.0)
    p.texte_centre(centre, HAUTEUR - 102, etat["titre"].upper(), "F2", 12.5)
    p.texte_centre(centre, HAUTEUR - 117, f"Période du {etat['debut']} au {etat['fin']}  -  {etat['portee']}", "F1", 9.5, GRIS)
    p.texte_centre(centre, HAUTEUR - 130, f"{etat['jours_travail']} jour(s) de travail écoulé(s)  -  {len(etat['lignes'])} agent(s)",
                   "F1", 9, GRIS)
    return p, HAUTEUR - 154


def _valeur(l, cle, i):
    if cle == "N°":
        return str(i)
    return {"Nom complet": l["nom_complet"], "Prés.": str(l["presents"]), "Ret.": str(l["retards"]), "Min.": str(l["minutes"]),
            "Abs.": str(l["absents"]), "Perm.": str(l["permissions"]), "Cgé": str(l["conges"]), "N.R.": str(l["non_renseignes"]),
            "Taux": "-" if l["taux"] is None else f"{l['taux']} %"}[cle]


def generer_etat_pdf(etat: dict, chemin, chemin_logo, avec_detail=True, date_impression=""):
    with open(chemin_logo, "rb") as f:
        jpeg = f.read()
    l_img, h_img, _ = _dimensions_jpeg(jpeg)
    dims = (l_img, h_img)
    pages = []
    p, y = _page(etat, dims)
    pages.append(p)

    def nouvelle_page():
        nonlocal p, y
        p, y = _page(etat, dims)
        pages.append(p)

    def en_tete(colonnes, positions):
        nonlocal y
        for (titre, largeur, centre), x in zip(colonnes, positions):
            if centre:
                p.texte_centre(x + largeur / 2, y, titre, "F2", 8, GRIS)
            else:
                p.texte(x + 3, y, titre, "F2", 8, GRIS)
        p.ligne(MARGE, y - 4, DROITE, y - 4, 0.5, FILET)
        y -= HAUT_LIGNE + 1

    def titre_section(texte):
        nonlocal y
        if y - 60 < BAS:
            nouvelle_page()
        p.fond(MARGE, y - 5, DROITE - MARGE, 18, FOND_CLAIR)
        p.texte(MARGE + 6, y, texte, "F2", 10)
        y -= 26

    # ---- tableau par agent
    pos = _positions(COLONNES)
    titre_section("Récapitulatif par agent")
    en_tete(COLONNES, pos)
    if not etat["lignes"]:
        p.texte_centre(LARGEUR / 2, y - 14, "Aucun agent à afficher.", "F3", 10, GRIS)
        y -= 40
    for i, l in enumerate(etat["lignes"], start=1):
        if y < BAS:
            nouvelle_page()
            en_tete(COLONNES, pos)
        for k, ((titre, largeur, centre), x) in enumerate(zip(COLONNES, pos)):
            v = _valeur(l, titre, i)
            if centre:
                p.texte_centre(x + largeur / 2, y, v, "F1", 8.5)
            else:
                texte, taille = ajuster(v, "F2", 8.5, largeur - 6)
                p.texte(x + 3, y, texte, "F2", taille)
        y -= HAUT_LIGNE
    if etat["lignes"]:
        if y < BAS:
            nouvelle_page()
        p.ligne(MARGE, y + 10, DROITE, y + 10, 0.8)
        t = etat["totaux"]
        total = {"N°": "", "Nom complet": "TOTAL", "Prés.": t["presents"], "Ret.": t["retards"], "Min.": t["minutes"],
                 "Abs.": t["absents"], "Perm.": t["permissions"], "Cgé": t["conges"], "N.R.": t["non_renseignes"],
                 "Taux": "-" if t["taux"] is None else f"{t['taux']} %"}
        for (titre, largeur, centre), x in zip(COLONNES, pos):
            v = str(total[titre])
            if centre:
                p.texte_centre(x + largeur / 2, y, v, "F2", 8.5)
            else:
                p.texte(x + 3, y, v, "F2", 8.5)
        y -= HAUT_LIGNE + 6
    lignes_legende = ("Prés. : jours présents (hors retards)  -  Ret. : jours de retard  -  Min. : minutes de retard  -  Abs. : absences",
                      "Perm. : jours de permission  -  Cgé : jours de congé  -  N.R. : jours non renseignés",
                      "Taux de présence = (présents + retards) / (jours de travail - permissions - congés). Un agent en retard est présent.")
    if y < BAS + 40:
        nouvelle_page()
    for ligne in lignes_legende:
        texte, taille = ajuster(ligne, "F3", 7.5, DROITE - MARGE)
        p.texte(MARGE, y, texte, "F3", taille, GRIS)
        y -= 11
    y -= 11

    # ---- détail
    if avec_detail:
        pos_d = _positions(COLONNES_DETAIL)
        titre_section(f"Détail des retards et des absences ({len(etat['detail'])})")
        if not etat["detail"]:
            p.texte(MARGE + 6, y, "Aucun retard ni absence sur cette période.", "F3", 9.5, GRIS)
            y -= 22
        else:
            en_tete(COLONNES_DETAIL, pos_d)
        for e in etat["detail"]:
            if y < BAS:
                nouvelle_page()
                en_tete(COLONNES_DETAIL, pos_d)
            arrivee = f"{e['heure']} (+{e['minutes']} min)" if e["statut"] == "RETARD" else "-"
            for (titre, largeur, _c), x, v in zip(COLONNES_DETAIL, pos_d, (e["jour"], e["nom_complet"], e["libelle"], arrivee,
                                                                            e["motif"] or "-")):
                texte, taille = ajuster(v, "F1", 8.5, largeur - 6)
                p.texte(x + 3, y, texte, "F1", taille)
            y -= HAUT_LIGNE
        y -= 14
        pos_a = _positions(COLONNES_AUT)
        titre_section(f"Permissions et congés de la période ({len(etat['autorisations'])})")
        if not etat["autorisations"]:
            p.texte(MARGE + 6, y, "Aucune permission ni aucun congé sur cette période.", "F3", 9.5, GRIS)
            y -= 22
        else:
            en_tete(COLONNES_AUT, pos_a)
        for a in etat["autorisations"]:
            if y < BAS:
                nouvelle_page()
                en_tete(COLONNES_AUT, pos_a)
            for (titre, largeur, _c), x, v in zip(COLONNES_AUT, pos_a, (a["nom_complet"], a["libelle_type"], a["nature"] or "-",
                                                                         a["debut"], a["fin"])):
                texte, taille = ajuster(v, "F1", 8.5, largeur - 6)
                p.texte(x + 3, y, texte, "F1", taille)
            y -= HAUT_LIGNE

    n = len(pages)
    for i, page in enumerate(pages, start=1):
        page.ligne(MARGE, 52, DROITE, 52, 0.5, FILET)
        page.texte(MARGE, 38, f"Imprimé le {date_impression}", "F3", 8, GRIS)
        page.texte_droite(DROITE, 38, f"Page {i} / {n}", "F1", 8, GRIS)
    with open(chemin, "wb") as f:
        f.write(_assembler([pg.octets() for pg in pages], jpeg, titre=etat["titre"]))
    return str(chemin)

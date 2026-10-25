"""Fiche d'inscription d'un candidat au format PDF (A4 portrait, une page).
Même principe que recu_pdf.py et rapport_pdf.py : aucune bibliothèque externe."""
import config
from recu_pdf import GRIS, NUIT, _Contenu, _dimensions_jpeg, ajuster, largeur_texte
from rapport_pdf import FILET, FOND_CLAIR, HAUTEUR, LARGEUR, _assembler

MARGE = 44


def _champ(p, x, y, libelle, valeur, largeur_max, gras=True):
    p.texte(x, y, libelle, "F1", 8.5, GRIS)
    x_val = x + largeur_texte(libelle, "F1", 8.5) + 5
    texte, taille = ajuster(valeur or "—", "F2" if gras else "F1", 10.5, largeur_max - (x_val - x))
    p.texte(x_val, y, texte, "F2" if gras else "F1", taille)


def _section(p, y, titre):
    p.fond(MARGE, y - 5, LARGEUR - 2 * MARGE, 19, FOND_CLAIR)
    p.texte(MARGE + 8, y, titre, "F2", 10)
    return y - 26


def _contenu(f: dict, dims_logo, date_impression) -> bytes:
    p = _Contenu()
    droite, centre = LARGEUR - MARGE, LARGEUR / 2
    col2 = centre + 10
    p.rectangle(18, 18, LARGEUR - 36, HAUTEUR - 36, epaisseur=1.2)

    # en-tête : logo, nom de l'école, devise
    hauteur_logo = 62
    p.image(MARGE - 4, HAUTEUR - 34 - hauteur_logo, hauteur_logo * dims_logo[0] / dims_logo[1], hauteur_logo)
    p.texte_centre(centre, HAUTEUR - 62, config.NOM_ECOLE, "F2", 18)
    p.texte_centre(centre, HAUTEUR - 80, "DISCIPLINE - AMOUR - TRAVAIL", "F2", 9.5, espacement=0.8)
    p.ligne(MARGE, HAUTEUR - 106, droite, HAUTEUR - 106, 1.0)
    p.texte_centre(centre, HAUTEUR - 130, "FICHE D'INSCRIPTION", "F2", 15)
    p.texte_centre(centre, HAUTEUR - 146, f"Année scolaire {f['annee']}", "F1", 10, GRIS)

    y = HAUTEUR - 176
    pas = 21
    _champ(p, MARGE, y, "Candidature N° :", f["num_cand"], col2 - MARGE - 8)
    _champ(p, col2, y, "Reçu de paiement N° :", f["n_recu"], droite - col2)
    y -= 30

    y = _section(p, y, "IDENTITÉ DU CANDIDAT")
    _champ(p, MARGE, y, "Nom complet :", f["nom_complet"], droite - MARGE)
    y -= pas
    _champ(p, MARGE, y, "Sexe :", "Masculin" if f["sexe"] == "M" else "Féminin", col2 - MARGE - 8)
    _champ(p, col2, y, "Nationalité :", f["nationalite"], droite - col2)
    y -= pas
    _champ(p, MARGE, y, "Date de naissance :", f["date_naissance"], col2 - MARGE - 8)
    _champ(p, col2, y, "Lieu de naissance :", f["lieu_naissance"], droite - col2)
    y -= pas
    _champ(p, MARGE, y, "Adresse :", f["adresse"], droite - MARGE)
    y -= pas
    _champ(p, MARGE, y, "Téléphone :", f["telephone"], droite - MARGE)
    y -= 32

    y = _section(p, y, "PARCOURS SCOLAIRE")
    _champ(p, MARGE, y, "Ancienne école :", f["ecole_origine"], droite - MARGE)
    y -= pas
    _champ(p, MARGE, y, "Pourcentage obtenu :", f"{f['pourcent_origine']} %", col2 - MARGE - 8)
    _champ(p, col2, y, "Doublant :", "Oui" if f["doublant"] else "Non", droite - col2)
    y -= pas
    _champ(p, MARGE, y, "Classe souhaitée :", f["classe"], droite - MARGE)
    y -= 32

    y = _section(p, y, "TUTEUR")
    _champ(p, MARGE, y, "Nom du tuteur :", f["nom_tuteur"], droite - MARGE)
    y -= pas
    _champ(p, MARGE, y, "Téléphone :", f["tel_tuteur"], droite - MARGE)
    y -= pas
    _champ(p, MARGE, y, "Adresse :", f["adresse_tuteur"], droite - MARGE)
    y -= 32

    # situation sur la liste d'attente
    p.fond(MARGE, y - 10, droite - MARGE, 36, FOND_CLAIR)
    if f["rang"]:
        p.texte(MARGE + 10, y + 4, "LISTE D'ATTENTE", "F2", 9, GRIS)
        p.texte(MARGE + 10, y - 8, f"Position {f['rang']} dans la classe « {f['classe']} » à la date d'impression", "F2", 11)
    else:
        p.texte(MARGE + 10, y + 4, "STATUT", "F2", 9, GRIS)
        p.texte(MARGE + 10, y - 8, f["libelle_statut"], "F2", 11)

    # signatures
    y_sig = 150
    p.texte(MARGE, y_sig, "Signature du tuteur", "F1", 9)
    p.ligne(MARGE, y_sig - 36, MARGE + 170, y_sig - 36, 0.6, GRIS)
    p.texte_droite(droite, y_sig, "Signature de l'agent d'inscription", "F1", 9)
    p.ligne(droite - 190, y_sig - 36, droite, y_sig - 36, 0.6, GRIS)
    p.texte_droite(droite, y_sig - 48, f["enregistre_par"], "F1", 7.5, GRIS)

    p.ligne(MARGE, 74, droite, 74, 0.5, FILET)
    p.texte(MARGE, 60, "L'inscription définitive dépend de la décision de l'école. Conservez cette fiche et le reçu de paiement.",
            "F3", 8, GRIS)
    p.texte(MARGE, 46, f"Enregistré le {f['date_enreg']}  •  imprimé le {date_impression}", "F3", 8, GRIS)
    return p.octets()


def generer_fiche_pdf(fiche: dict, chemin, chemin_logo, date_impression=""):
    with open(chemin_logo, "rb") as f:
        jpeg = f.read()
    l_img, h_img, _ = _dimensions_jpeg(jpeg)
    contenu = _contenu(fiche, (l_img, h_img), date_impression)
    with open(chemin, "wb") as f:
        f.write(_assembler([contenu], jpeg, titre="Fiche d'inscription"))
    return str(chemin)


def _contenu_avis(f: dict, dims_logo, date_impression) -> bytes:
    p = _Contenu()
    droite, centre = LARGEUR - MARGE, LARGEUR / 2
    col2 = centre + 10
    p.rectangle(18, 18, LARGEUR - 36, HAUTEUR - 36, epaisseur=1.2)
    hauteur_logo = 62
    p.image(MARGE - 4, HAUTEUR - 34 - hauteur_logo, hauteur_logo * dims_logo[0] / dims_logo[1], hauteur_logo)
    p.texte_centre(centre, HAUTEUR - 62, config.NOM_ECOLE, "F2", 18)
    p.texte_centre(centre, HAUTEUR - 80, "DISCIPLINE - AMOUR - TRAVAIL", "F2", 9.5, espacement=0.8)
    p.ligne(MARGE, HAUTEUR - 106, droite, HAUTEUR - 106, 1.0)
    p.texte_centre(centre, HAUTEUR - 130, "AVIS D'ADMISSION", "F2", 15)
    p.texte_centre(centre, HAUTEUR - 146, f"Année scolaire {f['annee']}", "F1", 10, GRIS)

    y = HAUTEUR - 186
    pas = 21
    y = _section(p, y, "CANDIDAT")
    _champ(p, MARGE, y, "Nom complet :", f["nom_complet"], droite - MARGE)
    y -= pas
    _champ(p, MARGE, y, "Date de naissance :", f["date_naissance"], col2 - MARGE - 8)
    _champ(p, col2, y, "Lieu de naissance :", f["lieu_naissance"], droite - col2)
    y -= pas
    _champ(p, MARGE, y, "Candidature N° :", f["num_cand"], col2 - MARGE - 8)
    _champ(p, col2, y, "Reçu de paiement N° :", f["n_recu"], droite - col2)
    y -= 34

    y = _section(p, y, "DÉCISION")
    _champ(p, MARGE, y, "Note au test d'admission :", f"{f['note_test']} / 100", droite - MARGE)
    y -= pas
    _champ(p, MARGE, y, "Décision :", "Dossier validé - candidat admis", droite - MARGE)
    y -= pas
    _champ(p, MARGE, y, "Classe d'affectation :", f["classe_affectee"], droite - MARGE)
    y -= pas
    _champ(p, MARGE, y, "Date de la décision :", f["date_decision"], droite - MARGE)
    y -= 38

    p.fond(MARGE, y - 14, droite - MARGE, 52, FOND_CLAIR)
    p.texte(MARGE + 10, y + 20, "MATRICULE DE L'ÉLÈVE", "F2", 9, GRIS)
    p.texte(MARGE + 10, y - 6, f["matricule"], "F2", 22)

    y_sig = 170
    p.texte(MARGE, y_sig, "Signature du tuteur", "F1", 9)
    p.ligne(MARGE, y_sig - 36, MARGE + 170, y_sig - 36, 0.6, GRIS)
    p.texte_droite(droite, y_sig, "Direction des études", "F1", 9)
    p.ligne(droite - 190, y_sig - 36, droite, y_sig - 36, 0.6, GRIS)

    p.ligne(MARGE, 74, droite, 74, 0.5, FILET)
    p.texte(MARGE, 60, "Le candidat est désormais élève du collège. Conservez cet avis : le matricule sert à toutes les opérations.",
            "F3", 8, GRIS)
    p.texte(MARGE, 46, f"Imprimé le {date_impression}", "F3", 8, GRIS)
    return p.octets()


def generer_avis_admission_pdf(fiche: dict, chemin, chemin_logo, date_impression=""):
    with open(chemin_logo, "rb") as f:
        jpeg = f.read()
    l_img, h_img, _ = _dimensions_jpeg(jpeg)
    contenu = _contenu_avis(fiche, (l_img, h_img), date_impression)
    with open(chemin, "wb") as f:
        f.write(_assembler([contenu], jpeg, titre="Avis d'admission"))
    return str(chemin)

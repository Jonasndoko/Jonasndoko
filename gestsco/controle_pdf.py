"""Liste des élèves en ordre au format PDF (A4 portrait, plusieurs pages si nécessaire).
Même principe que rapport_pdf.py : aucune bibliothèque externe."""
import config
from rapport_pdf import (BAS, BLANC, DROITE, FILET, FOND_CLAIR, HAUTEUR, HAUTEUR_LIGNE, LARGEUR, MARGE, _assembler)
from controle import ligne_classe_option
from recu_pdf import GRIS, NUIT, _Contenu, _dimensions_jpeg, ajuster, largeur_texte

# (titre, largeur, alignement) : N°, NOM / POSTNOM / PRENOM, SEXE
COLONNES = [("N°", 40, "c"), ("NOM, POSTNOM ET PRENOM", 395.28, "g"), ("SEXE", 60, "c")]
TITRE_PIED = "Direction des études"


def _x(indice):
    return MARGE + sum(c[1] for c in COLONNES[:indice])


class _MiseEnPage:
    def __init__(self, liste, dims_jpeg):
        self.r = liste
        self.l_img, self.h_img = dims_jpeg
        self.pages, self.p, self.y = [], None, 0

    def _cellule(self, indice, texte, police="F1", taille=9.5):
        _t, largeur, alignement = COLONNES[indice]
        texte, taille = ajuster(str(texte), police, taille, largeur - 10, taille_min=7)
        if alignement == "c":
            self.p.texte_centre(_x(indice) + largeur / 2, self.y, texte, police, taille)
        else:
            self.p.texte(_x(indice) + 6, self.y, texte, police, taille)

    def nouvelle_page(self):
        self.p = _Contenu()
        self.pages.append(self.p)
        p, r = self.p, self.r
        p.rectangle(MARGE - 14, 24, LARGEUR - 2 * (MARGE - 14), HAUTEUR - 48, 0.8, FILET)
        if len(self.pages) == 1:
            self._entete_complet()
        else:
            p.texte(MARGE, HAUTEUR - 46, config.NOM_ECOLE, "F2", 11)
            p.texte_droite(DROITE, HAUTEUR - 46, f"{r['frais_txt']}", "F2", 9)
            p.texte(MARGE, HAUTEUR - 60, f"{r['classe_txt']}   •   Année {r['annee']}",
                    "F1", 8.5, GRIS)
            p.ligne(MARGE, HAUTEUR - 68, DROITE, HAUTEUR - 68, 0.8)
            self.y = HAUTEUR - 90
            self.entete_tableau()

    def _entete_complet(self):
        p, r = self.p, self.r
        haut = HAUTEUR - 40
        h_logo = 66
        p.image(MARGE, haut - h_logo, h_logo * self.l_img / self.h_img, h_logo)
        p.texte_centre(LARGEUR / 2, haut - 28, config.NOM_ECOLE, "F2", 20)
        p.texte_centre(LARGEUR / 2, haut - 47, "DISCIPLINE - AMOUR - TRAVAIL", "F2", 10, espacement=0.9)
        p.ligne(MARGE, haut - h_logo - 10, DROITE, haut - h_logo - 10, 1.2)
        y = haut - h_logo - 38
        # titre : « LISTE DES ELEVES EN ORDRE AVEC LE FRAIS » + type de frais ; réduit si trop long pour la page
        titre, taille = ajuster(r["titre"], "F2", 14, DROITE - MARGE, taille_min=9)
        p.texte_centre(LARGEUR / 2, y, titre, "F2", taille)
        y -= 20
        ligne, taille = ajuster(r["classe_txt"], "F2", 11.5, DROITE - MARGE, taille_min=8)
        p.texte_centre(LARGEUR / 2, y, ligne, "F2", taille)
        y -= 16
        p.texte_centre(LARGEUR / 2, y, f"Année scolaire {r['annee']}", "F1", 9.5, GRIS)
        y -= 26
        self.y = y
        self.entete_tableau()

    def entete_tableau(self):
        p = self.p
        p.fond(MARGE, self.y - 5, DROITE - MARGE, HAUTEUR_LIGNE + 3, NUIT)
        for i, (titre, _l, _a) in enumerate(COLONNES):
            _t, largeur, alignement = COLONNES[i]
            if alignement == "c":
                p.texte_centre(_x(i) + largeur / 2, self.y, titre, "F2", 8.5, BLANC)
            else:
                p.texte(_x(i) + 6, self.y, titre, "F2", 8.5, BLANC)
        self.y -= HAUTEUR_LIGNE + 6

    def construire(self):
        r = self.r
        self.nouvelle_page()
        for i, l in enumerate(r["lignes"]):
            if self.y - HAUTEUR_LIGNE < BAS:
                self.nouvelle_page()
            if i % 2:
                self.p.fond(MARGE, self.y - 4.5, DROITE - MARGE, HAUTEUR_LIGNE, FOND_CLAIR)
            for k, valeur in enumerate((l["n"], l["nom_complet"], l["sexe"])):
                self._cellule(k, valeur)
            self.p.ligne(MARGE, self.y - 4.5, DROITE, self.y - 4.5, 0.4, FILET)
            self.y -= HAUTEUR_LIGNE

        # total puis « Direction des études » en bas à droite, souligné
        if self.y - 110 < 46:
            self.nouvelle_page()
        self.y -= 8
        self.p.texte(MARGE, self.y, f"Total : {len(r['lignes'])} élève(s) en ordre", "F2", 9.5)
        self.y -= 46
        largeur = largeur_texte(TITRE_PIED, "F2", 11)
        self.p.texte_droite(DROITE - 6, self.y, TITRE_PIED, "F2", 11)
        self.p.ligne(DROITE - 6 - largeur, self.y - 2.5, DROITE - 6, self.y - 2.5, 0.9)      # soulignement

        total = len(self.pages)
        for i, page in enumerate(self.pages, start=1):
            page.texte_centre(LARGEUR / 2, 32, f"Page {i} / {total}   •   Édité le {r['edite_le']}", "F1", 7.5, GRIS)
        return [page.octets() for page in self.pages]


def generer_liste_pdf(liste: dict, chemin, chemin_logo):
    with open(chemin_logo, "rb") as f:
        jpeg = f.read()
    dims = _dimensions_jpeg(jpeg)[:2]
    donnees = dict(liste)
    donnees["classe_txt"] = ligne_classe_option(liste)
    donnees["frais_txt"] = f"ÉLÈVES EN ORDRE - {liste['type_frais'].upper()}"
    contenus = _MiseEnPage(donnees, dims).construire()
    with open(chemin, "wb") as f:
        f.write(_assembler(contenus, jpeg, "Liste des élèves en ordre"))
    return str(chemin)


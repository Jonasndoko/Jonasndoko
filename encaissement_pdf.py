"""Rapport global des encaissements au format PDF (A4 portrait, plusieurs pages si nécessaire).
Même principe que rapport_pdf.py : aucune bibliothèque externe.

Contenu : 1) les paiements de la date, de TOUS les percepteurs, séparés par type de frais ;
2) les encaissements enregistrés : montant encaissé, montant versé, écart, par percepteur."""
import config
from argent import formater
from rapport_pdf import (BAS, BLANC, DROITE, FILET, FOND_CLAIR, HAUTEUR, HAUTEUR_LIGNE, LARGEUR, MARGE, _assembler)
from recu_pdf import GRIS, NUIT, _Contenu, _dimensions_jpeg, ajuster, largeur_texte

ROUGE = (0.70, 0.15, 0.12)
VERT = (0.12, 0.48, 0.20)

# (titre, largeur, alignement) ; la somme des largeurs = LARGEUR - 2 * MARGE = 515.28
COL_FRAIS = [("N°", 28, "c"), ("Percepteur", 237.28, "g"), ("Reçus", 60, "c"), ("Montant encaissé (reçus)", 190, "d")]
COL_VERS = [("N° op.", 40, "c"), ("Percepteur", 163.28, "g"), ("Devise", 48, "c"), ("Encaissé", 88, "d"),
            ("Versé", 88, "d"), ("Écart", 88, "d")]


def _positions(colonnes):
    x, positions = MARGE, []
    for _t, largeur, _a in colonnes:
        positions.append(x)
        x += largeur
    return positions


class _MiseEnPage:
    def __init__(self, rapport, dims_jpeg):
        self.r = rapport
        self.l_img, self.h_img = dims_jpeg
        self.pages, self.p, self.y = [], None, 0

    # --- cellules ------------------------------------------------------------
    def _cellule(self, colonnes, indice, texte, police="F1", taille=8.5, rgb=NUIT):
        _t, largeur, alignement = colonnes[indice]
        x = _positions(colonnes)[indice]
        texte, taille = ajuster(str(texte), police, taille, largeur - 8, taille_min=6.5)
        if alignement == "c":
            self.p.texte_centre(x + largeur / 2, self.y, texte, police, taille, rgb)
        elif alignement == "d":
            self.p.texte_droite(x + largeur - 4, self.y, texte, police, taille, rgb)
        else:
            self.p.texte(x + 4, self.y, texte, police, taille, rgb)

    # --- pages ---------------------------------------------------------------
    def nouvelle_page(self):
        self.p = _Contenu()
        self.pages.append(self.p)
        p, r = self.p, self.r
        p.rectangle(MARGE - 14, 24, LARGEUR - 2 * (MARGE - 14), HAUTEUR - 48, 0.8, FILET)
        if len(self.pages) == 1:
            self._entete_complet()
        else:
            p.texte(MARGE, HAUTEUR - 46, config.NOM_ECOLE, "F2", 11)
            p.texte_droite(DROITE, HAUTEUR - 46, "RAPPORT GLOBAL DES ENCAISSEMENTS", "F2", 11)
            p.texte(MARGE, HAUTEUR - 60, f"Date : {r['date_txt']}   •   Tous les percepteurs", "F1", 8.5, GRIS)
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
        p.texte_centre(LARGEUR / 2, y, "RAPPORT GLOBAL DES ENCAISSEMENTS", "F2", 15)
        y -= 30
        p.fond(MARGE, y - 28, DROITE - MARGE, 44, FOND_CLAIR)
        p.texte(MARGE + 10, y, "Date du rapport :", "F1", 9, GRIS)
        p.texte(MARGE + 10 + largeur_texte("Date du rapport :", "F1", 9) + 6, y, r["date_txt"], "F2", 11)
        p.texte(MARGE + 10, y - 18, "Percepteurs :", "F1", 9, GRIS)
        p.texte(MARGE + 10 + largeur_texte("Percepteurs :", "F1", 9) + 6, y - 18, "Tous les percepteurs", "F2", 11)
        p.texte_droite(DROITE - 10, y - 18, f"Édité le {r['edite_le']}", "F1", 8, GRIS)
        self.y = y - 52

    def assurer_place(self, hauteur, bas=BAS):
        if self.y - hauteur < bas:
            self.nouvelle_page()
            return True
        return False

    # --- éléments ------------------------------------------------------------
    def bandeau(self, texte, colonnes):
        p = self.p
        p.fond(MARGE, self.y - 5, DROITE - MARGE, 19, NUIT)
        p.texte(MARGE + 6, self.y, texte, "F2", 9.5, BLANC)
        self.y -= 22
        p.fond(MARGE, self.y - 4, DROITE - MARGE, HAUTEUR_LIGNE, FOND_CLAIR)
        for i, (titre, _l, _a) in enumerate(colonnes):
            self._cellule(colonnes, i, titre, "F2", 8.5)
        self.y -= HAUTEUR_LIGNE + 3

    def filet_ligne(self):
        self.p.ligne(MARGE, self.y - 4.5, DROITE, self.y - 4.5, 0.4, FILET)
        self.y -= HAUTEUR_LIGNE

    def total_droite(self, libelle, texte, fort=False):
        taille = 10 if fort else 9
        self.p.texte_droite(DROITE - 4, self.y, texte, "F2", taille, NUIT)
        self.p.texte_droite(DROITE - 4 - largeur_texte(texte, "F2", taille) - 12, self.y, libelle,
                            "F2" if fort else "F1", taille, NUIT)
        self.y -= HAUTEUR_LIGNE + (2 if fort else 0)

    def construire(self):
        r = self.r
        self.nouvelle_page()

        # ---- 1) paiements par type de frais
        if r["groupes"]:
            self.p.texte(MARGE, self.y, "1.  PAIEMENTS DE LA JOURNÉE, PAR TYPE DE FRAIS", "F2", 10.5)
            self.y -= 20
        for g in r["groupes"]:
            titre = "TYPE DE FRAIS :  " + g["type_frais"].upper()
            self.assurer_place(22 + HAUTEUR_LIGNE + 3 + 2 * HAUTEUR_LIGNE)
            self.bandeau(titre, COL_FRAIS)
            for numero, l in enumerate(g["lignes"], start=1):
                if self.assurer_place(HAUTEUR_LIGNE * 2):
                    self.bandeau(titre + "   (suite)", COL_FRAIS)
                for i, valeur in enumerate((numero, l["percepteur"], l["nb_recus"], l["montant_txt"])):
                    self._cellule(COL_FRAIS, i, valeur, "F2" if i == 3 else "F1")
                self.filet_ligne()
            self.assurer_place(HAUTEUR_LIGNE * (len(g["totaux"]) + 1))
            self.y -= 3
            for k, (devise, cents) in enumerate(g["totaux"]):
                self.total_droite(f"Total {g['type_frais']}  ({g['nb_recus']} reçu(s)) :" if k == 0 else "",
                                  f"{formater(cents)} {devise}")
            self.y -= 12

        if r["groupes"]:
            self.assurer_place(30 + 17 * len(r["totaux"]), bas=46)
            self.p.ligne(MARGE, self.y + 6, DROITE, self.y + 6, 1.2)
            self.y -= 8
            for k, (devise, cents) in enumerate(r["totaux"]):
                self.total_droite(f"TOTAL DES PAIEMENTS  ({r['nb_recus']} reçu(s)) :" if k == 0 else "",
                                  f"{formater(cents)} {devise}", fort=True)
            self.y -= 10
        else:
            self.p.texte(MARGE, self.y, "1.  PAIEMENTS DE LA JOURNÉE", "F2", 10.5)
            self.y -= 16
            self.p.texte(MARGE, self.y, "Aucun paiement enregistré à cette date.", "F3", 9, GRIS)
            self.y -= 24

        # ---- 2) encaissements, versements, écarts
        self.assurer_place(22 + 2 * HAUTEUR_LIGNE + 40)
        self.p.texte(MARGE, self.y, "2.  ENCAISSEMENTS ET VERSEMENTS DES PERCEPTEURS", "F2", 10.5)
        self.y -= 20
        if not r["versements"]:
            self.p.texte(MARGE, self.y, "Aucun encaissement enregistré à cette date.", "F3", 9, GRIS)
            self.y -= 18
        else:
            titre = "ENCAISSEMENTS DU " + r["date_txt"]
            self.bandeau(titre, COL_VERS)
            for i_v, v in enumerate(r["versements"]):
                derniere = i_v == len(r["versements"]) - 1          # la dernière ligne reste avec les totaux
                if self.assurer_place(HAUTEUR_LIGNE * (len(r["totaux_versements"]) + 3 if derniere else 2), bas=46):
                    self.bandeau(titre + "   (suite)", COL_VERS)
                couleur_ecart = ROUGE if v["ecart"] > 0 else (VERT if v["ecart"] < 0 else NUIT)
                valeurs = (v["n_enc"], v["percepteur"], v["devise"], v["encaisse_txt"], v["verse_txt"], v["ecart_txt"])
                for i, valeur in enumerate(valeurs):
                    self._cellule(COL_VERS, i, valeur, "F2" if i == 5 else "F1", rgb=couleur_ecart if i == 5 else NUIT)
                self.filet_ligne()
            self.assurer_place(HAUTEUR_LIGNE * (len(r["totaux_versements"]) + 2), bas=46)
            self.y -= 3
            for k, (devise, enc, ver, ecart) in enumerate(r["totaux_versements"]):
                self.total_droite(f"Total {devise}  -  encaissé {formater(enc)}   versé {formater(ver)}   écart :",
                                  f"{formater(ecart)} {devise}")
            self.y -= 4
            self.p.texte(MARGE, self.y, "Écart = montant encaissé - montant versé  (positif : manquant ; négatif : excédent).",
                         "F3", 8, GRIS)
            self.y -= 14

        if r["sans_versement"]:
            self.assurer_place(30)
            self.p.texte(MARGE, self.y, "Attention : aucun encaissement enregistré pour ce jour pour : "
                         + ", ".join(r["sans_versement"]) + ".", "F3", 8, ROUGE)
            self.y -= 14
        if r["nb_annules"]:
            self.assurer_place(20)
            self.p.texte(MARGE, self.y, f"Note : {r['nb_annules']} reçu(s) annulé(s) ce jour, non comptés dans ce rapport.",
                         "F3", 8, GRIS)
            self.y -= 14

        # ---- signature
        self.assurer_place(70, bas=46)
        self.y -= 18
        self.p.texte_droite(DROITE, self.y, f"Le {r['date_txt']}", "F2", 9.5)
        self.p.texte_droite(DROITE, self.y - 14, "Signature", "F1", 9)
        self.p.ligne(DROITE - 160, self.y - 46, DROITE, self.y - 46, 0.6, GRIS)

        total = len(self.pages)
        for i, page in enumerate(self.pages, start=1):
            page.texte_centre(LARGEUR / 2, 32, f"Page {i} / {total}   •   Rapport global des encaissements du {r['date_txt']}",
                              "F1", 7.5, GRIS)
        return [page.octets() for page in self.pages]


def generer_rapport_global_pdf(rapport: dict, chemin, chemin_logo):
    with open(chemin_logo, "rb") as f:
        jpeg = f.read()
    largeur_img, hauteur_img, _ = _dimensions_jpeg(jpeg)
    contenus = _MiseEnPage(rapport, (largeur_img, hauteur_img)).construire()
    with open(chemin, "wb") as f:
        f.write(_assembler(contenus, jpeg, "Rapport global des encaissements"))
    return str(chemin)

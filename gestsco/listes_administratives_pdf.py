"""Listes administratives du Secrétariat au format PDF (A4 portrait) : liste des élèves et liste des dossiers incomplets, par classe.
Même principe que controle_pdf.py : aucune bibliothèque externe. Chaque classe commence sur une nouvelle page."""
import config
from rapport_pdf import BAS, BLANC, DROITE, FILET, FOND_CLAIR, HAUTEUR, HAUTEUR_LIGNE, LARGEUR, MARGE, _assembler
from recu_pdf import GRIS, NUIT, _Contenu, _dimensions_jpeg, ajuster

LARGEUR_UTILE = DROITE - MARGE        # 515,28
# (titre, largeur, alignement, clé de l'élève)
COLONNES = {
    "eleves": [("N°", 28, "c", "n"), ("Matricule", 74, "g", "matricule"), ("Nom, postnom et prénom", 241.28, "g", "nom_complet"),
               ("Sexe", 36, "c", "sexe"), ("Naissance", 66, "c", "naissance"), ("Dossier", 70, "c", "dossier")],
    # Directions et Préfecture : pas d'état du dossier (propre au Secrétariat), le téléphone du tuteur à la place
    "eleves_direction": [("N°", 28, "c", "n"), ("Matricule", 74, "g", "matricule"), ("Nom, postnom et prénom", 211.28, "g", "nom_complet"),
                         ("Sexe", 36, "c", "sexe"), ("Naissance", 66, "c", "naissance"), ("Tél. du tuteur", 100, "g", "tel_tuteur")],
    "incomplets": [("N°", 28, "c", "n"), ("Matricule", 70, "g", "matricule"), ("Nom, postnom et prénom", 180, "g", "nom_complet"),
                   ("Sexe", 32, "c", "sexe"), ("Tuteur", 125, "g", "tuteur"), ("Téléphone", 80.28, "g", "tel_tuteur")],
}
TITRE_PIED = "Le Secrétariat"      # valeur par défaut : config de l'espace dans listes_administratives.ESPACES


def _x(cols, indice):
    return MARGE + sum(c[1] for c in cols[:indice])


class _MiseEnPage:
    def __init__(self, r, dims_jpeg, edite_le):
        self.espace = r.get("espace", "dossier_eleve")
        self.r, self.edite_le = r, edite_le
        self.cols = COLONNES["eleves_direction" if r["genre"] == "eleves" and self.espace != "dossier_eleve" else r["genre"]]
        self.l_img, self.h_img = dims_jpeg
        self.pages, self.p, self.y = [], None, 0
        self.classe = None
        self.premiere_de_classe = True

    # ---- cellules
    def _cellule(self, indice, texte, police="F1", taille=9.5):
        _t, largeur, alignement, _k = self.cols[indice]
        texte, taille = ajuster(str(texte), police, taille, largeur - 10, taille_min=7)
        if alignement == "c":
            self.p.texte_centre(_x(self.cols, indice) + largeur / 2, self.y, texte, police, taille)
        else:
            self.p.texte(_x(self.cols, indice) + 6, self.y, texte, police, taille)

    def _entete_tableau(self):
        p = self.p
        p.fond(MARGE, self.y - 5, LARGEUR_UTILE, HAUTEUR_LIGNE + 3, NUIT)
        for i, (titre, largeur, alignement, _k) in enumerate(self.cols):
            if alignement == "c":
                p.texte_centre(_x(self.cols, i) + largeur / 2, self.y, titre, "F2", 8.5, BLANC)
            else:
                p.texte(_x(self.cols, i) + 6, self.y, titre, "F2", 8.5, BLANC)
        self.y -= HAUTEUR_LIGNE + 6

    # ---- pages
    def _ligne_classe(self):
        k = self.classe
        texte = f"CLASSE : {k['classe']}" + (f"   -   OPTION : {k['option']}" if k["option"] else "")
        return texte

    def nouvelle_page(self, debut_de_classe, avec_tableau=True):
        self.p = _Contenu()
        self.pages.append(self.p)
        p, r = self.p, self.r
        p.rectangle(MARGE - 14, 24, LARGEUR - 2 * (MARGE - 14), HAUTEUR - 48, 0.8, FILET)
        if debut_de_classe:
            haut = HAUTEUR - 40
            h_logo = 66
            p.image(MARGE, haut - h_logo, h_logo * self.l_img / self.h_img, h_logo)
            p.texte_centre(LARGEUR / 2, haut - 28, config.NOM_ECOLE, "F2", 20)
            p.texte_centre(LARGEUR / 2, haut - 47, str(config.DEVISE_ECOLE).upper(), "F2", 10, espacement=0.9)
            p.ligne(MARGE, haut - h_logo - 10, DROITE, haut - h_logo - 10, 1.2)
            y = haut - h_logo - 38
            titre, taille = ajuster(r["titre"].upper(), "F2", 14, LARGEUR_UTILE, taille_min=9)
            p.texte_centre(LARGEUR / 2, y, titre, "F2", taille)
            y -= 20
            ligne, taille = ajuster(self._ligne_classe(), "F2", 11.5, LARGEUR_UTILE, taille_min=8)
            p.texte_centre(LARGEUR / 2, y, ligne, "F2", taille)
            y -= 16
            p.texte_centre(LARGEUR / 2, y, f"Année scolaire {r['annee']}", "F1", 9.5, GRIS)
            self.y = y - 26
        else:
            p.texte(MARGE, HAUTEUR - 46, config.NOM_ECOLE, "F2", 11)
            p.texte_droite(DROITE, HAUTEUR - 46, r["titre"].upper(), "F2", 9)
            p.texte(MARGE, HAUTEUR - 60, f"{self._ligne_classe()}   •   Année {r['annee']}", "F1", 8.5, GRIS)
            p.ligne(MARGE, HAUTEUR - 68, DROITE, HAUTEUR - 68, 0.8)
            self.y = HAUTEUR - 90
        if avec_tableau:
            self._entete_tableau()

    def _pied_de_classe(self):
        k, p = self.classe, None
        if self.y - 60 < 46:
            self.nouvelle_page(False, avec_tableau=False)      # le pied seul : pas d'en-tête de tableau sans ligne
        p = self.p
        self.y -= 8
        if self.r["genre"] == "eleves":
            texte = f"Effectif : {k['total']} élève(s)   -   {k['garcons']} garçon(s), {k['filles']} fille(s)"
            if k["incomplets"] and self.espace == "dossier_eleve":
                texte += f"   -   dossiers incomplets : {k['incomplets']}"
        else:
            texte = f"Total : {k['total']} dossier(s) incomplet(s)"
        p.texte(MARGE, self.y, texte, "F2", 9.5)
        self.y -= 40
        from recu_pdf import largeur_texte
        import listes_administratives
        titre_pied = listes_administratives.ESPACES.get(self.espace, TITRE_PIED)
        largeur = largeur_texte(titre_pied, "F2", 11)
        p.texte_droite(DROITE - 6, self.y, titre_pied, "F2", 11)
        p.ligne(DROITE - 6 - largeur, self.y - 2.5, DROITE - 6, self.y - 2.5, 0.9)

    def construire(self):
        for k in self.r["classes"]:
            self.classe = k
            self.nouvelle_page(True)
            for i, e in enumerate(k["eleves"]):
                if self.y - HAUTEUR_LIGNE < BAS:
                    self.nouvelle_page(False)
                if i % 2:
                    self.p.fond(MARGE, self.y - 4.5, LARGEUR_UTILE, HAUTEUR_LIGNE, FOND_CLAIR)
                valeurs = dict(e, dossier="Complet" if e["complet"] else "Incomplet")
                if e["desactive"]:
                    valeurs["nom_complet"] += " (désactivé)"
                for j, col in enumerate(self.cols):
                    self._cellule(j, valeurs[col[3]])
                self.p.ligne(MARGE, self.y - 4.5, DROITE, self.y - 4.5, 0.4, FILET)
                self.y -= HAUTEUR_LIGNE
            self._pied_de_classe()
        total = len(self.pages)
        for i, page in enumerate(self.pages, start=1):
            page.texte_centre(LARGEUR / 2, 32, f"Page {i} / {total}   •   Édité le {self.edite_le}", "F1", 7.5, GRIS)
        return [page.octets() for page in self.pages]


def generer(r: dict, jpeg: bytes, edite_le: str) -> bytes:
    """r : résultat de listes_administratives.liste ; jpeg : logo de l'école ; edite_le : date d'édition (jj/mm/aaaa)."""
    dims = _dimensions_jpeg(jpeg)[:2]
    contenus = _MiseEnPage(r, dims, edite_le).construire()
    return _assembler(contenus, jpeg, r["titre"])

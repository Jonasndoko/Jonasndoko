"""Tests du bulletin du secondaire et des humanités (bulletin_secondaire_pdf.py) : titre par classe, maxima, un bulletin par élève.
Lancer :  python -m unittest test_bulletin_secondaire"""
import os
import tempfile
import unittest

os.environ.setdefault("CSF_DATA_DIR", tempfile.mkdtemp())

import bulletin_secondaire_pdf as bs   # noqa: E402
import bulletins_pdf                   # noqa: E402


def _classe(annee_etude, option=""):
    return {"n_classe": 1, "designation": annee_etude + " A", "niveau": "Humanités" if option else "Secondaire", "option": option,
            "primaire": False, "annee_etude": annee_etude}


def _calc(classe, cours, nb_eleves=2):
    portees = [{"cle": "P1", "type": "periode", "periodes": [1]}, {"cle": "P2", "type": "periode", "periodes": [2]},
               {"cle": "S1", "type": "semestre", "periodes": [1, 2]}, {"cle": "X1", "type": "examen", "periodes": [2]},
               {"cle": "P3", "type": "periode", "periodes": [3]}, {"cle": "P4", "type": "periode", "periodes": [4]},
               {"cle": "S2", "type": "semestre", "periodes": [3, 4]}, {"cle": "X2", "type": "examen", "periodes": [4]},
               {"cle": "A", "type": "annee", "periodes": [1, 2, 3, 4]}]
    eleves = [{"matricule": str(i), "nom_complet": f"ELEVE {i}", "sexe": "F", "naissance": "01/02/2012", "lieu_naissance": "Kinshasa",
               "cours": {}, "portees": {}} for i in range(nb_eleves)]
    return {"annee": "2025-2026", "classe": classe, "portees": portees, "eleves": eleves, "stats": {}, "alertes": [],
            "cours": [{"id_cc": i + 1, "libelle": n, "heures": h, "professeur": ""} for i, (n, h) in enumerate(cours)]}


class TestBulletinSecondaire(unittest.TestCase):
    def test_titre_des_classes(self):
        self.assertEqual(bs._titre_classe(_classe("7ème")), ("7", "ème", "ANNEE DE BASE"))
        self.assertEqual(bs._titre_classe(_classe("8ème")), ("8", "ème", "ANNEE DE BASE"))
        self.assertEqual(bs._titre_classe(_classe("1ère", "Electricité générale")), ("1", "ère", "ANNEE HUMANITE ELECTRICITE GENERALE"))
        self.assertEqual(bs._titre_classe(_classe("2ème", "Electricité générale")), ("2", "ème", "ANNEE HUMANITE ELECTRICITE GENERALE"))
        self.assertEqual(bs._titre_classe(_classe("3ème", "Pédagogie générale")), ("3", "ème", "ANNEE HUMANITE PEDAGOGIE GENERALE"))

    def test_maxima_des_groupes(self):
        self.assertEqual(bs.maxima_colonnes(10, False), {"P": 10, "EX": 20, "TOT": 40, "TG": 80})
        self.assertEqual(bs.maxima_colonnes(100, True), {"P": 100, "TOT": 200, "TG": 400})

    def test_groupes_de_maxima_croissants(self):
        calc = _calc(_classe("2ème", "Electricité générale"), [("Mathématiques", 5), ("Religion", 1), ("Anglais", 2), ("Atelier", 10)])
        lignes = bs.lignes_du_tableau(calc)
        self.assertEqual([x[1] for x in lignes if x[0] == "max"], [10, 20, 50, 100])

    def test_un_bulletin_par_eleve_pour_chaque_classe(self):
        cours = [("Religion", 1), ("Français", 5), ("Mathématiques", 5), ("Anglais", 2)]
        for annee, option in (("7ème", ""), ("8ème", ""), ("1ère", "Electricité générale"), ("2ème", "Commerciale"), ("3ème", "Pédagogie")):
            calc = _calc(_classe(annee, option), cours, 3)
            pdf = bs.bulletins(calc, calc["eleves"])
            self.assertTrue(pdf.startswith(b"%PDF"))
            self.assertIn(b"/Count 3", pdf)

    def test_branchement_sur_l_impression_des_bulletins(self):
        calc = _calc(_classe("7ème"), [("Religion", 1)], 1)
        pdf = bulletins_pdf.bulletins(calc, calc["eleves"], [])
        self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()

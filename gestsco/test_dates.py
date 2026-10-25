"""Tests du champ date (saisie + calendrier) : la logique, sans interface.
Lancer :  python test_dates.py"""
import unittest
from datetime import date

import saisie_date as sd


class TestSaisieDate(unittest.TestCase):
    def test_lecture_de_la_date_tapee(self):
        for texte in ("08/10/2026", "8/10/2026", "08-10-2026", "08.10.2026", "2026-10-08", " 08/10/2026 "):
            self.assertEqual(sd.lire_date_texte(texte), date(2026, 10, 8), texte)

    def test_dates_invalides(self):
        for texte in ("", None, "31/02/2026", "abc", "08/13/2026", "08/10/1800", "08/10/2200", "8/10"):
            self.assertIsNone(sd.lire_date_texte(texte), texte)

    def test_format_affiche(self):
        self.assertEqual(sd.formater_date(date(2026, 1, 5)), "05/01/2026")

    def test_barres_ajoutees_pendant_la_frappe(self):
        self.assertEqual(sd.completer_frappe("0"), "0")
        self.assertEqual(sd.completer_frappe("08"), "08/")
        self.assertEqual(sd.completer_frappe("08/1"), "08/1")
        self.assertEqual(sd.completer_frappe("08/10"), "08/10/")
        self.assertEqual(sd.completer_frappe("08/10/2"), "08/10/2")
        self.assertEqual(sd.completer_frappe("8/"), "8/")                # séparé à la main : inchangé
        self.assertEqual(sd.completer_frappe("8/10"), "8/10")
        self.assertEqual(sd.completer_frappe("08/10/2026"), "08/10/2026")

    def test_frappe_permise(self):
        self.assertTrue(sd.frappe_permise(""))
        self.assertTrue(sd.frappe_permise("08/10/2026"))
        self.assertTrue(sd.frappe_permise("08-10-2026"))
        self.assertFalse(sd.frappe_permise("08/10/20266"))               # trop long
        self.assertFalse(sd.frappe_permise("08/ab"))                     # lettres refusées

    def test_grille_du_mois(self):
        s = sd.semaines(2026, 10)                                        # 1er octobre 2026 = jeudi
        self.assertEqual(s[0], [0, 0, 0, 1, 2, 3, 4])
        self.assertEqual(max(max(w) for w in s), 31)
        self.assertTrue(all(len(w) == 7 for w in s))
        self.assertEqual(sd.semaines(2024, 2)[-1][3], 29)                # 29 février 2024 (année bissextile), jeudi

    def test_changement_de_mois(self):
        self.assertEqual(sd.decaler_mois(2026, 12, 1), (2027, 1))
        self.assertEqual(sd.decaler_mois(2026, 1, -1), (2025, 12))
        self.assertEqual(sd.decaler_mois(2026, 10, 0), (2026, 10))
        self.assertEqual(sd.decaler_mois(2026, 3, -14), (2025, 1))

    def test_noms_en_francais(self):
        self.assertEqual(len(sd.MOIS), 12)
        self.assertEqual(sd.JOURS[0], "Lu")
        self.assertEqual(len(sd.JOURS), 7)


if __name__ == "__main__":
    unittest.main(verbosity=1)

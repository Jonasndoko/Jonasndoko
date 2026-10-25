"""Tests des maxima fixés par le titulaire (secondaire et humanités) et de l'impression du bulletin par le titulaire.
Lancer :  python -m unittest test_maxima_titulaire"""
import unittest

import bulletins
from aide_tests_proclamation import ouvrir_impression   # noqa: E402
import notes
import test_bulletins as tb
from bulletins import ErreurBulletins


class TestMaximaTitulaire(tb.Base):
    def maxima(self):
        return {c["id_cc"]: c for c in bulletins.maxima_cours(self.conn, self.s1, self.annee, self.c7)["cours"]}

    def test_sans_choix_du_titulaire_le_maximum_est_le_maximum_standard(self):
        m = self.maxima()
        self.assertEqual((m[self.maths]["maximum"], m[self.maths]["fixe"]), (20, False))
        self.assertEqual(len(m), 2)

    def test_seul_le_titulaire_fixe_les_maxima(self):
        with self.assertRaises(PermissionError):
            bulletins.maxima_cours(self.conn, self.s2, self.annee, self.c7)
        with self.assertRaises(PermissionError):
            bulletins.definir_maximum_cours(self.conn, self.s2, self.annee, self.c7, self.maths, 10)

    def test_le_maximum_du_titulaire_gouverne_la_saisie_des_points(self):
        bulletins.definir_maximum_cours(self.conn, self.s1, self.annee, self.c7, self.maths, 10)
        fiche = notes.fiche(self.conn, self.s1, self.maths, self.pers[0])
        self.assertEqual(fiche["evaluations"][0]["maximum"], 10)
        notes.enregistrer_points(self.conn, self.s1, self.maths, self.pers[0], {self.mat[0]: "8"})
        with self.assertRaises(ErreurBulletins):
            notes.enregistrer_points(self.conn, self.s1, self.maths, self.pers[0], {self.mat[1]: "11"})
        fiche = notes.fiche(self.conn, self.s1, self.maths, f"X{self.sems[0]}")
        self.assertEqual(fiche["evaluations"][0]["maximum"], 20)                              # examen = 2 x période

    def test_changer_le_maximum_met_a_jour_les_evaluations_existantes(self):
        notes.enregistrer_points(self.conn, self.s1, self.maths, self.pers[0], {self.mat[0]: "8"})
        bulletins.definir_maximum_cours(self.conn, self.s1, self.annee, self.c7, self.maths, 10)
        calc = bulletins.calculer(self.conn, self.annee, self.c7)
        self.assertEqual(calc["eleves"][0]["cours"][self.maths][f"P{self.pers[0]}"]["max"], 10)

    def test_refus_si_un_point_depasse_le_nouveau_maximum(self):
        notes.enregistrer_points(self.conn, self.s1, self.maths, self.pers[0], {self.mat[0]: "15"})
        with self.assertRaises(ErreurBulletins):
            bulletins.definir_maximum_cours(self.conn, self.s1, self.annee, self.c7, self.maths, 10)
        self.assertEqual(self.maxima()[self.maths]["maximum"], 20)

    def test_maximum_invalide_et_cours_d_une_autre_classe(self):
        for v in ("abc", "0", "-5", "9999"):
            with self.assertRaises(ErreurBulletins):
                bulletins.definir_maximum_cours(self.conn, self.s1, self.annee, self.c7, self.maths, v)
        autre = self.conn.execute("SELECT ID_CC FROM COURS_CLASSE WHERE N_CLASSE = ? LIMIT 1", (self.c8,)).fetchone()[0]
        with self.assertRaises(PermissionError):
            bulletins.definir_maximum_cours(self.conn, self.s1, self.annee, self.c7, autre, 10)

    def test_cours_de_100_points_sans_examen(self):
        r = bulletins.definir_maximum_cours(self.conn, self.s1, self.annee, self.c7, self.maths, 100)
        self.assertTrue(r["sans_examen"])
        with self.assertRaises(ErreurBulletins):
            notes.fiche(self.conn, self.s1, self.maths, f"X{self.sems[0]}")

    def test_le_titulaire_imprime_les_bulletins_de_sa_classe_et_d_un_eleve(self):
        bulletins.definir_maximum_cours(self.conn, self.s1, self.annee, self.c7, self.maths, 10)
        notes.enregistrer_points(self.conn, self.s1, self.maths, self.pers[0], {self.mat[0]: "8"})
        ouvrir_impression(self.conn, self.annee, self.c7)
        octets, nom = bulletins.document_pdf(self.conn, self.s1, "bulletins", self.annee, self.c7, "A")
        self.assertTrue(octets.startswith(b"%PDF"))
        self.assertIn(b"/Count 4", octets)                                                    # 4 élèves, 1 page chacun
        octets1, _ = bulletins.document_pdf(self.conn, self.s1, "bulletin", self.annee, self.c7, "A", self.mat[0])
        self.assertIn(b"/Count 1", octets1)
        with self.assertRaises(PermissionError):
            bulletins.document_pdf(self.conn, self.s2, "bulletins", self.annee, self.c7, "A")


if __name__ == "__main__":
    unittest.main()

"""Tests de la gestion des bulletins (Direction des études, fonctionnalité 4) : vue d'ensemble, résultats d'une classe, bulletin d'un élève,
erreurs et données manquantes, droits, PDF, export CSV, page web.
Lancer :  python -m unittest test_gestion_bulletins"""
import unittest

import app_web                # noqa: E402
import controle_notes         # noqa: E402
import gestion_bulletins      # noqa: E402
import notes                  # noqa: E402
from controle_notes import ErreurControle   # noqa: E402
from test_controle_notes import Fixture, MDP   # noqa: E402


class Base2(Fixture):
    def setUp(self):
        super().setUp()
        self.cle_s1 = f"S{self.sem1}"

    def anomalies(self, **kw):
        return gestion_bulletins.anomalies(self.conn, self.dire, self.annee, kw.pop("classe", None), kw.pop("cle", self.cle1), **kw)

    def codes(self, **kw):
        return {(a["code"], a["cours"]) for a in self.anomalies(**kw)["anomalies"]}


class TestApercu(Base2):
    def test_une_ligne_par_classe_et_statut(self):
        o = gestion_bulletins.apercu(self.conn, self.dire, self.annee, self.cle1)
        self.assertEqual(o["cle"], self.cle1)
        par = {k["designation"]: k for k in o["classes"]}
        self.assertEqual(par["7ème A"]["effectif"], 3)
        self.assertEqual(par["8ème A"]["statut"], "BLOQUE")            # maths de la 8ème : aucun point saisi pour une période échue
        self.assertEqual(par["7ème A"]["statut"], "A_VERIFIER")        # français incomplet
        self.assertEqual(o["total"]["classes"], 2)
        self.assertEqual(o["total"]["bloquees"], 1)

    def test_classe_prete_quand_tout_est_saisi(self):
        notes.enregistrer_points(self.conn, self.s2, self.fr7, self.per1, {"0000/26": "10", "0001/26": "9", "0002/26": "14"})
        gestion_bulletins.bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c7, self.m1)
        # la conduite est aussi attendue : on la cote pour les trois élèves
        for m in ("0000/26", "0001/26", "0002/26"):
            notes.enregistrer_conduite(self.conn, self.s1, self.maths7, self.per1, m, "B")
        o = gestion_bulletins.resultats_classe(self.conn, self.dire, self.annee, self.c7, self.cle1)
        self.assertEqual((o["erreurs"], o["alertes"], o["statut"]), (0, 0, "PRET"))

    def test_droit_de_lecture_exige(self):
        for s in (self.prefet, self.perc):
            with self.assertRaises(PermissionError):
                gestion_bulletins.apercu(self.conn, s, self.annee)


class TestResultatsEtBulletin(Base2):
    def test_resultats_de_la_classe(self):
        r = gestion_bulletins.resultats_classe(self.conn, self.dire, self.annee, self.c7, self.cle1)
        self.assertEqual(len(r["eleves"]), 3)
        premier = r["eleves"][0]
        self.assertEqual((premier["nom"].split()[0], premier["obtenu"], premier["max"], premier["rang"]), ("Kasongo", 25, 40, 1))   # 15 + 10
        self.assertEqual(next(c for c in r["cours"] if c["cours"] == "Mathématiques")["notes"], 3)
        self.assertTrue(r["anomalies"])

    def test_bulletin_d_un_eleve_pour_un_semestre(self):
        b = gestion_bulletins.bulletin_eleve(self.conn, self.dire, self.annee, self.c7, "0000/26", self.cle_s1)
        self.assertEqual([c["cle"] for c in b["colonnes"]][-1], self.cle_s1)
        self.assertEqual(b["totaux"][self.cle1]["obtenu"], 25)
        self.assertEqual(b["eleve"]["matricule"], "0000/26")
        self.assertIn("CONDUITE_MANQUANTE", {p["code"] for p in b["problemes"]})         # la conduite de l'élève n'est pas cotée
        with self.assertRaises(ErreurControle):
            gestion_bulletins.bulletin_eleve(self.conn, self.dire, self.annee, self.c7, "0009/26", self.cle1)     # élève d'une autre classe

    def test_pdf_et_journal(self):
        octets, nom = gestion_bulletins.document_pdf(self.conn, self.dire, self.annee, self.c7, self.cle1, "0000/26")
        self.assertTrue(octets.startswith(b"%PDF"))
        self.assertTrue(nom.endswith(".pdf"))
        octets, _ = gestion_bulletins.document_pdf(self.conn, self.dire, self.annee, self.c7, self.cle1)
        self.assertTrue(octets.startswith(b"%PDF"))
        self.assertTrue(self.conn.execute("SELECT 1 FROM JOURNAL WHERE ACTION = 'BULLETINS_CONSULTATION_PDF'").fetchone())
        with self.assertRaises(PermissionError):
            gestion_bulletins.document_pdf(self.conn, self.perc, self.annee, self.c7, self.cle1)


class TestAnomalies(Base2):
    def test_points_manquants_et_absents(self):
        c = self.codes(classe=self.c7)
        self.assertIn(("POINTS_MANQUANTS", "Français"), c)
        self.assertNotIn(("POINTS_MANQUANTS", "Mathématiques"), c)
        self.assertIn(("AUCUN_POINT", "Mathématiques"), self.codes(classe=self.c8))
        a = next(x for x in self.anomalies(classe=self.c7)["anomalies"] if x["code"] == "POINTS_MANQUANTS")
        self.assertEqual((a["gravite"], len(a["matricules"])), ("ALERTE", 2))

    def test_periode_a_venir_ne_manque_rien(self):
        r = gestion_bulletins.anomalies(self.conn, self.dire, self.annee, self.c7, f"P{self.per3}")
        self.assertFalse([a for a in r["anomalies"] if a["code"] in ("POINTS_MANQUANTS", "AUCUN_POINT")])

    def test_cours_sans_professeur(self):
        with self.conn:
            self.conn.execute("UPDATE COURS_CLASSE SET MATRICULE_PROF = NULL WHERE ID_CC = ?", (self.maths8,))
        self.assertIn(("SANS_PROFESSEUR", "Mathématiques"), self.codes(classe=self.c8))

    def test_conduite_non_cotee(self):
        self.assertIn(("CONDUITE_MANQUANTE", ""), self.codes(classe=self.c7))
        for m in ("0000/26", "0001/26", "0002/26"):
            notes.enregistrer_conduite(self.conn, self.s1, self.maths7, self.per1, m, "TB")
        self.assertNotIn(("CONDUITE_MANQUANTE", ""), self.codes(classe=self.c7))

    def test_point_hors_bareme(self):
        with self.conn:
            self.conn.execute("UPDATE NOTE SET POINTS = 55 WHERE MATRICULE = '0000/26' AND ID_EVAL = (SELECT ID_EVAL FROM EVALUATION WHERE ID_CC = ? "
                              "AND ID_PER = ? AND TYPE = 'PER')", (self.maths7, self.per1))
        r = self.anomalies(classe=self.c7)
        a = next(x for x in r["anomalies"] if x["code"] == "POINT_HORS_BAREME")
        self.assertEqual((a["gravite"], a["cours"]), ("ERREUR", "Mathématiques"))
        self.assertEqual(r["anomalies"][0]["gravite"], "ERREUR")                    # les erreurs d'abord

    def test_note_d_un_eleve_non_inscrit(self):
        with self.conn:
            self.conn.execute("DELETE FROM INSCRIRE WHERE MATRICULE = '0002/26'")
            self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('0002/26', 'Zola') ON CONFLICT DO NOTHING")
        notes.enregistrer_points(self.conn, self.s1, self.maths8, self.per1, {"0009/26": "5"})
        with self.conn:
            ev = self.conn.execute("SELECT ID_EVAL FROM EVALUATION WHERE ID_CC = ? AND TYPE = 'PER'", (self.maths7,)).fetchone()[0]
            self.conn.execute("INSERT OR REPLACE INTO NOTE (ID_EVAL, MATRICULE, POINTS, DATE_MODIF) VALUES (?,?,?,?)",
                              (ev, "0002/26", 7, "2026-10-01T00:00:00"))
        self.assertIn(("NOTE_NON_INSCRIT", "Mathématiques"), self.codes(classe=self.c7))

    def test_filtres_et_export(self):
        e = self.anomalies(gravite="ERREUR")
        self.assertTrue(all(a["gravite"] == "ERREUR" for a in e["anomalies"]))
        t = self.anomalies(code="POINTS_MANQUANTS")
        self.assertTrue(all(a["code"] == "POINTS_MANQUANTS" for a in t["anomalies"]))
        csv_ = gestion_bulletins.exporter_anomalies_csv(self.conn, self.dire, self.annee, None, self.cle1)
        self.assertIn("Points manquants", csv_)
        self.assertTrue(self.conn.execute("SELECT 1 FROM JOURNAL WHERE ACTION = 'BULLETINS_ANOMALIES_EXPORT'").fetchone())

    def test_calcul_incoherent_detecte(self):
        """Un total faux (ici simulé par un calcul altéré) est signalé comme erreur."""
        vrai = gestion_bulletins.bulletins.calculer

        def faux(conn, annee, n_classe):
            calc = vrai(conn, annee, n_classe)
            calc["eleves"][0]["portees"][self.cle1]["pct"] = 99.0
            return calc
        from unittest import mock
        with mock.patch("gestion_bulletins.bulletins.calculer", faux):
            r = self.anomalies(classe=self.c7)
        self.assertIn("CALCUL_INCOHERENT", {a["code"] for a in r["anomalies"]})


class TestPageWeb(Base2):
    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])
        self.cl = self.app.test_client()
        self.assertEqual(self.cl.post("/connexion", data={"login": "dire1", "mdp": MDP}).status_code, 302)
        self.base = "/m/etudes_discipline/direction_etudes"

    def test_onglet_et_vues(self):
        self.assertIn("Gestion des bulletins", self.cl.get(self.base).get_data(as_text=True))
        h = self.cl.get(f"{self.base}?f=bulletins").get_data(as_text=True)
        self.assertIn("7ème A", h)
        self.assertIn("Bloqué", h)
        for url in (f"?f=bulletins&vue=classe", f"?f=bulletins&vue=classe&classe={self.c7}&cle={self.cle1}",
                    f"?f=bulletins&vue=classe&classe={self.c7}&cle={self.cle_s1}&eleve=0000/26",
                    "?f=bulletins&vue=anomalies", f"?f=bulletins&vue=anomalies&gravite=ERREUR&classe={self.c8}"):
            self.assertEqual(self.cl.get(self.base + url).status_code, 200, url)
        h = self.cl.get(f"{self.base}?f=bulletins&vue=classe&classe={self.c7}&cle={self.cle1}").get_data(as_text=True)
        self.assertIn("Kasongo", h)
        self.assertIn("Moyenne par cours", h)
        h = self.cl.get(f"{self.base}?f=bulletins&vue=anomalies").get_data(as_text=True)
        self.assertIn("Points manquants", h)

    def test_pdf_et_csv(self):
        r = self.cl.get(f"{self.base}/bulletins/bulletin.pdf?annee={self.annee}&classe={self.c7}&cle={self.cle1}&eleve=0000/26")
        self.assertEqual((r.status_code, r.mimetype), (200, "application/pdf"))
        r = self.cl.get(f"{self.base}/bulletins/anomalies.csv?annee={self.annee}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["Content-Type"])
        self.assertEqual(self.cl.get(f"{self.base}/bulletins/bulletin.pdf?annee={self.annee}&classe=99999&cle={self.cle1}").status_code, 404)

    def test_autres_postes_refuses(self):
        for login in ("prefet1", "perc1"):
            cl = self.app.test_client()
            cl.post("/connexion", data={"login": login, "mdp": MDP})
            for url in ("?f=bulletins", "/bulletins/anomalies.csv", f"/bulletins/bulletin.pdf?annee={self.annee}&classe={self.c7}&cle={self.cle1}"):
                self.assertEqual(cl.get(self.base + url).status_code, 403, (login, url))


if __name__ == "__main__":
    unittest.main()

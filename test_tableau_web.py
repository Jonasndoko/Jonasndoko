"""Tests du Tableau de bord en ligne (web_tableau.py) : accès, libellés « élèves », année, graphiques, journal.
Lancer :  python -m unittest test_tableau_web"""
import os
import re
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web             # noqa: E402
import database            # noqa: E402
import demo                # noqa: E402
import droits              # noqa: E402
import security            # noqa: E402

MDP = "Tr@vail-Amour-2026"


class TestTableauWeb(unittest.TestCase):
    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "t.db")
        self.conn = database.connecter(self.chemin)
        demo.semer(self.conn)
        security.creer_utilisateur(self.conn, "admin1", "Alice Directrice", "ADMINISTRATEUR", MDP)
        self.id_int = security.creer_utilisateur(self.conn, "int1", "Ivan Intendant", "INTENDANT", MDP)
        self.app = app_web.creer_app(self.chemin)

    def client(self, login):
        c = self.app.test_client()
        r = c.post("/connexion", data={"login": login, "mdp": MDP}, follow_redirects=False)
        self.assertIn(r.status_code, (302, 303))
        return c

    def test_admin_arrive_sur_le_tableau_de_bord(self):
        c = self.client("admin1")
        r = c.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/tableau-de-bord"))

    def test_libelles_eleves_et_pas_inscrits(self):
        h = self.client("admin1").get("/tableau-de-bord").get_data(as_text=True)
        for mot in ("Élèves en règle", "Élèves pas en règle", "Personnel actif", "Situation des élèves", "Situation financière générale",
                    "Frais du logiciel des parents"):
            self.assertIn(mot, h)
        for interdit in ("inscrits", "évolution des inscriptions"):
            self.assertNotIn(interdit, h.lower())
        self.assertNotRegex(h, r'>(\d+\.\d)<')                          # graduations entières
        self.assertEqual(h.count("<svg"), 2)
        for retire in ("Filles", "Garçons", "filles et garçons", "Personnel enseignant", "Organisation scolaire"):
            self.assertNotIn(retire, h)

    def test_menu_principal_a_gauche_comme_sous_windows(self):
        h = self.client("admin1").get("/tableau-de-bord").get_data(as_text=True)
        self.assertIn('<nav class="lateral"', h)
        self.assertLess(h.index('<nav class="lateral"'), h.index("Évolution du nombre d'élèves"))
        for mot in ("MENU PRINCIPAL", "Tableau de bord", "Paiement des frais", "Se déconnecter"):
            self.assertIn(mot, h)
        self.assertEqual(self.client("admin1").get("/menu").status_code, 200)
        self.assertIn('<nav class="lateral"', self.client("admin1").get("/menu").get_data(as_text=True))

    def test_nombre_d_eleves_correct(self):
        n = self.conn.execute("SELECT COUNT(*) FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE=I.MATRICULE "
                              "WHERE I.ANNEESCO=(SELECT ANNEESCO FROM ANNEE_SCO ORDER BY ANNEESCO DESC LIMIT 1) AND E.ACTIF=1").fetchone()[0]
        h = self.client("admin1").get("/tableau-de-bord").get_data(as_text=True)
        self.assertIn(f'<span class="lib">Élèves</span><span class="nb">{n}</span>', h)

    def test_sans_droit_403_puis_avec_droit(self):
        c = self.client("int1")
        self.assertEqual(c.get("/tableau-de-bord").status_code, 403)
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_int, {("tableau", "LECTURE")})
        self.assertEqual(c.get("/tableau-de-bord").status_code, 200)
        self.assertTrue(c.get("/").headers["Location"].endswith("/tableau-de-bord"))
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_int, set())
        self.assertEqual(c.get("/tableau-de-bord").status_code, 403)       # effet immédiat

    def test_non_connecte_redirige(self):
        r = self.app.test_client().get("/tableau-de-bord")
        self.assertIn(r.status_code, (302, 401, 403))

    def test_annee_inconnue_ne_plante_pas(self):
        r = self.client("admin1").get("/tableau-de-bord?annee=1900-1901")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Année scolaire inconnue", r.get_data(as_text=True))

    def test_aucun_montant_ni_nom_d_eleve(self):
        h = self.client("admin1").get("/tableau-de-bord").get_data(as_text=True)
        noms = [l[0] for l in self.conn.execute("SELECT NOM FROM ELEVE LIMIT 5")]
        for n in noms:
            self.assertNotIn(n, h)

    def test_ouverture_journalisee(self):
        self.client("admin1").get("/tableau-de-bord")
        n = self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE ACTION = 'TABLEAU_DE_BORD_OUVERT'").fetchone()[0]
        self.assertGreaterEqual(n, 1)


if __name__ == "__main__":
    unittest.main()

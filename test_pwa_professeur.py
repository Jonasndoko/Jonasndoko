"""Espace des professeurs installable (icône et nom GESTSCO) : manifeste, service worker, page.
Lancer :  python -m unittest test_pwa_professeur"""
import json
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web   # noqa: E402
import config    # noqa: E402
import database  # noqa: E402


class TestPwaProfesseur(unittest.TestCase):
    def setUp(self):
        chemin = os.path.join(tempfile.mkdtemp(), "p.db")
        database.connecter(chemin).close()
        self.c = app_web.creer_app(chemin).test_client()

    def test_la_page_annonce_le_manifeste_et_l_icone(self):
        page = self.c.get("/professeur").get_data(as_text=True)
        self.assertIn('rel="manifest" href="/professeur/manifest.webmanifest"', page)
        self.assertIn("/assets/gestsco_180.png", page)
        self.assertIn('id="b-installer"', page)
        self.assertIn("/professeur-sw.js", page)

    def test_manifeste_nom_et_icones_du_logiciel(self):
        r = self.c.get("/professeur/manifest.webmanifest")
        self.assertEqual(r.status_code, 200)
        m = json.loads(r.get_data(as_text=True))
        self.assertEqual(m["short_name"], "GESTSCO")
        self.assertEqual(m["name"], "Système de Gestion Scolaire GESTSCO")
        self.assertEqual((m["start_url"], m["scope"], m["display"]), ("/professeur", "/professeur", "standalone"))
        self.assertEqual({i["purpose"] for i in m["icons"]}, {"any", "maskable"})
        for i in m["icons"]:                                              # chaque icône annoncée existe vraiment
            self.assertEqual(self.c.get(i["src"]).status_code, 200, i["src"])

    def test_service_worker_ne_touche_pas_a_l_api(self):
        r = self.c.get("/professeur-sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Service-Worker-Allowed"], "/professeur")
        js = r.get_data(as_text=True)
        self.assertIn("prof-" + config.VERSION, js)
        self.assertNotIn("/api/", js.split("COQUILLE")[1].split("];")[0])   # aucune donnée de l'API dans la liste mise en cache


if __name__ == "__main__":
    unittest.main()

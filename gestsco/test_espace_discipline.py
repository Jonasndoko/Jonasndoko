"""Tests du module « Espace Discipline » : module à part dans le menu, fonctionnalités en boutons groupés, droits relus à chaque requête.
Lancer :  python -m unittest test_espace_discipline"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web        # noqa: E402
import config         # noqa: E402
import database       # noqa: E402
import droits         # noqa: E402
import modules        # noqa: E402
import security       # noqa: E402
import web_etudes     # noqa: E402

MDP = "Tr@vail-Amour-2026"
ESPACE = "/m/etudes_discipline/direction_discipline"


class TestEspaceDiscipline(unittest.TestCase):
    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "ed.db")
        c = self.conn = database.connecter(self.chemin)
        for login, role in (("admin1", "ADMINISTRATEUR"), ("disc1", "DIRECTEUR_DISCIPLINE"), ("dire1", "DIRECTRICE_ETUDES"),
                            ("prefet1", "PREFET"), ("perc1", "PERCEPTEUR")):
            security.creer_utilisateur(c, login, login.title(), role, MDP)
        self.app = app_web.creer_app(self.chemin)
        self.clients = {}
        for login in ("admin1", "disc1", "dire1", "prefet1", "perc1"):
            cl = self.app.test_client()
            self.assertEqual(cl.post("/connexion", data={"login": login, "mdp": MDP}).status_code, 302)
            self.clients[login] = cl

    def session(self, login):
        return security.authentifier(self.conn, login, MDP).session

    def test_module_declare_et_en_ligne(self):
        self.assertEqual(dict((m[0], m[1]) for m in modules.MODULES)[config.MODULE_DISCIPLINE], "Espace Discipline")
        self.assertIn(config.MODULE_DISCIPLINE, app_web.MODULES_EN_LIGNE)
        self.assertTrue(os.path.exists(os.path.join(config.DOSSIER_ASSETS, f"ico_{config.MODULE_DISCIPLINE}.png")))
        self.assertEqual(config.ESPACES_MODULES[config.ESPACE_DISCIPLINE][0], config.MODULE_DISCIPLINE)

    def test_qui_a_le_module(self):
        for login, attendu in (("admin1", True), ("disc1", True), ("dire1", False), ("prefet1", False), ("perc1", False)):
            self.assertEqual(config.MODULE_DISCIPLINE in modules.modules_ouverts(self.conn, self.session(login)), attendu, login)

    def test_la_gestion_ne_garde_que_prefecture_et_secretariat(self):
        self.assertNotIn("etudes_discipline", [m[0] for m in modules.MODULES])

    def test_route_du_module(self):
        r = self.clients["disc1"].get("/m/discipline")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith(ESPACE))
        for login in ("dire1", "prefet1", "perc1"):
            self.assertEqual(self.clients[login].get("/m/discipline").status_code, 403, login)
            self.assertEqual(self.clients[login].get(ESPACE).status_code, 403, login)

    def test_boutons_groupes_couvrent_toutes_les_fonctionnalites(self):
        fonctions = config.FONCTIONNALITES_DIRECTIONS[config.ESPACE_DISCIPLINE]
        groupes = web_etudes._groupes_boutons(config.ESPACE_DISCIPLINE, fonctions)
        mises = [f[0] for _t, membres in groupes for f in membres]
        self.assertEqual(sorted(mises), sorted(f[0] for f in fonctions))
        self.assertEqual(mises[0], fonctions[0][0])
        self.assertNotIn("Autres", [t for t, _m in groupes])

    def test_page_avec_boutons(self):
        r = self.clients["disc1"].get(ESPACE)
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn('<h1 style="margin-top:0">Espace Discipline</h1>', html)
        self.assertEqual(html.count('class="em-btn '), len(config.FONCTIONNALITES_DIRECTIONS[config.ESPACE_DISCIPLINE]))
        self.assertEqual(html.count('class="em-btn actif"'), 1)                # un seul bouton actif (les onglets internes d'une fonctionnalité sont à part)
        self.assertNotIn("Gestion des études et discipline", html)
        self.assertNotIn('aria-label="Fonctionnalités de l\'espace"', html)

    def test_chaque_bouton_ouvre_sa_fonctionnalite(self):
        cl = self.clients["disc1"]
        for cle, _lib, _desc in config.FONCTIONNALITES_DIRECTIONS[config.ESPACE_DISCIPLINE]:
            r = cl.get(f"{ESPACE}?f={cle}")
            self.assertEqual(r.status_code, 200, cle)
            html = r.get_data(as_text=True)
            self.assertIn(f'href="{ESPACE}?f={cle}"', html, cle)
            self.assertEqual(html.count('class="em-btn actif"'), 1, cle)

    def test_barre_laterale(self):
        page = self.clients["admin1"].get("/menu").get_data(as_text=True)
        for lien in ('href="/m/etudes"', 'href="/m/discipline"', 'href="/m/prefecture"', 'href="/m/secretariat"'):
            self.assertIn(lien, page)
        for absent in ("/m/etudes_discipline/direction_discipline", "/m/etudes_discipline/direction_etudes"):
            self.assertNotIn(absent, page)

    def test_retrait_du_droit_effet_immediat(self):
        cl = self.clients["disc1"]
        self.assertEqual(cl.get(ESPACE).status_code, 200)
        uid = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = 'disc1'").fetchone()[0]
        with self.conn:
            droits.remplacer_droits(self.conn, uid, set())
        self.assertEqual(cl.get(ESPACE).status_code, 403)
        self.assertEqual(cl.get("/m/discipline").status_code, 403)


if __name__ == "__main__":
    unittest.main()

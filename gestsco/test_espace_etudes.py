"""Tests du module « Espace Études » : module à part dans le menu, fonctionnalités en boutons groupés, droits relus à chaque requête.
Lancer :  python -m unittest test_espace_etudes"""
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
ESPACE = "/m/etudes_discipline/direction_etudes"


class TestEspaceEtudes(unittest.TestCase):
    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "ee.db")
        c = self.conn = database.connecter(self.chemin)
        for login, role in (("admin1", "ADMINISTRATEUR"), ("dire1", "DIRECTRICE_ETUDES"), ("prefet1", "PREFET"),
                            ("disc1", "DIRECTEUR_DISCIPLINE"), ("perc1", "PERCEPTEUR")):
            security.creer_utilisateur(c, login, login.title(), role, MDP)
        self.app = app_web.creer_app(self.chemin)
        self.clients = {}
        for login in ("admin1", "dire1", "prefet1", "disc1", "perc1"):
            cl = self.app.test_client()
            self.assertEqual(cl.post("/connexion", data={"login": login, "mdp": MDP}).status_code, 302)
            self.clients[login] = cl

    def session(self, login):
        return security.authentifier(self.conn, login, MDP).session

    def test_module_declare_et_en_ligne(self):
        self.assertIn(config.MODULE_ETUDES, [m[0] for m in modules.MODULES])
        self.assertIn(config.MODULE_ETUDES, app_web.MODULES_EN_LIGNE)
        self.assertEqual(dict((m[0], m[1]) for m in modules.MODULES)[config.MODULE_ETUDES], "Espace Études")
        self.assertTrue(os.path.exists(os.path.join(config.DOSSIER_ASSETS, f"ico_{config.MODULE_ETUDES}.png")))

    def test_seuls_la_directrice_et_ladministrateur_ont_le_module(self):
        for login, attendu in (("admin1", True), ("dire1", True), ("prefet1", False), ("disc1", False), ("perc1", False)):
            self.assertEqual(config.MODULE_ETUDES in modules.modules_ouverts(self.conn, self.session(login)), attendu, login)

    def test_la_discipline_ne_contient_plus_lespace_etudes(self):
        admin = self.session("admin1")
        # les droits de l'espace restent ceux de la Direction des études (référence des pages de l'espace)
        self.assertIn(config.ESPACE_ETUDES, [c for c, _t in modules.sous_menus_ouverts(self.conn, admin)])
        # la Directrice n'a plus de raison d'ouvrir l'accueil de la discipline
        self.assertNotIn("etudes_discipline", [m[0] for m in modules.MODULES])

    def test_route_du_module(self):
        r = self.clients["dire1"].get("/m/etudes")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith(ESPACE))
        for login in ("prefet1", "disc1", "perc1"):
            self.assertEqual(self.clients[login].get("/m/etudes").status_code, 403, login)
            self.assertEqual(self.clients[login].get(ESPACE).status_code, 403, login)

    def test_boutons_groupes_couvrent_toutes_les_fonctionnalites(self):
        fonctions = config.FONCTIONNALITES_DIRECTIONS[config.ESPACE_ETUDES]
        groupes = web_etudes._groupes_boutons(config.ESPACE_ETUDES, fonctions)
        mises = [f[0] for _titre, membres in groupes for f in membres]
        self.assertEqual(sorted(mises), sorted(f[0] for f in fonctions))       # aucune oubliée, aucune en double
        self.assertEqual(mises[0], fonctions[0][0])                            # le premier bouton est la fonctionnalité ouverte par défaut
        self.assertNotIn("Autres", [t for t, _m in groupes])                   # la configuration couvre tout
        # une fonctionnalité oubliée par la configuration atterrit dans « Autres » au lieu de disparaître
        sup = fonctions + (("nouvelle", "Nouvelle", "..."),)
        self.assertEqual(web_etudes._groupes_boutons(config.ESPACE_ETUDES, sup)[-1], ("Autres", [("nouvelle", "Nouvelle", "...")]))

    def test_page_avec_boutons_et_sans_onglets(self):
        r = self.clients["dire1"].get(ESPACE)
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("<h1 style=\"margin-top:0\">Espace Études</h1>", html)
        self.assertEqual(html.count('class="em-btn '), len(config.FONCTIONNALITES_DIRECTIONS[config.ESPACE_ETUDES]))
        self.assertEqual(html.count('aria-current="page"'), 1)                 # un seul bouton actif
        self.assertNotIn("Gestion des études et discipline", html)             # plus de retour vers l'accueil de la discipline
        self.assertNotIn('aria-label="Fonctionnalités de l\'espace"', html)    # l'ancienne barre d'onglets a disparu

    def test_chaque_bouton_ouvre_sa_fonctionnalite(self):
        cl = self.clients["dire1"]
        for cle, _lib, _desc in config.FONCTIONNALITES_DIRECTIONS[config.ESPACE_ETUDES]:
            r = cl.get(f"{ESPACE}?f={cle}")
            self.assertEqual(r.status_code, 200, cle)
            html = r.get_data(as_text=True)
            self.assertIn(f'href="{ESPACE}?f={cle}"', html, cle)
            self.assertEqual(html.count('class="em-btn actif"'), 1, cle)

    def test_barre_laterale(self):
        page = self.clients["admin1"].get("/menu").get_data(as_text=True)
        self.assertIn('href="/m/etudes"', page)
        self.assertIn("Espace Études", page)
        for lien in ('href="/m/prefecture"', 'href="/m/secretariat"'):
            self.assertIn(lien, page)
        self.assertNotIn('/m/etudes_discipline/direction_etudes', page)        # plus de sous-entrée « Direction des études »

    def test_retrait_du_droit_effet_immediat(self):
        cl = self.clients["dire1"]
        self.assertEqual(cl.get(ESPACE).status_code, 200)
        uid = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = 'dire1'").fetchone()[0]
        with self.conn:
            droits.remplacer_droits(self.conn, uid, set())
        self.assertEqual(cl.get(ESPACE).status_code, 403)
        self.assertEqual(cl.get("/m/etudes").status_code, 403)

    def test_ecran_windows_compilable(self):
        for nom in ("ecrans.py", "ecrans_etudes.py"):
            with open(os.path.join(os.path.dirname(__file__), nom), encoding="utf-8") as f:
                compile(f.read(), nom, "exec")
        with open(os.path.join(os.path.dirname(__file__), "ecrans.py"), encoding="utf-8") as f:
            self.assertIn("config.ESPACES_MODULES", f.read())


if __name__ == "__main__":
    unittest.main()

"""Tests du module « Gestion des études et discipline » : un sous-menu par poste, droits relus à chaque requête, migration.
Lancer :  python -m unittest test_etudes_discipline"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web        # noqa: E402
import config         # noqa: E402
import database       # noqa: E402
import droits         # noqa: E402
import migrations     # noqa: E402
import modules        # noqa: E402
import security       # noqa: E402

MDP = "Tr@vail-Amour-2026"
POSTES = {"PREFET": "prefecture", "DIRECTRICE_ETUDES": "direction_etudes", "DIRECTEUR_DISCIPLINE": "direction_discipline",
          "SECRETAIRE": "dossier_eleve"}


class TestEtudesDiscipline(unittest.TestCase):
    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "e.db")
        c = self.conn = database.connecter(self.chemin)
        security.creer_utilisateur(c, "admin1", "Alice", "ADMINISTRATEUR", MDP)
        self.sessions = {}
        for role in POSTES:
            security.creer_utilisateur(c, role.lower(), role.title(), role, MDP)
        security.creer_utilisateur(c, "perc1", "Paul", "PERCEPTEUR", MDP)
        self.app = app_web.creer_app(self.chemin)
        self.clients = {}
        for login in ["admin1", "perc1"] + [r.lower() for r in POSTES]:
            cl = self.app.test_client()
            self.assertEqual(cl.post("/connexion", data={"login": login, "mdp": MDP}).status_code, 302)
            self.clients[login] = cl

    def session(self, login):
        return security.authentifier(self.conn, login, MDP).session

    def test_quatre_espaces_declares_chacun_un_module(self):
        cles = [m[0] for m in modules.MODULES]
        self.assertNotIn("etudes_discipline", cles)                      # l'ancien module d'accueil n'existe plus
        for cle_module, _titre, _g in config.ESPACES_MODULES.values():
            self.assertIn(cle_module, cles)
        self.assertEqual(sorted(config.ESPACES_MODULES), sorted(c for c, _t, _r in config.SOUS_MENUS_ETUDES))
        self.assertEqual([c for c, _t, _r in config.SOUS_MENUS_ETUDES],
                         ["prefecture", "direction_etudes", "direction_discipline", "dossier_eleve"])
        for cle, _t, _r in config.SOUS_MENUS_ETUDES:
            self.assertIn(cle, config.MODULES_DROITS)

    def test_chaque_poste_ne_voit_que_son_sous_menu(self):
        for role, cle in POSTES.items():
            s = self.session(role.lower())
            self.assertEqual([c for c, _t in modules.sous_menus_ouverts(self.conn, s)], [cle], role)
            propre = config.ESPACES_MODULES[cle][0]                       # chaque espace est un module du menu
            ouverts = modules.modules_ouverts(self.conn, s)
            self.assertIn(propre, ouverts, role)
            for autre_espace, (autre, _t, _g) in config.ESPACES_MODULES.items():
                if autre != propre:
                    self.assertNotIn(autre, ouverts, (role, autre))
        for cle_module, _t, _g in config.ESPACES_MODULES.values():
            self.assertNotIn(cle_module, modules.modules_ouverts(self.conn, self.session("perc1")))
        self.assertEqual(len(modules.sous_menus_ouverts(self.conn, self.session("admin1"))), 4)

    def test_acces_web_refuse_hors_de_son_sous_menu(self):
        for role, cle in POSTES.items():
            cl = self.clients[role.lower()]
            cle_module = config.ESPACES_MODULES[cle][0]
            module = cl.get("/m/" + cle_module)                            # /m/<module> ouvre l'espace du module
            self.assertEqual(module.status_code, 302)
            self.assertTrue(module.headers["Location"].endswith(f"/m/etudes_discipline/{cle}"))
            ancien = cl.get("/m/etudes_discipline")                        # ancienne adresse de l'accueil : redirige vers le premier module ouvert
            self.assertEqual(ancien.status_code, 302)
            self.assertTrue(ancien.headers["Location"].endswith(f"/m/etudes_discipline/{cle}"))
            for autre_module, _t, _g in config.ESPACES_MODULES.values():
                if autre_module != cle_module:
                    self.assertEqual(cl.get("/m/" + autre_module).status_code, 403, (role, autre_module))
            self.assertEqual(cl.get(f"/m/etudes_discipline/{cle}").status_code, 200)
            for autre in POSTES.values():
                if autre != cle:
                    self.assertEqual(cl.get(f"/m/etudes_discipline/{autre}").status_code, 403, (role, autre))
        perc = self.clients["perc1"]
        self.assertEqual(perc.get("/m/etudes_discipline").status_code, 403)
        for cle_module, _t, _g in config.ESPACES_MODULES.values():
            self.assertEqual(perc.get("/m/" + cle_module).status_code, 403, cle_module)
            self.assertEqual(self.clients["admin1"].get("/m/" + cle_module).status_code, 302, cle_module)
        self.assertEqual(perc.get("/m/etudes_discipline/prefecture").status_code, 403)
        self.assertEqual(self.clients["admin1"].get("/m/etudes_discipline/inconnu").status_code, 404)
        for cle in POSTES.values():
            self.assertEqual(self.clients["admin1"].get(f"/m/etudes_discipline/{cle}").status_code, 200)

    def test_la_barre_laterale_montre_les_modules(self):
        page = self.clients["prefet"].get("/menu").get_data(as_text=True)
        self.assertIn('href="/m/prefecture"', page)
        self.assertNotIn("Gestion des études et discipline", page)
        for autre in ("/m/secretariat", "/m/etudes\"", "/m/discipline"):
            self.assertNotIn(f'href="{autre}', page)

    def test_retrait_du_droit_effet_immediat(self):
        cl = self.clients["prefet"]
        self.assertEqual(cl.get("/m/etudes_discipline/prefecture").status_code, 200)
        uid = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = 'prefet'").fetchone()[0]
        with self.conn:
            droits.remplacer_droits(self.conn, uid, set())
        self.assertEqual(cl.get("/m/etudes_discipline/prefecture").status_code, 403)

    def test_migration_comptes_existants(self):
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE MODULE IN ('prefecture','direction_etudes','direction_discipline','dossier_eleve')")
            self.conn.execute("DELETE FROM ROLE_DROIT WHERE MODULE IN ('prefecture','direction_etudes','direction_discipline','dossier_eleve')")
        migrations._mig_etudes_discipline(self.conn)
        for role, cle in POSTES.items():
            self.assertIn((cle, "LECTURE"), droits.droits_par_defaut(self.conn, role))
            uid = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE ROLE = ?", (role,)).fetchone()[0]
            self.assertIn((cle, "LECTURE"), droits.droits_utilisateur(self.conn, uid))

    def test_ecran_windows_compilable(self):
        src = open(os.path.join(os.path.dirname(__file__), "ecrans_etudes.py"), encoding="utf-8").read()
        compile(src, "ecrans_etudes.py", "exec")


if __name__ == "__main__":
    unittest.main()

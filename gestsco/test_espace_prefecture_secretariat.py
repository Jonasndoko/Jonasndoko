"""Tests des modules « Préfecture » et « Secrétariat » : modules à part du menu, fonctionnalités en boutons groupés, droits relus à chaque requête.
Lancer :  python -m unittest test_espace_prefecture_secretariat"""
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
ESPACES = {"prefecture": ("prefet1", "prefecture", "Préfecture"), "secretariat": ("secr1", "dossier_eleve", "Secrétariat")}


class TestPrefectureSecretariat(unittest.TestCase):
    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "ps.db")
        c = self.conn = database.connecter(self.chemin)
        for login, role in (("admin1", "ADMINISTRATEUR"), ("prefet1", "PREFET"), ("secr1", "SECRETAIRE"),
                            ("dire1", "DIRECTRICE_ETUDES"), ("perc1", "PERCEPTEUR")):
            security.creer_utilisateur(c, login, login.title(), role, MDP)
        self.app = app_web.creer_app(self.chemin)
        self.clients = {}
        for login in ("admin1", "prefet1", "secr1", "dire1", "perc1"):
            cl = self.app.test_client()
            self.assertEqual(cl.post("/connexion", data={"login": login, "mdp": MDP}).status_code, 302)
            self.clients[login] = cl

    def session(self, login):
        return security.authentifier(self.conn, login, MDP).session

    def test_modules_declares_et_en_ligne(self):
        titres = dict((m[0], m[1]) for m in modules.MODULES)
        for cle_module, (_login, espace, titre) in ESPACES.items():
            self.assertEqual(titres[cle_module], titre)
            self.assertIn(cle_module, app_web.MODULES_EN_LIGNE)
            self.assertEqual(config.ESPACES_MODULES[espace][0], cle_module)
            self.assertTrue(os.path.exists(os.path.join(config.DOSSIER_ASSETS, f"ico_{cle_module}.png")))
        self.assertNotIn("etudes_discipline", titres)

    def test_qui_a_quel_module(self):
        attendu = {"admin1": {"prefecture", "secretariat"}, "prefet1": {"prefecture"}, "secr1": {"secretariat"}, "dire1": set(), "perc1": set()}
        for login, modules_attendus in attendu.items():
            ouverts = set(modules.modules_ouverts(self.conn, self.session(login)))
            for cle_module in ("prefecture", "secretariat"):
                self.assertEqual(cle_module in ouverts, cle_module in modules_attendus, (login, cle_module))

    def test_routes_des_modules(self):
        for cle_module, (login, espace, _t) in ESPACES.items():
            r = self.clients[login].get("/m/" + cle_module)
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r.headers["Location"].endswith(f"/m/etudes_discipline/{espace}"))
            for autre in ("dire1", "perc1"):
                self.assertEqual(self.clients[autre].get("/m/" + cle_module).status_code, 403, (autre, cle_module))
        self.assertEqual(self.clients["prefet1"].get("/m/secretariat").status_code, 403)
        self.assertEqual(self.clients["secr1"].get("/m/prefecture").status_code, 403)

    def test_boutons_groupes_couvrent_toutes_les_fonctionnalites(self):
        for espace in (config.ESPACE_PREFECTURE, config.ESPACE_SECRETARIAT):
            fonctions = web_etudes._fonctions_espace(espace)
            groupes = web_etudes._groupes_boutons(espace, fonctions)
            mises = [f[0] for _t, membres in groupes for f in membres]
            self.assertEqual(sorted(mises), sorted(f[0] for f in fonctions), espace)
            self.assertEqual(mises[0], fonctions[0][0], espace)                  # le premier bouton est la fonctionnalité ouverte par défaut
            self.assertNotIn("Autres", [t for t, _m in groupes], espace)

    def test_pages_avec_boutons_et_sans_onglets(self):
        for cle_module, (login, espace, titre) in ESPACES.items():
            html = self.clients[login].get(f"/m/etudes_discipline/{espace}").get_data(as_text=True)
            self.assertIn(f'<h1 style="margin-top:0">{titre}</h1>', html)
            self.assertEqual(html.count('class="em-btn '), len(web_etudes._fonctions_espace(espace)), espace)
            self.assertEqual(html.count('class="em-btn actif"'), 1, espace)
            self.assertNotIn("Gestion des études et discipline", html)
            self.assertNotIn('class="onglets" aria-label="Fonctionnalités de', html)

    def test_chaque_bouton_ouvre_sa_fonctionnalite(self):
        for cle_module, (login, espace, _t) in ESPACES.items():
            cl = self.clients[login]
            for cle, _lib, _desc in web_etudes._fonctions_espace(espace):
                if espace == "dossier_eleve" and cle == "inscription":
                    continue                                                      # ouvre le module Inscription (testé ci-dessous)
                r = cl.get(f"/m/etudes_discipline/{espace}?f={cle}")
                self.assertEqual(r.status_code, 200, (espace, cle))
                html = r.get_data(as_text=True)
                self.assertIn(f'href="/m/etudes_discipline/{espace}?f={cle}"', html, (espace, cle))
                self.assertEqual(html.count('class="em-btn actif"'), 1, (espace, cle))

    def test_inscription_dans_le_secretariat(self):
        html = self.clients["secr1"].get("/m/etudes_discipline/dossier_eleve").get_data(as_text=True)
        self.assertIn('href="/m/inscription"', html)                               # bouton « Inscription » du Secrétariat
        r = self.clients["secr1"].get("/m/inscription")
        self.assertEqual(r.status_code, 200)
        page = r.get_data(as_text=True)
        self.assertIn('<h1 style="margin-top:0">Secrétariat</h1>', page)
        self.assertEqual(page.count('class="em-btn actif"'), 1)                  # « Inscription » est le bouton actif
        self.assertIn('class="em-btn actif" href="/m/inscription"', page)
        self.assertNotIn("Gestion des études et discipline", page)

    def test_inscription_reservee_sans_le_droit(self):
        uid = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = 'secr1'").fetchone()[0]
        actuels = {(m, d) for m, d in droits.droits_utilisateur(self.conn, uid) if m != "inscription"}
        with self.conn:
            droits.remplacer_droits(self.conn, uid, actuels)
        html = self.clients["secr1"].get("/m/etudes_discipline/dossier_eleve").get_data(as_text=True)
        self.assertIn("Inscription (réservé)", html)
        self.assertIn('class="em-btn verrou"', html)

    def test_bulletins_du_secretariat_sans_annee_scolaire(self):
        r = self.clients["secr1"].get("/m/etudes_discipline/dossier_eleve?f=bulletins")
        self.assertEqual(r.status_code, 200)                                      # message au lieu d'une erreur 500
        self.assertIn("Aucune année scolaire", r.get_data(as_text=True))

    def test_annee_conservee_dans_les_boutons_de_la_prefecture(self):
        html = self.clients["prefet1"].get("/m/etudes_discipline/prefecture?f=tableau").get_data(as_text=True)
        self.assertEqual(html.count('class="em-btn '), len(config.FONCTIONNALITES_PREFECTURE))

    def test_ancienne_adresse_et_barre_laterale(self):
        r = self.clients["secr1"].get("/m/etudes_discipline")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/m/etudes_discipline/dossier_eleve"))
        self.assertEqual(self.clients["perc1"].get("/m/etudes_discipline").status_code, 403)
        page = self.clients["admin1"].get("/menu").get_data(as_text=True)
        for lien in ('href="/m/prefecture"', 'href="/m/secretariat"'):
            self.assertIn(lien, page)
        self.assertNotIn("Gestion des études et discipline", page)
        self.assertNotIn('class="entree sous-entree"', page)                   # plus de sous-entrées sous un module

    def test_retrait_du_droit_effet_immediat(self):
        for cle_module, (login, espace, _t) in ESPACES.items():
            cl = self.clients[login]
            self.assertEqual(cl.get(f"/m/etudes_discipline/{espace}").status_code, 200)
            uid = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = ?", (login,)).fetchone()[0]
            with self.conn:
                droits.remplacer_droits(self.conn, uid, set())
            self.assertEqual(cl.get(f"/m/etudes_discipline/{espace}").status_code, 403, espace)
            self.assertEqual(cl.get("/m/" + cle_module).status_code, 403, cle_module)


if __name__ == "__main__":
    unittest.main()

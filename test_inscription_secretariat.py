"""Tests de l'intégration du module Inscription au Secrétariat (onglet « Inscription », cadre commun, droits propres de l'inscription).
Lancer :  python -m unittest test_inscription_secretariat"""
import re
import unittest

import app_web                    # noqa: E402
import config                     # noqa: E402
import modules                    # noqa: E402
from test_notes import MDP        # noqa: E402
from test_prefecture_v57 import Fixture   # noqa: E402


class TestOnglet(Fixture):
    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])
        self.cl = self.app.test_client()
        self.assertEqual(self.cl.post("/connexion", data={"login": "secr1", "mdp": MDP}).status_code, 302)
        self.secretariat = "/m/etudes_discipline/dossier_eleve"

    def test_onglet_declare_apres_les_dossiers(self):
        self.assertEqual([c for c, _t, _d in config.FONCTIONNALITES_SECRETARIAT][:2], ["dossiers", "inscription"])

    def test_la_secretaire_a_les_droits_d_inscription_par_defaut(self):
        d = {(m, x) for m, x in self.conn.execute("SELECT MODULE, DROIT FROM DROIT WHERE ID_USER = ?", (self.secr.id_user,))}
        self.assertEqual({x for m, x in d if m == "inscription"}, {"LECTURE", "AJOUT", "MODIFICATION"})

    def test_onglet_visible_et_page_dans_le_cadre_du_secretariat(self):
        h = self.cl.get(self.secretariat).get_data(as_text=True)
        self.assertRegex(h, r'<a class="em-btn [^"]*" href="/m/inscription"[^>]*>.*?<span>Inscription</span></a>')      # bouton du Secrétariat
        r = self.cl.get("/m/inscription")
        self.assertEqual(r.status_code, 200)
        page = r.get_data(as_text=True)
        self.assertNotIn("Gestion des études et discipline", page)                # ce module n'existe plus : le Secrétariat est un module à part
        for mot in ("Secrétariat", "Formulaire d&#39;inscription", "Liste d&#39;attente",
                    "Validation et affectation", "Dossiers des élèves", "Bulletins scolaires"):
            self.assertIn(mot, page, mot)
        self.assertEqual(self.cl.get("/m/inscription/liste").status_code, 200)

    def test_pas_de_tuile_a_part_avec_le_secretariat(self):
        self.assertNotIn("inscription", modules.modules_ouverts(self.conn, self.secr))
        self.assertIn("dossier_eleve", [c for c, _t in modules.sous_menus_ouverts(self.conn, self.secr)])

    def test_sans_le_droit_d_inscription_l_onglet_est_verrouille(self):
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'inscription'", (self.secr.id_user,))
        h = self.cl.get(self.secretariat).get_data(as_text=True)
        self.assertNotIn('href="/m/inscription"', h)
        self.assertIn("Inscription (réservé)", h)
        self.assertIn('class="em-btn verrou"', h)
        self.assertEqual(self.cl.get("/m/inscription").status_code, 403)
        self.assertEqual(self.cl.get("/m/inscription/liste").status_code, 403)

    def test_les_autres_onglets_du_secretariat_restent_accessibles(self):
        for f in ("dossiers", "bulletins", "archives", "listes"):
            self.assertEqual(self.cl.get(f"{self.secretariat}?f={f}").status_code, 200, f)

    def test_poste_sans_secretariat_garde_la_tuile_et_les_pages(self):
        cl = self.app.test_client()
        cl.post("/connexion", data={"login": "dire1", "mdp": MDP})
        with self.conn:
            self.conn.executemany("INSERT INTO DROIT (ID_USER, MODULE, DROIT) VALUES (?, 'inscription', ?)",
                                  [(self.dire.id_user, "LECTURE")])
        self.assertIn("inscription", modules.modules_ouverts(self.conn, self.dire))
        page = cl.get("/m/inscription/liste").get_data(as_text=True)
        self.assertEqual(re.search(r"Dossiers des élèves", page), None)       # pas de cadre du Secrétariat
        self.assertIn("Liste d&#39;attente", page)


if __name__ == "__main__":
    unittest.main()

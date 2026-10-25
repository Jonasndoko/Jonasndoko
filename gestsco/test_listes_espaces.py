"""Tests de la liste des élèves par classe et année scolaire dans les quatre espaces : Direction des études, Direction de discipline,
Préfecture et Secrétariat (droit de Lecture de chaque module, PDF, CSV, journal, pas de dossiers incomplets hors Secrétariat).
Lancer :  python -m unittest test_listes_espaces"""
import unittest

import app_web                    # noqa: E402
import config                     # noqa: E402
import listes_administratives as la   # noqa: E402
from listes_administratives import ErreurListes   # noqa: E402
from test_listes_administratives import Fix, matricules   # noqa: E402
from test_notes import MDP        # noqa: E402

ESPACES = (("dire", "direction_etudes"), ("dird", "direction_discipline"), ("prefet", "prefecture"), ("secr", "dossier_eleve"))


class TestEspaces(Fix):
    def session(self, nom):
        return getattr(self, nom)

    def test_chaque_espace_voit_la_meme_liste(self):
        attendu = sorted(matricules(la.liste(self.conn, self.secr)))
        self.assertEqual(attendu, ["0000/26", "0001/26", "0002/26", "0009/26"])
        for nom, espace in ESPACES:
            r = la.liste(self.conn, self.session(nom), espace=espace)
            self.assertEqual(sorted(matricules(r)), attendu, espace)
            self.assertEqual([k["classe"] for k in r["classes"]], ["7ème A", "8ème A"], espace)
            self.assertEqual(r["resume"]["total"], 4)

    def test_filtres_classe_option_annee(self):
        for nom, espace in ESPACES:
            s = self.session(nom)
            self.assertEqual(matricules(la.liste(self.conn, s, n_classe=self.c8, espace=espace)), ["0009/26"])
            self.assertEqual(matricules(la.liste(self.conn, s, option="SCI", espace=espace)), ["0009/26"])
            self.assertEqual(la.liste(self.conn, s, annee="2019-2020", espace=espace)["resume"]["total"], 0)
            self.assertIn(self.annee, la.annees(self.conn, s, espace))
            self.assertEqual(len(la.filtres(self.conn, s, self.annee, espace)["classes"]), 2)

    def test_pas_de_dossiers_incomplets_hors_secretariat(self):
        for nom, espace in ESPACES[:3]:
            r = la.liste(self.conn, self.session(nom), genre="incomplets", espace=espace)
            self.assertEqual(r["genre"], "eleves", espace)
            self.assertEqual(r["resume"]["total"], 4)
        self.assertEqual(la.liste(self.conn, self.secr, genre="incomplets")["genre"], "incomplets")

    def test_un_poste_n_a_que_son_espace(self):
        for nom, espace in ESPACES:
            for autre_nom, autre in ESPACES:
                if autre == espace:
                    continue
                with self.assertRaises(PermissionError, msg=(nom, autre)):
                    la.liste(self.conn, self.session(nom), espace=autre)
        with self.assertRaises(ErreurListes):
            la.liste(self.conn, self.admin, espace="inconnu")
        for _nom, espace in ESPACES:
            self.assertEqual(la.liste(self.conn, self.admin, espace=espace)["resume"]["total"], 4)

    def test_droit_relu_a_chaque_appel(self):
        la.liste(self.conn, self.dird, espace="direction_discipline")
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'direction_discipline'", (self.dird.id_user,))
        with self.assertRaises(PermissionError):
            la.liste(self.conn, self.dird, espace="direction_discipline")

    def test_section_primaire_seule_refusee(self):
        with self.conn:
            self.conn.execute("INSERT INTO SECTION_UTILISATEUR (ID_USER, SECTION) VALUES (?, 'PRIMAIRE')", (self.dire.id_user,))
        with self.assertRaises(PermissionError):
            la.liste(self.conn, self.dire, espace="direction_etudes")

    def test_csv_sans_la_colonne_dossier_hors_secretariat(self):
        texte, nom = la.exporter_csv(self.conn, self.dire, espace="direction_etudes")
        entete = texte.splitlines()[0]
        self.assertNotIn("Dossier", entete)
        self.assertIn("Téléphone du tuteur", entete)
        self.assertEqual(len(texte.strip().splitlines()), 5)
        self.assertTrue(nom.endswith(".csv"))
        self.assertIn("Dossier", la.exporter_csv(self.conn, self.secr)[0].splitlines()[0])

    def test_pdf_de_chaque_espace(self):
        for nom, espace in ESPACES:
            octets, fichier = la.document_pdf(self.conn, self.session(nom), espace=espace)
            self.assertTrue(octets.startswith(b"%PDF"), espace)
            self.assertTrue(fichier.endswith(".pdf"))

    def test_journal_avec_l_espace(self):
        la.liste(self.conn, self.dird, espace="direction_discipline")
        la.exporter_csv(self.conn, self.prefet, espace="prefecture")
        la.document_pdf(self.conn, self.dire, espace="direction_etudes")
        d = [l["DETAIL"] for l in self.conn.execute("SELECT ACTION, DETAIL FROM JOURNAL WHERE ACTION LIKE 'LISTE_ADMIN%' ORDER BY ID_LOG")]
        self.assertTrue(any("espace direction_discipline" in x for x in d))
        self.assertTrue(any("espace prefecture" in x for x in d))
        self.assertTrue(any("espace direction_etudes" in x for x in d))

    def test_onglet_declare_dans_les_espaces(self):
        for sous in ("direction_etudes", "direction_discipline"):
            self.assertIn("listes", [c for c, _t, _d in config.FONCTIONNALITES_DIRECTIONS[sous]])
        self.assertEqual(config.FONCTIONNALITES_PREFECTURE[-1][0], "listes")
        self.assertIn("listes", [c for c, _t, _d in config.FONCTIONNALITES_SECRETARIAT])


class TestWebEspaces(Fix):
    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])

    def client(self, login):
        cl = self.app.test_client()
        self.assertEqual(cl.post("/connexion", data={"login": login, "mdp": MDP}).status_code, 302)
        return cl

    def test_page_pdf_csv_de_chaque_espace(self):
        for login, espace in (("dire1", "direction_etudes"), ("dird1", "direction_discipline"), ("prefet1", "prefecture"), ("secr1", "dossier_eleve")):
            cl = self.client(login)
            base = f"/m/etudes_discipline/{espace}"
            r = cl.get(f"{base}?f=listes")
            self.assertEqual(r.status_code, 200, espace)
            h = r.get_data(as_text=True)
            for mot in ("7ème A", "8ème A", "Générer la liste", "Imprimer (PDF)", "Exporter (CSV)"):
                self.assertIn(mot, h, (espace, mot))
            self.assertEqual("Dossiers incomplets" in h, espace == "dossier_eleve", espace)     # onglet et chiffre réservés au Secrétariat
            r = cl.get(f"{base}/listes/liste.pdf?annee={self.annee}&classe={self.c7}")
            self.assertEqual((r.status_code, r.mimetype), (200, "application/pdf"), espace)
            r = cl.get(f"{base}/listes/liste.csv?annee={self.annee}")
            self.assertEqual((r.status_code, r.mimetype), (200, "text/csv"), espace)
            self.assertIn("0000/26", r.get_data(as_text=True))

    def test_filtre_par_classe_dans_la_page(self):
        h = self.client("prefet1").get(f"/m/etudes_discipline/prefecture?f=listes&annee={self.annee}&classe={self.c8}").get_data(as_text=True)
        self.assertIn("0009/26", h)
        self.assertNotIn("0000/26", h)

    def test_autres_postes_refuses_et_anonyme(self):
        cl = self.client("dird1")
        for url in ("/m/etudes_discipline/direction_etudes?f=listes", "/m/etudes_discipline/prefecture?f=listes",
                    "/m/etudes_discipline/direction_etudes/listes/liste.pdf", "/m/etudes_discipline/prefecture/listes/liste.csv"):
            self.assertEqual(cl.get(url).status_code, 403, url)
        anonyme = self.app.test_client()
        self.assertIn(anonyme.get("/m/etudes_discipline/direction_etudes/listes/liste.pdf").status_code, (302, 401, 403))
        self.assertEqual(self.client("dire1").get("/m/etudes_discipline/inconnu/listes/liste.pdf").status_code, 404)

    def test_rien_a_imprimer_donne_404(self):
        self.assertEqual(self.client("dire1").get("/m/etudes_discipline/direction_etudes/listes/liste.pdf?annee=2019-2020").status_code, 404)


if __name__ == "__main__":
    unittest.main()

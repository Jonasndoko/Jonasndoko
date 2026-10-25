"""Tests du module Traçabilité et audit en ligne (web_audit.py) : droit de Lecture (ou Administrateur) relu à chaque appel, les six
fonctionnalités (journal, opérations financières et fiche, contrôles, contrôle financier, recherche, rapports), exportations CSV et PDF
(fichier effacé du serveur, exportation journalisée), saisies invalides, protection contre les envois venus d'un autre site.
Lancer :  python -m unittest test_audit_web"""
import glob
import html
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web         # noqa: E402
import config          # noqa: E402
import database        # noqa: E402
import demo            # noqa: E402
import droits          # noqa: E402
import security        # noqa: E402

MDP = "Tr@vail-Amour-2026"
ETRANGER = {"Origin": "https://autre-site.example"}
PAGES = ("/m/audit/journal", "/m/audit/finances", "/m/audit/controles", "/m/audit/financier", "/m/audit/recherche", "/m/audit/rapports")


class Base(unittest.TestCase):
    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "t.db")
        self.conn = database.connecter(self.chemin)
        self.login_perc, self.mdp_perc = demo.semer(self.conn)
        security.creer_utilisateur(self.conn, "admin1", "Alice Directrice", "ADMINISTRATEUR", MDP)
        security.creer_utilisateur(self.conn, "aud1", "Annie Auditrice", "INTENDANT", MDP)
        security.creer_utilisateur(self.conn, "sec1", "Sophie Secrétaire", "SECRETAIRE", MDP)
        self.id_aud = self.id_de("aud1")
        self.donner(self.id_aud, {("audit", "LECTURE")})
        self.app = app_web.creer_app(self.chemin)
        self.admin, self.aud, self.sec = (self.app.test_client() for _ in range(3))
        for c, l in ((self.admin, "admin1"), (self.aud, "aud1"), (self.sec, "sec1")):
            self.assertEqual(c.post("/connexion", data={"login": l, "mdp": MDP}).status_code, 302)

    def donner(self, id_user, accordes):
        with self.conn:
            droits.remplacer_droits(self.conn, id_user, accordes)

    def texte(self, r):
        return html.unescape(r.get_data(as_text=True))

    def journal(self, action):
        return self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE ACTION = ?", (action,)).fetchone()[0]

    def id_de(self, login):
        return self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = ?", (login,)).fetchone()[0]

    def sans_trace_des_paiements(self):
        """Fraude simulée : on contourne le verrou du journal pour effacer la trace des paiements."""
        self.conn.execute("DROP TRIGGER JOURNAL_NO_DELETE")
        self.conn.execute("DELETE FROM JOURNAL WHERE ACTION = 'PAIEMENT_ENREGISTRE'")
        self.conn.commit()

    def un_recu(self):
        return self.conn.execute("SELECT N_RECU FROM PAIEMENT ORDER BY NUM_SEQ LIMIT 1").fetchone()[0]


class TestAcces(Base):
    URLS = ("/m/audit",) + PAGES + ("/m/audit/fiche?ref=0001", "/m/audit/export/journal?format=csv")
    POSTS = ("/m/audit/controles/journal", "/m/audit/controles/concordance")

    def test_non_connecte(self):
        c = self.app.test_client()
        for url in self.URLS:
            self.assertEqual(c.get(url).status_code, 302, url)
        for url in self.POSTS:
            self.assertEqual(c.post(url).status_code, 302, url)

    def test_sans_droit_refuse(self):
        for url in self.URLS:
            self.assertEqual(self.sec.get(url).status_code, 403, url)
        for url in self.POSTS:
            self.assertEqual(self.sec.post(url).status_code, 403, url)

    def test_lecture_suffit_et_administrateur_aussi(self):
        for client in (self.aud, self.admin):
            for url in PAGES:
                self.assertEqual(client.get(url).status_code, 200, url)

    def test_le_retrait_du_droit_est_immediat(self):
        self.assertEqual(self.aud.get("/m/audit/journal").status_code, 200)
        self.donner(self.id_aud, set())
        self.assertEqual(self.aud.get("/m/audit/journal").status_code, 403)
        self.assertEqual(self.aud.get("/m/audit/export/journal?format=csv").status_code, 403)

    def test_menu_et_module_en_ligne(self):
        self.assertIn("/m/audit", self.texte(self.admin.get("/menu")))
        self.assertNotIn("en cours de migration", self.texte(self.admin.get("/m/audit", follow_redirects=True)))
        self.assertIn("/m/audit", self.aud.get("/", follow_redirects=False).headers["Location"])      # son seul module : accès direct

    def test_ouverture_journalisee(self):
        avant = self.journal("AUDIT_OUVERT")
        self.assertEqual(self.aud.get("/m/audit").status_code, 302)
        self.assertEqual(self.journal("AUDIT_OUVERT"), avant + 1)
        self.aud.get("/m/audit/journal")                                  # changer d'onglet n'inscrit rien de plus
        self.assertEqual(self.journal("AUDIT_OUVERT"), avant + 1)

    def test_envois_d_un_autre_site_refuses(self):
        for url in self.POSTS:
            self.assertEqual(self.admin.post(url, headers=ETRANGER).status_code, 403, url)


class TestJournal(Base):
    def test_affichage_et_filtres(self):
        page = self.texte(self.aud.get("/m/audit/journal"))
        self.assertIn("ligne(s) trouvée(s)", page)
        self.assertIn("Connexion", page)
        page = self.texte(self.aud.get("/m/audit/journal?u=sec1"))
        self.assertIn("sec1", page)
        self.assertNotIn("<td>aud1", page)
        page = self.texte(self.aud.get("/m/audit/journal?fin=1"))
        self.assertIn("Enregistrement d'un paiement", page)
        self.assertIn("Aucune ligne trouvée", self.texte(self.aud.get("/m/audit/journal?texte=zzzintrouvablezzz")))

    def test_dates(self):
        self.assertEqual(self.aud.get("/m/audit/journal?du=2026-01-01&au=2099-12-31").status_code, 200)
        self.assertEqual(self.aud.get("/m/audit/journal?du=08/10/2026").status_code, 200)             # JJ/MM/AAAA aussi
        r = self.aud.get("/m/audit/journal?du=pas-une-date")
        self.assertEqual(r.status_code, 400)
        self.assertIn("La date « du » est invalide", self.texte(r))
        self.assertIn("Tous les utilisateurs", self.texte(r))                                          # la page reste utilisable
        r = self.aud.get("/m/audit/journal?du=2026-12-01&au=2026-01-01")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.aud.get("/m/audit/journal?cat=BIDON").status_code, 400)

    def test_resultats_sont_echappes(self):
        with self.conn:
            database.journaliser(self.conn, None, "x", "TEST", "<script>alert(1)</script>")
        brut = self.aud.get("/m/audit/journal?texte=alert").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", brut)


class TestFinances(Base):
    def test_historique_et_totaux(self):
        page = self.texte(self.aud.get("/m/audit/finances"))
        self.assertIn("opération(s) trouvée(s)", page)
        self.assertIn(self.un_recu(), page)
        self.assertIn("USD", page)

    def test_fiche_d_une_operation(self):
        n = self.un_recu()
        page = self.texte(self.aud.get(f"/m/audit/fiche?ref={n}&retour=/m/audit/finances?recu={n}"))
        self.assertIn(f"Reçu N° {n}", page)
        self.assertIn("Traces du journal", page)
        self.assertIn('href="/m/audit/finances?recu=', page)
        page = self.texte(self.aud.get(f"/m/audit/fiche?ref={n}&retour=https://pirate.example/"))     # adresse extérieure ignorée
        self.assertNotIn("pirate.example", page)
        self.assertEqual(self.aud.get("/m/audit/fiche?ref=INCONNU").status_code, 404)

    def test_recherche_ciblee_journalisee_et_filtres(self):
        avant = self.journal("AUDIT_RECHERCHE_TRACES") + self.journal("AUDIT_FINANCIER_CONSULTE")
        n = self.un_recu()
        self.assertEqual(self.aud.get(f"/m/audit/finances?recu={n}").status_code, 200)
        self.assertGreater(self.journal("AUDIT_RECHERCHE_TRACES") + self.journal("AUDIT_FINANCIER_CONSULTE"), avant)
        r = self.aud.get("/m/audit/finances?eleve=zzzzinconnuzzzz")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Aucun élève trouvé", self.texte(r))
        self.assertEqual(self.aud.get("/m/audit/finances?type=BIDON").status_code, 400)
        self.assertEqual(self.aud.get("/m/audit/finances?type=PAIEMENT&ecart=1").status_code, 200)


class TestControles(Base):
    def test_integrite(self):
        avant = self.journal("AUDIT_CONTROLE")
        page = self.texte(self.aud.post("/m/audit/controles/journal"))
        self.assertIn("La chaîne d'empreintes est intacte", page)
        self.assertIn("Dernière empreinte", page)
        self.assertEqual(self.journal("AUDIT_CONTROLE"), avant + 1)

    def test_integrite_alteree_signalee(self):
        self.conn.execute("DROP TRIGGER JOURNAL_NO_UPDATE")                       # fraude : on contourne le verrou
        self.conn.execute("UPDATE JOURNAL SET DETAIL = 'falsifié' WHERE ID_LOG = 3")
        self.conn.commit()
        self.assertIn("ANOMALIE", self.texte(self.aud.post("/m/audit/controles/journal")))

    def test_concordance(self):
        page = self.texte(self.aud.post("/m/audit/controles/concordance"))
        self.assertIn("Concordance entre le journal", page)
        self.assertTrue("Tout concorde" in page or "point(s) à vérifier" in page)
        self.sans_trace_des_paiements()                                                      # des reçus sans trace
        self.assertIn("aucune trace de son enregistrement", self.texte(self.aud.post("/m/audit/controles/concordance")))


class TestControleFinancier(Base):
    def test_attend_le_clic(self):
        avant = self.journal("AUDIT_CONTROLE_FINANCIER")
        self.assertIn("cliquez sur « Lancer le contrôle »", self.texte(self.aud.get("/m/audit/financier")))
        self.assertEqual(self.journal("AUDIT_CONTROLE_FINANCIER"), avant)

    def test_lancer(self):
        avant = self.journal("AUDIT_CONTROLE_FINANCIER")
        page = self.texte(self.aud.get("/m/audit/financier?lancer=1"))
        self.assertEqual(self.journal("AUDIT_CONTROLE_FINANCIER"), avant + 1)
        for titre in ("Anomalies", "Paiements et reçus", "Encaissé et remis", "Annulations", "Corrections", "Rapports journaliers imprimés"):
            self.assertIn(titre, page)
        self.assertIn("reçu(s) et", page)
        self.assertIn("/m/audit/rapports", page)

    def test_filtres_invalides(self):
        self.assertEqual(self.aud.get("/m/audit/financier?lancer=1&perc=999").status_code, 400)
        self.assertEqual(self.aud.get("/m/audit/financier?lancer=1&perc=abc").status_code, 400)
        self.assertEqual(self.aud.get("/m/audit/financier?lancer=1&devise=XXX").status_code, 400)
        self.assertEqual(self.aud.get("/m/audit/financier?lancer=1&du=nimporte").status_code, 400)
        self.assertEqual(self.aud.get("/m/audit/financier?lancer=1&devise=USD").status_code, 200)

    def test_anomalie_visible(self):
        self.sans_trace_des_paiements()
        page = self.texte(self.aud.get("/m/audit/financier?lancer=1"))
        self.assertIn("ÉLEVÉE", page)
        self.assertIn("Piste de vérification", page)


class TestRecherche(Base):
    def test_recherches(self):
        self.assertIn("trace(s) trouvée(s)", self.texte(self.aud.get("/m/audit/recherche")))
        n = self.un_recu()
        page = self.texte(self.aud.get(f"/m/audit/recherche?recu={n}"))
        self.assertIn("Paiement", page)
        self.assertIn(f"N° de reçu : {n}", page)
        self.assertIn("Connexion", self.texte(self.aud.get("/m/audit/recherche?module=connexion")))
        self.assertEqual(self.aud.get("/m/audit/recherche?module=bidon").status_code, 400)
        self.assertEqual(self.aud.get("/m/audit/recherche?action=BIDON").status_code, 400)
        r = self.aud.get("/m/audit/recherche?module=connexion&action=PAIEMENT_ENREGISTRE")
        self.assertEqual(r.status_code, 400)
        self.assertIn("ne fait pas partie du module", self.texte(r))

    def test_liste_des_actions_groupee_par_module(self):
        page = self.texte(self.aud.get("/m/audit/recherche"))
        self.assertIn("<optgroup", page)
        self.assertIn('value="PAIEMENT_ENREGISTRE"', page)


class TestRapports(Base):
    def test_consulter_chaque_type(self):
        self.assertIn("Choisissez un rapport", self.texte(self.aud.get("/m/audit/rapports")))
        for type_, titre in (("GENERAL", "Rapport général des opérations"), ("FINANCIER", "Rapport des opérations financières"),
                             ("ANOMALIES", "Rapport des anomalies financières"), ("COMPLET", "Rapport d'audit complet")):
            r = self.aud.get(f"/m/audit/rapports?consulter=1&type={type_}&detail=1")
            self.assertEqual(r.status_code, 200, type_)
            page = self.texte(r)
            self.assertIn(titre, page)
            self.assertIn("Synthèse", page)
            self.assertIn("Édité le", page)
        self.assertGreaterEqual(self.journal("AUDIT_RAPPORT_GENERE"), 4)

    def test_refus(self):
        self.assertEqual(self.aud.get("/m/audit/rapports?consulter=1&type=BIDON").status_code, 400)
        self.assertEqual(self.aud.get("/m/audit/rapports?consulter=1&perc=999").status_code, 400)


class TestExports(Base):
    def setUp(self):
        super().setUp()
        self.existants = self.dossier()                          # d'autres suites peuvent avoir laissé leurs propres exports

    def dossier(self):
        return sorted(glob.glob(str(config.DOSSIER_AUDIT / "*")))

    def telecharger(self, url, mime):
        avant = self.journal("AUDIT_EXPORTE")
        r = self.aud.get(url)
        self.assertEqual(r.status_code, 200, url)
        self.assertEqual(r.headers["Content-Type"], mime)
        self.assertIn("attachment", r.headers["Content-Disposition"])
        self.assertIn("no-store", r.headers["Cache-Control"])
        self.assertEqual(self.journal("AUDIT_EXPORTE"), avant + 1, url)
        self.assertEqual(self.dossier(), self.existants, "le fichier ne doit pas rester sur le serveur")
        return r.get_data()

    def test_csv_et_pdf_de_chaque_nature(self):
        n = self.un_recu()
        csv_ = "text/csv; charset=utf-8"
        corps = self.telecharger("/m/audit/export/journal?format=csv", csv_)
        self.assertTrue(corps.startswith(b"\xef\xbb\xbf"))                               # accents corrects dans Excel
        self.assertIn(b"Date et heure", corps)
        self.assertTrue(self.telecharger("/m/audit/export/journal?format=pdf", "application/pdf").startswith(b"%PDF"))
        self.telecharger("/m/audit/export/historique?format=csv", csv_)
        self.assertTrue(self.telecharger(f"/m/audit/export/historique?format=pdf&recu={n}", "application/pdf").startswith(b"%PDF"))
        self.telecharger("/m/audit/export/traces?format=csv&module=connexion", csv_)
        self.assertTrue(self.telecharger("/m/audit/export/traces?format=pdf", "application/pdf").startswith(b"%PDF"))
        self.telecharger("/m/audit/export/rapport?format=csv&type=COMPLET&detail=1", csv_)
        self.assertTrue(self.telecharger("/m/audit/export/rapport?format=pdf&type=FINANCIER", "application/pdf").startswith(b"%PDF"))

    def test_l_export_reprend_les_filtres(self):
        corps = self.telecharger("/m/audit/export/journal?format=csv&u=sec1", "text/csv; charset=utf-8").decode("utf-8-sig")
        lignes = corps.strip().splitlines()[1:]
        self.assertTrue(lignes)
        self.assertTrue(all(";sec1;" in l for l in lignes))

    def test_refus(self):
        for url, code in (("/m/audit/export/journal?format=xls", 400), ("/m/audit/export/journal", 400),
                          ("/m/audit/export/inconnu?format=csv", 404), ("/m/audit/export/journal?format=csv&du=nimporte", 400),
                          ("/m/audit/export/journal?format=csv&texte=zzzintrouvablezzz", 400),
                          ("/m/audit/export/rapport?format=csv&type=BIDON", 400)):
            self.assertEqual(self.aud.get(url).status_code, code, url)
        self.assertEqual(self.dossier(), self.existants)


if __name__ == "__main__":
    unittest.main()

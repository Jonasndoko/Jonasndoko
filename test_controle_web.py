"""Tests du module Contrôle numérique en ligne (web_controle.py) : droits, liste des élèves en ordre, cascade classe/option, PDF,
contrôle d'un élève (statuts), sections, journal.   Lancer :  python -m unittest test_controle_web"""
import os
import html
import re
import tempfile
import unittest
from urllib.parse import urlencode

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web         # noqa: E402
import database        # noqa: E402
import demo            # noqa: E402
import droits          # noqa: E402
import paiements       # noqa: E402
import security        # noqa: E402

AN = demo.ANNEE_COURANTE
MDP = "Tr@vail-Amour-2026"


class Base(unittest.TestCase):
    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "c.db")
        self.conn = database.connecter(self.chemin)
        self.login, self.mdp = demo.semer(self.conn)
        security.creer_utilisateur(self.conn, "admin1", "Alice Directrice", "ADMINISTRATEUR", MDP)
        security.creer_utilisateur(self.conn, "dir1", "Diane Études", "DIRECTRICE_ETUDES", MDP)
        self.id_dir = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN='dir1'").fetchone()[0]
        self.app = app_web.creer_app(self.chemin)
        self.admin, self.dir = self.app.test_client(), self.app.test_client()
        for c, l in ((self.admin, "admin1"), (self.dir, "dir1")):
            self.assertEqual(c.post("/connexion", data={"login": l, "mdp": MDP}).status_code, 302)

    def droits_dir(self, *liste):
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_dir, {("controle", d) for d in liste})

    def liste(self, client=None, **p):
        base = dict(annee=AN, classe="8ème A", frais="INSC")
        base.update(p)
        return (client or self.admin).get("/m/controle?" + urlencode(base))

    def texte(self, r):
        return html.unescape(r.get_data(as_text=True))

    def journal(self, action):
        return self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE ACTION = ?", (action,)).fetchone()[0]


class TestAcces(Base):
    def test_non_connecte(self):
        for url in ("/m/controle", "/m/controle/eleve", "/m/controle/eleve/CSF-0001", "/m/controle/liste/pdf"):
            self.assertEqual(self.app.test_client().get(url).status_code, 302, url)

    def test_sans_droit_403(self):
        self.droits_dir()
        for url in ("/m/controle", "/m/controle/eleve", "/m/controle/eleve/CSF-0001", "/m/controle/liste/pdf?annee=x"):
            self.assertEqual(self.dir.get(url).status_code, 403, url)

    def test_lecture_suffit(self):
        self.droits_dir("LECTURE")
        self.assertEqual(self.liste(self.dir).status_code, 200)

    def test_menu_marque_le_module_en_ligne(self):
        page = self.texte(self.admin.get("/menu"))
        tuile = re.search(r'<a class="entree" href="/m/controle"[^>]*>(.*?)</a>', page, re.S).group(1)
        self.assertNotIn("bientôt", tuile)


class TestListe(Base):
    def test_page_vide_invite_a_choisir(self):
        t = self.texte(self.admin.get("/m/controle?annee=&classe=&frais="))
        self.assertIn("Choisissez l'année scolaire, la classe et le type de frais.", t)
        self.assertEqual(self.journal("LISTE_EN_ORDRE_CONSULTEE"), 0)

    def test_annee_courante_preselectionnee(self):
        self.assertRegex(self.texte(self.admin.get("/m/controle")), rf'<option value="{AN}" selected>')

    def test_liste_des_eleves_en_ordre(self):
        t = self.texte(self.liste())
        self.assertIn("LISTE DES ELEVES EN ORDRE AVEC LE FRAIS FRAIS D'INSCRIPTION", t)
        self.assertIn("MBUYI KALALA Jean-Pierre", t)
        self.assertIn("1 élève(s) en ordre sur", t)
        self.assertIn("Imprimer (PDF)", t)
        self.assertEqual(self.journal("LISTE_EN_ORDRE_CONSULTEE"), 1)

    def test_aucun_en_ordre(self):
        t = self.texte(self.liste(frais="MIN1"))
        self.assertIn("Aucun élève en ordre pour ce frais.", t)
        self.assertNotIn("Imprimer (PDF)", t)

    def test_option_choisie_d_office_et_cascade(self):
        t = self.liste(classe="4ème Commerciale et Gestion")           # une seule option : choisie d'office
        self.assertIn("OPTION : Commerciale et Gestion", self.texte(t))
        self.assertIn("KABONGO TSHIALA Émile", self.texte(t))
        self.assertIn("Option (humanités)", self.texte(t))
        t = self.admin.get("/m/controle?" + urlencode(dict(annee=AN, classe="7ème A", option="COM", frais="INSC")))   # option étrangère ignorée
        self.assertNotIn("OPTION :", self.texte(t))

    def test_valeurs_inventees_ignorees(self):
        t = self.texte(self.liste(classe="<script>x</script>"))
        self.assertNotIn("<script>x", t)
        self.assertIn("Choisissez", t)
        self.assertIn("Choisissez", self.texte(self.liste(frais="INCONNU")))

    def test_sans_tarif(self):
        with self.conn:
            self.conn.execute("DELETE FROM TARIF WHERE CODTF='EXAM' AND N_CLASSE=1 AND ANNEESCO=?", (AN,))
            self.conn.execute("UPDATE TYPE_FRAIS SET MONTANT = NULL, CODE_DEVISE = NULL WHERE CODTF = 'EXAM'")
        self.assertIn("Aucun tarif n'est défini", self.texte(self.liste(classe="7ème A", frais="EXAM")))

    def test_pdf(self):
        r = self.admin.get("/m/controle/liste/pdf?" + urlencode(dict(annee=AN, classe="8ème A", frais="INSC")))
        self.assertEqual((r.status_code, r.headers["Content-Type"]), (200, "application/pdf"))
        self.assertTrue(r.data.startswith(b"%PDF"))
        self.assertEqual(self.journal("LISTE_EN_ORDRE_IMPRIMEE"), 1)

    def test_pdf_liste_vide_et_choix_incomplets(self):
        r = self.admin.get("/m/controle/liste/pdf?" + urlencode(dict(annee=AN, classe="8ème A", frais="MIN1")))
        self.assertEqual(r.status_code, 400)
        self.assertIn("rien à imprimer", r.get_data(as_text=True))
        self.assertEqual(self.admin.get("/m/controle/liste/pdf").status_code, 400)

    def test_sections_fermees(self):
        with self.conn:
            self.conn.execute("UPDATE NIVEAU SET SECTION = 'PRIMAIRE' WHERE CODE_NIVEAU = 'N8'")
            self.conn.execute("INSERT INTO SECTION_UTILISATEUR (ID_USER, SECTION) VALUES (?, 'SECONDAIRE')", (self.id_dir,))
        self.droits_dir("LECTURE")
        t = self.texte(self.liste(self.dir))               # 8ème A est désormais au primaire : fermée à ce compte
        self.assertNotIn("MBUYI", t)
        self.assertIn("Choisissez", t)


class TestControleEleve(Base):
    def test_recherche_vers_fiche(self):
        r = self.admin.get("/m/controle/eleve?q=mbuyi")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/m/controle/eleve/CSF-0001", r.headers["Location"])
        t = self.texte(self.admin.get("/m/controle/eleve?q=a"))
        self.assertIn("au moins 2", t)
        self.assertIn("Aucun élève", self.texte(self.admin.get("/m/controle/eleve?q=zzzzzz")))

    def test_impaye(self):
        t = self.texte(self.admin.get("/m/controle/eleve/CSF-0001"))
        self.assertIn('class="statut impaye"', t)
        self.assertIn("IMPAYÉ", t)
        self.assertIn("Reste à payer :", t)
        self.assertEqual(self.journal("CONTROLE_NUMERIQUE"), 1)

    def test_en_ordre(self):
        perc = security.authentifier(self.conn, self.login, self.mdp).session
        for codtf, c in (("MIN1", 4500), ("MIN2", 9000), ("EXAM", 1500)):
            paiements.enregistrer_paiement(self.conn, perc, "CSF-0001", AN, codtf, c)
        t = self.texte(self.admin.get("/m/controle/eleve/CSF-0001"))
        self.assertIn('class="statut ordre"', t)
        self.assertIn("EN ORDRE", t)

    def test_non_inscrit(self):
        with self.conn:
            self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('CSF-0099', 'ZEBRE')")
        t = self.texte(self.admin.get("/m/controle/eleve/CSF-0099"))
        self.assertIn("NON INSCRIT", t)
        self.assertIn('class="statut noninscrit"', t)

    def test_inconnu_404(self):
        self.assertEqual(self.admin.get("/m/controle/eleve/XXX").status_code, 404)

    def test_section_fermee_403(self):
        with self.conn:
            self.conn.execute("UPDATE NIVEAU SET SECTION = 'PRIMAIRE' WHERE CODE_NIVEAU = 'N8'")
            self.conn.execute("INSERT INTO SECTION_UTILISATEUR (ID_USER, SECTION) VALUES (?, 'SECONDAIRE')", (self.id_dir,))
        self.droits_dir("LECTURE")
        self.assertEqual(self.dir.get("/m/controle/eleve/CSF-0001").status_code, 403)


if __name__ == "__main__":
    unittest.main()

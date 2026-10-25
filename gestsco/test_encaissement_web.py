"""Tests du module Encaissement en ligne (web_encaissement.py) : droits, enregistrement avec confirmation, écart, double clic,
erreurs, rapport global et PDF.
Lancer :  python -m unittest test_encaissement_web"""
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web        # noqa: E402
import database       # noqa: E402
import demo           # noqa: E402
import droits         # noqa: E402
import security       # noqa: E402

MDP = "Tr@vail-Amour-2026"


def aujourdhui():
    return datetime.now().strftime("%d/%m/%Y")


class Base(unittest.TestCase):
    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "e.db")
        self.conn = database.connecter(self.chemin)
        self.login, self.mdp = demo.semer(self.conn)
        security.creer_utilisateur(self.conn, "admin1", "Alice Directrice", "ADMINISTRATEUR", MDP)
        security.creer_utilisateur(self.conn, "sec1", "Marie Kabila", "SECRETAIRE", MDP)
        self.app = app_web.creer_app(self.chemin)
        self.admin, self.sec = self.app.test_client(), self.app.test_client()
        self.entrer(self.admin, "admin1", MDP)
        self.entrer(self.sec, "sec1", MDP)
        self.n_perc = self.conn.execute("SELECT N_PERC FROM PERCEPTEUR LIMIT 1").fetchone()[0]
        self.devise = self.conn.execute("SELECT CODE_DEVISE FROM DEVISE WHERE ACTIF = 1 ORDER BY CODE_DEVISE LIMIT 1").fetchone()[0]

    def entrer(self, client, login, mdp):
        self.assertEqual(client.post("/connexion", data={"login": login, "mdp": mdp}).status_code, 302)

    def texte(self, r):
        return r.get_data(as_text=True)

    def nb(self):
        return self.conn.execute("SELECT COUNT(*) FROM ENCAISSEMENT").fetchone()[0]

    def donnees(self, **plus):
        d = {"perc": str(self.n_perc), "devise": self.devise, "date": aujourdhui(), "encaisse": "1 250,50", "verse": "1 000"}
        d.update(plus)
        return d

    def accorder(self, login, *droits_):
        """Donne à un compte les droits indiqués sur le module encaissement."""
        id_user = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = ?", (login,)).fetchone()[0]
        with self.conn:
            for d in droits_:
                self.conn.execute("INSERT OR IGNORE INTO DROIT (ID_USER, MODULE, DROIT) VALUES (?,?,?)",
                                  (id_user, "encaissement", d))


class TestAcces(Base):
    def test_non_connecte(self):
        for url in ("/m/encaissement", "/m/encaissement/rapport", "/m/encaissement/rapport/pdf?date=" + aujourdhui()):
            self.assertEqual(self.app.test_client().get(url).status_code, 302, url)

    def test_compte_sans_droit_refuse(self):
        for url in ("/m/encaissement", "/m/encaissement/rapport"):
            self.assertEqual(self.sec.get(url).status_code, 403, url)
        self.assertEqual(self.sec.post("/m/encaissement/enregistrer", data=self.donnees()).status_code, 403)
        self.assertEqual(self.nb(), 0)

    def test_menu_indique_que_le_module_est_en_ligne(self):
        page = self.texte(self.admin.get("/menu"))
        tuile = re.search(r'<a class="entree" href="/m/encaissement"[^>]*>(.*?)</a>', page, re.S).group(1)
        self.assertNotIn("bientôt en ligne", tuile)

    def test_origine_etrangere_refusee(self):
        r = self.admin.post("/m/encaissement/enregistrer", data=self.donnees(), headers={"Origin": "https://pirate.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.nb(), 0)

    def test_lecture_seule_voit_le_rapport_pas_l_enregistrement(self):
        self.accorder("sec1", "LECTURE")
        r = self.sec.get("/m/encaissement")                                   # arrive directement sur le rapport
        self.assertEqual(r.status_code, 302)
        self.assertIn("/m/encaissement/rapport", r.headers["Location"])
        self.assertEqual(self.sec.get("/m/encaissement/rapport").status_code, 200)
        self.assertIn("(réservé)", self.texte(self.sec.get("/m/encaissement/rapport")))
        for etape in ("confirmer", "enregistrer"):
            self.assertEqual(self.sec.post(f"/m/encaissement/{etape}", data=self.donnees()).status_code, 403)
        self.assertEqual(self.nb(), 0)

    def test_ajout_sans_lecture_refuse(self):
        self.accorder("sec1", "AJOUT")                                         # comme dans le logiciel : sans Lecture, pas d'accès
        self.assertEqual(self.sec.get("/m/encaissement").status_code, 403)


class TestEnregistrement(Base):
    def test_formulaire(self):
        page = self.texte(self.admin.get("/m/encaissement"))
        self.assertIn("Enregistrement de l&#39;encaissement", page)
        self.assertIn(f'value="{self.n_perc}"', page)
        self.assertIn(self.devise, page)
        self.assertIn(aujourdhui(), page)

    def test_confirmation_n_enregistre_rien_et_calcule_l_ecart(self):
        r = self.admin.post("/m/encaissement/confirmer", data=self.donnees())
        self.assertEqual(r.status_code, 200)
        page = self.texte(r)
        self.assertIn("Confirmer l'encaissement", page)
        self.assertIn("250,50", page)                                          # écart = 1 250,50 - 1 000
        self.assertIn("Manquant", page)
        self.assertEqual(self.nb(), 0)

    def test_enregistrement_complet(self):
        r = self.admin.post("/m/encaissement/enregistrer", data=self.donnees())
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.nb(), 1)
        l = self.conn.execute("SELECT * FROM ENCAISSEMENT").fetchone()
        self.assertEqual((l["MONT_ENCAISSE"], l["MONT_VERSE"], l["ECART"]), (125050, 100000, 25050))
        self.assertEqual(l["SAISI_PAR"], "admin1")
        self.assertIn(f"Encaissement N° {l['N_ENC']} enregistré", self.texte(self.admin.get(r.headers["Location"])))
        self.assertIn("ENCAISSEMENT_ENREGISTRE", [x[0] for x in self.conn.execute("SELECT ACTION FROM JOURNAL")])

    def test_excedent_et_versement_nul(self):
        self.admin.post("/m/encaissement/enregistrer", data=self.donnees(encaisse="10", verse="12,5"))
        self.assertEqual(self.conn.execute("SELECT ECART FROM ENCAISSEMENT").fetchone()[0], -250)
        self.admin.post("/m/encaissement/enregistrer", data=self.donnees(encaisse="10", verse="0"))   # rien versé : permis
        self.assertEqual(self.nb(), 2)

    def test_double_clic_ne_cree_pas_deux_encaissements(self):
        r1 = self.admin.post("/m/encaissement/enregistrer", data=self.donnees())
        r2 = self.admin.post("/m/encaissement/enregistrer", data=self.donnees())
        self.assertEqual(self.nb(), 1)
        self.assertEqual(r2.status_code, 302)
        self.assertIn("deja=1", r2.headers["Location"])
        self.assertIn("aucun doublon", self.texte(self.admin.get(r2.headers["Location"])))
        self.assertEqual(r1.headers["Location"].split("ok=")[1].split("&")[0], r2.headers["Location"].split("ok=")[1].split("&")[0])

    def test_meme_saisie_apres_le_delai_est_acceptee(self):
        self.admin.post("/m/encaissement/enregistrer", data=self.donnees())
        vieux = (datetime.now() - timedelta(minutes=5)).astimezone().astimezone(__import__("datetime").timezone.utc)
        with self.conn:
            self.conn.execute("UPDATE ENCAISSEMENT SET DATE_SAISIE = ?", (database.iso(vieux),))
        self.admin.post("/m/encaissement/enregistrer", data=self.donnees())
        self.assertEqual(self.nb(), 2)

    def test_erreurs_affichees_et_rien_enregistre(self):
        demain = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
        cas = [(dict(perc=""), "Choisissez un percepteur"), (dict(perc="99999"), "Choisissez un percepteur"),
               (dict(encaisse=""), "Saisissez le montant encaissé"), (dict(encaisse="abc"), "invalide"),
               (dict(encaisse="0"), "supérieur à zéro"), (dict(devise=""), "Choisissez la devise"),
               (dict(devise="ZZZ"), "Choisissez la devise"), (dict(verse=""), "Saisissez le montant versé"),
               (dict(verse="-5"), "invalide"), (dict(date="31/02/2026"), "Date invalide"), (dict(date=demain), "futur")]
        for plus, attendu in cas:
            for etape in ("confirmer", "enregistrer"):
                r = self.admin.post(f"/m/encaissement/{etape}", data=self.donnees(**plus))
                self.assertEqual(r.status_code, 400, (plus, etape))
                self.assertIn(attendu, self.texte(r), (plus, etape))
        self.assertEqual(self.nb(), 0)

    def test_saisie_conservee_en_cas_d_erreur(self):
        page = self.texte(self.admin.post("/m/encaissement/enregistrer", data=self.donnees(verse="abc")))
        self.assertIn('value="1 250,50"', page)

    def test_message_succes_non_falsifiable(self):
        self.assertNotIn("enregistré.", self.texte(self.admin.get("/m/encaissement?ok=999")))
        self.assertNotIn("alert(1)", self.texte(self.admin.get("/m/encaissement?ok=<script>alert(1)</script>")))

    def test_percepteur_desactive_refuse(self):
        with self.conn:
            self.conn.execute("UPDATE UTILISATEUR SET ACTIF = 0 WHERE ID_USER = (SELECT ID_USER FROM PERCEPTEUR WHERE N_PERC = ?)",
                              (self.n_perc,))
        r = self.admin.post("/m/encaissement/enregistrer", data=self.donnees())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.nb(), 0)


class TestRapport(Base):
    def test_rapport_vide(self):
        page = self.texte(self.admin.get("/m/encaissement/rapport?date=01/01/2020"))
        self.assertIn("Aucun paiement ni encaissement", page)
        self.assertNotIn("Imprimer le rapport", page)

    def test_date_invalide(self):
        r = self.admin.get("/m/encaissement/rapport?date=n-importe-quoi")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Date invalide", self.texte(r))

    def test_rapport_avec_encaissement_et_pdf(self):
        self.admin.post("/m/encaissement/enregistrer", data=self.donnees())
        page = self.texte(self.admin.get(f"/m/encaissement/rapport?date={aujourdhui()}"))
        self.assertIn("1 encaissement(s)", page)
        self.assertIn("1 250,50", page)
        self.assertIn("Manquant", page)
        self.assertIn("Imprimer le rapport", page)
        r = self.admin.get(f"/m/encaissement/rapport/pdf?date={aujourdhui()}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Content-Type"], "application/pdf")
        self.assertTrue(r.data.startswith(b"%PDF"))
        self.assertIn("RAPPORT_GLOBAL_IMPRIME", [x[0] for x in self.conn.execute("SELECT ACTION FROM JOURNAL")])

    def test_pdf_vide_refuse_poliment(self):
        r = self.admin.get("/m/encaissement/rapport/pdf?date=01/01/2020")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Rien à imprimer", self.texte(r))

    def test_rapport_compte_les_paiements_des_percepteurs(self):
        # les reçus de démonstration datés d'aujourd'hui apparaissent par type de frais ; sinon le rapport ne montre que les versements
        page = self.texte(self.admin.get(f"/m/encaissement/rapport?date={aujourdhui()}"))
        n = self.conn.execute("SELECT COUNT(*) FROM PAIEMENT WHERE STATUT='VALIDE'").fetchone()[0]
        if n:
            self.assertIn("TYPE DE FRAIS", page)


if __name__ == "__main__":
    unittest.main()

"""Tests du Secrétariat > Bulletins scolaires : consulter, imprimer et archiver les bulletins validés par la Préfecture, par classe, période et option.
Lancer :  python -m unittest test_bulletins_secretariat"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web                  # noqa: E402
import bulletins_secretariat as bs   # noqa: E402
import proclamation             # noqa: E402
import security                 # noqa: E402
from bulletins_secretariat import ErreurBulletinsSecretariat   # noqa: E402
from test_notes import MDP                                     # noqa: E402
from test_proclamation import Base                             # noqa: E402


def journal(conn, action):
    return [l["DETAIL"] for l in conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = ? ORDER BY ID_LOG", (action,))]


class Fix(Base):
    def setUp(self):
        super().setUp()
        self.vus = None

    def confirmer(self):
        self.circuit_jusqu_a_la_confirmation()          # 0000 en ordre (tranche 2) : seul bulletin validé

    def archiver(self, session=None):
        return bs.archiver(self.conn, session or self.secr, self.annee, self.c7, self.cle)


class TestRegle(Fix):
    def test_rien_tant_que_le_prefet_n_a_pas_confirme(self):
        self.assertEqual(bs.liste(self.conn, self.secr, self.annee)["lignes"], [])
        self.autoriser()
        self.criteres(("SCO", 2))
        proclamation.valider(self.conn, self.dire, self.annee, self.c7, self.cle)
        proclamation.soumettre(self.conn, self.dire, self.annee, self.c7, self.cle)          # soumise, pas confirmée
        self.assertEqual(bs.liste(self.conn, self.secr, self.annee)["lignes"], [])
        for f in (lambda: bs.detail(self.conn, self.secr, self.annee, self.c7, self.cle),
                  lambda: bs.document_pdf(self.conn, self.secr, self.annee, self.c7, self.cle), self.archiver):
            with self.assertRaises(ErreurBulletinsSecretariat):
                f()

    def test_seuls_les_bulletins_valides_apparaissent(self):
        self.confirmer()
        r = bs.liste(self.conn, self.secr, self.annee)
        self.assertEqual([(l["classe"], l["valides"]) for l in r["lignes"]], [("7ème A", 1)])
        d = bs.detail(self.conn, self.secr, self.annee, self.c7, self.cle)
        self.assertEqual([e["matricule"] for e in d["eleves"]], ["0000/26"])
        self.assertEqual(d["effectif"], 3)

    def test_une_validation_retiree_par_le_prefet_disparait(self):
        self.confirmer()
        with self.conn:
            self.conn.execute("UPDATE VALIDATION_BULLETIN SET VALIDE = 0 WHERE MATRICULE = '0000/26'")
        self.assertEqual(bs.liste(self.conn, self.secr, self.annee)["lignes"], [])

    def test_filtres_classe_periode_option(self):
        self.confirmer()
        a = self.annee
        self.assertEqual(len(bs.liste(self.conn, self.secr, a, self.c7)["lignes"]), 1)
        self.assertEqual(bs.liste(self.conn, self.secr, a, self.c8)["lignes"], [])
        self.assertEqual(len(bs.liste(self.conn, self.secr, a, None, self.cle)["lignes"]), 1)
        self.assertEqual(bs.liste(self.conn, self.secr, a, None, "A")["lignes"], [])
        self.assertEqual(len(bs.liste(self.conn, self.secr, a, None, "", bs.SANS_OPTION)["lignes"]), 1)
        niveau = self.conn.execute("SELECT CODE_NIVEAU FROM CLASSE WHERE N_CLASSE = ?", (self.c7,)).fetchone()[0]
        with self.conn:
            self.conn.execute("INSERT INTO OPTION_SCO (CODE_OPTION, DESI_OPTION) VALUES ('BIO', 'Biochimie')")
            self.conn.execute("INSERT INTO POSSEDE (CODE_NIVEAU, CODE_OPTION) VALUES (?, 'BIO')", (niveau,))
            self.conn.execute("UPDATE CLASSE SET CODE_OPTION = 'BIO' WHERE N_CLASSE = ?", (self.c7,))
        self.assertEqual(len(bs.liste(self.conn, self.secr, a, None, "", "BIO")["lignes"]), 1)
        self.assertEqual(bs.liste(self.conn, self.secr, a, None, "", bs.SANS_OPTION)["lignes"], [])
        self.assertEqual(bs.liste(self.conn, self.secr, a, None, "", "AUTRE")["lignes"], [])
        f = bs.filtres(self.conn, self.secr, a)
        self.assertEqual(f["options"], [("BIO", "Biochimie")])
        self.assertEqual(bs.liste(self.conn, self.secr, a)["lignes"][0]["option"], "Biochimie")

    def test_le_primaire_est_exclu(self):
        self.confirmer()
        with self.assertRaises(ErreurBulletinsSecretariat):
            bs.detail(self.conn, self.secr, self.annee, self.cp, self.cle)


class TestImpression(Fix):
    def test_pdf_des_bulletins_valides(self):
        self.confirmer()
        octets, nom = bs.document_pdf(self.conn, self.secr, self.annee, self.c7, self.cle)
        self.assertTrue(octets.startswith(b"%PDF"))
        self.assertTrue(nom.endswith(".pdf"))
        octets, nom = bs.document_pdf(self.conn, self.secr, self.annee, self.c7, self.cle, "0000/26")
        self.assertTrue(octets.startswith(b"%PDF"))
        self.assertEqual(len(journal(self.conn, "BULLETINS_SECRETARIAT_IMPRIMES")), 2)

    def test_un_eleve_non_valide_ne_s_imprime_pas(self):
        self.confirmer()
        with self.assertRaises(ErreurBulletinsSecretariat):
            bs.document_pdf(self.conn, self.secr, self.annee, self.c7, self.cle, "0001/26")


class TestArchive(Fix):
    def test_archiver_et_rouvrir(self):
        self.confirmer()
        r = self.archiver()
        self.assertEqual((r["version"], r["nb_bulletins"]), (1, 1))
        octets, nom = bs.archive_pdf(self.conn, self.secr, r["id"])
        self.assertTrue(octets.startswith(b"%PDF"))
        self.assertIn("archive_v1", nom)
        self.assertEqual(self.archiver()["version"], 2)                       # une nouvelle copie, l'ancienne reste
        a = bs.archives(self.conn, self.secr, self.annee, self.c7, self.cle)
        self.assertEqual([x["classe"] for x in a], ["7ème A", "7ème A"])
        self.assertEqual(a[0]["par"], "secr1")
        self.assertEqual(bs.liste(self.conn, self.secr, self.annee)["lignes"][0]["archives"], 2)
        self.assertEqual(len(journal(self.conn, "BULLETINS_ARCHIVES")), 2)

    def test_la_copie_archivee_ne_change_pas(self):
        self.confirmer()
        r = self.archiver()
        avant = bs.archive_pdf(self.conn, self.secr, r["id"])[0]
        with self.conn:
            self.conn.execute("UPDATE VALIDATION_BULLETIN SET VALIDE = 0")
        self.assertEqual(bs.archive_pdf(self.conn, self.secr, r["id"])[0], avant)

    def test_archive_inconnue(self):
        with self.assertRaises(ErreurBulletinsSecretariat):
            bs.archive_pdf(self.conn, self.secr, 999)


class TestDroits(Fix):
    def test_seule_la_secretaire_et_l_admin_et_selon_le_droit(self):
        self.confirmer()
        for s in (self.prefet, self.dird):
            with self.assertRaises(PermissionError):
                bs.liste(self.conn, s, self.annee)
        self.assertEqual(len(bs.liste(self.conn, self.admin, self.annee)["lignes"]), 1)

    def test_archiver_exige_la_modification(self):
        self.confirmer()
        u = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = 'secr1'").fetchone()[0]
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'dossier_eleve' AND DROIT = 'MODIFICATION'", (u,))
        self.assertTrue(bs.liste(self.conn, self.secr, self.annee)["lignes"])           # lecture toujours possible
        with self.assertRaises(PermissionError):
            self.archiver()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ARCHIVE_BULLETIN").fetchone()[0], 0)


class TestWeb(Fix):
    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])
        self.cl = self.app.test_client()
        self.assertEqual(self.cl.post("/connexion", data={"login": "secr1", "mdp": MDP}).status_code, 302)
        self.base = "/m/etudes_discipline/dossier_eleve"

    def test_onglet_et_liste(self):
        self.confirmer()
        page = self.cl.get(self.base).get_data(as_text=True)
        self.assertIn("Bulletins scolaires", page)
        page = self.cl.get(self.base + "?f=bulletins").get_data(as_text=True)
        self.assertIn("7ème A", page)
        self.assertIn("validés par la Préfecture", page)

    def test_liste_vide_avant_confirmation(self):
        page = self.cl.get(self.base + "?f=bulletins").get_data(as_text=True)
        self.assertIn("Aucun bulletin validé par la Préfecture", page)

    def test_detail_pdf_et_archivage(self):
        self.confirmer()
        q = f"?f=bulletins&annee={self.annee}&classe={self.c7}&cle={self.cle}"
        page = self.cl.get(self.base + q).get_data(as_text=True)
        self.assertIn("0000/26", page)
        self.assertNotIn("0001/26", page)
        r = self.cl.get(f"{self.base}/bulletins/bulletin.pdf?annee={self.annee}&classe={self.c7}&cle={self.cle}")
        self.assertEqual((r.status_code, r.mimetype), (200, "application/pdf"))
        self.assertEqual(self.cl.get(f"{self.base}/bulletins/bulletin.pdf?annee={self.annee}&classe={self.c7}&cle={self.cle}&eleve=0001/26").status_code, 404)
        r = self.cl.post(self.base + "/bulletins/archiver", data={"annee": self.annee, "classe": self.c7, "cle": self.cle})
        self.assertEqual(r.status_code, 302)
        self.assertIn("Bulletins archivés", self.cl.get(r.headers["Location"]).get_data(as_text=True))
        page = self.cl.get(self.base + "?f=bulletins&vue=archives").get_data(as_text=True)
        self.assertIn("archive_v1", page)
        idl = self.conn.execute("SELECT ID_ARCHIVE FROM ARCHIVE_BULLETIN").fetchone()[0]
        r = self.cl.get(f"{self.base}/bulletins/archive/{idl}.pdf")
        self.assertEqual((r.status_code, r.mimetype), (200, "application/pdf"))

    def test_archiver_avant_confirmation_est_refuse(self):
        r = self.cl.post(self.base + "/bulletins/archiver", data={"annee": self.annee, "classe": self.c7, "cle": self.cle})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ARCHIVE_BULLETIN").fetchone()[0], 0)

    def test_un_autre_poste_n_a_pas_acces(self):
        self.confirmer()
        cl = self.app.test_client()
        self.assertEqual(cl.post("/connexion", data={"login": "dird1", "mdp": MDP}).status_code, 302)
        self.assertEqual(cl.get(f"{self.base}/bulletins/bulletin.pdf?annee={self.annee}&classe={self.c7}&cle={self.cle}").status_code, 403)
        self.assertEqual(cl.post(self.base + "/bulletins/archiver", data={"annee": self.annee, "classe": self.c7, "cle": self.cle}).status_code, 403)


if __name__ == "__main__":
    unittest.main()

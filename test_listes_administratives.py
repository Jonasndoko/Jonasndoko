"""Tests du Secrétariat > Listes et rapports administratifs : listes d'élèves par classe, option et année, dossiers incomplets, PDF et CSV.
Lancer :  python -m unittest test_listes_administratives"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web                    # noqa: E402
import audit                      # noqa: E402
import config                     # noqa: E402
import droits                     # noqa: E402
import listes_administratives as la   # noqa: E402
import secretariat                # noqa: E402
import security                   # noqa: E402
from listes_administratives import ErreurListes   # noqa: E402
from test_notes import MDP                        # noqa: E402
from test_prefecture_v57 import Fixture           # noqa: E402


def journal(conn, action):
    return [l["DETAIL"] for l in conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = ? ORDER BY ID_LOG", (action,))]


def matricules(r):
    return [e["matricule"] for k in r["classes"] for e in k["eleves"]]


class Fix(Fixture):
    def setUp(self):
        super().setUp()
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET SEXE = 'F' WHERE MATRICULE = '0002/26'")
            self.conn.execute("UPDATE ELEVE SET NOM_TUTEUR = 'Mme Mbuyi', TEL_TUTEUR = '0810000000' WHERE MATRICULE = '0001/26'")
            self.conn.execute("INSERT INTO OPTION_SCO (CODE_OPTION, DESI_OPTION) VALUES ('SCI', 'Scientifique')")
            self.conn.execute("INSERT INTO POSSEDE (CODE_NIVEAU, CODE_OPTION) VALUES ('SEC', 'SCI')")
            self.conn.execute("UPDATE CLASSE SET CODE_OPTION = 'SCI' WHERE N_CLASSE = ?", (self.c8,))

    def completer(self, *mats):
        for m in mats:
            secretariat.definir_etat(self.conn, self.secr, m, True)


class TestListes(Fix):
    def test_liste_des_eleves_par_classe_sans_le_primaire(self):
        r = la.liste(self.conn, self.secr)
        self.assertEqual(r["annee"], self.annee)
        self.assertEqual([k["classe"] for k in r["classes"]], ["7ème A", "8ème A"])
        self.assertEqual(sorted(matricules(r)), ["0000/26", "0001/26", "0002/26", "0009/26"])   # 0100/26 (primaire) n'apparaît jamais
        k7 = r["classes"][0]
        self.assertEqual((k7["total"], k7["garcons"], k7["filles"]), (3, 2, 1))
        self.assertEqual([e["n"] for e in k7["eleves"]], [1, 2, 3])
        noms = [e["nom_complet"] for e in k7["eleves"]]
        self.assertEqual(noms, sorted(noms, key=str.lower))
        self.assertEqual(r["resume"]["total"], 4)

    def test_filtre_classe_et_option(self):
        r = la.liste(self.conn, self.secr, n_classe=self.c8)
        self.assertEqual(matricules(r), ["0009/26"])
        self.assertEqual(r["classes"][0]["option"], "Scientifique")
        self.assertEqual(matricules(la.liste(self.conn, self.secr, option="SCI")), ["0009/26"])
        self.assertEqual(sorted(matricules(la.liste(self.conn, self.secr, option="-"))), ["0000/26", "0001/26", "0002/26"])
        self.assertEqual(matricules(la.liste(self.conn, self.secr, option="INCONNUE")), [])

    def test_filtre_annee(self):
        self.assertEqual(la.liste(self.conn, self.secr, annee="2019-2020")["resume"]["total"], 0)
        with self.conn:
            self.conn.execute("INSERT INTO ANNEE_SCO (ANNEESCO, EN_COURS) VALUES ('2025-2026', 0)")
            self.conn.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES ('2025-2026', '0000/26', ?)", (self.c7,))
        self.assertEqual(matricules(la.liste(self.conn, self.secr, annee="2025-2026")), ["0000/26"])
        self.assertEqual(la.annees(self.conn, self.secr), [self.annee, "2025-2026"])

    def test_desactives_exclus_sauf_demande(self):
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET ACTIF = 0 WHERE MATRICULE = '0002/26'")
        self.assertNotIn("0002/26", matricules(la.liste(self.conn, self.secr)))
        r = la.liste(self.conn, self.secr, desactives=True)
        self.assertIn("0002/26", matricules(r))
        self.assertTrue([e for k in r["classes"] for e in k["eleves"] if e["matricule"] == "0002/26"][0]["desactive"])

    def test_dossiers_incomplets(self):
        self.completer("0000/26", "0009/26")
        r = la.liste(self.conn, self.secr, "incomplets")
        self.assertEqual(sorted(matricules(r)), ["0001/26", "0002/26"])
        self.assertEqual(r["resume"]["total"], 2)
        e = r["classes"][0]["eleves"][0]
        self.assertTrue(any(x["tuteur"] == "Mme Mbuyi" for x in r["classes"][0]["eleves"]))
        self.assertFalse(e["complet"])
        self.assertEqual(matricules(la.liste(self.conn, self.secr, "incomplets", n_classe=self.c8)), [])    # 0009 est complet
        # remettre à incomplet le fait réapparaître ; un élève désactivé n'y figure jamais
        secretariat.definir_etat(self.conn, self.secr, "0009/26", False)
        self.assertEqual(matricules(la.liste(self.conn, self.secr, "incomplets", n_classe=self.c8)), ["0009/26"])
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET ACTIF = 0 WHERE MATRICULE = '0009/26'")
        self.assertEqual(matricules(la.liste(self.conn, self.secr, "incomplets", n_classe=self.c8, desactives=True)), [])

    def test_genre_inconnu_donne_la_liste_des_eleves(self):
        self.assertEqual(la.liste(self.conn, self.secr, "n_importe_quoi")["genre"], "eleves")

    def test_resume_complets_incomplets(self):
        self.completer("0000/26")
        r = la.liste(self.conn, self.secr)
        self.assertEqual((r["resume"]["complets"], r["resume"]["incomplets"]), (1, 3))


class TestDroitsEtJournal(Fix):
    def test_sans_droit_de_lecture_rien_n_est_donne(self):
        d = {x for x in droits.droits_utilisateur(self.conn, self.secr.id_user) if x[0] != "dossier_eleve"}
        droits.remplacer_droits(self.conn, self.secr.id_user, d)
        self.conn.commit()
        for f in (lambda: la.liste(self.conn, self.secr), lambda: la.document_pdf(self.conn, self.secr),
                  lambda: la.exporter_csv(self.conn, self.secr), lambda: la.annees(self.conn, self.secr)):
            with self.assertRaises(PermissionError):
                f()

    def test_un_autre_poste_n_y_a_pas_acces(self):
        for s in (self.dird, self.dire):
            with self.assertRaises(PermissionError):
                la.liste(self.conn, s)

    def test_le_journal_garde_la_trace(self):
        la.liste(self.conn, self.secr, "incomplets")
        la.document_pdf(self.conn, self.secr)
        la.exporter_csv(self.conn, self.secr)
        self.assertEqual(len(journal(self.conn, "LISTE_ADMIN_CONSULTEE")), 1)
        self.assertIn("Liste des dossiers incomplets", journal(self.conn, "LISTE_ADMIN_CONSULTEE")[0])
        self.assertEqual(len(journal(self.conn, "LISTE_ADMIN_IMPRIMEE")), 1)
        self.assertEqual(len(journal(self.conn, "LISTE_ADMIN_EXPORTEE")), 1)
        for a in ("LISTE_ADMIN_CONSULTEE", "LISTE_ADMIN_IMPRIMEE", "LISTE_ADMIN_EXPORTEE"):
            self.assertIn(a, audit.ACTIONS)

    def test_rien_n_est_modifie(self):
        avant = self.conn.execute("SELECT COUNT(*) FROM DOSSIER_ELEVE").fetchone()[0]
        la.liste(self.conn, self.secr, "incomplets")
        la.document_pdf(self.conn, self.secr, "incomplets")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM DOSSIER_ELEVE").fetchone()[0], avant)


class TestSorties(Fix):
    def test_pdf_valide_avec_une_page_par_classe(self):
        octets, nom = la.document_pdf(self.conn, self.secr)
        self.assertTrue(octets.startswith(b"%PDF-1.4") and octets.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"/Count 2", octets)                         # 7ème A et 8ème A : une page chacune
        self.assertTrue(nom.endswith(".pdf") and "liste_des_eleves" in nom, nom)
        octets, nom = la.document_pdf(self.conn, self.secr, "incomplets", n_classe=self.c8)
        self.assertIn(b"/Count 1", octets)
        self.assertIn("incomplets", nom)

    def test_pdf_plusieurs_pages_pour_une_grande_classe(self):
        with self.conn:
            for i in range(120):
                m = f"1{i:03d}/26"
                self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM, SEXE) VALUES (?,?,'M')", (m, f"Nom{i:03d}"))
                self.conn.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?,?,?)", (self.annee, m, self.c7))
        octets, _ = la.document_pdf(self.conn, self.secr, n_classe=self.c7)
        pages = int(octets.split(b"/Count ")[1].split(b" ")[0])
        self.assertGreaterEqual(pages, 4)

    def test_rien_a_imprimer(self):
        for f in (la.document_pdf, la.exporter_csv):
            with self.assertRaises(ErreurListes):
                f(self.conn, self.secr, "eleves", "2019-2020")

    def test_csv(self):
        self.completer("0000/26")
        texte, nom = la.exporter_csv(self.conn, self.secr)
        lignes = texte.splitlines()
        self.assertEqual(len(lignes), 1 + 4)
        self.assertTrue(lignes[0].startswith("Année scolaire;Classe;Option;N°;Matricule"))
        self.assertTrue(nom.endswith(".csv"))
        self.assertTrue(any("0000/26" in l and "Complet" in l and "Incomplet" not in l for l in lignes))
        self.assertTrue(any("Mme Mbuyi;0810000000" in l for l in lignes))


class TestWeb(Fix):
    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])
        self.cl = self.app.test_client()
        self.assertEqual(self.cl.post("/connexion", data={"login": "secr1", "mdp": MDP}).status_code, 302)
        self.base = "/m/etudes_discipline/dossier_eleve"

    def test_onglet_et_page(self):
        self.assertIn("Listes et rapports administratifs", self.cl.get(self.base).get_data(as_text=True))
        page = self.cl.get(self.base + "?f=listes").get_data(as_text=True)
        self.assertIn("Imprimer (PDF)", page)
        self.assertIn("7ème A", page)
        self.assertIn("8ème A", page)
        self.assertNotIn("Petit", page)                           # élève du primaire

    def test_filtres_et_dossiers_incomplets(self):
        self.completer("0000/26", "0001/26", "0002/26")
        page = self.cl.get(f"{self.base}?f=listes&genre=incomplets&annee={self.annee}").get_data(as_text=True)
        self.assertIn("8ème A", page)
        self.assertNotIn("7ème A</h3>", page)
        page = self.cl.get(f"{self.base}?f=listes&classe={self.c7}").get_data(as_text=True)
        self.assertNotIn("8ème A</h3>", page)

    def test_pdf_et_csv(self):
        r = self.cl.get(f"{self.base}/listes/liste.pdf?genre=eleves&annee={self.annee}")
        self.assertEqual((r.status_code, r.mimetype), (200, "application/pdf"))
        self.assertTrue(r.data.startswith(b"%PDF"))
        r = self.cl.get(f"{self.base}/listes/liste.csv?genre=incomplets")
        self.assertEqual((r.status_code, r.mimetype), (200, "text/csv"))
        self.assertIn("attachment", r.headers["Content-Disposition"])
        self.assertEqual(self.cl.get(f"{self.base}/listes/liste.pdf?annee=2019-2020").status_code, 404)

    def test_acces_refuse_sans_droit_et_sans_connexion(self):
        d = {x for x in droits.droits_utilisateur(self.conn, self.secr.id_user) if x[0] != "dossier_eleve"}
        droits.remplacer_droits(self.conn, self.secr.id_user, d)
        self.conn.commit()
        for url in ("?f=listes", "/listes/liste.pdf", "/listes/liste.csv"):
            self.assertEqual(self.cl.get(self.base + url).status_code, 403, url)
        anonyme = self.app.test_client()
        self.assertIn(anonyme.get(self.base + "/listes/liste.pdf").status_code, (302, 401, 403))


if __name__ == "__main__":
    unittest.main()

"""Tests du Secrétariat : la secrétaire détermine qu'un dossier d'élève est complet ; aucune pièce n'est obligatoire.
Lancer :  python -m unittest test_secretariat"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web             # noqa: E402
import config              # noqa: E402
import database            # noqa: E402
import droits              # noqa: E402
import migrations          # noqa: E402
import secretariat         # noqa: E402
import security            # noqa: E402
from secretariat import ErreurSecretariat   # noqa: E402
from test_notes import MDP                  # noqa: E402
from test_prefecture_v57 import Fixture     # noqa: E402


def journal(conn, action):
    return [l["DETAIL"] for l in conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = ? ORDER BY ID_LOG", (action,))]


def etat(conn, matricule):
    l = conn.execute("SELECT COMPLET FROM DOSSIER_ELEVE WHERE MATRICULE = ?", (matricule,)).fetchone()
    return None if l is None else bool(l["COMPLET"])


class TestRegle(Fixture):
    def test_un_dossier_est_incomplet_tant_que_la_secretaire_n_a_rien_decide(self):
        d = secretariat.liste_dossiers(self.conn, self.secr)
        self.assertEqual(d["resume"], {"eleves": 4, "complets": 0, "incomplets": 4})
        self.assertTrue(all(not e["complet"] for e in d["eleves"]))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM DOSSIER_ELEVE").fetchone()[0], 0)    # rien n'est écrit par une consultation

    def test_aucune_piece_n_est_obligatoire(self):
        """Aucune photo, aucun document, aucun paiement : la secrétaire déclare quand même le dossier complet."""
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PHOTO_ELEVE WHERE MATRICULE = '0002/26'").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PAIEMENT WHERE MATRICULE = '0002/26'").fetchone()[0], 0)   # 0002 n'a rien payé
        r = secretariat.definir_etat(self.conn, self.secr, "0002/26", True)
        self.assertEqual(r, {"matricule": "0002/26", "complet": True, "change": True})
        self.assertIs(etat(self.conn, "0002/26"), True)

    def test_l_etat_n_est_jamais_calcule(self):
        """Un élève avec photo, reçu soldé... reste incomplet tant que la secrétaire ne le décide pas."""
        with self.conn:
            self.conn.execute("INSERT INTO PHOTO_ELEVE (MATRICULE, PHOTO, DATE_PHOTO, PRIS_PAR) VALUES ('0000/26', ?, '2026-09-10', 'x')", (b"\xff\xd8\xff\xd9",))
        d = {e["matricule"]: e for e in secretariat.liste_dossiers(self.conn, self.secr)["eleves"]}
        self.assertFalse(d["0000/26"]["complet"])                          # 0000/26 est soldé et a une photo

    def test_la_structure_ne_contient_aucune_piece(self):
        colonnes = [l["name"] for l in self.conn.execute("PRAGMA table_info(DOSSIER_ELEVE)")]
        self.assertEqual(colonnes, ["MATRICULE", "COMPLET", "DATE_DECISION", "DECIDE_PAR"])      # ni pièce, ni année scolaire
        tables = [l[0] for l in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        self.assertFalse([t for t in tables if "PIECE" in t.upper()])

    def test_l_etat_est_propre_a_l_eleve_pas_a_une_annee(self):
        secretariat.definir_etat(self.conn, self.secr, "0000/26", True)
        with self.conn:
            self.conn.execute("INSERT INTO ANNEE_SCO (ANNEESCO, EN_COURS) VALUES ('2027-2028', 0)")
            self.conn.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES ('2027-2028', '0000/26', ?)", (self.c8,))
        d = secretariat.liste_dossiers(self.conn, self.secr, annee="2027-2028")
        self.assertEqual([(e["matricule"], e["complet"]) for e in d["eleves"]], [("0000/26", True)])

    def test_la_decision_peut_etre_reprise(self):
        secretariat.definir_etat(self.conn, self.secr, "0001/26", True)
        r = secretariat.definir_etat(self.conn, self.secr, "0001/26", False)
        self.assertTrue(r["change"])
        self.assertIs(etat(self.conn, "0001/26"), False)

    def test_rien_n_est_modifie_ailleurs(self):
        avant = (self.nb_paiements(), self.conn.execute("SELECT COUNT(*) FROM INSCRIRE").fetchone()[0])
        secretariat.definir_etat(self.conn, self.secr, "0001/26", True)
        self.assertEqual((self.nb_paiements(), self.conn.execute("SELECT COUNT(*) FROM INSCRIRE").fetchone()[0]), avant)


class TestDroitsEtJournal(Fixture):
    def test_seule_la_secretaire_ou_l_administrateur_decide(self):
        secretariat.definir_etat(self.conn, self.admin, "0000/26", True)
        secretariat.definir_etat(self.conn, self.secr, "0001/26", True)
        for poste in (self.prefet, self.dire, self.dird):
            with self.assertRaises(PermissionError):
                secretariat.definir_etat(self.conn, poste, "0002/26", True)
            with self.assertRaises(PermissionError):
                secretariat.liste_dossiers(self.conn, poste)
        self.assertEqual((etat(self.conn, "0002/26")), None)

    def test_lecture_seule_ne_permet_pas_de_decider(self):
        """Droits relus dans la base : retirer « Modification » à la secrétaire suffit."""
        u = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = 'secr1'").fetchone()[0]
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'dossier_eleve' AND DROIT = 'MODIFICATION'", (u,))
        self.assertEqual(secretariat.liste_dossiers(self.conn, self.secr)["resume"]["eleves"], 4)
        with self.assertRaises(PermissionError):
            secretariat.definir_etat(self.conn, self.secr, "0000/26", True)
        self.assertIsNone(etat(self.conn, "0000/26"))

    def test_droits_de_base_de_la_secretaire(self):
        self.assertEqual(set(config.DROITS_PAR_DEFAUT["SECRETAIRE"]["dossier_eleve"]), {"LECTURE", "MODIFICATION"})
        self.assertTrue(droits.a_droit(self.conn, self.secr, "dossier_eleve", "MODIFICATION"))
        self.assertFalse(droits.a_droit(self.conn, self.secr, "dossier_eleve", "SUPPRESSION"))

    def test_un_eleve_du_primaire_est_hors_sujet(self):
        with self.assertRaises(ErreurSecretariat):
            secretariat.definir_etat(self.conn, self.secr, "0100/26", True)
        self.assertNotIn("0100/26", [e["matricule"] for e in secretariat.liste_dossiers(self.conn, self.secr)["eleves"]])
        self.assertIsNone(etat(self.conn, "0100/26"))

    def test_eleve_inconnu_ou_desactive(self):
        with self.assertRaises(ErreurSecretariat):
            secretariat.definir_etat(self.conn, self.secr, "9999/26", True)
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET ACTIF = 0 WHERE MATRICULE = '0002/26'")
        with self.assertRaises(ErreurSecretariat):
            secretariat.definir_etat(self.conn, self.secr, "0002/26", True)

    def test_chaque_decision_est_journalisee_une_fois(self):
        secretariat.definir_etat(self.conn, self.secr, "0001/26", True)
        secretariat.definir_etat(self.conn, self.secr, "0001/26", True)            # déjà complet : rien de nouveau
        secretariat.definir_etat(self.conn, self.secr, "0001/26", False)
        self.assertEqual(len(journal(self.conn, "DOSSIER_ELEVE_COMPLET")), 1)
        self.assertTrue(journal(self.conn, "DOSSIER_ELEVE_COMPLET")[0].startswith("0001/26"))
        self.assertEqual(len(journal(self.conn, "DOSSIER_ELEVE_INCOMPLET")), 1)
        self.assertEqual(self.conn.execute("SELECT DECIDE_PAR FROM DOSSIER_ELEVE WHERE MATRICULE = '0001/26'").fetchone()[0], "secr1")
        self.assertEqual(database.verifier_journal(self.conn), (True, None))

    def test_actions_connues_du_journal(self):
        import audit
        for a in ("DOSSIER_ELEVE_COMPLET", "DOSSIER_ELEVE_INCOMPLET", "DOSSIERS_ELEVES_CONSULTES"):
            self.assertIn(a, audit.ACTIONS)

    def test_filtres_classe_etat_recherche(self):
        secretariat.definir_etat(self.conn, self.secr, "0000/26", True)
        self.assertEqual([e["matricule"] for e in secretariat.liste_dossiers(self.conn, self.secr, "complet")["eleves"]], ["0000/26"])
        self.assertEqual(len(secretariat.liste_dossiers(self.conn, self.secr, "incomplet")["eleves"]), 3)
        d = secretariat.liste_dossiers(self.conn, self.secr, "incomplet", n_classe=self.c8)
        self.assertEqual([e["matricule"] for e in d["eleves"]], ["0009/26"])
        d = secretariat.liste_dossiers(self.conn, self.secr, texte="Amisi")
        self.assertEqual([e["matricule"] for e in d["eleves"]], ["0001/26"])


class TestMigration(unittest.TestCase):
    def test_comptes_secretaires_existants_recoivent_modification_une_seule_fois(self):
        c = database.connecter(os.path.join(tempfile.mkdtemp(), "m.db"))
        security.creer_utilisateur(c, "secr1", "Secr", "SECRETAIRE", MDP)
        id_user = c.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = 'secr1'").fetchone()[0]
        with c:                                                       # base d'avant la v16 : pas de droit de modification
            c.execute("DELETE FROM DROIT WHERE ID_USER = ? AND DROIT = 'MODIFICATION'", (id_user,))
            c.execute("DELETE FROM ROLE_DROIT WHERE ROLE = 'SECRETAIRE' AND DROIT = 'MODIFICATION'")
        migrations._mig_secretariat_dossier(c)
        self.assertIn(("dossier_eleve", "MODIFICATION"), droits.droits_utilisateur(c, id_user))
        self.assertIn(("dossier_eleve", "MODIFICATION"), droits.droits_par_defaut(c, "SECRETAIRE"))
        self.assertEqual(migrations.VERSION_SCHEMA, 18)


class TestWeb(Fixture):
    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.chemin_bd())
        self.cl = self.app.test_client()
        self.assertEqual(self.cl.post("/connexion", data={"login": "secr1", "mdp": MDP}).status_code, 302)

    def chemin_bd(self):
        return self.conn.execute("PRAGMA database_list").fetchone()[2]

    def test_la_page_liste_les_dossiers(self):
        page = self.cl.get("/m/etudes_discipline/dossier_eleve").get_data(as_text=True)
        self.assertIn("Aucune pièce n'est obligatoire", page)
        for m in ("0000/26", "0001/26", "0002/26", "0009/26"):
            self.assertIn(m, page)
        self.assertNotIn("0100/26", page)
        self.assertIn("Déclarer complet", page)

    def test_declarer_complet_puis_reprendre(self):
        r = self.cl.post("/m/etudes_discipline/dossier_eleve/etat", data={"matricule": "0002/26", "etat": "complet"})
        self.assertEqual(r.status_code, 302)
        self.assertIs(etat(self.conn, "0002/26"), True)
        page = self.cl.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("Dossier déclaré complet.", page)
        self.assertIn("Remettre à incomplet", page)
        self.assertEqual(self.cl.post("/m/etudes_discipline/dossier_eleve/etat", data={"matricule": "0002/26", "etat": "incomplet"}).status_code, 302)
        self.assertIs(etat(self.conn, "0002/26"), False)

    def test_etat_invalide_ou_eleve_du_primaire(self):
        self.assertEqual(self.cl.post("/m/etudes_discipline/dossier_eleve/etat", data={"matricule": "0002/26", "etat": "x"}).status_code, 400)
        self.assertEqual(self.cl.post("/m/etudes_discipline/dossier_eleve/etat", data={"matricule": "0100/26", "etat": "complet"}).status_code, 400)
        self.assertIsNone(etat(self.conn, "0002/26"))

    def test_sans_droit_de_modification_la_page_est_en_lecture_seule(self):
        u = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = 'secr1'").fetchone()[0]
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'dossier_eleve' AND DROIT = 'MODIFICATION'", (u,))
        page = self.cl.get("/m/etudes_discipline/dossier_eleve").get_data(as_text=True)
        self.assertNotIn("Déclarer complet", page)
        self.assertIn("le droit « Modification » ne vous est pas accordé", page)
        self.assertEqual(self.cl.post("/m/etudes_discipline/dossier_eleve/etat", data={"matricule": "0002/26", "etat": "complet"}).status_code, 403)

    def test_les_autres_postes_n_y_ont_pas_acces(self):
        cl = self.app.test_client()
        self.assertEqual(cl.post("/connexion", data={"login": "prefet1", "mdp": MDP}).status_code, 302)
        self.assertEqual(cl.get("/m/etudes_discipline/dossier_eleve").status_code, 403)
        self.assertEqual(cl.post("/m/etudes_discipline/dossier_eleve/etat", data={"matricule": "0002/26", "etat": "complet"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()

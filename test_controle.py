"""Tests du module Contrôle numérique.  Lancer :  python test_controle.py"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import controle        # noqa: E402
import database        # noqa: E402
import demo            # noqa: E402
import droits          # noqa: E402
import paiements       # noqa: E402
import security        # noqa: E402
from controle import ErreurControle   # noqa: E402

AN = demo.ANNEE_COURANTE


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(":memory:")
        self.login, self.mdp = demo.semer(self.conn)
        self.perc = security.authentifier(self.conn, self.login, self.mdp).session
        security.creer_utilisateur(self.conn, "admin1", "Administrateur Test", "ADMINISTRATEUR", "Adm-Test#2026-xyz")
        self.admin = security.authentifier(self.conn, "admin1", "Adm-Test#2026-xyz").session
        security.creer_utilisateur(self.conn, "dir1", "Directrice Test", "DIRECTRICE_ETUDES", "Dir-Test#2026-xyz")
        self.dir = security.authentifier(self.conn, "dir1", "Dir-Test#2026-xyz").session

    def donner(self, session, *accordes):
        with self.conn:
            droits.remplacer_droits(self.conn, session.id_user, {("controle", d) for d in accordes})

    def liste(self, classe, option, codtf, annee=AN, session=None):
        return controle.eleves_en_ordre(self.conn, session or self.admin, annee, classe, option, codtf)


class TestListe(Base):
    def test_en_ordre_selon_le_tarif(self):
        # 8ème A (année courante) : CSF-0001 a payé INSC (3000/3000) mais seulement 5000/9000 de MIN1
        l = self.liste("8ème A", None, "INSC")
        self.assertEqual([x["matricule"] for x in l["lignes"]], ["CSF-0001"])
        self.assertEqual(l["lignes"][0]["n"], 1)
        self.assertEqual(l["lignes"][0]["sexe"], "M")
        self.assertEqual(self.liste("8ème A", None, "MIN1")["lignes"], [])

    def test_titre_et_champs(self):
        l = self.liste("8ème A", None, "INSC")
        self.assertEqual(l["titre"], "LISTE DES ELEVES EN ORDRE AVEC LE FRAIS FRAIS D'INSCRIPTION")
        self.assertEqual(controle.ligne_classe_option(l), "CLASSE : 8ème A")
        self.assertEqual(l["lignes"][0]["nom_complet"], "MBUYI KALALA Jean-Pierre")

    def test_option_des_humanites(self):
        self.assertEqual([o for o, _ in controle.liste_options(self.conn, "3ème Scientifique")], ["SCI"])
        self.assertEqual(controle.liste_options(self.conn, "8ème A"), [])
        l = self.liste("4ème Commerciale et Gestion", "COM", "INSC")       # CSF-0003 a payé son inscription
        self.assertEqual([x["matricule"] for x in l["lignes"]], ["CSF-0003"])
        self.assertIn("OPTION : Commerciale et Gestion", controle.ligne_classe_option(l))
        with self.assertRaises(ErreurControle):                              # option obligatoire quand elle existe
            self.liste("4ème Commerciale et Gestion", None, "INSC")

    def test_annee_precedente(self):
        l = self.liste("7ème A", None, "MIN2", annee=demo.ANNEE_PRECEDENTE)
        self.assertEqual([x["matricule"] for x in l["lignes"]], ["CSF-0001"])

    def test_recus_annules_ne_comptent_pas(self):
        with self.conn:
            self.conn.execute("UPDATE PAIEMENT SET STATUT='ANNULE' WHERE MATRICULE='CSF-0001' AND ANNEESCO=? AND CODTF='INSC'", (AN,))
        self.assertEqual(self.liste("8ème A", None, "INSC")["lignes"], [])

    def test_paiement_partiel_puis_solde(self):
        paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0001", AN, "MIN1", 4500)
        self.assertEqual(len(self.liste("8ème A", None, "MIN1")["lignes"]), 1)

    def test_eleve_desactive_exclu_et_tri_alphabetique(self):
        paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0006", AN, "INSC", 3000)
        l = self.liste("7ème A", None, "INSC")                               # 0004 et 0006 inscrits en 7ème
        self.assertEqual([x["matricule"] for x in l["lignes"]], ["CSF-0006"])
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET ACTIF = 0 WHERE MATRICULE = 'CSF-0006'")
        self.assertEqual(self.liste("7ème A", None, "INSC")["lignes"], [])

    def test_sans_tarif(self):
        with self.conn:
            self.conn.execute("DELETE FROM TARIF WHERE CODTF='EXAM' AND N_CLASSE=1 AND ANNEESCO=?", (AN,))
            self.conn.execute("UPDATE TYPE_FRAIS SET MONTANT = NULL, CODE_DEVISE = NULL WHERE CODTF = 'EXAM'")
        l = self.liste("7ème A", None, "EXAM")
        self.assertTrue(l["sans_tarif"])
        self.assertEqual(l["lignes"], [])

    def test_liste_des_types_de_frais_sans_trimestre(self):
        self.assertEqual([c for c, _ in controle.liste_types_frais(self.conn)], ["EXAM", "INSC", "MIN1", "MIN2"])
        with self.assertRaises(ErreurControle):                              # type de frais inconnu
            self.liste("8ème A", None, "INCONNU")

    def test_choix_obligatoires(self):
        with self.assertRaises(ErreurControle):
            controle.eleves_en_ordre(self.conn, self.admin, AN, "", None, "INSC")

    def test_droits(self):
        with self.assertRaises(PermissionError):
            self.liste("8ème A", None, "INSC", session=self.dir)
        self.donner(self.dir, "LECTURE")
        self.assertEqual(len(self.liste("8ème A", None, "INSC", session=self.dir)["lignes"]), 1)

    def test_pdf(self):
        l = self.liste("8ème A", None, "INSC")
        chemin = controle.preparer_liste_pdf(self.conn, self.admin, l)
        data = open(chemin, "rb").read()
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertIn(b"Direction des \xe9tudes", data)
        vide = self.liste("8ème A", None, "MIN1")
        with self.assertRaises(ErreurControle):
            controle.preparer_liste_pdf(self.conn, self.admin, vide)

    def test_pdf_plusieurs_pages(self):
        l = self.liste("8ème A", None, "INSC")
        l["lignes"] = [{"n": i, "matricule": f"M{i}", "nom_complet": f"ELEVE NUMERO {i} Prénom", "sexe": "F"}
                       for i in range(1, 131)]
        chemin = controle.preparer_liste_pdf(self.conn, self.admin, l)
        self.assertGreaterEqual(open(chemin, "rb").read().count(b"/Type /Page "), 3)

    def test_journal(self):
        l = self.liste("8ème A", None, "INSC")
        controle.journaliser_liste(self.conn, self.admin, l, "LISTE_EN_ORDRE_CONSULTEE")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE ACTION='LISTE_EN_ORDRE_CONSULTEE'").fetchone()[0], 1)
        self.assertTrue(database.verifier_journal(self.conn)[0])


class TestControleEleve(Base):
    def test_en_ordre(self):
        for codtf, c in (("MIN1", 4500), ("MIN2", 9000), ("EXAM", 1500)):      # 0001 solde tout l'an courant
            paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0001", AN, codtf, c)
        r = controle.controler_eleve(self.conn, self.admin, "CSF-0001")
        self.assertEqual(r["statut"], controle.EN_ORDRE)
        self.assertEqual((r["classe"], r["sexe"], r["dettes"]), ("8ème A", "Masculin", []))

    def test_impaye_annee_courante(self):
        r = controle.controler_eleve(self.conn, self.admin, "CSF-0001")          # reste du minerval
        self.assertEqual(r["statut"], controle.IMPAYE)
        self.assertTrue(r["dettes"])
        self.assertEqual(len(r["lignes"]), 4)

    def test_impaye_ancienne_dette(self):
        r = controle.controler_eleve(self.conn, self.admin, "CSF-0002")
        self.assertEqual(r["statut"], controle.IMPAYE)
        self.assertTrue(any(demo.ANNEE_PRECEDENTE in d for d in r["dettes"]))

    def test_non_inscrit_sans_dette(self):
        with self.conn:
            self.conn.execute("DELETE FROM PAIEMENT WHERE 0")
            self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('CSF-0099', 'ZEBRE')")
        r = controle.controler_eleve(self.conn, self.admin, "CSF-0099")
        self.assertEqual(r["statut"], controle.NON_INSCRIT)

    def test_droit_et_inconnu_et_journal(self):
        with self.assertRaises(PermissionError):
            controle.controler_eleve(self.conn, self.dir, "CSF-0001")
        with self.assertRaises(ErreurControle):
            controle.controler_eleve(self.conn, self.admin, "XXX")
        controle.controler_eleve(self.conn, self.admin, "CSF-0001")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE ACTION='CONTROLE_NUMERIQUE'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()

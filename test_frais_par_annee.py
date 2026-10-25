"""Frais obligatoires réservés à une année d'étude : examen d'État + dissertation (4ème humanités), ENAFEP (6ème primaire),
TENASSOP (8ème secondaire). Lancer :  python test_frais_par_annee.py"""
import unittest

import donnees
import migrations
import paiements
import referentiels as ref
import test_paiement_candidat as base
from test_paiement_candidat import AN


class TestFraisParAnnee(base.Base):
    def setUp(self):
        super().setUp()
        migrations._mig_frais_obligatoires(self.conn)        # appliquée automatiquement aux bases existantes
        with self.conn:
            self.conn.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU, SECTION) VALUES ('PRIM', 'Primaire', 'PRIMAIRE')")
            self.conn.execute("INSERT INTO CLASSE (N_CLASSE, DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES (60, '6ème A', 'PRIM', '6ème', 'A')")
            self.conn.execute("INSERT INTO CLASSE (N_CLASSE, DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES (61, '4ème A', 'PRIM', '4ème', 'A')")
            for i, (m, c) in enumerate((("PRIM-6", 60), ("PRIM-4", 61)), 1):
                self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES (?, 'ELEVE')", (m,))
                self.conn.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE, DATE_INSCRIPTION, STATUT) VALUES (?,?,?,?, 'NOUVEAU')",
                                  (AN, m, c, "2026-09-01"))
            for code in ("EXETAT", "DISSERT", "ENAFEP", "TENASSOP"):                  # l'Administrateur fixe un montant
                self.conn.execute("UPDATE TYPE_FRAIS SET MONTANT = 2000, CODE_DEVISE = 'USD' WHERE CODTF = ?", (code,))
        self.hum4 = 5            # « 4ème Commerciale et Gestion » (demo)
        self.sec8 = 2            # « 8ème A » (demo)
        self.sec7 = 1

    def codes(self, matricule, n_classe):
        return {l.codtf for l in donnees.situation(self.conn, matricule, AN, n_classe)}

    def test_les_types_sont_crees_par_la_migration(self):
        l = {r["CODTF"]: r["CLASSE_CIBLE"] for r in self.conn.execute("SELECT CODTF, CLASSE_CIBLE FROM TYPE_FRAIS WHERE CLASSE_CIBLE IS NOT NULL")}
        self.assertEqual(l, {"EXETAT": "HUM4", "DISSERT": "HUM4", "ENAFEP": "PRIM6", "TENASSOP": "SEC8"})

    def test_cible_de_classe(self):
        self.assertEqual(donnees.cible_de_classe(self.conn, self.hum4), "HUM4")
        self.assertEqual(donnees.cible_de_classe(self.conn, self.sec8), "SEC8")
        self.assertIsNone(donnees.cible_de_classe(self.conn, self.sec7))
        self.assertEqual(donnees.cible_de_classe(self.conn, 60), "PRIM6")
        self.assertIsNone(donnees.cible_de_classe(self.conn, 61))           # 4ème du PRIMAIRE : pas l'examen d'État

    def test_chaque_frais_n_est_du_que_par_sa_classe(self):
        cibles = {"EXETAT", "DISSERT", "ENAFEP", "TENASSOP"}
        self.assertEqual(self.codes("CSF-0003", self.hum4) & cibles, {"EXETAT", "DISSERT"})
        self.assertEqual(self.codes("PRIM-6", 60) & cibles, {"ENAFEP"})
        self.assertEqual(self.codes("CSF-0001", self.sec8) & cibles, {"TENASSOP"})
        self.assertEqual(self.codes("CSF-0004", self.sec7) & cibles, set())
        self.assertEqual(self.codes("PRIM-4", 61) & cibles, set())

    def test_sans_montant_rien_n_est_du(self):
        with self.conn:
            self.conn.execute("UPDATE TYPE_FRAIS SET MONTANT = NULL, CODE_DEVISE = NULL WHERE CODTF = 'EXETAT'")
        self.assertNotIn("EXETAT", self.codes("CSF-0003", self.hum4))

    def test_paiement_par_la_bonne_classe_seulement(self):
        self.assertTrue(paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0003", AN, "EXETAT", 2000))
        self.assertTrue(paiements.enregistrer_paiement(self.conn, self.perc, "PRIM-6", AN, "ENAFEP", 2000))
        with self.assertRaises(paiements.ErreurPaiement) as cm:
            paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "EXETAT", 2000)
        self.assertIn("réservé", str(cm.exception))
        with self.assertRaises(paiements.ErreurPaiement):
            paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0001", AN, "ENAFEP", 2000)

    def test_ces_frais_sont_ajoutes_au_total_du_de_la_classe(self):
        du = lambda m, c: sum(l.du for l in donnees.situation(self.conn, m, AN, c))
        avec = du("CSF-0003", self.hum4)
        with self.conn:
            self.conn.execute("UPDATE TYPE_FRAIS SET MONTANT = NULL, CODE_DEVISE = NULL WHERE CODTF IN ('EXETAT','DISSERT')")
        self.assertEqual(avec - du("CSF-0003", self.hum4), 4000)

    def test_le_champ_est_modifiable_dans_la_mise_a_jour_des_tables(self):
        champs = {c.nom for c in ref.TABLES["types_frais"].champs}
        self.assertIn("CLASSE_CIBLE", champs)

    def test_la_migration_15_existe(self):
        self.assertGreaterEqual(migrations.VERSION_SCHEMA, 15)


if __name__ == "__main__":
    unittest.main()

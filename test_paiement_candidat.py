"""Tests du paiement des frais d'inscription par un candidat sans matricule (bouton « Inscription » du module Paiement).
Lancer :  python test_paiement_candidat.py"""
import os
import sqlite3
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import audit                     # noqa: E402
import audit_financier           # noqa: E402
import database                  # noqa: E402
import demo                      # noqa: E402
import droits                    # noqa: E402
import inscription               # noqa: E402
import migrations                # noqa: E402
import paiements                 # noqa: E402
import referentiels as ref       # noqa: E402
import security                  # noqa: E402

MDP = "Tr@vail-Amour-2026"
AN = demo.ANNEE_COURANTE


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(os.path.join(tempfile.mkdtemp(), "cand.db"))
        security.creer_utilisateur(self.conn, "admin1", "Alice Administratrice", "ADMINISTRATEUR", MDP)
        self.admin = security.authentifier(self.conn, "admin1", MDP).session
        login, mdp = demo.semer(self.conn)
        self.perc = security.authentifier(self.conn, login, mdp).session
        id_sec = security.creer_utilisateur(self.conn, "sec1", "Sophie Secrétaire", "SECRETAIRE", MDP)
        with self.conn:
            droits.remplacer_droits(self.conn, id_sec, {("inscription", "LECTURE"), ("inscription", "AJOUT")})
        self.sec = security.authentifier(self.conn, "sec1", MDP).session
        ref.enregistrer(self.conn, self.admin, "types_frais",
                        {"CODTF": "INSC", "DESITF": "Frais d'inscription", "MONTANT": "30", "CODE_DEVISE": "USD",
                         "POUR_INSCRIPTION": True}, ("INSC",))
        self.classe = self.conn.execute("SELECT N_CLASSE FROM CLASSE WHERE ACTIF = 1 ORDER BY N_CLASSE").fetchone()[0]

    def payer(self, nom="Kalala", postnom="Mwamba", prenom="Joël", **plus):
        args = dict(annee=AN, n_classe=self.classe, codtf="INSC", centimes=3000)
        args.update(plus)
        return paiements.enregistrer_paiement_inscription(
            self.conn, self.perc, args["annee"], args["n_classe"], args["codtf"], args["centimes"], nom, postnom, prenom)


class TestPaiementCandidat(Base):
    def test_un_candidat_sans_matricule_obtient_un_recu(self):
        n = self.payer()
        l = self.conn.execute("SELECT * FROM PAIEMENT WHERE N_RECU = ?", (n,)).fetchone()
        self.assertIsNone(l["MATRICULE"])
        self.assertEqual(l["NOM_PAYEUR"], "KALALA MWAMBA JOËL")
        self.assertEqual(l["MONT_PAYE"], 3000)

    def test_le_recu_se_charge_et_se_imprime(self):
        n = self.payer()
        r = paiements.charger_recu(self.conn, n)
        self.assertEqual(r["nom_complet"], "KALALA MWAMBA JOËL")
        self.assertEqual(r["matricule"], "")
        self.assertIn("inscription", r["motif"])
        chemin = paiements.preparer_pdf(self.conn, self.perc, n)
        self.assertTrue(os.path.getsize(chemin) > 500)

    def test_le_recu_valide_une_candidature(self):
        n = self.payer()
        info = inscription.verifier_recu(self.conn, n)
        self.assertEqual(info["n_recu"], n)

    def test_le_montant_doit_etre_celui_des_frais(self):
        with self.assertRaises(paiements.ErreurPaiement):
            self.payer(centimes=1000)
        with self.assertRaises(paiements.ErreurPaiement):
            self.payer(centimes=5000)

    def test_nom_obligatoire(self):
        with self.assertRaises(paiements.ErreurPaiement):
            self.payer(nom="   ")

    def test_seuls_les_frais_d_inscription_sont_acceptes(self):
        autre = self.conn.execute("SELECT CODTF FROM TYPE_FRAIS WHERE POUR_INSCRIPTION = 0 LIMIT 1").fetchone()
        if autre:
            with self.assertRaises(paiements.ErreurPaiement):
                self.payer(codtf=autre[0])

    def test_pas_de_double_paiement_pour_la_meme_personne(self):
        self.payer()
        with self.assertRaises(paiements.ErreurPaiement) as e:
            self.payer(nom="kalala", postnom="mwamba", prenom="joël")
        self.assertIn("déjà payé", str(e.exception))
        self.payer(nom="Autre")                                # une autre personne peut payer

    def test_reserve_au_percepteur_avec_droit_ajout(self):
        with self.assertRaises(Exception):
            paiements.enregistrer_paiement_inscription(self.conn, self.sec, AN, self.classe, "INSC", 3000, "Test")
        with self.assertRaises(Exception):
            paiements.enregistrer_paiement_inscription(self.conn, self.admin, AN, self.classe, "INSC", 3000, "Test")

    def test_un_recu_ne_se_modifie_pas(self):
        n = self.payer()
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("UPDATE PAIEMENT SET NOM_PAYEUR = 'X' WHERE N_RECU = ?", (n,))

    def test_sans_matricule_ni_nom_la_base_refuse(self):
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute(
                "INSERT INTO PAIEMENT (N_RECU, ANNEESCO, NUM_SEQ, DATE_PAY, MATRICULE, N_CLASSE, CODTF, CODE_DEVISE, MONT_PAYE, N_PERC) "
                "VALUES ('9999', ?, 9999, '2026-01-01T00:00:00+00:00', NULL, ?, 'INSC', 'USD', 3000, 1)", (AN, self.classe))

    def test_le_rapport_de_caisse_compte_le_candidat(self):
        n = self.payer()
        jour = paiements.lire_date(paiements.datetime.now().strftime("%d/%m/%Y"))
        r = paiements.rapport_journalier(self.conn, self.perc, jour)
        recus = [l["n_recu"] for g in r["groupes"] for l in g["lignes"]]
        self.assertIn(n, recus)
        ligne = next(l for g in r["groupes"] for l in g["lignes"] if l["n_recu"] == n)
        self.assertIn("KALALA", ligne["nom_complet"])
        chemin = paiements.preparer_rapport_pdf(self.conn, self.perc, jour)
        self.assertTrue(os.path.exists(chemin))

    def test_audit_et_controle_voient_le_recu(self):
        n = self.payer()
        h = audit.historique_financier(self.conn, self.admin)
        refs = [o["reference"] for o in h["operations"]] if isinstance(h, dict) and "operations" in h else str(h)
        self.assertIn(n, refs)
        trace = audit.trace_operation(self.conn, self.admin, n)
        self.assertTrue(trace)
        anomalies = audit.controle_concordance(self.conn, self.admin)
        self.assertFalse([a for a in anomalies if n in str(a)], anomalies)
        audit_financier.controle_financier(self.conn, self.admin)

    def test_table_paiements_des_travaux_techniques(self):
        n = self.payer()
        res = ref.lister(self.conn, self.admin, "paiements", "")
        self.assertIn(n, str(res))


class TestMigration(Base):
    def test_une_ancienne_base_est_convertie_sans_perte(self):
        elv = self.conn.execute(
            "SELECT MATRICULE FROM INSCRIRE I WHERE ANNEESCO = ? AND NOT EXISTS (SELECT 1 FROM PAIEMENT P "
            "WHERE P.MATRICULE = I.MATRICULE AND P.CODTF = 'EXAM') LIMIT 1", (AN,)).fetchone()[0]
        recu = paiements.enregistrer_paiement(self.conn, self.perc, elv, AN, "EXAM", 1500)   # doit survivre à la migration
        avant = [tuple(r) for r in self.conn.execute(
            "SELECT N_RECU, MATRICULE, MONT_PAYE, STATUT FROM PAIEMENT ORDER BY N_RECU")]
        # on simule une base d'avant 0.24 : MATRICULE obligatoire, pas de NOM_PAYEUR
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.executescript("""
            BEGIN;
            CREATE TABLE PAIEMENT_OLD AS SELECT N_RECU, ANNEESCO, NUM_SEQ, DATE_PAY, MATRICULE, N_CLASSE, CODTF, CODE_DEVISE,
                MONT_PAYE, N_PERC, STATUT, MOTIF_ANNULATION, DATE_ANNULATION, ANNULE_PAR FROM PAIEMENT;
            DROP TABLE PAIEMENT;
            CREATE TABLE PAIEMENT (
                N_RECU TEXT PRIMARY KEY, ANNEESCO TEXT NOT NULL, NUM_SEQ INTEGER NOT NULL, DATE_PAY TEXT NOT NULL,
                MATRICULE TEXT NOT NULL, N_CLASSE INTEGER NOT NULL, CODTF TEXT NOT NULL, CODE_DEVISE TEXT NOT NULL,
                MONT_PAYE INTEGER NOT NULL, N_PERC INTEGER NOT NULL, STATUT TEXT NOT NULL DEFAULT 'VALIDE',
                MOTIF_ANNULATION TEXT, DATE_ANNULATION TEXT, ANNULE_PAR TEXT, UNIQUE (ANNEESCO, NUM_SEQ));
            INSERT INTO PAIEMENT SELECT * FROM PAIEMENT_OLD;
            DROP TABLE PAIEMENT_OLD;
            PRAGMA user_version = 6;
            COMMIT;""")
        self.conn.execute("PRAGMA foreign_keys = ON")
        actions = migrations.mettre_a_jour(self.conn, sauvegarder=False)
        self.assertTrue(any("sans matricule" in a for a in actions), actions)
        apres = [tuple(r) for r in self.conn.execute(
            "SELECT N_RECU, MATRICULE, MONT_PAYE, STATUT FROM PAIEMENT ORDER BY N_RECU")]
        self.assertEqual(avant, apres)
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        # les protections sont revenues et le paiement de candidat fonctionne
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("DELETE FROM PAIEMENT WHERE N_RECU = ?", (recu,))
        n = self.payer()
        self.assertIsNone(self.conn.execute("SELECT MATRICULE FROM PAIEMENT WHERE N_RECU = ?", (n,)).fetchone()[0])
        self.assertFalse(migrations.analyser(self.conn).a_faire)


if __name__ == "__main__":
    unittest.main()

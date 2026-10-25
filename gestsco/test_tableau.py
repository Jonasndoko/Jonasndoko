"""Tests du Tableau de bord : droits, élèves en règle / pas en règle, et surtout : AUCUNE donnée financière ni détail.
Lancer :  python test_tableau.py"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import acces               # noqa: E402
import config              # noqa: E402
import controle            # noqa: E402
import database            # noqa: E402
import demo                # noqa: E402
import donnees             # noqa: E402
import droits              # noqa: E402
import paiements           # noqa: E402
import security            # noqa: E402
import tableau             # noqa: E402
from tableau import ErreurTableau   # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(":memory:")
        self.login, self.mdp = demo.semer(self.conn)
        self.perc = security.authentifier(self.conn, self.login, self.mdp).session
        security.creer_utilisateur(self.conn, "admin1", "Administrateur Test", "ADMINISTRATEUR", "Adm-Test#2026-xyz")
        self.admin = security.authentifier(self.conn, "admin1", "Adm-Test#2026-xyz").session
        security.creer_utilisateur(self.conn, "intend1", "Intendant Test", "INTENDANT", "Int-Test#2026-xyz")
        self.intendant = security.authentifier(self.conn, "intend1", "Int-Test#2026-xyz").session

    def autoriser(self, session):
        with self.conn:
            droits.remplacer_droits(self.conn, session.id_user, {("tableau", "LECTURE")})


class TestDroits(Base):
    def test_sans_droit_refuse(self):
        self.assertFalse(tableau.peut(self.conn, self.intendant))
        with self.assertRaises(PermissionError):
            tableau.tableau_de_bord(self.conn, self.intendant)

    def test_percepteur_sans_droit_refuse(self):
        self.assertFalse(tableau.peut(self.conn, self.perc))
        with self.assertRaises(PermissionError):
            tableau.tableau_de_bord(self.conn, self.perc)

    def test_droit_accorde_puis_retire(self):
        self.autoriser(self.intendant)
        self.assertTrue(tableau.peut(self.conn, self.intendant))
        self.assertTrue(tableau.tableau_de_bord(self.conn, self.intendant)["eleves"]["inscrits"] > 0)
        with self.conn:
            droits.remplacer_droits(self.conn, self.intendant.id_user, set())
        self.assertFalse(tableau.peut(self.conn, self.intendant))            # effet immédiat, session ouverte
        with self.assertRaises(PermissionError):
            tableau.tableau_de_bord(self.conn, self.intendant)

    def test_administrateur_toujours_autorise(self):
        self.assertTrue(tableau.peut(self.conn, self.admin))

    def test_seule_la_lecture_existe(self):
        self.assertEqual(config.MODULES_DROITS["tableau"][1], ("LECTURE",))
        with self.assertRaises(ValueError):
            droits.normaliser({("tableau", "AJOUT")})

    def test_droit_de_base_d_un_role(self):
        with self.conn:
            droits.remplacer_droits_role(self.conn, "INTENDANT", {("tableau", "LECTURE")})
        id_user, _ = acces.creer_compte(self.conn, self.admin, "int2", "Int Deux", "INTENDANT")
        self.assertIn(("tableau", "LECTURE"), droits.droits_utilisateur(self.conn, id_user))

    def test_compte_desactive_refuse(self):
        self.autoriser(self.intendant)
        with self.conn:
            self.conn.execute("UPDATE UTILISATEUR SET ACTIF = 0 WHERE ID_USER = ?", (self.intendant.id_user,))
        self.assertFalse(tableau.peut(self.conn, self.intendant))


class TestVueGenerale(Base):
    def test_rien_d_autre_que_les_nombres_d_eleves(self):
        """Garde-fou : le résultat ne contient ni montant, ni opération, ni classe, ni nom d'élève."""
        d = tableau.tableau_de_bord(self.conn, self.admin)
        self.assertEqual(set(d), {"annee", "annees", "eleves"})
        self.assertEqual(set(d["eleves"]), {"inscrits", "en_regle", "pas_en_regle", "taux_en_regle"})
        for valeur in d["eleves"].values():
            self.assertIsInstance(valeur, int)
        texte = repr(d).lower()
        for interdit in ("usd", "montant", "recu", "reçu", "devise", "encaiss", "classe", "7ème", "nom"):
            self.assertNotIn(interdit, texte)

    def test_signature_sans_option_financiere(self):
        import inspect
        self.assertEqual(list(inspect.signature(tableau.tableau_de_bord).parameters), ["conn", "session", "annee"])

    def test_coherent_avec_le_controle_numerique(self):
        d = tableau.tableau_de_bord(self.conn, self.admin)
        annee = donnees.annee_courante(self.conn)
        inscrits = [l[0] for l in self.conn.execute(
            "SELECT I.MATRICULE FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE "
            "WHERE I.ANNEESCO = ? AND E.ACTIF = 1", (annee,))]
        statuts = [controle.controler_eleve(self.conn, self.admin, m)["statut"] for m in inscrits]
        self.assertEqual(d["eleves"]["inscrits"], len(inscrits))
        self.assertEqual(d["eleves"]["pas_en_regle"], statuts.count(controle.IMPAYE))
        self.assertEqual(d["eleves"]["en_regle"], statuts.count(controle.EN_ORDRE))
        self.assertEqual(d["eleves"]["en_regle"] + d["eleves"]["pas_en_regle"], d["eleves"]["inscrits"])

    def test_un_eleve_qui_solde_tout_passe_en_regle(self):
        avant = tableau.tableau_de_bord(self.conn, self.admin)["eleves"]
        annee = donnees.annee_courante(self.conn)
        for codtf, c in (("INSC", 3000), ("MIN1", 8000), ("MIN2", 8000), ("EXAM", 1500)):
            paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", annee, codtf, c)
        apres = tableau.tableau_de_bord(self.conn, self.admin)["eleves"]
        self.assertEqual(apres["en_regle"], avant["en_regle"] + 1)
        self.assertEqual(apres["pas_en_regle"], avant["pas_en_regle"] - 1)
        self.assertEqual(controle.controler_eleve(self.conn, self.admin, "CSF-0004")["statut"], controle.EN_ORDRE)

    def test_une_dette_ancienne_rend_pas_en_regle(self):
        self.assertTrue(donnees.dettes(self.conn, "CSF-0002"))
        self.assertGreaterEqual(tableau.tableau_de_bord(self.conn, self.admin)["eleves"]["pas_en_regle"], 1)

    def test_eleve_desactive_non_compte(self):
        avant = tableau.tableau_de_bord(self.conn, self.admin)["eleves"]["inscrits"]
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET ACTIF = 0 WHERE MATRICULE = 'CSF-0006'")
        self.assertEqual(tableau.tableau_de_bord(self.conn, self.admin)["eleves"]["inscrits"], avant - 1)

    def test_taux(self):
        e = tableau.tableau_de_bord(self.conn, self.admin)["eleves"]
        self.assertEqual(e["taux_en_regle"], round(100 * e["en_regle"] / e["inscrits"]))

    def test_annee_precedente(self):
        d = tableau.tableau_de_bord(self.conn, self.admin, demo.ANNEE_PRECEDENTE)
        self.assertEqual(d["annee"], demo.ANNEE_PRECEDENTE)
        self.assertEqual(d["eleves"]["inscrits"], 5)           # 0001, 0002, 0003, 0005, 0006

    def test_annee_inconnue_refusee(self):
        with self.assertRaises(ErreurTableau):
            tableau.tableau_de_bord(self.conn, self.admin, "1900-1901")

    def test_base_vide(self):
        conn = database.connecter(":memory:")
        security.creer_utilisateur(conn, "admin9", "Admin", "ADMINISTRATEUR", "Adm-Test#2026-xyz")
        s = security.authentifier(conn, "admin9", "Adm-Test#2026-xyz").session
        d = tableau.tableau_de_bord(conn, s)
        self.assertEqual(d["eleves"], {"inscrits": 0, "en_regle": 0, "pas_en_regle": 0, "taux_en_regle": 0})


class TestJournal(Base):
    def test_ouverture_journalisee(self):
        tableau.journaliser_ouverture(self.conn, self.admin)
        l = self.conn.execute("SELECT ACTION FROM JOURNAL ORDER BY ID_LOG DESC LIMIT 1").fetchone()
        self.assertEqual(l[0], "TABLEAU_DE_BORD_OUVERT")


class TestTendances(Base):
    def test_comptes_seulement(self):
        self.autoriser(self.intendant)
        d = tableau.tendances(self.conn, self.intendant)
        self.assertEqual(set(d), {"annees", "personnel"})
        for a in d["annees"]:
            self.assertEqual(set(a), {"annee", "inscrits", "filles", "garcons"})
            self.assertEqual(a["filles"] + a["garcons"], a["inscrits"])

    def test_sans_droit_refuse(self):
        with self.assertRaises(PermissionError):
            tableau.tendances(self.conn, self.perc)


class TestSynthese(Base):
    def test_sans_droit_refuse(self):
        with self.assertRaises(PermissionError):
            tableau.synthese(self.conn, self.perc)

    def test_structure_et_nombres_seulement(self):
        d = tableau.synthese(self.conn, self.admin)
        self.assertEqual(set(d), {"annee", "finances", "logiciel"})
        self.assertEqual(set(d["logiciel"]), {"configure", "inscrits", "payes", "taux", "codes_utilises"})
        for f in d["finances"]:
            self.assertEqual(set(f), {"devise", "du", "paye", "reste", "taux"})
            self.assertLessEqual(f["paye"], f["du"])
            self.assertEqual(f["du"] - f["paye"], f["reste"])
            self.assertTrue(0 <= f["taux"] <= 100)
        texte = repr(d).lower()
        for interdit in ("matricule", "nom_complet", "n_recu"):
            self.assertNotIn(interdit, texte)

    def test_finances_coherentes_avec_les_situations(self):
        d = tableau.synthese(self.conn, self.admin)
        annee = d["annee"]
        attendu = {}
        for e in self.conn.execute("SELECT I.MATRICULE, I.N_CLASSE FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE=I.MATRICULE "
                                   "WHERE I.ANNEESCO=? AND E.ACTIF=1", (annee,)):
            for l in donnees.situation(self.conn, e["MATRICULE"], annee, e["N_CLASSE"]):
                t = attendu.setdefault(l.devise, [0, 0])
                t[0] += l.du
                t[1] += min(l.paye, l.du)
        self.assertEqual({f["devise"]: [f["du"], f["paye"]] for f in d["finances"]}, attendu)

    def test_frais_du_logiciel_taux(self):
        d = tableau.synthese(self.conn, self.admin)
        self.assertFalse(d["logiciel"]["configure"])               # aucun type de frais marqué : rien à calculer
        annee = d["annee"]
        eleves = self.conn.execute("SELECT I.MATRICULE, I.N_CLASSE FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE=I.MATRICULE "
                                   "WHERE I.ANNEESCO=? AND E.ACTIF=1 ORDER BY I.MATRICULE", (annee,)).fetchall()
        with self.conn:
            self.conn.execute("INSERT INTO TYPE_FRAIS (CODTF, DESITF, MONTANT, CODE_DEVISE, POUR_APPLI_PARENTS) "
                              "SELECT 'LOGI', 'Frais du logiciel des parents', 500, CODE_DEVISE, 1 FROM DEVISE LIMIT 1")
            devise = self.conn.execute("SELECT CODE_DEVISE FROM TYPE_FRAIS WHERE CODTF='LOGI'").fetchone()[0]
            n_perc = self.conn.execute("SELECT N_PERC FROM PERCEPTEUR LIMIT 1").fetchone()[0]
            for i, e in enumerate(eleves[:2]):
                self.conn.execute("INSERT INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE) VALUES ('LOGI',?,?,500,?)",
                                  (e["N_CLASSE"], annee, devise))
                self.conn.execute("INSERT INTO PAIEMENT (N_RECU, ANNEESCO, NUM_SEQ, DATE_PAY, MATRICULE, N_CLASSE, CODTF, CODE_DEVISE, "
                                  "MONT_PAYE, N_PERC, STATUT) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                  (f"T-{i}", annee, 9000 + i, "2026-10-01", e["MATRICULE"], e["N_CLASSE"], "LOGI", devise, 500, n_perc,
                                   "VALIDE" if i == 0 else "ANNULE"))
        d = tableau.synthese(self.conn, self.admin)["logiciel"]
        self.assertTrue(d["configure"])
        self.assertEqual(d["payes"], 1)                            # le reçu annulé ne compte pas
        self.assertEqual(d["taux"], round(100 / len(eleves)))
        for f in tableau.synthese(self.conn, self.admin)["finances"]:   # le frais du logiciel n'entre pas dans les frais scolaires
            self.assertNotIn("LOGI", repr(f))

    def test_annee_inconnue_refusee(self):
        with self.assertRaises(ErreurTableau):
            tableau.synthese(self.conn, self.admin, "1900-1901")


if __name__ == "__main__":
    unittest.main()

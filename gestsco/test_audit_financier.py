"""Tests de : Contrôle et audit financier, Recherche et filtrage des traces, Génération des rapports d'audit.
Lancer :  python test_audit_financier.py"""
import csv
import datetime
import os
import py_compile
import re
import tempfile
import unittest
from pathlib import Path

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import audit                   # noqa: E402
import audit_financier as af   # noqa: E402
import audit_rapports as ar    # noqa: E402
import audit_recherche as rech   # noqa: E402
import config                  # noqa: E402
import database                # noqa: E402
import demo                    # noqa: E402
import droits                  # noqa: E402
import encaissements           # noqa: E402
import paiements               # noqa: E402
import referentiels as ref     # noqa: E402
import security                # noqa: E402
from audit import ErreurAudit  # noqa: E402

AUJOURDHUI = datetime.date.today()
AUJ_TXT = AUJOURDHUI.strftime("%d/%m/%Y")
DEMAIN = AUJOURDHUI + datetime.timedelta(days=1)
TOUS_DROITS_ENC = ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(":memory:")
        self.login, self.mdp = demo.semer(self.conn)           # percepteur1 + 10 reçus (550,00 USD) d'aujourd'hui
        self.perc = security.authentifier(self.conn, self.login, self.mdp).session
        self.n_perc = paiements.numero_percepteur(self.conn, self.perc)
        security.creer_utilisateur(self.conn, "admin1", "Administrateur Test", "ADMINISTRATEUR", "Adm-Test#2026-xyz")
        self.admin = security.authentifier(self.conn, "admin1", "Adm-Test#2026-xyz").session
        security.creer_utilisateur(self.conn, "intend1", "Intendant Test", "INTENDANT", "Int-Test#2026-xyz")
        self.intendant = security.authentifier(self.conn, "intend1", "Int-Test#2026-xyz").session
        with self.conn:
            droits.remplacer_droits(self.conn, self.intendant.id_user, {("encaissement", d) for d in TOUS_DROITS_ENC})
        self.total = self.conn.execute("SELECT SUM(MONT_PAYE) FROM PAIEMENT").fetchone()[0]       # 55000

    def encaisser(self, encaisse=None, verse=None):
        encaisse = self.total if encaisse is None else encaisse
        return encaissements.enregistrer(self.conn, self.intendant, self.n_perc, AUJ_TXT, "USD", encaisse,
                                         encaisse if verse is None else verse)

    def controle(self, **filtres):
        return af.controle_financier(self.conn, self.admin, **filtres)

    def codes(self, **filtres):
        return sorted(a["code"] for a in self.controle(**filtres)["anomalies"])

    def sans_declencheur(self, *noms):
        """Simule une fraude : on retire le verrou de la base pour modifier hors de l'application."""
        for nom in noms:
            self.conn.execute(f"DROP TRIGGER {nom}")

    def actions(self, action):
        return self.conn.execute("SELECT * FROM JOURNAL WHERE ACTION = ? ORDER BY ID_LOG", (action,)).fetchall()


# ================================================================== 1) contrôle et audit financier
class TestDroitsEtJournal(Base):
    def test_sans_droit_refuse_partout(self):
        for appel in (lambda: af.controle_financier(self.conn, self.intendant),
                      lambda: af.liste_percepteurs(self.conn, self.intendant),
                      lambda: rech.rechercher_traces(self.conn, self.intendant),
                      lambda: rech.exporter_traces(self.conn, self.intendant, "csv"),
                      lambda: ar.generer_rapport(self.conn, self.intendant, "FINANCIER"),
                      lambda: ar.exporter_rapport(self.conn, self.intendant, "FINANCIER", "pdf")):
            with self.assertRaises(PermissionError):
                appel()

    def test_responsable_autorise_par_la_lecture(self):
        with self.conn:
            droits.remplacer_droits(self.conn, self.intendant.id_user, {("audit", "LECTURE")})
        self.assertEqual(af.controle_financier(self.conn, self.intendant)["nb_anomalies"]["ÉLEVÉE"], 0)

    def test_le_controle_est_inscrit_au_journal(self):
        self.controle()
        ligne = self.actions("AUDIT_CONTROLE_FINANCIER")[-1]
        self.assertEqual(ligne["LOGIN"], "admin1")
        self.assertIn("reçu(s)", ligne["DETAIL"])
        avant = len(self.actions("AUDIT_CONTROLE_FINANCIER"))
        af.controle_financier(self.conn, self.admin, journaliser_controle=False)
        self.assertEqual(len(self.actions("AUDIT_CONTROLE_FINANCIER")), avant)

    def test_controle_ne_modifie_rien(self):
        avant = [tuple(r) for r in self.conn.execute("SELECT * FROM PAIEMENT")]
        self.controle()
        self.assertEqual(avant, [tuple(r) for r in self.conn.execute("SELECT * FROM PAIEMENT")])


class TestPaiementsEtRecus(Base):
    def test_base_saine_une_seule_remarque_pas_d_encaissement(self):
        c = self.controle()
        self.assertEqual(len(c["paiements"]), 10)
        self.assertTrue(all(p["verification"] == "Conforme" for p in c["paiements"]))
        self.assertEqual(self.codes(), ["RECUS_SANS_ENCAISSEMENT"])               # seule remarque : rien n'est encaissé
        self.assertEqual(c["anomalies"][0]["gravite"], "FAIBLE")                  # journée en cours

    def test_tout_concorde_aucune_anomalie(self):
        self.encaisser()
        c = self.controle()
        self.assertEqual(c["anomalies"], [])
        g = c["rapprochement"][0]
        self.assertEqual((g["recus_total"], g["encaisse"], g["verse"], g["ecart_remise"], g["diff_recus"],
                          g["journal_total"], g["statut"]), (self.total, self.total, self.total, 0, 0, self.total, "Conforme"))

    def test_recu_sans_trace_au_journal(self):
        modele = self.conn.execute(
            "SELECT ANNEESCO, MATRICULE, N_CLASSE, CODTF FROM PAIEMENT WHERE N_RECU='0001'").fetchone()
        with self.conn:
            self.conn.execute(
                "INSERT INTO PAIEMENT (N_RECU, ANNEESCO, NUM_SEQ, DATE_PAY, MATRICULE, N_CLASSE, CODTF, CODE_DEVISE, MONT_PAYE, N_PERC) "
                "VALUES ('0011',?,11,?, ?, ?, ?,'USD', 100, ?)",
                (*modele[:1], database.iso(database.maintenant()), *modele[1:], self.n_perc))
        codes = self.codes()
        self.assertIn("RECU_SANS_TRACE", codes)
        self.assertIn("CAISSE_JOURNAL_DIFFERENT", codes)                           # le rapport et le journal diffèrent
        p = next(x for x in self.controle()["paiements"] if x["n_recu"] == "0011")
        self.assertEqual(p["verification"], "Anomalie")
        self.assertIn("aucune trace", p["enregistre_par"])

    def test_montant_du_recu_different_du_journal(self):
        self.sans_declencheur("PAIEMENT_NO_UPDATE")
        with self.conn:
            self.conn.execute("UPDATE PAIEMENT SET MONT_PAYE = 100 WHERE N_RECU = '0003'")
        c = self.controle()
        a = next(x for x in c["anomalies"] if x["code"] == "RECU_DIFFERENT_DU_JOURNAL")
        self.assertIn("montant", a["message"])
        self.assertIn("0003", a["message"])
        self.assertIn("CAISSE_JOURNAL_DIFFERENT", [x["code"] for x in c["anomalies"]])

    def test_recu_enregistre_par_un_autre_compte(self):
        self.sans_declencheur("PAIEMENT_NO_UPDATE")
        security.creer_utilisateur(self.conn, "perc2", "Marie Percepteur", "PERCEPTEUR", "Marie-Test#2026-xyz")
        n2 = self.conn.execute("SELECT N_PERC FROM PERCEPTEUR WHERE ID_USER = (SELECT ID_USER FROM UTILISATEUR "
                               "WHERE LOGIN = 'perc2')").fetchone()[0]
        with self.conn:
            self.conn.execute("UPDATE PAIEMENT SET N_PERC = ? WHERE N_RECU = '0005'", (n2,))
        a = next(x for x in self.controle()["anomalies"] if x["code"] == "RECU_ENREGISTRE_PAR_AUTRE")
        self.assertIn("percepteur1", a["message"])

    def test_recu_supprime_hors_application(self):
        self.sans_declencheur("PAIEMENT_NO_DELETE")
        with self.conn:
            self.conn.execute("DELETE FROM PAIEMENT WHERE N_RECU = '0010'")
        codes = self.codes()
        self.assertIn("RECU_ABSENT_DE_LA_TABLE", codes)
        self.assertIn("CAISSE_JOURNAL_DIFFERENT", codes)

    def test_trou_de_numerotation(self):
        self.sans_declencheur("PAIEMENT_NO_DELETE")
        with self.conn:
            self.conn.execute("DELETE FROM PAIEMENT WHERE N_RECU = '0004'")
        a = next(x for x in self.controle()["anomalies"] if x["code"] == "NUMEROS_MANQUANTS")
        self.assertIn("0004", a["message"])

    def test_trop_percu(self):
        with self.conn:       # le frais d'inscription de l'élève 0004 vaut 30,00 : un reçu de 200,00 inséré hors application
            self.conn.execute(
                "INSERT INTO PAIEMENT (N_RECU, ANNEESCO, NUM_SEQ, DATE_PAY, MATRICULE, N_CLASSE, CODTF, CODE_DEVISE, MONT_PAYE, N_PERC) "
                "VALUES ('0011','2026-2027',11,?, 'CSF-0001', 2, 'INSC','USD', 20000, ?)",
                (database.iso(database.maintenant()), self.n_perc))
        self.assertIn("TROP_PERCU", self.codes())

    def test_duplicata_multiples_signales(self):
        for _ in range(af.SEUIL_DUPLICATA):
            paiements.preparer_pdf(self.conn, self.perc, "0001", duplicata=True)
        a = next(x for x in self.controle()["anomalies"] if x["code"] == "RECU_DUPLICATAS_MULTIPLES")
        self.assertEqual((a["gravite"], a["reference"]), ("FAIBLE", "0001"))
        p = next(x for x in self.controle()["paiements"] if x["n_recu"] == "0001")
        self.assertEqual(p["duplicatas"], af.SEUIL_DUPLICATA)

    def test_journal_altere_signale(self):
        self.sans_declencheur("JOURNAL_NO_UPDATE")
        with self.conn:
            self.conn.execute("UPDATE JOURNAL SET DETAIL = 'falsifié' WHERE ID_LOG = 3")
        c = self.controle()
        self.assertIn("JOURNAL_ALTERE", [a["code"] for a in c["anomalies"]])
        self.assertFalse(c["journal"]["ok"])

    def test_apres_reinitialisation_les_anciennes_traces_sont_ignorees(self):
        with self.conn:
            database.journaliser(self.conn, self.admin.id_user, "admin1", "APPLICATION_REINITIALISEE", "test")
        c = self.controle()
        self.assertTrue(c["apres_reinitialisation"])
        # les 10 reçus n'ont plus de trace utile : ils sont signalés, mais la base ne plante pas
        self.assertIn("RECU_SANS_TRACE", [a["code"] for a in c["anomalies"]])


class TestEncaisseEtRemis(Base):
    def test_manquant_a_la_remise(self):
        n = self.encaisser(verse=self.total - 2000)
        c = self.controle()
        a = next(x for x in c["anomalies"] if x["code"] == "REMISE_MANQUANT")
        self.assertEqual((a["gravite"], a["reference"]), ("ÉLEVÉE", f"ENC-{n}"))
        self.assertIn("20,00", a["message"])
        s = c["synthese"][0]
        self.assertEqual((s["encaisse"], s["verse"], s["ecart_remise"], s["diff_recus"]),
                         (self.total, self.total - 2000, 2000, 0))

    def test_excedent(self):
        self.encaisser(verse=self.total + 500)
        a = next(x for x in self.controle()["anomalies"] if x["code"] == "REMISE_EXCEDENT")
        self.assertEqual(a["gravite"], "MOYENNE")

    def test_encaisse_different_des_recus(self):
        self.encaisser(encaisse=self.total - 1000)
        a = next(x for x in self.controle()["anomalies"] if x["code"] == "ENCAISSE_DIFFERENT_DES_RECUS")
        self.assertEqual(a["gravite"], "ÉLEVÉE")
        self.assertIn("-10,00", a["message"])

    def test_recus_sans_encaissement_les_jours_passes_sont_moyens(self):
        with self.conn:        # tous les reçus passent à hier
            self.conn.execute("DROP TRIGGER PAIEMENT_NO_UPDATE")
            hier = database.iso(database.maintenant() - datetime.timedelta(days=2))
            self.conn.execute("UPDATE PAIEMENT SET DATE_PAY = ?", (hier,))
        self.assertIn("RECUS_SANS_ENCAISSEMENT", self.codes())
        a = next(x for x in self.controle()["anomalies"] if x["code"] == "RECUS_SANS_ENCAISSEMENT")
        self.assertEqual(a["gravite"], "MOYENNE")

    def test_encaissement_sans_recu(self):
        with self.conn:
            self.conn.execute("UPDATE PERCEPTEUR SET N_PERC = N_PERC")           # table prête
        security.creer_utilisateur(self.conn, "perc2", "Marie Percepteur", "PERCEPTEUR", "Marie-Test#2026-xyz")
        n2 = self.conn.execute("SELECT MAX(N_PERC) FROM PERCEPTEUR").fetchone()[0]
        encaissements.enregistrer(self.conn, self.intendant, n2, AUJ_TXT, "USD", 5000, 5000)
        self.assertIn("ENCAISSEMENT_SANS_RECU", self.codes())

    def test_encaissements_multiples_et_somme(self):
        self.encaisser(encaisse=30000)
        self.encaisser(encaisse=self.total - 30000)
        c = self.controle()
        self.assertIn("ENCAISSEMENTS_MULTIPLES", [a["code"] for a in c["anomalies"]])
        self.assertNotIn("ENCAISSE_DIFFERENT_DES_RECUS", [a["code"] for a in c["anomalies"]])     # la somme concorde

    def test_ecart_incoherent_et_encaissement_modifie_hors_application(self):
        n = self.encaisser()
        with self.conn:
            self.conn.execute("UPDATE ENCAISSEMENT SET MONT_VERSE = 100, ECART = 0 WHERE N_ENC = ?", (n,))
        codes = self.codes()
        self.assertIn("ENCAISSEMENT_ECART_INCOHERENT", codes)
        self.assertIn("ENCAISSEMENT_DIFFERENT_DU_JOURNAL", codes)

    def test_encaissement_sans_trace(self):
        with self.conn:
            self.conn.execute("INSERT INTO ENCAISSEMENT (DATE_ENC, N_PERC, CODE_DEVISE, MONT_ENCAISSE, MONT_VERSE, ECART, "
                              "SAISI_PAR, DATE_SAISIE) VALUES (?,?,?,?,?,?,?,?)",
                              (AUJOURDHUI.isoformat(), self.n_perc, "USD", self.total, self.total, 0, "intend1",
                               database.iso(database.maintenant())))
        self.assertIn("ENCAISSEMENT_SANS_TRACE", self.codes())

    def test_encaissement_modifie_par_l_application_reste_conforme(self):
        n = self.encaisser(encaisse=self.total - 500)
        encaissements.modifier(self.conn, self.intendant, n, self.n_perc, AUJ_TXT, "USD", self.total, self.total)
        codes = self.codes()
        self.assertNotIn("ENCAISSEMENT_DIFFERENT_DU_JOURNAL", codes)
        self.assertNotIn("ENCAISSEMENT_SANS_TRACE", codes)


class TestAnnulationsEtCorrections(Base):
    def test_annulation_qui_quand_pourquoi_et_delai(self):
        ref.annuler_paiement(self.conn, self.admin, "0002", "Erreur de saisie du montant")
        c = self.controle()
        a = c["annulations"][0]
        self.assertEqual((a["n_recu"], a["montant"], a["motif"]), ("0002", 8000, "Erreur de saisie du montant"))
        self.assertIn("percepteur1", a["enregistre_par"])
        self.assertIn("admin1", a["annule_par"])
        self.assertTrue(a["delai"])
        s = c["synthese"][0]
        self.assertEqual((s["annules_nb"], s["recus_nb"], s["recus_total"]), (1, 9, self.total - 8000))

    def test_annulation_apres_encaissement(self):
        self.encaisser()
        ref.annuler_paiement(self.conn, self.admin, "0002", "Erreur de saisie du montant")
        codes = self.codes()
        self.assertIn("ANNULATION_APRES_ENCAISSEMENT", codes)
        self.assertIn("ENCAISSE_DIFFERENT_DES_RECUS", codes)                      # l'encaissement ne suit plus les reçus

    def test_annulation_avant_encaissement_est_normale(self):
        ref.annuler_paiement(self.conn, self.admin, "0002", "Erreur de saisie du montant")
        self.encaisser(encaisse=self.total - 8000)
        self.assertEqual(self.controle()["anomalies"], [])

    def test_annulation_hors_application(self):
        with self.conn:
            self.conn.execute("UPDATE PAIEMENT SET STATUT = 'ANNULE', MOTIF_ANNULATION = 'x', DATE_ANNULATION = ?, "
                              "ANNULE_PAR = 'z' WHERE N_RECU = '0002'", (database.iso(database.maintenant()),))
        self.assertIn("RECU_ANNULE_SANS_TRACE", self.codes())

    def test_annulations_nombreuses(self):
        for n in ("0001", "0002", "0003"):
            ref.annuler_paiement(self.conn, self.admin, n, "Erreur de saisie")
        a = next(x for x in self.controle()["anomalies"] if x["code"] == "ANNULATIONS_NOMBREUSES")
        self.assertIn("3 reçu(s) annulé(s) sur 10", a["message"])

    def test_correction_reduisant_l_ecart(self):
        n = self.encaisser(verse=self.total - 3000)
        encaissements.modifier(self.conn, self.intendant, n, self.n_perc, AUJ_TXT, "USD", self.total, self.total - 100)
        c = self.controle()
        corr = [x for x in c["corrections"] if x["nature"] == "Encaissement modifié"]
        self.assertEqual(len(corr), 1)
        self.assertIn("écart 30,00", corr[0]["avant"])
        self.assertIn("écart 1,00", corr[0]["apres"])
        self.assertEqual(corr[0]["par_login"], "intend1")
        a = next(x for x in c["anomalies"] if x["code"] == "ENCAISSEMENT_CORRIGE")
        self.assertEqual(a["gravite"], "MOYENNE")
        self.assertIn("réduit", a["message"])

    def test_encaissement_supprime_avec_ecart(self):
        n = self.encaisser(verse=self.total - 3000)
        encaissements.supprimer(self.conn, self.intendant, n)
        c = self.controle()
        self.assertEqual([x["nature"] for x in c["corrections"]], ["Encaissement supprimé"])
        a = next(x for x in c["anomalies"] if x["code"] == "ENCAISSEMENT_SUPPRIME")
        self.assertEqual(a["gravite"], "ÉLEVÉE")                                # il présentait un écart
        self.assertEqual(c["rapprochement"][0]["encaisse"], None)

    def test_modification_de_tarif_listee(self):
        ref.enregistrer(self.conn, self.admin, "types_frais", {"DESITF": "Frais d'inscription", "MONTANT": "35",
                                                                "CODE_DEVISE": "USD"}, ("INSC",))
        corr = [x for x in self.controle()["corrections"] if "Types de frais" in x["nature"]]
        self.assertEqual(len(corr), 1)
        self.assertIn("30,00 -> 35,00", corr[0]["apres"])                       # montants lisibles, pas en centimes


class TestRapportsJournaliers(Base):
    def test_rapport_imprime_conforme(self):
        paiements.preparer_rapport_pdf(self.conn, self.perc, AUJOURDHUI)
        encaissements.preparer_rapport_pdf(self.conn, self.admin, AUJOURDHUI)
        self.encaisser()
        c = self.controle()
        self.assertEqual([r["statut"] for r in c["rapports"]], ["Conforme", "Conforme"])
        self.assertEqual(c["anomalies"], [])
        caisse = next(r for r in c["rapports"] if r["type"] == "Rapport de caisse")
        self.assertEqual((caisse["imprime_nb"], caisse["actuel_nb"], caisse["imprime_total"]), (10, 10, "550,00 USD"))

    def test_rapport_perime_apres_annulation(self):
        paiements.preparer_rapport_pdf(self.conn, self.perc, AUJOURDHUI)
        ref.annuler_paiement(self.conn, self.admin, "0002", "Erreur de saisie")
        c = self.controle()
        self.assertEqual(c["rapports"][0]["statut"], "Conforme, modifié depuis")
        self.assertIn("RAPPORT_PERIME_ANNULATION", [a["code"] for a in c["anomalies"]])
        self.assertNotIn("RAPPORT_NON_CONFORME", [a["code"] for a in c["anomalies"]])      # l'écart est expliqué

    def test_rapport_perime_apres_nouveau_paiement(self):
        paiements.preparer_rapport_pdf(self.conn, self.perc, AUJOURDHUI)
        paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", "2026-2027", "EXAM", 1500)
        a = next(x for x in self.controle()["anomalies"] if x["code"] == "RAPPORT_PERIME_AJOUT")
        self.assertEqual(a["gravite"], "FAIBLE")

    def test_rapport_non_conforme_si_un_montant_change_apres(self):
        paiements.preparer_rapport_pdf(self.conn, self.perc, AUJOURDHUI)
        self.sans_declencheur("PAIEMENT_NO_UPDATE")
        with self.conn:
            self.conn.execute("UPDATE PAIEMENT SET MONT_PAYE = MONT_PAYE - 500 WHERE N_RECU = '0003'")
        c = self.controle()
        self.assertEqual(c["rapports"][0]["statut"], "Écart")
        a = next(x for x in c["anomalies"] if x["code"] == "RAPPORT_NON_CONFORME")
        self.assertEqual(a["gravite"], "ÉLEVÉE")
        self.assertIn("550,00 USD", a["message"])

    def test_rapport_global_encaissement_supprime_depuis(self):
        n = self.encaisser()
        encaissements.preparer_rapport_pdf(self.conn, self.admin, AUJOURDHUI)
        encaissements.supprimer(self.conn, self.intendant, n)
        self.assertNotIn("RAPPORT_NON_CONFORME", self.codes())                    # la suppression est connue du journal

    def test_ancienne_trace_non_comparable(self):
        with self.conn:
            database.journaliser(self.conn, self.perc.id_user, "percepteur1", "RAPPORT_CAISSE_IMPRIME",
                                 f"{AUJOURDHUI.isoformat()} | 10 reçu(s)")
        c = self.controle()
        self.assertEqual(c["rapports"][0]["statut"], "Non comparable")
        self.assertNotIn("RAPPORT_NON_CONFORME", [a["code"] for a in c["anomalies"]])


class TestFiltresDuControle(Base):
    def test_periode(self):
        self.encaisser(verse=self.total - 100)
        self.assertEqual(self.controle(du=DEMAIN)["paiements"], [])
        self.assertEqual(self.controle(du=DEMAIN)["anomalies"], [])
        self.assertEqual(len(self.controle(du=AUJOURDHUI, au=AUJOURDHUI)["paiements"]), 10)
        with self.assertRaises(ErreurAudit):
            self.controle(du=DEMAIN, au=AUJOURDHUI)
        with self.assertRaises(ErreurAudit):
            self.controle(du="2026-01-01")

    def test_percepteur_et_devise(self):
        self.assertEqual(len(self.controle(n_perc=self.n_perc)["paiements"]), 10)
        self.assertEqual(self.controle(n_perc=self.n_perc + 99 if False else self.n_perc, devise="CDF")["paiements"], [])
        with self.assertRaises(ErreurAudit):
            self.controle(n_perc=999)
        with self.assertRaises(ErreurAudit):
            self.controle(devise="XYZ")
        self.assertEqual([p[0] for p in af.liste_percepteurs(self.conn, self.admin)], [self.n_perc])
        self.assertEqual(af.liste_devises(self.conn, self.admin), ["CDF", "USD"])

    def test_numerotation_non_controlee_sur_un_sous_ensemble(self):
        self.sans_declencheur("PAIEMENT_NO_DELETE")
        with self.conn:
            self.conn.execute("DELETE FROM PAIEMENT WHERE N_RECU = '0004'")
        self.assertIn("NUMEROS_MANQUANTS", self.codes())
        self.assertNotIn("NUMEROS_MANQUANTS", self.codes(devise="USD"))


# ================================================================== 2) recherche et filtrage des traces
class TestRecherche(Base):
    def test_chaque_action_a_un_module(self):
        for code in audit.ACTIONS:
            self.assertIn(code, rech.MODULE_DE_L_ACTION, code)
            self.assertIn(rech.module_de(code), rech.MODULES_TRACES)
        self.assertEqual(rech.module_de("CODE_INCONNU"), "autre")
        libelles = [l for _c, l in rech.liste_actions()]
        self.assertEqual(len(libelles), len(set(libelles)))                         # la liste déroulante a des libellés uniques

    def test_filtre_utilisateur(self):
        r = rech.rechercher_traces(self.conn, self.admin, login="PERCEPTEUR1")
        self.assertGreater(r["total"], 0)
        self.assertTrue(all(l["login"] == "percepteur1" for l in r["lignes"]))

    def test_filtre_periode_et_date_unique(self):
        self.assertGreater(rech.rechercher_traces(self.conn, self.admin, du=AUJOURDHUI, au=AUJOURDHUI)["total"], 0)
        self.assertEqual(rech.rechercher_traces(self.conn, self.admin, du=DEMAIN)["total"], 0)
        with self.assertRaises(ErreurAudit):
            rech.rechercher_traces(self.conn, self.admin, du=DEMAIN, au=AUJOURDHUI)

    def test_filtre_module(self):
        r = rech.rechercher_traces(self.conn, self.admin, module="paiement")
        self.assertGreater(r["total"], 0)
        self.assertTrue(all(l["module"] == "paiement" and l["module_txt"] == "Paiement des frais" for l in r["lignes"]))
        self.assertTrue(all(l["action"] != "CONNEXION_OK" for l in r["lignes"]))
        self.assertEqual(rech.rechercher_traces(self.conn, self.admin, module="acces")["lignes"][0]["action"], "COMPTE_CREE")
        with self.assertRaises(ErreurAudit):
            rech.rechercher_traces(self.conn, self.admin, module="inexistant")

    def test_module_autre_prend_les_codes_inconnus(self):
        with self.conn:
            database.journaliser(self.conn, None, "x", "ACTION_D_UNE_VERSION_FUTURE", "d")
        r = rech.rechercher_traces(self.conn, self.admin, module="autre")
        self.assertEqual([l["action"] for l in r["lignes"]], ["ACTION_D_UNE_VERSION_FUTURE"])

    def test_filtre_type_d_action(self):
        r = rech.rechercher_traces(self.conn, self.admin, action="PAIEMENT_ENREGISTRE")
        self.assertEqual(r["total"], 10)
        with self.assertRaises(ErreurAudit):
            rech.rechercher_traces(self.conn, self.admin, action="N_IMPORTE_QUOI")
        with self.assertRaises(ErreurAudit):                                         # action d'un autre module
            rech.rechercher_traces(self.conn, self.admin, module="carte", action="PAIEMENT_ENREGISTRE")
        self.assertEqual(rech.rechercher_traces(self.conn, self.admin, module="paiement",
                                                action="PAIEMENT_ENREGISTRE")["total"], 10)

    def test_numero_de_recu_toutes_ses_traces(self):
        paiements.preparer_pdf(self.conn, self.perc, "0003", duplicata=True)
        ref.annuler_paiement(self.conn, self.admin, "0003", "Erreur de saisie")
        for saisie in ("0003", "3"):
            r = rech.rechercher_traces(self.conn, self.admin, n_recu=saisie)
            self.assertEqual(sorted(l["action"] for l in r["lignes"]),
                             ["DUPLICATA_IMPRIME", "PAIEMENT_ANNULE", "PAIEMENT_ENREGISTRE"], saisie)
            self.assertTrue(all(l["n_recu"] == "0003" and l["matricule"] == "CSF-0001" for l in r["lignes"]))
        self.assertEqual(rech.rechercher_traces(self.conn, self.admin, n_recu="9999")["total"], 0)

    def test_matricule_trouve_paiements_consultations_et_annulations(self):
        paiements.journaliser_consultation_recus(self.conn, self.perc, "CSF-0002")
        ref.annuler_paiement(self.conn, self.admin, "0006", "Erreur de saisie")           # le reçu 0006 est celui de CSF-0001
        r = rech.rechercher_traces(self.conn, self.admin, matricule="CSF-0001")
        actions = [l["action"] for l in r["lignes"]]
        self.assertEqual(actions.count("PAIEMENT_ENREGISTRE"), 6)
        self.assertIn("PAIEMENT_ANNULE", actions)
        self.assertNotIn("RECUS_ELEVE_CONSULTES", actions)                                  # c'était CSF-0002
        self.assertTrue(all(l["matricule"] == "CSF-0001" for l in r["lignes"]))
        self.assertEqual(rech.rechercher_traces(self.conn, self.admin, matricule="CSF-0002")["lignes"][0]["action"],
                         "RECUS_ELEVE_CONSULTES")

    def test_matricule_par_fragment_de_nom_sans_accents(self):
        r = rech.rechercher_traces(self.conn, self.admin, matricule="emile")
        self.assertGreater(r["total"], 0)
        self.assertTrue(all(l["matricule"] == "CSF-0003" for l in r["lignes"]))

    def test_matricule_ne_confond_pas_les_numeros_proches(self):
        with self.conn:
            database.journaliser(self.conn, None, "x", "FICHE_CARTE_CONSULTEE", "CSF-00011")
            database.journaliser(self.conn, None, "x", "FICHE_CARTE_CONSULTEE", "CSF-0001")
        r = rech.rechercher_traces(self.conn, self.admin, matricule="CSF-0001", action="FICHE_CARTE_CONSULTEE")
        self.assertEqual([l["detail"] for l in r["lignes"]], ["CSF-0001"])

    def test_eleve_supprime_reste_retrouvable_par_son_matricule(self):
        cle = ref.enregistrer(self.conn, self.admin, "eleves", {"NOM": "SUPPRIME"})
        ref.supprimer(self.conn, self.admin, "eleves", cle)
        r = rech.rechercher_traces(self.conn, self.admin, matricule=cle[0])
        self.assertEqual({l["action"] for l in r["lignes"]}, {"REF_AJOUT", "REF_SUPPRESSION"})

    def test_filtres_combines(self):
        r = rech.rechercher_traces(self.conn, self.admin, login="percepteur1", module="paiement",
                                   action="PAIEMENT_ENREGISTRE", matricule="CSF-0002", du=AUJOURDHUI, au=AUJOURDHUI)
        self.assertEqual(r["total"], 2)                                                  # CSF-0002 : deux reçus
        self.assertTrue(all(l["login"] == "percepteur1" and l["matricule"] == "CSF-0002" for l in r["lignes"]))
        self.assertEqual(rech.rechercher_traces(self.conn, self.admin, login="admin1", matricule="CSF-0002")["total"], 0)
        self.assertEqual(rech.rechercher_traces(self.conn, self.admin, n_recu="0001", matricule="CSF-0002")["total"], 0)

    def test_texte_libre_et_caracteres_speciaux(self):
        self.assertGreater(rech.rechercher_traces(self.conn, self.admin, texte="enregistrement paiement")["total"], 0)
        self.assertGreater(rech.rechercher_traces(self.conn, self.admin, texte="Paiement des frais")["total"], 0)  # module
        for texte in ("100%", "a_b", "'; DROP TABLE JOURNAL; --", "\\"):
            self.assertIsInstance(rech.rechercher_traces(self.conn, self.admin, texte=texte, matricule="CSF-0001 (")["total"], int)

    def test_limite_total_et_ordre(self):
        r = rech.rechercher_traces(self.conn, self.admin, limite=3)
        self.assertEqual(len(r["lignes"]), 3)
        self.assertGreater(r["total"], 3)
        ids = [l["id"] for l in r["lignes"]]
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertEqual(len(rech.rechercher_traces(self.conn, self.admin, limite=None)["lignes"]),
                         rech.rechercher_traces(self.conn, self.admin)["total"])

    def test_recherche_ciblee_inscrite_au_journal_pas_la_generale(self):
        rech.rechercher_traces(self.conn, self.admin, login="percepteur1")
        self.assertEqual(self.actions("AUDIT_RECHERCHE_TRACES"), [])
        rech.rechercher_traces(self.conn, self.admin, n_recu="0001", matricule="CSF-0001")
        ligne = self.actions("AUDIT_RECHERCHE_TRACES")[-1]
        self.assertEqual(ligne["LOGIN"], "admin1")
        self.assertIn("reçu : 0001", ligne["DETAIL"])
        self.assertIn("élève : CSF-0001", ligne["DETAIL"])

    def test_filtres_decrits_en_clair(self):
        r = rech.rechercher_traces(self.conn, self.admin, login="admin1", module="paiement", n_recu="1", du=AUJOURDHUI)
        texte = " ; ".join(rech.decrire_filtres(r))
        for attendu in ("Utilisateur : admin1", "Module : Paiement des frais", "N° de reçu : 1", "depuis le"):
            self.assertIn(attendu, texte)

    def test_export_csv_et_pdf(self):
        chemin = rech.exporter_traces(self.conn, self.admin, "csv", module="paiement", matricule="CSF-0001")
        lignes = list(csv.reader(open(chemin, encoding="utf-8-sig", newline=""), delimiter=";"))
        self.assertEqual(lignes[0][:6], ["Date et heure", "Utilisateur", "Module", "Action", "N° reçu", "Matricule"])
        attendu = rech.rechercher_traces(self.conn, self.admin, module="paiement", matricule="CSF-0001")["total"]
        self.assertEqual(len(lignes) - 1, attendu)
        self.assertTrue(all(l[5] == "CSF-0001" for l in lignes[1:]))
        brut = open(rech.exporter_traces(self.conn, self.admin, "pdf", login="percepteur1"), "rb").read()
        self.assertTrue(brut.startswith(b"%PDF-1.4") and brut.rstrip().endswith(b"%%EOF"))
        self.assertIn("Recherche dans les traces", self.actions("AUDIT_EXPORTE")[-1]["DETAIL"])
        with self.assertRaises(ErreurAudit):
            rech.exporter_traces(self.conn, self.admin, "csv", du=DEMAIN)


# ================================================================== 3) génération des rapports d'audit
class TestRapports(Base):
    def preparer_anomalies(self):
        self.encaisser(verse=self.total - 2000)
        ref.annuler_paiement(self.conn, self.admin, "0002", "Erreur de saisie")

    def test_quatre_types_et_type_inconnu(self):
        self.assertEqual(set(ar.TYPES_RAPPORT), {"GENERAL", "FINANCIER", "ANOMALIES", "COMPLET"})
        for t in ar.TYPES_RAPPORT:
            d = ar.generer_rapport(self.conn, self.admin, t)
            self.assertEqual(d["titre"], ar.TYPES_RAPPORT[t])
            self.assertTrue(d["sections"] and d["resume"])
            self.assertTrue(d["journal"]["ok"])
        with self.assertRaises(ErreurAudit):
            ar.generer_rapport(self.conn, self.admin, "AUTRE")

    def test_rapport_financier_contient_tout_le_perimetre(self):
        self.preparer_anomalies()
        d = ar.generer_rapport(self.conn, self.admin, "FINANCIER")
        titres = " | ".join(s["titre"] for s in d["sections"])
        for attendu in ("Synthèse financière", "Rapprochement journalier", "Paiements enregistrés", "Annulations",
                        "Corrections", "Rapports journaliers imprimés", "Anomalies financières"):
            self.assertIn(attendu, titres)
        section = {s["titre"].split(" :")[0].split(",")[0]: s for s in d["sections"]}
        self.assertEqual(len(section["Paiements enregistrés et reçus"]["lignes"]), 10)
        self.assertEqual(len(section["Annulations de reçus"]["lignes"]), 1)
        self.assertGreaterEqual(d["nb_anomalies"]["ÉLEVÉE"], 1)
        self.assertTrue(any("manquant" in v for _l, v in d["resume"]))

    def test_rapport_des_anomalies(self):
        self.preparer_anomalies()
        d = ar.generer_rapport(self.conn, self.admin, "ANOMALIES")
        s = next(x for x in d["sections"] if x["titre"] == "Anomalies financières")
        self.assertEqual(s["colonnes"][-1][0], "Piste de vérification")
        self.assertEqual(len(s["lignes"]), sum(d["nb_anomalies"].values()))
        self.assertEqual(s["lignes"][0][0], "ÉLEVÉE")                                   # la plus grave en premier
        self.assertEqual(s["couleurs"][0], "rouge")
        for ligne, a in zip(s["lignes"], self.controle_anomalies()):
            self.assertEqual(ligne[-1], ar.CONSEILS.get(a["code"], ar.CONSEIL_PAR_DEFAUT))

    def controle_anomalies(self):
        return af.controle_financier(self.conn, self.admin, journaliser_controle=False)["anomalies"]

    def test_chaque_anomalie_possible_a_une_piste(self):
        source = Path(af.__file__).read_text(encoding="utf-8")
        codes = set(re.findall(r'(?:signaler|sig)\(\s*"([A-Z_]+)"', source))
        self.assertGreater(len(codes), 20)
        self.assertEqual(sorted(c for c in codes if c not in ar.CONSEILS), [])

    def test_anomalie_apres_corrections_sans_anomalie(self):
        self.encaisser()
        d = ar.generer_rapport(self.conn, self.admin, "ANOMALIES")
        s = next(x for x in d["sections"] if x["titre"] == "Anomalies financières")
        self.assertEqual(s["lignes"], [])
        self.assertIn("Aucune anomalie", s["vide"])

    def test_rapport_general_toutes_les_operations(self):
        ref.annuler_paiement(self.conn, self.admin, "0002", "Erreur de saisie")
        security.authentifier(self.conn, "fantome", "Mauvais-mdp#2026")
        total = self.conn.execute("SELECT COUNT(*) FROM JOURNAL").fetchone()[0]           # avant la génération
        d = ar.generer_rapport(self.conn, self.admin, "GENERAL", journaliser_generation=False)
        par = {s["titre"].split(" (")[0]: s for s in d["sections"]}
        self.assertGreaterEqual(total, 15)
        self.assertEqual(len(par["Détail de toutes les opérations"]["lignes"]), total)
        self.assertEqual(sum(int(l[1]) for l in par["Opérations par catégorie"]["lignes"]), total)
        self.assertEqual(sum(int(l[1]) for l in par["Opérations par module"]["lignes"]), total)
        sensibles = next(s for t, s in par.items() if t.startswith("Opérations sensibles"))
        actions = " ".join(l[3] for l in sensibles["lignes"])
        self.assertIn("Annulation d'un paiement", actions)
        self.assertIn("Échec de connexion", actions)
        users = {l[0] for l in par["Activité par utilisateur"]["lignes"]}
        self.assertTrue({"percepteur1", "admin1", "fantome"} <= users)
        d2 = ar.generer_rapport(self.conn, self.admin, "GENERAL", avec_detail=False)
        self.assertFalse(any(s["titre"].startswith("Détail") for s in d2["sections"]))
        d3 = ar.generer_rapport(self.conn, self.admin, "GENERAL", login="percepteur1")
        self.assertTrue(all(l[0] == "percepteur1" for l in
                            next(s for s in d3["sections"] if s["titre"].startswith("Activité"))["lignes"]))

    def test_rapport_complet_reunit_tout(self):
        self.preparer_anomalies()
        d = ar.generer_rapport(self.conn, self.admin, "COMPLET")
        titres = [s["titre"] for s in d["sections"]]
        self.assertEqual(titres[0], "Répartition des anomalies par catégorie")
        self.assertTrue(any(t.startswith("Anomalies") for t in titres))
        self.assertTrue(any(t.startswith("Paiements") for t in titres))
        self.assertTrue(any(t.startswith("Détail de toutes") for t in titres))
        self.assertEqual(sum(1 for t in titres if t == "Anomalies financières"), 1)

    def test_periode_et_filtres_dans_le_rapport(self):
        d = ar.generer_rapport(self.conn, self.admin, "FINANCIER", du=DEMAIN, devise="USD")
        self.assertIn("Période : depuis le", " ".join(d["filtres"]))
        self.assertIn("Devise : USD", d["filtres"])
        self.assertEqual(next(s for s in d["sections"] if s["titre"].startswith("Paiements"))["lignes"], [])

    def test_generation_et_exportation_inscrites_au_journal(self):
        ar.generer_rapport(self.conn, self.admin, "FINANCIER")
        self.assertIn("Rapport des opérations financières", self.actions("AUDIT_RAPPORT_GENERE")[-1]["DETAIL"])
        ar.exporter_rapport(self.conn, self.admin, "FINANCIER", "csv")
        self.assertEqual(len(self.actions("AUDIT_RAPPORT_GENERE")), 1)                # l'export n'ajoute pas une consultation
        ligne = self.actions("AUDIT_EXPORTE")[-1]
        self.assertEqual(ligne["LOGIN"], "admin1")
        self.assertIn("CSV", ligne["DETAIL"])

    def test_export_pdf_de_chaque_rapport(self):
        self.preparer_anomalies()
        for t in ar.TYPES_RAPPORT:
            chemin = ar.exporter_rapport(self.conn, self.admin, t, "pdf")
            brut = open(chemin, "rb").read()
            self.assertTrue(brut.startswith(b"%PDF-1.4") and brut.rstrip().endswith(b"%%EOF"), t)
            self.assertIn(b"/MediaBox [0 0 841.89 595.28]", brut)
            self.assertIn(b"Date et signature", brut)                                  # cases de signature
            self.assertIn(b"Page 1 /", brut)
        brut = open(ar.exporter_rapport(self.conn, self.admin, "ANOMALIES", "pdf"), "rb").read()
        self.assertIn(b"ANOMALIES FINANCI", brut.upper())

    def test_export_pdf_plusieurs_pages(self):
        with self.conn:
            for i in range(300):
                database.journaliser(self.conn, None, "x", "CONNEXION_ECHEC", f"tentative {i} " + "mot " * 30)
        brut = open(ar.exporter_rapport(self.conn, self.admin, "GENERAL", "pdf"), "rb").read()
        pages = int(re.search(rb"/Count (\d+)", brut).group(1))
        self.assertGreater(pages, 5)
        self.assertIn(f"Page {pages} / {pages}".encode(), brut)

    def test_export_csv_sections_et_montants_negatifs(self):
        self.encaisser(verse=self.total + 1500)                                           # excédent : écart négatif
        chemin = ar.exporter_rapport(self.conn, self.admin, "FINANCIER", "csv")
        brut = open(chemin, "rb").read()
        self.assertTrue(brut.startswith(b"\xef\xbb\xbf"))
        lignes = list(csv.reader(open(chemin, encoding="utf-8-sig", newline=""), delimiter=";"))
        self.assertEqual(lignes[0], ["Rapport des opérations financières"])
        titres = [l[0] for l in lignes if len(l) == 1 and l[0]]
        self.assertIn("Anomalies financières", titres)
        self.assertIn("Synthèse", titres)
        synthese = next(l for l in lignes if l and l[0] == "Devise")
        ligne = lignes[lignes.index(synthese) + 1]
        self.assertIn("-15,00", ligne)                                                    # non altéré par la protection

    def test_export_csv_neutralise_les_formules(self):
        with self.conn:
            database.journaliser(self.conn, None, "=CMD()", "CONNEXION_ECHEC", "+1+1")
        chemin = ar.exporter_rapport(self.conn, self.admin, "GENERAL", "csv")
        texte = open(chemin, encoding="utf-8-sig").read()
        self.assertIn("'=CMD()", texte)
        self.assertIn("'+1+1", texte)
        self.assertNotIn(";=CMD()", texte)

    def test_format_inconnu(self):
        with self.assertRaises(ErreurAudit):
            ar.exporter_rapport(self.conn, self.admin, "FINANCIER", "docx")

    def test_les_exports_vont_dans_le_dossier_d_audit(self):
        chemin = ar.exporter_rapport(self.conn, self.admin, "FINANCIER", "csv")
        self.assertEqual(os.path.dirname(chemin), str(config.DOSSIER_AUDIT))
        self.assertIn("Rapport_financier_", os.path.basename(chemin))


class TestEcrans(unittest.TestCase):
    def test_le_code_des_ecrans_se_compile(self):
        """tkinter n'est pas toujours installé là où les tests tournent : on vérifie au moins la syntaxe."""
        for nom in ("ecrans_audit.py", "ecrans_audit_financier.py"):
            compile((Path(__file__).parent / nom).read_text(encoding="utf-8"), nom, "exec")


if __name__ == "__main__":
    unittest.main()

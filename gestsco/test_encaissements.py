"""Tests du module Encaissement des fonds perçus et de la suppression avec données liées.
Lancer :  python test_encaissements.py"""
import datetime
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import argent          # noqa: E402
import database        # noqa: E402
import demo            # noqa: E402
import droits          # noqa: E402
import encaissements   # noqa: E402
import paiements       # noqa: E402
import referentiels as ref   # noqa: E402
import security        # noqa: E402
from encaissements import ErreurEncaissement   # noqa: E402
from security import Session   # noqa: E402

AUJOURDHUI = datetime.date.today()
AUJ_TXT = AUJOURDHUI.strftime("%d/%m/%Y")


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(":memory:")
        self.login, self.mdp = demo.semer(self.conn)           # crée percepteur1 + paiements d'aujourd'hui
        self.perc = security.authentifier(self.conn, self.login, self.mdp).session
        self.n_perc = paiements.numero_percepteur(self.conn, self.perc)
        # un administrateur et un compte « intendant » sans droit d'ajout
        security.creer_utilisateur(self.conn, "admin1", "Administrateur Test", "ADMINISTRATEUR", "Adm-Test#2026-xyz")
        self.admin = security.authentifier(self.conn, "admin1", "Adm-Test#2026-xyz").session
        security.creer_utilisateur(self.conn, "intend1", "Intendant Test", "INTENDANT", "Int-Test#2026-xyz")
        self.intendant = security.authentifier(self.conn, "intend1", "Int-Test#2026-xyz").session

    def donner(self, session, *accordes):
        with self.conn:
            droits.remplacer_droits(self.conn, session.id_user, {("encaissement", d) for d in accordes})


class TestEnregistrement(Base):
    def test_ecart_calcule(self):
        self.assertEqual(encaissements.calculer_ecart(10000, 9000), 1000)
        self.assertEqual(encaissements.calculer_ecart(10000, 11000), -1000)
        self.assertEqual(encaissements.etiquette_ecart(1000), "Manquant")
        self.assertEqual(encaissements.etiquette_ecart(-1), "Excédent")
        self.assertEqual(encaissements.etiquette_ecart(0), "Aucun écart")

    def test_enregistrer_et_relire(self):
        self.donner(self.intendant, "LECTURE", "AJOUT")
        n = encaissements.enregistrer(self.conn, self.intendant, self.n_perc, AUJ_TXT, "USD", 25000, 24000)
        e = encaissements.charger(self.conn, self.intendant, n)
        self.assertEqual((e["encaisse"], e["verse"], e["ecart"], e["devise"]), (25000, 24000, 1000, "USD"))
        self.assertEqual(e["percepteur"], "Percepteur Démonstration")
        self.assertEqual(e["jour"], AUJOURDHUI)

    def test_droit_ajout_obligatoire(self):
        self.donner(self.intendant, "LECTURE")
        with self.assertRaises(PermissionError):
            encaissements.enregistrer(self.conn, self.intendant, self.n_perc, AUJ_TXT, "USD", 100, 100)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ENCAISSEMENT").fetchone()[0], 0)

    def test_sans_droit_du_tout(self):
        with self.assertRaises(PermissionError):
            encaissements.lister(self.conn, self.intendant)
        with self.assertRaises(PermissionError):
            encaissements.rapport_global(self.conn, self.intendant, AUJ_TXT)

    def test_admin_a_tous_les_droits(self):
        n = encaissements.enregistrer(self.conn, self.admin, self.n_perc, AUJ_TXT, "USD", 500, 500)
        encaissements.modifier(self.conn, self.admin, n, self.n_perc, AUJ_TXT, "USD", 600, 500)
        encaissements.supprimer(self.conn, self.admin, n)

    def test_controles(self):
        a = self.admin
        cas = [
            (None, AUJ_TXT, "USD", 100, 100),                       # pas de percepteur
            (self.n_perc, "pas une date", "USD", 100, 100),
            (self.n_perc, (AUJOURDHUI + datetime.timedelta(days=2)).strftime("%d/%m/%Y"), "USD", 100, 100),   # futur
            (self.n_perc, AUJ_TXT, "", 100, 100),                   # pas de devise
            (self.n_perc, AUJ_TXT, "XXX", 100, 100),                # devise inconnue
            (self.n_perc, AUJ_TXT, "USD", 0, 0),                    # encaissé nul
            (self.n_perc, AUJ_TXT, "USD", 100, -1),                 # versé négatif
            (999, AUJ_TXT, "USD", 100, 100),                        # percepteur inconnu
        ]
        for c in cas:
            with self.assertRaises(ErreurEncaissement, msg=str(c)):
                encaissements.enregistrer(self.conn, a, *c)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ENCAISSEMENT").fetchone()[0], 0)

    def test_verse_zero_permis_et_excedent(self):
        n = encaissements.enregistrer(self.conn, self.admin, self.n_perc, AUJ_TXT, "USD", 5000, 0)
        self.assertEqual(encaissements.charger(self.conn, self.admin, n)["ecart"], 5000)
        n = encaissements.enregistrer(self.conn, self.admin, self.n_perc, AUJ_TXT, "USD", 5000, 6000)
        self.assertEqual(encaissements.charger(self.conn, self.admin, n)["ecart"], -1000)

    def test_devise_et_percepteur_desactives(self):
        with self.conn:
            self.conn.execute("UPDATE DEVISE SET ACTIF = 0 WHERE CODE_DEVISE = 'CDF'")
        with self.assertRaises(ErreurEncaissement):
            encaissements.enregistrer(self.conn, self.admin, self.n_perc, AUJ_TXT, "CDF", 100, 100)
        self.assertEqual([c for c, _ in encaissements.liste_devises(self.conn)], ["USD"])
        self.assertEqual(len(encaissements.liste_percepteurs(self.conn)), 1)
        with self.conn:
            self.conn.execute("UPDATE UTILISATEUR SET ACTIF = 0 WHERE ID_USER = ?", (self.perc.id_user,))
        self.assertEqual(encaissements.liste_percepteurs(self.conn), [])
        with self.assertRaises(ErreurEncaissement):
            encaissements.enregistrer(self.conn, self.admin, self.n_perc, AUJ_TXT, "USD", 100, 100)

    def test_lire_montant(self):
        self.assertEqual(encaissements.lire_montant("1 250,50"), 125050)
        self.assertEqual(encaissements.lire_montant("0", zero_permis=True), 0)
        for mauvais in ("", "  ", "abc", "-5", "0", "1,234"):
            with self.assertRaises(ErreurEncaissement, msg=mauvais):
                encaissements.lire_montant(mauvais)

    def test_modifier_recalcule_l_ecart(self):
        self.donner(self.intendant, "LECTURE", "AJOUT", "MODIFICATION")
        n = encaissements.enregistrer(self.conn, self.intendant, self.n_perc, AUJ_TXT, "USD", 10000, 10000)
        encaissements.modifier(self.conn, self.intendant, n, self.n_perc, AUJ_TXT, "USD", 12000, 10000)
        self.assertEqual(encaissements.charger(self.conn, self.intendant, n)["ecart"], 2000)
        with self.assertRaises(ErreurEncaissement):
            encaissements.modifier(self.conn, self.intendant, 999, self.n_perc, AUJ_TXT, "USD", 1, 1)

    def test_modifier_exige_le_droit(self):
        self.donner(self.intendant, "LECTURE", "AJOUT")
        n = encaissements.enregistrer(self.conn, self.intendant, self.n_perc, AUJ_TXT, "USD", 100, 100)
        with self.assertRaises(PermissionError):
            encaissements.modifier(self.conn, self.intendant, n, self.n_perc, AUJ_TXT, "USD", 200, 100)

    def test_supprimer(self):
        self.donner(self.intendant, "LECTURE", "AJOUT")
        n = encaissements.enregistrer(self.conn, self.intendant, self.n_perc, AUJ_TXT, "USD", 100, 100)
        with self.assertRaises(PermissionError):
            encaissements.supprimer(self.conn, self.intendant, n)
        self.donner(self.intendant, "LECTURE", "SUPPRESSION")
        encaissements.supprimer(self.conn, self.intendant, n)
        self.assertEqual(encaissements.lister(self.conn, self.intendant), [])
        with self.assertRaises(ErreurEncaissement):
            encaissements.supprimer(self.conn, self.intendant, n)

    def test_journal(self):
        n = encaissements.enregistrer(self.conn, self.admin, self.n_perc, AUJ_TXT, "USD", 100, 90)
        encaissements.modifier(self.conn, self.admin, n, self.n_perc, AUJ_TXT, "USD", 100, 100)
        encaissements.supprimer(self.conn, self.admin, n)
        actions = [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL WHERE ACTION LIKE 'ENCAISSEMENT%'")]
        self.assertEqual(actions, ["ENCAISSEMENT_ENREGISTRE", "ENCAISSEMENT_MODIFIE", "ENCAISSEMENT_SUPPRIME"])
        self.assertTrue(database.verifier_journal(self.conn)[0])


class TestRapportGlobal(Base):
    def setUp(self):
        super().setUp()
        # un 2e percepteur qui encaisse aussi aujourd'hui
        security.creer_utilisateur(self.conn, "percepteur2", "Zoé Percepteur", "PERCEPTEUR", "Perc-Deux#2026-xyz")
        self.perc2 = security.authentifier(self.conn, "percepteur2", "Perc-Deux#2026-xyz").session
        self.n_perc2 = paiements.numero_percepteur(self.conn, self.perc2)
        with self.conn:
            droits.remplacer_droits(self.conn, self.perc2.id_user, {("paiement", "LECTURE"), ("paiement", "AJOUT")})
        paiements.enregistrer_paiement(self.conn, self.perc2, "CSF-0004", demo.ANNEE_COURANTE, "INSC", 3000)

    def test_rapport_tous_les_percepteurs_par_type_de_frais(self):
        r = encaissements.rapport_global(self.conn, self.admin, AUJ_TXT)
        types = {g["type_frais"]: g for g in r["groupes"]}
        insc = next(g for k, g in types.items() if k.startswith("Frais d'inscription"))
        noms = {l["percepteur"] for l in insc["lignes"]}
        self.assertEqual(noms, {"Percepteur Démonstration", "Zoé Percepteur"})      # les deux percepteurs
        total_insc = dict(insc["totaux"])["USD"]
        self.assertEqual(total_insc, sum(l["montants"]["USD"] for l in insc["lignes"]))
        self.assertEqual(dict(r["totaux"])["USD"], sum(dict(g["totaux"])["USD"] for g in r["groupes"]))
        total_sql = self.conn.execute("SELECT SUM(MONT_PAYE) FROM PAIEMENT WHERE STATUT = 'VALIDE'").fetchone()[0]
        self.assertEqual(dict(r["totaux"])["USD"], total_sql)
        self.assertEqual(r["nb_recus"], self.conn.execute("SELECT COUNT(*) FROM PAIEMENT").fetchone()[0])

    def test_recus_annules_exclus(self):
        avant = encaissements.rapport_global(self.conn, self.admin, AUJ_TXT)
        recu = self.conn.execute("SELECT N_RECU, MONT_PAYE FROM PAIEMENT ORDER BY N_RECU LIMIT 1").fetchone()
        ref.annuler_paiement(self.conn, self.admin, recu["N_RECU"], "Erreur de saisie du reçu")
        apres = encaissements.rapport_global(self.conn, self.admin, AUJ_TXT)
        self.assertEqual(apres["nb_recus"], avant["nb_recus"] - 1)
        self.assertEqual(apres["nb_annules"], 1)
        self.assertEqual(dict(apres["totaux"])["USD"], dict(avant["totaux"])["USD"] - recu["MONT_PAYE"])

    def test_versements_ecarts_et_totaux(self):
        encaissements.enregistrer(self.conn, self.admin, self.n_perc, AUJ_TXT, "USD", 20000, 19000)
        encaissements.enregistrer(self.conn, self.admin, self.n_perc2, AUJ_TXT, "USD", 5000, 5500)
        encaissements.enregistrer(self.conn, self.admin, self.n_perc2, AUJ_TXT, "CDF", 100000, 100000)
        r = encaissements.rapport_global(self.conn, self.admin, AUJ_TXT)
        self.assertEqual(r["nb_encaissements"], 3)
        self.assertEqual({d: (e, v, x) for d, e, v, x in r["totaux_versements"]},
                         {"USD": (25000, 24500, 500), "CDF": (100000, 100000, 0)})
        self.assertEqual([v["percepteur"] for v in r["versements"]],
                         ["Percepteur Démonstration", "Zoé Percepteur", "Zoé Percepteur"])
        self.assertEqual(r["sans_versement"], [])

    def test_percepteur_sans_versement_signale(self):
        encaissements.enregistrer(self.conn, self.admin, self.n_perc, AUJ_TXT, "USD", 20000, 20000)
        r = encaissements.rapport_global(self.conn, self.admin, AUJ_TXT)
        self.assertEqual(r["sans_versement"], ["Zoé Percepteur"])

    def test_autre_date_vide(self):
        r = encaissements.rapport_global(self.conn, self.admin, "01/01/2020")
        self.assertTrue(encaissements.rapport_vide(r))
        with self.assertRaises(ErreurEncaissement):
            encaissements.rapport_global(self.conn, self.admin, "n'importe quoi")
        with self.assertRaises(ErreurEncaissement):
            encaissements.preparer_rapport_pdf(self.conn, self.admin, "01/01/2020")

    def test_encaissement_seul_sans_paiement(self):
        hier = AUJOURDHUI - datetime.timedelta(days=1)
        encaissements.enregistrer(self.conn, self.admin, self.n_perc, hier.strftime("%d/%m/%Y"), "USD", 700, 700)
        r = encaissements.rapport_global(self.conn, self.admin, hier.strftime("%d/%m/%Y"))
        self.assertFalse(encaissements.rapport_vide(r))
        self.assertEqual((r["nb_recus"], r["nb_encaissements"]), (0, 1))

    def test_pdf(self):
        encaissements.enregistrer(self.conn, self.admin, self.n_perc, AUJ_TXT, "USD", 20000, 19000)
        chemin = encaissements.preparer_rapport_pdf(self.conn, self.admin, AUJ_TXT)
        with open(chemin, "rb") as f:
            contenu = f.read()
        self.assertTrue(contenu.startswith(b"%PDF-1.4"))
        self.assertTrue(contenu.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"Rapport global des encaissements", contenu)
        self.assertTrue(any(l["ACTION"] == "RAPPORT_GLOBAL_IMPRIME" for l in self.conn.execute("SELECT ACTION FROM JOURNAL")))

    def test_pdf_plusieurs_pages(self):
        for i in range(80):
            encaissements.enregistrer(self.conn, self.admin, self.n_perc if i % 2 else self.n_perc2, AUJ_TXT, "USD",
                                      1000 + i, 900)
        chemin = encaissements.preparer_rapport_pdf(self.conn, self.admin, AUJ_TXT)
        with open(chemin, "rb") as f:
            self.assertGreaterEqual(f.read().count(b"/Type /Page "), 2)

    def test_pdf_lisible_par_un_lecteur(self):
        import shutil
        import subprocess
        if not shutil.which("pdfinfo"):
            self.skipTest("pdfinfo absent")
        encaissements.enregistrer(self.conn, self.admin, self.n_perc, AUJ_TXT, "USD", 20000, 19000)
        chemin = encaissements.preparer_rapport_pdf(self.conn, self.admin, AUJ_TXT)
        sortie = subprocess.run(["pdfinfo", chemin], capture_output=True, text=True)
        self.assertEqual(sortie.returncode, 0, sortie.stderr)


class TestTablesEtSuppression(Base):
    def test_table_encaissements_visible_et_supprimable(self):
        n = encaissements.enregistrer(self.conn, self.admin, self.n_perc, AUJ_TXT, "USD", 100, 100)
        lignes = ref.lister(self.conn, self.admin, "encaissements")["lignes"]
        self.assertEqual(len(lignes), 1)
        ref.supprimer(self.conn, self.admin, "encaissements", (n,))
        self.assertEqual(ref.lister(self.conn, self.admin, "encaissements")["lignes"], [])

    def test_devise_utilisee_par_un_encaissement(self):
        encaissements.enregistrer(self.conn, self.admin, self.n_perc, AUJ_TXT, "CDF", 100, 100)
        with self.assertRaises(ref.ErreurUtilisee):
            ref.supprimer(self.conn, self.admin, "devises", ("CDF",))

    def test_supprimer_avec_liees_sans_recus(self):
        """Une classe d'essai avec un tarif et une inscription, mais aucun reçu : suppression en cascade possible."""
        with self.conn:
            self.conn.execute("INSERT INTO CLASSE (N_CLASSE, DESI_CLASSE, CODE_NIVEAU) VALUES (50, 'Classe essai', 'N7')")
            self.conn.execute("INSERT INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE) VALUES ('INSC', 50, ?, 1000, 'USD')", (demo.ANNEE_COURANTE,))
            self.conn.execute("INSERT INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE) VALUES ('EXAM', 50, ?, 1000, 'USD')", (demo.ANNEE_COURANTE,))
            self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('ESSAI-1', 'ESSAI')")
            self.conn.execute("INSERT INTO INSCRIRE VALUES (?, 'ESSAI-1', 50, '2026-09-01', 'NOUVEAU')", (demo.ANNEE_COURANTE,))
        with self.assertRaises(ref.ErreurUtilisee):
            ref.supprimer(self.conn, self.admin, "classes", (50,))                    # le chemin simple refuse
        apercu = ref.apercu_suppression(self.conn, self.admin, "classes", (50,))
        self.assertTrue(apercu["possible"])
        self.assertEqual(dict(apercu["liees"]), {"Tarifs": 2, "Inscriptions": 1})
        ref.supprimer_avec_liees(self.conn, self.admin, "classes", (50,))
        self.assertIsNone(self.conn.execute("SELECT 1 FROM CLASSE WHERE N_CLASSE = 50").fetchone())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM TARIF WHERE N_CLASSE = 50").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM INSCRIRE WHERE N_CLASSE = 50").fetchone()[0], 0)
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM ELEVE WHERE MATRICULE = 'ESSAI-1'").fetchone())   # l'élève reste
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertTrue(database.verifier_journal(self.conn)[0])

    def test_cascade_niveau_et_option(self):
        """Un niveau d'essai : sa classe, ses options par niveau et leurs tarifs partent avec lui."""
        with self.conn:
            self.conn.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU) VALUES ('NX', 'Niveau essai')")
            self.conn.execute("INSERT INTO POSSEDE VALUES ('NX', 'SCI')")
            self.conn.execute("INSERT INTO CLASSE (N_CLASSE, DESI_CLASSE, CODE_NIVEAU, CODE_OPTION) VALUES (60, 'NX Sci', 'NX', 'SCI')")
            self.conn.execute("INSERT INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE) VALUES ('INSC', 60, ?, 1000, 'USD')", (demo.ANNEE_COURANTE,))
        ref.supprimer_avec_liees(self.conn, self.admin, "niveaux", ("NX",))
        self.assertIsNone(self.conn.execute("SELECT 1 FROM NIVEAU WHERE CODE_NIVEAU = 'NX'").fetchone())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CLASSE WHERE N_CLASSE = 60").fetchone()[0], 0)
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM OPTION_SCO WHERE CODE_OPTION = 'SCI'").fetchone())

    def test_cascade_refusee_s_il_y_a_des_recus(self):
        apercu = ref.apercu_suppression(self.conn, self.admin, "types_frais", ("INSC",))
        self.assertFalse(apercu["possible"])
        self.assertGreater(apercu["recus"], 0)
        with self.assertRaises(ref.ErreurRef) as e:
            ref.supprimer_avec_liees(self.conn, self.admin, "types_frais", ("INSC",))
        self.assertIn("reçu", str(e.exception))
        self.assertIn("Réinitialisation", str(e.exception))
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM TYPE_FRAIS WHERE CODTF = 'INSC'").fetchone())   # rien supprimé
        self.assertGreater(self.conn.execute("SELECT COUNT(*) FROM TARIF WHERE CODTF = 'INSC'").fetchone()[0], 0)

    def test_cascade_percepteur_supprime_ses_encaissements(self):
        security.creer_utilisateur(self.conn, "percepteur3", "Troisième", "PERCEPTEUR", "Perc-Trois#2026-xyz")
        n3 = self.conn.execute("SELECT N_PERC FROM PERCEPTEUR p JOIN UTILISATEUR u ON u.ID_USER = p.ID_USER "
                               "WHERE u.LOGIN = 'percepteur3'").fetchone()[0]
        encaissements.enregistrer(self.conn, self.admin, n3, AUJ_TXT, "USD", 100, 100)
        with self.assertRaises(ref.ErreurUtilisee):
            ref.supprimer(self.conn, self.admin, "percepteurs", (n3,))
        ref.supprimer_avec_liees(self.conn, self.admin, "percepteurs", (n3,))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ENCAISSEMENT").fetchone()[0], 0)

    def test_cascade_reservee_a_l_administrateur(self):
        with self.assertRaises(PermissionError):
            ref.supprimer_avec_liees(self.conn, self.perc, "classes", (5,))
        with self.assertRaises(PermissionError):
            ref.apercu_suppression(self.conn, self.intendant, "classes", (5,))

    def test_les_recus_restent_non_supprimables(self):
        with self.assertRaises(ref.ErreurRef):
            ref.supprimer(self.conn, self.admin, "paiements", ("2026-000001",))

    def test_base_ancienne_recoit_la_table(self):
        """Une base sans la table ENCAISSEMENT est mise à jour automatiquement, sans perte."""
        import migrations
        with self.conn:
            self.conn.execute("DROP TABLE ENCAISSEMENT")
        analyse = migrations.analyser(self.conn)
        self.assertTrue(any(t.nom == "ENCAISSEMENT" and t.statut == "MANQUANTE" for t in analyse.tables))
        migrations.mettre_a_jour(self.conn, sauvegarder=False)
        self.assertTrue(migrations._table_existe(self.conn, "ENCAISSEMENT"))
        self.assertGreater(self.conn.execute("SELECT COUNT(*) FROM PAIEMENT").fetchone()[0], 0)

    def test_reinitialisation_vide_aussi_les_encaissements(self):
        import reinitialisation
        encaissements.enregistrer(self.conn, self.admin, self.n_perc, AUJ_TXT, "USD", 100, 100)
        self.assertIn("ENCAISSEMENT", reinitialisation.apercu(self.conn, self.admin))
        reinitialisation.reinitialiser(self.conn, self.admin, "Adm-Test#2026-xyz", "REINITIALISER")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ENCAISSEMENT").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)

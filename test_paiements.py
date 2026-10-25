"""Tests du module de paiement. Lancer :  python test_paiements.py"""
import config
import datetime
import os
import sqlite3
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import argent          # noqa: E402
import database        # noqa: E402
import demo            # noqa: E402
import donnees         # noqa: E402
import paiements       # noqa: E402
import security        # noqa: E402
from security import Session   # noqa: E402

AN, AN0 = demo.ANNEE_COURANTE, demo.ANNEE_PRECEDENTE


class TestArgent(unittest.TestCase):
    def test_conversion(self):
        self.assertEqual(argent.vers_centimes("25"), 2500)
        self.assertEqual(argent.vers_centimes("25,5"), 2550)
        self.assertEqual(argent.vers_centimes("1 250.50"), 125050)
        for mauvais in ("", "abc", "-5", "1,234", "1e3", "5,", ",5", "1.2.3"):
            with self.assertRaises(ValueError, msg=mauvais):
                argent.vers_centimes(mauvais)

    def test_format(self):
        self.assertEqual(argent.formater(125050), "1 250,50")
        self.assertEqual(argent.formater(5), "0,05")


class TestModule(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(":memory:")
        self.login, self.mdp = demo.semer(self.conn)
        r = security.authentifier(self.conn, self.login, self.mdp)
        self.assertTrue(r.ok)
        self.perc = r.session

    # --- recherche ---------------------------------------------------------
    def test_recherche(self):
        self.assertEqual([r["matricule"] for r in donnees.rechercher_eleves(self.conn, "CSF-0003")], ["CSF-0003"])
        self.assertEqual([r["matricule"] for r in donnees.rechercher_eleves(self.conn, "csf-0003")], ["CSF-0003"])
        self.assertEqual([r["matricule"] for r in donnees.rechercher_eleves(self.conn, "emile")], ["CSF-0003"])   # accents
        self.assertEqual([r["matricule"] for r in donnees.rechercher_eleves(self.conn, "ngoy beatrice")], ["CSF-0002"])
        self.assertEqual(len(donnees.rechercher_eleves(self.conn, "CSF-")), 6)
        self.assertEqual(donnees.rechercher_eleves(self.conn, "zzzz"), [])
        self.assertEqual(donnees.rechercher_eleves(self.conn, "a"), [])
        self.assertEqual(donnees.rechercher_eleves(self.conn, "' OR 1=1 --"), [])

    # --- situation ---------------------------------------------------------
    def test_situation_partielle(self):
        lignes = {l.codtf: l for l in donnees.situation(self.conn, "CSF-0001", AN, 2)}
        self.assertEqual(lignes["INSC"].statut, "Soldé")
        self.assertEqual(lignes["MIN1"].statut, "Partiel")
        self.assertEqual((lignes["MIN1"].du, lignes["MIN1"].paye, lignes["MIN1"].reste), (9000, 4500, 4500))
        self.assertEqual(lignes["MIN2"].statut, "Non payé")

    def test_dettes_toutes_annees(self):
        d = donnees.dettes(self.conn, "CSF-0002")
        self.assertIn((AN0, "USD", 9000 + 1500), [x for x in d if x[0] == AN0])         # MIN2 + EXAM de l'an dernier
        self.assertTrue(any(a == AN for a, _, _ in d))
        self.assertEqual([x for x in donnees.dettes(self.conn, "CSF-0001") if x[0] == AN0], [])

    def test_eleve_non_inscrit_cette_annee(self):
        self.assertEqual([i["ANNEESCO"] for i in donnees.inscriptions(self.conn, "CSF-0005")], [AN0])

    def test_option_seulement_en_humanites(self):
        i = {x["ANNEESCO"]: x for x in donnees.inscriptions(self.conn, "CSF-0003")}
        self.assertEqual(i[AN]["DESI_OPTION"], "Commerciale et Gestion")
        self.assertIsNone(donnees.inscriptions(self.conn, "CSF-0001")[0]["DESI_OPTION"])

    # --- enregistrement ----------------------------------------------------
    def test_paiement_et_numerotation(self):
        n1 = paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "INSC", 3000)
        n2 = paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "MIN1", 4000)
        self.assertNotEqual(n1, n2)
        self.assertRegex(n1, r"^\d{4}$")                                      # format 0001 (sans année ni tiret)
        self.assertRegex(n2, r"^\d{4}$")
        self.assertEqual(int(n2), int(n1) + 1)
        lignes = {l.codtf: l for l in donnees.situation(self.conn, "CSF-0004", AN, 1)}
        self.assertEqual(lignes["INSC"].statut, "Soldé")
        self.assertEqual(lignes["MIN1"].reste, 8000 - 4000)

    def test_refus_depassement_et_double_paiement(self):
        with self.assertRaises(paiements.ErreurPaiement):
            paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "INSC", 3001)
        paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "INSC", 3000)
        with self.assertRaises(paiements.ErreurPaiement):                      # déjà soldé
            paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "INSC", 100)

    def test_refus_montants_invalides(self):
        for c in (0, -5, 1.5, "100", None):
            with self.assertRaises(paiements.ErreurPaiement):
                paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "INSC", c)

    def test_refus_eleve_non_inscrit_ou_frais_inconnu(self):
        with self.assertRaises(paiements.ErreurPaiement):
            paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0005", AN, "INSC", 100)       # pas inscrit en 2026-27
        with self.assertRaises(paiements.ErreurPaiement):
            paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "XXXX", 100)
        with self.assertRaises(paiements.ErreurPaiement):
            paiements.enregistrer_paiement(self.conn, self.perc, "INCONNU", AN, "INSC", 100)

    def test_paiement_ancienne_dette(self):
        n = paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0002", AN0, "MIN2", 9000)
        self.assertRegex(n, r"^\d{4}$")
        self.assertEqual({l.codtf: l.reste for l in donnees.situation(self.conn, "CSF-0002", AN0, 2)}["MIN2"], 0)

    def test_reserve_aux_percepteurs(self):
        security.creer_utilisateur(self.conn, "directeur", "Jean Dupont", "ADMINISTRATEUR", "Tr@vail-Amour-2026")
        direction = security.authentifier(self.conn, "directeur", "Tr@vail-Amour-2026").session
        with self.assertRaises(PermissionError):
            paiements.enregistrer_paiement(self.conn, direction, "CSF-0004", AN, "INSC", 3000)
        self.assertTrue(os.path.getsize(paiements.preparer_pdf(self.conn, direction, "0001", True)) > 500)  # duplicata ouvert
        security.creer_utilisateur(self.conn, "sec1", "Marie Kabila", "SECRETAIRE", "Tr@vail-Amour-2026")      # aucun droit
        sec = security.authentifier(self.conn, "sec1", "Tr@vail-Amour-2026").session
        with self.assertRaises(PermissionError):
            paiements.preparer_pdf(self.conn, sec, "0001")
        with self.assertRaises(PermissionError):
            paiements.enregistrer_paiement(self.conn, None, "CSF-0004", AN, "INSC", 3000)
        faux = Session(self.perc.id_user, "x", "Faux", "ADMINISTRATEUR")
        with self.assertRaises(PermissionError):
            paiements.enregistrer_paiement(self.conn, faux, "CSF-0004", AN, "INSC", 3000)

    def test_percepteur_cree_avec_son_numero(self):
        n = self.conn.execute("SELECT COUNT(*) FROM PERCEPTEUR").fetchone()[0]
        security.creer_utilisateur(self.conn, "percepteur2", "Marie Kabila", "PERCEPTEUR", "Tr@vail-Amour-2026")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PERCEPTEUR").fetchone()[0], n + 1)

    # --- intégrité ---------------------------------------------------------
    def test_recu_ni_modifiable_ni_supprimable(self):
        n = paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "INSC", 3000)
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("DELETE FROM PAIEMENT WHERE N_RECU = ?", (n,))
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("UPDATE PAIEMENT SET MONT_PAYE = 1 WHERE N_RECU = ?", (n,))
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("UPDATE PAIEMENT SET MATRICULE = 'CSF-0001' WHERE N_RECU = ?", (n,))

    def test_annulation_libere_le_solde_et_bloque_l_impression(self):
        n = paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "INSC", 3000)
        with self.conn:
            self.conn.execute("UPDATE PAIEMENT SET STATUT = 'ANNULE' WHERE N_RECU = ?", (n,))
        self.assertEqual(donnees.situation(self.conn, "CSF-0004", AN, 1)[0].paye, 0)
        with self.assertRaises(paiements.ErreurPaiement):
            paiements.preparer_pdf(self.conn, self.perc, n)

    def test_journal_apres_operations(self):
        paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "INSC", 3000)
        self.assertEqual(database.verifier_journal(self.conn), (True, None))
        actions = [r[0] for r in self.conn.execute("SELECT ACTION FROM JOURNAL")]
        self.assertIn("PAIEMENT_ENREGISTRE", actions)

    # --- reçus -------------------------------------------------------------
    def test_contenu_du_recu(self):
        n = paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0003", AN, "MIN1", 6500)
        r = paiements.charger_recu(self.conn, n)
        self.assertEqual(r["nom_complet"], "KABONGO TSHIALA Émile")
        self.assertEqual(r["classe"], "4ème Commerciale et Gestion")
        self.assertEqual(r["option"], "Commerciale et Gestion")
        self.assertEqual((r["montant_txt"], r["devise"]), ("65,00", "USD"))
        self.assertEqual(r["type_frais"], "Frais scolaire (minerval) 1")
        self.assertEqual(r["nom_percepteur"], "Percepteur Démonstration")
        sans_option = paiements.charger_recu(self.conn, paiements.enregistrer_paiement(
            self.conn, self.perc, "CSF-0004", AN, "INSC", 3000))
        self.assertEqual(sans_option["option"], "")

    def test_recu_identique_apres_changement_de_tarif(self):
        n = paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "INSC", 3000)
        avant = paiements.charger_recu(self.conn, n)
        with self.conn:
            self.conn.execute("UPDATE TARIF SET MONTANT = 9999 WHERE CODTF = 'INSC'")
        self.assertEqual(paiements.charger_recu(self.conn, n), avant)

    def test_pdf_original_et_duplicata(self):
        n = paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0003", AN, "MIN1", 6500)
        p1 = paiements.preparer_pdf(self.conn, self.perc, n)
        p2 = paiements.preparer_pdf(self.conn, self.perc, n, duplicata=True)
        for p in (p1, p2):
            with open(p, "rb") as f:
                donnees_pdf = f.read()
            self.assertTrue(donnees_pdf.startswith(b"%PDF-1.4"))
            self.assertTrue(donnees_pdf.rstrip().endswith(b"%%EOF"))
        try:
            from pypdf import PdfReader
        except ImportError:
            return
        t1, t2 = (PdfReader(p).pages[0].extract_text() for p in (p1, p2))
        for attendu in (config.NOM_ECOLE, "DISCIPLINE - AMOUR - TRAVAIL", n, "KABONGO TSHIALA ÉMILE",
                        "Commerciale et Gestion", "Frais scolaire (minerval) 1", "65,00 USD", "REÇU DE PAIEMENT", "MONTANT PAYÉ",
                        "RESTE À PAYER", "MERCI"):
            self.assertIn(attendu, t1)
        # le nom du percepteur n'est pas sur le reçu ; un duplicata est identique à l'original (aucune mention)
        for interdit in ("Percepteur", "Démonstration", "DUPLICATA", "uplicata", "imprimé le"):
            self.assertNotIn(interdit, t1)
            self.assertNotIn(interdit, t2)
        self.assertEqual(t1, t2)
        # format ticket de caisse : 80 mm de large (226,77 pt), hauteur selon le contenu, police à chasse fixe
        page = PdfReader(p1).pages[0]
        self.assertAlmostEqual(float(page.mediabox.width), 226.77, places=1)
        self.assertGreater(float(page.mediabox.height), float(page.mediabox.width))
        self.assertEqual(page["/Resources"]["/Font"]["/F1"].get_object()["/BaseFont"], "/Courier")
        actions = [r[0] for r in self.conn.execute("SELECT ACTION FROM JOURNAL")]
        self.assertIn("RECU_IMPRIME", actions)
        self.assertIn("DUPLICATA_IMPRIME", actions)

    def test_paiement_partiel_d_une_tranche(self):
        """Une tranche peut être payée en partie : le reçu donne le montant payé et le reste à payer de la tranche."""
        def recu(centimes):
            n = paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "MIN1", centimes)
            return n, paiements.charger_recu(self.conn, n)
        _, r = recu(1000)                                              # 10 sur une tranche de 40 : accepté
        self.assertEqual((r["tranche"]["numero"], r["tranche"]["reste_txt"], r["montant_txt"]), (1, "30,00", "10,00"))
        _, r = recu(1500)                                              # cumul 25
        self.assertEqual((r["tranche"]["numero"], r["tranche"]["reste_txt"]), (1, "15,00"))
        _, r = recu(1500)                                              # cumul 40 : tranche 1 soldée
        self.assertEqual((r["tranche"]["numero"], r["tranche"]["reste_txt"]), (1, "0,00"))
        n, r = recu(2000)                                              # cumul 60 : 20 payés sur la tranche 2
        self.assertEqual((r["tranche"]["numero"], r["tranche"]["nombre"], r["tranche"]["reste_txt"]), (2, 2, "20,00"))
        with self.assertRaises(paiements.ErreurPaiement):              # jamais plus que le reste dû
            recu(3000)
        # le percepteur n'est pas sur le PDF mais sa trace reste dans le système
        self.assertEqual(self.conn.execute("SELECT N_PERC FROM PAIEMENT WHERE N_RECU = ?", (n,)).fetchone()[0], r["n_perc"])
        self.assertTrue(self.conn.execute("SELECT 1 FROM JOURNAL WHERE ACTION = 'PAIEMENT_ENREGISTRE' AND DETAIL LIKE ?",
                                          (n + "%",)).fetchone())
        try:
            from pypdf import PdfReader
        except ImportError:
            return
        texte = PdfReader(paiements.preparer_pdf(self.conn, self.perc, n)).pages[0].extract_text()
        for attendu in ("Tranche", "2 sur 2", "MONTANT PAYÉ", "20,00 USD", "RESTE À PAYER (tranche)"):
            self.assertIn(attendu, texte)
        self.assertEqual(texte, PdfReader(paiements.preparer_pdf(self.conn, self.perc, n, duplicata=True)).pages[0].extract_text())

    def test_frais_en_une_fois_refuse_toujours_le_partiel(self):
        with self.assertRaises(paiements.ErreurPaiement) as e:
            paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "EXAM", 1000)
        self.assertIn("une seule fois", str(e.exception))

    def test_liste_des_recus_d_un_eleve(self):
        recus = paiements.recus_eleve(self.conn, "CSF-0001")
        self.assertEqual(len(recus), 6)
        self.assertEqual(paiements.recus_eleve(self.conn, "CSF-0006"), [])


class TestRapportCaisse(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(":memory:")
        self.login, self.mdp = demo.semer(self.conn)
        self.perc = security.authentifier(self.conn, self.login, self.mdp).session
        self.aujourdhui = datetime.date.today()

    def _inserer(self, n, jour_delta=0, codtf="INSC", montant=100, statut="VALIDE", n_perc=1, mat="CSF-0004", classe=1):
        date_pay = database.iso((datetime.datetime.now() + datetime.timedelta(days=jour_delta)).astimezone(datetime.timezone.utc))
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE) VALUES (?,?,?,?,?)", (codtf, classe, AN, 999999, "USD"))
            self.conn.execute(
                "INSERT INTO PAIEMENT (N_RECU, ANNEESCO, NUM_SEQ, DATE_PAY, MATRICULE, N_CLASSE, CODTF, CODE_DEVISE, MONT_PAYE, N_PERC, STATUT) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (f"2026-{n:06d}", AN, n, date_pay, mat, classe, codtf, "USD", montant, n_perc, statut))

    def test_rapport_du_jour_separe_par_type_de_frais(self):
        r = paiements.rapport_journalier(self.conn, self.perc, self.aujourdhui)
        self.assertEqual(r["nb_recus"], 10)
        self.assertEqual([g["type_frais"] for g in r["groupes"]],
                         ["Frais d'examen", "Frais d'inscription", "Frais scolaire (minerval) 1",
                          "Frais scolaire (minerval) 2"])
        self.assertEqual([len(g["lignes"]) for g in r["groupes"]], [1, 4, 4, 1])
        self.assertEqual(r["totaux"], [("USD", 55000)])
        self.assertEqual((r["n_perc"], r["nom_percepteur"]), (1, "Percepteur Démonstration"))
        ligne = r["groupes"][2]["lignes"][3]               # minerval de l'élève en humanités
        self.assertEqual((ligne["nom_complet"], ligne["classe"], ligne["option"], ligne["montant_txt"]),
                         ("KABONGO TSHIALA Émile", "3ème Scientifique", "Scientifique", "120,00 USD"))

    def test_filtre_par_date(self):
        self._inserer(900, jour_delta=-1)
        self.assertEqual(paiements.rapport_journalier(self.conn, self.perc, self.aujourdhui)["nb_recus"], 10)
        hier = paiements.rapport_journalier(self.conn, self.perc, self.aujourdhui - datetime.timedelta(days=1))
        self.assertEqual((hier["nb_recus"], hier["totaux"]), (1, [("USD", 100)]))
        self.assertEqual(paiements.rapport_journalier(self.conn, self.perc, self.aujourdhui + datetime.timedelta(days=1))["nb_recus"], 0)

    def test_chaque_percepteur_ne_voit_que_ses_paiements(self):
        security.creer_utilisateur(self.conn, "percepteur2", "Marie Kabila", "PERCEPTEUR", "Tr@vail-Amour-2026")
        p2 = security.authentifier(self.conn, "percepteur2", "Tr@vail-Amour-2026").session
        self.assertEqual(paiements.rapport_journalier(self.conn, p2, self.aujourdhui)["nb_recus"], 0)
        paiements.enregistrer_paiement(self.conn, p2, "CSF-0004", AN, "INSC", 3000)
        r2 = paiements.rapport_journalier(self.conn, p2, self.aujourdhui)
        self.assertEqual((r2["nb_recus"], r2["n_perc"], r2["nom_percepteur"]), (1, 2, "Marie Kabila"))
        self.assertEqual(paiements.rapport_journalier(self.conn, self.perc, self.aujourdhui)["nb_recus"], 10)

    def test_recus_annules_exclus_mais_signales(self):
        with self.conn:
            self.conn.execute("UPDATE PAIEMENT SET STATUT = 'ANNULE' WHERE N_RECU = '0001'")
        r = paiements.rapport_journalier(self.conn, self.perc, self.aujourdhui)
        self.assertEqual((r["nb_recus"], r["nb_annules"]), (9, 1))

    def test_lecture_de_la_date(self):
        for texte in ("08/10/2026", "8/10/2026", "08-10-2026", "08.10.2026", "2026-10-08", " 08/10/2026 "):
            self.assertEqual(paiements.lire_date(texte), datetime.date(2026, 10, 8), texte)
        for mauvais in ("", "demain", "32/01/2026", "08/13/2026", "2026/10/08"):
            with self.assertRaises(paiements.ErreurPaiement, msg=mauvais):
                paiements.lire_date(mauvais)

    def test_reserve_aux_percepteurs(self):
        security.creer_utilisateur(self.conn, "directeur", "Jean Dupont", "ADMINISTRATEUR", "Tr@vail-Amour-2026")
        direction = security.authentifier(self.conn, "directeur", "Tr@vail-Amour-2026").session
        # tout compte ayant accès au module voit le rapport (tous les percepteurs, ou un percepteur choisi)
        r = paiements.rapport_journalier(self.conn, direction, self.aujourdhui)
        self.assertEqual(r["nom_percepteur"], "Tous les percepteurs")
        self.assertEqual(r["nb_recus"], paiements.rapport_journalier(self.conn, self.perc, self.aujourdhui)["nb_recus"])
        un = paiements.rapport_journalier(self.conn, direction, self.aujourdhui, n_perc=1)
        self.assertEqual(un["n_perc"], 1)
        self.assertTrue(os.path.getsize(paiements.preparer_rapport_pdf(self.conn, direction, self.aujourdhui)) > 500)
        with self.assertRaises(paiements.ErreurPaiement):
            paiements.rapport_journalier(self.conn, direction, self.aujourdhui, n_perc=999)
        # un compte sans aucun droit sur le module est refusé
        security.creer_utilisateur(self.conn, "sec1", "Marie Kabila", "SECRETAIRE", "Tr@vail-Amour-2026")
        sec = security.authentifier(self.conn, "sec1", "Tr@vail-Amour-2026").session
        with self.assertRaises(PermissionError):
            paiements.rapport_journalier(self.conn, sec, self.aujourdhui)
        with self.assertRaises(PermissionError):
            paiements.preparer_rapport_pdf(self.conn, sec, self.aujourdhui)

    def test_impression_refusee_si_rien_a_imprimer(self):
        with self.assertRaises(paiements.ErreurPaiement):
            paiements.preparer_rapport_pdf(self.conn, self.perc, self.aujourdhui + datetime.timedelta(days=3))

    def test_pdf_du_rapport(self):
        chemin = paiements.preparer_rapport_pdf(self.conn, self.perc, self.aujourdhui)
        with open(chemin, "rb") as f:
            brut = f.read()
        self.assertTrue(brut.startswith(b"%PDF-1.4") and brut.rstrip().endswith(b"%%EOF"))
        self.assertIn("RAPPORT_CAISSE_IMPRIME", [r[0] for r in self.conn.execute("SELECT ACTION FROM JOURNAL")])
        try:
            from pypdf import PdfReader
        except ImportError:
            return
        texte = PdfReader(chemin).pages[0].extract_text()
        for attendu in (config.NOM_ECOLE, "DISCIPLINE - AMOUR - TRAVAIL", "RAPPORT JOURNALIER DE CAISSE",
                        self.aujourdhui.strftime("%d/%m/%Y"), "Percepteur Démonstration", "N° 1",
                        "N° Reçu", "Nom complet", "Classe", "Option", "Montant",
                        "TYPE DE FRAIS :  FRAIS D'INSCRIPTION", "TYPE DE FRAIS :  FRAIS SCOLAIRE (MINERVAL) 2",
                        "KABONGO TSHIALA Émile", "Scientifique", "TOTAL GÉNÉRAL DE LA JOURNÉE", "550,00 USD",
                        "Signature Percepteur"):
            self.assertIn(attendu, texte)

    def test_rapport_de_plusieurs_pages(self):
        for i in range(1, 121):
            self._inserer(1000 + i, codtf="MIN1" if i % 2 else "EXAM", montant=100 * i, mat="CSF-0003", classe=5)
        chemin = paiements.preparer_rapport_pdf(self.conn, self.perc, self.aujourdhui)
        try:
            from pypdf import PdfReader
        except ImportError:
            return
        pages = PdfReader(chemin).pages
        self.assertGreater(len(pages), 2)
        tout = "\n".join(p.extract_text() for p in pages)
        for i in range(1, 121):
            self.assertIn(f"2026-{1000 + i:06d}", tout)                  # aucun reçu perdu entre les pages
        self.assertIn(f"Page {len(pages)} / {len(pages)}", tout)
        self.assertIn("(suite)", tout)
        self.assertIn("130 reçu(s)", tout)


class TestMigration(unittest.TestCase):
    def test_ancienne_base_v01_conservee(self):
        chemin = os.path.join(tempfile.mkdtemp(), "ancienne.db")
        c = sqlite3.connect(chemin)
        c.executescript("""CREATE TABLE UTILISATEUR (ID_USER INTEGER PRIMARY KEY AUTOINCREMENT,
            LOGIN TEXT NOT NULL UNIQUE COLLATE NOCASE, NOM_COMPLET TEXT NOT NULL,
            ROLE TEXT NOT NULL CHECK (ROLE IN ('DIRECTION','SECRETARIAT','CELLULE_FINANCIERE')),
            MDP_HASH TEXT NOT NULL, ACTIF INTEGER NOT NULL DEFAULT 1, DOIT_CHANGER_MDP INTEGER NOT NULL DEFAULT 0,
            DATE_CREATION TEXT NOT NULL, DERNIERE_CONNEXION TEXT);""")
        c.execute("INSERT INTO UTILISATEUR (LOGIN, NOM_COMPLET, ROLE, MDP_HASH, DATE_CREATION) VALUES (?,?,?,?,?)",
                  ("directeur", "Jean Dupont", "DIRECTION", security.hacher_mdp("Tr@vail-Amour-2026"), "2026-10-08"))
        c.commit()
        c.close()
        conn = database.connecter(chemin)
        r = security.authentifier(conn, "directeur", "Tr@vail-Amour-2026")
        self.assertTrue(r.ok)                                                                      # compte conservé
        self.assertEqual(r.session.role, "ADMINISTRATEUR")                                         # ancien nom converti
        security.creer_utilisateur(conn, "perc", "Un Percepteur", "PERCEPTEUR", "Tr@vail-Amour-2026")  # nouveau rôle accepté
        conn.close()
        conn = database.connecter(chemin)                                                         # 2e ouverture : idempotent
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM UTILISATEUR").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)

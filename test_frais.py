"""Tests des types de frais (montant + devise), des frais payés par tranches, des classes à divisions et de la
migration des anciennes bases.   Lancer :  python test_frais.py"""
import os
import sqlite3
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import database                  # noqa: E402
import demo                      # noqa: E402
import donnees                   # noqa: E402
import migrations                # noqa: E402
import paiements                 # noqa: E402
import referentiels as ref       # noqa: E402
import security                  # noqa: E402
from paiements import ErreurPaiement   # noqa: E402

MDP = "Tr@vail-Amour-2026"
AN, AN0 = demo.ANNEE_COURANTE, demo.ANNEE_PRECEDENTE


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(os.path.join(tempfile.mkdtemp(), "frais.db"))
        security.creer_utilisateur(self.conn, "admin1", "Alice Administratrice", "ADMINISTRATEUR", MDP)
        self.admin = security.authentifier(self.conn, "admin1", MDP).session
        login, mdp = demo.semer(self.conn)
        self.perc = security.authentifier(self.conn, login, mdp).session

    def payer(self, mat, codtf, centimes, annee=AN):
        return paiements.enregistrer_paiement(self.conn, self.perc, mat, annee, codtf, centimes)

    def ligne(self, mat, codtf, classe, annee=AN):
        return {l.codtf: l for l in donnees.situation(self.conn, mat, annee, classe)}[codtf]


class TestTypeDeFrais(Base):
    def test_montant_et_devise_vont_ensemble_ou_restent_vides(self):
        """Un frais qui dépend de la classe n'a pas de montant propre : montant et devise vides ensemble (le montant se fixe
        dans Tarifs). Un seul des deux est refusé."""
        base = {"CODTF": "BIB", "DESITF": "Bibliothèque"}
        for incomplet in ({"CODE_DEVISE": "USD"}, {"MONTANT": "10"}):
            with self.assertRaises(ref.ErreurRef) as e:
                ref.enregistrer(self.conn, self.admin, "types_frais", dict(base, **incomplet))
            self.assertIn("ensemble", str(e.exception))
        ref.enregistrer(self.conn, self.admin, "types_frais", dict(base, MONTANT="10,50", CODE_DEVISE="USD"))
        self.assertEqual(self.conn.execute("SELECT MONTANT, CODE_DEVISE, PAR_TRANCHE FROM TYPE_FRAIS WHERE CODTF='BIB'").fetchone()[:],
                         (1050, "USD", 0))
        ref.enregistrer(self.conn, self.admin, "types_frais", {"CODTF": "UNI", "DESITF": "Uniforme"})       # selon la classe
        self.assertEqual(self.conn.execute("SELECT MONTANT, CODE_DEVISE FROM TYPE_FRAIS WHERE CODTF='UNI'").fetchone()[:],
                         (None, None))
        self.assertIsNone(donnees.montant_du(self.conn, "UNI", 1, AN))                    # sans tarif de classe : rien n'est dû
        self.assertNotIn("UNI", [l.codtf for l in donnees.situation(self.conn, "CSF-0004", AN, 1)])

    def test_le_montant_du_type_s_applique_a_toutes_les_classes_sans_tarif(self):
        for classe in (1, 2, 3, 4, 5):
            l = self.ligne("CSF-0004", "INSC", classe)
            self.assertEqual((l.du, l.devise), (3000, "USD"))

    def test_nouveau_type_applique_sans_saisir_de_tarif(self):
        ref.enregistrer(self.conn, self.admin, "types_frais", {"CODTF": "BIB", "DESITF": "Bibliothèque", "MONTANT": "10",
                                                              "CODE_DEVISE": "CDF"})
        l = self.ligne("CSF-0004", "BIB", 1)
        self.assertEqual((l.du, l.devise, l.statut), (1000, "CDF", "Non payé"))
        n = self.payer("CSF-0004", "BIB", 1000)
        self.assertEqual(paiements.charger_recu(self.conn, n)["devise"], "CDF")
        self.assertEqual(self.ligne("CSF-0004", "BIB", 1).statut, "Soldé")

    def test_tarif_de_classe_prioritaire(self):
        with self.conn:
            self.conn.execute("INSERT INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE) VALUES ('INSC', 1, ?, 2000, 'USD')", (AN,))
        self.assertEqual(self.ligne("CSF-0004", "INSC", 1).du, 2000)
        self.assertEqual(self.ligne("CSF-0004", "INSC", 2).du, 3000)

    def test_nouvelle_annee_reprend_le_montant_du_type(self):
        with self.conn:
            self.conn.execute("INSERT INTO ANNEE_SCO (ANNEESCO, EN_COURS) VALUES ('2027-2028', 0)")
        self.assertEqual(self.ligne("CSF-0004", "INSC", 1, annee="2027-2028").du, 3000)

    def test_paiement_fige_le_tarif_et_le_changement_ulterieur_ne_touche_pas_le_paye(self):
        self.payer("CSF-0004", "INSC", 3000)
        figes = self.conn.execute("SELECT MONTANT FROM TARIF WHERE CODTF='INSC' AND N_CLASSE=1 AND ANNEESCO=?", (AN,)).fetchone()
        self.assertEqual(figes[0], 3000)
        ref.enregistrer(self.conn, self.admin, "types_frais", {"CODTF": "INSC", "DESITF": "Frais d'inscription", "MONTANT": "50",
                                                              "CODE_DEVISE": "USD"}, ("INSC",))
        self.assertEqual(self.ligne("CSF-0004", "INSC", 1).statut, "Soldé")                # classe 1 : déjà figé
        self.assertEqual(self.ligne("CSF-0004", "INSC", 4).du, 5000)                       # classe sans paiement : nouveau montant
        self.assertTrue(any(l[0] == "TARIF_FIGE" for l in self.conn.execute("SELECT ACTION FROM JOURNAL")))

    def test_devise_et_mode_de_paiement_verrouilles_apres_paiement(self):
        self.payer("CSF-0004", "INSC", 3000)
        base = {"CODTF": "INSC", "DESITF": "Frais d'inscription", "MONTANT": "30", "CODE_DEVISE": "USD"}
        with self.assertRaises(ref.ErreurRef) as e:
            ref.enregistrer(self.conn, self.admin, "types_frais", dict(base, CODE_DEVISE="CDF"), ("INSC",))
        self.assertIn("devise", str(e.exception))
        with self.assertRaises(ref.ErreurRef) as e:
            ref.enregistrer(self.conn, self.admin, "types_frais", dict(base, PAR_TRANCHE=True), ("INSC",))
        self.assertIn("tranches", str(e.exception))
        ref.enregistrer(self.conn, self.admin, "types_frais", dict(base, DESITF="Inscription"), ("INSC",))   # renommer : permis


class TestPaiementEnUneFois(Base):
    def test_un_frais_ordinaire_se_paie_en_entier(self):
        for c in (1000, 2999, 3001):
            with self.assertRaises(ErreurPaiement) as e:
                self.payer("CSF-0004", "INSC", c)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PAIEMENT WHERE MATRICULE='CSF-0004'").fetchone()[0], 0)
        self.payer("CSF-0004", "INSC", 3000)

    def test_message_indique_le_montant(self):
        with self.assertRaises(ErreurPaiement) as e:
            self.payer("CSF-0004", "INSC", 1000)
        self.assertIn("une seule fois", str(e.exception))
        self.assertIn("30,00 USD", str(e.exception))

    def test_ligne_mode(self):
        l = self.ligne("CSF-0004", "INSC", 1)
        self.assertEqual((l.mode, l.prochain_montant, l.par_tranche), ("Paiement en une seule fois", 3000, False))


class TestTranches(Base):
    def test_situation_par_tranches(self):
        l = self.ligne("CSF-0004", "MIN1", 1)                                  # 80,00 en 50 % + 50 %
        self.assertEqual((l.par_tranche, l.paliers, l.prochain_montant, l.numero_tranche), (True, (4000, 8000), 4000, 1))
        self.assertEqual(l.mode, "Par tranches : tranche 1 sur 2")
        self.payer("CSF-0004", "MIN1", 4000)
        l = self.ligne("CSF-0004", "MIN1", 1)
        self.assertEqual((l.paye, l.reste, l.statut, l.prochain_montant, l.numero_tranche), (4000, 4000, "Partiel", 4000, 2))
        self.payer("CSF-0004", "MIN1", 4000)
        l = self.ligne("CSF-0004", "MIN1", 1)
        self.assertEqual((l.statut, l.prochain_montant), ("Soldé", 0))
        self.assertIn("payée", l.mode)

    def test_paiement_partiel_d_une_tranche_accepte(self):
        """Une tranche peut être payée en partie (même 1 centime) ; elle reste ouverte avec ce qu'il en reste ; jamais plus que le reste dû."""
        self.payer("CSF-0004", "MIN1", 3999)
        l = self.ligne("CSF-0004", "MIN1", 1)
        self.assertEqual((l.numero_tranche, l.prochain_montant, l.statut), (1, 1, "Partiel"))
        self.payer("CSF-0004", "MIN1", 1)
        l = self.ligne("CSF-0004", "MIN1", 1)
        self.assertEqual((l.numero_tranche, l.prochain_montant), (2, 4000))
        with self.assertRaises(ErreurPaiement) as e:
            self.payer("CSF-0004", "MIN1", 5000)                              # plus que le reste dû (40,00)
        self.assertIn("dépasse", str(e.exception))
        with self.assertRaises(ErreurPaiement):
            self.payer("CSF-0004", "MIN1", 0)

    def test_plusieurs_tranches_d_un_coup(self):
        self.payer("CSF-0004", "MIN1", 8000)
        self.assertEqual(self.ligne("CSF-0004", "MIN1", 1).statut, "Soldé")

    def test_paliers_a_partir_des_montants_des_tranches(self):
        self.assertEqual(donnees.paliers((3300, 3300, 3400), 10000, True), (3300, 6600, 10000))
        self.assertEqual(donnees.paliers((10000,), 10000, True), (10000,))                  # une seule tranche
        self.assertEqual(donnees.paliers((3000, 3000), 3000, False), (3000,))               # frais ordinaire : tout d'un coup
        self.assertEqual(donnees.paliers(tuple([100] * 36), 3600, True)[-1], 3600)          # nombre de tranches libre
        for mauvais in ((3300, 3300), (3300, 3300, 3500), (), None, (0, 10000), (-5, 10005)):
            self.assertIsNone(donnees.paliers(mauvais, 10000, True), mauvais)               # total != montant : inutilisable

    def test_tranches_inegales_d_un_tarif(self):
        ref.enregistrer(self.conn, self.admin, "tarifs", {"MONTANT": "100", "CODE_DEVISE": "USD", "TRANCHES": "33;33;34"},
                        ("MIN2", 1, AN))
        l = self.ligne("CSF-0004", "MIN2", 1)
        self.assertEqual((l.paliers, l.prochain_montant), ((3300, 6600, 10000), 3300))
        self.payer("CSF-0004", "MIN2", 3300)
        self.payer("CSF-0004", "MIN2", 3300)
        self.assertEqual(self.ligne("CSF-0004", "MIN2", 1).prochain_montant, 3400)
        with self.assertRaises(ErreurPaiement) as e:
            self.payer("CSF-0004", "MIN2", 3500)                                  # plus que le reste dû
        self.assertIn("34,00 USD", str(e.exception))
        self.payer("CSF-0004", "MIN2", 3300)                                      # payer moins que la tranche est permis
        self.assertEqual(self.ligne("CSF-0004", "MIN2", 1).prochain_montant, 100)

    def test_tranches_incompletes_bloquent_le_paiement(self):
        with self.conn:
            self.conn.execute("UPDATE TARIF SET TRANCHES = NULL WHERE CODTF = 'MIN1' AND N_CLASSE = 1")
        l = self.ligne("CSF-0004", "MIN1", 1)
        self.assertTrue(l.tranches_mal_definies)
        self.assertIn("non définies", l.mode)
        with self.assertRaises(ErreurPaiement) as e:
            self.payer("CSF-0004", "MIN1", 4000)
        self.assertIn("pas définies", str(e.exception))

    def test_ancien_paiement_partiel_hors_tranche_reste_utilisable(self):
        """Base d'avant : un paiement partiel de 50,00 sur 80,00 ; on ne peut plus payer que jusqu'à la fin de tranche."""
        n = self.payer("CSF-0004", "MIN1", 4000)
        with self.conn:                                                             # on simule une ancienne base : 5000 payé
            self.conn.execute("DROP TRIGGER PAIEMENT_NO_UPDATE")
            self.conn.execute("UPDATE PAIEMENT SET MONT_PAYE = 5000 WHERE N_RECU = ?", (n,))
        l = self.ligne("CSF-0004", "MIN1", 1)
        self.assertEqual((l.paye, l.prochain_montant), (5000, 3000))
        self.payer("CSF-0004", "MIN1", 3000)
        self.assertEqual(self.ligne("CSF-0004", "MIN1", 1).statut, "Soldé")

    def test_annulation_libere_la_tranche(self):
        self.payer("CSF-0004", "MIN1", 4000)
        n = self.payer("CSF-0004", "MIN1", 4000)
        ref.annuler_paiement(self.conn, self.admin, n, "Erreur de saisie")
        l = self.ligne("CSF-0004", "MIN1", 1)
        self.assertEqual((l.paye, l.numero_tranche, l.prochain_montant), (4000, 2, 4000))

    def test_tarif_par_tranche_verrouille(self):
        self.payer("CSF-0004", "MIN1", 4000)
        for changement in ({"MONTANT": "90", "TRANCHES": "45;45"},             # le montant change
                           {"MONTANT": "80", "TRANCHES": "30;50"},             # seules les tranches changent
                           {"MONTANT": "80", "TRANCHES": "80"}):
            with self.assertRaises(ref.ErreurRef) as e:
                ref.enregistrer(self.conn, self.admin, "tarifs", dict(changement, CODE_DEVISE="USD"), ("MIN1", 1, AN))
            self.assertIn("par tranches", str(e.exception))


class TestTranchesLibres(Base):
    """Le nombre de tranches et le montant de chacune sont libres ; le total doit faire le montant dû. Les frais qui
    dépendent de la classe (frais scolaire : 300 en 1ère-3ème, 600 en 4ème) se règlent dans Tarifs."""

    def erreur(self, appel):
        with self.assertRaises(ref.ErreurRef) as e:
            appel()
        return str(e.exception)

    def type_frais(self, **plus):
        saisie = {"CODTF": "BUS", "DESITF": "Transport", "MONTANT": "60", "CODE_DEVISE": "USD", "PAR_TRANCHE": True,
                  "TRANCHES": "20;20;20"}
        saisie.update(plus)
        return ref.enregistrer(self.conn, self.admin, "types_frais", saisie)

    def tranches_de(self, codtf):
        return self.conn.execute("SELECT TRANCHES FROM TYPE_FRAIS WHERE CODTF = ?", (codtf,)).fetchone()[0]

    def test_formats_de_saisie(self):
        for saisie, attendu in (("20;20;20", "2000;2000;2000"), ("3x20", "2000;2000;2000"), ("3 x 20", "2000;2000;2000"),
                                ("10 + 25,5 + 24,50", "1000;2550;2450"), ("60", "6000"), ("2x15;30", "1500;1500;3000"),
                                ("20 ; 20 ; 20 ;", "2000;2000;2000")):
            ref.supprimer_avec_liees(self.conn, self.admin, "types_frais", ("BUS",)) if self.tranches_de_ou_none("BUS") else None
            self.type_frais(TRANCHES=saisie)
            self.assertEqual(self.tranches_de("BUS"), attendu, saisie)

    def tranches_de_ou_none(self, codtf):
        l = self.conn.execute("SELECT 1 FROM TYPE_FRAIS WHERE CODTF = ?", (codtf,)).fetchone()
        return l is not None

    def test_saisies_refusees(self):
        for mauvaise in ("abc", "20;;x", "0;60", "-20;80", "20;20;20;", "1x", "x20", "20,555;39,445"):
            if mauvaise in ("20;20;20;",):
                continue                                                          # un « ; » final est toléré
            self.erreur(lambda: self.type_frais(TRANCHES=mauvaise))
        self.assertIn("36 tranches", self.erreur(lambda: self.type_frais(MONTANT="37", TRANCHES="37x1")))

    def test_le_total_doit_faire_le_montant(self):
        self.assertIn("manque 10,00", self.erreur(lambda: self.type_frais(TRANCHES="20;30")))
        self.assertIn("en trop 5,00", self.erreur(lambda: self.type_frais(TRANCHES="20;20;25")))
        self.assertIn("indiquez le montant de chaque tranche", self.erreur(lambda: self.type_frais(TRANCHES="")))

    def test_nombre_de_tranches_libre(self):
        for n in (1, 2, 5, 10, 12, 13, 24, 36):                                 # plus de limite à 12
            ref.supprimer_avec_liees(self.conn, self.admin, "types_frais", ("BUS",)) if self.tranches_de_ou_none("BUS") else None
            self.type_frais(MONTANT=str(n * 5), TRANCHES=f"{n}x5")
            self.assertEqual(len(self.tranches_de("BUS").split(";")), n)

    def test_un_frais_ordinaire_n_a_pas_de_tranches(self):
        self.assertIn("une seule fois", self.erreur(lambda: self.type_frais(PAR_TRANCHE=False)))
        ref.enregistrer(self.conn, self.admin, "types_frais", {"CODTF": "BIB", "DESITF": "Bib", "MONTANT": "10", "CODE_DEVISE": "USD"})
        self.assertIsNone(self.tranches_de("BIB"))

    def test_frais_sans_montant_propre_les_tranches_se_fixent_par_tarif(self):
        self.assertIn("dans « Tarifs »", self.erreur(lambda: self.type_frais(MONTANT="", CODE_DEVISE="")))
        self.type_frais(MONTANT="", CODE_DEVISE="", TRANCHES="")                  # permis : montant et tranches viendront des tarifs
        self.assertIsNone(self.tranches_de("BUS"))
        # un tarif d'un frais par tranches doit fixer ses tranches
        self.assertIn("indiquez le montant de chaque tranche", self.erreur(lambda: ref.enregistrer(
            self.conn, self.admin, "tarifs", {"CODTF": "BUS", "N_CLASSE": [1], "ANNEESCO": AN, "MONTANT": "60", "CODE_DEVISE": "USD"})))
        # et un tarif d'un frais ordinaire n'en a pas
        self.assertIn("une seule fois", self.erreur(lambda: ref.enregistrer(
            self.conn, self.admin, "tarifs", {"CODTF": "INSC", "N_CLASSE": [1], "ANNEESCO": AN, "MONTANT": "30",
                                              "CODE_DEVISE": "USD", "TRANCHES": "15;15"})))

    def test_total_des_tranches_d_un_tarif(self):
        self.type_frais(MONTANT="", CODE_DEVISE="", TRANCHES="")
        base = {"CODTF": "BUS", "N_CLASSE": [1], "ANNEESCO": AN, "MONTANT": "300", "CODE_DEVISE": "USD"}
        self.assertIn("manque 100,00", self.erreur(lambda: ref.enregistrer(self.conn, self.admin, "tarifs", dict(base, TRANCHES="100;100"))))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM TARIF WHERE CODTF='BUS'").fetchone()[0], 0)    # rien créé
        ref.enregistrer(self.conn, self.admin, "tarifs", dict(base, TRANCHES="3x100"))
        self.assertEqual(self.conn.execute("SELECT TRANCHES FROM TARIF WHERE CODTF='BUS'").fetchone()[0], "10000;10000;10000")

    def test_frais_scolaire_300_en_1ere_2eme_3eme_et_600_en_4eme(self):
        """Cas d'usage demandé : même frais, montant et tranches différents selon la classe."""
        ref.enregistrer(self.conn, self.admin, "types_frais",
                        {"CODTF": "FS", "DESITF": "Frais scolaire", "PAR_TRANCHE": True})              # aucun montant propre
        ref.enregistrer(self.conn, self.admin, "tarifs", {"CODTF": "FS", "N_CLASSE": [3, 4], "ANNEESCO": AN, "MONTANT": "300",
                                                          "CODE_DEVISE": "USD", "TRANCHES": "3x100"})
        ref.enregistrer(self.conn, self.admin, "tarifs", {"CODTF": "FS", "N_CLASSE": [5], "ANNEESCO": AN, "MONTANT": "600",
                                                          "CODE_DEVISE": "USD", "TRANCHES": "200;150;150;100"})
        a, b = self.ligne("CSF-0002", "FS", 3), self.ligne("CSF-0003", "FS", 5)
        self.assertEqual((a.du, a.paliers, a.prochain_montant), (30000, (10000, 20000, 30000), 10000))
        self.assertEqual((b.du, b.paliers, b.prochain_montant), (60000, (20000, 35000, 50000, 60000), 20000))
        self.assertNotIn("FS", [x.codtf for x in donnees.situation(self.conn, "CSF-0004", AN, 1)])        # classe sans tarif : rien dû
        # la classe 3 paie 3 tranches de 100, la classe 5 : 200, 150, 150, 100
        self.payer("CSF-0002", "FS", 10000)
        self.assertEqual(self.ligne("CSF-0002", "FS", 3).numero_tranche, 2)
        paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0003", AN, "FS", 10000)              # 100 sur une tranche de 200
        self.assertEqual(self.ligne("CSF-0003", "FS", 5).prochain_montant, 10000)                    # il reste 100 à payer pour la tranche 1
        paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0003", AN, "FS", 10000)
        self.assertEqual(self.ligne("CSF-0003", "FS", 5).prochain_montant, 15000)
        # le tarif figé au 1er paiement garde ses tranches
        self.assertEqual(self.conn.execute("SELECT TRANCHES FROM TARIF WHERE CODTF='FS' AND N_CLASSE=5").fetchone()[0],
                         "20000;15000;15000;10000")

    def test_paiement_fige_les_tranches_du_type_de_frais(self):
        self.type_frais(CODTF="BUS", MONTANT="60", TRANCHES="10;20;30")
        self.payer("CSF-0004", "BUS", 1000)
        self.assertEqual(self.conn.execute("SELECT TRANCHES FROM TARIF WHERE CODTF='BUS' AND N_CLASSE=1").fetchone()[0],
                         "1000;2000;3000")
        ref.enregistrer(self.conn, self.admin, "types_frais", {"CODTF": "BUS", "DESITF": "Transport", "MONTANT": "60",
                                                              "CODE_DEVISE": "USD", "PAR_TRANCHE": True, "TRANCHES": "30;30"}, ("BUS",))
        self.assertEqual(self.ligne("CSF-0004", "BUS", 1).paliers, (1000, 3000, 6000))      # classe déjà engagée : inchangée
        self.assertEqual(self.ligne("CSF-0004", "BUS", 4).paliers, (3000, 6000))             # classe neuve : nouvelles tranches

    def test_liste_affiche_les_tranches(self):
        self.type_frais(TRANCHES="10;20;30")
        types = {x["cle"][0]: x["valeurs"] for x in ref.lister(self.conn, self.admin, "types_frais")["lignes"]}
        self.assertEqual((types["BUS"][2], types["BUS"][4], types["BUS"][5]), ("60,00", "3 tranche(s)", "10,00 ; 20,00 ; 30,00"))
        self.assertEqual(types["INSC"][4:], ["En une seule fois", "", "", "", ""])      # Paiement, Tranches, Inscription, App. parents, Réservé à (non marqués)
        self.assertEqual(types["MIN1"][2], "Selon la classe")
        ref.enregistrer(self.conn, self.admin, "types_frais", {"CODTF": "X", "DESITF": "X", "PAR_TRANCHE": True})
        types = {x["cle"][0]: x["valeurs"] for x in ref.lister(self.conn, self.admin, "types_frais")["lignes"]}
        self.assertEqual(types["X"][4], "Par tranches (voir Tarifs)")
        tarifs = [x["valeurs"] for x in ref.lister(self.conn, self.admin, "tarifs")["lignes"] if x["valeurs"][1].startswith("MIN1")]
        self.assertEqual(tarifs[0][4], "40,00 ; 40,00")

    def test_la_modification_reaffiche_les_tranches_saisies(self):
        self.type_frais(TRANCHES="10;20;30")
        brut = ref.lire(self.conn, self.admin, "types_frais", ("BUS",))
        champ = next(c for c in ref.table("types_frais").champs if c.nom == "TRANCHES")
        texte = ref.afficher_valeur(champ, brut["TRANCHES"])
        self.assertEqual(texte, "10,00 ; 20,00 ; 30,00")
        ref.enregistrer(self.conn, self.admin, "types_frais", {"DESITF": "Transport", "MONTANT": "60", "CODE_DEVISE": "USD",
                                                              "PAR_TRANCHE": True, "TRANCHES": texte}, ("BUS",))   # ré-acceptée telle quelle
        self.assertEqual(self.tranches_de("BUS"), "1000;2000;3000")

    def test_l_ancienne_table_tranches_n_existe_plus(self):
        self.assertNotIn("tranches", ref.TABLES)
        self.assertIsNone(self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='TRANCHE'").fetchone())

    def test_suppression_d_un_type_sans_paiement(self):
        self.type_frais()
        ref.supprimer(self.conn, self.admin, "types_frais", ("BUS",))
        self.assertFalse(self.tranches_de_ou_none("BUS"))


class TestTarifsParClasses(Base):
    """Un tarif s'ajoute pour plusieurs classes à la fois (cases cochées) : tout est créé, ou rien."""

    def ajouter(self, classes, **plus):
        saisie = {"CODTF": "BUS", "N_CLASSE": classes, "ANNEESCO": AN, "MONTANT": "12", "CODE_DEVISE": "USD"}
        saisie.update(plus)
        return ref.enregistrer(self.conn, self.admin, "tarifs", saisie)

    def setUp(self):
        super().setUp()
        ref.enregistrer(self.conn, self.admin, "types_frais", {"CODTF": "BUS", "DESITF": "Bus", "MONTANT": "10",
                                                              "CODE_DEVISE": "USD"})

    def lignes(self):
        return self.conn.execute("SELECT N_CLASSE, MONTANT FROM TARIF WHERE CODTF='BUS' AND ANNEESCO=? ORDER BY N_CLASSE",
                                 (AN,)).fetchall()

    def test_plusieurs_classes_en_une_fois(self):
        cle = self.ajouter([1, 2, 4])                                     # liste, comme l'écran la fournit
        self.assertEqual(cle, ("BUS", 1, AN))
        self.assertEqual([tuple(l) for l in self.lignes()], [(1, 1200), (2, 1200), (4, 1200)])

    def test_texte_separe_par_des_virgules(self):
        self.ajouter("1, 3")
        self.assertEqual([l[0] for l in self.lignes()], [1, 3])

    def test_doublons_dans_la_selection_ignores(self):
        self.ajouter([2, 2, "2"])
        self.assertEqual([l[0] for l in self.lignes()], [2])

    def test_au_moins_une_classe(self):
        for vide in ([], "", None):
            with self.assertRaises(ref.ErreurRef) as e:
                self.ajouter(vide)
            self.assertIn("cochez au moins un choix", str(e.exception))
        self.assertEqual(self.lignes(), [])

    def test_tout_ou_rien_si_un_tarif_existe_deja(self):
        self.ajouter([2])
        with self.assertRaises(ref.ErreurRef) as e:
            self.ajouter([1, 2, 3], MONTANT="99")
        self.assertIn("8ème A", str(e.exception))                        # la classe déjà couverte est nommée
        self.assertEqual([tuple(l) for l in self.lignes()], [(2, 1200)])  # rien n'a été créé pour 1 et 3

    def test_classe_inconnue_refusee(self):
        with self.assertRaises(ref.ErreurRef):
            self.ajouter([1, 999])
        self.assertEqual(self.lignes(), [])

    def test_une_ligne_au_journal_par_classe(self):
        avant = self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE ACTION='REF_AJOUT'").fetchone()[0]
        self.ajouter([1, 2, 3])
        apres = self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE ACTION='REF_AJOUT'").fetchone()[0]
        self.assertEqual(apres - avant, 3)
        self.assertTrue(database.verifier_journal(self.conn)[0])

    def test_liste_rangee_par_tarif_avec_la_classe(self):
        self.ajouter([2, 1])
        t = [x["valeurs"] for x in ref.lister(self.conn, self.admin, "tarifs")["lignes"] if "BUS" in x["valeurs"][1]]
        self.assertEqual([(v[0], v[2], v[5]) for v in t], [(AN, "12,00", "7ème A"), (AN, "12,00", "8ème A")])

    def test_modification_d_une_seule_classe(self):
        self.ajouter([1, 2])
        ref.enregistrer(self.conn, self.admin, "tarifs", {"MONTANT": "15", "CODE_DEVISE": "USD"}, ("BUS", 2, AN))
        self.assertEqual([tuple(l) for l in self.lignes()], [(1, 1200), (2, 1500)])

    def test_le_paiement_utilise_le_tarif_de_la_classe(self):
        self.ajouter([1])
        self.assertEqual(donnees.montant_du(self.conn, "BUS", 1, AN), (1200, "USD"))
        self.assertEqual(donnees.montant_du(self.conn, "BUS", 2, AN), (1000, "USD"))      # sans tarif : montant du type de frais


class TestAncienneBaseAvecTrimestres(Base):
    """Une base des versions précédentes garde sa table SEMESTRE et la colonne CODE_SEMESTRE : rien n'est supprimé,
    le programme ne s'en sert plus."""

    def test_base_avec_semestres_reste_utilisable(self):
        with self.conn:
            self.conn.execute("CREATE TABLE SEMESTRE (CODE_SEMESTRE TEXT PRIMARY KEY, DESI_SEMESTRE TEXT NOT NULL, "
                              "ACTIF INTEGER NOT NULL DEFAULT 1)")
            self.conn.execute("INSERT INTO SEMESTRE VALUES ('S1', '1er semestre', 1)")
            self.conn.execute("ALTER TABLE TYPE_FRAIS ADD COLUMN CODE_SEMESTRE TEXT REFERENCES SEMESTRE(CODE_SEMESTRE)")
            self.conn.execute("UPDATE TYPE_FRAIS SET CODE_SEMESTRE = 'S1' WHERE CODTF = 'INSC'")
        analyse = migrations.analyser(self.conn)
        self.assertEqual(analyse.bloquants, [])
        self.assertFalse(analyse.a_faire)
        self.assertEqual(self.ligne("CSF-0004", "INSC", 1).designation, "Frais d'inscription")
        self.payer("CSF-0004", "INSC", 3000)
        self.assertEqual(self.ligne("CSF-0004", "INSC", 1).statut, "Soldé")
        ref.enregistrer(self.conn, self.admin, "types_frais", {"CODTF": "NEW", "DESITF": "Nouveau", "MONTANT": "5",
                                                              "CODE_DEVISE": "USD"})
        self.assertNotIn("semestres", ref.TABLES)


class TestMigration(unittest.TestCase):
    def ancienne_base(self, incomplete=False):
        """Une base de la version précédente : sans montant/devise dans TYPE_FRAIS, sans division dans CLASSE, tranches
        en pourcentages (table TRANCHE), sans colonne TRANCHES."""
        chemin = os.path.join(tempfile.mkdtemp(), "ancienne.db")
        conn = database.connecter(chemin)
        security.creer_utilisateur(conn, "admin1", "Alice Administratrice", "ADMINISTRATEUR", MDP)
        demo.semer(conn)
        with conn:
            for c in range(1, 6):                                      # INSC : même montant dans toutes les classes (AN)
                conn.execute("INSERT OR IGNORE INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE) VALUES ('INSC', ?, ?, 3000, 'USD')", (c, AN))
            for c in range(1, 4):                                      # EXAM : seulement 3 classes sur 5
                conn.execute("INSERT OR IGNORE INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE) VALUES ('EXAM', ?, ?, 1500, 'USD')", (c, AN))
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript("""
            DROP TRIGGER IF EXISTS CANDIDATURE_EXIGE_PAIEMENT; DROP TRIGGER IF EXISTS CANDIDATURE_NO_UPDATE;
            DROP TABLE IF EXISTS CANDIDATURE;               -- une base de cette version n'a pas encore de candidatures
            CREATE TABLE TF_OLD (CODTF TEXT PRIMARY KEY, DESITF TEXT NOT NULL, CODE_SEMESTRE TEXT, ACTIF INTEGER NOT NULL DEFAULT 1);
            INSERT INTO TF_OLD (CODTF, DESITF, ACTIF) SELECT CODTF, DESITF, ACTIF FROM TYPE_FRAIS;
            DROP TABLE TYPE_FRAIS; ALTER TABLE TF_OLD RENAME TO TYPE_FRAIS;
            CREATE TABLE CL_OLD (N_CLASSE INTEGER PRIMARY KEY AUTOINCREMENT, DESI_CLASSE TEXT NOT NULL, CODE_NIVEAU TEXT NOT NULL,
                                 CODE_OPTION TEXT, ACTIF INTEGER NOT NULL DEFAULT 1);
            INSERT INTO CL_OLD SELECT N_CLASSE, DESI_CLASSE, CODE_NIVEAU, CODE_OPTION, ACTIF FROM CLASSE;
            DROP TABLE CLASSE; ALTER TABLE CL_OLD RENAME TO CLASSE;
            CREATE TABLE TA_OLD (CODTF TEXT NOT NULL, N_CLASSE INTEGER NOT NULL, ANNEESCO TEXT NOT NULL, MONTANT INTEGER NOT NULL,
                                 CODE_DEVISE TEXT NOT NULL, PRIMARY KEY (CODTF, N_CLASSE, ANNEESCO));
            INSERT INTO TA_OLD SELECT CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE FROM TARIF;
            DROP TABLE TARIF; ALTER TABLE TA_OLD RENAME TO TARIF;
            CREATE TABLE TRANCHE (CODTF TEXT NOT NULL, N_TRANCHE INTEGER NOT NULL, POURCENT INTEGER NOT NULL,
                                  PRIMARY KEY (CODTF, N_TRANCHE));
            PRAGMA user_version = 4;""")
        conn.executemany("INSERT INTO TRANCHE VALUES (?,?,?)", [("MIN1", 1, 40), ("MIN1", 2, 30), ("MIN1", 3, 30)] + (
            [("MIN2", 1, 50)] if incomplete else [("MIN2", 1, 50), ("MIN2", 2, 50)]))
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def test_mise_a_jour_sans_perte(self):
        conn = self.ancienne_base()
        nb_recus = conn.execute("SELECT COUNT(*) FROM PAIEMENT").fetchone()[0]
        nb_tarifs = conn.execute("SELECT COUNT(*) FROM TARIF").fetchone()[0]
        analyse = migrations.analyser(conn)
        self.assertTrue(analyse.a_faire)
        actions = migrations.mettre_a_jour(conn, sauvegarder=False)
        self.assertTrue(any("Migration 5" in a for a in actions) and any("Migration 6" in a for a in actions), actions)
        self.assertFalse(migrations.analyser(conn).a_faire)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM PAIEMENT").fetchone()[0], nb_recus)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM TARIF").fetchone()[0], nb_tarifs)
        types = {l["CODTF"]: l for l in conn.execute("SELECT * FROM TYPE_FRAIS")}
        self.assertEqual((types["INSC"]["MONTANT"], types["INSC"]["CODE_DEVISE"]), (3000, "USD"))       # même montant partout
        self.assertIsNone(types["EXAM"]["MONTANT"])                                                      # classes non toutes couvertes
        self.assertIsNone(types["MIN1"]["MONTANT"])                                                      # montants différents
        self.assertEqual(types["MIN1"]["PAR_TRANCHE"], 0)
        classes = {l["N_CLASSE"]: l for l in conn.execute("SELECT * FROM CLASSE")}
        self.assertEqual((classes[1]["ANNEE_ETUDE"], classes[1]["DIVISION"], classes[1]["DESI_CLASSE"]), ("7ème", "A", "7ème A"))
        self.assertEqual((classes[3]["ANNEE_ETUDE"], classes[3]["DIVISION"], classes[3]["DESI_CLASSE"]), ("1ère", None, "1ère Pédagogie"))
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], migrations.VERSION_SCHEMA)
        # ce que les élèves doivent n'a pas changé
        self.assertEqual(donnees.montant_du(conn, "EXAM", 5, AN), None)
        self.assertEqual(donnees.montant_du(conn, "EXAM", 1, AN), (1500, "USD"))
        self.assertEqual(donnees.montant_du(conn, "INSC", 5, AN), (3000, "USD"))

    def test_les_tranches_en_pourcentage_deviennent_des_montants(self):
        conn = self.ancienne_base()
        migrations.mettre_a_jour(conn, sauvegarder=False)
        # MIN1 : 40 % + 30 % + 30 % de 80,00 (classe 1) -> 32,00 + 24,00 + 24,00 ; de 90,00 (classe 2) -> 36 + 27 + 27
        tr = {(l["N_CLASSE"], l["ANNEESCO"]): l["TRANCHES"] for l in conn.execute("SELECT * FROM TARIF WHERE CODTF = 'MIN1'")}
        self.assertEqual(tr[(1, AN)], "3200;2400;2400")
        self.assertEqual(tr[(2, AN)], "3600;2700;2700")
        self.assertEqual({tuple(map(int, v.split(";"))) for k, v in tr.items() if k[1] == AN and k[0] == 5}, {(5200, 3900, 3900)})
        # MIN2 : 50 % + 50 %
        self.assertEqual(conn.execute("SELECT TRANCHES FROM TARIF WHERE CODTF='MIN2' AND N_CLASSE=1 AND ANNEESCO=?", (AN,)).fetchone()[0],
                         "4000;4000")
        # chaque tarif converti a un total exact et la logique de paiement l'accepte
        for l in conn.execute("SELECT MONTANT, TRANCHES FROM TARIF WHERE TRANCHES IS NOT NULL"):
            self.assertEqual(sum(donnees.lire_tranches(l["TRANCHES"])), l["MONTANT"])
        self.assertIsNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'TRANCHE'").fetchone())      # tout converti : supprimée
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertFalse(migrations.analyser(conn).a_faire)

    def test_tranches_incompletes_gardees_a_la_main(self):
        conn = self.ancienne_base(incomplete=True)
        migrations.mettre_a_jour(conn, sauvegarder=False)
        self.assertIsNotNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'TRANCHE'").fetchone())   # rien n'est perdu
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM TRANCHE WHERE CODTF='MIN2'").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT TRANCHES FROM TARIF WHERE CODTF='MIN1' AND N_CLASSE=1 AND ANNEESCO=?", (AN,)).fetchone()[0],
                         "3200;2400;2400")                                                                   # MIN1 complet : converti
        self.assertIsNone(conn.execute("SELECT TRANCHES FROM TARIF WHERE CODTF='MIN2' AND N_CLASSE=1 AND ANNEESCO=?", (AN,)).fetchone()[0])

    def test_base_neuve_sans_migration_5(self):
        conn = database.connecter(":memory:")
        self.assertFalse(migrations.analyser(conn).a_faire)


if __name__ == "__main__":
    unittest.main(verbosity=1)

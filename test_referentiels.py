"""Tests de la mise à jour des tables de référence, des droits par rôle et de la montée de version.
Lancer :  python test_referentiels.py"""
import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import acces                      # noqa: E402
import config                     # noqa: E402
import database                   # noqa: E402
import demo                       # noqa: E402
import donnees                    # noqa: E402
import droits                     # noqa: E402
import migrations                 # noqa: E402
import paiements                  # noqa: E402
import referentiels as ref        # noqa: E402
import security                   # noqa: E402

MDP = "Tr@vail-Amour-2026"


def base(avec_demo=False):
    conn = database.connecter(os.path.join(tempfile.mkdtemp(), "ref.db"))
    security.creer_utilisateur(conn, "admin1", "Alice Administratrice", "ADMINISTRATEUR", MDP)
    admin = security.authentifier(conn, "admin1", MDP).session
    if avec_demo:
        login, mdp = demo.semer(conn)
        return conn, admin, security.authentifier(conn, login, mdp).session
    return conn, admin


def session_de(conn, login, poste):
    security.creer_utilisateur(conn, login, f"Nom de {login}", poste, MDP)
    return security.authentifier(conn, login, MDP).session


class TestReferentiels(unittest.TestCase):
    def setUp(self):
        self.conn, self.admin = base()

    def ajouter(self, cle, **saisie):
        return ref.enregistrer(self.conn, self.admin, cle, saisie)

    def erreur(self, appel):
        with self.assertRaises(ref.ErreurRef) as e:
            appel()
        return str(e.exception)

    def amorcer(self):
        """Un petit établissement complet, créé uniquement avec les écrans de mise à jour."""
        self.ajouter("annees", ANNEESCO="2026-2027", EN_COURS=True)
        self.ajouter("niveaux", CODE_NIVEAU="n3", DESI_NIVEAU="3ème année", SECTION="SECONDAIRE")
        self.ajouter("options", CODE_OPTION="sci", DESI_OPTION="Scientifique")
        self.ajouter("possede", CODE_NIVEAU="N3", CODE_OPTION="SCI")
        self.classe = self.ajouter("classes", ANNEE_ETUDE="3ème", DIVISION="a", CODE_NIVEAU="N3", CODE_OPTION="SCI")[0]
        self.ajouter("devises", CODE_DEVISE="usd", DESI_DEVISE="Dollar américain")
        self.ajouter("types_frais", CODTF="min1", DESITF="Minerval", MONTANT="80", CODE_DEVISE="USD")
        self.ajouter("tarifs", CODTF="MIN1", N_CLASSE=str(self.classe), ANNEESCO="2026-2027", MONTANT="80", CODE_DEVISE="USD")
        self.mat = self.ajouter("eleves", NOM="Kabila", POSTNOM="Mwamba", PRENOM="Joël", SEXE="M",
                                DATE_NAISSANCE="15/03/2010")[0]
        self.ajouter("inscriptions", ANNEESCO="2026-2027", MATRICULE=self.mat, N_CLASSE=str(self.classe),
                     DATE_INSCRIPTION="01/09/2026", STATUT="NOUVEAU")

    # ----------------------------------------------------------- accès
    def test_reserve_a_l_administrateur(self):
        sec = session_de(self.conn, "sec1", "SECRETAIRE")
        self.amorcer()
        for appel in (lambda: ref.lister(self.conn, sec, "eleves"),
                      lambda: ref.lire(self.conn, sec, "eleves", (self.mat,)),
                      lambda: ref.enregistrer(self.conn, sec, "niveaux", {"CODE_NIVEAU": "X", "DESI_NIVEAU": "X"}),
                      lambda: ref.supprimer(self.conn, sec, "niveaux", ("N3",)),
                      lambda: ref.changer_etat(self.conn, sec, "niveaux", ("N3",), False),
                      lambda: ref.annuler_paiement(self.conn, sec, "0001", "motif valable"),
                      lambda: ref.enregistrer(self.conn, None, "niveaux", {"CODE_NIVEAU": "X", "DESI_NIVEAU": "X"})):
            with self.assertRaises(PermissionError):
                appel()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM NIVEAU").fetchone()[0], 1)

    # ----------------------------------------------------------- ajout / modification
    def test_amorcage_complet_et_listes(self):
        self.amorcer()
        r = ref.lister(self.conn, self.admin, "inscriptions")
        self.assertEqual(len(r["lignes"]), 1)
        self.assertEqual(r["lignes"][0]["valeurs"][1], self.mat)
        self.assertRegex(self.mat, r"^0001/\d{2}$")                       # matricule 0001/AA attribué par le système
        self.assertEqual(r["lignes"][0]["valeurs"][5], "01/09/2026")
        t = ref.lister(self.conn, self.admin, "tarifs")["lignes"][0]["valeurs"]
        self.assertEqual(t[2], "80,00")
        self.assertEqual(ref.lire(self.conn, self.admin, "eleves", (self.mat,))["DATE_NAISSANCE"], "2010-03-15")
        self.assertEqual(self.conn.execute("SELECT MONTANT FROM TARIF").fetchone()[0], 8000)       # centimes
        self.assertEqual(self.conn.execute("SELECT CODE_NIVEAU FROM NIVEAU").fetchone()[0], "N3")  # majuscules

    def test_champs_obligatoires_et_formats(self):
        self.assertIn("obligatoire", self.erreur(lambda: self.ajouter("niveaux", CODE_NIVEAU="", DESI_NIVEAU="x")))
        self.assertIn("espace", self.erreur(lambda: self.ajouter("niveaux", CODE_NIVEAU="N 3", DESI_NIVEAU="x", SECTION="SECONDAIRE")))
        self.assertIn("2026-2027", self.erreur(lambda: self.ajouter("annees", ANNEESCO="2026")))
        self.assertIn("se suivent", self.erreur(lambda: self.ajouter("annees", ANNEESCO="2026-2028")))
        self.assertIn("Date invalide", self.erreur(lambda: self.ajouter("eleves", MATRICULE="A1", NOM="x", DATE_NAISSANCE="31/02/2010")))
        self.assertIn("non permise", self.erreur(lambda: self.ajouter("eleves", MATRICULE="A1", NOM="x", SEXE="Z")))
        self.assertIn("caractères", self.erreur(lambda: self.ajouter("niveaux", CODE_NIVEAU="N1", DESI_NIVEAU="x" * 200)))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM NIVEAU").fetchone()[0], 0)

    def test_doublon_refuse(self):
        self.ajouter("niveaux", CODE_NIVEAU="N1", DESI_NIVEAU="Un", SECTION="SECONDAIRE")
        self.assertIn("existe déjà", self.erreur(lambda: self.ajouter("niveaux", CODE_NIVEAU="n1", DESI_NIVEAU="Autre", SECTION="SECONDAIRE")))

    def test_modification_cle_non_modifiable(self):
        self.ajouter("niveaux", CODE_NIVEAU="N1", DESI_NIVEAU="Un", SECTION="SECONDAIRE")
        ref.enregistrer(self.conn, self.admin, "niveaux", {"CODE_NIVEAU": "N9", "DESI_NIVEAU": "Première année", "SECTION": "SECONDAIRE"}, ("N1",))
        self.assertEqual(self.conn.execute("SELECT CODE_NIVEAU, DESI_NIVEAU FROM NIVEAU").fetchone()[:], ("N1", "Première année"))
        actions = [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")]
        self.assertEqual(actions.count("REF_AJOUT"), 1)
        self.assertEqual(actions.count("REF_MODIFICATION"), 1)

    def test_modification_sans_changement_ne_journalise_pas(self):
        self.ajouter("niveaux", CODE_NIVEAU="N1", DESI_NIVEAU="Un", SECTION="SECONDAIRE")
        avant = self.conn.execute("SELECT COUNT(*) FROM JOURNAL").fetchone()[0]
        ref.enregistrer(self.conn, self.admin, "niveaux", {"DESI_NIVEAU": "Un", "SECTION": "SECONDAIRE"}, ("N1",))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM JOURNAL").fetchone()[0], avant)

    def test_annee_en_cours_unique(self):
        self.ajouter("annees", ANNEESCO="2025-2026", EN_COURS=True)
        self.ajouter("annees", ANNEESCO="2026-2027", EN_COURS=True)
        self.assertEqual([l[0] for l in self.conn.execute("SELECT ANNEESCO FROM ANNEE_SCO WHERE EN_COURS = 1")], ["2026-2027"])
        self.assertEqual(donnees.annee_courante(self.conn), "2026-2027")
        self.assertIn("en cours", self.erreur(lambda: ref.changer_etat(self.conn, self.admin, "annees", ("2026-2027",), False)))

    def test_classe_option_doit_etre_proposee_au_niveau(self):
        self.ajouter("niveaux", CODE_NIVEAU="N3", DESI_NIVEAU="Humanités", SECTION="SECONDAIRE")
        self.ajouter("options", CODE_OPTION="SCI", DESI_OPTION="Scientifique")
        msg = self.erreur(lambda: self.ajouter("classes", ANNEE_ETUDE="3ème", CODE_NIVEAU="N3", CODE_OPTION="SCI"))
        self.assertIn("Options par niveau", msg)
        self.ajouter("classes", ANNEE_ETUDE="7ème", DIVISION="A", CODE_NIVEAU="N3")      # niveau sans option : option vide
        self.ajouter("possede", CODE_NIVEAU="N3", CODE_OPTION="SCI")
        c = self.ajouter("classes", ANNEE_ETUDE="3ème", CODE_NIVEAU="N3", CODE_OPTION="SCI")
        self.assertEqual(c, (2,))                                                          # numéro automatique

    def test_option_obligatoire_en_humanites_et_interdite_ailleurs(self):
        self.ajouter("niveaux", CODE_NIVEAU="HUM", DESI_NIVEAU="Humanités", SECTION="SECONDAIRE")
        self.ajouter("niveaux", CODE_NIVEAU="PRI", DESI_NIVEAU="Primaire", SECTION="PRIMAIRE")
        self.ajouter("options", CODE_OPTION="SCI", DESI_OPTION="Scientifique")
        self.ajouter("possede", CODE_NIVEAU="HUM", CODE_OPTION="SCI")
        self.assertIn("choisissez l'option", self.erreur(lambda: self.ajouter("classes", ANNEE_ETUDE="1ère", DIVISION="A", CODE_NIVEAU="HUM")))
        self.assertIn("humanités", self.erreur(lambda: self.ajouter("classes", ANNEE_ETUDE="1ère", DIVISION="A", CODE_NIVEAU="PRI", CODE_OPTION="SCI")))
        self.ajouter("classes", ANNEE_ETUDE="1ère", DIVISION="A", CODE_NIVEAU="PRI")
        self.ajouter("classes", ANNEE_ETUDE="1ère", DIVISION="A", CODE_NIVEAU="HUM", CODE_OPTION="SCI")

    def test_classes_et_divisions(self):
        """Désignation composée par le système ; divisions A, B, C, D ; doublons refusés ; suit les modifications."""
        self.ajouter("niveaux", CODE_NIVEAU="PRI", DESI_NIVEAU="Primaire", SECTION="PRIMAIRE")
        nums = [self.ajouter("classes", ANNEE_ETUDE="1ère primaire", DIVISION=d, CODE_NIVEAU="PRI")[0] for d in "abcd"]
        noms = [self.conn.execute("SELECT DESI_CLASSE FROM CLASSE WHERE N_CLASSE = ?", (n,)).fetchone()[0] for n in nums]
        self.assertEqual(noms, ["1ère primaire A", "1ère primaire B", "1ère primaire C", "1ère primaire D"])
        self.assertIn("existe déjà", self.erreur(lambda: self.ajouter("classes", ANNEE_ETUDE="1ère PRIMAIRE", DIVISION="B", CODE_NIVEAU="PRI")))
        self.assertIn("Division", self.erreur(lambda: self.ajouter("classes", ANNEE_ETUDE="1ère", DIVISION="ABCD", CODE_NIVEAU="PRI")))
        ref.enregistrer(self.conn, self.admin, "classes", {"ANNEE_ETUDE": "1ère primaire", "DIVISION": "E", "CODE_NIVEAU": "PRI",
                                                          "CODE_OPTION": ""}, (nums[3],))
        self.assertEqual(self.conn.execute("SELECT DESI_CLASSE FROM CLASSE WHERE N_CLASSE = ?", (nums[3],)).fetchone()[0],
                         "1ère primaire E")
        self.ajouter("classes", ANNEE_ETUDE="6ème primaire", CODE_NIVEAU="PRI")           # classe unique : sans division
        self.assertEqual(self.conn.execute("SELECT DESI_CLASSE FROM CLASSE WHERE N_CLASSE = 5").fetchone()[0], "6ème primaire")

    def test_valeur_hors_liste_refusee(self):
        self.assertIn("liste", self.erreur(lambda: self.ajouter("classes", ANNEE_ETUDE="X", CODE_NIVEAU="N99")))
        self.assertIn("liste", self.erreur(lambda: self.ajouter("tarifs", CODTF="Z", N_CLASSE="abc", ANNEESCO="2026-2027",
                                                                MONTANT="5", CODE_DEVISE="USD")))

    def test_montants(self):
        self.amorcer()
        base_t = dict(CODTF="MIN1", N_CLASSE=str(self.classe), ANNEESCO="2026-2027", CODE_DEVISE="USD")
        self.assertIn("Montant invalide", self.erreur(lambda: self.ajouter("tarifs", MONTANT="abc", **base_t)))
        self.assertIn("supérieur à zéro", self.erreur(lambda: self.ajouter("tarifs", MONTANT="0", **base_t)))
        ref.enregistrer(self.conn, self.admin, "tarifs", {"MONTANT": "1 250,50", "CODE_DEVISE": "USD"},
                        ("MIN1", self.classe, "2026-2027"))
        self.assertEqual(self.conn.execute("SELECT MONTANT FROM TARIF").fetchone()[0], 125050)

    # ----------------------------------------------------------- suppression / désactivation
    def test_suppression_libre_puis_bloquee_si_utilise(self):
        self.ajouter("niveaux", CODE_NIVEAU="N1", DESI_NIVEAU="Un", SECTION="SECONDAIRE")
        ref.supprimer(self.conn, self.admin, "niveaux", ("N1",))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM NIVEAU").fetchone()[0], 0)
        self.amorcer()
        msg = self.erreur(lambda: ref.supprimer(self.conn, self.admin, "niveaux", ("N3",)))
        self.assertIn("Classes (1)", msg)
        self.assertIn("Désactivez", msg)
        self.assertIn("Inscriptions (1)", self.erreur(lambda: ref.supprimer(self.conn, self.admin, "eleves", (self.mat,))))
        self.assertIn("Tarifs (1)", self.erreur(lambda: ref.supprimer(self.conn, self.admin, "types_frais", ("MIN1",))))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM NIVEAU").fetchone()[0], 1)

    def test_desactivation_et_reactivation(self):
        self.amorcer()
        ref.changer_etat(self.conn, self.admin, "niveaux", ("N3",), False)
        self.assertEqual(self.conn.execute("SELECT ACTIF FROM NIVEAU").fetchone()[0], 0)
        self.assertNotIn("N3", [v for v, _ in ref.options(self.conn, "niveaux")])           # plus proposé
        self.assertIn("N3", [v for v, _ in ref.options(self.conn, "niveaux", inclure="N3")])  # sauf s'il est déjà choisi
        self.assertFalse(ref.lister(self.conn, self.admin, "niveaux")["lignes"][0]["actif"])
        ref.changer_etat(self.conn, self.admin, "niveaux", ("N3",), True)
        self.assertIn("N3", [v for v, _ in ref.options(self.conn, "niveaux")])
        actions = [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")]
        self.assertIn("REF_DESACTIVATION", actions)
        self.assertIn("REF_REACTIVATION", actions)

    def test_operations_non_prevues(self):
        self.amorcer()
        self.assertIn("n'est pas prévue", self.erreur(lambda: ref.enregistrer(self.conn, self.admin, "possede",
                                                                              {"CODE_NIVEAU": "N3", "CODE_OPTION": "SCI"}, ("N3", "SCI"))))
        self.assertIn("pas permise", self.erreur(lambda: ref.supprimer(self.conn, self.admin, "paiements", ("x",))))
        self.assertIn("n'est pas prévu", self.erreur(lambda: ref.enregistrer(self.conn, self.admin, "paiements", {})))
        self.assertIn("désactivation", self.erreur(lambda: ref.changer_etat(self.conn, self.admin, "tarifs",
                                                                         ("MIN1", self.classe, "2026-2027"), False)))

    def test_eleve_desactive_introuvable_et_sans_paiement(self):
        conn, admin, perc = base(avec_demo=True)
        self.assertTrue(donnees.rechercher_eleves(conn, "CSF-0004"))
        ref.changer_etat(conn, admin, "eleves", ("CSF-0004",), False)
        self.assertEqual(donnees.rechercher_eleves(conn, "CSF-0004"), [])
        with self.assertRaises(paiements.ErreurPaiement) as e:
            paiements.enregistrer_paiement(conn, perc, "CSF-0004", demo.ANNEE_COURANTE, "INSC", 3000)
        self.assertIn("désactivé", str(e.exception))
        ref.changer_etat(conn, admin, "eleves", ("CSF-0004",), True)
        paiements.enregistrer_paiement(conn, perc, "CSF-0004", demo.ANNEE_COURANTE, "INSC", 3000)
        ref.changer_etat(conn, admin, "types_frais", ("MIN1",), False)
        with self.assertRaises(paiements.ErreurPaiement):
            paiements.enregistrer_paiement(conn, perc, "CSF-0004", demo.ANNEE_COURANTE, "MIN1", 1000)

    # ----------------------------------------------------------- règles d'intégrité
    def test_tarif_et_inscription_verrouilles_apres_paiement(self):
        conn, admin, perc = base(avec_demo=True)
        n = paiements.enregistrer_paiement(conn, perc, "CSF-0004", demo.ANNEE_COURANTE, "INSC", 3000)
        cle_tarif = ("INSC", 1, demo.ANNEE_COURANTE)           # tarif « figé » au moment du paiement
        e = lambda **kw: self.erreur_sur(conn, lambda: ref.enregistrer(conn, admin, "tarifs", kw, cle_tarif))
        self.assertIn("devise", e(MONTANT="30", CODE_DEVISE="CDF"))
        self.assertIn("en dessous", e(MONTANT="20", CODE_DEVISE="USD"))
        ref.enregistrer(conn, admin, "tarifs", {"MONTANT": "35", "CODE_DEVISE": "USD"}, cle_tarif)    # hausse permise
        # frais payé par tranches : le montant ne bouge plus dès qu'une tranche est payée
        paiements.enregistrer_paiement(conn, perc, "CSF-0004", demo.ANNEE_COURANTE, "MIN1", 4000)
        self.assertIn("par tranches", self.erreur_sur(conn, lambda: ref.enregistrer(
            conn, admin, "tarifs", {"MONTANT": "90", "CODE_DEVISE": "USD"}, ("MIN1", 1, demo.ANNEE_COURANTE))))
        self.assertIn("changer la classe", self.erreur_sur(conn, lambda: ref.enregistrer(
            conn, admin, "inscriptions", {"N_CLASSE": "2", "STATUT": "NOUVEAU"}, (demo.ANNEE_COURANTE, "CSF-0004"))))
        ref.enregistrer(conn, admin, "inscriptions", {"N_CLASSE": "1", "STATUT": "TRANSFERT"}, (demo.ANNEE_COURANTE, "CSF-0004"))
        self.assertEqual(conn.execute("SELECT STATUT FROM INSCRIRE WHERE MATRICULE='CSF-0004' AND ANNEESCO=?",
                                      (demo.ANNEE_COURANTE,)).fetchone()[0], "TRANSFERT")

    def erreur_sur(self, conn, appel):
        with self.assertRaises(ref.ErreurRef) as e:
            appel()
        return str(e.exception)

    def test_percepteurs(self):
        id_user = security.creer_utilisateur(self.conn, "perc9", "Percepteur Neuf", "PERCEPTEUR", MDP)
        self.assertEqual([v for v, _ in ref.options(self.conn, "comptes_percepteurs")], [])      # déjà enregistré
        n = self.conn.execute("SELECT N_PERC FROM PERCEPTEUR WHERE ID_USER = ?", (id_user,)).fetchone()[0]
        ref.supprimer(self.conn, self.admin, "percepteurs", (n,))                                  # aucun paiement : permis
        self.assertEqual([v for v, _ in ref.options(self.conn, "comptes_percepteurs")], [id_user])
        n2 = ref.enregistrer(self.conn, self.admin, "percepteurs", {"ID_USER": str(id_user)})[0]
        self.assertEqual(ref.lister(self.conn, self.admin, "percepteurs")["lignes"][0]["valeurs"][1], "Percepteur Neuf")
        ref.changer_etat(self.conn, self.admin, "percepteurs", (n2,), False)
        self.assertFalse(security.authentifier(self.conn, "perc9", MDP).ok)                        # compte bloqué
        self.assertFalse(ref.lister(self.conn, self.admin, "percepteurs")["lignes"][0]["actif"])
        ref.changer_etat(self.conn, self.admin, "percepteurs", (n2,), True)
        self.assertTrue(security.authentifier(self.conn, "perc9", MDP).ok)

    def test_percepteur_avec_paiements_non_supprimable(self):
        conn, admin, perc = base(avec_demo=True)
        n = conn.execute("SELECT N_PERC FROM PERCEPTEUR").fetchone()[0]
        self.assertIn("Paiements", self.erreur_sur(conn, lambda: ref.supprimer(conn, admin, "percepteurs", (n,))))

    # ----------------------------------------------------------- paiements
    def test_annulation_de_paiement(self):
        conn, admin, perc = base(avec_demo=True)
        n = paiements.enregistrer_paiement(conn, perc, "CSF-0004", demo.ANNEE_COURANTE, "INSC", 3000)
        avant = {l.codtf: l.paye for l in donnees.situation(conn, "CSF-0004", demo.ANNEE_COURANTE, 1)}["INSC"]
        self.assertEqual(avant, 3000)
        self.assertIn("motif", self.erreur_sur(conn, lambda: ref.annuler_paiement(conn, admin, n, "")))
        ref.annuler_paiement(conn, admin, n, "Erreur de saisie du montant")
        apres = {l.codtf: l.paye for l in donnees.situation(conn, "CSF-0004", demo.ANNEE_COURANTE, 1)}["INSC"]
        self.assertEqual(apres, 0)
        r = conn.execute("SELECT STATUT, MOTIF_ANNULATION, ANNULE_PAR, DATE_ANNULATION, MONT_PAYE FROM PAIEMENT WHERE N_RECU = ?", (n,)).fetchone()
        self.assertEqual((r[0], r[1], r[2], r[4]), ("ANNULE", "Erreur de saisie du montant", "admin1", 3000))
        self.assertIsNotNone(r[3])
        self.assertIn("déjà annulé", self.erreur_sur(conn, lambda: ref.annuler_paiement(conn, admin, n, "Encore un motif")))
        self.assertIn("introuvable", self.erreur_sur(conn, lambda: ref.annuler_paiement(conn, admin, "0000-000000", "Motif valable")))
        with self.assertRaises(paiements.ErreurPaiement):                                  # plus de duplicata
            paiements.preparer_pdf(conn, admin, n, duplicata=True)
        paiements.enregistrer_paiement(conn, perc, "CSF-0004", demo.ANNEE_COURANTE, "INSC", 3000)   # on peut repayer
        ligne = [l for l in ref.lister(conn, admin, "paiements")["lignes"] if l["cle"] == (n,)][0]
        self.assertFalse(ligne["actif"])
        self.assertEqual(ligne["valeurs"][-1], "ANNULÉ")
        self.assertEqual(paiements.rapport_journalier(conn, perc, __import__("datetime").date.today())["nb_annules"], 1)
        # le reçu reste intact : modification et suppression directes toujours impossibles
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("UPDATE PAIEMENT SET MONT_PAYE = 1 WHERE N_RECU = ?", (n,))
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM PAIEMENT WHERE N_RECU = ?", (n,))
        self.assertIn("PAIEMENT_ANNULE", [l["ACTION"] for l in conn.execute("SELECT ACTION FROM JOURNAL")])

    # ----------------------------------------------------------- listes
    def test_toutes_les_tables_se_listent_avec_les_donnees_de_demo(self):
        conn, admin, _ = base(avec_demo=True)
        attendu = {"annees": 2, "niveaux": 5, "classes": 5, "eleves": 6, "devises": 2}
        for cle in ref.TABLES:
            r = ref.lister(conn, admin, cle)
            self.assertTrue(r["colonnes"], cle)
            for ligne in r["lignes"]:
                self.assertEqual(len(ligne["valeurs"]), len(r["colonnes"]), cle)
                ref.lire(conn, admin, cle, ligne["cle"])                                   # chaque ligne se relit
        for cle, n in attendu.items():
            self.assertEqual(len(ref.lister(conn, admin, cle)["lignes"]), n, cle)
        self.assertGreater(len(ref.lister(conn, admin, "paiements")["lignes"]), 5)

    def test_recherche_sans_accents_ni_casse(self):
        conn, admin, _ = base(avec_demo=True)
        trouves = ref.lister(conn, admin, "eleves", "mutombo grace")["lignes"]
        self.assertEqual([l["cle"] for l in trouves], [("CSF-0004",)])
        self.assertEqual(ref.lister(conn, admin, "eleves", "introuvable")["lignes"], [])

    def test_chaque_table_se_liste_vide(self):
        for cle in ref.TABLES:
            self.assertEqual(ref.lister(self.conn, self.admin, cle)["lignes"], [], cle)

    def test_journal_intact_apres_toutes_ces_operations(self):
        self.amorcer()
        ref.changer_etat(self.conn, self.admin, "niveaux", ("N3",), False)
        self.assertEqual(database.verifier_journal(self.conn), (True, None))
        detail = " ".join(l["DETAIL"] for l in self.conn.execute("SELECT DETAIL FROM JOURNAL"))
        self.assertNotIn("Mwamba", detail)                                                  # pas de données personnelles


# ================================================================== droits par rôle
class TestRoles(unittest.TestCase):
    def setUp(self):
        self.conn, self.admin = base()

    def test_droits_de_base_semes_dans_une_base_neuve(self):
        lignes = {r["role"]: r for r in acces.lister_roles(self.conn, self.admin)}
        self.assertEqual(list(lignes), list(config.ROLES))
        self.assertEqual(lignes["PERCEPTEUR"]["droits"], {("paiement", "LECTURE"), ("paiement", "AJOUT")})
        self.assertEqual(lignes["SECRETAIRE"]["droits"], {("dossier_eleve", "LECTURE"), ("dossier_eleve", "MODIFICATION"),
                                                          ("inscription", "LECTURE"), ("inscription", "AJOUT"), ("inscription", "MODIFICATION")})
        self.assertEqual(lignes["ADMINISTRATEUR"]["nb_utilisateurs"], 1)

    def test_changer_les_droits_d_un_role(self):
        sec_avant = session_de(self.conn, "sec1", "SECRETAIRE")
        droits_role, n = acces.definir_droits_role(self.conn, self.admin, "SECRETAIRE", {("paiement", "AJOUT")})
        self.assertEqual((droits_role, n), ({("paiement", "AJOUT"), ("paiement", "LECTURE")}, 0))
        self.assertFalse(droits.a_droit(self.conn, sec_avant, "paiement", "LECTURE"))      # comptes existants inchangés
        sec_apres = session_de(self.conn, "sec2", "SECRETAIRE")
        self.assertTrue(droits.a_droit(self.conn, sec_apres, "paiement", "AJOUT"))         # nouveaux comptes
        _, n = acces.definir_droits_role(self.conn, self.admin, "SECRETAIRE", {("paiement", "AJOUT")}, appliquer_aux_utilisateurs=True)
        self.assertEqual(n, 2)
        self.assertTrue(droits.a_droit(self.conn, sec_avant, "paiement", "LECTURE"))
        acces.definir_droits_role(self.conn, self.admin, "SECRETAIRE", set())              # on peut tout retirer
        self.assertEqual(droits.droits_par_defaut(self.conn, "SECRETAIRE"), set())
        sec3 = session_de(self.conn, "sec3", "SECRETAIRE")
        self.assertEqual(droits.droits_utilisateur(self.conn, sec3.id_user), set())

    def test_changement_de_poste_utilise_les_droits_du_role(self):
        acces.definir_droits_role(self.conn, self.admin, "CONTROLEUR", {("paiement", "AJOUT")})
        id_user, _ = acces.creer_compte(self.conn, self.admin, "marie", "Marie Kabila", "SECRETAIRE")
        acces.modifier_compte(self.conn, self.admin, id_user, "Marie Kabila", "CONTROLEUR", True)
        self.assertEqual(droits.droits_utilisateur(self.conn, id_user), {("paiement", "AJOUT"), ("paiement", "LECTURE")})
        acces.droits_par_defaut_du_poste(self.conn, self.admin, id_user)

    def test_reserve_admin_et_validations(self):
        sec = session_de(self.conn, "sec1", "SECRETAIRE")
        with self.assertRaises(PermissionError):
            acces.lister_roles(self.conn, sec)
        with self.assertRaises(PermissionError):
            acces.definir_droits_role(self.conn, sec, "SECRETAIRE", {("paiement", "AJOUT")})
        with self.assertRaises(acces.ErreurAcces):
            acces.definir_droits_role(self.conn, self.admin, "ROI", set())
        with self.assertRaises(acces.ErreurAcces):
            acces.definir_droits_role(self.conn, self.admin, "SECRETAIRE", {("paiement", "SUPPRESSION")})
        acces.definir_droits_role(self.conn, self.admin, "SECRETAIRE", {("paiement", "AJOUT")})
        self.assertIn("DROITS_ROLE_MODIFIES", [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")])


# ================================================================== montée de version depuis la 0.4
def base_version_04(chemin):
    """Base telle que livrée par la version 0.4 : sans colonnes ACTIF, sans annulation, sans ROLE_DROIT."""
    s = database.SCHEMA
    s = re.sub(r",\n\s+ACTIF\s+INTEGER NOT NULL DEFAULT 1 CHECK \(ACTIF IN \(0,1\)\),\n\s+NATIONALITE\s+TEXT,\n\s+CODE_QR\s+TEXT[^\n]*\n\);",
               "\n);", s)                                   # ELEVE d'avant : ni ACTIF, ni NATIONALITE, ni CODE_QR
    s = re.sub(r",\n\s+ACTIF\s+INTEGER NOT NULL DEFAULT 1 CHECK \(ACTIF IN \(0,1\)\)(?=\n\);)", "", s)
    s = re.sub(r"\n\s+ACTIF\s+INTEGER NOT NULL DEFAULT 1 CHECK \(ACTIF IN \(0,1\)\),\n(?=\s+FOREIGN KEY)", "\n", s)
    s = re.sub(r"\n\s+(MOTIF_ANNULATION|DATE_ANNULATION|ANNULE_PAR)\s+TEXT,[^\n]*", "", s)
    s = re.sub(r"CREATE TABLE IF NOT EXISTS ROLE_DROIT \(.*?\);\n", "", s, flags=re.S)
    assert "ROLE_DROIT" not in s and "MOTIF_ANNULATION" not in s.split("CREATE TABLE IF NOT EXISTS PAIEMENT")[1].split(");")[0]
    c = sqlite3.connect(chemin)
    c.executescript(s)
    c.execute("INSERT INTO UTILISATEUR (LOGIN, NOM_COMPLET, ROLE, MDP_HASH, DATE_CREATION) VALUES "
              "('admin', 'Alice', 'ADMINISTRATEUR', ?, '2026-10-08T00:00:00+00:00')", (security.hacher_mdp(MDP),))
    c.execute("INSERT INTO DROIT VALUES (1, 'paiement', 'LECTURE')")
    c.execute("INSERT INTO DROIT VALUES (1, 'paiement', 'IMPRESSION')")
    c.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU) VALUES ('N1', 'Première')")
    c.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('CSF-1', 'KABILA')")
    c.execute("PRAGMA user_version = 2")
    c.commit()
    c.close()


class TestMonteeDeVersion(unittest.TestCase):
    def test_base_04_mise_a_niveau_sans_perte(self):
        chemin = os.path.join(tempfile.mkdtemp(), "v04.db")
        base_version_04(chemin)
        c = sqlite3.connect(chemin)
        self.assertNotIn("ACTIF", [r[1] for r in c.execute("PRAGMA table_info(ELEVE)")])
        c.close()
        conn = database.connecter(chemin)
        for t in ("NIVEAU", "OPTION_SCO", "CLASSE", "ANNEE_SCO", "ELEVE", "DEVISE", "TYPE_FRAIS"):
            self.assertIn("ACTIF", [r[1] for r in conn.execute(f"PRAGMA table_info({t})")], t)
        for col in ("MOTIF_ANNULATION", "DATE_ANNULATION", "ANNULE_PAR"):
            self.assertIn(col, [r[1] for r in conn.execute("PRAGMA table_info(PAIEMENT)")])
        self.assertEqual(conn.execute("SELECT ACTIF FROM ELEVE").fetchone()[0], 1)             # lignes existantes : actives
        for col in ("NATIONALITE", "CODE_QR"):
            self.assertIn(col, [r[1] for r in conn.execute("PRAGMA table_info(ELEVE)")])
        ligne = conn.execute("SELECT MATRICULE, CODE_QR FROM ELEVE").fetchone()
        self.assertEqual(ligne["MATRICULE"], "CSF-1")                                            # matricule conservé
        self.assertTrue(ligne["CODE_QR"].startswith("CSF|CSF-1|"))                               # QR attribué à l'existant
        self.assertEqual(conn.execute("SELECT DESI_NIVEAU FROM NIVEAU").fetchone()[0], "Première")
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], migrations.VERSION_SCHEMA)
        attendu = sum(len(droits.droits_config(r)) for r in config.ROLES)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ROLE_DROIT").fetchone()[0], attendu)
        self.assertEqual(droits.droits_par_defaut(conn, "PERCEPTEUR"), {("paiement", "LECTURE"), ("paiement", "AJOUT")})
        self.assertEqual(droits.droits_utilisateur(conn, 1), {("paiement", "LECTURE")})        # IMPRESSION retiré
        self.assertFalse(migrations.analyser(conn).a_faire)
        self.assertTrue(any(Path(config.DOSSIER_SAUVEGARDES).glob("Avant-miseajour*")))
        self.assertEqual(database.verifier_journal(conn)[0], True)
        # et les nouvelles écrans fonctionnent sur cette base
        admin = security.authentifier(conn, "admin", MDP).session
        ref.changer_etat(conn, admin, "eleves", ("CSF-1",), False)
        self.assertEqual(conn.execute("SELECT ACTIF FROM ELEVE").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)

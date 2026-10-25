"""Tests du module Inscription : tables, frais d'inscription, formulaire, refus sans paiement, liste d'attente, fiche PDF.
Lancer :  python test_inscription.py"""
import os
import sqlite3
import tempfile
import unittest
from datetime import date

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import config                    # noqa: E402
import database                  # noqa: E402
import demo                      # noqa: E402
import droits                    # noqa: E402
import inscription               # noqa: E402
import migrations                # noqa: E402
import modules                   # noqa: E402
import paiements                 # noqa: E402
import referentiels as ref       # noqa: E402
import reinitialisation          # noqa: E402
import security                  # noqa: E402
from inscription import ErreurInscription   # noqa: E402

MDP = "Tr@vail-Amour-2026"
AN = demo.ANNEE_COURANTE                      # 2026-2027


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(os.path.join(tempfile.mkdtemp(), "insc.db"))
        security.creer_utilisateur(self.conn, "admin1", "Alice Administratrice", "ADMINISTRATEUR", MDP)
        self.admin = security.authentifier(self.conn, "admin1", MDP).session
        login, mdp = demo.semer(self.conn)
        self.perc = security.authentifier(self.conn, login, mdp).session
        # le secrétaire : Lecture + Ajout sur le module Inscription (accordés par l'administrateur)
        id_sec = security.creer_utilisateur(self.conn, "sec1", "Sophie Secrétaire", "SECRETAIRE", MDP)
        with self.conn:
            droits.remplacer_droits(self.conn, id_sec, {("inscription", "LECTURE"), ("inscription", "AJOUT")})
        self.sec = security.authentifier(self.conn, "sec1", MDP).session
        # le type de frais « Frais d'inscription » (INSC) est marqué comme tel par l'administrateur
        ref.enregistrer(self.conn, self.admin, "types_frais",
                        {"CODTF": "INSC", "DESITF": "Frais d'inscription", "MONTANT": "30", "CODE_DEVISE": "USD",
                         "POUR_INSCRIPTION": True}, ("INSC",))
        self.nb_cand = 0
        self.recu = self.recu_candidat()         # reçu valide de frais d'inscription (année en cours)

    def recu_candidat(self):
        """Reçu d'inscription valide, neuf à chaque appel : payé par un candidat (sans matricule), comme à la caisse."""
        self.nb_cand += 1
        return paiements.enregistrer_paiement_inscription(self.conn, self.perc, AN, 1, "INSC", 3000, f"Payeur{'x' * self.nb_cand}")

    def payer(self, matricule, codtf, centimes):
        return paiements.enregistrer_paiement(self.conn, self.perc, matricule, AN, codtf, centimes)

    def formulaire(self, **plus):
        saisie = dict(n_recu=self.recu, nom="kalala", postnom="mwamba", prenom="joël", sexe="M", date_naissance="15/03/2012",
                      lieu_naissance="Kinshasa", nationalite="Congolaise", adresse="Av. de la Paix 12, Lemba",
                      telephone="0810000099", ecole_origine="Institut Les Lauriers", pourcent_origine="68,5",
                      doublant=False, n_classe=1, nom_tuteur="Mme Kalala Rose", tel_tuteur="+243 82 000 00 01",
                      adresse_tuteur="Av. de la Paix 12, Lemba")
        saisie.update(plus)
        return saisie


class TestTables(Base):
    def test_tables_creees(self):
        noms = {l[0] for l in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("CANDIDATURE", noms)
        colonnes = {l[1] for l in self.conn.execute("PRAGMA table_info(TYPE_FRAIS)")}
        self.assertIn("POUR_INSCRIPTION", colonnes)

    def test_une_ancienne_base_recoit_les_nouvelles_tables(self):
        """Une base d'avant le module Inscription (sans CANDIDATURE ni POUR_INSCRIPTION) est mise à jour sans perte."""
        debut = database.SCHEMA.index("-- ===================== Inscription")
        fin = database.SCHEMA.index("-- Données d'ESSAI")
        ancien = database.SCHEMA[:debut] + database.SCHEMA[fin:]
        ancien = ancien.replace("    TRANCHES      TEXT,", "    TRANCHES      TEXT")
        ancien = "\n".join(l for l in ancien.split("\n")
                          if not l.strip().startswith(("POUR_INSCRIPTION", "POUR_APPLI_PARENTS", "CLASSE_CIBLE")))
        self.assertNotIn("POUR_INSCRIPTION", ancien)
        chemin = os.path.join(tempfile.mkdtemp(), "ancienne.db")
        conn = sqlite3.connect(chemin)
        conn.row_factory = sqlite3.Row
        conn.executescript(ancien)
        conn.execute("INSERT INTO TYPE_FRAIS (CODTF, DESITF) VALUES ('X', 'Ancien frais')")
        conn.execute(f"PRAGMA user_version = {migrations.VERSION_SCHEMA}")
        conn.commit()
        self.assertTrue(migrations.analyser(conn).a_faire)
        migrations.mettre_a_jour(conn, sauvegarder=False)
        self.assertFalse(migrations.analyser(conn).a_faire)
        self.assertEqual(conn.execute("SELECT DESITF, POUR_INSCRIPTION FROM TYPE_FRAIS WHERE CODTF = 'X'").fetchone()[:],
                         ("Ancien frais", 0))                                 # rien n'est perdu, le nouveau champ vaut 0
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM CANDIDATURE").fetchone()[0], 0)
        conn.close()

    def test_reinitialisation_vide_aussi_les_candidatures(self):
        inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire())
        reinitialisation.reinitialiser(self.conn, self.admin, MDP, "REINITIALISER")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CANDIDATURE").fetchone()[0], 0)


class TestFraisInscription(Base):
    def test_seul_un_type_marque_valide_une_candidature(self):
        recu_min = self.payer("CSF-0004", "EXAM", 1500)
        with self.assertRaises(ErreurInscription) as e:
            inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire(n_recu=recu_min))
        self.assertIn("pas les frais d'inscription", str(e.exception))

    def test_frais_d_inscription_pas_par_tranches(self):
        with self.assertRaises(ref.ErreurRef):
            ref.enregistrer(self.conn, self.admin, "types_frais",
                            {"CODTF": "INSC", "DESITF": "Frais d'inscription", "MONTANT": "30", "CODE_DEVISE": "USD",
                             "PAR_TRANCHE": True, "TRANCHES": "10;10;10", "POUR_INSCRIPTION": True}, ("INSC",))

    def test_aucun_type_marque_aucune_candidature(self):
        ref.enregistrer(self.conn, self.admin, "types_frais",
                        {"CODTF": "INSC", "DESITF": "Frais d'inscription", "MONTANT": "30", "CODE_DEVISE": "USD",
                         "POUR_INSCRIPTION": False}, ("INSC",))
        self.assertEqual(inscription.types_frais_inscription(self.conn), [])
        with self.assertRaises(ErreurInscription):
            inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire())


class TestFormulaire(Base):
    def test_candidature_enregistree_sur_la_liste_d_attente(self):
        r = inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire())
        self.assertEqual((r["num_cand"], r["ordre"], r["rang"], r["annee"]), ("C0001/26", 1, 1, AN))
        f = inscription.charger_candidature(self.conn, self.sec, r["n_cand"])
        self.assertEqual((f["nom_complet"], f["statut"], f["classe"], f["pourcent_origine"], f["doublant"]),
                         ("KALALA MWAMBA Joël", "EN_ATTENTE", "7ème A", "68,5", False))
        self.assertEqual((f["nom_tuteur"], f["tel_tuteur"], f["date_naissance"]),
                         ("Mme Kalala Rose", "+243 82 000 00 01", "15/03/2012"))

    def test_le_journal_garde_la_trace(self):
        inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire())
        l = self.conn.execute("SELECT LOGIN, DETAIL FROM JOURNAL WHERE ACTION = 'CANDIDATURE_ENREGISTREE'").fetchone()
        self.assertEqual(l["LOGIN"], "sec1")
        self.assertIn(self.recu, l["DETAIL"])

    def test_numero_de_recu_sans_zeros_accepte(self):
        r = inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire(n_recu=str(int(self.recu))))
        self.assertEqual(r["ordre"], 1)

    def test_champs_obligatoires(self):
        for cle, message in (("nom", "nom du candidat"), ("adresse", "adresse du candidat"), ("ecole_origine", "ancienne école"),
                             ("nom_tuteur", "nom du tuteur"), ("tel_tuteur", "tuteur"), ("adresse_tuteur", "adresse du tuteur"),
                             ("pourcent_origine", "pourcentage"), ("date_naissance", "naissance"), ("n_recu", "reçu"),
                             ("sexe", "sexe"), ("doublant", "doublant"), ("n_classe", "classe")):
            with self.subTest(cle):
                with self.assertRaises(ErreurInscription) as e:
                    inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire(**{cle: ""}))
                self.assertIn(message, str(e.exception))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CANDIDATURE").fetchone()[0], 0)

    def test_valeurs_invalides(self):
        for plus, message in (({"pourcent_origine": "120"}, "entre 0 et 100"), ({"pourcent_origine": "abc"}, "invalide"),
                              ({"pourcent_origine": "-3"}, "entre 0 et 100"),
                              ({"date_naissance": "31/02/2012"}, "invalide"),
                              ({"date_naissance": date(date.today().year + 1, 1, 1).strftime("%d/%m/%Y")}, "futur"),
                              ({"date_naissance": "01/01/1950"}, "vérifiez"),
                              ({"tel_tuteur": "abc"}, "invalide"), ({"n_classe": 999}, "n'existe pas")):
            with self.subTest(plus):
                with self.assertRaises(ErreurInscription) as e:
                    inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire(**plus))
                self.assertIn(message, str(e.exception))

    def test_classe_desactivee_refusee(self):
        with self.conn:
            self.conn.execute("UPDATE CLASSE SET ACTIF = 0 WHERE N_CLASSE = 1")
        with self.assertRaises(ErreurInscription) as e:
            inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire())
        self.assertIn("désactivée", str(e.exception))
        self.assertNotIn(1, [n for n, _ in inscription.classes_proposees(self.conn)])


class TestPaiementObligatoire(Base):
    def test_sans_recu_pas_de_candidature(self):
        with self.assertRaises(ErreurInscription) as e:
            inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire(n_recu="9999"))
        self.assertIn("n'existe pas", str(e.exception))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CANDIDATURE").fetchone()[0], 0)

    def test_recu_annule_refuse(self):
        ref.annuler_paiement(self.conn, self.admin, self.recu, "Erreur de saisie du percepteur")
        with self.assertRaises(ErreurInscription) as e:
            inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire())
        self.assertIn("annulé", str(e.exception))

    def test_un_recu_ne_sert_qu_une_fois(self):
        inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire())
        with self.assertRaises(ErreurInscription) as e:
            inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire(nom="autre"))
        self.assertIn("déjà servi", str(e.exception))
        self.assertIn("C0001/26", str(e.exception))

    def test_verification_du_recu_a_l_ecran(self):
        info = inscription.verifier_recu_pour_ecran(self.conn, self.sec, self.recu)
        self.assertEqual((info["type_frais"], info["montant_txt"], info["devise"], info["annee"]),
                         ("Frais d'inscription", "30,00", "USD", AN))

    def test_la_base_refuse_aussi_sans_passer_par_l_application(self):
        """Même un enregistrement direct dans la base est refusé s'il n'y a pas de paiement valide."""
        sql = ("INSERT INTO CANDIDATURE (ANNEESCO, ORDRE, NUM_CAND, N_RECU, NOM, SEXE, DATE_NAISSANCE, ADRESSE, ECOLE_ORIGINE, "
               "POURCENT_ORIGINE, DOUBLANT, N_CLASSE, NOM_TUTEUR, TEL_TUTEUR, ADRESSE_TUTEUR, DATE_ENREG, ENREGISTRE_PAR) "
               "VALUES (?, 1, 'C0001/26', ?, 'X', 'M', '2012-01-01', 'a', 'e', 50, 0, 1, 't', '123456', 'a', '2026-10-01', 'x')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(sql, (AN, "9999"))                                   # reçu inexistant
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(sql, (AN, self.payer("CSF-0004", "EXAM", 1500)))      # reçu d'un autre frais
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(sql, ("2025-2026", self.recu))                       # reçu d'une autre année
        self.conn.execute(sql, (AN, self.recu))                                    # reçu valide : accepté
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE CANDIDATURE SET N_RECU = '0001' WHERE ORDRE = 1")   # le reçu ne change plus


class TestListeAttente(Base):
    def test_ordre_d_arrivee_et_rang_par_classe(self):
        # 0005 et 0010 = reçus d'inscription déjà présents dans les données de démonstration (année en cours, valides)
        recus = [self.recu, "0005", "0010"]
        a = inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire(n_recu=recus[0], nom="Alpha", n_classe=1))
        b = inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire(n_recu=recus[1], nom="Bravo", n_classe=2))
        c = inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire(n_recu=recus[2], nom="Charlie", n_classe=1))
        self.assertEqual([(a["ordre"], a["rang"]), (b["ordre"], b["rang"]), (c["ordre"], c["rang"])], [(1, 1), (2, 1), (3, 2)])
        liste = inscription.liste_attente(self.conn, self.sec)
        self.assertEqual([(l["nom_complet"], l["rang"]) for l in liste], [("ALPHA MWAMBA Joël", 1), ("BRAVO MWAMBA Joël", 1),
                                                                         ("CHARLIE MWAMBA Joël", 2)])
        self.assertEqual([l["nom_complet"][:5] for l in inscription.liste_attente(self.conn, self.sec, n_classe=1)],
                         ["ALPHA", "CHARL"])
        self.assertEqual([l["nom_complet"][:5] for l in inscription.liste_attente(self.conn, self.sec, recherche="charlie")],
                         ["CHARL"])
        self.assertEqual(inscription.liste_attente(self.conn, self.sec, statut="ADMIS"), [])

    def test_le_rang_d_un_candidat_ne_depend_pas_de_la_recherche(self):
        inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire(nom="Alpha"))
        inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire(n_recu="0005", nom="Bravo"))
        self.assertEqual(inscription.liste_attente(self.conn, self.sec, recherche="bravo")[0]["rang"], 2)


class TestDroits(Base):
    def test_sans_droit_ajout_pas_d_enregistrement(self):
        with self.conn:
            droits.remplacer_droits(self.conn, self.sec.id_user, {("inscription", "LECTURE")})
        with self.assertRaises(PermissionError):
            inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire())
        self.assertEqual(inscription.liste_attente(self.conn, self.sec), [])           # la lecture reste permise

    def test_sans_droit_lecture_rien_n_est_visible(self):
        with self.conn:
            droits.remplacer_droits(self.conn, self.sec.id_user, set())
        for appel in (lambda: inscription.liste_attente(self.conn, self.sec),
                      lambda: inscription.verifier_recu_pour_ecran(self.conn, self.sec, self.recu)):
            with self.assertRaises(PermissionError):
                appel()
        self.assertNotIn("inscription", modules.modules_ouverts(self.conn, self.sec))

    def test_le_module_est_ouvert_au_secretaire_autorise_et_a_l_administrateur(self):
        self.assertIn("inscription", modules.modules_ouverts(self.conn, self.sec))           # sans accès au Secrétariat : tuile à part
        self.assertNotIn("inscription", modules.modules_ouverts(self.conn, self.admin))      # avec le Secrétariat : onglet « Inscription »
        self.assertIn("dossier_eleve", [c for c, _t in modules.sous_menus_ouverts(self.conn, self.admin)])
        self.assertNotIn("inscription", modules.modules_ouverts(self.conn, self.perc))

    def test_le_droit_existe_dans_le_gestionnaire_d_acces(self):
        self.assertEqual(config.MODULES_DROITS["inscription"][1], ("LECTURE", "AJOUT", "MODIFICATION"))
        with self.assertRaises(ValueError):
            droits.normaliser({("inscription", "SUPPRESSION")})


class TestFiche(Base):
    def test_fiche_pdf(self):
        r = inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire())
        chemin = inscription.preparer_fiche_pdf(self.conn, self.sec, r["n_cand"])
        with open(chemin, "rb") as f:
            octets = f.read()
        self.assertTrue(octets.startswith(b"%PDF-1.4") and octets.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"FICHE D'INSCRIPTION", octets)
        self.assertIn(b"C0001/26", octets)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE ACTION = 'FICHE_INSCRIPTION_IMPRIMEE'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()

"""Tests de la 2ème fonctionnalité du module Inscription : test d'admission, validation du dossier, affectation à une
classe, passage au statut d'élève avec matricule (même modèle 0001/26).
Lancer :  python test_admission.py"""
import os
import re
import sqlite3
import tempfile
import unittest
from datetime import date

import test_inscription as base            # prépare l'environnement de test et la base (CSF_DATA_DIR)
from test_inscription import AN, MDP, Base, config, database, droits, inscription, migrations, paiements, ref, security
from inscription import ErreurInscription

AA = f"{date.today().year % 100:02d}"      # année d'inscription sur 2 chiffres (fin du matricule)


class Admission(Base):
    def setUp(self):
        super().setUp()
        # le directeur des études : Lecture + Modification (valide et affecte) ; le secrétaire garde Lecture + Ajout
        id_dir = security.creer_utilisateur(self.conn, "dir1", "Diane Directrice", "DIRECTRICE_ETUDES", MDP)
        with self.conn:
            droits.remplacer_droits(self.conn, id_dir, {("inscription", "LECTURE"), ("inscription", "MODIFICATION")})
        self.dir = security.authentifier(self.conn, "dir1", MDP).session

    def candidat(self, **plus):
        """Nouveau candidat sur la liste d'attente (un reçu d'inscription neuf à chaque fois)."""
        deja = self.conn.execute("SELECT COUNT(*) FROM CANDIDATURE").fetchone()[0]
        # le 1er candidat utilise le reçu préparé par Base ; les suivants paient avec un élève payeur créé pour l'occasion
        if deja == 0:
            recu = self.recu
        else:
            recu = self.recu_candidat()
        return inscription.enregistrer_candidature(self.conn, self.sec, self.formulaire(n_recu=recu, **plus))["n_cand"]

    def ligne(self, n_cand):
        return self.conn.execute("SELECT * FROM CANDIDATURE WHERE N_CAND = ?", (n_cand,)).fetchone()


class TestTest(Admission):
    def test_reussite_valide_le_dossier(self):
        n = self.candidat()
        r = inscription.enregistrer_resultat_test(self.conn, self.dir, n, "62,5")
        self.assertEqual((r["resultat"], r["valide"], r["note"]), ("REUSSI", True, 62.5))
        l = self.ligne(n)
        self.assertEqual((l["STATUT"], l["RESULTAT_TEST"], l["NOTE_TEST"], l["TEST_PAR"]), ("EN_ATTENTE", "REUSSI", 62.5, "dir1"))
        self.assertEqual(inscription.liste_validation(self.conn, self.dir)[0]["etape"], "A_AFFECTER")

    def test_le_seuil_exact_reussit(self):
        n = self.candidat()
        self.assertTrue(inscription.enregistrer_resultat_test(self.conn, self.dir, n, str(config.SEUIL_REUSSITE_TEST))["valide"])

    def test_echec_refuse_la_candidature(self):
        n = self.candidat()
        r = inscription.enregistrer_resultat_test(self.conn, self.dir, n, "49,9")
        self.assertEqual((r["resultat"], r["valide"]), ("ECHOUE", False))
        self.assertEqual(self.ligne(n)["STATUT"], "REFUSE")
        with self.assertRaises(ErreurInscription):                    # un refusé ne s'affecte pas
            inscription.affecter_candidat(self.conn, self.dir, n)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ELEVE WHERE MATRICULE LIKE '%/%'").fetchone()[0], 0)

    def test_le_resultat_ne_s_enregistre_qu_une_fois(self):
        n = self.candidat()
        inscription.enregistrer_resultat_test(self.conn, self.dir, n, "70")
        with self.assertRaises(ErreurInscription) as e:
            inscription.enregistrer_resultat_test(self.conn, self.dir, n, "20")
        self.assertIn("déjà enregistré", str(e.exception))
        self.assertEqual(self.ligne(n)["NOTE_TEST"], 70)

    def test_notes_invalides(self):
        n = self.candidat()
        for mauvaise in ("", "abc", "-1", "101", "nan"):
            with self.assertRaises(ErreurInscription, msg=mauvaise):
                inscription.enregistrer_resultat_test(self.conn, self.dir, n, mauvaise)
        self.assertIsNone(self.ligne(n)["RESULTAT_TEST"])

    def test_droit_modification_exige(self):
        n = self.candidat()
        with self.assertRaises(PermissionError):
            inscription.enregistrer_resultat_test(self.conn, self.sec, n, "80")      # le secrétaire n'a que Lecture + Ajout
        with self.assertRaises(PermissionError):
            inscription.affecter_candidat(self.conn, self.sec, n)
        self.assertTrue(inscription.enregistrer_resultat_test(self.conn, self.admin, n, "80")["valide"])   # l'Administrateur a tout


class TestAffectation(Admission):
    def valide(self, **plus):
        n = self.candidat(**plus)
        inscription.enregistrer_resultat_test(self.conn, self.dir, n, "75")
        return n

    def test_le_candidat_devient_eleve_avec_matricule(self):
        n = self.valide()
        r = inscription.affecter_candidat(self.conn, self.dir, n)
        self.assertEqual(r["matricule"], f"0001/{AA}")
        self.assertRegex(r["matricule"], r"^\d{4}/\d{2}$")
        e = self.conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = ?", (r["matricule"],)).fetchone()
        self.assertEqual((e["NOM"], e["POSTNOM"], e["PRENOM"], e["SEXE"], e["DATE_NAISSANCE"], e["NATIONALITE"], e["ACTIF"]),
                         ("KALALA", "MWAMBA", "Joël", "M", "2012-03-15", "Congolaise", 1))
        self.assertEqual((e["NOM_TUTEUR"], e["TEL_TUTEUR"]), ("Mme Kalala Rose", "+243 82 000 00 01"))
        self.assertTrue(e["CODE_QR"].startswith(f"CSF|{r['matricule']}|"))
        i = self.conn.execute("SELECT * FROM INSCRIRE WHERE MATRICULE = ?", (r["matricule"],)).fetchone()
        self.assertEqual((i["ANNEESCO"], i["N_CLASSE"], i["STATUT"]), (AN, 1, "NOUVEAU"))
        l = self.ligne(n)
        self.assertEqual((l["STATUT"], l["MATRICULE"], l["N_CLASSE_AFFECTEE"], l["DECISION_PAR"]), ("ADMIS", r["matricule"], 1, "dir1"))

    def test_numerotation_suit_le_meme_modele(self):
        a = inscription.affecter_candidat(self.conn, self.dir, self.valide())["matricule"]
        b = inscription.affecter_candidat(self.conn, self.dir, self.valide(nom="mukendi"))["matricule"]
        c = inscription.affecter_candidat(self.conn, self.dir, self.valide(nom="ilunga"))["matricule"]
        self.assertEqual([a, b, c], [f"0001/{AA}", f"0002/{AA}", f"0003/{AA}"])
        # le même compteur que l'ajout d'un élève à la main : pas de doublon, pas de trou
        ref.enregistrer(self.conn, self.admin, "eleves", {"NOM": "TEST", "SEXE": "M"})
        self.assertIn(f"0004/{AA}", {l[0] for l in self.conn.execute("SELECT MATRICULE FROM ELEVE")})

    def test_classe_differente_de_celle_souhaitee(self):
        n = self.valide()                                              # souhaitée : classe 1
        r = inscription.affecter_candidat(self.conn, self.dir, n, n_classe=2)
        self.assertEqual(self.ligne(n)["N_CLASSE_AFFECTEE"], 2)
        self.assertEqual(self.conn.execute("SELECT N_CLASSE FROM INSCRIRE WHERE MATRICULE = ?", (r["matricule"],)).fetchone()[0], 2)
        self.assertEqual(self.ligne(n)["N_CLASSE"], 1)                 # le vœu d'origine est conservé

    def test_doublant_inscrit_comme_redoublant(self):
        r = inscription.affecter_candidat(self.conn, self.dir, self.valide(doublant=True))
        self.assertEqual(self.conn.execute("SELECT STATUT FROM INSCRIRE WHERE MATRICULE = ?", (r["matricule"],)).fetchone()[0],
                         "REDOUBLANT")

    def test_sans_test_reussi_pas_d_affectation(self):
        n = self.candidat()
        with self.assertRaises(ErreurInscription) as e:
            inscription.affecter_candidat(self.conn, self.dir, n)
        self.assertIn("réussir le test", str(e.exception))
        self.assertEqual(self.ligne(n)["STATUT"], "EN_ATTENTE")

    def test_pas_deux_affectations(self):
        n = self.valide()
        r = inscription.affecter_candidat(self.conn, self.dir, n)
        with self.assertRaises(ErreurInscription) as e:
            inscription.affecter_candidat(self.conn, self.dir, n)
        self.assertIn(r["matricule"], str(e.exception))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ELEVE WHERE MATRICULE LIKE '%/%'").fetchone()[0], 1)

    def test_classe_desactivee_ou_inconnue(self):
        n = self.valide()
        with self.assertRaises(ErreurInscription):
            inscription.affecter_candidat(self.conn, self.dir, n, n_classe=9999)
        ref.changer_etat(self.conn, self.admin, "classes", (2,), False) if hasattr(ref, "changer_etat") else \
            self.conn.execute("UPDATE CLASSE SET ACTIF = 0 WHERE N_CLASSE = 2")
        with self.assertRaises(ErreurInscription):
            inscription.affecter_candidat(self.conn, self.dir, n, n_classe=2)
        self.assertEqual(self.ligne(n)["STATUT"], "EN_ATTENTE")        # rien n'a été créé

    def test_recu_annule_apres_candidature_bloque_l_affectation(self):
        n = self.valide()
        ref.annuler_paiement(self.conn, self.admin, self.recu, "Chèque sans provision")
        with self.assertRaises(ErreurInscription) as e:
            inscription.affecter_candidat(self.conn, self.dir, n)
        self.assertIn("annulé", str(e.exception))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ELEVE WHERE MATRICULE LIKE '%/%'").fetchone()[0], 0)

    def test_doublon_d_identite_refuse(self):
        a = self.valide()
        inscription.affecter_candidat(self.conn, self.dir, a)
        b = self.valide()                                              # même nom, même naissance : probablement le même enfant
        with self.assertRaises(ErreurInscription) as e:
            inscription.affecter_candidat(self.conn, self.dir, b)
        self.assertIn(f"0001/{AA}", str(e.exception))
        self.assertEqual(self.ligne(b)["STATUT"], "EN_ATTENTE")

    def test_tout_ou_rien(self):
        """Une erreur en cours d'affectation ne laisse ni élève, ni inscription, ni matricule consommé."""
        n = self.valide()
        self.conn.execute("CREATE TRIGGER CASSE BEFORE INSERT ON INSCRIRE BEGIN SELECT RAISE(ABORT, 'panne simulée'); END")
        with self.assertRaises(ErreurInscription):
            inscription.affecter_candidat(self.conn, self.dir, n)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ELEVE WHERE MATRICULE LIKE '%/%'").fetchone()[0], 0)
        self.assertEqual(self.ligne(n)["STATUT"], "EN_ATTENTE")
        self.assertIsNone(self.conn.execute("SELECT DERNIER FROM MATRICULE_SEQ WHERE ANNEE = ?", (AA,)).fetchone())
        self.conn.execute("DROP TRIGGER CASSE")
        self.assertEqual(inscription.affecter_candidat(self.conn, self.dir, n)["matricule"], f"0001/{AA}")

    def test_l_eleve_peut_maintenant_payer(self):
        """Inscrit pour l'année, le nouvel élève est reconnu par le module Paiement (matricule, classe)."""
        import donnees
        r = inscription.affecter_candidat(self.conn, self.dir, self.valide())
        trouves = donnees.rechercher_eleves(self.conn, r["matricule"])
        self.assertEqual([t["matricule"] for t in trouves], [r["matricule"]])
        self.assertNotEqual(trouves[0]["classe"], "—")

    def test_la_base_refuse_un_admis_sans_test(self):
        n = self.candidat()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE CANDIDATURE SET STATUT = 'ADMIS' WHERE N_CAND = ?", (n,))
        self.conn.rollback()

    def test_journal(self):
        n = self.valide()
        r = inscription.affecter_candidat(self.conn, self.dir, n)
        actions = {l["ACTION"]: l["DETAIL"] for l in self.conn.execute("SELECT ACTION, DETAIL FROM JOURNAL")}
        self.assertIn("note 75/100", actions["CANDIDATURE_TEST_ENREGISTRE"])
        self.assertIn(r["matricule"], actions["CANDIDAT_ADMIS_AFFECTE"])
        self.assertNotIn("KALALA", actions["CANDIDAT_ADMIS_AFFECTE"])     # pas de nom d'élève dans le journal


class TestListeEtAvis(Admission):
    def test_etapes_et_filtres(self):
        a, b, c, d = self.candidat(), self.candidat(nom="mukendi"), self.candidat(nom="ilunga"), self.candidat(nom="banza")
        inscription.enregistrer_resultat_test(self.conn, self.dir, b, "80")
        inscription.enregistrer_resultat_test(self.conn, self.dir, c, "80")
        inscription.affecter_candidat(self.conn, self.dir, c)
        inscription.enregistrer_resultat_test(self.conn, self.dir, d, "10")
        etapes = {l["n_cand"]: l["etape"] for l in inscription.liste_validation(self.conn, self.dir)}
        self.assertEqual(etapes, {a: "A_TESTER", b: "A_AFFECTER", c: "ADMIS", d: "REFUSE"})
        self.assertEqual([l["n_cand"] for l in inscription.liste_validation(self.conn, self.dir, etape="A_AFFECTER")], [b])
        admis = inscription.liste_validation(self.conn, self.dir, recherche="ilunga")[0]
        self.assertEqual((admis["matricule"], admis["classe_affectee"], admis["note_test"]), (f"0001/{AA}", admis["classe"], "80"))
        # un admis quitte la liste d'attente
        self.assertNotIn(c, [l["n_cand"] for l in inscription.liste_attente(self.conn, self.sec)])
        self.assertEqual({l["n_cand"] for l in inscription.liste_attente(self.conn, self.sec)}, {a, b})

    def test_avis_d_admission_pdf(self):
        n = self.candidat()
        with self.assertRaises(ErreurInscription):                      # pas admis : pas d'avis
            inscription.preparer_avis_admission_pdf(self.conn, self.dir, n)
        inscription.enregistrer_resultat_test(self.conn, self.dir, n, "88")
        r = inscription.affecter_candidat(self.conn, self.dir, n)
        chemin = inscription.preparer_avis_admission_pdf(self.conn, self.dir, n)
        self.assertTrue(os.path.basename(chemin).startswith("Avis_admission_"))
        self.assertNotIn("/", os.path.basename(chemin))
        with open(chemin, "rb") as f:
            self.assertTrue(f.read(5).startswith(b"%PDF"))
        self.assertTrue(self.conn.execute("SELECT 1 FROM JOURNAL WHERE ACTION = 'AVIS_ADMISSION_IMPRIME'").fetchone())

    def test_ecran_onglets_selon_les_droits(self):
        try:
            import ecrans_inscription as ecr
        except ImportError:
            self.skipTest("tkinter indisponible")
        self.assertEqual(ecr.onglets_autorises(self.conn, self.sec), {"liste", "formulaire"})
        self.assertEqual(ecr.onglets_autorises(self.conn, self.dir), {"liste", "validation"})
        self.assertEqual(ecr.onglets_autorises(self.conn, self.admin), {"liste", "formulaire", "validation"})


class TestAncienneBase(unittest.TestCase):
    def test_base_0_22_recoit_les_nouvelles_colonnes(self):
        """Une base de la version 0.22 (CANDIDATURE sans les colonnes du test) est mise à jour sans perdre de candidature."""
        schema = database.SCHEMA
        debut = schema.index("    -- test d'admission, validation et affectation")
        fin = schema.index("    DATE_ENREG      TEXT    NOT NULL")
        ancien = schema[:debut] + schema[fin:]
        d1 = ancien.index("-- Un candidat ne devient ADMIS")
        d2 = ancien.index("-- Données d'ESSAI")
        ancien = ancien[:d1] + ancien[d2:]
        self.assertNotIn("NOTE_TEST", ancien)
        ancien = re.sub(r",\n    SECTION     TEXT NOT NULL DEFAULT 'SECONDAIRE' CHECK[^\n]*", "", ancien)     # NIVEAU de la 0.22 : sans section
        self.assertNotIn("SECTION     TEXT", ancien)
        conn = sqlite3.connect(os.path.join(tempfile.mkdtemp(), "v022.db"))
        conn.row_factory = sqlite3.Row
        conn.executescript(ancien)
        conn.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU, ACTIF) VALUES ('PRI','Primaire',1)")
        conn.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU) VALUES ('1ère A','PRI')")
        conn.execute("INSERT INTO ANNEE_SCO VALUES ('2026-2027',1,1)")
        conn.execute("INSERT INTO TYPE_FRAIS (CODTF, DESITF, POUR_INSCRIPTION) VALUES ('INSC','Inscription',1)")
        conn.execute("INSERT INTO DEVISE VALUES ('USD','Dollar',1)")
        conn.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('CSF-1','X')")
        conn.execute("INSERT INTO INSCRIRE VALUES ('2026-2027','CSF-1',1,'2026-09-01','NOUVEAU')")
        conn.execute(f"PRAGMA user_version = 10")      # base d'avant les sections (migration 11)
        conn.commit()
        self.assertTrue(migrations.analyser(conn).a_faire)
        migrations.mettre_a_jour(conn, sauvegarder=False)
        self.assertFalse(migrations.analyser(conn).a_faire)
        self.assertEqual(conn.execute("SELECT SECTION FROM NIVEAU WHERE CODE_NIVEAU = 'PRI'").fetchone()[0], "PRIMAIRE")   # migration 11
        colonnes = {l[1] for l in conn.execute("PRAGMA table_info(CANDIDATURE)")}
        self.assertTrue({"NOTE_TEST", "RESULTAT_TEST", "N_CLASSE_AFFECTEE", "DECISION_PAR"} <= colonnes)
        self.assertIn("CANDIDATURE_ADMIS_EXIGE_TEST", {l[0] for l in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")})
        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Tests de la saisie des points par les professeurs (notes.py) : identité, cloisonnement, évaluations, points, conduite, journal.
Lancer :  python test_notes.py"""
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import config         # noqa: E402
import cours          # noqa: E402
import database       # noqa: E402
import notes          # noqa: E402
import personnel      # noqa: E402
import security       # noqa: E402
from notes import ErreurNotes  # noqa: E402

MDP = "Tr@vail-Amour-2026"


def agent(**a):
    base = {"nom": "mukendi", "postnom": "kabeya", "prenom": "jean", "sexe": "M", "date_naissance": "15/03/1985", "adresse": "Kinshasa",
            "telephone": "0812345678", "email": "", "date_engagement": "01/09/2015", "fonction": "Enseignant",
            "statut_pro": "PERMANENT", "matricule": ""}
    base.update(a)
    return base


class Base(unittest.TestCase):
    def setUp(self):
        c = self.conn = database.connecter(os.path.join(tempfile.mkdtemp(), "n.db"))
        security.creer_utilisateur(c, "admin1", "Alice", "ADMINISTRATEUR", MDP)
        self.admin = security.authentifier(c, "admin1", MDP).session
        with c:
            c.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU) VALUES ('SEC', 'Secondaire')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('7ème A', 'SEC', '7ème', 'A')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('8ème A', 'SEC', '8ème', 'A')")
        self.c7, self.c8 = (r[0] for r in c.execute("SELECT N_CLASSE FROM CLASSE ORDER BY N_CLASSE"))
        self.annee = cours.creer_annee(c, self.admin, "2026-2027", "07/09/2026", "10/07/2027", en_cours=True)
        cours.generer_structure_standard(c, self.admin, self.annee)
        self.per1, self.per2, self.per3, self.per4 = (r[0] for r in c.execute("SELECT ID_PER FROM PERIODE_SCO ORDER BY DATE_DEBUT"))
        self.sem1, self.sem2 = (r[0] for r in c.execute("SELECT ID_SEM FROM SEMESTRE_SCO ORDER BY DATE_DEBUT"))
        self.m1 = personnel.enregistrer_agent(c, self.admin, agent())["matricule"]
        self.m2 = personnel.enregistrer_agent(c, self.admin, agent(nom="banza", prenom="paul"))["matricule"]
        ids = {}
        for nom in ("Mathématiques", "Français"):
            ids[nom] = cours.ajouter_cours(c, self.admin, {"libelle": nom, "code_niveau": "SEC", "heures_semaine": "4"})
        cours.ouvrir_cours(c, self.admin, self.annee, self.c7)
        cours.ouvrir_cours(c, self.admin, self.annee, self.c8)
        cc = lambda classe, cr: c.execute("SELECT ID_CC FROM COURS_CLASSE WHERE N_CLASSE = ? AND ID_COURS = ?", (classe, ids[cr])).fetchone()[0]
        self.maths7, self.fr7, self.maths8 = cc(self.c7, "Mathématiques"), cc(self.c7, "Français"), cc(self.c8, "Mathématiques")
        cours.attribuer_professeur(c, self.admin, [self.maths7, self.maths8], self.m1)
        cours.attribuer_professeur(c, self.admin, [self.fr7], self.m2)
        with c:
            for i, nom in enumerate(("Kasongo", "Amisi", "Zola")):
                c.execute("INSERT INTO ELEVE (MATRICULE, NOM, POSTNOM, PRENOM, SEXE) VALUES (?,?,?,?,?)", (f"000{i}/26", nom, "X", "Y", "M"))
                c.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?,?,?)", (self.annee, f"000{i}/26", self.c7))
            c.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('0009/26', 'Autre')")
            c.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?,?,?)", (self.annee, "0009/26", self.c8))
        self.p1 = notes.creer_compte_professeur(c, self.admin, self.m1)
        self.p2 = notes.creer_compte_professeur(c, self.admin, self.m2)
        self.s1 = security.authentifier(c, self.p1["login"], self.p1["mdp_temporaire"]).session
        self.s2 = security.authentifier(c, self.p2["login"], self.p2["mdp_temporaire"]).session
        self.cles = [f"P{p}" for p in (self.per1, self.per2, self.per3, self.per4)] + [f"X{self.sem1}", f"X{self.sem2}"]
        self.ouvrir(self.cles)                                                       # par défaut, le titulaire a ouvert toutes les saisies

    def ouvrir(self, cles, classes=None):
        """Ouvre à la saisie ces périodes / examens (clés « P<id> » / « X<id> ») dans les classes (7ème et 8ème par défaut), sans passer
        par le titulaire : sert à préparer un essai."""
        with self.conn:
            for classe in (classes or (self.c7, self.c8)):
                for cle in cles:
                    self.conn.execute("INSERT OR IGNORE INTO AUTORISATION_SAISIE (ANNEESCO, N_CLASSE, CLE, DATE_ENREG, ENREGISTRE_PAR) "
                                      "VALUES (?,?,?,?,?)", (self.annee, classe, cle, "2026-09-01T00:00:00", "essai"))

    def fermer_tout(self):
        with self.conn:
            self.conn.execute("DELETE FROM AUTORISATION_SAISIE")

    def actions(self):
        return [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL ORDER BY ID_LOG")]


class TestComptes(Base):
    def test_compte_cree_avec_poste_professeur_et_mdp_a_changer(self):
        self.assertEqual(self.s1.role, "PROFESSEUR")
        self.assertTrue(self.s1.doit_changer_mdp)
        self.assertEqual(notes.compte_du_professeur(self.conn, self.admin, self.m1)["login"], self.p1["login"])
        with self.assertRaises(ErreurNotes):
            notes.creer_compte_professeur(self.conn, self.admin, self.m1)             # déjà un compte

    def test_creer_un_compte_est_reserve_a_l_administrateur(self):
        with self.assertRaises(PermissionError):
            notes.creer_compte_professeur(self.conn, self.s1, self.m2)

    def test_un_compte_non_relie_n_a_pas_acces(self):
        security.creer_utilisateur(self.conn, "sec1", "Sophie", "SECRETAIRE", MDP)
        sec = security.authentifier(self.conn, "sec1", MDP).session
        for s in (sec, self.admin):
            with self.assertRaises(PermissionError):
                notes.mes_classes(self.conn, s)

    def test_compte_desactive_perd_l_acces_tout_de_suite(self):
        with self.conn:
            self.conn.execute("UPDATE UTILISATEUR SET ACTIF = 0 WHERE ID_USER = ?", (self.s1.id_user,))
        with self.assertRaises(PermissionError):
            notes.mes_classes(self.conn, self.s1)


class TestCloisonnement(Base):
    def test_le_professeur_ne_voit_que_ses_cours(self):
        r = notes.mes_classes(self.conn, self.s1)
        self.assertEqual({k["designation"] for k in r["classes"]}, {"7ème A", "8ème A"})
        self.assertEqual([c["cours"] for k in r["classes"] for c in k["cours"]], ["Mathématiques", "Mathématiques"])
        r2 = notes.mes_classes(self.conn, self.s2)
        self.assertEqual([c["cours"] for k in r2["classes"] for c in k["cours"]], ["Français"])
        self.assertEqual(len(r["semestres"]), 2)
        self.assertEqual(len(r["semestres"][0]["periodes"]), 2)
        self.assertEqual(r["semestres"][0]["examen"]["id"], f"X{r['semestres'][0]['id']}")

    def test_cours_d_un_collegue_refuse_partout(self):
        with self.assertRaises(PermissionError):
            notes.fiche(self.conn, self.s1, self.fr7, self.per1)
        with self.assertRaises(PermissionError):
            notes.enregistrer_points(self.conn, self.s1, self.fr7, self.per1, {"0000/26": "5"})
        with self.assertRaises(PermissionError):
            notes.definir_maximum(self.conn, self.s1, self.fr7, self.per1, "10")
        notes.enregistrer_points(self.conn, self.s2, self.fr7, self.per1, {"0000/26": "5"})
        e = self.conn.execute("SELECT ID_EVAL FROM EVALUATION").fetchone()[0]
        with self.assertRaises(PermissionError):
            notes.supprimer_evaluation(self.conn, self.s1, e)
        self.assertFalse(hasattr(notes, "releve"))                                       # plus de relevé de l'année pour le professeur

    def test_eleve_d_une_autre_classe_refuse(self):
        with self.assertRaises(PermissionError):
            notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0009/26": "5"})
        with self.assertRaises(PermissionError):
            notes.enregistrer_conduite(self.conn, self.s1, self.maths7, self.per1, "0009/26", "B")

    def test_les_eleves_de_la_fiche_sont_ceux_de_la_classe_par_ordre_alphabetique(self):
        f = notes.fiche(self.conn, self.s1, self.maths7, self.per1)
        self.assertEqual([e["nom_complet"].split()[0] for e in f["eleves"]], ["Amisi", "Kasongo", "Zola"])


class TestPointsDePeriodeEtExamen(Base):
    def test_le_professeur_ne_peut_plus_creer_d_interrogation_devoir_ou_examen_libre(self):
        for ancien in ("ajouter_evaluation", "modifier_evaluation"):
            self.assertFalse(hasattr(notes, ancien))
        self.assertEqual([t["sigle"] for t in notes.legende()["types"]], ["P", "EX"])

    def test_la_fiche_ne_montre_que_la_periode_choisie(self):
        f = notes.fiche(self.conn, self.s1, self.maths7, self.per1)
        self.assertEqual([c["code"] for c in f["evaluations"]], ["P"])
        self.assertEqual([c["maximum"] for c in f["evaluations"]], [20])
        self.assertTrue(f["evaluations"][0]["editable"])
        f2 = notes.fiche(self.conn, self.s1, self.maths7, self.per3)
        self.assertEqual(f2["periode"]["cle"], f"P{self.per3}")
        fx = notes.fiche(self.conn, self.s1, self.maths7, f"X{self.sem1}")
        self.assertEqual([(c["code"], c["maximum"]) for c in fx["evaluations"]], [("EX", 40)])
        self.assertEqual(fx["periode"]["genre"], "X")

    def test_points_de_la_periode_sans_total_ni_pourcentage_pour_le_professeur(self):
        r = notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": "15,5", "0001/26": "20", "0002/26": ""})
        self.assertEqual(r, {"enregistres": 2, "effaces": 0})
        notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per2, {"0000/26": "12"})
        notes.enregistrer_points(self.conn, self.s1, self.maths7, f"X{self.sem1}", {"0000/26": "30"})
        f = notes.fiche(self.conn, self.s1, self.maths7, self.per1)
        kas = next(e for e in f["eleves"] if e["matricule"] == "0000/26")
        self.assertEqual(kas["points"], {f"P{self.per1}": 15.5})                       # rien des autres périodes ni de l'examen
        for interdit in ("total", "sur", "pourcentage"):
            self.assertNotIn(interdit, kas)
        self.assertEqual(set(kas), {"matricule", "nom_complet", "sexe", "points", "conduite"})
        fx = notes.fiche(self.conn, self.s1, self.maths7, f"X{self.sem1}")
        self.assertEqual(next(e for e in fx["eleves"] if e["matricule"] == "0000/26")["points"], {f"X{self.sem1}": 30})
        self.assertEqual(next(e for e in f["eleves"] if e["matricule"] == "0002/26")["points"], {f"P{self.per1}": None})
        self.assertNotIn("TOT", [a["sigle"] for a in notes.legende()["autres"]])
        self.assertNotIn("%", [a["sigle"] for a in notes.legende()["autres"]])

    def test_un_seul_enregistrement_par_periode_et_par_examen(self):
        notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": "10"})
        notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": "11", "0001/26": "9"})
        notes.enregistrer_points(self.conn, self.s1, self.maths7, f"X{self.sem1}", {"0000/26": "30"})
        self.assertEqual(self.conn.execute("SELECT TYPE, COUNT(*) FROM EVALUATION GROUP BY TYPE ORDER BY TYPE").fetchall()[0][0], "EXA")
        self.assertEqual([tuple(r) for r in self.conn.execute("SELECT TYPE, ID_PER, NUMERO FROM EVALUATION ORDER BY TYPE")],
                         [("EXA", self.per2, 1), ("PER", self.per1, 1)])       # l'examen est rangé dans la dernière période du semestre
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM NOTE").fetchone()[0], 3)

    def test_une_periode_ou_un_semestre_d_une_autre_annee_est_refuse(self):
        with self.assertRaises(ErreurNotes):
            notes.enregistrer_points(self.conn, self.s1, self.maths7, 9999, {"0000/26": "5"})
        with self.assertRaises(ErreurNotes):
            notes.enregistrer_points(self.conn, self.s1, self.maths7, "X9999", {"0000/26": "5"})
        with self.assertRaises(ErreurNotes):
            notes.fiche(self.conn, self.s1, self.maths7, "Xabc")

    def test_tout_ou_rien_si_un_point_est_invalide(self):
        for mauvais in ("21", "-1", "abc", "5,555"):
            with self.assertRaises(ErreurNotes, msg=mauvais):
                notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": "5", "0001/26": mauvais})
        with self.assertRaises(ErreurNotes):
            notes.enregistrer_points(self.conn, self.s1, self.maths7, f"X{self.sem1}", {"0000/26": "41"})      # l'examen est sur 40
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM NOTE").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM EVALUATION").fetchone()[0], 0)

    def test_effacer_un_point_et_aucun_changement_sans_journal(self):
        notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": "7"})
        avant = self.actions().count("NOTES_ENREGISTREES")
        self.assertEqual(notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": "7"}), {"enregistres": 0, "effaces": 0})
        self.assertEqual(self.actions().count("NOTES_ENREGISTREES"), avant)
        self.assertEqual(notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": ""}), {"enregistres": 0, "effaces": 1})

    def test_maximum_propre_au_cours_et_pas_sous_un_point_deja_saisi(self):
        notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": "9"})
        with self.assertRaises(ErreurNotes):
            notes.definir_maximum(self.conn, self.s1, self.maths7, self.per1, "5")                  # un élève a déjà 9
        notes.definir_maximum(self.conn, self.s1, self.maths7, self.per1, "30")
        self.assertEqual(notes.fiche(self.conn, self.s1, self.maths7, self.per1)["evaluations"][0]["maximum"], 30)
        notes.definir_maximum(self.conn, self.s1, self.maths7, self.per2, "10")                     # avant toute saisie : crée la colonne
        self.assertEqual(notes.fiche(self.conn, self.s1, self.maths7, self.per2)["evaluations"][0]["maximum"], 10)
        with self.assertRaises(ErreurNotes):
            notes.definir_maximum(self.conn, self.s1, self.maths7, self.per1, "0")
        notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0001/26": "25"})     # le nouveau maximum (30) s'applique
        id_eval = self.conn.execute("SELECT ID_EVAL FROM EVALUATION WHERE ID_PER = ? AND TYPE = 'PER'", (self.per1,)).fetchone()[0]
        notes.supprimer_evaluation(self.conn, self.s1, id_eval)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM NOTE").fetchone()[0], 0)

    def test_annee_desactivee_pas_de_saisie(self):
        with self.conn:
            self.conn.execute("UPDATE ANNEE_SCO SET ACTIF = 0 WHERE ANNEESCO = ?", (self.annee,))
        with self.assertRaises(ErreurNotes):
            notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": "5"})
        with self.assertRaises(ErreurNotes):
            notes.definir_maximum(self.conn, self.s1, self.maths7, self.per1, "20")
        self.assertFalse(notes.fiche(self.conn, self.s1, self.maths7, self.per1)["modifiable"])

    def test_les_anciennes_evaluations_ne_sont_plus_montrees_au_professeur(self):
        with self.conn:
            cur = self.conn.execute("INSERT INTO EVALUATION (ID_CC, ID_PER, TYPE, NUMERO, DATE_EVAL, MAXIMUM, DATE_ENREG, ENREGISTRE_PAR) "
                                    "VALUES (?,?,?,?,?,?,?,?)", (self.maths7, self.per1, "INT", 1, "2026-10-01", 10, "2026-10-01", "x"))
            self.conn.execute("INSERT INTO NOTE (ID_EVAL, MATRICULE, POINTS, DATE_MODIF) VALUES (?,?,?,?)", (cur.lastrowid, "0000/26", 8, "x"))
        notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": "15"})
        f = notes.fiche(self.conn, self.s1, self.maths7, self.per1)
        self.assertEqual([c["code"] for c in f["evaluations"]], ["P"])                          # plus d'INT 1, INT 2... dans sa page
        self.assertEqual(next(e for e in f["eleves"] if e["matricule"] == "0000/26")["points"], {f"P{self.per1}": 15})
        self.assertNotIn("INT", str(f))
        self.assertEqual(self.conn.execute("SELECT POINTS FROM NOTE WHERE MATRICULE = '0000/26' AND POINTS = 8").fetchone()[0], 8)  # conservé


class TestAutorisationDuTitulaire(Base):
    """Le professeur ne saisit que la période (ou l'examen) que le titulaire de la classe a autorisée."""

    def test_rien_ne_se_saisit_sans_autorisation_du_titulaire(self):
        self.fermer_tout()
        with self.assertRaises(ErreurNotes) as e:
            notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": "5"})
        self.assertIn("titulaire", str(e.exception))
        with self.assertRaises(ErreurNotes):
            notes.enregistrer_conduite(self.conn, self.s1, self.maths7, self.per1, "0000/26", "B")
        with self.assertRaises(ErreurNotes):
            notes.fiche(self.conn, self.s1, self.maths7, self.per1)                             # il ne voit même pas la fiche
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM NOTE").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CONDUITE").fetchone()[0], 0)

    def test_chaque_periode_et_chaque_examen_s_ouvrent_separement(self):
        import bulletins
        self.fermer_tout()
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c7, self.m2)       # s2 (Français) est titulaire du 7ème A
        t = self.s2
        bulletins.definir_autorisation(self.conn, t, self.annee, self.c7, f"P{self.per1}", True)
        notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": "5"})
        for fermee in (self.per2, f"X{self.sem1}", self.per3):                                   # le reste est fermé
            with self.assertRaises(ErreurNotes):
                notes.enregistrer_points(self.conn, self.s1, self.maths7, fermee, {"0000/26": "5"})
        bulletins.definir_autorisation(self.conn, t, self.annee, self.c7, f"X{self.sem1}", True)
        notes.enregistrer_points(self.conn, self.s1, self.maths7, f"X{self.sem1}", {"0000/26": "30"})
        r = notes.mes_classes(self.conn, self.s1)
        par = {k["designation"]: k for k in r["classes"]}
        self.assertEqual(par["7ème A"]["autorisees"], sorted([f"P{self.per1}", f"X{self.sem1}"]))
        self.assertEqual(par["8ème A"]["autorisees"], [])                                        # une autre classe : fermée
        with self.assertRaises(ErreurNotes):
            notes.enregistrer_points(self.conn, self.s1, self.maths8, self.per1, {"0009/26": "5"})
        # le titulaire ferme : plus de saisie, mais les points déjà saisis restent
        bulletins.definir_autorisation(self.conn, t, self.annee, self.c7, f"P{self.per1}", False)
        with self.assertRaises(ErreurNotes):
            notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": "6"})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM NOTE").fetchone()[0], 2)
        self.assertEqual(self.actions().count("SAISIE_AUTORISEE"), 2)
        self.assertEqual(self.actions().count("SAISIE_FERMEE"), 1)

    def test_calendrier_pour_la_page_sans_date_d_ouverture(self):
        s = notes.mes_classes(self.conn, self.s1)["semestres"][0]
        self.assertEqual([p["cle"] for p in s["periodes"]], [f"P{self.per1}", f"P{self.per2}"])
        self.assertEqual(s["examen"]["cle"], f"X{self.sem1}")
        self.assertNotIn("ouverte", s["periodes"][0])
        self.assertFalse(hasattr(config, "JOURS_SAISIE_AVANT_FIN"))


class TestConduite(Base):
    def test_conduite_donnee_changee_retiree(self):
        notes.enregistrer_conduite(self.conn, self.s1, self.maths7, self.per1, "0000/26", "tb")
        f = notes.fiche(self.conn, self.s1, self.maths7, self.per1)
        self.assertEqual(next(e for e in f["eleves"] if e["matricule"] == "0000/26")["conduite"], "TB")
        notes.enregistrer_conduite(self.conn, self.s1, self.maths7, self.per1, "0000/26", "B")
        notes.enregistrer_conduite(self.conn, self.s1, self.maths7, self.per1, "0001/26", "E")
        notes.enregistrer_conduite(self.conn, self.s1, self.maths7, self.per1, "0001/26", "")
        f = notes.fiche(self.conn, self.s1, self.maths7, self.per1)
        self.assertEqual([e["conduite"] for e in f["eleves"]], ["", "B", ""])
        with self.assertRaises(ErreurNotes):
            notes.enregistrer_conduite(self.conn, self.s1, self.maths7, self.per1, "0000/26", "ZZ")
        with self.assertRaises(ErreurNotes):
            notes.enregistrer_conduite(self.conn, self.s1, self.maths7, f"X{self.sem1}", "0000/26", "B")    # pas de conduite pour l'examen
        for c, _l in notes.COTES_CONDUITE:
            self.assertLessEqual(len(c), 3)

    def test_journal_et_protection_des_suppressions_du_programme(self):
        notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": "6"})
        for a in ("COMPTE_PROFESSEUR_CREE", "EVALUATION_AJOUT", "NOTES_ENREGISTREES"):
            self.assertIn(a, self.actions())
        with self.assertRaises(cours.ErreurCours):
            cours.retirer_cours_de_classe(self.conn, self.admin, self.maths7)
        with self.assertRaises(cours.ErreurCours):
            cours.supprimer_periode(self.conn, self.admin, self.per1)


class TestMigrationAncienneBase(unittest.TestCase):
    def test_une_ancienne_table_evaluation_est_reconstruite_sans_perte(self):
        import sqlite3
        import migrations
        chemin = os.path.join(tempfile.mkdtemp(), "ancienne.db")
        conn = database.connecter(chemin)
        security.creer_utilisateur(conn, "admin1", "Alice", "ADMINISTRATEUR", MDP)
        admin = security.authentifier(conn, "admin1", MDP).session
        annee = cours.creer_annee(conn, admin, "2026-2027", "07/09/2026", "10/07/2027", en_cours=True)
        cours.generer_structure_standard(conn, admin, annee)
        with conn:
            conn.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU) VALUES ('SEC', 'Secondaire')")
            conn.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('7ème A', 'SEC', '7ème', 'A')")
            conn.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('0000/26', 'Kasongo')")
        cours.ajouter_cours(conn, admin, {"libelle": "Maths", "code_niveau": "SEC", "heures_semaine": "4"})
        classe = conn.execute("SELECT N_CLASSE FROM CLASSE").fetchone()[0]
        cours.ouvrir_cours(conn, admin, annee, classe)
        id_cc = conn.execute("SELECT ID_CC FROM COURS_CLASSE").fetchone()[0]
        per = conn.execute("SELECT ID_PER FROM PERIODE_SCO ORDER BY DATE_DEBUT").fetchone()[0]
        # on remet l'ancienne définition (types INT, DEV, IG, EXA seulement) et l'ancien numéro de structure
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA legacy_alter_table = ON")                                              # NOTE garde son lien vers EVALUATION
        conn.executescript("""
            ALTER TABLE EVALUATION RENAME TO EVAL_TMP;
            CREATE TABLE EVALUATION (ID_EVAL INTEGER PRIMARY KEY AUTOINCREMENT, ID_CC INTEGER NOT NULL, ID_PER INTEGER NOT NULL,
              TYPE TEXT NOT NULL CHECK (TYPE IN ('INT','DEV','IG','EXA')), NUMERO INTEGER NOT NULL CHECK (NUMERO >= 1),
              DATE_EVAL TEXT NOT NULL, MAXIMUM REAL NOT NULL CHECK (MAXIMUM > 0 AND MAXIMUM <= 1000), DATE_ENREG TEXT NOT NULL,
              ENREGISTRE_PAR TEXT NOT NULL, UNIQUE (ID_CC, ID_PER, TYPE, NUMERO));
            DROP TABLE EVAL_TMP;""")
        conn.execute("INSERT INTO EVALUATION (ID_CC, ID_PER, TYPE, NUMERO, DATE_EVAL, MAXIMUM, DATE_ENREG, ENREGISTRE_PAR) VALUES (?,?,?,?,?,?,?,?)",
                     (id_cc, per, "INT", 1, "2026-10-01", 10, "2026-10-01", "x"))
        conn.execute("INSERT INTO NOTE (ID_EVAL, MATRICULE, POINTS, DATE_MODIF) VALUES (1, '0000/26', 7, 'x')")
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA user_version = 8")
        conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO EVALUATION (ID_CC, ID_PER, TYPE, NUMERO, DATE_EVAL, MAXIMUM, DATE_ENREG, ENREGISTRE_PAR) "
                         "VALUES (?,?,?,?,?,?,?,?)", (id_cc, per, "PER", 1, "2026-10-01", 20, "x", "x"))
        conn.close()
        conn = database.connecter(chemin)                                                           # l'ouverture met la structure à niveau
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], migrations.VERSION_SCHEMA)
        self.assertEqual(tuple(conn.execute("SELECT TYPE, MAXIMUM FROM EVALUATION").fetchone()), ("INT", 10))     # rien perdu
        self.assertEqual(conn.execute("SELECT POINTS FROM NOTE WHERE MATRICULE = '0000/26'").fetchone()[0], 7)
        with conn:
            conn.execute("INSERT INTO EVALUATION (ID_CC, ID_PER, TYPE, NUMERO, DATE_EVAL, MAXIMUM, DATE_ENREG, ENREGISTRE_PAR) VALUES (?,?,?,?,?,?,?,?)",
                         (id_cc, per, "PER", 1, "2026-10-01", 20, "x", "x"))                          # « PER » est maintenant permis
        self.assertEqual([tuple(r) for r in conn.execute("PRAGMA foreign_key_check").fetchall()], [])
        conn.close()


if __name__ == "__main__":
    unittest.main()

"""Tests du calcul automatique et des bulletins (bulletins.py, bulletins_pdf.py) : calculs, rangs, mentions, résultats,
droits du professeur titulaire, documents PDF, journal.
Lancer :  python test_bulletins.py"""
import http.client
import json
import os
import tempfile
import unittest
from datetime import date
from unittest import mock

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import bulletins          # noqa: E402
from aide_tests_proclamation import ouvrir_impression   # noqa: E402
import config             # noqa: E402
import cours              # noqa: E402
import database           # noqa: E402
import notes              # noqa: E402
import personnel          # noqa: E402
import security           # noqa: E402
import serveur_notes      # noqa: E402
from bulletins import ErreurBulletins  # noqa: E402

MDP = "Tr@vail-Amour-2026"


def agent(**a):
    base = {"nom": "mukendi", "postnom": "kabeya", "prenom": "jean", "sexe": "M", "date_naissance": "15/03/1985", "adresse": "Kinshasa",
            "telephone": "0812345678", "email": "", "date_engagement": "01/09/2015", "fonction": "Enseignant",
            "statut_pro": "PERMANENT", "matricule": ""}
    base.update(a)
    return base


class Base(unittest.TestCase):
    def setUp(self):
        config.NOTE_MANQUANTE = "IGNOREE"
        config.EXAMEN_DANS_SEMESTRE = True
        c = self.conn = database.connecter(os.path.join(tempfile.mkdtemp(), "b.db"))
        security.creer_utilisateur(c, "admin1", "Alice", "ADMINISTRATEUR", MDP)
        self.admin = security.authentifier(c, "admin1", MDP).session
        with c:
            c.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU) VALUES ('SEC', 'Secondaire')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('7ème A', 'SEC', '7ème', 'A')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('8ème A', 'SEC', '8ème', 'A')")
        self.c7, self.c8 = (r[0] for r in c.execute("SELECT N_CLASSE FROM CLASSE ORDER BY N_CLASSE"))
        self.annee = cours.creer_annee(c, self.admin, "2026-2027", "07/09/2026", "10/07/2027", en_cours=True)
        cours.generer_structure_standard(c, self.admin, self.annee)
        self.pers = [r[0] for r in c.execute("SELECT ID_PER FROM PERIODE_SCO ORDER BY DATE_DEBUT")]
        self.sems = [r[0] for r in c.execute("SELECT ID_SEM FROM SEMESTRE_SCO ORDER BY DATE_DEBUT")]
        with c:                                                                                  # le titulaire a ouvert toutes les saisies
            for classe in (self.c7, self.c8):
                for cle in [f"P{i}" for i in self.pers] + [f"X{i}" for i in self.sems]:
                    c.execute("INSERT INTO AUTORISATION_SAISIE (ANNEESCO, N_CLASSE, CLE, DATE_ENREG, ENREGISTRE_PAR) VALUES (?,?,?,?,?)",
                              (self.annee, classe, cle, "2026-09-01T00:00:00", "essai"))
        self.m1 = personnel.enregistrer_agent(c, self.admin, agent())["matricule"]               # titulaire du 7ème A
        self.m2 = personnel.enregistrer_agent(c, self.admin, agent(nom="banza", prenom="paul"))["matricule"]
        ids = {n: cours.ajouter_cours(c, self.admin, {"libelle": n, "code_niveau": "SEC", "heures_semaine": "4"})
               for n in ("Mathématiques", "Français")}
        cours.ouvrir_cours(c, self.admin, self.annee, self.c7)
        cours.ouvrir_cours(c, self.admin, self.annee, self.c8)
        cc = lambda classe, nom: c.execute("SELECT ID_CC FROM COURS_CLASSE WHERE N_CLASSE = ? AND ID_COURS = ?", (classe, ids[nom])).fetchone()[0]
        self.maths, self.fr = cc(self.c7, "Mathématiques"), cc(self.c7, "Français")
        cours.attribuer_professeur(c, self.admin, [self.maths], self.m1)
        cours.attribuer_professeur(c, self.admin, [self.fr], self.m2)
        self.mat = ("0001/26", "0002/26", "0003/26", "0004/26")
        with c:
            for m, nom in zip(self.mat, ("Amisi", "Kasongo", "Tshala", "Zola")):
                c.execute("INSERT INTO ELEVE (MATRICULE, NOM, POSTNOM, PRENOM, SEXE) VALUES (?,?,?,?,?)", (m, nom, "X", "Y", "M"))
                c.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?,?,?)", (self.annee, m, self.c7))
        self.p1 = p1 = notes.creer_compte_professeur(c, self.admin, self.m1)
        self.p2 = p2 = notes.creer_compte_professeur(c, self.admin, self.m2)
        self.s1 = security.authentifier(c, p1["login"], p1["mdp_temporaire"]).session
        self.s2 = security.authentifier(c, p2["login"], p2["mdp_temporaire"]).session
        bulletins.designer_titulaire(c, self.admin, self.annee, self.c7, self.m1)

    def saisir(self, session, id_cc, per, maximum, valeurs):
        """Points d'un cours pour une période (id) ou l'examen d'un semestre ('X<id>') : un seul point par élève."""
        notes.definir_maximum(self.conn, session, id_cc, per, maximum)
        return notes.enregistrer_points(self.conn, session, id_cc, per,
                                        dict(zip(self.mat, (str(v) if v is not None else "" for v in valeurs))))


class Calculs(Base):
    def remplir_periode(self, i):
        """Période i : Maths /30 et Français /20 ; Amisi 41/50, Kasongo 30/50, Tshala 30/50, Zola 15/50."""
        per = self.pers[i]
        self.saisir(self.s1, self.maths, per, 30, (24, 18, 18, 9))
        self.saisir(self.s2, self.fr, per, 20, (17, 12, 12, 6))

    def test_totaux_pourcentages_rangs_ex_aequo(self):
        self.remplir_periode(0)
        r = bulletins.calculer(self.conn, self.annee, self.c7)
        e = {x["matricule"]: x["portees"][f"P{self.pers[0]}"] for x in r["eleves"]}
        self.assertEqual((e["0001/26"]["obtenu"], e["0001/26"]["max"], e["0001/26"]["pct"]), (41, 50, 82.0))
        self.assertEqual(e["0002/26"]["pct"], 60.0)
        self.assertEqual(e["0004/26"]["pct"], 30.0)
        self.assertEqual([e[m]["rang"] for m in self.mat], [1, 2, 2, 4])           # ex aequo : 1, 2, 2, 4
        self.assertEqual(e["0001/26"]["mention"], "Grande distinction")
        self.assertEqual(e["0002/26"]["mention"], "Satisfaction")
        self.assertEqual(e["0004/26"]["mention"], "")
        self.assertEqual(e["0001/26"]["resultat"], config.RESULTAT_REUSSI)
        self.assertEqual(e["0004/26"]["resultat"], config.RESULTAT_ECHEC)
        c = next(x for x in r["eleves"] if x["matricule"] == "0001/26")["cours"][self.maths]
        self.assertEqual(c[f"P{self.pers[0]}"], {"obtenu": 24, "max": 30, "pct": 80.0})
        self.assertEqual(r["stats"][f"P{self.pers[0]}"]["reussis"], 3)
        self.assertEqual(r["stats"][f"P{self.pers[0]}"]["taux"], 75.0)

    def test_semestre_et_annee_et_attente(self):
        self.remplir_periode(0)
        self.remplir_periode(1)
        r = bulletins.calculer(self.conn, self.annee, self.c7)
        s1 = {x["matricule"]: x["portees"][f"S{self.sems[0]}"] for x in r["eleves"]}
        self.assertEqual((s1["0001/26"]["obtenu"], s1["0001/26"]["max"]), (82, 100))
        self.assertTrue(s1["0001/26"]["complet"])
        s2 = r["eleves"][0]["portees"][f"S{self.sems[1]}"]                         # 2ème semestre : rien saisi
        self.assertEqual(s2["resultat"], config.DECISION_ATTENTE)
        a = r["eleves"][0]["portees"]["A"]                                         # année incomplète : jamais de décision devinée
        self.assertFalse(a["complet"])
        self.assertEqual(a["resultat"], config.DECISION_ATTENTE)
        self.assertEqual(a["mention"], "")
        self.remplir_periode(2)
        self.remplir_periode(3)
        a = bulletins.calculer(self.conn, self.annee, self.c7)["eleves"][0]["portees"]["A"]
        self.assertTrue(a["complet"])
        self.assertEqual((a["obtenu"], a["max"], a["pct"]), (164, 200, 82.0))
        self.assertEqual(a["resultat"], config.DECISION_REUSSI)

    def test_le_semestre_est_periode_1_plus_periode_2_plus_examen(self):
        self.remplir_periode(0)
        self.remplir_periode(1)
        self.saisir(self.s1, self.maths, f"X{self.sems[0]}", 40, (36, 20, 20, 10))
        self.saisir(self.s2, self.fr, f"X{self.sems[0]}", 40, (30, 20, 20, 10))
        r = bulletins.calculer(self.conn, self.annee, self.c7)
        ami = next(x for x in r["eleves"] if x["matricule"] == "0001/26")["portees"]
        self.assertEqual((ami[f"P{self.pers[0]}"]["obtenu"], ami[f"P{self.pers[0]}"]["max"]), (41, 50))     # l'examen n'entre pas dans la période
        self.assertEqual((ami[f"P{self.pers[1]}"]["obtenu"], ami[f"P{self.pers[1]}"]["max"]), (41, 50))
        self.assertEqual((ami[f"X{self.sems[0]}"]["obtenu"], ami[f"X{self.sems[0]}"]["max"]), (66, 80))
        self.assertEqual((ami[f"S{self.sems[0]}"]["obtenu"], ami[f"S{self.sems[0]}"]["max"]), (148, 180))   # 41 + 41 + 66
        maths = next(x for x in r["eleves"] if x["matricule"] == "0001/26")["cours"][self.maths]
        self.assertEqual(maths[f"S{self.sems[0]}"], {"obtenu": 84, "max": 100, "pct": 84.0})
        self.assertTrue(ami[f"S{self.sems[0]}"]["complet"])
        config.EXAMEN_DANS_SEMESTRE = False                                                                   # variante : périodes seules
        try:
            ami = next(x for x in bulletins.calculer(self.conn, self.annee, self.c7)["eleves"] if x["matricule"] == "0001/26")["portees"]
            self.assertEqual((ami[f"S{self.sems[0]}"]["obtenu"], ami[f"S{self.sems[0]}"]["max"]), (82, 100))
            self.assertEqual(ami[f"X{self.sems[0]}"]["obtenu"], 66)
        finally:
            config.EXAMEN_DANS_SEMESTRE = True

    def test_semestre_sans_examen_est_complet_mais_l_examen_manquant_est_signale(self):
        self.remplir_periode(0)
        self.remplir_periode(1)
        r = bulletins.calculer(self.conn, self.annee, self.c7)
        ami = next(x for x in r["eleves"] if x["matricule"] == "0001/26")["portees"]
        self.assertTrue(ami[f"S{self.sems[0]}"]["complet"])
        self.assertEqual(ami[f"S{self.sems[0]}"]["obtenu"], 82)
        self.assertEqual(ami[f"X{self.sems[0]}"]["resultat"], config.DECISION_ATTENTE)
        self.assertTrue(any("Examen - " in m and "aucun point" in m for m in r["alertes"]))

    def test_anciennes_evaluations_toujours_comptees(self):
        """Une ancienne interrogation (INT, saisie avant ce changement) reste dans le total de sa période."""
        per = self.pers[0]
        self.saisir(self.s1, self.maths, per, 20, (16, 12, 12, 6))
        with self.conn:
            cur = self.conn.execute("INSERT INTO EVALUATION (ID_CC, ID_PER, TYPE, NUMERO, DATE_EVAL, MAXIMUM, DATE_ENREG, ENREGISTRE_PAR) "
                                    "VALUES (?,?,?,?,?,?,?,?)", (self.maths, per, "INT", 1, "2026-10-01", 10, "2026-10-01", "x"))
            self.conn.execute("INSERT INTO NOTE (ID_EVAL, MATRICULE, POINTS, DATE_MODIF) VALUES (?,?,?,?)", (cur.lastrowid, "0001/26", 8, "x"))
        r = bulletins.calculer(self.conn, self.annee, self.c7)
        c = next(x for x in r["eleves"] if x["matricule"] == "0001/26")["cours"][self.maths][f"P{per}"]
        self.assertEqual((c["obtenu"], c["max"]), (24, 30))

    def test_note_manquante_ignoree_ou_zero(self):
        per = self.pers[0]
        self.saisir(self.s1, self.maths, per, 20, (16, 12, None, 6))
        a = bulletins.calculer(self.conn, self.annee, self.c7)
        t = {x["matricule"]: x["portees"][f"P{per}"] for x in a["eleves"]}
        self.assertEqual((t["0003/26"]["obtenu"], t["0003/26"]["max"]), (None, None))   # rien à calculer
        self.assertEqual(t["0003/26"]["resultat"], config.DECISION_ATTENTE)
        self.assertIsNone(t["0003/26"]["rang"])
        self.assertEqual([x["matricule"] for x in a["eleves"] if x["portees"][f"P{per}"]["rang"]], ["0001/26", "0002/26", "0004/26"])
        self.assertTrue(any("points manquants" in m for m in a["alertes"]))
        config.NOTE_MANQUANTE = "ZERO"
        t = {x["matricule"]: x["portees"][f"P{per}"] for x in bulletins.calculer(self.conn, self.annee, self.c7)["eleves"]}
        self.assertEqual((t["0003/26"]["obtenu"], t["0003/26"]["max"], t["0003/26"]["pct"]), (0, 20, 0.0))

    def test_conduite_la_plus_frequente_sinon_la_plus_faible(self):
        per = self.pers[0]
        self.remplir_periode(0)
        for cc, s, cote in ((self.maths, self.s1, "TB"), (self.fr, self.s2, "AB")):
            notes.enregistrer_conduite(self.conn, s, cc, per, self.mat[0], cote)
        notes.enregistrer_conduite(self.conn, self.s1, self.maths, per, self.mat[1], "B")
        t = {x["matricule"]: x["portees"][f"P{per}"]["conduite"] for x in bulletins.calculer(self.conn, self.annee, self.c7)["eleves"]}
        self.assertEqual(t["0001/26"], "AB")        # égalité TB / AB : la plus faible
        self.assertEqual(t["0002/26"], "B")
        self.assertEqual(t["0003/26"], "")

    def test_alertes_cours_sans_evaluation(self):
        a = bulletins.calculer(self.conn, self.annee, self.c7)["alertes"]
        self.assertTrue(any("Mathématiques : aucun point" in m for m in a))

    def test_colonnes_du_bulletin(self):
        p = bulletins._portees(self.conn, self.annee)
        self.assertEqual(len(bulletins.colonnes_bulletin(p, f"P{self.pers[0]}")), 1)
        self.assertEqual([c["cle"] for c in bulletins.colonnes_bulletin(p, f"S{self.sems[0]}")],
                         [f"P{self.pers[0]}", f"P{self.pers[1]}", f"X{self.sems[0]}", f"S{self.sems[0]}"])
        self.assertEqual(len(bulletins.colonnes_bulletin(p, f"X{self.sems[0]}")), 1)
        self.assertEqual(len(bulletins.colonnes_bulletin(p, "A")), 7)
        with self.assertRaises(ErreurBulletins):
            bulletins.colonnes_bulletin(p, "X9")


class Droits(Base):
    def test_seul_le_titulaire_voit_la_fonctionnalite(self):
        self.assertEqual(bulletins.acces(self.conn, self.s1), {"titulaire": True, "enseigne": True})
        self.assertEqual(bulletins.acces(self.conn, self.s2), {"titulaire": False, "enseigne": True})
        self.assertEqual(len(bulletins.mes_classes(self.conn, self.s1)["classes"]), 1)
        appels = (lambda: bulletins.mes_classes(self.conn, self.s2),
                  lambda: bulletins.resultats(self.conn, self.s2, self.annee, self.c7, "A"),
                  lambda: bulletins.document_pdf(self.conn, self.s2, "bulletins", self.annee, self.c7, "A"),
                  lambda: bulletins.document_pdf(self.conn, self.s2, "liste", self.annee, self.c7, "A"),
                  lambda: bulletins.document_pdf(self.conn, self.s2, "proclamation", self.annee, self.c7),
                  lambda: bulletins.resultats(self.conn, self.s1, self.annee, self.c8, "A"))     # titulaire du 7ème, pas du 8ème
        for appel in appels:
            with self.assertRaises(PermissionError):
                appel()

    def test_ni_l_administrateur_ni_un_compte_non_professeur(self):
        with self.assertRaises(PermissionError):
            bulletins.resultats(self.conn, self.admin, self.annee, self.c7, "A")

    def test_desigation_demande_le_droit_modification(self):
        with self.assertRaises(PermissionError):
            bulletins.designer_titulaire(self.conn, self.s1, self.annee, self.c7, self.m2)
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c7, self.m2)          # remplace m1
        self.assertEqual(bulletins.acces(self.conn, self.s1), {"titulaire": False, "enseigne": True})
        self.assertEqual(bulletins.acces(self.conn, self.s2), {"titulaire": True, "enseigne": True})
        bulletins.retirer_titulaire(self.conn, self.admin, self.annee, self.c7)
        self.assertEqual(bulletins.acces(self.conn, self.s2), {"titulaire": False, "enseigne": True})
        with self.assertRaises(ErreurBulletins):
            bulletins.retirer_titulaire(self.conn, self.admin, self.annee, self.c7)
        actions = [r[0] for r in self.conn.execute("SELECT ACTION FROM JOURNAL WHERE ACTION LIKE 'TITULAIRE%'")]
        self.assertEqual(actions, ["TITULAIRE_DESIGNE", "TITULAIRE_DESIGNE", "TITULAIRE_RETIRE"])

    def test_agent_inconnu_ou_desactive(self):
        with self.assertRaises(ErreurBulletins):
            bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c7, "ZZZ")
        with self.assertRaises(ErreurBulletins):
            bulletins.designer_titulaire(self.conn, self.admin, "2030-2031", self.c7, self.m1)


class Documents(Base):
    def setUp(self):
        super().setUp()
        for i in range(4):
            per = self.pers[i]
            self.saisir(self.s1, self.maths, per, 20, (16, 12, 12, 6))
            self.saisir(self.s2, self.fr, per, 20, (17, 12, 12, 6))
        for sem in self.sems:
            self.saisir(self.s1, self.maths, f"X{sem}", 40, (30, 24, 24, 12))
            self.saisir(self.s2, self.fr, f"X{sem}", 40, (30, 24, 24, 12))

    def test_pdf_et_journal(self):
        ouvrir_impression(self.conn, self.annee, self.c7)
        pdf, nom = bulletins.document_pdf(self.conn, self.s1, "bulletins", self.annee, self.c7, "A")
        self.assertTrue(pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF"))
        self.assertEqual(pdf.count(b"/Type /Page "), 4)                                          # un bulletin par élève
        self.assertTrue(nom.startswith("bulletin_7eme_a") and nom.endswith(".pdf"))
        un, _ = bulletins.document_pdf(self.conn, self.s1, "bulletin", self.annee, self.c7, f"S{self.sems[0]}", "0002/26")
        self.assertEqual(un.count(b"/Type /Page "), 1)
        for genre in ("liste", "proclamation"):
            octets, _n = bulletins.document_pdf(self.conn, self.s1, genre, self.annee, self.c7, f"P{self.pers[0]}")
            self.assertTrue(octets.startswith(b"%PDF"))
        actions = {r[0] for r in self.conn.execute("SELECT ACTION FROM JOURNAL")}
        self.assertTrue({"BULLETINS_GENERES", "LISTE_RESULTATS_GENEREE", "PROCLAMATION_GENEREE"} <= actions)

    def test_eleve_d_une_autre_classe_refuse(self):
        with self.conn:
            self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('0009/26', 'Autre')")
            self.conn.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?,?,?)", (self.annee, "0009/26", self.c8))
        with self.assertRaises(PermissionError):
            bulletins.document_pdf(self.conn, self.s1, "bulletin", self.annee, self.c7, "A", "0009/26")

    def test_resultats_classes(self):
        r = bulletins.resultats(self.conn, self.s1, self.annee, self.c7, "A")
        self.assertEqual([l["rang"] for l in r["lignes"]], [1, 2, 2, 4])
        self.assertEqual(r["lignes"][0]["nom_complet"], "Amisi X Y")
        self.assertEqual(r["stats"]["effectif"], 4)
        self.assertEqual(r["alertes"], [])

    # ------------------------------------------------------------------ espace du titulaire : liste des élèves, cotes, réussites / échecs
    def abaisser_amisi(self):
        """Amisi échoue en période 1 (4/40) ; Kasongo et Tshala 24/40 (60 %) ; Zola 12/40 (30 %)."""
        per = self.pers[0]
        self.saisir(self.s1, self.maths, per, 20, (2, 12, 12, 6))
        self.saisir(self.s2, self.fr, per, 20, (2, 12, 12, 6))
        return f"P{per}"

    def test_liste_dans_l_ordre_des_reussites_puis_echecs(self):
        cle = self.abaisser_amisi()
        noms = lambda r: [l["nom_complet"].split()[0] for l in r["lignes"]]
        r = bulletins.resultats(self.conn, self.s1, self.annee, self.c7, cle)                 # par défaut : réussites d'abord
        self.assertEqual(noms(r), ["Kasongo", "Tshala", "Zola", "Amisi"])
        self.assertEqual([l["reussite"] for l in r["lignes"]], [True, True, False, False])
        a = bulletins.resultats(self.conn, self.s1, self.annee, self.c7, cle, ordre="alpha")
        self.assertEqual(noms(a), ["Amisi", "Kasongo", "Tshala", "Zola"])
        self.assertEqual(r["stats"]["reussis"], 2)
        self.assertEqual(r["stats"]["echecs"], 2)

    def test_les_en_attente_viennent_apres_les_echecs(self):
        cle = f"S{self.sems[0]}"
        with self.conn:                                                    # Tshala n'a plus de points en période 2 : semestre incomplet
            self.conn.execute("DELETE FROM NOTE WHERE MATRICULE = '0003/26' AND ID_EVAL IN (SELECT ID_EVAL FROM EVALUATION WHERE ID_PER = ?)",
                              (self.pers[1],))
        r = bulletins.resultats(self.conn, self.s1, self.annee, self.c7, cle)
        self.assertEqual(r["lignes"][-1]["nom_complet"].split()[0], "Tshala")
        self.assertIsNone(r["lignes"][-1]["reussite"])
        self.assertEqual([l["reussite"] for l in r["lignes"]], [True, True, False, None])

    def test_le_pdf_de_la_liste_suit_le_meme_ordre(self):
        cle = self.abaisser_amisi()
        ouvrir_impression(self.conn, self.annee, self.c7)
        calc = bulletins.calculer(self.conn, self.annee, self.c7)
        ordre = sorted(calc["eleves"], key=lambda e: (bulletins.ordre_reussite(e["portees"][cle]), e["nom_complet"].lower()))
        self.assertEqual([e["nom_complet"].split()[0] for e in ordre], ["Kasongo", "Tshala", "Zola", "Amisi"])
        pdf, nom = bulletins.document_pdf(self.conn, self.s1, "liste", self.annee, self.c7, cle)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertTrue(nom.startswith("resultats_7eme_a"))

    def test_cotes_d_un_eleve_dans_tous_les_cours(self):
        f = bulletins.fiche_eleve(self.conn, self.s1, self.annee, self.c7, "0002/26")
        self.assertEqual(f["eleve"]["nom_complet"], "Kasongo X Y")
        self.assertEqual({c["libelle"] for c in f["cours"]}, {"Mathématiques", "Français"})          # les cours des deux professeurs
        p1 = f"P{self.pers[0]}"
        maths = next(c for c in f["cours"] if c["libelle"] == "Mathématiques")
        self.assertEqual(maths["cotes"][p1], {"obtenu": 12, "max": 20, "pct": 60.0})
        self.assertEqual(f["totaux"][p1]["obtenu"], 24)
        self.assertEqual(f["totaux"][p1]["resultat"], config.RESULTAT_REUSSI)
        self.assertEqual(f["totaux"]["A"]["rang"], 2)
        self.assertEqual([c["type"] for c in f["colonnes"]].count("periode"), 4)
        self.assertEqual(f["colonnes"][-1]["cle"], "A")
        self.assertEqual(f["effectif"], 4)

    def test_cotes_d_un_eleve_refusees_hors_de_sa_classe_ou_a_un_non_titulaire(self):
        with self.conn:
            self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('0009/26', 'Autre')")
            self.conn.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?,?,?)", (self.annee, "0009/26", self.c8))
        with self.assertRaises(PermissionError):
            bulletins.fiche_eleve(self.conn, self.s1, self.annee, self.c7, "0009/26")             # élève d'une autre classe
        with self.assertRaises(PermissionError):
            bulletins.fiche_eleve(self.conn, self.s1, self.annee, self.c8, "0009/26")             # classe dont il n'est pas titulaire
        with self.assertRaises(PermissionError):
            bulletins.fiche_eleve(self.conn, self.s2, self.annee, self.c7, "0002/26")             # collègue non titulaire
        with self.assertRaises(PermissionError):
            bulletins.fiche_eleve(self.conn, self.s1, self.annee, self.c7, None)

    def test_portee_par_defaut_est_la_plus_recente_complete(self):
        k = bulletins.mes_classes(self.conn, self.s1)["classes"][0]
        self.assertEqual(k["portee_defaut"], "A")                                                    # tout est saisi : l'année


class TitulaireSansCours(Base):
    """Un titulaire qui n'enseigne pas : il voit la liste de ses élèves et leurs cotes (jamais « Points » ni « Présence »)."""
    def setUp(self):
        super().setUp()
        self.m3 = personnel.enregistrer_agent(self.conn, self.admin, agent(nom="lumbala", prenom="eric"))["matricule"]
        self.p3 = notes.creer_compte_professeur(self.conn, self.admin, self.m3)
        self.s3 = security.authentifier(self.conn, self.p3["login"], self.p3["mdp_temporaire"]).session
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c8, self.m3)
        with self.conn:
            for m, nom in (("0101/26", "Bope"), ("0102/26", "Ilunga")):
                self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM, POSTNOM, PRENOM, SEXE) VALUES (?,?,?,?,?)", (m, nom, "X", "Y", "F"))
                self.conn.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?,?,?)", (self.annee, m, self.c8))

    def test_acces_titulaire_sans_cours(self):
        self.assertEqual(bulletins.acces(self.conn, self.s3), {"titulaire": True, "enseigne": False})
        self.assertEqual(bulletins.acces(self.conn, self.s1), {"titulaire": True, "enseigne": True})      # titulaire et professeur

    def test_la_liste_des_eleves_s_affiche_meme_sans_points(self):
        r = bulletins.resultats(self.conn, self.s3, self.annee, self.c8, "A", ordre="alpha")
        self.assertEqual([l["nom_complet"].split()[0] for l in r["lignes"]], ["Bope", "Ilunga"])
        f = bulletins.fiche_eleve(self.conn, self.s3, self.annee, self.c8, "0101/26")
        self.assertEqual(f["eleve"]["matricule"], "0101/26")

    def test_la_liste_des_eleves_s_affiche_meme_sans_semestres_ni_periodes(self):
        with self.conn:
            self.conn.execute("DELETE FROM AUTORISATION_SAISIE")
            self.conn.execute("DELETE FROM PERIODE_SCO")
            self.conn.execute("DELETE FROM SEMESTRE_SCO")
        r = bulletins.resultats(self.conn, self.s3, self.annee, self.c8, "")
        self.assertIsNone(r["portee"])
        self.assertEqual([l["nom_complet"].split()[0] for l in r["lignes"]], ["Bope", "Ilunga"])
        self.assertEqual(bulletins.mes_classes(self.conn, self.s3)["classes"][0]["portee_defaut"], "")
        self.assertEqual(bulletins.fiche_eleve(self.conn, self.s3, self.annee, self.c8, "0102/26")["colonnes"], [])

    def test_le_titulaire_ne_voit_pas_la_classe_d_un_autre(self):
        with self.assertRaises(PermissionError):
            bulletins.resultats(self.conn, self.s3, self.annee, self.c7, "A")


class ServeurWeb(Documents):
    """Par le serveur web : l'onglet n'est offert qu'au titulaire ; les autres professeurs reçoivent un refus (403)."""
    def setUp(self):
        super().setUp()
        chemin = self.conn.execute("PRAGMA database_list").fetchone()[2]
        self.srv = serveur_notes.Serveur(port=0, hote="127.0.0.1", chemin_bd=chemin).demarrer()
        self.addCleanup(self.srv.arreter)
        self.j1, self.j2 = self.connecter(self.p1), self.connecter(self.p2)

    def requete(self, methode, chemin, corps=None, jeton=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=30)
        en = {"Content-Type": "application/json"}
        if jeton:
            en["Authorization"] = "Bearer " + jeton
        c.request(methode, chemin, json.dumps(corps) if corps is not None else None, en)
        r = c.getresponse()
        data = r.read()
        ent = dict(r.getheaders())
        c.close()
        return r.status, data, ent

    def connecter(self, p):
        st, d, _ = self.requete("POST", "/api/connexion", {"login": p["login"], "mdp": p["mdp_temporaire"]})
        self.assertEqual(st, 200, d)
        jeton = json.loads(d)["jeton"]
        nouveau = "Nouveau-Mdp#2026-ok"
        st, d, _ = self.requete("POST", "/api/mdp", {"ancien": p["mdp_temporaire"], "nouveau": nouveau, "confirmation": nouveau}, jeton)
        self.assertEqual(st, 200, d)
        return jeton

    def get(self, chemin, jeton, **q):
        from urllib.parse import urlencode
        return self.requete("GET", "/api/" + chemin + ("?" + urlencode(q) if q else ""), jeton=jeton)

    def test_acces_reserve_au_titulaire(self):
        self.assertEqual(json.loads(self.get("bulletins/acces", self.j1)[1]), {"titulaire": True, "enseigne": True})
        self.assertEqual(json.loads(self.get("bulletins/acces", self.j2)[1]), {"titulaire": False, "enseigne": True})
        for chemin, q in (("bulletins/classes", {}), ("bulletins/eleve", {"annee": self.annee, "classe": self.c7, "matricule": "0001/26"}),
                          ("bulletins/resultats", {"annee": self.annee, "classe": self.c7, "portee": "A"}),
                          ("bulletins/pdf", {"genre": "bulletins", "annee": self.annee, "classe": self.c7, "portee": "A"}),
                          ("bulletins/pdf", {"genre": "proclamation", "annee": self.annee, "classe": self.c7})):
            st, d, _ = self.get(chemin, self.j2, **q)
            self.assertEqual(st, 403, (chemin, d))
            self.assertIn("titulaire", json.loads(d)["erreur"])
        self.assertEqual(self.get("bulletins/acces", "jeton-bidon")[0], 401)

    def test_le_titulaire_recoit_ses_resultats_et_un_vrai_pdf(self):
        st, d, _ = self.get("bulletins/classes", self.j1)
        self.assertEqual(st, 200)
        cl = json.loads(d)
        self.assertEqual([c["designation"] for c in cl["classes"]], ["7ème A"])
        st, d, _ = self.get("bulletins/resultats", self.j1, annee=self.annee, classe=self.c7, portee="A")
        self.assertEqual(st, 200)
        self.assertEqual([l["rang"] for l in json.loads(d)["lignes"]], [1, 2, 2, 4])
        ouvrir_impression(self.conn, self.annee, self.c7)
        st, d, ent = self.get("bulletins/pdf", self.j1, genre="bulletins", annee=self.annee, classe=self.c7, portee="A")
        self.assertEqual(st, 200)
        self.assertEqual(ent["Content-Type"], "application/pdf")
        self.assertTrue(d.startswith(b"%PDF"))
        self.assertIn("filename=", ent["Content-Disposition"])
        st, d, _ = self.get("bulletins/pdf", self.j1, genre="bulletins", annee=self.annee, classe=self.c8, portee="A")
        self.assertEqual(st, 403)                                         # une autre classe que la sienne

    def test_le_titulaire_consulte_les_cotes_d_un_eleve_par_le_serveur(self):
        st, d, _ = self.get("bulletins/eleve", self.j1, annee=self.annee, classe=self.c7, matricule="0002/26")
        self.assertEqual(st, 200, d)
        f = json.loads(d)
        self.assertEqual(f["eleve"]["nom_complet"], "Kasongo X Y")
        self.assertEqual(len(f["cours"]), 2)
        self.assertEqual(self.get("bulletins/eleve", self.j2, annee=self.annee, classe=self.c7, matricule="0002/26")[0], 403)
        self.assertEqual(self.get("bulletins/eleve", self.j1, annee=self.annee, classe=self.c7, matricule="9999/26")[0], 403)
        st, d, _ = self.get("bulletins/resultats", self.j1, annee=self.annee, classe=self.c7, portee="A", ordre="alpha")
        self.assertEqual([l["nom_complet"].split()[0] for l in json.loads(d)["lignes"]], ["Amisi", "Kasongo", "Tshala", "Zola"])

    def test_la_page_contient_l_onglet_cree_seulement_pour_un_titulaire(self):
        st, d, _ = self.requete("GET", "/")
        self.assertIn(b'"bulletins/acces"', d)
        self.assertIn(b'class="onglet cache" data-mode="bulletins" id="o-classe">Ma classe', d)   # onglet caché : le script ne le montre qu'au titulaire
        self.assertIn(b'"bulletins/eleve"', d)


if __name__ == "__main__":
    unittest.main()

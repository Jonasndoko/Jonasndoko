"""Tests de « Gestion des cours et des enseignants » (Gestion scolaire, 1ère fonctionnalité) : calendrier scolaire, cours,
programme des classes, professeurs, droits, journal.
Lancer :  python test_cours.py"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import cours          # noqa: E402
import database       # noqa: E402
import droits         # noqa: E402
import personnel      # noqa: E402
import security       # noqa: E402
from cours import ErreurCours  # noqa: E402

MDP = "Tr@vail-Amour-2026"


def saisie_agent(**autres):
    base = {"nom": "mukendi", "postnom": "kabeya", "prenom": "jean", "sexe": "M", "date_naissance": "15/03/1985",
            "adresse": "Kinshasa", "telephone": "0812345678", "email": "", "date_engagement": "01/09/2015",
            "fonction": "Enseignant", "statut_pro": "PERMANENT", "matricule": ""}
    base.update(autres)
    return base


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(os.path.join(tempfile.mkdtemp(), "c.db"))
        security.creer_utilisateur(self.conn, "admin1", "Alice", "ADMINISTRATEUR", MDP)
        self.admin = security.authentifier(self.conn, "admin1", MDP).session
        self.id_sec = security.creer_utilisateur(self.conn, "sec1", "Sophie", "SECRETAIRE", MDP)
        self.sec = security.authentifier(self.conn, "sec1", MDP).session
        c = self.conn
        with c:
            c.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU) VALUES ('SEC', 'Secondaire'), ('HUM', 'Humanités')")
            c.execute("INSERT INTO OPTION_SCO (CODE_OPTION, DESI_OPTION) VALUES ('SCI', 'Scientifique'), ('COM', 'Commerciale')")
            c.execute("INSERT INTO POSSEDE (CODE_NIVEAU, CODE_OPTION) VALUES ('HUM', 'SCI'), ('HUM', 'COM')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('7ème A', 'SEC', '7ème', 'A')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('8ème A', 'SEC', '8ème', 'A')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, CODE_OPTION, ANNEE_ETUDE, DIVISION) VALUES ('3ème Sci', 'HUM', 'SCI', '3ème', '')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, CODE_OPTION, ANNEE_ETUDE, DIVISION) VALUES ('3ème Com', 'HUM', 'COM', '3ème', '')")
        self.c7, self.c8, self.csci, self.ccom = (r[0] for r in c.execute("SELECT N_CLASSE FROM CLASSE ORDER BY N_CLASSE"))
        self.annee = cours.creer_annee(c, self.admin, "2026-2027", "07/09/2026", "10/07/2027", en_cours=True)
        self.prof = personnel.enregistrer_agent(c, self.admin, saisie_agent())["matricule"]
        self.prof2 = personnel.enregistrer_agent(c, self.admin, saisie_agent(nom="banza", prenom="paul"))["matricule"]

    def donner(self, *noms):
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_sec, {("direction_etudes", d) for d in noms})

    def actions(self):
        return [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL ORDER BY ID_LOG")]

    def cours(self, libelle, niveau="SEC", option="", annee_etude="", heures="4"):
        return cours.ajouter_cours(self.conn, self.admin, {"libelle": libelle, "code_niveau": niveau, "code_option": option,
                                                           "annee_etude": annee_etude, "heures_semaine": heures})


class TestCalendrier(Base):
    def test_annee_creee_en_cours_et_dates(self):
        a = cours.lister_annees(self.conn, self.admin)[0]
        self.assertEqual((a["annee"], a["en_cours"], a["debut"], a["fin"]), ("2026-2027", True, "07/09/2026", "10/07/2027"))
        cours.creer_annee(self.conn, self.admin, "2027-2028", "06/09/2027", "08/07/2028", en_cours=True)
        self.assertEqual([x["annee"] for x in cours.lister_annees(self.conn, self.admin) if x["en_cours"]], ["2027-2028"])

    def test_annee_invalide(self):
        for annee, d, f in (("2026-2028", "07/09/2026", "10/07/2027"), ("2027-2028", "07/09/2026", "10/07/2027"),
                            ("2027-2028", "10/07/2028", "06/09/2027"), ("2026-2027", "07/09/2026", "10/07/2027")):
            with self.assertRaises(ErreurCours):
                cours.creer_annee(self.conn, self.admin, annee, d, f)

    def test_annee_existante_sans_dates_recoit_ses_dates(self):
        with self.conn:
            self.conn.execute("INSERT INTO ANNEE_SCO (ANNEESCO, EN_COURS, ACTIF) VALUES ('2025-2026', 0, 1)")
        self.assertFalse(next(a for a in cours.lister_annees(self.conn, self.admin) if a["annee"] == "2025-2026")["avec_dates"])
        cours.creer_annee(self.conn, self.admin, "2025-2026", "08/09/2025", "10/07/2026")
        self.assertTrue(next(a for a in cours.lister_annees(self.conn, self.admin) if a["annee"] == "2025-2026")["avec_dates"])

    def test_structure_standard(self):
        r = cours.generer_structure_standard(self.conn, self.admin, self.annee)
        self.assertEqual(r, {"semestres": 2, "periodes": 4})
        cal = cours.calendrier_annee(self.conn, self.admin, self.annee)
        self.assertEqual([len(s["periodes"]) for s in cal["semestres"]], [2, 2])
        self.assertEqual(cal["semestres"][0]["debut"], "07/09/2026")
        self.assertEqual(cal["semestres"][1]["fin"], "10/07/2027")
        self.assertEqual(cal["semestres"][0]["periodes"][0]["debut"], "07/09/2026")
        with self.assertRaises(ErreurCours):
            cours.generer_structure_standard(self.conn, self.admin, self.annee)

    def test_semestres_dans_l_annee_sans_chevauchement(self):
        s1 = cours.ajouter_semestre(self.conn, self.admin, self.annee, "1er semestre", "07/09/2026", "31/01/2027")
        with self.assertRaises(ErreurCours):
            cours.ajouter_semestre(self.conn, self.admin, self.annee, "2ème semestre", "31/01/2027", "10/07/2027")      # chevauche
        with self.assertRaises(ErreurCours):
            cours.ajouter_semestre(self.conn, self.admin, self.annee, "2ème semestre", "01/02/2027", "20/07/2027")      # hors année
        with self.assertRaises(ErreurCours):
            cours.ajouter_semestre(self.conn, self.admin, self.annee, "1ER SEMESTRE", "01/02/2027", "10/07/2027")      # doublon de nom
        cours.ajouter_semestre(self.conn, self.admin, self.annee, "2ème semestre", "01/02/2027", "10/07/2027")
        cours.modifier_semestre(self.conn, self.admin, s1, "Premier semestre", "07/09/2026", "30/01/2027")

    def test_periodes_dans_le_semestre(self):
        s1 = cours.ajouter_semestre(self.conn, self.admin, self.annee, "1er semestre", "07/09/2026", "31/01/2027")
        p1 = cours.ajouter_periode(self.conn, self.admin, s1, "1ère période", "07/09/2026", "30/10/2026")
        with self.assertRaises(ErreurCours):
            cours.ajouter_periode(self.conn, self.admin, s1, "2ème période", "30/10/2026", "31/01/2027")             # chevauche
        with self.assertRaises(ErreurCours):
            cours.ajouter_periode(self.conn, self.admin, s1, "2ème période", "02/11/2026", "05/02/2027")             # hors semestre
        cours.ajouter_periode(self.conn, self.admin, s1, "2ème période", "02/11/2026", "31/01/2027")
        with self.assertRaises(ErreurCours):                                                                           # sortirait
            cours.modifier_semestre(self.conn, self.admin, s1, "1er semestre", "07/09/2026", "20/01/2027")
        with self.assertRaises(ErreurCours):
            cours.supprimer_semestre(self.conn, self.admin, s1)                                                       # contient des périodes
        cours.supprimer_periode(self.conn, self.admin, p1)

    def test_deux_semestres_de_deux_periodes_au_maximum(self):
        s1 = cours.ajouter_semestre(self.conn, self.admin, self.annee, "1er semestre", "07/09/2026", "31/01/2027")
        cours.ajouter_semestre(self.conn, self.admin, self.annee, "2ème semestre", "01/02/2027", "10/07/2027")
        with self.assertRaises(cours.ErreurCours):
            cours.ajouter_semestre(self.conn, self.admin, self.annee, "3ème semestre", "11/07/2027", "10/07/2027")
        cours.ajouter_periode(self.conn, self.admin, s1, "1ère période", "07/09/2026", "30/10/2026")
        cours.ajouter_periode(self.conn, self.admin, s1, "2ème période", "02/11/2026", "20/12/2026")
        with self.assertRaises(cours.ErreurCours):
            cours.ajouter_periode(self.conn, self.admin, s1, "3ème période", "05/01/2027", "31/01/2027")

    def test_dates_de_l_annee_doivent_contenir_les_semestres(self):
        cours.ajouter_semestre(self.conn, self.admin, self.annee, "1er semestre", "07/09/2026", "31/01/2027")
        with self.assertRaises(ErreurCours):
            cours.modifier_dates_annee(self.conn, self.admin, self.annee, "15/09/2026", "10/07/2027")
        cours.modifier_dates_annee(self.conn, self.admin, self.annee, "01/09/2026", "15/07/2027")

    def test_semestre_sans_dates_d_annee_refuse(self):
        with self.conn:
            self.conn.execute("INSERT INTO ANNEE_SCO (ANNEESCO, EN_COURS, ACTIF) VALUES ('2025-2026', 0, 1)")
        with self.assertRaises(ErreurCours):
            cours.ajouter_semestre(self.conn, self.admin, "2025-2026", "1er semestre", "08/09/2025", "31/01/2026")


class TestCours(Base):
    def test_cours_par_niveau_option_annee_etude(self):
        self.cours("mathématiques")
        self.cours("Mathématiques", "HUM", "SCI")
        self.cours("Mathématiques", "SEC", annee_etude="7ème")
        liste = cours.lister_cours(self.conn, self.admin)
        self.assertEqual(len(liste), 3)
        self.assertEqual(sorted(c["libelle"] for c in liste), ["Mathématiques"] * 3)
        with self.assertRaises(ErreurCours):
            self.cours("MATHÉMATIQUES".lower().replace("é", "é"))        # doublon exact (casse ignorée)

    def test_option_seulement_si_le_niveau_la_propose(self):
        with self.assertRaises(ErreurCours):
            self.cours("Dessin", "SEC", "SCI")
        self.cours("Dessin", "HUM")                                      # commun à toutes les options
        with self.assertRaises(ErreurCours):
            self.cours("Dessin", "SEC", annee_etude="5ème")              # aucune classe de cette année d'étude
        with self.assertRaises(ErreurCours):
            self.cours("", "SEC")
        with self.assertRaises(ErreurCours):
            self.cours("Dessin", "XXX")
        with self.assertRaises(ErreurCours):
            self.cours("Sport", "SEC", heures="99")

    def test_modifier_desactiver_supprimer(self):
        i = self.cours("Français")
        cours.modifier_cours(self.conn, self.admin, i, {"libelle": "Français 1", "code_niveau": "SEC", "heures_semaine": "5"})
        self.assertEqual(cours.lister_cours(self.conn, self.admin)[0]["heures"], 5)
        cours.changer_activite_cours(self.conn, self.admin, i, False)
        self.assertEqual(cours.lister_cours(self.conn, self.admin, inclure_inactifs=False), [])
        cours.changer_activite_cours(self.conn, self.admin, i, True)
        cours.supprimer_cours(self.conn, self.admin, i)
        self.assertEqual(cours.lister_cours(self.conn, self.admin), [])

    def test_cours_utilise_ne_change_plus_de_niveau_et_ne_se_supprime_pas(self):
        i = self.cours("Français")
        cours.ouvrir_cours(self.conn, self.admin, self.annee, self.c7, [i])
        with self.assertRaises(ErreurCours):
            cours.modifier_cours(self.conn, self.admin, i, {"libelle": "Français", "code_niveau": "HUM", "heures_semaine": "4"})
        cours.modifier_cours(self.conn, self.admin, i, {"libelle": "Français", "code_niveau": "SEC", "heures_semaine": "6"})
        with self.assertRaises(ErreurCours):
            cours.supprimer_cours(self.conn, self.admin, i)

    def test_recherche_et_filtre_niveau(self):
        self.cours("Mathématiques")
        self.cours("Chimie", "HUM", "SCI")
        self.assertEqual([c["libelle"] for c in cours.lister_cours(self.conn, self.admin, code_niveau="HUM")], ["Chimie"])
        self.assertEqual(len(cours.lister_cours(self.conn, self.admin, recherche="MATHEMATIQ")), 1)


class TestProgramme(Base):
    def preparer(self):
        self.math_sec = self.cours("Mathématiques")                       # tout le niveau secondaire
        self.sci7 = self.cours("Sciences", annee_etude="7ème")           # 7ème seulement
        self.chimie = self.cours("Chimie", "HUM", "SCI")                  # humanités scientifiques
        self.anglais = self.cours("Anglais", "HUM")                       # humanités, toutes options

    def test_cours_applicables_a_chaque_classe(self):
        self.preparer()
        noms = lambda n: sorted(c["libelle"] for c in cours.programme_classe(self.conn, self.admin, self.annee, n)["a_ouvrir"])
        self.assertEqual(noms(self.c7), ["Mathématiques", "Sciences"])
        self.assertEqual(noms(self.c8), ["Mathématiques"])
        self.assertEqual(noms(self.csci), ["Anglais", "Chimie"])
        self.assertEqual(noms(self.ccom), ["Anglais"])

    def test_ouvrir_tous_puis_rien_de_plus(self):
        self.preparer()
        self.assertEqual(cours.ouvrir_cours(self.conn, self.admin, self.annee, self.c7), 2)
        self.assertEqual(cours.ouvrir_cours(self.conn, self.admin, self.annee, self.c7), 0)
        p = cours.programme_classe(self.conn, self.admin, self.annee, self.c7)
        self.assertEqual((len(p["cours"]), p["a_ouvrir"]), (2, []))
        self.assertEqual(p["cours"][0]["heures"], 4)

    def test_cours_non_applicable_ou_double_refuse(self):
        self.preparer()
        with self.assertRaises(ErreurCours):
            cours.ouvrir_cours(self.conn, self.admin, self.annee, self.c8, [self.sci7])                 # 7ème seulement
        with self.assertRaises(ErreurCours):
            cours.ouvrir_cours(self.conn, self.admin, self.annee, self.ccom, [self.chimie])             # option différente
        cours.ouvrir_cours(self.conn, self.admin, self.annee, self.c7, [self.math_sec])
        with self.assertRaises(ErreurCours):
            cours.ouvrir_cours(self.conn, self.admin, self.annee, self.c7, [self.math_sec])
        cours.changer_activite_cours(self.conn, self.admin, self.sci7, False)
        with self.assertRaises(ErreurCours):
            cours.ouvrir_cours(self.conn, self.admin, self.annee, self.c7, [self.sci7])

    def test_heures_et_retrait(self):
        self.preparer()
        cours.ouvrir_cours(self.conn, self.admin, self.annee, self.c8)
        cc = cours.programme_classe(self.conn, self.admin, self.annee, self.c8)["cours"][0]["id"]
        cours.modifier_heures(self.conn, self.admin, cc, "6")
        self.assertEqual(cours.programme_classe(self.conn, self.admin, self.annee, self.c8)["cours"][0]["heures"], 6)
        with self.assertRaises(ErreurCours):
            cours.modifier_heures(self.conn, self.admin, cc, "abc")
        cours.retirer_cours_de_classe(self.conn, self.admin, cc)
        self.assertEqual(cours.programme_classe(self.conn, self.admin, self.annee, self.c8)["cours"], [])


class TestProfesseurs(Base):
    def preparer(self):
        m = self.cours("Mathématiques")
        f = self.cours("Français", heures="5")
        cours.ouvrir_cours(self.conn, self.admin, self.annee, self.c7)
        cours.ouvrir_cours(self.conn, self.admin, self.annee, self.c8)
        self.cc = {(l["classe"], l["cours"]): l["id"] for n in (self.c7, self.c8)
                   for l in cours.programme_classe(self.conn, self.admin, self.annee, n)["cours"]}
        return m, f

    def test_attribuer_un_cours_a_plusieurs_classes(self):
        self.preparer()
        r = cours.attribuer_professeur(self.conn, self.admin, [self.cc[("7ème A", "Mathématiques")], self.cc[("8ème A", "Mathématiques")]],
                                       self.prof)
        self.assertEqual(r, {"faits": 2, "inchanges": 0})
        d = cours.classes_du_professeur(self.conn, self.admin, self.annee, self.prof)
        self.assertEqual((d["nb_classes"], d["nb_cours"], d["heures"]), (2, 2, 8))
        self.assertEqual({l["classe"] for l in d["lignes"]}, {"7ème A", "8ème A"})
        self.assertEqual(d["lignes"][0]["professeur"], "MUKENDI KABEYA Jean")
        r = cours.attribuer_professeur(self.conn, self.admin, [self.cc[("7ème A", "Mathématiques")]], self.prof)
        self.assertEqual(r, {"faits": 0, "inchanges": 1})

    def test_un_seul_professeur_par_cours_changer_et_retirer(self):
        self.preparer()
        cc = self.cc[("7ème A", "Français")]
        cours.attribuer_professeur(self.conn, self.admin, [cc], self.prof)
        cours.attribuer_professeur(self.conn, self.admin, [cc], self.prof2)                     # remplace
        self.assertEqual(cours.classes_du_professeur(self.conn, self.admin, self.annee, self.prof)["nb_cours"], 0)
        self.assertEqual(cours.classes_du_professeur(self.conn, self.admin, self.annee, self.prof2)["nb_cours"], 1)
        cours.attribuer_professeur(self.conn, self.admin, [cc], "")                              # retire
        self.assertEqual(cours.classes_du_professeur(self.conn, self.admin, self.annee, self.prof2)["nb_cours"], 0)
        self.assertEqual(self.actions().count("PROFESSEUR_ATTRIBUE"), 2)
        self.assertEqual(self.actions().count("PROFESSEUR_RETIRE"), 1)

    def test_agent_desactive_ou_inconnu_refuse(self):
        self.preparer()
        cc = self.cc[("7ème A", "Français")]
        personnel.changer_activite(self.conn, self.admin, self.prof2, False)
        with self.assertRaises(ErreurCours):
            cours.attribuer_professeur(self.conn, self.admin, [cc], self.prof2)
        with self.assertRaises(ErreurCours):
            cours.attribuer_professeur(self.conn, self.admin, [cc], "XXX")
        with self.assertRaises(ErreurCours):
            cours.attribuer_professeur(self.conn, self.admin, [], self.prof)

    def test_liste_des_professeurs_et_charge(self):
        self.preparer()
        cours.attribuer_professeur(self.conn, self.admin, [self.cc[("7ème A", "Français")], self.cc[("8ème A", "Français")]], self.prof)
        liste = cours.lister_professeurs(self.conn, self.admin, self.annee)
        self.assertEqual(len(liste), 2)
        p = next(x for x in liste if x["matricule"] == self.prof)
        self.assertEqual((p["nb_cours"], p["nb_classes"], p["heures"]), (2, 2, 10))
        self.assertEqual([x["matricule"] for x in cours.lister_professeurs(self.conn, self.admin, self.annee, seulement_enseignants=True)], [self.prof])
        self.assertEqual(len(cours.lister_professeurs(self.conn, self.admin, self.annee, recherche="banza")), 1)

    def test_retrait_du_cours_de_la_classe_supprime_l_attribution(self):
        self.preparer()
        cc = self.cc[("7ème A", "Français")]
        cours.attribuer_professeur(self.conn, self.admin, [cc], self.prof)
        cours.retirer_cours_de_classe(self.conn, self.admin, cc)
        self.assertEqual(cours.classes_du_professeur(self.conn, self.admin, self.annee, self.prof)["nb_cours"], 0)


class TestDroits(Base):
    def test_sans_droit(self):
        for appel in (lambda: cours.lister_annees(self.conn, self.sec), lambda: cours.lister_cours(self.conn, self.sec),
                      lambda: cours.lister_classes(self.conn, self.sec)):
            with self.assertRaises(PermissionError):
                appel()

    def test_lecture_seule(self):
        self.donner("LECTURE")
        cours.lister_cours(self.conn, self.sec)
        for appel in (lambda: cours.ajouter_cours(self.conn, self.sec, {"libelle": "X", "code_niveau": "SEC"}),
                      lambda: cours.creer_annee(self.conn, self.sec, "2030-2031", "01/09/2030", "01/07/2031"),
                      lambda: cours.ouvrir_cours(self.conn, self.sec, self.annee, self.c7)):
            with self.assertRaises(PermissionError):
                appel()

    def test_ajout_sans_modification_ni_suppression(self):
        self.donner("LECTURE", "AJOUT")
        i = cours.ajouter_cours(self.conn, self.sec, {"libelle": "Latin", "code_niveau": "SEC", "heures_semaine": "2"})
        cours.ouvrir_cours(self.conn, self.sec, self.annee, self.c7)
        cc = cours.programme_classe(self.conn, self.sec, self.annee, self.c7)["cours"][0]["id"]
        cours.attribuer_professeur(self.conn, self.sec, [cc], self.prof)                       # cours sans professeur : Ajout suffit
        with self.assertRaises(PermissionError):
            cours.attribuer_professeur(self.conn, self.sec, [cc], self.prof2)                  # changer : Modification
        with self.assertRaises(PermissionError):
            cours.attribuer_professeur(self.conn, self.sec, [cc], "")
        with self.assertRaises(PermissionError):
            cours.modifier_heures(self.conn, self.sec, cc, "3")
        with self.assertRaises(PermissionError):
            cours.changer_activite_cours(self.conn, self.sec, i, False)
        with self.assertRaises(PermissionError):
            cours.retirer_cours_de_classe(self.conn, self.sec, cc)
        with self.assertRaises(PermissionError):
            cours.supprimer_cours(self.conn, self.sec, i)

    def test_journal_valide_et_structure_a_jour(self):
        self.cours("Latin")
        self.assertEqual(database.verifier_journal(self.conn), (True, None))
        self.assertIn("COURS_AJOUT", self.actions())
        self.assertIn("ANNEE_SCOLAIRE_CREEE", self.actions())


if __name__ == "__main__":
    unittest.main()

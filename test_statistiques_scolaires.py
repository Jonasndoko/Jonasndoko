"""Tests des statistiques et rapports scolaires (Direction des études, fonctionnalité 5) : moyennes, classement, taux, comparaison des
périodes, rapports enseignants et classes, droits, impression, page web.
Lancer :  python -m unittest test_statistiques_scolaires"""
import unittest

import app_web                      # noqa: E402
import notes                        # noqa: E402
import statistiques_scolaires as st   # noqa: E402
from controle_notes import ErreurControle   # noqa: E402
from test_controle_notes import Fixture, MDP   # noqa: E402


class Base3(Fixture):
    def stats(self, classe=None, cle=None):
        return st.statistiques(self.conn, self.dire, self.annee, cle or self.cle1, classe)

    def classe7(self, s):
        return next(k for k in s["classes"] if k["n_classe"] == self.c7)


class TestMoyennes(Base3):
    def test_moyenne_par_eleve_classe_et_cours(self):
        s = self.stats(self.c7)
        eleves = {e["matricule"]: e for e in s["eleves"]}
        self.assertEqual(eleves["0000/26"]["pct"], 62.5)          # (15 + 10) / 40
        self.assertEqual(eleves["0001/26"]["pct"], 40.0)          # 8 / 20 (le français n'a pas de point pour lui)
        self.assertEqual(eleves["0002/26"]["pct"], 60.0)
        self.assertEqual(self.classe7(s)["moyenne"], round((62.5 + 40 + 60) / 3, 1))
        maths = next(c for c in s["cours"] if c["id_cc"] == self.maths7)
        self.assertEqual((maths["moyenne"], maths["notes"], maths["attendues"]), (58.3, 3, 3))        # (75 + 40 + 60) / 3
        self.assertEqual(next(c for c in s["cours"] if c["id_cc"] == self.fr7)["moyenne"], 50.0)

    def test_ecole_et_portee_par_defaut(self):
        s = st.statistiques(self.conn, self.dire, self.annee)
        self.assertEqual(s["cle"], self.cle1)
        self.assertEqual(s["ecole"]["effectif"], 4)
        self.assertEqual(s["ecole"]["nb_classes"], 2)
        self.assertIsNotNone(s["ecole"]["moyenne"])

    def test_cours_filtres_et_eleves_seulement_avec_classe(self):
        s = st.statistiques(self.conn, self.dire, self.annee, self.cle1)
        self.assertEqual(s["eleves"], [])
        self.assertEqual(len(s["cours"]), 4)
        s = self.stats(self.c8)
        self.assertEqual({c["n_classe"] for c in s["cours"]}, {self.c8})
        self.assertEqual(len(s["classes"]), 2)                       # les totaux de l'école portent sur toutes les classes


class TestClassementEtTaux(Base3):
    def test_classement_selon_les_regles(self):
        s = self.stats(self.c7)
        self.assertEqual([e["matricule"] for e in s["eleves"]], ["0000/26", "0002/26", "0001/26"])
        self.assertEqual([e["rang"] for e in s["eleves"]], [1, 2, 3])

    def test_ex_aequo_meme_rang(self):
        notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0000/26": "15", "0001/26": "12", "0002/26": "12"})
        notes.enregistrer_points(self.conn, self.s2, self.fr7, self.per1, {"0000/26": "10", "0001/26": "10", "0002/26": "10"})
        s = self.stats(self.c7)
        self.assertEqual({e["matricule"]: e["rang"] for e in s["eleves"]}, {"0000/26": 1, "0001/26": 2, "0002/26": 2})        # 62,5 ; 55 ; 55
        s = self.stats(self.c7)
        notes.enregistrer_points(self.conn, self.s2, self.fr7, self.per1, {"0000/26": "5"})
        self.assertEqual(sorted(e["rang"] for e in self.stats(self.c7)["eleves"]), [1, 1, 3])         # 50 ; 55 ; 55 -> 55, 55, 50 : rangs 1, 1, 3

    def test_reussites_d_abord_puis_echecs_puis_attente(self):
        s = self.stats(self.c7)
        etats = [e["reussite"] for e in s["eleves"]]
        ordre = [0 if x is True else 1 if x is False else 2 for x in etats]
        self.assertEqual(ordre, sorted(ordre))

    def test_taux_reussite_et_echec(self):
        s = self.stats()
        k = self.classe7(s)
        decides = k["reussis"] + k["echecs"]
        if decides:
            self.assertEqual(round(k["taux_reussite"] + k["taux_echec"], 1), 100.0)
        e = s["ecole"]
        self.assertEqual(e["reussis"], sum(c["reussis"] for c in s["classes"]))
        self.assertEqual(e["echecs"], sum(c["echecs"] for c in s["classes"]))
        maths = next(c for c in s["cours"] if c["id_cc"] == self.maths7)
        self.assertEqual((maths["reussis"], maths["echecs"]), (2, 1))      # 75 % et 60 % réussissent, 40 % échoue

    def test_attente_comptee_a_part(self):
        s = self.stats()
        self.assertEqual(self.classe7(s)["attente"], self.classe7(s)["effectif"] - self.classe7(s)["reussis"] - self.classe7(s)["echecs"])


class TestComparaison(Base3):
    def setUp(self):
        super().setUp()
        notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per2, {"0000/26": "10", "0001/26": "9", "0002/26": "12"})
        notes.enregistrer_points(self.conn, self.s2, self.fr7, self.per2, {"0000/26": "14", "0001/26": "10", "0002/26": "13"})
        self.p2 = f"P{self.per2}"

    def test_classes_avec_evolution(self):
        c = st.comparaison(self.conn, self.dire, self.annee, "classes")
        cles = [x["cle"] for x in c["colonnes"]]
        self.assertIn(self.cle1, cles)
        self.assertIn(self.p2, cles)
        self.assertIn(f"S{self.sem1}", cles)
        ligne = next(l for l in c["lignes"] if l["libelle"].startswith("7"))
        v1, v2 = ligne["moyennes"][self.cle1]["valeur"], ligne["moyennes"][self.p2]["valeur"]
        self.assertIsNone(ligne["moyennes"][self.cle1]["delta"])
        self.assertEqual(ligne["moyennes"][self.p2]["delta"], round(v2 - v1, 1))
        self.assertEqual(ligne["tendance"], round(v2 - v1, 1))
        self.assertEqual(c["ecole"]["libelle"], "Ensemble de l'école")

    def test_cours_et_eleves_exigent_une_classe(self):
        with self.assertRaises(ErreurControle):
            st.comparaison(self.conn, self.dire, self.annee, "cours")
        c = st.comparaison(self.conn, self.dire, self.annee, "cours", self.c7)
        self.assertEqual({l["libelle"] for l in c["lignes"]}, {"Mathématiques", "Français"})
        maths = next(l for l in c["lignes"] if l["libelle"] == "Mathématiques")
        self.assertEqual(maths["moyennes"][self.p2]["valeur"], round((50 + 45 + 60) / 3, 1))
        e = st.comparaison(self.conn, self.dire, self.annee, "eleves", self.c7)
        k = next(l for l in e["lignes"] if l["sous"] == "0000/26")
        self.assertEqual(k["moyennes"][self.cle1]["valeur"], 62.5)
        self.assertEqual(k["moyennes"][self.p2]["valeur"], 60.0)            # (10 + 14) / 40
        self.assertEqual(k["moyennes"][self.p2]["delta"], -2.5)


class TestRapports(Base3):
    def test_performance_des_enseignants(self):
        s = self.stats()
        par = {e["matricule"]: e for e in s["enseignants"]}
        self.assertEqual((par[self.m1]["notes"], par[self.m1]["attendues"], par[self.m1]["taux_saisie"]), (3, 4, 75.0))      # maths 7ème + maths 8ème
        self.assertEqual((par[self.m2]["notes"], par[self.m2]["attendues"], par[self.m2]["taux_saisie"]), (1, 3, 33.3))
        self.assertEqual(par[self.m1]["nb_cours"], 2)
        self.assertEqual(par[self.m1]["classes"], ["7ème A", "8ème A"])
        self.assertEqual(s["enseignants"][0]["rang"], 1)

    def test_cours_sans_professeur_hors_rapport_enseignants(self):
        with self.conn:
            self.conn.execute("UPDATE COURS_CLASSE SET MATRICULE_PROF = NULL WHERE ID_CC = ?", (self.fr7,))
        s = self.stats()
        self.assertNotIn(self.m2, {e["matricule"] for e in s["enseignants"]})

    def test_classement_des_classes(self):
        s = self.stats()
        self.assertEqual([k["rang"] for k in s["classes"]], sorted(k["rang"] for k in s["classes"] if k["rang"]) + [None] * sum(1 for k in s["classes"] if k["rang"] is None))

    def test_examen_sans_objet_non_attendu(self):
        with self.conn:
            self.conn.execute("UPDATE COURS_CLASSE SET MAX_PERIODE = 100 WHERE ID_CC = ?", (self.fr7,))
        s = st.statistiques(self.conn, self.dire, self.annee, f"X{self.sem1}")
        self.assertEqual(next(c for c in s["cours"] if c["id_cc"] == self.fr7)["attendues"], 0)


class TestDroitsEtImpression(Base3):
    def test_droit_de_lecture_exige(self):
        for s in (self.prefet, self.perc):
            for f in (lambda: st.statistiques(self.conn, s, self.annee), lambda: st.comparaison(self.conn, s, self.annee),
                      lambda: st.impression(self.conn, s, "moyennes", self.annee)):
                with self.assertRaises(PermissionError):
                    f()

    def test_impression_et_journal(self):
        for vue in ("moyennes", "reussite", "rapports"):
            r = st.impression(self.conn, self.dire, vue, self.annee, self.cle1)
            self.assertEqual((r["vue"], r["annee"]), (vue, self.annee))
        r = st.impression(self.conn, self.dire, "classement", self.annee, self.cle1, self.c7)
        self.assertEqual(len(r["s"]["eleves"]), 3)
        r = st.impression(self.conn, self.dire, "comparaison", self.annee, "", self.c7, "cours")
        self.assertTrue(r["c"]["lignes"])
        self.assertTrue(self.conn.execute("SELECT 1 FROM JOURNAL WHERE ACTION = 'STATISTIQUES_IMPRIMEES'").fetchone())
        with self.assertRaises(ErreurControle):
            st.impression(self.conn, self.dire, "classement", self.annee, self.cle1)               # classe obligatoire
        with self.assertRaises(ErreurControle):
            st.impression(self.conn, self.dire, "inconnu", self.annee)

    def test_classe_inconnue_ou_periode_inconnue(self):
        with self.assertRaises(ErreurControle):
            st.statistiques(self.conn, self.dire, self.annee, self.cle1, 99999)
        s = st.statistiques(self.conn, self.dire, self.annee, "P99999")                             # clé inconnue : portée par défaut
        self.assertEqual(s["cle"], self.cle1)


class TestPageWeb(Base3):
    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])
        self.cl = self.app.test_client()
        self.assertEqual(self.cl.post("/connexion", data={"login": "dire1", "mdp": MDP}).status_code, 302)
        self.base = "/m/etudes_discipline/direction_etudes"

    def test_onglet_et_vues(self):
        self.assertIn("Statistiques et rapports scolaires", self.cl.get(self.base).get_data(as_text=True))
        for vue in ("moyennes", "classement", "reussite", "comparaison", "rapports"):
            r = self.cl.get(f"{self.base}?f=statistiques&vue={vue}")
            self.assertEqual(r.status_code, 200, vue)
        h = self.cl.get(f"{self.base}?f=statistiques&vue=moyennes&classe={self.c7}&cle={self.cle1}").get_data(as_text=True)
        for mot in ("Moyenne par classe", "Moyenne par cours", "Moyenne par élève", "Kasongo", "Imprimer"):
            self.assertIn(mot, h)
        h = self.cl.get(f"{self.base}?f=statistiques&vue=classement&classe={self.c7}&cle={self.cle1}").get_data(as_text=True)
        self.assertIn("Règles de l'école", h)
        h = self.cl.get(f"{self.base}?f=statistiques&vue=rapports&cle={self.cle1}").get_data(as_text=True)
        self.assertIn("performance des enseignants", h)
        h = self.cl.get(f"{self.base}?f=statistiques&vue=comparaison&niveau=cours").get_data(as_text=True)
        self.assertIn("Choisissez une classe", h)
        h = self.cl.get(f"{self.base}?f=statistiques&vue=comparaison&niveau=eleves&classe={self.c7}").get_data(as_text=True)
        self.assertIn("Kasongo", h)

    def test_impression(self):
        for url in (f"vue=moyennes&annee={self.annee}&cle={self.cle1}", f"vue=reussite&annee={self.annee}", f"vue=rapports&annee={self.annee}",
                    f"vue=classement&annee={self.annee}&classe={self.c7}&cle={self.cle1}", f"vue=comparaison&annee={self.annee}&niveau=classes"):
            r = self.cl.get(f"{self.base}/statistiques/impression?{url}")
            self.assertEqual(r.status_code, 200, url)
            h = r.get_data(as_text=True)
            self.assertIn("window.print()", h)
            self.assertIn("Imprimé le", h)
        self.assertEqual(self.cl.get(f"{self.base}/statistiques/impression?vue=bidon").status_code, 404)
        self.assertEqual(self.cl.get(f"{self.base}/statistiques/impression?vue=classement&annee={self.annee}").status_code, 404)

    def test_autres_postes_refuses(self):
        for login in ("prefet1", "perc1"):
            cl = self.app.test_client()
            cl.post("/connexion", data={"login": login, "mdp": MDP})
            for url in ("?f=statistiques", "/statistiques/impression?vue=moyennes"):
                self.assertEqual(cl.get(self.base + url).status_code, 403, (login, url))


if __name__ == "__main__":
    unittest.main()

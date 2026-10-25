"""Tests des fonctionnalités 5 (Consultation de la discipline) et 6 (Consultation des études) de la Préfecture.
Lancer :  python -m unittest test_prefecture_v58"""
import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web         # noqa: E402
import config          # noqa: E402
import notes           # noqa: E402
import prefecture      # noqa: E402
from prefecture import ErreurPrefecture   # noqa: E402
from test_notes import MDP                # noqa: E402
from test_prefecture_v57 import Fixture   # noqa: E402

TABLES_LECTURE_SEULE = ("PRESENCE_ELEVE", "CONDUITE", "NOTE", "EVALUATION", "DECISION_PREFET", "RAPPORT_RESPONSABLE", "PAIEMENT")


class Base58(Fixture):
    def absent(self, matricule, jour, id_cc=None, statut="A"):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO PRESENCE_ELEVE (ID_CC, DATE_COURS, MATRICULE, STATUT, DATE_MODIF, MODIFIE_PAR) "
                              "VALUES (?,?,?,?,'2026-09-10T00:00:00','essai')", (id_cc or self.maths7, jour.isoformat(), matricule, statut))

    def points(self, per, valeurs, maximum=30):
        notes.definir_maximum(self.conn, self.s1, self.maths7, per, maximum)
        notes.enregistrer_points(self.conn, self.s1, self.maths7, per, valeurs)

    def compte(self):
        return {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES_LECTURE_SEULE}


class TestDiscipline(Base58):
    def test_les_six_fonctionnalites(self):
        self.assertEqual([c for c, _t, _d in config.FONCTIONNALITES_PREFECTURE],
                         ["tableau", "suivi", "finances", "decisions", "discipline", "etudes", "proclamation", "documents", "renvois", "listes"])
        titres = {c: t for c, t, _d in config.FONCTIONNALITES_PREFECTURE}
        self.assertEqual(titres["discipline"], "Consultation de la discipline")
        self.assertEqual(titres["etudes"], "Consultation des études")

    def test_droits_et_section(self):
        for appel in (lambda: prefecture.consultation_discipline(self.conn, self.secr), lambda: prefecture.discipline_eleve(self.conn, self.secr, "0000/26"),
                      lambda: prefecture.consultation_etudes(self.conn, self.secr), lambda: prefecture.bulletin_eleve(self.conn, self.secr, "0000/26")):
            with self.assertRaises(PermissionError):
                appel()
        for poste in (self.dire, self.dird):                 # les directions n'ont pas la Préfecture
            with self.assertRaises(PermissionError):
                prefecture.consultation_discipline(self.conn, poste)

    def test_vue_d_ensemble_absences_et_conduite(self):
        aujourd = date.today()
        self.absent("0000/26", aujourd)                                         # absent aujourd'hui
        self.absent("0001/26", aujourd, statut="P")                           # présent aujourd'hui
        for i in range(1, 4):                                                    # 0002 : 3 journées d'absence récentes
            self.absent("0002/26", aujourd - timedelta(days=i))
        self.absent("0002/26", aujourd - timedelta(days=2), self.fr7)           # même journée, autre cours : une seule journée
        notes.enregistrer_conduite(self.conn, self.s1, self.maths7, self.per1, "0000/26", "M")
        d = prefecture.consultation_discipline(self.conn, self.prefet)
        self.assertEqual(d["annee"], self.annee)
        self.assertTrue(d["annee_en_cours"])
        self.assertEqual(d["resume"]["eleves"], 4)                             # l'élève du primaire n'est pas compté
        self.assertEqual((d["resume"]["presents"], d["resume"]["absents"]), (1, 1))
        self.assertEqual(d["resume"]["absences_repetees"], 1)
        lignes = {e["matricule"]: e for e in d["eleves"]}
        self.assertNotIn("0100/26", lignes)
        self.assertEqual(lignes["0000/26"]["jour"], "A")
        self.assertEqual(lignes["0000/26"]["conduite"], "M")
        self.assertEqual(lignes["0000/26"]["conduite_libelle"], "Mauvaise")
        self.assertEqual(lignes["0002/26"]["absences_annee"], 3)
        self.assertTrue(lignes["0002/26"]["repetee"])
        self.assertEqual(lignes["0001/26"]["conduite"], "")

    def test_filtres_et_recherche(self):
        aujourd = date.today()
        self.absent("0000/26", aujourd)
        for i in range(1, 4):
            self.absent("0002/26", aujourd - timedelta(days=i))
        absents = prefecture.consultation_discipline(self.conn, self.prefet, filtre="absents")
        self.assertEqual([e["matricule"] for e in absents["eleves"]], ["0000/26"])
        self.assertEqual(absents["resume"]["eleves"], 4)                       # le résumé reste celui de tous les élèves
        repetees = prefecture.consultation_discipline(self.conn, self.prefet, filtre="repetees")
        self.assertEqual([e["matricule"] for e in repetees["eleves"]], ["0002/26"])
        self.assertEqual(prefecture.consultation_discipline(self.conn, self.prefet, filtre="n'importe quoi")["filtre"], "")
        classe8 = prefecture.consultation_discipline(self.conn, self.prefet, n_classe=self.c8)
        self.assertEqual([e["matricule"] for e in classe8["eleves"]], ["0009/26"])
        self.assertEqual([e["matricule"] for e in prefecture.consultation_discipline(self.conn, self.prefet, texte="zola")["eleves"]], ["0002/26"])
        with self.assertRaises(ErreurPrefecture):
            prefecture.consultation_discipline(self.conn, self.prefet, n_classe="abc")
        with self.assertRaises(ErreurPrefecture):
            prefecture.consultation_discipline(self.conn, self.prefet, annee="1999-2000")

    def test_decisions_disciplinaires_et_rapports(self):
        self.decision()                                                          # disciplinaire, élève 0001
        prefecture.enregistrer_decision(self.conn, self.prefet, date.today().isoformat(), "pedagogique", "Autre sujet")
        prefecture.deposer_rapport(self.conn, self.dird, "direction_discipline", "Bilan de la semaine", "Trois absences injustifiées.")
        prefecture.deposer_rapport(self.conn, self.dire, "direction_etudes", "Rapport des études", "Résultats en baisse.")
        d = prefecture.consultation_discipline(self.conn, self.prefet)
        self.assertEqual([x["objet"] for x in d["decisions"]], ["Renvoi temporaire"])
        self.assertEqual(d["resume"]["decisions"], 1)
        self.assertEqual([r["titre"] for r in d["rapports"]], ["Bilan de la semaine"])        # seulement la Direction de discipline

    def test_discipline_d_un_eleve(self):
        aujourd = date.today()
        self.absent("0001/26", aujourd - timedelta(days=1))
        self.absent("0001/26", aujourd - timedelta(days=1), self.fr7)
        self.absent("0001/26", aujourd - timedelta(days=2), statut="P")
        notes.enregistrer_conduite(self.conn, self.s1, self.maths7, self.per1, "0001/26", "B")
        notes.enregistrer_conduite(self.conn, self.s2, self.fr7, self.per1, "0001/26", "TB")      # égalité : la plus faible (B)
        self.decision()
        d = prefecture.discipline_eleve(self.conn, self.prefet, "0001/26")
        self.assertEqual(d["annee"], self.annee)
        self.assertEqual((d["jours_presents"], d["jours_absents"]), (1, 1))
        self.assertEqual(len(d["absences"]), 1)
        self.assertEqual(d["absences"][0]["cours"], ["Français", "Mathématiques"])
        premiere = d["conduite"][0]
        self.assertEqual((premiere["cote"], premiere["libelle"], premiere["nb_cours"]), ("B", "Bonne", 2))
        self.assertEqual(len(d["conduite"]), 4)
        self.assertEqual([x["objet"] for x in d["decisions"]], ["Renvoi temporaire"])

    def test_eleve_du_primaire_ou_inconnu(self):
        with self.assertRaises(PermissionError):
            prefecture.discipline_eleve(self.conn, self.prefet, "0100/26")
        with self.assertRaises(ErreurPrefecture):
            prefecture.discipline_eleve(self.conn, self.prefet, "9999/26")

    def test_consultation_seule_et_journal(self):
        self.absent("0000/26", date.today())
        avant = self.compte()
        prefecture.consultation_discipline(self.conn, self.prefet)
        prefecture.discipline_eleve(self.conn, self.prefet, "0000/26")
        self.assertEqual(self.compte(), avant)
        self.assertTrue({"PREFECTURE_DISCIPLINE_CONSULTEE", "PREFECTURE_DISCIPLINE_ELEVE_CONSULTEE"} <= set(self.actions()))


class TestEtudes(Base58):
    def remplir(self):
        """Période 1, Maths /30 : Kasongo 24, Amisi 18, Zola 9 (Français non saisi)."""
        self.points(self.per1, {"0000/26": "24", "0001/26": "18", "0002/26": "9"})

    def test_vue_par_classe(self):
        e = prefecture.consultation_etudes(self.conn, self.prefet)
        self.assertEqual(e["annee"], self.annee)
        self.assertIsNone(e["detail"])
        self.assertEqual({k["classe"] for k in e["classes"]}, {"7ème A", "8ème A"})      # pas la classe du primaire
        sept = next(k for k in e["classes"] if k["classe"] == "7ème A")
        self.assertEqual((sept["effectif"], sept["cours"], sept["titulaire"]), (3, 2, ""))
        self.assertTrue(sept["calendrier"])
        self.assertGreater(sept["alertes"], 0)                                       # des points manquent encore

    def test_detail_d_une_classe_dans_l_ordre_des_resultats(self):
        self.remplir()
        e = prefecture.consultation_etudes(self.conn, self.prefet, n_classe=self.c7, cle=f"P{self.per1}")
        d = e["detail"]
        self.assertEqual((d["classe"], d["cle"], d["effectif"]), ("7ème A", f"P{self.per1}", 3))
        self.assertEqual([x["nom_complet"].split()[0] for x in d["eleves"]], ["Kasongo", "Amisi", "Zola"])
        self.assertEqual([x["rang"] for x in d["eleves"]], [1, 2, 3])
        self.assertEqual(d["eleves"][0]["pct"], 80.0)
        self.assertTrue(d["eleves"][0]["reussite"])
        self.assertFalse(d["eleves"][2]["reussite"])
        maths = next(c for c in d["cours"] if c["libelle"] == "Mathématiques")
        self.assertEqual((maths["notes"], maths["moyenne"]), (3, 56.7))
        self.assertTrue(maths["professeur"])
        self.assertGreater(d["nb_alertes"], 0)
        self.assertEqual(len(d["portees"]), 9)                                        # 4 périodes, 2 examens, 2 semestres et l'année
        defaut = prefecture.consultation_etudes(self.conn, self.prefet, n_classe=self.c7, cle="inconnue")["detail"]
        self.assertEqual(defaut["cle"], "A")                                          # clé inconnue : l'année

    def test_classe_du_primaire_ou_inconnue(self):
        with self.assertRaises(PermissionError):
            prefecture.consultation_etudes(self.conn, self.prefet, n_classe=self.cp)
        with self.assertRaises(ErreurPrefecture):
            prefecture.consultation_etudes(self.conn, self.prefet, n_classe=99999)
        with self.assertRaises(ErreurPrefecture):
            prefecture.consultation_etudes(self.conn, self.prefet, n_classe="x")

    def test_bulletin_d_un_eleve(self):
        self.remplir()
        b = prefecture.bulletin_eleve(self.conn, self.prefet, "0001/26")
        self.assertEqual((b["classe"], b["annee"], b["effectif"]), ("7ème A", self.annee, 3))
        self.assertEqual([c["libelle"] for c in b["cours"]], ["Français", "Mathématiques"])
        maths = next(c for c in b["cours"] if c["libelle"] == "Mathématiques")
        cle = f"P{self.per1}"
        self.assertEqual((maths["cotes"][cle]["obtenu"], maths["cotes"][cle]["max"]), (18, 30))
        self.assertEqual((b["totaux"][cle]["pct"], b["totaux"][cle]["rang"]), (60.0, 2))
        self.assertEqual(b["colonnes"][0]["cle"], cle)

    def test_bulletin_refuse_pour_le_primaire_ou_inconnu(self):
        with self.assertRaises(PermissionError):
            prefecture.bulletin_eleve(self.conn, self.prefet, "0100/26")
        with self.assertRaises(ErreurPrefecture):
            prefecture.bulletin_eleve(self.conn, self.prefet, "9999/26")

    def test_consultation_seule_et_journal(self):
        self.remplir()
        avant = self.compte()
        prefecture.consultation_etudes(self.conn, self.prefet)
        prefecture.consultation_etudes(self.conn, self.prefet, n_classe=self.c7)
        prefecture.bulletin_eleve(self.conn, self.prefet, "0000/26")
        self.assertEqual(self.compte(), avant)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM TITULAIRE_CLASSE").fetchone()[0], 0)
        self.assertTrue({"PREFECTURE_ETUDES_CONSULTEES", "PREFECTURE_BULLETIN_CONSULTE"} <= set(self.actions()))


class TestWeb58(Base58):
    def setUp(self):
        super().setUp()
        chemin = self.conn.execute("PRAGMA database_list").fetchone()[2]
        self.app = app_web.creer_app(chemin)
        self.clients = {}
        for login in ("prefet1", "dire1", "dird1", "secr1", "admin1"):
            cl = self.app.test_client()
            self.assertEqual(cl.post("/connexion", data={"login": login, "mdp": MDP}).status_code, 302)
            self.clients[login] = cl

    def page(self, login, url):
        r = self.clients[login].get(url)
        return r.status_code, r.get_data(as_text=True)

    def test_la_page_a_six_fonctionnalites(self):
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture")
        self.assertEqual(code, 200)
        for texte in ("Consultation de la discipline", "Consultation des études"):
            self.assertIn(f"<span>{texte}</span>", html)                  # boutons du module Préfecture (plus d'onglets numérotés)

    def test_page_discipline(self):
        self.absent("0000/26", date.today())
        self.decision()
        prefecture.deposer_rapport(self.conn, self.dird, "direction_discipline", "Bilan de la semaine", "Trois absences injustifiées.")
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=discipline")
        self.assertEqual(code, 200)
        for texte in ("Consultation seule", "Kasongo", "Absent", "Renvoi temporaire", "Bilan de la semaine", "justificatifs"):
            self.assertIn(texte, html)
        self.assertNotIn("Petit", html)                                               # l'élève du primaire
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=discipline&filtre=absents&q=zola")
        self.assertEqual(code, 200)
        self.assertIn("Aucun élève trouvé", html)
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=discipline&eleve=0001%2F26")
        self.assertEqual(code, 200)
        for texte in ("Amisi", "Conduite", "Décisions disciplinaires le concernant", "Renvoi temporaire"):
            self.assertIn(texte, html)
        self.assertEqual(self.page("prefet1", "/m/etudes_discipline/prefecture?f=discipline&eleve=0100%2F26")[0], 403)
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=discipline&eleve=9999%2F26")
        self.assertEqual(code, 200)
        self.assertIn("Élève introuvable", html)

    def test_page_etudes_et_bulletin(self):
        self.points(self.per1, {"0000/26": "24", "0001/26": "18", "0002/26": "9"})
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=etudes")
        self.assertEqual(code, 200)
        for texte in ("Consultation seule", "7ème A", "8ème A"):
            self.assertIn(texte, html)
        self.assertNotIn("3ème prim", html)
        code, html = self.page("prefet1", f"/m/etudes_discipline/prefecture?f=etudes&classe={self.c7}&cle=P{self.per1}")
        self.assertEqual(code, 200)
        for texte in ("Kasongo", "80.0 %", "Situation pédagogique", "Mathématiques", "Bulletin"):
            self.assertIn(texte, html)
        self.assertEqual(self.page("prefet1", f"/m/etudes_discipline/prefecture?f=etudes&classe={self.cp}")[0], 403)
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=etudes&eleve=0001%2F26")
        self.assertEqual(code, 200)
        for texte in ("Bulletin · Amisi", "18 / 30", "60.0 %", "aucune note ne se saisit"):
            self.assertIn(texte, html)
        self.assertEqual(self.page("prefet1", "/m/etudes_discipline/prefecture?f=etudes&eleve=0100%2F26")[0], 403)

    def test_pages_refusees_aux_autres_postes(self):
        for poste in ("secr1", "dire1", "dird1"):
            for f in ("discipline", "etudes"):
                self.assertEqual(self.page(poste, f"/m/etudes_discipline/prefecture?f={f}")[0], 403)
        for f in ("discipline", "etudes"):
            self.assertEqual(self.page("admin1", f"/m/etudes_discipline/prefecture?f={f}")[0], 200)

    def test_aucun_formulaire_d_ecriture_dans_les_deux_pages(self):
        for f in ("discipline", "etudes"):
            html = self.page("prefet1", f"/m/etudes_discipline/prefecture?f={f}")[1]
            self.assertNotIn('action="/m/etudes_discipline', html)               # seul le bouton Déconnexion de l'en-tête est un POST


if __name__ == "__main__":
    unittest.main()

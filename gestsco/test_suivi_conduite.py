"""Tests de la Direction de discipline > Suivi de la conduite : cotes des professeurs, observations, comportements, incidents et mentions
(règlement scolaire), solde de conduite, historique d'un élève, annulation, droits, journal.
Lancer :  python -m unittest test_suivi_conduite"""
import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web                      # noqa: E402
import audit                        # noqa: E402
import config                       # noqa: E402
import droits                       # noqa: E402
import suivi_conduite as sc         # noqa: E402
from suivi_conduite import ErreurConduite   # noqa: E402
from test_notes import MDP                  # noqa: E402
from test_prefecture_v57 import Fixture     # noqa: E402


def journal(conn, action):
    return [l["DETAIL"] for l in conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = ? ORDER BY ID_LOG", (action,))]


class Fix(Fixture):
    """Classe 7ème A : 0000 (Kasongo), 0001 (Amisi), 0002 (Zola) ; 8ème A : 0009 ; primaire : 0100.
    Cotes de la 1re période : Kasongo B en maths et AB en français ; Amisi M en maths et P en français ; Zola : aucune."""

    def setUp(self):
        super().setUp()
        with self.conn:
            for cc, m, cote in ((self.maths7, "0000/26", "B"), (self.fr7, "0000/26", "AB"), (self.maths7, "0001/26", "M"), (self.fr7, "0001/26", "P")):
                self.conn.execute("INSERT INTO CONDUITE (ID_CC, ID_PER, MATRICULE, COTE, DATE_MODIF) VALUES (?,?,?,?,?)", (cc, self.per1, m, cote, "2026-10-01T10:00:00"))

    def donner(self, session, droit):
        d = droits.droits_utilisateur(self.conn, session.id_user) | {("direction_discipline", droit)}
        droits.remplacer_droits(self.conn, session.id_user, d)
        self.conn.commit()

    def ajouter(self, matricule="0001/26", genre="INCIDENT", code="BAGARRE", description="Bagarre dans la cour avec un camarade", **plus):
        champs = dict(annee=self.annee, matricule=matricule, genre=genre, code=code, date_texte=date.today().isoformat(), description=description)
        champs.update(plus)
        return sc.enregistrer(self.conn, self.dird, **champs)

    def total(self, matricule="0001/26"):
        return sc.historique_eleve(self.conn, self.dird, matricule, self.annee)["totaux"]


class TestReglement(unittest.TestCase):
    def test_le_reglement_est_coherent(self):
        codes = [a["code"] for a in sc.reglement()]
        self.assertEqual(len(codes), len(set(codes)))
        for a in sc.reglement():
            self.assertIn(a["genre"], ("MENTION", "COMPORTEMENT", "INCIDENT"))
            self.assertIn(a["nature"], ("POSITIF", "NEGATIF"))
            self.assertIn(a["gravite"], config.LIBELLE_GRAVITES)
            self.assertEqual(a["gravite"] == "", a["genre"] == "MENTION")
            self.assertEqual(a["points"] > 0, a["nature"] == "POSITIF", a["code"])
        self.assertTrue({a["nature"] for a in sc.reglement() if a["genre"] == "MENTION"} == {"POSITIF", "NEGATIF"})

    def test_la_fonctionnalite_est_declaree(self):
        cles = [c for c, _t, _d in config.FONCTIONNALITES_DIRECTIONS["direction_discipline"]]
        self.assertEqual(cles, ["presences", "conduite", "convocation", "listes", "rapport"])


class TestCotesDesProfesseurs(Fix):
    def test_tableau_par_periode(self):
        r = sc.observations_professeurs(self.conn, self.dird, self.annee, self.c7, self.per1)
        self.assertEqual([c["cours"] for c in r["cours"]], ["Français", "Mathématiques"])
        par = {e["matricule"]: e for e in r["eleves"]}
        self.assertEqual(par["0000/26"]["cotes"], ["AB", "B"])
        self.assertEqual((par["0000/26"]["retenue"], par["0000/26"]["nb_cotes"]), ("AB", 2))       # à égalité, la plus faible
        self.assertEqual((par["0001/26"]["retenue"], par["0001/26"]["a_surveiller"]), ("M", True))
        self.assertEqual((par["0002/26"]["retenue"], par["0002/26"]["nb_cotes"]), ("", 0))
        self.assertEqual((r["nb_cotes_total"], r["a_surveiller"]), (4, 1))
        self.assertNotIn("0009/26", par)                                                           # autre classe

    def test_tableau_toutes_periodes(self):
        r = sc.observations_professeurs(self.conn, self.dird, self.annee, self.c7)
        par = {e["matricule"]: e for e in r["eleves"]}
        self.assertEqual([p["cote"] for p in par["0000/26"]["periodes"]], ["AB", "", "", "", "", ""][:len(r["periodes"])])
        self.assertEqual(par["0001/26"]["periodes"][0]["cote"], "M")

    def test_cas_refuses(self):
        with self.assertRaises(ErreurConduite):
            sc.observations_professeurs(self.conn, self.dird, self.annee, self.cp)                 # classe du primaire
        with self.assertRaises(ErreurConduite):
            sc.observations_professeurs(self.conn, self.dird, self.annee, self.c7, 99999)

    def test_les_cotes_ne_sont_jamais_modifiees(self):
        avant = self.conn.execute("SELECT * FROM CONDUITE ORDER BY ID_CC, MATRICULE").fetchall()
        sc.observations_professeurs(self.conn, self.dird, self.annee, self.c7, self.per1)
        sc.historique_eleve(self.conn, self.dird, "0001/26", self.annee)
        self.assertEqual([tuple(x) for x in avant], [tuple(x) for x in self.conn.execute("SELECT * FROM CONDUITE ORDER BY ID_CC, MATRICULE").fetchall()])


class TestEnregistrer(Fix):
    def test_incident_et_points_du_reglement(self):
        r = self.ajouter()
        self.assertEqual((r["genre"], r["nature"], r["points"]), ("INCIDENT", "NEGATIF", -4))
        h = sc.historique_eleve(self.conn, self.dird, "0001/26", self.annee)
        x = h["entrees"][0]
        self.assertEqual((x["libelle"], x["gravite"], x["points"], x["par"], x["annulee"]), ("Bagarre", "GRAVE", -4, "dird1", False))
        self.assertEqual((h["totaux"]["incidents"], h["totaux"]["solde"], h["classe"]), (1, -4, "7ème A"))

    def test_comportement_mention_et_observation(self):
        self.ajouter(genre="COMPORTEMENT", code="TELEPHONE", description="Téléphone sorti pendant le cours")
        self.ajouter(genre="MENTION", code="FELICITATIONS", description="Premier de la classe en conduite")
        self.ajouter(genre="MENTION", code="AVERTISSEMENT", description="Retards après la récréation")
        self.ajouter(genre="OBSERVATION", code="", nature="POSITIF", description="Aide ses camarades en difficulté")
        t = self.total()
        self.assertEqual((t["comportements"], t["mentions_positives"], t["mentions_negatives"], t["observations"]), (1, 1, 1, 1))
        self.assertEqual(t["solde"], -2 + 3 - 1 + 0)
        self.assertEqual((t["positives"], t["negatives"]), (2, 2))

    def test_observation_neutre_sans_points(self):
        self.ajouter(genre="OBSERVATION", code="", nature="NEUTRE", description="Entretien avec la mère de l'élève")
        x = sc.historique_eleve(self.conn, self.dird, "0001/26", self.annee)["entrees"][0]
        self.assertEqual((x["points"], x["nature"], x["libelle"]), (0, "NEUTRE", "Observation disciplinaire"))

    def test_validations(self):
        for champs in (dict(genre=""), dict(genre="AUTRE"), dict(code="NEXISTEPAS"), dict(code="FELICITATIONS"),          # code d'un autre genre
                       dict(description=""), dict(description="abc"), dict(description="x" * 1001), dict(lieu="x" * 101), dict(mesure="x" * 301),
                       dict(date_texte=(date.today() + timedelta(days=1)).isoformat()), dict(date_texte="01/01/2020"), dict(date_texte="pas une date"),
                       dict(genre="OBSERVATION", code="", nature=""), dict(genre="OBSERVATION", code="", nature="FORT"), dict(matricule="9999/99")):
            with self.assertRaises(ErreurConduite, msg=str(champs)):
                self.ajouter(**champs)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CONDUITE_OBSERVATION").fetchone()[0], 0)

    def test_eleve_du_primaire_ou_desactive_ou_autre_annee(self):
        with self.assertRaises(PermissionError):
            self.ajouter(matricule="0100/26")
        with self.assertRaises(ErreurConduite):
            self.ajouter(annee="2025-2026")
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET ACTIF = 0 WHERE MATRICULE = '0002/26'")
        with self.assertRaises(ErreurConduite):
            self.ajouter(matricule="0002/26")

    def test_la_classe_est_celle_de_l_inscription(self):
        self.ajouter(matricule="0009/26")
        self.assertEqual(self.conn.execute("SELECT N_CLASSE FROM CONDUITE_OBSERVATION").fetchone()[0], self.c8)

    def test_le_reglement_modifie_ne_change_pas_l_historique(self):
        self.ajouter()
        ancien = config.REGLEMENT_CONDUITE
        try:
            config.REGLEMENT_CONDUITE = tuple(("BAGARRE", "Bagarre (nouvelle règle)", "INCIDENT", "NEGATIF", "MOYENNE", -1) if a[0] == "BAGARRE" else a for a in ancien)
            x = sc.historique_eleve(self.conn, self.dird, "0001/26", self.annee)["entrees"][0]
            self.assertEqual((x["libelle"], x["points"], x["gravite"]), ("Bagarre", -4, "GRAVE"))
        finally:
            config.REGLEMENT_CONDUITE = ancien

    def test_a_suivre(self):
        self.assertFalse(self.total()["a_suivre"])
        self.ajouter(genre="COMPORTEMENT", code="RETARD", description="Arrive en retard chaque matin")
        self.ajouter(genre="COMPORTEMENT", code="TENUE", description="Chemise hors du pantalon")
        self.assertFalse(self.total()["a_suivre"])                                  # 2 entrées négatives, solde -2
        self.ajouter(genre="COMPORTEMENT", code="BAVARDAGE", description="Bavardage répété en classe")
        self.assertTrue(self.total()["a_suivre"])                                   # 3 entrées négatives
        self.ajouter(matricule="0002/26")                                           # une bagarre : -4, une seule entrée
        self.assertFalse(self.total("0002/26")["a_suivre"])
        self.ajouter(matricule="0002/26", code="VIOLENCE", description="Menaces contre un élève")
        self.assertTrue(self.total("0002/26")["a_suivre"])                          # solde -9


class TestAnnulation(Fix):
    def test_annuler_garde_l_entree_et_retire_les_points(self):
        self.ajouter()
        i = self.conn.execute("SELECT ID_OBS FROM CONDUITE_OBSERVATION").fetchone()[0]
        self.donner(self.dird, "MODIFICATION")
        with self.assertRaises(ErreurConduite):
            sc.annuler(self.conn, self.dird, i, "")                                  # motif obligatoire
        sc.annuler(self.conn, self.dird, i, "Enregistré pour le mauvais élève")
        h = sc.historique_eleve(self.conn, self.dird, "0001/26", self.annee)
        self.assertEqual((len(h["entrees"]), h["entrees"][0]["annulee"], h["totaux"]["solde"], h["totaux"]["incidents"], h["totaux"]["annulees"]), (1, True, 0, 0, 1))
        self.assertEqual((h["entrees"][0]["annulee_par"], h["entrees"][0]["motif_annulation"]), ("dird1", "Enregistré pour le mauvais élève"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CONDUITE_OBSERVATION").fetchone()[0], 1)           # rien n'est supprimé
        with self.assertRaises(ErreurConduite):
            sc.annuler(self.conn, self.dird, i, "encore")                            # déjà annulée
        with self.assertRaises(ErreurConduite):
            sc.annuler(self.conn, self.dird, 99999, "motif")

    def test_annuler_exige_le_droit_modification(self):
        self.ajouter()
        i = self.conn.execute("SELECT ID_OBS FROM CONDUITE_OBSERVATION").fetchone()[0]
        with self.assertRaises(PermissionError):
            sc.annuler(self.conn, self.dird, i, "motif")
        self.assertEqual(self.conn.execute("SELECT ANNULE_LE FROM CONDUITE_OBSERVATION").fetchone()[0], None)

    def test_on_n_annule_pas_une_autre_annee(self):
        self.ajouter()
        with self.conn:
            self.conn.execute("INSERT INTO ANNEE_SCO (ANNEESCO, EN_COURS) VALUES ('2027-2028', 1)")
            self.conn.execute("UPDATE ANNEE_SCO SET EN_COURS = 0 WHERE ANNEESCO = ?", (self.annee,))
        self.donner(self.dird, "MODIFICATION")
        with self.assertRaises(ErreurConduite):
            sc.annuler(self.conn, self.dird, self.conn.execute("SELECT ID_OBS FROM CONDUITE_OBSERVATION").fetchone()[0], "motif")


class TestVuesEtHistorique(Fix):
    def test_apercu_par_classe_et_par_eleve(self):
        self.ajouter()
        self.ajouter(matricule="0000/26", genre="MENTION", code="ENCOURAGEMENTS", description="Progrès constants")
        r = sc.apercu(self.conn, self.dird, self.annee)
        c7 = next(c for c in r["classes"] if c["n_classe"] == self.c7)
        self.assertEqual((c7["effectif"], c7["incidents"], c7["mentions_positives"], c7["solde"], c7["a_suivre_nb"]), (3, 1, 1, -2, 0))
        self.assertEqual((r["totaux"]["effectif"], r["totaux"]["incidents"]), (4, 1))
        d = sc.apercu(self.conn, self.dird, self.annee, self.c7)
        self.assertEqual(sorted(e["matricule"] for e in d["eleves"]), ["0000/26", "0001/26", "0002/26"])
        self.assertEqual(next(e for e in d["eleves"] if e["matricule"] == "0001/26")["solde"], -4)

    def test_registre_et_filtres(self):
        self.ajouter()
        self.ajouter(matricule="0000/26", genre="MENTION", code="FELICITATIONS", description="Meilleure conduite du mois")
        self.ajouter(matricule="0009/26", genre="COMPORTEMENT", code="TELEPHONE", description="Téléphone en classe")
        tout = sc.registre(self.conn, self.dird, self.annee)
        self.assertEqual(tout["total"], 3)
        self.assertEqual(tout["entrees"][0]["nom_complet"] != "", True)
        self.assertEqual([x["classe"] for x in sc.registre(self.conn, self.dird, self.annee, self.c8)["entrees"]], ["8ème A"])
        self.assertEqual(sc.registre(self.conn, self.dird, self.annee, genre="MENTION")["total"], 1)
        self.assertEqual(sc.registre(self.conn, self.dird, self.annee, nature="NEGATIF")["total"], 2)
        self.assertEqual(sc.registre(self.conn, self.dird, self.annee, debut_texte=(date.today() + timedelta(days=-1)).isoformat(),
                                     fin_texte=(date.today() + timedelta(days=-1)).isoformat())["total"], 0)
        with self.assertRaises(ErreurConduite):
            sc.registre(self.conn, self.dird, self.annee, debut_texte="2026-10-10", fin_texte="2026-10-01")

    def test_registre_cache_les_annulees_sauf_demande(self):
        self.ajouter()
        self.donner(self.dird, "MODIFICATION")
        sc.annuler(self.conn, self.dird, self.conn.execute("SELECT ID_OBS FROM CONDUITE_OBSERVATION").fetchone()[0], "Erreur de saisie")
        self.assertEqual(sc.registre(self.conn, self.dird, self.annee)["total"], 0)
        r = sc.registre(self.conn, self.dird, self.annee, annulees=True)
        self.assertEqual((r["total"], r["entrees"][0]["annulee"], r["totaux"]["incidents"]), (1, True, 0))

    def test_historique_complet_d_un_eleve(self):
        self.ajouter()
        self.decision()                                                              # décision du Préfet (renvoi temporaire) pour 0001/26
        h = sc.historique_eleve(self.conn, self.dird, "0001/26")
        self.assertEqual(h["annee"], self.annee)
        self.assertEqual([x["objet"] for x in h["decisions"]], ["Renvoi temporaire"])
        p1 = h["conduite"][0]
        self.assertEqual((p1["cote"], p1["a_surveiller"], sorted(d["cote"] for d in p1["detail"])), ("M", True, ["M", "P"]))
        self.assertEqual([(r["annee"], r["incidents"], r["solde"]) for r in h["resume"]], [(self.annee, 1, -4)])
        self.assertTrue(h["modifiable"])
        with self.assertRaises(PermissionError):
            sc.historique_eleve(self.conn, self.dird, "0100/26")
        with self.assertRaises(ErreurConduite):
            sc.historique_eleve(self.conn, self.dird, "9999/99")
        with self.assertRaises(ErreurConduite):
            sc.historique_eleve(self.conn, self.dird, "0001/26", "2019-2020")

    def test_recherche_d_eleves(self):
        r = sc.chercher_eleves(self.conn, self.dird, self.annee, "Amisi")
        self.assertEqual([e["matricule"] for e in r["eleves"]], ["0001/26"])
        self.assertEqual(sc.chercher_eleves(self.conn, self.dird, self.annee, "Petit")["eleves"], [])        # élève du primaire
        self.assertEqual(sc.chercher_eleves(self.conn, self.dird, self.annee, "")["eleves"], [])


class TestDroitsEtJournal(Fix):
    def test_acces_par_poste(self):
        sc.apercu(self.conn, self.dird, self.annee)                                  # Directeur de discipline : Lecture
        sc.apercu(self.conn, self.admin, self.annee)
        for s in (self.prefet, self.dire, self.secr):
            for appel in (lambda: sc.apercu(self.conn, s, self.annee), lambda: sc.historique_eleve(self.conn, s, "0001/26"),
                          lambda: sc.registre(self.conn, s, self.annee), lambda: sc.observations_professeurs(self.conn, s, self.annee, self.c7),
                          lambda: sc.enregistrer(self.conn, s, self.annee, "0001/26", "INCIDENT", "BAGARRE", "", "Bagarre dans la cour")):
                with self.assertRaises(PermissionError):
                    appel()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CONDUITE_OBSERVATION").fetchone()[0], 0)

    def test_ajout_exige_le_droit_ajout(self):
        with self.conn:
            droits.remplacer_droits(self.conn, self.dird.id_user, {("direction_discipline", "LECTURE")})
        with self.assertRaises(PermissionError):
            self.ajouter()
        sc.apercu(self.conn, self.dird, self.annee)                                  # la lecture reste possible

    def test_droits_par_defaut_du_directeur(self):
        self.assertTrue(sc.peut(self.conn, self.dird, "LECTURE"))
        self.assertTrue(sc.peut(self.conn, self.dird, "AJOUT"))
        self.assertFalse(sc.peut(self.conn, self.dird, "MODIFICATION"))

    def test_actions_inscrites_au_journal_et_connues_de_l_audit(self):
        self.ajouter()
        self.donner(self.dird, "MODIFICATION")
        sc.annuler(self.conn, self.dird, self.conn.execute("SELECT ID_OBS FROM CONDUITE_OBSERVATION").fetchone()[0], "Erreur de saisie")
        sc.apercu(self.conn, self.dird, self.annee)
        agis = {"SUIVI_CONDUITE_CONSULTE", "CONDUITE_ENTREE_AJOUTEE", "CONDUITE_ENTREE_ANNULEE"}
        self.assertTrue(agis <= set(self.actions()))
        for a in agis:
            self.assertIn(a, audit.ACTIONS)
        self.assertIn("Bagarre", journal(self.conn, "CONDUITE_ENTREE_AJOUTEE")[0])
        self.assertIn("-4", journal(self.conn, "CONDUITE_ENTREE_AJOUTEE")[0])
        self.assertIn("Erreur de saisie", journal(self.conn, "CONDUITE_ENTREE_ANNULEE")[0])


class TestWeb(Fix):
    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])
        self.cl = self.app.test_client()
        self.assertEqual(self.cl.post("/connexion", data={"login": "dird1", "mdp": MDP}).status_code, 302)
        self.base = "/m/etudes_discipline/direction_discipline"

    def url(self, **kw):
        q = "&".join(f"{k}={v}" for k, v in kw.items())
        return f"{self.base}?f=conduite&{q}"

    def fiche(self, m="0001%2F26"):
        return self.cl.get(self.url(vue="eleve", annee=self.annee, eleve=m)).get_data(as_text=True)

    def test_onglet_et_vues(self):
        self.assertIn("Suivi de la conduite", self.cl.get(self.base).get_data(as_text=True))
        page = self.cl.get(self.url(annee=self.annee)).get_data(as_text=True)
        self.assertIn("7ème A", page)
        self.assertIn("Élèves à suivre", page)
        page = self.cl.get(self.url(annee=self.annee, classe=self.c7)).get_data(as_text=True)
        self.assertIn("Kasongo", page)
        self.assertNotIn("Petit", page)
        page = self.cl.get(self.url(vue="professeurs", annee=self.annee, classe=self.c7, periode=self.per1)).get_data(as_text=True)
        self.assertIn("Conduite de 7ème A", page)
        self.assertIn("Mathématiques", page)
        page = self.cl.get(self.url(vue="professeurs", annee=self.annee, classe=self.c7)).get_data(as_text=True)
        self.assertIn("Conduite de 7ème A", page)
        self.assertIn("Choisissez une classe", self.cl.get(self.url(vue="professeurs", annee=self.annee)).get_data(as_text=True))
        self.assertIn("Aucune entrée", self.cl.get(self.url(vue="registre", annee=self.annee)).get_data(as_text=True))
        self.assertIn("Amisi", self.cl.get(self.url(vue="eleve", annee=self.annee, q="Amisi")).get_data(as_text=True))
        page = self.fiche()
        self.assertIn("Ajouter une entrée", page)
        self.assertIn("Solde de conduite", page)
        self.assertIn("Bagarre", page)                                               # le règlement est proposé dans le formulaire

    def test_ajouter_par_la_page_puis_voir_dans_les_vues(self):
        base = {"vue": "eleve", "annee": self.annee, "eleve": "0001/26", "matricule": "0001/26"}
        r = self.cl.post(self.base + "/conduite/ajouter", data=dict(base, type_entree="INCIDENT", code="BAGARRE", date_fait=date.today().isoformat(),
                                                                    description="Bagarre à la sortie", lieu="Cour", mesure="Parents convoqués"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("Entrée enregistrée", self.cl.get(r.headers["Location"]).get_data(as_text=True))
        page = self.fiche()
        self.assertIn("Bagarre à la sortie", page)
        self.assertIn("Parents convoqués", page)
        self.assertIn("Bagarre à la sortie", self.cl.get(self.url(vue="registre", annee=self.annee)).get_data(as_text=True))
        self.assertIn("-4", self.cl.get(self.url(annee=self.annee, classe=self.c7)).get_data(as_text=True))
        # erreur : le formulaire est réaffiché avec le message et les valeurs saisies
        r = self.cl.post(self.base + "/conduite/ajouter", data=dict(base, type_entree="INCIDENT", code="BAGARRE", date_fait=date.today().isoformat(),
                                                                    description="abc"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("au moins 5 caractères", r.get_data(as_text=True))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CONDUITE_OBSERVATION").fetchone()[0], 1)

    def test_observation_par_la_page(self):
        base = {"vue": "eleve", "annee": self.annee, "eleve": "0000/26", "matricule": "0000/26"}
        r = self.cl.post(self.base + "/conduite/ajouter", data=dict(base, type_entree="OBSERVATION", nature_obs="POSITIF", date_fait="",
                                                                    description="Très bon comportement lors de la sortie"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.total("0000/26")["positives"], 1)

    def test_annuler_par_la_page(self):
        self.ajouter()
        i = self.conn.execute("SELECT ID_OBS FROM CONDUITE_OBSERVATION").fetchone()[0]
        base = {"vue": "eleve", "annee": self.annee, "eleve": "0001/26", "id": i, "motif_annulation": "Erreur"}
        self.assertEqual(self.cl.post(self.base + "/conduite/annuler", data=base).status_code, 403)       # pas de droit Modification
        self.donner(self.dird, "MODIFICATION")
        self.assertIn("Annuler l'entrée", self.fiche())
        r = self.cl.post(self.base + "/conduite/annuler", data=dict(base, motif_annulation=""))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.cl.post(self.base + "/conduite/annuler", data=base).status_code, 302)
        self.assertIn("Annulée", self.fiche())
        self.assertEqual(self.cl.post(self.base + "/conduite/inconnue", data=base).status_code, 404)

    def test_sans_droit_ajout_pas_de_formulaire(self):
        with self.conn:
            droits.remplacer_droits(self.conn, self.dird.id_user, {("direction_discipline", "LECTURE")})
        page = self.fiche()
        self.assertNotIn("Ajouter une entrée", page)
        self.assertIn("le droit « Ajout » ne vous est pas accordé", page)
        r = self.cl.post(self.base + "/conduite/ajouter", data={"annee": self.annee, "matricule": "0001/26", "type_entree": "INCIDENT", "code": "BAGARRE",
                                                                "description": "Bagarre dans la cour"})
        self.assertEqual(r.status_code, 403)

    def test_acces_refuse_aux_autres_postes(self):
        secr = self.app.test_client()
        self.assertEqual(secr.post("/connexion", data={"login": "secr1", "mdp": MDP}).status_code, 302)
        self.assertEqual(secr.get(self.url()).status_code, 403)
        self.assertEqual(secr.post(self.base + "/conduite/ajouter", data={"matricule": "0000/26"}).status_code, 403)
        self.assertIn(self.app.test_client().get(self.url()).status_code, (302, 401, 403))

    def test_post_sans_origine_valide_refuse(self):
        r = self.cl.post(self.base + "/conduite/ajouter", data={"matricule": "0001/26"}, headers={"Origin": "http://autre-site.example"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()

"""Tests de la Direction de discipline > Gestion des présences : consulter les saisies des professeurs, vérifier la journée, confirmer ou corriger,
absences par classe et par élève.
Lancer :  python -m unittest test_gestion_presences"""
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
import gestion_presences as gp      # noqa: E402
import presence_eleves              # noqa: E402
from gestion_presences import ErreurPresences   # noqa: E402
from test_notes import MDP                      # noqa: E402
from test_prefecture_v57 import Fixture         # noqa: E402


def jour_de_classe(recul=0) -> date:
    """Le dernier jour de classe (lundi à vendredi) à `recul` jours de classe d'aujourd'hui."""
    d = date.today()
    while d.weekday() > 4:
        d -= timedelta(days=1)
    for _ in range(recul):
        d -= timedelta(days=1)
        while d.weekday() > 4:
            d -= timedelta(days=1)
    return d


def texte(d):
    return d.strftime("%d/%m/%Y")


def journal(conn, action):
    return [l["DETAIL"] for l in conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = ? ORDER BY ID_LOG", (action,))]


class Fix(Fixture):
    """Classe 7ème A : 0000 (Kasongo), 0001 (Amisi), 0002 (Zola) ; 8ème A : 0009. Le jour J : maths (prof 1) et français (prof 2).
    0000 présent partout ; 0001 absent en maths seulement ; 0002 absent en français seulement ; 0009 jamais pointé."""

    def setUp(self):
        super().setUp()
        self.J = jour_de_classe()
        self.j = texte(self.J)
        self.pointer(self.s1, self.maths7, self.j, {"0000/26": "P", "0001/26": "A", "0002/26": "P"})
        self.pointer(self.s2, self.fr7, self.j, {"0000/26": "P", "0001/26": "P", "0002/26": "A"})

    def pointer(self, session, id_cc, jour, statuts):
        for m, s in statuts.items():
            presence_eleves.marquer(self.conn, session, id_cc, jour, m, s)

    def donner(self, session, droit):
        d = droits.droits_utilisateur(self.conn, session.id_user) | {("direction_discipline", droit)}
        droits.remplacer_droits(self.conn, session.id_user, d)
        self.conn.commit()

    def ligne(self, matricule, n_classe=None, jour=None):
        r = gp.classe_du_jour(self.conn, self.dird, self.annee, n_classe or self.c7, jour or self.j)
        return next(e for e in r["eleves"] if e["matricule"] == matricule)

    def nb_pointages(self):
        return self.conn.execute("SELECT COUNT(*), GROUP_CONCAT(STATUT, '') FROM (SELECT STATUT FROM PRESENCE_ELEVE ORDER BY ID_CC, DATE_COURS, MATRICULE)").fetchone()[:]


class TestConsultation(Fix):
    def test_presence_du_jour_par_classe(self):
        r = gp.journee(self.conn, self.dird, self.annee, self.j)
        c7 = next(c for c in r["classes"] if c["n_classe"] == self.c7)
        self.assertEqual((c7["effectif"], c7["presents"], c7["absents"], c7["non_renseignes"], c7["cours_pointes"]), (3, 1, 2, 0, 2))
        self.assertEqual((c7["a_verifier"], c7["partiels"], c7["confirmes"], c7["corriges"]), (3, 2, 0, 0))
        c8 = next(c for c in r["classes"] if c["n_classe"] == self.c8)
        self.assertEqual((c8["effectif"], c8["presents"], c8["absents"], c8["non_renseignes"], c8["a_verifier"]), (1, 0, 0, 1, 0))
        self.assertEqual(r["totaux"]["effectif"], 4)
        self.assertNotIn("0100/26", [e["matricule"] for e in gp.classe_du_jour(self.conn, self.dird, self.annee, self.c7, self.j)["eleves"]])

    def test_les_saisies_des_professeurs(self):
        d = gp.classe_du_jour(self.conn, self.dird, self.annee, self.c7, self.j)
        par_cours = {x["cours"]: x for x in d["saisies"]}
        self.assertEqual(sorted(par_cours), ["Français", "Mathématiques"])
        m = par_cours["Mathématiques"]
        self.assertEqual((m["pointes"], m["presents"], m["absents"], m["non_pointes"]), (3, 2, 1, 0))
        self.assertTrue(m["professeur"] and m["professeur"] != "Sans professeur")
        self.assertEqual(m["par"], self.p1["login"])
        eleve = {e["matricule"]: e for e in d["eleves"]}
        self.assertEqual(eleve["0001/26"]["manques"], ["Mathématiques"])
        self.assertTrue(eleve["0001/26"]["partiel"])
        self.assertEqual((eleve["0000/26"]["statut"], eleve["0000/26"]["origine"]), ("P", "PROFS"))
        self.assertEqual(eleve["0001/26"]["statut"], "A")

    def test_jour_non_pointe_est_non_renseigne(self):
        autre = texte(jour_de_classe(1))
        e = self.ligne("0000/26", jour=autre)
        self.assertEqual((e["statut"], e["origine"], e["pointes"]), ("", "", 0))

    def test_jours_interdits(self):
        with self.assertRaises(ErreurPresences):
            gp.journee(self.conn, self.dird, self.annee, texte(date.today() + timedelta(days=1)))
        with self.assertRaises(ErreurPresences):
            gp.journee(self.conn, self.dird, self.annee, "01/01/2020")
        with self.assertRaises(ErreurPresences):
            gp.classe_du_jour(self.conn, self.dird, self.annee, self.cp, self.j)         # classe du primaire : introuvable ici

    def test_la_consultation_ne_modifie_rien(self):
        avant = self.nb_pointages()
        gp.journee(self.conn, self.dird, self.annee, self.j)
        gp.classe_du_jour(self.conn, self.dird, self.annee, self.c7, self.j)
        self.assertEqual(self.nb_pointages(), avant)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PRESENCE_DECISION").fetchone()[0], 0)


class TestDroits(Fix):
    def test_acces_par_poste(self):
        gp.journee(self.conn, self.dird, self.annee, self.j)                     # Directeur de discipline : Lecture
        gp.journee(self.conn, self.admin, self.annee, self.j)
        for s in (self.secr, self.dire, self.prefet):
            with self.assertRaises(PermissionError):
                gp.journee(self.conn, s, self.annee, self.j)

    def test_le_directeur_confirme_mais_n_annule_pas_par_defaut(self):
        gp.confirmer(self.conn, self.dird, self.annee, "0000/26", self.j)         # Ajout : accordé par défaut
        i = self.conn.execute("SELECT ID_DEC FROM PRESENCE_DECISION").fetchone()[0]
        with self.assertRaises(PermissionError):
            gp.annuler(self.conn, self.dird, i, "erreur")                         # Modification : non accordé par défaut
        self.donner(self.dird, "MODIFICATION")
        gp.annuler(self.conn, self.dird, i, "erreur")

    def test_sans_droit_d_ajout_on_ne_decide_pas(self):
        d = {x for x in droits.droits_utilisateur(self.conn, self.dird.id_user) if x != ("direction_discipline", "AJOUT")}
        droits.remplacer_droits(self.conn, self.dird.id_user, d)
        self.conn.commit()
        gp.journee(self.conn, self.dird, self.annee, self.j)                      # Lecture reste possible
        for f in (lambda: gp.confirmer(self.conn, self.dird, self.annee, "0000/26", self.j),
                  lambda: gp.corriger(self.conn, self.dird, self.annee, "0001/26", self.j, "P", "motif"),
                  lambda: gp.confirmer_classe(self.conn, self.dird, self.annee, self.c7, self.j)):
            with self.assertRaises(PermissionError):
                f()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PRESENCE_DECISION").fetchone()[0], 0)

    def test_compte_limite_au_primaire(self):
        with self.conn:
            self.conn.execute("DELETE FROM SECTION_UTILISATEUR WHERE ID_USER = ?", (self.dird.id_user,))
            self.conn.execute("INSERT INTO SECTION_UTILISATEUR (ID_USER, SECTION) VALUES (?, 'PRIMAIRE')", (self.dird.id_user,))
        with self.assertRaises(PermissionError):
            gp.journee(self.conn, self.dird, self.annee, self.j)


class TestConfirmerCorriger(Fix):
    def test_confirmer_garde_les_pointages(self):
        avant = self.nb_pointages()
        r = gp.confirmer(self.conn, self.dird, self.annee, "0000/26", self.j)
        self.assertEqual((r["statut"], r["change"]), ("P", True))
        e = self.ligne("0000/26")
        self.assertEqual((e["statut"], e["origine"]), ("P", "CONFIRME"))
        self.assertEqual(self.nb_pointages(), avant)                              # le pointage des professeurs n'a pas bougé
        self.assertEqual(len(journal(self.conn, "PRESENCE_JOUR_CONFIRMEE")), 1)
        self.assertFalse(gp.confirmer(self.conn, self.dird, self.annee, "0000/26", self.j)["change"])    # idem : rien d'écrit
        self.assertEqual(len(journal(self.conn, "PRESENCE_JOUR_CONFIRMEE")), 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PRESENCE_DECISION").fetchone()[0], 1)

    def test_on_ne_confirme_pas_un_eleve_non_pointe(self):
        with self.assertRaises(ErreurPresences):
            gp.confirmer(self.conn, self.dird, self.annee, "0009/26", self.j)

    def test_corriger_exige_un_motif_et_un_autre_statut(self):
        with self.assertRaises(ErreurPresences):
            gp.corriger(self.conn, self.dird, self.annee, "0001/26", self.j, "P", "")
        with self.assertRaises(ErreurPresences):
            gp.corriger(self.conn, self.dird, self.annee, "0001/26", self.j, "A", "déjà absent")          # identique aux pointages
        with self.assertRaises(ErreurPresences):
            gp.corriger(self.conn, self.dird, self.annee, "0001/26", self.j, "X", "motif")
        with self.assertRaises(ErreurPresences):
            gp.corriger(self.conn, self.dird, self.annee, "0001/26", self.j, "P", "x" * 400)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PRESENCE_DECISION").fetchone()[0], 0)

    def test_corriger_remplace_le_statut_retenu(self):
        gp.corriger(self.conn, self.dird, self.annee, "0001/26", self.j, "P", "Justificatif médical reçu")
        e = self.ligne("0001/26")
        self.assertEqual((e["statut"], e["profs"], e["origine"]), ("P", "A", "CORRIGE"))
        self.assertEqual(e["decision"]["motif"], "Justificatif médical reçu")
        self.assertIn("Absent -> Présent", journal(self.conn, "PRESENCE_JOUR_CORRIGEE")[0])
        c7 = next(c for c in gp.journee(self.conn, self.dird, self.annee, self.j)["classes"] if c["n_classe"] == self.c7)
        self.assertEqual((c7["presents"], c7["absents"], c7["corriges"]), (2, 1, 1))
        # les pointages bruts sont intacts : l'ancienne lecture (Préfecture, bulletins) voit toujours « absent »
        self.assertEqual(presence_eleves._statuts_jour(self.conn, self.annee, self.c7, self.J.isoformat())["0001/26"]["statut"], "A")

    def test_corriger_un_jour_non_pointe(self):
        gp.corriger(self.conn, self.dird, self.annee, "0009/26", self.j, "A", "Absence signalée par la famille")
        e = self.ligne("0009/26", self.c8)
        self.assertEqual((e["statut"], e["profs"], e["origine"]), ("A", "", "CORRIGE"))

    def test_nouvelle_decision_remplace_sans_rien_supprimer(self):
        gp.confirmer(self.conn, self.dird, self.annee, "0001/26", self.j)
        gp.corriger(self.conn, self.dird, self.annee, "0001/26", self.j, "P", "Retard seulement")
        lignes = self.conn.execute("SELECT GENRE, ANNULE_LE, MOTIF_ANNULATION FROM PRESENCE_DECISION ORDER BY ID_DEC").fetchall()
        self.assertEqual([(l["GENRE"], bool(l["ANNULE_LE"])) for l in lignes], [("CONFIRME", True), ("CORRIGE", False)])
        self.assertIn("Remplacée", lignes[0]["MOTIF_ANNULATION"])

    def test_confirmation_perimee_si_le_professeur_change_son_pointage(self):
        gp.confirmer(self.conn, self.dird, self.annee, "0001/26", self.j)
        self.assertEqual(self.ligne("0001/26")["origine"], "CONFIRME")
        presence_eleves.marquer(self.conn, self.s1, self.maths7, self.j, "0001/26", "P")      # le professeur corrige : 0001 devient présent
        e = self.ligne("0001/26")
        self.assertEqual((e["statut"], e["origine"], e["a_revoir"]), ("P", "PROFS", True))
        self.assertEqual(e["profs"], "P")

    def test_correction_signalee_si_le_pointage_change_ensuite(self):
        gp.corriger(self.conn, self.dird, self.annee, "0001/26", self.j, "P", "Justifié")
        presence_eleves.marquer(self.conn, self.s2, self.fr7, self.j, "0001/26", "A")         # un autre cours passe à absent : pointages inchangés (A)
        self.assertFalse(self.ligne("0001/26")["modifie_depuis"])
        presence_eleves.marquer(self.conn, self.s1, self.maths7, self.j, "0001/26", "P")
        presence_eleves.marquer(self.conn, self.s2, self.fr7, self.j, "0001/26", "P")         # tout présent : l'état des pointages a changé
        e = self.ligne("0001/26")
        self.assertEqual((e["statut"], e["origine"], e["modifie_depuis"]), ("P", "CORRIGE", True))

    def test_confirmer_une_classe(self):
        gp.corriger(self.conn, self.dird, self.annee, "0001/26", self.j, "P", "Justifié")
        r = gp.confirmer_classe(self.conn, self.dird, self.annee, self.c7, self.j)
        self.assertEqual(r["faits"], 2)                                                      # 0000 et 0002 ; 0001 déjà corrigé
        self.assertEqual(self.ligne("0001/26")["origine"], "CORRIGE")
        self.assertEqual(self.ligne("0002/26")["origine"], "CONFIRME")
        self.assertEqual(gp.confirmer_classe(self.conn, self.dird, self.annee, self.c7, self.j)["faits"], 0)
        self.assertEqual(gp.confirmer_classe(self.conn, self.dird, self.annee, self.c8, self.j)["faits"], 0)   # 0009 non pointé : intact
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PRESENCE_DECISION WHERE MATRICULE = '0009/26'").fetchone()[0], 0)
        self.assertEqual(len(journal(self.conn, "PRESENCE_CLASSE_CONFIRMEE")), 1)

    def test_annuler_ramene_aux_pointages(self):
        gp.corriger(self.conn, self.dird, self.annee, "0001/26", self.j, "P", "Justifié")
        i = self.conn.execute("SELECT ID_DEC FROM PRESENCE_DECISION").fetchone()[0]
        self.donner(self.dird, "MODIFICATION")
        with self.assertRaises(ErreurPresences):
            gp.annuler(self.conn, self.dird, i, "")                                          # motif obligatoire
        gp.annuler(self.conn, self.dird, i, "Justificatif refusé")
        e = self.ligne("0001/26")
        self.assertEqual((e["statut"], e["origine"], e["decision"]), ("A", "PROFS", None))
        ligne = self.conn.execute("SELECT * FROM PRESENCE_DECISION WHERE ID_DEC = ?", (i,)).fetchone()
        self.assertEqual((ligne["ANNULE_PAR"], ligne["MOTIF_ANNULATION"]), (self.dird.login, "Justificatif refusé"))   # la ligne est conservée
        with self.assertRaises(ErreurPresences):
            gp.annuler(self.conn, self.dird, i, "encore")                                    # déjà annulée
        self.assertEqual(len(journal(self.conn, "PRESENCE_JOUR_ANNULEE")), 1)

    def test_limites(self):
        with self.assertRaises(ErreurPresences):                                              # futur
            gp.corriger(self.conn, self.dird, self.annee, "0001/26", texte(date.today() + timedelta(days=1)), "P", "motif")
        samedi = date.today()
        while samedi.weekday() != 5:
            samedi -= timedelta(days=1)
        with self.assertRaises(ErreurPresences):                                              # pas un jour de classe
            gp.corriger(self.conn, self.dird, self.annee, "0001/26", texte(samedi), "P", "motif")
        with self.assertRaises(PermissionError):                                              # élève du primaire
            gp.corriger(self.conn, self.dird, self.annee, "0100/26", self.j, "A", "motif")
        with self.assertRaises(ErreurPresences):
            gp.corriger(self.conn, self.dird, self.annee, "9999/99", self.j, "A", "motif")
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET ACTIF = 0 WHERE MATRICULE = '0002/26'")
        with self.assertRaises(ErreurPresences):
            gp.corriger(self.conn, self.dird, self.annee, "0002/26", self.j, "P", "motif")
        with self.conn:
            self.conn.execute("INSERT INTO ANNEE_SCO (ANNEESCO, EN_COURS) VALUES ('2025-2026', 0)")
        with self.assertRaises(ErreurPresences):                                              # année passée : consultation seule
            gp.corriger(self.conn, self.dird, "2025-2026", "0001/26", self.j, "P", "motif")


class TestAbsences(Fix):
    def setUp(self):
        super().setUp()
        self.J2 = jour_de_classe(1)                      # la veille : 0001 absent en maths ; 0000 présent
        self.j2 = texte(self.J2)
        self.pointer(self.s1, self.maths7, self.j2, {"0000/26": "P", "0001/26": "A", "0002/26": "P"})
        self.du, self.au = texte(self.J2), texte(self.J)

    def test_absences_par_classe(self):
        r = gp.absences_classe(self.conn, self.dird, self.annee, self.c7, self.du, self.au)
        par = {e["matricule"]: e for e in r["eleves"]}
        self.assertEqual(r["jours_pointes"], 2)
        self.assertEqual((par["0000/26"]["jours_presents"], par["0000/26"]["jours_absents"]), (2, 0))
        self.assertEqual((par["0001/26"]["jours_presents"], par["0001/26"]["jours_absents"]), (0, 2))
        self.assertEqual((par["0002/26"]["jours_presents"], par["0002/26"]["jours_absents"]), (1, 1))
        self.assertEqual(par["0002/26"]["taux"], 50.0)
        self.assertEqual(r["total_absences"], 3)
        self.assertEqual(par["0001/26"]["dates_absence"], sorted({self.j, self.j2}, key=lambda t: t[::-1]))

    def test_les_corrections_comptent_dans_les_absences(self):
        gp.corriger(self.conn, self.dird, self.annee, "0001/26", self.j, "P", "Justifié")
        gp.corriger(self.conn, self.dird, self.annee, "0000/26", self.j, "A", "Sorti à 8 h")
        r = gp.absences_classe(self.conn, self.dird, self.annee, self.c7, self.du, self.au)
        par = {e["matricule"]: e for e in r["eleves"]}
        self.assertEqual((par["0001/26"]["jours_presents"], par["0001/26"]["jours_absents"], par["0001/26"]["corriges"]), (1, 1, 1))
        self.assertEqual((par["0000/26"]["jours_presents"], par["0000/26"]["jours_absents"]), (1, 1))

    def test_periode_par_defaut_et_erreurs(self):
        r = gp.absences_classe(self.conn, self.dird, self.annee, self.c7)
        self.assertEqual(r["jours_pointes"], 2)
        with self.assertRaises(ErreurPresences):
            gp.absences_classe(self.conn, self.dird, self.annee, self.c7, self.au, self.du)
        with self.assertRaises(ErreurPresences):
            gp.absences_classe(self.conn, self.dird, self.annee, self.cp)

    def test_absences_d_un_eleve(self):
        gp.corriger(self.conn, self.dird, self.annee, "0001/26", self.j2, "P", "Justifié")
        r = gp.absences_eleve(self.conn, self.dird, self.annee, "0001/26", self.du, self.au)
        self.assertEqual((r["jours_absents"], r["jours_presents"], r["jours_corriges"]), (1, 1, 1))
        self.assertEqual(r["absences"][0]["date"], self.j)
        self.assertEqual(r["absences"][0]["manques"], ["Mathématiques"])
        self.assertEqual(r["taux"], 50.0)
        self.assertEqual([(h["genre"], h["statut"], h["annulee"]) for h in r["historique"]], [("Corrigé", "Présent", False)])
        with self.assertRaises(PermissionError):
            gp.absences_eleve(self.conn, self.dird, self.annee, "0100/26")

    def test_recherche_d_un_eleve(self):
        r = gp.chercher_eleves(self.conn, self.dird, self.annee, "amisi")
        self.assertEqual([e["matricule"] for e in r["eleves"]], ["0001/26"])
        self.assertEqual(gp.chercher_eleves(self.conn, self.dird, self.annee, "Petit")["eleves"], [])        # primaire
        self.assertEqual(gp.chercher_eleves(self.conn, self.dird, self.annee, "")["eleves"], [])


class TestJournal(Fix):
    def test_actions_inscrites(self):
        for a in ("GESTION_PRESENCES_CONSULTEE", "PRESENCE_JOUR_CONFIRMEE", "PRESENCE_JOUR_CORRIGEE", "PRESENCE_CLASSE_CONFIRMEE", "PRESENCE_JOUR_ANNULEE"):
            self.assertIn(a, audit.ACTIONS)
        gp.journee(self.conn, self.dird, self.annee, self.j)
        self.assertEqual(len(journal(self.conn, "GESTION_PRESENCES_CONSULTEE")), 1)


class TestWeb(Fix):
    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])
        self.cl = self.app.test_client()
        self.assertEqual(self.cl.post("/connexion", data={"login": "dird1", "mdp": MDP}).status_code, 302)
        self.base = "/m/etudes_discipline/direction_discipline"

    def url(self, **kw):
        q = "&".join(f"{k}={v}" for k, v in kw.items())
        return f"{self.base}?f=presences&{q}"

    def test_onglet_et_vues(self):
        self.assertIn("Gestion des présences", self.cl.get(self.base).get_data(as_text=True))
        page = self.cl.get(self.url(annee=self.annee, jour=self.J.isoformat())).get_data(as_text=True)
        self.assertIn("7ème A", page)
        self.assertIn("8ème A", page)
        page = self.cl.get(self.url(annee=self.annee, jour=self.J.isoformat(), classe=self.c7)).get_data(as_text=True)
        self.assertIn("Présences saisies par les professeurs", page)
        self.assertIn("Kasongo", page)
        self.assertIn("Absent à : Mathématiques", page)
        self.assertNotIn("Petit", page)
        page = self.cl.get(self.url(vue="classe", annee=self.annee, classe=self.c7)).get_data(as_text=True)
        self.assertIn("Absences de 7ème A", page)
        page = self.cl.get(self.url(vue="eleve", annee=self.annee, q="Amisi")).get_data(as_text=True)
        self.assertIn("Voir les absences", page)
        page = self.cl.get(self.url(vue="eleve", annee=self.annee, eleve="0001/26".replace("/", "%2F"))).get_data(as_text=True)
        self.assertIn("Jours absents", page)

    def test_confirmer_corriger_annuler_par_la_page(self):
        base = {"vue": "jour", "annee": self.annee, "jour": self.J.isoformat(), "classe": str(self.c7)}
        r = self.cl.post(self.base + "/presences/confirmer", data=dict(base, matricule="0000/26"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("Présence confirmée", self.cl.get(r.headers["Location"]).get_data(as_text=True))
        r = self.cl.post(self.base + "/presences/corriger", data=dict(base, matricule="0001/26", statut="P", motif=""))
        self.assertEqual(r.status_code, 400)
        self.assertIn("motif", r.get_data(as_text=True))
        r = self.cl.post(self.base + "/presences/corriger", data=dict(base, matricule="0001/26", statut="P", motif="Justifié"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.ligne("0001/26")["origine"], "CORRIGE")
        i = self.conn.execute("SELECT ID_DEC FROM PRESENCE_DECISION WHERE GENRE = 'CORRIGE'").fetchone()[0]
        self.assertEqual(self.cl.post(self.base + "/presences/annuler", data=dict(base, id=i, motif_annulation="x")).status_code, 403)   # pas de droit Modification
        self.donner(self.dird, "MODIFICATION")
        self.assertEqual(self.cl.post(self.base + "/presences/annuler", data=dict(base, id=i, motif_annulation="refusé")).status_code, 302)
        self.assertEqual(self.ligne("0001/26")["origine"], "PROFS")
        r = self.cl.post(self.base + "/presences/confirmer_classe", data=base)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.cl.post(self.base + "/presences/inconnue", data=base).status_code, 404)

    def test_acces_refuse_aux_autres_postes(self):
        secr = self.app.test_client()
        self.assertEqual(secr.post("/connexion", data={"login": "secr1", "mdp": MDP}).status_code, 302)
        self.assertEqual(secr.get(self.url()).status_code, 403)
        self.assertEqual(secr.post(self.base + "/presences/confirmer", data={"matricule": "0000/26"}).status_code, 403)
        self.assertIn(self.app.test_client().get(self.url()).status_code, (302, 401, 403))


if __name__ == "__main__":
    unittest.main()

"""Tests du contrôle des notes (Direction des études, fonctionnalité 3) : situation par période, notes manquantes, fiche d'un cours,
demandes de correction, côté professeur, droits, page web.
Lancer :  python -m unittest test_controle_notes"""
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web          # noqa: E402
import controle_notes   # noqa: E402
import droits           # noqa: E402
import notes            # noqa: E402
import security         # noqa: E402
from controle_notes import ErreurControle   # noqa: E402
from test_notes import Base, MDP            # noqa: E402


class Fixture(Base):
    def setUp(self):
        super().setUp()
        c = self.conn
        for login, role in (("dire1", "DIRECTRICE_ETUDES"), ("prefet1", "PREFET"), ("perc1", "PERCEPTEUR")):
            security.creer_utilisateur(c, login, login.title(), role, MDP)
        self.dire, self.prefet, self.perc = (security.authentifier(c, x, MDP).session for x in ("dire1", "prefet1", "perc1"))
        fin1 = c.execute("SELECT DATE_FIN FROM PERIODE_SCO WHERE ID_PER = ?", (self.per1,)).fetchone()[0]
        self.apres_p1 = date.fromisoformat(fin1) + timedelta(days=3)
        patch = mock.patch("notes.aujourdhui", return_value=self.apres_p1)
        patch.start()
        self.addCleanup(patch.stop)
        self.cle1 = f"P{self.per1}"
        # 7ème A : maths (prof 1) complet pour la période 1 ; français (prof 2) : 1 élève sur 3
        notes.enregistrer_points(c, self.s1, self.maths7, self.per1, {"0000/26": "15", "0001/26": "8", "0002/26": "12"})
        notes.enregistrer_points(c, self.s2, self.fr7, self.per1, {"0000/26": "10"})

    def etat(self, cours, cle=None, classe=None):
        s = controle_notes.synthese(self.conn, self.dire, self.annee, cle or self.cle1)
        for k in s["classes"]:
            for f in k["cours"]:
                if f["id_cc"] == cours:
                    return f


class TestSituation(Fixture):
    def test_etats_des_fiches(self):
        self.assertEqual(self.etat(self.maths7)["etat"], "COMPLET")
        f = self.etat(self.fr7)
        self.assertEqual((f["etat"], f["nb_saisies"], f["nb_manquantes"], f["retard"]), ("INCOMPLET", 1, 2, True))
        self.assertEqual(self.etat(self.maths8)["nb_eleves"], 1)                  # la classe 8 a un élève : non saisi
        self.assertEqual(self.etat(self.maths8)["etat"], "NON_SAISI")

    def test_periode_par_defaut_est_la_derniere_echue(self):
        s = controle_notes.synthese(self.conn, self.dire, self.annee)
        self.assertEqual(s["cle"], self.cle1)
        self.assertEqual(s["total"]["fiches"], 4)                                  # maths et français dans chaque classe
        self.assertEqual(s["total"]["complets"], 1)
        self.assertEqual(s["total"]["manquantes"], 4)

    def test_periode_a_venir_pas_en_retard(self):
        f = self.etat(self.fr7, f"P{self.per3}")
        self.assertEqual(f["etat"], "NON_SAISI")
        self.assertFalse(f["retard"])

    def test_cours_sans_professeur(self):
        with self.conn:
            self.conn.execute("UPDATE COURS_CLASSE SET MATRICULE_PROF = NULL WHERE ID_CC = ?", (self.maths8,))
        self.assertEqual(self.etat(self.maths8)["etat"], "SANS_PROF")

    def test_examen_sans_objet_pour_cours_a_100_points(self):
        with self.conn:
            self.conn.execute("UPDATE COURS_CLASSE SET MAX_PERIODE = 100 WHERE ID_CC = ?", (self.fr7,))
        self.assertEqual(self.etat(self.fr7, f"X{self.sem1}")["etat"], "SANS_OBJET")
        self.assertEqual(self.etat(self.maths7, f"X{self.sem1}")["etat"], "NON_SAISI")

    def test_note_d_un_ancien_eleve_ne_compte_pas(self):
        with self.conn:                                                           # l'élève 0002 quitte la classe : sa note ne compte plus
            self.conn.execute("DELETE FROM INSCRIRE WHERE MATRICULE = '0002/26'")
        f = self.etat(self.maths7)
        self.assertEqual((f["nb_eleves"], f["nb_saisies"], f["etat"]), (2, 2, "COMPLET"))

    def test_droit_de_lecture_exige(self):
        for s in (self.prefet, self.perc, self.s1):
            with self.assertRaises(PermissionError):
                controle_notes.synthese(self.conn, s, self.annee)
        controle_notes.synthese(self.conn, self.admin, self.annee)


class TestManquantes(Fixture):
    def test_groupes_par_professeur(self):
        r = controle_notes.manquantes(self.conn, self.dire, self.annee)
        par = {g["matricule"]: g for g in r["professeurs"]}
        self.assertEqual(par[self.m2]["nb_manquantes"], 2)                        # français 7ème : 2 manquantes
        self.assertEqual(par[self.m1]["nb_manquantes"], 1)                        # maths 8ème : 1 manquante (maths 7ème complet)
        self.assertEqual(par[""]["nb_manquantes"], 1)                             # français 8ème : sans professeur
        self.assertEqual(r["professeurs"][-1]["matricule"], "")                   # le groupe sans professeur vient en dernier
        self.assertEqual(r["nb_fiches"], 3)
        self.assertEqual(r["nb_a_relancer"], 2)

    def test_periodes_en_cours_seulement_sur_demande(self):
        sans = controle_notes.manquantes(self.conn, self.dire, self.annee)["nb_fiches"]
        avec = controle_notes.manquantes(self.conn, self.dire, self.annee, en_cours=True)["nb_fiches"]
        self.assertGreaterEqual(avec, sans)
        self.assertEqual(controle_notes.manquantes(self.conn, self.dire, self.annee, self.m2)["nb_fiches"], 1)

    def test_export_csv(self):
        csv_ = controle_notes.exporter_manquantes_csv(self.conn, self.dire, self.annee)
        self.assertIn("Notes manquantes", csv_)
        self.assertEqual(len(csv_.strip().splitlines()), 4)
        self.assertIn("NOTES_MANQUANTES_EXPORT", [l[0] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")])


class TestFiche(Fixture):
    def test_points_et_reperes(self):
        f = controle_notes.fiche(self.conn, self.dire, self.maths7, self.cle1)
        self.assertEqual({e["nom"].split()[0]: e["points"] for e in f["eleves"]}, {"Amisi": 8, "Kasongo": 15, "Zola": 12})
        self.assertEqual((f["stats"]["minimum"], f["stats"]["maximum"], f["stats"]["moyenne"]), (8, 15, 11.7))
        self.assertEqual(f["stats"]["sous_la_moitie"], 1)
        self.assertTrue(f["peut_demander"])

    def test_points_manquants_signales(self):
        f = controle_notes.fiche(self.conn, self.dire, self.fr7, self.cle1)
        self.assertEqual(sum(1 for e in f["eleves"] if e["points"] is None), 2)

    def test_cours_inconnu_ou_periode_inconnue(self):
        with self.assertRaises(ErreurControle):
            controle_notes.fiche(self.conn, self.dire, 99999, self.cle1)
        with self.assertRaises(ErreurControle):
            controle_notes.fiche(self.conn, self.dire, self.maths7, "P99999")

    def test_lecture_inscrite_au_journal(self):
        controle_notes.fiche(self.conn, self.dire, self.maths7, self.cle1)
        self.assertIn("NOTES_CONSULTATION", [l[0] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")])


class TestDemandes(Fixture):
    def test_demande_de_notes_manquantes(self):
        r = controle_notes.demander(self.conn, self.dire, self.fr7, self.cle1, "MANQUANTE")
        self.assertEqual(len(r["ids"]), 1)
        d = controle_notes.liste_demandes(self.conn, self.dire, self.annee)[0]
        self.assertEqual((d["type"], d["statut"], d["manquantes_actuelles"]), ("MANQUANTE", "OUVERTE", 2))
        self.assertIn("2 élève(s) sur 3", d["motif"])
        self.assertIn("CORRECTION_DEMANDEE", [l[0] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")])

    def test_correction_exige_un_motif_et_peut_viser_des_eleves(self):
        with self.assertRaises(ErreurControle):
            controle_notes.demander(self.conn, self.dire, self.maths7, self.cle1, "CORRECTION", "")
        r = controle_notes.demander(self.conn, self.dire, self.maths7, self.cle1, "CORRECTION", "Point supérieur à la feuille de cotes",
                                    ["0001/26", "0002/26"])
        self.assertEqual(len(r["ids"]), 2)
        self.assertEqual({d["eleve"].split()[0] for d in controle_notes.liste_demandes(self.conn, self.dire, self.annee)}, {"Amisi", "Zola"})

    def test_pas_de_doublon_ouvert(self):
        controle_notes.demander(self.conn, self.dire, self.fr7, self.cle1, "MANQUANTE")
        with self.assertRaises(ErreurControle):
            controle_notes.demander(self.conn, self.dire, self.fr7, self.cle1, "MANQUANTE")

    def test_refus(self):
        with self.assertRaises(ErreurControle):                                   # tout est saisi
            controle_notes.demander(self.conn, self.dire, self.maths7, self.cle1, "MANQUANTE")
        with self.assertRaises(ErreurControle):                                   # élève d'une autre classe
            controle_notes.demander(self.conn, self.dire, self.maths7, self.cle1, "CORRECTION", "À revoir svp", ["0009/26"])
        with self.assertRaises(ErreurControle):
            controle_notes.demander(self.conn, self.dire, self.maths7, self.cle1, "AUTRE", "x")
        with self.conn:
            self.conn.execute("UPDATE COURS_CLASSE SET MATRICULE_PROF = NULL WHERE ID_CC = ?", (self.fr7,))
        with self.assertRaises(ErreurControle):                                   # pas de professeur
            controle_notes.demander(self.conn, self.dire, self.fr7, self.cle1, "MANQUANTE")

    def test_droit_ajout_exige(self):
        for s in (self.prefet, self.perc, self.s1):
            with self.assertRaises(PermissionError):
                controle_notes.demander(self.conn, s, self.fr7, self.cle1, "MANQUANTE")
        with self.conn:                                                           # Lecture seule : consulte mais n'envoie pas
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'direction_etudes' AND DROIT = 'AJOUT'", (self.dire.id_user,))
        self.assertFalse(controle_notes.fiche(self.conn, self.dire, self.fr7, self.cle1)["peut_demander"])
        with self.assertRaises(PermissionError):
            controle_notes.demander(self.conn, self.dire, self.fr7, self.cle1, "MANQUANTE")

    def test_saisie_fermee_signalee(self):
        self.fermer_tout()
        self.assertTrue(controle_notes.demander(self.conn, self.dire, self.fr7, self.cle1, "MANQUANTE")["fermee"])

    def test_relancer_tous_les_professeurs(self):
        self.assertEqual(controle_notes.demander_les_manquantes(self.conn, self.dire, self.annee)["creees"], 2)
        self.assertEqual(controle_notes.demander_les_manquantes(self.conn, self.dire, self.annee)["creees"], 0)
        self.assertEqual(controle_notes.manquantes(self.conn, self.dire, self.annee)["nb_a_relancer"], 0)

    def test_annuler(self):
        controle_notes.demander(self.conn, self.dire, self.fr7, self.cle1, "MANQUANTE")
        i = controle_notes.liste_demandes(self.conn, self.dire, self.annee)[0]["id"]
        with self.assertRaises(PermissionError):
            controle_notes.annuler_demande(self.conn, self.prefet, i)
        controle_notes.annuler_demande(self.conn, self.dire, i)
        self.assertEqual(controle_notes.liste_demandes(self.conn, self.dire, self.annee)[0]["statut"], "ANNULEE")
        with self.assertRaises(ErreurControle):
            controle_notes.annuler_demande(self.conn, self.dire, i)
        self.assertEqual(controle_notes.liste_demandes(self.conn, self.dire, self.annee, "OUVERTE"), [])


class TestProfesseur(Fixture):
    def test_chaque_professeur_ne_voit_que_les_siennes(self):
        controle_notes.demander(self.conn, self.dire, self.fr7, self.cle1, "MANQUANTE")
        controle_notes.demander(self.conn, self.dire, self.maths7, self.cle1, "CORRECTION", "Revoir le point de Amisi", ["0001/26"])
        m1, m2 = controle_notes.mes_demandes(self.conn, self.s1), controle_notes.mes_demandes(self.conn, self.s2)
        self.assertEqual([d["cours"] for d in m1["ouvertes"]], ["Mathématiques"])
        self.assertEqual([d["cours"] for d in m2["ouvertes"]], ["Français"])
        self.assertEqual(controle_notes.nombre_ouvertes(self.conn, self.s1), 1)
        for s in (self.dire, self.prefet):                                          # un compte non professeur n'a pas cette page
            with self.assertRaises(PermissionError):
                controle_notes.mes_demandes(self.conn, s)

    def test_traiter_une_correction(self):
        controle_notes.demander(self.conn, self.dire, self.maths7, self.cle1, "CORRECTION", "Revoir le point de Amisi", ["0001/26"])
        i = controle_notes.mes_demandes(self.conn, self.s1)["ouvertes"][0]["id"]
        with self.assertRaises(PermissionError):                                    # le professeur d'un autre cours ne peut pas la traiter
            controle_notes.traiter_demande(self.conn, self.s2, i, "fait")
        with self.assertRaises(ErreurControle):                                     # réponse obligatoire
            controle_notes.traiter_demande(self.conn, self.s1, i, "")
        notes.enregistrer_points(self.conn, self.s1, self.maths7, self.per1, {"0001/26": "9"})
        controle_notes.traiter_demande(self.conn, self.s1, i, "Point corrigé : 9")
        d = controle_notes.liste_demandes(self.conn, self.dire, self.annee, "TRAITEE")[0]
        self.assertEqual((d["reponse"], d["statut"]), ("Point corrigé : 9", "TRAITEE"))
        self.assertEqual(controle_notes.mes_demandes(self.conn, self.s1)["nb_ouvertes"], 0)
        with self.assertRaises(ErreurControle):
            controle_notes.traiter_demande(self.conn, self.s1, i, "encore")
        with self.assertRaises(ErreurControle):                                     # la direction ne peut plus l'annuler
            controle_notes.annuler_demande(self.conn, self.dire, i)

    def test_manquantes_restantes_exigent_une_explication(self):
        controle_notes.demander(self.conn, self.dire, self.fr7, self.cle1, "MANQUANTE")
        i = controle_notes.mes_demandes(self.conn, self.s2)["ouvertes"][0]["id"]
        with self.assertRaises(ErreurControle):
            controle_notes.traiter_demande(self.conn, self.s2, i, "")
        notes.enregistrer_points(self.conn, self.s2, self.fr7, self.per1, {"0001/26": "11", "0002/26": "13"})
        self.assertTrue(controle_notes.mes_demandes(self.conn, self.s2)["ouvertes"][0]["maintenant_complet"])
        controle_notes.traiter_demande(self.conn, self.s2, i, "")                   # tout est saisi : pas de réponse nécessaire
        self.assertEqual(controle_notes.liste_demandes(self.conn, self.dire, self.annee, "TRAITEE")[0]["statut"], "TRAITEE")

    def test_demande_annulee_disparait_des_ouvertes(self):
        controle_notes.demander(self.conn, self.dire, self.fr7, self.cle1, "MANQUANTE")
        i = controle_notes.mes_demandes(self.conn, self.s2)["ouvertes"][0]["id"]
        controle_notes.annuler_demande(self.conn, self.dire, i)
        m = controle_notes.mes_demandes(self.conn, self.s2)
        self.assertEqual((m["nb_ouvertes"], len(m["historique"])), (0, 1))
        with self.assertRaises(ErreurControle):
            controle_notes.traiter_demande(self.conn, self.s2, i, "ok")


class TestWeb(Fixture):
    def setUp(self):
        super().setUp()
        self.chemin = self.conn.execute("PRAGMA database_list").fetchone()[2]
        self.app = app_web.creer_app(self.chemin)
        self.cl = self.app.test_client()
        self.assertEqual(self.cl.post("/connexion", data={"login": "dire1", "mdp": MDP}).status_code, 302)
        self.base = "/m/etudes_discipline/direction_etudes"

    def test_onglet_et_vues(self):
        h = self.cl.get(self.base).get_data(as_text=True)
        self.assertIn("Contrôle des notes", h)
        for url in (f"{self.base}?f=notes", f"{self.base}?f=notes&vue=manquantes", f"{self.base}?f=notes&vue=demandes",
                    f"{self.base}?f=notes&cc={self.fr7}&cle={self.cle1}"):
            r = self.cl.get(url)
            self.assertEqual(r.status_code, 200, url)
        h = self.cl.get(f"{self.base}?f=notes").get_data(as_text=True)
        self.assertIn("Français", h)
        self.assertIn("Incomplet", h)
        self.assertIn("manquant", self.cl.get(f"{self.base}?f=notes&cc={self.fr7}&cle={self.cle1}").get_data(as_text=True))

    def test_demander_puis_annuler_par_la_page(self):
        r = self.cl.post(f"{self.base}/notes/demander", data={"id_cc": self.fr7, "cle": self.cle1, "type": "MANQUANTE", "vue": "manquantes"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("Demande envoyée", self.cl.get(r.headers["Location"]).get_data(as_text=True))
        liste = self.cl.get(f"{self.base}?f=notes&vue=demandes").get_data(as_text=True)
        self.assertIn("Notes manquantes", liste)
        self.assertIn("Annuler la demande", liste)
        i = controle_notes.liste_demandes(self.conn, self.dire, self.annee)[0]["id"]
        self.assertEqual(self.cl.post(f"{self.base}/notes/annuler", data={"id": i, "vue": "demandes"}).status_code, 302)
        self.assertEqual(controle_notes.liste_demandes(self.conn, self.dire, self.annee)[0]["statut"], "ANNULEE")

    def test_erreur_affichee_dans_la_page(self):
        r = self.cl.post(f"{self.base}/notes/demander", data={"id_cc": self.maths7, "cle": self.cle1, "type": "CORRECTION", "motif": "", "cc": self.maths7})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Expliquez au professeur", r.get_data(as_text=True))

    def test_relancer_et_csv(self):
        self.assertEqual(self.cl.post(f"{self.base}/notes/relancer", data={"annee": self.annee, "vue": "manquantes"}).status_code, 302)
        self.assertEqual(len(controle_notes.liste_demandes(self.conn, self.dire, self.annee)), 2)
        r = self.cl.get(f"{self.base}/notes/manquantes.csv?annee={self.annee}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["Content-Type"])

    def test_autres_postes_refuses(self):
        for login in ("prefet1", "perc1"):
            cl = self.app.test_client()
            cl.post("/connexion", data={"login": login, "mdp": MDP})
            self.assertEqual(cl.get(f"{self.base}?f=notes").status_code, 403, login)
            self.assertEqual(cl.post(f"{self.base}/notes/relancer", data={}).status_code, 403, login)
            self.assertEqual(cl.get(f"{self.base}/notes/manquantes.csv").status_code, 403, login)

    def test_api_du_professeur(self):
        controle_notes.demander(self.conn, self.dire, self.fr7, self.cle1, "MANQUANTE")
        cl = self.app.test_client()
        r = cl.post("/api/connexion", json={"login": self.p2["login"], "mdp": self.p2["mdp_temporaire"]})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["doit_changer_mdp"])
        # le mot de passe provisoire doit d'abord être changé
        tete = {"Authorization": "Bearer " + r.get_json()["jeton"]}
        self.assertEqual(cl.get("/api/corrections", headers=tete).status_code, 403)
        nouveau = "Neuf-Mdp-Solide-2026!"
        self.assertEqual(cl.post("/api/mdp", headers=tete, json={"ancien": self.p2["mdp_temporaire"], "nouveau": nouveau, "confirmation": nouveau}).status_code, 200)
        r = cl.post("/api/connexion", json={"login": self.p2["login"], "mdp": nouveau})
        tete = {"Authorization": "Bearer " + r.get_json()["jeton"]}
        g = cl.get("/api/corrections", headers=tete).get_json()
        self.assertEqual(g["nb_ouvertes"], 1)
        i = g["ouvertes"][0]["id"]
        self.assertEqual(cl.post("/api/corrections/traiter", headers=tete, json={"id": i, "reponse": ""}).status_code, 400)
        self.assertEqual(cl.post("/api/corrections/traiter", headers=tete, json={"id": i, "reponse": "Élèves absents à l'évaluation"}).status_code, 200)
        self.assertEqual(cl.get("/api/corrections", headers=tete).get_json()["nb_ouvertes"], 0)


class TestVerification(Fixture):
    def setUp(self):
        super().setUp()
        c = self.conn
        notes.enregistrer_points(c, self.s1, self.maths7, self.per2, {"0000/26": "10", "0001/26": "9"})
        notes.enregistrer_points(c, self.s1, self.maths7, f"X{self.sem1}", {"0000/26": "30", "0001/26": "20", "0002/26": "25"})
        self.cle_s1 = f"S{self.sem1}"

    def ligne(self, r, matricule, id_cc):
        for k in r["classes"]:
            for e in k["eleves"]:
                if e["matricule"] == matricule:
                    return e, next(l for l in e["lignes"] if l["id_cc"] == id_cc)

    def test_par_classe_toutes_les_colonnes(self):
        r = controle_notes.verifier(self.conn, self.dire, self.annee, self.c7)
        self.assertEqual(r["nb_eleves"], 3)
        cles = [c["cle"] for c in r["colonnes"]]
        self.assertIn(self.cle1, cles)
        self.assertIn(f"X{self.sem1}", cles)
        self.assertIn(self.cle_s1, cles)
        self.assertNotIn("A", cles)
        e, l = self.ligne(r, "0000/26", self.maths7)
        self.assertEqual((l["cases"][self.cle1]["obtenu"], l["cases"][self.cle1]["max"]), (15, 20))
        self.assertEqual(l["cases"][f"P{self.per2}"]["obtenu"], 10)
        self.assertEqual(l["cases"][f"X{self.sem1}"]["obtenu"], 30)

    def test_total_semestre_somme_periodes_et_examen(self):
        r = controle_notes.verifier(self.conn, self.dire, self.annee, self.c7, None, "", self.cle_s1)
        self.assertEqual([c["cle"] for c in r["colonnes"]], [self.cle_s1])
        e, l = self.ligne(r, "0000/26", self.maths7)
        x = l["cases"][self.cle_s1]
        self.assertEqual((x["obtenu"], x["max"], x["etat"]), (15 + 10 + 30, 80, "OK"))
        self.assertEqual(e["total"][self.cle_s1]["obtenu"], 15 + 10 + 30 + 10)       # + français (10 en période 1)

    def test_manquant_et_partiel(self):
        r = controle_notes.verifier(self.conn, self.dire, self.annee, self.c7, self.fr7, "", "")
        e, l = self.ligne(r, "0001/26", self.fr7)                                      # pas de point en français pour 0001
        self.assertEqual(l["cases"][self.cle1]["etat"], "MANQUANT")
        e, l = self.ligne(r, "0000/26", self.fr7)
        self.assertEqual(l["cases"][self.cle1]["etat"], "OK")
        self.assertEqual(l["cases"][self.cle_s1]["etat"], "PARTIEL")                   # période 2 et examen sans point
        self.assertIn("Examen", l["cases"][self.cle_s1]["manque"])
        self.assertGreater(r["nb_manquantes"], 0)

    def test_filtre_cours_et_eleve(self):
        r = controle_notes.verifier(self.conn, self.dire, self.annee, None, self.maths7, "amisi", self.cle1)
        self.assertEqual((r["nb_eleves"], r["classes"][0]["eleves"][0]["matricule"]), (1, "0001/26"))
        self.assertEqual(len(r["classes"][0]["eleves"][0]["lignes"]), 1)
        r = controle_notes.verifier(self.conn, self.dire, self.annee, None, None, "0009/26")      # un élève de l'autre classe, sans classe choisie
        self.assertEqual([k["n_classe"] for k in r["classes"]], [self.c8])

    def test_total_et_rang_de_l_eleve(self):
        r = controle_notes.verifier(self.conn, self.dire, self.annee, self.c7, None, "", self.cle1)
        rangs = {e["matricule"]: e["total"][self.cle1]["rang"] for k in r["classes"] for e in k["eleves"]}
        self.assertEqual(rangs["0000/26"], 1)

    def test_examen_sans_objet_pour_cours_a_100_points(self):
        with self.conn:
            self.conn.execute("UPDATE COURS_CLASSE SET MAX_PERIODE = 100 WHERE ID_CC = ?", (self.fr7,))
        r = controle_notes.verifier(self.conn, self.dire, self.annee, self.c7, self.fr7, "", f"X{self.sem1}")
        e, l = self.ligne(r, "0000/26", self.fr7)
        self.assertEqual(l["cases"][f"X{self.sem1}"]["etat"], "SANS_OBJET")

    def test_filtres_obligatoires_et_droits(self):
        with self.assertRaises(ErreurControle):
            controle_notes.verifier(self.conn, self.dire, self.annee)
        with self.assertRaises(ErreurControle):
            controle_notes.verifier(self.conn, self.dire, self.annee, self.c7, None, "", "P99999")
        for s in (self.prefet, self.perc):
            with self.assertRaises(PermissionError):
                controle_notes.verifier(self.conn, s, self.annee, self.c7)

    def test_journal_et_csv(self):
        csv_ = controle_notes.exporter_verification_csv(self.conn, self.dire, self.annee, self.c7, None, "", self.cle_s1)
        self.assertIn("Total (tous les cours)", csv_)
        self.assertIn("55/80", csv_)
        self.assertTrue(self.conn.execute("SELECT 1 FROM JOURNAL WHERE ACTION = 'NOTES_VERIFICATION'").fetchone())

    def test_page_web(self):
        app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])
        cl = app.test_client()
        cl.post("/connexion", data={"login": "dire1", "mdp": MDP})
        base = "/m/etudes_discipline/direction_etudes?f=notes&vue=verif"
        h = cl.get(base).get_data(as_text=True)
        self.assertIn("Vérification des notes", h)
        self.assertIn("Aucune vérification demandée", h)
        h = cl.get(f"{base}&classe={self.c7}&cle={self.cle_s1}").get_data(as_text=True)
        self.assertIn("Kasongo", h)
        self.assertIn("55", h)
        self.assertIn("Total (tous les cours)", h)
        self.assertEqual(cl.get(f"{base}&eleve=amisi").status_code, 200)
        r = cl.get(f"/m/etudes_discipline/direction_etudes/notes/verification.csv?annee={self.annee}&classe={self.c7}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["Content-Type"])


if __name__ == "__main__":
    unittest.main()

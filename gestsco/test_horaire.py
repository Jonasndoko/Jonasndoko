"""Tests de l'élaboration horaire (Direction des études, fonctionnalité 1).
Lancer :  python -m unittest test_horaire"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import config          # noqa: E402
import horaires        # noqa: E402
import migrations      # noqa: E402
import security        # noqa: E402
from horaires import ErreurHoraire   # noqa: E402
from test_notes import Base, MDP     # noqa: E402


class Fixture(Base):
    def setUp(self):
        super().setUp()
        c = self.conn
        for login, role in (("dire1", "DIRECTRICE_ETUDES"), ("prefet1", "PREFET"), ("dird1", "DIRECTEUR_DISCIPLINE"), ("perc1", "PERCEPTEUR")):
            security.creer_utilisateur(c, login, login.title(), role, MDP)
        self.dire, self.prefet, self.dird, self.perc = (security.authentifier(c, x, MDP).session for x in ("dire1", "prefet1", "dird1", "perc1"))
        self.h7 = horaires.creer_horaire(c, self.dire, self.annee, self.c7, "MATIN")
        self.h8 = horaires.creer_horaire(c, self.dire, self.annee, self.c8, "MATIN")

    def placer(self, classe, jour, ordre, cc, s=None):
        return horaires.placer(self.conn, s or self.dire, self.annee, classe, jour, ordre, cc)


class TestHeures(Fixture):
    def test_journee_par_defaut(self):
        p = horaires.parametres(self.conn, self.dire, self.annee)["vacations"]
        matin = [(c["type"], c["debut"], c["fin"]) for c in p["MATIN"]["creneaux"]]
        self.assertEqual(matin, [("COURS", "07:00", "07:45"), ("COURS", "07:45", "08:30"), ("COURS", "08:30", "09:15"), ("COURS", "09:15", "10:00"),
                                 ("COURS", "10:00", "10:45"), ("PAUSE", "10:45", "11:05"), ("COURS", "11:05", "11:50"), ("COURS", "11:50", "12:35")])
        self.assertEqual(p["MATIN"]["nb_cours"], 7)
        self.assertEqual(p["APRES_MIDI"]["creneaux"][0]["debut"], "12:00")
        self.assertEqual(p["APRES_MIDI"]["creneaux"][-1]["fin"], "17:35")

    def test_regler_les_heures_et_recreation(self):
        horaires.definir_parametres(self.conn, self.dire, self.annee, "MATIN", "07:30", 40, 5, 15, 2, recreation_apres=2, duree_recreation=10)
        cr = horaires.parametres(self.conn, self.dire, self.annee)["vacations"]["MATIN"]["creneaux"]
        self.assertEqual(cr[0]["debut"], "07:30")
        self.assertEqual([c["type"] for c in cr], ["COURS", "COURS", "RECREATION", "COURS", "COURS", "COURS", "PAUSE", "COURS", "COURS"])
        for mauvais in (("13:00", 45, 5, 20, 2), ("07:00", 10, 5, 20, 2), ("07:00", 45, 0, 20, 2), ("25:00", 45, 5, 20, 2)):
            with self.assertRaises(ErreurHoraire):
                horaires.definir_parametres(self.conn, self.dire, self.annee, "MATIN", *mauvais)
        with self.assertRaises(ErreurHoraire):                       # la récréation ne peut pas suivre le cours qui précède la pause
            horaires.definir_parametres(self.conn, self.dire, self.annee, "MATIN", "07:00", 45, 5, 20, 2, recreation_apres=5)

    def test_reduire_la_journee_refuse_si_cours_deborde(self):
        self.placer(self.c7, 0, 7, self.maths7)
        with self.assertRaises(ErreurHoraire):
            horaires.definir_parametres(self.conn, self.dire, self.annee, "MATIN", "07:00", 45, 5, 20, 1)


class TestGrille(Fixture):
    def test_placer_remplacer_retirer(self):
        s = self.placer(self.c7, 0, 1, self.maths7)
        g = horaires.grille(self.conn, self.dire, self.annee, self.c7)
        self.assertEqual(g["cases"]["0-1"]["cours"], "Mathématiques")
        self.assertEqual(g["cases"]["0-1"]["id_seance"], s)
        self.placer(self.c7, 0, 1, self.fr7)                           # remplace
        self.assertEqual(horaires.grille(self.conn, self.dire, self.annee, self.c7)["cases"]["0-1"]["cours"], "Français")
        horaires.retirer(self.conn, self.dire, self.annee, horaires.grille(self.conn, self.dire, self.annee, self.c7)["cases"]["0-1"]["id_seance"])
        self.assertEqual(horaires.grille(self.conn, self.dire, self.annee, self.c7)["cases"], {})

    def test_cours_d_une_autre_classe_ou_jour_ferme(self):
        with self.assertRaises(ErreurHoraire):
            self.placer(self.c7, 0, 1, self.maths8)
        with self.assertRaises(ErreurHoraire):
            self.placer(self.c7, 6, 1, self.maths7)                      # dimanche
        with self.assertRaises(ErreurHoraire):
            self.placer(self.c7, 0, 8, self.maths7)                      # 7 cours seulement

    def test_heures_de_la_semaine(self):
        for o in range(1, 5):
            self.placer(self.c7, o % 5, o, self.maths7)
        with self.assertRaises(ErreurHoraire):
            self.placer(self.c7, 4, 6, self.maths7)                      # 4 heures par semaine, déjà 4
        g = horaires.grille(self.conn, self.dire, self.annee, self.c7)
        m = next(c for c in g["cours"] if c["id_cc"] == self.maths7)
        self.assertEqual((m["places"], m["heures"], m["reste"]), (4, 4, 0))

    def test_deplacer_et_echanger(self):
        a = self.placer(self.c7, 0, 1, self.maths7)
        self.placer(self.c7, 1, 2, self.fr7)
        horaires.deplacer(self.conn, self.dire, self.annee, a, 2, 3)
        self.assertEqual(horaires.grille(self.conn, self.dire, self.annee, self.c7)["cases"]["2-3"]["cours"], "Mathématiques")
        r = horaires.deplacer(self.conn, self.dire, self.annee, a, 1, 2)    # case occupée : échange
        self.assertTrue(r["echange"])
        cases = horaires.grille(self.conn, self.dire, self.annee, self.c7)["cases"]
        self.assertEqual((cases["1-2"]["cours"], cases["2-3"]["cours"]), ("Mathématiques", "Français"))


class TestConflits(Fixture):
    def test_meme_professeur_deux_classes_meme_moment(self):
        self.placer(self.c7, 0, 1, self.maths7)                          # m1 en 7ème A le lundi, 1er cours
        with self.assertRaises(ErreurHoraire) as e:
            self.placer(self.c8, 0, 1, self.maths8)                      # m1 aussi en 8ème A : refusé
        self.assertIn("deux endroits", str(e.exception))
        self.assertEqual(horaires.grille(self.conn, self.dire, self.annee, self.c8)["cases"], {})     # rien n'a été enregistré
        self.placer(self.c8, 0, 2, self.maths8)                          # un autre créneau : accepté
        self.assertEqual(horaires.conflits(self.conn, self.dire, self.annee)["conflits"], [])

    def test_conflit_entre_matin_et_apres_midi(self):
        horaires.changer_vacation(self.conn, self.dire, self.annee, self.c8, "APRES_MIDI")
        self.placer(self.c7, 0, 7, self.maths7)                          # 11:50-12:35
        with self.assertRaises(ErreurHoraire):
            self.placer(self.c8, 0, 1, self.maths8)                      # 12:00-12:45 : chevauchement
        self.placer(self.c8, 0, 2, self.maths8)                          # 12:45-13:30 : libre

    def test_changer_de_professeur_qui_cree_un_conflit_est_refuse(self):
        self.placer(self.c7, 0, 1, self.maths7)                          # m1
        self.placer(self.c7, 1, 1, self.fr7)                             # m2 mais un autre jour
        s = self.placer(self.c8, 2, 1, self.maths8)
        horaires.deplacer(self.conn, self.dire, self.annee, s, 1, 1)     # m1 mardi : pas de conflit (m2 est en 7ème A mardi, m1 ne l'est pas)
        with self.assertRaises(ErreurHoraire):
            horaires.affecter_professeur(self.conn, self.dire, self.annee, self.maths8, self.m2)    # m2 déjà en 7ème A mardi cours 1
        self.assertEqual(self.conn.execute("SELECT MATRICULE_PROF FROM COURS_CLASSE WHERE ID_CC = ?", (self.maths8,)).fetchone()[0], self.m1)

    def test_deplacement_qui_cree_un_conflit_est_refuse(self):
        self.placer(self.c7, 0, 1, self.maths7)
        s = self.placer(self.c8, 0, 2, self.maths8)
        with self.assertRaises(ErreurHoraire):
            horaires.deplacer(self.conn, self.dire, self.annee, s, 0, 1)
        self.assertEqual(horaires.grille(self.conn, self.dire, self.annee, self.c8)["cases"]["0-2"]["cours"], "Mathématiques")

    def test_cours_sans_professeur_signale(self):
        horaires.affecter_professeur(self.conn, self.dire, self.annee, self.fr7, "")
        self.placer(self.c7, 0, 1, self.fr7)
        g = horaires.grille(self.conn, self.dire, self.annee, self.c7)
        self.assertTrue(any("aucun professeur" in a for a in g["alertes"]))
        self.assertEqual(len(horaires.conflits(self.conn, self.dire, self.annee)["sans_professeur"]), 1)


class TestPublication(Fixture):
    def test_publier_et_consulter(self):
        self.placer(self.c7, 0, 1, self.maths7)
        self.assertEqual(horaires.classes(self.conn, self.prefet, self.annee)["classes"], [])           # brouillon : invisible du Préfet
        with self.assertRaises(PermissionError):
            horaires.grille(self.conn, self.perc, self.annee, self.c7)
        horaires.publier(self.conn, self.dire, self.annee, self.c7)
        l = horaires.classes(self.conn, self.prefet, self.annee)["classes"]
        self.assertEqual([x["n_classe"] for x in l], [self.c7])
        g = horaires.grille(self.conn, self.dird, self.annee, self.c7)
        self.assertFalse(g["complet"])
        self.assertEqual(g["cases"]["0-1"]["cours"], "Mathématiques")
        for ecriture in (lambda: self.placer(self.c7, 0, 2, self.fr7, self.prefet), lambda: horaires.publier(self.conn, self.prefet, self.annee, self.c7)):
            with self.assertRaises(PermissionError):
                ecriture()

    def test_publication_refusee_si_vide_ou_sans_professeur(self):
        with self.assertRaises(ErreurHoraire):
            horaires.publier(self.conn, self.dire, self.annee, self.c7)
        horaires.affecter_professeur(self.conn, self.dire, self.annee, self.fr7, "")
        self.placer(self.c7, 0, 1, self.fr7)
        with self.assertRaises(ErreurHoraire):
            horaires.publier(self.conn, self.dire, self.annee, self.c7)

    def test_publier_tout_et_retrait(self):
        self.placer(self.c7, 0, 1, self.maths7)
        r = horaires.publier_tout(self.conn, self.dire, self.annee)
        self.assertEqual(len(r["publies"]), 1)
        self.assertEqual(len(r["refuses"]), 1)                           # la 8ème A est vide
        with self.assertRaises(ErreurHoraire):
            horaires.supprimer_horaire(self.conn, self.dire, self.annee, self.c7)   # publié : on le retire d'abord
        horaires.retirer_publication(self.conn, self.dire, self.annee, self.c7)
        self.assertEqual(horaires.classes(self.conn, self.prefet, self.annee)["classes"], [])
        horaires.supprimer_horaire(self.conn, self.dire, self.annee, self.c7)
        self.assertFalse(horaires.grille(self.conn, self.dire, self.annee, self.c7)["existe"])

    def test_horaire_du_professeur(self):
        self.placer(self.c7, 0, 1, self.maths7)
        self.placer(self.c8, 0, 2, self.maths8)
        v = horaires.horaire_professeur(self.conn, self.dire, self.annee, self.m1)
        self.assertEqual(v["nb_seances"], 2)
        self.assertEqual([(l["debut"], l["cases"][0][0]["classe"]) for l in v["lignes"]], [("07:00", "7ème A"), ("07:45", "8ème A")])
        self.assertEqual(horaires.horaire_professeur(self.conn, self.prefet, self.annee, self.m1)["nb_seances"], 0)    # rien de publié
        horaires.publier(self.conn, self.dire, self.annee, self.c7)
        self.assertEqual(horaires.horaire_professeur(self.conn, self.prefet, self.annee, self.m1)["nb_seances"], 1)
        # le professeur lui-même ne voit que le publié
        mien = horaires.mon_horaire(self.conn, self.s1, self.annee)             # self.s1 : compte du professeur m1
        self.assertEqual(mien["nb_seances"], 1)
        with self.assertRaises(PermissionError):
            horaires.mon_horaire(self.conn, self.dire, self.annee)       # pas un compte professeur


class TestDroits(Fixture):
    def test_droits_par_defaut_de_la_directrice(self):
        for d in ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION"):
            self.assertTrue(horaires.peut(self.conn, self.dire, d), d)
        self.assertFalse(horaires.peut(self.conn, self.prefet))
        self.assertFalse(horaires.peut(self.conn, self.dird))

    def test_chaque_droit_est_exige(self):
        a = self.placer(self.c7, 0, 1, self.maths7)
        for droit, appel in (("AJOUT", lambda: self.placer(self.c7, 1, 1, self.fr7)),
                             ("MODIFICATION", lambda: horaires.deplacer(self.conn, self.dire, self.annee, a, 3, 3)),
                             ("SUPPRESSION", lambda: horaires.retirer(self.conn, self.dire, self.annee, a))):
            with self.conn:
                self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'direction_etudes' AND DROIT = ?", (self.dire.id_user, droit))
            with self.assertRaises(PermissionError, msg=droit):
                appel()

    def test_migration_14_donne_les_droits_aux_comptes_existants(self):
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'direction_etudes' AND DROIT IN ('MODIFICATION','SUPPRESSION')",
                              (self.dire.id_user,))
        migrations._mig_horaire_direction(self.conn)
        self.assertTrue(horaires.peut(self.conn, self.dire, "SUPPRESSION"))
        self.assertGreaterEqual(migrations.VERSION_SCHEMA, 14)

    def test_primaire_refuse(self):
        with self.conn:
            self.conn.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU, SECTION) VALUES ('PRI', 'Primaire', 'PRIMAIRE')")
            self.conn.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('3ème prim', 'PRI', '3ème', 'A')")
        cp = self.conn.execute("SELECT MAX(N_CLASSE) FROM CLASSE").fetchone()[0]
        with self.assertRaises(PermissionError):
            horaires.creer_horaire(self.conn, self.dire, self.annee, cp, "MATIN")
        self.assertNotIn(cp, [k["n_classe"] for k in horaires.classes(self.conn, self.dire, self.annee)["classes"]])

    def test_journal(self):
        self.placer(self.c7, 0, 1, self.maths7)
        horaires.publier(self.conn, self.dire, self.annee, self.c7)
        actions = {l[0] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")}
        self.assertTrue({"HORAIRE_CREE", "HORAIRE_SEANCE_PLACEE", "HORAIRE_PUBLIE"} <= actions)


if __name__ == "__main__":
    unittest.main()


class TestWeb(Fixture):
    """Pages et formulaires : la Directrice élabore, les autres consultent le publié."""

    def setUp(self):
        super().setUp()
        import app_web
        chemin = self.conn.execute("PRAGMA database_list").fetchone()[2]
        self.app = app_web.creer_app(chemin)
        self.clients = {}
        for login in ("dire1", "prefet1", "dird1", "perc1"):
            cl = self.app.test_client()
            self.assertEqual(cl.post("/connexion", data={"login": login, "mdp": MDP}).status_code, 302)
            self.clients[login] = cl
        cl = self.app.test_client()
        r = cl.post("/api/connexion", json={"login": self.p1["login"], "mdp": self.p1["mdp_temporaire"]})
        self.jeton = r.get_json()["jeton"]
        r = cl.post("/api/mdp", json={"ancien": self.p1["mdp_temporaire"], "nouveau": MDP, "confirmation": MDP}, headers={"Authorization": "Bearer " + self.jeton})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.base = {"annee": self.annee, "vue": "classes", "classe": str(self.c7)}

    def post(self, login, action, **champs):
        return self.clients[login].post(f"/m/etudes_discipline/direction_etudes/horaire/{action}", data={**self.base, **champs})

    def get(self, login, url):
        r = self.clients[login].get(url)
        return r.status_code, r.get_data(as_text=True)

    def test_la_page_est_la_premiere_fonctionnalite(self):
        code, html = self.get("dire1", "/m/etudes_discipline/direction_etudes")
        self.assertEqual(code, 200)
        for titre in ("Élaboration horaire", "Présences et heures des professeurs", "Rapport au Préfet"):
            self.assertIn(f"<span>{titre}</span>", html)                   # boutons de l'Espace Études (plus d'onglets numérotés)
        self.assertEqual(html.count('class="em-btn '), 14)
        self.assertIn('class="em-btn actif"', html)
        for groupe in ("Organisation des cours", "Suivi pédagogique", "Présences", "Listes et communication"):
            self.assertIn(f'<p class="em-titre">{groupe}</p>', html)
        self.assertNotIn("Gestion des études et discipline", html)       # plus de lien de retour vers l'accueil de la discipline
        self.assertIn("7ème A", html)
        self.assertNotIn("Nouveau rapport", html)
        self.assertIn("Nouveau rapport", self.get("dire1", "/m/etudes_discipline/direction_etudes?f=rapport")[1])

    def test_grille_placer_conflit_publier(self):
        code, html = self.get("dire1", f"/m/etudes_discipline/direction_etudes?f=horaire&annee={self.annee}&classe={self.c7}")
        self.assertEqual(code, 200)
        for t in ("Lundi", "Vendredi", "07:00 – 07:45", "Pause", "11:50 – 12:35", "Placer un cours"):
            self.assertIn(t, html)
        self.assertEqual(self.post("dire1", "placer", jour="0", ordre="1", id_cc=str(self.maths7)).status_code, 302)
        self.assertEqual(self.post("dire1", "placer", jour="0", ordre="1", id_cc=str(self.maths8), classe=str(self.c8)).status_code, 400)
        r = self.post("dire1", "placer", jour="0", ordre="1", id_cc=str(self.maths8), classe=str(self.c8))
        self.assertIn("deux endroits", r.get_data(as_text=True))
        self.assertEqual(self.post("dire1", "publier").status_code, 302)
        self.assertIn("Retirer de la publication", self.get("dire1", f"/m/etudes_discipline/direction_etudes?f=horaire&classe={self.c7}")[1])

    def test_les_autres_ne_peuvent_pas_ecrire(self):
        for login in ("prefet1", "dird1", "perc1"):
            self.assertEqual(self.post(login, "placer", jour="0", ordre="1", id_cc=str(self.maths7)).status_code, 403, login)
        self.assertEqual(self.post("dire1", "inconnue").status_code, 404)
        r = self.clients["dire1"].post("/m/etudes_discipline/direction_etudes/horaire/placer", data={**self.base, "jour": "0", "ordre": "1", "id_cc": str(self.maths7)},
                                        headers={"Origin": "https://autre-site.example"})
        self.assertEqual(r.status_code, 403)

    def test_consultation_publiee_seulement(self):
        self.post("dire1", "placer", jour="1", ordre="2", id_cc=str(self.maths7))
        self.assertNotIn("7ème A", self.get("prefet1", "/m/etudes_discipline/horaires")[1].split("Par professeur")[0])
        self.assertEqual(self.get("prefet1", f"/m/etudes_discipline/horaires/classe/{self.c7}")[0], 404)       # brouillon
        self.assertEqual(self.get("perc1", "/m/etudes_discipline/horaires")[0], 403)
        self.post("dire1", "publier")
        code, html = self.get("prefet1", "/m/etudes_discipline/horaires")
        self.assertIn("7ème A", html)
        code, html = self.get("dird1", f"/m/etudes_discipline/horaires/classe/{self.c7}")
        self.assertEqual(code, 200)
        self.assertIn("Mathématiques", html)
        self.assertIn("window.print()", html)
        code, html = self.get("dird1", f"/m/etudes_discipline/horaires/professeur/{self.m1}")
        self.assertIn("7ème A", html)
        self.assertEqual(self.get("perc1", f"/m/etudes_discipline/horaires/classe/{self.c7}")[0], 403)
        self.assertIn("Consulter les horaires publiés", self.get("prefet1", "/m/etudes_discipline/prefecture")[1])

    def test_vues_heures_professeurs_conflits(self):
        self.post("dire1", "placer", jour="0", ordre="1", id_cc=str(self.maths7))
        for vue, texte in (("heures", "Début de la journée"), ("professeurs", "Professeur"), ("conflits", "Aucun conflit")):
            code, html = self.get("dire1", f"/m/etudes_discipline/direction_etudes?f=horaire&vue={vue}&annee={self.annee}&prof={self.m1}")
            self.assertEqual(code, 200, vue)
            self.assertIn(texte, html, vue)
        self.assertEqual(self.post("dire1", "heures", vacation="MATIN", debut="07:30", duree_cours="40", nb_avant="5", duree_pause="15", nb_apres="2").status_code, 302)
        self.assertIn("07:30", self.get("dire1", "/m/etudes_discipline/direction_etudes?f=horaire&vue=heures")[1])

    def test_le_professeur_voit_son_horaire_publie(self):
        def mien():
            r = self.app.test_client().get("/api/horaire/mien", headers={"Authorization": "Bearer " + self.jeton})
            return r.status_code, r.get_json()
        self.post("dire1", "placer", jour="0", ordre="3", id_cc=str(self.maths7))
        self.assertEqual(mien()[1]["nb_seances"], 0)                         # brouillon : rien
        self.post("dire1", "publier")
        code, j = mien()
        self.assertEqual(code, 200)
        self.assertEqual((j["nb_seances"], j["lignes"][0]["debut"], j["lignes"][0]["cases"]["0"][0]["classe"]), (1, "08:30", "7ème A"))
        from page_professeur import PAGE
        self.assertIn('data-mode="horaire"', PAGE)

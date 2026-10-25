"""Tests de « Présences et heures des professeurs » (Direction des études, fonctionnalité 2).
Lancer :  python -m unittest test_heures_profs"""
import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import config          # noqa: E402
import heures_profs    # noqa: E402
import horaires        # noqa: E402
import personnel       # noqa: E402
import presences       # noqa: E402
from horaires import ErreurHoraire   # noqa: E402
from test_horaire import Fixture     # noqa: E402
from test_notes import MDP, agent    # noqa: E402

LUNDI, MARDI, MERCREDI = "2026-10-05", "2026-10-06", "2026-10-07"      # semaine passée : lundi 5 au vendredi 9 octobre 2026
SEMAINE = (LUNDI, "2026-10-09")


class Base2(Fixture):
    """m1 : lundi 07:00-07:45 et 07:45-08:30 en 7ème A, 08:30-09:15 en 8ème A, mardi 07:00-07:45 en 7ème A (180 min par semaine).
    m2 : mardi 07:45-08:30 et mercredi 07:00-07:45 en 7ème A (90 min). Les deux classes sont publiées."""

    def setUp(self):
        super().setUp()
        self.placer(self.c7, 0, 1, self.maths7)
        self.placer(self.c7, 0, 2, self.maths7)
        self.placer(self.c8, 0, 3, self.maths8)
        self.placer(self.c7, 1, 1, self.maths7)
        self.placer(self.c7, 1, 2, self.fr7)
        self.placer(self.c7, 2, 1, self.fr7)
        horaires.publier(self.conn, self.dire, self.annee, self.c7)
        horaires.publier(self.conn, self.dire, self.annee, self.c8)

    def pointer(self, matricule, jour, statut, heure="", motif=""):
        presences.enregistrer_pointage(self.conn, self.admin, matricule, jour, statut, heure, motif)

    def liste(self, **plus):
        args = dict(annee=self.annee, debut_texte=SEMAINE[0], fin_texte=SEMAINE[1])
        args.update(plus)
        return heures_profs.liste(self.conn, self.dire, **args)

    def prof(self, matricule, **plus):
        return next(p for p in self.liste(**plus)["profs"] if p["matricule"] == matricule)

    def chiffres(self, p):
        return {k: p[k] for k in ("prevu", "donne", "manque", "justifie", "non_renseigne", "a_venir")}


class TestCalcul(Base2):
    def test_sans_pointage_tout_est_non_renseigne(self):
        p = self.prof(self.m1)
        self.assertEqual(self.chiffres(p), {"prevu": 180, "donne": 0, "manque": 0, "justifie": 0, "non_renseigne": 180, "a_venir": 0})
        self.assertIsNone(p["taux"])                                       # l'absence n'est jamais devinée
        self.assertEqual((p["hebdo"], p["prevu_txt"], p["nb_prevues"], p["nb_non_renseignees"]), (180, "3 h 00", 4, 4))
        self.assertEqual(self.chiffres(self.prof(self.m2)), {"prevu": 90, "donne": 0, "manque": 0, "justifie": 0, "non_renseigne": 90, "a_venir": 0})

    def test_present_et_absent(self):
        self.pointer(self.m1, LUNDI, "PRESENT")
        self.pointer(self.m1, MARDI, "ABSENT", motif="Malade")
        p = self.prof(self.m1)
        self.assertEqual(self.chiffres(p), {"prevu": 180, "donne": 135, "manque": 45, "justifie": 0, "non_renseigne": 0, "a_venir": 0})
        self.assertEqual(p["taux"], 75)                                    # 135 / (135 + 45)
        self.assertEqual((p["nb_donnees"], p["nb_manquees"]), (3, 1))
        self.assertEqual(p["donne_txt"], "2 h 15")

    def test_retard_en_milieu_de_cours(self):
        self.pointer(self.m1, LUNDI, "RETARD", "07:40")                    # le 1er cours (07:00-07:45) est donné pendant 5 min sur 45
        p = self.prof(self.m1)
        self.assertEqual((p["donne"], p["manque"], p["nb_partielles"], p["nb_donnees"]), (5 + 45 + 45, 40, 1, 2))

    def test_present_avec_heure_d_arrivee_notee(self):
        self.pointer(self.m1, LUNDI, "PRESENT", "07:20")                   # « présent » pour l'école (avant 7 h 30), mais en retard au cours de 7 h
        p = self.prof(self.m1)
        self.assertEqual((p["donne"], p["manque"], p["nb_partielles"]), (25 + 45 + 45, 20, 1))
        self.pointer(self.m1, MARDI, "PRESENT")                            # sans heure notée : séance donnée
        self.assertEqual(self.prof(self.m1)["donne"], 25 + 45 + 45 + 45)

    def test_retard_apres_un_cours_entier(self):
        self.pointer(self.m1, LUNDI, "RETARD", "08:00")                    # 07:00-07:45 manqué ; 07:45-08:30 : 30 min données, 15 manquées
        p = self.prof(self.m1)
        self.assertEqual((p["donne"], p["manque"], p["nb_manquees"], p["nb_partielles"]), (30 + 45, 45 + 15, 1, 1))

    def test_permission_et_conge_sont_justifies(self):
        presences.accorder_autorisation(self.conn, self.admin, self.m1, "PERMISSION", "Raison familiale", MARDI, MARDI)
        p = self.prof(self.m1)
        self.assertEqual((p["justifie"], p["manque"], p["nb_justifiees"], p["non_renseigne"]), (45, 0, 1, 135))
        self.pointer(self.m1, LUNDI, "PRESENT")
        p = self.prof(self.m1)
        self.assertEqual((p["donne"], p["justifie"], p["taux"]), (135, 45, 100))      # la permission ne pèse pas sur le taux

    def test_jour_non_travaille_et_engagement(self):
        presences.ajouter_jour_ferme(self.conn, self.admin, MARDI, "Fête")
        self.assertEqual(self.prof(self.m1)["prevu"], 135)                 # le mardi ne compte pas
        self.assertEqual(self.prof(self.m2)["prevu"], 45)                  # seul le mercredi reste
        with self.conn:
            self.conn.execute("UPDATE PERSONNEL SET DATE_ENGAGEMENT = '2026-10-08' WHERE MATRICULE = ?", (self.m2,))
        self.assertEqual(self.prof(self.m2)["prevu"], 0)                   # avant l'engagement : rien n'est dû

    def test_jours_a_venir(self):
        lundi = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 + 7)            # un lundi dans le futur
        r = heures_profs.liste(self.conn, self.dire, self.annee, lundi.isoformat(), (lundi + timedelta(days=4)).isoformat())
        p = next(x for x in r["profs"] if x["matricule"] == self.m1)
        self.assertEqual((p["a_venir"], p["donne"], p["manque"], p["non_renseigne"], p["nb_a_venir"]), (180, 0, 0, 0, 4))
        self.assertTrue(r["a_venir"])

    def test_seuls_les_horaires_publies_comptent(self):
        horaires.retirer_publication(self.conn, self.dire, self.annee, self.c8)
        r = self.liste()
        self.assertEqual(r["classes_non_publiees"], ["8ème A"])
        self.assertEqual(next(p for p in r["profs"] if p["matricule"] == self.m1)["prevu"], 135)      # sans le cours de la 8ème A
        horaires.retirer_publication(self.conn, self.dire, self.annee, self.c7)
        self.assertEqual(self.liste()["profs"], [])

    def test_confirmation_et_incoherence_par_la_presence_des_eleves(self):
        with self.conn:
            for jour in (LUNDI, MARDI):
                self.conn.execute("INSERT INTO PRESENCE_ELEVE (ID_CC, DATE_COURS, MATRICULE, STATUT, DATE_MODIF, MODIFIE_PAR) "
                                  "VALUES (?,?,?,'P','2026-10-05T00:00:00','essai')", (self.maths7, jour, "0000/26"))
        self.pointer(self.m1, LUNDI, "PRESENT")
        self.pointer(self.m1, MARDI, "ABSENT")
        p = self.prof(self.m1)
        self.assertEqual((p["confirme"], p["incoherentes"]), (2, 1))       # lundi : 2 séances de maths 7ème confirmées ; mardi : élèves pointés malgré l'absence

    def test_totaux_et_recherche(self):
        self.pointer(self.m1, LUNDI, "PRESENT")
        self.pointer(self.m2, MARDI, "ABSENT")
        r = self.liste()
        self.assertEqual((r["totaux"]["prevu"], r["totaux"]["donne"], r["totaux"]["manque"]), (270, 135, 45))
        self.assertEqual([p["nom"] for p in r["profs"]], sorted((p["nom"] for p in r["profs"]), key=str.lower))
        r = self.liste(recherche="banza")
        self.assertEqual([p["matricule"] for p in r["profs"]], [self.m2])
        self.assertEqual(r["totaux"]["prevu"], 90)

    def test_aucune_ecriture_sauf_le_journal(self):
        avant = {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("PRESENCE", "AUTORISATION_ABSENCE", "HORAIRE_SEANCE", "COURS_CLASSE")}
        self.liste()
        heures_profs.detail(self.conn, self.dire, self.annee, self.m1, *SEMAINE)
        heures_profs.exporter_csv(self.conn, self.dire, self.annee, *SEMAINE)
        apres = {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in avant}
        self.assertEqual(avant, apres)


class TestDetail(Base2):
    def test_detail_par_cours_et_par_seance(self):
        self.pointer(self.m1, LUNDI, "RETARD", "07:40")
        self.pointer(self.m1, MARDI, "ABSENT", motif="Malade")
        d = heures_profs.detail(self.conn, self.dire, self.annee, self.m1, *SEMAINE)
        p = d["prof"]
        self.assertEqual([(k["classe"], k["cours"], k["prevu"]) for k in p["cours"]], [("7ème A", "Mathématiques", 135), ("8ème A", "Mathématiques", 45)])
        self.assertEqual([(l["iso"], l["debut"], l["classe"], l["code"]) for l in p["lignes"]],
                         [(LUNDI, "07:00", "7ème A", "PARTIEL"), (LUNDI, "07:45", "7ème A", "DONNE"), (LUNDI, "08:30", "8ème A", "DONNE"),
                          (MARDI, "07:00", "7ème A", "MANQUE")])
        self.assertEqual((p["lignes"][0]["donne"], p["lignes"][0]["manque"]), ("0 h 05", "0 h 40"))
        self.assertEqual((p["lignes"][0]["motif"], p["lignes"][3]["motif"]), ("arrivé à 07:40", "Malade"))
        self.assertEqual(p["lignes"][0]["nom_jour"], "Lundi")

    def test_erreurs(self):
        with self.assertRaises(ErreurHoraire):
            heures_profs.detail(self.conn, self.dire, self.annee, "9999/99", *SEMAINE)
        sans_cours = personnel.enregistrer_agent(self.conn, self.admin, agent(nom="sans", prenom="cours"))["matricule"]
        with self.assertRaises(ErreurHoraire):                                 # l'agent existe mais n'a aucune séance dans un horaire publié
            heures_profs.detail(self.conn, self.dire, self.annee, sans_cours, *SEMAINE)


class TestPeriode(Base2):
    def test_periode(self):
        for debut, fin in ((SEMAINE[1], SEMAINE[0]), ("pas une date", SEMAINE[1]), ("2026-01-01", "2027-12-31")):
            with self.assertRaises(ErreurHoraire):
                self.liste(debut_texte=debut, fin_texte=fin)
        r = self.liste(debut_texte="", fin_texte="")                          # vide : le mois en cours
        d, f = heures_profs.periode_par_defaut()
        self.assertEqual((r["debut_iso"], r["fin_iso"]), (d, f))
        self.assertEqual(self.liste(debut_texte="05/10/2026", fin_texte="09/10/2026")["debut_iso"], LUNDI)
        self.assertEqual([x[0] for x in heures_profs.raccourcis()], ["Cette semaine", "Ce mois", "Mois précédent"])

    def test_formater(self):
        self.assertEqual([heures_profs.formater(m) for m in (0, 45, 60, 135, 600)], ["0 h 00", "0 h 45", "1 h 00", "2 h 15", "10 h 00"])


class TestDroitsEtJournal(Base2):
    def test_droits(self):
        for s in (self.prefet, self.dird, self.perc):
            for appel in (lambda: heures_profs.liste(self.conn, s, self.annee, *SEMAINE), lambda: heures_profs.detail(self.conn, s, self.annee, self.m1, *SEMAINE),
                          lambda: heures_profs.exporter_csv(self.conn, s, self.annee, *SEMAINE)):
                with self.assertRaises(PermissionError):
                    appel()
        self.assertTrue(heures_profs.liste(self.conn, self.admin, self.annee, *SEMAINE)["profs"])
        with self.conn:                                                         # la Directrice perd sa Lecture : plus rien ne s'affiche
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'direction_etudes' AND DROIT = 'LECTURE'", (self.dire.id_user,))
        with self.assertRaises(PermissionError):
            heures_profs.liste(self.conn, self.dire, self.annee, *SEMAINE)

    def test_journal(self):
        self.liste()
        heures_profs.detail(self.conn, self.dire, self.annee, self.m1, *SEMAINE)
        heures_profs.exporter_csv(self.conn, self.dire, self.annee, *SEMAINE)
        actions = [l[0] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")]
        for a in ("HEURES_PROFS_CONSULTEES", "HEURES_PROF_DETAIL_CONSULTE", "HEURES_PROFS_EXPORTEES"):
            self.assertIn(a, actions)
            self.assertIn(a, __import__("audit").ACTIONS)

    def test_csv(self):
        self.pointer(self.m1, LUNDI, "PRESENT")
        brut = heures_profs.exporter_csv(self.conn, self.dire, self.annee, *SEMAINE)
        self.assertTrue(brut.startswith("﻿".encode("utf-8")))
        lignes = brut.decode("utf-8-sig").split("\r\n")
        self.assertTrue(lignes[0].startswith("Matricule;Professeur;Heures par semaine"))
        m1 = next(l for l in lignes if l.startswith(self.m1)).split(";")
        self.assertEqual((m1[3], m1[4]), ("3,00", "2,25"))                     # prévues 3 h, données 2,25 h
        self.assertTrue(lignes[-2].startswith(";TOTAL;"))


class TestWeb(Base2):
    def setUp(self):
        super().setUp()
        import app_web
        chemin = self.conn.execute("PRAGMA database_list").fetchone()[2]
        self.app = app_web.creer_app(chemin)
        self.clients = {}
        for login in ("dire1", "prefet1", "dird1"):
            cl = self.app.test_client()
            self.assertEqual(cl.post("/connexion", data={"login": login, "mdp": MDP}).status_code, 302)
            self.clients[login] = cl
        self.pointer(self.m1, LUNDI, "PRESENT")
        self.pointer(self.m1, MARDI, "ABSENT")
        self.q = f"annee={self.annee}&du={SEMAINE[0]}&au={SEMAINE[1]}"

    def get(self, login, url):
        r = self.clients[login].get(url)
        return r.status_code, r.get_data(as_text=True)

    def test_fonctionnalites_de_la_direction(self):
        self.assertEqual([c for c, _t, _d in config.FONCTIONNALITES_DIRECTIONS["direction_etudes"]], ["horaire", "heures", "notes", "bulletins", "proclamation", "statistiques", "passage", "calendrier", "cours", "programme", "enseignants", "presence_eleves", "listes", "rapport"])

    def test_page_liste_et_detail(self):
        code, page = self.get("dire1", f"/m/etudes_discipline/direction_etudes?f=heures&{self.q}")
        self.assertEqual(code, 200)
        for texte in ("Présences et heures des professeurs", "Heures données", "2 h 15", "75 %", "Imprimer", "Exporter (CSV)"):
            self.assertIn(texte, page)
        code, page = self.get("dire1", f"/m/etudes_discipline/direction_etudes?f=heures&prof={self.m1}&{self.q}")
        self.assertEqual(code, 200)
        for texte in ("Par cours", "Séance par séance", "Mathématiques", "Manqué", "Tous les professeurs"):
            self.assertIn(texte, page)

    def test_erreur_de_periode_affichee(self):
        code, page = self.get("dire1", f"/m/etudes_discipline/direction_etudes?f=heures&annee={self.annee}&du={SEMAINE[1]}&au={SEMAINE[0]}")
        self.assertEqual(code, 200)
        self.assertIn("avant la date de début", page)

    def test_impression_et_csv(self):
        code, page = self.get("dire1", f"/m/etudes_discipline/direction_etudes/heures/impression?{self.q}")
        self.assertEqual(code, 200)
        self.assertIn("Présences et heures des professeurs", page)
        self.assertIn("window.print()", page)
        code, page = self.get("dire1", f"/m/etudes_discipline/direction_etudes/heures/impression?{self.q}&prof={self.m1}")
        self.assertIn("Séance par séance", page)
        r = self.clients["dire1"].get(f"/m/etudes_discipline/direction_etudes/heures/export.csv?{self.q}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["Content-Type"])
        self.assertIn("attachment", r.headers["Content-Disposition"])
        self.assertEqual(self.get("dire1", f"/m/etudes_discipline/direction_etudes/heures/impression?{self.q}&prof=ZZ")[0], 404)

    def test_acces_refuse_aux_autres_postes(self):
        for login in ("prefet1", "dird1"):
            for url in (f"/m/etudes_discipline/direction_etudes?f=heures&{self.q}", f"/m/etudes_discipline/direction_etudes/heures/impression?{self.q}",
                        f"/m/etudes_discipline/direction_etudes/heures/export.csv?{self.q}"):
                self.assertEqual(self.get(login, url)[0], 403, (login, url))
        anonyme = self.app.test_client()
        self.assertEqual(anonyme.get(f"/m/etudes_discipline/direction_etudes/heures/export.csv?{self.q}").status_code, 302)


if __name__ == "__main__":
    unittest.main()

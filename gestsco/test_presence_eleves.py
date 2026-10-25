"""Tests de la présence des élèves aux cours (presence_eleves.py) : pointage, règle de la journée, cloisonnement, directions.
Lancer :  python test_presence_eleves.py"""
import unittest

import cours
import droits
import presence_eleves as pe
import security
from test_notes import Base, MDP

J1, J2 = "15/09/2026", "16/09/2026"


class TestPresenceEleves(Base):
    def marquer(self, session, cc, jour, matricule, statut):
        return pe.marquer(self.conn, session, cc, jour, matricule, statut)

    def test_le_professeur_pointe_et_voit_la_liste(self):
        l = pe.liste(self.conn, self.s1, self.maths7, J1)
        self.assertEqual([e["nom_complet"][:6] for e in l["eleves"]], ["Amisi ", "Kasong", "Zola X"])
        self.assertEqual((l["presents"], l["absents"], l["non_pointes"]), (0, 0, 3))
        self.marquer(self.s1, self.maths7, J1, "0000/26", "P")
        self.marquer(self.s1, self.maths7, J1, "0001/26", "A")
        l = pe.liste(self.conn, self.s1, self.maths7, J1)
        self.assertEqual((l["presents"], l["absents"], l["non_pointes"]), (1, 1, 1))
        self.marquer(self.s1, self.maths7, J1, "0001/26", "")                      # retrait du pointage
        self.assertEqual(pe.liste(self.conn, self.s1, self.maths7, J1)["non_pointes"], 2)
        self.assertIn("PRESENCE_ELEVE_MARQUEE", self.actions())

    def test_tous_presents_ne_touche_pas_aux_absents(self):
        self.marquer(self.s1, self.maths7, J1, "0002/26", "A")
        self.assertEqual(pe.tous_presents(self.conn, self.s1, self.maths7, J1)["faits"], 2)
        l = pe.liste(self.conn, self.s1, self.maths7, J1)
        self.assertEqual((l["presents"], l["absents"]), (2, 1))
        self.assertEqual(pe.tous_presents(self.conn, self.s1, self.maths7, J1)["faits"], 0)

    def test_regle_de_la_journee_present_seulement_s_il_a_assiste_a_tous_les_cours(self):
        pe.tous_presents(self.conn, self.s1, self.maths7, J1)                       # maths : tous présents
        self.marquer(self.s2, self.fr7, J1, "0000/26", "P")
        self.marquer(self.s2, self.fr7, J1, "0001/26", "A")                         # absent en français
        self.marquer(self.s2, self.fr7, J1, "0002/26", "P")
        # le professeur ne voit que SES heures de cours : ni la journée, ni le pointage des collègues
        par = {e["matricule"]: e for e in pe.liste(self.conn, self.s1, self.maths7, J1)["eleves"]}
        self.assertEqual(par["0001/26"]["statut"], "P")                              # présent en maths
        self.assertTrue(all("journee" not in e and "manques" not in e for e in par.values()))
        # la direction (vue de toutes les classes) voit la journée : absent en français = absent pour la journée
        d = {e["matricule"]: e for e in pe.eleves_de_la_classe(self.conn, self.admin, self.annee, self.c7, J1)["eleves"]}
        self.assertEqual(d["0000/26"]["journee"], "P")
        self.assertEqual(d["0001/26"]["journee"], "A")
        self.assertEqual(d["0001/26"]["manques"], ["Français"])
        # un autre jour : rien pointé -> journée non renseignée
        self.assertTrue(all(e["journee"] == "" for e in pe.eleves_de_la_classe(self.conn, self.admin, self.annee, self.c7, J2)["eleves"]))

    def test_cloisonnement(self):
        with self.assertRaises(PermissionError):
            self.marquer(self.s2, self.maths7, J1, "0000/26", "P")                  # cours d'un collègue
        with self.assertRaises(PermissionError):
            pe.liste(self.conn, self.s2, self.maths7, J1)
        with self.assertRaises(PermissionError):
            pe.historique(self.conn, self.s2, self.maths7)
        with self.assertRaises(PermissionError):
            self.marquer(self.s1, self.maths7, J1, "0009/26", "P")                  # élève d'une autre classe
        with self.assertRaises(PermissionError):
            pe.classes_du_jour(self.conn, self.s1, self.annee, J1)                  # le professeur n'a pas la vue des directions
        with self.assertRaises(PermissionError):
            pe.liste(self.conn, self.admin, self.maths7, J1)                        # l'administrateur n'est pas un professeur

    def test_dates_et_statuts_refuses(self):
        for jour in ("01/01/2099", "01/01/2025", "31/02/2026", "abc"):
            with self.assertRaises(pe.ErreurPresence if jour in ("01/01/2099", "01/01/2025") else Exception):
                self.marquer(self.s1, self.maths7, jour, "0000/26", "P")
        with self.assertRaises(pe.ErreurPresence):
            self.marquer(self.s1, self.maths7, J1, "0000/26", "X")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PRESENCE_ELEVE").fetchone()[0], 0)

    def test_historique_par_classe(self):
        pe.tous_presents(self.conn, self.s1, self.maths7, J1)
        self.marquer(self.s1, self.maths7, J2, "0000/26", "A")
        self.marquer(self.s1, self.maths7, J2, "0001/26", "P")
        h = pe.historique(self.conn, self.s1, self.maths7)
        self.assertEqual(h["jours"], ["16/09/2026", "15/09/2026"])
        ami = next(e for e in h["eleves"] if e["matricule"] == "0001/26")
        kas = next(e for e in h["eleves"] if e["matricule"] == "0000/26")
        self.assertEqual((kas["presences"], kas["absences"], kas["taux"], kas["codes"]), (1, 1, 50.0, ["A", "P"]))
        self.assertEqual((ami["presences"], ami["absences"], ami["taux"]), (2, 0, 100.0))

    def test_les_directions_voient_toutes_les_classes(self):
        pe.tous_presents(self.conn, self.s1, self.maths7, J1)
        self.marquer(self.s2, self.fr7, J1, "0001/26", "A")
        pe.tous_presents(self.conn, self.s1, self.maths8, J1)
        security.creer_utilisateur(self.conn, "sec1", "Sophie", "SECRETAIRE", MDP)
        sec = security.authentifier(self.conn, "sec1", MDP).session
        with self.assertRaises(PermissionError):                                     # secrétaire sans le droit
            pe.classes_du_jour(self.conn, sec, self.annee, J1)
        r = pe.classes_du_jour(self.conn, self.admin, self.annee, J1)
        par = {c["classe"]: c for c in r["classes"]}
        self.assertEqual((par["7ème A"]["effectif"], par["7ème A"]["presents"], par["7ème A"]["absents"], par["7ème A"]["cours_pointes"]), (3, 2, 1, 2))
        self.assertEqual((par["8ème A"]["effectif"], par["8ème A"]["presents"]), (1, 1))
        self.assertEqual(r["totaux"]["effectif"], 4)
        liste = pe.eleves_de_la_classe(self.conn, self.admin, self.annee, self.c7, J1)
        a = next(e for e in liste["eleves"] if e["matricule"] == "0001/26")
        self.assertEqual((a["journee"], a["manques"]), ("A", ["Français"]))
        self.assertEqual({c["cours"]: c["statut"] for c in a["cours"]}, {"Mathématiques": "P", "Français": "A"})

    def test_droit_lecture_donne_la_vue_et_le_recapitulatif(self):
        pe.tous_presents(self.conn, self.s1, self.maths7, J1)
        self.marquer(self.s2, self.fr7, J1, "0000/26", "A")
        pe.tous_presents(self.conn, self.s1, self.maths7, J2)
        # le poste « Directeur de discipline » : droit de base « Lecture » sur « Présence des élèves » ; « Lecture » et « Ajout » sur son sous-menu « Direction de discipline », rien d'autre
        security.creer_utilisateur(self.conn, "dd1", "Daniel D", "DIRECTEUR_DISCIPLINE", MDP)
        dd = security.authentifier(self.conn, "dd1", MDP).session
        self.assertEqual(droits.droits_utilisateur(self.conn, dd.id_user), {("presence_eleves", "LECTURE"), ("direction_discipline", "LECTURE"), ("direction_discipline", "AJOUT")})
        r = pe.recapitulatif_classe(self.conn, dd, self.annee, self.c7, J1, J2)
        self.assertEqual(r["jours_pointes"], 2)
        k = next(e for e in r["eleves"] if e["matricule"] == "0000/26")
        self.assertEqual((k["jours_presents"], k["jours_absents"], k["taux"]), (1, 1, 50.0))
        with self.assertRaises(pe.ErreurPresence):
            pe.recapitulatif_classe(self.conn, dd, self.annee, self.c7, J2, J1)
        with self.assertRaises(PermissionError):                                     # lecture seule : il ne pointe pas
            pe.liste(self.conn, dd, self.maths7, J1)
        with self.assertRaises(PermissionError):
            pe.marquer(self.conn, dd, self.maths7, J1, "0000/26", "A")
        with self.assertRaises(PermissionError):                                     # ni les cours, ni les points : pas Gestion scolaire
            cours.lister_classes(self.conn, dd)
        self.assertEqual([c["classe"] for c in pe.classes_du_jour(self.conn, dd, self.annee, J1)["classes"]][:1], ["7ème A"])
        self.assertTrue(pe.lister_annees(self.conn, dd))
        import modules
        self.assertEqual(modules.modules_ouverts(self.conn, dd), ["presence_eleves", "discipline"])   # Espace Discipline : module à part
        self.assertIsNone(modules.module_direct(self.conn, dd))      # deux modules : le menu principal s'affiche

    def test_la_directrice_des_etudes_voit_aussi_la_presence(self):
        pe.tous_presents(self.conn, self.s1, self.maths7, J1)
        security.creer_utilisateur(self.conn, "de1", "Diane E", "DIRECTRICE_ETUDES", MDP)
        de = security.authentifier(self.conn, "de1", MDP).session
        r = pe.classes_du_jour(self.conn, de, self.annee, J1)
        self.assertEqual(r["totaux"]["presents"], 3)

    def test_le_titulaire_ne_voit_pas_la_presence_des_autres(self):
        import bulletins
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c7, self.m2)       # s2 (Français) est titulaire de la 7ème A
        pe.tous_presents(self.conn, self.s1, self.maths7, J1)                                     # pointage du collègue de maths
        with self.assertRaises(PermissionError):
            pe.liste(self.conn, self.s2, self.maths7, J1)                                         # le titulaire ne gère pas ce cours
        with self.assertRaises(PermissionError):
            pe.classes_du_jour(self.conn, self.s2, self.annee, J1)                                # ni la vue des directions
        self.assertTrue(all("journee" not in e for e in pe.liste(self.conn, self.s2, self.fr7, J1)["eleves"]))


if __name__ == "__main__":
    unittest.main()

"""Tests de « Fonctions et affectations » (Gestion du personnel, 2ème fonctionnalité) : fonctions et services, affectations,
historique, listes du personnel, droits, journal.
Lancer :  python test_affectations.py"""
import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import affectations  # noqa: E402
import database      # noqa: E402
import droits        # noqa: E402
import migrations    # noqa: E402
import personnel     # noqa: E402
import security      # noqa: E402
from personnel import ErreurPersonnel  # noqa: E402

MDP = "Tr@vail-Amour-2026"


def fr(jour: date) -> str:
    return jour.strftime("%d/%m/%Y")


def saisie(**autres):
    base = {"nom": "mukendi", "postnom": "kabeya", "prenom": "jean", "sexe": "M", "date_naissance": "15/03/1985",
            "adresse": "Kinshasa", "telephone": "0812345678", "email": "", "date_engagement": "01/09/2015",
            "fonction": "Enseignant", "statut_pro": "PERMANENT", "matricule": ""}
    base.update(autres)
    return base


class TestAffectations(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(os.path.join(tempfile.mkdtemp(), "a.db"))
        security.creer_utilisateur(self.conn, "admin1", "Alice", "ADMINISTRATEUR", MDP)
        self.admin = security.authentifier(self.conn, "admin1", MDP).session
        self.id_sec = security.creer_utilisateur(self.conn, "sec1", "Sophie", "SECRETAIRE", MDP)
        self.sec = security.authentifier(self.conn, "sec1", MDP).session

    def donner(self, *noms):
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_sec, {("personnel", d) for d in noms})

    def agent(self, **autres):
        return personnel.enregistrer_agent(self.conn, self.admin, saisie(**autres))["matricule"]

    def fonction(self, libelle):
        return affectations.ajouter_referentiel(self.conn, self.admin, "FONCTION", libelle)

    def service(self, libelle):
        return affectations.ajouter_referentiel(self.conn, self.admin, "SERVICE", libelle)

    def affecter(self, m, id_f, debut, fin="", service=None, resp="", motif="", user=None):
        return affectations.affecter(self.conn, user or self.admin, m, {
            "id_fonction": id_f, "id_service": service, "responsabilite": resp, "date_debut": debut, "date_fin": fin,
            "motif": motif})

    def actions(self):
        return [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL ORDER BY ID_LOG")]

    def hist(self, m):
        return affectations.historique_agent(self.conn, self.admin, m)

    # ---------------------------------------------------------- fonctions et services
    def test_ajouter_renommer_desactiver_supprimer_une_fonction(self):
        id_f = self.fonction("  économe  ")
        self.assertEqual(affectations.liste_referentiel(self.conn, self.admin, "FONCTION")[0]["libelle"], "Économe")
        with self.assertRaises(ErreurPersonnel):
            self.fonction("ÉCONOME" if False else "économe")                       # doublon (casse ignorée)
        affectations.renommer_referentiel(self.conn, self.admin, "FONCTION", id_f, "Intendant adjoint")
        affectations.changer_activite_referentiel(self.conn, self.admin, "FONCTION", id_f, False)
        self.assertEqual(affectations.liste_referentiel(self.conn, self.admin, "FONCTION", inclure_inactifs=False), [])
        affectations.changer_activite_referentiel(self.conn, self.admin, "FONCTION", id_f, True)
        affectations.supprimer_referentiel(self.conn, self.admin, "FONCTION", id_f)
        self.assertEqual(affectations.liste_referentiel(self.conn, self.admin, "FONCTION"), [])
        for a in ("FONCTION_AJOUT", "FONCTION_MODIFICATION", "FONCTION_DESACTIVATION", "FONCTION_ACTIVATION", "FONCTION_SUPPRESSION"):
            self.assertIn(a, self.actions())

    def test_nom_vide_ou_trop_long_refuse_et_les_services_marchent_pareil(self):
        for genre in ("FONCTION", "SERVICE"):
            for nom in ("", "   ", "x" * 61):
                with self.subTest(genre=genre, nom=nom), self.assertRaises(ErreurPersonnel):
                    affectations.ajouter_referentiel(self.conn, self.admin, genre, nom)
        self.service("Discipline")
        with self.assertRaises(ErreurPersonnel):
            self.service("discipline")

    def test_une_fonction_utilisee_ne_se_supprime_pas(self):
        m = self.agent()
        id_f = affectations.liste_referentiel(self.conn, self.admin, "FONCTION")[0]["id"]
        self.assertTrue(m)
        with self.assertRaisesRegex(ErreurPersonnel, "Désactivez"):
            affectations.supprimer_referentiel(self.conn, self.admin, "FONCTION", id_f)
        id_s = self.service("Discipline")
        self.affecter(m, id_f, "01/01/2020", service=id_s)
        with self.assertRaisesRegex(ErreurPersonnel, "Désactivez-le"):
            affectations.supprimer_referentiel(self.conn, self.admin, "SERVICE", id_s)

    # ---------------------------------------------------------- première affectation (dossier personnel)
    def test_l_enregistrement_d_un_agent_cree_sa_fonction_et_sa_premiere_affectation(self):
        m = self.agent(fonction="surveillant")
        fonctions = affectations.liste_referentiel(self.conn, self.admin, "FONCTION")
        self.assertEqual([f["libelle"] for f in fonctions], ["Surveillant"])
        h = self.hist(m)
        self.assertEqual(len(h), 1)
        self.assertEqual((h[0]["fonction"], h[0]["date_debut"], h[0]["date_fin"], h[0]["statut"], h[0]["motif"]),
                         ("Surveillant", "01/09/2015", "", "EN_COURS", "Engagement"))
        self.assertEqual(personnel.charger_agent(self.conn, self.admin, m)["fonction"], "Surveillant")
        m2 = self.agent(nom="Autre", fonction="SURVEILLANT")                        # même fonction, casse différente
        self.assertEqual(len(affectations.liste_referentiel(self.conn, self.admin, "FONCTION")), 1)
        self.assertEqual(personnel.charger_agent(self.conn, self.admin, m2)["fonction"], "Surveillant")

    def test_une_fonction_desactivee_n_est_pas_acceptee_a_l_enregistrement(self):
        self.agent()
        id_f = affectations.liste_referentiel(self.conn, self.admin, "FONCTION")[0]["id"]
        affectations.changer_activite_referentiel(self.conn, self.admin, "FONCTION", id_f, False)
        with self.assertRaisesRegex(ErreurPersonnel, "désactivée"):
            self.agent(nom="Autre")
        self.assertEqual(len(personnel.rechercher(self.conn, self.admin)), 1)       # rien d'enregistré à moitié

    # ---------------------------------------------------------- changement de fonction et historique
    def test_un_changement_de_fonction_termine_l_ancienne_affectation_la_veille(self):
        m = self.agent()
        id_prefet = self.fonction("Préfet des études")
        id_service = self.service("Administration")
        r = self.affecter(m, id_prefet, "01/09/2020", service=id_service, resp="Chef de service", motif="Promotion")
        self.assertEqual(len(r["terminees"]), 1)
        h = self.hist(m)
        self.assertEqual([(a["fonction"], a["date_debut"], a["date_fin"], a["statut"]) for a in h],
                         [("Préfet des études", "01/09/2020", "", "EN_COURS"),
                          ("Enseignant", "01/09/2015", "31/08/2020", "TERMINEE")])
        self.assertEqual((h[0]["service"], h[0]["responsabilite"], h[0]["motif"]), ("Administration", "Chef de service", "Promotion"))
        self.assertEqual(personnel.charger_agent(self.conn, self.admin, m)["fonction"], "Préfet des études")
        self.assertEqual(affectations.situation_actuelle(self.conn, self.admin, m)["fonction"], "Préfet des études")
        self.assertIn("AFFECTATION_ENREGISTREE", self.actions())
        self.assertIn("AFFECTATION_TERMINEE", self.actions())

    def test_chevauchements_et_dates_incoherentes_refuses(self):
        m = self.agent()
        id_f = self.fonction("Surveillant")
        self.affecter(m, id_f, "01/09/2018", fin="30/06/2019")
        self.affecter(m, id_f, "01/09/2020")
        cas = [("01/09/2020", ""),            # même jour de début qu'une affectation existante
               ("01/01/2019", "31/12/2019"),  # recouvre la période terminée (ancienne affectation commencée plus tôt = ok) mais pas la suivante
               ("01/09/2014", ""),            # avant l'engagement
               ("", ""), ("31/02/2020", ""), ("01/10/2021", "01/09/2021")]
        for debut, fin in cas:
            with self.subTest(debut=debut, fin=fin), self.assertRaises(ErreurPersonnel):
                self.affecter(m, id_f, debut, fin=fin)

    def test_une_affectation_a_duree_limitee_puis_la_suivante(self):
        m = self.agent()
        id_f = self.fonction("Titulaire de classe")
        self.affecter(m, id_f, "01/09/2021", fin="30/06/2022", resp="Titulaire de la 3ème A")
        h = self.hist(m)
        self.assertEqual([(a["date_debut"], a["date_fin"], a["statut"]) for a in h],
                         [("01/09/2021", "30/06/2022", "TERMINEE"), ("01/09/2015", "31/08/2021", "TERMINEE")])
        self.affecter(m, id_f, "01/09/2022")
        self.assertEqual(self.hist(m)[0]["statut"], "EN_COURS")
        self.assertEqual(self.hist(m)[1]["date_fin"], "30/06/2022")                  # la fin déjà fixée n'est pas touchée

    def test_affectation_future_a_venir_la_fonction_actuelle_ne_change_pas_encore(self):
        m = self.agent()
        id_f = self.fonction("Préfet")
        demain = date.today() + timedelta(days=30)
        self.affecter(m, id_f, fr(demain))
        h = self.hist(m)
        self.assertEqual((h[0]["statut"], h[1]["statut"]), ("A_VENIR", "EN_COURS"))
        self.assertEqual(h[1]["date_fin"], fr(demain - timedelta(days=1)))
        self.assertEqual(personnel.charger_agent(self.conn, self.admin, m)["fonction"], "Enseignant")

    def test_agent_desactive_refuse_service_ou_fonction_desactive_refuse(self):
        m = self.agent()
        id_f, id_s = self.fonction("Préfet"), self.service("Discipline")
        affectations.changer_activite_referentiel(self.conn, self.admin, "SERVICE", id_s, False)
        with self.assertRaisesRegex(ErreurPersonnel, "désactivé"):
            self.affecter(m, id_f, "01/09/2020", service=id_s)
        affectations.changer_activite_referentiel(self.conn, self.admin, "FONCTION", id_f, False)
        with self.assertRaisesRegex(ErreurPersonnel, "désactivée"):
            self.affecter(m, id_f, "01/09/2020")
        affectations.changer_activite_referentiel(self.conn, self.admin, "FONCTION", id_f, True)
        personnel.changer_activite(self.conn, self.admin, m, False)
        with self.assertRaisesRegex(ErreurPersonnel, "désactivé"):
            self.affecter(m, id_f, "01/09/2020")
        self.assertEqual(len(self.hist(m)), 1)

    def test_un_echec_ne_laisse_rien_a_moitie(self):
        m = self.agent()
        id_f = self.fonction("Préfet")
        with self.assertRaises(ErreurPersonnel):
            self.affecter(m, id_f, "01/09/2020", fin="01/01/2020")
        h = self.hist(m)
        self.assertEqual((len(h), h[0]["date_fin"]), (1, ""))                       # l'ancienne affectation n'a pas été fermée

    # ---------------------------------------------------------- terminer / corriger
    def test_terminer_une_affectation(self):
        m = self.agent()
        a = self.hist(m)[0]
        affectations.terminer_affectation(self.conn, self.admin, a["id_aff"], "30/06/2024", "Départ à la retraite")
        h = self.hist(m)[0]
        self.assertEqual((h["date_fin"], h["statut"], h["motif"]), ("30/06/2024", "TERMINEE", "Départ à la retraite"))
        self.assertIsNone(affectations.situation_actuelle(self.conn, self.admin, m))
        for mauvaise in ("", "31/08/2015", "pas une date"):                         # avant le début de l'affectation
            with self.subTest(mauvaise), self.assertRaises(ErreurPersonnel):
                affectations.terminer_affectation(self.conn, self.admin, a["id_aff"], mauvaise)

    def test_corriger_une_affectation_et_ses_garde_fous(self):
        m = self.agent()
        id_f, id_s = self.fonction("Préfet"), self.service("Discipline")
        self.affecter(m, id_f, "01/09/2020")
        ancien, recent = self.hist(m)[1], self.hist(m)[0]
        champs = affectations.modifier_affectation(self.conn, self.admin, recent["id_aff"], {
            "id_fonction": id_f, "id_service": id_s, "responsabilite": "Chef", "date_debut": "01/09/2020", "date_fin": "",
            "motif": ""})
        self.assertEqual(sorted(champs), ["responsabilité", "service"])
        self.assertEqual(affectations.modifier_affectation(self.conn, self.admin, recent["id_aff"], {
            "id_fonction": id_f, "id_service": id_s, "responsabilite": "Chef", "date_debut": "01/09/2020", "date_fin": "",
            "motif": ""}), [])
        with self.assertRaises(ErreurPersonnel):                                    # l'ancienne ne peut pas déborder sur la récente
            affectations.terminer_affectation(self.conn, self.admin, ancien["id_aff"], "01/01/2021")
        with self.assertRaises(ErreurPersonnel):
            affectations.modifier_affectation(self.conn, self.admin, 9999, {"id_fonction": id_f, "date_debut": "01/01/2020"})
        self.assertIn("AFFECTATION_MODIFIEE", self.actions())

    def test_renommer_une_fonction_met_a_jour_les_dossiers(self):
        m = self.agent()
        id_f = affectations.liste_referentiel(self.conn, self.admin, "FONCTION")[0]["id"]
        affectations.renommer_referentiel(self.conn, self.admin, "FONCTION", id_f, "Professeur")
        self.assertEqual(personnel.charger_agent(self.conn, self.admin, m)["fonction"], "Professeur")
        self.assertEqual(self.hist(m)[0]["fonction"], "Professeur")

    # ---------------------------------------------------------- listes du personnel
    def preparer_ecole(self):
        self.m1 = self.agent(nom="Banza", fonction="Enseignant")
        self.m2 = self.agent(nom="Kalonji", prenom="Éric", fonction="Enseignant")
        self.m3 = self.agent(nom="Tshala", fonction="Secrétaire")
        self.f_ens = affectations.liste_referentiel(self.conn, self.admin, "FONCTION")
        self.id_ens = next(f["id"] for f in self.f_ens if f["libelle"] == "Enseignant")
        self.id_sec_f = next(f["id"] for f in self.f_ens if f["libelle"] == "Secrétaire")
        self.s_adm, self.s_ens = self.service("Administration"), self.service("Enseignement")
        self.affecter(self.m1, self.id_ens, "01/09/2016", service=self.s_ens, resp="Titulaire de la 1ère A")
        self.affecter(self.m2, self.id_ens, "01/09/2016", service=self.s_ens)
        self.affecter(self.m3, self.id_sec_f, "01/09/2016", service=self.s_adm)

    def test_liste_par_fonction(self):
        self.preparer_ecole()
        r = affectations.liste_personnel(self.conn, self.admin, "FONCTION")
        self.assertEqual(r["total"], 3)
        self.assertEqual([(g["libelle"], [a["nom_complet"] for a in g["agents"]]) for g in r["groupes"]],
                         [("Enseignant", ["BANZA KABEYA Jean", "KALONJI KABEYA Éric"]), ("Secrétaire", ["TSHALA KABEYA Jean"])])
        self.assertEqual(r["groupes"][0]["agents"][0]["responsabilite"], "Titulaire de la 1ère A")
        un = affectations.liste_personnel(self.conn, self.admin, "FONCTION", self.id_sec_f)
        self.assertEqual((un["total"], un["filtre"], [g["libelle"] for g in un["groupes"]]), (1, "Secrétaire", ["Secrétaire"]))
        self.assertIn("LISTE_PERSONNEL_CONSULTEE", self.actions())

    def test_liste_par_service_avec_agents_sans_service(self):
        self.preparer_ecole()
        m4 = self.agent(nom="Zola", fonction="Gardien")                              # affecté à aucun service
        r = affectations.liste_personnel(self.conn, self.admin, "SERVICE")
        self.assertEqual([(g["libelle"], len(g["agents"])) for g in r["groupes"]],
                         [("Administration", 1), ("Enseignement", 2), (affectations.SANS_SERVICE, 1)])
        self.assertEqual(r["groupes"][2]["agents"][0]["matricule"], m4)
        un = affectations.liste_personnel(self.conn, self.admin, "SERVICE", self.s_ens)
        self.assertEqual(un["total"], 2)

    def test_liste_a_une_date_passee_et_agents_desactives_exclus(self):
        self.preparer_ecole()
        id_prefet = self.fonction("Préfet")
        self.affecter(self.m1, id_prefet, "01/09/2022")
        avant = affectations.liste_personnel(self.conn, self.admin, "FONCTION", jour_texte="01/01/2021")
        self.assertEqual({g["libelle"] for g in avant["groupes"]}, {"Enseignant", "Secrétaire"})
        self.assertEqual(avant["total"], 3)
        apres = affectations.liste_personnel(self.conn, self.admin, "FONCTION")
        self.assertEqual({g["libelle"] for g in apres["groupes"]}, {"Enseignant", "Secrétaire", "Préfet"})
        personnel.changer_activite(self.conn, self.admin, self.m3, False)
        self.assertEqual(affectations.liste_personnel(self.conn, self.admin, "FONCTION")["total"], 2)
        with self.assertRaises(ErreurPersonnel):
            affectations.liste_personnel(self.conn, self.admin, "FONCTION", jour_texte="n'importe quoi")

    def test_un_agent_sans_affectation_en_cours_est_signale(self):
        m = self.agent()
        a = self.hist(m)[0]
        affectations.terminer_affectation(self.conn, self.admin, a["id_aff"], "30/06/2024")
        r = affectations.liste_personnel(self.conn, self.admin, "FONCTION")
        self.assertEqual([(g["libelle"], len(g["agents"])) for g in r["groupes"]], [(affectations.SANS_AFFECTATION, 1)])

    def test_liste_pdf(self):
        self.preparer_ecole()
        for mode in ("FONCTION", "SERVICE"):
            chemin = affectations.preparer_liste_pdf(self.conn, self.admin, mode)
            self.assertTrue(open(chemin, "rb").read().startswith(b"%PDF-"))
        self.assertEqual(self.actions().count("LISTE_PERSONNEL_IMPRIMEE"), 2)

    def test_liste_pdf_de_plusieurs_pages(self):
        for i in range(70):
            self.agent(nom=f"Agent{i:03d}", fonction=f"Fonction numéro {i % 3}")
        chemin = affectations.preparer_liste_pdf(self.conn, self.admin, "FONCTION")
        contenu = open(chemin, "rb").read()
        self.assertGreaterEqual(contenu.count(b"/Type /Page "), 2)

    # ---------------------------------------------------------- droits
    def test_sans_droit_rien_n_est_possible(self):
        m = self.agent()
        id_f = affectations.liste_referentiel(self.conn, self.admin, "FONCTION")[0]["id"]
        for appel in (lambda: affectations.liste_referentiel(self.conn, self.sec, "FONCTION"),
                      lambda: affectations.ajouter_referentiel(self.conn, self.sec, "SERVICE", "X"),
                      lambda: affectations.historique_agent(self.conn, self.sec, m),
                      lambda: affectations.liste_personnel(self.conn, self.sec, "FONCTION"),
                      lambda: affectations.preparer_liste_pdf(self.conn, self.sec, "FONCTION"),
                      lambda: self.affecter(m, id_f, "01/09/2020", user=self.sec)):
            with self.assertRaises(PermissionError):
                appel()

    def test_chaque_droit_ouvre_seulement_son_operation(self):
        m = self.agent()
        id_f = self.fonction("Préfet")
        a = self.hist(m)[0]
        self.donner("LECTURE")
        affectations.liste_personnel(self.conn, self.sec, "FONCTION")
        affectations.historique_agent(self.conn, self.sec, m)
        for appel in (lambda: affectations.ajouter_referentiel(self.conn, self.sec, "FONCTION", "Nouvelle"),
                      lambda: self.affecter(m, id_f, "01/09/2020", user=self.sec),
                      lambda: affectations.renommer_referentiel(self.conn, self.sec, "FONCTION", id_f, "Autre"),
                      lambda: affectations.terminer_affectation(self.conn, self.sec, a["id_aff"], "30/06/2024"),
                      lambda: affectations.supprimer_referentiel(self.conn, self.sec, "FONCTION", id_f)):
            with self.assertRaises(PermissionError):
                appel()
        self.donner("LECTURE", "AJOUT")
        affectations.ajouter_referentiel(self.conn, self.sec, "FONCTION", "Nouvelle")
        self.affecter(m, id_f, "01/09/2020", user=self.sec)
        self.donner("LECTURE", "MODIFICATION")
        affectations.renommer_referentiel(self.conn, self.sec, "FONCTION", id_f, "Préfet adjoint")
        self.donner("LECTURE", "SUPPRESSION")
        affectations.supprimer_referentiel(self.conn, self.sec, "FONCTION",
                                           next(f["id"] for f in affectations.liste_referentiel(self.conn, self.admin, "FONCTION")
                                                if f["libelle"] == "Nouvelle"))

    # ---------------------------------------------------------- base
    def test_structure_a_jour_et_journal_valide(self):
        self.assertFalse(migrations.analyser(self.conn).a_faire)
        self.agent()
        self.assertEqual(database.verifier_journal(self.conn), (True, None))

    def test_la_base_refuse_une_fin_avant_le_debut(self):
        m = self.agent()
        with self.assertRaises(Exception), self.conn:
            self.conn.execute("UPDATE AFFECTATION SET DATE_FIN = '2000-01-01' WHERE MATRICULE = ?", (m,))

    def test_migration_des_agents_enregistres_avant_cette_version(self):
        m = self.agent(fonction="Comptable")
        with self.conn:                                    # on remet la base dans l'état de la version précédente
            self.conn.execute("DELETE FROM AFFECTATION")
            self.conn.execute("DELETE FROM FONCTION_PERSONNEL")
            self.conn.execute("PRAGMA user_version = 7")
        self.assertTrue(migrations.analyser(self.conn).a_faire)
        migrations.mettre_a_jour(self.conn, sauvegarder=False)
        h = self.hist(m)
        self.assertEqual((len(h), h[0]["fonction"], h[0]["date_debut"], h[0]["statut"]), (1, "Comptable", "01/09/2015", "EN_COURS"))
        migrations.mettre_a_jour(self.conn, sauvegarder=False)                      # rejouée : rien de doublé
        self.assertEqual(len(self.hist(m)), 1)


if __name__ == "__main__":
    unittest.main()

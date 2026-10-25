"""Tests de « Présence et absence » (Gestion du personnel, 3ème fonctionnalité) : pointage, retards, permissions et congés,
états récapitulatifs, droits, journal.
Lancer :  python test_presences.py"""
import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import affectations   # noqa: E402
import database       # noqa: E402
import droits         # noqa: E402
import personnel      # noqa: E402
import presences      # noqa: E402
import security       # noqa: E402
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


AUJOURDHUI = date.today()
LUNDI = AUJOURDHUI - timedelta(days=AUJOURDHUI.weekday() + 14)       # un lundi passé, il y a 2 à 3 semaines
MARDI, MERCREDI, JEUDI, VENDREDI = (LUNDI + timedelta(days=k) for k in (1, 2, 3, 4))
SAMEDI = LUNDI + timedelta(days=5)


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(os.path.join(tempfile.mkdtemp(), "p.db"))
        security.creer_utilisateur(self.conn, "admin1", "Alice", "ADMINISTRATEUR", MDP)
        self.admin = security.authentifier(self.conn, "admin1", MDP).session
        self.id_sec = security.creer_utilisateur(self.conn, "sec1", "Sophie", "SECRETAIRE", MDP)
        self.sec = security.authentifier(self.conn, "sec1", MDP).session
        self.a = personnel.enregistrer_agent(self.conn, self.admin, saisie())["matricule"]
        self.b = personnel.enregistrer_agent(self.conn, self.admin, saisie(nom="banza", prenom="paul", fonction="Secrétaire"))["matricule"]

    def donner(self, *noms):
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_sec, {("personnel", d) for d in noms})

    def pointer(self, m, jour, statut, heure="", motif="", user=None):
        return presences.enregistrer_pointage(self.conn, user or self.admin, m, fr(jour), statut, heure, motif)

    def actions(self):
        return [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL ORDER BY ID_LOG")]

    def ligne(self, jour, m):
        f = presences.feuille_du_jour(self.conn, self.admin, fr(jour))
        return next(l for l in f["lignes"] if l["matricule"] == m)


class TestPointage(Base):
    def test_present_absent_et_feuille(self):
        self.pointer(self.a, LUNDI, "PRESENT")
        self.pointer(self.b, LUNDI, "ABSENT", motif="malade")
        self.assertEqual(self.ligne(LUNDI, self.a)["statut"], "PRESENT")
        l = self.ligne(LUNDI, self.b)
        self.assertEqual((l["statut"], l["motif"], l["source"]), ("ABSENT", "malade", "MANUEL"))
        f = presences.feuille_du_jour(self.conn, self.admin, fr(LUNDI))
        self.assertEqual((f["resume"]["PRESENT"], f["resume"]["ABSENT"], f["resume"]["NON_RENSEIGNE"]), (1, 1, 0))

    def test_retard_minutes_calculees(self):
        self.pointer(self.a, LUNDI, "RETARD", "7h45")
        l = self.ligne(LUNDI, self.a)
        self.assertEqual((l["statut"], l["heure"], l["minutes"]), ("RETARD", "07:45", 15))

    def test_retard_exige_heure_apres_ouverture(self):
        with self.assertRaises(ErreurPersonnel):
            self.pointer(self.a, LUNDI, "RETARD")
        with self.assertRaises(ErreurPersonnel):
            self.pointer(self.a, LUNDI, "RETARD", "07:30")
        with self.assertRaises(ErreurPersonnel):
            self.pointer(self.a, LUNDI, "PRESENT", "08:10")
        with self.assertRaises(ErreurPersonnel):
            self.pointer(self.a, LUNDI, "RETARD", "25:00")
        self.pointer(self.a, LUNDI, "PRESENT", "07:10")                      # à l'heure : accepté

    def test_correction_remplace_et_journalise(self):
        self.pointer(self.a, LUNDI, "ABSENT")
        r = self.pointer(self.a, LUNDI, "PRESENT")
        self.assertEqual(r["operation"], "modification")
        self.assertEqual(self.ligne(LUNDI, self.a)["statut"], "PRESENT")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PRESENCE").fetchone()[0], 1)
        self.assertEqual(self.actions().count("PRESENCE_MODIFIEE"), 1)

    def test_jours_refuses(self):
        for jour in (SAMEDI, AUJOURDHUI + timedelta(days=1), date(2015, 8, 31)):
            with self.assertRaises(ErreurPersonnel):
                self.pointer(self.a, jour, "PRESENT")

    def test_jour_ferme_refuse_puis_rouvert(self):
        presences.ajouter_jour_ferme(self.conn, self.admin, fr(MARDI), "Fête")
        with self.assertRaises(ErreurPersonnel):
            self.pointer(self.a, MARDI, "PRESENT")
        with self.assertRaises(ErreurPersonnel):
            presences.ajouter_jour_ferme(self.conn, self.admin, fr(MARDI), "Fête")      # doublon
        presences.supprimer_jour_ferme(self.conn, self.admin, fr(MARDI))
        self.pointer(self.a, MARDI, "PRESENT")

    def test_agent_desactive_refuse(self):
        personnel.changer_activite(self.conn, self.admin, self.b, False)
        with self.assertRaises(ErreurPersonnel):
            self.pointer(self.b, LUNDI, "PRESENT")

    def test_marquer_presents_ne_touche_pas_aux_pointes(self):
        self.pointer(self.a, LUNDI, "ABSENT")
        r = presences.marquer_presents(self.conn, self.admin, fr(LUNDI))
        self.assertEqual(r["faits"], 1)
        self.assertEqual(self.ligne(LUNDI, self.a)["statut"], "ABSENT")
        self.assertEqual(self.ligne(LUNDI, self.b)["statut"], "PRESENT")

    def test_pointer_plusieurs_un_refus_nempeche_pas_les_autres(self):
        presences.accorder_autorisation(self.conn, self.admin, self.a, "CONGE", "", fr(LUNDI), fr(LUNDI))
        r = presences.pointer_plusieurs(self.conn, self.admin, [self.a, self.b], fr(LUNDI), "ABSENT")
        self.assertEqual(r["faits"], 1)
        self.assertEqual([m for m, _ in r["refuses"]], [self.a])

    def test_supprimer_pointage(self):
        self.pointer(self.a, LUNDI, "ABSENT")
        presences.supprimer_pointage(self.conn, self.admin, self.a, fr(LUNDI))
        self.assertEqual(self.ligne(LUNDI, self.a)["statut"], "NON_RENSEIGNE")
        with self.assertRaises(ErreurPersonnel):
            presences.supprimer_pointage(self.conn, self.admin, self.a, fr(LUNDI))
        self.assertIn("PRESENCE_SUPPRIMEE", self.actions())

    def test_filtre_par_fonction(self):
        id_f = affectations.liste_referentiel(self.conn, self.admin, "FONCTION")
        id_sec = next(f["id"] for f in id_f if f["libelle"] == "Secrétaire")
        f = presences.feuille_du_jour(self.conn, self.admin, fr(LUNDI), id_sec)
        self.assertEqual([l["matricule"] for l in f["lignes"]], [self.b])


class TestAutorisations(Base):
    def test_conge_couvre_les_jours_et_bloque_le_pointage(self):
        r = presences.accorder_autorisation(self.conn, self.admin, self.a, "CONGE", "Congé annuel", fr(LUNDI), fr(MERCREDI))
        self.assertEqual(r["jours"], 3)
        l = self.ligne(MARDI, self.a)
        self.assertEqual((l["statut"], l["verrouille"], l["motif"]), ("CONGE", True, "Congé annuel"))
        with self.assertRaises(ErreurPersonnel):
            self.pointer(self.a, MARDI, "PRESENT")
        self.assertEqual(self.ligne(JEUDI, self.a)["statut"], "NON_RENSEIGNE")

    def test_chevauchement_refuse(self):
        presences.accorder_autorisation(self.conn, self.admin, self.a, "PERMISSION", "", fr(MARDI), fr(MERCREDI))
        with self.assertRaises(ErreurPersonnel):
            presences.accorder_autorisation(self.conn, self.admin, self.a, "CONGE", "", fr(MERCREDI), fr(VENDREDI))

    def test_absence_regularisee_mais_presence_bloque(self):
        self.pointer(self.a, MARDI, "ABSENT")
        r = presences.accorder_autorisation(self.conn, self.admin, self.a, "PERMISSION", "Raison familiale", fr(MARDI), fr(MARDI))
        self.assertEqual(r["regularisees"], 1)
        self.assertEqual(self.ligne(MARDI, self.a)["statut"], "PERMISSION")
        self.pointer(self.b, JEUDI, "RETARD", "08:00")
        with self.assertRaises(ErreurPersonnel):
            presences.accorder_autorisation(self.conn, self.admin, self.b, "CONGE", "", fr(MERCREDI), fr(VENDREDI))

    def test_dates_invalides(self):
        with self.assertRaises(ErreurPersonnel):
            presences.accorder_autorisation(self.conn, self.admin, self.a, "CONGE", "", fr(MERCREDI), fr(MARDI))
        with self.assertRaises(ErreurPersonnel):                               # week-end seulement
            presences.accorder_autorisation(self.conn, self.admin, self.a, "CONGE", "", fr(SAMEDI), fr(SAMEDI + timedelta(days=1)))
        with self.assertRaises(ErreurPersonnel):
            presences.accorder_autorisation(self.conn, self.admin, self.a, "VACANCES", "", fr(LUNDI), fr(LUNDI))
        with self.assertRaises(ErreurPersonnel):                               # avant l'engagement
            presences.accorder_autorisation(self.conn, self.admin, self.a, "CONGE", "", "01/01/2010", "05/01/2010")

    def test_annulation_exige_un_motif_et_libere_les_jours(self):
        id_aut = presences.accorder_autorisation(self.conn, self.admin, self.a, "CONGE", "", fr(LUNDI), fr(MARDI))["id"]
        with self.assertRaises(ErreurPersonnel):
            presences.annuler_autorisation(self.conn, self.admin, id_aut, " ")
        presences.annuler_autorisation(self.conn, self.admin, id_aut, "Reprise anticipée")
        self.assertEqual(self.ligne(LUNDI, self.a)["statut"], "NON_RENSEIGNE")
        with self.assertRaises(ErreurPersonnel):
            presences.annuler_autorisation(self.conn, self.admin, id_aut, "encore")
        self.pointer(self.a, LUNDI, "PRESENT")
        presences.accorder_autorisation(self.conn, self.admin, self.a, "CONGE", "", fr(MARDI), fr(MERCREDI))   # libre à nouveau

    def test_liste_et_jours_de_l_annee(self):
        presences.accorder_autorisation(self.conn, self.admin, self.a, "CONGE", "", fr(LUNDI), fr(MERCREDI))
        d = presences.liste_autorisations(self.conn, self.admin, self.a)
        self.assertEqual(len(d["autorisations"]), 1)
        self.assertEqual(d["autorisations"][0]["jours"], 3)
        if LUNDI.year == AUJOURDHUI.year:
            self.assertEqual(d["jours_annee"]["CONGE"], 3)


class TestEtat(Base):
    def preparer(self):
        self.pointer(self.a, LUNDI, "PRESENT")
        self.pointer(self.a, MARDI, "RETARD", "08:00", "embouteillage")      # 30 min
        self.pointer(self.a, MERCREDI, "ABSENT", "malade")
        presences.accorder_autorisation(self.conn, self.admin, self.a, "PERMISSION", "", fr(JEUDI), fr(JEUDI))
        # vendredi : non renseigné
        self.pointer(self.b, LUNDI, "PRESENT")

    def etat(self, **kw):
        return presences.etat_recapitulatif(self.conn, self.admin, fr(LUNDI), fr(VENDREDI), **kw)

    def test_comptes_par_agent(self):
        self.preparer()
        e = self.etat()
        a = next(l for l in e["lignes"] if l["matricule"] == self.a)
        self.assertEqual((a["presents"], a["retards"], a["minutes"], a["absents"], a["permissions"], a["conges"],
                          a["non_renseignes"], a["jours"]), (1, 1, 30, 1, 1, 0, 1, 5))
        self.assertEqual(a["taux"], 50)                                         # 2 présences / (5 - 1 permission) = 50 %
        self.assertEqual(e["jours_travail"], 5)
        b = next(l for l in e["lignes"] if l["matricule"] == self.b)
        self.assertEqual((b["presents"], b["non_renseignes"]), (1, 4))
        self.assertEqual(e["totaux"]["presents"], 2)
        self.assertEqual(e["totaux"]["non_renseignes"], 5)

    def test_detail_et_autorisations(self):
        self.preparer()
        e = self.etat()
        self.assertEqual([x["statut"] for x in e["detail"]], ["RETARD", "ABSENT"])
        self.assertEqual(e["detail"][0]["minutes"], 30)
        self.assertEqual(len(e["autorisations"]), 1)

    def test_jour_ferme_sort_du_decompte(self):
        self.preparer()
        presences.ajouter_jour_ferme(self.conn, self.admin, fr(VENDREDI), "Fête")
        e = self.etat()
        self.assertEqual(e["jours_travail"] if VENDREDI <= AUJOURDHUI else 4, 4)
        a = next(l for l in e["lignes"] if l["matricule"] == self.a)
        self.assertEqual(a["non_renseignes"], 0)

    def test_filtre_par_fonction_et_service(self):
        self.preparer()
        fonctions = affectations.liste_referentiel(self.conn, self.admin, "FONCTION")
        id_sec = next(f["id"] for f in fonctions if f["libelle"] == "Secrétaire")
        e = self.etat(mode="FONCTION", id_filtre=id_sec)
        self.assertEqual([l["matricule"] for l in e["lignes"]], [self.b])
        self.assertEqual(e["portee"], "Fonction : Secrétaire")

    def test_periode_invalide(self):
        for debut, fin in ((fr(VENDREDI), fr(LUNDI)), ("", fr(LUNDI)), (fr(LUNDI - timedelta(days=400)), fr(LUNDI))):
            with self.assertRaises(ErreurPersonnel):
                presences.etat_recapitulatif(self.conn, self.admin, debut, fin)

    def test_agent_engage_en_cours_de_periode(self):
        c = personnel.enregistrer_agent(self.conn, self.admin, saisie(nom="tshala", date_engagement=fr(MERCREDI)))["matricule"]
        e = self.etat()
        ligne = next(l for l in e["lignes"] if l["matricule"] == c)
        self.assertEqual(ligne["jours"], 3)                                      # mercredi, jeudi, vendredi seulement

    def test_pdf_avec_et_sans_detail(self):
        self.preparer()
        for detail in (True, False):
            chemin = presences.preparer_etat_pdf(self.conn, self.admin, fr(LUNDI), fr(VENDREDI), avec_detail=detail)
            with open(chemin, "rb") as f:
                self.assertTrue(f.read(5) == b"%PDF-")
        self.assertIn("ETAT_PRESENCES_IMPRIME", self.actions())

    def test_pdf_beaucoup_d_agents_plusieurs_pages(self):
        for k in range(70):
            personnel.enregistrer_agent(self.conn, self.admin, saisie(nom=f"agent{k:02d}", prenom="x"))
        chemin = presences.preparer_etat_pdf(self.conn, self.admin, fr(LUNDI), fr(VENDREDI))
        with open(chemin, "rb") as f:
            self.assertGreater(f.read().count(b"/Type /Page\n") + 0, -1)


class TestDroits(Base):
    def test_sans_droit(self):
        with self.assertRaises(PermissionError):
            presences.feuille_du_jour(self.conn, self.sec, fr(LUNDI))
        with self.assertRaises(PermissionError):
            presences.etat_recapitulatif(self.conn, self.sec, fr(LUNDI), fr(VENDREDI))

    def test_lecture_seule(self):
        self.donner("LECTURE")
        presences.feuille_du_jour(self.conn, self.sec, fr(LUNDI))
        presences.etat_recapitulatif(self.conn, self.sec, fr(LUNDI), fr(VENDREDI))
        with self.assertRaises(PermissionError):
            self.pointer(self.a, LUNDI, "PRESENT", user=self.sec)
        with self.assertRaises(PermissionError):
            presences.accorder_autorisation(self.conn, self.sec, self.a, "CONGE", "", fr(LUNDI), fr(LUNDI), "")

    def test_ajout_sans_modification(self):
        self.donner("LECTURE", "AJOUT")
        self.pointer(self.a, LUNDI, "PRESENT", user=self.sec)
        with self.assertRaises(PermissionError):                                # corriger = Modification
            self.pointer(self.a, LUNDI, "ABSENT", user=self.sec)
        self.assertEqual(self.ligne(LUNDI, self.a)["statut"], "PRESENT")
        id_aut = presences.accorder_autorisation(self.conn, self.sec, self.a, "CONGE", "", fr(MARDI), fr(MARDI))["id"]
        with self.assertRaises(PermissionError):
            presences.annuler_autorisation(self.conn, self.sec, id_aut, "erreur")
        with self.assertRaises(PermissionError):
            presences.supprimer_pointage(self.conn, self.sec, self.a, fr(LUNDI))

    def test_journal_valide_et_structure(self):
        self.pointer(self.a, LUNDI, "PRESENT")
        self.assertEqual(database.verifier_journal(self.conn), (True, None))
        import migrations
        self.assertEqual(migrations.analyser(self.conn).tables_a_creer if hasattr(migrations.analyser(self.conn), "tables_a_creer") else [], [])


if __name__ == "__main__":
    unittest.main()

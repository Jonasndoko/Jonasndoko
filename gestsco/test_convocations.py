"""Tests de la Direction de discipline > Convocation du parent : choix de l'élève, coordonnées du parent, motif, rendez-vous, instructions, envoi par
notification dans l'application des parents, accusé de lecture, annulation, droits, journal, cloisonnement entre parents, pages web.
Lancer :  python -m unittest test_convocations"""
import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web                      # noqa: E402
import config                       # noqa: E402
import convocations as cv           # noqa: E402
import droits                       # noqa: E402
import sessions_web                 # noqa: E402
from convocations import ErreurConvocation   # noqa: E402
from test_notes import MDP                   # noqa: E402
from test_prefecture_v57 import Fixture      # noqa: E402

DEMAIN = (date.today() + timedelta(days=1)).isoformat()


def journal(conn, action):
    return [l["DETAIL"] for l in conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = ? ORDER BY ID_LOG", (action,))]


class Fix(Fixture):
    """Élèves : 0000 Kasongo, 0001 Amisi (tuteur et téléphone renseignés), 0002 Zola (7ème A), 0009 Autre (8ème A), 0100 Petit (primaire).
    Paiements valides R1 (0000) et R2 (0001) : ils servent de reçus pour lier des comptes parents."""

    def setUp(self):
        super().setUp()
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET NOM_TUTEUR = 'Papa Amisi', TEL_TUTEUR = '0812345678', ADRESSE = '12 av. du Collège' WHERE MATRICULE = '0001/26'")

    def donner(self, session, droit):
        d = droits.droits_utilisateur(self.conn, session.id_user) | {("direction_discipline", droit)}
        droits.remplacer_droits(self.conn, session.id_user, d)
        self.conn.commit()

    def lier_parent(self, matricule="0001/26", n_recu="R2", nom="Papa Amisi", ident="0812345678"):
        """Crée un compte parent actif lié à l'élève par un reçu valide ; retourne son identifiant."""
        with self.conn:
            id_parent = self.conn.execute("SELECT ID_PARENT FROM COMPTE_PARENT WHERE IDENTIFIANT = ?", (ident,)).fetchone()
            if id_parent:
                id_parent = id_parent[0]
            else:
                id_parent = self.conn.execute("INSERT INTO COMPTE_PARENT (IDENTIFIANT, NOM_COMPLET, MDP_HASH, DATE_CREATION) VALUES (?,?,?,?)",
                                              (ident, nom, "x", "2026-09-10T08:00:00")).lastrowid
            self.conn.execute("INSERT INTO CODE_PARENT (CODE, N_RECU, MATRICULE, ANNEESCO, DATE_GEN, ID_PARENT, DATE_UTILISATION) VALUES (?,?,?,?,?,?,?)",
                              (f"CODE{n_recu}", n_recu, matricule, self.annee, "2026-09-10T08:00:00", id_parent, "2026-09-10T09:00:00"))
            self.conn.execute("INSERT INTO ENFANT_PARENT (ID_PARENT, MATRICULE, DATE_LIEN) VALUES (?,?,?)", (id_parent, matricule, "2026-09-10T09:00:00"))
        return id_parent

    def convoquer(self, matricule="0001/26", **plus):
        champs = dict(matricule=matricule, motif="Absences répétées en classe", date_texte=DEMAIN, heure_texte="09:30", lieu="", instructions="")
        champs.update(plus)
        return cv.enregistrer(self.conn, self.dird, **champs)

    def etat(self, id_conv):
        return self.conn.execute("SELECT STATUT FROM CONVOCATION_PARENT WHERE ID_CONV = ?", (id_conv,)).fetchone()[0]


class TestChoixEtCoordonnees(Fix):
    def test_la_fonctionnalite_est_declaree(self):
        cles = [c for c, _t, _d in config.FONCTIONNALITES_DIRECTIONS["direction_discipline"]]
        self.assertIn("convocation", cles)
        self.assertEqual(cles[-1], "rapport")

    def test_recherche_d_un_eleve(self):
        r = cv.chercher_eleves(self.conn, self.dird, "Amisi")
        self.assertEqual([(e["matricule"], e["classe"]) for e in r["eleves"]], [("0001/26", "7ème A")])
        self.assertEqual(cv.chercher_eleves(self.conn, self.dird, "Petit")["eleves"], [])        # primaire : jamais proposé
        self.assertEqual(cv.chercher_eleves(self.conn, self.dird, "")["eleves"], [])
        self.assertEqual(len(cv.chercher_eleves(self.conn, self.dird, "/26")["eleves"]), 4)

    def test_coordonnees_du_parent(self):
        self.lier_parent()
        f = cv.coordonnees_parent(self.conn, self.dird, "0001/26")
        self.assertEqual((f["nom_complet"][:5], f["classe"]), ("Amisi", "7ème A"))
        self.assertEqual((f["parent"]["nom"], f["parent"]["telephone"], f["parent"]["renseigne"]), ("Papa Amisi", "0812345678", True))
        self.assertTrue(f["peut_notifier"])
        self.assertEqual([c["nom"] for c in f["comptes"]], ["Papa Amisi"])

    def test_fiche_sans_parent_ni_compte(self):
        f = cv.coordonnees_parent(self.conn, self.dird, "0002/26")
        self.assertFalse(f["parent"]["renseigne"])
        self.assertFalse(f["peut_notifier"])
        self.assertEqual(f["comptes"], [])

    def test_compte_dont_l_acces_est_coupe_n_est_pas_destinataire(self):
        self.lier_parent()
        with self.conn:
            self.conn.execute("UPDATE PAIEMENT SET STATUT = 'ANNULE' WHERE N_RECU = 'R2'")
        self.assertFalse(cv.coordonnees_parent(self.conn, self.dird, "0001/26")["peut_notifier"])

    def test_eleve_du_primaire_ou_inconnu_ou_desactive(self):
        with self.assertRaises(PermissionError):
            cv.coordonnees_parent(self.conn, self.dird, "0100/26")
        with self.assertRaises(ErreurConvocation):
            cv.coordonnees_parent(self.conn, self.dird, "9999/99")
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET ACTIF = 0 WHERE MATRICULE = '0002/26'")
        with self.assertRaises(ErreurConvocation):
            cv.coordonnees_parent(self.conn, self.dird, "0002/26")
        self.assertEqual(cv.chercher_eleves(self.conn, self.dird, "Zola")["eleves"], [])


class TestEnregistrer(Fix):
    def test_brouillon_copie_les_coordonnees_et_le_lieu_par_defaut(self):
        r = self.convoquer(instructions="  Se munir  du carnet.  ")
        self.assertEqual((r["envoyee"], r["raison"]), (False, ""))
        d = cv.detail(self.conn, self.dird, r["id"])
        self.assertEqual((d["statut"], d["parent"], d["telephone"], d["lieu"], d["heure"]), ("BROUILLON", "Papa Amisi", "0812345678", "Direction de discipline", "09:30"))
        self.assertEqual(d["instructions"], "Se munir du carnet.")
        with self.conn:                                                       # modifier la fiche ne réécrit pas la convocation
            self.conn.execute("UPDATE ELEVE SET NOM_TUTEUR = 'Autre nom' WHERE MATRICULE = '0001/26'")
        self.assertEqual(cv.detail(self.conn, self.dird, r["id"])["parent"], "Papa Amisi")
        self.assertIn("CONVOCATION_ENREGISTREE", [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")])

    def test_formats_de_date_et_d_heure(self):
        d = (date.today() + timedelta(days=5))
        r = self.convoquer(date_texte=d.strftime("%d/%m/%Y"), heure_texte="8h05", lieu="Bureau du Préfet")
        v = cv.detail(self.conn, self.dird, r["id"])
        self.assertEqual((v["jour"], v["heure"], v["lieu"]), (d.isoformat(), "08:05", "Bureau du Préfet"))

    def test_validations(self):
        hier = (date.today() - timedelta(days=1)).isoformat()
        loin = (date.today() + timedelta(days=400)).isoformat()
        for plus in ({"motif": "  "}, {"motif": "abc"}, {"motif": "x" * 301}, {"date_texte": ""}, {"date_texte": "pas une date"}, {"date_texte": hier},
                     {"date_texte": loin}, {"heure_texte": ""}, {"heure_texte": "25:00"}, {"heure_texte": "9:75"}, {"lieu": "l" * 101},
                     {"instructions": "i" * 601}, {"matricule": "9999/99"}):
            with self.assertRaises(ErreurConvocation, msg=str(plus)):
                self.convoquer(**plus)
        with self.assertRaises(PermissionError):
            self.convoquer(matricule="0100/26")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CONVOCATION_PARENT").fetchone()[0], 0)

    def test_aujourd_hui_est_accepte(self):
        self.assertTrue(self.convoquer(date_texte=date.today().isoformat())["id"])


class TestEnvoi(Fix):
    def test_enregistrer_et_envoyer_notifie_les_comptes_lies(self):
        p1 = self.lier_parent()
        self.payer("0001/26", 500, 3)                                                  # 2e reçu : le 2e parent du même élève
        p2 = self.lier_parent(n_recu="R3", nom="Maman Amisi", ident="0899999999")
        r = self.convoquer(envoyer=True)
        self.assertEqual((r["envoyee"], r["destinataires"]), (True, 2))
        self.assertEqual(self.etat(r["id"]), "ENVOYEE")
        self.assertEqual(sorted(x[0] for x in self.conn.execute("SELECT ID_PARENT FROM CONVOCATION_DESTINATAIRE WHERE ID_CONV = ?", (r["id"],))), sorted([p1, p2]))
        self.assertTrue(any("2 compte(s) parent" in l for l in journal(self.conn, "CONVOCATION_ENVOYEE")))
        d = cv.detail(self.conn, self.dird, r["id"])
        self.assertEqual((d["statut"], d["envoyee_par"], d["peut_envoyer"]), ("ENVOYEE", "dird1", False))
        self.assertEqual(len(d["destinataires"]), 2)

    def test_sans_compte_parent_la_convocation_reste_en_brouillon_avec_la_raison(self):
        r = self.convoquer(envoyer=True)
        self.assertFalse(r["envoyee"])
        self.assertIn("Aucun parent", r["raison"])
        self.assertEqual(self.etat(r["id"]), "BROUILLON")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CONVOCATION_DESTINATAIRE").fetchone()[0], 0)
        with self.assertRaises(ErreurConvocation):
            cv.envoyer_convocation(self.conn, self.dird, r["id"])
        self.lier_parent()                                                    # le parent active l'application : l'envoi devient possible
        self.assertEqual(cv.envoyer_convocation(self.conn, self.dird, r["id"])["destinataires"], 1)
        self.assertEqual(self.etat(r["id"]), "ENVOYEE")

    def test_pas_d_envoi_double_ni_apres_annulation_ni_apres_la_date(self):
        self.lier_parent()
        r = self.convoquer(envoyer=True)
        with self.assertRaises(ErreurConvocation):
            cv.envoyer_convocation(self.conn, self.dird, r["id"])
        b = self.convoquer(matricule="0001/26")
        self.donner(self.dird, "MODIFICATION")
        cv.annuler(self.conn, self.dird, b["id"], "Erreur de saisie")
        with self.assertRaises(ErreurConvocation):
            cv.envoyer_convocation(self.conn, self.dird, b["id"])
        c = self.convoquer(date_texte=date.today().isoformat())
        with self.conn:
            self.conn.execute("UPDATE CONVOCATION_PARENT SET DATE_RDV = ? WHERE ID_CONV = ?", ((date.today() - timedelta(days=2)).isoformat(), c["id"]))
        with self.assertRaises(ErreurConvocation):
            cv.envoyer_convocation(self.conn, self.dird, c["id"])

    def test_eleve_desactive_apres_enregistrement_n_est_plus_convoque(self):
        self.lier_parent()
        r = self.convoquer()
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET ACTIF = 0 WHERE MATRICULE = '0001/26'")
        with self.assertRaises(ErreurConvocation):
            cv.envoyer_convocation(self.conn, self.dird, r["id"])


class TestAnnulation(Fix):
    def test_annuler_exige_le_droit_modification_et_un_motif(self):
        self.lier_parent()
        r = self.convoquer(envoyer=True)
        with self.assertRaises(PermissionError):
            cv.annuler(self.conn, self.dird, r["id"], "Contre-ordre")
        self.donner(self.dird, "MODIFICATION")
        with self.assertRaises(ErreurConvocation):
            cv.annuler(self.conn, self.dird, r["id"], "")
        cv.annuler(self.conn, self.dird, r["id"], "Rendez-vous reporté")
        self.assertEqual(self.etat(r["id"]), "ANNULEE")
        d = cv.detail(self.conn, self.dird, r["id"])
        self.assertEqual((d["statut"], d["motif_annulation"], d["annulee_par"]), ("ANNULEE", "Rendez-vous reporté", "dird1"))
        with self.assertRaises(ErreurConvocation):
            cv.annuler(self.conn, self.dird, r["id"], "encore")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CONVOCATION_PARENT").fetchone()[0], 1)      # rien n'est supprimé
        self.assertTrue(journal(self.conn, "CONVOCATION_ANNULEE"))


class TestListe(Fix):
    def test_liste_filtres_et_totaux(self):
        self.lier_parent()
        a = self.convoquer(envoyer=True)
        b = self.convoquer(matricule="0000/26", motif="Retards fréquents")
        c = self.convoquer(matricule="0009/26", motif="Bagarre")
        l = cv.liste(self.conn, self.dird)
        self.assertEqual([x["id"] for x in l["convocations"]], [c["id"], b["id"], a["id"]])
        self.assertEqual(l["totaux"], {"BROUILLON": 2, "ENVOYEE": 1, "ANNULEE": 0})
        self.assertEqual([x["id"] for x in cv.liste(self.conn, self.dird, statut="ENVOYEE")["convocations"]], [a["id"]])
        self.assertEqual([x["id"] for x in cv.liste(self.conn, self.dird, n_classe=self.c8)["convocations"]], [c["id"]])
        self.assertEqual([x["id"] for x in cv.liste(self.conn, self.dird, texte="Kasongo")["convocations"]], [b["id"]])
        env = [x for x in cv.liste(self.conn, self.dird)["convocations"] if x["id"] == a["id"]][0]
        self.assertEqual((env["nb_destinataires"], env["nb_lues"]), (1, 0))

    def test_lettre_du_detail_suit_le_modele(self):
        r = self.convoquer(instructions="Apporter le carnet")
        d = cv.detail(self.conn, self.dird, r["id"])
        l = d["lettre"]
        self.assertEqual((l["ecole"], l["titre"], l["signature"]), (config.NOM_ECOLE, "CONVOCATION DU PARENT", "Le Directeur de discipline"))
        self.assertEqual([x[0] for x in l["lignes"]], ["Élève", "Classe", "Parent ou tuteur", "Motif", "Date du rendez-vous", "Heure", "Lieu"])
        self.assertEqual(l["instructions"], "Apporter le carnet")
        self.assertIn("situation scolaire de votre enfant", l["texte"])


class TestDroits(Fix):
    def test_lecture_pour_le_directeur_ajout_par_defaut_modification_non(self):
        self.assertTrue(cv.peut(self.conn, self.dird, "LECTURE"))
        self.assertTrue(cv.peut(self.conn, self.dird, "AJOUT"))
        self.assertFalse(cv.peut(self.conn, self.dird, "MODIFICATION"))

    def test_autres_postes_refuses(self):
        for s in (self.secr, self.dire):
            for appel in (lambda: cv.chercher_eleves(self.conn, s, "Amisi"), lambda: cv.liste(self.conn, s),
                          lambda: cv.coordonnees_parent(self.conn, s, "0001/26"),
                          lambda: cv.enregistrer(self.conn, s, "0001/26", "Absences répétées", DEMAIN, "09:00")):
                with self.assertRaises(PermissionError):
                    appel()

    def test_lecture_seule_ne_peut_pas_enregistrer(self):
        droits.remplacer_droits(self.conn, self.dird.id_user, {("direction_discipline", "LECTURE")})
        self.conn.commit()
        self.assertTrue(cv.liste(self.conn, self.dird)["annee"])
        with self.assertRaises(PermissionError):
            self.convoquer()


class TestParent(Fix):
    """API de l'application des parents : /parent/api/convocations."""

    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])
        self.cl = self.app.test_client()
        self.p1 = self.lier_parent()                                                   # Papa Amisi -> 0001/26
        self.p2 = self.lier_parent(matricule="0000/26", n_recu="R1", nom="Papa Kasongo", ident="0700000000")
        self.t1, self.t2 = sessions_web.ouvrir(self.p1, "PARENT"), sessions_web.ouvrir(self.p2, "PARENT")

    def get(self, url, jeton=None):
        return self.cl.get(url, headers={"Authorization": f"Bearer {jeton}"} if jeton else {})

    def post(self, url, jeton=None):
        return self.cl.post(url, json={}, headers={"Authorization": f"Bearer {jeton}"} if jeton else {})

    def test_le_parent_recoit_la_notification_et_seulement_la_sienne(self):
        r = self.convoquer(envoyer=True, instructions="Apporter le carnet")
        d = self.get("/parent/api/convocations", self.t1).get_json()
        self.assertEqual(d["non_lues"], 1)
        v = d["convocations"][0]
        self.assertEqual((v["id"], v["statut"], v["lue"], v["date"], v["heure"], v["lieu"]), (r["id"], "ENVOYEE", False, cv._fr(DEMAIN), "09:30", "Direction de discipline"))
        self.assertEqual(v["lettre"]["instructions"], "Apporter le carnet")
        self.assertIn("Amisi", v["enfant"])
        corps = self.get("/parent/api/convocations", self.t1).get_data(as_text=True)
        for interne in ("0001/26", "dird1", "enregistre", "ENREGISTRE_PAR"):
            self.assertNotIn(interne, corps)
        autre = self.get("/parent/api/convocations", self.t2).get_json()                # le parent d'un autre élève ne voit rien
        self.assertEqual((autre["convocations"], autre["non_lues"]), ([], 0))

    def test_brouillon_invisible_pour_le_parent(self):
        self.convoquer()
        self.assertEqual(self.get("/parent/api/convocations", self.t1).get_json()["convocations"], [])

    def test_accuse_de_lecture(self):
        r = self.convoquer(envoyer=True)
        self.assertEqual(self.post(f"/parent/api/convocations/{r['id']}/lue", self.t1).status_code, 200)
        d = self.get("/parent/api/convocations", self.t1).get_json()
        self.assertEqual((d["non_lues"], d["convocations"][0]["lue"]), (0, True))
        self.assertEqual(cv.liste(self.conn, self.dird)["convocations"][0]["nb_lues"], 1)
        self.assertTrue(cv.detail(self.conn, self.dird, r["id"])["destinataires"][0]["lue"])
        self.post(f"/parent/api/convocations/{r['id']}/lue", self.t1)                  # idempotent : une seule trace
        self.assertEqual(len(journal(self.conn, "PARENT_CONVOCATION_LUE")), 1)

    def test_un_parent_ne_peut_pas_marquer_la_convocation_d_un_autre(self):
        r = self.convoquer(envoyer=True)
        self.assertEqual(self.post(f"/parent/api/convocations/{r['id']}/lue", self.t2).status_code, 403)
        self.assertEqual(self.post("/parent/api/convocations/9999/lue", self.t1).status_code, 403)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CONVOCATION_DESTINATAIRE WHERE LU_LE IS NOT NULL").fetchone()[0], 0)

    def test_sans_session_ou_avec_une_session_du_personnel(self):
        self.assertEqual(self.get("/parent/api/convocations").status_code, 401)
        self.assertEqual(self.get("/parent/api/convocations", "n-importe-quoi").status_code, 401)
        self.assertEqual(self.post("/parent/api/convocations/1/lue").status_code, 401)

    def test_convocation_annulee_reste_visible_marquee_annulee(self):
        r = self.convoquer(envoyer=True)
        self.donner(self.dird, "MODIFICATION")
        cv.annuler(self.conn, self.dird, r["id"], "Rendez-vous reporté")
        d = self.get("/parent/api/convocations", self.t1).get_json()
        self.assertEqual((d["convocations"][0]["statut"], d["convocations"][0]["motif_annulation"], d["non_lues"]), ("ANNULEE", "Rendez-vous reporté", 0))

    def test_acces_coupe_cache_la_convocation(self):
        self.convoquer(envoyer=True)
        with self.conn:
            self.conn.execute("UPDATE PAIEMENT SET STATUT = 'ANNULE' WHERE N_RECU = 'R2'")
        self.assertEqual(self.get("/parent/api/convocations", self.t1).get_json()["convocations"], [])

    def test_compte_desactive_ne_recoit_plus(self):
        self.convoquer(envoyer=True)
        with self.conn:
            self.conn.execute("UPDATE COMPTE_PARENT SET ACTIF = 0 WHERE ID_PARENT = ?", (self.p1,))
        self.assertEqual(self.get("/parent/api/convocations", self.t1).status_code, 401)

    def test_la_page_parents_contient_les_convocations(self):
        page = self.cl.get("/parents").get_data(as_text=True)
        self.assertIn("/convocations", page)
        self.assertIn("ouvrirConvocations", page)


class TestWeb(Fix):
    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])
        self.cl = self.app.test_client()
        self.assertEqual(self.cl.post("/connexion", data={"login": "dird1", "mdp": MDP}).status_code, 302)
        self.base = "/m/etudes_discipline/direction_discipline"
        self.lier_parent()

    def champs(self, **kw):
        c = {"matricule": "0001/26", "motif": "Absences répétées", "date_rdv": DEMAIN, "heure_rdv": "09:30", "lieu": "Direction de discipline",
             "instructions": "Apporter le carnet", "envoyer": "1"}
        c.update(kw)
        return c

    def test_onglet_visible_et_parcours_de_choix_de_l_eleve(self):
        self.assertIn("Convocation du parent", self.cl.get(self.base).get_data(as_text=True))
        page = self.cl.get(self.base + "?f=convocation").get_data(as_text=True)
        self.assertIn("Sélectionner l'élève concerné", page)
        page = self.cl.get(self.base + "?f=convocation&q=Amisi").get_data(as_text=True)
        self.assertIn("Convoquer", page)
        self.assertNotIn("Petit", page)
        page = self.cl.get(self.base + "?f=convocation&eleve=0001%2F26").get_data(as_text=True)
        for texte in ("Papa Amisi", "0812345678", "Notification possible", "Enregistrer et envoyer au parent", "Instructions complémentaires"):
            self.assertIn(texte, page)

    def test_enregistrer_et_envoyer_par_la_page(self):
        r = self.cl.post(self.base + "/convocation/enregistrer", data=self.champs())
        self.assertEqual(r.status_code, 302)
        page = self.cl.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("Convocation envoyée", page)
        self.assertIn("CONVOCATION DU PARENT", page)
        self.assertIn("Papa Amisi", page)
        self.assertEqual(self.conn.execute("SELECT STATUT FROM CONVOCATION_PARENT").fetchone()[0], "ENVOYEE")
        self.assertIn("Convocations enregistrées", self.cl.get(self.base + "?f=convocation&vue=liste").get_data(as_text=True))

    def test_enregistrer_sans_envoyer_puis_envoyer(self):
        r = self.cl.post(self.base + "/convocation/enregistrer", data=self.champs(envoyer="0"))
        self.assertIn("brouillon", self.cl.get(r.headers["Location"]).get_data(as_text=True))
        i = self.conn.execute("SELECT ID_CONV FROM CONVOCATION_PARENT").fetchone()[0]
        r = self.cl.post(self.base + "/convocation/envoyer", data={"id": i})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.conn.execute("SELECT STATUT FROM CONVOCATION_PARENT").fetchone()[0], "ENVOYEE")

    def test_erreurs_affichees_et_formulaire_conserve(self):
        r = self.cl.post(self.base + "/convocation/enregistrer", data=self.champs(motif="x"))
        self.assertEqual(r.status_code, 400)
        page = r.get_data(as_text=True)
        self.assertIn("motif", page)
        self.assertIn("Apporter le carnet", page)                                     # le texte saisi n'est pas perdu
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CONVOCATION_PARENT").fetchone()[0], 0)

    def test_envoi_impossible_sans_compte_affiche_l_explication_et_garde_le_brouillon(self):
        r = self.cl.post(self.base + "/convocation/enregistrer", data=self.champs(matricule="0002/26"))
        self.assertEqual(r.status_code, 200)
        page = r.get_data(as_text=True)
        self.assertIn("Aucun parent", page)
        self.assertEqual(self.conn.execute("SELECT STATUT FROM CONVOCATION_PARENT").fetchone()[0], "BROUILLON")

    def test_annuler_par_la_page_selon_le_droit(self):
        self.cl.post(self.base + "/convocation/enregistrer", data=self.champs())
        i = self.conn.execute("SELECT ID_CONV FROM CONVOCATION_PARENT").fetchone()[0]
        self.assertEqual(self.cl.post(self.base + "/convocation/annuler", data={"id": i, "motif_annulation": "Reporté"}).status_code, 403)
        self.donner(self.dird, "MODIFICATION")
        self.assertEqual(self.cl.post(self.base + "/convocation/annuler", data={"id": i, "motif_annulation": ""}).status_code, 400)
        r = self.cl.post(self.base + "/convocation/annuler", data={"id": i, "motif_annulation": "Reporté"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("Annulée", self.cl.get(r.headers["Location"]).get_data(as_text=True))

    def test_impression_de_la_lettre(self):
        self.cl.post(self.base + "/convocation/enregistrer", data=self.champs())
        i = self.conn.execute("SELECT ID_CONV FROM CONVOCATION_PARENT").fetchone()[0]
        page = self.cl.get(f"{self.base}/convocation/{i}/impression").get_data(as_text=True)
        for texte in ("CONVOCATION DU PARENT", "Papa Amisi", "Le Directeur de discipline", "Apporter le carnet"):
            self.assertIn(texte, page)
        self.assertEqual(self.cl.get(f"{self.base}/convocation/9999/impression").status_code, 404)

    def test_les_autres_postes_n_ont_aucun_acces(self):
        secr = self.app.test_client()
        self.assertEqual(secr.post("/connexion", data={"login": "secr1", "mdp": MDP}).status_code, 302)
        i = self.convoquer(envoyer=True)["id"]
        self.assertEqual(secr.get(self.base + "?f=convocation").status_code, 403)
        self.assertEqual(secr.post(self.base + "/convocation/enregistrer", data=self.champs()).status_code, 403)
        self.assertEqual(secr.get(f"{self.base}/convocation/{i}/impression").status_code, 403)

    def test_origine_non_verifiee_refusee(self):
        r = self.cl.post(self.base + "/convocation/enregistrer", data=self.champs(), headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CONVOCATION_PARENT").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()

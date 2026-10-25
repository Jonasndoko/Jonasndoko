"""Tests de la proclamation : autorisation du titulaire, frais exigés (tranche ou totalité), validation par la Directrice des études,
changement de décision et confirmation par le Préfet, impression limitée aux bulletins validés (secondaire et humanitaire).
Lancer :  python -m unittest test_proclamation"""
import json
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web             # noqa: E402
import bulletins           # noqa: E402
import database            # noqa: E402
import proclamation        # noqa: E402
from notes import ErreurNotes                  # noqa: E402
from proclamation import ErreurProclamation    # noqa: E402
from test_notes import MDP                     # noqa: E402
from test_prefecture_v57 import Fixture        # noqa: E402


class Base(Fixture):
    """Fixture de la Préfecture + titulaire de la 7ème A (m1) + frais scolaire en 3 tranches de 100 (0000 : 200 payés, 0001 : 100, 0002 : rien)."""

    def setUp(self):
        super().setUp()
        c = self.conn
        with c:
            c.execute("INSERT INTO TYPE_FRAIS (CODTF, DESITF, MONTANT, CODE_DEVISE, PAR_TRANCHE, TRANCHES) "
                      "VALUES ('SCO', 'Frais scolaire', 30000, 'USD', 1, '10000;10000;10000')")
            for classe in (self.c7, self.c8):                                             # un paiement exige un tarif pour la classe
                c.execute("INSERT INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE, TRANCHES) VALUES ('SCO', ?, ?, 30000, 'USD', '10000;10000;10000')",
                          (classe, self.annee))
        self.payer_sco("0000/26", 20000, 101)
        self.payer_sco("0001/26", 10000, 102)
        bulletins.designer_titulaire(c, self.admin, self.annee, self.c7, self.m1)
        self.cle = f"P{self.per1}"

    def payer_sco(self, matricule, centimes, seq):
        classe = self.conn.execute("SELECT N_CLASSE FROM INSCRIRE WHERE MATRICULE = ?", (matricule,)).fetchone()[0]
        with self.conn:
            self.conn.execute("INSERT INTO PAIEMENT (N_RECU, ANNEESCO, NUM_SEQ, DATE_PAY, MATRICULE, N_CLASSE, CODTF, CODE_DEVISE, MONT_PAYE, N_PERC) "
                              "VALUES (?,?,?,?,?,?,'SCO','USD',?,1)", (f"R{seq}", self.annee, seq, "2026-09-10", matricule, classe, centimes))

    # raccourcis
    def autoriser(self):
        return proclamation.autoriser(self.conn, self.dire, self.annee, self.c7, self.cle)

    def criteres(self, *crit):
        return proclamation.definir_criteres(self.conn, self.dire, self.annee, self.c7, self.cle, [{"codtf": c, "tranche": t} for c, t in crit])

    def apercu(self, session=None):
        return proclamation.apercu(self.conn, session or self.dire, self.annee, self.c7, self.cle)

    def lignes(self):
        return {e["matricule"]: e for e in self.apercu()["eleves"]}

    def circuit_jusqu_a_la_confirmation(self, tranche=2):
        self.autoriser()
        self.criteres(("SCO", tranche))
        proclamation.valider(self.conn, self.dire, self.annee, self.c7, self.cle)
        proclamation.soumettre(self.conn, self.dire, self.annee, self.c7, self.cle)
        proclamation.confirmer(self.conn, self.prefet, self.annee, self.c7, self.cle)

    def pdf(self, genre="bulletins", matricule=None, cle=None):
        return bulletins.document_pdf(self.conn, self.s1, genre, self.annee, self.c7, cle or self.cle, matricule)


class TestFraisExiges(Base):
    def test_tranche_demandee(self):
        self.autoriser()
        self.criteres(("SCO", 2))
        l = self.lignes()
        self.assertEqual([l[m]["en_ordre"] for m in ("0000/26", "0001/26", "0002/26")], [True, False, False])
        self.assertEqual(l["0001/26"]["manques"], ["Frais scolaire (tranche 2)"])

    def test_premiere_tranche(self):
        self.autoriser()
        self.criteres(("SCO", 1))
        l = self.lignes()
        self.assertEqual([l[m]["en_ordre"] for m in ("0000/26", "0001/26", "0002/26")], [True, True, False])

    def test_totalite(self):
        self.autoriser()
        self.criteres(("SCO", None))
        self.assertEqual([e["en_ordre"] for e in self.apercu()["eleves"]], [False, False, False])      # personne n'a payé les 300
        self.payer_sco("0002/26", 30000, 103)
        self.assertTrue(self.lignes()["0002/26"]["en_ordre"])

    def test_autres_frais_en_plus(self):
        """0000 a payé 2 tranches du scolaire et le Minerval en totalité ; 0001 a payé la tranche 1 mais seulement 40 sur 100 de Minerval."""
        self.autoriser()
        self.criteres(("SCO", 1), ("MIN", None))
        l = self.lignes()
        self.assertEqual([l[m]["en_ordre"] for m in ("0000/26", "0001/26", "0002/26")], [True, False, False])
        self.assertEqual(l["0001/26"]["manques"], ["Minerval (totalité)"])

    def test_un_frais_non_du_n_empeche_pas(self):
        """Un frais réservé à une autre année d'étude n'est pas proposé ; un frais sans tarif pour la classe ne bloque personne."""
        with self.conn:
            self.conn.execute("INSERT INTO TYPE_FRAIS (CODTF, DESITF, MONTANT, CODE_DEVISE, CLASSE_CIBLE) VALUES ('EXA', 'Examen', 5000, 'USD', 'HUM4')")
        self.assertNotIn("EXA", [f["codtf"] for f in proclamation.frais_disponibles(self.conn, self.dire, self.annee, self.c7)])
        self.autoriser()
        with self.assertRaises(ErreurProclamation):
            self.criteres(("EXA", None))

    def test_les_frais_proposes(self):
        with self.conn:
            self.conn.execute("INSERT INTO TYPE_FRAIS (CODTF, DESITF, MONTANT, CODE_DEVISE, POUR_INSCRIPTION) VALUES ('INS', 'Inscription', 2000, 'USD', 1)")
        f = {x["codtf"]: x for x in proclamation.frais_disponibles(self.conn, self.dire, self.annee, self.c7)}
        self.assertEqual(set(f), {"MIN", "SCO"})                                      # pas le frais d'inscription
        self.assertEqual((f["SCO"]["par_tranche"], f["SCO"]["nb_tranches"]), (True, 3))
        self.assertEqual((f["MIN"]["par_tranche"], f["MIN"]["nb_tranches"]), (False, 0))

    def test_criteres_invalides(self):
        self.autoriser()
        for crit in ([], [("SCO", 4)], [("SCO", "x")], [("MIN", 1)], [("INCONNU", None)]):
            with self.assertRaises(ErreurProclamation, msg=str(crit)):
                self.criteres(*crit)
        self.assertEqual(self.apercu()["criteres"], [])

    def test_la_directrice_ne_voit_aucun_montant(self):
        self.autoriser()
        self.criteres(("SCO", 2), ("MIN", None))
        texte = json.dumps(self.apercu(), ensure_ascii=False)
        for interdit in ("10000", "20000", "100,00", "200,00", "MONT_PAYE", "montant"):
            self.assertNotIn(interdit, texte)


class TestCircuit(Base):
    def test_circuit_complet_et_impression(self):
        self.circuit_jusqu_a_la_confirmation()
        self.assertEqual(self.apercu()["statut"], "CONFIRMEE")
        pdf, nom = self.pdf("bulletin", "0000/26")
        self.assertTrue(pdf.startswith(b"%PDF"))
        pdf, _ = self.pdf("bulletins")
        self.assertEqual(pdf.count(b"/Type /Page "), 1)                                # un seul bulletin : 0000 est le seul validé
        with self.assertRaises(ErreurNotes) as e:
            self.pdf("bulletin", "0001/26")
        self.assertIn("pas validé", str(e.exception))

    def test_le_titulaire_consulte_toujours_mais_n_imprime_qu_au_bout(self):
        etapes = []
        r = bulletins.resultats(self.conn, self.s1, self.annee, self.c7, self.cle)         # consultation libre dès le départ
        self.assertEqual(len(r["lignes"]), 3)
        self.assertEqual((r["proclamation"]["statut"], r["proclamation"]["imprimable"]), (None, False))
        for genre, mat in (("bulletins", None), ("bulletin", "0000/26"), ("liste", None)):
            with self.assertRaises(ErreurNotes) as e:
                self.pdf(genre, mat)
            etapes.append(str(e.exception))
        self.assertTrue(all("pas encore autorisé" in m for m in etapes))
        self.autoriser()
        self.criteres(("SCO", 2))
        with self.assertRaises(ErreurNotes) as e:
            self.pdf("bulletin", "0000/26")
        self.assertIn("en cours de validation", str(e.exception))
        proclamation.valider(self.conn, self.dire, self.annee, self.c7, self.cle)
        proclamation.soumettre(self.conn, self.dire, self.annee, self.c7, self.cle)
        with self.assertRaises(ErreurNotes) as e:
            self.pdf("bulletin", "0000/26")
        self.assertIn("confirmation du Préfet", str(e.exception))
        r = bulletins.resultats(self.conn, self.s1, self.annee, self.c7, self.cle)
        self.assertEqual((r["proclamation"]["statut"], r["proclamation"]["imprimable"]), ("TRANSMISE", False))
        self.assertEqual([l["valide"] for l in r["lignes"]], [False, False, False])         # pas imprimable tant que le Préfet n'a pas confirmé
        proclamation.confirmer(self.conn, self.prefet, self.annee, self.c7, self.cle)
        r = bulletins.resultats(self.conn, self.s1, self.annee, self.c7, self.cle)
        self.assertEqual((r["proclamation"]["imprimable"], r["proclamation"]["nb_valides"]), (True, 1))
        self.assertEqual({l["matricule"]: l["valide"] for l in r["lignes"]}, {"0000/26": True, "0001/26": False, "0002/26": False})

    def test_chaque_periode_a_sa_proclamation(self):
        self.circuit_jusqu_a_la_confirmation()
        with self.assertRaises(ErreurNotes):
            self.pdf("bulletin", "0000/26", cle=f"P{self.per2}")                           # une autre période n'est pas autorisée
        with self.assertRaises(ErreurNotes):
            self.pdf("proclamation")                                                      # la proclamation de l'année demande « A »
        self.assertEqual(bulletins.document_pdf(self.conn, self.s1, "liste", self.annee, self.c7, self.cle)[1].startswith("resultats"), True)

    def test_un_autre_titulaire_ou_une_autre_classe_reste_refuse(self):
        self.circuit_jusqu_a_la_confirmation()
        with self.assertRaises(PermissionError):
            bulletins.document_pdf(self.conn, self.s2, "bulletins", self.annee, self.c7, self.cle)
        with self.assertRaises(PermissionError):
            self.pdf("bulletin", "0009/26")                                               # élève d'une autre classe

    def test_la_directrice_valide_seulement_les_eleves_en_ordre(self):
        self.autoriser()
        self.criteres(("SCO", 2))
        with self.assertRaises(ErreurProclamation) as e:
            proclamation.valider(self.conn, self.dire, self.annee, self.c7, self.cle, ["0000/26", "0001/26"])
        self.assertIn("Amisi", str(e.exception))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM VALIDATION_BULLETIN").fetchone()[0], 0)       # rien d'écrit
        with self.assertRaises(ErreurProclamation):
            proclamation.valider(self.conn, self.dire, self.annee, self.c7, self.cle, ["0009/26"])           # hors de la classe
        self.assertEqual(proclamation.valider(self.conn, self.dire, self.annee, self.c7, self.cle, ["0000/26"]), {"valides": 1, "deja": 0})
        self.assertEqual(proclamation.valider(self.conn, self.dire, self.annee, self.c7, self.cle, ["0000/26"]), {"valides": 0, "deja": 1})
        self.assertEqual(proclamation.retirer_validation(self.conn, self.dire, self.annee, self.c7, self.cle, ["0000/26"]), {"retires": 1})
        self.assertFalse(self.lignes()["0000/26"]["valide"])

    def test_il_faut_des_frais_avant_de_valider_et_des_bulletins_avant_de_soumettre(self):
        self.autoriser()
        with self.assertRaises(ErreurProclamation):
            proclamation.valider(self.conn, self.dire, self.annee, self.c7, self.cle)
        self.criteres(("SCO", 2))
        with self.assertRaises(ErreurProclamation):
            proclamation.soumettre(self.conn, self.dire, self.annee, self.c7, self.cle)

    def test_apres_la_soumission_la_directrice_ne_change_plus_rien(self):
        self.autoriser()
        self.criteres(("SCO", 2))
        proclamation.valider(self.conn, self.dire, self.annee, self.c7, self.cle)
        proclamation.soumettre(self.conn, self.dire, self.annee, self.c7, self.cle)
        for appel in (lambda: self.criteres(("SCO", 1)),
                      lambda: proclamation.valider(self.conn, self.dire, self.annee, self.c7, self.cle),
                      lambda: proclamation.retirer_validation(self.conn, self.dire, self.annee, self.c7, self.cle, ["0000/26"]),
                      lambda: proclamation.soumettre(self.conn, self.dire, self.annee, self.c7, self.cle)):
            with self.assertRaises(ErreurProclamation):
                appel()
        with self.assertRaises(ErreurProclamation):
            self.autoriser()                                                              # déjà autorisé

    def test_autorisation_par_periode_et_classe_valide(self):
        with self.assertRaises(ErreurProclamation):
            proclamation.autoriser(self.conn, self.dire, self.annee, self.c7, "Z99")
        with self.assertRaises(ErreurProclamation):
            proclamation.autoriser(self.conn, self.dire, self.annee, 9999, self.cle)
        self.assertEqual(self.apercu()["statut"], None)


class TestPrefet(Base):
    def test_le_prefet_change_la_decision_avec_motif(self):
        self.autoriser()
        self.criteres(("SCO", 2))
        proclamation.valider(self.conn, self.dire, self.annee, self.c7, self.cle)
        with self.assertRaises(ErreurProclamation):                                       # pas avant la soumission
            proclamation.changer_decision(self.conn, self.prefet, self.annee, self.c7, self.cle, "0001/26", True, "Dispense")
        proclamation.soumettre(self.conn, self.dire, self.annee, self.c7, self.cle)
        with self.assertRaises(ErreurProclamation):
            proclamation.changer_decision(self.conn, self.prefet, self.annee, self.c7, self.cle, "0001/26", True, "  ")      # motif obligatoire
        r = proclamation.changer_decision(self.conn, self.prefet, self.annee, self.c7, self.cle, "0001/26", True, "Arrangement avec la famille")
        self.assertTrue(r["change"])
        proclamation.changer_decision(self.conn, self.prefet, self.annee, self.c7, self.cle, "0000/26", False, "Fraude constatée")
        self.assertFalse(proclamation.changer_decision(self.conn, self.prefet, self.annee, self.c7, self.cle, "0000/26", False, "Encore")["change"])
        l = self.lignes()
        self.assertEqual((l["0001/26"]["valide"], l["0001/26"]["decision"]["origine"], l["0001/26"]["decision"]["motif"]),
                         (True, "PREFET", "Arrangement avec la famille"))
        self.assertFalse(l["0001/26"]["en_ordre"])                                       # le Préfet voit que l'élève n'est pas en ordre
        self.assertFalse(l["0000/26"]["valide"])
        proclamation.confirmer(self.conn, self.prefet, self.annee, self.c7, self.cle)
        self.pdf("bulletin", "0001/26")                                                   # imprimable après confirmation
        with self.assertRaises(ErreurNotes):
            self.pdf("bulletin", "0000/26")                                               # validation retirée par le Préfet

    def test_il_peut_encore_changer_apres_la_confirmation(self):
        self.circuit_jusqu_a_la_confirmation()
        proclamation.changer_decision(self.conn, self.prefet, self.annee, self.c7, self.cle, "0002/26", True, "Régularisé après la clôture")
        self.pdf("bulletin", "0002/26")

    def test_confirmer_demande_une_proclamation_soumise_avec_des_valides(self):
        with self.assertRaises(ErreurProclamation):
            proclamation.confirmer(self.conn, self.prefet, self.annee, self.c7, self.cle)         # pas encore autorisée
        self.autoriser()
        with self.assertRaises(ErreurProclamation):
            proclamation.confirmer(self.conn, self.prefet, self.annee, self.c7, self.cle)         # pas soumise
        self.criteres(("SCO", 2))
        proclamation.valider(self.conn, self.dire, self.annee, self.c7, self.cle)
        proclamation.soumettre(self.conn, self.dire, self.annee, self.c7, self.cle)
        proclamation.changer_decision(self.conn, self.prefet, self.annee, self.c7, self.cle, "0000/26", False, "Erreur de saisie")
        with self.assertRaises(ErreurProclamation):
            proclamation.confirmer(self.conn, self.prefet, self.annee, self.c7, self.cle)         # plus aucun bulletin validé
        proclamation.changer_decision(self.conn, self.prefet, self.annee, self.c7, self.cle, "0000/26", True, "Finalement en ordre")
        proclamation.confirmer(self.conn, self.prefet, self.annee, self.c7, self.cle)
        with self.assertRaises(ErreurProclamation):
            proclamation.confirmer(self.conn, self.prefet, self.annee, self.c7, self.cle)         # une seule fois

    def test_liste_des_proclamations(self):
        self.autoriser()
        l = proclamation.liste_proclamations(self.conn, self.prefet)["proclamations"]
        self.assertEqual([(x["classe"], x["statut"], x["valides"]) for x in l], [("7ème A", "AUTORISEE", 0)])


class TestDroitsEtJournal(Base):
    def test_chacun_son_role(self):
        for appel in (lambda: proclamation.autoriser(self.conn, self.prefet, self.annee, self.c7, self.cle),
                      lambda: proclamation.autoriser(self.conn, self.secr, self.annee, self.c7, self.cle)):
            with self.assertRaises(PermissionError):
                appel()
        self.autoriser()
        self.criteres(("SCO", 2))
        proclamation.valider(self.conn, self.dire, self.annee, self.c7, self.cle)
        with self.assertRaises(PermissionError):                                          # le Préfet ne valide pas, il confirme
            proclamation.valider(self.conn, self.prefet, self.annee, self.c7, self.cle)
        proclamation.soumettre(self.conn, self.dire, self.annee, self.c7, self.cle)
        for appel in (lambda: proclamation.confirmer(self.conn, self.dire, self.annee, self.c7, self.cle),
                      lambda: proclamation.changer_decision(self.conn, self.dire, self.annee, self.c7, self.cle, "0001/26", True, "x y z")):
            with self.assertRaises(PermissionError):                                      # la Directrice ne confirme pas et ne change pas
                appel()
        for poste in (self.secr, self.dird, self.s1):
            with self.assertRaises(PermissionError):
                proclamation.apercu(self.conn, poste, self.annee, self.c7, self.cle)
        self.assertEqual(self.apercu(self.prefet)["statut"], "TRANSMISE")                 # le Préfet consulte

    def test_lecture_seule(self):
        u = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = 'dire1'").fetchone()[0]
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'direction_etudes' AND DROIT = 'MODIFICATION'", (u,))
        self.assertEqual(self.apercu()["statut"], None)
        with self.assertRaises(PermissionError):
            self.autoriser()

    def test_journal(self):
        self.circuit_jusqu_a_la_confirmation()
        proclamation.changer_decision(self.conn, self.prefet, self.annee, self.c7, self.cle, "0001/26", True, "Arrangement avec la famille")
        self.apercu()
        actions = self.actions()
        for a in ("PROCLAMATION_AUTORISEE", "PROCLAMATION_CRITERES", "BULLETIN_VALIDE", "PROCLAMATION_SOUMISE", "PROCLAMATION_CONFIRMEE",
                  "PROCLAMATION_DECISION_PREFET", "PROCLAMATION_CONSULTEE"):
            self.assertIn(a, actions)
        detail = self.conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = 'PROCLAMATION_DECISION_PREFET'").fetchone()[0]
        self.assertIn("0001/26", detail)
        self.assertIn("Arrangement avec la famille", detail)
        self.assertEqual(self.conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = 'PROCLAMATION_CRITERES'").fetchone()[0].count("tranche 2"), 1)
        self.assertEqual(database.verifier_journal(self.conn), (True, None))
        import audit
        for a in ("PROCLAMATION_AUTORISEE", "PROCLAMATION_CRITERES", "BULLETIN_VALIDE", "BULLETIN_VALIDATION_RETIREE", "PROCLAMATION_SOUMISE",
                  "PROCLAMATION_DECISION_PREFET", "PROCLAMATION_CONFIRMEE", "PROCLAMATION_CONSULTEE"):
            self.assertIn(a, audit.ACTIONS)

    def test_le_primaire_n_a_pas_ce_circuit(self):
        """Un titulaire de classe du primaire imprime comme avant : le circuit ne concerne que le secondaire et humanitaire."""
        with self.assertRaises(ErreurProclamation):
            proclamation.autoriser(self.conn, self.dire, self.annee, self.cp, self.cle)


class TestWeb(Base):
    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])
        self.dir_c = self.client("dire1")
        self.pre_c = self.client("prefet1")

    def client(self, login):
        cl = self.app.test_client()
        self.assertEqual(cl.post("/connexion", data={"login": login, "mdp": MDP}).status_code, 302)
        return cl

    def donnees(self, **plus):
        d = {"annee": self.annee, "classe": str(self.c7), "cle": self.cle}
        d.update(plus)
        return d

    def post(self, cl, sous, action, **plus):
        return cl.post(f"/m/etudes_discipline/{sous}/proclamation/{action}", data=self.donnees(**plus))

    def test_le_circuit_par_les_pages(self):
        page = self.dir_c.get("/m/etudes_discipline/direction_etudes?f=proclamation").get_data(as_text=True)
        self.assertIn("Proclamation des résultats", page)
        r = self.post(self.dir_c, "direction_etudes", "autoriser")
        self.assertEqual(r.status_code, 302)
        page = self.dir_c.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("Titulaire autorisé pour cette période.", page)
        self.assertIn("Frais scolaire", page)
        self.assertEqual(self.post(self.dir_c, "direction_etudes", "criteres", frais_SCO="2", frais_MIN="").status_code, 302)
        page = self.dir_c.get(f"/m/etudes_discipline/direction_etudes?f=proclamation&annee={self.annee}&classe={self.c7}&cle={self.cle}").get_data(as_text=True)
        self.assertIn("Valider tous les élèves en ordre", page)
        self.assertIn("Frais scolaire (tranche 2)", page)
        self.assertEqual(self.post(self.dir_c, "direction_etudes", "valider_ordre").status_code, 302)
        self.assertEqual(self.post(self.dir_c, "direction_etudes", "soumettre").status_code, 302)
        page = self.pre_c.get(f"/m/etudes_discipline/prefecture?f=proclamation&annee={self.annee}&classe={self.c7}&cle={self.cle}").get_data(as_text=True)
        self.assertIn("Confirmer la proclamation", page)
        self.assertEqual(self.post(self.pre_c, "prefecture", "decision", matricule="0001/26", valide="1", motif="").status_code, 400)
        self.assertEqual(self.post(self.pre_c, "prefecture", "decision", matricule="0001/26", valide="1", motif="Arrangement").status_code, 302)
        self.assertEqual(self.post(self.pre_c, "prefecture", "confirmer").status_code, 302)
        self.assertEqual(self.apercu()["statut"], "CONFIRMEE")
        self.assertEqual(sorted(m for m, e in self.lignes().items() if e["valide"]), ["0000/26", "0001/26"])

    def test_erreur_affichee_et_droits_du_serveur(self):
        r = self.post(self.dir_c, "direction_etudes", "valider_ordre")                    # pas encore autorisé
        self.assertEqual(r.status_code, 400)
        self.assertIn("pas encore autorisé", r.get_data(as_text=True))
        self.assertEqual(self.post(self.pre_c, "direction_etudes", "autoriser").status_code, 403)       # le Préfet n'a pas l'espace de la Directrice
        self.assertEqual(self.post(self.dir_c, "prefecture", "confirmer").status_code, 403)
        self.assertEqual(self.post(self.dir_c, "direction_etudes", "confirmer").status_code, 404)       # action inconnue pour cet espace
        self.assertEqual(self.dir_c.get("/m/etudes_discipline/prefecture?f=proclamation").status_code, 403)

    def test_le_titulaire_est_informe_par_l_api(self):
        page = self.dir_c.get("/m/etudes_discipline/direction_etudes?f=proclamation")
        self.assertEqual(page.status_code, 200)
        r = bulletins.resultats(self.conn, self.s1, self.annee, self.c7, self.cle)
        self.assertIn("Pas encore autorisée", r["proclamation"]["libelle"])


if __name__ == "__main__":
    unittest.main()

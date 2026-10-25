"""Tests de la v0.57 : écran d'accueil du module, Préfecture (situation financière, décisions et rapports), rapports des directions.
Lancer :  python -m unittest test_prefecture_v57"""
import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web         # noqa: E402
import config          # noqa: E402
import droits          # noqa: E402
import migrations      # noqa: E402
import prefecture      # noqa: E402
import security        # noqa: E402
from prefecture import ErreurPrefecture   # noqa: E402
from test_notes import Base, MDP          # noqa: E402


class Fixture(Base):
    """Préfet, directions, secrétaire, élèves du secondaire (dont un du primaire) et frais : 0000 soldé, 0001 partiel, 0002 et 0009 sans paiement."""

    def setUp(self):
        super().setUp()
        c = self.conn
        for login, role in (("prefet1", "PREFET"), ("dire1", "DIRECTRICE_ETUDES"), ("dird1", "DIRECTEUR_DISCIPLINE"),
                            ("secr1", "SECRETAIRE"), ("perc1", "PERCEPTEUR")):
            security.creer_utilisateur(c, login, login.title(), role, MDP)
        self.prefet, self.dire, self.dird, self.secr = (security.authentifier(c, x, MDP).session for x in ("prefet1", "dire1", "dird1", "secr1"))
        with c:
            c.execute("INSERT INTO DEVISE (CODE_DEVISE, DESI_DEVISE) VALUES ('USD', 'Dollar')")
            c.execute("INSERT INTO TYPE_FRAIS (CODTF, DESITF, MONTANT, CODE_DEVISE) VALUES ('MIN', 'Minerval', 10000, 'USD')")
            # un élève du PRIMAIRE (avec une dette) : il ne doit jamais apparaître
            c.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU, SECTION) VALUES ('PRI', 'Primaire', 'PRIMAIRE')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('3ème prim', 'PRI', '3ème', 'A')")
            self.cp = c.execute("SELECT MAX(N_CLASSE) FROM CLASSE").fetchone()[0]
            c.execute("INSERT INTO ELEVE (MATRICULE, NOM, SEXE) VALUES ('0100/26', 'Petit', 'F')")
            c.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?,?,?)", (self.annee, "0100/26", self.cp))
            for classe in (self.c7, self.c8, self.cp):
                c.execute("INSERT INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE) VALUES ('MIN', ?, ?, 10000, 'USD')", (classe, self.annee))
        self.payer("0000/26", 10000, 1)            # soldé
        self.payer("0001/26", 4000, 2)             # partiel (reste 60,00)
        # 0002/26 et 0009/26 n'ont rien payé

    def payer(self, matricule, centimes, seq):
        classe = self.conn.execute("SELECT N_CLASSE FROM INSCRIRE WHERE MATRICULE = ?", (matricule,)).fetchone()[0]
        with self.conn:
            self.conn.execute("INSERT INTO PAIEMENT (N_RECU, ANNEESCO, NUM_SEQ, DATE_PAY, MATRICULE, N_CLASSE, CODTF, CODE_DEVISE, MONT_PAYE, N_PERC) "
                              "VALUES (?,?,?,?,?,?,'MIN','USD',?,1)", (f"R{seq}", self.annee, seq, "2026-09-10", matricule, classe, centimes))

    def nb_paiements(self):
        return self.conn.execute("SELECT COUNT(*), COALESCE(SUM(MONT_PAYE), 0) FROM PAIEMENT").fetchone()[:]

    def decision(self, **plus):
        champs = dict(date_decision=date.today().isoformat(), categorie="disciplinaire", objet="Renvoi temporaire", detail="Trois jours",
                      annee=self.annee, matricule="0001/26")
        champs.update(plus)
        return prefecture.enregistrer_decision(self.conn, self.prefet, **champs)


class TestV57(Fixture):
    # ------------------------------------------------------------------ 3. situation financière
    def test_totaux_et_nombre_d_eleves(self):
        r = prefecture.situation_financiere(self.conn, self.prefet)
        self.assertEqual(r["annee"], self.annee)
        self.assertEqual(r["resume"]["eleves"], 4)                       # l'élève du primaire n'est pas compté
        self.assertEqual((r["resume"]["en_regle"], r["resume"]["avec_dette"]), (1, 3))
        usd = r["resume"]["devises"][0]
        self.assertEqual((usd["devise"], usd["du"], usd["paye"], usd["reste"]), ("USD", "400,00", "140,00", "260,00"))
        self.assertNotIn("0100/26", [e["matricule"] for e in r["eleves"]])

    def test_filtres_dette_et_regle(self):
        dette = prefecture.situation_financiere(self.conn, self.prefet, filtre="dette")
        self.assertEqual(sorted(e["matricule"] for e in dette["eleves"]), ["0001/26", "0002/26", "0009/26"])
        regle = prefecture.situation_financiere(self.conn, self.prefet, filtre="regle")
        self.assertEqual([e["matricule"] for e in regle["eleves"]], ["0000/26"])
        classe = prefecture.situation_financiere(self.conn, self.prefet, n_classe=self.c8)
        self.assertEqual([e["matricule"] for e in classe["eleves"]], ["0009/26"])
        nom = prefecture.situation_financiere(self.conn, self.prefet, texte="Amisi")
        self.assertEqual([e["matricule"] for e in nom["eleves"]], ["0001/26"])

    def test_detail_d_un_eleve(self):
        d = prefecture.finances_eleve(self.conn, self.prefet, "0001/26")
        self.assertEqual([(l["designation"], l["du"], l["paye"], l["reste"], l["statut"]) for l in d["frais"]],
                         [("Minerval", "100,00", "40,00", "60,00", "Partiel")])
        self.assertFalse(d["en_regle"])
        self.assertTrue(prefecture.finances_eleve(self.conn, self.prefet, "0000/26")["en_regle"])
        with self.assertRaises(PermissionError):
            prefecture.finances_eleve(self.conn, self.prefet, "0100/26")        # élève du primaire
        with self.assertRaises(ErreurPrefecture):
            prefecture.finances_eleve(self.conn, self.prefet, "9999/99")

    def test_finances_consultation_seule_et_journal(self):
        avant = self.nb_paiements()
        prefecture.situation_financiere(self.conn, self.prefet)
        prefecture.finances_eleve(self.conn, self.prefet, "0002/26")
        self.assertEqual(self.nb_paiements(), avant)                              # rien ne s'encaisse ici
        for nom in ("encaisser", "enregistrer_paiement", "payer"):
            self.assertFalse(hasattr(prefecture, nom))
        self.assertTrue({"PREFECTURE_FINANCES_CONSULTEES", "PREFECTURE_FINANCE_ELEVE_CONSULTEE"} <= set(self.actions()))

    def test_finances_droits(self):
        for s in (self.secr, self.dire):
            with self.assertRaises(PermissionError):
                prefecture.situation_financiere(self.conn, s)
        # le Préfet perd la Lecture sur « Paiement des frais » : plus de chiffres, même avec la Préfecture
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'paiement'", (self.prefet.id_user,))
        self.assertFalse(prefecture.peut_finances(self.conn, self.prefet))
        with self.assertRaises(PermissionError):
            prefecture.situation_financiere(self.conn, self.prefet)
        with self.assertRaises(PermissionError):
            prefecture.finances_eleve(self.conn, self.prefet, "0000/26")
        self.assertTrue(prefecture.situation_financiere(self.conn, self.admin)["eleves"])

    # ------------------------------------------------------------------ 4. décisions
    def test_enregistrer_et_lister_une_decision(self):
        n = self.decision()
        l = prefecture.liste_decisions(self.conn, self.prefet)["decisions"]
        self.assertEqual(len(l), 1)
        self.assertEqual((l[0]["id"], l[0]["objet"], l[0]["categorie"], l[0]["matricule"], l[0]["annulee"]), (n, "Renvoi temporaire", "Disciplinaire", "0001/26", False))
        self.assertIn("Amisi", l[0]["eleve"])
        self.assertIn("PREFECTURE_DECISION_ENREGISTREE", self.actions())
        autre = self.decision(categorie="pedagogique", objet="Reprise de l'examen", matricule="")
        self.assertEqual([d["id"] for d in prefecture.liste_decisions(self.conn, self.prefet, categorie="pedagogique")["decisions"]], [autre])

    def test_date_au_format_jj_mm_aaaa(self):
        self.decision(date_decision="05/09/2026")
        self.assertEqual(prefecture.liste_decisions(self.conn, self.prefet)["decisions"][0]["date"], "05/09/2026")

    def test_validations(self):
        demain = (date.today() + timedelta(days=1)).isoformat()
        for plus in ({"objet": "  "}, {"objet": "x" * 151}, {"date_decision": demain}, {"date_decision": "pas une date"},
                     {"categorie": "inconnue"}, {"matricule": "9999/99"}, {"annee": "1999-2000"}, {"detail": "y" * 4001}):
            with self.assertRaises(ErreurPrefecture, msg=str(plus)):
                self.decision(**plus)
        with self.assertRaises(PermissionError):
            self.decision(matricule="0100/26")                                      # élève du primaire
        self.assertEqual(prefecture.liste_decisions(self.conn, self.prefet)["decisions"], [])

    def test_annulation_garde_la_decision(self):
        n = self.decision()
        with self.assertRaises(ErreurPrefecture):
            prefecture.annuler_decision(self.conn, self.prefet, n, "ok")             # motif trop court
        prefecture.annuler_decision(self.conn, self.prefet, n, "Décision prise par erreur")
        d = prefecture.liste_decisions(self.conn, self.prefet)["decisions"][0]
        self.assertTrue(d["annulee"])
        self.assertEqual((d["annule_par"], d["motif"]), ("prefet1", "Décision prise par erreur"))
        with self.assertRaises(ErreurPrefecture):
            prefecture.annuler_decision(self.conn, self.prefet, n, "Encore une fois")
        with self.assertRaises(ErreurPrefecture):
            prefecture.annuler_decision(self.conn, self.prefet, 9999, "Décision inconnue")
        self.assertIn("PREFECTURE_DECISION_ANNULEE", self.actions())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM DECISION_PREFET").fetchone()[0], 1)      # jamais supprimée

    def test_droits_des_decisions(self):
        for s in (self.secr, self.dire, self.dird):
            with self.assertRaises(PermissionError):
                prefecture.enregistrer_decision(self.conn, s, date.today().isoformat(), "autre", "Essai")
            with self.assertRaises(PermissionError):
                prefecture.liste_decisions(self.conn, s)
        n = self.decision()
        with self.conn:                                                              # plus d'« Ajout » : consultation seulement
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'prefecture' AND DROIT = 'AJOUT'", (self.prefet.id_user,))
        with self.assertRaises(PermissionError):
            self.decision()
        self.assertEqual(len(prefecture.liste_decisions(self.conn, self.prefet)["decisions"]), 1)
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'prefecture' AND DROIT = 'MODIFICATION'", (self.prefet.id_user,))
        with self.assertRaises(PermissionError):
            prefecture.annuler_decision(self.conn, self.prefet, n, "Motif suffisant")

    # ------------------------------------------------------------------ rapports des responsables
    def test_rapport_d_une_direction_lu_par_le_prefet(self):
        n = prefecture.deposer_rapport(self.conn, self.dire, "direction_etudes", "Bilan de la 1re période", "Résultats en hausse.")
        m = prefecture.deposer_rapport(self.conn, self.dird, "direction_discipline", "Incidents d'octobre", "Deux retards répétés.")
        tous = prefecture.rapports_des_responsables(self.conn, self.prefet)
        self.assertEqual({r["id"] for r in tous}, {n, m})
        self.assertEqual([r["id"] for r in prefecture.rapports_des_responsables(self.conn, self.prefet, "direction_etudes")], [n])
        self.assertEqual(tous[0]["direction"] in ("Direction des études", "Direction de discipline"), True)
        self.assertIn("RAPPORT_ENVOYE_AU_PREFET", self.actions())
        self.assertIn("PREFECTURE_RAPPORTS_CONSULTES", self.actions())

    def test_chaque_direction_ne_voit_que_ses_rapports(self):
        prefecture.deposer_rapport(self.conn, self.dire, "direction_etudes", "Titre", "Texte")
        self.assertEqual(len(prefecture.rapports_de_la_direction(self.conn, self.dire, "direction_etudes")), 1)
        for s, espace in ((self.dird, "direction_etudes"), (self.secr, "direction_etudes"), (self.prefet, "direction_etudes")):
            with self.assertRaises(PermissionError):
                prefecture.rapports_de_la_direction(self.conn, s, espace)
        with self.assertRaises(PermissionError):
            prefecture.deposer_rapport(self.conn, self.dird, "direction_etudes", "Titre", "Texte")      # pas son espace
        with self.assertRaises(PermissionError):
            prefecture.deposer_rapport(self.conn, self.secr, "direction_etudes", "Titre", "Texte")
        for s in (self.dire, self.dird, self.secr):                                  # les rapports reçus ne sont lisibles que par le Préfet
            with self.assertRaises(PermissionError):
                prefecture.rapports_des_responsables(self.conn, s)
        with self.assertRaises(ErreurPrefecture):
            prefecture.deposer_rapport(self.conn, self.dire, "direction_etudes", "", "Texte")
        with self.assertRaises(ErreurPrefecture):
            prefecture.deposer_rapport(self.conn, self.dire, "direction_etudes", "Titre", "  ")
        with self.assertRaises(ErreurPrefecture):
            prefecture.deposer_rapport(self.conn, self.dire, "inconnu", "Titre", "Texte")

    # ------------------------------------------------------------------ migration et valeurs par défaut
    def test_droits_par_defaut_des_postes(self):
        self.assertTrue({"LECTURE", "AJOUT", "MODIFICATION"} <= {d for m, d in droits.droits_par_defaut(self.conn, "PREFET") if m == "prefecture"})
        self.assertIn(("direction_etudes", "AJOUT"), droits.droits_par_defaut(self.conn, "DIRECTRICE_ETUDES"))
        self.assertIn(("direction_discipline", "AJOUT"), droits.droits_par_defaut(self.conn, "DIRECTEUR_DISCIPLINE"))
        self.assertNotIn(("prefecture", "SUPPRESSION"), droits.droits_par_defaut(self.conn, "PREFET"))

    def test_migration_13_comptes_existants(self):
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE DROIT = 'AJOUT' AND MODULE IN ('prefecture','direction_etudes','direction_discipline')")
            self.conn.execute("DELETE FROM ROLE_DROIT WHERE DROIT = 'AJOUT' AND MODULE IN ('prefecture','direction_etudes','direction_discipline')")
        migrations._mig_prefecture_decisions(self.conn)
        self.assertTrue(prefecture.peut_ecrire(self.conn, self.prefet, "AJOUT"))
        self.assertTrue(prefecture.peut_rapport(self.conn, self.dire, "direction_etudes", "AJOUT"))
        self.assertTrue(prefecture.peut_rapport(self.conn, self.dird, "direction_discipline", "AJOUT"))
        self.assertEqual(self.conn.execute("PRAGMA user_version").fetchone()[0], migrations.VERSION_SCHEMA)
        self.assertGreaterEqual(migrations.VERSION_SCHEMA, 13)


class TestV57Web(Fixture):
    """Pages : écran d'accueil à cartes, espaces, formulaires (mêmes données que ci-dessus)."""

    def setUp(self):
        super().setUp()
        chemin = self.conn.execute("PRAGMA database_list").fetchone()[2]
        self.app = app_web.creer_app(chemin)
        self.clients = {}
        for login in ("prefet1", "dire1", "dird1", "secr1", "perc1", "admin1"):
            cl = self.app.test_client()
            self.assertEqual(cl.post("/connexion", data={"login": login, "mdp": MDP}).status_code, 302)
            self.clients[login] = cl

    def page(self, login, url, **kw):
        r = self.clients[login].get(url, **kw)
        return r.status_code, r.get_data(as_text=True)

    def test_modules_a_part_et_ancienne_adresse(self):
        code, html = self.page("prefet1", "/menu")
        self.assertEqual(code, 200)
        self.assertIn('href="/m/prefecture"', html)
        for absent in ("Gestion des études et discipline", "/m/etudes\"", "/m/discipline", "/m/secretariat"):
            self.assertNotIn(absent, html)
        r = self.clients["prefet1"].get("/m/etudes_discipline")           # ancienne adresse : premier module ouvert
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/m/etudes_discipline/prefecture"))
        self.assertEqual(self.page("dire1", "/m/etudes_discipline/prefecture")[0], 403)
        code, html = self.page("dire1", "/m/etudes_discipline/direction_etudes")
        self.assertEqual(code, 200)
        self.assertNotIn('href="/m/etudes_discipline/prefecture"', html)
        self.assertEqual(self.page("perc1", "/m/etudes_discipline")[0], 403)
        admin = self.page("admin1", "/menu")[1]
        for cle_module in ("etudes", "discipline", "prefecture", "secretariat"):
            self.assertIn(f'href="/m/{cle_module}"', admin)

    def test_page_prefecture_a_ses_fonctionnalites(self):
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture")
        self.assertEqual(code, 200)
        for texte in ("Tableau de bord", "Suivi des élèves", "Situation financière des élèves", "Décisions et rapports", "Préfecture"):
            self.assertIn(texte, html)

    def test_page_finances(self):
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=finances")
        self.assertEqual(code, 200)
        self.assertIn("Consultation seule", html)
        self.assertIn("260,00", html)
        self.assertNotIn("0100/26", html)
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=finances&eleve=0001%2F26")
        self.assertEqual(code, 200)
        self.assertIn("Minerval", html)
        self.assertIn("60,00", html)
        self.assertNotIn("Enregistrer le paiement", html)
        self.assertEqual(self.page("prefet1", "/m/etudes_discipline/prefecture?f=finances&eleve=0100%2F26")[0], 403)
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'paiement'", (self.prefet.id_user,))
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=finances")
        self.assertEqual(code, 200)
        self.assertIn("Paiement des frais", html)
        self.assertNotIn("260,00", html)

    def test_enregistrer_puis_annuler_une_decision_en_ligne(self):
        cl = self.clients["prefet1"]
        r = cl.post("/m/etudes_discipline/prefecture/decisions", data={"date": date.today().isoformat(), "categorie": "administrative",
                                                                       "objet": "Fermeture exceptionnelle", "detail": "Fête nationale", "matricule": ""})
        self.assertEqual(r.status_code, 302)
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=decisions")
        self.assertIn("Fermeture exceptionnelle", html)
        self.assertIn("En vigueur", html)
        n = self.conn.execute("SELECT ID_DECISION FROM DECISION_PREFET").fetchone()[0]
        r = cl.post(f"/m/etudes_discipline/prefecture/decisions/{n}/annuler", data={"motif": "Date mal choisie"})
        self.assertEqual(r.status_code, 302)
        html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=decisions")[1]
        self.assertIn("Annulée", html)
        self.assertIn("Date mal choisie", html)
        # erreur de saisie : la page est réaffichée avec le message et la saisie
        r = cl.post("/m/etudes_discipline/prefecture/decisions", data={"date": date.today().isoformat(), "categorie": "autre", "objet": "", "detail": "Texte à garder"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Texte à garder", r.get_data(as_text=True))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM DECISION_PREFET").fetchone()[0], 1)

    def test_decisions_refusees_aux_autres(self):
        data = {"date": date.today().isoformat(), "categorie": "autre", "objet": "Essai"}
        for login in ("secr1", "dire1", "dird1", "perc1"):
            self.assertEqual(self.clients[login].post("/m/etudes_discipline/prefecture/decisions", data=data).status_code, 403, login)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM DECISION_PREFET").fetchone()[0], 0)
        r = self.clients["prefet1"].post("/m/etudes_discipline/prefecture/decisions", data=data, headers={"Origin": "https://autre-site.example"})
        self.assertEqual(r.status_code, 403)                                         # formulaire venu d'un autre site

    def test_rapport_envoye_en_ligne_puis_lu_par_le_prefet(self):
        r = self.clients["dire1"].post("/m/etudes_discipline/direction_etudes/rapport",
                                       data={"titre": "Bilan trimestriel", "contenu": "Les cours se déroulent bien.", "date": date.today().isoformat()})
        self.assertEqual(r.status_code, 302)
        self.assertIn("Bilan trimestriel", self.page("dire1", "/m/etudes_discipline/direction_etudes?f=rapport")[1])
        html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=decisions")[1]
        self.assertIn("Bilan trimestriel", html)
        self.assertIn("Les cours se déroulent bien.", html)
        self.assertNotIn("Bilan trimestriel", self.page("dird1", "/m/etudes_discipline/direction_discipline")[1])
        self.assertEqual(self.clients["dird1"].post("/m/etudes_discipline/direction_etudes/rapport", data={"titre": "T", "contenu": "C"}).status_code, 403)
        self.assertEqual(self.clients["secr1"].post("/m/etudes_discipline/dossier_eleve/rapport", data={"titre": "T", "contenu": "C"}).status_code, 404)
        self.assertEqual(self.clients["prefet1"].post("/m/etudes_discipline/direction_etudes/rapport", data={"titre": "T", "contenu": "C"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()

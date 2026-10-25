"""Tests de l'application mobile des parents (parents.py, web_parents.py) : code généré à la validation du paiement (1 paiement = 1 code = 1 élève),
activation, ajout d'un enfant, cloisonnement entre parents, reçu annulé, lecture des frais / présences / conduite / résultats, limites d'essais.
Lancer :  python -m unittest test_parents"""
import os
import re
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web             # noqa: E402
import paiements           # noqa: E402
import parents             # noqa: E402
import presence_eleves     # noqa: E402
import notes               # noqa: E402
import security            # noqa: E402
import sessions_web        # noqa: E402
from test_bulletins import Base as BaseBulletins, MDP   # noqa: E402

CODE = re.compile(r"^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")


class Base(BaseBulletins):
    def setUp(self):
        super().setUp()
        c = self.conn
        with c:
            c.execute("INSERT OR IGNORE INTO DEVISE (CODE_DEVISE, DESI_DEVISE) VALUES ('USD', 'Dollar')")
            c.execute("INSERT INTO TYPE_FRAIS (CODTF, DESITF, MONTANT, CODE_DEVISE, POUR_APPLI_PARENTS) VALUES ('APP', 'Frais du logiciel des parents', 500, 'USD', 1)")
            c.execute("INSERT INTO TYPE_FRAIS (CODTF, DESITF, MONTANT, CODE_DEVISE, PAR_TRANCHE, TRANCHES) VALUES ('EXA', 'Frais d''examen', 2000, 'USD', 1, '1000;1000')")
        security.creer_utilisateur(c, "perc1", "Marie Percepteur", "PERCEPTEUR", MDP)
        self.perc = security.authentifier(c, "perc1", MDP).session
        self.chemin = c.execute("PRAGMA database_list").fetchone()[2]
        self.app = app_web.creer_app(self.chemin)
        self.cl = self.app.test_client()

    def payer(self, matricule, codtf="APP", centimes=500):
        return paiements.enregistrer_paiement(self.conn, self.perc, matricule, self.annee, codtf, centimes)

    def code(self, matricule):
        n = self.payer(matricule)
        return parents.code_du_recu(self.conn, n)["code"], n

    def post(self, url, jeton=None, **corps):
        return self.cl.post(url, json=corps, headers={"Authorization": f"Bearer {jeton}"} if jeton else {})

    def get(self, url, jeton):
        return self.cl.get(url, headers={"Authorization": f"Bearer {jeton}"})

    def activer(self, matricule="0001/26", nom="Papa Amisi", ident="0812345678", mdp="Motdepasse1"):
        code, _ = self.code(matricule)
        r = self.post("/parent/api/inscription", code=code, nom=nom, identifiant=ident, mdp=mdp)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()


class TestCodes(Base):
    def test_un_paiement_du_frais_du_logiciel_genere_un_code(self):
        n = self.payer("0001/26")
        c = parents.code_du_recu(self.conn, n)
        self.assertRegex(c["code"], CODE)
        self.assertFalse(c["utilise"])
        self.assertIn("CODE_PARENT_GENERE", [r[0] for r in self.conn.execute("SELECT ACTION FROM JOURNAL")])
        self.assertNotIn(c["code"].replace("-", ""), " ".join(r[0] or "" for r in self.conn.execute("SELECT DETAIL FROM JOURNAL")))   # le code n'est pas dans le journal

    def test_un_autre_frais_ne_genere_pas_de_code(self):
        n = self.payer("0001/26", "EXA", 2000)
        self.assertIsNone(parents.code_du_recu(self.conn, n))

    def test_un_code_par_paiement_et_par_eleve(self):
        a, _ = self.code("0001/26")
        b, _ = self.code("0002/26")
        self.assertNotEqual(a, b)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CODE_PARENT").fetchone()[0], 2)
        with self.assertRaises(paiements.ErreurPaiement):            # déjà payé : pas de second reçu, donc pas de second code
            self.payer("0001/26")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CODE_PARENT").fetchone()[0], 2)

    def test_le_recu_pdf_porte_le_code(self):
        n = self.payer("0001/26")
        recu = paiements.charger_recu(self.conn, n)
        self.assertEqual(recu["code_parent"]["code"], parents.code_du_recu(self.conn, n)["code"])
        chemin = paiements.preparer_pdf(self.conn, self.perc, n, duplicata=False)
        with open(chemin, "rb") as f:
            self.assertTrue(f.read(5) == b"%PDF-")

    def test_l_espace_parents_web_est_public(self):
        r = self.cl.get("/parents")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Espace parents", r.get_data(as_text=True))
        self.assertIn("/parent/api", r.get_data(as_text=True))

    def test_une_page_de_telechargement_publique(self):
        r = self.cl.get("/parents/application")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Application Parents", r.get_data(as_text=True))
        self.assertEqual(self.cl.get("/parents/telecharger").status_code, 302)      # pas encore de fichier : retour à la page


class TestActivation(Base):
    def test_parcours_code_puis_compte(self):
        code, n = self.code("0001/26")
        v = self.post("/parent/api/code/verifier", code=code.lower().replace("-", " "))      # tolère minuscules et espaces
        self.assertEqual(v.status_code, 200)
        self.assertEqual(v.get_json()["classe"], "7ème A")
        self.assertNotIn("matricule", v.get_data(as_text=True).lower())
        r = self.post("/parent/api/inscription", code=code, nom="Papa Amisi", identifiant="0812 345 678", mdp="Motdepasse1")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertTrue(d["jeton"])
        self.assertEqual(len(d["enfants"]), 1)
        self.assertTrue(d["enfants"][0]["acces"])
        self.assertNotIn("0001/26", r.get_data(as_text=True))                                  # le matricule ne sort jamais
        self.assertTrue(parents.code_du_recu(self.conn, n)["utilise"])
        self.assertEqual(parents.code_du_recu(self.conn, n)["code"], "")                       # un code utilisé n'est plus montré

    def test_le_code_ne_sert_qu_une_fois(self):
        code, _ = self.code("0001/26")
        self.assertEqual(self.post("/parent/api/inscription", code=code, nom="Papa Amisi", identifiant="0812345678", mdp="Motdepasse1").status_code, 200)
        r = self.post("/parent/api/inscription", code=code, nom="Autre Personne", identifiant="0899999999", mdp="Motdepasse1")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.post("/parent/api/code/verifier", code=code).status_code, 400)

    def test_code_invalide(self):
        for faux in ("", "ABCD", "AAAA-BBBB-CCCC", "0000-0000-0000", None):
            self.assertEqual(self.post("/parent/api/code/verifier", code=faux).status_code, 400, faux)

    def test_mot_de_passe_et_identifiant_controles(self):
        code, _ = self.code("0001/26")
        for mdp in ("court1", "uniquementdeslettres", "12345678901"):
            self.assertEqual(self.post("/parent/api/inscription", code=code, nom="Papa Amisi", identifiant="0812345678", mdp=mdp).status_code, 400, mdp)
        self.assertEqual(self.post("/parent/api/inscription", code=code, nom="Papa Amisi", identifiant="abc", mdp="Motdepasse1").status_code, 400)
        self.assertEqual(self.post("/parent/api/inscription", code=code, nom="Pa", identifiant="0812345678", mdp="Motdepasse1").status_code, 400)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM COMPTE_PARENT").fetchone()[0], 0)
        self.assertFalse(parents.code_du_recu(self.conn, self.conn.execute("SELECT N_RECU FROM CODE_PARENT").fetchone()[0])["utilise"])   # le code n'est pas consommé

    def test_identifiant_deja_pris(self):
        self.activer()
        code, _ = self.code("0002/26")
        r = self.post("/parent/api/inscription", code=code, nom="Autre Papa", identifiant="0812345678", mdp="Motdepasse1")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(parents.code_du_recu(self.conn, self.conn.execute("SELECT N_RECU FROM CODE_PARENT WHERE MATRICULE = '0002/26'").fetchone()[0])["utilise"])

    def test_reçu_annule_le_code_ne_marche_plus(self):
        code, n = self.code("0001/26")
        with self.conn:
            self.conn.execute("UPDATE PAIEMENT SET STATUT = 'ANNULE', MOTIF_ANNULATION = 'erreur', DATE_ANNULATION = '2026-09-10T00:00:00', ANNULE_PAR = 'admin1' WHERE N_RECU = ?", (n,))
        self.assertEqual(self.post("/parent/api/code/verifier", code=code).status_code, 400)


class TestComptes(Base):
    def test_connexion_deconnexion_et_ajout_d_un_enfant(self):
        d = self.activer()
        r = self.post("/parent/api/connexion", identifiant="0812345678", mdp="Motdepasse1")
        self.assertEqual(r.status_code, 200)
        jeton = r.get_json()["jeton"]
        self.assertEqual(len(self.get("/parent/api/enfants", jeton).get_json()["enfants"]), 1)
        # un autre enfant : nouveau paiement, nouveau code (1 paiement = 1 élève)
        code2, _ = self.code("0002/26")
        r = self.post("/parent/api/enfants", jeton, code=code2)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        liste = self.get("/parent/api/enfants", jeton).get_json()["enfants"]
        self.assertEqual(len(liste), 2)
        self.assertEqual(self.post("/parent/api/enfants", jeton, code=code2).status_code, 400)       # code déjà utilisé
        self.post("/parent/api/deconnexion", jeton)
        self.assertEqual(self.get("/parent/api/enfants", jeton).status_code, 401)

    def test_mauvais_mot_de_passe_puis_blocage_du_compte(self):
        self.activer()
        for _ in range(parents.ECHECS_MAX_COMPTE):
            self.assertEqual(self.post("/parent/api/connexion", identifiant="0812345678", mdp="faux").status_code, 400)
        r = self.post("/parent/api/connexion", identifiant="0812345678", mdp="Motdepasse1")           # même le bon mot de passe est refusé un moment
        self.assertEqual(r.status_code, 400)
        self.assertIn("Patientez", r.get_json()["erreur"])

    def test_aucune_session_croisee_avec_le_personnel(self):
        d = self.activer()
        jeton_parent = d["jeton"]
        # le jeton d'un parent ne donne aucun accès au personnel (cookie) ni à l'API professeur
        self.cl.set_cookie("gestisc_session", jeton_parent)
        self.assertEqual(self.cl.get("/m/paiement").status_code, 302)
        # et un jeton du personnel ne sert à rien dans l'application des parents
        jeton_perso = sessions_web.ouvrir(self.perc.id_user, "PERSONNEL")
        self.assertEqual(self.get("/parent/api/enfants", jeton_perso).status_code, 401)
        self.assertEqual(self.get("/parent/api/enfants", "n'importe quoi").status_code, 401)
        self.assertEqual(self.cl.get("/parent/api/enfants").status_code, 401)

    def test_changer_le_mot_de_passe(self):
        d = self.activer()
        r = self.post("/parent/api/mot-de-passe", d["jeton"], ancien="Faux12345", nouveau="Nouveau12345")
        self.assertEqual(r.status_code, 400)
        r = self.post("/parent/api/mot-de-passe", d["jeton"], ancien="Motdepasse1", nouveau="Nouveau12345")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.get("/parent/api/enfants", d["jeton"]).status_code, 401)            # l'ancienne session est fermée
        self.assertEqual(self.post("/parent/api/connexion", identifiant="0812345678", mdp="Nouveau12345").status_code, 200)


class TestCloisonnement(Base):
    def test_un_parent_ne_voit_que_ses_enfants(self):
        a = self.activer("0001/26", ident="0811111111")
        b = self.activer("0002/26", nom="Papa Kasongo", ident="0822222222")
        id_a, id_b = a["enfants"][0]["id"], b["enfants"][0]["id"]
        self.assertNotEqual(id_a, id_b)
        for chemin in ("frais", "presences", "conduite", "resultats"):
            self.assertEqual(self.get(f"/parent/api/enfants/{id_a}/{chemin}", a["jeton"]).status_code, 200, chemin)
            r = self.get(f"/parent/api/enfants/{id_a}/{chemin}", b["jeton"])                        # l'enfant d'un autre parent
            self.assertEqual(r.status_code, 403, chemin)
            self.assertEqual(self.get(f"/parent/api/enfants/9999/{chemin}", a["jeton"]).status_code, 403, chemin)

    def test_reçu_annule_coupe_l_acces(self):
        a = self.activer("0001/26")
        id_a = a["enfants"][0]["id"]
        self.assertEqual(self.get(f"/parent/api/enfants/{id_a}/frais", a["jeton"]).status_code, 200)
        with self.conn:
            self.conn.execute("UPDATE PAIEMENT SET STATUT = 'ANNULE', MOTIF_ANNULATION = 'erreur', DATE_ANNULATION = '2026-09-10T00:00:00', ANNULE_PAR = 'admin1' "
                              "WHERE MATRICULE = '0001/26' AND CODTF = 'APP'")
        r = self.get(f"/parent/api/enfants/{id_a}/frais", a["jeton"])
        self.assertEqual(r.status_code, 403)
        self.assertFalse(r.get_json()["acces"])
        self.assertFalse(self.get("/parent/api/enfants", a["jeton"]).get_json()["enfants"][0]["acces"])

    def test_nouvelle_annee_il_faut_un_nouveau_paiement(self):
        a = self.activer("0001/26")
        with self.conn:
            self.conn.execute("INSERT INTO ANNEE_SCO (ANNEESCO, EN_COURS) VALUES ('2027-2028', 0)")
            self.conn.execute("UPDATE ANNEE_SCO SET EN_COURS = 0")
            self.conn.execute("UPDATE ANNEE_SCO SET EN_COURS = 1 WHERE ANNEESCO = '2027-2028'")
        self.assertFalse(self.get("/parent/api/enfants", a["jeton"]).get_json()["enfants"][0]["acces"])
        self.assertEqual(self.get(f"/parent/api/enfants/{a['enfants'][0]['id']}/frais", a["jeton"]).status_code, 403)


class TestDonnees(Base):
    def test_frais_payes_et_dettes(self):
        a = self.activer("0001/26")
        self.payer("0001/26", "EXA", 1000)                                                         # 10 sur 20 USD d'examen : partiel
        f = self.get(f"/parent/api/enfants/{a['enfants'][0]['id']}/frais", a["jeton"]).get_json()
        noms = [l["designation"] for l in f["lignes"]]
        self.assertIn("Frais d'examen", noms)
        self.assertNotIn("Frais du logiciel des parents", noms)                                    # le frais du logiciel n'est pas listé
        ex = next(l for l in f["lignes"] if l["designation"] == "Frais d'examen")
        self.assertEqual((ex["du"]["texte"], ex["paye"]["texte"], ex["reste"]["texte"], ex["statut"]), ("20,00", "10,00", "10,00", "Partiel"))
        self.assertEqual(f["totaux"][0]["reste"]["texte"], "10,00")
        self.assertEqual([p["frais"] for p in f["paiements"]], ["Frais d'examen"])
        self.assertNotIn("matricule", self.get(f"/parent/api/enfants/{a['enfants'][0]['id']}/frais", a["jeton"]).get_data(as_text=True).lower())

    def test_presences_conduite_et_resultats(self):
        a = self.activer("0001/26")
        c, adm = self.conn, self.admin
        jour1, jour2 = "15/09/2026", "16/09/2026"
        presence_eleves.marquer(c, self.s1, self.maths, jour1, "0001/26", "P")
        presence_eleves.marquer(c, self.s2, self.fr, jour1, "0001/26", "A")                        # absent en français : absent pour la journée
        presence_eleves.marquer(c, self.s1, self.maths, jour2, "0001/26", "P")
        self.saisir(self.s1, self.maths, self.pers[0], 30, (24, 18, 18, 9))
        self.saisir(self.s2, self.fr, self.pers[0], 20, (17, 12, 12, 6))
        notes.enregistrer_conduite(c, self.s1, self.maths, self.pers[0], "0001/26", "TB")
        notes.enregistrer_conduite(c, self.s2, self.fr, self.pers[0], "0001/26", "B")
        i = a["enfants"][0]["id"]

        p = self.get(f"/parent/api/enfants/{i}/presences", a["jeton"]).get_json()
        self.assertEqual((p["presents"], p["absents"], p["taux"]), (1, 1, 50.0))
        absent = next(j for j in p["jours"] if j["statut"] == "A")
        self.assertEqual(absent["manques"], ["Français"])

        cd = self.get(f"/parent/api/enfants/{i}/conduite", a["jeton"]).get_json()
        premiere = cd["periodes"][0]
        self.assertEqual(premiere["cote"], "B")                                                    # à égalité, la plus faible
        self.assertEqual({x["cours"]: x["cote"] for x in premiere["par_cours"]}, {"Mathématiques": "TB", "Français": "B"})

        r = self.get(f"/parent/api/enfants/{i}/resultats", a["jeton"]).get_json()
        cle = f"P{self.pers[0]}"
        par_cours = {x["libelle"]: x["cotes"][cle] for x in r["cours"]}
        self.assertEqual((par_cours["Mathématiques"]["obtenu"], par_cours["Mathématiques"]["max"]), (24, 30))
        total = next(t for t in r["totaux"] if t["cle"] == cle)
        self.assertEqual((total["obtenu"], total["max"], total["pct"], total["rang"], total["effectif"]), (41, 50, 82.0, 1, 4))
        # le parent ne reçoit que les points de SON enfant
        brut = self.get(f"/parent/api/enfants/{i}/resultats", a["jeton"]).get_data(as_text=True)
        for autre in ("0002/26", "0003/26", "0004/26", "Kasongo", "Tshala", "Zola"):
            self.assertNotIn(autre, brut)

    def test_lecture_seule(self):
        a = self.activer("0001/26")
        i = a["enfants"][0]["id"]
        for chemin in ("frais", "presences", "conduite", "resultats"):
            self.assertEqual(self.post(f"/parent/api/enfants/{i}/{chemin}", a["jeton"]).status_code, 405)
            self.assertEqual(self.cl.get(f"/parent/api/enfants/{i}/{chemin}.pdf", headers={"Authorization": f"Bearer {a['jeton']}"}).status_code, 404)


class TestReferentiel(Base):
    def test_le_frais_du_logiciel_est_un_champ_du_referentiel(self):
        import referentiels
        t = referentiels.TABLES["types_frais"]
        self.assertIn("POUR_APPLI_PARENTS", [c.nom for c in t.champs])


if __name__ == "__main__":
    unittest.main()

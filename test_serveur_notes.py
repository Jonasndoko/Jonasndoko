"""Tests du serveur web de la saisie des points (serveur_notes.py) : connexion, jeton, cloisonnement, changement de mot de passe,
points, impression PDF, protections. Lancer :  python test_serveur_notes.py"""
import http.client
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock
from urllib.parse import urlencode

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import notes            # noqa: E402
import security         # noqa: E402
import serveur_notes    # noqa: E402
from test_notes import Base, MDP  # noqa: E402


class TestServeur(Base):
    def setUp(self):
        super().setUp()
        self.chemin = self.conn.execute("PRAGMA database_list").fetchone()[2]
        self.srv = serveur_notes.Serveur(port=0, hote="127.0.0.1", chemin_bd=self.chemin).demarrer()
        self.addCleanup(self.srv.arreter)

    def appel(self, methode, chemin, corps=None, jeton=None, brut=False):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=20)
        en = {"Content-Type": "application/json"}
        if jeton:
            en["Authorization"] = "Bearer " + jeton
        c.request(methode, chemin, json.dumps(corps) if corps is not None else None, en)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, (data if brut else json.loads(data.decode("utf-8"))), dict(r.getheaders())

    def connexion(self, p, mdp=None):
        st, j, _ = self.appel("POST", "/api/connexion", {"login": p["login"], "mdp": mdp or p["mdp_temporaire"]})
        return st, j

    def pret(self, p):
        """Connexion + changement du mot de passe provisoire : retourne le jeton."""
        st, j = self.connexion(p)
        self.assertEqual(st, 200)
        self.assertTrue(j["doit_changer_mdp"])
        nouveau = "Nouveau-Mdp#2026-ok"
        st, r, _ = self.appel("POST", "/api/mdp", {"ancien": p["mdp_temporaire"], "nouveau": nouveau, "confirmation": nouveau}, j["jeton"])
        self.assertEqual(st, 200, r)
        return j["jeton"]

    def test_page_et_entetes_de_securite(self):
        st, data, en = self.appel("GET", "/", brut=True)
        self.assertEqual(st, 200)
        self.assertIn(b"Saisie des points", data)
        self.assertEqual(en.get("Cache-Control"), "no-store")
        self.assertIn("frame-ancestors 'none'", en.get("Content-Security-Policy", ""))
        self.assertEqual(self.appel("GET", "/inconnu")[0], 404)

    def test_connexion_refusee_pour_un_autre_poste_ou_un_mauvais_mot_de_passe(self):
        self.assertEqual(self.connexion(self.p1, "Mauvais-mdp#2026")[0], 401)
        security.creer_utilisateur(self.conn, "sec1", "Sophie", "SECRETAIRE", MDP)
        st, _, _ = self.appel("POST", "/api/connexion", {"login": "sec1", "mdp": MDP})
        self.assertEqual(st, 401)                                       # un poste autre que Professeur n'entre pas ici
        st, _, _ = self.appel("POST", "/api/connexion", {"login": "admin1", "mdp": MDP})
        self.assertEqual(st, 401)

    def test_sans_jeton_rien_ne_passe(self):
        for chemin in ("/api/classes", "/api/fiche?cc=1&per=1", "/api/bulletins/autorisations?annee=2026-2027&classe=1"):
            self.assertEqual(self.appel("GET", chemin)[0], 401)
        self.assertEqual(self.appel("GET", "/api/classes", jeton="faux")[0], 401)
        self.assertEqual(self.appel("POST", "/api/points", {"cc": 1, "per": 1, "valeurs": {}})[0], 401)

    def test_mot_de_passe_provisoire_a_changer_d_abord(self):
        st, j = self.connexion(self.p1)
        st, r, _ = self.appel("GET", "/api/classes", jeton=j["jeton"])
        self.assertEqual(st, 403)
        st, r, _ = self.appel("POST", "/api/mdp", {"ancien": self.p1["mdp_temporaire"], "nouveau": "faible", "confirmation": "faible"}, j["jeton"])
        self.assertEqual(st, 400)
        jeton = self.pret(self.p2)
        self.assertEqual(self.appel("GET", "/api/classes", jeton=jeton)[0], 200)

    def test_parcours_complet_du_professeur(self):
        jeton = self.pret(self.p1)
        st, r, _ = self.appel("GET", "/api/classes", jeton=jeton)
        self.assertEqual({k["designation"] for k in r["classes"]}, {"7ème A", "8ème A"})
        self.assertEqual([t["sigle"] for t in r["legende"]["types"]], ["P", "EX"])
        sem = r["semestres"][0]
        st, r, _ = self.appel("POST", "/api/points", {"cc": self.maths7, "per": self.per1, "valeurs": {"0000/26": "8,5", "0001/26": None}}, jeton)
        self.assertEqual((st, r["enregistres"]), (200, 1))
        st, r, _ = self.appel("POST", "/api/points", {"cc": self.maths7, "per": self.per1, "valeurs": {"0000/26": "25"}}, jeton)
        self.assertEqual(st, 400)                                                    # plus que le maximum (20)
        st, r, _ = self.appel("POST", "/api/points", {"cc": self.maths7, "per": sem["examen"]["id"], "valeurs": {"0000/26": "30"}}, jeton)
        self.assertEqual((st, r["enregistres"]), (200, 1))
        for plus_propose in ("maximum", "evaluation/supprimer"):                     # le professeur ne saisit que les points et la conduite
            self.assertEqual(self.appel("POST", "/api/" + plus_propose, {"cc": self.maths7, "per": self.per1, "maximum": "30", "id": 1}, jeton)[0], 400)
        st, _, _ = self.appel("POST", "/api/conduite", {"cc": self.maths7, "per": self.per1, "matricule": "0000/26", "cote": "TB"}, jeton)
        self.assertEqual(st, 200)
        st, f, _ = self.appel("GET", f"/api/fiche?cc={self.maths7}&per={self.per1}", jeton=jeton)
        kas = next(x for x in f["eleves"] if x["matricule"] == "0000/26")
        self.assertEqual((kas["points"][f"P{self.per1}"], kas["conduite"]), (8.5, "TB"))
        self.assertEqual([c["code"] for c in f["evaluations"]], ["P"])               # une seule colonne : la période autorisée
        for interdit in ("total", "sur", "pourcentage"):                             # ni total, ni pourcentage, ni autres périodes
            self.assertNotIn(interdit, kas)
        self.assertEqual(list(kas["points"]), [f"P{self.per1}"])
        self.assertEqual(self.appel("GET", f"/api/releve?cc={self.maths7}", jeton=jeton)[0], 400)    # plus de relevé de l'année
        for ancien in ("evaluation", "evaluation/modifier"):                          # plus de création libre d'évaluations
            self.assertEqual(self.appel("POST", "/api/" + ancien, {"cc": self.maths7, "per": self.per1, "type": "INT"}, jeton)[0], 400)

    def test_saisie_refusee_tant_que_le_titulaire_n_a_pas_ouvert_la_periode(self):
        self.fermer_tout()
        jeton = self.pret(self.p1)
        st, r, _ = self.appel("POST", "/api/points", {"cc": self.maths7, "per": self.per1, "valeurs": {"0000/26": "8"}}, jeton)
        self.assertEqual(st, 400)
        self.assertIn("titulaire", r["erreur"])
        st, f, _ = self.appel("GET", f"/api/fiche?cc={self.maths7}&per={self.per1}", jeton=jeton)
        self.assertEqual(st, 400)
        st, _, _ = self.appel("POST", "/api/conduite", {"cc": self.maths7, "per": self.per1, "matricule": "0000/26", "cote": "TB"}, jeton)
        self.assertEqual(st, 400)
        st, r, _ = self.appel("GET", "/api/classes", jeton=jeton)
        self.assertTrue(all(k["autorisees"] == [] for k in r["classes"]))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM NOTE").fetchone()[0], 0)

    def test_le_titulaire_ouvre_et_ferme_la_saisie_a_ses_collegues(self):
        import bulletins
        self.fermer_tout()
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c7, self.m1)         # p1 est titulaire du 7ème A
        j1, j2 = self.pret(self.p1), self.pret(self.p2)
        q = f"annee={self.annee}&classe={self.c7}"
        st, r, _ = self.appel("GET", "/api/bulletins/autorisations?" + q, jeton=j1)
        self.assertEqual(st, 200)
        self.assertEqual([x["cle"] for x in r["elements"]][:3], [f"P{self.per1}", f"P{self.per2}", f"X{self.sem1}"])
        self.assertFalse(any(x["autorisee"] for x in r["elements"]))
        self.assertEqual(self.appel("GET", "/api/bulletins/autorisations?" + q, jeton=j2)[0], 403)   # un collègue non titulaire : refusé
        corps = {"annee": self.annee, "classe": self.c7, "cle": f"P{self.per1}", "autorisee": True}
        self.assertEqual(self.appel("POST", "/api/bulletins/autoriser", corps, j2)[0], 403)
        self.assertEqual(self.appel("POST", "/api/bulletins/autoriser", corps, j1)[0], 200)
        # le collègue (Français) peut maintenant saisir la période 1 de la 7ème A, mais pas la période 2
        pts = lambda per: self.appel("POST", "/api/points", {"cc": self.fr7, "per": per, "valeurs": {"0000/26": "12"}}, j2)
        self.assertEqual(pts(self.per1)[0], 200)
        self.assertEqual(pts(self.per2)[0], 400)
        # le titulaire ferme : la saisie s'arrête, les points déjà saisis restent
        corps["autorisee"] = False
        self.assertEqual(self.appel("POST", "/api/bulletins/autoriser", corps, j1)[0], 200)
        self.assertEqual(pts(self.per1)[0], 400)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM NOTE").fetchone()[0], 1)
        self.assertEqual(self.appel("POST", "/api/bulletins/autoriser", {**corps, "cle": "S1"}, j1)[0], 400)   # ni semestre, ni année
        self.assertEqual(self.appel("POST", "/api/bulletins/autoriser", {**corps, "classe": self.c8, "autorisee": True}, j1)[0], 403)  # pas sa classe
        self.assertIn("SAISIE_FERMEE", self.actions())

    def test_le_cours_d_un_collegue_est_interdit_et_l_identite_ne_vient_pas_du_navigateur(self):
        jeton = self.pret(self.p1)
        self.assertEqual(self.appel("GET", f"/api/fiche?cc={self.fr7}&per={self.per1}", jeton=jeton)[0], 403)
        st, r, _ = self.appel("POST", "/api/points", {"cc": self.fr7, "per": self.per1, "valeurs": {"0000/26": "5"}, "matricule": self.m2,
                                                      "login": self.p2["login"]}, jeton)
        self.assertEqual(st, 403)
        for mauvais in ("abc", "1; DROP TABLE NOTE", "None", "-5"):
            st, _, _ = self.appel("GET", "/api/fiche?" + urlencode({"cc": mauvais, "per": self.per1}), jeton=jeton)
            self.assertIn(st, (400, 403))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM NOTE").fetchone()[0], 0)

    def test_pas_d_impression_pour_le_professeur(self):
        jeton = self.pret(self.p1)
        self.assertIn(self.appel("POST", "/api/lien-pdf", {"cc": self.maths7, "per": self.per1}, jeton)[0], (400, 404))
        self.assertEqual(self.appel("GET", "/pdf/abc", brut=True)[0], 404)

    def test_deconnexion_ferme_la_session(self):
        jeton = self.pret(self.p1)
        self.assertEqual(self.appel("POST", "/api/deconnexion", {}, jeton)[0], 200)
        self.assertEqual(self.appel("GET", "/api/classes", jeton=jeton)[0], 401)

    def test_session_expiree(self):
        jeton = self.pret(self.p1)
        from datetime import timedelta
        self.srv.etat.sessions[jeton].derniere_activite -= timedelta(minutes=31)
        self.assertEqual(self.appel("GET", "/api/classes", jeton=jeton)[0], 401)

    def test_trop_d_echecs_depuis_une_adresse(self):
        for _ in range(serveur_notes.ECHECS_MAX_PAR_ADRESSE):
            self.srv.etat.noter_echec("127.0.0.1")
        self.assertEqual(self.connexion(self.p1)[0], 429)

    def test_requete_trop_grande(self):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=10)
        c.request("POST", "/api/connexion", "x" * 10, {"Content-Length": str(serveur_notes.TAILLE_MAX + 1)})
        self.assertEqual(c.getresponse().status, 400)


if __name__ == "__main__":
    unittest.main()

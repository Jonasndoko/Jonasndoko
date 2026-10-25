"""Tests de l'application web (app_web.py) : installation protégée, connexion, cookies, menu selon les droits, espace professeurs.
Lancer :  python -m unittest test_web"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"
os.environ["GESTISC_CODE_INSTALL"] = "code-secret-install"

import app_web          # noqa: E402
import security         # noqa: E402
from test_notes import Base, MDP  # noqa: E402


class TestWeb(Base):
    def setUp(self):
        super().setUp()
        chemin = self.conn.execute("PRAGMA database_list").fetchone()[2]
        self.app = app_web.creer_app(chemin)
        self.cl = self.app.test_client()

    def entrer(self, login="admin1", mdp=MDP, client=None):
        return (client or self.cl).post("/connexion", data={"login": login, "mdp": mdp})

    def test_non_connecte_renvoye_a_la_connexion(self):
        r = self.cl.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/connexion", r.headers["Location"])
        self.assertEqual(self.cl.get("/m/paiement").status_code, 302)

    def test_connexion_admin_menu_et_cookie_protege(self):
        r = self.entrer()
        self.assertEqual(r.status_code, 302)
        cookie = r.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        page = self.cl.get("/menu").get_data(as_text=True)
        self.assertIn("Alice", page)
        self.assertIn("Gestionnaire d", page)                         # l'Administrateur voit tous les modules
        self.assertEqual(self.cl.get("/m/acces", follow_redirects=True).status_code, 200)   # module en ligne depuis la v0.49

    def test_mauvais_mot_de_passe(self):
        r = self.entrer(mdp="Faux-mdp#2026-x")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Set-Cookie", r.headers)
        self.assertEqual(self.cl.get("/").status_code, 302)

    def test_module_non_autorise_refuse(self):
        security.creer_utilisateur(self.conn, "perc1", "Paul", "PERCEPTEUR", MDP)
        c2 = self.app.test_client()
        self.entrer("perc1", client=c2)
        self.assertEqual(c2.get("/m/acces").status_code, 403)         # réservé à l'Administrateur
        self.assertEqual(c2.get("/m/travaux").status_code, 403)

    def test_professeur_refuse_sur_la_connexion_du_personnel(self):
        # changer d'abord le mot de passe provisoire n'est pas nécessaire : l'entrée est refusée avant tout cookie
        r = self.entrer(self.p1["login"], self.p1["mdp_temporaire"])
        self.assertNotIn("Set-Cookie", r.headers)
        self.assertIn("espace professeurs", r.get_data(as_text=True))

    def test_deconnexion_ferme_la_session(self):
        self.entrer()
        self.assertEqual(self.cl.get("/menu").status_code, 200)
        self.assertEqual(self.cl.post("/deconnexion").status_code, 302)
        self.assertEqual(self.cl.get("/").status_code, 302)

    def test_origine_etrangere_refusee(self):
        r = self.cl.post("/connexion", data={"login": "admin1", "mdp": MDP}, headers={"Origin": "https://pirate.example"})
        self.assertEqual(r.status_code, 403)

    def test_session_coupee_si_compte_desactive(self):
        self.entrer()
        self.assertEqual(self.cl.get("/menu").status_code, 200)
        with self.conn:
            self.conn.execute("UPDATE UTILISATEUR SET ACTIF = 0 WHERE LOGIN = 'admin1'")
        self.assertEqual(self.cl.get("/").status_code, 302)

    def test_entetes_de_securite(self):
        r = self.cl.get("/connexion")
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])

    # ------------------------------------------------------------------ espace professeurs
    def test_api_professeur_de_bout_en_bout(self):
        self.assertIn("Saisie des points", self.cl.get("/professeur").get_data(as_text=True))
        self.assertEqual(self.cl.get("/api/classes").status_code, 401)
        r = self.cl.post("/api/connexion", json={"login": self.p1["login"], "mdp": self.p1["mdp_temporaire"]})
        self.assertEqual(r.status_code, 200)
        jeton = r.get_json()["jeton"]
        self.assertTrue(r.get_json()["doit_changer_mdp"])
        h = {"Authorization": "Bearer " + jeton}
        self.assertEqual(self.cl.get("/api/classes", headers=h).status_code, 403)       # mot de passe provisoire à changer d'abord
        nouveau = "Nouveau-Mdp#2026-ok"
        r = self.cl.post("/api/mdp", json={"ancien": self.p1["mdp_temporaire"], "nouveau": nouveau, "confirmation": nouveau}, headers=h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        r = self.cl.get("/api/classes", headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json())
        self.assertEqual(self.cl.post("/api/deconnexion", headers=h).status_code, 200)
        self.assertEqual(self.cl.get("/api/classes", headers=h).status_code, 401)

    def test_api_refuse_les_autres_postes(self):
        r = self.cl.post("/api/connexion", json={"login": "admin1", "mdp": MDP})
        self.assertEqual(r.status_code, 401)

    def test_jeton_du_personnel_inutilisable_sur_l_api_professeur(self):
        self.entrer()
        jeton = self.cl.get_cookie("gestisc_session").value
        self.assertEqual(self.cl.get("/api/classes", headers={"Authorization": "Bearer " + jeton}).status_code, 401)


class TestInstallation(unittest.TestCase):
    def setUp(self):
        import database
        self.chemin = os.path.join(tempfile.mkdtemp(), "v.db")
        database.connecter(self.chemin).close()
        self.cl = app_web.creer_app(self.chemin).test_client()

    def test_installation_exige_le_code_puis_disparait(self):
        self.assertIn("/installation", self.cl.get("/connexion").headers["Location"])
        d = {"nom": "Directeur", "login": "chef1", "mdp": "Un-Bon-Mdp#2026-z", "confirmation": "Un-Bon-Mdp#2026-z", "code": "mauvais"}
        r = self.cl.post("/installation", data=d)
        self.assertEqual(r.status_code, 200)
        self.assertIn("incorrect", r.get_data(as_text=True))
        d["code"] = "code-secret-install"
        self.assertEqual(self.cl.post("/installation", data=d).status_code, 302)
        self.assertEqual(self.cl.get("/installation").status_code, 404)
        self.assertEqual(self.cl.post("/connexion", data={"login": "chef1", "mdp": d["mdp"]}).status_code, 302)


if __name__ == "__main__":
    unittest.main()

"""Tests du Gestionnaire d'accès en ligne (web_acces.py) : réservé à l'Administrateur, utilisateurs (création, modification,
activation, mot de passe provisoire, déblocage), rôles (création, suppression, droits de base), autorisations (droits et sections),
garde-fous (dernier administrateur, propre compte), protection contre les envois venus d'un autre site, journal.
Lancer :  python -m unittest test_acces_web"""
import html
import os
import re
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web         # noqa: E402
import database        # noqa: E402
import droits          # noqa: E402
import demo            # noqa: E402
import sections        # noqa: E402
import security        # noqa: E402

MDP = "Tr@vail-Amour-2026"
ETRANGER = {"Origin": "https://autre-site.example"}


class Base(unittest.TestCase):
    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "t.db")
        self.conn = database.connecter(self.chemin)
        demo.semer(self.conn)
        security.creer_utilisateur(self.conn, "admin1", "Alice Directrice", "ADMINISTRATEUR", MDP)
        security.creer_utilisateur(self.conn, "admin2", "Bob Directeur", "ADMINISTRATEUR", MDP)
        self.id_sec = security.creer_utilisateur(self.conn, "sec1", "Sophie Secrétaire", "SECRETAIRE", MDP)
        self.comptes_au_depart = self.journal("COMPTE_CREE")
        self.app = app_web.creer_app(self.chemin)
        self.admin, self.sec = self.app.test_client(), self.app.test_client()
        for c, l in ((self.admin, "admin1"), (self.sec, "sec1")):
            self.assertEqual(c.post("/connexion", data={"login": l, "mdp": MDP}).status_code, 302)

    def texte(self, r):
        return html.unescape(r.get_data(as_text=True))

    def journal(self, action):
        return self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE ACTION = ?", (action,)).fetchone()[0]

    def id_de(self, login):
        return self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = ?", (login,)).fetchone()[0]

    def secret(self, r):
        return re.search(r'id="secret">([^<]+)<', self.texte(r)).group(1).strip()


class TestAcces(Base):
    URLS = ("/m/acces", "/m/acces/utilisateurs", "/m/acces/utilisateurs?modifier=1", "/m/acces/roles", "/m/acces/autorisations")
    POSTS = ("/m/acces/utilisateurs/nouveau", "/m/acces/utilisateurs/modifier", "/m/acces/utilisateurs/etat", "/m/acces/utilisateurs/mdp",
             "/m/acces/utilisateurs/debloquer", "/m/acces/roles/nouveau", "/m/acces/roles/supprimer", "/m/acces/roles/droits",
             "/m/acces/autorisations/enregistrer", "/m/acces/autorisations/defaut")

    def test_non_connecte(self):
        c = self.app.test_client()
        for url in self.URLS:
            self.assertEqual(c.get(url).status_code, 302, url)
        for url in self.POSTS:
            self.assertEqual(c.post(url, data={}).status_code, 302, url)

    def test_reserve_a_l_administrateur(self):
        for url in self.URLS:
            self.assertEqual(self.sec.get(url).status_code, 403, url)
        for url in self.POSTS:
            self.assertEqual(self.sec.post(url, data={"id": "1", "r": "SECRETAIRE"}).status_code, 403, url)

    def test_un_compte_a_droits_etendus_n_est_pas_administrateur(self):
        self.admin.post("/m/acces/autorisations/enregistrer", data={"id": self.id_sec, "s": ["PRIMAIRE", "SECONDAIRE"], "d": ["paiement:AJOUT"]})
        self.assertEqual(self.sec.get("/m/acces/utilisateurs").status_code, 403)

    def test_menu_marque_le_module_en_ligne(self):
        page = self.texte(self.admin.get("/menu"))
        self.assertIn("/m/acces", page)
        self.assertNotIn("en cours de migration", self.texte(self.admin.get("/m/acces", follow_redirects=True)))

    def test_origine_etrangere_refusee(self):
        for url in self.POSTS:
            self.assertEqual(self.admin.post(url, data={"id": "1"}, headers=ETRANGER).status_code, 403, url)
        self.assertEqual(self.journal("COMPTE_CREE"), self.comptes_au_depart)

    def test_pages_s_affichent(self):
        self.assertIn("Alice Directrice", self.texte(self.admin.get("/m/acces/utilisateurs")))
        self.assertIn("Directeur de discipline", self.texte(self.admin.get("/m/acces/roles")))
        self.assertEqual(self.admin.get("/m/acces/utilisateurs?modifier=99999").status_code, 404)
        self.assertEqual(self.admin.get("/m/acces/utilisateurs?modifier=abc").status_code, 400)
        self.assertEqual(self.admin.get("/m/acces/roles?r=INCONNU").status_code, 404)
        self.assertEqual(self.admin.get("/m/acces/autorisations?id=99999").status_code, 404)


class TestUtilisateurs(Base):
    def test_creation_et_premiere_connexion(self):
        r = self.admin.post("/m/acces/utilisateurs/nouveau", data={"login": "Perc2", "nom": "Paul Percepteur", "poste": "PERCEPTEUR"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("no-store", r.headers["Cache-Control"])
        provisoire = self.secret(r)
        self.assertEqual(self.journal("COMPTE_CREE"), self.comptes_au_depart + 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE DETAIL LIKE ?", ("%" + provisoire + "%",)).fetchone()[0], 0)
        self.assertNotIn(provisoire, self.texte(self.admin.get("/m/acces/utilisateurs")))        # ne se réaffiche jamais
        u = self.conn.execute("SELECT ROLE, DOIT_CHANGER_MDP FROM UTILISATEUR WHERE LOGIN = 'perc2'").fetchone()
        self.assertEqual((u["ROLE"], u["DOIT_CHANGER_MDP"]), ("PERCEPTEUR", 1))
        self.assertTrue(droits.a_droit(self.conn, security.Session(self.id_de("perc2"), "perc2", "x", "PERCEPTEUR", False), "paiement", "AJOUT"))
        c = self.app.test_client()
        self.assertEqual(c.post("/connexion", data={"login": "perc2", "mdp": provisoire}).status_code, 302)
        self.assertIn("/mot-de-passe", c.get("/").headers["Location"])

    def test_creation_refusee_garde_la_saisie(self):
        r = self.admin.post("/m/acces/utilisateurs/nouveau", data={"login": "sec1", "nom": "Doublon Test", "poste": "SECRETAIRE"})
        self.assertEqual(r.status_code, 400)
        page = self.texte(r)
        self.assertIn("existe déjà", page)
        self.assertIn('value="Doublon Test"', page)
        r = self.admin.post("/m/acces/utilisateurs/nouveau", data={"login": "x y", "nom": "Quelqu Un", "poste": "SECRETAIRE"})
        self.assertEqual(r.status_code, 400)
        r = self.admin.post("/m/acces/utilisateurs/nouveau", data={"login": "nouveau1", "nom": "Quelqu Un", "poste": "POSTE_BIDON"})
        self.assertEqual(r.status_code, 400)

    def test_modification_et_changement_de_poste(self):
        self.admin.post("/m/acces/autorisations/enregistrer", data={"id": self.id_sec, "s": ["PRIMAIRE", "SECONDAIRE"], "d": ["encaissement:LECTURE"]})
        r = self.admin.post("/m/acces/utilisateurs/modifier", data={"id": self.id_sec, "nom": "Sophie Nouvelle", "poste": "INTENDANT", "actif": "1"})
        self.assertEqual(r.status_code, 302)
        u = self.conn.execute("SELECT NOM_COMPLET, ROLE FROM UTILISATEUR WHERE ID_USER = ?", (self.id_sec,)).fetchone()
        self.assertEqual((u["NOM_COMPLET"], u["ROLE"]), ("Sophie Nouvelle", "INTENDANT"))
        self.assertEqual(droits.droits_utilisateur(self.conn, self.id_sec), droits.droits_par_defaut(self.conn, "INTENDANT"))
        self.assertEqual(self.journal("COMPTE_MODIFIE"), 1)
        r = self.admin.post("/m/acces/utilisateurs/modifier", data={"id": self.id_sec, "nom": "ab", "poste": "INTENDANT", "actif": "1"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.admin.post("/m/acces/utilisateurs/modifier", data={"id": "99999", "nom": "Nom Valide", "poste": "INTENDANT"}).status_code, 404)

    def test_garde_fous_propre_compte_et_dernier_admin(self):
        moi = self.id_de("admin1")
        r = self.admin.post("/m/acces/utilisateurs/modifier", data={"id": moi, "nom": "Alice Directrice", "poste": "SECRETAIRE", "actif": "1"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("propre poste", self.texte(r))
        r = self.admin.post("/m/acces/utilisateurs/etat", data={"id": moi, "actif": "0"})
        self.assertEqual(r.status_code, 400)
        # un seul autre administrateur : le désactiver est permis, puis le dernier admin ne peut plus être retiré
        self.assertEqual(self.admin.post("/m/acces/utilisateurs/etat", data={"id": self.id_de("admin2"), "actif": "0"}).status_code, 302)
        self.assertEqual(self.admin.post("/m/acces/utilisateurs/etat", data={"id": self.id_de("admin2"), "actif": "0"}).status_code, 400)  # déjà désactivé

    def test_dernier_administrateur_protege(self):
        self.conn.execute("UPDATE UTILISATEUR SET ACTIF = 0 WHERE LOGIN = 'admin2'")
        self.conn.commit()
        self.conn.execute("UPDATE UTILISATEUR SET ROLE = 'ADMINISTRATEUR' WHERE LOGIN = 'sec1'")
        self.conn.commit()
        self.assertEqual(self.admin.post("/m/acces/utilisateurs/modifier", data={"id": self.id_de("admin2"), "nom": "Bob Directeur", "poste": "ADMINISTRATEUR", "actif": "1"}).status_code, 302)

    def test_desactivation_et_reactivation(self):
        r = self.admin.post("/m/acces/utilisateurs/etat", data={"id": self.id_sec, "actif": "0"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.app.test_client().post("/connexion", data={"login": "sec1", "mdp": MDP}).status_code, 200)
        self.assertEqual(self.sec.get("/").status_code, 302)                                      # la session ouverte tombe aussi
        self.assertEqual(self.admin.post("/m/acces/utilisateurs/etat", data={"id": self.id_sec, "actif": "1"}).status_code, 302)
        self.assertEqual(self.app.test_client().post("/connexion", data={"login": "sec1", "mdp": MDP}).status_code, 302)
        self.assertEqual((self.journal("COMPTE_DESACTIVE"), self.journal("COMPTE_ACTIVE")), (1, 1))

    def test_mot_de_passe_provisoire(self):
        r = self.admin.post("/m/acces/utilisateurs/mdp", data={"id": self.id_sec})
        self.assertEqual(r.status_code, 200)
        provisoire = self.secret(r)
        self.assertEqual(self.journal("MDP_REINITIALISE"), 1)
        c = self.app.test_client()
        self.assertEqual(c.post("/connexion", data={"login": "sec1", "mdp": MDP}).status_code, 200)
        self.assertEqual(c.post("/connexion", data={"login": "sec1", "mdp": provisoire}).status_code, 302)
        self.assertNotIn(provisoire, self.texte(self.admin.get("/m/acces/utilisateurs")))
        self.assertEqual(self.admin.post("/m/acces/utilisateurs/mdp", data={"id": "99999"}).status_code, 400)
        self.assertEqual(self.admin.post("/m/acces/utilisateurs/mdp", data={"id": "abc"}).status_code, 400)

    def test_deblocage(self):
        c = self.app.test_client()
        for _ in range(6):
            c.post("/connexion", data={"login": "sec1", "mdp": "mauvais-mot-de-passe"})
        self.assertIn("Bloqué", self.texte(self.admin.get("/m/acces/utilisateurs")))
        self.assertEqual(self.admin.post("/m/acces/utilisateurs/debloquer", data={"id": self.id_sec}).status_code, 302)
        self.assertNotIn("Bloqué (trop", self.texte(self.admin.get("/m/acces/utilisateurs")))
        self.assertEqual(self.journal("COMPTE_DEBLOQUE"), 1)


class TestRoles(Base):
    def test_creation_droits_et_suppression(self):
        r = self.admin.post("/m/acces/roles/nouveau", data={"libelle": "Chef de discipline"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("r=CHEF_DE_DISCIPLINE", r.headers["Location"])
        self.assertIn("Chef de discipline", self.texte(self.admin.get("/m/acces/roles?r=CHEF_DE_DISCIPLINE")))
        r = self.admin.post("/m/acces/roles/droits", data={"r": "CHEF_DE_DISCIPLINE", "d": ["presence_eleves:LECTURE", "personnel:AJOUT"]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(droits.droits_par_defaut(self.conn, "CHEF_DE_DISCIPLINE"),
                         {("presence_eleves", "LECTURE"), ("personnel", "AJOUT"), ("personnel", "LECTURE")})     # Lecture ajoutée d'office
        # un compte créé avec ce rôle reçoit ces droits
        self.admin.post("/m/acces/utilisateurs/nouveau", data={"login": "chef1", "nom": "Chef Un", "poste": "CHEF_DE_DISCIPLINE"})
        self.assertIn(("personnel", "AJOUT"), droits.droits_utilisateur(self.conn, self.id_de("chef1")))
        r = self.admin.post("/m/acces/roles/supprimer", data={"r": "CHEF_DE_DISCIPLINE"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("donné à 1 compte", self.texte(r))
        self.admin.post("/m/acces/utilisateurs/modifier", data={"id": self.id_de("chef1"), "nom": "Chef Un", "poste": "SECRETAIRE", "actif": "1"})
        self.assertEqual(self.admin.post("/m/acces/roles/supprimer", data={"r": "CHEF_DE_DISCIPLINE"}).status_code, 302)
        self.assertFalse(droits.role_existe(self.conn, "CHEF_DE_DISCIPLINE"))
        self.assertEqual((self.journal("ROLE_CREE"), self.journal("DROITS_ROLE_MODIFIES"), self.journal("ROLE_SUPPRIME")), (1, 1, 1))

    def test_refus(self):
        self.assertEqual(self.admin.post("/m/acces/roles/nouveau", data={"libelle": "Secrétaire"}).status_code, 400)       # existe déjà
        self.assertEqual(self.admin.post("/m/acces/roles/nouveau", data={"libelle": "ab"}).status_code, 400)
        r = self.admin.post("/m/acces/roles/supprimer", data={"r": "SECRETAIRE"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("ne peuvent pas être supprimés", self.texte(r))
        self.assertEqual(self.admin.post("/m/acces/roles/droits", data={"r": "INCONNU"}).status_code, 404)

    def test_droits_invalides_refuses(self):
        for valeur in ("module_bidon:LECTURE", "paiement:SUPPRESSION", "sans-deux-points"):
            r = self.admin.post("/m/acces/roles/droits", data={"r": "SECRETAIRE", "d": valeur})
            self.assertIn(r.status_code, (400,), valeur)
        self.assertEqual(self.journal("DROITS_ROLE_MODIFIES"), 0)

    def test_application_aux_comptes_existants(self):
        avant = droits.droits_utilisateur(self.conn, self.id_sec)
        self.admin.post("/m/acces/roles/droits", data={"r": "SECRETAIRE", "d": ["paiement:LECTURE"]})
        self.assertEqual(droits.droits_utilisateur(self.conn, self.id_sec), avant)                 # sans la case : comptes inchangés
        r = self.admin.post("/m/acces/roles/droits", data={"r": "SECRETAIRE", "d": ["paiement:LECTURE"], "appliquer": "1"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(droits.droits_utilisateur(self.conn, self.id_sec), {("paiement", "LECTURE")})


class TestAutorisations(Base):
    def test_enregistrement_droits_et_sections_effet_immediat(self):
        self.assertIn("Sophie Secrétaire", self.texte(self.admin.get(f"/m/acces/autorisations?id={self.id_sec}")))
        r = self.admin.post("/m/acces/autorisations/enregistrer",
                            data={"id": self.id_sec, "d": ["controle:LECTURE", "personnel:AJOUT"], "s": ["SECONDAIRE"]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(droits.droits_utilisateur(self.conn, self.id_sec),
                         {("controle", "LECTURE"), ("personnel", "AJOUT"), ("personnel", "LECTURE")})
        self.assertEqual(sections.sections_explicites(self.conn, self.id_sec), frozenset({"SECONDAIRE"}))
        self.assertEqual((self.journal("DROITS_MODIFIES"), self.journal("SECTIONS_UTILISATEUR_MODIFIEES")), (1, 1))
        menu = self.texte(self.sec.get("/"))                                  # effet immédiat sur la session déjà ouverte
        self.assertIn("/m/controle", menu)
        self.assertIn("/m/personnel", menu)
        self.assertNotIn("/m/paiement", menu)
        page = self.texte(self.admin.get(f"/m/acces/autorisations?id={self.id_sec}"))
        self.assertRegex(page, r'value="controle:LECTURE" checked')
        self.assertRegex(page, r'value="SECONDAIRE" checked')
        self.assertNotRegex(page, r'value="PRIMAIRE" checked')

    def test_cases_sans_objet_ne_sont_pas_acceptees(self):
        for valeur in ("tableau:AJOUT", "travaux:LECTURE", "paiement:MODIFICATION"):
            r = self.admin.post("/m/acces/autorisations/enregistrer", data={"id": self.id_sec, "d": valeur, "s": ["PRIMAIRE"]})
            self.assertEqual(r.status_code, 400, valeur)

    def test_rien_n_est_ecrit_si_une_partie_est_invalide(self):
        avant = (droits.droits_utilisateur(self.conn, self.id_sec), sections.sections_explicites(self.conn, self.id_sec))
        # sections vides
        self.assertEqual(self.admin.post("/m/acces/autorisations/enregistrer", data={"id": self.id_sec, "d": ["controle:LECTURE"]}).status_code, 400)
        # droit invalide avec sections valides
        self.assertEqual(self.admin.post("/m/acces/autorisations/enregistrer", data={"id": self.id_sec, "d": ["x:LECTURE"], "s": ["PRIMAIRE"]}).status_code, 400)
        self.assertEqual(avant, (droits.droits_utilisateur(self.conn, self.id_sec), sections.sections_explicites(self.conn, self.id_sec)))
        self.assertEqual(self.journal("DROITS_MODIFIES") + self.journal("SECTIONS_UTILISATEUR_MODIFIEES"), 0)

    def test_page_d_erreur_garde_les_cases(self):
        r = self.admin.post("/m/acces/autorisations/enregistrer", data={"id": self.id_sec, "d": ["controle:LECTURE"]})
        page = self.texte(r)
        self.assertIn("Cochez au moins une section", page)
        self.assertRegex(page, r'value="controle:LECTURE" checked')

    def test_compte_inconnu(self):
        self.assertEqual(self.admin.post("/m/acces/autorisations/enregistrer", data={"id": "99999", "d": [], "s": ["PRIMAIRE"]}).status_code, 404)
        self.assertEqual(self.admin.post("/m/acces/autorisations/defaut", data={"id": "99999"}).status_code, 404)
        self.assertEqual(self.admin.post("/m/acces/autorisations/enregistrer", data={"id": "abc"}).status_code, 400)

    def test_retablir_les_droits_du_role(self):
        self.admin.post("/m/acces/autorisations/enregistrer", data={"id": self.id_sec, "d": ["controle:LECTURE"], "s": ["PRIMAIRE", "SECONDAIRE"]})
        r = self.admin.post("/m/acces/autorisations/defaut", data={"id": self.id_sec})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(droits.droits_utilisateur(self.conn, self.id_sec), droits.droits_par_defaut(self.conn, "SECRETAIRE"))


if __name__ == "__main__":
    unittest.main()

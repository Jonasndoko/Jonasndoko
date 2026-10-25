"""Tests du module Travaux techniques en ligne (web_travaux.py) : réservé à l'Administrateur, mise à jour des tables (ajout, modification,
désactivation, suppression avec données liées, annulation d'un reçu), structure de la base, authentification (code de récupération,
mot de passe provisoire, déblocage, page « Mot de passe oublié »), sauvegarde et téléchargement, protection contre les envois venus
d'un autre site, journal.
Lancer :  python -m unittest test_travaux_web"""
import html
import io
import json
import os
import re
import shutil
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web         # noqa: E402
import config          # noqa: E402
import database        # noqa: E402
import miseajour       # noqa: E402
import demo            # noqa: E402
import security        # noqa: E402

MDP = "Tr@vail-Amour-2026"
NOUVEAU = "N0uveau-Mot-2026!"
ETRANGER = {"Origin": "https://autre-site.example"}
AN = demo.ANNEE_COURANTE


def cle(*valeurs) -> str:
    return json.dumps(list(valeurs))


class Base(unittest.TestCase):
    def setUp(self):
        for ancien in config.DOSSIER_SAUVEGARDES.glob("*"):          # le dossier des sauvegardes est commun à tous les tests
            ancien.unlink()
        self.chemin = os.path.join(tempfile.mkdtemp(), "t.db")
        self.conn = database.connecter(self.chemin)
        self.login_perc, self.mdp_perc = demo.semer(self.conn)
        security.creer_utilisateur(self.conn, "admin1", "Alice Directrice", "ADMINISTRATEUR", MDP)
        security.creer_utilisateur(self.conn, "admin2", "Bob Directeur", "ADMINISTRATEUR", MDP)
        self.id_sec = security.creer_utilisateur(self.conn, "sec1", "Sophie Secrétaire", "SECRETAIRE", MDP)
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


class TestAcces(Base):
    URLS = ("/m/travaux", "/m/travaux/tables", "/m/travaux/tables?t=eleves", "/m/travaux/tables/nouveau?t=niveaux",
            "/m/travaux/structure", "/m/travaux/auth", "/m/travaux/sauvegarde", "/m/travaux/sauvegarde/telecharger?f=x.csfbak",
            "/m/travaux/restauration", "/m/travaux/restauration/examiner?f=x.csfbak", "/m/travaux/miseajour")
    POSTS = ("/m/travaux/tables/nouveau", "/m/travaux/tables/modifier", "/m/travaux/tables/supprimer", "/m/travaux/tables/etat",
             "/m/travaux/tables/annuler-recu", "/m/travaux/structure/maj", "/m/travaux/structure/integrite", "/m/travaux/auth/code",
             "/m/travaux/auth/annuler-code", "/m/travaux/auth/provisoire", "/m/travaux/auth/debloquer", "/m/travaux/sauvegarde/creer",
             "/m/travaux/restauration/importer", "/m/travaux/restauration/restaurer", "/m/travaux/miseajour/controler",
             "/m/travaux/miseajour/installer", "/m/travaux/miseajour/annuler", "/m/travaux/miseajour/revenir")

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
            self.assertEqual(self.sec.post(url, data={"t": "niveaux", "id": "1", "k": cle("X")}).status_code, 403, url)

    def test_menu_marque_le_module_en_ligne(self):
        page = self.texte(self.admin.get("/menu"))
        tuile = re.search(r'<a class="entree" href="/m/travaux"[^>]*>(.*?)</a>', page, re.S).group(1)
        self.assertNotIn("bientôt", tuile)
        self.assertNotIn("migration", tuile)

    def test_origine_etrangere_refusee(self):
        for url in self.POSTS + ("/mot-de-passe-oublie",):
            self.assertEqual(self.admin.post(url, data={"t": "niveaux", "id": "1", "k": cle("X")}, headers=ETRANGER).status_code, 403, url)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CODE_RECUPERATION").fetchone()[0], 0)

    def test_toutes_les_tables_s_affichent_et_ont_un_formulaire(self):
        import referentiels as ref
        for k, t in ref.TABLES.items():
            self.assertEqual(self.admin.get(f"/m/travaux/tables?t={k}").status_code, 200, k)
            if t.peut_creer:
                self.assertEqual(self.admin.get(f"/m/travaux/tables/nouveau?t={k}").status_code, 200, k)
        self.assertEqual(self.admin.get("/m/travaux/tables?t=inconnue").status_code, 404)
        self.assertEqual(self.admin.get("/m/travaux/tables/modifier?t=niveaux&k=pas-du-json").status_code, 400)
        self.assertEqual(self.admin.get("/m/travaux/tables/modifier?t=niveaux&k=" + json.dumps(["A", "B"])).status_code, 400)


class TestTables(Base):
    NIVEAU = {"t": "niveaux", "CODE_NIVEAU": "z9", "DESI_NIVEAU": "Niveau d'essai", "SECTION": "SECONDAIRE"}

    def test_ajout_modification_desactivation_suppression(self):
        r = self.admin.post("/m/travaux/tables/nouveau", data=self.NIVEAU)
        self.assertEqual(r.status_code, 302, self.texte(r)[:500])
        self.assertIn("ok=ajoute", r.headers["Location"])
        self.assertEqual(self.conn.execute("SELECT DESI_NIVEAU FROM NIVEAU WHERE CODE_NIVEAU = 'Z9'").fetchone()[0], "Niveau d'essai")
        self.assertEqual(self.journal("REF_AJOUT"), 1)
        self.assertIn("Niveau d'essai", self.texte(self.admin.get("/m/travaux/tables?t=niveaux&q=essai")))

        k = cle("Z9")
        page = self.texte(self.admin.get(f"/m/travaux/tables/modifier?t=niveaux&k={k}"))
        self.assertIn("Niveau d'essai", page)
        r = self.admin.post("/m/travaux/tables/modifier", data={"t": "niveaux", "k": k, "DESI_NIVEAU": "Autre nom", "SECTION": "SECONDAIRE"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.conn.execute("SELECT DESI_NIVEAU FROM NIVEAU WHERE CODE_NIVEAU = 'Z9'").fetchone()[0], "Autre nom")
        self.assertEqual(self.journal("REF_MODIFICATION"), 1)
        # rien ne change : message dédié
        r = self.admin.post("/m/travaux/tables/modifier", data={"t": "niveaux", "k": k, "DESI_NIVEAU": "Autre nom", "SECTION": "SECONDAIRE"})
        self.assertEqual(self.journal("REF_MODIFICATION"), 1)

        r = self.admin.post("/m/travaux/tables/etat", data={"t": "niveaux", "k": k, "action": "desactiver"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.conn.execute("SELECT ACTIF FROM NIVEAU WHERE CODE_NIVEAU = 'Z9'").fetchone()[0], 0)
        self.admin.post("/m/travaux/tables/etat", data={"t": "niveaux", "k": k, "action": "reactiver"})
        self.assertEqual(self.conn.execute("SELECT ACTIF FROM NIVEAU WHERE CODE_NIVEAU = 'Z9'").fetchone()[0], 1)

        r = self.admin.post("/m/travaux/tables/supprimer", data={"t": "niveaux", "k": k})
        self.assertEqual(r.status_code, 302)
        self.assertIn("ok=supprime", r.headers["Location"])
        self.assertIsNone(self.conn.execute("SELECT 1 FROM NIVEAU WHERE CODE_NIVEAU = 'Z9'").fetchone())
        self.assertEqual(self.journal("REF_SUPPRESSION"), 1)

    def test_erreur_de_saisie_garde_les_valeurs(self):
        self.admin.post("/m/travaux/tables/nouveau", data=self.NIVEAU)
        r = self.admin.post("/m/travaux/tables/nouveau", data=self.NIVEAU)
        self.assertEqual(r.status_code, 400)
        page = self.texte(r)
        self.assertIn("Niveau d'essai", page)                       # la saisie est remise dans le formulaire
        self.assertIn('class="erreur"', page)
        r = self.admin.post("/m/travaux/tables/nouveau", data={"t": "niveaux", "CODE_NIVEAU": "", "DESI_NIVEAU": "x", "SECTION": "SECONDAIRE"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("obligatoire", self.texte(r))

    def test_cle_non_modifiable_et_ligne_disparue(self):
        self.admin.post("/m/travaux/tables/nouveau", data=self.NIVEAU)
        self.admin.post("/m/travaux/tables/modifier", data={"t": "niveaux", "k": cle("Z9"), "CODE_NIVEAU": "AUTRE", "DESI_NIVEAU": "Y", "SECTION": "SECONDAIRE"})
        self.assertIsNone(self.conn.execute("SELECT 1 FROM NIVEAU WHERE CODE_NIVEAU = 'AUTRE'").fetchone())
        self.assertEqual(self.admin.get("/m/travaux/tables/modifier?t=niveaux&k=" + cle("NEXISTEPAS")).status_code, 404)

    def test_table_sans_modification_ni_suppression_refusees(self):
        self.assertEqual(self.admin.get("/m/travaux/tables/nouveau?t=paiements").status_code, 403)
        self.assertEqual(self.admin.get("/m/travaux/tables/modifier?t=possede&k=" + cle("A", "B")).status_code, 403)

    def test_suppression_avec_donnees_liees_demande_confirmation(self):
        self.admin.post("/m/travaux/tables/nouveau", data={"t": "options", "CODE_OPTION": "ZO", "DESI_OPTION": "Option d'essai"})
        self.admin.post("/m/travaux/tables/nouveau", data=self.NIVEAU)
        r = self.admin.post("/m/travaux/tables/nouveau", data={"t": "possede", "CODE_NIVEAU": "Z9", "CODE_OPTION": "ZO"})
        self.assertEqual(r.status_code, 302, self.texte(r)[:600])
        k = cle("Z9")
        r = self.admin.post("/m/travaux/tables/supprimer", data={"t": "niveaux", "k": k})
        self.assertEqual(r.status_code, 200)                         # page d'aperçu, rien n'est supprimé
        page = self.texte(r)
        self.assertIn("Options par niveau", page)
        self.assertIn("Supprimer la donnée et les données liées", page)
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM NIVEAU WHERE CODE_NIVEAU = 'Z9'").fetchone())
        r = self.admin.post("/m/travaux/tables/supprimer", data={"t": "niveaux", "k": k, "avec_liees": "1"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("ok=supprime_liees", r.headers["Location"])
        self.assertIsNone(self.conn.execute("SELECT 1 FROM NIVEAU WHERE CODE_NIVEAU = 'Z9'").fetchone())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM POSSEDE WHERE CODE_NIVEAU = 'Z9'").fetchone()[0], 0)
        self.assertEqual(self.journal("REF_SUPPRESSION_AVEC_LIEES"), 1)

    def test_suppression_impossible_si_un_recu_en_depend(self):
        mat = self.conn.execute("SELECT MATRICULE FROM PAIEMENT WHERE STATUT = 'VALIDE' LIMIT 1").fetchone()
        if not mat:
            self.skipTest("la démonstration ne contient aucun paiement")
        r = self.admin.post("/m/travaux/tables/supprimer", data={"t": "eleves", "k": cle(mat[0])})
        page = self.texte(r)
        self.assertIn("reçu", page)
        self.assertNotIn("Supprimer la donnée et les données liées", page)
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM ELEVE WHERE MATRICULE = ?", (mat[0],)).fetchone())

    def test_formulaires_complexes_eleve_et_tarif(self):
        """Champs date, choix, montant, tranches et cases à cocher multiples : la saisie du navigateur est comprise par referentiels.py."""
        r = self.admin.post("/m/travaux/tables/nouveau", data={
            "t": "eleves", "NOM": "Zztest", "POSTNOM": "mbuyi", "PRENOM": "Marie", "SEXE": "F", "DATE_NAISSANCE": "2012-05-17"})
        self.assertEqual(r.status_code, 302, self.texte(r)[:600])
        ligne = self.conn.execute("SELECT MATRICULE, NOM, DATE_NAISSANCE FROM ELEVE WHERE NOM = 'Zztest'").fetchone()
        self.assertIsNotNone(ligne)                                  # matricule attribué par le système (champ non saisi), il contient « / »
        self.assertEqual(ligne["DATE_NAISSANCE"], "2012-05-17")
        page = self.texte(self.admin.get("/m/travaux/tables/modifier?t=eleves&k=" + cle(ligne["MATRICULE"])))
        self.assertIn('value="2012-05-17"', page)                  # la date enregistrée revient au format d'un champ <input type=date>

        r = self.admin.post("/m/travaux/tables/nouveau", data={"t": "types_frais", "CODTF": "zt", "DESITF": "Frais d'essai"})
        self.assertEqual(r.status_code, 302, self.texte(r)[:600])
        types = "ZT"
        classes = [str(c[0]) for c in self.conn.execute("SELECT N_CLASSE FROM CLASSE ORDER BY N_CLASSE LIMIT 2")]
        devise = self.conn.execute("SELECT CODE_DEVISE FROM DEVISE LIMIT 1").fetchone()[0]
        annee = self.conn.execute("SELECT ANNEESCO FROM ANNEE_SCO WHERE EN_COURS = 1").fetchone()[0]
        donnees = {"t": "tarifs", "CODTF": types, "N_CLASSE": classes, "ANNEESCO": annee, "MONTANT": "150,50", "CODE_DEVISE": devise,
                   "TRANCHES": ""}
        r = self.admin.post("/m/travaux/tables/nouveau", data=donnees)
        self.assertEqual(r.status_code, 302, self.texte(r)[:800])
        n = self.conn.execute("SELECT COUNT(*) FROM TARIF WHERE CODTF = ? AND ANNEESCO = ?", (types, annee)).fetchone()[0]
        self.assertEqual(n, len(classes))                            # une ligne par classe cochée
        r = self.admin.post("/m/travaux/tables/nouveau", data={**donnees, "N_CLASSE": []})
        self.assertEqual(r.status_code, 400)
        self.assertIn("cochez au moins un choix", self.texte(r))

    def test_annulation_d_un_recu(self):
        ligne = self.conn.execute("SELECT N_RECU FROM PAIEMENT WHERE STATUT = 'VALIDE' LIMIT 1").fetchone()
        if not ligne:
            self.skipTest("la démonstration ne contient aucun paiement")
        n = ligne[0]
        k = cle(n)
        self.assertEqual(self.admin.get(f"/m/travaux/tables/annuler-recu?k={k}").status_code, 200)
        r = self.admin.post("/m/travaux/tables/annuler-recu", data={"k": k, "motif": "ok"})
        self.assertEqual(r.status_code, 200)                         # motif trop court : on reste sur la page
        self.assertIn("motif", self.texte(r))
        self.assertEqual(self.conn.execute("SELECT STATUT FROM PAIEMENT WHERE N_RECU = ?", (n,)).fetchone()[0], "VALIDE")
        r = self.admin.post("/m/travaux/tables/annuler-recu", data={"k": k, "motif": "Erreur de saisie du montant"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.conn.execute("SELECT STATUT FROM PAIEMENT WHERE N_RECU = ?", (n,)).fetchone()[0], "ANNULE")
        self.assertEqual(self.journal("PAIEMENT_ANNULE"), 1)
        r = self.admin.post("/m/travaux/tables/annuler-recu", data={"k": k, "motif": "Encore une fois"})
        self.assertIn("déjà annulé", self.texte(r))


class TestStructure(Base):
    def test_analyse_et_integrite(self):
        page = self.texte(self.admin.get("/m/travaux/structure"))
        self.assertIn("tables sont à jour", page)
        self.assertIn("UTILISATEUR", page)
        page = self.texte(self.admin.post("/m/travaux/structure/integrite"))
        self.assertIn("✔", page)

    def test_mise_a_jour_sans_travail(self):
        page = self.texte(self.admin.post("/m/travaux/structure/maj"))
        self.assertIn("Rien à mettre à jour", page)


class TestAuthentification(Base):
    def code_depuis(self, reponse) -> str:
        m = re.search(r'id="secret"[^>]*>([A-Z0-9]{4}-[A-Z0-9]{4})<', self.texte(reponse))
        self.assertIsNotNone(m, self.texte(reponse)[:800])
        return m.group(1)

    def test_page_liste_les_comptes_et_le_journal(self):
        page = self.texte(self.admin.get("/m/travaux/auth"))
        for nom in ("Alice Directrice", "Sophie Secrétaire", "sec1"):
            self.assertIn(nom, page)
        self.assertIn("Connexion réussie", page)

    def test_code_de_recuperation_de_bout_en_bout(self):
        r = self.admin.post("/m/travaux/auth/code", data={"id": self.id_sec})
        self.assertEqual(r.status_code, 200)
        self.assertIn("no-store", r.headers["Cache-Control"])
        code = self.code_depuis(r)
        self.assertEqual(self.journal("CODE_RECUP_GENERE"), 1)
        # le code n'est jamais stocké en clair, ni écrit dans le journal
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CODE_RECUPERATION WHERE CODE_HASH LIKE ?", ("%" + code.replace("-", "") + "%",)).fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE DETAIL LIKE ?", ("%" + code + "%",)).fetchone()[0], 0)
        self.assertNotIn(code, self.texte(self.admin.get("/m/travaux/auth")))      # ne se réaffiche jamais
        self.assertIn("Valable encore", self.texte(self.admin.get("/m/travaux/auth")))

        anonyme = self.app.test_client()
        r = anonyme.post("/mot-de-passe-oublie", data={"login": "sec1", "code": "FAUX-CODE", "nouveau": NOUVEAU, "confirmation": NOUVEAU})
        self.assertIn("invalide ou expiré", self.texte(r))
        r = anonyme.post("/mot-de-passe-oublie", data={"login": "sec1", "code": code.lower(), "nouveau": NOUVEAU, "confirmation": NOUVEAU})
        self.assertIn("Votre mot de passe a été changé", self.texte(r))
        self.assertEqual(anonyme.post("/connexion", data={"login": "sec1", "mdp": NOUVEAU}).status_code, 302)
        r = anonyme.post("/mot-de-passe-oublie", data={"login": "sec1", "code": code, "nouveau": NOUVEAU + "x", "confirmation": NOUVEAU + "x"})
        self.assertIn("invalide ou expiré", self.texte(r))                           # usage unique

    def test_code_annule(self):
        self.admin.post("/m/travaux/auth/code", data={"id": self.id_sec})
        r = self.admin.post("/m/travaux/auth/annuler-code", data={"id": self.id_sec})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CODE_RECUPERATION").fetchone()[0], 0)
        r = self.admin.post("/m/travaux/auth/annuler-code", data={"id": self.id_sec})
        self.assertEqual(r.status_code, 400)

    def test_pas_de_code_pour_soi_meme_ni_compte_inconnu(self):
        r = self.admin.post("/m/travaux/auth/code", data={"id": self.id_de("admin1")})
        self.assertEqual(r.status_code, 400)
        self.assertIn("propre compte", self.texte(r))
        self.assertEqual(self.admin.post("/m/travaux/auth/code", data={"id": "99999"}).status_code, 400)
        self.assertEqual(self.admin.post("/m/travaux/auth/code", data={"id": "abc"}).status_code, 400)

    def test_mot_de_passe_provisoire(self):
        r = self.admin.post("/m/travaux/auth/provisoire", data={"id": self.id_sec})
        self.assertEqual(r.status_code, 200)
        m = re.search(r'id="secret"[^>]*>([^<]+)<', self.texte(r))
        provisoire = m.group(1).strip()
        self.assertEqual(self.journal("MDP_REINITIALISE"), 1)
        c = self.app.test_client()
        self.assertEqual(c.post("/connexion", data={"login": "sec1", "mdp": MDP}).status_code, 200)       # l'ancien ne marche plus
        r = c.post("/connexion", data={"login": "sec1", "mdp": provisoire})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/mot-de-passe", c.get("/").headers["Location"])                                     # changement obligatoire
        self.assertNotIn(provisoire, self.texte(self.admin.get("/m/travaux/auth")))

    def test_deblocage(self):
        c = self.app.test_client()
        for _ in range(6):
            c.post("/connexion", data={"login": "sec1", "mdp": "mauvais-mot-de-passe"})
        self.assertIn("Bloqué", self.texte(self.admin.get("/m/travaux/auth")))
        r = self.admin.post("/m/travaux/auth/debloquer", data={"id": self.id_sec})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("Bloqué (trop", self.texte(self.admin.get("/m/travaux/auth")))
        self.assertEqual(self.journal("COMPTE_DEBLOQUE"), 1)

    def test_lien_mot_de_passe_oublie_sur_la_connexion(self):
        self.assertIn("/mot-de-passe-oublie", self.app.test_client().get("/connexion").get_data(as_text=True))
        self.assertEqual(self.app.test_client().get("/mot-de-passe-oublie").status_code, 200)


class TestSauvegarde(Base):
    def test_creation_et_telechargement(self):
        self.assertIn("Aucune sauvegarde", self.texte(self.admin.get("/m/travaux/sauvegarde")))
        r = self.admin.post("/m/travaux/sauvegarde/creer")
        self.assertEqual(r.status_code, 302)
        page = self.texte(self.admin.get("/m/travaux/sauvegarde"))
        nom = re.search(r"(Sauvegarde[^<\"]*\.csfbak)", page).group(1)
        self.assertEqual(self.journal("SAUVEGARDE_CREEE"), 1)
        r = self.admin.get(f"/m/travaux/sauvegarde/telecharger?f={nom}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r.headers["Content-Disposition"])
        self.assertTrue(r.data.startswith(b"PK"))                    # archive zip
        self.assertEqual(self.journal("SAUVEGARDE_TELECHARGEE"), 1)
        self.assertEqual(self.sec.get(f"/m/travaux/sauvegarde/telecharger?f={nom}").status_code, 403)

    def test_telechargement_limite_aux_sauvegardes(self):
        for f in ("../college.db", "..%2Fcollege.db", "college.db", "/etc/passwd", "inconnu.csfbak", ""):
            self.assertEqual(self.admin.get("/m/travaux/sauvegarde/telecharger?f=" + f).status_code, 404, f)


class TestRestauration(Base):
    def faire_sauvegarde(self):
        self.admin.post("/m/travaux/sauvegarde/creer")
        page = self.texte(self.admin.get("/m/travaux/restauration"))
        return re.search(r"(Sauvegarde[^<\"]*\.csfbak)", page).group(1)

    def restaurer(self, nom, **plus):
        d = {"f": nom, "confirmation": "RESTAURER", "mdp": MDP}
        d.update(plus)
        return self.admin.post("/m/travaux/restauration/restaurer", data=d)

    def test_examen_puis_restauration(self):
        nom = self.faire_sauvegarde()
        page = self.texte(self.admin.get(f"/m/travaux/restauration/examiner?f={nom}"))
        self.assertIn("Fichier contrôlé", page)
        security.creer_utilisateur(self.conn, "apres", "Ajouté Après", "SECRETAIRE", MDP)
        r = self.restaurer(nom)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/connexion", r.headers["Location"])
        c = database.connecter(self.chemin)
        try:
            self.assertIsNone(c.execute("SELECT 1 FROM UTILISATEUR WHERE LOGIN = 'apres'").fetchone())
            self.assertEqual(c.execute("SELECT COUNT(*) FROM JOURNAL WHERE ACTION = 'RESTAURATION_EFFECTUEE'").fetchone()[0], 1)
        finally:
            c.close()
        self.assertEqual(self.admin.get("/m/travaux/restauration").status_code, 302)       # session fermée : reconnexion demandée

    def test_confirmation_et_mot_de_passe_exiges(self):
        nom = self.faire_sauvegarde()
        security.creer_utilisateur(self.conn, "apres", "Ajouté Après", "SECRETAIRE", MDP)
        self.assertEqual(self.restaurer(nom, confirmation="oui").status_code, 400)
        r = self.restaurer(nom, mdp="mauvais")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Mot de passe incorrect", self.texte(r))
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM UTILISATEUR WHERE LOGIN = 'apres'").fetchone())   # rien n'a changé

    def test_seulement_un_fichier_de_la_liste(self):
        for f in ("../college.db", "college.db", "/etc/passwd", "inconnu.csfbak", ""):
            self.assertEqual(self.restaurer(f).status_code, 404, f)
            self.assertEqual(self.admin.get("/m/travaux/restauration/examiner?f=" + f).status_code, 404, f)

    def test_envoi_d_un_fichier(self):
        nom = self.faire_sauvegarde()
        octets = self.admin.get(f"/m/travaux/sauvegarde/telecharger?f={nom}").data
        r = self.admin.post("/m/travaux/restauration/importer", data={"fichier": (io.BytesIO(octets), "ma_copie.csfbak")},
                            content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        self.assertIn("Importee", r.headers["Location"])
        self.assertEqual(self.journal("SAUVEGARDE_IMPORTEE"), 1)
        self.assertEqual(self.admin.get(r.headers["Location"]).status_code, 200)

    def test_envoi_refuse(self):
        def envoyer(contenu, nom):
            return self.admin.post("/m/travaux/restauration/importer", data={"fichier": (io.BytesIO(contenu), nom)},
                                   content_type="multipart/form-data")
        self.assertEqual(envoyer(b"n'importe quoi", "x.csfbak").status_code, 400)          # pas une sauvegarde
        self.assertEqual(envoyer(b"PK", "x.zip").status_code, 400)                          # mauvaise extension
        nom = self.faire_sauvegarde()
        octets = bytearray(self.admin.get(f"/m/travaux/sauvegarde/telecharger?f={nom}").data)
        octets[len(octets) // 2] ^= 0xFF                                                    # fichier abîmé
        self.assertEqual(envoyer(bytes(octets), "abime.csfbak").status_code, 400)
        self.assertFalse(any("Importee" in b for b in os.listdir(config.DOSSIER_SAUVEGARDES)))   # rien n'est resté sur le serveur
        self.assertEqual(self.sec.post("/m/travaux/restauration/importer", data={}).status_code, 403)

    def test_origine_etrangere_refusee(self):
        nom = self.faire_sauvegarde()
        r = self.admin.post("/m/travaux/restauration/restaurer", data={"f": nom, "confirmation": "RESTAURER", "mdp": MDP},
                            headers=ETRANGER)
        self.assertEqual(r.status_code, 403)


CLE_MAJ = "cle-de-maj-2026"


class TestMiseAJour(Base):
    """Mise à jour du programme depuis le navigateur. Le « programme » est un dossier temporaire : le vrai code n'est jamais touché."""

    def setUp(self):
        super().setUp()
        shutil.rmtree(os.path.join(os.environ["CSF_DATA_DIR"], "mises_a_jour_recues"), ignore_errors=True)
        self.tmp = tempfile.mkdtemp()
        self.prog = os.path.join(self.tmp, "programme")
        self.source = os.path.join(self.tmp, "source")
        for dossier, version, contenu in ((self.prog, config.VERSION, "ancien"), (self.source, "9.9", "nouveau")):
            os.makedirs(os.path.join(dossier, "templates"))
            for f in ("main.py", "config.py", "database.py", "migrations.py", "wsgi.py"):
                with open(os.path.join(dossier, f), "w", encoding="utf-8") as h:
                    h.write(f'VERSION = "{version}"\n# {contenu}\n' if f == "config.py" else f"# {f} {contenu}\n")
            with open(os.path.join(dossier, "templates", "page.html"), "w", encoding="utf-8") as h:
                h.write(contenu)
        self.paquet = os.path.join(self.tmp, "maj.csfupd")
        miseajour.creer_paquet(self.paquet, CLE_MAJ, dossier=self.source, structure=99)
        self.ancien_dossier = config.DOSSIER_APP
        config.DOSSIER_APP = __import__("pathlib").Path(self.prog)

    def tearDown(self):
        config.DOSSIER_APP = self.ancien_dossier
        shutil.rmtree(self.tmp, ignore_errors=True)

    def envoyer(self, cle=CLE_MAJ, client=None, octets=None, nom="maj.csfupd"):
        if octets is None:
            with open(self.paquet, "rb") as f:
                octets = f.read()
        return (client or self.admin).post("/m/travaux/miseajour/controler",
                                           data={"fichier": (io.BytesIO(octets), nom), "cle": cle}, content_type="multipart/form-data")

    def nom_recu(self, page):
        return re.search(r'name="f" value="(maj_[^"]+\.csfupd)"', page).group(1)

    def test_controle_puis_installation(self):
        r = self.envoyer()
        self.assertEqual(r.status_code, 200)
        page = self.texte(r)
        self.assertIn("Signature valide", page)
        self.assertIn("9.9", page)
        nom = self.nom_recu(page)
        r = self.admin.post("/m/travaux/miseajour/installer", data={"f": nom, "cle": CLE_MAJ, "mdp": MDP})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Mise à jour installée", self.texte(r))
        with open(os.path.join(self.prog, "templates", "page.html"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "nouveau")                                       # les pages web sont mises à jour aussi
        with open(os.path.join(self.prog, "config.py"), encoding="utf-8") as f:
            self.assertIn("9.9", f.read())
        self.assertEqual(self.journal("MISE_A_JOUR_PROGRAMME"), 1)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "x")))
        self.assertEqual(len(miseajour.lister_archives(self.prog)), 1)
        self.assertEqual(os.listdir(os.path.join(os.environ["CSF_DATA_DIR"], "mises_a_jour_recues")), [])   # fichier reçu effacé

    def test_mauvaise_cle_refusee(self):
        r = self.envoyer(cle="mauvaise-cle-123")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Clé de mise à jour incorrecte", self.texte(r))
        self.assertEqual(self.journal("MISE_A_JOUR_REFUSEE"), 1)
        self.assertEqual(os.listdir(os.path.join(os.environ["CSF_DATA_DIR"], "mises_a_jour_recues")), [])

    def test_mauvais_mot_de_passe_ou_cle_a_l_installation(self):
        nom = self.nom_recu(self.texte(self.envoyer()))
        r = self.admin.post("/m/travaux/miseajour/installer", data={"f": nom, "cle": CLE_MAJ, "mdp": "faux"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Mot de passe incorrect", self.texte(r))
        r = self.admin.post("/m/travaux/miseajour/installer", data={"f": nom, "cle": "autre-cle-123", "mdp": MDP})
        self.assertEqual(r.status_code, 400)
        with open(os.path.join(self.prog, "templates", "page.html"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "ancien")                                       # rien n'a changé

    def test_fichier_abime_refuse(self):
        with open(self.paquet, "rb") as f:
            octets = bytearray(f.read())
        octets[len(octets) // 2] ^= 0xFF
        self.assertEqual(self.envoyer(octets=bytes(octets)).status_code, 400)
        self.assertEqual(self.envoyer(octets=b"pas une archive").status_code, 400)
        self.assertEqual(self.envoyer(nom="maj.zip").status_code, 400)

    def test_version_pas_plus_recente_refusee(self):
        for f in ("config.py",):
            with open(os.path.join(self.source, f), "w", encoding="utf-8") as h:
                h.write(f'VERSION = "{config.VERSION}"\n')
        miseajour.creer_paquet(self.paquet, CLE_MAJ, dossier=self.source, structure=99)
        nom = self.nom_recu(self.texte(self.envoyer()))
        r = self.admin.post("/m/travaux/miseajour/installer", data={"f": nom, "cle": CLE_MAJ, "mdp": MDP})
        self.assertEqual(r.status_code, 400)
        self.assertIn("pas plus récente", self.texte(r))

    def test_nom_de_fichier_libre_refuse(self):
        for f in ("../x.csfupd", "/etc/passwd", "absent.csfupd", ""):
            r = self.admin.post("/m/travaux/miseajour/installer", data={"f": f, "cle": CLE_MAJ, "mdp": MDP})
            self.assertEqual(r.status_code, 400, f)

    def test_retour_a_la_version_gardee(self):
        nom = self.nom_recu(self.texte(self.envoyer()))
        self.admin.post("/m/travaux/miseajour/installer", data={"f": nom, "cle": CLE_MAJ, "mdp": MDP})
        archive = miseajour.lister_archives(self.prog)[0]["nom"]
        miseajour.config.VERSION  # (la base de test est à jour : la structure gardée est celle de la base)
        r = self.admin.post("/m/travaux/miseajour/revenir", data={"nom": archive, "mdp": "faux"})
        self.assertEqual(r.status_code, 400)
        r = self.admin.post("/m/travaux/miseajour/revenir", data={"nom": archive, "mdp": MDP})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Retour effectué", self.texte(r))
        with open(os.path.join(self.prog, "templates", "page.html"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "ancien")
        self.assertEqual(self.journal("RETOUR_ANCIENNE_VERSION"), 1)

    def test_reserve_a_l_administrateur_et_origine(self):
        self.assertEqual(self.envoyer(client=self.sec).status_code, 403)
        r = self.admin.post("/m/travaux/miseajour/installer", data={"f": "x.csfupd", "cle": CLE_MAJ, "mdp": MDP}, headers=ETRANGER)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.sec.post("/m/travaux/miseajour/revenir", data={"nom": "x", "mdp": MDP}).status_code, 403)


if __name__ == "__main__":
    unittest.main()

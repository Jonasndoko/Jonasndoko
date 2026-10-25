"""Tests des fonctionnalités de la Direction des études (etudes_gestion.py) et du module Présence des élèves (web_presence.py) : accès et droits fins, années et périodes,
cours, programme des classes, enseignants (titulaire, compte), présence en lecture, protection contre les envois d'autres sites, journal.
Lancer :  python -m unittest test_etudes_gestion"""
import html
import os
import re
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web             # noqa: E402
import config              # noqa: E402
import cours               # noqa: E402
import database            # noqa: E402
import droits              # noqa: E402
import notes               # noqa: E402
import personnel           # noqa: E402
import presence_eleves as pe   # noqa: E402
import security            # noqa: E402

MDP = "Tr@vail-Amour-2026"
ETRANGER = {"Origin": "https://autre-site.example"}
J = "2026-09-15"


def agent(**a):
    base = {"nom": "mukendi", "postnom": "kabeya", "prenom": "jean", "sexe": "M", "date_naissance": "15/03/1985", "adresse": "Kinshasa",
            "telephone": "0812345678", "email": "", "date_engagement": "01/09/2015", "fonction": "Enseignant", "statut_pro": "PERMANENT",
            "matricule": ""}
    base.update(a)
    return base


class Base(unittest.TestCase):
    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "g.db")
        c = self.conn = database.connecter(self.chemin)
        security.creer_utilisateur(c, "admin1", "Alice Directrice", "ADMINISTRATEUR", MDP)
        self.admin_s = security.authentifier(c, "admin1", MDP).session
        self.id_sec = security.creer_utilisateur(c, "sec1", "Sophie Secrétaire", "SECRETAIRE", MDP)
        security.creer_utilisateur(c, "disc1", "Denis Discipline", "DIRECTEUR_DISCIPLINE", MDP)
        with c:
            c.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU) VALUES ('SEC', 'Secondaire'), ('HUM', 'Humanités')")
            c.execute("INSERT INTO OPTION_SCO (CODE_OPTION, DESI_OPTION) VALUES ('SCI', 'Scientifique')")
            c.execute("INSERT INTO POSSEDE (CODE_NIVEAU, CODE_OPTION) VALUES ('HUM', 'SCI')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('7ème A', 'SEC', '7ème', 'A')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('8ème A', 'SEC', '8ème', 'A')")
        self.c7, self.c8 = (r[0] for r in c.execute("SELECT N_CLASSE FROM CLASSE ORDER BY N_CLASSE"))
        self.annee = cours.creer_annee(c, self.admin_s, "2026-2027", "07/09/2026", "10/07/2027", en_cours=True)
        cours.generer_structure_standard(c, self.admin_s, self.annee)
        self.m1 = personnel.enregistrer_agent(c, self.admin_s, agent())["matricule"]
        self.m2 = personnel.enregistrer_agent(c, self.admin_s, agent(nom="banza", prenom="paul"))["matricule"]
        self.maths = cours.ajouter_cours(c, self.admin_s, {"libelle": "Mathématiques", "code_niveau": "SEC", "heures_semaine": "4"})
        self.fr = cours.ajouter_cours(c, self.admin_s, {"libelle": "Français", "code_niveau": "SEC", "heures_semaine": "5"})
        cours.ouvrir_cours(c, self.admin_s, self.annee, self.c7)            # la 8ème A reste sans cours ouverts
        self.cc = {r["ID_COURS"]: r["ID_CC"] for r in c.execute("SELECT * FROM COURS_CLASSE WHERE N_CLASSE = ?", (self.c7,))}
        with c:
            for i, nom in enumerate(("Kasongo", "Amisi", "Zola")):
                c.execute("INSERT INTO ELEVE (MATRICULE, NOM, POSTNOM, PRENOM, SEXE) VALUES (?,?,?,?,?)", (f"000{i}/26", nom, "X", "Y", "M"))
                c.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?,?,?)", (self.annee, f"000{i}/26", self.c7))
        self.app = app_web.creer_app(self.chemin)
        self.admin, self.sec, self.disc = (self.app.test_client() for _ in range(3))
        for cl, login in ((self.admin, "admin1"), (self.sec, "sec1"), (self.disc, "disc1")):
            self.assertEqual(cl.post("/connexion", data={"login": login, "mdp": MDP}).status_code, 302)

    def donner(self, *noms):
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_sec, {("direction_etudes", d) for d in noms})

    def texte(self, r):
        return html.unescape(r.get_data(as_text=True))

    def actions(self):
        return [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL ORDER BY ID_LOG")]

    def pointer(self):
        """Un professeur pointe le 15/09 : Kasongo présent partout, Amisi absent en français, Zola présent."""
        p = notes.creer_compte_professeur(self.conn, self.admin_s, self.m1)
        p2 = notes.creer_compte_professeur(self.conn, self.admin_s, self.m2)
        cours.attribuer_professeur(self.conn, self.admin_s, [self.cc[self.maths]], self.m1)
        cours.attribuer_professeur(self.conn, self.admin_s, [self.cc[self.fr]], self.m2)
        s1 = security.authentifier(self.conn, p["login"], p["mdp_temporaire"]).session
        s2 = security.authentifier(self.conn, p2["login"], p2["mdp_temporaire"]).session
        for m in ("0000/26", "0001/26", "0002/26"):
            pe.marquer(self.conn, s1, self.cc[self.maths], "15/09/2026", m, "P")
        pe.marquer(self.conn, s2, self.cc[self.fr], "15/09/2026", "0000/26", "P")
        pe.marquer(self.conn, s2, self.cc[self.fr], "15/09/2026", "0001/26", "A")
        pe.marquer(self.conn, s2, self.cc[self.fr], "15/09/2026", "0002/26", "P")


class TestAcces(Base):
    GETS = ("/m/etudes_discipline/direction_etudes?f=calendrier", "/m/etudes_discipline/direction_etudes?f=cours", "/m/etudes_discipline/direction_etudes?f=programme", "/m/etudes_discipline/direction_etudes?f=enseignants")
    POSTS = ("/m/etudes_discipline/direction_etudes/gestion/calendrier/annee", "/m/etudes_discipline/direction_etudes/gestion/calendrier/dates", "/m/etudes_discipline/direction_etudes/gestion/calendrier/en-cours",
             "/m/etudes_discipline/direction_etudes/gestion/calendrier/standard", "/m/etudes_discipline/direction_etudes/gestion/calendrier/semestre", "/m/etudes_discipline/direction_etudes/gestion/calendrier/periode",
             "/m/etudes_discipline/direction_etudes/gestion/calendrier/modifier", "/m/etudes_discipline/direction_etudes/gestion/calendrier/supprimer", "/m/etudes_discipline/direction_etudes/gestion/cours/enregistrer",
             "/m/etudes_discipline/direction_etudes/gestion/cours/activite", "/m/etudes_discipline/direction_etudes/gestion/cours/supprimer", "/m/etudes_discipline/direction_etudes/gestion/programme/ouvrir",
             "/m/etudes_discipline/direction_etudes/gestion/programme/attribuer", "/m/etudes_discipline/direction_etudes/gestion/programme/retirer-prof", "/m/etudes_discipline/direction_etudes/gestion/programme/retirer-cours",
             "/m/etudes_discipline/direction_etudes/gestion/programme/heures", "/m/etudes_discipline/direction_etudes/gestion/enseignants/associer", "/m/etudes_discipline/direction_etudes/gestion/enseignants/detacher",
             "/m/etudes_discipline/direction_etudes/gestion/enseignants/titulaire", "/m/etudes_discipline/direction_etudes/gestion/enseignants/titulaire-retirer", "/m/etudes_discipline/direction_etudes/gestion/enseignants/compte")

    def test_non_connecte(self):
        c = self.app.test_client()
        for url in self.GETS + ("/m/etudes_discipline/direction_etudes?f=presence_eleves", "/m/presence_eleves"):
            self.assertEqual(c.get(url).status_code, 302, url)
        for url in self.POSTS:
            self.assertEqual(c.post(url, data={}).status_code, 302, url)

    def test_sans_droit_tout_est_refuse(self):
        for url in self.GETS + ("/m/etudes_discipline/direction_etudes?f=presence_eleves", "/m/presence_eleves"):
            self.assertEqual(self.sec.get(url).status_code, 403, url)
        for url in self.POSTS:
            self.assertEqual(self.sec.post(url, data={"a": self.annee, "c": self.c7, "m": self.m1}).status_code, 403, url)

    def test_la_direction_de_discipline_ne_voit_que_la_presence(self):
        for url in self.GETS:
            self.assertEqual(self.disc.get(url).status_code, 403, url)
        for url in self.POSTS:
            self.assertEqual(self.disc.post(url, data={"a": self.annee, "c": self.c7}).status_code, 403, url)
        self.assertEqual(self.disc.get("/m/etudes_discipline/direction_etudes?f=presence_eleves").status_code, 403)
        r = self.disc.get("/m/presence_eleves")
        self.assertEqual(r.status_code, 200)
        page = self.texte(r)
        self.assertIn("Présence des élèves", page)
        self.assertNotIn("Années et périodes", page)                  # aucun onglet de gestion
        self.assertIn(self.disc.get("/m/gestion_scolaire").status_code, (403, 404))      # le module n'existe plus

    def test_le_module_gestion_scolaire_n_existe_plus(self):
        page = self.admin.get("/menu").get_data(as_text=True)
        self.assertNotIn("/m/gestion_scolaire", page)
        self.assertNotIn('href="/m/etudes_discipline"', page)         # l'ancien module d'accueil n'existe plus non plus
        self.assertIn('href="/m/etudes"', page)
        self.assertIn(self.admin.get("/m/gestion_scolaire").status_code, (403, 404))
        self.assertIn(self.admin.get("/m/gestion_scolaire/cours").status_code, (403, 404))
        self.assertNotIn("gestion_scolaire", config.MODULES_DROITS)
        # deux modules (Présence des élèves + Gestion des études et discipline) : le menu principal s'affiche
        self.assertEqual(self.disc.get("/").status_code, 200)

    def test_les_fonctionnalites_sont_dans_la_direction_des_etudes(self):
        page = self.texte(self.admin.get("/m/etudes_discipline/direction_etudes"))
        for titre in ("Années et périodes", "Cours", "Programme des classes", "Enseignants et classes", "Présence des élèves"):
            self.assertIn(titre, page)
        # les autres espaces ne les affichent pas
        page = self.texte(self.admin.get("/m/etudes_discipline/direction_discipline"))
        self.assertNotIn("Programme des classes", page)

    def test_origine_etrangere_refusee(self):
        for url in self.POSTS:
            self.assertEqual(self.admin.post(url, data={"a": self.annee, "c": self.c7}, headers=ETRANGER).status_code, 403, url)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM COURS").fetchone()[0], 2)

    def test_toutes_les_pages_s_affichent(self):
        for url in self.GETS + ("/m/etudes_discipline/direction_etudes?f=presence_eleves", f"/m/etudes_discipline/direction_etudes?f=programme&a={self.annee}&c={self.c7}",
                                 f"/m/etudes_discipline/direction_etudes?f=enseignants&a={self.annee}&c={self.c7}&m={self.m1}"):
            r = self.admin.get(url)
            self.assertEqual(r.status_code, 200, url)

    def test_droits_fins(self):
        self.donner("LECTURE")
        self.assertEqual(self.sec.get("/m/etudes_discipline/direction_etudes?f=cours").status_code, 200)
        page = self.texte(self.sec.get("/m/etudes_discipline/direction_etudes?f=cours"))
        self.assertNotIn("Nouveau cours", page)                         # pas de formulaire sans le droit Ajout
        r = self.sec.post("/m/etudes_discipline/direction_etudes/gestion/cours/enregistrer", data={"libelle": "Histoire", "code_niveau": "SEC"})
        self.assertEqual(r.status_code, 403)
        self.donner("LECTURE", "AJOUT")
        r = self.sec.post("/m/etudes_discipline/direction_etudes/gestion/cours/enregistrer", data={"libelle": "Histoire", "code_niveau": "SEC", "heures_semaine": "2"})
        self.assertEqual(r.status_code, 302)
        ident = self.conn.execute("SELECT ID_COURS FROM COURS WHERE LIBELLE = 'Histoire'").fetchone()[0]
        r = self.sec.post("/m/etudes_discipline/direction_etudes/gestion/cours/enregistrer", data={"id": ident, "libelle": "Histoire 2", "code_niveau": "SEC"})
        self.assertEqual(r.status_code, 403)                            # modifier demande « Modification »
        self.assertEqual(self.sec.post("/m/etudes_discipline/direction_etudes/gestion/cours/supprimer", data={"id": ident}).status_code, 403)
        self.donner("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")
        self.assertEqual(self.sec.post("/m/etudes_discipline/direction_etudes/gestion/cours/supprimer", data={"id": ident}).status_code, 302)


class TestCalendrier(Base):
    def test_annee_dates_en_cours_et_erreur(self):
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/calendrier/annee", data={"annee": "2027-2028", "debut": "2027-09-06", "fin": "2028-07-08"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("a=2027-2028", r.headers["Location"])
        self.assertEqual(self.conn.execute("SELECT DATE_DEBUT FROM ANNEE_CALENDRIER WHERE ANNEESCO = '2027-2028'").fetchone()[0], "2027-09-06")
        self.assertEqual(self.admin.post("/m/etudes_discipline/direction_etudes/gestion/calendrier/en-cours", data={"a": "2027-2028"}).status_code, 302)
        self.assertEqual(self.conn.execute("SELECT ANNEESCO FROM ANNEE_SCO WHERE EN_COURS = 1").fetchone()[0], "2027-2028")
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/calendrier/dates", data={"a": "2027-2028", "debut": "2027-09-07", "fin": "2028-07-09"})
        self.assertEqual(r.status_code, 302)
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/calendrier/annee", data={"annee": "2026-2028", "debut": "2027-09-06", "fin": "2028-07-08"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("deux années qui se suivent", self.texte(r))
        self.assertIn("ANNEE_SCOLAIRE_CREEE", self.actions())

    def test_semestres_et_periodes(self):
        page = self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=calendrier&a={self.annee}"))
        self.assertIn("1er semestre", page.lower().replace("premier", "1er")) if "semestre" in page.lower() else self.fail("aucun semestre affiché")
        sem = self.conn.execute("SELECT ID_SEM, DATE_DEBUT FROM SEMESTRE_SCO ORDER BY DATE_DEBUT").fetchone()
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/calendrier/modifier", data={
            "genre": "S", "id": sem["ID_SEM"], "a": self.annee, "libelle": "Semestre un", "debut": sem["DATE_DEBUT"],
            "fin": self.conn.execute("SELECT DATE_FIN FROM SEMESTRE_SCO WHERE ID_SEM = ?", (sem["ID_SEM"],)).fetchone()[0]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.conn.execute("SELECT LIBELLE FROM SEMESTRE_SCO WHERE ID_SEM = ?", (sem["ID_SEM"],)).fetchone()[0], "Semestre un")
        # une période hors des dates de son semestre est refusée
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/calendrier/periode", data={"id_sem": sem["ID_SEM"], "a": self.annee, "libelle": "Hors", "debut": "2030-01-01", "fin": "2030-02-01"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PERIODE_SCO WHERE LIBELLE = 'Hors'").fetchone()[0], 0)

    def test_structure_standard_primaire_en_trimestres(self):
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/calendrier/standard", data={"a": self.annee, "s": "PRIMAIRE"})
        self.assertEqual(r.status_code, 302, self.texte(r)[:300])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM SEMESTRE_SCO WHERE SECTION = 'PRIMAIRE'").fetchone()[0], 3)
        page = self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=calendrier&a={self.annee}&s=PRIMAIRE"))
        self.assertIn("Trimestres et périodes", page)
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/calendrier/standard", data={"a": self.annee, "s": "PRIMAIRE"})
        self.assertEqual(r.status_code, 400)                            # déjà créée

    def test_suppression_d_un_semestre(self):
        self.admin.post("/m/etudes_discipline/direction_etudes/gestion/calendrier/standard", data={"a": self.annee, "s": "PRIMAIRE"})
        sem = self.conn.execute("SELECT ID_SEM FROM SEMESTRE_SCO WHERE SECTION = 'PRIMAIRE' ORDER BY DATE_DEBUT LIMIT 1").fetchone()[0]
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/calendrier/supprimer", data={"genre": "S", "id": sem, "a": self.annee, "s": "PRIMAIRE"})
        self.assertEqual(r.status_code, 400)                            # un trimestre ne se supprime qu'une fois ses périodes retirées
        self.assertIn("supprimez-les d'abord", self.texte(r))
        for per in [x[0] for x in self.conn.execute("SELECT ID_PER FROM PERIODE_SCO WHERE ID_SEM = ?", (sem,))]:
            self.assertEqual(self.admin.post("/m/etudes_discipline/direction_etudes/gestion/calendrier/supprimer", data={"genre": "P", "id": per, "a": self.annee, "s": "PRIMAIRE"}).status_code, 302)
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/calendrier/supprimer", data={"genre": "S", "id": sem, "a": self.annee, "s": "PRIMAIRE"})
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(self.conn.execute("SELECT 1 FROM SEMESTRE_SCO WHERE ID_SEM = ?", (sem,)).fetchone())


class TestCours(Base):
    def test_ajout_modification_activite_suppression(self):
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/cours/enregistrer", data={"libelle": "Histoire", "code_niveau": "SEC", "heures_semaine": "2"})
        self.assertEqual(r.status_code, 302)
        ident = self.conn.execute("SELECT ID_COURS FROM COURS WHERE LIBELLE = 'Histoire'").fetchone()[0]
        page = self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=cours&e={ident}"))
        self.assertIn("Modifier le cours", page)
        self.assertIn('value="Histoire"', page)
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/cours/enregistrer", data={"id": ident, "libelle": "Histoire-Géo", "code_niveau": "SEC", "heures_semaine": "3"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.conn.execute("SELECT HEURES_SEMAINE FROM COURS WHERE ID_COURS = ?", (ident,)).fetchone()[0], 3)
        self.admin.post("/m/etudes_discipline/direction_etudes/gestion/cours/activite", data={"id": ident, "action": "desactiver"})
        self.assertEqual(self.conn.execute("SELECT ACTIF FROM COURS WHERE ID_COURS = ?", (ident,)).fetchone()[0], 0)
        self.admin.post("/m/etudes_discipline/direction_etudes/gestion/cours/activite", data={"id": ident, "action": "activer"})
        self.assertEqual(self.conn.execute("SELECT ACTIF FROM COURS WHERE ID_COURS = ?", (ident,)).fetchone()[0], 1)
        self.assertEqual(self.admin.post("/m/etudes_discipline/direction_etudes/gestion/cours/supprimer", data={"id": ident}).status_code, 302)
        self.assertIsNone(self.conn.execute("SELECT 1 FROM COURS WHERE ID_COURS = ?", (ident,)).fetchone())
        for a in ("COURS_AJOUT", "COURS_MODIFICATION", "COURS_DESACTIVATION", "COURS_ACTIVATION"):
            self.assertIn(a, self.actions())

    def test_erreurs_gardent_la_saisie(self):
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/cours/enregistrer", data={"libelle": "Mathématiques", "code_niveau": "SEC", "heures_semaine": "4"})
        self.assertEqual(r.status_code, 400)
        page = self.texte(r)
        self.assertIn("existe déjà", page)
        self.assertIn('value="Mathématiques"', page)
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/cours/enregistrer", data={"libelle": "Chimie", "code_niveau": "SEC", "code_option": "SCI"})
        self.assertIn("pas proposée", self.texte(r))                    # l'option SCI n'existe qu'en humanités
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/cours/enregistrer", data={"libelle": "Chimie", "code_niveau": "HUM", "code_option": "SCI", "heures_semaine": "99"})
        self.assertIn("nombre entier", self.texte(r))

    def test_cours_utilise_non_supprimable(self):
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/cours/supprimer", data={"id": self.maths})
        self.assertEqual(r.status_code, 400)
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM COURS WHERE ID_COURS = ?", (self.maths,)).fetchone())

    def test_filtres(self):
        page = self.texte(self.admin.get("/m/etudes_discipline/direction_etudes?f=cours&n=SEC&q=fran"))
        self.assertIn("Français", page)
        self.assertNotIn("Mathématiques", page)


class TestProgramme(Base):
    def post(self, endpoint, **data):
        return self.admin.post("/m/etudes_discipline/direction_etudes/gestion/programme/" + endpoint, data={"a": self.annee, "c": self.c8, **data})

    def test_ouvrir_attribuer_heures_retirer(self):
        page = self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=programme&a={self.annee}&c={self.c8}"))
        self.assertIn("Mathématiques", page)                           # applicable, pas encore ouvert
        r = self.post("ouvrir", ids=str(self.maths))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM COURS_CLASSE WHERE N_CLASSE = ?", (self.c8,)).fetchone()[0], 1)
        r = self.post("ouvrir", tous="1")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM COURS_CLASSE WHERE N_CLASSE = ?", (self.c8,)).fetchone()[0], 2)
        ids = [str(r[0]) for r in self.conn.execute("SELECT ID_CC FROM COURS_CLASSE WHERE N_CLASSE = ?", (self.c8,))]
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/programme/attribuer", data={"a": self.annee, "c": self.c8, "ids": ids, "matricule": self.m1})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM COURS_CLASSE WHERE N_CLASSE = ? AND MATRICULE_PROF = ?", (self.c8, self.m1)).fetchone()[0], 2)
        self.assertIn("MUKENDI", self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=programme&a={self.annee}&c={self.c8}")))
        self.assertEqual(self.post("heures", id=ids[0], heures="6").status_code, 302)
        self.assertEqual(self.conn.execute("SELECT HEURES_SEMAINE FROM COURS_CLASSE WHERE ID_CC = ?", (ids[0],)).fetchone()[0], 6)
        self.assertEqual(self.post("retirer-prof", ids=ids).status_code, 302)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM COURS_CLASSE WHERE MATRICULE_PROF IS NOT NULL AND N_CLASSE = ?", (self.c8,)).fetchone()[0], 0)
        self.assertEqual(self.post("retirer-cours", ids=ids).status_code, 302)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM COURS_CLASSE WHERE N_CLASSE = ?", (self.c8,)).fetchone()[0], 0)
        for a in ("COURS_OUVERT_CLASSE", "PROFESSEUR_ATTRIBUE", "COURS_HEURES_MODIFIEES", "PROFESSEUR_RETIRE", "COURS_RETIRE_CLASSE"):
            self.assertIn(a, self.actions())

    def test_erreurs(self):
        r = self.post("ouvrir")                                        # rien de coché
        self.assertEqual(r.status_code, 400)
        self.assertIn("au moins un cours", self.texte(r))
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/programme/ouvrir", data={"a": self.annee, "c": self.c7, "ids": str(self.maths)})
        self.assertIn("déjà ouvert", self.texte(r))
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/programme/attribuer", data={"a": self.annee, "c": self.c7, "matricule": self.m1})
        self.assertIn("au moins un cours", self.texte(r))
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/programme/attribuer", data={"a": self.annee, "c": self.c7, "ids": str(self.cc[self.maths]), "matricule": "XXXX"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.post("heures", id=str(self.cc[self.maths]), heures="99").status_code, 400)

    def test_cours_avec_points_non_retirable(self):
        per = self.conn.execute("SELECT ID_PER FROM PERIODE_SCO ORDER BY DATE_DEBUT LIMIT 1").fetchone()[0]
        with self.conn:
            self.conn.execute("INSERT INTO CONDUITE (ID_CC, ID_PER, MATRICULE, COTE, DATE_MODIF) VALUES (?,?,?,?,?)",
                              (self.cc[self.maths], per, "0000/26", "A", "2026-09-20T00:00:00"))
        r = self.admin.post("/m/etudes_discipline/direction_etudes/gestion/programme/retirer-cours", data={"a": self.annee, "c": self.c7, "ids": str(self.cc[self.maths])})
        self.assertEqual(r.status_code, 400)
        self.assertIn("points sont déjà saisis", self.texte(r))
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM COURS_CLASSE WHERE ID_CC = ?", (self.cc[self.maths],)).fetchone())


class TestEnseignants(Base):
    def post(self, endpoint, **data):
        return self.admin.post("/m/etudes_discipline/direction_etudes/gestion/enseignants/" + endpoint, data={"a": self.annee, "c": self.c7, "m": self.m1, **data})

    def test_associer_detacher_charge(self):
        self.assertEqual(self.post("associer").status_code, 302)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM COURS_CLASSE WHERE MATRICULE_PROF = ?", (self.m1,)).fetchone()[0], 2)
        page = self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=enseignants&a={self.annee}&c={self.c7}&m={self.m1}"))
        self.assertIn("1 classe(s), 2 cours, 9 h/sem.", page)
        r = self.post("associer")                                       # plus aucun cours sans professeur
        self.assertEqual(r.status_code, 400)
        self.assertIn("aucun cours sans professeur", self.texte(r))
        ids = [str(r[0]) for r in self.conn.execute("SELECT ID_CC FROM COURS_CLASSE WHERE MATRICULE_PROF = ?", (self.m1,))]
        self.assertEqual(self.post("detacher", ids=ids).status_code, 302)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM COURS_CLASSE WHERE MATRICULE_PROF = ?", (self.m1,)).fetchone()[0], 0)
        self.assertEqual(self.post("detacher").status_code, 400)        # rien de coché

    def test_recherche_et_enseignants_seulement(self):
        self.post("associer")
        page = self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=enseignants&a={self.annee}&seuls=1"))
        self.assertIn("MUKENDI", page)
        self.assertNotIn("BANZA", page)
        self.assertIn("BANZA", self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=enseignants&a={self.annee}&q=banza")))

    def test_titulaire(self):
        self.assertEqual(self.post("titulaire").status_code, 302)
        self.assertIn(self.m1, self.conn.execute("SELECT MATRICULE FROM TITULAIRE_CLASSE WHERE N_CLASSE = ?", (self.c7,)).fetchone()[0])
        self.assertIn("Titulaire 2026-2027", self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=enseignants&a={self.annee}&c={self.c7}")))
        self.assertEqual(self.post("titulaire-retirer").status_code, 302)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM TITULAIRE_CLASSE").fetchone()[0], 0)
        r = self.post("titulaire-retirer")
        self.assertEqual(r.status_code, 400)
        self.assertIn("pas de titulaire", self.texte(r))
        self.assertIn("TITULAIRE_DESIGNE", self.actions())

    def test_compte_du_professeur_montre_une_fois(self):
        r = self.post("compte")
        self.assertEqual(r.status_code, 200)
        self.assertIn("no-store", r.headers["Cache-Control"])
        page = self.texte(r)
        mdp = re.search(r"Mot de passe provisoire</p>\s*<div[^>]*>([^<]+)<", page).group(1).strip()
        login = re.search(r"Identifiant</p>\s*<div[^>]*>([^<]+)<", page).group(1).strip()
        self.assertIn("COMPTE_PROFESSEUR_CREE", self.actions())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE DETAIL LIKE ?", ("%" + mdp + "%",)).fetchone()[0], 0)
        self.assertNotIn(mdp, self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=enseignants&a={self.annee}&m={self.m1}")))
        c = self.app.test_client()                                     # le professeur se connecte sur /professeur (API de l'espace professeurs)
        r = c.post("/api/connexion", json={"login": login, "mdp": mdp})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["doit_changer_mdp"])
        self.assertIn("/professeur", page)
        r = self.post("compte")                                         # déjà créé
        self.assertEqual(r.status_code, 400)
        self.assertIn("déjà un compte", self.texte(r))

    def test_compte_reserve_a_l_administrateur(self):
        self.donner("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")
        r = self.sec.post("/m/etudes_discipline/direction_etudes/gestion/enseignants/compte", data={"a": self.annee, "m": self.m1})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM COMPTE_PROFESSEUR").fetchone()[0], 0)
        page = self.texte(self.sec.get(f"/m/etudes_discipline/direction_etudes?f=enseignants&a={self.annee}&m={self.m1}"))
        self.assertNotIn("Créer le compte", page)


class TestPresence(Base):
    def test_journee_detail_et_recapitulatif(self):
        self.pointer()
        page = self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=presence_eleves&a={self.annee}&j={J}"))
        self.assertIn("15/09/2026 · 3 élèves : 2 présents, 1 absents, 0 non renseignés.", page)
        page = self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=presence_eleves&a={self.annee}&j={J}&c={self.c7}"))
        self.assertIn("Absent à : Français", page)
        self.assertIn("Amisi", page)
        page = self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=presence_eleves&a={self.annee}&j={J}&c={self.c7}&mode=recap&d1={J}&d2={J}"))
        self.assertIn("1 jour(s) pointé(s)", page)
        self.assertIn("100,0 %", page)
        self.assertIn("0,0 %", page)
        # la direction de discipline voit la même chose
        self.assertIn("2 présents", self.texte(self.disc.get(f"/m/presence_eleves?a={self.annee}&j={J}")))

    def test_jour_sans_pointage_et_jour_futur(self):
        page = self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=presence_eleves&a={self.annee}&j={J}"))
        self.assertIn("0 présents, 0 absents, 3 non renseignés", page)
        r = self.admin.get(f"/m/etudes_discipline/direction_etudes?f=presence_eleves&a={self.annee}&j=2099-01-01")
        self.assertIn("pas encore arrivé", self.texte(r))
        self.assertIn("Date invalide", self.texte(self.admin.get(f"/m/etudes_discipline/direction_etudes?f=presence_eleves&a={self.annee}&j=nimporte")))

    def test_recapitulatif_dates_inversees(self):
        r = self.admin.get(f"/m/etudes_discipline/direction_etudes?f=presence_eleves&a={self.annee}&j={J}&c={self.c7}&mode=recap&d1=2026-09-20&d2=2026-09-10")
        self.assertIn("avant la date de début", self.texte(r))


class TestMigrationDroits(unittest.TestCase):
    """Migration 18 : les droits de l'ancien module « Gestion scolaire » passent à « Direction des études »."""

    def test_droits_reportes_puis_anciennes_lignes_supprimees(self):
        import migrations
        conn = database.connecter(os.path.join(tempfile.mkdtemp(), "m.db"))
        security.creer_utilisateur(conn, "sec1", "Sophie Secrétaire", "SECRETAIRE", MDP)
        uid = conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = 'sec1'").fetchone()[0]
        with conn:
            for d in ("LECTURE", "AJOUT"):
                conn.execute("INSERT INTO DROIT (ID_USER, MODULE, DROIT) VALUES (?, 'gestion_scolaire', ?)", (uid, d))
            conn.execute("INSERT INTO ROLE_DROIT (ROLE, MODULE, DROIT) VALUES ('SECRETAIRE', 'gestion_scolaire', 'MODIFICATION')")
        self.assertNotIn(("direction_etudes", "AJOUT"), droits.droits_utilisateur(conn, uid))
        migrations._mig_gestion_scolaire_supprimee(conn)
        mes = droits.droits_utilisateur(conn, uid)
        self.assertIn(("direction_etudes", "LECTURE"), mes)
        self.assertIn(("direction_etudes", "AJOUT"), mes)
        self.assertNotIn(("direction_etudes", "MODIFICATION"), mes)                      # rien de plus que ce qui était accordé
        self.assertIn(("direction_etudes", "MODIFICATION"), droits.droits_par_defaut(conn, "SECRETAIRE"))
        for table in ("DROIT", "ROLE_DROIT"):
            self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE MODULE = 'gestion_scolaire'").fetchone()[0], 0)
        migrations._mig_gestion_scolaire_supprimee(conn)                                  # sans effet la deuxième fois
        self.assertEqual(len([d for d in droits.droits_utilisateur(conn, uid) if d[0] == "direction_etudes"]), 2)

    def test_la_directrice_des_etudes_gere_les_cours_par_defaut(self):
        conn = database.connecter(os.path.join(tempfile.mkdtemp(), "d.db"))
        security.creer_utilisateur(conn, "admin1", "Alice", "ADMINISTRATEUR", MDP)
        security.creer_utilisateur(conn, "dir1", "Diane Études", "DIRECTRICE_ETUDES", MDP)
        s = security.authentifier(conn, "dir1", MDP).session
        for d in ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION"):
            self.assertTrue(cours.peut(conn, s, d), d)


if __name__ == "__main__":
    unittest.main()

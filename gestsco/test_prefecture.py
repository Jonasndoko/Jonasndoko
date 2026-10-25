"""Tests du sous-menu Préfecture (prefecture.py + page web) : tableau de bord, suivi des élèves, section secondaire, droits.
Lancer :  python -m unittest test_prefecture"""
import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web        # noqa: E402
import config         # noqa: E402
import droits         # noqa: E402
import modules        # noqa: E402
import prefecture     # noqa: E402
import security       # noqa: E402
import sections       # noqa: E402
from test_notes import Base, MDP   # noqa: E402


class TestPrefecture(Base):
    def setUp(self):
        super().setUp()
        c = self.conn
        security.creer_utilisateur(c, "prefet1", "Pierre Préfet", "PREFET", MDP)
        security.creer_utilisateur(c, "secr1", "Sophie", "SECRETAIRE", MDP)
        self.prefet = security.authentifier(c, "prefet1", MDP).session
        self.secr = security.authentifier(c, "secr1", MDP).session
        # une classe du PRIMAIRE avec un élève : le sous-menu ne doit jamais la voir
        with c:
            c.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU, SECTION) VALUES ('PRI', 'Primaire', 'PRIMAIRE')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('3ème prim', 'PRI', '3ème', 'A')")
            self.cp = c.execute("SELECT MAX(N_CLASSE) FROM CLASSE").fetchone()[0]
            c.execute("INSERT INTO ELEVE (MATRICULE, NOM, SEXE) VALUES ('0100/26', 'Petit', 'F')")
            c.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?,?,?)", (self.annee, "0100/26", self.cp))

    def absent(self, matricule, jour, id_cc=None):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO PRESENCE_ELEVE (ID_CC, DATE_COURS, MATRICULE, STATUT, DATE_MODIF, MODIFIE_PAR) "
                              "VALUES (?,?,?,'A','2026-09-10T00:00:00','essai')", (id_cc or self.maths7, jour.isoformat(), matricule))

    # ------------------------------------------------------------------ droits et section
    def test_droit_par_defaut_du_prefet_et_refus_ailleurs(self):
        self.assertTrue(prefecture.peut(self.conn, self.prefet))
        self.assertTrue(prefecture.peut(self.conn, self.admin))
        self.assertFalse(prefecture.peut(self.conn, self.secr))
        for appel in (lambda: prefecture.tableau_de_bord(self.conn, self.secr), lambda: prefecture.chercher_eleves(self.conn, self.secr),
                      lambda: prefecture.profil_eleve(self.conn, self.secr, "0000/26")):
            with self.assertRaises(PermissionError):
                appel()

    def test_droit_retire_effet_immediat(self):
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'prefecture'", (self.prefet.id_user,))
        with self.assertRaises(PermissionError):
            prefecture.tableau_de_bord(self.conn, self.prefet)

    def test_compte_limite_au_primaire_n_a_pas_le_module(self):
        sections.definir_sections(self.conn, self.admin, self.prefet.id_user, [sections.PRIMAIRE])
        self.assertFalse(prefecture.peut(self.conn, self.prefet))
        self.assertEqual(modules.sous_menus_ouverts(self.conn, self.prefet), [])
        self.assertNotIn("etudes_discipline", modules.modules_ouverts(self.conn, self.prefet))
        with self.assertRaises(PermissionError):
            prefecture.tableau_de_bord(self.conn, self.prefet)

    def test_titre_secretariat(self):
        titres = dict(modules.sous_menus_ouverts(self.conn, self.admin))
        self.assertEqual(titres["dossier_eleve"], "Secrétariat")
        self.assertEqual([c for c, _t, _d in config.FONCTIONNALITES_PREFECTURE],
                         ["tableau", "suivi", "finances", "decisions", "discipline", "etudes", "proclamation", "documents", "renvois", "listes"])

    # ------------------------------------------------------------------ 1. tableau de bord
    def test_tableau_secondaire_seulement(self):
        t = prefecture.tableau_de_bord(self.conn, self.prefet)
        self.assertEqual(t["annee"], self.annee)
        self.assertEqual(t["effectif"], {"eleves": 4, "filles": 0, "garcons": 3, "classes": 2})      # l'élève du primaire n'est pas compté
        self.assertEqual({k["classe"] for k in t["classes"]}, {"7ème A", "8ème A"})
        textes = " ".join(a["texte"] for a in t["alertes"])
        self.assertIn("7ème A : aucun titulaire désigné.", textes)
        self.assertEqual(t["en_attente"], {"candidatures": 0, "sans_test": 0, "a_affecter": 0})
        self.assertIn("PREFECTURE_TABLEAU_OUVERT", self.actions())

    def test_presence_du_jour_et_absences_repetees(self):
        auj = date.today()
        for i in range(3):
            self.absent("0001/26", auj - timedelta(days=i))
        t = prefecture.tableau_de_bord(self.conn, self.prefet)
        k7 = next(k for k in t["classes"] if k["classe"] == "7ème A")
        self.assertEqual((k7["presents"], k7["absents"]), (0, 1))
        self.assertEqual(t["jour"]["absents"], 1)
        self.assertEqual([(e["matricule"], e["jours"]) for e in t["absences_repetees"]], [("0001/26", 3)])
        self.assertTrue(any("jours d'absence" in a["texte"] for a in t["alertes"]))

    def test_candidature_en_attente_du_secondaire_comptee(self):
        with self.conn:
            self.conn.execute("PRAGMA foreign_keys = OFF")
            self.conn.execute("DROP TRIGGER CANDIDATURE_EXIGE_PAIEMENT")        # ici on ne teste pas le paiement, seulement le comptage
            self.conn.execute(
                "INSERT INTO CANDIDATURE (ANNEESCO, ORDRE, NUM_CAND, N_RECU, NOM, SEXE, DATE_NAISSANCE, ADRESSE, ECOLE_ORIGINE, POURCENT_ORIGINE, "
                "DOUBLANT, N_CLASSE, NOM_TUTEUR, TEL_TUTEUR, ADRESSE_TUTEUR, DATE_ENREG, ENREGISTRE_PAR) "
                "VALUES (?,1,'C0001/26','R1','Cand','M','2014-01-01','x','E',60,0,?, 't','1','x','2026-09-01','essai')", (self.annee, self.c7))
        t = prefecture.tableau_de_bord(self.conn, self.prefet)
        self.assertEqual(t["en_attente"]["candidatures"], 1)
        self.assertEqual(t["en_attente"]["sans_test"], 1)

    def test_annee_inconnue(self):
        with self.assertRaises(prefecture.ErreurPrefecture):
            prefecture.tableau_de_bord(self.conn, self.prefet, "1999-2000")

    # ------------------------------------------------------------------ 2. suivi des élèves
    def test_recherche_filtre_et_exclut_le_primaire(self):
        tous = prefecture.chercher_eleves(self.conn, self.prefet)
        self.assertEqual([e["matricule"] for e in tous["eleves"]], ["0001/26", "0009/26", "0000/26", "0002/26"])
        self.assertNotIn("0100/26", [e["matricule"] for e in tous["eleves"]])
        self.assertEqual([e["matricule"] for e in prefecture.chercher_eleves(self.conn, self.prefet, texte="kason")["eleves"]], ["0000/26"])
        self.assertEqual([e["matricule"] for e in prefecture.chercher_eleves(self.conn, self.prefet, texte="0002")["eleves"]], ["0002/26"])
        self.assertEqual(len(prefecture.chercher_eleves(self.conn, self.prefet, n_classe=self.c8)["eleves"]), 1)
        self.assertEqual(prefecture.chercher_eleves(self.conn, self.prefet, texte="%")["eleves"], [])        # « % » est un caractère, pas un joker
        self.assertEqual(prefecture.chercher_eleves(self.conn, self.prefet, n_classe=self.cp)["eleves"], [])  # classe du primaire : rien

    def test_dossier_d_un_eleve(self):
        auj = date.today()
        self.absent("0000/26", auj - timedelta(days=1))
        d = prefecture.profil_eleve(self.conn, self.prefet, "0000/26")
        self.assertEqual(d["eleve"]["nom_complet"], "Kasongo X Y")
        self.assertEqual(d["classe_actuelle"]["classe"], "7ème A")
        self.assertEqual([x["annee"] for x in d["dossier"]], [self.annee])
        self.assertEqual(d["dossier"][0]["presences"], {"presents": 0, "absents": 1})
        self.assertEqual(len(d["absences"]), 1)
        self.assertEqual(d["absences"][0]["cours"], ["Mathématiques"])
        self.assertIn("PREFECTURE_DOSSIER_CONSULTE", self.actions())

    def test_dossier_refuse_pour_le_primaire_et_eleve_inconnu(self):
        with self.assertRaises(PermissionError):
            prefecture.profil_eleve(self.conn, self.prefet, "0100/26")
        with self.assertRaises(prefecture.ErreurPrefecture):
            prefecture.profil_eleve(self.conn, self.prefet, "9999/99")

    def test_aucune_donnee_financiere(self):
        d = prefecture.profil_eleve(self.conn, self.prefet, "0000/26")
        t = prefecture.tableau_de_bord(self.conn, self.prefet)
        for structure in (d, t):
            self.assertNotIn("paiement", str(structure).lower())


class TestPrefectureWeb(Base):
    def setUp(self):
        super().setUp()
        c = self.conn
        security.creer_utilisateur(c, "prefet1", "Pierre Préfet", "PREFET", MDP)
        security.creer_utilisateur(c, "secr1", "Sophie", "SECRETAIRE", MDP)
        with c:
            c.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU, SECTION) VALUES ('PRI', 'Primaire', 'PRIMAIRE')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('3ème prim', 'PRI', '3ème', 'A')")
            cp = c.execute("SELECT MAX(N_CLASSE) FROM CLASSE").fetchone()[0]
            c.execute("INSERT INTO ELEVE (MATRICULE, NOM, SEXE) VALUES ('0100/26', 'Petit', 'F')")
            c.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?,?,?)", (self.annee, "0100/26", cp))
        chemin = c.execute("PRAGMA database_list").fetchone()["file"]
        self.app = app_web.creer_app(chemin)
        self.cl = {}
        for login in ("prefet1", "secr1", "admin1"):
            cl = self.app.test_client()
            self.assertEqual(cl.post("/connexion", data={"login": login, "mdp": MDP}).status_code, 302)
            self.cl[login] = cl

    def page(self, login, url):
        r = self.cl[login].get(url)
        return r.status_code, r.get_data(as_text=True)

    def test_tableau_de_bord_affiche(self):
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture")
        self.assertEqual(code, 200)
        for texte in ("Supervision générale", "<span>Tableau de bord</span>", "<span>Suivi des élèves</span>", "Alertes", "Situation par classe", "7ème A"):
            self.assertIn(texte, html)
        self.assertNotIn("Petit", html)

    def test_suivi_liste_et_dossier(self):
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=suivi")
        self.assertEqual(code, 200)
        self.assertIn("Kasongo", html)
        self.assertNotIn("Petit", html)
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=suivi&q=zola")
        self.assertIn("Zola", html)
        self.assertNotIn("Kasongo", html)
        code, html = self.page("prefet1", "/m/etudes_discipline/prefecture?f=suivi&eleve=0000/26")
        self.assertEqual(code, 200)
        for texte in ("Kasongo X Y", "Profil", "Dossier scolaire", "Historique des absences", "Retour à la liste"):
            self.assertIn(texte, html)

    def test_dossier_du_primaire_refuse_et_autres_postes(self):
        self.assertEqual(self.page("prefet1", "/m/etudes_discipline/prefecture?f=suivi&eleve=0100/26")[0], 403)
        self.assertEqual(self.page("secr1", "/m/etudes_discipline/prefecture")[0], 403)
        code, html = self.page("secr1", "/m/etudes_discipline/dossier_eleve")
        self.assertEqual(code, 200)
        self.assertIn("Secrétariat", html)

    def test_parametres_invalides_sans_erreur_serveur(self):
        for url in ("?f=bidon", "?annee=1999-2000", "?f=suivi&annee=zzz", "?f=suivi&classe=abc", "?f=suivi&eleve=inconnu"):
            code, html = self.page("prefet1", "/m/etudes_discipline/prefecture" + url)
            self.assertEqual(code, 200, url)

    def test_texte_saisi_est_echappe(self):
        code, html = self.page("prefet1", '/m/etudes_discipline/prefecture?f=suivi&q=<script>alert(1)</script>')
        self.assertEqual(code, 200)
        self.assertNotIn("<script>alert(1)</script>", html)


if __name__ == "__main__":
    unittest.main()

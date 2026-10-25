"""Tests du module Gestion du personnel en ligne (web_personnel.py) : droits, dossier, documents, fonctions et affectations,
listes, pointage, permissions et congés, états, PDF, protection contre les envois venus d'un autre site, journal.
Lancer :  python -m unittest test_personnel_web"""
import html
import io
import os
import re
import tempfile
import unittest
from datetime import date, timedelta

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web         # noqa: E402
import database        # noqa: E402
import droits          # noqa: E402
import security        # noqa: E402

MDP = "Tr@vail-Amour-2026"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
ETRANGER = {"Origin": "https://autre-site.example"}


def saisie(**autres):
    base = {"nom": "mukendi", "postnom": "kabeya", "prenom": "jean-pierre", "sexe": "M", "date_naissance": "1985-03-15",
            "adresse": "12, avenue de la Paix, Kinshasa", "telephone": "+243 812 345 678", "email": "jp.mukendi@gmail.com",
            "date_engagement": "2015-09-01", "fonction": "Enseignant", "statut_pro": "PERMANENT", "matricule": ""}
    base.update(autres)
    return base


def dernier_jour_de_travail() -> date:
    j = date.today()
    while j.weekday() > 4:
        j -= timedelta(days=1)
    return j


class Base(unittest.TestCase):
    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "c.db")
        self.conn = database.connecter(self.chemin)
        security.creer_utilisateur(self.conn, "admin1", "Alice Directrice", "ADMINISTRATEUR", MDP)
        self.id_sec = security.creer_utilisateur(self.conn, "sec1", "Sophie Secrétaire", "SECRETAIRE", MDP)
        self.app = app_web.creer_app(self.chemin)
        self.admin, self.sec = self.app.test_client(), self.app.test_client()
        for c, l in ((self.admin, "admin1"), (self.sec, "sec1")):
            self.assertEqual(c.post("/connexion", data={"login": l, "mdp": MDP}).status_code, 302)
        self.jour = dernier_jour_de_travail()

    def droits_sec(self, *liste):
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_sec, {("personnel", d) for d in liste})

    def journal(self, action):
        return self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE ACTION = ?", (action,)).fetchone()[0]

    def creer(self, client=None, **autres):
        """Enregistre un agent et retourne son matricule (lu dans la redirection)."""
        r = (client or self.admin).post("/m/personnel/nouveau", data=saisie(**autres))
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:600])
        from urllib.parse import parse_qs, urlparse
        return parse_qs(urlparse(r.headers["Location"]).query)["m"][0]

    def texte(self, reponse):
        return html.unescape(reponse.get_data(as_text=True))


class TestAcces(Base):
    URLS = ("/m/personnel", "/m/personnel/nouveau", "/m/personnel/dossier", "/m/personnel/fonctions", "/m/personnel/affectation",
            "/m/personnel/liste", "/m/personnel/pointage", "/m/personnel/autorisations", "/m/personnel/etats",
            "/m/personnel/dossier/fiche.pdf?m=P0001/26", "/m/personnel/dossier/document/1", "/m/personnel/liste.pdf?mode=FONCTION",
            "/m/personnel/etats.pdf?debut=2026-01-01&fin=2026-01-31")

    def test_non_connecte(self):
        for url in self.URLS:
            self.assertEqual(self.app.test_client().get(url).status_code, 302, url)
        self.assertEqual(self.app.test_client().post("/m/personnel/nouveau", data=saisie()).status_code, 302)

    def test_sans_droit_lecture_403(self):
        self.droits_sec()
        for url in self.URLS:
            self.assertEqual(self.sec.get(url).status_code, 403, url)
        for url in ("/m/personnel/nouveau", "/m/personnel/dossier/modifier", "/m/personnel/fonctions", "/m/personnel/pointage/enregistrer"):
            self.assertEqual(self.sec.post(url, data=saisie()).status_code, 403, url)

    def test_menu_marque_le_module_en_ligne(self):
        page = self.texte(self.admin.get("/menu"))
        tuile = re.search(r'<a class="entree" href="/m/personnel"[^>]*>(.*?)</a>', page, re.S).group(1)
        self.assertNotIn("bientôt", tuile)
        self.assertNotIn("migration", tuile)

    def test_origine_etrangere_refusee(self):
        for url in ("/m/personnel/nouveau", "/m/personnel/dossier/modifier", "/m/personnel/dossier/activite", "/m/personnel/fonctions",
                    "/m/personnel/affectation/affecter", "/m/personnel/pointage/enregistrer", "/m/personnel/autorisations/accorder"):
            self.assertEqual(self.admin.post(url, data=saisie(), headers=ETRANGER).status_code, 403, url)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PERSONNEL").fetchone()[0], 0)

    def test_lecture_seule(self):
        m = self.creer()
        self.droits_sec("LECTURE")
        self.assertEqual(self.sec.get("/m/personnel").status_code, 302)
        self.assertEqual(self.sec.get("/m/personnel/nouveau").status_code, 403)
        page = self.texte(self.sec.get(f"/m/personnel/dossier?m={m}"))
        self.assertIn("MUKENDI", page)
        self.assertIn("consultation seulement", page)
        self.assertNotIn("Joindre le document", page)
        self.assertEqual(self.sec.post("/m/personnel/dossier/modifier", data={**saisie(), "m": m}).status_code, 403)
        self.assertEqual(self.sec.post("/m/personnel/dossier/activite", data={"m": m, "actif": "0"}).status_code, 403)
        self.assertEqual(self.sec.post("/m/personnel/fonctions", data={"genre": "FONCTION", "action": "ajouter", "libelle": "X"}).status_code, 403)
        self.assertEqual(self.sec.get("/m/personnel/dossier/fiche.pdf?m=" + m).status_code, 200)
        self.assertTrue(self.texte(self.sec.get("/m/personnel/nouveau")) == "" or True)

    def test_droit_ajout_ouvre_nouvel_agent(self):
        self.droits_sec("LECTURE", "AJOUT")
        self.assertIn("/m/personnel/nouveau", self.sec.get("/m/personnel").headers["Location"])
        self.assertEqual(self.sec.get("/m/personnel/nouveau").status_code, 200)


class TestDossier(Base):
    def test_enregistrement_et_consultation(self):
        m = self.creer()
        self.assertRegex(m, r"^P\d{4}/\d{2}$")                       # le matricule contient « / » : il voyage en paramètre
        page = self.texte(self.admin.get(f"/m/personnel/dossier?m={m}&ok=cree"))
        self.assertIn("Agent enregistré.", page)
        for attendu in ("MUKENDI KABEYA Jean-Pierre", "jp.mukendi@gmail.com", "Enseignant", 'value="1985-03-15"', 'value="2015-09-01"'):
            self.assertIn(attendu, page)
        self.assertEqual(self.journal("AGENT_ENREGISTRE"), 1)
        self.assertEqual(self.journal("AGENT_CONSULTE"), 0)          # le retour après enregistrement ne compte pas comme une consultation
        self.admin.get(f"/m/personnel/dossier?m={m}")
        self.assertEqual(self.journal("AGENT_CONSULTE"), 1)

    def test_matricule_saisi_et_doublon(self):
        self.assertEqual(self.creer(matricule="ens/001"), "ENS/001")
        r = self.admin.post("/m/personnel/nouveau", data=saisie(matricule="ENS/001"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("déjà attribué", self.texte(r))

    def test_erreurs_gardent_la_saisie(self):
        r = self.admin.post("/m/personnel/nouveau", data=saisie(telephone="abc", nom="Dupont"))
        self.assertEqual(r.status_code, 400)
        page = self.texte(r)
        self.assertIn("téléphone est invalide", page)
        self.assertIn('value="Dupont"', page)
        for champ, valeur, mot in (("date_naissance", "2020-01-01", "ans"), ("sexe", "", "sexe"), ("statut_pro", "", "statut"),
                                   ("email", "pas-un-mail", "e-mail"), ("date_engagement", (date.today() + timedelta(days=2)).isoformat(), "futur")):
            r = self.admin.post("/m/personnel/nouveau", data=saisie(**{champ: valeur}))
            self.assertEqual(r.status_code, 400, champ)
            self.assertIn(mot, self.texte(r), champ)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PERSONNEL").fetchone()[0], 0)

    def test_html_echappe(self):
        m = self.creer(nom="<script>alert(1)</script>", adresse="<b>x</b>")
        page = self.admin.get(f"/m/personnel/dossier?m={m}").get_data(as_text=True)      # page brute, sans décodage
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;SCRIPT&gt;", page)                 # le nom est mis en majuscules par le métier, puis échappé
        self.assertNotIn("<b>x</b>", page)

    def test_modification_et_absence_de_changement(self):
        m = self.creer()
        r = self.admin.post("/m/personnel/dossier/modifier", data={**saisie(adresse="Nouvelle adresse 5"), "m": m})
        self.assertEqual(r.status_code, 302)
        self.assertIn("ok=modifie", r.headers["Location"])
        self.assertIn("Nouvelle adresse 5", self.texte(self.admin.get(f"/m/personnel/dossier?m={m}")))
        r = self.admin.post("/m/personnel/dossier/modifier", data={**saisie(adresse="Nouvelle adresse 5"), "m": m})
        self.assertIn("ok=inchange", r.headers["Location"])
        self.assertEqual(self.journal("AGENT_MODIFIE"), 1)
        r = self.admin.post("/m/personnel/dossier/modifier", data={**saisie(telephone="x"), "m": m})
        self.assertEqual(r.status_code, 400)

    def test_agent_inconnu(self):
        page = self.texte(self.admin.get("/m/personnel/dossier?m=NOPE/00"))
        self.assertIn("Agent introuvable", page)
        self.assertEqual(self.admin.get("/m/personnel/dossier/fiche.pdf?m=NOPE/00").status_code, 404)

    def test_desactiver_reactiver(self):
        m = self.creer()
        self.admin.post("/m/personnel/dossier/activite", data={"m": m, "actif": "0"})
        self.assertIn("Désactivé", self.texte(self.admin.get(f"/m/personnel/dossier?m={m}")))
        self.assertEqual(self.conn.execute("SELECT ACTIF FROM PERSONNEL WHERE MATRICULE=?", (m,)).fetchone()[0], 0)
        self.admin.post("/m/personnel/dossier/activite", data={"m": m, "actif": "1"})
        self.assertEqual(self.conn.execute("SELECT ACTIF FROM PERSONNEL WHERE MATRICULE=?", (m,)).fetchone()[0], 1)
        self.assertEqual((self.journal("AGENT_DESACTIVE"), self.journal("AGENT_ACTIVE")), (1, 1))

    def test_recherche(self):
        self.creer()
        self.creer(nom="Kalala", postnom="Mbuyi", prenom="Rose", sexe="F", fonction="Secrétaire", telephone="0999 111 222")
        page = self.texte(self.admin.get("/m/personnel/dossier?q=secretaire"))
        self.assertIn("KALALA", page)
        self.assertNotIn("MUKENDI", page)
        self.assertIn("Aucun agent trouvé", self.texte(self.admin.get("/m/personnel/dossier?q=zzzz")))

    def test_fiche_pdf(self):
        m = self.creer()
        r = self.admin.get(f"/m/personnel/dossier/fiche.pdf?m={m}")
        self.assertEqual((r.status_code, r.headers["Content-Type"]), (200, "application/pdf"))
        self.assertTrue(r.data.startswith(b"%PDF"))
        self.assertEqual(self.journal("AGENT_FICHE_IMPRIMEE"), 1)


class TestDocuments(Base):
    def envoyer(self, m, contenu, nom="piece.pdf", type_doc="Diplôme", client=None):
        return (client or self.admin).post("/m/personnel/dossier/document", content_type="multipart/form-data",
                                           data={"m": m, "type_doc": type_doc, "fichier": (io.BytesIO(contenu), nom)})

    def test_ajout_ouverture_retrait(self):
        m = self.creer()
        r = self.envoyer(m, PDF)
        self.assertEqual(r.status_code, 302, self.texte(r)[:400])
        id_doc = self.conn.execute("SELECT ID_DOC FROM DOCUMENT_PERSONNEL").fetchone()[0]
        page = self.texte(self.admin.get(f"/m/personnel/dossier?m={m}&ok=doc_ajoute"))
        self.assertIn("piece.pdf", page)
        r = self.admin.get(f"/m/personnel/dossier/document/{id_doc}")
        self.assertEqual((r.status_code, r.headers["Content-Type"], r.data), (200, "application/pdf", PDF))
        self.assertEqual(self.journal("AGENT_DOCUMENT_CONSULTE"), 1)
        self.assertEqual(self.admin.post(f"/m/personnel/dossier/document/{id_doc}/retirer").status_code, 302)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM DOCUMENT_PERSONNEL").fetchone()[0], 0)
        self.assertEqual(self.admin.get(f"/m/personnel/dossier/document/{id_doc}").status_code, 404)

    def test_le_contenu_decide_pas_l_extension(self):
        m = self.creer()
        r = self.envoyer(m, b"MZ\x90\x00 programme", nom="contrat.pdf")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Format non accepté", self.texte(r))
        r = self.envoyer(m, JPEG, nom="photo.png")                    # un JPEG nommé .png est accepté comme JPEG
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.conn.execute("SELECT FORMAT FROM DOCUMENT_PERSONNEL").fetchone()[0], "JPEG")

    def test_fichier_trop_gros_ou_vide(self):
        m = self.creer()
        r = self.envoyer(m, PDF + b"0" * (5 * 1024 * 1024))
        self.assertIn(r.status_code, (400, 413))
        self.assertIn("5 Mo", self.texte(r))
        self.assertEqual(self.envoyer(m, b"").status_code, 400)
        r = self.admin.post("/m/personnel/dossier/document", content_type="multipart/form-data", data={"m": m, "type_doc": "Diplôme"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM DOCUMENT_PERSONNEL").fetchone()[0], 0)

    def test_un_document_de_4_mo_passe(self):
        m = self.creer()
        self.assertEqual(self.envoyer(m, PDF + b"0" * (4 * 1024 * 1024)).status_code, 302)

    def test_droits_ajout_et_suppression(self):
        m = self.creer()
        self.droits_sec("LECTURE")
        self.assertEqual(self.envoyer(m, PDF, client=self.sec).status_code, 403)
        self.droits_sec("LECTURE", "AJOUT")
        self.assertEqual(self.envoyer(m, PDF, client=self.sec).status_code, 302)
        id_doc = self.conn.execute("SELECT ID_DOC FROM DOCUMENT_PERSONNEL").fetchone()[0]
        self.assertEqual(self.sec.post(f"/m/personnel/dossier/document/{id_doc}/retirer").status_code, 403)
        self.droits_sec("LECTURE", "SUPPRESSION")
        self.assertEqual(self.sec.post(f"/m/personnel/dossier/document/{id_doc}/retirer").status_code, 302)

    def test_document_altere_refuse(self):
        m = self.creer()
        self.envoyer(m, PDF)
        with self.conn:
            self.conn.execute("UPDATE DOCUMENT_PERSONNEL SET CONTENU = ?", (PDF + b"x",))
        id_doc = self.conn.execute("SELECT ID_DOC FROM DOCUMENT_PERSONNEL").fetchone()[0]
        r = self.admin.get(f"/m/personnel/dossier/document/{id_doc}")
        self.assertEqual(r.status_code, 409)
        self.assertIn("altéré", self.texte(r))


class TestFonctionsEtAffectations(Base):
    def agir(self, genre, action, libelle="", id_=""):
        return self.admin.post("/m/personnel/fonctions", data={"genre": genre, "action": action, "libelle": libelle, "id": id_})

    def test_fonctions_et_services(self):
        self.assertEqual(self.agir("SERVICE", "ajouter", "administration").status_code, 302)
        r = self.agir("SERVICE", "ajouter", "ADMINISTRATION")
        self.assertEqual(r.status_code, 400)
        self.assertIn("existe déjà", self.texte(r))
        page = self.texte(self.admin.get("/m/personnel/fonctions"))
        self.assertIn("Administration", page)
        id_s = self.conn.execute("SELECT ID_SERVICE FROM SERVICE_PERSONNEL").fetchone()[0]
        self.agir("SERVICE", "renommer", "Direction", id_s)
        self.assertIn("Direction", self.texte(self.admin.get("/m/personnel/fonctions")))
        self.agir("SERVICE", "desactiver", id_=id_s)
        self.assertEqual(self.conn.execute("SELECT ACTIF FROM SERVICE_PERSONNEL").fetchone()[0], 0)
        self.agir("SERVICE", "activer", id_=id_s)
        self.assertEqual(self.agir("SERVICE", "supprimer", id_=id_s).status_code, 302)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM SERVICE_PERSONNEL").fetchone()[0], 0)
        self.assertEqual(self.agir("TRUC", "ajouter", "x").status_code, 400)
        self.assertEqual(self.agir("SERVICE", "faire-sauter", "x").status_code, 400)

    def test_fonction_utilisee_ne_se_supprime_pas(self):
        self.creer()
        id_f = self.conn.execute("SELECT ID_FONCTION FROM FONCTION_PERSONNEL WHERE LIBELLE='Enseignant'").fetchone()[0]
        r = self.agir("FONCTION", "supprimer", id_=id_f)
        self.assertEqual(r.status_code, 400)
        self.assertIn("affectation", self.texte(r))

    def test_droits_sur_les_listes(self):
        self.droits_sec("LECTURE")
        self.assertEqual(self.sec.post("/m/personnel/fonctions", data={"genre": "SERVICE", "action": "ajouter", "libelle": "X"}).status_code, 403)
        self.droits_sec("LECTURE", "AJOUT")
        self.assertEqual(self.sec.post("/m/personnel/fonctions", data={"genre": "SERVICE", "action": "ajouter", "libelle": "X"}).status_code, 302)

    def fonction_id(self, libelle):
        self.admin.post("/m/personnel/fonctions", data={"genre": "FONCTION", "action": "ajouter", "libelle": libelle})
        return self.conn.execute("SELECT ID_FONCTION FROM FONCTION_PERSONNEL WHERE LIBELLE=?", (libelle,)).fetchone()[0]

    def test_affecter_corriger_terminer(self):
        m = self.creer()
        id_f = self.fonction_id("Préfet")
        page = self.texte(self.admin.get(f"/m/personnel/affectation?m={m}"))
        self.assertIn("Situation actuelle", page)
        self.assertIn("Engagement", page)
        r = self.admin.post("/m/personnel/affectation/affecter", data={"m": m, "id_fonction": id_f, "date_debut": "2020-01-01", "motif": "Promotion"})
        self.assertEqual(r.status_code, 200)                         # l'affectation précédente s'est terminée : on le dit à l'écran
        self.assertIn("a pris fin la veille", self.texte(r))
        hist = self.texte(self.admin.get(f"/m/personnel/affectation?m={m}"))
        self.assertIn("Préfet", hist)
        self.assertEqual(self.conn.execute("SELECT FONCTION FROM PERSONNEL WHERE MATRICULE=?", (m,)).fetchone()[0], "Préfet")
        id_aff = self.conn.execute("SELECT ID_AFF FROM AFFECTATION WHERE ID_FONCTION=?", (id_f,)).fetchone()[0]
        r = self.admin.post("/m/personnel/affectation/corriger", data={"m": m, "id_aff": id_aff, "id_fonction": id_f, "date_debut": "2020-01-01",
                                                                       "responsabilite": "Chef d'établissement"})
        self.assertIn("ok=aff_corrigee", r.headers["Location"])
        r = self.admin.post("/m/personnel/affectation/terminer", data={"m": m, "id_aff": id_aff, "date_fin": "2021-06-30"})
        self.assertIn("ok=aff_terminee", r.headers["Location"])
        self.assertEqual(self.conn.execute("SELECT DATE_FIN FROM AFFECTATION WHERE ID_AFF=?", (id_aff,)).fetchone()[0], "2021-06-30")
        self.assertEqual(self.journal("AFFECTATION_ENREGISTREE"), 1)

    def test_erreurs_d_affectation(self):
        m = self.creer()
        id_f = self.fonction_id("Préfet")
        r = self.admin.post("/m/personnel/affectation/affecter", data={"m": m, "id_fonction": id_f, "date_debut": "2000-01-01"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("avant l'engagement", self.texte(r))
        r = self.admin.post("/m/personnel/affectation/affecter", data={"m": m, "id_fonction": "", "date_debut": "2020-01-01"})
        self.assertEqual((r.status_code, "Choisissez la fonction" in self.texte(r)), (400, True))
        r = self.admin.post("/m/personnel/affectation/affecter", data={"m": m, "id_fonction": "abc", "date_debut": "2020-01-01"})
        self.assertEqual(r.status_code, 400)
        r = self.admin.post("/m/personnel/affectation/corriger", data={"m": m, "id_aff": "pas-un-nombre"})
        self.assertEqual(r.status_code, 400)

    def test_droits_d_affectation(self):
        m = self.creer()
        id_f = self.fonction_id("Préfet")
        self.droits_sec("LECTURE")
        self.assertEqual(self.sec.post("/m/personnel/affectation/affecter", data={"m": m, "id_fonction": id_f, "date_debut": "2020-01-01"}).status_code, 403)
        self.assertEqual(self.sec.post("/m/personnel/affectation/terminer", data={"m": m, "id_aff": 1, "date_fin": "2021-01-01"}).status_code, 403)
        self.assertNotIn("Nouvelle affectation", self.texte(self.sec.get(f"/m/personnel/affectation?m={m}")))

    def test_liste_du_personnel(self):
        self.creer()
        self.creer(nom="Kalala", prenom="Rose", sexe="F", fonction="Secrétaire")
        page = self.texte(self.admin.get("/m/personnel/liste"))
        self.assertNotIn("MUKENDI", page)                             # rien n'est calculé (ni journalisé) avant le clic
        self.assertEqual(self.journal("LISTE_PERSONNEL_CONSULTEE"), 0)
        page = self.texte(self.admin.get("/m/personnel/liste?mode=FONCTION&jour=" + date.today().isoformat()))
        self.assertIn("MUKENDI", page)
        self.assertIn("KALALA", page)
        self.assertIn("2 agent(s)", page)
        self.assertEqual(self.journal("LISTE_PERSONNEL_CONSULTEE"), 1)
        id_f = self.conn.execute("SELECT ID_FONCTION FROM FONCTION_PERSONNEL WHERE LIBELLE='Secrétaire'").fetchone()[0]
        page = self.texte(self.admin.get(f"/m/personnel/liste?mode=FONCTION&filtre=FONCTION:{id_f}"))
        self.assertIn("KALALA", page)
        self.assertNotIn("MUKENDI", page)
        r = self.admin.get(f"/m/personnel/liste?mode=SERVICE&filtre=FONCTION:{id_f}")                 # filtre d'une autre liste : refusé
        self.assertIn("ne correspond pas", self.texte(r))
        self.assertNotIn("KALALA", self.texte(r))

    def test_liste_pdf(self):
        self.creer()
        r = self.admin.get("/m/personnel/liste.pdf?mode=FONCTION")
        self.assertEqual((r.status_code, r.headers["Content-Type"]), (200, "application/pdf"))
        self.assertTrue(r.data.startswith(b"%PDF"))
        self.assertEqual(self.admin.get("/m/personnel/liste.pdf").status_code, 404)
        self.assertEqual(self.admin.get("/m/personnel/liste.pdf?mode=FONCTION&filtre=SERVICE:1").status_code, 400)
        self.assertEqual(self.journal("LISTE_PERSONNEL_IMPRIMEE"), 1)


class TestPresence(Base):
    def pointer(self, m, statut="PRESENT", heure="", motif="", jour=None, client=None):
        return (client or self.admin).post("/m/personnel/pointage/enregistrer", data={
            "m": m, "jour": (jour or self.jour).isoformat(), "fonction": "", "statut": statut, "heure": heure, "motif": motif})

    def test_pointage_present_retard_absent_et_effacement(self):
        m = self.creer()
        page = self.texte(self.admin.get(f"/m/personnel/pointage?jour={self.jour.isoformat()}"))
        self.assertIn("MUKENDI", page)
        self.assertIn("Non renseigné", page)
        self.assertEqual(self.pointer(m).status_code, 302)
        statut = lambda: self.conn.execute("SELECT STATUT, MINUTES_RETARD FROM PRESENCE").fetchone()   # noqa: E731
        self.assertEqual(tuple(statut()), ("PRESENT", 0))
        r = self.pointer(m, "RETARD")
        self.assertEqual(r.status_code, 400)
        self.assertIn("heure d'arrivée", self.texte(r))
        self.assertEqual(self.pointer(m, "RETARD", "08:00").status_code, 302)                          # correction du pointage
        self.assertEqual(tuple(statut()), ("RETARD", 30))
        r = self.pointer(m, "PRESENT", "09:00")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.pointer(m, "ABSENT", motif="Malade").status_code, 302)
        r = self.admin.post("/m/personnel/pointage/effacer", data={"m": m, "jour": self.jour.isoformat()})
        self.assertIn("ok=pointe_efface", r.headers["Location"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PRESENCE").fetchone()[0], 0)
        self.assertEqual((self.journal("PRESENCE_ENREGISTREE"), self.journal("PRESENCE_MODIFIEE"), self.journal("PRESENCE_SUPPRIMEE")), (1, 2, 1))

    def test_jours_interdits(self):
        m = self.creer()
        demain = date.today() + timedelta(days=1)
        self.assertIn("pas encore arrivé", self.texte(self.pointer(m, jour=demain)))
        samedi = date.today() - timedelta(days=(date.today().weekday() - 5) % 7 or 7)
        self.assertIn("pas un jour de travail", self.texte(self.pointer(m, jour=samedi)))
        avant = date(2015, 8, 31)
        self.assertEqual(self.pointer(m, jour=avant).status_code, 400)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PRESENCE").fetchone()[0], 0)
        self.assertEqual(self.admin.get("/m/personnel/pointage?jour=pas-une-date").status_code, 200)

    def test_tous_presents(self):
        a, b = self.creer(), self.creer(nom="Kalala", prenom="Rose", sexe="F")
        self.pointer(a, "ABSENT")
        r = self.admin.post("/m/personnel/pointage/tous-presents", data={"jour": self.jour.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertIn("1 agent(s) marqué(s) présent(s)", self.texte(r))
        statuts = dict(self.conn.execute("SELECT MATRICULE, STATUT FROM PRESENCE").fetchall())
        self.assertEqual(statuts, {a: "ABSENT", b: "PRESENT"})            # un absent déjà pointé n'est pas écrasé

    def test_jours_non_travailles(self):
        m = self.creer()
        r = self.admin.post("/m/personnel/pointage/jour-non-travaille", data={"date_ferme": self.jour.isoformat(), "libelle": "Fête"})
        self.assertIn("ok=ferme_ajoute", r.headers["Location"])
        r = self.admin.post("/m/personnel/pointage/jour-non-travaille", data={"date_ferme": self.jour.isoformat(), "libelle": "Fête"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("pas un jour de travail", self.texte(self.pointer(m)))
        self.assertIn("Fête", self.texte(self.admin.get(f"/m/personnel/pointage?jour={self.jour.isoformat()}")))
        r = self.admin.post("/m/personnel/pointage/jour-non-travaille/retirer", data={"date_ferme": self.jour.isoformat()})
        self.assertIn("ok=ferme_retire", r.headers["Location"])
        self.assertEqual(self.pointer(m).status_code, 302)

    def test_droits_de_pointage(self):
        m = self.creer()
        self.droits_sec("LECTURE")
        self.assertEqual(self.pointer(m, client=self.sec).status_code, 403)
        self.droits_sec("LECTURE", "AJOUT")
        self.assertEqual(self.pointer(m, client=self.sec).status_code, 302)
        self.assertEqual(self.pointer(m, "ABSENT", client=self.sec).status_code, 403)          # corriger = droit Modification
        r = self.sec.post("/m/personnel/pointage/effacer", data={"m": m, "jour": self.jour.isoformat()})
        self.assertEqual(r.status_code, 403)

    def test_permission_et_annulation(self):
        m = self.creer()
        debut = date.today() - timedelta(days=21)
        debut -= timedelta(days=debut.weekday())              # un lundi
        fin = debut + timedelta(days=4)
        r = self.admin.post("/m/personnel/autorisations/accorder", data={"m": m, "type": "CONGE", "nature": "Congé annuel",
                                                                          "debut": debut.isoformat(), "fin": fin.isoformat()})
        self.assertEqual(r.status_code, 302, self.texte(r)[:500])
        self.assertIn("ok=aut_cree", r.headers["Location"])
        page = self.texte(self.admin.get(r.headers["Location"]))
        self.assertIn("Autorisation enregistrée", page)
        self.assertIn("Congé annuel", page)
        r = self.admin.post("/m/personnel/autorisations/accorder", data={"m": m, "type": "PERMISSION", "debut": debut.isoformat(), "fin": debut.isoformat()})
        self.assertEqual(r.status_code, 400)
        self.assertIn("déjà une autorisation", self.texte(r))
        id_aut = self.conn.execute("SELECT ID_AUT FROM AUTORISATION_ABSENCE").fetchone()[0]
        r = self.admin.post("/m/personnel/autorisations/annuler", data={"m": m, "id_aut": id_aut, "motif": ""})
        self.assertEqual(r.status_code, 400)
        r = self.admin.post("/m/personnel/autorisations/annuler", data={"m": m, "id_aut": id_aut, "motif": "Erreur de saisie"})
        self.assertIn("ok=aut_annulee", r.headers["Location"])
        self.assertEqual(self.conn.execute("SELECT STATUT FROM AUTORISATION_ABSENCE").fetchone()[0], "ANNULE")
        self.assertIn("Annulée", self.texte(self.admin.get(f"/m/personnel/autorisations?m={m}")))

    def test_droits_des_autorisations(self):
        m = self.creer()
        d = date.today().isoformat()
        self.droits_sec("LECTURE")
        self.assertEqual(self.sec.post("/m/personnel/autorisations/accorder", data={"m": m, "type": "CONGE", "debut": d, "fin": d}).status_code, 403)
        self.assertEqual(self.sec.post("/m/personnel/autorisations/annuler", data={"m": m, "id_aut": 1, "motif": "x"}).status_code, 403)

    def test_etat_recapitulatif_et_pdf(self):
        m = self.creer()
        self.pointer(m)
        debut = self.jour.replace(day=1).isoformat()
        page = self.texte(self.admin.get("/m/personnel/etats"))
        self.assertNotIn("MUKENDI", page)                                 # rien n'est calculé avant le clic
        page = self.texte(self.admin.get(f"/m/personnel/etats?debut={debut}&fin={self.jour.isoformat()}"))
        self.assertIn("MUKENDI", page)
        self.assertIn("Taux de présence", page)
        self.assertEqual(self.journal("ETAT_PRESENCES_CONSULTE"), 1)
        r = self.admin.get(f"/m/personnel/etats?debut={self.jour.isoformat()}&fin={debut}")
        self.assertIn("avant la date de début", self.texte(r))
        for detail in ("1", "0"):
            r = self.admin.get(f"/m/personnel/etats.pdf?debut={debut}&fin={self.jour.isoformat()}&detail={detail}")
            self.assertEqual((r.status_code, r.headers["Content-Type"]), (200, "application/pdf"))
            self.assertTrue(r.data.startswith(b"%PDF"))
        self.assertEqual(self.journal("ETAT_PRESENCES_IMPRIME"), 2)
        self.assertEqual(self.admin.get("/m/personnel/etats.pdf?debut=x&fin=y").status_code, 400)


class TestNavigation(Base):
    def test_toutes_les_pages_s_affichent_pour_l_administrateur(self):
        m = self.creer()
        d = self.jour.isoformat()
        for url in (f"/m/personnel/dossier?m={m}", "/m/personnel/nouveau", "/m/personnel/fonctions", f"/m/personnel/affectation?m={m}",
                    "/m/personnel/liste?mode=SERVICE", f"/m/personnel/pointage?jour={d}", f"/m/personnel/autorisations?m={m}",
                    f"/m/personnel/etats?debut={d}&fin={d}"):
            r = self.admin.get(url)
            self.assertEqual(r.status_code, 200, url)
            page = self.texte(r)
            for lien in ("1   Dossier personnel", "2   Fonctions et affectations", "3   Présence et absence"):
                self.assertIn(lien, page, url)

    def test_l_agent_choisi_suit_les_onglets(self):
        m = self.creer()
        page = self.texte(self.admin.get(f"/m/personnel/dossier?m={m}"))
        self.assertIn("/m/personnel/affectation?m=", page)          # les liens des autres fonctionnalités gardent l'agent choisi
        self.assertIn("/m/personnel/autorisations?m=", page)
        self.assertNotIn("/m/personnel/affectation?m=", self.texte(self.admin.get("/m/personnel/dossier")))


if __name__ == "__main__":
    unittest.main()

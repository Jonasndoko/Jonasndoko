"""Tests du module Carte en ligne (web_carte.py) : droits, sections, fiche, QR, photo (envoi, remplacement, retrait), PDF, journal.
Lancer :  python -m unittest test_carte_web"""
import io
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web         # noqa: E402
import camera          # noqa: E402
import database        # noqa: E402
import demo            # noqa: E402
import droits          # noqa: E402
import security        # noqa: E402

MDP = "Tr@vail-Amour-2026"


def jpeg():
    if camera.disponible():
        import numpy as np
        return camera.photo_vers_jpeg(np.full((480, 640, 3), 180, np.uint8))
    return b"\xff\xd8\xff\xe0" + b"\x00" * 200 + b"\xff\xd9"


class Base(unittest.TestCase):
    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "c.db")
        self.conn = database.connecter(self.chemin)
        demo.semer(self.conn)
        security.creer_utilisateur(self.conn, "admin1", "Alice Directrice", "ADMINISTRATEUR", MDP)
        security.creer_utilisateur(self.conn, "sec1", "Sophie Secrétaire", "SECRETAIRE", MDP)
        self.id_sec = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN='sec1'").fetchone()[0]
        self.app = app_web.creer_app(self.chemin)
        self.admin, self.sec = self.app.test_client(), self.app.test_client()
        for c, l in ((self.admin, "admin1"), (self.sec, "sec1")):
            self.assertEqual(c.post("/connexion", data={"login": l, "mdp": MDP}).status_code, 302)
        # CSF-0002 : 3ème année / 1ère Pédagogie (secondaire) ; CSF-0001 : 8ème (1ère année : voir test des sections)
        self.sec_ok = "CSF-0002"

    def droits_sec(self, *liste):
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_sec, {("carte", d) for d in liste})

    def envoyer(self, client, mat, contenu=None, nom="photo.jpg"):
        return client.post(f"/m/carte/eleve/{mat}/photo", data={"photo": (io.BytesIO(contenu if contenu is not None else jpeg()), nom)},
                           content_type="multipart/form-data")

    def journal(self, action):
        return self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE ACTION = ?", (action,)).fetchone()[0]


class TestAcces(Base):
    def test_non_connecte(self):
        for url in ("/m/carte", "/m/carte/eleve/CSF-0002", "/m/carte/eleve/CSF-0002/pdf", "/m/carte/eleve/CSF-0002/photo.jpg"):
            self.assertEqual(self.app.test_client().get(url).status_code, 302, url)
        self.assertEqual(self.app.test_client().post("/m/carte/eleve/CSF-0002/photo").status_code, 302)

    def test_sans_droit_lecture_403(self):
        self.droits_sec()
        for url in ("/m/carte", "/m/carte/eleve/CSF-0002", "/m/carte/eleve/CSF-0002/pdf"):
            self.assertEqual(self.sec.get(url).status_code, 403, url)

    def test_menu_marque_le_module_en_ligne(self):
        import re
        page = self.admin.get("/menu").get_data(as_text=True)
        tuile = re.search(r'<a class="entree" href="/m/carte"[^>]*>(.*?)</a>', page, re.S).group(1)
        self.assertNotIn("bientôt", tuile)

    def test_eleve_inconnu_404(self):
        self.assertEqual(self.admin.get("/m/carte/eleve/NOPE").status_code, 404)


class TestFiche(Base):
    def test_recherche_et_fiche(self):
        r = self.admin.get("/m/carte?q=ngoy")
        self.assertEqual(r.status_code, 302)                      # un seul résultat : direct sur la fiche
        self.assertIn("/m/carte/eleve/CSF-0002", r.headers["Location"])
        page = self.admin.get("/m/carte/eleve/CSF-0002").get_data(as_text=True)
        for t in ("NGOY", "Lubumbashi", "<svg", "Aucune photo", "IMPRIMER LA CARTE"):
            self.assertIn(t, page)
        self.assertEqual(self.journal("FICHE_CARTE_CONSULTEE"), 1)

    def test_recherche_trop_courte_et_introuvable(self):
        self.assertIn("au moins 2", self.admin.get("/m/carte?q=a").get_data(as_text=True))
        self.assertIn("Aucun élève", self.admin.get("/m/carte?q=zzzzzz").get_data(as_text=True))


class TestPhoto(Base):
    def test_envoi_remplacement_retrait(self):
        r = self.envoyer(self.admin, "CSF-0002")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(self.journal("PHOTO_ENREGISTREE"), 1)
        p = self.admin.get("/m/carte/eleve/CSF-0002/photo.jpg")
        self.assertEqual((p.status_code, p.data[:2]), (200, b"\xff\xd8"))
        page = self.admin.get("/m/carte/eleve/CSF-0002?ok=photo").get_data(as_text=True)
        self.assertIn("Photo enregistrée", page)
        self.assertEqual(self.journal("FICHE_CARTE_CONSULTEE"), 0)    # retour après envoi : pas de ligne de plus
        self.assertEqual(self.envoyer(self.admin, "CSF-0002").status_code, 200)
        self.assertEqual(self.journal("PHOTO_REMPLACEE"), 1)
        r = self.admin.post("/m/carte/eleve/CSF-0002/photo/retirer")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.admin.get("/m/carte/eleve/CSF-0002/photo.jpg").status_code, 404)

    def test_refus_fichier_invalide(self):
        r = self.envoyer(self.admin, "CSF-0002", b"%PDF-1.4 pas une image")
        self.assertEqual(r.status_code, 400)
        self.assertIn("JPEG", r.get_json()["erreur"])
        self.assertEqual(self.admin.post("/m/carte/eleve/CSF-0002/photo").status_code, 400)       # aucun fichier
        if camera.disponible():
            self.assertEqual(self.envoyer(self.admin, "CSF-0002", b"\xff\xd8" + b"x" * 500).status_code, 400)   # faux JPEG

    def test_droits_ajout_modification_suppression(self):
        self.droits_sec("LECTURE")
        self.assertEqual(self.envoyer(self.sec, "CSF-0002").status_code, 403)
        self.droits_sec("LECTURE", "AJOUT")
        self.assertEqual(self.envoyer(self.sec, "CSF-0002").status_code, 200)
        self.assertEqual(self.envoyer(self.sec, "CSF-0002").status_code, 403)           # remplacer = Modification
        self.assertEqual(self.sec.post("/m/carte/eleve/CSF-0002/photo/retirer").status_code, 403)
        self.droits_sec("LECTURE", "MODIFICATION", "SUPPRESSION")
        self.assertEqual(self.envoyer(self.sec, "CSF-0002").status_code, 200)
        self.assertEqual(self.sec.post("/m/carte/eleve/CSF-0002/photo/retirer").status_code, 302)

    def test_boutons_selon_les_droits(self):
        self.droits_sec("LECTURE")
        page = self.sec.get("/m/carte/eleve/CSF-0002").get_data(as_text=True)
        self.assertNotIn("Prendre la photo", page)
        self.droits_sec("LECTURE", "AJOUT")
        self.assertIn("Prendre la photo", self.sec.get("/m/carte/eleve/CSF-0002").get_data(as_text=True))

    def test_origine_etrangere_refusee(self):
        r = self.admin.post("/m/carte/eleve/CSF-0002/photo", data={"photo": (io.BytesIO(jpeg()), "p.jpg")},
                            content_type="multipart/form-data", headers={"Origin": "https://pirate.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.admin.post("/m/carte/eleve/CSF-0002/photo/retirer", headers={"Origin": "https://pirate.example"}).status_code, 403)


class TestPdf(Base):
    def test_pdf_a4_et_format_carte(self):
        self.envoyer(self.admin, "CSF-0002")
        for fmt in ("a4", "carte"):
            r = self.admin.get(f"/m/carte/eleve/CSF-0002/pdf?format={fmt}")
            self.assertEqual(r.status_code, 200, fmt)
            self.assertEqual(r.headers["Content-Type"], "application/pdf")
            self.assertTrue(r.data.startswith(b"%PDF"))
        self.assertEqual(self.journal("CARTE_IMPRIMEE"), 2)

    def test_pdf_sans_photo(self):
        self.assertEqual(self.admin.get("/m/carte/eleve/CSF-0002/pdf").status_code, 200)

    def test_eleve_desactive_pas_de_carte(self):
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET ACTIF = 0 WHERE MATRICULE = 'CSF-0002'")
        r = self.admin.get("/m/carte/eleve/CSF-0002/pdf")
        self.assertEqual(r.status_code, 400)
        self.assertIn("désactivé", r.get_data(as_text=True))


class TestSections(Base):
    def test_pas_de_carte_au_primaire(self):
        with self.conn:
            self.conn.execute("UPDATE NIVEAU SET SECTION = 'PRIMAIRE' WHERE CODE_NIVEAU = 'N7'")      # 7ème : classe de CSF-0004
        self.assertEqual(self.admin.get("/m/carte/eleve/CSF-0004").status_code, 403)
        self.assertEqual(self.admin.get("/m/carte/eleve/CSF-0004/pdf").status_code, 403)
        self.assertEqual(self.envoyer(self.admin, "CSF-0004").status_code, 403)
        self.assertEqual(self.admin.get("/m/carte/eleve/CSF-0002").status_code, 200)       # le secondaire reste accessible


if __name__ == "__main__":
    unittest.main()

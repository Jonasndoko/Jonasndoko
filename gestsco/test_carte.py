"""Tests du module Carte : matricule et QR automatiques, nationalité, photo, carte PDF, QR lisible.
Lancer :  python test_carte.py"""
import os
import tempfile
import unittest
from datetime import date

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import acces                      # noqa: E402
import camera                     # noqa: E402
import carte                      # noqa: E402
import config                     # noqa: E402
import database                   # noqa: E402
import donnees                    # noqa: E402
import droits                     # noqa: E402
import identite                   # noqa: E402
import qr                         # noqa: E402
import referentiels as ref        # noqa: E402
import reinitialisation           # noqa: E402
import security                   # noqa: E402

MDP = "Tr@vail-Amour-2026"
AA = f"{date.today().year % 100:02d}"          # année d'inscription sur 2 chiffres (fin du matricule)


def jpeg_de_test():
    """Petite photo JPEG de test (sans OpenCV : en-tête JPEG minimal valide pour les contrôles d'enregistrement)."""
    if camera.disponible():
        import numpy as np
        image = np.full((480, 640, 3), 180, np.uint8)
        return camera.photo_vers_jpeg(image)
    return b"\xff\xd8\xff\xe0" + b"\x00" * 200 + b"\xff\xd9"


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(os.path.join(tempfile.mkdtemp(), "c.db"))
        security.creer_utilisateur(self.conn, "admin1", "Alice Administratrice", "ADMINISTRATEUR", MDP)
        self.admin = security.authentifier(self.conn, "admin1", MDP).session
        security.creer_utilisateur(self.conn, "sec1", "Sophie Secrétaire", "SECRETAIRE", MDP)
        self.sec = security.authentifier(self.conn, "sec1", MDP).session

    def eleve(self, **plus):
        saisie = dict(NOM="Kabila", POSTNOM="Mwamba", PRENOM="Joël", SEXE="M", DATE_NAISSANCE="15/03/2010",
                      LIEU_NAISSANCE="Kinshasa", NATIONALITE="Congolaise", ADRESSE="Av. de la Paix 12, Lemba")
        saisie.update(plus)
        return ref.enregistrer(self.conn, self.admin, "eleves", saisie)[0]


class TestMatriculeEtQr(Base):
    def test_matricule_automatique_dans_l_ordre_d_ajout(self):
        self.assertEqual([self.eleve(NOM="A"), self.eleve(NOM="B"), self.eleve(NOM="C")],
                         [f"0001/{AA}", f"0002/{AA}", f"0003/{AA}"])

    def test_la_numerotation_repart_de_0001_chaque_annee(self):
        with self.conn:
            self.assertEqual(identite.nouveau_matricule(self.conn, date(2026, 10, 1)), "0001/26")
            self.assertEqual(identite.nouveau_matricule(self.conn, date(2026, 11, 5)), "0002/26")
            self.assertEqual(identite.nouveau_matricule(self.conn, date(2027, 1, 4)), "0001/27")
            self.assertEqual(identite.nouveau_matricule(self.conn, date(2026, 12, 1)), "0003/26")
        self.assertEqual(identite.formater_matricule(12, 2026), "0012/26")

    def test_recherche_par_matricule_avec_barre(self):
        m = self.eleve(NOM="Kabila")
        self.assertEqual([r["matricule"] for r in donnees.rechercher_eleves(self.conn, m)], [m])
        self.assertEqual([r["matricule"] for r in donnees.rechercher_eleves(self.conn, "kabila")], [m])

    def test_matricule_utilisable_dans_un_nom_de_fichier(self):
        self.assertEqual(identite.nom_de_fichier("0001/26"), "0001-26")

    def test_matricule_saisi_a_la_main_est_ignore(self):
        cle = ref.enregistrer(self.conn, self.admin, "eleves", {"MATRICULE": "ZZZ", "NOM": "Test"})
        self.assertEqual(cle, (f"0001/{AA}",))

    def test_matricule_jamais_redonne_apres_suppression(self):
        a = self.eleve(NOM="A")
        ref.supprimer(self.conn, self.admin, "eleves", (a,))
        self.assertEqual(self.eleve(NOM="B"), f"0002/{AA}")

    def test_matricule_manuel_existant_est_saute(self):
        self.conn.execute(f"INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('0001/{AA}', 'Ancien')")
        self.assertEqual(self.eleve(NOM="B"), f"0002/{AA}")

    def test_code_qr_unique_et_stable(self):
        a, b = self.eleve(NOM="A"), self.eleve(NOM="B")
        qa = self.conn.execute("SELECT CODE_QR FROM ELEVE WHERE MATRICULE = ?", (a,)).fetchone()[0]
        qb = self.conn.execute("SELECT CODE_QR FROM ELEVE WHERE MATRICULE = ?", (b,)).fetchone()[0]
        self.assertNotEqual(qa, qb)
        self.assertTrue(qa.startswith(f"CSF|{a}|"))
        ref.enregistrer(self.conn, self.admin, "eleves", {"NOM": "Autre nom"}, (a,))        # modifier ne change pas le QR
        self.assertEqual(self.conn.execute("SELECT CODE_QR FROM ELEVE WHERE MATRICULE = ?", (a,)).fetchone()[0], qa)

    def test_qr_attribue_a_un_eleve_cree_sans_lui(self):
        self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('OLD-1', 'Ancien')")
        code = identite.assurer_code_qr(self.conn, "OLD-1")
        self.assertTrue(code.startswith("CSF|OLD-1|"))
        self.assertEqual(identite.assurer_code_qr(self.conn, "OLD-1"), code)

    def test_nationalite_et_adresse_enregistrees(self):
        m = self.eleve()
        ligne = ref.lire(self.conn, self.admin, "eleves", (m,))
        self.assertEqual((ligne["NATIONALITE"], ligne["ADRESSE"], ligne["SEXE"]), ("Congolaise", "Av. de la Paix 12, Lemba", "M"))

    def test_reinitialisation_remet_la_numerotation_a_un(self):
        self.eleve()
        reinitialisation.reinitialiser(self.conn, self.admin, MDP, "REINITIALISER")
        self.assertEqual(self.eleve(NOM="Nouveau"), f"0001/{AA}")


class TestQrLisible(unittest.TestCase):
    def test_qr_decode_par_opencv(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV absent : lecture du QR non vérifiable ici")
        for texte in ("CSF|000001|A1B2C3D4E5F6", "CSF|OLD-1|0123456789AB", "a" * 90):
            m = qr.matrice(texte)
            n = len(m)
            img = np.full(((n + 8) * 6, (n + 8) * 6), 255, np.uint8)
            for i in range(n):
                for j in range(n):
                    if m[i][j]:
                        img[(i + 4) * 6:(i + 5) * 6, (j + 4) * 6:(j + 5) * 6] = 0
            valeur, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
            self.assertEqual(valeur, texte)

    def test_texte_trop_long(self):
        with self.assertRaises(ValueError):
            qr.matrice("x" * 200)


class TestCarte(Base):
    def test_fiche_complete(self):
        m = self.eleve()
        f = carte.fiche(self.conn, self.admin, m)
        self.assertEqual((f["matricule"], f["sexe_txt"], f["nationalite"], f["naissance"]),
                         (m, "Masculin", "Congolaise", "15/03/2010"))
        self.assertEqual(f["adresse"], "Av. de la Paix 12, Lemba")
        self.assertEqual(f["nom_complet"], "Kabila Mwamba Joël")
        self.assertFalse(f["a_photo"])
        self.assertTrue(f["code_qr"].startswith(f"CSF|{m}|"))

    def test_droits(self):
        m = self.eleve()
        with self.assertRaises(PermissionError):
            carte.fiche(self.conn, self.sec, m)
        acces.definir_droits(self.conn, self.admin, self.sec.id_user, {("carte", "LECTURE")})
        carte.fiche(self.conn, self.sec, m)
        with self.assertRaises(PermissionError):
            carte.enregistrer_photo(self.conn, self.sec, m, jpeg_de_test())
        acces.definir_droits(self.conn, self.admin, self.sec.id_user, {("carte", "AJOUT")})
        carte.enregistrer_photo(self.conn, self.sec, m, jpeg_de_test())
        with self.assertRaises(PermissionError):                                # remplacer = Modification
            carte.enregistrer_photo(self.conn, self.sec, m, jpeg_de_test())
        with self.assertRaises(PermissionError):
            carte.supprimer_photo(self.conn, self.sec, m)

    def test_photo(self):
        m = self.eleve()
        self.assertIsNone(carte.lire_photo(self.conn, self.admin, m))
        carte.enregistrer_photo(self.conn, self.admin, m, jpeg_de_test())
        self.assertTrue(carte.a_photo(self.conn, m))
        carte.enregistrer_photo(self.conn, self.admin, m, jpeg_de_test())       # remplacement
        for mauvais in (b"", b"pas une image", b"\xff\xd8" + b"x" * (carte.TAILLE_MAX_PHOTO + 1)):
            with self.assertRaises(carte.ErreurCarte):
                carte.enregistrer_photo(self.conn, self.admin, m, mauvais)
        carte.supprimer_photo(self.conn, self.admin, m)
        with self.assertRaises(carte.ErreurCarte):
            carte.supprimer_photo(self.conn, self.admin, m)
        self.assertEqual(database.verifier_journal(self.conn), (True, None))

    def test_la_photo_suit_l_eleve_a_la_suppression(self):
        m = self.eleve()
        carte.enregistrer_photo(self.conn, self.admin, m, jpeg_de_test())
        ref.supprimer(self.conn, self.admin, "eleves", (m,))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PHOTO_ELEVE").fetchone()[0], 0)

    def test_pdf_a4_et_format_carte(self):
        m = self.eleve()
        carte.enregistrer_photo(self.conn, self.admin, m, jpeg_de_test())
        for a4, pages in ((True, 1), (False, 2)):
            chemin = carte.preparer_carte_pdf(self.conn, self.admin, m, a4=a4)
            with open(chemin, "rb") as f:
                pdf = f.read()
            self.assertTrue(pdf.startswith(b"%PDF-1.4"))
            self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))
            self.assertEqual(pdf.count(b"/Type /Page "), pages)
            if not a4:                                                           # portrait : hauteur > largeur
                self.assertIn(b"/MediaBox [0 0 153.07 242.65]", pdf)
        self.assertIn("CARTE_IMPRIMEE", [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")])

    def test_pdf_sans_photo(self):
        chemin = carte.preparer_carte_pdf(self.conn, self.admin, self.eleve(), a4=False)
        self.assertTrue(os.path.getsize(chemin) > 1000)

    def test_eleve_desactive_non_imprimable(self):
        m = self.eleve()
        ref.changer_etat(self.conn, self.admin, "eleves", (m,), False)
        with self.assertRaises(carte.ErreurCarte):
            carte.preparer_carte_pdf(self.conn, self.admin, m)

    def test_recherche_par_nom(self):
        m = self.eleve()
        self.assertEqual([r["matricule"] for r in donnees.rechercher_eleves(self.conn, "kabila joel")], [m])


class TestCamera(unittest.TestCase):
    def test_zone_portrait(self):
        self.assertEqual(camera.zone_portrait(640, 480), (140, 0, 360, 480))
        x, y, l, h = camera.zone_portrait(300, 600)
        self.assertEqual((l, h * 3), (300, l * 4))

    def test_photo_vers_jpeg(self):
        if not camera.disponible():
            self.skipTest("OpenCV absent")
        import numpy as np
        jpeg = camera.photo_vers_jpeg(np.zeros((480, 640, 3), np.uint8))
        self.assertEqual(jpeg[:2], b"\xff\xd8")
        self.assertLess(len(jpeg), carte.TAILLE_MAX_PHOTO)


class TestDroitsAdmin(Base):
    def test_admin_a_tous_les_droits_carte(self):
        for d in ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION"):
            self.assertTrue(carte.peut(self.conn, self.admin, d))
        self.assertEqual(set(config.MODULES_DROITS["carte"][1]), {"LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION"})


if __name__ == "__main__":
    unittest.main()

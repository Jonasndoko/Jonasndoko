"""Tests de la mise à jour du programme depuis un fichier .csfupd.
Lancer :  python test_miseajour.py"""
import json
import os
import py_compile
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import config                  # noqa: E402
import database                # noqa: E402
import miseajour               # noqa: E402
import security                # noqa: E402

CLE, MDP = "Cle-de-mise-a-jour-2026", "Adm-Test#2026-xyz"
OBLIGATOIRES = ("main.py", "config.py", "database.py", "migrations.py")


def faire_programme(dossier: Path, version, contenu="ancien"):
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "assets").mkdir(exist_ok=True)
    for f in OBLIGATOIRES:
        (dossier / f).write_text(f"# {f} {contenu}\n", encoding="utf-8")
    (dossier / "config.py").write_text(f'VERSION = "{version}"\n# {contenu}\n', encoding="utf-8")
    (dossier / "assets" / "logo.png").write_bytes(contenu.encode())
    (dossier / "LISEZMOI.md").write_text(contenu, encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.prog = self.tmp / "programme"
        faire_programme(self.prog, config.VERSION, "ancien")
        src = self.tmp / "source"
        faire_programme(src, "9.9", "nouveau")
        self.fichier = self.tmp / ("maj" + miseajour.EXTENSION)
        self.manifeste = miseajour.creer_paquet(self.fichier, CLE, dossier=src, structure=99)
        self.conn = database.connecter(":memory:")
        security.creer_utilisateur(self.conn, "admin1", "Administrateur Test", "ADMINISTRATEUR", MDP)
        self.admin = security.authentifier(self.conn, "admin1", MDP).session
        security.creer_utilisateur(self.conn, "perc1", "Percepteur Test", "PERCEPTEUR", "Perc-Test#2026-xyz")
        self.perc = security.authentifier(self.conn, "perc1", "Perc-Test#2026-xyz").session

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lire(self, f):
        return (self.prog / f).read_text(encoding="utf-8")

    def installer(self, **k):
        return miseajour.installer(self.conn, self.admin, self.fichier, k.get("cle", CLE), k.get("mdp", MDP),
                                   dossier_programme=self.prog)

    def journal(self, action):
        return self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE ACTION = ?", (action,)).fetchone()[0]

    def reecrire(self, modifier):
        """Fabrique une variante du fichier de mise à jour : modifier(dict nom -> octets) puis réécriture de l'archive."""
        with zipfile.ZipFile(self.fichier) as z:
            contenu = {i.filename: z.read(i) for i in z.infolist()}
        modifier(contenu)
        with zipfile.ZipFile(self.fichier, "w") as z:
            for n, d in contenu.items():
                z.writestr(n, d)


class TestControle(Base):
    def test_fichier_valide(self):
        m = miseajour.examiner(self.fichier, CLE)
        self.assertEqual(m["version"], "9.9")
        self.assertEqual(m["empreinte"], self.manifeste["empreinte"])
        self.assertEqual(len(m["empreinte"]), 12)
        self.assertGreaterEqual(m["nb_fichiers"], 6)

    def test_mauvaise_cle_refusee(self):
        with self.assertRaisesRegex(miseajour.ErreurMiseAJour, "Clé"):
            miseajour.examiner(self.fichier, "autre-cle-123")

    def test_fichier_modifie_refuse(self):
        self.reecrire(lambda c: c.__setitem__("fichiers/main.py", b"import os; os.system('x')"))
        with self.assertRaisesRegex(miseajour.ErreurMiseAJour, "abîmé ou modifié"):
            miseajour.examiner(self.fichier, CLE)

    def test_manifeste_modifie_refuse(self):
        def m(c):
            man = json.loads(c["manifeste.json"])
            man["version"] = "99.0"
            c["manifeste.json"] = json.dumps(man).encode()
        self.reecrire(m)
        with self.assertRaises(miseajour.ErreurMiseAJour):
            miseajour.examiner(self.fichier, CLE)

    def test_fichier_ajoute_refuse(self):
        self.reecrire(lambda c: c.__setitem__("fichiers/pirate.py", b"print(1)"))
        with self.assertRaisesRegex(miseajour.ErreurMiseAJour, "non annoncés"):
            miseajour.examiner(self.fichier, CLE)

    def test_chemins_dangereux_refuses(self):
        for nom in ("../evil.py", "/etc/x.py", "a/b/c.py", "sous/dossier.py", "C:\\x.py", "..\\x.py", "fichier.exe", "x.bat.sh", "templates/sous/x.html", "autre/x.html"):
            self.assertFalse(miseajour._chemin_sur(nom), nom)
        for nom in ("main.py", "assets/logo.png", "Lancer.bat", "LISEZMOI.md", "templates/page.html"):
            self.assertTrue(miseajour._chemin_sur(nom), nom)

    def test_chemin_dangereux_dans_un_fichier_signe_refuse(self):
        """Même avec la bonne clé (le développeur se trompe), un chemin qui sort du dossier est refusé."""
        src = self.tmp / "source2"
        faire_programme(src, "9.9")
        man = {"application": "x", "version": "9.9", "structure": 1, "date": "d", "sel": "00" * 16,
               "fichiers": {"../evil.py": miseajour._sha256_octets(b"x"), **{f: "0" * 64 for f in OBLIGATOIRES}}}
        man["mac"] = miseajour._cachet(man, CLE)
        with zipfile.ZipFile(self.fichier, "w") as z:
            z.writestr("manifeste.json", json.dumps(man))
            z.writestr("fichiers/../evil.py", b"x")
        with self.assertRaisesRegex(miseajour.ErreurMiseAJour, "non autorisé"):
            miseajour.examiner(self.fichier, CLE)

    def test_archive_illisible_ou_absente(self):
        self.fichier.write_bytes(b"pas une archive")
        with self.assertRaises(miseajour.ErreurMiseAJour):
            miseajour.examiner(self.fichier, CLE)
        with self.assertRaises(miseajour.ErreurMiseAJour):
            miseajour.examiner(self.tmp / "absent.csfupd", CLE)

    def test_cle_trop_courte_pour_creer(self):
        with self.assertRaises(miseajour.ErreurMiseAJour):
            miseajour.creer_paquet(self.tmp / "x.csfupd", "court", dossier=self.prog, structure=1)


class TestInstallation(Base):
    def test_installation_complete(self):
        r = self.installer()
        self.assertEqual((r["ancienne"], r["nouvelle"]), (config.VERSION, "9.9"))
        self.assertIn("nouveau", self.lire("main.py"))
        self.assertEqual((self.prog / "assets" / "logo.png").read_bytes(), b"nouveau")
        self.assertEqual(self.journal("MISE_A_JOUR_PROGRAMME"), 1)
        self.assertTrue(r["securite"].exists())
        self.assertFalse((self.prog / ".maj_en_cours").exists())
        self.assertEqual([f for f in os.listdir(self.prog) if f.endswith(".maj")], [])
        arch = miseajour.lister_archives(self.prog)
        self.assertEqual(len(arch), 1)
        self.assertEqual(arch[0]["version"], config.VERSION)
        self.assertIn("ancien", (self.prog / miseajour.DOSSIER_ARCHIVES / arch[0]["nom"] / "main.py").read_text(encoding="utf-8"))

    def test_les_donnees_ne_sont_pas_dans_les_fichiers_du_programme(self):
        self.assertTrue(config.dossier_donnees() != self.prog)
        self.assertFalse(any(f.endswith((".db", ".csfbak")) for f in miseajour.fichiers_du_programme(self.prog)))

    def test_refus_non_administrateur(self):
        with self.assertRaises(PermissionError):
            miseajour.installer(self.conn, self.perc, self.fichier, CLE, MDP, dossier_programme=self.prog)
        self.assertIn("ancien", self.lire("main.py"))

    def test_mauvais_mot_de_passe_et_mauvaise_cle_journalises(self):
        with self.assertRaisesRegex(miseajour.ErreurMiseAJour, "Mot de passe"):
            self.installer(mdp="faux")
        with self.assertRaisesRegex(miseajour.ErreurMiseAJour, "Clé"):
            self.installer(cle="mauvaise-cle")
        self.assertEqual(self.journal("MISE_A_JOUR_REFUSEE"), 2)
        self.assertIn("ancien", self.lire("main.py"))          # rien n'a bougé
        self.assertEqual(miseajour.lister_archives(self.prog), [])

    def test_version_pas_plus_recente_refusee(self):
        src = self.tmp / "vieux"
        faire_programme(src, "0.1", "vieux")
        miseajour.creer_paquet(self.fichier, CLE, dossier=src, structure=1)
        with self.assertRaisesRegex(miseajour.ErreurMiseAJour, "pas plus récente"):
            self.installer()
        self.assertIn("ancien", self.lire("main.py"))

    def test_echec_en_cours_de_route_remet_la_version_precedente(self):
        vrai = os.replace
        appels = []

        def capricieux(a, b):
            appels.append(b)
            if len(appels) == 3:
                raise OSError("disque plein")
            return vrai(a, b)
        miseajour.os.replace = capricieux
        try:
            with self.assertRaisesRegex(miseajour.ErreurMiseAJour, "version précédente"):
                self.installer()
        finally:
            miseajour.os.replace = vrai
        for f in OBLIGATOIRES + ("LISEZMOI.md",):
            self.assertIn("ancien", self.lire(f), f)
        self.assertEqual((self.prog / "assets" / "logo.png").read_bytes(), b"ancien")
        self.assertEqual(self.journal("MISE_A_JOUR_ECHEC"), 1)
        self.assertEqual(self.journal("MISE_A_JOUR_PROGRAMME"), 0)

    def test_seules_les_3_dernieres_versions_sont_gardees(self):
        for i in range(5):
            src = self.tmp / f"v{i}"
            faire_programme(src, f"9.{i}", f"v{i}")
            miseajour.creer_paquet(self.fichier, CLE, dossier=src, structure=99)
            self.installer()
            # la version installée devient « 0.20 » pour la suivante : on simule en remettant config.VERSION
        self.assertLessEqual(len(miseajour.lister_archives(self.prog)), miseajour.NB_ARCHIVES)


class TestRetour(Base):
    def test_retour_a_l_ancienne_version_et_re_avance(self):
        self.conn.execute("PRAGMA user_version = 5")
        self.installer()                                       # structure gardée de l'ancienne version : 5
        nom = miseajour.lister_archives(self.prog)[0]["nom"]
        r = miseajour.revenir(self.conn, self.admin, nom, MDP, dossier_programme=self.prog)
        self.assertEqual(r["nouvelle"], config.VERSION)
        self.assertIn("ancien", self.lire("main.py"))
        self.assertEqual(self.journal("RETOUR_ANCIENNE_VERSION"), 1)
        self.assertEqual(len(miseajour.lister_archives(self.prog)), 2)    # la version quittée est gardée aussi

    def test_retour_refuse_si_la_base_a_ete_transformee(self):
        self.conn.execute("PRAGMA user_version = 1")
        self.installer()
        self.conn.execute("PRAGMA user_version = 9")           # la nouvelle version a transformé la base
        nom = miseajour.lister_archives(self.prog)[0]["nom"]
        with self.assertRaisesRegex(miseajour.ErreurMiseAJour, "Avant-mise-a-jour"):
            miseajour.revenir(self.conn, self.admin, nom, MDP, dossier_programme=self.prog)
        self.assertIn("nouveau", self.lire("main.py"))

    def test_retour_reserve_a_l_administrateur_avec_mot_de_passe(self):
        self.installer()
        nom = miseajour.lister_archives(self.prog)[0]["nom"]
        with self.assertRaises(PermissionError):
            miseajour.revenir(self.conn, self.perc, nom, MDP, dossier_programme=self.prog)
        with self.assertRaises(miseajour.ErreurMiseAJour):
            miseajour.revenir(self.conn, self.admin, nom, "faux", dossier_programme=self.prog)
        with self.assertRaises(miseajour.ErreurMiseAJour):
            miseajour.revenir(self.conn, self.admin, "inconnue", MDP, dossier_programme=self.prog)


class TestVraiProgramme(unittest.TestCase):
    def test_le_vrai_dossier_donne_un_fichier_valide_et_complet(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            m = miseajour.creer_paquet(tmp / "v.csfupd", CLE)
            self.assertEqual(m["version"], config.VERSION)
            self.assertIn("miseajour.py", m["fichiers"])
            self.assertIn("assets/icone.png", m["fichiers"])
            self.assertIn("Lancer.bat", m["fichiers"])
            self.assertEqual(miseajour.examiner(tmp / "v.csfupd", CLE)["empreinte"], m["empreinte"])
            self.assertFalse(any("ancienne_version" in f or "__pycache__" in f for f in m["fichiers"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_interface_compile(self):
        for f in ("miseajour.py", "ecrans_travaux.py"):
            py_compile.compile(str(Path(__file__).with_name(f)), doraise=True)


if __name__ == "__main__":
    unittest.main()

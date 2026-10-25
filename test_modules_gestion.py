"""Tests du module « Gestion du personnel » (et disparition de « Gestion scolaire ») : présence au menu, droits, accès.
Lancer :  python test_modules_gestion.py"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import config        # noqa: E402
import database      # noqa: E402
import droits        # noqa: E402
import modules       # noqa: E402
import security      # noqa: E402

MDP = "Tr@vail-Amour-2026"
NOUVEAUX = ("personnel",)


class TestModulesGestion(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(os.path.join(tempfile.mkdtemp(), "g.db"))
        security.creer_utilisateur(self.conn, "admin1", "Alice", "ADMINISTRATEUR", MDP)
        self.admin = security.authentifier(self.conn, "admin1", MDP).session
        self.id_sec = security.creer_utilisateur(self.conn, "sec1", "Sophie", "SECRETAIRE", MDP)
        self.sec = security.authentifier(self.conn, "sec1", MDP).session

    def test_les_modules_sont_au_menu(self):
        cles = [m[0] for m in modules.MODULES]
        for k in NOUVEAUX:
            self.assertIn(k, cles)
            self.assertIn(k, config.MODULES_DROITS)
            self.assertEqual(set(config.MODULES_DROITS[k][1]), {"LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION"})

    def test_gestion_scolaire_n_existe_plus(self):
        self.assertNotIn("gestion_scolaire", [m[0] for m in modules.MODULES])
        self.assertNotIn("gestion_scolaire", config.MODULES_DROITS)
        self.assertNotIn("gestion_scolaire", modules.modules_ouverts(self.conn, self.admin))

    def test_l_administrateur_y_a_acces(self):
        ouverts = modules.modules_ouverts(self.conn, self.admin)
        for k in NOUVEAUX:
            self.assertIn(k, ouverts)

    def test_un_compte_sans_droit_n_y_a_pas_acces_puis_oui_avec_lecture(self):
        for k in NOUVEAUX:
            self.assertNotIn(k, modules.modules_ouverts(self.conn, self.sec))
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_sec, {("personnel", "LECTURE")})
        ouverts = modules.modules_ouverts(self.conn, self.sec)
        self.assertIn("personnel", ouverts)
        self.assertEqual(modules.module_direct(self.conn, self.sec), "personnel")

    def test_l_ecran_est_importable_et_les_cles_correspondent(self):
        src = open(os.path.join(os.path.dirname(__file__), "ecrans_gestion.py"), encoding="utf-8").read()
        compile(src, "ecrans_gestion.py", "exec")
        self.assertIn('CLE_DROITS = "presence_eleves"', src)
        self.assertNotIn("ModuleGestionScolaire", src)
        src = open(os.path.join(os.path.dirname(__file__), "ecrans_personnel.py"), encoding="utf-8").read()
        compile(src, "ecrans_personnel.py", "exec")
        self.assertIn("class ModulePersonnel", src)


if __name__ == "__main__":
    unittest.main()

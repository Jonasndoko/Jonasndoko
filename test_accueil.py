"""Tests : arrivée directe dans le module quand le compte n'en a qu'un seul.
Lancer :  python test_accueil.py"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import acces                      # noqa: E402
import database                   # noqa: E402
import droits                     # noqa: E402
import modules                    # noqa: E402
import security                   # noqa: E402

MDP = "Tr@vail-Amour-2026"


def base():
    conn = database.connecter(os.path.join(tempfile.mkdtemp(), "t.db"))
    security.creer_utilisateur(conn, "admin1", "Alice Administratrice", "ADMINISTRATEUR", MDP)
    return conn, security.authentifier(conn, "admin1", MDP).session


def compte(conn, admin, login, role):
    acces.creer_compte(conn, admin, login, login.title(), role)
    ligne = conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = ?", (login,)).fetchone()
    return ligne["ID_USER"]


def session_de(conn, id_user, role):
    class S:                                     # session minimale : seuls id_user et role servent aux droits
        pass
    s = S()
    s.id_user, s.role = id_user, role
    return s


class TestAccueilDirect(unittest.TestCase):
    def setUp(self):
        self.conn, self.admin = base()

    def test_percepteur_un_seul_module_arrive_dans_paiement(self):
        i = compte(self.conn, self.admin, "perc1", "PERCEPTEUR")
        s = session_de(self.conn, i, "PERCEPTEUR")
        self.assertEqual(modules.modules_ouverts(self.conn, s), ["paiement"])
        self.assertEqual(modules.module_direct(self.conn, s), "paiement")
        self.assertFalse(modules.menu_utile(self.conn, s))

    def test_intendant_un_seul_module(self):
        i = compte(self.conn, self.admin, "int1", "INTENDANT")
        s = session_de(self.conn, i, "INTENDANT")
        self.assertEqual(modules.module_direct(self.conn, s), "paiement")

    def test_intendant_avec_encaissement_seul(self):
        i = compte(self.conn, self.admin, "int2", "INTENDANT")
        droits.remplacer_droits(self.conn, i, {("encaissement", "AJOUT")})
        self.conn.commit()
        s = session_de(self.conn, i, "INTENDANT")
        self.assertEqual(modules.module_direct(self.conn, s), "encaissement")

    def test_deux_modules_menu_principal(self):
        i = compte(self.conn, self.admin, "int3", "INTENDANT")
        droits.remplacer_droits(self.conn, i, {("paiement", "LECTURE"), ("encaissement", "LECTURE")})
        self.conn.commit()
        s = session_de(self.conn, i, "INTENDANT")
        self.assertEqual(modules.modules_ouverts(self.conn, s), ["paiement", "encaissement"])
        self.assertIsNone(modules.module_direct(self.conn, s))
        self.assertTrue(modules.menu_utile(self.conn, s))

    def test_aucun_module_menu_principal(self):
        i = compte(self.conn, self.admin, "sec1", "SECRETAIRE")
        s = session_de(self.conn, i, "SECRETAIRE")
        self.assertEqual(modules.modules_ouverts(self.conn, s), ["secretariat"])      # sous-menu « Dossier élève » du Secrétariat
        with self.conn:
            droits.remplacer_droits(self.conn, i, set())
        self.assertEqual(modules.modules_ouverts(self.conn, s), [])
        self.assertIsNone(modules.module_direct(self.conn, s))

    def test_administrateur_garde_le_menu(self):
        self.assertIsNone(modules.module_direct(self.conn, self.admin))
        self.assertEqual(len(modules.modules_ouverts(self.conn, self.admin)), 12)   # + Traçabilité et audit + (Inscription : dans le Secrétariat) + Gestion du personnel + Espace Études + Espace Discipline + Préfecture + Secrétariat

    def test_droits_relus_a_chaque_appel(self):
        i = compte(self.conn, self.admin, "perc2", "PERCEPTEUR")
        s = session_de(self.conn, i, "PERCEPTEUR")
        self.assertEqual(modules.module_direct(self.conn, s), "paiement")
        droits.remplacer_droits(self.conn, i, {("paiement", "LECTURE"), ("carte", "LECTURE")})
        self.conn.commit()
        self.assertIsNone(modules.module_direct(self.conn, s))

    def test_sans_session(self):
        self.assertEqual(modules.modules_ouverts(self.conn, None), [])
        self.assertIsNone(modules.module_direct(self.conn, None))


if __name__ == "__main__":
    unittest.main()

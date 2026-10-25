"""Tests : rôles créés par l'administrateur, poste choisi à la connexion, réinitialisation.
Lancer :  python test_roles_reinit.py"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import acces                      # noqa: E402
import config                     # noqa: E402
import database                   # noqa: E402
import demo                       # noqa: E402
import droits                     # noqa: E402
import reinitialisation           # noqa: E402
import security                   # noqa: E402

MDP = "Tr@vail-Amour-2026"


def base():
    conn = database.connecter(os.path.join(tempfile.mkdtemp(), "t.db"))
    security.creer_utilisateur(conn, "admin1", "Alice Administratrice", "ADMINISTRATEUR", MDP)
    return conn, security.authentifier(conn, "admin1", MDP).session


class TestRolesCrees(unittest.TestCase):
    def setUp(self):
        self.conn, self.admin = base()

    def test_creer_role_et_compte(self):
        code = acces.creer_role(self.conn, self.admin, "Chef de discipline", {("encaissement", "AJOUT")})
        self.assertEqual(code, "CHEF_DE_DISCIPLINE")
        self.assertEqual(droits.roles(self.conn)[code], "Chef de discipline")
        self.assertEqual(droits.droits_par_defaut(self.conn, code),
                         {("encaissement", "AJOUT"), ("encaissement", "LECTURE")})
        id_user, _ = acces.creer_compte(self.conn, self.admin, "chef1", "Jean Chef", code)
        self.assertEqual(droits.droits_utilisateur(self.conn, id_user),
                         {("encaissement", "AJOUT"), ("encaissement", "LECTURE")})

    def test_doublon_et_nom_invalide(self):
        acces.creer_role(self.conn, self.admin, "Bibliothécaire")
        for nom in ("Bibliothécaire", "bibliothecaire", "Préfet", "ab", "!!!"):
            with self.assertRaises(acces.ErreurAcces):
                acces.creer_role(self.conn, self.admin, nom)

    def test_supprimer_role(self):
        code = acces.creer_role(self.conn, self.admin, "Surveillant")
        acces.creer_compte(self.conn, self.admin, "surv1", "Paul Surveillant", code)
        with self.assertRaises(acces.ErreurAcces):                 # encore utilisé
            acces.supprimer_role(self.conn, self.admin, code)
        with self.assertRaises(acces.ErreurAcces):                 # poste de base
            acces.supprimer_role(self.conn, self.admin, "PERCEPTEUR")
        self.conn.execute("DELETE FROM DROIT"); self.conn.execute("DELETE FROM UTILISATEUR WHERE LOGIN='surv1'")
        acces.supprimer_role(self.conn, self.admin, code)
        self.assertNotIn(code, droits.roles(self.conn))

    def test_reserve_a_l_administrateur(self):
        security.creer_utilisateur(self.conn, "sec1", "Sophie Secrétaire", "SECRETAIRE", MDP)
        sec = security.authentifier(self.conn, "sec1", MDP, "SECRETAIRE").session
        with self.assertRaises(PermissionError):
            acces.creer_role(self.conn, sec, "Intrus")

    def test_quatre_droits_sur_les_nouveaux_modules(self):
        for module in ("encaissement", "controle"):
            self.assertEqual(set(config.MODULES_DROITS[module][1]), {"LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION"})


class TestActivationComptes(unittest.TestCase):
    def setUp(self):
        self.conn, self.admin = base()
        self.id_user, _ = acces.creer_compte(self.conn, self.admin, "sec1", "Sophie Secrétaire", "SECRETAIRE")

    def actif(self, id_user):
        return self.conn.execute("SELECT ACTIF FROM UTILISATEUR WHERE ID_USER = ?", (id_user,)).fetchone()[0]

    def test_desactiver_puis_activer(self):
        acces.changer_etat_compte(self.conn, self.admin, self.id_user, False)
        self.assertEqual(self.actif(self.id_user), 0)
        acces.changer_etat_compte(self.conn, self.admin, self.id_user, True)
        self.assertEqual(self.actif(self.id_user), 1)
        actions = [l[0] for l in self.conn.execute("SELECT ACTION FROM JOURNAL WHERE ACTION LIKE 'COMPTE_%ACTIVE'")]
        self.assertEqual(actions, ["COMPTE_DESACTIVE", "COMPTE_ACTIVE"])
        self.assertTrue(database.verifier_journal(self.conn)[0])

    def test_compte_desactive_ne_se_connecte_plus(self):
        id_user, mdp = acces.creer_compte(self.conn, self.admin, "sec2", "Paul Secrétaire", "SECRETAIRE")
        acces.reinitialiser_mdp(self.conn, self.admin, id_user)
        acces.changer_etat_compte(self.conn, self.admin, id_user, False)
        with self.conn:
            self.conn.execute("UPDATE UTILISATEUR SET MDP_HASH = ? WHERE ID_USER = ?",
                              (security.hacher_mdp(MDP), id_user))
        self.assertFalse(security.authentifier(self.conn, "sec2", MDP).ok)
        acces.changer_etat_compte(self.conn, self.admin, id_user, True)
        self.assertTrue(security.authentifier(self.conn, "sec2", MDP).ok)

    def test_garde_fous(self):
        with self.assertRaises(acces.ErreurAcces):                 # soi-même
            acces.changer_etat_compte(self.conn, self.admin, self.admin.id_user, False)
        id_adm2, _ = acces.creer_compte(self.conn, self.admin, "admin2", "Second Admin", config.ADMINISTRATEUR)
        acces.changer_etat_compte(self.conn, self.admin, id_adm2, False)
        with self.assertRaises(acces.ErreurAcces):                 # déjà dans cet état
            acces.changer_etat_compte(self.conn, self.admin, id_adm2, False)
        with self.assertRaises(acces.ErreurAcces):
            acces.changer_etat_compte(self.conn, self.admin, self.id_user, True)
        with self.assertRaises(acces.ErreurAcces):                 # compte inconnu
            acces.changer_etat_compte(self.conn, self.admin, 9999, False)

    def test_reserve_a_l_administrateur(self):
        sec = security.Session(self.id_user, "sec1", "Sophie Secrétaire", "SECRETAIRE")
        with self.assertRaises(PermissionError):
            acces.changer_etat_compte(self.conn, sec, self.id_user, False)


class TestPosteALaConnexion(unittest.TestCase):
    def setUp(self):
        self.conn, self.admin = base()

    def test_bon_poste(self):
        r = security.authentifier(self.conn, "admin1", MDP, "ADMINISTRATEUR")
        self.assertTrue(r.ok)
        self.assertEqual(r.session.libelle_role, config.LIBELLE_ROLES["ADMINISTRATEUR"])

    def test_mauvais_poste_refuse_comme_un_mauvais_mot_de_passe(self):
        r = security.authentifier(self.conn, "admin1", MDP, "SECRETAIRE")
        self.assertFalse(r.ok)
        self.assertEqual(r.message.split("\n")[0], security.MESSAGE_ECHEC)

    def test_libelle_du_role_cree(self):
        code = acces.creer_role(self.conn, self.admin, "Chef de discipline")
        _, mdp = acces.creer_compte(self.conn, self.admin, "chef1", "Jean Chef", code)
        self.conn.execute("UPDATE UTILISATEUR SET MDP_HASH = ? WHERE LOGIN = 'chef1'", (security.hacher_mdp(MDP),))
        r = security.authentifier(self.conn, "chef1", MDP, code)
        self.assertTrue(r.ok)
        self.assertEqual(r.session.libelle_role, "Chef de discipline")


class TestReinitialisation(unittest.TestCase):
    def setUp(self):
        self.conn, self.admin = base()
        demo.semer(self.conn)                                     # des données de test, dans une base temporaire
        self.assertGreater(self.conn.execute("SELECT COUNT(*) FROM ELEVE").fetchone()[0], 0)

    def vide(self):
        return all(n == 0 for n in reinitialisation.apercu(self.conn, self.admin).values())

    def test_efface_les_donnees_scolaires_et_garde_les_comptes(self):
        r = reinitialisation.reinitialiser(self.conn, self.admin, MDP, "reinitialiser")
        self.assertTrue(self.vide())
        self.assertTrue(r["securite"].exists())
        self.assertGreaterEqual(self.conn.execute("SELECT COUNT(*) FROM UTILISATEUR").fetchone()[0], 2)
        self.assertEqual(database.verifier_journal(self.conn), (True, None))
        action = self.conn.execute("SELECT ACTION FROM JOURNAL ORDER BY ID_LOG DESC LIMIT 1").fetchone()[0]
        self.assertEqual(action, "APPLICATION_REINITIALISEE")

    def test_les_recus_restent_proteges_apres(self):
        reinitialisation.reinitialiser(self.conn, self.admin, MDP, "REINITIALISER")
        declencheurs = {l[0] for l in self.conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        self.assertIn("PAIEMENT_NO_DELETE", declencheurs)

    def test_refus_mauvais_mot_de_passe_ou_phrase(self):
        with self.assertRaises(reinitialisation.ErreurReinitialisation):
            reinitialisation.reinitialiser(self.conn, self.admin, "faux", "REINITIALISER")
        with self.assertRaises(reinitialisation.ErreurReinitialisation):
            reinitialisation.reinitialiser(self.conn, self.admin, MDP, "oui")
        self.assertFalse(self.vide())

    def test_reserve_a_l_administrateur(self):
        sec = security.authentifier(self.conn, "percepteur1", self._mdp_perc(), "PERCEPTEUR").session
        with self.assertRaises(PermissionError):
            reinitialisation.reinitialiser(self.conn, sec, MDP, "REINITIALISER")

    def _mdp_perc(self):
        mdp = "Autre-Mdp-2026!x"
        self.conn.execute("UPDATE UTILISATEUR SET MDP_HASH = ? WHERE LOGIN = 'percepteur1'", (security.hacher_mdp(mdp),))
        return mdp

    def test_option_comptes_et_roles(self):
        acces.creer_role(self.conn, self.admin, "Surveillant")
        reinitialisation.reinitialiser(self.conn, self.admin, MDP, "REINITIALISER", comptes_aussi=True)
        logins = [l[0] for l in self.conn.execute("SELECT LOGIN FROM UTILISATEUR")]
        self.assertEqual(logins, ["admin1"])
        self.assertEqual(list(droits.roles(self.conn)), list(config.ROLES))
        self.assertTrue(security.authentifier(self.conn, "admin1", MDP, "ADMINISTRATEUR").ok)


if __name__ == "__main__":
    unittest.main()

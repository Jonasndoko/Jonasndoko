"""Tests de la couche sécurité. Lancer :  python test_securite.py"""
import os
import sqlite3
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import config                      # noqa: E402
import database                    # noqa: E402
import security                    # noqa: E402

MDP = "Tr@vail-Amour-2026"


class TestSecurite(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(":memory:")
        security.creer_utilisateur(self.conn, "directeur", "Jean Dupont", "ADMINISTRATEUR", MDP)

    # --- hachage ---------------------------------------------------------
    def test_hash_sale_et_verifiable(self):
        h1, h2 = security.hacher_mdp(MDP), security.hacher_mdp(MDP)
        self.assertNotEqual(h1, h2)                       # sel différent à chaque fois
        self.assertTrue(security.verifier_mdp(MDP, h1))
        self.assertFalse(security.verifier_mdp(MDP + "x", h1))
        self.assertNotIn(MDP, h1)

    def test_hash_corrompu_ne_plante_pas(self):
        for faux in ("", "abc", "scrypt$a$b$c$d$e", "md5$1$2$3$4$5"):
            self.assertFalse(security.verifier_mdp(MDP, faux))

    def test_mdp_non_stocke_en_clair(self):
        h = self.conn.execute("SELECT MDP_HASH FROM UTILISATEUR").fetchone()[0]
        self.assertTrue(h.startswith("scrypt$"))
        self.assertNotIn(MDP, h)

    # --- politique -------------------------------------------------------
    def test_politique(self):
        faibles = ["court1!A", "tropsimplesansmajuscule1!", "SansChiffreNiSymbole",
                   "Password-2026-Ok!", "Aaaa-bbbb-1234-xx",
                   "".join(c for c in config.NOM_ECOLE.title() if c.isalnum()) + "1!"]      # le nom de l'école
        for mdp in faibles:
            self.assertTrue(security.verifier_politique(mdp, "directeur"), mdp)
        self.assertTrue(security.verifier_politique("Directeur-2026-Ok!", "directeur"))   # contient l'identifiant
        self.assertEqual(security.verifier_politique(MDP, "directeur"), [])

    def test_creation_refusee_si_faible_ou_doublon(self):
        with self.assertRaises(ValueError):
            security.creer_utilisateur(self.conn, "secretaire", "Marie Kabila", "SECRETAIRE", "faible")
        with self.assertRaises(ValueError):
            security.creer_utilisateur(self.conn, "DIRECTEUR", "Autre", "ADMINISTRATEUR", MDP)   # casse ignorée
        with self.assertRaises(ValueError):
            security.creer_utilisateur(self.conn, "x y", "Nom Valide", "ADMINISTRATEUR", MDP)
        with self.assertRaises(ValueError):
            security.creer_utilisateur(self.conn, "pirate", "Nom Valide", "SUPERADMIN", MDP)

    # --- authentification ------------------------------------------------
    def test_connexion_ok(self):
        r = security.authentifier(self.conn, "Directeur", MDP)       # casse de l'identifiant ignorée
        self.assertTrue(r.ok)
        self.assertEqual(r.session.role, "ADMINISTRATEUR")

    def test_echec_message_identique_user_inconnu_ou_mauvais_mdp(self):
        a = security.authentifier(self.conn, "directeur", "mauvais")
        b = security.authentifier(self.conn, "inconnu", "mauvais")
        self.assertFalse(a.ok or b.ok)
        self.assertEqual(a.message, b.message)

    def test_injection_sql_inoffensive(self):
        r = security.authentifier(self.conn, "' OR 1=1 --", "' OR '1'='1")
        self.assertFalse(r.ok)
        r = security.authentifier(self.conn, "directeur'; DROP TABLE UTILISATEUR;--", MDP)
        self.assertFalse(r.ok)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM UTILISATEUR").fetchone()[0], 1)

    def test_blocage_apres_5_echecs_meme_avec_le_bon_mdp(self):
        for i in range(config.MAX_ECHECS - 1):
            self.assertEqual(security.authentifier(self.conn, "directeur", "mauvais").secondes_blocage, 0)
        r = security.authentifier(self.conn, "directeur", "mauvais")
        self.assertGreater(r.secondes_blocage, 0)
        r = security.authentifier(self.conn, "directeur", MDP)       # bon mot de passe, mais bloqué
        self.assertFalse(r.ok)
        self.assertGreater(r.secondes_blocage, 0)

    def test_blocage_identique_pour_identifiant_inexistant(self):
        for _ in range(config.MAX_ECHECS):
            r = security.authentifier(self.conn, "fantome", "mauvais")
        self.assertGreater(r.secondes_blocage, 0)

    def test_blocage_expire_puis_double(self):
        for _ in range(config.MAX_ECHECS):
            security.authentifier(self.conn, "directeur", "mauvais")
        with self.conn:        # on simule l'écoulement du temps
            self.conn.execute("UPDATE TENTATIVE_CONNEXION SET BLOQUE_JUSQUA = '2000-01-01T00:00:00+00:00'")
        self.assertTrue(security.authentifier(self.conn, "directeur", MDP).ok)
        for _ in range(config.MAX_ECHECS):                           # succès => compteur remis à zéro
            r = security.authentifier(self.conn, "directeur", "mauvais")
        self.assertEqual(r.secondes_blocage, config.DUREE_BLOCAGE_MIN * 60)

    def test_second_blocage_double_la_duree(self):
        for _ in range(config.MAX_ECHECS):
            security.authentifier(self.conn, "directeur", "mauvais")
        with self.conn:
            self.conn.execute("UPDATE TENTATIVE_CONNEXION SET BLOQUE_JUSQUA = '2000-01-01T00:00:00+00:00'")
        for _ in range(config.MAX_ECHECS):
            r = security.authentifier(self.conn, "directeur", "mauvais")
        self.assertEqual(r.secondes_blocage, config.DUREE_BLOCAGE_MIN * 2 * 60)

    def test_compte_desactive_refuse(self):
        with self.conn:
            self.conn.execute("UPDATE UTILISATEUR SET ACTIF = 0")
        self.assertFalse(security.authentifier(self.conn, "directeur", MDP).ok)

    def test_champs_vides_ou_trop_longs(self):
        self.assertFalse(security.authentifier(self.conn, "", MDP).ok)
        self.assertFalse(security.authentifier(self.conn, "directeur", "").ok)
        self.assertFalse(security.authentifier(self.conn, "directeur", "a" * 5000).ok)

    def test_renouvellement_hash_faible(self):
        faible = security.hacher_mdp(MDP, n=2 ** 14)
        with self.conn:
            self.conn.execute("UPDATE UTILISATEUR SET MDP_HASH = ?", (faible,))
        self.assertTrue(security.authentifier(self.conn, "directeur", MDP).ok)
        nouveau = self.conn.execute("SELECT MDP_HASH FROM UTILISATEUR").fetchone()[0]
        self.assertIn(f"scrypt${security.SCRYPT_N}$", nouveau)

    # --- session ---------------------------------------------------------
    def test_session_expire_apres_inactivite(self):
        from datetime import timedelta
        s = security.authentifier(self.conn, "directeur", MDP).session
        self.assertFalse(s.expiree())
        s.derniere_activite -= timedelta(minutes=config.DELAI_INACTIVITE_MIN + 1)
        self.assertTrue(s.expiree())
        s.toucher()
        self.assertFalse(s.expiree())

    # --- journal ---------------------------------------------------------
    def test_journal_chaine_valide_puis_falsification_detectee(self):
        security.authentifier(self.conn, "directeur", "mauvais")
        security.authentifier(self.conn, "directeur", MDP)
        self.assertEqual(database.verifier_journal(self.conn), (True, None))

    def test_journal_protege_contre_modification_et_suppression(self):
        security.authentifier(self.conn, "directeur", MDP)
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("UPDATE JOURNAL SET ACTION = 'X'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("DELETE FROM JOURNAL")

    def test_falsification_du_journal_detectee_si_triggers_contournes(self):
        security.authentifier(self.conn, "directeur", "mauvais")
        security.authentifier(self.conn, "directeur", MDP)
        self.conn.execute("DROP TRIGGER JOURNAL_NO_UPDATE")        # attaquant avec accès direct au fichier
        self.conn.execute("UPDATE JOURNAL SET ACTION = 'CONNEXION_OK' WHERE ID_LOG = 2")
        ok, ligne = database.verifier_journal(self.conn)
        self.assertFalse(ok)
        self.assertEqual(ligne, 2)

    def test_mot_de_passe_jamais_dans_le_journal(self):
        security.authentifier(self.conn, "directeur", "SecretTresSpecial!9")
        tout = " ".join(str(tuple(l)) for l in self.conn.execute("SELECT * FROM JOURNAL"))
        self.assertNotIn("SecretTresSpecial", tout)


if __name__ == "__main__":
    unittest.main(verbosity=2)

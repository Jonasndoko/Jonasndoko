"""Tests : récupération du mot de passe par code temporaire (2 minutes), généré par le système et remis par
l'Administrateur. Lancer :  python test_recuperation.py"""
import os
import tempfile
import time
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import acces                      # noqa: E402
import config                     # noqa: E402
import database                   # noqa: E402
import migrations                 # noqa: E402
import recuperation               # noqa: E402
import reinitialisation           # noqa: E402
import security                   # noqa: E402

MDP = "Tr@vail-Amour-2026"
NOUVEAU = "Nouv3au-Secret#77"
ErreurR = recuperation.ErreurRecuperation


def base():
    conn = database.connecter(os.path.join(tempfile.mkdtemp(), "t.db"))
    security.creer_utilisateur(conn, "admin1", "Alice Administratrice", "ADMINISTRATEUR", MDP)
    admin = security.authentifier(conn, "admin1", MDP).session
    id_user, _ = acces.creer_compte(conn, admin, "paul", "Paul Percepteur", "PERCEPTEUR")
    conn.execute("UPDATE UTILISATEUR SET MDP_HASH = ?, DOIT_CHANGER_MDP = 0 WHERE ID_USER = ?",
                 (security.hacher_mdp(MDP), id_user))
    conn.commit()
    return conn, admin, id_user


class TestGeneration(unittest.TestCase):
    def setUp(self):
        self.conn, self.admin, self.paul = base()

    def test_duree_par_defaut_deux_minutes(self):
        self.assertEqual(config.DUREE_CODE_RECUPERATION_SEC, 120)
        code, secondes = recuperation.generer_code(self.conn, self.admin, self.paul)
        self.assertEqual(secondes, 120)
        reste = recuperation.secondes_restantes(self.conn, self.paul)
        self.assertTrue(118 <= reste <= 120, reste)

    def test_code_fabrique_par_le_systeme(self):
        code, _ = recuperation.generer_code(self.conn, self.admin, self.paul)
        self.assertEqual(len(code), config.LONGUEUR_CODE_RECUPERATION)
        self.assertTrue(all(c in "23456789ABCDEFGHJKLMNPQRSTUVWXYZ" for c in code))
        self.assertEqual(recuperation.formater_code("K7M4PQXR"), "K7M4-PQXR")
        autres = {recuperation.generer_code(self.conn, self.admin, self.paul)[0] for _ in range(5)}
        self.assertGreater(len(autres), 1)                          # pas un code fixe

    def test_code_jamais_stocke_en_clair(self):
        code, _ = recuperation.generer_code(self.conn, self.admin, self.paul)
        for table in ("CODE_RECUPERATION", "JOURNAL"):
            for ligne in self.conn.execute(f"SELECT * FROM {table}"):
                self.assertNotIn(code, " ".join(str(v) for v in tuple(ligne)))
        ligne = self.conn.execute("SELECT CODE_HASH FROM CODE_RECUPERATION").fetchone()
        self.assertTrue(ligne[0].startswith("scrypt$"))

    def test_reservee_a_ladministrateur(self):
        paul = security.authentifier(self.conn, "paul", MDP).session
        with self.assertRaises(PermissionError):
            recuperation.generer_code(self.conn, paul, self.paul)
        with self.assertRaises(PermissionError):
            recuperation.annuler_code(self.conn, paul, self.paul)
        with self.assertRaises(PermissionError):
            recuperation.codes_en_cours(self.conn, paul)
        with self.assertRaises(PermissionError):
            recuperation.journal_authentification(self.conn, paul)

    def test_refus_compte_inconnu_desactive_ou_soi_meme(self):
        with self.assertRaises(ErreurR):
            recuperation.generer_code(self.conn, self.admin, 9999)
        with self.assertRaises(ErreurR):
            recuperation.generer_code(self.conn, self.admin, self.admin.id_user)
        acces.changer_etat_compte(self.conn, self.admin, self.paul, False)
        with self.assertRaises(ErreurR):
            recuperation.generer_code(self.conn, self.admin, self.paul)

    def test_un_seul_code_par_compte(self):
        ancien, _ = recuperation.generer_code(self.conn, self.admin, self.paul)
        nouveau, _ = recuperation.generer_code(self.conn, self.admin, self.paul)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CODE_RECUPERATION").fetchone()[0], 1)
        with self.assertRaises(ErreurR):                             # l'ancien est détruit
            recuperation.recuperer_mdp(self.conn, "paul", ancien, NOUVEAU, NOUVEAU)
        recuperation.recuperer_mdp(self.conn, "paul", nouveau, NOUVEAU, NOUVEAU)

    def test_annuler_le_code(self):
        code, _ = recuperation.generer_code(self.conn, self.admin, self.paul)
        recuperation.annuler_code(self.conn, self.admin, self.paul)
        self.assertEqual(recuperation.secondes_restantes(self.conn, self.paul), 0)
        with self.assertRaises(ErreurR):
            recuperation.recuperer_mdp(self.conn, "paul", code, NOUVEAU, NOUVEAU)
        with self.assertRaises(ErreurR):                             # plus rien à annuler
            recuperation.annuler_code(self.conn, self.admin, self.paul)

    def test_codes_en_cours(self):
        self.assertEqual(recuperation.codes_en_cours(self.conn, self.admin), {})
        recuperation.generer_code(self.conn, self.admin, self.paul)
        en_cours = recuperation.codes_en_cours(self.conn, self.admin)
        self.assertEqual(list(en_cours), [self.paul])
        self.assertTrue(0 < en_cours[self.paul] <= 120)


class TestRecuperation(unittest.TestCase):
    def setUp(self):
        self.conn, self.admin, self.paul = base()
        self.code, _ = recuperation.generer_code(self.conn, self.admin, self.paul)

    def test_recuperation_reussie(self):
        recuperation.recuperer_mdp(self.conn, "paul", self.code, NOUVEAU, NOUVEAU)
        self.assertTrue(security.authentifier(self.conn, "paul", NOUVEAU, "PERCEPTEUR").ok)
        self.assertFalse(security.authentifier(self.conn, "paul", MDP).ok)          # l'ancien ne marche plus
        ligne = self.conn.execute("SELECT DOIT_CHANGER_MDP FROM UTILISATEUR WHERE LOGIN = 'paul'").fetchone()
        self.assertEqual(ligne[0], 0)                                               # il l'a choisi lui-même

    def test_usage_unique(self):
        recuperation.recuperer_mdp(self.conn, "paul", self.code, NOUVEAU, NOUVEAU)
        self.assertEqual(recuperation.secondes_restantes(self.conn, self.paul), 0)
        with self.assertRaises(ErreurR):
            recuperation.recuperer_mdp(self.conn, "paul", self.code, "Autre-Mdp#9988x", "Autre-Mdp#9988x")

    def test_saisie_tolerante(self):
        code_saisi = " " + recuperation.formater_code(self.code).lower() + " "
        recuperation.recuperer_mdp(self.conn, " PAUL ", code_saisi, NOUVEAU, NOUVEAU)
        self.assertTrue(security.authentifier(self.conn, "paul", NOUVEAU).ok)

    def test_lve_un_blocage(self):
        for _ in range(config.MAX_ECHECS):
            security.authentifier(self.conn, "paul", "faux-mot-de-passe")
        self.assertGreater(security._secondes_blocage_restantes(self.conn, "paul"), 0)
        recuperation.recuperer_mdp(self.conn, "paul", self.code, NOUVEAU, NOUVEAU)
        self.assertEqual(security._secondes_blocage_restantes(self.conn, "paul"), 0)
        self.assertTrue(security.authentifier(self.conn, "paul", NOUVEAU).ok)

    def test_expiration_apres_le_delai(self):
        defaut = config.DUREE_CODE_RECUPERATION_SEC
        config.DUREE_CODE_RECUPERATION_SEC = 1
        try:
            code, _ = recuperation.generer_code(self.conn, self.admin, self.paul)
        finally:
            config.DUREE_CODE_RECUPERATION_SEC = defaut
        time.sleep(1.6)
        self.assertEqual(recuperation.secondes_restantes(self.conn, self.paul), 0)
        with self.assertRaises(ErreurR) as e:
            recuperation.recuperer_mdp(self.conn, "paul", code, NOUVEAU, NOUVEAU)
        self.assertEqual(str(e.exception), recuperation.MESSAGE_ECHEC)
        self.assertFalse(security.authentifier(self.conn, "paul", NOUVEAU).ok)      # mot de passe inchangé
        self.assertTrue(security.authentifier(self.conn, "paul", MDP).ok)

    def test_le_code_disparait_de_la_base(self):
        self.conn.execute("UPDATE CODE_RECUPERATION SET DATE_EXPIRATION = '2000-01-01T00:00:00+00:00'")
        self.conn.commit()
        self.assertEqual(recuperation.codes_en_cours(self.conn, self.admin), {})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CODE_RECUPERATION").fetchone()[0], 0)
        actions = [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")]
        self.assertIn("CODE_RECUP_EXPIRE", actions)

    def test_trois_essais_faux_detruisent_le_code(self):
        for _ in range(config.MAX_ESSAIS_CODE):
            with self.assertRaises(ErreurR):
                recuperation.recuperer_mdp(self.conn, "paul", "ZZZZZZZZ", NOUVEAU, NOUVEAU)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM CODE_RECUPERATION").fetchone()[0], 0)
        with self.assertRaises(ErreurR):                             # même le bon code ne marche plus
            recuperation.recuperer_mdp(self.conn, "paul", self.code, NOUVEAU, NOUVEAU)
        actions = [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")]
        self.assertIn("CODE_RECUP_DETRUIT", actions)

    def test_deux_essais_faux_puis_le_bon(self):
        for _ in range(config.MAX_ESSAIS_CODE - 1):
            with self.assertRaises(ErreurR):
                recuperation.recuperer_mdp(self.conn, "paul", "ZZZZZZZZ", NOUVEAU, NOUVEAU)
        recuperation.recuperer_mdp(self.conn, "paul", self.code, NOUVEAU, NOUVEAU)

    def test_message_identique_quel_que_soit_lechec(self):
        acces.creer_compte(self.conn, self.admin, "luc", "Luc Controleur", "CONTROLEUR")           # sans code
        acces.creer_compte(self.conn, self.admin, "off", "Off Desactive", "CONTROLEUR")
        off = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = 'off'").fetchone()[0]
        code_off, _ = recuperation.generer_code(self.conn, self.admin, off)
        acces.changer_etat_compte(self.conn, self.admin, off, False)
        messages = set()
        for login, code in (("paul", "ZZZZZZZZ"), ("luc", self.code), ("inconnu", self.code), ("off", code_off)):
            with self.assertRaises(ErreurR) as e:
                recuperation.recuperer_mdp(self.conn, login, code, NOUVEAU, NOUVEAU)
            messages.add(str(e.exception))
        self.assertEqual(messages, {recuperation.MESSAGE_ECHEC})

    def test_mot_de_passe_faible_ne_brule_pas_le_code(self):
        with self.assertRaises(ErreurR) as e:
            recuperation.recuperer_mdp(self.conn, "paul", self.code, "court", "court")
        self.assertIn("trop faible", str(e.exception))
        with self.assertRaises(ErreurR):
            recuperation.recuperer_mdp(self.conn, "paul", self.code, NOUVEAU, NOUVEAU + "x")   # confirmation différente
        self.assertEqual(self.conn.execute("SELECT ESSAIS FROM CODE_RECUPERATION").fetchone()[0], 0)
        recuperation.recuperer_mdp(self.conn, "paul", self.code, NOUVEAU, NOUVEAU)               # le code sert toujours

    def test_ancien_mot_de_passe_refuse_seulement_avec_un_bon_code(self):
        with self.assertRaises(ErreurR) as e:                        # mauvais code : message générique (pas d'oracle)
            recuperation.recuperer_mdp(self.conn, "paul", "ZZZZZZZZ", MDP, MDP)
        self.assertEqual(str(e.exception), recuperation.MESSAGE_ECHEC)
        with self.assertRaises(ErreurR) as e:                        # bon code : on peut le dire
            recuperation.recuperer_mdp(self.conn, "paul", self.code, MDP, MDP)
        self.assertIn("différent", str(e.exception))
        recuperation.recuperer_mdp(self.conn, "paul", self.code, NOUVEAU, NOUVEAU)               # code non consommé

    def test_champs_vides(self):
        for login, code in (("", self.code), ("paul", ""), ("paul", " - ")):
            with self.assertRaises(ErreurR):
                recuperation.recuperer_mdp(self.conn, login, code, NOUVEAU, NOUVEAU)

    def test_journal_complet_sans_le_code(self):
        recuperation.recuperer_mdp(self.conn, "paul", self.code, NOUVEAU, NOUVEAU)
        actions = [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")]
        for attendu in ("CODE_RECUP_GENERE", "CODE_RECUP_UTILISE", "MDP_RECUPERE"):
            self.assertIn(attendu, actions)
        for l in self.conn.execute("SELECT * FROM JOURNAL"):
            self.assertNotIn(self.code, " ".join(str(v) for v in tuple(l)))
        self.assertEqual(database.verifier_journal(self.conn), (True, None))
        vus = {l["ACTION"] for l in recuperation.journal_authentification(self.conn, self.admin)}
        self.assertIn("CODE_RECUP_UTILISE", vus)
        for action in vus:
            self.assertIn(action, recuperation.LIBELLES_ACTIONS)


class TestCodeDetruitParAilleurs(unittest.TestCase):
    def setUp(self):
        self.conn, self.admin, self.paul = base()
        self.code, _ = recuperation.generer_code(self.conn, self.admin, self.paul)

    def _sans_code(self):
        return self.conn.execute("SELECT COUNT(*) FROM CODE_RECUPERATION").fetchone()[0] == 0

    def test_changement_de_mot_de_passe_par_lutilisateur(self):
        paul = security.authentifier(self.conn, "paul", MDP).session
        security.changer_mdp(self.conn, paul, MDP, NOUVEAU, NOUVEAU)
        self.assertTrue(self._sans_code())

    def test_mot_de_passe_provisoire_donne_par_ladministrateur(self):
        acces.reinitialiser_mdp(self.conn, self.admin, self.paul)
        self.assertTrue(self._sans_code())

    def test_desactivation_du_compte(self):
        acces.changer_etat_compte(self.conn, self.admin, self.paul, False)
        self.assertTrue(self._sans_code())

    def test_desactivation_par_modification_du_compte(self):
        acces.modifier_compte(self.conn, self.admin, self.paul, "Paul Percepteur", "PERCEPTEUR", False)
        self.assertTrue(self._sans_code())

    def test_reinitialisation_de_lapplication(self):
        self.assertIn("CODE_RECUPERATION", reinitialisation.TABLES_COMPTES)
        self.assertNotIn("CODE_RECUPERATION", reinitialisation.tables_scolaires(self.conn))
        reinitialisation.reinitialiser(self.conn, self.admin, MDP, "REINITIALISER")             # données scolaires seules
        self.assertFalse(self._sans_code())
        reinitialisation.reinitialiser(self.conn, self.admin, MDP, "REINITIALISER", comptes_aussi=True)
        self.assertTrue(self._sans_code())


class TestBaseExistante(unittest.TestCase):
    def test_table_creee_sur_une_ancienne_base(self):
        conn, _admin, _ = base()
        conn.execute("DROP TABLE CODE_RECUPERATION")                 # base d'une version précédente
        conn.commit()
        self.assertTrue(any(t.nom == "CODE_RECUPERATION" and t.statut == "MANQUANTE"
                            for t in migrations.analyser(conn).tables))
        migrations.mettre_a_jour(conn, sauvegarder=False)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM CODE_RECUPERATION").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()

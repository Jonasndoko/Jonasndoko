"""Tests des données d'essai (installation, opérations pour chaque poste, suppression propre).
Lancer :  python test_essai.py"""
import os
import py_compile
import tempfile
import unittest
from pathlib import Path

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import audit_financier as af   # noqa: E402
import config                  # noqa: E402
import database                # noqa: E402
import demo                    # noqa: E402
import donnees                 # noqa: E402
import essai                   # noqa: E402
import paiements               # noqa: E402
import reinitialisation        # noqa: E402
import security                # noqa: E402

MDP_ADMIN = "Adm-Test#2026-xyz"


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(":memory:")
        self.login, self.mdp = demo.semer(self.conn)          # vraies données : 6 élèves, 5 classes, 10 reçus
        security.creer_utilisateur(self.conn, "admin1", "Administrateur Test", "ADMINISTRATEUR", MDP_ADMIN)
        self.admin = security.authentifier(self.conn, "admin1", MDP_ADMIN).session
        self.perc_reel = security.authentifier(self.conn, self.login, self.mdp).session
        self.avant = self.photo()

    def photo(self):
        """Contenu des vraies données (hors essai) pour vérifier qu'elles ne bougent pas."""
        c = self.conn
        return {
            "eleves": [tuple(l) for l in c.execute("SELECT MATRICULE, NOM, CODE_QR FROM ELEVE ORDER BY 1")],
            "inscrire": [tuple(l) for l in c.execute("SELECT * FROM INSCRIRE ORDER BY 1, 2")],
            "types": [tuple(l) for l in c.execute("SELECT * FROM TYPE_FRAIS ORDER BY 1")],
            "tarifs": [tuple(l) for l in c.execute("SELECT * FROM TARIF ORDER BY 1, 2, 3")],
            "recus": [tuple(l) for l in c.execute("SELECT * FROM PAIEMENT ORDER BY NUM_SEQ")],
            "classes": [tuple(l) for l in c.execute("SELECT * FROM CLASSE ORDER BY 1")],
            "users": [l[0] for l in c.execute("SELECT LOGIN FROM UTILISATEUR ORDER BY 1")],
        }

    def n(self, table, where="1=1"):
        return self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]

    def codes(self):
        return sorted(a["code"] for a in af.controle_financier(self.conn, self.admin)["anomalies"])


class TestInstallation(Base):
    def setUp(self):
        super().setUp()
        self.codes_avant = self.codes()
        self.r = essai.installer(self.conn, self.admin)

    def test_au_moins_100_eleves_inscrits_dans_les_classes_existantes(self):
        eleves = [l[0] for l in self.conn.execute("SELECT CLE FROM DONNEE_ESSAI WHERE TABLE_SQL = 'ELEVE'")]
        self.assertGreaterEqual(len(eleves), 100)
        self.assertEqual(self.r["eleves"], len(eleves))
        self.assertEqual(self.n("ELEVE"), 6 + len(eleves))
        classes = {l[0] for l in self.conn.execute("SELECT N_CLASSE FROM CLASSE")}
        for l in self.conn.execute("SELECT DISTINCT I.N_CLASSE FROM INSCRIRE I JOIN DONNEE_ESSAI D ON D.CLE = I.MATRICULE "
                                   "WHERE D.TABLE_SQL = 'ELEVE'"):
            self.assertIn(l[0], classes)
        self.assertEqual(self.n("CLASSE"), 5)                  # aucune classe créée
        for m in eleves:
            self.assertRegex(m, r"^\d{4}/\d{2}$")
        e = self.conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = ?", (eleves[0],)).fetchone()
        self.assertTrue(e["CODE_QR"])

    def test_frais_scolaire_depend_de_la_classe_avec_tranches_libres(self):
        annee = donnees.annee_courante(self.conn)
        par_classe = {}
        for c in self.conn.execute("SELECT N_CLASSE, ANNEE_ETUDE FROM CLASSE"):
            montant, devise, tranches = donnees.conditions_du(self.conn, "ESS-MIN", c["N_CLASSE"], annee)
            self.assertEqual(sum(tranches), montant)
            self.assertIsNotNone(donnees.paliers(tranches, montant, True))
            par_classe[c["ANNEE_ETUDE"]] = (montant, len(tranches))
        self.assertEqual(par_classe["4ème"][0], 60000)         # 600,00
        self.assertEqual(par_classe["1ère"][0], 30000)         # 300,00
        self.assertEqual(par_classe["3ème"][0], 30000)
        self.assertNotEqual(par_classe["4ème"][1], par_classe["1ère"][1])      # nombre de tranches libre
        # assurance : tranches définies au niveau du type de frais
        self.assertEqual(donnees.conditions_du(self.conn, "ESS-ASS", 1, annee)[2], (1000, 1000, 1000))

    def test_un_compte_par_poste_et_connexion_possible(self):
        postes = {p for _l, p, _m in self.r["comptes"]}
        self.assertEqual(postes, {config.LIBELLE_ROLES[r] for r in config.ROLES})
        for login, _poste, mdp in self.r["comptes"]:
            res = security.authentifier(self.conn, login, mdp)
            self.assertTrue(res.ok, login)
        texte = Path(self.r["fichier"]).read_text(encoding="utf-8")
        for login, _p, mdp in self.r["comptes"]:
            self.assertIn(login, texte)
            self.assertIn(mdp, texte)
        self.assertEqual(len({m for _l, _p, m in self.r["comptes"]}), len(self.r["comptes"]))   # mots de passe distincts

    def test_operations_de_chaque_utilisateur_au_journal(self):
        logins = {c[0] for c in essai.COMPTES}
        agis = {l[0] for l in self.conn.execute("SELECT DISTINCT LOGIN FROM JOURNAL WHERE ACTION = 'CONNEXION_OK'")}
        self.assertTrue(logins <= agis)
        self.assertEqual(self.n("JOURNAL", "ACTION = 'CONNEXION_ECHEC' AND LOGIN = 'essai.prefet'"), 1)
        for action, login in (("PAIEMENT_ENREGISTRE", "essai.percepteur1"), ("PAIEMENT_ENREGISTRE", "essai.percepteur2"),
                              ("PAIEMENT_ANNULE", "essai.administrateur"), ("ENCAISSEMENT_ENREGISTRE", "essai.intendant"),
                              ("ENCAISSEMENT_MODIFIE", "essai.intendant"), ("ENCAISSEMENT_SUPPRIME", "essai.intendant"),
                              ("FICHE_CARTE_CONSULTEE", "essai.secretaire"), ("DECONNEXION", "essai.prefet")):
            self.assertGreater(self.n("JOURNAL", f"ACTION = '{action}' AND LOGIN = '{login}'"), 0, (action, login))
        self.assertEqual(self.n("JOURNAL", "ACTION = 'DONNEES_ESSAI_AJOUTEES'"), 1)

    def test_paiements_varies_par_tranches_annulations_et_dettes(self):
        recus = self.n("PAIEMENT", "CODTF LIKE 'ESS-%'")
        self.assertGreater(recus, 150)
        self.assertEqual(self.n("PAIEMENT", "CODTF LIKE 'ESS-%' AND STATUT = 'ANNULE'"), 3)
        # des élèves à tous les stades : soldé, partiel, rien payé
        mats = [l[0] for l in self.conn.execute("SELECT CLE FROM DONNEE_ESSAI WHERE TABLE_SQL = 'ELEVE'")]
        statuts = set()
        for m in mats:
            for i in donnees.inscriptions(self.conn, m):
                for ligne in donnees.situation(self.conn, m, i["ANNEESCO"], i["N_CLASSE"]):
                    if ligne.codtf == "ESS-MIN":
                        statuts.add(ligne.statut)
        self.assertEqual(statuts, {"Soldé", "Partiel", "Non payé"})
        # un frais payé tranche par tranche : plusieurs reçus pour le même élève et le même frais
        self.assertGreater(self.n("(SELECT MATRICULE FROM PAIEMENT WHERE CODTF = 'ESS-MIN' GROUP BY MATRICULE HAVING COUNT(*) > 1)"), 0)
        self.assertEqual(self.n("ENCAISSEMENT"), 2)
        ecarts = [l[0] for l in self.conn.execute("SELECT ECART FROM ENCAISSEMENT ORDER BY N_ENC")]
        self.assertEqual(sorted(ecarts)[0], 0)
        self.assertEqual(sorted(ecarts)[1], 500)               # manquant de 5,00

    def test_pas_de_double_installation_et_vraies_donnees_intactes(self):
        with self.assertRaises(essai.ErreurEssai):
            essai.installer(self.conn, self.admin)
        apres = self.photo()
        for cle in ("types", "tarifs", "classes"):             # les vraies lignes sont toujours là, inchangées
            self.assertTrue(set(self.avant[cle]) <= set(apres[cle]), cle)
        self.assertEqual(self.avant["recus"], [r for r in apres["recus"] if r[0] in {x[0] for x in self.avant["recus"]}])

    def test_le_controle_financier_ne_signale_que_le_manquant_voulu(self):
        """Seules sont signalées les situations mises exprès pour essayer le contrôle : 5,00 non versés, un encaissement
        corrigé et un encaissement supprimé. Aucun reçu sans trace, aucun trou de numérotation..."""
        anomalies = af.controle_financier(self.conn, self.admin)["anomalies"]
        self.assertEqual(sorted(a["code"] for a in anomalies if a["code"] not in self.codes_avant),
                         ["ENCAISSEMENT_CORRIGE", "ENCAISSEMENT_SUPPRIME", "REMISE_MANQUANT"],
                         [a["message"] for a in anomalies])


class TestSuppression(Base):
    def setUp(self):
        super().setUp()
        self.codes_avant = self.codes()
        self.r = essai.installer(self.conn, self.admin)

    def supprimer(self):
        return essai.supprimer(self.conn, self.admin, MDP_ADMIN, "supprimer")

    def test_garde_fous(self):
        with self.assertRaises(essai.ErreurEssai):
            essai.supprimer(self.conn, self.admin, "faux-mot-de-passe", "SUPPRIMER")
        with self.assertRaises(essai.ErreurEssai):
            essai.supprimer(self.conn, self.admin, MDP_ADMIN, "oui")
        with self.assertRaises(PermissionError):
            essai.supprimer(self.conn, self.perc_reel, MDP_ADMIN, "SUPPRIMER")
        with self.assertRaises(PermissionError):
            essai.installer(self.conn, self.perc_reel)
        self.assertTrue(essai.installe(self.conn))             # rien n'a été supprimé
        self.assertEqual(self.n("JOURNAL", "ACTION = 'DONNEES_ESSAI_REFUSEES'"), 1)

    def test_tout_disparait_et_le_reste_ne_bouge_pas(self):
        e = self.supprimer()
        self.assertGreaterEqual(e["élèves"], 100)
        self.assertEqual(self.photo(), self.avant)             # exactement l'état d'avant l'installation
        self.assertEqual(self.n("DONNEE_ESSAI"), 0)
        self.assertEqual(self.n("DROIT", "ID_USER NOT IN (SELECT ID_USER FROM UTILISATEUR)"), 0)
        self.assertEqual(self.n("PERCEPTEUR"), 1)
        self.assertEqual(self.n("ENCAISSEMENT"), 0)
        self.assertEqual(self.n("MATRICULE_SEQ"), 0)           # le compteur est revenu à zéro (aucun élève réel au format 0001/26)
        self.assertEqual(self.n("TENTATIVE_CONNEXION"), 0)
        self.assertEqual(self.n("CODE_RECUPERATION"), 0)
        self.assertFalse(essai.installe(self.conn))
        self.assertTrue(database.verifier_journal(self.conn)[0])

    def test_les_recus_restent_proteges_apres_la_suppression(self):
        self.supprimer()
        with self.assertRaises(Exception):
            self.conn.execute("DELETE FROM PAIEMENT")
        self.assertEqual(self.n("PAIEMENT"), 10)

    def test_pas_de_fausse_alerte_apres_la_suppression(self):
        self.supprimer()
        self.assertEqual(self.codes(), self.codes_avant)

    def test_numerotation_repart_sans_alerte_ni_doublon(self):
        """Les reçus d'essai étaient 0011, 0012... : après la suppression le prochain vrai reçu est de nouveau 0011."""
        self.supprimer()
        n = paiements.enregistrer_paiement(self.conn, self.perc_reel, "CSF-0004", "2026-2027", "INSC", 3000)
        self.assertEqual(n, "0011")
        self.assertEqual(self.codes(), self.codes_avant)       # ni « trace double », ni « numéros manquants »

    def test_vrais_recus_avant_et_apres_gardent_une_numerotation_sans_trou_signale(self):
        """Un vrai reçu fait AVANT l'essai (0001-0010) puis un autre APRÈS : aucun trou signalé."""
        self.supprimer()
        paiements.enregistrer_paiement(self.conn, self.perc_reel, "CSF-0004", "2026-2027", "EXAM", 1500)
        self.assertNotIn("NUMEROS_MANQUANTS", self.codes())

    def test_compte_garde_et_desactive_si_un_vrai_recu_s_y_rattache(self):
        login, mdp = next((l, m) for l, _p, m in self.r["comptes"] if l == "essai.percepteur1"), None
        sess = security.authentifier(self.conn, "essai.percepteur1", dict((l, m) for l, _p, m in self.r["comptes"])["essai.percepteur1"]).session
        paiements.enregistrer_paiement(self.conn, sess, "CSF-0004", "2026-2027", "INSC", 3000)     # vrai élève, vrai frais
        e = self.supprimer()
        self.assertEqual(e["comptes désactivés"], 1)
        l = self.conn.execute("SELECT ACTIF FROM UTILISATEUR WHERE LOGIN = 'essai.percepteur1'").fetchone()
        self.assertEqual(l["ACTIF"], 0)
        self.assertIsNone(self.conn.execute("SELECT 1 FROM UTILISATEUR WHERE LOGIN = 'essai.percepteur2'").fetchone())
        self.assertEqual(self.n("PAIEMENT"), 11)               # le vrai reçu est conservé

    def test_reinstallation_possible_apres_suppression(self):
        self.supprimer()
        r = essai.installer(self.conn, self.admin)
        self.assertGreaterEqual(r["eleves"], 100)
        self.assertEqual(self.n("ELEVE"), 6 + r["eleves"])

    def test_reinitialisation_vide_aussi_le_registre(self):
        reinitialisation.reinitialiser(self.conn, self.admin, MDP_ADMIN, "REINITIALISER", comptes_aussi=True)
        self.assertEqual(self.n("DONNEE_ESSAI"), 0)
        self.assertEqual(self.n("UTILISATEUR"), 1)
        af.controle_financier(self.conn, self.admin)           # le contrôle fonctionne toujours


class TestCasParticuliers(Base):
    def test_refuse_moins_de_100_eleves(self):
        with self.assertRaises(essai.ErreurEssai):
            essai.installer(self.conn, self.admin, 50)
        self.assertFalse(essai.installe(self.conn))

    def test_refuse_sans_classe(self):
        with self.conn:
            self.conn.execute("PRAGMA foreign_keys = OFF")
            self.conn.execute("UPDATE CLASSE SET ACTIF = 0")
        self.conn.execute("PRAGMA foreign_keys = ON")
        with self.assertRaises(essai.ErreurEssai):
            essai.installer(self.conn, self.admin)

    def test_installation_interrompue_ne_laisse_rien(self):
        original = essai._operations
        essai._operations = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("panne"))
        try:
            with self.assertRaises(RuntimeError):
                essai.installer(self.conn, self.admin)
        finally:
            essai._operations = original
        self.assertEqual(self.photo(), self.avant)
        self.assertFalse(essai.installe(self.conn))
        self.assertEqual(self.n("TARIF", "CODTF LIKE 'ESS-%'"), 0)

    def test_compte_existant_bloque_l_installation_sans_rien_laisser(self):
        security.creer_utilisateur(self.conn, "essai.prefet", "Quelqu'un", "PREFET", "Autre-Mdp#2026-xyz")
        with self.assertRaises(essai.ErreurEssai):
            essai.installer(self.conn, self.admin)
        self.assertEqual(self.n("ELEVE"), 6)
        self.assertEqual(self.n("UTILISATEUR", "LOGIN = 'essai.prefet'"), 1)       # le compte existant n'est pas touché

    def test_interface_compile(self):
        for f in ("essai.py", "ecrans_travaux.py"):
            py_compile.compile(str(Path(__file__).with_name(f)), doraise=True)


if __name__ == "__main__":
    unittest.main()

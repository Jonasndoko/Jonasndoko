"""Tests du module Travaux techniques : postes, droits d'accès, mise à jour des tables, sauvegarde, restauration.
Lancer :  python test_travaux.py"""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import acces                      # noqa: E402
import config                     # noqa: E402
import database                   # noqa: E402
import demo                       # noqa: E402
import droits                     # noqa: E402
import migrations                 # noqa: E402
import paiements                  # noqa: E402
import sauvegarde                 # noqa: E402
import security                   # noqa: E402
from security import Session      # noqa: E402

MDP = "Tr@vail-Amour-2026"


def nouvelle_base(avec_demo=False):
    chemin = os.path.join(tempfile.mkdtemp(), "test.db")
    conn = database.connecter(chemin)
    security.creer_utilisateur(conn, "admin1", "Alice Administratrice", "ADMINISTRATEUR", MDP)
    admin = security.authentifier(conn, "admin1", MDP).session
    if avec_demo:
        demo.semer(conn)
    return conn, admin, chemin


def ouvrir_session(conn, login, mdp=MDP):
    r = security.authentifier(conn, login, mdp)
    assert r.ok, r.message
    return r.session


def creer(conn, login, poste):
    security.creer_utilisateur(conn, login, f"Nom de {login}", poste, MDP)
    return ouvrir_session(conn, login)


def base_version_03(chemin):
    """Fabrique une base comme celle de la version 0.3 : anciens postes, liste de rôles figée, pas de table DROIT."""
    ancien = database.SCHEMA.replace(
        "ROLE               TEXT    NOT NULL,           -- poste : validé par l'application (config.ROLES)",
        "ROLE TEXT NOT NULL CHECK (ROLE IN ('DIRECTION','SECRETARIAT','CELLULE_FINANCIERE','PERCEPTEUR')),")
    assert ancien != database.SCHEMA
    c = sqlite3.connect(chemin)
    c.executescript(ancien)
    c.execute("DROP TABLE DROIT")
    for login, role in (("directeur", "DIRECTION"), ("secretaire", "SECRETARIAT"),
                        ("financier", "CELLULE_FINANCIERE"), ("perc", "PERCEPTEUR")):
        c.execute("INSERT INTO UTILISATEUR (LOGIN, NOM_COMPLET, ROLE, MDP_HASH, DATE_CREATION) VALUES (?,?,?,?,?)",
                  (login, f"Nom de {login}", role, security.hacher_mdp(MDP), "2026-10-08T00:00:00+00:00"))
    c.execute("INSERT INTO PERCEPTEUR (ID_USER) VALUES (4)")
    c.execute("INSERT INTO DEVISE (CODE_DEVISE, DESI_DEVISE) VALUES ('USD', 'Dollar')")
    c.commit()
    c.close()


# ================================================================== postes et droits
class TestPostesEtDroits(unittest.TestCase):
    def setUp(self):
        self.conn, self.admin, _ = nouvelle_base()

    def test_huit_postes(self):
        self.assertEqual(len(config.ROLES), 8)
        for r in ("PREFET", "ADMINISTRATEUR", "SECRETAIRE", "INTENDANT", "PERCEPTEUR", "CONTROLEUR", "DIRECTRICE_ETUDES",
                  "DIRECTEUR_DISCIPLINE"):
            self.assertIn(r, config.ROLES)
            self.assertIn(r, config.LIBELLE_ROLES)
        for i, r in enumerate(config.ROLES):
            security.creer_utilisateur(self.conn, f"user{i}", f"Utilisateur {i}", r, MDP)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM UTILISATEUR").fetchone()[0], len(config.ROLES) + 1)
        with self.assertRaises(ValueError):
            security.creer_utilisateur(self.conn, "x1", "Nom Valide", "DIRECTION", MDP)       # ancien nom : refusé

    def test_droits_par_defaut_a_la_creation(self):
        perc = creer(self.conn, "perc1", "PERCEPTEUR")
        sec = creer(self.conn, "sec1", "SECRETAIRE")
        self.assertEqual(droits.droits_utilisateur(self.conn, perc.id_user),
                         {("paiement", "LECTURE"), ("paiement", "AJOUT")})
        self.assertEqual(droits.droits_utilisateur(self.conn, sec.id_user), {("dossier_eleve", "LECTURE"), ("dossier_eleve", "MODIFICATION"), ("inscription", "LECTURE"), ("inscription", "AJOUT"), ("inscription", "MODIFICATION")})
        self.assertTrue(droits.a_droit(self.conn, self.admin, "paiement", "LECTURE"))
        self.assertFalse(droits.a_droit(self.conn, self.admin, "paiement", "AJOUT"))

    def test_exiger_droit_et_effet_immediat(self):
        sec = creer(self.conn, "sec1", "SECRETAIRE")
        with self.assertRaises(PermissionError):
            droits.exiger_droit(self.conn, sec, "paiement", "LECTURE")
        acces.definir_droits(self.conn, self.admin, sec.id_user, {("paiement", "LECTURE")})
        droits.exiger_droit(self.conn, sec, "paiement", "LECTURE")                 # même session, effet immédiat
        acces.definir_droits(self.conn, self.admin, sec.id_user, set())
        with self.assertRaises(PermissionError):
            droits.exiger_droit(self.conn, sec, "paiement", "LECTURE")

    def test_session_falsifiee_ou_compte_desactive_refuses(self):
        perc = creer(self.conn, "perc1", "PERCEPTEUR")
        faux = Session(perc.id_user, "perc1", "Faux", "ADMINISTRATEUR")                # mauvais poste
        self.assertFalse(droits.a_droit(self.conn, faux, "paiement", "LECTURE"))
        self.assertFalse(droits.est_admin(self.conn, faux))
        self.assertFalse(droits.a_droit(self.conn, None, "paiement", "LECTURE"))
        self.assertFalse(droits.a_droit(self.conn, Session(9999, "x", "x", "PERCEPTEUR"), "paiement", "LECTURE"))
        acces.modifier_compte(self.conn, self.admin, perc.id_user, "Nom de perc1", "PERCEPTEUR", False)
        self.assertFalse(droits.a_droit(self.conn, perc, "paiement", "LECTURE"))         # désactivé = immédiat

    def test_lecture_ajoutee_d_office_et_droits_inexistants_refuses(self):
        sec = creer(self.conn, "sec1", "SECRETAIRE")
        accordes = acces.definir_droits(self.conn, self.admin, sec.id_user, {("paiement", "AJOUT")})
        self.assertEqual(accordes, {("paiement", "AJOUT"), ("paiement", "LECTURE")})
        with self.assertRaises(acces.ErreurAcces):
            acces.definir_droits(self.conn, self.admin, sec.id_user, {("paiement", "SUPPRESSION")})   # reçu jamais supprimé
        with self.assertRaises(acces.ErreurAcces):
            acces.definir_droits(self.conn, self.admin, sec.id_user, {("paiement", "IMPRESSION")})    # droit supprimé
        with self.assertRaises(acces.ErreurAcces):
            acces.definir_droits(self.conn, self.admin, sec.id_user, {("eleves", "LECTURE")})
        self.assertEqual(droits.droits_utilisateur(self.conn, sec.id_user), accordes)     # refus = rien changé

    def test_droit_par_defaut_du_poste_retablis(self):
        perc = creer(self.conn, "perc1", "PERCEPTEUR")
        acces.definir_droits(self.conn, self.admin, perc.id_user, set())
        acces.droits_par_defaut_du_poste(self.conn, self.admin, perc.id_user)
        self.assertIn(("paiement", "AJOUT"), droits.droits_utilisateur(self.conn, perc.id_user))


class TestPaiementEtDroits(unittest.TestCase):
    def setUp(self):
        self.conn, self.admin, _ = nouvelle_base(avec_demo=True)
        self.an = demo.ANNEE_COURANTE

    def _perc(self):
        mdp = "Tr@vail-Amour-2026"
        security.creer_utilisateur(self.conn, "perc2", "Percepteur Deux", "PERCEPTEUR", mdp)
        return ouvrir_session(self.conn, "perc2")

    def test_percepteur_sans_droit_ajout_ne_peut_pas_encaisser(self):
        perc = self._perc()
        acces.definir_droits(self.conn, self.admin, perc.id_user, {("paiement", "LECTURE")})
        with self.assertRaises(PermissionError):
            paiements.enregistrer_paiement(self.conn, perc, "CSF-0004", self.an, "INSC", 3000)
        acces.definir_droits(self.conn, self.admin, perc.id_user, {("paiement", "AJOUT")})
        n = paiements.enregistrer_paiement(self.conn, perc, "CSF-0004", self.an, "INSC", 3000)
        self.assertRegex(n, r"^\d{4}$")

    def test_intendant_imprime_mais_n_encaisse_pas(self):
        perc = self._perc()
        n = paiements.enregistrer_paiement(self.conn, perc, "CSF-0004", self.an, "INSC", 3000)
        intendant = creer(self.conn, "intend1", "INTENDANT")
        with self.assertRaises(PermissionError):
            paiements.enregistrer_paiement(self.conn, intendant, "CSF-0004", self.an, "MIN1", 1000)
        chemin = paiements.preparer_pdf(self.conn, intendant, n, duplicata=True)
        self.assertTrue(os.path.getsize(chemin) > 500)

    def test_droit_ajout_ne_suffit_pas_sans_etre_percepteur(self):
        sec = creer(self.conn, "sec1", "SECRETAIRE")
        acces.definir_droits(self.conn, self.admin, sec.id_user, {("paiement", "AJOUT")})
        with self.assertRaises(PermissionError):                       # enregistrer = poste Percepteur ET droit Ajout
            paiements.enregistrer_paiement(self.conn, sec, "CSF-0004", self.an, "INSC", 3000)
        # le rapport, lui, est ouvert à tout compte qui a accès au module
        self.assertEqual(paiements.rapport_journalier(self.conn, sec, paiements.lire_date("08/10/2026"))["nom_percepteur"],
                         "Tous les percepteurs")

    def test_onglets_selon_les_droits(self):
        # (la fonction qui choisit les onglets est dans ecrans_paiement, qui a besoin de tkinter : on contrôle ici
        #  les droits sur lesquels elle s'appuie)
        perc = self._perc()
        a = lambda s, d: droits.a_droit(self.conn, s, "paiement", d)
        self.assertTrue(a(perc, "LECTURE") and a(perc, "AJOUT"))
        prefet = creer(self.conn, "pref1", "PREFET")
        self.assertTrue(a(prefet, "LECTURE") and not a(prefet, "AJOUT"))


# ================================================================== gestion des comptes
class TestAcces(unittest.TestCase):
    def setUp(self):
        self.conn, self.admin, _ = nouvelle_base()

    def test_reserve_a_l_administrateur(self):
        sec = creer(self.conn, "sec1", "SECRETAIRE")
        cible = self.admin.id_user
        for appel in (lambda: acces.lister_utilisateurs(self.conn, sec),
                      lambda: acces.creer_compte(self.conn, sec, "pirate", "Pirate Pirate", "ADMINISTRATEUR"),
                      lambda: acces.modifier_compte(self.conn, sec, cible, "Nom Valide", "SECRETAIRE", True),
                      lambda: acces.reinitialiser_mdp(self.conn, sec, cible),
                      lambda: acces.debloquer(self.conn, sec, cible),
                      lambda: acces.lire_droits(self.conn, sec, cible),
                      lambda: acces.definir_droits(self.conn, sec, sec.id_user, {("paiement", "AJOUT")}),
                      lambda: migrations.mise_a_jour_manuelle(self.conn, sec),
                      lambda: migrations.analyse_admin(self.conn, sec),
                      lambda: migrations.controle_integrite(self.conn, sec),
                      lambda: sauvegarde.sauvegarder(self.conn, sec),
                      lambda: sauvegarde.restaurer(self.conn, sec, "x.csfbak"),
                      lambda: acces.creer_compte(self.conn, None, "pirate", "Pirate Pirate", "ADMINISTRATEUR")):
            with self.assertRaises(PermissionError):
                appel()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM UTILISATEUR").fetchone()[0], 2)

    def test_creation_compte_mot_de_passe_provisoire(self):
        id_user, mdp = acces.creer_compte(self.conn, self.admin, "marie", "Marie Kabila", "PERCEPTEUR")
        self.assertEqual(security.verifier_politique(mdp, "marie"), [])
        r = security.authentifier(self.conn, "marie", mdp)
        self.assertTrue(r.ok)
        self.assertTrue(r.session.doit_changer_mdp)                      # changement obligatoire
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PERCEPTEUR WHERE ID_USER = ?", (id_user,)).fetchone()[0], 1)
        journal = " ".join(f"{l['ACTION']} {l['DETAIL']}" for l in self.conn.execute("SELECT * FROM JOURNAL"))
        self.assertNotIn(mdp, journal)                                   # jamais dans le journal
        self.assertEqual(database.verifier_journal(self.conn), (True, None))
        with self.assertRaises(acces.ErreurAcces):
            acces.creer_compte(self.conn, self.admin, "MARIE", "Autre Personne", "SECRETAIRE")   # doublon
        with self.assertRaises(acces.ErreurAcces):
            acces.creer_compte(self.conn, self.admin, "nouveau", "Nouveau Compte", "ROI")      # poste inconnu

    def test_changement_de_mot_de_passe(self):
        _, mdp = acces.creer_compte(self.conn, self.admin, "marie", "Marie Kabila", "SECRETAIRE")
        s = security.authentifier(self.conn, "marie", mdp).session
        with self.assertRaises(ValueError):
            security.changer_mdp(self.conn, s, "mauvais", "Nouveau-Mdp-2026!", "Nouveau-Mdp-2026!")
        with self.assertRaises(ValueError):
            security.changer_mdp(self.conn, s, mdp, "faible", "faible")
        with self.assertRaises(ValueError):
            security.changer_mdp(self.conn, s, mdp, "Nouveau-Mdp-2026!", "Autre-Mdp-2026!!")
        security.changer_mdp(self.conn, s, mdp, "Nouveau-Mdp-2026!", "Nouveau-Mdp-2026!")
        self.assertFalse(s.doit_changer_mdp)
        self.assertFalse(security.authentifier(self.conn, "marie", mdp).ok)
        r = security.authentifier(self.conn, "marie", "Nouveau-Mdp-2026!")
        self.assertTrue(r.ok)
        self.assertFalse(r.session.doit_changer_mdp)

    def test_dernier_administrateur_protege(self):
        with self.assertRaises(acces.ErreurAcces):        # on ne se rétrograde pas soi-même
            acces.modifier_compte(self.conn, self.admin, self.admin.id_user, "Alice Administratrice", "SECRETAIRE", True)
        with self.assertRaises(acces.ErreurAcces):        # ni ne se désactive
            acces.modifier_compte(self.conn, self.admin, self.admin.id_user, "Alice Administratrice", "ADMINISTRATEUR", False)
        autre_id, mdp = acces.creer_compte(self.conn, self.admin, "bob", "Bob Second", "ADMINISTRATEUR")
        acces.modifier_compte(self.conn, self.admin, autre_id, "Bob Second", "SECRETAIRE", True)   # il en reste un : ok
        bob = security.authentifier(self.conn, "bob", mdp).session
        self.assertEqual(bob.role, "SECRETAIRE")
        self.assertFalse(droits.est_admin(self.conn, bob))

    def test_changement_de_poste_remet_les_droits_par_defaut(self):
        id_user, _ = acces.creer_compte(self.conn, self.admin, "marie", "Marie Kabila", "SECRETAIRE")
        self.assertEqual(droits.droits_utilisateur(self.conn, id_user), {("dossier_eleve", "LECTURE"), ("dossier_eleve", "MODIFICATION"), ("inscription", "LECTURE"), ("inscription", "AJOUT"), ("inscription", "MODIFICATION")})
        acces.modifier_compte(self.conn, self.admin, id_user, "Marie Kabila", "PERCEPTEUR", True)
        self.assertIn(("paiement", "AJOUT"), droits.droits_utilisateur(self.conn, id_user))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PERCEPTEUR WHERE ID_USER = ?", (id_user,)).fetchone()[0], 1)
        acces.modifier_compte(self.conn, self.admin, id_user, "Marie Kabila", "CONTROLEUR", True)
        acces.modifier_compte(self.conn, self.admin, id_user, "Marie Kabila", "PERCEPTEUR", True)   # retour : pas de doublon
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PERCEPTEUR WHERE ID_USER = ?", (id_user,)).fetchone()[0], 1)

    def test_reinitialisation_et_deblocage(self):
        id_user, mdp = acces.creer_compte(self.conn, self.admin, "marie", "Marie Kabila", "SECRETAIRE")
        for _ in range(config.MAX_ECHECS):
            security.authentifier(self.conn, "marie", "mauvais-mot-de-passe")
        self.assertGreater(security.authentifier(self.conn, "marie", mdp).secondes_blocage, 0)
        nouveau = acces.reinitialiser_mdp(self.conn, self.admin, id_user)
        self.assertNotEqual(nouveau, mdp)
        r = security.authentifier(self.conn, "marie", nouveau)          # le blocage est levé en même temps
        self.assertTrue(r.ok and r.session.doit_changer_mdp)
        self.assertFalse(security.authentifier(self.conn, "marie", mdp).ok)
        for _ in range(config.MAX_ECHECS):
            security.authentifier(self.conn, "marie", "mauvais-mot-de-passe")
        acces.debloquer(self.conn, self.admin, id_user)
        self.assertTrue(security.authentifier(self.conn, "marie", nouveau).ok)

    def test_premier_demarrage_tant_que_pas_d_administrateur(self):
        conn = database.connecter(os.path.join(tempfile.mkdtemp(), "v.db"))
        self.assertTrue(security.aucun_administrateur(conn))
        security.creer_utilisateur(conn, "sec1", "Marie Kabila", "SECRETAIRE", MDP)
        self.assertTrue(security.aucun_administrateur(conn))             # des comptes existent, mais pas d'administrateur
        security.creer_utilisateur(conn, "adm1", "Alice Admin", "ADMINISTRATEUR", MDP)
        self.assertFalse(security.aucun_administrateur(conn))

    def test_modifications_journalisees(self):
        id_user, _ = acces.creer_compte(self.conn, self.admin, "marie", "Marie Kabila", "SECRETAIRE")
        acces.definir_droits(self.conn, self.admin, id_user, {("paiement", "LECTURE")})
        acces.modifier_compte(self.conn, self.admin, id_user, "Marie Kabila", "SECRETAIRE", False)
        actions = [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")]
        for a in ("COMPTE_CREE", "DROITS_MODIFIES", "COMPTE_MODIFIE"):
            self.assertIn(a, actions)
        self.assertEqual(database.verifier_journal(self.conn), (True, None))


# ================================================================== mise à jour des tables
class TestMiseAJour(unittest.TestCase):
    def test_base_neuve(self):
        conn = database.connecter(os.path.join(tempfile.mkdtemp(), "n.db"))
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], migrations.VERSION_SCHEMA)
        a = migrations.analyser(conn)
        self.assertFalse(a.a_faire)
        self.assertTrue(all(t.statut == "OK" for t in a.tables))
        self.assertIn("DROIT", {t.nom for t in a.tables})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM JOURNAL").fetchone()[0], 0)

    def test_ancienne_base_v03_mise_a_niveau(self):
        chemin = os.path.join(tempfile.mkdtemp(), "ancienne.db")
        base_version_03(chemin)
        avant = set(Path(config.DOSSIER_SAUVEGARDES).glob("Avant-miseajour*")) if config.DOSSIER_SAUVEGARDES.exists() else set()
        conn = database.connecter(chemin)
        roles = {l["LOGIN"]: l["ROLE"] for l in conn.execute("SELECT LOGIN, ROLE FROM UTILISATEUR")}
        self.assertEqual(roles, {"directeur": "ADMINISTRATEUR", "secretaire": "SECRETAIRE",
                                 "financier": "INTENDANT", "perc": "PERCEPTEUR"})
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], migrations.VERSION_SCHEMA)
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(conn.execute("SELECT N_PERC, ID_USER FROM PERCEPTEUR").fetchone()[1], 4)    # lien conservé
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM DEVISE").fetchone()[0], 1)               # données conservées
        s = ouvrir_session(conn, "perc")
        self.assertTrue(droits.a_droit(conn, s, "paiement", "AJOUT"))                                # droits initiaux
        self.assertTrue(droits.a_droit(conn, ouvrir_session(conn, "directeur"), "paiement", "LECTURE"))
        self.assertTrue(droits.est_admin(conn, ouvrir_session(conn, "directeur")))
        self.assertEqual(database.verifier_journal(conn)[0], True)
        self.assertIn("STRUCTURE_MISE_A_JOUR", [l["ACTION"] for l in conn.execute("SELECT ACTION FROM JOURNAL")])
        apres = set(config.DOSSIER_SAUVEGARDES.glob("Avant-miseajour*"))
        self.assertEqual(len(apres - avant), 1)                                                      # sauvegarde de sécurité
        # le compte reconstruit accepte les nouveaux postes
        security.creer_utilisateur(conn, "pref", "Un Préfet", "PREFET", MDP)
        conn.close()
        # 2e ouverture : rien à refaire, pas de nouvelle sauvegarde, droits retirés non rétablis
        conn = database.connecter(chemin)
        admin = ouvrir_session(conn, "directeur")
        perc_id = conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN='perc'").fetchone()[0]
        acces.definir_droits(conn, admin, perc_id, set())
        conn.close()
        conn = database.connecter(chemin)
        self.assertEqual(droits.droits_utilisateur(conn, perc_id), set())
        self.assertEqual(set(config.DOSSIER_SAUVEGARDES.glob("Avant-miseajour*")), apres)
        conn.close()

    def test_table_manquante_recreee_par_l_administrateur(self):
        conn, admin, _ = nouvelle_base()
        conn.execute("DROP TABLE DROIT")
        conn.commit()
        a = migrations.analyse_admin(conn, admin)
        self.assertTrue(a.a_faire)
        self.assertEqual({t.nom: t.statut for t in a.tables}["DROIT"], "MANQUANTE")
        actions = migrations.mise_a_jour_manuelle(conn, admin)
        self.assertTrue(any("DROIT" in x for x in actions))
        self.assertFalse(migrations.analyser(conn).a_faire)
        self.assertEqual(migrations.mise_a_jour_manuelle(conn, admin), [])                 # idempotent

    def test_colonne_manquante_ajoutee_et_inconnue_conservee(self):
        conn, admin, _ = nouvelle_base()
        conn.execute("CREATE TABLE TABLE_INCONNUE (A INTEGER)")
        conn.execute("INSERT INTO TABLE_INCONNUE VALUES (1)")
        conn.commit()
        vraie = migrations.structure_attendue

        def attendue():
            s = vraie()
            s["tables"]["ELEVE"] = s["tables"]["ELEVE"] + [(99, "EMAIL", "TEXT", 0, None, 0),
                                                           (100, "COULEUR", "INTEGER", 1, "1", 0)]
            return s
        migrations.structure_attendue = attendue
        try:
            a = migrations.analyser(conn)
            eleve = {t.nom: t for t in a.tables}["ELEVE"]
            self.assertEqual(eleve.statut, "COLONNES_MANQUANTES")
            self.assertEqual(eleve.manquantes, ["EMAIL", "COULEUR"])
            self.assertEqual({t.nom: t.statut for t in a.tables}["TABLE_INCONNUE"], "INCONNUE")
            migrations.mise_a_jour_manuelle(conn, admin)
        finally:
            migrations.structure_attendue = vraie
        colonnes = {c["name"] for c in conn.execute("PRAGMA table_info(ELEVE)")}
        self.assertTrue({"EMAIL", "COULEUR"} <= colonnes)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM TABLE_INCONNUE").fetchone()[0], 1)    # rien supprimé

    def test_colonne_obligatoire_sans_valeur_par_defaut_signalee(self):
        conn, _, _ = nouvelle_base()
        vraie = migrations.structure_attendue

        def attendue():
            s = vraie()
            s["tables"]["ELEVE"] = s["tables"]["ELEVE"] + [(99, "CODE", "TEXT", 1, None, 0)]
            return s
        migrations.structure_attendue = attendue
        try:
            self.assertTrue(any("ELEVE.CODE" in b for b in migrations.analyser(conn).bloquants))
        finally:
            migrations.structure_attendue = vraie

    def test_declencheur_manquant_recree(self):
        conn, admin, _ = nouvelle_base()
        conn.execute("DROP TRIGGER PAIEMENT_NO_DELETE")
        conn.commit()
        self.assertTrue(migrations.analyser(conn).a_faire)
        migrations.mise_a_jour_manuelle(conn, admin)
        self.assertFalse(migrations.analyser(conn).a_faire)

    def test_base_plus_recente_refusee(self):
        chemin = os.path.join(tempfile.mkdtemp(), "future.db")
        conn = database.connecter(chemin)
        conn.execute("PRAGMA user_version = 99")
        conn.commit()
        conn.close()
        with self.assertRaises(migrations.ErreurMiseAJour):
            database.connecter(chemin)

    def test_controle_integrite(self):
        conn, admin, _ = nouvelle_base()
        res = migrations.controle_integrite(conn, admin)
        self.assertTrue(all(r[1] for r in res))
        self.assertEqual(len(res), 3)
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("INSERT INTO DROIT VALUES (999, 'paiement', 'LECTURE')")       # compte inexistant
        conn.commit()
        res = migrations.verifier_integrite(conn)
        self.assertFalse(dict((r[0], r[1]) for r in res)["Liens entre les tables (références)"])


# ================================================================== sauvegarde et restauration
class TestSauvegarde(unittest.TestCase):
    def setUp(self):
        self.conn, self.admin, self.chemin = nouvelle_base(avec_demo=True)

    def test_sauvegarde_contenu_et_manifeste(self):
        dossier = tempfile.mkdtemp()
        f = sauvegarde.sauvegarder(self.conn, self.admin, dossier)
        self.assertEqual(f.parent, Path(dossier))
        self.assertTrue(f.name.endswith(config.EXTENSION_SAUVEGARDE))
        self.assertEqual(list(Path(dossier).glob("*.part")), [])
        m = sauvegarde.lire_manifeste(f)
        self.assertEqual(m["contenu"]["eleves"], 6)
        self.assertEqual(m["contenu"]["utilisateurs"], 2)
        self.assertGreater(m["contenu"]["paiements"], 0)
        self.assertEqual(m["version_programme"], config.VERSION)
        self.assertEqual(len(m["sha256"]), 64)
        with zipfile.ZipFile(f) as z:
            self.assertEqual(set(z.namelist()), {"college.db", "manifeste.json"})
        self.assertIn("SAUVEGARDE_CREEE", [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL")])
        self.assertEqual([s["nom"] for s in sauvegarde.lister(dossier)], [f.name])

    def test_deux_sauvegardes_meme_seconde_ne_s_ecrasent_pas(self):
        dossier = tempfile.mkdtemp()
        a = sauvegarde.creer_sauvegarde(self.conn, dossier)
        b = sauvegarde.creer_sauvegarde(self.conn, dossier)
        c = sauvegarde.creer_sauvegarde(self.conn, dossier)
        self.assertEqual(len({a, b, c}), 3)

    def test_dossier_inutilisable(self):
        fichier = tempfile.NamedTemporaryFile(delete=False).name
        with self.assertRaises(sauvegarde.ErreurSauvegarde):
            sauvegarde.sauvegarder(self.conn, self.admin, os.path.join(fichier, "sous-dossier"))

    def test_restauration_aller_retour(self):
        f = sauvegarde.sauvegarder(self.conn, self.admin, tempfile.mkdtemp())
        nb_paiements = self.conn.execute("SELECT COUNT(*) FROM PAIEMENT").fetchone()[0]
        security.creer_utilisateur(self.conn, "apres", "Ajouté Après", "SECRETAIRE", MDP)
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = 1")                  # modifications à annuler
        avant = set(config.DOSSIER_SAUVEGARDES.glob("Avant-restauration*"))
        examen = sauvegarde.examiner(f)
        self.assertEqual((examen["eleves"], examen["utilisateurs"], examen["administrateurs"]), (6, 2, 1))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM UTILISATEUR").fetchone()[0], 3)   # examiner ne change rien
        resultat = sauvegarde.restaurer(self.conn, self.admin, f)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM UTILISATEUR").fetchone()[0], 2)
        self.assertIsNone(self.conn.execute("SELECT 1 FROM UTILISATEUR WHERE LOGIN = 'apres'").fetchone())
        self.assertTrue(droits.a_droit(self.conn, self.admin, "paiement", "LECTURE"))              # droits d'avant
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PAIEMENT").fetchone()[0], nb_paiements)
        self.assertTrue(resultat["securite"].exists())                                             # sauvegarde de sécurité
        self.assertEqual(len(set(config.DOSSIER_SAUVEGARDES.glob("Avant-restauration*")) - avant), 1)
        self.assertEqual(database.verifier_journal(self.conn), (True, None))
        self.assertEqual(self.conn.execute("SELECT ACTION FROM JOURNAL ORDER BY ID_LOG DESC LIMIT 1").fetchone()[0],
                         "RESTAURATION_EFFECTUEE")
        # la sauvegarde de sécurité permet d'annuler la restauration
        sauvegarde.restaurer(self.conn, self.admin, resultat["securite"])
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM UTILISATEUR WHERE LOGIN = 'apres'").fetchone())

    def test_restauration_dans_une_nouvelle_connexion(self):
        """Le fichier réellement modifié sur le disque contient bien les données restaurées."""
        f = sauvegarde.sauvegarder(self.conn, self.admin, tempfile.mkdtemp())
        security.creer_utilisateur(self.conn, "apres", "Ajouté Après", "SECRETAIRE", MDP)
        sauvegarde.restaurer(self.conn, self.admin, f)
        self.conn.close()
        c = database.connecter(self.chemin)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM UTILISATEUR").fetchone()[0], 2)
        self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        c.close()

    def test_fichier_modifie_refuse_et_base_intacte(self):
        f = sauvegarde.sauvegarder(self.conn, self.admin, tempfile.mkdtemp())
        truque = f.with_name("truque.csfbak")
        with zipfile.ZipFile(f) as z, zipfile.ZipFile(truque, "w") as t:
            octets = bytearray(z.read("college.db"))
            octets[-100] ^= 0xFF
            t.writestr("college.db", bytes(octets))
            t.writestr("manifeste.json", z.read("manifeste.json"))
        with self.assertRaises(sauvegarde.ErreurSauvegarde) as e:
            sauvegarde.restaurer(self.conn, self.admin, truque)
        self.assertIn("empreinte", str(e.exception))
        with self.assertRaises(sauvegarde.ErreurSauvegarde):
            sauvegarde.examiner(truque)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ELEVE").fetchone()[0], 6)

    def test_fichiers_invalides_refuses(self):
        dossier = tempfile.mkdtemp()
        texte = Path(dossier, "notes.csfbak")
        texte.write_text("ceci n'est pas une sauvegarde")
        sans_manifeste = Path(dossier, "vide.csfbak")
        with zipfile.ZipFile(sans_manifeste, "w") as z:
            z.writestr("autre.txt", "x")
        autre_bd = Path(dossier, "autre.db")
        c = sqlite3.connect(autre_bd)
        c.execute("CREATE TABLE T (A)")
        c.commit()
        c.close()
        for fichier in (texte, sans_manifeste, autre_bd, Path(dossier, "inexistant.csfbak")):
            with self.assertRaises(sauvegarde.ErreurSauvegarde, msg=str(fichier)):
                sauvegarde.restaurer(self.conn, self.admin, fichier)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ELEVE").fetchone()[0], 6)

    def test_restauration_d_une_ancienne_base_la_met_a_niveau(self):
        ancienne = os.path.join(tempfile.mkdtemp(), "college_v03.db")
        base_version_03(ancienne)
        resume = sauvegarde.examiner(ancienne)
        self.assertFalse(resume["controle"])
        self.assertEqual(resume["administrateurs"], 1)                    # DIRECTION compté comme administrateur
        sauvegarde.restaurer(self.conn, self.admin, ancienne)
        roles = {l["LOGIN"]: l["ROLE"] for l in self.conn.execute("SELECT LOGIN, ROLE FROM UTILISATEUR")}
        self.assertEqual(roles["directeur"], "ADMINISTRATEUR")
        self.assertEqual(self.conn.execute("PRAGMA user_version").fetchone()[0], migrations.VERSION_SCHEMA)
        self.assertFalse(migrations.analyser(self.conn).a_faire)
        self.assertEqual(database.verifier_journal(self.conn), (True, None))
        self.assertTrue(security.aucun_administrateur(self.conn) is False)

    def test_sauvegarde_d_une_base_en_service_puis_ouverture_directe(self):
        """Le fichier .db contenu dans l'archive est une vraie base utilisable."""
        f = sauvegarde.creer_sauvegarde(self.conn, tempfile.mkdtemp())
        sortie = tempfile.mkdtemp()
        with zipfile.ZipFile(f) as z:
            z.extract("college.db", sortie)
        c = sqlite3.connect(os.path.join(sortie, "college.db"))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM ELEVE").fetchone()[0], 6)
        c.close()


if __name__ == "__main__":
    unittest.main(verbosity=1)

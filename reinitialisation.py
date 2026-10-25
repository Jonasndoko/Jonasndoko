"""Réinitialisation de l'application (Administrateur uniquement).

Vide toutes les données scolaires (années, niveaux, options, classes, élèves, inscriptions, devises,
types de frais, tarifs, paiements) pour repartir d'une application vide. Les comptes, les rôles, les droits et le
journal sont conservés, sauf si l'administrateur demande aussi de les remettre à zéro (il garde alors son propre compte).

Garde-fous : mot de passe de l'administrateur redemandé, phrase de confirmation à taper, sauvegarde de sécurité
automatique juste avant, opération inscrite dans le journal.
"""
import sqlite3

import config
import database
import droits
import sauvegarde
import security
from database import journaliser

PHRASE_CONFIRMATION = "REINITIALISER"

# Tables qui ne sont jamais des données scolaires : comptes, droits, rôles, sécurité, journal.
TABLES_COMPTES = ("UTILISATEUR", "DROIT", "ROLE", "ROLE_DROIT", "TENTATIVE_CONNEXION", "CODE_RECUPERATION",
                 "JOURNAL", "PERCEPTEUR", "DONNEE_ESSAI")


class ErreurReinitialisation(Exception):
    """Erreur dont le message peut être affiché tel quel."""


def tables_scolaires(conn) -> list:
    noms = [l[0] for l in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return [n for n in noms if n not in TABLES_COMPTES]


def apercu(conn, session) -> dict:
    """{table: nombre de lignes} des données scolaires qui seraient effacées."""
    droits.exiger_admin(conn, session)
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables_scolaires(conn)}


def reinitialiser(conn, session, mot_de_passe, confirmation, comptes_aussi=False) -> dict:
    """Efface les données scolaires (et, si `comptes_aussi`, les autres comptes et les rôles créés).
    Retourne {'effaces': {table: n}, 'securite': chemin de la sauvegarde faite avant}."""
    droits.exiger_admin(conn, session)
    if (confirmation or "").strip().upper() != PHRASE_CONFIRMATION:
        raise ErreurReinitialisation(f"Tapez exactement « {PHRASE_CONFIRMATION} » pour confirmer.")
    ligne = conn.execute("SELECT MDP_HASH FROM UTILISATEUR WHERE ID_USER = ?", (session.id_user,)).fetchone()
    if not ligne or not security.verifier_mdp(mot_de_passe or "", ligne["MDP_HASH"]):
        with conn:
            journaliser(conn, session.id_user, session.login, "REINITIALISATION_REFUSEE", "mot de passe incorrect")
        raise ErreurReinitialisation("Mot de passe incorrect.")

    tables = tables_scolaires(conn)
    effaces = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    securite = sauvegarde.sauvegarde_securite(conn, "Avant-reinitialisation")      # filet de sécurité
    conn.commit()

    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        # Les reçus sont protégés contre la suppression : on retire ces protections le temps de l'opération,
        # elles sont remises en place juste après (database.SCHEMA).
        for l in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' "
                              "AND tbl_name IN (%s)" % ",".join("?" * len(tables)), tables).fetchall():
            conn.execute(f'DROP TRIGGER IF EXISTS "{l[0]}"')
        with conn:
            if getattr(conn, "backend", "") == "postgresql":     # TRUNCATE : tout d'un coup (clés étrangères respectées), compteurs remis à 1
                conn.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY")
            else:
                for t in tables:
                    conn.execute(f'DELETE FROM "{t}"')
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone():
                conn.execute("DELETE FROM sqlite_sequence WHERE name IN (%s)" % ",".join("?" * len(tables)), tables)
            if comptes_aussi:
                conn.execute("DELETE FROM DROIT WHERE ID_USER <> ?", (session.id_user,))
                conn.execute("DELETE FROM PERCEPTEUR WHERE ID_USER <> ?", (session.id_user,))
                conn.execute("DELETE FROM UTILISATEUR WHERE ID_USER <> ?", (session.id_user,))
                conn.execute("DELETE FROM TENTATIVE_CONNEXION")
                conn.execute("DELETE FROM DONNEE_ESSAI")
                conn.execute("DELETE FROM CODE_RECUPERATION WHERE ID_USER <> ?", (session.id_user,))
                conn.execute("DELETE FROM ROLE")
                conn.execute("DELETE FROM ROLE_DROIT")
                for role in config.ROLES:
                    droits.remplacer_droits_role(conn, role, droits.droits_config(role))
            journaliser(conn, session.id_user, session.login, "APPLICATION_REINITIALISEE",
                        ("données scolaires + autres comptes et rôles" if comptes_aussi else "données scolaires")
                        + f" | sécurité : {securite.name}")
    finally:
        try:
            conn.executescript(database.SCHEMA)               # remet les protections des reçus
        finally:
            conn.execute(f"PRAGMA foreign_keys = {'ON' if fk else 'OFF'}")
    return {"effaces": effaces, "securite": securite}

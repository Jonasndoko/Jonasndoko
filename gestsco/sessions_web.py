"""Sessions de l'application web : stockées dans un petit fichier SQLite à part (sessions_web.db), donc valables quel que soit le nombre
de processus de l'hébergeur. Seul l'empreinte SHA-256 du jeton est conservée (un vol du fichier ne donne aucun jeton utilisable).
Les identités (rôle, droits) sont toujours relues dans la base principale : une désactivation de compte coupe la session aussitôt."""
import hashlib
import secrets
import sqlite3
from datetime import timedelta

import config
import database
from database import iso, lire_iso, maintenant
from security import Session

ECHECS_MAX_PAR_ADRESSE = 25
FENETRE_ECHECS = timedelta(minutes=10)
SESSIONS_MAX = 10000


def _connexion():
    c = sqlite3.connect(config.dossier_donnees() / "sessions_web.db", timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS SESSION_WEB (EMPREINTE TEXT PRIMARY KEY, ID_USER INTEGER NOT NULL, "
              "TYPE TEXT NOT NULL, DERNIERE TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS ECHEC_ADRESSE (ADRESSE TEXT NOT NULL, QUAND TEXT NOT NULL)")
    return c


def _empreinte(jeton: str) -> str:
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


def _delai(type_):
    if type_ == "PARENT":
        return timedelta(days=config.DELAI_INACTIVITE_PARENT_JOURS)
    if type_ == "CTRL":
        return timedelta(minutes=config.DELAI_INACTIVITE_CTRL_MIN)
    return timedelta(minutes=config.DELAI_INACTIVITE_PROF_MIN if type_ == "PROF" else config.DELAI_INACTIVITE_MIN)


def ouvrir(id_user: int, type_: str = "PERSONNEL") -> str:
    """Crée une session et retourne le jeton (à poser dans un cookie ou à renvoyer à la page des professeurs)."""
    jeton = secrets.token_urlsafe(32)
    c = _connexion()
    try:
        with c:
            for e, t, d in [(l["EMPREINTE"], l["TYPE"], l["DERNIERE"]) for l in c.execute("SELECT * FROM SESSION_WEB")]:
                if maintenant() - lire_iso(d) > _delai(t):
                    c.execute("DELETE FROM SESSION_WEB WHERE EMPREINTE = ?", (e,))
            if c.execute("SELECT COUNT(*) FROM SESSION_WEB").fetchone()[0] >= SESSIONS_MAX:
                raise RuntimeError("Le serveur est occupé : réessayez dans quelques minutes.")
            c.execute("INSERT INTO SESSION_WEB VALUES (?,?,?,?)", (_empreinte(jeton), id_user, type_, iso(maintenant())))
    finally:
        c.close()
    return jeton


def retrouver(conn, jeton: str, type_: str = None):
    """Session valide (et prolongée) pour ce jeton, ou None. `conn` : base principale."""
    if not jeton:
        return None
    c = _connexion()
    try:
        l = c.execute("SELECT * FROM SESSION_WEB WHERE EMPREINTE = ?", (_empreinte(jeton),)).fetchone()
        if l is None or (type_ and l["TYPE"] != type_):
            return None
        if maintenant() - lire_iso(l["DERNIERE"]) > _delai(l["TYPE"]):
            with c:
                c.execute("DELETE FROM SESSION_WEB WHERE EMPREINTE = ?", (l["EMPREINTE"],))
            return None
        with c:
            c.execute("UPDATE SESSION_WEB SET DERNIERE = ? WHERE EMPREINTE = ?", (iso(maintenant()), l["EMPREINTE"]))
    finally:
        c.close()
    u = conn.execute("SELECT * FROM UTILISATEUR WHERE ID_USER = ? AND ACTIF = 1", (l["ID_USER"],)).fetchone()
    if u is None:
        fermer(jeton)
        return None
    import droits
    return Session(u["ID_USER"], u["LOGIN"], u["NOM_COMPLET"], u["ROLE"], bool(u["DOIT_CHANGER_MDP"]),
                   libelle_poste=droits.libelle_role(conn, u["ROLE"]))


def retrouver_id(jeton: str, type_: str):
    """Identifiant (ID_USER de la session) d'un jeton valide du type demandé, prolongé ; None sinon. Sans lien avec la table
    UTILISATEUR : sert aux sessions des parents (type PARENT), dont l'identifiant est un ID_PARENT."""
    if not jeton:
        return None
    c = _connexion()
    try:
        l = c.execute("SELECT * FROM SESSION_WEB WHERE EMPREINTE = ? AND TYPE = ?", (_empreinte(jeton), type_)).fetchone()
        if l is None:
            return None
        if maintenant() - lire_iso(l["DERNIERE"]) > _delai(l["TYPE"]):
            with c:
                c.execute("DELETE FROM SESSION_WEB WHERE EMPREINTE = ?", (l["EMPREINTE"],))
            return None
        with c:
            c.execute("UPDATE SESSION_WEB SET DERNIERE = ? WHERE EMPREINTE = ?", (iso(maintenant()), l["EMPREINTE"]))
        return l["ID_USER"]
    finally:
        c.close()


def fermer_toutes(id_user: int, type_: str):
    """Ferme toutes les sessions d'un identifiant (changement de mot de passe d'un parent)."""
    c = _connexion()
    try:
        with c:
            c.execute("DELETE FROM SESSION_WEB WHERE ID_USER = ? AND TYPE = ?", (id_user, type_))
    finally:
        c.close()


def fermer_tout():
    """Ferme TOUTES les sessions (après une restauration : les comptes de la base restaurée peuvent être différents)."""
    c = _connexion()
    try:
        with c:
            c.execute("DELETE FROM SESSION_WEB")
    finally:
        c.close()


def fermer(jeton: str):
    c = _connexion()
    try:
        with c:
            c.execute("DELETE FROM SESSION_WEB WHERE EMPREINTE = ?", (_empreinte(jeton or ""),))
    finally:
        c.close()


def trop_d_echecs(adresse: str) -> bool:
    c = _connexion()
    try:
        limite = iso(maintenant() - FENETRE_ECHECS)
        with c:
            c.execute("DELETE FROM ECHEC_ADRESSE WHERE QUAND < ?", (limite,))
        return c.execute("SELECT COUNT(*) FROM ECHEC_ADRESSE WHERE ADRESSE = ?", (adresse,)).fetchone()[0] >= ECHECS_MAX_PAR_ADRESSE
    finally:
        c.close()


def noter_echec(adresse: str):
    c = _connexion()
    try:
        with c:
            c.execute("INSERT INTO ECHEC_ADRESSE VALUES (?,?)", (adresse, iso(maintenant())))
    finally:
        c.close()

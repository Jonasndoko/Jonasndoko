"""Droit d'accès : l'administrateur crée les comptes et accorde les droits. Toutes les fonctions refusent
tout autre poste, et refusent aussi un administrateur dont le compte a été désactivé entre-temps."""
import config
import droits
import security
from database import journaliser


class ErreurAcces(Exception):
    """Erreur métier dont le message peut être affiché tel quel."""


def lister_utilisateurs(conn, session) -> list:
    droits.exiger_admin(conn, session)
    return conn.execute(
        "SELECT ID_USER, LOGIN, NOM_COMPLET, ROLE, ACTIF, DOIT_CHANGER_MDP, DATE_CREATION, DERNIERE_CONNEXION, "
        "       (SELECT BLOQUE_JUSQUA FROM TENTATIVE_CONNEXION T WHERE T.LOGIN = U.LOGIN) AS BLOQUE_JUSQUA "
        "FROM UTILISATEUR U ORDER BY U.NOM_COMPLET COLLATE NOCASE").fetchall()


def _utilisateur(conn, id_user):
    ligne = conn.execute("SELECT * FROM UTILISATEUR WHERE ID_USER = ?", (id_user,)).fetchone()
    if not ligne:
        raise ErreurAcces("Compte introuvable.")
    return ligne


def _autres_admins_actifs(conn, id_user) -> int:
    return conn.execute("SELECT COUNT(*) FROM UTILISATEUR WHERE ROLE = ? AND ACTIF = 1 AND ID_USER <> ?",
                        (config.ADMINISTRATEUR, id_user)).fetchone()[0]


def creer_compte(conn, session, login, nom_complet, poste):
    """Crée un compte avec un mot de passe provisoire (à changer à la première connexion) et les droits par
    défaut du poste. Retourne (id_user, mot de passe provisoire : à communiquer, il n'est plus jamais affiché)."""
    droits.exiger_admin(conn, session)
    mdp = security.generer_mdp_temporaire(login)
    try:
        id_user = security.creer_utilisateur(conn, login, nom_complet, poste, mdp, doit_changer=True,
                                             id_acteur=session.id_user)
    except ValueError as erreur:
        raise ErreurAcces(str(erreur)) from erreur
    return id_user, mdp


def modifier_compte(conn, session, id_user, nom_complet, poste, actif):
    """Modifie le nom, le poste et l'état (actif / désactivé) d'un compte.
    Si le poste change, les droits sont remis aux droits par défaut du nouveau poste."""
    droits.exiger_admin(conn, session)
    cible = _utilisateur(conn, id_user)
    nom_complet = " ".join((nom_complet or "").split())
    if len(nom_complet) < 3:
        raise ErreurAcces("Le nom complet est obligatoire.")
    if not droits.role_existe(conn, poste):
        raise ErreurAcces("Poste inconnu.")
    actif = bool(actif)
    if id_user == session.id_user and (poste != cible["ROLE"] or not actif):
        raise ErreurAcces("Vous ne pouvez pas changer votre propre poste ni désactiver votre propre compte.")
    quitte_admin = cible["ROLE"] == config.ADMINISTRATEUR and cible["ACTIF"] and (poste != cible["ROLE"] or not actif)
    if quitte_admin and _autres_admins_actifs(conn, id_user) == 0:
        raise ErreurAcces("Il doit toujours rester au moins un Administrateur actif.")
    with conn:
        conn.execute("UPDATE UTILISATEUR SET NOM_COMPLET = ?, ROLE = ?, ACTIF = ? WHERE ID_USER = ?",
                     (nom_complet, poste, int(actif), id_user))
        if not actif:
            conn.execute("DELETE FROM CODE_RECUPERATION WHERE ID_USER = ?", (id_user,))
        if poste == "PERCEPTEUR":
            conn.execute("INSERT OR IGNORE INTO PERCEPTEUR (ID_USER) VALUES (?)", (id_user,))
        if poste != cible["ROLE"]:
            droits.accorder_par_defaut(conn, id_user, poste)
        journaliser(conn, session.id_user, session.login, "COMPTE_MODIFIE",
                    f"{cible['LOGIN']} | poste {cible['ROLE']} -> {poste} | actif {cible['ACTIF']} -> {int(actif)}")


def changer_etat_compte(conn, session, id_user, actif):
    """Active ou désactive un compte (boutons « Activer » / « Désactiver »). Un compte désactivé ne peut plus se
    connecter ; son historique (reçus, journal) reste intact. On ne peut ni se désactiver soi-même ni désactiver le
    dernier Administrateur actif."""
    droits.exiger_admin(conn, session)
    cible = _utilisateur(conn, id_user)
    actif = bool(actif)
    if bool(cible["ACTIF"]) == actif:
        raise ErreurAcces("Ce compte est déjà " + ("actif." if actif else "désactivé."))
    if not actif:
        if id_user == session.id_user:
            raise ErreurAcces("Vous ne pouvez pas désactiver votre propre compte.")
        if cible["ROLE"] == config.ADMINISTRATEUR and _autres_admins_actifs(conn, id_user) == 0:
            raise ErreurAcces("Il doit toujours rester au moins un Administrateur actif.")
    with conn:
        conn.execute("UPDATE UTILISATEUR SET ACTIF = ? WHERE ID_USER = ?", (int(actif), id_user))
        if not actif:
            conn.execute("DELETE FROM CODE_RECUPERATION WHERE ID_USER = ?", (id_user,))
        journaliser(conn, session.id_user, session.login, "COMPTE_ACTIVE" if actif else "COMPTE_DESACTIVE", cible["LOGIN"])


def reinitialiser_mdp(conn, session, id_user) -> str:
    """Nouveau mot de passe provisoire (changement obligatoire à la prochaine connexion) ; lève aussi le blocage."""
    droits.exiger_admin(conn, session)
    cible = _utilisateur(conn, id_user)
    mdp = security.generer_mdp_temporaire(cible["LOGIN"])
    with conn:
        conn.execute("UPDATE UTILISATEUR SET MDP_HASH = ?, DOIT_CHANGER_MDP = 1 WHERE ID_USER = ?",
                     (security.hacher_mdp(mdp), id_user))
        conn.execute("DELETE FROM TENTATIVE_CONNEXION WHERE LOGIN = ?", (cible["LOGIN"],))
        conn.execute("DELETE FROM CODE_RECUPERATION WHERE ID_USER = ?", (id_user,))   # un code en cours n'a plus de sens
        journaliser(conn, session.id_user, session.login, "MDP_REINITIALISE", cible["LOGIN"])
    return mdp


def debloquer(conn, session, id_user):
    droits.exiger_admin(conn, session)
    cible = _utilisateur(conn, id_user)
    with conn:
        conn.execute("DELETE FROM TENTATIVE_CONNEXION WHERE LOGIN = ?", (cible["LOGIN"],))
        journaliser(conn, session.id_user, session.login, "COMPTE_DEBLOQUE", cible["LOGIN"])


def lire_droits(conn, session, id_user) -> set:
    droits.exiger_admin(conn, session)
    _utilisateur(conn, id_user)
    return droits.droits_utilisateur(conn, id_user)


def definir_droits(conn, session, id_user, accordes) -> set:
    """Remplace les droits du compte. Lecture est ajoutée d'office à tout module où un droit est accordé."""
    droits.exiger_admin(conn, session)
    cible = _utilisateur(conn, id_user)
    try:
        normalises = droits.normaliser(accordes)
    except ValueError as erreur:
        raise ErreurAcces(str(erreur)) from erreur
    with conn:
        droits.remplacer_droits(conn, id_user, normalises)
        journaliser(conn, session.id_user, session.login, "DROITS_MODIFIES",
                    f"{cible['LOGIN']} | {droits.resume(normalises)}")
    return normalises


def droits_par_defaut_du_poste(conn, session, id_user) -> set:
    droits.exiger_admin(conn, session)
    cible = _utilisateur(conn, id_user)
    return definir_droits(conn, session, id_user, droits.droits_par_defaut(conn, cible["ROLE"]))


# ------------------------------------------------------------------ rôles (droits de base de chaque poste)
def lister_roles(conn, session) -> list:
    """Tous les postes (7 de base + ceux créés) : [{role, libelle, nb_utilisateurs (actifs), droits, de_base}]."""
    droits.exiger_admin(conn, session)
    nombres = {l["ROLE"]: l["N"] for l in conn.execute(
        "SELECT ROLE, COUNT(*) AS N FROM UTILISATEUR WHERE ACTIF = 1 GROUP BY ROLE")}
    return [{"role": r, "libelle": libelle, "nb_utilisateurs": nombres.get(r, 0),
             "droits": droits.droits_par_defaut(conn, r), "de_base": r in config.ROLES}
            for r, libelle in droits.roles(conn).items()]


def _code_role(libelle) -> str:
    """Code interne d'un rôle : majuscules sans accents, chiffres et _ (ex. « Chef de discipline » -> CHEF_DE_DISCIPLINE)."""
    import re
    import unicodedata
    texte = unicodedata.normalize("NFD", libelle).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", "_", texte).strip("_")


def creer_role(conn, session, libelle, accordes=()):
    """Crée un nouveau rôle (poste) avec ses droits de base. Retourne son code."""
    droits.exiger_admin(conn, session)
    libelle = " ".join((libelle or "").split())
    if not 3 <= len(libelle) <= 40:
        raise ErreurAcces("Le nom du rôle doit avoir entre 3 et 40 caractères.")
    code = _code_role(libelle)
    if len(code) < 3:
        raise ErreurAcces("Le nom du rôle doit contenir des lettres ou des chiffres.")
    existants = droits.roles(conn)
    if code in existants or libelle.lower() in {l.lower() for l in existants.values()}:
        raise ErreurAcces("Ce rôle existe déjà.")
    try:
        normalises = droits.normaliser(accordes)
    except ValueError as erreur:
        raise ErreurAcces(str(erreur)) from erreur
    with conn:
        conn.execute("INSERT INTO ROLE (CODE, LIBELLE) VALUES (?,?)", (code, libelle))
        droits.remplacer_droits_role(conn, code, normalises)
        journaliser(conn, session.id_user, session.login, "ROLE_CREE", f"{code} | {libelle}")
    return code


def supprimer_role(conn, session, code):
    """Supprime un rôle créé par l'administrateur, à condition qu'aucun compte ne l'utilise.
    Les 8 postes de base ne se suppriment pas."""
    droits.exiger_admin(conn, session)
    if code in config.ROLES:
        raise ErreurAcces("Les 8 postes de base ne peuvent pas être supprimés.")
    if code not in droits.roles(conn):
        raise ErreurAcces("Rôle introuvable.")
    n = conn.execute("SELECT COUNT(*) FROM UTILISATEUR WHERE ROLE = ?", (code,)).fetchone()[0]
    if n:
        raise ErreurAcces(f"Ce rôle est donné à {n} compte(s) : changez d'abord leur rôle (Utilisateurs > Modifier).")
    with conn:
        conn.execute("DELETE FROM ROLE_DROIT WHERE ROLE = ?", (code,))
        conn.execute("DELETE FROM ROLE WHERE CODE = ?", (code,))
        journaliser(conn, session.id_user, session.login, "ROLE_SUPPRIME", code)


def definir_droits_role(conn, session, role, accordes, appliquer_aux_utilisateurs=False):
    """Règle les droits de base d'un poste (valables pour les futurs comptes et les changements de poste).
    Si `appliquer_aux_utilisateurs`, les comptes existants de ce poste reçoivent aussi ces droits (leurs réglages
    individuels sont écrasés). Retourne (droits enregistrés, nombre de comptes mis à jour)."""
    droits.exiger_admin(conn, session)
    if not droits.role_existe(conn, role):
        raise ErreurAcces("Poste inconnu.")
    try:
        normalises = droits.normaliser(accordes)
    except ValueError as erreur:
        raise ErreurAcces(str(erreur)) from erreur
    with conn:
        droits.remplacer_droits_role(conn, role, normalises)
        ids = [l["ID_USER"] for l in conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE ROLE = ?", (role,))] \
            if appliquer_aux_utilisateurs else []
        for id_user in ids:
            droits.remplacer_droits(conn, id_user, normalises)
        journaliser(conn, session.id_user, session.login, "DROITS_ROLE_MODIFIES",
                    f"{role} | {droits.resume(normalises)} | appliqué à {len(ids)} compte(s)")
    return normalises, len(ids)

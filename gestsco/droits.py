"""Droits d'accès : qui a le droit de faire quoi, module par module.

Les droits sont toujours relus dans la base au moment de l'action (jamais gardés en mémoire dans la session) :
si l'administrateur retire un droit ou désactive un compte, l'effet est immédiat, même pour quelqu'un de connecté.
"""
import sqlite3

import config


def _utilisateur_actif(conn, session):
    """Ligne UTILISATEUR de la session, ou None si le compte n'existe plus, est désactivé,
    ou si le poste de la session ne correspond pas à celui de la base (session falsifiée)."""
    if session is None:
        return None
    ligne = conn.execute("SELECT ID_USER, ROLE, ACTIF FROM UTILISATEUR WHERE ID_USER = ?",
                         (session.id_user,)).fetchone()
    if not ligne or not ligne["ACTIF"] or ligne["ROLE"] != session.role:
        return None
    return ligne


# ------------------------------------------------------------------ rôles (postes)
def roles(conn) -> dict:
    """{code: libellé} : les 8 postes de base, puis les rôles créés par l'administrateur (par ordre alphabétique)."""
    resultat = {r: config.LIBELLE_ROLES[r] for r in config.ROLES}
    try:
        for l in conn.execute("SELECT CODE, LIBELLE FROM ROLE ORDER BY LIBELLE COLLATE NOCASE"):
            resultat[l[0]] = l[1]
    except sqlite3.OperationalError:                  # table pas encore créée (base en cours de mise à jour)
        pass
    return resultat


def libelle_role(conn, code) -> str:
    return roles(conn).get(code, code)


def role_existe(conn, code) -> bool:
    return code in roles(conn)


# ------------------------------------------------------------------ administrateur
def est_admin(conn, session) -> bool:
    ligne = _utilisateur_actif(conn, session)
    return bool(ligne and ligne["ROLE"] == config.ADMINISTRATEUR)


def exiger_admin(conn, session):
    if not est_admin(conn, session):
        raise PermissionError("Accès refusé : cette opération est réservée à l'Administrateur.")


# ------------------------------------------------------------------ droits par module
def droits_utilisateur(conn, id_user) -> set:
    """Ensemble de couples (module, droit) accordés à un compte."""
    return {(l["MODULE"], l["DROIT"]) for l in
            conn.execute("SELECT MODULE, DROIT FROM DROIT WHERE ID_USER = ?", (id_user,))}


def a_droit(conn, session, module, droit) -> bool:
    if not _utilisateur_actif(conn, session):
        return False
    return conn.execute("SELECT 1 FROM DROIT WHERE ID_USER = ? AND MODULE = ? AND DROIT = ?",
                        (session.id_user, module, droit)).fetchone() is not None


def exiger_droit(conn, session, module, droit):
    if not a_droit(conn, session, module, droit):
        titre = config.MODULES_DROITS.get(module, (module,))[0]
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS.get(droit, droit)} » "
                              f"sur le module « {titre} ».")


# ------------------------------------------------------------------ attribution
def droits_config(role) -> set:
    """Droits de base d'origine (config.py), avant toute modification par l'administrateur."""
    return {(module, droit) for module, liste in config.DROITS_PAR_DEFAUT.get(role, {}).items() for droit in liste}


def droits_par_defaut(conn, role) -> set:
    """Droits de base du rôle, tels que réglés par l'administrateur (table ROLE_DROIT)."""
    try:
        return {(l[0], l[1]) for l in conn.execute("SELECT MODULE, DROIT FROM ROLE_DROIT WHERE ROLE = ?", (role,))}
    except sqlite3.OperationalError:                  # table pas encore créée (base en cours de mise à jour)
        return droits_config(role)


def remplacer_droits_role(conn, role, droits):
    """Remplace les droits de base du rôle. Ne valide pas la transaction."""
    droits = normaliser(droits)
    conn.execute("DELETE FROM ROLE_DROIT WHERE ROLE = ?", (role,))
    conn.executemany("INSERT INTO ROLE_DROIT (ROLE, MODULE, DROIT) VALUES (?,?,?)",
                     [(role, m, d) for m, d in sorted(droits)])


def normaliser(droits) -> set:
    """Valide les couples (module, droit) et ajoute LECTURE à tout module où un droit est accordé
    (on ne peut ni ajouter, ni imprimer… ce qu'on n'a pas le droit de voir). Lève ValueError si invalide."""
    resultat = set()
    for module, droit in droits:
        if module not in config.MODULES_DROITS:
            raise ValueError(f"Module inconnu : {module}")
        if droit not in config.MODULES_DROITS[module][1]:
            raise ValueError(f"Le droit « {config.LIBELLE_DROITS.get(droit, droit)} » n'existe pas "
                             f"dans le module « {config.MODULES_DROITS[module][0]} ».")
        resultat.add((module, droit))
    for module in {m for m, _ in resultat}:
        resultat.add((module, "LECTURE"))
    return resultat


def remplacer_droits(conn, id_user, droits):
    """Remplace tous les droits du compte. Ne valide pas la transaction (c'est l'appelant qui le fait)."""
    droits = normaliser(droits)
    conn.execute("DELETE FROM DROIT WHERE ID_USER = ?", (id_user,))
    conn.executemany("INSERT INTO DROIT (ID_USER, MODULE, DROIT) VALUES (?,?,?)",
                     [(id_user, m, d) for m, d in sorted(droits)])


def accorder_par_defaut(conn, id_user, role):
    remplacer_droits(conn, id_user, droits_par_defaut(conn, role))


def resume(droits) -> str:
    """Texte lisible : « Paiement : Lecture, Ajout »."""
    lignes = []
    for module, (titre, possibles) in config.MODULES_DROITS.items():
        accordes = [config.LIBELLE_DROITS[d] for d in possibles if (module, d) in droits]
        if accordes:
            lignes.append(f"{titre} : {', '.join(accordes)}")
    return " | ".join(lignes) or "Aucun droit"

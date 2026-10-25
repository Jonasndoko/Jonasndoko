"""Récupération du mot de passe oublié par un CODE TEMPORAIRE (sans interface graphique : testable seul).

Déroulement
1. L'utilisateur a oublié son mot de passe : il prévient l'Administrateur.
2. L'Administrateur (Travaux techniques > Authentification et mots de passe) demande au système de générer un
   code de récupération pour ce compte, et le lui communique (de vive voix, jamais par écrit).
3. L'utilisateur clique sur « Mot de passe oublié ? » sur l'écran de connexion, saisit son identifiant, le code et
   choisit son nouveau mot de passe.

Règles de sécurité
- Le code est fabriqué par le système (générateur cryptographique) ; personne ne le choisit.
- Il est valable `config.DUREE_CODE_RECUPERATION_SEC` secondes (2 minutes) puis il DISPARAÎT : la ligne est supprimée
  de la base. Il n'est jamais stocké en clair (seulement son empreinte scrypt) : il n'est montré qu'une seule fois,
  à l'Administrateur, au moment de sa création.
- Un seul code par compte : en générer un nouveau détruit le précédent.
- Usage unique : un code qui a servi disparaît. Après `config.MAX_ESSAIS_CODE` essais faux, il est détruit.
- Le message d'échec est toujours le même (code faux, expiré, identifiant inconnu ou compte désactivé) : on ne
  révèle à personne si un code existe pour un compte.
- Tout est inscrit au journal (sans jamais écrire le code).
- Un compte ne peut pas se générer son propre code (il est déjà connecté : « Mon mot de passe » existe).
"""
import secrets
from datetime import timedelta

import config
import droits
import security
from database import iso, journaliser, lire_iso, maintenant

# Sans 0, 1, I, O (confusions à voix haute et à la lecture)
_ALPHABET_CODE = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

MESSAGE_ECHEC = "Code de récupération invalide ou expiré.\nDemandez-en un nouveau à l'Administrateur."


class ErreurRecuperation(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ------------------------------------------------------------------ présentation du code
def formater_code(code: str) -> str:
    """K7M4PQXR -> K7M4-PQXR (plus lisible ; le tiret est facultatif à la saisie)."""
    moitie = len(code) // 2
    return f"{code[:moitie]}-{code[moitie:]}"


def normaliser_code(texte: str) -> str:
    """Accepte minuscules, espaces et tirets : « k7m4 pqxr » -> K7M4PQXR."""
    return "".join(c for c in (texte or "").upper() if c.isalnum())


def _nouveau_code() -> str:
    return "".join(secrets.choice(_ALPHABET_CODE) for _ in range(config.LONGUEUR_CODE_RECUPERATION))


# ------------------------------------------------------------------ nettoyage
def purger_expires(conn) -> int:
    """Supprime de la base tous les codes dont les 2 minutes sont écoulées. Retourne leur nombre."""
    maintenant_iso = iso(maintenant())
    expires = conn.execute(
        "SELECT C.ID_USER, U.LOGIN FROM CODE_RECUPERATION C JOIN UTILISATEUR U ON U.ID_USER = C.ID_USER "
        "WHERE C.DATE_EXPIRATION <= ?", (maintenant_iso,)).fetchall()
    if not expires:
        return 0
    with conn:
        for e in expires:
            conn.execute("DELETE FROM CODE_RECUPERATION WHERE ID_USER = ?", (e["ID_USER"],))
            journaliser(conn, e["ID_USER"], e["LOGIN"], "CODE_RECUP_EXPIRE")
    return len(expires)


def supprimer_code(conn, id_user):
    """Détruit le code d'un compte, s'il en a un (sans journal : l'appelant journalise sa propre opération).
    Ne valide pas la transaction."""
    conn.execute("DELETE FROM CODE_RECUPERATION WHERE ID_USER = ?", (id_user,))


# ------------------------------------------------------------------ côté Administrateur
def generer_code(conn, session, id_user):
    """Génère un code pour un compte. Retourne (code en clair, secondes de validité).
    Le code en clair n'est renvoyé qu'ici : il n'existe nulle part ailleurs."""
    droits.exiger_admin(conn, session)
    cible = conn.execute("SELECT ID_USER, LOGIN, ACTIF FROM UTILISATEUR WHERE ID_USER = ?", (id_user,)).fetchone()
    if not cible:
        raise ErreurRecuperation("Compte introuvable.")
    if not cible["ACTIF"]:
        raise ErreurRecuperation("Ce compte est désactivé : réactivez-le d'abord (Gestionnaire d'accès).")
    if id_user == session.id_user:
        raise ErreurRecuperation("Vous ne pouvez pas générer un code pour votre propre compte "
                                 "(utilisez « Mon mot de passe » ; un autre Administrateur peut vous en générer un).")
    purger_expires(conn)
    code = _nouveau_code()
    maintenant_ = maintenant()
    expiration = maintenant_ + timedelta(seconds=config.DUREE_CODE_RECUPERATION_SEC)
    with conn:
        conn.execute("DELETE FROM CODE_RECUPERATION WHERE ID_USER = ?", (id_user,))      # un seul code par compte
        conn.execute("INSERT INTO CODE_RECUPERATION (ID_USER, CODE_HASH, DATE_CREATION, DATE_EXPIRATION, ESSAIS, CREE_PAR) "
                     "VALUES (?,?,?,?,0,?)",
                     (id_user, security.hacher_mdp(code), iso(maintenant_), iso(expiration), session.login))
        journaliser(conn, session.id_user, session.login, "CODE_RECUP_GENERE",
                    f"{cible['LOGIN']} | valable {config.DUREE_CODE_RECUPERATION_SEC} s")
    return code, config.DUREE_CODE_RECUPERATION_SEC


def annuler_code(conn, session, id_user):
    """L'Administrateur détruit le code avant son expiration (code donné à la mauvaise personne, par exemple)."""
    droits.exiger_admin(conn, session)
    cible = conn.execute("SELECT LOGIN FROM UTILISATEUR WHERE ID_USER = ?", (id_user,)).fetchone()
    if not cible:
        raise ErreurRecuperation("Compte introuvable.")
    existait = conn.execute("SELECT 1 FROM CODE_RECUPERATION WHERE ID_USER = ?", (id_user,)).fetchone()
    if not existait:
        raise ErreurRecuperation("Ce compte n'a pas de code de récupération en cours.")
    with conn:
        supprimer_code(conn, id_user)
        journaliser(conn, session.id_user, session.login, "CODE_RECUP_ANNULE", cible["LOGIN"])


def secondes_restantes(conn, id_user) -> int:
    """Secondes de validité qui restent au code du compte (0 : pas de code, ou expiré)."""
    ligne = conn.execute("SELECT DATE_EXPIRATION FROM CODE_RECUPERATION WHERE ID_USER = ?", (id_user,)).fetchone()
    if not ligne:
        return 0
    reste = (lire_iso(ligne["DATE_EXPIRATION"]) - maintenant()).total_seconds()
    return max(0, int(reste) + (1 if reste % 1 else 0))


def codes_en_cours(conn, session) -> dict:
    """{id_user: secondes restantes} des codes encore valables (les expirés sont détruits au passage)."""
    droits.exiger_admin(conn, session)
    purger_expires(conn)
    return {l["ID_USER"]: secondes_restantes(conn, l["ID_USER"])
            for l in conn.execute("SELECT ID_USER FROM CODE_RECUPERATION")}


def journal_authentification(conn, session, limite=60) -> list:
    """Dernières opérations d'authentification (connexions, échecs, blocages, mots de passe, codes de récupération)."""
    droits.exiger_admin(conn, session)
    return conn.execute(
        "SELECT DATE_HEURE, LOGIN, ACTION, DETAIL FROM JOURNAL WHERE ACTION LIKE 'CONNEXION%' OR ACTION LIKE 'MDP_%' "
        "OR ACTION LIKE 'CODE_RECUP_%' OR ACTION LIKE 'COMPTE_%' ORDER BY ID_LOG DESC LIMIT ?", (int(limite),)).fetchall()


LIBELLES_ACTIONS = {
    "CONNEXION_OK": "Connexion réussie",
    "CONNEXION_ECHEC": "Connexion échouée",
    "CONNEXION_REFUSEE_BLOCAGE": "Connexion refusée (compte bloqué)",
    "MDP_CHANGE": "Mot de passe changé",
    "MDP_CHANGEMENT_REFUSE": "Changement de mot de passe refusé",
    "MDP_REINITIALISE": "Mot de passe provisoire donné",
    "MDP_RECUPERE": "Mot de passe récupéré avec un code",
    "CODE_RECUP_GENERE": "Code de récupération généré",
    "CODE_RECUP_ANNULE": "Code de récupération annulé",
    "CODE_RECUP_EXPIRE": "Code de récupération expiré (détruit)",
    "CODE_RECUP_UTILISE": "Code de récupération utilisé",
    "CODE_RECUP_ECHEC": "Code de récupération refusé",
    "CODE_RECUP_DETRUIT": "Code détruit (trop d'essais faux)",
    "COMPTE_CREE": "Compte créé",
    "COMPTE_MODIFIE": "Compte modifié",
    "COMPTE_ACTIVE": "Compte activé",
    "COMPTE_DESACTIVE": "Compte désactivé",
    "COMPTE_DEBLOQUE": "Compte débloqué",
}


# ------------------------------------------------------------------ côté utilisateur (écran de connexion)
def recuperer_mdp(conn, login, code, nouveau, confirmation=None):
    """Change le mot de passe grâce au code reçu de l'Administrateur. Lève ErreurRecuperation (message affichable).

    Ordre des contrôles : d'abord ce qui ne dépend que de la saisie (champs, confirmation, politique du mot de passe :
    un mot de passe trop faible ne brûle pas le code), puis le code, puis seulement après un code valide, la
    comparaison avec l'ancien mot de passe (sinon cela donnerait un moyen de tester l'ancien mot de passe sans code).
    """
    login_n = security.normaliser_login(login)
    code_n = normaliser_code(code)
    if not login_n or not code_n:
        raise ErreurRecuperation("Saisissez votre identifiant et le code de récupération.")
    if confirmation is not None and nouveau != confirmation:
        raise ErreurRecuperation("Les deux nouveaux mots de passe ne sont pas identiques.")
    problemes = security.verifier_politique(nouveau or "", login_n)
    if problemes:
        raise ErreurRecuperation("Mot de passe trop faible :\n- " + "\n- ".join(problemes))

    purger_expires(conn)
    utilisateur = conn.execute("SELECT * FROM UTILISATEUR WHERE LOGIN = ?", (login_n,)).fetchone()
    ligne = (conn.execute("SELECT * FROM CODE_RECUPERATION WHERE ID_USER = ?", (utilisateur["ID_USER"],)).fetchone()
             if utilisateur and utilisateur["ACTIF"] else None)

    # Toujours un calcul scrypt complet, que le compte ait un code ou non : même temps de réponse.
    hash_stocke = ligne["CODE_HASH"] if ligne else security._hash_factice_pour_temps_constant()
    valide = security.verifier_mdp(code_n, hash_stocke) and ligne is not None

    if not valide:
        with conn:
            detail = ""
            if ligne:
                essais = ligne["ESSAIS"] + 1
                if essais >= config.MAX_ESSAIS_CODE:
                    supprimer_code(conn, ligne["ID_USER"])
                    detail = "code détruit : trop d'essais faux"
                    journaliser(conn, ligne["ID_USER"], login_n, "CODE_RECUP_DETRUIT", detail)
                else:
                    conn.execute("UPDATE CODE_RECUPERATION SET ESSAIS = ? WHERE ID_USER = ?",
                                 (essais, ligne["ID_USER"]))
            journaliser(conn, utilisateur["ID_USER"] if utilisateur else None, login_n, "CODE_RECUP_ECHEC", detail)
        raise ErreurRecuperation(MESSAGE_ECHEC)

    if security.verifier_mdp(nouveau, utilisateur["MDP_HASH"]):
        raise ErreurRecuperation("Le nouveau mot de passe doit être différent de l'ancien.")

    with conn:
        conn.execute("UPDATE UTILISATEUR SET MDP_HASH = ?, DOIT_CHANGER_MDP = 0 WHERE ID_USER = ?",
                     (security.hacher_mdp(nouveau), utilisateur["ID_USER"]))
        conn.execute("DELETE FROM TENTATIVE_CONNEXION WHERE LOGIN = ?", (utilisateur["LOGIN"],))   # lève un blocage
        supprimer_code(conn, utilisateur["ID_USER"])                                              # usage unique
        journaliser(conn, utilisateur["ID_USER"], utilisateur["LOGIN"], "CODE_RECUP_UTILISE")
        journaliser(conn, utilisateur["ID_USER"], utilisateur["LOGIN"], "MDP_RECUPERE")

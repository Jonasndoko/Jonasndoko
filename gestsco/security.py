"""Sécurité : hachage des mots de passe, politique, blocage anti-force-brute, sessions."""
import base64
import hashlib
import hmac
import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import config
import droits
from database import iso, journaliser, lire_iso, maintenant

# ------------------------------------------------------------------ hachage
# scrypt (fonction « memory-hard » résistante aux attaques par GPU), sel aléatoire unique par compte.
SCRYPT_N, SCRYPT_R, SCRYPT_P, DKLEN = 2 ** 15, 8, 1, 32
SCRYPT_MAXMEM = 2 ** 27

MESSAGE_ECHEC = "Identifiant, mot de passe ou poste incorrect."


def _b64(donnees: bytes) -> str:
    return base64.b64encode(donnees).decode("ascii")


def _octets_mdp(mdp: str) -> bytes:
    return unicodedata.normalize("NFKC", mdp).encode("utf-8")


def hacher_mdp(mdp: str, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P) -> str:
    sel = secrets.token_bytes(16)
    empreinte = hashlib.scrypt(_octets_mdp(mdp), salt=sel, n=n, r=r, p=p, dklen=DKLEN, maxmem=SCRYPT_MAXMEM)
    return f"scrypt${n}${r}${p}${_b64(sel)}${_b64(empreinte)}"


def verifier_mdp(mdp: str, stocke: str) -> bool:
    """Comparaison en temps constant. Retourne False (jamais d'exception) si le format est invalide."""
    try:
        algo, n, r, p, sel, attendu = stocke.split("$")
        if algo != "scrypt":
            return False
        attendu = base64.b64decode(attendu)
        calcule = hashlib.scrypt(_octets_mdp(mdp), salt=base64.b64decode(sel), n=int(n), r=int(r),
                                 p=int(p), dklen=len(attendu), maxmem=SCRYPT_MAXMEM)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calcule, attendu)


def hash_a_renouveler(stocke: str) -> bool:
    """Vrai si le hash a été fait avec des paramètres plus faibles que les paramètres actuels."""
    try:
        _, n, r, p, _, _ = stocke.split("$")
        return (int(n), int(r), int(p)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P)
    except ValueError:
        return True


_hash_factice = None


def _hash_factice_pour_temps_constant() -> str:
    """Hash jeté, utilisé quand l'identifiant n'existe pas : le temps de réponse reste identique."""
    global _hash_factice
    if _hash_factice is None:
        _hash_factice = hacher_mdp(secrets.token_urlsafe(24))
    return _hash_factice


# ------------------------------------------------------------------ politique
MOTS_INTERDITS = ("password", "motdepasse", "azerty", "qwerty", "123456", "admin",
                  "bienvenue", "welcome")
RE_LOGIN = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def exigences_mdp(mdp: str, login: str = ""):
    """Liste de (texte, respectée ?) - sert à la fois à la validation et à l'affichage en direct."""
    simple = _sans_accents(mdp)
    login_s = _sans_accents(login.strip())
    ecole = "".join(c for c in _sans_accents(config.NOM_ECOLE) if c.isalnum())         # le nom de l'école est un mot de passe trop prévisible
    interdits = MOTS_INTERDITS + ((ecole,) if len(ecole) >= 6 else ())
    return [
        (f"Au moins {config.LONGUEUR_MIN_MDP} caractères", len(mdp) >= config.LONGUEUR_MIN_MDP),
        ("Une lettre minuscule", any(c.islower() for c in mdp)),
        ("Une lettre majuscule", any(c.isupper() for c in mdp)),
        ("Un chiffre", any(c.isdigit() for c in mdp)),
        ("Un symbole (ex : ! ? # @ %)", any(not c.isalnum() and not c.isspace() for c in mdp)),
        ("Ne contient ni l'identifiant ni un mot trop courant",
         not any(m in simple for m in interdits) and not (len(login_s) >= 3 and login_s in simple)),
        ("Pas de caractère répété 4 fois de suite", re.search(r"(.)\1{3,}", mdp) is None),
    ]


def verifier_politique(mdp: str, login: str = ""):
    problemes = [t for t, ok in exigences_mdp(mdp, login) if not ok]
    if len(mdp) > config.LONGUEUR_MAX_MDP:
        problemes.append(f"Au plus {config.LONGUEUR_MAX_MDP} caractères")
    return problemes


# ------------------------------------------------------------------ utilisateurs
def normaliser_login(login: str) -> str:
    return unicodedata.normalize("NFKC", login or "").strip()[:64]


def aucun_utilisateur(conn) -> bool:
    return conn.execute("SELECT COUNT(*) FROM UTILISATEUR").fetchone()[0] == 0


def aucun_administrateur(conn) -> bool:
    """Vrai tant qu'aucun compte Administrateur actif n'existe (écran « Premier démarrage »)."""
    return conn.execute("SELECT COUNT(*) FROM UTILISATEUR WHERE ROLE = ? AND ACTIF = 1",
                        (config.ADMINISTRATEUR,)).fetchone()[0] == 0


_ALPHABET_LETTRES = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz"     # sans I, l, O, o : lisible à voix haute
_ALPHABET_CHIFFRES = "23456789"


def generer_mdp_temporaire(login: str = "") -> str:
    """Mot de passe provisoire conforme à la politique, sans caractères ambigus. Ex. : Kfmtp-Xe7wRq#58"""
    while True:
        lettres = "".join(secrets.choice(_ALPHABET_LETTRES) for _ in range(5)) + "-" + \
                  "".join(secrets.choice(_ALPHABET_LETTRES) for _ in range(5))
        mdp = lettres + secrets.choice("#@%!") + "".join(secrets.choice(_ALPHABET_CHIFFRES) for _ in range(2))
        if not verifier_politique(mdp, login):
            return mdp


def changer_mdp(conn, session, ancien: str, nouveau: str, confirmation: str = None):
    """Changement de mot de passe par l'utilisateur lui-même. Lève ValueError (message affichable)."""
    ligne = conn.execute("SELECT MDP_HASH FROM UTILISATEUR WHERE ID_USER = ? AND ACTIF = 1", (session.id_user,)).fetchone()
    if not ligne or not verifier_mdp(ancien or "", ligne["MDP_HASH"]):
        with conn:
            journaliser(conn, session.id_user, session.login, "MDP_CHANGEMENT_REFUSE")
        raise ValueError("Le mot de passe actuel est incorrect.")
    if confirmation is not None and nouveau != confirmation:
        raise ValueError("Les deux nouveaux mots de passe ne sont pas identiques.")
    if nouveau == ancien:
        raise ValueError("Le nouveau mot de passe doit être différent de l'actuel.")
    problemes = verifier_politique(nouveau, session.login)
    if problemes:
        raise ValueError("Mot de passe trop faible :\n- " + "\n- ".join(problemes))
    with conn:
        conn.execute("UPDATE UTILISATEUR SET MDP_HASH = ?, DOIT_CHANGER_MDP = 0 WHERE ID_USER = ?",
                     (hacher_mdp(nouveau), session.id_user))
        conn.execute("DELETE FROM CODE_RECUPERATION WHERE ID_USER = ?", (session.id_user,))
        journaliser(conn, session.id_user, session.login, "MDP_CHANGE")
    session.doit_changer_mdp = False


def creer_utilisateur(conn, login, nom_complet, role, mdp, doit_changer=False, id_acteur=None):
    """Crée un compte. Lève ValueError (message affichable) si une règle n'est pas respectée."""
    login = normaliser_login(login)
    nom_complet = " ".join((nom_complet or "").split())
    if not RE_LOGIN.match(login):
        raise ValueError("L'identifiant doit avoir 3 à 32 caractères : lettres, chiffres, point, tiret ou _.")
    if len(nom_complet) < 3:
        raise ValueError("Le nom complet est obligatoire.")
    if not droits.role_existe(conn, role):
        raise ValueError("Rôle inconnu.")
    problemes = verifier_politique(mdp, login)
    if problemes:
        raise ValueError("Mot de passe trop faible :\n- " + "\n- ".join(problemes))
    if conn.execute("SELECT 1 FROM UTILISATEUR WHERE LOGIN = ?", (login,)).fetchone():
        raise ValueError("Cet identifiant existe déjà.")
    with conn:
        curseur = conn.execute(
            "INSERT INTO UTILISATEUR (LOGIN, NOM_COMPLET, ROLE, MDP_HASH, DOIT_CHANGER_MDP, DATE_CREATION) "
            "VALUES (?,?,?,?,?,?)",
            (login, nom_complet, role, hacher_mdp(mdp), int(doit_changer), iso(maintenant())),
        )
        if role == "PERCEPTEUR":
            conn.execute("INSERT INTO PERCEPTEUR (ID_USER) VALUES (?)", (curseur.lastrowid,))
        droits.accorder_par_defaut(conn, curseur.lastrowid, role)
        journaliser(conn, id_acteur or curseur.lastrowid, login, "COMPTE_CREE", f"rôle={role}")
    return curseur.lastrowid


# ------------------------------------------------------------------ session
@dataclass
class Session:
    id_user: int
    login: str
    nom_complet: str
    role: str
    doit_changer_mdp: bool = False
    derniere_activite: datetime = field(default_factory=maintenant)
    libelle_poste: str = ""

    def toucher(self):
        self.derniere_activite = maintenant()

    def expiree(self) -> bool:
        return maintenant() - self.derniere_activite > timedelta(minutes=config.DELAI_INACTIVITE_MIN)

    @property
    def libelle_role(self) -> str:
        return self.libelle_poste or config.LIBELLE_ROLES.get(self.role, self.role)


@dataclass
class ResultatConnexion:
    ok: bool
    message: str = ""
    session: Session = None
    secondes_blocage: int = 0


def exiger_role(session, *roles):
    """Contrôle d'accès côté logique métier (en plus du masquage des menus dans l'interface)."""
    if session is None or session.role not in roles:
        raise PermissionError("Accès refusé : cette opération est réservée au rôle "
                              + " / ".join(config.LIBELLE_ROLES.get(r, r) for r in roles) + ".")


def fermer_session(conn, session: Session, motif="DECONNEXION"):
    with conn:
        journaliser(conn, session.id_user, session.login, motif)


# ------------------------------------------------------------------ authentification
def _secondes_blocage_restantes(conn, login_n: str) -> int:
    ligne = conn.execute("SELECT BLOQUE_JUSQUA FROM TENTATIVE_CONNEXION WHERE LOGIN = ?", (login_n,)).fetchone()
    if not ligne or not ligne["BLOQUE_JUSQUA"]:
        return 0
    reste = (lire_iso(ligne["BLOQUE_JUSQUA"]) - maintenant()).total_seconds()
    return max(0, int(reste) + (1 if reste % 1 else 0))


def _enregistrer_echec(conn, login_n: str):
    """Incrémente le compteur. Retourne (secondes de blocage déclenché, essais restants)."""
    ligne = conn.execute("SELECT ECHECS, NB_BLOCAGES FROM TENTATIVE_CONNEXION WHERE LOGIN = ?",
                         (login_n,)).fetchone()
    echecs = (ligne["ECHECS"] if ligne else 0) + 1
    nb_blocages = ligne["NB_BLOCAGES"] if ligne else 0
    bloque_jusqua, secondes = None, 0
    if echecs >= config.MAX_ECHECS:
        minutes = min(config.DUREE_BLOCAGE_MIN * (2 ** nb_blocages), config.BLOCAGE_MAX_MIN)
        bloque_jusqua = iso(maintenant() + timedelta(minutes=minutes))
        secondes = minutes * 60
        echecs, nb_blocages = 0, nb_blocages + 1
    conn.execute(
        "INSERT INTO TENTATIVE_CONNEXION (LOGIN, ECHECS, NB_BLOCAGES, BLOQUE_JUSQUA) VALUES (?,?,?,?) "
        "ON CONFLICT(LOGIN) DO UPDATE SET ECHECS = excluded.ECHECS, NB_BLOCAGES = excluded.NB_BLOCAGES, "
        "BLOQUE_JUSQUA = COALESCE(excluded.BLOQUE_JUSQUA, TENTATIVE_CONNEXION.BLOQUE_JUSQUA)",
        (login_n, echecs, nb_blocages, bloque_jusqua),
    )
    return secondes, config.MAX_ECHECS - echecs


def formater_duree(secondes: int) -> str:
    minutes, sec = divmod(max(0, secondes), 60)
    return f"{minutes:02d}:{sec:02d}"


def authentifier(conn, login: str, mdp: str, role=None) -> ResultatConnexion:
    """`role` (facultatif) : poste choisi dans la liste de l'écran de connexion. S'il ne correspond pas au poste du
    compte, la connexion est refusée comme un mot de passe faux (même message, même compteur d'échecs)."""
    login_n = normaliser_login(login)
    if not login_n or not mdp or len(mdp) > 256:
        return ResultatConnexion(False, "Saisissez votre identifiant et votre mot de passe.")

    # 1) Blocage en cours : on ne vérifie même pas le mot de passe (le bon est refusé aussi)
    restant = _secondes_blocage_restantes(conn, login_n)
    if restant > 0:
        with conn:
            journaliser(conn, None, login_n, "CONNEXION_REFUSEE_BLOCAGE")
        return ResultatConnexion(False, "Trop de tentatives. Compte temporairement bloqué.",
                                 secondes_blocage=restant)

    # 2) Vérification (toujours un calcul scrypt complet, même si l'identifiant n'existe pas)
    utilisateur = conn.execute("SELECT * FROM UTILISATEUR WHERE LOGIN = ?", (login_n,)).fetchone()
    actif = bool(utilisateur and utilisateur["ACTIF"])
    hash_stocke = utilisateur["MDP_HASH"] if actif else _hash_factice_pour_temps_constant()
    mot_de_passe_valide = verifier_mdp(mdp, hash_stocke)
    if role is not None and actif and utilisateur["ROLE"] != role:
        mot_de_passe_valide = False

    # 3) Échec
    if not (mot_de_passe_valide and actif):
        with conn:
            secondes, essais = _enregistrer_echec(conn, login_n)
            journaliser(conn, utilisateur["ID_USER"] if utilisateur else None, login_n, "CONNEXION_ECHEC",
                        "blocage déclenché" if secondes else "")
        if secondes:
            return ResultatConnexion(False, "Trop de tentatives. Compte temporairement bloqué.",
                                     secondes_blocage=secondes)
        message = MESSAGE_ECHEC
        if essais <= 2:
            message += f"\nIl vous reste {essais} essai(s) avant blocage."
        return ResultatConnexion(False, message)

    # 4) Succès
    with conn:
        conn.execute("DELETE FROM TENTATIVE_CONNEXION WHERE LOGIN = ?", (login_n,))
        conn.execute("UPDATE UTILISATEUR SET DERNIERE_CONNEXION = ? WHERE ID_USER = ?",
                     (iso(maintenant()), utilisateur["ID_USER"]))
        if hash_a_renouveler(utilisateur["MDP_HASH"]):          # montée en gamme automatique du hash
            conn.execute("UPDATE UTILISATEUR SET MDP_HASH = ? WHERE ID_USER = ?",
                         (hacher_mdp(mdp), utilisateur["ID_USER"]))
        journaliser(conn, utilisateur["ID_USER"], utilisateur["LOGIN"], "CONNEXION_OK")
    session = Session(utilisateur["ID_USER"], utilisateur["LOGIN"], utilisateur["NOM_COMPLET"],
                      utilisateur["ROLE"], bool(utilisateur["DOIT_CHANGER_MDP"]),
                      libelle_poste=droits.libelle_role(conn, utilisateur["ROLE"]))
    return ResultatConnexion(True, session=session)

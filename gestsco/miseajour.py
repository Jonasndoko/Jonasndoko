"""Mise à jour du programme depuis un fichier « .csfupd » (clé USB, dossier réseau, courriel), sans internet.

Le fichier de mise à jour est une archive zip qui contient les fichiers du programme et un manifeste :
version, empreinte SHA-256 de chaque fichier et un cachet HMAC calculé avec la CLÉ DE MISE À JOUR choisie par celui
qui prépare le fichier. Cette clé n'est écrite nulle part dans le programme : elle se communique séparément (par
téléphone, par exemple). Sans la bonne clé, un fichier fabriqué ou modifié par quelqu'un d'autre est refusé.

Installation (Administrateur seulement, mot de passe redemandé) :
1. contrôle complet du fichier AVANT toute modification (cachet, empreintes, chemins, types de fichiers, version plus récente) ;
2. sauvegarde de sécurité de la base de données ;
3. copie de la version actuelle dans « ancienne_version » (les 3 dernières sont gardées) ;
4. remplacement des fichiers ; au moindre problème, la version précédente est remise en place ;
5. inscription au journal. La structure de la base est mise à jour toute seule au prochain démarrage.

Retour arrière : on peut revenir à une version gardée dans « ancienne_version » (refusé si la base a déjà été
transformée par la version plus récente : il faut alors restaurer la sauvegarde « Avant-mise-a-jour »).
Les données (base, reçus, sauvegardes) sont hors du dossier du programme : elles ne sont jamais touchées par les fichiers.

Préparer un fichier de mise à jour (côté développeur) :   python miseajour.py creer mise_a_jour_0.21.csfupd
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sys
import zipfile
import zlib
from datetime import datetime
from pathlib import Path

import config
import database
import droits
import sauvegarde
import security
from database import journaliser

EXTENSION = ".csfupd"
NOM_MANIFESTE = "manifeste.json"
DOSSIER_ARCHIVES = "ancienne_version"
NB_ARCHIVES = 3
EXTENSIONS_PERMISES = {".py", ".md", ".bat", ".png", ".jpg", ".txt", ".html"}
DOSSIERS_PERMIS = {"", "assets", "templates"}          # le programme est à plat, plus les images (assets) et les pages web (templates)
TAILLE_MAX = 200 * 1024 * 1024
ITERATIONS = 200_000


class ErreurMiseAJour(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== outils
def _sha256_octets(donnees: bytes) -> str:
    return hashlib.sha256(donnees).hexdigest()


def _sha256_fichier(chemin) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def _version_tuple(texte) -> tuple:
    try:
        return tuple(int(x) for x in str(texte).strip().split("."))
    except ValueError:
        raise ErreurMiseAJour(f"Numéro de version illisible : « {texte} ».") from None


def _canonique(manifeste: dict) -> bytes:
    return json.dumps({k: v for k, v in manifeste.items() if k != "mac"}, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _cachet(manifeste: dict, cle: str) -> str:
    sel = bytes.fromhex(manifeste["sel"])
    derivee = hashlib.pbkdf2_hmac("sha256", cle.encode("utf-8"), sel, ITERATIONS)
    return hmac.new(derivee, _canonique(manifeste), hashlib.sha256).hexdigest()


def empreinte(manifeste: dict) -> str:
    """Empreinte du fichier de mise à jour, à comparer avec celle communiquée par le développeur (12 premiers caractères)."""
    return hashlib.sha256(_canonique(manifeste)).hexdigest()[:12].upper()


def _chemin_sur(nom: str) -> bool:
    """Un chemin de l'archive doit rester dans le dossier du programme (pas de « .. », pas de chemin absolu)."""
    if not nom or nom.startswith(("/", "\\")) or "\\" in nom or ":" in nom:
        return False
    p = Path(nom)
    if p.is_absolute() or ".." in p.parts or len(p.parts) > 2:
        return False
    if (p.parent.as_posix() if len(p.parts) > 1 else "") not in DOSSIERS_PERMIS:
        return False
    return p.suffix.lower() in EXTENSIONS_PERMISES


def fichiers_du_programme(dossier) -> list:
    """Chemins relatifs (à plat + assets/ + templates/) des fichiers du programme présents dans `dossier`."""
    dossier, resultat = Path(dossier), []
    for p in sorted(dossier.iterdir()):
        if p.is_file() and p.suffix.lower() in EXTENSIONS_PERMISES:
            resultat.append(p.name)
    for sous in ("assets", "templates"):
        if (dossier / sous).is_dir():
            resultat += [f"{sous}/{p.name}" for p in sorted((dossier / sous).iterdir())
                         if p.is_file() and p.suffix.lower() in EXTENSIONS_PERMISES]
    return resultat


def _lire_version(dossier) -> str:
    texte = (Path(dossier) / "config.py").read_text(encoding="utf-8")
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', texte, re.M)
    if not m:
        raise ErreurMiseAJour("Version introuvable dans config.py.")
    return m.group(1)


# ================================================================== préparer un fichier de mise à jour
def creer_paquet(sortie, cle: str, dossier=None, structure=None) -> dict:
    """Prépare le fichier de mise à jour à partir du dossier du programme. Retourne le manifeste (avec son empreinte)."""
    dossier = Path(dossier or config.DOSSIER_APP)
    if len(cle or "") < 8:
        raise ErreurMiseAJour("La clé de mise à jour doit avoir au moins 8 caractères.")
    if structure is None:
        import migrations
        structure = migrations.VERSION_SCHEMA
    fichiers = fichiers_du_programme(dossier)
    manifeste = {"application": config.NOM_ECOLE, "version": _lire_version(dossier), "structure": structure,
                 "date": database.iso(database.maintenant()), "sel": secrets.token_hex(16),
                 "fichiers": {f: _sha256_fichier(dossier / f) for f in fichiers}}
    manifeste["mac"] = _cachet(manifeste, cle)
    sortie = Path(sortie)
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(NOM_MANIFESTE, json.dumps(manifeste, ensure_ascii=False, indent=1))
        for f in fichiers:
            z.write(dossier / f, "fichiers/" + f)
    manifeste["empreinte"] = empreinte(manifeste)
    return manifeste


# ================================================================== contrôle d'un fichier de mise à jour
def examiner(chemin, cle: str) -> dict:
    """Contrôle complet, sans rien modifier. Retourne le manifeste (+ 'empreinte', 'nb_fichiers').
    Lève ErreurMiseAJour (message affichable) au moindre doute."""
    chemin = Path(chemin)
    if not chemin.is_file():
        raise ErreurMiseAJour("Fichier de mise à jour introuvable.")
    try:
        z = zipfile.ZipFile(chemin)
    except (zipfile.BadZipFile, OSError):
        raise ErreurMiseAJour("Ce fichier n'est pas un fichier de mise à jour valide (archive illisible).") from None
    with z:
        try:
            manifeste = json.loads(z.read(NOM_MANIFESTE).decode("utf-8"))
            sel, mac, fichiers = manifeste["sel"], manifeste["mac"], manifeste["fichiers"]
            bytes.fromhex(sel)
            _version_tuple(manifeste["version"])
        except (KeyError, ValueError, UnicodeDecodeError, TypeError):
            raise ErreurMiseAJour("Ce fichier n'est pas un fichier de mise à jour valide (manifeste absent ou abîmé).") from None
        if not isinstance(fichiers, dict) or not fichiers:
            raise ErreurMiseAJour("Le fichier de mise à jour ne contient aucun fichier.")
        if not hmac.compare_digest(_cachet(manifeste, cle or ""), str(mac)):
            raise ErreurMiseAJour("Clé de mise à jour incorrecte, ou fichier modifié : mise à jour refusée.")
        presents = {i.filename: i for i in z.infolist() if not i.is_dir()}
        total = 0
        for nom, attendu in fichiers.items():
            if not _chemin_sur(nom):
                raise ErreurMiseAJour(f"Fichier non autorisé dans la mise à jour : « {nom} ».")
            info = presents.get("fichiers/" + nom)
            if info is None:
                raise ErreurMiseAJour(f"Fichier annoncé mais absent de l'archive : « {nom} ».")
            total += info.file_size
            if total > TAILLE_MAX:
                raise ErreurMiseAJour("Le fichier de mise à jour est anormalement gros.")
            try:
                contenu = z.read(info)
            except (zipfile.BadZipFile, zlib.error, EOFError, OSError):
                raise ErreurMiseAJour(f"Le fichier « {nom} » est abîmé dans l'archive.") from None
            if _sha256_octets(contenu) != attendu:
                raise ErreurMiseAJour(f"Le fichier « {nom} » est abîmé ou modifié (empreinte différente).")
        en_trop = [n for n in presents if n != NOM_MANIFESTE and n[len("fichiers/"):] not in fichiers]
        if en_trop:
            raise ErreurMiseAJour(f"L'archive contient des fichiers non annoncés : « {en_trop[0]} ».")
        for obligatoire in ("main.py", "config.py", "database.py", "migrations.py"):
            if obligatoire not in fichiers:
                raise ErreurMiseAJour(f"Mise à jour incomplète : « {obligatoire} » manque.")
    manifeste["empreinte"] = empreinte(manifeste)
    manifeste["nb_fichiers"] = len(fichiers)
    return manifeste


# ================================================================== installation
def _verifier_admin_et_mdp(conn, session, mot_de_passe, refus):
    droits.exiger_admin(conn, session)
    ligne = conn.execute("SELECT MDP_HASH FROM UTILISATEUR WHERE ID_USER = ?", (session.id_user,)).fetchone()
    if not ligne or not security.verifier_mdp(mot_de_passe or "", ligne["MDP_HASH"]):
        with conn:
            journaliser(conn, session.id_user, session.login, refus, "mot de passe incorrect")
        raise ErreurMiseAJour("Mot de passe incorrect.")


def _archiver(dossier: Path, version: str, structure_bd: int) -> Path:
    racine = dossier / DOSSIER_ARCHIVES
    racine.mkdir(exist_ok=True)
    cible = racine / f"{version}_{datetime.now():%Y%m%d-%H%M%S}"
    n = 1
    while cible.exists():
        n += 1
        cible = racine / f"{version}_{datetime.now():%Y%m%d-%H%M%S}_{n}"
    for f in fichiers_du_programme(dossier):
        (cible / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dossier / f, cible / f)
    (cible / "version.json").write_text(json.dumps({"version": version, "structure": structure_bd, "archive": datetime.now().isoformat(timespec="seconds")}),
                                        encoding="utf-8")
    for ancienne in lister_archives(dossier)[NB_ARCHIVES:]:                  # on ne garde que les plus récentes
        shutil.rmtree(dossier / DOSSIER_ARCHIVES / ancienne["nom"], ignore_errors=True)
    return cible


def _copier_vers(source: Path, dossier: Path, fichiers):
    """Remplace les fichiers du programme un par un (fichier temporaire puis remplacement)."""
    for f in fichiers:
        cible = dossier / f
        cible.parent.mkdir(parents=True, exist_ok=True)
        temp = cible.with_name(cible.name + ".maj")
        shutil.copy2(source / f, temp)
        os.replace(temp, cible)


def installer(conn, session, chemin, cle, mot_de_passe, dossier_programme=None) -> dict:
    """Installe la mise à jour. Retourne {'ancienne', 'nouvelle', 'fichiers', 'securite', 'archive', 'empreinte'}."""
    dossier = Path(dossier_programme or config.DOSSIER_APP)
    _verifier_admin_et_mdp(conn, session, mot_de_passe, "MISE_A_JOUR_REFUSEE")
    try:
        manifeste = examiner(chemin, cle)
    except ErreurMiseAJour as erreur:
        with conn:
            journaliser(conn, session.id_user, session.login, "MISE_A_JOUR_REFUSEE", str(erreur))
        raise
    actuelle, nouvelle = config.VERSION, manifeste["version"]
    if _version_tuple(nouvelle) <= _version_tuple(actuelle):
        raise ErreurMiseAJour(f"Cette mise à jour (version {nouvelle}) n'est pas plus récente que la version installée "
                              f"({actuelle}).")

    securite = sauvegarde.sauvegarde_securite(conn, "Avant-mise-a-jour")
    structure_bd = conn.execute("PRAGMA user_version").fetchone()[0]
    archive = _archiver(dossier, actuelle, structure_bd)
    mis = []
    try:
        with zipfile.ZipFile(chemin) as z, _Temporaire(dossier) as tmp:
            for nom in manifeste["fichiers"]:
                cible = tmp / nom
                cible.parent.mkdir(parents=True, exist_ok=True)
                cible.write_bytes(z.read("fichiers/" + nom))
                if _sha256_fichier(cible) != manifeste["fichiers"][nom]:
                    raise ErreurMiseAJour(f"Écriture incorrecte de « {nom} ».")
            for nom in manifeste["fichiers"]:                      # tout est prêt et vérifié : remplacement
                _copier_vers(tmp, dossier, [nom])
                mis.append(nom)
    except BaseException as erreur:
        try:
            _copier_vers(archive, dossier, mis)                    # remise en place de la version précédente
        finally:
            with conn:
                journaliser(conn, session.id_user, session.login, "MISE_A_JOUR_ECHEC",
                            f"{actuelle} -> {nouvelle} : {erreur} | version précédente remise en place")
        if isinstance(erreur, ErreurMiseAJour):
            raise
        raise ErreurMiseAJour(f"La mise à jour a échoué ({erreur}). La version précédente a été remise en place.") from erreur

    with conn:
        journaliser(conn, session.id_user, session.login, "MISE_A_JOUR_PROGRAMME",
                    f"{actuelle} -> {nouvelle} | {len(mis)} fichiers | empreinte {manifeste['empreinte']} | "
                    f"sécurité : {securite.name} | ancienne version : {archive.name}")
    return {"ancienne": actuelle, "nouvelle": nouvelle, "fichiers": len(mis), "securite": securite,
            "archive": archive.name, "empreinte": manifeste["empreinte"]}


class _Temporaire:
    """Dossier de préparation, effacé à la fin (même en cas d'erreur)."""

    def __init__(self, dossier):
        self.chemin = Path(dossier) / ".maj_en_cours"

    def __enter__(self):
        shutil.rmtree(self.chemin, ignore_errors=True)
        self.chemin.mkdir()
        return self.chemin

    def __exit__(self, *_):
        shutil.rmtree(self.chemin, ignore_errors=True)


# ================================================================== retour à une ancienne version
def lister_archives(dossier_programme=None) -> list:
    """Versions gardées, de la plus récente à la plus ancienne : [{'nom', 'version', 'structure', 'date'}]."""
    racine = Path(dossier_programme or config.DOSSIER_APP) / DOSSIER_ARCHIVES
    resultat = []
    if racine.is_dir():
        for d in racine.iterdir():
            try:
                v = json.loads((d / "version.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            resultat.append({"nom": d.name, "version": v.get("version", "?"), "structure": v.get("structure", 0),
                             "date": v.get("archive", "")})
    return sorted(resultat, key=lambda a: a["date"], reverse=True)


def revenir(conn, session, nom, mot_de_passe, dossier_programme=None) -> dict:
    """Remet une version gardée dans « ancienne_version ». La version actuelle est elle-même gardée (on peut y revenir)."""
    dossier = Path(dossier_programme or config.DOSSIER_APP)
    _verifier_admin_et_mdp(conn, session, mot_de_passe, "MISE_A_JOUR_REFUSEE")
    choix = next((a for a in lister_archives(dossier) if a["nom"] == nom), None)
    if not choix:
        raise ErreurMiseAJour("Cette version n'est plus disponible.")
    bd = conn.execute("PRAGMA user_version").fetchone()[0]
    if bd > choix["structure"]:
        raise ErreurMiseAJour(
            f"Retour impossible : la base de données a déjà été transformée par la version actuelle (structure n° {bd}, "
            f"la version {choix['version']} connaît le n° {choix['structure']}). Pour revenir en arrière, restaurez d'abord "
            f"la sauvegarde « Avant-mise-a-jour » (Travaux techniques > Restauration) : les données saisies depuis seront perdues.")
    source = dossier / DOSSIER_ARCHIVES / nom
    fichiers = fichiers_du_programme(source)
    if not fichiers:
        raise ErreurMiseAJour("Cette version gardée est vide ou abîmée.")
    actuelle = config.VERSION
    archive = _archiver(dossier, actuelle, bd)
    try:
        _copier_vers(source, dossier, fichiers)
    except BaseException as erreur:
        _copier_vers(archive, dossier, fichiers_du_programme(archive))
        raise ErreurMiseAJour(f"Retour impossible ({erreur}). La version actuelle a été remise en place.") from erreur
    with conn:
        journaliser(conn, session.id_user, session.login, "RETOUR_ANCIENNE_VERSION",
                    f"{actuelle} -> {choix['version']} | {len(fichiers)} fichiers | version quittée gardée : {archive.name}")
    return {"ancienne": actuelle, "nouvelle": choix["version"], "fichiers": len(fichiers), "archive": archive.name}


def recharger_web() -> bool:
    """Version web : demande à l'hébergeur de recharger l'application en « touchant » wsgi.py (hébergeurs qui surveillent ce
    fichier). Retourne True si le fichier a pu être touché. Sinon, l'Administrateur recharge l'application à la main."""
    try:
        os.utime(config.DOSSIER_APP / "wsgi.py", None)
        return True
    except OSError:
        return False


def redemarrer():
    """Relance le programme (nouvelle version) dans un nouveau processus ; l'appelant ferme ensuite la fenêtre actuelle."""
    import subprocess
    subprocess.Popen([sys.executable, str(config.DOSSIER_APP / "main.py")], cwd=str(config.DOSSIER_APP))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "creer":
        import getpass
        cle = getpass.getpass("Clé de mise à jour (à communiquer séparément à l'Administrateur) : ")
        if cle != getpass.getpass("Retapez la clé : "):
            sys.exit("Les deux clés sont différentes.")
        m = creer_paquet(sys.argv[2], cle)
        print(f"Fichier créé : {sys.argv[2]}\nVersion : {m['version']}  |  {len(m['fichiers'])} fichiers\n"
              f"Empreinte à communiquer avec la clé : {m['empreinte']}")
    else:
        print(__doc__)

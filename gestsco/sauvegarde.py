"""Sauvegarde et restauration de la base de données (réservées à l'Administrateur).

Une sauvegarde est une archive « .csfbak » (zip) contenant :
  - college.db      : copie cohérente de la base (faite avec l'API de sauvegarde de SQLite, même si le
                      programme est ouvert) ;
  - manifeste.json  : date, version du programme, nombre d'élèves/paiements/comptes, empreinte SHA-256 de la base.
À la restauration, l'empreinte est recontrôlée : un fichier abîmé ou modifié est refusé avant toute modification.
ATTENTION : la sauvegarde n'est pas chiffrée (elle contient les données des élèves et les empreintes des mots de passe) :
la ranger dans un endroit sûr.
"""
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import config
import database
import droits
import migrations

NOM_BD, NOM_MANIFESTE = "college.db", "manifeste.json"
ENTETE_SQLITE = b"SQLite format 3\x00"


class ErreurSauvegarde(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ------------------------------------------------------------------ outils
def _sha256(chemin) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def _compter(conn, table, condition="") -> int:
    existe = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)).fetchone()
    if not existe:
        return 0
    return conn.execute(f'SELECT COUNT(*) FROM "{table}" {condition}').fetchone()[0]


def _contenu(conn) -> dict:
    return {"utilisateurs": _compter(conn, "UTILISATEUR"), "eleves": _compter(conn, "ELEVE"),
            "paiements": _compter(conn, "PAIEMENT", "WHERE STATUT = 'VALIDE'")}


def dossier_defaut() -> Path:
    config.DOSSIER_SAUVEGARDES.mkdir(parents=True, exist_ok=True)
    return config.DOSSIER_SAUVEGARDES


def _nom_libre(dossier: Path, prefixe: str) -> Path:
    base = f"{prefixe}_{datetime.now().strftime('%Y-%m-%d_%Hh%Mm%Ss')}"
    chemin, n = dossier / (base + config.EXTENSION_SAUVEGARDE), 1
    while chemin.exists():
        n += 1
        chemin = dossier / f"{base}_{n}{config.EXTENSION_SAUVEGARDE}"
    return chemin


# ------------------------------------------------------------------ sauvegarde
def creer_sauvegarde(conn, dossier=None, prefixe="Sauvegarde", cree_par="") -> Path:
    """Écrit l'archive de sauvegarde dans `dossier` (par défaut : le dossier des sauvegardes) et retourne son chemin."""
    dossier = Path(dossier) if dossier else dossier_defaut()
    try:
        dossier.mkdir(parents=True, exist_ok=True)
    except OSError as erreur:
        raise ErreurSauvegarde(f"Impossible d'utiliser le dossier « {dossier} » : {erreur}") from erreur
    conn.commit()
    final = _nom_libre(dossier, prefixe)
    partiel = final.with_suffix(final.suffix + ".part")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            copie = Path(tmp) / NOM_BD
            cible = sqlite3.connect(copie)
            try:
                if getattr(conn, "backend", "") == "postgresql":
                    import pgcopie
                    pgcopie.exporter(conn, cible)          # PostgreSQL -> college.db : l'archive reste la même sur les deux moteurs
                else:
                    conn.backup(cible)
            finally:
                cible.close()
            manifeste = {
                "application": config.NOM_ECOLE, "version_programme": config.VERSION,
                "version_structure": conn.execute("PRAGMA user_version").fetchone()[0],
                "date": database.iso(database.maintenant()), "cree_par": cree_par,
                "fichier_bd": NOM_BD, "taille_bd": copie.stat().st_size, "sha256": _sha256(copie),
                "contenu": _contenu(conn),
            }
            with zipfile.ZipFile(partiel, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(copie, NOM_BD)
                z.writestr(NOM_MANIFESTE, json.dumps(manifeste, ensure_ascii=False, indent=2))
        partiel.replace(final)
    except (OSError, sqlite3.Error) as erreur:
        partiel.unlink(missing_ok=True)
        raise ErreurSauvegarde(f"La sauvegarde a échoué : {erreur}") from erreur
    return final


def sauvegarde_securite(conn, prefixe) -> Path:
    """Sauvegarde automatique faite avant une opération risquée (mise à jour, restauration)."""
    return creer_sauvegarde(conn, None, prefixe, cree_par="SYSTEME")


def sauvegarder(conn, session, dossier=None) -> Path:
    droits.exiger_admin(conn, session)
    chemin = creer_sauvegarde(conn, dossier, "Sauvegarde", cree_par=session.login)
    with conn:
        database.journaliser(conn, session.id_user, session.login, "SAUVEGARDE_CREEE", chemin.name)
    return chemin


# ------------------------------------------------------------------ liste
def lire_manifeste(chemin):
    """Manifeste d'une archive, ou None si le fichier n'est pas une sauvegarde lisible."""
    try:
        with zipfile.ZipFile(chemin) as z:
            return json.loads(z.read(NOM_MANIFESTE).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None


def lister(dossier=None) -> list:
    """Sauvegardes d'un dossier, la plus récente d'abord : dicts {chemin, nom, date, taille, manifeste}."""
    dossier = Path(dossier) if dossier else config.DOSSIER_SAUVEGARDES
    resultat = []
    if dossier.is_dir():
        for f in dossier.glob("*" + config.EXTENSION_SAUVEGARDE):
            manifeste = lire_manifeste(f)
            date = (manifeste or {}).get("date") or database.iso(datetime.fromtimestamp(f.stat().st_mtime).astimezone())
            resultat.append({"chemin": f, "nom": f.name, "date": date, "taille": f.stat().st_size,
                             "manifeste": manifeste})
    return sorted(resultat, key=lambda s: s["date"], reverse=True)


# ------------------------------------------------------------------ examen d'un fichier à restaurer
def _extraire(chemin, tmp):
    """Extrait et contrôle le fichier. Retourne (chemin de la base extraite, manifeste ou None)."""
    chemin = Path(chemin)
    if not chemin.is_file():
        raise ErreurSauvegarde("Fichier introuvable.")
    sortie = Path(tmp) / "a_restaurer.db"
    manifeste = None
    if zipfile.is_zipfile(chemin):
        try:
            with zipfile.ZipFile(chemin) as z:
                manifeste = json.loads(z.read(NOM_MANIFESTE).decode("utf-8"))
                if z.getinfo(NOM_BD).file_size > 4 << 30:
                    raise ErreurSauvegarde("Fichier de sauvegarde anormalement gros.")
                with z.open(NOM_BD) as src, open(sortie, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        except (KeyError, ValueError, zipfile.BadZipFile, OSError) as erreur:
            raise ErreurSauvegarde("Ce fichier n'est pas une sauvegarde valide du programme "
                                   "(archive incomplète ou abîmée).") from erreur
        if _sha256(sortie) != manifeste.get("sha256"):
            raise ErreurSauvegarde("La sauvegarde est abîmée ou a été modifiée (l'empreinte de contrôle ne "
                                   "correspond pas). Restauration refusée : utilisez une autre sauvegarde.")
    else:
        with open(chemin, "rb") as f:
            if f.read(16) != ENTETE_SQLITE:
                raise ErreurSauvegarde("Ce fichier n'est ni une sauvegarde du programme (.csfbak) "
                                       "ni une base de données.")
        shutil.copyfile(chemin, sortie)
    return sortie, manifeste


def _controler_et_mettre_a_niveau(chemin_bd):
    """Ouvre la copie extraite, vérifie qu'elle est saine et qu'elle vient bien de ce programme, la met à niveau.
    Retourne la connexion (à fermer par l'appelant)."""
    t = None
    try:
        t = sqlite3.connect(chemin_bd)
        t.row_factory = sqlite3.Row
        if [l[0] for l in t.execute("PRAGMA integrity_check").fetchall()] != ["ok"]:
            raise ErreurSauvegarde("La base contenue dans ce fichier est abîmée : restauration refusée.")
        colonnes = {c["name"] for c in t.execute('PRAGMA table_info("UTILISATEUR")').fetchall()}
        if not {"LOGIN", "MDP_HASH", "ROLE"} <= colonnes:
            raise ErreurSauvegarde("Ce fichier ne contient pas la base de GESTSCO.")
        t.execute("PRAGMA foreign_keys = ON")
        migrations.mettre_a_jour(t, sauvegarder=False)
        return t
    except (sqlite3.DatabaseError, migrations.ErreurMiseAJour, ErreurSauvegarde) as erreur:
        if t is not None:
            t.close()                                  # libère le fichier (indispensable sous Windows)
        if isinstance(erreur, ErreurSauvegarde):
            raise
        raise ErreurSauvegarde(f"Fichier illisible ou incompatible : {erreur}") from erreur


def examiner(chemin) -> dict:
    """Contrôle un fichier de sauvegarde SANS rien modifier. Retourne un résumé affichable.
    Lève ErreurSauvegarde si le fichier ne peut pas être restauré."""
    with tempfile.TemporaryDirectory() as tmp:
        bd, manifeste = _extraire(chemin, tmp)
        t = _controler_et_mettre_a_niveau(bd)
        try:
            resume = dict(_contenu(t))
            resume["administrateurs"] = t.execute(
                "SELECT COUNT(*) FROM UTILISATEUR WHERE ROLE = ? AND ACTIF = 1", (config.ADMINISTRATEUR,)).fetchone()[0]
        finally:
            t.close()
    resume.update({"date": (manifeste or {}).get("date", ""), "version_programme": (manifeste or {}).get("version_programme", ""),
                   "controle": bool(manifeste)})
    return resume


# ------------------------------------------------------------------ restauration
def restaurer(conn, session, chemin) -> dict:
    """Remplace TOUTE la base actuelle par celle de la sauvegarde. Retourne {'resume', 'securite'}.
    Une sauvegarde de sécurité de la base actuelle est faite juste avant ; si quelque chose échoue,
    la base actuelle reste intacte."""
    droits.exiger_admin(conn, session)
    with tempfile.TemporaryDirectory() as tmp:
        bd, manifeste = _extraire(chemin, tmp)
        t = _controler_et_mettre_a_niveau(bd)
        try:
            securite = sauvegarde_securite(conn, "Avant-restauration")
            conn.commit()
            try:
                if getattr(conn, "backend", "") == "postgresql":
                    import pgcopie
                    pgcopie.importer(conn, t, vider=True)   # une seule transaction : tout ou rien
                else:
                    t.backup(conn)                       # copie atomique : tout ou rien
            except Exception as erreur:
                raise ErreurSauvegarde(f"La restauration a échoué : {erreur}. La base actuelle n'a pas été modifiée. "
                                       f"Une sauvegarde de sécurité existe : {securite.name}") from erreur
            resume = _contenu(t)
        finally:
            t.close()
    with conn:
        database.journaliser(conn, session.id_user, session.login, "RESTAURATION_EFFECTUEE",
                             f"{Path(chemin).name} | sécurité : {securite.name}")
    return {"resume": resume, "securite": securite}

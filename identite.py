"""Identité d'un élève : numéro matricule et code QR, attribués automatiquement par le système.

- Matricule : « 0001/26 » = numéro d'ordre (4 chiffres) / année d'inscription (2 derniers chiffres). La numérotation
  repart de 0001 chaque année. Le compteur ne recule jamais, mais le matricule d'un élève RENVOYÉ est libéré (table MATRICULE_LIBRE) et redonné en
  premier au prochain élève inscrit la même année (renvoi.py). Un matricule supprimé autrement n'est pas redonné. Après une
  réinitialisation, il repart de 0001. Les élèves déjà présents gardent leur ancien matricule.
- Code QR : texte unique propre à l'élève « CSF|matricule|code secret » (le code secret rend la carte infalsifiable :
  on ne peut pas fabriquer le QR d'un élève à partir de son seul matricule).
"""
import re
import secrets
from datetime import date

LONGUEUR_ORDRE = 4
PREFIXE_QR = "CSF"
FORMAT_MATRICULE = re.compile(r"\d{4,}/\d{2}")


def formater_matricule(ordre: int, annee: int) -> str:
    return f"{ordre:0{LONGUEUR_ORDRE}d}/{annee % 100:02d}"


def nouveau_matricule(conn, jour: date = None) -> str:
    """Réserve et retourne le prochain matricule de l'année d'inscription (`jour`, par défaut aujourd'hui).
    À appeler dans la transaction qui enregistre l'élève."""
    annee = f"{(jour or date.today()).year % 100:02d}"
    while True:                              # 1) un numéro libéré par un renvoi (le plus petit d'abord), 2) sinon le compteur
        libre = conn.execute("SELECT ORDRE FROM MATRICULE_LIBRE WHERE ANNEE = ? ORDER BY ORDRE LIMIT 1", (annee,)).fetchone()
        if libre is None:
            break
        conn.execute("DELETE FROM MATRICULE_LIBRE WHERE ANNEE = ? AND ORDRE = ?", (annee, libre[0]))
        matricule = f"{libre[0]:0{LONGUEUR_ORDRE}d}/{annee}"
        if not conn.execute("SELECT 1 FROM ELEVE WHERE MATRICULE = ?", (matricule,)).fetchone():
            return matricule
    while True:
        conn.execute("INSERT OR IGNORE INTO MATRICULE_SEQ (ANNEE, DERNIER) VALUES (?, 0)", (annee,))
        conn.execute("UPDATE MATRICULE_SEQ SET DERNIER = DERNIER + 1 WHERE ANNEE = ?", (annee,))
        ordre = conn.execute("SELECT DERNIER FROM MATRICULE_SEQ WHERE ANNEE = ?", (annee,)).fetchone()[0]
        matricule = f"{ordre:0{LONGUEUR_ORDRE}d}/{annee}"
        if not conn.execute("SELECT 1 FROM ELEVE WHERE MATRICULE = ?", (matricule,)).fetchone():   # déjà pris ?
            return matricule


def nom_de_fichier(matricule: str) -> str:
    """Le « / » du matricule n'est pas permis dans un nom de fichier : « 0001/26 » -> « 0001-26 »."""
    return matricule.replace("/", "-").replace("\\", "-")


def nouveau_code_qr(conn, matricule: str) -> str:
    while True:
        code = f"{PREFIXE_QR}|{matricule}|{secrets.token_hex(6).upper()}"
        if not conn.execute("SELECT 1 FROM ELEVE WHERE CODE_QR = ?", (code,)).fetchone():
            return code


def generer(conn, valeurs: dict):
    """Crochet de l'ajout d'un élève (referentiels) : matricule et QR attribués par le système."""
    valeurs["MATRICULE"] = nouveau_matricule(conn)
    valeurs["CODE_QR"] = nouveau_code_qr(conn, valeurs["MATRICULE"])


def assurer_code_qr(conn, matricule: str) -> str:
    """Retourne le code QR de l'élève ; s'il n'en a pas encore (élève ajouté avant cette version), il lui en est attribué un."""
    ligne = conn.execute("SELECT CODE_QR FROM ELEVE WHERE MATRICULE = ?", (matricule,)).fetchone()
    if ligne is None:
        raise ValueError("Élève introuvable.")
    if ligne["CODE_QR"]:
        return ligne["CODE_QR"]
    code = nouveau_code_qr(conn, matricule)
    with conn:
        conn.execute("UPDATE ELEVE SET CODE_QR = ? WHERE MATRICULE = ? AND CODE_QR IS NULL", (code, matricule))
    return conn.execute("SELECT CODE_QR FROM ELEVE WHERE MATRICULE = ?", (matricule,)).fetchone()["CODE_QR"]


def attribuer_aux_eleves_existants(conn):
    """Migration : un code QR pour chaque élève qui n'en a pas (les matricules existants sont conservés)."""
    with conn:
        for l in conn.execute("SELECT MATRICULE FROM ELEVE WHERE CODE_QR IS NULL").fetchall():
            conn.execute("UPDATE ELEVE SET CODE_QR = ? WHERE MATRICULE = ?", (nouveau_code_qr(conn, l["MATRICULE"]), l["MATRICULE"]))

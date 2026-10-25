"""Renvoi d'un élève par le Préfet des études.

- Le Préfet (droit « Modification » sur « Préfecture », section secondaire et humanitaire) renvoie un élève avec une date et un motif.
- L'élève renvoyé RESTE dans les archives, avec la mention « Renvoyé » : son identité, ses reçus, ses notes, ses présences et tous ses
  documents sont conservés. Il est désactivé (il disparaît des classes, des listes de présence, du suivi et du contrôle numérique ; sa
  carte et l'accès de ses parents ne sont plus valables).
- Son MATRICULE est libéré : le dossier de l'élève renvoyé est re-clé vers une clé d'archive (« 0007/26 » -> « 0007/26-R »), dans toutes
  les tables qui le citent. Sans cela, le prochain élève qui reçoit « 0007/26 » hériterait des reçus, des notes et des absences du
  renvoyé. Le numéro d'ordre libéré est redonné en premier au prochain élève inscrit la même année (identite.nouveau_matricule).
- Un renvoi n'est jamais supprimé ni modifié (déclencheurs). Il est inscrit au journal et dans les décisions du Préfet.
- Le journal d'audit n'est pas réécrit : ses lignes anciennes gardent l'ancien matricule ; la ligne du renvoi cite les deux clés.
"""
import re
import sqlite3

import config
import prefecture
import sections
from database import iso, journaliser, maintenant
from prefecture import ErreurPrefecture

SUFFIXE = "-R"
MIN_MOTIF = 5
_FORMAT = re.compile(r"^(\d{4,})/(\d{2})$")


class ErreurRenvoi(ErreurPrefecture):
    """Erreur dont le message peut être affiché tel quel."""


def _exiger_droit(conn, session):
    prefecture.exiger(conn, session)
    if not prefecture.peut_ecrire(conn, session, "MODIFICATION"):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS['MODIFICATION']} » "
                              f"sur « {config.MODULES_DROITS[prefecture.MODULE][0]} ».")


def peut_renvoyer(conn, session) -> bool:
    return prefecture.peut_ecrire(conn, session, "MODIFICATION")


def _tables_a_rekeyer(conn) -> list:
    """Tables dont une colonne MATRICULE désigne un élève (clé étrangère vers ELEVE ou INSCRIRE), hors ELEVE elle-même."""
    noms = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    tables = []
    for t in noms:
        if t == "ELEVE":
            continue
        for f in conn.execute(f'PRAGMA foreign_key_list("{t}")'):
            if f[2] in ("ELEVE", "INSCRIRE") and f[3] == "MATRICULE":
                tables.append(t)
                break
    return tables


def _cle_d_archive(conn, matricule) -> str:
    k, cle = 1, f"{matricule}{SUFFIXE}"
    while conn.execute("SELECT 1 FROM ELEVE WHERE MATRICULE = ?", (cle,)).fetchone():
        k += 1
        cle = f"{matricule}{SUFFIXE}{k}"
    return cle


def _transferer(conn, ancien, archive):
    """Change la clé de l'élève dans ELEVE et dans toutes les tables qui la citent (dans la transaction en cours). Les reçus sont
    verrouillés par un déclencheur : il est retiré le temps du transfert puis recréé à l'identique."""
    pg = getattr(conn, "backend", "") == "postgresql"
    if pg:                                        # PostgreSQL : le déclencheur est suspendu puis réactivé (dans la même transaction)
        declencheurs = []
        conn.execute("ALTER TABLE PAIEMENT DISABLE TRIGGER PAIEMENT_NO_UPDATE")
    else:
        declencheurs = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'PAIEMENT' "
                                    "AND name = 'PAIEMENT_NO_UPDATE'").fetchall()
    for d in declencheurs:
        conn.execute(f'DROP TRIGGER "{d[0]}"')
    conn.execute("PRAGMA defer_foreign_keys = ON")
    conn.execute("UPDATE ELEVE SET MATRICULE = ?, ACTIF = 0 WHERE MATRICULE = ?", (archive, ancien))
    for t in _tables_a_rekeyer(conn):
        conn.execute(f'UPDATE "{t}" SET MATRICULE = ? WHERE MATRICULE = ? COLLATE NOCASE', (archive, ancien))
    for d in declencheurs:
        conn.execute(d[1])
    if pg:
        conn.execute("ALTER TABLE PAIEMENT ENABLE TRIGGER PAIEMENT_NO_UPDATE")
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise ErreurRenvoi("Le transfert du dossier a échoué : rien n'a été modifié.")


def renvoyer_eleve(conn, session, matricule, date_renvoi, motif, annee=None) -> dict:
    """Renvoie un élève. Retourne {'ancien', 'archive', 'libere', 'decision'} ('libere' : le matricule redevenu disponible, ou '')."""
    _exiger_droit(conn, session)
    m = str(matricule or "").strip()
    if not m:
        raise ErreurRenvoi("Matricule : champ obligatoire.")
    e = conn.execute("SELECT MATRICULE, NOM, POSTNOM, PRENOM, ACTIF FROM ELEVE WHERE MATRICULE = ?", (m,)).fetchone()
    if not e:
        raise ErreurRenvoi("Élève introuvable : vérifiez le matricule.")
    ancien = e["MATRICULE"]
    if sections.section_de_eleve(conn, ancien) != sections.SECONDAIRE:
        raise PermissionError(prefecture.REFUS_SECTION)
    if conn.execute("SELECT 1 FROM RENVOI WHERE MATRICULE_ARCHIVE = ?", (ancien,)).fetchone():
        raise ErreurRenvoi("Cet élève est déjà renvoyé.")
    if not e["ACTIF"]:
        raise ErreurRenvoi("Cet élève est déjà désactivé : réactivez-le d'abord s'il doit être renvoyé.")
    jour = prefecture._date_saisie(date_renvoi)
    motif = prefecture._texte(motif, "Motif du renvoi", prefecture.MAX_TEXTE)
    if len(motif) < MIN_MOTIF:
        raise ErreurRenvoi("Motif du renvoi : donnez au moins quelques mots.")
    annee = prefecture._annee(conn, annee)
    nom = " ".join(x for x in (e["NOM"], e["POSTNOM"], e["PRENOM"]) if x)
    archive = _cle_d_archive(conn, ancien)
    format_ = _FORMAT.match(ancien)

    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")           # le retrait temporaire du déclencheur des reçus doit se défaire avec le reste
    try:
        _transferer(conn, ancien, archive)
        cur = conn.execute("INSERT INTO DECISION_PREFET (DATE_DECISION, CATEGORIE, OBJET, DETAIL, ANNEESCO, MATRICULE, DATE_ENREG, ENREGISTRE_PAR) "
                           "VALUES (?,?,?,?,?,?,?,?)", (jour, "disciplinaire", f"Renvoi de l'élève {nom}", motif, annee or None, archive,
                                                         iso(maintenant()), session.login))
        id_decision = cur.lastrowid
        conn.execute("INSERT INTO RENVOI (MATRICULE_ARCHIVE, ANCIEN_MATRICULE, DATE_RENVOI, MOTIF, ANNEESCO, ID_DECISION, DECIDE_PAR, DATE_ENREG) "
                     "VALUES (?,?,?,?,?,?,?,?)", (archive, ancien, jour, motif, annee or None, id_decision, session.login, iso(maintenant())))
        if format_:
            conn.execute("INSERT OR IGNORE INTO MATRICULE_LIBRE (ANNEE, ORDRE, LIBERE_LE) VALUES (?,?,?)",
                         (format_.group(2), int(format_.group(1)), iso(maintenant())))
        journaliser(conn, session.id_user, session.login, "ELEVE_RENVOYE",
                    f"{nom} | ancien matricule {ancien} (libéré) -> dossier archivé sous {archive} | décision N° {id_decision} | {jour}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"ancien": ancien, "archive": archive, "libere": ancien, "decision": id_decision}


# ================================================================== consultation
def info(conn, matricule) -> dict:
    """Renseignements du renvoi d'un élève (par la clé de son dossier), ou None s'il n'est pas renvoyé."""
    r = conn.execute("SELECT * FROM RENVOI WHERE MATRICULE_ARCHIVE = ?", (str(matricule or "").strip(),)).fetchone()
    if not r:
        return None
    return {"id": r["ID_RENVOI"], "ancien_matricule": r["ANCIEN_MATRICULE"], "archive": r["MATRICULE_ARCHIVE"],
            "date": prefecture._fr(r["DATE_RENVOI"]), "motif": r["MOTIF"], "par": r["DECIDE_PAR"], "annee": r["ANNEESCO"] or ""}


def est_renvoye(conn, matricule) -> bool:
    return info(conn, matricule) is not None


def liste_renvois(conn, session) -> list:
    """Élèves renvoyés (les plus récents d'abord), avec ce qu'est devenu leur ancien matricule (libre ou déjà réattribué)."""
    prefecture.exiger(conn, session)
    lignes = conn.execute("SELECT R.*, E.NOM, E.POSTNOM, E.PRENOM FROM RENVOI R JOIN ELEVE E ON E.MATRICULE = R.MATRICULE_ARCHIVE "
                          "ORDER BY R.DATE_RENVOI DESC, R.ID_RENVOI DESC LIMIT ?", (prefecture.MAX_DECISIONS,)).fetchall()
    resultat = []
    for r in lignes:
        suivant = conn.execute("SELECT NOM, POSTNOM, PRENOM FROM ELEVE WHERE MATRICULE = ?", (r["ANCIEN_MATRICULE"],)).fetchone()
        libre = conn.execute("SELECT 1 FROM MATRICULE_LIBRE WHERE ANNEE = ? AND ORDRE = ?",
                             _cle_libre(r["ANCIEN_MATRICULE"])).fetchone() if _FORMAT.match(r["ANCIEN_MATRICULE"]) else None
        resultat.append({"id": r["ID_RENVOI"], "archive": r["MATRICULE_ARCHIVE"], "ancien_matricule": r["ANCIEN_MATRICULE"],
                         "eleve": " ".join(x for x in (r["NOM"], r["POSTNOM"], r["PRENOM"]) if x), "date": prefecture._fr(r["DATE_RENVOI"]),
                         "motif": r["MOTIF"], "par": r["DECIDE_PAR"], "annee": r["ANNEESCO"] or "",
                         "matricule_libre": bool(libre),
                         "reattribue_a": " ".join(x for x in (suivant["NOM"], suivant["POSTNOM"], suivant["PRENOM"]) if x) if suivant else ""})
    return resultat


def _cle_libre(matricule):
    m = _FORMAT.match(matricule)
    return (m.group(2), int(m.group(1)))

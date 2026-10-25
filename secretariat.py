"""Sous-menu « Secrétariat » (Gestion des études et discipline) : état « dossier complet » de chaque élève, sans interface graphique.

Règle de l'école : c'est la SECRÉTAIRE qui détermine qu'un dossier est complet. AUCUNE PIÈCE N'EST OBLIGATOIRE :
- l'état n'est jamais calculé ni déduit (ni de la photo, ni d'un document, ni d'un paiement) : il n'existe aucune liste de pièces ;
- rien ne bloque la décision : un dossier peut être déclaré complet sans aucun document, et l'état n'a aucun effet sur les
  inscriptions, les paiements, les notes ni les bulletins ;
- l'état est propre à l'élève (pas à une année scolaire) : une ligne par élève, absente tant que la secrétaire n'a rien décidé
  (un dossier sans ligne est « incomplet »).

Droits (relus dans la base à chaque appel : un refus donne une PermissionError, jamais une donnée) :
- consulter la liste : « Lecture » sur « Secrétariat » (ou Administrateur) ;
- déclarer complet ou remettre à incomplet : « Modification » sur « Secrétariat » (ou Administrateur).
Le sous-menu ne concerne que la section « Secondaire et humanitaire » : un élève du primaire n'y apparaît jamais et ne peut pas être
modifié ici. Chaque décision est inscrite au journal (qui, quand, quel élève) ; elle peut être reprise à tout moment.
"""
import config
import donnees
import droits
import sections
from database import iso, journaliser, maintenant

MODULE = "dossier_eleve"
MAX_RESULTATS = 300                      # taille maximale de la liste
ETATS = (("tous", "Tous"), ("complet", "Complets"), ("incomplet", "Incomplets"))
REFUS_SECTION = "Accès refusé : ce sous-menu concerne seulement la section secondaire et humanitaire."


class ErreurSecretariat(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== droits
def peut(conn, session, droit="LECTURE") -> bool:
    """Droit demandé sur « Secrétariat » (ou Administrateur) ET section Secondaire et humanitaire ouverte au compte."""
    if session is None:
        return False
    if sections.SECONDAIRE not in sections.sections_de(conn, session):
        return False
    return droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, droit)


def exiger(conn, session, droit="LECTURE"):
    if not peut(conn, session, droit):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS[droit]} » "
                              f"sur « {config.MODULES_DROITS[MODULE][0]} » (section secondaire et humanitaire).")


# ================================================================== consultation
_ELEVES_SECONDAIRE = (
    "SELECT DISTINCT I.MATRICULE FROM INSCRIRE I JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
    "WHERE N.SECTION = 'SECONDAIRE'")


def _fr(texte) -> str:
    texte = str(texte or "")
    return f"{texte[8:10]}/{texte[5:7]}/{texte[0:4]}" if len(texte) >= 10 and texte[4] == "-" else texte


def liste_dossiers(conn, session, etat="tous", texte="", n_classe=None, annee=None) -> dict:
    """Élèves actifs du secondaire et humanitaire (inscrits cette année ; l'année en cours par défaut) avec l'état de leur dossier.
    Retourne {'annee', 'etat', 'texte', 'resume': {'eleves','complets','incomplets'}, 'eleves': [...], 'tronque': bool}.
    Le résumé porte sur toute la sélection (classe et recherche comprises), avant le filtre d'état."""
    exiger(conn, session)
    annee = str(annee or "").strip() or donnees.annee_courante(conn)
    etat = etat if etat in {e for e, _t in ETATS} else "tous"
    texte = str(texte or "").strip()
    vide = {"annee": annee, "etat": etat, "texte": texte, "resume": {"eleves": 0, "complets": 0, "incomplets": 0}, "eleves": [], "tronque": False}
    if not annee:
        return vide
    cond = ["I.ANNEESCO = ?", "N.SECTION = 'SECONDAIRE'", "E.ACTIF = 1"]
    param = [annee]
    if n_classe:
        cond.append("I.N_CLASSE = ?")
        param.append(int(n_classe))
    if texte:
        cond.append("(E.MATRICULE LIKE ? OR E.NOM LIKE ? OR COALESCE(E.POSTNOM, '') LIKE ? OR COALESCE(E.PRENOM, '') LIKE ?)")
        param += [f"%{texte}%"] * 4
    lignes = conn.execute(
        "SELECT E.MATRICULE, E.NOM, E.POSTNOM, E.PRENOM, E.SEXE, C.N_CLASSE, C.DESI_CLASSE, "
        "       COALESCE(D.COMPLET, 0) AS COMPLET, D.DATE_DECISION, D.DECIDE_PAR "
        "FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE "
        "JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU LEFT JOIN DOSSIER_ELEVE D ON D.MATRICULE = E.MATRICULE "
        f"WHERE {' AND '.join(cond)} ORDER BY C.DESI_CLASSE COLLATE NOCASE, E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE",
        param).fetchall()
    complets = sum(1 for l in lignes if l["COMPLET"])
    gardees = [l for l in lignes if etat == "tous" or (etat == "complet") == bool(l["COMPLET"])]
    eleves = [{"matricule": l["MATRICULE"], "nom_complet": " ".join(x for x in (l["NOM"], l["POSTNOM"], l["PRENOM"]) if x),
               "sexe": l["SEXE"] or "", "n_classe": l["N_CLASSE"], "classe": l["DESI_CLASSE"], "complet": bool(l["COMPLET"]),
               "date": _fr(l["DATE_DECISION"])[:10] if l["DATE_DECISION"] else "", "par": l["DECIDE_PAR"] or ""}
              for l in gardees[:MAX_RESULTATS]]
    journaliser(conn, session.id_user, session.login, "DOSSIERS_ELEVES_CONSULTES",
                f"{annee} | état {etat}" + (f" | recherche « {texte[:40]} »" if texte else ""))
    conn.commit()
    return {"annee": annee, "etat": etat, "texte": texte,
            "resume": {"eleves": len(lignes), "complets": complets, "incomplets": len(lignes) - complets},
            "eleves": eleves, "tronque": len(gardees) > MAX_RESULTATS}


def classes_pour_le_filtre(conn, session, annee=None) -> list:
    """[{n_classe, designation}] des classes du secondaire et humanitaire qui ont des élèves inscrits cette année."""
    exiger(conn, session)
    annee = str(annee or "").strip() or donnees.annee_courante(conn)
    if not annee:
        return []
    return [{"n_classe": l["N_CLASSE"], "designation": l["DESI_CLASSE"]} for l in conn.execute(
        "SELECT DISTINCT C.N_CLASSE, C.DESI_CLASSE FROM INSCRIRE I JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE "
        "JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU WHERE I.ANNEESCO = ? AND N.SECTION = 'SECONDAIRE' "
        "ORDER BY C.DESI_CLASSE COLLATE NOCASE", (annee,))]


# ================================================================== décision de la secrétaire
def definir_etat(conn, session, matricule, complet: bool) -> dict:
    """La secrétaire déclare le dossier de l'élève complet (True) ou incomplet (False). Aucune pièce n'est exigée : rien d'autre que
    l'existence de l'élève (secondaire et humanitaire, actif) n'est vérifié. Retourne {'matricule', 'complet', 'change'}.
    'change' est False si l'état demandé était déjà celui de l'élève (rien n'est écrit, rien n'est journalisé)."""
    exiger(conn, session, "MODIFICATION")
    matricule = str(matricule or "").strip()
    eleve = conn.execute("SELECT MATRICULE, NOM, POSTNOM, PRENOM, ACTIF FROM ELEVE WHERE MATRICULE = ?", (matricule,)).fetchone()
    if not eleve:
        raise ErreurSecretariat("Élève inconnu.")
    if not eleve["ACTIF"]:
        raise ErreurSecretariat("Cet élève est désactivé : son dossier ne peut plus être modifié.")
    if not conn.execute(f"SELECT 1 FROM ({_ELEVES_SECONDAIRE}) WHERE MATRICULE = ?", (eleve["MATRICULE"],)).fetchone():
        raise ErreurSecretariat(REFUS_SECTION)
    complet = bool(complet)
    actuel = conn.execute("SELECT COMPLET FROM DOSSIER_ELEVE WHERE MATRICULE = ?", (eleve["MATRICULE"],)).fetchone()
    if bool(actuel["COMPLET"] if actuel else 0) == complet:
        return {"matricule": eleve["MATRICULE"], "complet": complet, "change": False}
    nom = " ".join(x for x in (eleve["NOM"], eleve["POSTNOM"], eleve["PRENOM"]) if x)
    with conn:
        conn.execute("INSERT INTO DOSSIER_ELEVE (MATRICULE, COMPLET, DATE_DECISION, DECIDE_PAR) VALUES (?,?,?,?) "
                     "ON CONFLICT(MATRICULE) DO UPDATE SET COMPLET = excluded.COMPLET, DATE_DECISION = excluded.DATE_DECISION, "
                     "DECIDE_PAR = excluded.DECIDE_PAR",
                     (eleve["MATRICULE"], int(complet), iso(maintenant()), session.login))
        journaliser(conn, session.id_user, session.login, "DOSSIER_ELEVE_COMPLET" if complet else "DOSSIER_ELEVE_INCOMPLET",
                    f"{eleve['MATRICULE']} | {nom}")
    return {"matricule": eleve["MATRICULE"], "complet": complet, "change": True}

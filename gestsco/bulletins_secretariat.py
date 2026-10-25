"""Secrétariat, 2e fonctionnalité « Bulletins scolaires » (secondaire et humanitaire), sans interface graphique : testable seule.

La secrétaire CONSULTE, IMPRIME et ARCHIVE les bulletins VALIDÉS PAR LA PRÉFECTURE, par classe, par période (période, examen, semestre
ou année) et par option. Elle ne calcule rien, ne valide rien et ne modifie aucun point.

Ce qui est « validé par la Préfecture » (circuit de proclamation.py) : la proclamation de la classe et de la période est CONFIRMÉE par le
Préfet ET le bulletin de l'élève est validé (VALIDE = 1, après la décision de la Directrice des études et, s'il y a lieu, celle du Préfet).
Tant que la proclamation n'est pas confirmée, rien n'apparaît ici ; un élève dont la validation est retirée n'apparaît pas non plus.

Archivage : « Archiver » range dans la base une copie PDF figée des bulletins validés de la classe pour la période (table ARCHIVE_BULLETIN :
qui, quand, combien de bulletins). Plus tard, un recalcul ou un changement de décision ne modifie pas la copie archivée. Chaque archivage
crée une nouvelle copie numérotée (version) ; une archive n'est jamais modifiée ni supprimée par l'application.

Droits (relus dans la base à chaque appel ; refus = PermissionError, jamais une donnée) : consulter, imprimer et rouvrir une archive =
« Lecture » sur « Secrétariat » ; archiver = « Modification » sur « Secrétariat » (ou Administrateur). Section secondaire et humanitaire
seulement. Chaque consultation, impression et archivage est inscrit au journal.
"""
import re

import bulletins
import config
import controle_notes
import donnees
import sections
import secretariat
from database import iso, journaliser, maintenant

SANS_OPTION = "-"                        # valeur du filtre « classes sans option »
MAX_LIGNES = 400


class ErreurBulletinsSecretariat(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== droits et outils
def peut(conn, session, droit="LECTURE") -> bool:
    return secretariat.peut(conn, session, droit)


def exiger(conn, session, droit="LECTURE"):
    secretariat.exiger(conn, session, droit)


def _annee(conn, annee) -> str:
    return controle_notes._annee(conn, annee)


def _fr(texte) -> str:
    texte = str(texte or "")
    return f"{texte[8:10]}/{texte[5:7]}/{texte[0:4]}" if len(texte) >= 10 and texte[4] == "-" else texte


def _portees(conn, annee) -> list:
    return bulletins._portees(conn, annee, sections.SECONDAIRE)


def _libelle_portee(p) -> str:
    return p["libelle"] if p["type"] != "periode" else f"{p['semestre']} - {p['libelle']}"


def _classe(conn, session, n_classe) -> dict:
    """Classe du secondaire et humanitaire visible par le compte."""
    try:
        n = int(n_classe)
    except (TypeError, ValueError):
        raise ErreurBulletinsSecretariat("Choisissez une classe.") from None
    ligne = conn.execute(
        "SELECT C.N_CLASSE, C.DESI_CLASSE, C.CODE_OPTION, O.DESI_OPTION FROM CLASSE C JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
        "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION WHERE C.N_CLASSE = ? AND N.SECTION = 'SECONDAIRE'", (n,)).fetchone()
    if not ligne:
        raise ErreurBulletinsSecretariat("Cette classe n'existe pas au secondaire et humanitaire.")
    sections.exiger_classe(conn, session, n)
    return {"n_classe": ligne["N_CLASSE"], "designation": ligne["DESI_CLASSE"], "option": ligne["DESI_OPTION"] or "",
            "code_option": ligne["CODE_OPTION"] or ""}


def _portee(conn, annee, cle) -> dict:
    cle = str(cle or "").strip().upper()
    p = next((x for x in _portees(conn, annee) if x["cle"] == cle), None)
    if not p:
        raise ErreurBulletinsSecretariat("Choisissez la période, l'examen, le semestre ou l'année.")
    return p


def _validation(conn, annee, n_classe, cle) -> tuple:
    """(proclamation confirmée ?, {matricules validés}, date de confirmation, confirmée par). Seule une proclamation CONFIRMÉE donne des
    bulletins : sinon l'ensemble est vide."""
    ligne = conn.execute("SELECT STATUT, CONFIRMEE_LE, CONFIRMEE_PAR FROM PROCLAMATION WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ?",
                         (annee, n_classe, cle)).fetchone()
    if not ligne or ligne["STATUT"] != "CONFIRMEE":
        return False, set(), "", ""
    valides = {l["MATRICULE"] for l in conn.execute(
        "SELECT MATRICULE FROM VALIDATION_BULLETIN WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ? AND VALIDE = 1", (annee, n_classe, cle))}
    return True, valides, (ligne["CONFIRMEE_LE"] or "")[:10], ligne["CONFIRMEE_PAR"] or ""


def _exiger_validation(conn, annee, n_classe, cle) -> tuple:
    confirmee, valides, le, par = _validation(conn, annee, n_classe, cle)
    if not confirmee:
        raise ErreurBulletinsSecretariat("La proclamation de cette classe pour cette période n'est pas encore confirmée par le Préfet : "
                                         "aucun bulletin n'est disponible.")
    if not valides:
        raise ErreurBulletinsSecretariat("Aucun bulletin validé pour cette classe et cette période.")
    return valides, le, par


def _tracer(conn, session, action, detail):
    journaliser(conn, session.id_user, session.login, action, detail)


# ================================================================== filtres
def filtres(conn, session, annee=None) -> dict:
    """Listes des filtres pour l'année : classes et options ayant au moins une proclamation confirmée, périodes de l'année."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    classes, options = [], {}
    for l in conn.execute(
            "SELECT DISTINCT C.N_CLASSE, C.DESI_CLASSE, C.CODE_OPTION, O.DESI_OPTION FROM PROCLAMATION P JOIN CLASSE C ON C.N_CLASSE = P.N_CLASSE "
            "JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
            "WHERE P.ANNEESCO = ? AND P.STATUT = 'CONFIRMEE' AND N.SECTION = 'SECONDAIRE' ORDER BY C.DESI_CLASSE COLLATE NOCASE", (annee,)):
        if not sections.peut_classe(conn, session, l["N_CLASSE"]):
            continue
        classes.append({"n_classe": l["N_CLASSE"], "designation": l["DESI_CLASSE"], "code_option": l["CODE_OPTION"] or "",
                        "option": l["DESI_OPTION"] or ""})
        if l["CODE_OPTION"]:
            options[l["CODE_OPTION"]] = l["DESI_OPTION"]
    return {"annee": annee, "annees": controle_notes.liste_annees(conn), "classes": classes,
            "options": sorted(options.items(), key=lambda x: x[1].lower()), "sans_option": any(not k["code_option"] for k in classes),
            "portees": [{"cle": p["cle"], "libelle": _libelle_portee(p), "type": p["type"]} for p in _portees(conn, annee)]}


# ================================================================== 1. consulter : bulletins validés par la Préfecture
def liste(conn, session, annee=None, n_classe=None, cle="", option="") -> dict:
    """Bulletins validés par la Préfecture : une ligne par classe et période dont la proclamation est CONFIRMÉE et qui compte au moins un
    bulletin validé. Filtres : classe, période (`cle`), option (code, ou « - » pour les classes sans option).
    Retourne {'annee', 'filtres', 'lignes': [...], 'resume': {...}, 'tronque'}."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    cle = str(cle or "").strip().upper()
    option = str(option or "").strip()
    cond, param = ["P.ANNEESCO = ?", "P.STATUT = 'CONFIRMEE'", "N.SECTION = 'SECONDAIRE'"], [annee]
    if n_classe:
        cond.append("P.N_CLASSE = ?")
        param.append(int(n_classe))
    if cle:
        cond.append("P.CLE = ?")
        param.append(cle)
    if option == SANS_OPTION:
        cond.append("COALESCE(C.CODE_OPTION, '') = ''")
    elif option:
        cond.append("C.CODE_OPTION = ?")
        param.append(option)
    libelles = {p["cle"]: (_libelle_portee(p), i) for i, p in enumerate(_portees(conn, annee))}
    lignes = []
    for l in conn.execute(
            "SELECT P.N_CLASSE, P.CLE, P.CONFIRMEE_LE, P.CONFIRMEE_PAR, C.DESI_CLASSE, O.DESI_OPTION, "
            " (SELECT COUNT(*) FROM VALIDATION_BULLETIN V WHERE V.ANNEESCO = P.ANNEESCO AND V.N_CLASSE = P.N_CLASSE AND V.CLE = P.CLE AND V.VALIDE = 1) AS NB_VALIDES, "
            " (SELECT COUNT(*) FROM ARCHIVE_BULLETIN A WHERE A.ANNEESCO = P.ANNEESCO AND A.N_CLASSE = P.N_CLASSE AND A.CLE = P.CLE) AS NB_ARCHIVES, "
            " (SELECT MAX(A.ARCHIVE_LE) FROM ARCHIVE_BULLETIN A WHERE A.ANNEESCO = P.ANNEESCO AND A.N_CLASSE = P.N_CLASSE AND A.CLE = P.CLE) AS DERNIERE "
            "FROM PROCLAMATION P JOIN CLASSE C ON C.N_CLASSE = P.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
            "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
            f"WHERE {' AND '.join(cond)} ORDER BY C.DESI_CLASSE COLLATE NOCASE", param):
        if not l["NB_VALIDES"] or l["CLE"] not in libelles or not sections.peut_classe(conn, session, l["N_CLASSE"]):
            continue
        lignes.append({"n_classe": l["N_CLASSE"], "classe": l["DESI_CLASSE"], "option": l["DESI_OPTION"] or "", "cle": l["CLE"],
                       "portee": libelles[l["CLE"]][0], "ordre": libelles[l["CLE"]][1], "valides": l["NB_VALIDES"],
                       "confirmee_le": _fr((l["CONFIRMEE_LE"] or "")[:10]), "confirmee_par": l["CONFIRMEE_PAR"] or "",
                       "archives": l["NB_ARCHIVES"], "derniere_archive": _fr((l["DERNIERE"] or "")[:10])})
    lignes.sort(key=lambda x: (x["classe"].lower(), x["ordre"]))
    resume = {"lignes": len(lignes), "bulletins": sum(x["valides"] for x in lignes), "archivees": sum(1 for x in lignes if x["archives"])}
    _tracer(conn, session, "BULLETINS_SECRETARIAT_CONSULTES",
            f"{annee} | classe {n_classe or 'toutes'} | période {cle or 'toutes'} | option {option or 'toutes'}")
    conn.commit()
    return {"annee": annee, "lignes": lignes[:MAX_LIGNES], "tronque": len(lignes) > MAX_LIGNES, "resume": resume, "filtres": filtres(conn, session, annee)}


def detail(conn, session, annee, n_classe, cle) -> dict:
    """Bulletins validés d'une classe pour une période : un élève par ligne (pourcentage, rang, mention, résultat), et les archives déjà faites."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    k = _classe(conn, session, n_classe)
    p = _portee(conn, annee, cle)
    valides, le, par = _exiger_validation(conn, annee, k["n_classe"], p["cle"])
    calc = bulletins.calculer(conn, annee, k["n_classe"])
    eleves = []
    for e in sorted((x for x in calc["eleves"] if x["matricule"] in valides), key=lambda x: x["nom_complet"].lower()):
        r = e["portees"].get(p["cle"]) or {}
        eleves.append({"matricule": e["matricule"], "nom_complet": e["nom_complet"], "pct": r.get("pct"), "rang": r.get("rang"),
                       "mention": r.get("mention") or "", "resultat": r.get("resultat") or "-"})
    _tracer(conn, session, "BULLETINS_SECRETARIAT_CONSULTES", f"{annee} | {k['designation']} | {_libelle_portee(p)} | {len(eleves)} bulletin(s)")
    conn.commit()
    return {"annee": annee, "classe": k, "cle": p["cle"], "portee": _libelle_portee(p), "confirmee_le": _fr(le), "confirmee_par": par,
            "effectif": len(calc["eleves"]), "eleves": eleves, "archives": archives(conn, session, annee, k["n_classe"], p["cle"], journaliser_=False),
            "peut_archiver": peut(conn, session, "MODIFICATION")}


# ================================================================== 2. imprimer
def _pdf(conn, annee, k, p, valides, matricule=None):
    """(octets, nombre de bulletins, nom du fichier) des bulletins validés de la classe (ou d'un seul élève)."""
    import bulletins_pdf
    calc = bulletins.calculer(conn, annee, k["n_classe"])
    titulaire = bulletins.titulaire_de(conn, annee, k["n_classe"])
    calc["titulaire"] = donnees.nom_complet(titulaire) if titulaire else ""
    colonnes = bulletins.colonnes_bulletin(calc["portees"], p["cle"])
    if matricule:
        if str(matricule) not in valides:
            raise ErreurBulletinsSecretariat("Ce bulletin n'est pas validé par la Préfecture : il ne peut pas être imprimé.")
        eleves = [e for e in calc["eleves"] if e["matricule"] == str(matricule)]
    else:
        eleves = [e for e in calc["eleves"] if e["matricule"] in valides]
    if not eleves:
        raise ErreurBulletinsSecretariat("Aucun bulletin validé à imprimer.")
    octets = bulletins_pdf.bulletins(calc, eleves, colonnes)
    nom = bulletins._nom_fichier("bulletin", k["designation"], annee, p["cle"], eleves[0]["nom_complet"] if matricule else "")
    return octets, len(eleves), re.sub(r"\.pdf$", "", nom) + ".pdf"


def document_pdf(conn, session, annee, n_classe, cle, matricule=None):
    """PDF des bulletins validés d'une classe pour une période (ou d'un seul élève, `matricule`). Retourne (octets, nom du fichier).
    Les élèves non validés n'y figurent jamais."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    k = _classe(conn, session, n_classe)
    p = _portee(conn, annee, cle)
    valides, _le, _par = _exiger_validation(conn, annee, k["n_classe"], p["cle"])
    octets, nb, nom = _pdf(conn, annee, k, p, valides, matricule)
    _tracer(conn, session, "BULLETINS_SECRETARIAT_IMPRIMES", f"{annee} | {k['designation']} | {_libelle_portee(p)} | {nb} bulletin(s)")
    conn.commit()
    return octets, nom


# ================================================================== 3. archiver
def archiver(conn, session, annee, n_classe, cle) -> dict:
    """Range une copie PDF figée des bulletins validés de la classe pour la période. Retourne {'id', 'version', 'nb_bulletins', 'taille'}."""
    exiger(conn, session, "MODIFICATION")
    annee = _annee(conn, annee)
    k = _classe(conn, session, n_classe)
    p = _portee(conn, annee, cle)
    valides, _le, _par = _exiger_validation(conn, annee, k["n_classe"], p["cle"])
    octets, nb, nom = _pdf(conn, annee, k, p, valides)
    version = conn.execute("SELECT COUNT(*) FROM ARCHIVE_BULLETIN WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ?",
                           (annee, k["n_classe"], p["cle"])).fetchone()[0] + 1
    nom = re.sub(r"\.pdf$", "", nom) + f"_archive_v{version}.pdf"
    with conn:
        cur = conn.execute("INSERT INTO ARCHIVE_BULLETIN (ANNEESCO, N_CLASSE, CLE, NB_BULLETINS, NOM_FICHIER, CONTENU, TAILLE, ARCHIVE_LE, ARCHIVE_PAR, ID_USER) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?)", (annee, k["n_classe"], p["cle"], nb, nom, octets, len(octets), iso(maintenant()),
                                                            session.login, session.id_user))
        _tracer(conn, session, "BULLETINS_ARCHIVES", f"{annee} | {k['designation']} | {_libelle_portee(p)} | {nb} bulletin(s) | version {version}")
    return {"id": cur.lastrowid, "version": version, "nb_bulletins": nb, "taille": len(octets)}


def archives(conn, session, annee=None, n_classe=None, cle="", option="", journaliser_=True) -> list:
    """Archives de bulletins (la plus récente d'abord) : filtres classe, période et option. Les copies elles-mêmes ne sont pas chargées."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    cond, param = ["A.ANNEESCO = ?", "N.SECTION = 'SECONDAIRE'"], [annee]
    if n_classe:
        cond.append("A.N_CLASSE = ?")
        param.append(int(n_classe))
    if str(cle or "").strip():
        cond.append("A.CLE = ?")
        param.append(str(cle).strip().upper())
    option = str(option or "").strip()
    if option == SANS_OPTION:
        cond.append("COALESCE(C.CODE_OPTION, '') = ''")
    elif option:
        cond.append("C.CODE_OPTION = ?")
        param.append(option)
    libelles = {p["cle"]: _libelle_portee(p) for p in _portees(conn, annee)}
    resultat = []
    for l in conn.execute(
            "SELECT A.ID_ARCHIVE, A.N_CLASSE, A.CLE, A.NB_BULLETINS, A.NOM_FICHIER, A.TAILLE, A.ARCHIVE_LE, A.ARCHIVE_PAR, C.DESI_CLASSE, O.DESI_OPTION "
            "FROM ARCHIVE_BULLETIN A JOIN CLASSE C ON C.N_CLASSE = A.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
            "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
            f"WHERE {' AND '.join(cond)} ORDER BY A.ID_ARCHIVE DESC LIMIT {MAX_LIGNES}", param):
        if not sections.peut_classe(conn, session, l["N_CLASSE"]):
            continue
        resultat.append({"id": l["ID_ARCHIVE"], "n_classe": l["N_CLASSE"], "classe": l["DESI_CLASSE"], "option": l["DESI_OPTION"] or "", "cle": l["CLE"],
                         "portee": libelles.get(l["CLE"], l["CLE"]), "nb_bulletins": l["NB_BULLETINS"], "nom": l["NOM_FICHIER"],
                         "taille_ko": max(1, round(l["TAILLE"] / 1024)), "le": _fr(l["ARCHIVE_LE"][:10]), "heure": l["ARCHIVE_LE"][11:16],
                         "par": l["ARCHIVE_PAR"]})
    if journaliser_:
        _tracer(conn, session, "ARCHIVES_BULLETINS_CONSULTEES", f"{annee} | classe {n_classe or 'toutes'} | période {cle or 'toutes'} | option {option or 'toutes'}")
        conn.commit()
    return resultat


def archive_pdf(conn, session, id_archive):
    """Rouvre une archive : (octets, nom du fichier). La copie est rendue telle qu'elle a été archivée."""
    exiger(conn, session)
    try:
        ident = int(id_archive)
    except (TypeError, ValueError):
        raise ErreurBulletinsSecretariat("Archive inconnue.") from None
    l = conn.execute("SELECT A.*, C.DESI_CLASSE FROM ARCHIVE_BULLETIN A JOIN CLASSE C ON C.N_CLASSE = A.N_CLASSE WHERE A.ID_ARCHIVE = ?", (ident,)).fetchone()
    if not l:
        raise ErreurBulletinsSecretariat("Archive inconnue.")
    sections.exiger_classe(conn, session, l["N_CLASSE"])
    _tracer(conn, session, "ARCHIVE_BULLETINS_OUVERTE", f"{l['ANNEESCO']} | {l['DESI_CLASSE']} | {l['CLE']} | {l['NOM_FICHIER']}")
    conn.commit()
    return bytes(l["CONTENU"]), l["NOM_FICHIER"]

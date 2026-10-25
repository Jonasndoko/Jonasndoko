"""Secrétariat, 3e fonctionnalité « Archives scolaires » (secondaire et humanitaire), sans interface graphique : testable seule.

La secrétaire CLASSE et RETROUVE les bulletins, les dossiers des anciens élèves et les documents des années scolaires précédentes, par
élève et par année scolaire. Trois sortes de documents se trouvent au même endroit :
  1. les documents CLASSÉS ici par la secrétaire (fichier numérisé PDF, JPEG ou PNG de 5 Mo au plus, rangé dans la base : il suit donc les
     sauvegardes). Trois catégories (config.CATEGORIES_ARCHIVES) : bulletin d'une année scolaire, dossier d'un ancien élève (rattachés à un
     élève), document d'une année scolaire (procès-verbal, liste, registre... : sans élève) ;
  2. les copies PDF des bulletins archivés par « Bulletins scolaires » (bulletins_secretariat.py) : une copie par classe et par période,
     retrouvée à partir d'un élève par la classe où il était inscrit cette année-là ;
  3. les documents officiels SIGNÉS par la Préfecture (attestations, certificats : documents_officiels.py), rouverts en PDF.
Seule la catégorie 1 est écrite par cette fonctionnalité ; les catégories 2 et 3 sont seulement retrouvées (lecture seule).

L'année d'un document classé est libre (format AAAA-AAAA) : elle peut précéder l'installation du logiciel. Un « ancien élève » est un élève
du secondaire désactivé ou sans inscription dans l'année en cours ; la recherche peut se limiter à eux.

Rien n'est jamais supprimé : « retirer du classement » (erreur de rangement, par exemple) demande un motif, masque le document de la liste
et du dossier de l'élève, mais le fichier reste dans la base ; la liste peut aussi afficher les documents retirés.

Droits (relus dans la base à chaque appel ; refus = PermissionError, jamais une donnée), sur « Secrétariat » (ou Administrateur) et section
secondaire et humanitaire : Lecture = rechercher, consulter le dossier d'un élève, ouvrir un document ; Modification = classer ;
Suppression = retirer du classement. Chaque recherche, consultation, ouverture, classement et retrait est inscrit au journal.
"""
import hashlib
import re

import config
import donnees
import sections
import secretariat
from database import iso, journaliser, maintenant

FORMATS = {"PDF": ("pdf", b"%PDF-", "application/pdf"), "JPEG": ("jpg", b"\xff\xd8\xff", "image/jpeg"),
           "PNG": ("png", b"\x89PNG\r\n\x1a\n", "image/png")}
GENRE_BULLETIN_CLASSE = "ARCHIVE_BULLETIN"
GENRE_OFFICIEL = "OFFICIEL"
LIBELLE_BULLETIN_CLASSE = "Bulletins de la classe (copie archivée)"
LIBELLE_OFFICIEL = "Document officiel signé"
MAX_RESULTATS = 300
MAX_ELEVES = 30
MAX_TITRE, MAX_NOTE, MAX_MOTIF = 120, 500, 300
_ANNEE = re.compile(r"^\d{4}-\d{4}$")


class ErreurArchives(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== droits et outils
def peut(conn, session, droit="LECTURE") -> bool:
    return secretariat.peut(conn, session, droit)


def exiger(conn, session, droit="LECTURE"):
    secretariat.exiger(conn, session, droit)


def _fr(texte) -> str:
    texte = str(texte or "")
    return f"{texte[8:10]}/{texte[5:7]}/{texte[0:4]}" if len(texte) >= 10 and texte[4] == "-" else texte


def _tracer(conn, session, action, detail):
    journaliser(conn, session.id_user, session.login, action, detail)


def categories() -> list:
    """[{cle, libelle, eleve}] : catégories de classement. `eleve` : le document est rattaché à un élève."""
    return [{"cle": c, "libelle": lib, "eleve": bool(el)} for c, lib, el in config.CATEGORIES_ARCHIVES]


def genres() -> list:
    """[(clé, libellé)] du filtre « Type » de la recherche."""
    return ([(c["cle"], c["libelle"]) for c in categories()] + [(GENRE_BULLETIN_CLASSE, LIBELLE_BULLETIN_CLASSE), (GENRE_OFFICIEL, LIBELLE_OFFICIEL)])


def _libelle_categorie(cle) -> str:
    return next((c["libelle"] for c in categories() if c["cle"] == cle), cle)


def annees(conn) -> list:
    """Années scolaires du logiciel et années des documents classés, la plus récente d'abord."""
    vues = {l[0] for l in conn.execute("SELECT ANNEESCO FROM ANNEE_SCO")}
    vues |= {l[0] for l in conn.execute("SELECT DISTINCT ANNEESCO FROM ARCHIVE_SCOLAIRE")}
    return sorted(vues, reverse=True)


def _format_du_contenu(contenu: bytes):
    """'PDF', 'JPEG' ou 'PNG' d'après le CONTENU du fichier (pas son extension, qu'on peut changer à la main)."""
    return next((nom for nom, (_e, signature, _m) in FORMATS.items() if contenu.startswith(signature)), None)


def type_mime(format_) -> str:
    return FORMATS[format_][2]


def _eleve(conn, session, matricule) -> dict:
    """Élève qui a été inscrit au secondaire et humanitaire (une année quelconque), actif ou non."""
    matricule = str(matricule or "").strip()
    l = conn.execute("SELECT MATRICULE, NOM, POSTNOM, PRENOM, SEXE, DATE_NAISSANCE, LIEU_NAISSANCE, ACTIF FROM ELEVE WHERE MATRICULE = ?",
                     (matricule,)).fetchone()
    if not l:
        raise ErreurArchives("Élève inconnu : vérifiez le matricule.")
    if not conn.execute(f"SELECT 1 FROM ({secretariat._ELEVES_SECONDAIRE}) WHERE MATRICULE = ?", (l["MATRICULE"],)).fetchone():
        raise ErreurArchives(secretariat.REFUS_SECTION)
    return {"matricule": l["MATRICULE"], "nom": donnees.nom_complet(l), "sexe": l["SEXE"] or "", "naissance": _fr(l["DATE_NAISSANCE"]),
            "lieu": l["LIEU_NAISSANCE"] or "", "actif": bool(l["ACTIF"])}


def _anciens(conn) -> set:
    """Matricules des élèves du secondaire désactivés ou sans inscription dans l'année en cours."""
    courante = donnees.annee_courante(conn)
    return {l[0] for l in conn.execute(
        f"SELECT E.MATRICULE FROM ELEVE E WHERE E.MATRICULE IN ({secretariat._ELEVES_SECONDAIRE}) AND (E.ACTIF = 0 OR NOT EXISTS "
        "(SELECT 1 FROM INSCRIRE I WHERE I.MATRICULE = E.MATRICULE AND I.ANNEESCO = ?))", (courante or "",))}


# ================================================================== classer, retirer, ouvrir
def classer(conn, session, annee, categorie, titre, contenu: bytes, nom_fichier, matricule="", note="") -> int:
    """Classe un fichier numérisé dans les archives (droit « Modification »). Retourne le numéro du document classé.
    Une catégorie rattachée à un élève exige son matricule ; une catégorie « année » n'en a pas."""
    exiger(conn, session, "MODIFICATION")
    annee = str(annee or "").strip()
    if not _ANNEE.match(annee) or int(annee[5:]) != int(annee[:4]) + 1:
        raise ErreurArchives("Année scolaire : écrivez-la sous la forme 2022-2023 (deux années qui se suivent).")
    cat = next((c for c in categories() if c["cle"] == str(categorie or "")), None)
    if not cat:
        raise ErreurArchives("Choisissez la catégorie du document.")
    titre = re.sub(r"\s+", " ", str(titre or "")).strip()
    note = str(note or "").replace("\r", "").strip()
    if not titre:
        raise ErreurArchives("Titre : champ obligatoire.")
    if len(titre) > MAX_TITRE:
        raise ErreurArchives(f"Titre : {MAX_TITRE} caractères au plus.")
    if len(note) > MAX_NOTE:
        raise ErreurArchives(f"Note : {MAX_NOTE} caractères au plus.")
    eleve = None
    if cat["eleve"]:
        if not str(matricule or "").strip():
            raise ErreurArchives("Choisissez l'élève : cette catégorie est rattachée à un élève (matricule).")
        eleve = _eleve(conn, session, matricule)
    if not contenu:
        raise ErreurArchives("Le fichier est vide.")
    if len(contenu) > config.TAILLE_MAX_ARCHIVE:
        raise ErreurArchives(f"Le fichier dépasse {config.TAILLE_MAX_ARCHIVE // (1024 * 1024)} Mo : numérisez-le en résolution plus basse.")
    format_ = _format_du_contenu(contenu)
    if not format_:
        raise ErreurArchives("Format non accepté : le document doit être un PDF, une image JPEG ou une image PNG.")
    empreinte = hashlib.sha256(contenu).hexdigest()
    mat = eleve["matricule"] if eleve else None
    if conn.execute("SELECT 1 FROM ARCHIVE_SCOLAIRE WHERE EMPREINTE = ? AND ANNEESCO = ? AND COALESCE(MATRICULE, '') = ? AND RETIRE_LE IS NULL",
                    (empreinte, annee, mat or "")).fetchone():
        raise ErreurArchives("Ce fichier est déjà classé pour cette année" + (" et cet élève." if mat else "."))
    nom_fichier = re.split(r"[\\/]", str(nom_fichier or "document"))[-1][:120] or "document"
    with conn:
        ident = conn.execute(
            "INSERT INTO ARCHIVE_SCOLAIRE (ANNEESCO, MATRICULE, CATEGORIE, TITRE, NOTE, NOM_FICHIER, FORMAT, TAILLE, EMPREINTE, CONTENU, "
            "CLASSE_LE, CLASSE_PAR, ID_USER) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (annee, mat, cat["cle"], titre, note or None, nom_fichier, format_, len(contenu), empreinte, contenu, iso(maintenant()),
             session.login, session.id_user)).lastrowid
        _tracer(conn, session, "ARCHIVE_SCOLAIRE_CLASSEE",
                f"{annee} | {cat['libelle'].split(' (')[0]} | {titre} | {mat or 'sans élève'} | {nom_fichier} | {format_} | {len(contenu)} octets")
    return ident


def retirer(conn, session, id_arch, motif) -> None:
    """Retire un document du classement (droit « Suppression ») : motif obligatoire ; le fichier reste dans la base."""
    exiger(conn, session, "SUPPRESSION")
    l = _ligne(conn, id_arch)
    motif = re.sub(r"\s+", " ", str(motif or "")).strip()
    if not motif:
        raise ErreurArchives("Indiquez le motif du retrait.")
    if len(motif) > MAX_MOTIF:
        raise ErreurArchives(f"Motif : {MAX_MOTIF} caractères au plus.")
    if l["RETIRE_LE"]:
        raise ErreurArchives("Ce document est déjà retiré du classement.")
    with conn:
        conn.execute("UPDATE ARCHIVE_SCOLAIRE SET RETIRE_LE = ?, RETIRE_PAR = ?, MOTIF_RETRAIT = ? WHERE ID_ARCH = ?",
                     (iso(maintenant()), session.login, motif, l["ID_ARCH"]))
        _tracer(conn, session, "ARCHIVE_SCOLAIRE_RETIREE", f"{l['ANNEESCO']} | {l['TITRE']} | {l['MATRICULE'] or 'sans élève'} | motif : {motif}")


def _ligne(conn, id_arch):
    try:
        n = int(id_arch)
    except (TypeError, ValueError):
        raise ErreurArchives("Document introuvable.") from None
    l = conn.execute("SELECT * FROM ARCHIVE_SCOLAIRE WHERE ID_ARCH = ?", (n,)).fetchone()
    if not l:
        raise ErreurArchives("Document introuvable.")
    return l


def ouvrir(conn, session, id_arch) -> tuple:
    """Rouvre un document classé, tel qu'il a été rangé : (octets, format, nom du fichier). Un document retiré reste lisible (piste de contrôle)."""
    exiger(conn, session)
    l = _ligne(conn, id_arch)
    _tracer(conn, session, "ARCHIVE_SCOLAIRE_OUVERTE", f"{l['ANNEESCO']} | {l['TITRE']} | {l['MATRICULE'] or 'sans élève'} | {l['NOM_FICHIER']}")
    conn.commit()
    return bytes(l["CONTENU"]), l["FORMAT"], l["NOM_FICHIER"]


def ouvrir_document_officiel(conn, session, id_doc) -> tuple:
    """PDF d'un document officiel SIGNÉ (lecture seule, droit « Lecture » sur « Secrétariat ») : (octets, nom du fichier)."""
    import documents_officiels
    exiger(conn, session)
    try:
        n = int(id_doc)
    except (TypeError, ValueError):
        raise ErreurArchives("Document introuvable.") from None
    l = conn.execute("SELECT * FROM DOCUMENT_OFFICIEL WHERE ID_DOC = ? AND STATUT = 'SIGNE'", (n,)).fetchone()
    if not l:
        raise ErreurArchives("Document introuvable : seuls les documents signés se rouvrent ici.")
    sections.exiger_classe(conn, session, l["N_CLASSE"])
    e = conn.execute("SELECT NOM, POSTNOM, PRENOM FROM ELEVE WHERE MATRICULE = ?", (l["MATRICULE"],)).fetchone()
    k = conn.execute("SELECT DESI_CLASSE FROM CLASSE WHERE N_CLASSE = ?", (l["N_CLASSE"],)).fetchone()
    d = dict(documents_officiels._vue(l), eleve=donnees.nom_complet(e), classe=k["DESI_CLASSE"])
    octets, nom = documents_officiels.fabriquer_pdf(d)
    _tracer(conn, session, "ARCHIVE_SCOLAIRE_OUVERTE", f"{l['ANNEESCO']} | {l['TITRE']} | {l['MATRICULE']} | {l['NUMERO']}")
    conn.commit()
    return octets, nom


def ouvrir_bulletins_classe(conn, session, id_archive) -> tuple:
    """Rouvre une copie de bulletins archivée par « Bulletins scolaires » : (octets, nom du fichier)."""
    import bulletins_secretariat
    try:
        return bulletins_secretariat.archive_pdf(conn, session, id_archive)
    except bulletins_secretariat.ErreurBulletinsSecretariat as ex:
        raise ErreurArchives(str(ex)) from None


# ================================================================== rechercher
def _eleves_trouves(conn, session, texte, anciens_seulement) -> list:
    """Élèves du secondaire (une année quelconque) dont le nom, le postnom, le prénom ou le matricule contient `texte`."""
    cond, param = [f"E.MATRICULE IN ({secretariat._ELEVES_SECONDAIRE})"], []
    if texte:
        cond.append("(E.MATRICULE LIKE ? OR E.NOM LIKE ? OR COALESCE(E.POSTNOM, '') LIKE ? OR COALESCE(E.PRENOM, '') LIKE ?)")
        param += [f"%{texte}%"] * 4
    anciens = _anciens(conn)
    lignes = []
    for l in conn.execute(f"SELECT E.MATRICULE, E.NOM, E.POSTNOM, E.PRENOM FROM ELEVE E WHERE {' AND '.join(cond)} "
                          "ORDER BY E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE", param):
        if anciens_seulement and l["MATRICULE"] not in anciens:
            continue
        lignes.append({"matricule": l["MATRICULE"], "nom": donnees.nom_complet(l), "ancien": l["MATRICULE"] in anciens})
    return lignes


def _items(conn, session, matricules, annee, genre, retires, texte="") -> list:
    """Documents des trois sources. `matricules` : ensemble d'élèves visés, ou None pour ne pas filtrer par élève.
    Les documents sans élève ne sont gardés que si `matricules` est None ou si le titre contient `texte`."""
    noms = {}
    items = []
    secondaires = {l[0] for l in conn.execute(secretariat._ELEVES_SECONDAIRE)}          # un élève du primaire n'apparaît jamais

    def dans(m):
        return matricules is None or m in matricules

    def nom(m):
        if m not in noms:
            e = conn.execute("SELECT NOM, POSTNOM, PRENOM FROM ELEVE WHERE MATRICULE = ?", (m,)).fetchone()
            noms[m] = donnees.nom_complet(e) if e else m
        return noms[m]

    def classe_de(m, a):
        k = conn.execute("SELECT C.DESI_CLASSE FROM INSCRIRE I JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE WHERE I.MATRICULE = ? AND I.ANNEESCO = ?", (m, a)).fetchone()
        return k["DESI_CLASSE"] if k else ""

    # -- 1. documents classés par la secrétaire
    if genre in ("", *[c["cle"] for c in categories()]):
        cond, param = [], []
        if annee:
            cond.append("A.ANNEESCO = ?")
            param.append(annee)
        if genre:
            cond.append("A.CATEGORIE = ?")
            param.append(genre)
        if not retires:
            cond.append("A.RETIRE_LE IS NULL")
        for l in conn.execute(
                "SELECT A.ID_ARCH, A.ANNEESCO, A.MATRICULE, A.CATEGORIE, A.TITRE, A.NOTE, A.NOM_FICHIER, A.FORMAT, A.TAILLE, A.CLASSE_LE, A.CLASSE_PAR, "
                "A.RETIRE_LE, A.RETIRE_PAR, A.MOTIF_RETRAIT FROM ARCHIVE_SCOLAIRE A" + (f" WHERE {' AND '.join(cond)}" if cond else "") +
                " ORDER BY A.ANNEESCO DESC, A.ID_ARCH DESC", param):
            if l["MATRICULE"]:
                if l["MATRICULE"] not in secondaires or not dans(l["MATRICULE"]):
                    continue
            elif matricules is not None and not (texte and texte.lower() in (l["TITRE"] + " " + (l["NOTE"] or "")).lower()):
                continue
            items.append({"source": "classe", "id": l["ID_ARCH"], "genre": l["CATEGORIE"], "genre_libelle": _libelle_categorie(l["CATEGORIE"]).split(" (")[0],
                          "annee": l["ANNEESCO"], "titre": l["TITRE"], "note": l["NOTE"] or "", "matricule": l["MATRICULE"] or "",
                          "eleve": nom(l["MATRICULE"]) if l["MATRICULE"] else "", "classe": classe_de(l["MATRICULE"], l["ANNEESCO"]) if l["MATRICULE"] else "",
                          "format": l["FORMAT"], "taille_ko": max(1, round(l["TAILLE"] / 1024)), "le": _fr(l["CLASSE_LE"][:10]), "par": l["CLASSE_PAR"],
                          "retire": bool(l["RETIRE_LE"]), "retire_le": _fr((l["RETIRE_LE"] or "")[:10]), "retire_par": l["RETIRE_PAR"] or "",
                          "motif_retrait": l["MOTIF_RETRAIT"] or "", "tri": l["CLASSE_LE"]})
    # -- 2. copies de bulletins archivées par « Bulletins scolaires » (par classe : retrouvées par la classe de l'élève cette année-là)
    if genre in ("", GENRE_BULLETIN_CLASSE):
        import bulletins_secretariat
        cond, param = ["N.SECTION = 'SECONDAIRE'"], []
        if annee:
            cond.append("A.ANNEESCO = ?")
            param.append(annee)
        libelles = {}
        for l in conn.execute(
                "SELECT A.ID_ARCHIVE, A.ANNEESCO, A.N_CLASSE, A.CLE, A.NB_BULLETINS, A.NOM_FICHIER, A.TAILLE, A.ARCHIVE_LE, A.ARCHIVE_PAR, C.DESI_CLASSE "
                "FROM ARCHIVE_BULLETIN A JOIN CLASSE C ON C.N_CLASSE = A.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
                f"WHERE {' AND '.join(cond)} ORDER BY A.ANNEESCO DESC, A.ID_ARCHIVE DESC", param):
            if not sections.peut_classe(conn, session, l["N_CLASSE"]):
                continue
            if l["ANNEESCO"] not in libelles:
                libelles[l["ANNEESCO"]] = {p["cle"]: bulletins_secretariat._libelle_portee(p) for p in bulletins_secretariat._portees(conn, l["ANNEESCO"])}
            eleve, matricule = "", ""
            if matricules is not None:
                inscrits = [r["MATRICULE"] for r in conn.execute("SELECT MATRICULE FROM INSCRIRE WHERE ANNEESCO = ? AND N_CLASSE = ?", (l["ANNEESCO"], l["N_CLASSE"]))
                            if r["MATRICULE"] in matricules]
                if not inscrits:
                    continue
                if len(inscrits) == 1:
                    matricule, eleve = inscrits[0], nom(inscrits[0])
                else:
                    eleve = f"{len(inscrits)} élèves de la classe"
            items.append({"source": "bulletin", "id": l["ID_ARCHIVE"], "genre": GENRE_BULLETIN_CLASSE, "genre_libelle": LIBELLE_BULLETIN_CLASSE,
                          "annee": l["ANNEESCO"], "titre": f"{l['DESI_CLASSE']} · {libelles[l['ANNEESCO']].get(l['CLE'], l['CLE'])} ({l['NB_BULLETINS']} bulletin(s))",
                          "note": "", "matricule": matricule, "eleve": eleve, "classe": l["DESI_CLASSE"], "format": "PDF",
                          "taille_ko": max(1, round(l["TAILLE"] / 1024)), "le": _fr(l["ARCHIVE_LE"][:10]), "par": l["ARCHIVE_PAR"], "retire": False,
                          "retire_le": "", "retire_par": "", "motif_retrait": "", "tri": l["ARCHIVE_LE"]})
    # -- 3. documents officiels signés
    if genre in ("", GENRE_OFFICIEL):
        cond, param = ["D.STATUT = 'SIGNE'"], []
        if annee:
            cond.append("D.ANNEESCO = ?")
            param.append(annee)
        for l in conn.execute(
                "SELECT D.ID_DOC, D.ANNEESCO, D.MATRICULE, D.N_CLASSE, D.TITRE, D.NUMERO, D.SIGNE_LE, D.SIGNE_PAR, C.DESI_CLASSE FROM DOCUMENT_OFFICIEL D "
                f"JOIN CLASSE C ON C.N_CLASSE = D.N_CLASSE WHERE {' AND '.join(cond)} ORDER BY D.ANNEESCO DESC, D.ID_DOC DESC", param):
            if l["MATRICULE"] not in secondaires or not dans(l["MATRICULE"]) or not sections.peut_classe(conn, session, l["N_CLASSE"]):
                continue
            items.append({"source": "officiel", "id": l["ID_DOC"], "genre": GENRE_OFFICIEL, "genre_libelle": LIBELLE_OFFICIEL, "annee": l["ANNEESCO"],
                          "titre": f"{l['TITRE']} n° {l['NUMERO']}", "note": "", "matricule": l["MATRICULE"], "eleve": nom(l["MATRICULE"]),
                          "classe": l["DESI_CLASSE"], "format": "PDF", "taille_ko": 0, "le": _fr((l["SIGNE_LE"] or "")[:10]), "par": l["SIGNE_PAR"] or "",
                          "retire": False, "retire_le": "", "retire_par": "", "motif_retrait": "", "tri": l["SIGNE_LE"] or ""})
    items.sort(key=lambda x: (x["annee"], x["tri"]), reverse=True)
    return items


def rechercher(conn, session, texte="", annee="", genre="", anciens=False, retires=False) -> dict:
    """Recherche dans les archives : `texte` = nom, postnom, prénom ou matricule d'un élève (vide : tous), `annee` = année scolaire (vide :
    toutes), `genre` = type de document (genres()), `anciens` = élèves désactivés ou sans inscription cette année, `retires` = afficher aussi les
    documents retirés du classement. Retourne {'items', 'eleves', 'resume', 'tronque', 'annees', 'genres', ...}."""
    exiger(conn, session)
    texte, annee, genre = str(texte or "").strip(), str(annee or "").strip(), str(genre or "").strip()
    if genre not in {g for g, _l in genres()}:
        genre = ""
    eleves = _eleves_trouves(conn, session, texte, bool(anciens)) if (texte or anciens) else None
    matricules = {e["matricule"] for e in eleves} if eleves is not None else None
    items = _items(conn, session, matricules, annee, genre, bool(retires), texte)
    compte = {}
    for it in items:
        if it["matricule"] and not it["retire"] and it["source"] == "classe":
            compte[it["matricule"]] = compte.get(it["matricule"], 0) + 1
    renvoyes = {l[0] for l in conn.execute("SELECT MATRICULE_ARCHIVE FROM RENVOI")}
    liste_eleves = [dict(e, nb_documents=compte.get(e["matricule"], 0), renvoye=e["matricule"] in renvoyes)
                    for e in (eleves or [])] if texte else []
    _tracer(conn, session, "ARCHIVES_SCOLAIRES_CONSULTEES",
            f"année {annee or 'toutes'} | type {genre or 'tous'}" + (f" | recherche « {texte[:40]} »" if texte else "") + (" | anciens élèves" if anciens else "")
            + (" | avec retirés" if retires else ""))
    conn.commit()
    return {"texte": texte, "annee": annee, "genre": genre, "anciens": bool(anciens), "retires": bool(retires), "items": items[:MAX_RESULTATS],
            "tronque": len(items) > MAX_RESULTATS, "eleves": liste_eleves[:MAX_ELEVES], "eleves_tronque": len(liste_eleves) > MAX_ELEVES,
            "resume": {"documents": len(items), "classes": sum(1 for x in items if x["source"] == "classe" and not x["retire"]),
                       "bulletins": sum(1 for x in items if x["source"] == "bulletin"), "officiels": sum(1 for x in items if x["source"] == "officiel"),
                       "retires": sum(1 for x in items if x["retire"])},
            "annees": annees(conn), "genres": genres(), "peut_classer": peut(conn, session, "MODIFICATION"),
            "peut_retirer": peut(conn, session, "SUPPRESSION")}


def dossier(conn, session, matricule) -> dict:
    """Dossier archivé d'un élève (actuel ou ancien) : identité, parcours (année, classe, option, statut) et tous ses documents, toutes années."""
    exiger(conn, session)
    e = _eleve(conn, session, matricule)
    parcours = [{"annee": l["ANNEESCO"], "classe": l["DESI_CLASSE"], "option": l["DESI_OPTION"] or "", "statut": l["STATUT"] or ""}
                for l in conn.execute(
                    "SELECT I.ANNEESCO, I.STATUT, C.N_CLASSE, C.DESI_CLASSE, O.DESI_OPTION FROM INSCRIRE I JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE "
                    "JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
                    "WHERE I.MATRICULE = ? AND N.SECTION = 'SECONDAIRE' ORDER BY I.ANNEESCO DESC", (e["matricule"],))]
    ancien = e["matricule"] in _anciens(conn)
    import renvoi
    items = _items(conn, session, {e["matricule"]}, "", "", False)
    _tracer(conn, session, "DOSSIER_ARCHIVE_CONSULTE", f"{e['matricule']} | {e['nom']} | {len(items)} document(s)")
    conn.commit()
    return {"eleve": e, "ancien": ancien, "renvoi": renvoi.info(conn, e["matricule"]), "parcours": parcours, "items": items, "annees": annees(conn), "categories": [c for c in categories() if c["eleve"]],
            "peut_classer": peut(conn, session, "MODIFICATION"), "peut_retirer": peut(conn, session, "SUPPRESSION")}

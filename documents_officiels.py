"""Préfecture, fonctionnalité « Documents scolaires officiels » (secondaire et humanitaire), sans interface graphique : testable seule.

Le Préfet PRÉPARE les attestations de fréquentation, certificats de scolarité et autres documents autorisés par l'établissement
(config.DOCUMENTS_OFFICIELS, config.AUTRES_DOCUMENTS_AUTORISES), puis les SOUMET à la signature ou à la validation requise
(config.APPROBATIONS_DOCUMENT). Circuit d'un document :
  BROUILLON : préparé pour un élève inscrit dans l'année (texte proposé, modifiable) ; modifiable tant qu'il n'est pas soumis.
  SOUMIS    : en attente de la signature ou de la validation choisie (signature du Préfet, validation de la Directrice des études ou
              signature d'une autre autorité, nommée). Il n'est plus modifiable.
  SIGNE     : la signature ou la validation est enregistrée (qui, quand) ; un numéro unique est attribué ; le PDF est alors un document
              officiel. Un document soumis peut aussi être renvoyé en brouillon avec un motif.
  ANNULE    : un document soumis ou signé peut être annulé avec un motif ; il reste dans la liste, marqué « Annulé ». Rien n'est supprimé.
Un PDF peut être imprimé à toute étape, mais seul un document SIGNÉ porte un numéro et ne porte pas la mention « PROJET ».

Droits sur « Préfecture » (relus dans la base à chaque appel ; refus = PermissionError) : Lecture = consulter et imprimer ; Ajout =
préparer et modifier un brouillon ; Modification = soumettre, enregistrer la signature ou la validation, renvoyer, annuler.
L'Administrateur a tous les droits. Section secondaire et humanitaire seulement. Chaque étape est inscrite au journal.
"""
import re
from datetime import date

import config
import donnees
import prefecture
import sections
from database import iso, journaliser, maintenant

MAX_TEXTE = 1800
MAX_MOTIF = 300
MAX_LISTE = 300
A_COMPLETER = "[Complétez le texte de ce document.]"
ETATS = (("BROUILLON", "Brouillon"), ("SOUMIS", "Soumis"), ("SIGNE", "Signé ou validé"), ("ANNULE", "Annulé"))


class ErreurDocument(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== droits et outils
def peut(conn, session, droit="LECTURE") -> bool:
    return prefecture.peut(conn, session) if droit == "LECTURE" else prefecture.peut_ecrire(conn, session, droit)


def exiger(conn, session, droit="LECTURE"):
    if not peut(conn, session, droit):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS[droit]} » "
                              f"sur « {config.MODULES_DROITS['prefecture'][0]} » (section secondaire et humanitaire).")


def _fr(texte) -> str:
    texte = str(texte or "")
    return f"{texte[8:10]}/{texte[5:7]}/{texte[0:4]}" if len(texte) >= 10 and texte[4] == "-" else texte


def _tracer(conn, session, action, detail):
    journaliser(conn, session.id_user, session.login, action, detail)


def types_disponibles() -> list:
    """[{cle, titre}] : les types proposés ; pour « AUTRE », un type par titre autorisé (clé « AUTRE:<titre> »)."""
    resultat = []
    for cle, titre in config.DOCUMENTS_OFFICIELS:
        if cle == "AUTRE":
            resultat += [{"cle": f"AUTRE:{t}", "titre": t} for t in config.AUTRES_DOCUMENTS_AUTORISES]
        else:
            resultat.append({"cle": cle, "titre": titre})
    return resultat


def _type(cle) -> tuple:
    """(type, titre) d'après la clé choisie ; ErreurDocument si le document n'est pas autorisé par l'établissement."""
    t = next((x for x in types_disponibles() if x["cle"] == str(cle or "")), None)
    if not t:
        raise ErreurDocument("Ce document n'est pas autorisé par l'établissement.")
    return ("AUTRE" if t["cle"].startswith("AUTRE:") else t["cle"]), t["titre"]


def _inscription(conn, session, annee, matricule) -> dict:
    """Élève du secondaire et humanitaire inscrit dans l'année : identité et classe (copiées dans le document)."""
    annee = prefecture._annee(conn, annee)
    if not annee:
        raise ErreurDocument("Aucune année scolaire n'est enregistrée.")
    l = conn.execute(
        "SELECT E.MATRICULE, E.NOM, E.POSTNOM, E.PRENOM, E.SEXE, E.DATE_NAISSANCE, E.LIEU_NAISSANCE, C.N_CLASSE, C.DESI_CLASSE, O.DESI_OPTION, "
        "I.STATUT FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE "
        "JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
        "WHERE I.ANNEESCO = ? AND E.MATRICULE = ? AND N.SECTION = 'SECONDAIRE'", (annee, str(matricule or "").strip())).fetchone()
    if not l:
        raise ErreurDocument("Cet élève n'est pas inscrit au secondaire et humanitaire pour cette année : vérifiez le matricule.")
    sections.exiger_classe(conn, session, l["N_CLASSE"])
    return {"annee": annee, "matricule": l["MATRICULE"], "nom": donnees.nom_complet(l), "sexe": l["SEXE"] or "", "naissance": _fr(l["DATE_NAISSANCE"]),
            "lieu": l["LIEU_NAISSANCE"] or "", "n_classe": l["N_CLASSE"], "classe": l["DESI_CLASSE"], "option": l["DESI_OPTION"] or "",
            "statut_inscription": l["STATUT"] or ""}


def texte_par_defaut(type_doc, titre, e) -> str:
    """Texte proposé pour le document (le Préfet peut le modifier avant de soumettre)."""
    ne = ("née" if e["sexe"] == "F" else "né") if e["sexe"] else "né(e)"
    inscrit = "inscrite" if e["sexe"] == "F" else "inscrit" if e["sexe"] else "inscrit(e)"
    identite = f"{e['nom']}, {ne}" + (f" à {e['lieu']}" if e["lieu"] else "") + (f" le {e['naissance']}" if e["naissance"] else "") + f", matricule {e['matricule']}"
    classe = e["classe"] + (f", option {e['option']}" if e["option"] else "")
    debut = "Le Préfet des études du " + config.NOM_ECOLE.title()
    if type_doc == "ATTESTATION_FREQUENTATION":
        return (f"{debut} atteste que l'élève {identite}, est régulièrement {inscrit} et fréquente la classe de {classe} "
                f"de cet établissement pendant l'année scolaire {e['annee']}.\n\nLa présente attestation est délivrée à l'intéressé(e) pour servir et valoir ce que de droit.")
    if type_doc == "CERTIFICAT_SCOLARITE":
        return (f"{debut} certifie que l'élève {identite}, est {inscrit} dans la classe de {classe} de cet établissement "
                f"pour l'année scolaire {e['annee']}.\n\nLe présent certificat est délivré à l'intéressé(e) pour servir et valoir ce que de droit.")
    return f"{debut} atteste que l'élève {identite}, est {inscrit} dans la classe de {classe} pour l'année scolaire {e['annee']}.\n\n{A_COMPLETER}"


def _nettoyer(texte, nom, maximum, obligatoire=True) -> str:
    texte = re.sub(r"[ \t]+", " ", str(texte or "").replace("\r", "")).strip()
    texte = re.sub(r"\n{3,}", "\n\n", texte)
    if obligatoire and not texte:
        raise ErreurDocument(f"{nom} : champ obligatoire.")
    if len(texte) > maximum:
        raise ErreurDocument(f"{nom} : {maximum} caractères au plus.")
    return texte


def _ligne(conn, session, id_doc):
    try:
        n = int(id_doc)
    except (TypeError, ValueError):
        raise ErreurDocument("Document introuvable.") from None
    l = conn.execute("SELECT * FROM DOCUMENT_OFFICIEL WHERE ID_DOC = ?", (n,)).fetchone()
    if not l:
        raise ErreurDocument("Document introuvable.")
    sections.exiger_classe(conn, session, l["N_CLASSE"])
    return l


def _etat_exige(l, *statuts):
    if l["STATUT"] not in statuts:
        noms = dict(ETATS)
        raise ErreurDocument(f"Cette étape n'est plus possible : le document est « {noms[l['STATUT']].lower()} ».")


def _libelle_approbation(cle) -> str:
    return dict(config.APPROBATIONS_DOCUMENT).get(cle or "", "")


def _vue(l, noms=None) -> dict:
    return {"id": l["ID_DOC"], "annee": l["ANNEESCO"], "matricule": l["MATRICULE"], "n_classe": l["N_CLASSE"], "type": l["TYPE"], "titre": l["TITRE"],
            "contenu": l["CONTENU"], "statut": l["STATUT"], "statut_libelle": dict(ETATS)[l["STATUT"]], "approbation": l["APPROBATION"] or "",
            "approbation_libelle": _libelle_approbation(l["APPROBATION"]), "signataire": l["SIGNATAIRE"] or "", "motif_retour": l["MOTIF_RETOUR"] or "",
            "numero": l["NUMERO"] or "", "cree_le": _fr(l["CREE_LE"][:10]), "cree_par": l["CREE_PAR"], "soumis_le": _fr((l["SOUMIS_LE"] or "")[:10]),
            "signe_le": _fr((l["SIGNE_LE"] or "")[:10]), "signe_par": l["SIGNE_PAR"] or "", "motif_annulation": l["MOTIF_ANNULATION"] or ""}


# ================================================================== consultation
def eleves_inscrits(conn, session, annee=None) -> dict:
    """Élèves actifs du secondaire et humanitaire inscrits dans l'année, pour choisir l'élève d'un nouveau document."""
    exiger(conn, session)
    annee = prefecture._annee(conn, annee)
    if not annee:
        return {"annee": "", "eleves": []}
    lignes = conn.execute(
        "SELECT E.MATRICULE, E.NOM, E.POSTNOM, E.PRENOM, C.N_CLASSE, C.DESI_CLASSE FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE "
        "JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
        "WHERE I.ANNEESCO = ? AND N.SECTION = 'SECONDAIRE' AND E.ACTIF = 1 ORDER BY C.DESI_CLASSE COLLATE NOCASE, E.NOM COLLATE NOCASE", (annee,)).fetchall()
    return {"annee": annee, "eleves": [{"matricule": l["MATRICULE"], "nom": donnees.nom_complet(l), "classe": l["DESI_CLASSE"]}
                                       for l in lignes if sections.peut_classe(conn, session, l["N_CLASSE"])]}


def liste(conn, session, annee=None, statut="", cle_type="", texte="") -> dict:
    """Documents de l'année (le plus récent d'abord), avec le résumé par état. Filtres : état, type (clé de types_disponibles ou « AUTRE »), recherche."""
    exiger(conn, session)
    annee = prefecture._annee(conn, annee)
    statut = statut if statut in dict(ETATS) else ""
    texte = str(texte or "").strip()
    cond, param = ["D.ANNEESCO = ?"], [annee]
    if cle_type:
        cond.append("D.TITRE = ?")
        param.append(next((x["titre"] for x in types_disponibles() if x["cle"] == cle_type), "?"))
    if texte:
        cond.append("(D.MATRICULE LIKE ? OR E.NOM LIKE ? OR COALESCE(E.POSTNOM, '') LIKE ? OR COALESCE(E.PRENOM, '') LIKE ? OR COALESCE(D.NUMERO, '') LIKE ?)")
        param += [f"%{texte}%"] * 5
    lignes = conn.execute(
        "SELECT D.*, E.NOM, E.POSTNOM, E.PRENOM, C.DESI_CLASSE FROM DOCUMENT_OFFICIEL D JOIN ELEVE E ON E.MATRICULE = D.MATRICULE "
        f"JOIN CLASSE C ON C.N_CLASSE = D.N_CLASSE WHERE {' AND '.join(cond)} ORDER BY D.ID_DOC DESC", param).fetchall() if annee else []
    lignes = [l for l in lignes if sections.peut_classe(conn, session, l["N_CLASSE"])]
    resume = {k: sum(1 for l in lignes if l["STATUT"] == k) for k, _t in ETATS}
    gardees = [l for l in lignes if not statut or l["STATUT"] == statut]
    documents = [dict(_vue(l), eleve=donnees.nom_complet(l), classe=l["DESI_CLASSE"]) for l in gardees[:MAX_LISTE]]
    _tracer(conn, session, "DOCUMENTS_OFFICIELS_CONSULTES", f"{annee} | état {statut or 'tous'}" + (f" | recherche « {texte[:40]} »" if texte else ""))
    conn.commit()
    return {"annee": annee, "annees": prefecture.liste_annees(conn), "statut": statut, "type": cle_type, "texte": texte, "resume": resume,
            "documents": documents, "tronque": len(gardees) > MAX_LISTE, "types": types_disponibles(), "etats": ETATS,
            "approbations": config.APPROBATIONS_DOCUMENT,
            "peut_ajout": peut(conn, session, "AJOUT"), "peut_modif": peut(conn, session, "MODIFICATION")}


def lire(conn, session, id_doc) -> dict:
    exiger(conn, session)
    l = _ligne(conn, session, id_doc)
    e = conn.execute("SELECT NOM, POSTNOM, PRENOM FROM ELEVE WHERE MATRICULE = ?", (l["MATRICULE"],)).fetchone()
    k = conn.execute("SELECT DESI_CLASSE FROM CLASSE WHERE N_CLASSE = ?", (l["N_CLASSE"],)).fetchone()
    return dict(_vue(l), eleve=donnees.nom_complet(e), classe=k["DESI_CLASSE"])


# ================================================================== préparer
def preparer(conn, session, annee, matricule, cle_type, contenu="") -> int:
    """Prépare un brouillon pour un élève inscrit (droit « Ajout »). `contenu` vide : texte proposé. Retourne le numéro du document."""
    exiger(conn, session, "AJOUT")
    type_doc, titre = _type(cle_type)
    e = _inscription(conn, session, annee, matricule)
    texte = _nettoyer(contenu, "Texte du document", MAX_TEXTE, obligatoire=False) or texte_par_defaut(type_doc, titre, e)
    with conn:
        cur = conn.execute("INSERT INTO DOCUMENT_OFFICIEL (ANNEESCO, MATRICULE, N_CLASSE, TYPE, TITRE, CONTENU, CREE_LE, CREE_PAR) VALUES (?,?,?,?,?,?,?,?)",
                           (e["annee"], e["matricule"], e["n_classe"], type_doc, titre, texte, iso(maintenant()), session.login))
        _tracer(conn, session, "DOCUMENT_OFFICIEL_PREPARE", f"N° interne {cur.lastrowid} | {titre} | {e['matricule']} | {e['annee']}")
    return cur.lastrowid


def modifier(conn, session, id_doc, contenu) -> None:
    """Modifie le texte d'un brouillon (droit « Ajout »)."""
    exiger(conn, session, "AJOUT")
    l = _ligne(conn, session, id_doc)
    _etat_exige(l, "BROUILLON")
    texte = _nettoyer(contenu, "Texte du document", MAX_TEXTE)
    with conn:
        conn.execute("UPDATE DOCUMENT_OFFICIEL SET CONTENU = ? WHERE ID_DOC = ?", (texte, l["ID_DOC"]))
        _tracer(conn, session, "DOCUMENT_OFFICIEL_MODIFIE", f"N° interne {l['ID_DOC']} | {l['TITRE']} | {l['MATRICULE']}")


# ================================================================== soumettre, signer, renvoyer, annuler
def soumettre(conn, session, id_doc, approbation, signataire="") -> None:
    """Soumet un brouillon à la signature ou à la validation requise (droit « Modification »). Pour « signature d'une autre autorité », le nom
    ou la fonction du signataire est obligatoire. Le texte doit être complet."""
    exiger(conn, session, "MODIFICATION")
    l = _ligne(conn, session, id_doc)
    _etat_exige(l, "BROUILLON")
    if approbation not in dict(config.APPROBATIONS_DOCUMENT):
        raise ErreurDocument("Choisissez la signature ou la validation requise.")
    signataire = _nettoyer(signataire, "Signataire", 100, obligatoire=approbation == "SIGNATURE_AUTRE")
    if A_COMPLETER in l["CONTENU"]:
        raise ErreurDocument("Le texte du document n'est pas complet : remplacez la mention « Complétez le texte » avant de soumettre.")
    with conn:
        conn.execute("UPDATE DOCUMENT_OFFICIEL SET STATUT = 'SOUMIS', APPROBATION = ?, SIGNATAIRE = ?, MOTIF_RETOUR = NULL, SOUMIS_LE = ?, SOUMIS_PAR = ? "
                     "WHERE ID_DOC = ?", (approbation, signataire or None, iso(maintenant()), session.login, l["ID_DOC"]))
        _tracer(conn, session, "DOCUMENT_OFFICIEL_SOUMIS", f"N° interne {l['ID_DOC']} | {l['TITRE']} | {l['MATRICULE']} | {_libelle_approbation(approbation)}")


def _numero(conn, l) -> str:
    """N° <ordre>/<année>/<sigle> : ordre par année et par type de document (jamais redonné : les documents ne sont pas supprimés)."""
    ordre = conn.execute("SELECT COUNT(*) FROM DOCUMENT_OFFICIEL WHERE ANNEESCO = ? AND TITRE = ? AND NUMERO IS NOT NULL", (l["ANNEESCO"], l["TITRE"])).fetchone()[0] + 1
    sigle = "".join(m[0] for m in re.findall(r"[A-Za-zÀ-ÿ]{3,}", l["TITRE"])).upper()[:4] or "DOC"
    sigle = donnees.sans_accents(sigle).upper()
    while True:
        numero = f"{ordre:03d}/{l['ANNEESCO']}/{sigle}"
        if not conn.execute("SELECT 1 FROM DOCUMENT_OFFICIEL WHERE NUMERO = ?", (numero,)).fetchone():
            return numero
        ordre += 1


def signer(conn, session, id_doc, signataire="") -> str:
    """Enregistre la signature ou la validation d'un document soumis (droit « Modification ») et lui attribue son numéro. `signataire` : la personne
    qui a signé ou validé (par défaut le compte du Préfet pour la signature du Préfet, ou le nom indiqué à la soumission). Retourne le numéro."""
    exiger(conn, session, "MODIFICATION")
    l = _ligne(conn, session, id_doc)
    _etat_exige(l, "SOUMIS")
    nom = _nettoyer(signataire, "Signataire", 100, obligatoire=False) or l["SIGNATAIRE"] or (
        (session.nom_complet or session.login) if l["APPROBATION"] == "SIGNATURE_PREFET" else _libelle_approbation(l["APPROBATION"]))
    with conn:
        numero = _numero(conn, l)
        conn.execute("UPDATE DOCUMENT_OFFICIEL SET STATUT = 'SIGNE', NUMERO = ?, SIGNATAIRE = ?, SIGNE_LE = ?, SIGNE_PAR = ? WHERE ID_DOC = ?",
                     (numero, nom, iso(maintenant()), session.login, l["ID_DOC"]))
        _tracer(conn, session, "DOCUMENT_OFFICIEL_SIGNE", f"N° {numero} | {l['TITRE']} | {l['MATRICULE']} | {_libelle_approbation(l['APPROBATION'])}")
    return numero


def renvoyer(conn, session, id_doc, motif) -> None:
    """Renvoie un document soumis en brouillon, avec un motif (droit « Modification »)."""
    exiger(conn, session, "MODIFICATION")
    l = _ligne(conn, session, id_doc)
    _etat_exige(l, "SOUMIS")
    motif = _nettoyer(motif, "Motif du renvoi", MAX_MOTIF)
    if len(motif) < 5:
        raise ErreurDocument("Motif du renvoi : donnez au moins quelques mots.")
    with conn:
        conn.execute("UPDATE DOCUMENT_OFFICIEL SET STATUT = 'BROUILLON', MOTIF_RETOUR = ? WHERE ID_DOC = ?", (motif, l["ID_DOC"]))
        _tracer(conn, session, "DOCUMENT_OFFICIEL_RENVOYE", f"N° interne {l['ID_DOC']} | {l['TITRE']} | {l['MATRICULE']}")


def annuler(conn, session, id_doc, motif) -> None:
    """Annule un document soumis ou signé, avec un motif (droit « Modification »). Il reste dans la liste. Un brouillon ne s'annule pas : on le modifie."""
    exiger(conn, session, "MODIFICATION")
    l = _ligne(conn, session, id_doc)
    _etat_exige(l, "SOUMIS", "SIGNE")
    motif = _nettoyer(motif, "Motif de l'annulation", MAX_MOTIF)
    if len(motif) < 5:
        raise ErreurDocument("Motif de l'annulation : donnez au moins quelques mots.")
    with conn:
        conn.execute("UPDATE DOCUMENT_OFFICIEL SET STATUT = 'ANNULE', ANNULE_LE = ?, ANNULE_PAR = ?, MOTIF_ANNULATION = ? WHERE ID_DOC = ?",
                     (iso(maintenant()), session.login, motif, l["ID_DOC"]))
        _tracer(conn, session, "DOCUMENT_OFFICIEL_ANNULE", f"{l['NUMERO'] or 'N° interne ' + str(l['ID_DOC'])} | {l['TITRE']} | {l['MATRICULE']}")


# ================================================================== impression
def fabriquer_pdf(d) -> tuple:
    """(octets, nom du fichier) du PDF d'un document déjà lu (dictionnaire de `lire`). Sans contrôle de droit : l'appelant l'a fait."""
    import document_officiel_pdf
    import bulletins
    with open(config.DOSSIER_ASSETS / "armoiries_rdc.jpg", "rb") as f:
        jpeg = f.read()
    date_edition = (d["signe_le"] if d["statut"] == "SIGNE" else "") or date.today().strftime("%d/%m/%Y")
    octets = document_officiel_pdf.generer(
        dict(d, ville=config.VILLE_BULLETIN, date_edition=date_edition, approbation=d["approbation_libelle"]),
        {"ecole": config.NOM_ECOLE, "devise": config.DEVISE_ECOLE}, jpeg)
    nom = bulletins._nom_fichier(d["titre"], d["eleve"], d["annee"], d["numero"].replace("/", "-") if d["numero"] else "projet")
    return octets, nom + ".pdf"


def document_pdf(conn, session, id_doc):
    """PDF d'un document, à son état actuel (« PROJET » tant qu'il n'est pas signé). Retourne (octets, nom du fichier)."""
    exiger(conn, session)
    d = lire(conn, session, id_doc)
    octets, nom = fabriquer_pdf(d)
    nom = nom[:-4]
    _tracer(conn, session, "DOCUMENT_OFFICIEL_IMPRIME", f"{d['numero'] or 'N° interne ' + str(d['id'])} | {d['titre']} | {d['matricule']} | {d['statut_libelle']}")
    conn.commit()
    return octets, nom + ".pdf"

"""Module « Gestion du personnel » - première fonctionnalité : DOSSIER PERSONNEL (sans interface : testable seul).

Ce que le dossier permet :
  - enregistrer un nouvel agent : nom, postnom, prénom, sexe, date de naissance, adresse, téléphone, e-mail, matricule,
    date d'engagement, fonction et statut professionnel ;
  - consulter et modifier ses informations (le matricule ne change plus après la création) ;
  - joindre ses documents administratifs numérisés (PDF, JPEG ou PNG, 5 Mo au plus chacun) et les rouvrir ;
  - consulter et imprimer sa fiche individuelle (PDF, une page).

Un agent n'est jamais supprimé : quand il quitte l'école on le DÉSACTIVE (son dossier est conservé).

Droits (module « personnel », Gestionnaire d'accès ; l'Administrateur les a tous) :
  - Lecture       : ouvrir le module, consulter un dossier, ouvrir un document, imprimer la fiche individuelle ;
  - Ajout         : enregistrer un agent, joindre un document ;
  - Modification  : modifier les informations d'un agent, le désactiver ou le réactiver ;
  - Suppression   : retirer un document joint par erreur.
Chaque droit est relu dans la base au moment de l'action, et chaque opération est inscrite au journal.
"""
import hashlib
import re
import sqlite3
import time
from datetime import date

import config
import donnees
import droits
from database import iso, journaliser, maintenant
from saisie_date import lire_date_texte

MODULE = "personnel"

STATUTS = {"PERMANENT": "Permanent", "CONTRACTUEL": "Contractuel", "VACATAIRE": "Vacataire",
           "STAGIAIRE": "Stagiaire", "TEMPORAIRE": "Temporaire"}
# Fonctions proposées dans la liste ; on peut aussi en taper une autre (une école a toujours une fonction imprévue).
FONCTIONS = ("Préfet", "Directrice des études", "Secrétaire", "Intendant", "Percepteur", "Contrôleur", "Enseignant",
             "Surveillant", "Comptable", "Bibliothécaire", "Laborantin", "Gardien", "Agent d'entretien")
TYPES_DOCUMENT = ("Pièce d'identité", "Contrat d'engagement", "Lettre d'engagement ou de nomination", "Diplôme",
                  "Curriculum vitae", "Certificat médical", "Attestation de service", "Autre document")

TAILLE_MAX_DOCUMENT = 5 * 1024 * 1024          # 5 Mo
FORMATS = {"PDF": ("pdf", b"%PDF-"), "JPEG": ("jpg", b"\xff\xd8\xff"), "PNG": ("png", b"\x89PNG\r\n\x1a\n")}
AGE_MIN, AGE_MAX = 16, 80                      # bornes de plausibilité de la date de naissance d'un agent (en années)
# La fonction n'est pas modifiable ici : elle change par une AFFECTATION (Fonctions et affectations), pour que
# l'historique des changements de fonction soit complet.
CHAMPS_MODIFIABLES = ("NOM", "POSTNOM", "PRENOM", "SEXE", "DATE_NAISSANCE", "ADRESSE", "TELEPHONE", "EMAIL",
                      "DATE_ENGAGEMENT", "STATUT_PRO")
LIBELLES_CHAMPS = {"NOM": "nom", "POSTNOM": "postnom", "PRENOM": "prénom", "SEXE": "sexe",
                   "DATE_NAISSANCE": "date de naissance", "ADRESSE": "adresse", "TELEPHONE": "téléphone",
                   "EMAIL": "e-mail", "DATE_ENGAGEMENT": "date d'engagement", "FONCTION": "fonction",
                   "STATUT_PRO": "statut professionnel"}


class ErreurPersonnel(Exception):
    """Erreur métier dont le message peut être affiché tel quel à l'utilisateur."""


# ------------------------------------------------------------------ droits
def peut(conn, session, droit) -> bool:
    return droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, droit)


def exiger(conn, session, droit):
    if not peut(conn, session, droit):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS.get(droit, droit)} » "
                              f"sur le module « {config.MODULES_DROITS[MODULE][0]} ».")


# ------------------------------------------------------------------ lecture des saisies
def _texte(valeur) -> str:
    return " ".join((valeur or "").split())


def _obligatoire(valeur, nom) -> str:
    texte = _texte(valeur)
    if not texte:
        raise ErreurPersonnel(f"Renseignez {nom}.")
    return texte


def _age(naissance: date, jour: date) -> int:
    return jour.year - naissance.year - ((jour.month, jour.day) < (naissance.month, naissance.day))


def lire_date_naissance(texte) -> date:
    jour = lire_date_texte(texte)
    if jour is None:
        raise ErreurPersonnel("Date de naissance invalide. Écrivez-la ainsi : 15/03/1985")
    aujourdhui = date.today()
    if jour > aujourdhui:
        raise ErreurPersonnel("La date de naissance ne peut pas être dans le futur.")
    age = _age(jour, aujourdhui)
    if age < AGE_MIN or age > AGE_MAX:
        raise ErreurPersonnel(f"La date de naissance donne {age} an(s) : vérifiez-la "
                              f"(un agent a entre {AGE_MIN} et {AGE_MAX} ans).")
    return jour


def lire_date_engagement(texte, naissance: date) -> date:
    jour = lire_date_texte(texte)
    if jour is None:
        raise ErreurPersonnel("Date d'engagement invalide. Écrivez-la ainsi : 01/09/2020")
    if jour > date.today():
        raise ErreurPersonnel("La date d'engagement ne peut pas être dans le futur.")
    if _age(naissance, jour) < AGE_MIN:
        raise ErreurPersonnel(f"La date d'engagement est incohérente : l'agent n'avait pas {AGE_MIN} ans à cette date.")
    return jour


def lire_telephone(texte) -> str:
    tel = _texte(texte)
    if not tel:
        raise ErreurPersonnel("Renseignez le numéro de téléphone de l'agent.")
    if not re.fullmatch(r"[0-9+()\-./ ]+", tel) or len(re.sub(r"\D", "", tel)) < 6:
        raise ErreurPersonnel("Le numéro de téléphone est invalide (chiffres, +, espaces ; 6 chiffres au moins).")
    return tel


def lire_email(texte) -> str:
    """Adresse e-mail (Gmail ou autre) : facultative, mais correcte si elle est donnée. Enregistrée en minuscules."""
    adresse = _texte(texte).lower()
    if not adresse:
        return ""
    if len(adresse) > 120 or not re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)*\.[a-z]{2,}", adresse):
        raise ErreurPersonnel("L'adresse e-mail est invalide. Exemple : prenom.nom@gmail.com")
    return adresse


def lire_matricule(texte) -> str:
    """Matricule saisi (vide = attribué par le système). Lettres, chiffres, « / », « - » et « . » seulement."""
    m = _texte(texte).upper()
    if not m:
        return ""
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9/.\-]{1,23}", m):
        raise ErreurPersonnel("Le matricule est invalide : lettres, chiffres, « / » et « - » seulement "
                              "(2 à 24 caractères). Laissez-le vide pour que le système l'attribue.")
    return m


def _valider(saisie: dict, avec_fonction=True) -> dict:
    """Contrôle les champs communs à l'enregistrement et à la modification. Retourne les valeurs prêtes pour la base."""
    nom = _obligatoire(saisie.get("nom"), "le nom de l'agent").upper()
    sexe = (saisie.get("sexe") or "").strip().upper()
    if sexe not in ("M", "F"):
        raise ErreurPersonnel("Choisissez le sexe de l'agent.")
    naissance = lire_date_naissance(saisie.get("date_naissance"))
    statut = (saisie.get("statut_pro") or "").strip().upper()
    if statut not in STATUTS:                                        # le libellé affiché est accepté aussi
        statut = next((c for c, l in STATUTS.items() if l.lower() == statut.lower()), "")
    return {
        "NOM": nom,
        "POSTNOM": _texte(saisie.get("postnom")).upper() or None,
        "PRENOM": _texte(saisie.get("prenom")).title() or None,
        "SEXE": sexe,
        "DATE_NAISSANCE": naissance.isoformat(),
        "ADRESSE": _obligatoire(saisie.get("adresse"), "l'adresse de l'agent"),
        "TELEPHONE": lire_telephone(saisie.get("telephone")),
        "EMAIL": lire_email(saisie.get("email")) or None,
        "DATE_ENGAGEMENT": lire_date_engagement(saisie.get("date_engagement"), naissance).isoformat(),
        "FONCTION": _obligatoire(saisie.get("fonction"), "la fonction de l'agent") if avec_fonction else None,
        "STATUT_PRO": statut or _erreur("Choisissez le statut professionnel de l'agent."),
    }


def _erreur(message):
    raise ErreurPersonnel(message)


# ------------------------------------------------------------------ matricule
def nouveau_matricule(conn, jour: date = None) -> str:
    """Réserve et retourne le prochain matricule d'agent : « P0001/26 » (numéro d'ordre / année d'engagement).
    Compteur propre aux agents (clé « P26 » de MATRICULE_SEQ) ; il ne recule jamais. À appeler dans la transaction d'ajout."""
    cle = f"P{(jour or date.today()).year % 100:02d}"
    while True:
        conn.execute("INSERT OR IGNORE INTO MATRICULE_SEQ (ANNEE, DERNIER) VALUES (?, 0)", (cle,))
        conn.execute("UPDATE MATRICULE_SEQ SET DERNIER = DERNIER + 1 WHERE ANNEE = ?", (cle,))
        ordre = conn.execute("SELECT DERNIER FROM MATRICULE_SEQ WHERE ANNEE = ?", (cle,)).fetchone()[0]
        matricule = f"P{ordre:04d}/{cle[1:]}"
        if not conn.execute("SELECT 1 FROM PERSONNEL WHERE MATRICULE = ?", (matricule,)).fetchone():
            return matricule


# ------------------------------------------------------------------ enregistrement et modification
def enregistrer_agent(conn, session, saisie: dict) -> dict:
    """Enregistre un nouvel agent. Retourne {'matricule', 'nom_complet'}."""
    exiger(conn, session, "AJOUT")
    valeurs = _valider(saisie)
    matricule = lire_matricule(saisie.get("matricule"))
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if matricule:
            if conn.execute("SELECT 1 FROM PERSONNEL WHERE MATRICULE = ?", (matricule,)).fetchone():
                raise ErreurPersonnel(f"Le matricule {matricule} est déjà attribué à un autre agent.")
        else:
            matricule = nouveau_matricule(conn)
        import affectations
        fonction = affectations.obtenir_fonction(conn, valeurs["FONCTION"])   # créée si elle n'existe pas encore
        valeurs["FONCTION"] = fonction["LIBELLE"]
        conn.execute(
            "INSERT INTO PERSONNEL (MATRICULE, NOM, POSTNOM, PRENOM, SEXE, DATE_NAISSANCE, ADRESSE, TELEPHONE, EMAIL, "
            "DATE_ENGAGEMENT, FONCTION, STATUT_PRO, ACTIF, DATE_ENREG, ENREGISTRE_PAR) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
            (matricule, valeurs["NOM"], valeurs["POSTNOM"], valeurs["PRENOM"], valeurs["SEXE"], valeurs["DATE_NAISSANCE"],
             valeurs["ADRESSE"], valeurs["TELEPHONE"], valeurs["EMAIL"], valeurs["DATE_ENGAGEMENT"], valeurs["FONCTION"],
             valeurs["STATUT_PRO"], iso(maintenant()), session.login))
        affectations.creer_initiale(conn, matricule, fonction["ID_FONCTION"], valeurs["DATE_ENGAGEMENT"], session.login)
        journaliser(conn, session.id_user, session.login, "AGENT_ENREGISTRE",
                    f"{matricule} | {valeurs['NOM']} | {valeurs['FONCTION']} | {STATUTS[valeurs['STATUT_PRO']]}")
        conn.commit()
    except sqlite3.IntegrityError as erreur:
        conn.rollback()
        raise ErreurPersonnel(f"Enregistrement impossible : {erreur}") from None
    except BaseException:
        conn.rollback()
        raise
    return {"matricule": matricule,
            "nom_complet": " ".join(p for p in (valeurs["NOM"], valeurs["POSTNOM"], valeurs["PRENOM"]) if p)}


def _ligne(conn, matricule):
    ligne = conn.execute("SELECT * FROM PERSONNEL WHERE MATRICULE = ?", (matricule,)).fetchone()
    if not ligne:
        raise ErreurPersonnel("Agent introuvable.")
    return ligne


def modifier_agent(conn, session, matricule, saisie: dict) -> list:
    """Modifie les informations d'un agent (pas son matricule ni sa fonction : voir affectations.py). Retourne la liste des champs réellement changés
    (vide : rien n'a changé, rien n'est écrit)."""
    exiger(conn, session, "MODIFICATION")
    valeurs = _valider(saisie, avec_fonction=False)
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        avant = _ligne(conn, matricule)
        changes = [c for c in CHAMPS_MODIFIABLES if (avant[c] or None) != (valeurs[c] or None)]
        if changes:
            conn.execute("UPDATE PERSONNEL SET " + ", ".join(f"{c} = ?" for c in CHAMPS_MODIFIABLES)
                         + ", DATE_MODIF = ?, MODIFIE_PAR = ? WHERE MATRICULE = ?",
                         [valeurs[c] for c in CHAMPS_MODIFIABLES] + [iso(maintenant()), session.login, avant["MATRICULE"]])
            journaliser(conn, session.id_user, session.login, "AGENT_MODIFIE",
                        f"{avant['MATRICULE']} | " + ", ".join(LIBELLES_CHAMPS[c] for c in changes))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return [LIBELLES_CHAMPS[c] for c in changes]


def changer_activite(conn, session, matricule, actif: bool):
    """Désactive (l'agent a quitté l'école) ou réactive un agent. Le dossier et les documents sont conservés."""
    exiger(conn, session, "MODIFICATION")
    ligne = _ligne(conn, matricule)
    if bool(ligne["ACTIF"]) == bool(actif):
        return
    with conn:
        conn.execute("UPDATE PERSONNEL SET ACTIF = ?, DATE_MODIF = ?, MODIFIE_PAR = ? WHERE MATRICULE = ?",
                     (1 if actif else 0, iso(maintenant()), session.login, ligne["MATRICULE"]))
        journaliser(conn, session.id_user, session.login, "AGENT_ACTIVE" if actif else "AGENT_DESACTIVE", ligne["MATRICULE"])


# ------------------------------------------------------------------ consultation
def _formater(texte) -> str:
    """'2010-03-25' -> '25/03/2010'."""
    return date.fromisoformat(texte).strftime("%d/%m/%Y") if texte else ""


def _vers_dict(l, nb_documents=0) -> dict:
    return {
        "matricule": l["MATRICULE"], "nom": l["NOM"], "postnom": l["POSTNOM"] or "", "prenom": l["PRENOM"] or "",
        "nom_complet": donnees.nom_complet(l), "sexe": l["SEXE"], "libelle_sexe": "Masculin" if l["SEXE"] == "M" else "Féminin",
        "date_naissance": _formater(l["DATE_NAISSANCE"]), "adresse": l["ADRESSE"], "telephone": l["TELEPHONE"],
        "email": l["EMAIL"] or "", "date_engagement": _formater(l["DATE_ENGAGEMENT"]), "fonction": l["FONCTION"],
        "statut_pro": l["STATUT_PRO"], "libelle_statut": STATUTS.get(l["STATUT_PRO"], l["STATUT_PRO"]),
        "actif": bool(l["ACTIF"]), "nb_documents": nb_documents,
        "date_enreg": _formater(l["DATE_ENREG"][:10]), "enregistre_par": l["ENREGISTRE_PAR"],
        "date_modif": _formater(l["DATE_MODIF"][:10]) if l["DATE_MODIF"] else "", "modifie_par": l["MODIFIE_PAR"] or "",
    }


def rechercher(conn, session, texte="", inclure_inactifs=True) -> list:
    """Agents dont le matricule, le nom, la fonction ou le téléphone contient chaque mot saisi (accents et casse ignorés),
    par ordre alphabétique."""
    exiger(conn, session, "LECTURE")
    fragments = [donnees.sans_accents(f) for f in _texte(texte).split()]
    nb_docs = {l[0]: l[1] for l in conn.execute("SELECT MATRICULE, COUNT(*) FROM DOCUMENT_PERSONNEL GROUP BY MATRICULE")}
    resultat = []
    for l in conn.execute("SELECT * FROM PERSONNEL ORDER BY NOM COLLATE NOCASE, POSTNOM COLLATE NOCASE, PRENOM COLLATE NOCASE"):
        if not inclure_inactifs and not l["ACTIF"]:
            continue
        if fragments:
            meule = donnees.sans_accents(f"{l['MATRICULE']} {donnees.nom_complet(l)} {l['FONCTION']} {l['TELEPHONE']}")
            if not all(f in meule for f in fragments):
                continue
        resultat.append(_vers_dict(l, nb_docs.get(l["MATRICULE"], 0)))
    return resultat


def charger_agent(conn, session, matricule) -> dict:
    exiger(conn, session, "LECTURE")
    l = _ligne(conn, matricule)
    nb = conn.execute("SELECT COUNT(*) FROM DOCUMENT_PERSONNEL WHERE MATRICULE = ?", (l["MATRICULE"],)).fetchone()[0]
    return _vers_dict(l, nb)


def consulter_dossier(conn, session, matricule) -> dict:
    """Comme charger_agent, et la consultation est inscrite au journal (données personnelles)."""
    agent = charger_agent(conn, session, matricule)
    with conn:
        journaliser(conn, session.id_user, session.login, "AGENT_CONSULTE", agent["matricule"])
    return agent


# ------------------------------------------------------------------ documents numérisés
def _format_du_contenu(contenu: bytes):
    """'PDF', 'JPEG' ou 'PNG' d'après le CONTENU du fichier (pas son extension, qu'on peut changer à la main)."""
    return next((nom for nom, (_ext, signature) in FORMATS.items() if contenu.startswith(signature)), None)


def ajouter_document(conn, session, matricule, type_doc, chemin) -> int:
    """Joint un document numérisé (fichier du poste) au dossier de l'agent. Retourne son numéro."""
    exiger(conn, session, "AJOUT")
    try:
        with open(chemin, "rb") as f:
            contenu = f.read(TAILLE_MAX_DOCUMENT + 1)
    except OSError as erreur:
        raise ErreurPersonnel(f"Le fichier n'a pas pu être lu : {erreur.strerror or erreur}") from None
    return ajouter_document_octets(conn, session, matricule, type_doc, contenu, re.split(r"[\\/]", str(chemin))[-1])


def ajouter_document_octets(conn, session, matricule, type_doc, contenu: bytes, nom_fichier) -> int:
    """Joint un document déjà lu en mémoire (version web : fichier reçu du navigateur). Mêmes contrôles que ci-dessus."""
    exiger(conn, session, "AJOUT")
    agent = _ligne(conn, matricule)
    type_doc = _texte(type_doc)
    if not type_doc:
        raise ErreurPersonnel("Choisissez le type du document.")
    if not contenu:
        raise ErreurPersonnel("Le fichier est vide.")
    if len(contenu) > TAILLE_MAX_DOCUMENT:
        raise ErreurPersonnel(f"Le fichier dépasse {TAILLE_MAX_DOCUMENT // (1024 * 1024)} Mo : réduisez-le "
                              f"(numérisez en résolution plus basse) avant de le joindre.")
    format_ = _format_du_contenu(contenu)
    if not format_:
        raise ErreurPersonnel("Format non accepté : le document doit être un PDF, une image JPEG ou une image PNG.")
    nom_fichier = re.split(r"[\\/]", str(nom_fichier or "document"))[-1][:120] or "document"
    with conn:
        id_doc = conn.execute(
            "INSERT INTO DOCUMENT_PERSONNEL (MATRICULE, TYPE_DOC, NOM_FICHIER, FORMAT, TAILLE, EMPREINTE, CONTENU, "
            "DATE_AJOUT, AJOUTE_PAR) VALUES (?,?,?,?,?,?,?,?,?)",
            (agent["MATRICULE"], type_doc, nom_fichier, format_, len(contenu), hashlib.sha256(contenu).hexdigest(), contenu,
             iso(maintenant()), session.login)).lastrowid
        journaliser(conn, session.id_user, session.login, "AGENT_DOCUMENT_AJOUTE",
                    f"{agent['MATRICULE']} | {type_doc} | {nom_fichier} | {format_} | {len(contenu)} octets")
    return id_doc


def liste_documents(conn, session, matricule) -> list:
    """Documents joints au dossier (sans leur contenu), du plus récent au plus ancien."""
    exiger(conn, session, "LECTURE")
    return [{"id_doc": l["ID_DOC"], "type_doc": l["TYPE_DOC"], "nom_fichier": l["NOM_FICHIER"], "format": l["FORMAT"],
             "taille": l["TAILLE"], "taille_txt": taille_lisible(l["TAILLE"]), "date_ajout": _formater(l["DATE_AJOUT"][:10]),
             "ajoute_par": l["AJOUTE_PAR"]}
            for l in conn.execute("SELECT ID_DOC, TYPE_DOC, NOM_FICHIER, FORMAT, TAILLE, DATE_AJOUT, AJOUTE_PAR "
                                  "FROM DOCUMENT_PERSONNEL WHERE MATRICULE = ? ORDER BY ID_DOC DESC", (matricule,))]


def taille_lisible(octets) -> str:
    if octets < 1024:
        return f"{octets} o"
    if octets < 1024 * 1024:
        return f"{octets / 1024:.0f} Ko"
    return f"{octets / (1024 * 1024):.1f} Mo".replace(".", ",")


def preparer_document(conn, session, id_doc) -> str:
    """Écrit une copie du document dans le dossier du personnel et retourne son chemin (pour l'ouvrir dans le lecteur du
    poste). Les copies de plus d'un jour sont effacées à chaque appel : elles ne doivent pas s'accumuler."""
    exiger(conn, session, "LECTURE")
    l = conn.execute("SELECT * FROM DOCUMENT_PERSONNEL WHERE ID_DOC = ?", (id_doc,)).fetchone()
    if not l:
        raise ErreurPersonnel("Document introuvable.")
    if hashlib.sha256(l["CONTENU"]).hexdigest() != l["EMPREINTE"]:
        raise ErreurPersonnel("Ce document est altéré (son empreinte ne correspond plus) : ne l'utilisez pas, "
                              "signalez-le à l'Administrateur.")
    dossier = config.DOSSIER_PERSONNEL / "ouverts"
    dossier.mkdir(parents=True, exist_ok=True)
    limite = time.time() - 86400
    for ancien in dossier.iterdir():
        try:
            if ancien.is_file() and ancien.stat().st_mtime < limite:
                ancien.unlink()
        except OSError:
            pass
    sur = re.sub(r"[^A-Za-z0-9]+", "-", l["MATRICULE"]).strip("-")
    chemin = dossier / f"{sur}_{l['ID_DOC']}.{FORMATS[l['FORMAT']][0]}"
    chemin.write_bytes(l["CONTENU"])
    with conn:
        journaliser(conn, session.id_user, session.login, "AGENT_DOCUMENT_CONSULTE",
                    f"{l['MATRICULE']} | {l['TYPE_DOC']} | {l['NOM_FICHIER']}")
    return str(chemin)


def lire_document(conn, session, id_doc) -> tuple:
    """Contenu d'un document joint, pour l'envoyer au navigateur : (octets, format 'PDF'|'JPEG'|'PNG', nom du fichier).
    Même contrôle d'empreinte et même ligne de journal que preparer_document, sans écrire de copie sur le disque."""
    exiger(conn, session, "LECTURE")
    l = conn.execute("SELECT * FROM DOCUMENT_PERSONNEL WHERE ID_DOC = ?", (id_doc,)).fetchone()
    if not l:
        raise ErreurPersonnel("Document introuvable.")
    if hashlib.sha256(l["CONTENU"]).hexdigest() != l["EMPREINTE"]:
        raise ErreurPersonnel("Ce document est altéré (son empreinte ne correspond plus) : ne l'utilisez pas, "
                              "signalez-le à l'Administrateur.")
    with conn:
        journaliser(conn, session.id_user, session.login, "AGENT_DOCUMENT_CONSULTE",
                    f"{l['MATRICULE']} | {l['TYPE_DOC']} | {l['NOM_FICHIER']}")
    return bytes(l["CONTENU"]), l["FORMAT"], l["NOM_FICHIER"]


def matricule_du_document(conn, id_doc):
    """Matricule de l'agent propriétaire du document (ou None) : pour revenir à son dossier après une action."""
    l = conn.execute("SELECT MATRICULE FROM DOCUMENT_PERSONNEL WHERE ID_DOC = ?", (id_doc,)).fetchone()
    return l[0] if l else None


def supprimer_document(conn, session, id_doc):
    """Retire un document joint (droit « Suppression »). L'opération reste inscrite au journal."""
    exiger(conn, session, "SUPPRESSION")
    l = conn.execute("SELECT MATRICULE, TYPE_DOC, NOM_FICHIER, EMPREINTE FROM DOCUMENT_PERSONNEL WHERE ID_DOC = ?",
                     (id_doc,)).fetchone()
    if not l:
        raise ErreurPersonnel("Document introuvable.")
    with conn:
        conn.execute("DELETE FROM DOCUMENT_PERSONNEL WHERE ID_DOC = ?", (id_doc,))
        journaliser(conn, session.id_user, session.login, "AGENT_DOCUMENT_SUPPRIME",
                    f"{l['MATRICULE']} | {l['TYPE_DOC']} | {l['NOM_FICHIER']} | empreinte {l['EMPREINTE'][:12]}")


# ------------------------------------------------------------------ fiche individuelle
def preparer_fiche_pdf(conn, session, matricule) -> str:
    """Génère la fiche individuelle (PDF A4) de l'agent et retourne son chemin."""
    import personnel_pdf
    agent = charger_agent(conn, session, matricule)                       # vérifie le droit Lecture
    documents = liste_documents(conn, session, matricule)
    config.DOSSIER_PERSONNEL.mkdir(parents=True, exist_ok=True)
    sur = re.sub(r"[^A-Za-z0-9]+", "-", agent["matricule"]).strip("-")
    chemin = str(config.DOSSIER_PERSONNEL / f"Fiche_personnel_{sur}.pdf")
    personnel_pdf.generer_fiche_pdf(agent, documents, chemin, config.DOSSIER_ASSETS / "logo_recu.jpg",
                                    date_impression=maintenant().astimezone().strftime("%d/%m/%Y"))
    with conn:
        journaliser(conn, session.id_user, session.login, "AGENT_FICHE_IMPRIMEE", agent["matricule"])
    return chemin

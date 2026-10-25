"""Module « Contrôle numérique ».

1. Édition de la liste des élèves EN ORDRE : on choisit l'année scolaire, la classe (et
   l'option pour les humanités) et le type de frais. Un élève est « en ordre » quand il est inscrit dans cette classe
   pour cette année, que son compte élève est actif, qu'un tarif existe pour ce frais dans sa classe et que le total de
   ses reçus VALIDES pour ce frais couvre le tarif (les reçus annulés ne comptent pas).
2. Contrôle numérique d'un élève : on saisit son nom ou son matricule ; le système affiche ses informations et son
   statut « EN ORDRE » ou « IMPAYÉ ».
   Règle : IMPAYÉ dès qu'il reste un montant à payer sur un frais de l'année en cours ou d'une année précédente ;
   EN ORDRE sinon. Un élève non inscrit pour l'année en cours et sans dette est signalé « NON INSCRIT ».

Droit : tout compte qui a la Lecture sur le module (l'Administrateur y a accès) ; chaque opération est inscrite au journal.
"""
from datetime import datetime

import argent
import config
import donnees
import droits
import identite
import sections
from database import journaliser

MODULE = "controle"

EN_ORDRE, IMPAYE, NON_INSCRIT = "EN ORDRE", "IMPAYÉ", "NON INSCRIT"
NON_APPLICABLE = "FRAIS NON DÛ"      # contrôle mobile d'un seul frais : ce frais n'existe pas pour la classe de l'élève
TOUS_LES_FRAIS = "TOUS"


class ErreurControle(Exception):
    """Erreur métier dont le message peut être affiché tel quel à l'utilisateur."""


# ------------------------------------------------------------------ droits
def peut(conn, session, droit="LECTURE") -> bool:
    return droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, droit)


def exiger(conn, session):
    if not peut(conn, session):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS['LECTURE']} » "
                              f"sur le module « {config.MODULES_DROITS[MODULE][0]} ».")


# ------------------------------------------------------------------ listes de choix (en cascade)
def liste_annees(conn) -> list:
    """Années scolaires actives, la plus récente d'abord."""
    return [l[0] for l in conn.execute("SELECT ANNEESCO FROM ANNEE_SCO WHERE ACTIF = 1 ORDER BY ANNEESCO DESC")]


def liste_classes(conn, session=None) -> list:
    """Désignations des classes actives (sans doublon : une même classe peut exister avec plusieurs options) ; avec `session` :
    seulement celles des sections ouvertes à ce compte."""
    fs, ps = sections.filtre_classes(conn, session, "N_CLASSE") if session is not None else ("", ())
    return [l[0] for l in conn.execute(
        "SELECT DISTINCT DESI_CLASSE FROM CLASSE WHERE ACTIF = 1 " + (f"AND {fs} " if fs else "") + "ORDER BY DESI_CLASSE COLLATE NOCASE", ps)]


def liste_options(conn, desi_classe) -> list:
    """[(code, désignation)] des options de cette classe (vide : classe sans option, pas encore en humanités)."""
    return [(l[0], l[1]) for l in conn.execute(
        "SELECT DISTINCT O.CODE_OPTION, O.DESI_OPTION FROM CLASSE C JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
        "WHERE C.ACTIF = 1 AND C.DESI_CLASSE = ? ORDER BY O.DESI_OPTION COLLATE NOCASE", (desi_classe,))]


def liste_types_frais(conn) -> list:
    """[(code, désignation)] des types de frais actifs."""
    return [(l[0], l[1]) for l in conn.execute(
        "SELECT CODTF, DESITF FROM TYPE_FRAIS WHERE ACTIF = 1 ORDER BY DESITF COLLATE NOCASE, CODTF")]


def _numeros_classes(conn, desi_classe, code_option) -> list:
    if code_option:
        lignes = conn.execute("SELECT N_CLASSE FROM CLASSE WHERE DESI_CLASSE = ? AND CODE_OPTION = ?",
                              (desi_classe, code_option))
    else:
        lignes = conn.execute("SELECT N_CLASSE FROM CLASSE WHERE DESI_CLASSE = ?", (desi_classe,))
    return [l[0] for l in lignes]


# ------------------------------------------------------------------ 1) liste des élèves en ordre
def eleves_en_ordre(conn, session, annee, desi_classe, code_option, codtf) -> dict:
    """Retourne le dictionnaire de la liste (titre, lignes numérotées, informations d'en-tête)."""
    exiger(conn, session)
    if not annee:
        raise ErreurControle("Choisissez l'année scolaire.")
    if not desi_classe:
        raise ErreurControle("Choisissez la classe.")
    if not codtf:
        raise ErreurControle("Choisissez le type de frais.")
    if liste_options(conn, desi_classe) and not code_option:
        raise ErreurControle("Cette classe a des options : choisissez l'option.")

    frais = conn.execute("SELECT DESITF FROM TYPE_FRAIS WHERE CODTF = ?", (codtf,)).fetchone()
    if not frais:
        raise ErreurControle("Type de frais introuvable.")
    option = conn.execute("SELECT DESI_OPTION FROM OPTION_SCO WHERE CODE_OPTION = ?", (code_option,)).fetchone() \
        if code_option else None
    classes = [n for n in _numeros_classes(conn, desi_classe, code_option) if sections.peut_classe(conn, session, n)]
    if not classes:
        raise ErreurControle("Classe introuvable.")

    marques = ",".join("?" * len(classes))
    inscrits = conn.execute(
        f"SELECT E.MATRICULE, E.NOM, E.POSTNOM, E.PRENOM, E.SEXE, I.N_CLASSE, "
        f"  COALESCE((SELECT T.MONTANT FROM TARIF T WHERE T.CODTF = ? AND T.N_CLASSE = I.N_CLASSE AND T.ANNEESCO = I.ANNEESCO), "
        f"           (SELECT F.MONTANT FROM TYPE_FRAIS F WHERE F.CODTF = ?)) AS DU, "
        f"  COALESCE((SELECT SUM(P.MONT_PAYE) FROM PAIEMENT P WHERE P.ANNEESCO = I.ANNEESCO AND P.MATRICULE = I.MATRICULE "
        f"            AND P.CODTF = ? AND P.STATUT = 'VALIDE'), 0) AS PAYE "
        f"FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE "
        f"WHERE I.ANNEESCO = ? AND I.N_CLASSE IN ({marques}) AND E.ACTIF = 1 "
        f"ORDER BY E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE, E.MATRICULE",
        (codtf, codtf, codtf, annee, *classes)).fetchall()

    en_ordre = [l for l in inscrits if l["DU"] is not None and l["PAYE"] >= l["DU"]]
    sans_tarif = bool(inscrits) and all(l["DU"] is None for l in inscrits)
    lignes = [{"n": i, "matricule": l["MATRICULE"], "nom_complet": donnees.nom_complet(l), "sexe": l["SEXE"] or ""}
              for i, l in enumerate(en_ordre, start=1)]
    classe_txt = desi_classe
    return {
        "titre": f"LISTE DES ELEVES EN ORDRE AVEC LE FRAIS {frais['DESITF'].upper()}",
        "type_frais": frais["DESITF"], "classe": classe_txt, "option": option["DESI_OPTION"] if option else "",
        "annee": annee, "codtf": codtf,
        "lignes": lignes, "nb_inscrits": len(inscrits), "sans_tarif": sans_tarif,
        "edite_le": datetime.now().strftime("%d/%m/%Y à %H:%M"),
    }


def ligne_classe_option(liste) -> str:
    """'CLASSE : 3ème Scientifique   -   OPTION : Scientifique' (sans option : seulement la classe)."""
    texte = f"CLASSE : {liste['classe']}"
    if liste["option"]:
        texte += f"   -   OPTION : {liste['option']}"
    return texte


def journaliser_liste(conn, session, liste, action):
    with conn:
        journaliser(conn, session.id_user, session.login, action,
                    f"{liste['annee']} | {liste['codtf']} | {liste['classe']} | {liste['option'] or '-'} | "
                    f"{len(liste['lignes'])} élève(s) en ordre sur {liste['nb_inscrits']}")


def preparer_liste_pdf(conn, session, liste) -> str:
    """Génère le PDF de la liste et retourne son chemin."""
    import controle_pdf
    exiger(conn, session)
    if not liste["lignes"]:
        raise ErreurControle("Aucun élève en ordre : rien à imprimer.")
    config.DOSSIER_RECUS.mkdir(parents=True, exist_ok=True)
    nom = "".join(c if c.isalnum() else "_" for c in f"{liste['annee']}_{liste['codtf']}_{liste['classe']}_{liste['option']}")
    chemin = str(config.DOSSIER_RECUS / f"Liste_en_ordre_{nom}.pdf")
    controle_pdf.generer_liste_pdf(liste, chemin, config.DOSSIER_ASSETS / "logo_recu.jpg")
    journaliser_liste(conn, session, liste, "LISTE_EN_ORDRE_IMPRIMEE")
    return chemin


# ------------------------------------------------------------------ 2) contrôle d'un élève
def _construire(conn, session, matricule):
    """Calcule le contrôle d'un élève sans rien écrire au journal. Retourne (résultat, lignes de situation, inscription)."""
    exiger(conn, session)
    eleve = donnees.get_eleve(conn, matricule)
    if not eleve:
        raise ErreurControle("Élève introuvable.")
    sections.exiger_eleve(conn, session, matricule)
    if not eleve["ACTIF"] and conn.execute("SELECT 1 FROM RENVOI WHERE MATRICULE_ARCHIVE = ?", (eleve["MATRICULE"],)).fetchone():
        raise ErreurControle("Élève renvoyé : cette carte n'est plus valable.")
    annee = donnees.annee_courante(conn)
    insc = next((i for i in donnees.inscriptions(conn, matricule) if i["ANNEESCO"] == annee), None)
    lignes = donnees.situation(conn, matricule, annee, insc["N_CLASSE"]) if insc else []
    dettes = donnees.dettes(conn, matricule)
    if dettes:
        statut = IMPAYE
    elif not insc:
        statut = NON_INSCRIT
    else:
        statut = EN_ORDRE
    resultat = {
        "matricule": eleve["MATRICULE"], "nom_complet": donnees.nom_complet(eleve),
        "sexe": {"M": "Masculin", "F": "Féminin"}.get(eleve["SEXE"], "—"),
        "actif": bool(eleve["ACTIF"]), "annee": annee,
        "classe": insc["DESI_CLASSE"] if insc else "", "option": (insc["DESI_OPTION"] or "") if insc else "",
        "inscrit": bool(insc), "statut": statut,
        "lignes": [{"frais": l.designation, "du": f"{argent.formater(l.du)} {l.devise}",
                    "paye": f"{argent.formater(l.paye)} {l.devise}", "reste": f"{argent.formater(l.reste)} {l.devise}",
                    "statut": l.statut, "reste_positif": l.reste > 0} for l in lignes],
        "sans_frais": bool(insc) and not lignes,
        "dettes": [f"année {a} : {argent.formater(r)} {d}" for a, d, r in dettes],
    }
    return resultat, lignes, insc


def controler_eleve(conn, session, matricule) -> dict:
    """Informations de l'élève (année en cours) et statut EN ORDRE / IMPAYÉ."""
    resultat, _lignes, _insc = _construire(conn, session, matricule)
    with conn:
        journaliser(conn, session.id_user, session.login, "CONTROLE_NUMERIQUE", f"{matricule} | {resultat['statut']}")
    return resultat


# ------------------------------------------------------------------ 3) application mobile de contrôle
# Le contrôleur se connecte (identifiant + mot de passe) depuis son téléphone, choisit un type de frais (ou tous), puis
# contrôle chaque élève en scannant le QR de sa carte ou en tapant son matricule. L'application mobile n'existe que si
# l'autorité académique autorisée l'a activée ; elle peut la couper à tout moment (effet immédiat sur les téléphones connectés).
class ErreurMobileCoupee(ErreurControle):
    """L'application mobile de contrôle n'est pas activée."""


MESSAGE_MOBILE_COUPEE = "L'application mobile de contrôle n'est pas activée. Adressez-vous à l'autorité académique."


def mobile_etat(conn) -> dict:
    """{'actif': bool, 'par': login ou '', 'le': texte ou ''}"""
    l = conn.execute("SELECT ACTIF, MODIFIE_PAR, MODIFIE_LE FROM CONTROLE_MOBILE WHERE ID = 1").fetchone()
    if not l:
        return {"actif": False, "par": "", "le": ""}
    return {"actif": bool(l["ACTIF"]), "par": l["MODIFIE_PAR"] or "", "le": l["MODIFIE_LE"] or ""}


def mobile_actif(conn) -> bool:
    return mobile_etat(conn)["actif"]


def peut_gerer_mobile(conn, session) -> bool:
    """Autorité académique autorisée : l'Administrateur, ou le compte à qui il a accordé la Modification sur ce module."""
    return peut(conn, session, "MODIFICATION")


def definir_mobile(conn, session, actif: bool) -> dict:
    """Active ou coupe l'application mobile de contrôle (inscrit au journal)."""
    if not peut_gerer_mobile(conn, session):
        raise PermissionError("Accès refusé : seule l'autorité académique autorisée (droit « Modification » sur le module "
                              "« Contrôle numérique ») active ou coupe l'application mobile de contrôle.")
    with conn:
        conn.execute("INSERT INTO CONTROLE_MOBILE (ID, ACTIF, MODIFIE_PAR, MODIFIE_LE) VALUES (1, ?, ?, ?) "
                     "ON CONFLICT(ID) DO UPDATE SET ACTIF = excluded.ACTIF, MODIFIE_PAR = excluded.MODIFIE_PAR, "
                     "MODIFIE_LE = excluded.MODIFIE_LE",
                     (1 if actif else 0, session.login, datetime.now().strftime("%d/%m/%Y à %H:%M")))
        journaliser(conn, session.id_user, session.login, "CONTROLE_MOBILE_ACTIVE" if actif else "CONTROLE_MOBILE_COUPE", "")
    return mobile_etat(conn)


def exiger_mobile(conn, session):
    """Droit de contrôle (Lecture) ET application activée : vérifié à chaque requête du téléphone."""
    exiger(conn, session)
    if not mobile_actif(conn):
        raise ErreurMobileCoupee(MESSAGE_MOBILE_COUPEE)


def frais_pour_mobile(conn, session) -> list:
    """[(code, désignation)] proposés au contrôleur avant de commencer."""
    exiger_mobile(conn, session)
    return liste_types_frais(conn)


def retrouver_eleve(conn, code) -> tuple:
    """Texte scanné (QR de la carte) ou matricule tapé -> (matricule, 'QR' ou 'MATRICULE').
    Un QR n'est accepté que s'il a été délivré par le logiciel (son code complet est cherché, pas seulement le matricule)."""
    texte = " ".join(str(code or "").split())
    if not texte:
        raise ErreurControle("Scannez la carte ou saisissez le matricule de l'élève.")
    if len(texte) > 80:
        raise ErreurControle("Code illisible : scannez de nouveau la carte ou saisissez le matricule.")
    if texte.startswith(identite.PREFIXE_QR + "|"):
        l = conn.execute("SELECT MATRICULE FROM ELEVE WHERE CODE_QR = ?", (texte,)).fetchone()
        if not l:
            raise ErreurControle("Carte non reconnue : ce code QR n'a pas été délivré par l'école.")
        return l["MATRICULE"], "QR"
    candidats = [texte, texte.upper(), texte.replace("-", "/"), texte.upper().replace("-", "/")]
    for c in dict.fromkeys(candidats):
        l = conn.execute("SELECT MATRICULE FROM ELEVE WHERE MATRICULE = ?", (c,)).fetchone()
        if l:
            return l["MATRICULE"], "MATRICULE"
    raise ErreurControle("Matricule introuvable.")


def photo_pour_controle(conn, session, matricule):
    """JPEG de l'élève pour que le contrôleur compare avec la personne présente, ou None (pas de photo, ou section primaire)."""
    exiger(conn, session)
    sections.exiger_eleve(conn, session, matricule)
    l = conn.execute("SELECT PHOTO FROM PHOTO_ELEVE WHERE MATRICULE = ?", (matricule,)).fetchone()
    return bytes(l["PHOTO"]) if l else None


def controler_mobile(conn, session, code, codtf) -> dict:
    """Contrôle d'un élève depuis l'application mobile. `codtf` : un type de frais, ou TOUS_LES_FRAIS.
    - TOUS_LES_FRAIS : mêmes règles que le contrôle web (IMPAYÉ dès qu'il reste un montant dû, cette année ou avant) ;
    - un frais : EN ORDRE si ce frais est soldé pour l'année en cours, IMPAYÉ sinon ; FRAIS NON DÛ si ce frais n'existe pas
      pour la classe de l'élève (jamais « en ordre » par défaut, comme dans la liste des élèves en ordre)."""
    exiger_mobile(conn, session)
    codtf = (codtf or TOUS_LES_FRAIS).strip()
    choisi = None
    if codtf != TOUS_LES_FRAIS:
        choisi = next((t for t in liste_types_frais(conn) if t[0] == codtf), None)
        if not choisi:
            raise ErreurControle("Type de frais introuvable : choisissez-le de nouveau.")
    matricule, mode = retrouver_eleve(conn, code)
    resultat, lignes, insc = _construire(conn, session, matricule)
    if choisi:
        ligne = next((l for l in lignes if l.codtf == codtf), None)
        if not insc:
            statut = NON_INSCRIT
        elif ligne is None:
            statut = NON_APPLICABLE
        else:
            statut = EN_ORDRE if ligne.reste == 0 else IMPAYE
        resultat["statut"] = statut
        resultat["lignes"] = [l for l, o in zip(resultat["lignes"], lignes) if o.codtf == codtf]
        resultat["dettes"] = []
        resultat["sans_frais"] = False
    resultat["frais_choisi"] = choisi[1] if choisi else "Tous les frais"
    resultat["identification"] = mode
    with conn:
        journaliser(conn, session.id_user, session.login, "CONTROLE_MOBILE",
                    f"{matricule} | {codtf} | {resultat['statut']} | {mode}")
    return resultat

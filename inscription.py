"""Module « Inscription » : formulaire d'inscription d'un candidat et liste d'attente.

Parcours :
  1. le candidat paie à la caisse (module Paiement des frais) un type de frais marqué « Frais d'inscription »
     (Travaux techniques > Mise à jour des tables > Types de frais) ; un reçu lui est remis ;
  2. il va chez l'utilisateur concerné (le secrétaire) qui remplit le FORMULAIRE D'INSCRIPTION (première fonctionnalité) :
     identité, ancienne école et pourcentage, doublant ou non, tuteur (nom, téléphone, adresse), classe souhaitée,
     et le numéro du reçu ;
  3. il enregistre et imprime la fiche : le candidat est mis sur la LISTE D'ATTENTE (par ordre d'arrivée, classe par classe).

Le paiement n'est jamais enregistré ici. Le système REFUSE toute candidature dont le reçu n'existe pas, est annulé,
n'est pas de type « frais d'inscription », ou a déjà servi pour un autre candidat (contrôle de l'application, doublé par un
déclencheur de la base : voir CANDIDATURE_EXIGE_PAIEMENT dans database.py).

  4. VALIDATION ET AFFECTATION (deuxième fonctionnalité) : le candidat passe le test d'admission ; on enregistre sa note.
     Note >= seuil (config.SEUIL_REUSSITE_TEST) : le dossier est VALIDÉ ; sinon la candidature est REFUSÉE.
     Un dossier validé est AFFECTÉ à une classe : le candidat devient ÉLÈVE (statut ADMIS), le système lui attribue
     son matricule (même modèle que partout : 0001/26) et son code QR, et l'inscrit dans la classe pour l'année.

Droits (module « inscription », Gestionnaire d'accès ; l'Administrateur les a tous) :
  - Lecture       : ouvrir le module, consulter la liste d'attente, réimprimer une fiche ;
  - Ajout         : remplir le formulaire et enregistrer une candidature ;
  - Modification  : enregistrer le résultat du test, valider et affecter (le candidat devient élève).
Chaque opération est contrôlée dans la base au moment de l'action et inscrite au journal.
"""
import re
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation

import argent
import config
import donnees
import droits
import identite
import sections
from database import iso, journaliser, lire_iso, maintenant
from paiements import lire_date
from paiements import ErreurPaiement

MODULE = "inscription"
STATUTS = {"EN_ATTENTE": "En attente", "ADMIS": "Admis", "REFUSE": "Refusé", "RETIRE": "Retiré"}
ETAPES = {"A_TESTER": "Test à passer", "A_AFFECTER": "Réussi - à affecter", "ADMIS": "Admis (élève)",
          "REFUSE": "Refusé (test échoué)", "RETIRE": "Retiré"}
AGE_MIN, AGE_MAX = 3, 30                       # bornes de plausibilité de la date de naissance (en années)


class ErreurInscription(Exception):
    """Erreur métier dont le message peut être affiché tel quel à l'utilisateur."""


# ------------------------------------------------------------------ droits
def peut(conn, session, droit) -> bool:
    return droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, droit)


def exiger(conn, session, droit):
    if not peut(conn, session, droit):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS.get(droit, droit)} » "
                              f"sur le module « {config.MODULES_DROITS[MODULE][0]} ».")


# ------------------------------------------------------------------ listes de choix
def classes_proposees(conn, session=None) -> list:
    """[(n_classe, libellé)] des classes actives, pour la liste « classe souhaitée » (avec `session` : seulement celles des sections
    ouvertes à ce compte)."""
    fs, ps = sections.filtre_classes(conn, session, "C.N_CLASSE") if session is not None else ("", ())
    return [(l["N_CLASSE"], l["LIBELLE"]) for l in conn.execute(
        "SELECT C.N_CLASSE, C.DESI_CLASSE || ' (' || C.CODE_NIVEAU || COALESCE(' / ' || C.CODE_OPTION, '') || ')' AS LIBELLE "
        "FROM CLASSE C WHERE C.ACTIF = 1 " + (f"AND {fs} " if fs else "") + "ORDER BY C.CODE_NIVEAU, C.DESI_CLASSE", ps)]


def annees_proposees(conn) -> list:
    return [l[0] for l in conn.execute("SELECT ANNEESCO FROM ANNEE_SCO ORDER BY ANNEESCO DESC")]


def types_frais_inscription(conn) -> list:
    """[(code, désignation)] des types de frais actifs marqués « frais d'inscription »."""
    return [(l["CODTF"], l["DESITF"]) for l in conn.execute(
        "SELECT CODTF, DESITF FROM TYPE_FRAIS WHERE POUR_INSCRIPTION = 1 AND ACTIF = 1 ORDER BY CODTF")]


# ------------------------------------------------------------------ lecture des saisies
def _texte(valeur) -> str:
    return " ".join((valeur or "").split())


def _obligatoire(valeur, nom) -> str:
    texte = _texte(valeur)
    if not texte:
        raise ErreurInscription(f"Renseignez {nom}.")
    return texte


def lire_pourcentage(texte) -> float:
    """'68,5' ou '68.5 %' -> 68.5 ; doit être entre 0 et 100."""
    brut = _texte(texte).replace("%", "").replace(",", ".").strip()
    if not brut:
        raise ErreurInscription("Renseignez le pourcentage obtenu à l'ancienne école.")
    try:
        valeur = Decimal(brut)
    except InvalidOperation:
        raise ErreurInscription("Le pourcentage est invalide : écrivez-le ainsi : 68 ou 68,5.") from None
    if not valeur.is_finite() or valeur < 0 or valeur > 100:
        raise ErreurInscription("Le pourcentage doit être compris entre 0 et 100.")
    return float(valeur)


def lire_date_naissance(texte) -> date:
    try:
        jour = lire_date(texte)
    except ErreurPaiement:
        raise ErreurInscription("Date de naissance invalide. Écrivez-la ainsi : 15/03/2010") from None
    aujourdhui = date.today()
    if jour > aujourdhui:
        raise ErreurInscription("La date de naissance ne peut pas être dans le futur.")
    age = aujourdhui.year - jour.year - ((aujourdhui.month, aujourdhui.day) < (jour.month, jour.day))
    if age < AGE_MIN or age > AGE_MAX:
        raise ErreurInscription(f"La date de naissance donne {age} an(s) : vérifiez-la "
                                f"(un candidat a entre {AGE_MIN} et {AGE_MAX} ans).")
    return jour


def lire_telephone(texte, nom, obligatoire=True) -> str:
    tel = _texte(texte)
    if not tel:
        if obligatoire:
            raise ErreurInscription(f"Renseignez {nom}.")
        return ""
    if not re.fullmatch(r"[0-9+()\-./ ]+", tel) or len(re.sub(r"\D", "", tel)) < 6:
        raise ErreurInscription(f"Le numéro de téléphone {nom} est invalide (chiffres, +, espaces ; 6 chiffres au moins).")
    return tel


def normaliser_recu(texte) -> str:
    """'1' -> '0001' (les reçus sont numérotés 0001, 0002...)."""
    n = _texte(texte)
    if not n:
        raise ErreurInscription("Saisissez le numéro du reçu de paiement des frais d'inscription : "
                                "sans paiement, la candidature ne peut pas être validée.")
    return n.zfill(4) if n.isdigit() else n.upper()


# ------------------------------------------------------------------ vérification du paiement
def verifier_recu(conn, n_recu) -> dict:
    """Le reçu prouve-t-il que le candidat a payé ? Lève ErreurInscription (message affichable) sinon.
    Retourne les informations du reçu (pour l'afficher à l'écran avant l'enregistrement)."""
    n_recu = normaliser_recu(n_recu)
    l = conn.execute(
        "SELECT P.N_RECU, P.ANNEESCO, P.DATE_PAY, P.MONT_PAYE, P.CODE_DEVISE, P.STATUT, F.DESITF, F.POUR_INSCRIPTION "
        "FROM PAIEMENT P JOIN TYPE_FRAIS F ON F.CODTF = P.CODTF WHERE P.N_RECU = ?", (n_recu,)).fetchone()
    if not l:
        raise ErreurInscription(f"Le reçu N° {n_recu} n'existe pas. Vérifiez le numéro écrit sur le reçu remis par le percepteur.")
    if l["STATUT"] != "VALIDE":
        raise ErreurInscription(f"Le reçu N° {n_recu} est annulé : le candidat n'a donc pas payé. "
                                f"Il doit repasser à la caisse.")
    if not l["POUR_INSCRIPTION"]:
        raise ErreurInscription(f"Le reçu N° {n_recu} concerne « {l['DESITF']} », pas les frais d'inscription : "
                                f"il ne peut pas valider une candidature.")
    deja = conn.execute("SELECT NUM_CAND, NOM, POSTNOM, PRENOM FROM CANDIDATURE WHERE N_RECU = ?", (n_recu,)).fetchone()
    if deja:
        raise ErreurInscription(f"Le reçu N° {n_recu} a déjà servi pour la candidature {deja['NUM_CAND']} "
                                f"({donnees.nom_complet(deja)}). Un reçu ne vaut que pour un seul candidat.")
    return {"n_recu": l["N_RECU"], "annee": l["ANNEESCO"], "type_frais": l["DESITF"],
            "date_txt": lire_iso(l["DATE_PAY"]).astimezone().strftime("%d/%m/%Y"),
            "montant_txt": argent.formater(l["MONT_PAYE"]), "devise": l["CODE_DEVISE"]}


def verifier_recu_pour_ecran(conn, session, n_recu) -> dict:
    exiger(conn, session, "LECTURE")
    return verifier_recu(conn, n_recu)


# ------------------------------------------------------------------ enregistrement de la candidature
def enregistrer_candidature(conn, session, saisie: dict) -> dict:
    """Valide le formulaire et met le candidat sur la liste d'attente.
    Retourne {'n_cand', 'num_cand', 'ordre', 'rang', 'annee'} ; `rang` = position dans la liste d'attente de la classe."""
    exiger(conn, session, "AJOUT")

    nom = _obligatoire(saisie.get("nom"), "le nom du candidat").upper()
    postnom = _texte(saisie.get("postnom")).upper() or None
    prenom = _texte(saisie.get("prenom")).title() or None
    sexe = (saisie.get("sexe") or "").strip().upper()
    if sexe not in ("M", "F"):
        raise ErreurInscription("Choisissez le sexe du candidat.")
    naissance = lire_date_naissance(saisie.get("date_naissance"))
    lieu = _texte(saisie.get("lieu_naissance")) or None
    nationalite = _texte(saisie.get("nationalite")) or None
    adresse = _obligatoire(saisie.get("adresse"), "l'adresse du candidat")
    telephone = lire_telephone(saisie.get("telephone"), "du candidat", obligatoire=False) or None

    ecole = _obligatoire(saisie.get("ecole_origine"), "l'ancienne école du candidat")
    pourcent = lire_pourcentage(saisie.get("pourcent_origine"))
    doublant = saisie.get("doublant")
    if doublant is None or doublant == "":
        raise ErreurInscription("Précisez si le candidat est doublant ou non.")
    doublant = 1 if doublant in (True, 1, "1", "OUI", "Oui", "oui") else 0

    n_classe = saisie.get("n_classe")
    if n_classe in (None, ""):
        raise ErreurInscription("Choisissez la classe dans laquelle le candidat veut être inscrit.")

    tuteur = _obligatoire(saisie.get("nom_tuteur"), "le nom du tuteur")
    tel_tuteur = lire_telephone(saisie.get("tel_tuteur"), "du tuteur")
    adresse_tuteur = _obligatoire(saisie.get("adresse_tuteur"), "l'adresse du tuteur")
    n_recu = normaliser_recu(saisie.get("n_recu"))

    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")                  # verrou d'écriture : pas de double numéro d'arrivée
    try:
        classe = conn.execute("SELECT ACTIF, DESI_CLASSE FROM CLASSE WHERE N_CLASSE = ?", (n_classe,)).fetchone()
        if not classe:
            raise ErreurInscription("Cette classe n'existe pas.")
        if not classe["ACTIF"]:
            raise ErreurInscription("Cette classe est désactivée : choisissez-en une autre.")
        sections.exiger_classe(conn, session, n_classe)
        recu = verifier_recu(conn, n_recu)           # le paiement : sans lui, rien n'est enregistré
        annee = recu["annee"]
        ordre = conn.execute("SELECT COALESCE(MAX(ORDRE), 0) + 1 FROM CANDIDATURE WHERE ANNEESCO = ?", (annee,)).fetchone()[0]
        num_cand = f"C{ordre:04d}/{annee[2:4]}"
        curseur = conn.execute(
            "INSERT INTO CANDIDATURE (ANNEESCO, ORDRE, NUM_CAND, N_RECU, NOM, POSTNOM, PRENOM, SEXE, DATE_NAISSANCE, "
            "LIEU_NAISSANCE, NATIONALITE, ADRESSE, TELEPHONE, ECOLE_ORIGINE, POURCENT_ORIGINE, DOUBLANT, N_CLASSE, "
            "NOM_TUTEUR, TEL_TUTEUR, ADRESSE_TUTEUR, STATUT, DATE_ENREG, ENREGISTRE_PAR) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'EN_ATTENTE',?,?)",
            (annee, ordre, num_cand, n_recu, nom, postnom, prenom, sexe, naissance.isoformat(), lieu, nationalite,
             adresse, telephone, ecole, pourcent, doublant, int(n_classe), tuteur, tel_tuteur, adresse_tuteur,
             iso(maintenant()), session.login))
        n_cand = curseur.lastrowid
        rang = conn.execute("SELECT COUNT(*) FROM CANDIDATURE WHERE ANNEESCO = ? AND N_CLASSE = ? AND STATUT = 'EN_ATTENTE' "
                            "AND ORDRE <= ?", (annee, int(n_classe), ordre)).fetchone()[0]
        journaliser(conn, session.id_user, session.login, "CANDIDATURE_ENREGISTREE",
                    f"{num_cand} | reçu {n_recu} | {nom} | classe {classe['DESI_CLASSE']} | {annee}")
        conn.commit()
        return {"n_cand": n_cand, "num_cand": num_cand, "ordre": ordre, "rang": rang, "annee": annee}
    except sqlite3.IntegrityError as erreur:         # filet de sécurité : la base refuse aussi (reçu déjà pris, trigger...)
        conn.rollback()
        if "frais d'inscription" in str(erreur):
            raise ErreurInscription("Candidature refusée : aucun paiement valide des frais d'inscription pour ce reçu.") from None
        if "N_RECU" in str(erreur):
            raise ErreurInscription(f"Le reçu N° {n_recu} a déjà servi pour une autre candidature.") from None
        raise ErreurInscription(f"Enregistrement impossible : {erreur}") from None
    except BaseException:
        conn.rollback()
        raise


# ------------------------------------------------------------------ liste d'attente et fiche
def _etape(l) -> str:
    """Où en est la candidature : test à passer, réussi (à affecter), admis, refusé, retiré."""
    if l["STATUT"] in ("ADMIS", "REFUSE", "RETIRE"):
        return l["STATUT"]
    return "A_AFFECTER" if l["RESULTAT_TEST"] == "REUSSI" else "A_TESTER"


def _ligne_vers_dict(l, rang=None) -> dict:
    return {
        "n_cand": l["N_CAND"], "num_cand": l["NUM_CAND"], "ordre": l["ORDRE"], "rang": rang, "annee": l["ANNEESCO"],
        "n_recu": l["N_RECU"], "nom_complet": donnees.nom_complet(l), "sexe": l["SEXE"],
        "date_naissance": date.fromisoformat(l["DATE_NAISSANCE"]).strftime("%d/%m/%Y"),
        "lieu_naissance": l["LIEU_NAISSANCE"] or "", "nationalite": l["NATIONALITE"] or "", "adresse": l["ADRESSE"],
        "telephone": l["TELEPHONE"] or "", "ecole_origine": l["ECOLE_ORIGINE"],
        "pourcent_origine": f"{l['POURCENT_ORIGINE']:g}".replace(".", ","), "doublant": bool(l["DOUBLANT"]),
        "n_classe": l["N_CLASSE"], "classe": l["DESI_CLASSE"], "nom_tuteur": l["NOM_TUTEUR"],
        "tel_tuteur": l["TEL_TUTEUR"], "adresse_tuteur": l["ADRESSE_TUTEUR"], "statut": l["STATUT"],
        "libelle_statut": STATUTS[l["STATUT"]],
        "date_enreg": lire_iso(l["DATE_ENREG"]).astimezone().strftime("%d/%m/%Y"),
        "enregistre_par": l["ENREGISTRE_PAR"],
        # test d'admission, validation et affectation
        "note_test": None if l["NOTE_TEST"] is None else f"{l['NOTE_TEST']:g}".replace(".", ","),
        "resultat_test": l["RESULTAT_TEST"], "etape": _etape(l), "libelle_etape": ETAPES[_etape(l)],
        "matricule": l["MATRICULE"], "n_classe_affectee": l["N_CLASSE_AFFECTEE"],
        "classe_affectee": l["DESI_AFFECTEE"] or "",
        "date_decision": "" if not l["DATE_DECISION"] else lire_iso(l["DATE_DECISION"]).astimezone().strftime("%d/%m/%Y"),
    }


_SELECT = ("SELECT K.*, C.DESI_CLASSE, CA.DESI_CLASSE AS DESI_AFFECTEE FROM CANDIDATURE K "
           "JOIN CLASSE C ON C.N_CLASSE = K.N_CLASSE LEFT JOIN CLASSE CA ON CA.N_CLASSE = K.N_CLASSE_AFFECTEE ")


def liste_attente(conn, session, annee=None, n_classe=None, statut="EN_ATTENTE", recherche="") -> list:
    """Candidatures de l'année (par défaut : l'année en cours), dans l'ordre d'arrivée. `rang` = position dans la liste
    d'attente de SA classe (calculé sur toutes les candidatures en attente, même si la recherche en masque certaines)."""
    exiger(conn, session, "LECTURE")
    annee = annee or donnees.annee_courante(conn)
    if not annee:
        return []
    toutes = [l for l in conn.execute(_SELECT + "WHERE K.ANNEESCO = ? ORDER BY K.ORDRE", (annee,)).fetchall()
              if sections.peut_classe(conn, session, l["N_CLASSE"])]
    compteurs, resultat = {}, []
    fragments = [donnees.sans_accents(f) for f in _texte(recherche).split()]
    for l in toutes:
        rang = None
        if l["STATUT"] == "EN_ATTENTE":
            compteurs[l["N_CLASSE"]] = compteurs.get(l["N_CLASSE"], 0) + 1
            rang = compteurs[l["N_CLASSE"]]
        if statut and l["STATUT"] != statut:
            continue
        if n_classe and l["N_CLASSE"] != n_classe:
            continue
        if fragments:
            texte = donnees.sans_accents(f"{l['NUM_CAND']} {l['N_RECU']} {l['NOM']} {l['POSTNOM'] or ''} {l['PRENOM'] or ''}")
            if not all(f in texte for f in fragments):
                continue
        resultat.append(_ligne_vers_dict(l, rang))
    return resultat


def charger_candidature(conn, session, n_cand) -> dict:
    exiger(conn, session, "LECTURE")
    l = conn.execute(_SELECT + "WHERE K.N_CAND = ?", (n_cand,)).fetchone()
    if not l:
        raise ErreurInscription("Candidature introuvable.")
    sections.exiger_classe(conn, session, l["N_CLASSE"])
    rang = None
    if l["STATUT"] == "EN_ATTENTE":
        rang = conn.execute("SELECT COUNT(*) FROM CANDIDATURE WHERE ANNEESCO = ? AND N_CLASSE = ? AND STATUT = 'EN_ATTENTE' "
                            "AND ORDRE <= ?", (l["ANNEESCO"], l["N_CLASSE"], l["ORDRE"])).fetchone()[0]
    return _ligne_vers_dict(l, rang)


def preparer_fiche_pdf(conn, session, n_cand) -> str:
    """Génère la fiche d'inscription (PDF A4) du candidat et retourne son chemin."""
    import inscription_pdf
    fiche = charger_candidature(conn, session, n_cand)                  # vérifie le droit Lecture
    config.DOSSIER_RECUS.mkdir(parents=True, exist_ok=True)
    chemin = str(config.DOSSIER_RECUS / f"Fiche_inscription_{fiche['num_cand'].replace('/', '-')}.pdf")
    inscription_pdf.generer_fiche_pdf(fiche, chemin, config.DOSSIER_ASSETS / "logo_recu.jpg",
                                      date_impression=maintenant().astimezone().strftime("%d/%m/%Y"))
    with conn:
        journaliser(conn, session.id_user, session.login, "FICHE_INSCRIPTION_IMPRIMEE", fiche["num_cand"])
    return chemin


# ================================================================== 2ème fonctionnalité : validation et affectation
def lire_note_test(texte) -> float:
    """'72' ou '72,5' -> 72.5 ; la note du test est sur 100."""
    brut = _texte(texte).replace("%", "").replace(",", ".").strip()
    if not brut:
        raise ErreurInscription("Saisissez la note obtenue par le candidat au test (sur 100).")
    try:
        valeur = Decimal(brut)
    except InvalidOperation:
        raise ErreurInscription("La note est invalide : écrivez-la ainsi : 62 ou 62,5 (sur 100).") from None
    if not valeur.is_finite() or valeur < 0 or valeur > 100:
        raise ErreurInscription("La note du test doit être comprise entre 0 et 100.")
    return float(valeur)


def seuil_reussite() -> float:
    return float(config.SEUIL_REUSSITE_TEST)


def liste_validation(conn, session, annee=None, n_classe=None, etape=None, recherche="") -> list:
    """Toutes les candidatures de l'année (ordre d'arrivée) avec leur étape : test à passer, réussi (à affecter), admis,
    refusé. `etape` : None = toutes ; sinon une clé de ETAPES. Droit Lecture."""
    exiger(conn, session, "LECTURE")
    annee = annee or donnees.annee_courante(conn)
    if not annee:
        return []
    fragments = [donnees.sans_accents(f) for f in _texte(recherche).split()]
    resultat = []
    for l in conn.execute(_SELECT + "WHERE K.ANNEESCO = ? ORDER BY K.ORDRE", (annee,)).fetchall():
        if not sections.peut_classe(conn, session, l["N_CLASSE"]):
            continue
        if etape and _etape(l) != etape:
            continue
        if n_classe and l["N_CLASSE"] != n_classe:
            continue
        if fragments:
            texte = donnees.sans_accents(f"{l['NUM_CAND']} {l['N_RECU']} {l['MATRICULE'] or ''} "
                                         f"{l['NOM']} {l['POSTNOM'] or ''} {l['PRENOM'] or ''}")
            if not all(f in texte for f in fragments):
                continue
        resultat.append(_ligne_vers_dict(l))
    return resultat


def _charger_pour_decision(conn, n_cand, session=None):
    l = conn.execute(_SELECT + "WHERE K.N_CAND = ?", (n_cand,)).fetchone()
    if not l:
        raise ErreurInscription("Candidature introuvable.")
    if session is not None:
        sections.exiger_classe(conn, session, l["N_CLASSE"])
    return l


def enregistrer_resultat_test(conn, session, n_cand, note_texte) -> dict:
    """Enregistre la note du test d'admission d'un candidat en attente (une seule fois).
    Note >= seuil : dossier VALIDÉ (le candidat reste à affecter) ; note < seuil : candidature REFUSÉE (définitif).
    Retourne {'num_cand', 'note', 'seuil', 'resultat', 'valide'}."""
    exiger(conn, session, "MODIFICATION")
    note = lire_note_test(note_texte)
    seuil = seuil_reussite()
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        l = _charger_pour_decision(conn, n_cand, session)
        if l["STATUT"] != "EN_ATTENTE":
            raise ErreurInscription(f"La candidature {l['NUM_CAND']} n'est plus en attente "
                                    f"({STATUTS[l['STATUT']].lower()}) : le test ne peut plus être enregistré.")
        if l["RESULTAT_TEST"]:
            raise ErreurInscription(f"Le résultat du test de la candidature {l['NUM_CAND']} est déjà enregistré "
                                    f"({l['NOTE_TEST']:g} / 100).")
        reussi = note >= seuil
        maintenant_iso = iso(maintenant())
        if reussi:
            conn.execute("UPDATE CANDIDATURE SET NOTE_TEST = ?, RESULTAT_TEST = 'REUSSI', DATE_TEST = ?, TEST_PAR = ? "
                         "WHERE N_CAND = ?", (note, maintenant_iso, session.login, n_cand))
        else:
            conn.execute("UPDATE CANDIDATURE SET NOTE_TEST = ?, RESULTAT_TEST = 'ECHOUE', DATE_TEST = ?, TEST_PAR = ?, "
                         "STATUT = 'REFUSE', DATE_DECISION = ?, DECISION_PAR = ? WHERE N_CAND = ?",
                         (note, maintenant_iso, session.login, maintenant_iso, session.login, n_cand))
        journaliser(conn, session.id_user, session.login, "CANDIDATURE_TEST_ENREGISTRE",
                    f"{l['NUM_CAND']} | note {note:g}/100 | seuil {seuil:g} | "
                    + ("REUSSI : dossier validé" if reussi else "ECHOUE : candidature refusée"))
        conn.commit()
        return {"num_cand": l["NUM_CAND"], "note": note, "seuil": seuil,
                "resultat": "REUSSI" if reussi else "ECHOUE", "valide": reussi}
    except BaseException:
        conn.rollback()
        raise


def _meme_identite(conn, l):
    """Un élève déjà enregistré avec le même nom complet et la même date de naissance ? (évite un double matricule)"""
    cle = donnees.sans_accents(f"{l['NOM']} {l['POSTNOM'] or ''} {l['PRENOM'] or ''}")
    for e in conn.execute("SELECT MATRICULE, NOM, POSTNOM, PRENOM FROM ELEVE WHERE DATE_NAISSANCE = ?",
                          (l["DATE_NAISSANCE"],)):
        if donnees.sans_accents(f"{e['NOM']} {e['POSTNOM'] or ''} {e['PRENOM'] or ''}") == cle:
            return e["MATRICULE"]
    return None


def affecter_candidat(conn, session, n_cand, n_classe=None) -> dict:
    """Affecte un candidat dont le dossier est validé (test réussi) à une classe : il devient ÉLÈVE.
    En une seule transaction (tout ou rien) : l'élève est créé avec son matricule (0001/26...) et son code QR, il est
    inscrit dans la classe pour l'année de sa candidature, et la candidature passe à ADMIS.
    `n_classe` : classe d'affectation (par défaut la classe souhaitée). Retourne {'num_cand','matricule','classe','annee','n_classe'}."""
    exiger(conn, session, "MODIFICATION")
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        l = _charger_pour_decision(conn, n_cand, session)
        if l["STATUT"] == "ADMIS":
            raise ErreurInscription(f"La candidature {l['NUM_CAND']} est déjà admise : élève {l['MATRICULE']}.")
        if l["STATUT"] != "EN_ATTENTE":
            raise ErreurInscription(f"La candidature {l['NUM_CAND']} est « {STATUTS[l['STATUT']].lower()} » : "
                                    f"elle ne peut pas être affectée.")
        if l["RESULTAT_TEST"] != "REUSSI":
            raise ErreurInscription("Le dossier n'est pas validé : le candidat doit d'abord réussir le test "
                                    "(enregistrez son résultat).")
        n_classe = int(n_classe or l["N_CLASSE"])
        classe = conn.execute("SELECT ACTIF, DESI_CLASSE FROM CLASSE WHERE N_CLASSE = ?", (n_classe,)).fetchone()
        if not classe:
            raise ErreurInscription("Cette classe n'existe pas.")
        if not classe["ACTIF"]:
            raise ErreurInscription("Cette classe est désactivée : choisissez-en une autre.")
        sections.exiger_classe(conn, session, n_classe)
        annee = conn.execute("SELECT ACTIF FROM ANNEE_SCO WHERE ANNEESCO = ?", (l["ANNEESCO"],)).fetchone()
        if not annee or not annee["ACTIF"]:
            raise ErreurInscription(f"L'année scolaire {l['ANNEESCO']} est désactivée : affectation impossible.")
        paiement = conn.execute("SELECT STATUT FROM PAIEMENT WHERE N_RECU = ?", (l["N_RECU"],)).fetchone()
        if not paiement or paiement["STATUT"] != "VALIDE":
            raise ErreurInscription(f"Le reçu N° {l['N_RECU']} a été annulé depuis l'enregistrement : le paiement des "
                                    f"frais d'inscription n'est plus valable. Le candidat doit repasser à la caisse.")
        doublon = _meme_identite(conn, l)
        if doublon:
            raise ErreurInscription(f"Un élève de même identité existe déjà (matricule {doublon}). Vérifiez qu'il ne "
                                    f"s'agit pas du même enfant avant de créer un second matricule.")

        matricule = identite.nouveau_matricule(conn)                 # 0001/26 : numéro d'ordre / année
        conn.execute(
            "INSERT INTO ELEVE (MATRICULE, NOM, POSTNOM, PRENOM, SEXE, DATE_NAISSANCE, LIEU_NAISSANCE, ADRESSE, TELEPHONE, "
            "NOM_TUTEUR, TEL_TUTEUR, ACTIF, NATIONALITE, CODE_QR) VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
            (matricule, l["NOM"], l["POSTNOM"], l["PRENOM"], l["SEXE"], l["DATE_NAISSANCE"], l["LIEU_NAISSANCE"],
             l["ADRESSE"], l["TELEPHONE"], l["NOM_TUTEUR"], l["TEL_TUTEUR"], l["NATIONALITE"],
             identite.nouveau_code_qr(conn, matricule)))
        conn.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE, DATE_INSCRIPTION, STATUT) VALUES (?,?,?,?,?)",
                     (l["ANNEESCO"], matricule, n_classe, date.today().isoformat(),
                      "REDOUBLANT" if l["DOUBLANT"] else "NOUVEAU"))
        conn.execute("UPDATE CANDIDATURE SET STATUT = 'ADMIS', MATRICULE = ?, N_CLASSE_AFFECTEE = ?, DATE_DECISION = ?, "
                     "DECISION_PAR = ? WHERE N_CAND = ?", (matricule, n_classe, iso(maintenant()), session.login, n_cand))
        souhaitee = "" if n_classe == l["N_CLASSE"] else f" (souhaitée : {l['DESI_CLASSE']})"
        journaliser(conn, session.id_user, session.login, "CANDIDAT_ADMIS_AFFECTE",
                    f"{l['NUM_CAND']} | matricule {matricule} | classe {classe['DESI_CLASSE']}{souhaitee} | {l['ANNEESCO']}")
        conn.commit()
        return {"num_cand": l["NUM_CAND"], "matricule": matricule, "classe": classe["DESI_CLASSE"],
                "annee": l["ANNEESCO"], "n_classe": n_classe}
    except sqlite3.IntegrityError as erreur:
        conn.rollback()
        raise ErreurInscription(f"Affectation impossible : {erreur}") from None
    except BaseException:
        conn.rollback()
        raise


def preparer_avis_admission_pdf(conn, session, n_cand) -> str:
    """Avis d'admission (PDF A4) d'un candidat devenu élève : matricule et classe. Droit Lecture."""
    import inscription_pdf
    fiche = charger_candidature(conn, session, n_cand)
    if fiche["statut"] != "ADMIS":
        raise ErreurInscription("Cette candidature n'est pas admise : il n'y a pas d'avis d'admission à imprimer.")
    config.DOSSIER_RECUS.mkdir(parents=True, exist_ok=True)
    chemin = str(config.DOSSIER_RECUS / f"Avis_admission_{identite.nom_de_fichier(fiche['matricule'])}.pdf")
    inscription_pdf.generer_avis_admission_pdf(fiche, chemin, config.DOSSIER_ASSETS / "logo_recu.jpg",
                                               date_impression=maintenant().astimezone().strftime("%d/%m/%Y"))
    with conn:
        journaliser(conn, session.id_user, session.login, "AVIS_ADMISSION_IMPRIME",
                    f"{fiche['num_cand']} | matricule {fiche['matricule']}")
    return chemin

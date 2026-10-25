"""Module « Gestion du personnel » - troisième fonctionnalité : PRÉSENCE ET ABSENCE (sans interface : testable seul).

Ce que cette fonctionnalité permet :
  - enregistrer, jour par jour, la PRÉSENCE, le RETARD ou l'ABSENCE de chaque agent (« Pointage du jour ») ;
  - enregistrer les PERMISSIONS et les CONGÉS (une période autorisée : ses jours ne sont jamais des absences) ;
  - produire des ÉTATS RÉCAPITULATIFS par période (à l'écran et en PDF), par agent, par fonction ou par service.

Règles :
  - un seul enregistrement par agent et par jour ; le corriger remplace le précédent (le journal garde la trace) ;
  - on ne pointe que les jours de TRAVAIL : lundi à vendredi (config.JOURS_DE_TRAVAIL), sauf les « jours non travaillés »
    (fêtes, vacances) saisis par l'école ; jamais dans le futur, jamais avant l'engagement de l'agent ;
  - RETARD : l'heure d'arrivée est obligatoire ; les minutes de retard se calculent seules par rapport à l'heure d'ouverture
    (config.HEURE_DEBUT_SERVICE). Un agent en retard est présent : il compte dans les présences ;
  - un jour couvert par une permission ou un congé s'affiche « Permission » / « Congé » et ne se pointe pas ;
  - accorder une permission ou un congé sur des jours déjà marqués ABSENT les régularise (l'absence est remplacée) ; sur des
    jours marqués présent ou en retard, c'est refusé ; deux autorisations ne se chevauchent pas ;
  - un jour de travail sans pointage ni autorisation est « Non renseigné » : l'absence n'est jamais devinée ;
  - taux de présence = (présents + retards) / (jours de travail - permissions - congés).
Le champ SOURCE de chaque pointage ('MANUEL' pour l'instant) est prévu pour le futur pointeur biométrique : il enregistrera
ses pointages avec la même fonction `enregistrer_pointage(..., source="BIOMETRIQUE")`.

Droits (module « personnel » ; l'Administrateur les a tous) :
  Lecture : feuille du jour, autorisations, états ; Ajout : pointer, accorder une permission / un congé, ajouter un jour non
  travaillé ; Modification : corriger un pointage, annuler une autorisation ; Suppression : effacer un pointage saisi par erreur,
  retirer un jour non travaillé. Chaque opération est contrôlée au moment de l'action et inscrite au journal.
"""
import re
import sqlite3
from datetime import date, datetime, timedelta

import config
import donnees
from affectations import _date as _lire_date
from database import iso, journaliser, maintenant
from personnel import ErreurPersonnel, _formater, _ligne, _texte, exiger, peut

__all__ = ["peut", "exiger", "ErreurPersonnel"]

STATUTS_POINTAGE = {"PRESENT": "Présent", "RETARD": "En retard", "ABSENT": "Absent"}
STATUTS_JOUR = {**STATUTS_POINTAGE, "PERMISSION": "Permission", "CONGE": "Congé", "NON_RENSEIGNE": "Non renseigné"}
TYPES_AUTORISATION = {"PERMISSION": "Permission", "CONGE": "Congé"}
NATURES = {"PERMISSION": ("Raison familiale", "Raison personnelle", "Raison de santé", "Formation ou mission"),
           "CONGE": ("Congé annuel", "Congé de maladie", "Congé de maternité", "Congé de paternité", "Congé sans solde")}
LONGUEUR_MAX_TEXTE = 200
DUREE_MAX_JOURS = 366


# ================================================================== lecture des saisies
def _jour(texte, nom="date") -> date:
    return _lire_date(texte, nom)


def lire_heure(texte) -> str:
    """« 7:45 », « 07h45 », « 0745 » -> « 07:45 »."""
    t = _texte(texte)
    m = re.fullmatch(r"(\d{1,2})\s*[:hH.]?\s*(\d{2})", t)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ErreurPersonnel("L'heure d'arrivée est invalide. Écrivez-la ainsi : 07:45")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _minutes(heure: str) -> int:
    return int(heure[:2]) * 60 + int(heure[3:])


def minutes_de_retard(heure: str) -> int:
    """Minutes écoulées entre l'heure d'ouverture et l'heure d'arrivée (0 si l'agent est à l'heure)."""
    return max(0, _minutes(heure) - _minutes(config.HEURE_DEBUT_SERVICE))


def _motif(texte) -> str:
    t = _texte(texte)
    if len(t) > LONGUEUR_MAX_TEXTE:
        raise ErreurPersonnel(f"Le motif est trop long ({LONGUEUR_MAX_TEXTE} caractères au plus).")
    return t


# ================================================================== jours de travail
def _fermes(conn, debut: date, fin: date) -> set:
    return {l[0] for l in conn.execute("SELECT DATE_JOUR FROM JOUR_FERME WHERE DATE_JOUR BETWEEN ? AND ?",
                                       (debut.isoformat(), fin.isoformat()))}


def jours_de_travail(conn, debut: date, fin: date) -> list:
    """Jours (date) de travail de l'école entre deux dates incluses."""
    fermes = _fermes(conn, debut, fin)
    jours, j = [], debut
    while j <= fin:
        if j.weekday() in config.JOURS_DE_TRAVAIL and j.isoformat() not in fermes:
            jours.append(j)
        j += timedelta(days=1)
    return jours


def jour_de_travail(conn, jour: date) -> bool:
    return bool(jours_de_travail(conn, jour, jour))


def _raison_non_travail(conn, jour: date) -> str:
    ligne = conn.execute("SELECT LIBELLE FROM JOUR_FERME WHERE DATE_JOUR = ?", (jour.isoformat(),)).fetchone()
    if ligne:
        return f"Jour non travaillé : {ligne['LIBELLE']}"
    if jour.weekday() not in config.JOURS_DE_TRAVAIL:
        return "Jour de repos (week-end)"
    return ""


def liste_jours_fermes(conn, session, annee=None) -> list:
    exiger(conn, session, "LECTURE")
    requete, params = "SELECT DATE_JOUR, LIBELLE FROM JOUR_FERME ", ()
    if annee:
        requete, params = requete + "WHERE DATE_JOUR LIKE ? ", (f"{int(annee):04d}-%",)
    return [{"date": _formater(l["DATE_JOUR"]), "iso": l["DATE_JOUR"], "libelle": l["LIBELLE"]}
            for l in conn.execute(requete + "ORDER BY DATE_JOUR", params)]


def ajouter_jour_ferme(conn, session, jour_texte, libelle):
    exiger(conn, session, "AJOUT")
    jour = _jour(jour_texte, "date du jour non travaillé")
    libelle = _texte(libelle)
    if not libelle:
        raise ErreurPersonnel("Écrivez la raison (exemple : Fête de l'indépendance).")
    if len(libelle) > 80:
        raise ErreurPersonnel("La raison est trop longue (80 caractères au plus).")
    try:
        with conn:
            conn.execute("INSERT INTO JOUR_FERME (DATE_JOUR, LIBELLE) VALUES (?, ?)", (jour.isoformat(), libelle))
            journaliser(conn, session.id_user, session.login, "JOUR_FERME_AJOUT", f"{jour.strftime('%d/%m/%Y')} | {libelle}")
    except sqlite3.IntegrityError:
        raise ErreurPersonnel(f"Le {jour.strftime('%d/%m/%Y')} est déjà dans la liste des jours non travaillés.") from None


def supprimer_jour_ferme(conn, session, jour_texte):
    exiger(conn, session, "SUPPRESSION")
    jour = _jour(jour_texte, "date")
    ligne = conn.execute("SELECT * FROM JOUR_FERME WHERE DATE_JOUR = ?", (jour.isoformat(),)).fetchone()
    if not ligne:
        raise ErreurPersonnel("Ce jour n'est pas dans la liste des jours non travaillés.")
    with conn:
        conn.execute("DELETE FROM JOUR_FERME WHERE DATE_JOUR = ?", (jour.isoformat(),))
        journaliser(conn, session.id_user, session.login, "JOUR_FERME_SUPPRIME",
                    f"{jour.strftime('%d/%m/%Y')} | {ligne['LIBELLE']}")


# ================================================================== autorisations (permissions et congés)
def _autorisation_du_jour(conn, matricule, jour_iso):
    return conn.execute("SELECT * FROM AUTORISATION_ABSENCE WHERE MATRICULE = ? AND STATUT = 'ACCORDE' "
                        "AND DATE_DEBUT <= ? AND DATE_FIN >= ?", (matricule, jour_iso, jour_iso)).fetchone()


def _agent_pour_pointage(conn, matricule, jour: date):
    agent = _ligne(conn, matricule)
    if not agent["ACTIF"]:
        raise ErreurPersonnel(f"{donnees.nom_complet(agent)} : le dossier est désactivé, on ne pointe plus cet agent.")
    if jour.isoformat() < agent["DATE_ENGAGEMENT"]:
        raise ErreurPersonnel(f"{donnees.nom_complet(agent)} : engagé le {_formater(agent['DATE_ENGAGEMENT'])}, "
                              f"on ne peut pas le pointer avant.")
    return agent


# ================================================================== pointage
def _verifier_jour(conn, jour: date):
    if jour > date.today():
        raise ErreurPersonnel("On ne peut pas pointer un jour qui n'est pas encore arrivé.")
    raison = _raison_non_travail(conn, jour)
    if raison:
        raise ErreurPersonnel(f"Le {jour.strftime('%d/%m/%Y')} n'est pas un jour de travail ({raison.lower()}).")


def _pointer(conn, session, matricule, jour: date, statut, heure, motif, source) -> str:
    """Enregistre ou corrige un pointage SANS valider la transaction. Retourne 'ajout' ou 'modification'."""
    if statut not in STATUTS_POINTAGE:
        raise ErreurPersonnel("Choisissez : présent, en retard ou absent.")
    if source not in ("MANUEL", "BIOMETRIQUE"):
        raise ValueError("source inconnue")
    agent = _agent_pour_pointage(conn, matricule, jour)
    nom = donnees.nom_complet(agent)
    j = jour.isoformat()
    autorisation = _autorisation_du_jour(conn, matricule, j)
    if autorisation:
        raise ErreurPersonnel(f"{nom} est en {TYPES_AUTORISATION[autorisation['TYPE']].lower()} du "
                              f"{_formater(autorisation['DATE_DEBUT'])} au {_formater(autorisation['DATE_FIN'])} : "
                              f"on ne le pointe pas ce jour-là.")
    motif = _motif(motif)
    heure_iso, minutes = None, 0
    if statut == "ABSENT":
        pass
    else:
        if statut == "RETARD" and not _texte(heure):
            raise ErreurPersonnel(f"{nom} : écrivez l'heure d'arrivée de l'agent en retard.")
        if _texte(heure):
            heure_iso = lire_heure(heure)
            minutes = minutes_de_retard(heure_iso)
        if statut == "RETARD" and minutes == 0:
            raise ErreurPersonnel(f"{nom} : arrivé à {heure_iso}, avant ou à l'heure d'ouverture ({config.HEURE_DEBUT_SERVICE}) : "
                                  f"il n'est pas en retard.")
        if statut == "PRESENT" and minutes > 0:
            raise ErreurPersonnel(f"{nom} : arrivé à {heure_iso}, après l'heure d'ouverture ({config.HEURE_DEBUT_SERVICE}) : "
                                  f"choisissez « En retard ».")
    existant = conn.execute("SELECT * FROM PRESENCE WHERE MATRICULE = ? AND DATE_JOUR = ?", (matricule, j)).fetchone()
    exiger(conn, session, "MODIFICATION" if existant else "AJOUT")
    maintenant_iso = iso(maintenant())
    detail = (f"{matricule} | {nom} | {jour.strftime('%d/%m/%Y')} | {STATUTS_POINTAGE[statut]}"
              + (f" à {heure_iso} ({minutes} min)" if statut == "RETARD" else "") + (f" | {motif}" if motif else "")
              + ("" if source == "MANUEL" else f" | {source}"))
    if existant:
        conn.execute("UPDATE PRESENCE SET STATUT=?, HEURE_ARRIVEE=?, MINUTES_RETARD=?, MOTIF=?, SOURCE=?, DATE_MODIF=?, MODIFIE_PAR=? "
                     "WHERE ID_PRES=?", (statut, heure_iso, minutes, motif or None, source, maintenant_iso, session.login,
                                          existant["ID_PRES"]))
        journaliser(conn, session.id_user, session.login, "PRESENCE_MODIFIEE",
                    detail + f" | avant : {STATUTS_POINTAGE[existant['STATUT']]}")
        return "modification"
    conn.execute("INSERT INTO PRESENCE (MATRICULE, DATE_JOUR, STATUT, HEURE_ARRIVEE, MINUTES_RETARD, MOTIF, SOURCE, DATE_ENREG, "
                 "ENREGISTRE_PAR) VALUES (?,?,?,?,?,?,?,?,?)",
                 (matricule, j, statut, heure_iso, minutes, motif or None, source, maintenant_iso, session.login))
    journaliser(conn, session.id_user, session.login, "PRESENCE_ENREGISTREE", detail)
    return "ajout"


def enregistrer_pointage(conn, session, matricule, jour_texte, statut, heure="", motif="", source="MANUEL") -> dict:
    """Pointe UN agent pour un jour (nouveau pointage ou correction). Retourne {'operation': 'ajout'|'modification'}."""
    exiger(conn, session, "LECTURE")
    jour = _jour(jour_texte, "date du pointage")
    _verifier_jour(conn, jour)
    try:
        with conn:
            operation = _pointer(conn, session, matricule, jour, statut, heure, motif, source)
    except sqlite3.IntegrityError as erreur:
        raise ErreurPersonnel(f"Enregistrement impossible : {erreur}") from None
    return {"operation": operation}


def pointer_plusieurs(conn, session, matricules, jour_texte, statut, heure="", motif="") -> dict:
    """Même pointage pour plusieurs agents. Un agent refusé (en congé, désactivé...) n'empêche pas les autres.
    Retourne {'faits': n, 'refuses': [(matricule, message)]}."""
    exiger(conn, session, "LECTURE")
    jour = _jour(jour_texte, "date du pointage")
    _verifier_jour(conn, jour)
    faits, refuses = 0, []
    for m in matricules:
        try:
            with conn:
                _pointer(conn, session, m, jour, statut, heure, motif, "MANUEL")
            faits += 1
        except ErreurPersonnel as erreur:
            refuses.append((m, str(erreur)))
        except PermissionError:
            raise
    return {"faits": faits, "refuses": refuses}


def supprimer_pointage(conn, session, matricule, jour_texte):
    """Efface un pointage saisi par erreur : le jour redevient « Non renseigné »."""
    exiger(conn, session, "SUPPRESSION")
    jour = _jour(jour_texte, "date")
    ligne = conn.execute("SELECT * FROM PRESENCE WHERE MATRICULE = ? AND DATE_JOUR = ?", (matricule, jour.isoformat())).fetchone()
    if not ligne:
        raise ErreurPersonnel("Aucun pointage à effacer pour cet agent ce jour-là.")
    agent = _ligne(conn, matricule)
    with conn:
        conn.execute("DELETE FROM PRESENCE WHERE ID_PRES = ?", (ligne["ID_PRES"],))
        journaliser(conn, session.id_user, session.login, "PRESENCE_SUPPRIMEE",
                    f"{matricule} | {donnees.nom_complet(agent)} | {jour.strftime('%d/%m/%Y')} | {STATUTS_POINTAGE[ligne['STATUT']]}")


# ================================================================== feuille du jour
def _matricules_de_la_fonction(conn, id_fonction, j: str) -> set:
    return {l[0] for l in conn.execute("SELECT MATRICULE FROM AFFECTATION WHERE ID_FONCTION = ? AND DATE_DEBUT <= ? "
                                       "AND (DATE_FIN IS NULL OR DATE_FIN >= ?)", (int(id_fonction), j, j))}


def feuille_du_jour(conn, session, jour_texte="", id_fonction=None) -> dict:
    """Situation de chaque agent un jour donné (aujourd'hui si vide).
    Retourne {'jour', 'jour_iso', 'travaille', 'raison', 'lignes': [...], 'resume': {statut: nombre}}.
    Chaque ligne : matricule, nom_complet, fonction, statut (STATUTS_JOUR), libelle, heure, minutes, motif, source, verrouille
    (vrai pour une permission / un congé : on ne le pointe pas)."""
    exiger(conn, session, "LECTURE")
    jour = _jour(jour_texte, "date") if _texte(jour_texte) else date.today()
    j = jour.isoformat()
    raison = _raison_non_travail(conn, jour)
    admis = _matricules_de_la_fonction(conn, id_fonction, j) if id_fonction not in (None, "") else None
    pointages = {l["MATRICULE"]: l for l in conn.execute("SELECT * FROM PRESENCE WHERE DATE_JOUR = ?", (j,))}
    lignes = []
    for a in conn.execute("SELECT * FROM PERSONNEL WHERE DATE_ENGAGEMENT <= ? ORDER BY NOM COLLATE NOCASE, POSTNOM, PRENOM", (j,)):
        if admis is not None and a["MATRICULE"] not in admis:
            continue
        p = pointages.get(a["MATRICULE"])
        if not a["ACTIF"] and p is None:
            continue                                         # agent désactivé : seulement s'il a un pointage ce jour-là
        aut = None if p else _autorisation_du_jour(conn, a["MATRICULE"], j)
        if p:
            statut, verrou = p["STATUT"], False
        elif aut:
            statut, verrou = aut["TYPE"], True
        else:
            statut, verrou = "NON_RENSEIGNE", False
        lignes.append({"matricule": a["MATRICULE"], "nom_complet": donnees.nom_complet(a), "fonction": a["FONCTION"] or "",
                       "statut": statut, "libelle": STATUTS_JOUR[statut], "heure": (p["HEURE_ARRIVEE"] or "") if p else "",
                       "minutes": p["MINUTES_RETARD"] if p else 0,
                       "motif": (p["MOTIF"] or "") if p else (aut["NATURE"] or "") if aut else "",
                       "source": p["SOURCE"] if p else "", "verrouille": verrou, "actif": bool(a["ACTIF"])})
    resume = {s: 0 for s in STATUTS_JOUR}
    for l in lignes:
        resume[l["statut"]] += 1
    return {"jour": jour.strftime("%d/%m/%Y"), "jour_iso": j, "travaille": not raison, "raison": raison, "lignes": lignes,
            "resume": resume}


def marquer_presents(conn, session, jour_texte, id_fonction=None) -> dict:
    """Marque « Présent » tous les agents encore « Non renseigné » ce jour-là (raccourci du pointage du matin)."""
    feuille = feuille_du_jour(conn, session, jour_texte, id_fonction)
    cibles = [l["matricule"] for l in feuille["lignes"] if l["statut"] == "NON_RENSEIGNE" and l["actif"]]
    if not cibles:
        return {"faits": 0, "refuses": []}
    return pointer_plusieurs(conn, session, cibles, jour_texte, "PRESENT")


# ================================================================== permissions et congés
def accorder_autorisation(conn, session, matricule, type_, nature, debut_texte, fin_texte, motif="") -> dict:
    """Enregistre une permission ou un congé du `debut` au `fin` (inclus). Retourne {'id', 'jours', 'regularisees'} :
    `regularisees` = nombre d'absences déjà marquées sur cette période et remplacées par l'autorisation."""
    exiger(conn, session, "AJOUT")
    if type_ not in TYPES_AUTORISATION:
        raise ErreurPersonnel("Choisissez : permission ou congé.")
    debut, fin = _jour(debut_texte, "date de début"), _jour(fin_texte, "date de fin")
    if fin < debut:
        raise ErreurPersonnel("La date de fin est avant la date de début.")
    if (fin - debut).days + 1 > DUREE_MAX_JOURS:
        raise ErreurPersonnel(f"La période ne peut pas dépasser {DUREE_MAX_JOURS} jours.")
    nature, motif = _texte(nature) or TYPES_AUTORISATION[type_], _motif(motif)
    if len(nature) > 60:
        raise ErreurPersonnel("La nature est trop longue (60 caractères au plus).")
    agent = _ligne(conn, matricule)
    nom = donnees.nom_complet(agent)
    if not agent["ACTIF"]:
        raise ErreurPersonnel("Le dossier de cet agent est désactivé.")
    if debut.isoformat() < agent["DATE_ENGAGEMENT"]:
        raise ErreurPersonnel(f"{nom} est engagé le {_formater(agent['DATE_ENGAGEMENT'])} : la période ne peut pas commencer avant.")
    if not jours_de_travail(conn, debut, fin):
        raise ErreurPersonnel("Cette période ne contient aucun jour de travail.")
    d, f = debut.isoformat(), fin.isoformat()
    chevauche = conn.execute("SELECT * FROM AUTORISATION_ABSENCE WHERE MATRICULE = ? AND STATUT = 'ACCORDE' "
                             "AND DATE_DEBUT <= ? AND DATE_FIN >= ?", (matricule, f, d)).fetchone()
    if chevauche:
        raise ErreurPersonnel(f"{nom} a déjà une autorisation du {_formater(chevauche['DATE_DEBUT'])} au "
                              f"{_formater(chevauche['DATE_FIN'])} qui touche cette période. Annulez-la d'abord si besoin.")
    present = conn.execute("SELECT DATE_JOUR, STATUT FROM PRESENCE WHERE MATRICULE = ? AND DATE_JOUR BETWEEN ? AND ? "
                           "AND STATUT <> 'ABSENT' ORDER BY DATE_JOUR LIMIT 1", (matricule, d, f)).fetchone()
    if present:
        raise ErreurPersonnel(f"{nom} est marqué « {STATUTS_POINTAGE[present['STATUT']].lower()} » le "
                              f"{_formater(present['DATE_JOUR'])} : corrigez ou effacez d'abord ce pointage.")
    n_jours = len(jours_de_travail(conn, debut, fin))
    try:
        with conn:
            regularisees = conn.execute("DELETE FROM PRESENCE WHERE MATRICULE = ? AND DATE_JOUR BETWEEN ? AND ? "
                                        "AND STATUT = 'ABSENT'", (matricule, d, f)).rowcount
            cur = conn.execute("INSERT INTO AUTORISATION_ABSENCE (MATRICULE, TYPE, NATURE, DATE_DEBUT, DATE_FIN, MOTIF, DATE_ENREG, "
                               "ENREGISTRE_PAR) VALUES (?,?,?,?,?,?,?,?)",
                               (matricule, type_, nature, d, f, motif or None, iso(maintenant()), session.login))
            journaliser(conn, session.id_user, session.login, "AUTORISATION_ENREGISTREE",
                        f"{matricule} | {nom} | {TYPES_AUTORISATION[type_]} ({nature}) | du {debut.strftime('%d/%m/%Y')} au "
                        f"{fin.strftime('%d/%m/%Y')} | {n_jours} jour(s) de travail"
                        + (f" | {regularisees} absence(s) régularisée(s)" if regularisees else "") + (f" | {motif}" if motif else ""))
    except sqlite3.IntegrityError as erreur:
        raise ErreurPersonnel(f"Enregistrement impossible : {erreur}") from None
    return {"id": cur.lastrowid, "jours": n_jours, "regularisees": regularisees}


def annuler_autorisation(conn, session, id_aut, motif):
    """Annule une permission ou un congé (le motif est obligatoire). Ses jours redeviennent « Non renseigné »."""
    exiger(conn, session, "MODIFICATION")
    motif = _motif(motif)
    if not motif:
        raise ErreurPersonnel("Écrivez le motif de l'annulation.")
    ligne = conn.execute("SELECT * FROM AUTORISATION_ABSENCE WHERE ID_AUT = ?", (id_aut,)).fetchone()
    if not ligne:
        raise ErreurPersonnel("Autorisation introuvable.")
    if ligne["STATUT"] == "ANNULE":
        raise ErreurPersonnel("Cette autorisation est déjà annulée.")
    agent = _ligne(conn, ligne["MATRICULE"])
    with conn:
        conn.execute("UPDATE AUTORISATION_ABSENCE SET STATUT='ANNULE', MOTIF_ANNULATION=?, DATE_ANNULATION=?, ANNULE_PAR=? "
                     "WHERE ID_AUT=?", (motif, iso(maintenant()), session.login, id_aut))
        journaliser(conn, session.id_user, session.login, "AUTORISATION_ANNULEE",
                    f"{ligne['MATRICULE']} | {donnees.nom_complet(agent)} | {TYPES_AUTORISATION[ligne['TYPE']]} du "
                    f"{_formater(ligne['DATE_DEBUT'])} au {_formater(ligne['DATE_FIN'])} | {motif}")


def liste_autorisations(conn, session, matricule) -> dict:
    """Autorisations d'un agent (la plus récente d'abord) et, pour l'année en cours, les jours de travail pris par type.
    Retourne {'autorisations': [...], 'jours_annee': {'PERMISSION': n, 'CONGE': n}, 'annee': aaaa}."""
    exiger(conn, session, "LECTURE")
    _ligne(conn, matricule)
    annee = date.today().year
    debut_an, fin_an = date(annee, 1, 1), date(annee, 12, 31)
    liste, jours_annee = [], {"PERMISSION": 0, "CONGE": 0}
    for l in conn.execute("SELECT * FROM AUTORISATION_ABSENCE WHERE MATRICULE = ? ORDER BY DATE_DEBUT DESC, ID_AUT DESC", (matricule,)):
        d, f = date.fromisoformat(l["DATE_DEBUT"]), date.fromisoformat(l["DATE_FIN"])
        jours = len(jours_de_travail(conn, d, f))
        if l["STATUT"] == "ACCORDE":
            a, b = max(d, debut_an), min(f, fin_an)
            if a <= b:
                jours_annee[l["TYPE"]] += len(jours_de_travail(conn, a, b))
        liste.append({"id": l["ID_AUT"], "type": l["TYPE"], "libelle_type": TYPES_AUTORISATION[l["TYPE"]],
                      "nature": l["NATURE"] or "", "debut": _formater(l["DATE_DEBUT"]), "fin": _formater(l["DATE_FIN"]),
                      "jours": jours, "motif": l["MOTIF"] or "", "statut": l["STATUT"],
                      "libelle_statut": "Accordée" if l["STATUT"] == "ACCORDE" else "Annulée",
                      "motif_annulation": l["MOTIF_ANNULATION"] or ""})
    return {"autorisations": liste, "jours_annee": jours_annee, "annee": annee}


# ================================================================== états récapitulatifs
MAX_PERIODE_JOURS = 366


def _periode(debut_texte, fin_texte):
    debut, fin = _jour(debut_texte, "date de début de la période"), _jour(fin_texte, "date de fin de la période")
    if fin < debut:
        raise ErreurPersonnel("La date de fin de la période est avant la date de début.")
    if (fin - debut).days + 1 > MAX_PERIODE_JOURS:
        raise ErreurPersonnel(f"La période ne peut pas dépasser {MAX_PERIODE_JOURS} jours.")
    return debut, fin


def _agents_du_filtre(conn, debut: date, fin: date, mode, id_filtre):
    """Agents concernés par l'état : ceux dont l'affectation touche la période (par fonction ou par service), sinon tous les
    agents en service pendant la période. Retourne (lignes PERSONNEL, libellé du filtre ou None)."""
    d, f = debut.isoformat(), fin.isoformat()
    libelle = None
    if mode in ("FONCTION", "SERVICE") and id_filtre not in (None, ""):
        table, cle = ("FONCTION_PERSONNEL", "ID_FONCTION") if mode == "FONCTION" else ("SERVICE_PERSONNEL", "ID_SERVICE")
        ref = conn.execute(f"SELECT LIBELLE FROM {table} WHERE {cle} = ?", (int(id_filtre),)).fetchone()
        if not ref:
            raise ErreurPersonnel("Fonction ou service introuvable.")
        libelle = ref["LIBELLE"]
        agents = conn.execute(f"SELECT P.* FROM PERSONNEL P WHERE P.DATE_ENGAGEMENT <= ? AND EXISTS (SELECT 1 FROM AFFECTATION A "
                              f"WHERE A.MATRICULE = P.MATRICULE AND A.{cle} = ? AND A.DATE_DEBUT <= ? "
                              f"AND (A.DATE_FIN IS NULL OR A.DATE_FIN >= ?)) ORDER BY P.NOM COLLATE NOCASE, P.POSTNOM, P.PRENOM",
                              (f, int(id_filtre), f, d)).fetchall()
    else:
        agents = conn.execute("SELECT * FROM PERSONNEL WHERE DATE_ENGAGEMENT <= ? ORDER BY NOM COLLATE NOCASE, POSTNOM, PRENOM",
                              (f,)).fetchall()
    return agents, libelle


def _calculer(conn, debut: date, fin: date, mode, id_filtre) -> dict:
    aujourdhui = date.today()
    limite = min(fin, aujourdhui)
    agents, libelle = _agents_du_filtre(conn, debut, fin, mode, id_filtre)
    jours = jours_de_travail(conn, debut, limite) if limite >= debut else []
    pointages = {}
    for l in conn.execute("SELECT * FROM PRESENCE WHERE DATE_JOUR BETWEEN ? AND ?", (debut.isoformat(), fin.isoformat())):
        pointages[(l["MATRICULE"], l["DATE_JOUR"])] = l
    autorisations = {}
    for l in conn.execute("SELECT * FROM AUTORISATION_ABSENCE WHERE STATUT = 'ACCORDE' AND DATE_DEBUT <= ? AND DATE_FIN >= ?",
                          (fin.isoformat(), debut.isoformat())):
        autorisations.setdefault(l["MATRICULE"], []).append(l)
    lignes, detail, liste_aut = [], [], []
    for a in agents:
        m = a["MATRICULE"]
        c = {"presents": 0, "retards": 0, "minutes": 0, "absents": 0, "permissions": 0, "conges": 0, "non_renseignes": 0}
        attendus = 0
        for j in jours:
            ji = j.isoformat()
            if ji < a["DATE_ENGAGEMENT"]:
                continue
            p = pointages.get((m, ji))
            if p:
                if p["STATUT"] == "PRESENT":
                    c["presents"] += 1
                elif p["STATUT"] == "RETARD":
                    c["retards"] += 1
                    c["minutes"] += p["MINUTES_RETARD"]
                    detail.append({"jour": j.strftime("%d/%m/%Y"), "iso": ji, "matricule": m, "nom_complet": donnees.nom_complet(a),
                                   "statut": "RETARD", "libelle": "En retard", "heure": p["HEURE_ARRIVEE"] or "",
                                   "minutes": p["MINUTES_RETARD"], "motif": p["MOTIF"] or ""})
                else:
                    c["absents"] += 1
                    detail.append({"jour": j.strftime("%d/%m/%Y"), "iso": ji, "matricule": m, "nom_complet": donnees.nom_complet(a),
                                   "statut": "ABSENT", "libelle": "Absent", "heure": "", "minutes": 0, "motif": p["MOTIF"] or ""})
            else:
                aut = next((x for x in autorisations.get(m, []) if x["DATE_DEBUT"] <= ji <= x["DATE_FIN"]), None)
                if aut:
                    c["permissions" if aut["TYPE"] == "PERMISSION" else "conges"] += 1
                else:
                    c["non_renseignes"] += 1
            attendus += 1
        for x in autorisations.get(m, []):
            liste_aut.append({"matricule": m, "nom_complet": donnees.nom_complet(a), "type": x["TYPE"],
                              "libelle_type": TYPES_AUTORISATION[x["TYPE"]], "nature": x["NATURE"] or "",
                              "debut": _formater(x["DATE_DEBUT"]), "fin": _formater(x["DATE_FIN"]), "motif": x["MOTIF"] or ""})
        du = attendus - c["permissions"] - c["conges"]
        taux = round(100 * (c["presents"] + c["retards"]) / du) if du > 0 else None
        if not a["ACTIF"] and attendus == 0:
            continue
        lignes.append({"matricule": m, "nom_complet": donnees.nom_complet(a), "fonction": a["FONCTION"] or "",
                       "jours": attendus, "taux": taux, **c})
    detail.sort(key=lambda e: (e["iso"], donnees.sans_accents(e["nom_complet"])))
    totaux = {k: sum(l[k] for l in lignes) for k in ("jours", "presents", "retards", "minutes", "absents", "permissions", "conges",
                                                     "non_renseignes")}
    du = totaux["jours"] - totaux["permissions"] - totaux["conges"]
    totaux["taux"] = round(100 * (totaux["presents"] + totaux["retards"]) / du) if du > 0 else None
    return {"lignes": lignes, "detail": detail, "autorisations": liste_aut, "totaux": totaux, "jours_travail": len(jours),
            "filtre": libelle, "a_venir": fin > aujourdhui}


def _titre_filtre(mode, libelle):
    return f"{'Fonction' if mode == 'FONCTION' else 'Service'} : {libelle}" if libelle else "Tout le personnel"


def etat_recapitulatif(conn, session, debut_texte, fin_texte, mode=None, id_filtre=None, consultation=True) -> dict:
    """État récapitulatif des présences et absences d'une période, par agent (voir l'en-tête du module pour les règles).
    mode : 'FONCTION' ou 'SERVICE' avec `id_filtre`, ou None pour tout le personnel."""
    exiger(conn, session, "LECTURE")
    debut, fin = _periode(debut_texte, fin_texte)
    r = _calculer(conn, debut, fin, mode, id_filtre)
    r.update({"debut": debut.strftime("%d/%m/%Y"), "fin": fin.strftime("%d/%m/%Y"), "titre": "État récapitulatif des présences et absences",
              "portee": _titre_filtre(mode, r["filtre"])})
    if consultation:
        with conn:
            journaliser(conn, session.id_user, session.login, "ETAT_PRESENCES_CONSULTE",
                        f"du {r['debut']} au {r['fin']} | {r['portee']} | {len(r['lignes'])} agent(s)")
    return r


def preparer_etat_pdf(conn, session, debut_texte, fin_texte, mode=None, id_filtre=None, avec_detail=True) -> str:
    """Génère l'état récapitulatif en PDF (A4) et retourne son chemin."""
    import presences_pdf
    etat = etat_recapitulatif(conn, session, debut_texte, fin_texte, mode, id_filtre, consultation=False)
    config.DOSSIER_PERSONNEL.mkdir(parents=True, exist_ok=True)
    chemin = str(config.DOSSIER_PERSONNEL / "Etat_presences_absences.pdf")
    presences_pdf.generer_etat_pdf(etat, chemin, config.DOSSIER_ASSETS / "logo_recu.jpg", avec_detail=avec_detail,
                                   date_impression=maintenant().astimezone().strftime("%d/%m/%Y"))
    with conn:
        journaliser(conn, session.id_user, session.login, "ETAT_PRESENCES_IMPRIME",
                    f"du {etat['debut']} au {etat['fin']} | {etat['portee']} | {len(etat['lignes'])} agent(s)")
    return chemin


# ================================================================== périodes courantes (raccourcis des écrans)
def periode_du_mois(jour: date) -> tuple:
    debut = jour.replace(day=1)
    suivant = (debut + timedelta(days=32)).replace(day=1)
    return debut, suivant - timedelta(days=1)


def periode_mois_precedent(jour: date) -> tuple:
    return periode_du_mois(jour.replace(day=1) - timedelta(days=1))


def periode_de_la_semaine(jour: date) -> tuple:
    debut = jour - timedelta(days=jour.weekday())
    return debut, debut + timedelta(days=6)

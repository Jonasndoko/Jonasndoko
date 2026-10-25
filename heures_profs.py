"""Direction des études, 2e fonctionnalité : « Présences et heures des professeurs » (sans interface graphique : testable seule).

La Directrice des études (droit « direction_etudes », Lecture) consulte, pour une période :
  - la présence de chaque professeur (pointage du personnel : présent, en retard, absent, permission, congé) ;
  - le calcul de ses heures de cours : heures PRÉVUES par l'horaire publié, heures DONNÉES, heures MANQUÉES, heures justifiées
    (permission ou congé), jours NON RENSEIGNÉS, heures À VENIR ; le taux d'exécution ; le détail séance par séance et par cours.
Consultation seule : rien n'est modifié ici (le pointage se fait dans « Gestion du personnel > Présence et absence »).

Règles de calcul (une « séance » = un cours de l'horaire publié, un jour de la semaine, à son créneau) :
- Seuls les horaires PUBLIÉS comptent ; les séances d'un cours sans professeur ne comptent pour personne (signalées). Le nombre d'horaires non
  publiés est signalé.
- On ne compte que les jours de TRAVAIL de l'école (config.JOURS_DE_TRAVAIL, hors jours non travaillés) à partir de la date d'engagement de l'agent.
- Jour futur : la séance est « à venir ».
- Professeur PRÉSENT ou EN RETARD : s'il n'a pas d'heure d'arrivée notée, ses séances sont données ; sinon une séance finie avant son
  arrivée est manquée, une séance en cours à son arrivée est donnée pour la partie restante (« partielle »), les suivantes sont données
  (le pointage du personnel ne note « en retard » qu'après 7 h 30, mais un cours du matin commence à 7 h : l'heure d'arrivée, même pour un
  « présent », sert au calcul). ABSENT : séance manquée (non justifiée).
- Jour couvert par une PERMISSION ou un CONGÉ accordé : séance manquée mais JUSTIFIÉE (jamais comptée comme absence).
- Jour sans pointage ni autorisation : « non renseigné » (l'absence n'est jamais devinée) : ni donné, ni manqué.
- Taux d'exécution = heures données / (heures données + heures manquées non justifiées).
- Une séance donnée est « confirmée » quand le professeur a aussi pointé les élèves de ce cours ce jour-là (présence des élèves).
  Si le professeur est marqué absent ou en permission alors que ses élèves ont été pointés pour ce cours ce jour-là, la séance est signalée
  comme INCOHÉRENTE (à vérifier).
- Limite : l'horaire est le modèle hebdomadaire EN VIGUEUR. Si l'horaire change en cours d'année, le calcul des jours déjà passés utilise
  l'horaire actuel (l'historique des horaires n'est pas conservé).
- Les heures sont des heures réelles (minutes réelles des créneaux, ex. 45 minutes par cours).
Chaque consultation est inscrite au journal.
"""
import csv
import io
from datetime import date

import donnees
import horaires
import presences
from database import journaliser
from horaires import ErreurHoraire

MAX_PERIODE_JOURS = presences.MAX_PERIODE_JOURS
LIBELLES = {"DONNE": "Donné", "PARTIEL": "Donné en partie", "MANQUE": "Manqué", "JUSTIFIE": "Manqué (justifié)",
            "NON_RENSEIGNE": "Non renseigné", "A_VENIR": "À venir"}


# ================================================================== outils
def formater(minutes) -> str:
    """165 -> « 2 h 45 »."""
    m = int(round(minutes))
    return f"{m // 60} h {m % 60:02d}"


def _decimal(minutes) -> str:
    return f"{minutes / 60:.2f}".replace(".", ",")


def _lire_date(texte, nom) -> date:
    try:
        return presences._jour(texte, nom)
    except presences.ErreurPersonnel as ex:
        raise ErreurHoraire(str(ex)) from None


def periode_par_defaut(jour=None) -> tuple:
    """Le mois de `jour` (aujourd'hui par défaut), en (début, fin) au format AAAA-MM-JJ."""
    d, f = presences.periode_du_mois(jour or date.today())
    return d.isoformat(), f.isoformat()


def raccourcis(jour=None) -> list:
    """Périodes proposées à l'écran : [(libellé, début, fin)]."""
    j = jour or date.today()
    return [(lib, d.isoformat(), f.isoformat()) for lib, (d, f) in (
        ("Cette semaine", presences.periode_de_la_semaine(j)), ("Ce mois", presences.periode_du_mois(j)),
        ("Mois précédent", presences.periode_mois_precedent(j)))]


def _periode(debut_texte, fin_texte) -> tuple:
    if not str(debut_texte or "").strip() and not str(fin_texte or "").strip():
        debut_texte, fin_texte = periode_par_defaut()
    debut, fin = _lire_date(debut_texte, "date de début de la période"), _lire_date(fin_texte, "date de fin de la période")
    if fin < debut:
        raise ErreurHoraire("La date de fin de la période est avant la date de début.")
    if (fin - debut).days + 1 > MAX_PERIODE_JOURS:
        raise ErreurHoraire(f"La période ne peut pas dépasser {MAX_PERIODE_JOURS} jours.")
    return debut, fin


def _minutes_heure(texte) -> int | None:
    try:
        return int(texte[:2]) * 60 + int(texte[3:5])
    except (TypeError, ValueError):
        return None


def _issue(jour: date, aujourdhui: date, pointage, autorisation, s) -> tuple:
    """(code, minutes données, minutes manquées) d'une séance un jour donné."""
    duree = s["f"] - s["d"]
    if jour > aujourdhui:
        return "A_VENIR", 0, 0
    if pointage:
        if pointage["STATUT"] == "ABSENT":
            return "MANQUE", 0, duree
        arrivee = _minutes_heure(pointage["HEURE_ARRIVEE"])            # présent ou en retard : l'heure d'arrivée, si elle est notée, compte
        if arrivee is None or arrivee <= s["d"]:
            return "DONNE", duree, 0
        if arrivee >= s["f"]:
            return "MANQUE", 0, duree
        return "PARTIEL", s["f"] - arrivee, arrivee - s["d"]
    if autorisation:
        return "JUSTIFIE", 0, duree
    return "NON_RENSEIGNE", 0, 0


def _vide() -> dict:
    return {"prevu": 0, "donne": 0, "manque": 0, "justifie": 0, "non_renseigne": 0, "a_venir": 0, "confirme": 0, "incoherentes": 0,
            "nb_prevues": 0, "nb_donnees": 0, "nb_partielles": 0, "nb_manquees": 0, "nb_justifiees": 0, "nb_non_renseignees": 0,
            "nb_a_venir": 0}


_MIN = {"DONNE": "donne", "MANQUE": "manque", "JUSTIFIE": "justifie", "NON_RENSEIGNE": "non_renseigne", "A_VENIR": "a_venir"}
_NB = {"DONNE": "nb_donnees", "PARTIEL": "nb_partielles", "MANQUE": "nb_manquees", "JUSTIFIE": "nb_justifiees",
       "NON_RENSEIGNE": "nb_non_renseignees", "A_VENIR": "nb_a_venir"}


def _cumuler(acc, code, donne, manque, duree, confirme, incoherente) -> None:
    acc["prevu"] += duree
    acc["nb_prevues"] += 1
    acc[_NB[code]] += 1
    if code == "PARTIEL":
        acc["donne"] += donne
        acc["manque"] += manque
    elif code == "JUSTIFIE":
        acc["justifie"] += duree
    else:
        acc[_MIN[code]] += duree if code in ("NON_RENSEIGNE", "A_VENIR") else (donne if code == "DONNE" else manque)
    acc["confirme"] += 1 if confirme else 0
    acc["incoherentes"] += 1 if incoherente else 0


def _finir(acc) -> dict:
    """Ajoute le taux, l'échu et les textes à un cumul."""
    acc["echu"] = acc["donne"] + acc["manque"] + acc["justifie"] + acc["non_renseigne"]
    base = acc["donne"] + acc["manque"]
    acc["taux"] = round(100 * acc["donne"] / base) if base > 0 else None
    for k in ("prevu", "echu", "donne", "manque", "justifie", "non_renseigne", "a_venir"):
        acc[k + "_txt"] = formater(acc[k])
    return acc


# ================================================================== calcul
def _calculer(conn, annee, debut: date, fin: date, matricule=None, avec_detail=False) -> dict:
    aujourdhui = date.today()
    toutes = horaires._seances_de_l_annee(conn, annee)
    publiees = [s for s in toutes if s["statut"] == "PUBLIE"]
    sans_prof = sum(1 for s in publiees if not s["matricule"])
    classes_non_publiees = sorted({s["classe"] for s in toutes if s["statut"] != "PUBLIE"})
    par_prof = {}
    for s in publiees:
        if s["matricule"] and (matricule is None or s["matricule"] == matricule):
            par_prof.setdefault(s["matricule"], {}).setdefault(s["jour"], []).append(s)
    jours = presences.jours_de_travail(conn, debut, fin)
    d_iso, f_iso = debut.isoformat(), fin.isoformat()
    pointages = {(l["MATRICULE"], l["DATE_JOUR"]): l for l in
                 conn.execute("SELECT * FROM PRESENCE WHERE DATE_JOUR BETWEEN ? AND ?", (d_iso, f_iso))}
    autorisations = {}
    for l in conn.execute("SELECT * FROM AUTORISATION_ABSENCE WHERE STATUT = 'ACCORDE' AND DATE_DEBUT <= ? AND DATE_FIN >= ?", (f_iso, d_iso)):
        autorisations.setdefault(l["MATRICULE"], []).append(l)
    eleves_pointes = {(l["ID_CC"], l["DATE_COURS"]) for l in conn.execute(
        "SELECT DISTINCT ID_CC, DATE_COURS FROM PRESENCE_ELEVE WHERE DATE_COURS BETWEEN ? AND ?", (d_iso, f_iso))}
    agents = {l["MATRICULE"]: l for l in conn.execute("SELECT * FROM PERSONNEL")}
    profs, total = [], _vide()
    for m, gabarit in par_prof.items():
        a = agents.get(m)
        if a is None:
            continue
        acc, par_cours, lignes = _vide(), {}, []
        hebdo = sum(s["f"] - s["d"] for seances in gabarit.values() for s in seances)
        for j in jours:
            ji = j.isoformat()
            if ji < a["DATE_ENGAGEMENT"] or j.weekday() not in gabarit:
                continue
            p = pointages.get((m, ji))
            aut = next((x for x in autorisations.get(m, []) if x["DATE_DEBUT"] <= ji <= x["DATE_FIN"]), None) if not p else None
            for s in sorted(gabarit[j.weekday()], key=lambda x: x["d"]):
                code, donne, manque = _issue(j, aujourdhui, p, aut, s)
                duree = s["f"] - s["d"]
                pointe = (s["id_cc"], ji) in eleves_pointes
                confirme = pointe and code in ("DONNE", "PARTIEL")
                incoherente = pointe and code in ("MANQUE", "JUSTIFIE")
                _cumuler(acc, code, donne, manque, duree, confirme, incoherente)
                if avec_detail:
                    _cumuler(par_cours.setdefault((s["classe"], s["cours"]), _vide()), code, donne, manque, duree, confirme, incoherente)
                    motif = ""
                    if p:
                        motif = p["MOTIF"] or (f"arrivé à {p['HEURE_ARRIVEE']}" if p["HEURE_ARRIVEE"] and code in ("PARTIEL", "MANQUE") else "")
                    elif aut:
                        motif = " : ".join(x for x in (presences.TYPES_AUTORISATION[aut["TYPE"]], aut["NATURE"] or "") if x)
                    lignes.append({"iso": ji, "jour": j.strftime("%d/%m/%Y"), "nom_jour": horaires.NOMS_JOURS[j.weekday()],
                                   "debut": s["debut"], "fin": s["fin"], "classe": s["classe"], "cours": s["cours"], "code": code,
                                   "libelle": LIBELLES[code], "donne": formater(donne), "manque": formater(manque) if code != "JUSTIFIE" else formater(duree),
                                   "motif": motif, "confirme": confirme, "incoherente": incoherente})
        _finir(acc)
        ligne = {"matricule": m, "nom": donnees.nom_complet(a), "fonction": a["FONCTION"] or "", "hebdo": hebdo, "hebdo_txt": formater(hebdo), **acc}
        if avec_detail:
            ligne["cours"] = [{"classe": k[0], "cours": k[1], **_finir(v)} for k, v in sorted(par_cours.items())]
            ligne["lignes"] = lignes
        profs.append(ligne)
        for k, v in acc.items():
            if isinstance(v, int) and k in total:
                total[k] += v
    profs.sort(key=lambda x: donnees.sans_accents(x["nom"]))
    _finir(total)
    return {"annee": annee, "debut": debut.strftime("%d/%m/%Y"), "fin": fin.strftime("%d/%m/%Y"), "debut_iso": d_iso, "fin_iso": f_iso,
            "profs": profs, "totaux": total, "jours_travail": len(jours), "a_venir": fin > aujourdhui,
            "classes_non_publiees": classes_non_publiees, "seances_sans_professeur": sans_prof, "libelles": LIBELLES}


def _journal(conn, session, action, detail) -> None:
    with conn:
        journaliser(conn, session.id_user, session.login, action, detail)


# ================================================================== consultation
def liste(conn, session, annee=None, debut_texte="", fin_texte="", recherche="", consultation=True) -> dict:
    """Présences et heures de tous les professeurs de l'horaire publié, pour une période (le mois en cours par défaut)."""
    horaires.exiger(conn, session, "LECTURE")
    annee = horaires._annee(conn, annee)
    debut, fin = _periode(debut_texte, fin_texte)
    r = _calculer(conn, annee, debut, fin)
    q = donnees.sans_accents(str(recherche or "").strip())
    if q:
        r["profs"] = [p for p in r["profs"] if q in donnees.sans_accents(p["nom"]) or q in p["matricule"].lower()]
        total = _vide()
        for p in r["profs"]:
            for k in total:
                total[k] += p[k]
        r["totaux"] = _finir(total)
    r["recherche"] = str(recherche or "").strip()
    if consultation:
        _journal(conn, session, "HEURES_PROFS_CONSULTEES", f"{annee} | du {r['debut']} au {r['fin']} | {len(r['profs'])} professeur(s)")
    return r


def detail(conn, session, annee, matricule, debut_texte="", fin_texte="", consultation=True) -> dict:
    """Heures d'un professeur : totaux, détail par cours et séance par séance, pour une période."""
    horaires.exiger(conn, session, "LECTURE")
    annee = horaires._annee(conn, annee)
    debut, fin = _periode(debut_texte, fin_texte)
    m = str(matricule or "").strip()
    r = _calculer(conn, annee, debut, fin, matricule=m, avec_detail=True)
    if not r["profs"]:
        if not conn.execute("SELECT 1 FROM PERSONNEL WHERE MATRICULE = ?", (m,)).fetchone():
            raise ErreurHoraire("Agent introuvable.")
        raise ErreurHoraire("Ce professeur n'a aucune séance dans un horaire publié pour cette année.")
    r["prof"] = r["profs"][0]
    if consultation:
        _journal(conn, session, "HEURES_PROF_DETAIL_CONSULTE", f"{m} | {annee} | du {r['debut']} au {r['fin']}")
    return r


def exporter_csv(conn, session, annee=None, debut_texte="", fin_texte="", recherche="") -> bytes:
    """Récapitulatif au format CSV (UTF-8 avec BOM, séparateur « ; », heures en décimal) pour un tableur."""
    r = liste(conn, session, annee, debut_texte, fin_texte, recherche, consultation=False)
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";", lineterminator="\r\n")
    w.writerow(["Matricule", "Professeur", "Heures par semaine", "Heures prévues", "Heures données", "Heures manquées",
                "Heures justifiées", "Heures non renseignées", "Heures à venir", "Taux d'exécution (%)"])
    for p in r["profs"]:
        w.writerow([p["matricule"], p["nom"], _decimal(p["hebdo"]), _decimal(p["prevu"]), _decimal(p["donne"]), _decimal(p["manque"]),
                    _decimal(p["justifie"]), _decimal(p["non_renseigne"]), _decimal(p["a_venir"]), "" if p["taux"] is None else p["taux"]])
    t = r["totaux"]
    w.writerow(["", "TOTAL", "", _decimal(t["prevu"]), _decimal(t["donne"]), _decimal(t["manque"]), _decimal(t["justifie"]),
                _decimal(t["non_renseigne"]), _decimal(t["a_venir"]), "" if t["taux"] is None else t["taux"]])
    _journal(conn, session, "HEURES_PROFS_EXPORTEES", f"{r['annee']} | du {r['debut']} au {r['fin']} | {len(r['profs'])} professeur(s)")
    return "﻿".encode("utf-8") + sortie.getvalue().encode("utf-8")

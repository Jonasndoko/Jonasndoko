"""Direction des études, 1re fonctionnalité : « Élaboration horaire » (sans interface graphique : testable seule).

La Directrice des études (droit « direction_etudes ») :
  - règle les heures de chaque vacation (matin / après-midi) : début de la journée, durée d'un cours, nombre de cours avant et après la
    pause, durée de la pause, récréation facultative ;
  - crée l'horaire de chaque classe (choix de la vacation), place les cours dans la grille (jour + numéro du cours), affecte les professeurs ;
  - détecte les conflits (un professeur dans deux classes au même moment) : un placement ou une affectation qui crée un conflit est refusé ;
  - modifie, déplace ou échange des cours en cas de changement ; consulte et imprime par classe ou par professeur ;
  - publie les horaires validés : les professeurs et les responsables ne voient QUE les horaires publiés.

Journée par défaut : 7 cours de 45 minutes, 5 cours, la pause, puis 2 cours ; vacation du matin à 7 h, de l'après-midi à 12 h
(config.HORAIRE_PAR_DEFAUT). Les jours de classe sont ceux de config.JOURS_DE_TRAVAIL.

Règles :
- Un horaire concerne une classe de la section « Secondaire et humanitaire » (sections.py).
- Le professeur d'une séance est toujours celui du cours de la classe (COURS_CLASSE.MATRICULE_PROF) : une seule source de vérité.
- Droits sur « Direction des études » (relus dans la base à chaque appel) : Lecture = consulter, imprimer ; Ajout = créer un horaire, placer
  un cours, affecter un professeur à un cours sans professeur ; Modification = déplacer, remplacer, changer un professeur ou une vacation,
  régler les heures, publier ; Suppression = retirer un cours de la grille, supprimer un horaire. L'Administrateur a tous les droits.
- Les comptes qui n'ont pas la Direction des études mais ouvrent un autre sous-menu du module, et les professeurs (leur propre horaire),
  voient seulement les horaires PUBLIÉS, en lecture seule.
- Toute écriture est inscrite au journal.
"""
import re
from datetime import date

import config
import donnees
import droits
import modules
import notes
import sections
from database import iso, journaliser, maintenant

MODULE = "direction_etudes"
VACATIONS = dict(config.VACATIONS_HORAIRE)
JOURS = tuple(config.JOURS_DE_TRAVAIL)
NOMS_JOURS = config.NOMS_JOURS
MAX_COURS_PAR_JOUR = 10
_HEURE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class ErreurHoraire(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== droits
def _secondaire(conn, session) -> bool:
    return session is not None and sections.SECONDAIRE in sections.sections_de(conn, session)


def peut(conn, session, droit="LECTURE") -> bool:
    """Droit sur « Direction des études » (ou Administrateur), section Secondaire et humanitaire ouverte au compte."""
    return _secondaire(conn, session) and (droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, droit))


def exiger(conn, session, droit="LECTURE"):
    if not peut(conn, session, droit):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS.get(droit, droit)} » "
                              f"sur « {config.MODULES_DROITS[MODULE][0]} » (section secondaire et humanitaire).")


def peut_consulter_publies(conn, session) -> bool:
    """Lecture seule des horaires publiés : la direction elle-même, ou tout compte qui ouvre un sous-menu du module Études et discipline."""
    return bool(modules.sous_menus_ouverts(conn, session))


def _mode_lecture(conn, session) -> bool:
    """True : le compte voit tout (direction) ; False : horaires publiés seulement. PermissionError si aucun des deux."""
    if peut(conn, session, "LECTURE"):
        return True
    if peut_consulter_publies(conn, session):
        return False
    raise PermissionError("Accès refusé : les horaires ne vous sont pas ouverts.")


# ================================================================== outils
def _annee(conn, annee) -> str:
    a = str(annee or "").strip() or donnees.annee_courante(conn)
    if not a or not conn.execute("SELECT 1 FROM ANNEE_SCO WHERE ANNEESCO = ?", (a,)).fetchone():
        raise ErreurHoraire("Aucune année scolaire n'est définie : créez-la d'abord (Direction des études > Années).")
    return a


def liste_annees(conn) -> list:
    return [l[0] for l in conn.execute("SELECT ANNEESCO FROM ANNEE_SCO ORDER BY ANNEESCO DESC")]


def _minutes(texte) -> int:
    m = _HEURE.match(str(texte or "").strip())
    if not m:
        raise ErreurHoraire("Heure invalide : écrivez-la comme 07:00 ou 12:00.")
    return int(m.group(1)) * 60 + int(m.group(2))


def _hm(minutes) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _entier(valeur, nom, mini, maxi) -> int:
    try:
        n = int(str(valeur).strip())
    except (TypeError, ValueError):
        raise ErreurHoraire(f"{nom} : nombre entier attendu.") from None
    if not mini <= n <= maxi:
        raise ErreurHoraire(f"{nom} : entre {mini} et {maxi}.")
    return n


def _jour(valeur) -> int:
    try:
        j = int(valeur)
    except (TypeError, ValueError):
        raise ErreurHoraire("Jour invalide.") from None
    if j not in JOURS:
        raise ErreurHoraire("Ce jour n'est pas un jour de classe.")
    return j


def _vacation(valeur) -> str:
    v = str(valeur or "").strip().upper()
    if v not in VACATIONS:
        raise ErreurHoraire("Choisissez la vacation : matin ou après-midi.")
    return v


def jours() -> list:
    return [{"index": j, "nom": NOMS_JOURS[j]} for j in JOURS]


# ================================================================== heures : réglage et créneaux
def creneaux(p) -> list:
    """Journée d'une vacation, d'après ses réglages : cours (numérotés), pause, récréation. Chaque élément :
    {type: COURS|PAUSE|RECREATION, ordre (cours seulement), libelle, debut, fin, d, f (en minutes)}."""
    t = _minutes(p["debut"])
    total = p["nb_avant"] + p["nb_apres"]
    sortie = []

    def ajouter(type_, libelle, duree, ordre=None):
        nonlocal t
        sortie.append({"type": type_, "ordre": ordre, "libelle": libelle, "debut": _hm(t), "fin": _hm(t + duree), "d": t, "f": t + duree})
        t += duree

    for i in range(1, total + 1):
        ajouter("COURS", f"Cours {i}", p["duree_cours"], i)
        if i < total:
            if i == p["nb_avant"]:
                ajouter("PAUSE", "Pause", p["duree_pause"])
            elif p["recreation_apres"] and i == p["recreation_apres"]:
                ajouter("RECREATION", "Récréation", p["duree_recreation"])
    return sortie


def _parametres_bruts(conn, annee, vacation) -> dict:
    l = conn.execute("SELECT * FROM HORAIRE_PARAM WHERE ANNEESCO = ? AND VACATION = ?", (annee, vacation)).fetchone()
    if not l:
        return dict(config.HORAIRE_PAR_DEFAUT[vacation])
    return {"debut": l["DEBUT"], "duree_cours": l["DUREE_COURS"], "nb_avant": l["NB_AVANT"], "duree_pause": l["DUREE_PAUSE"],
            "nb_apres": l["NB_APRES"], "recreation_apres": l["RECREATION_APRES"], "duree_recreation": l["DUREE_RECREATION"]}


def _tous_creneaux(conn, annee) -> dict:
    return {v: creneaux(_parametres_bruts(conn, annee, v)) for v in VACATIONS}


def parametres(conn, session, annee=None) -> dict:
    """Réglage des heures de chaque vacation pour l'année, avec les créneaux qui en résultent."""
    _mode_lecture(conn, session)
    annee = _annee(conn, annee)
    sortie = {}
    for v, lib in VACATIONS.items():
        p = _parametres_bruts(conn, annee, v)
        sortie[v] = {**p, "vacation": v, "libelle": lib, "creneaux": creneaux(p), "nb_cours": p["nb_avant"] + p["nb_apres"]}
    return {"annee": annee, "vacations": sortie}


def definir_parametres(conn, session, annee, vacation, debut, duree_cours, nb_avant, duree_pause, nb_apres,
                       recreation_apres=0, duree_recreation=10) -> dict:
    """Règle les heures d'une vacation (droit « Modification »). Refusé si un cours déjà placé sortirait de la journée, ou si le changement
    met un professeur à deux endroits à la fois."""
    exiger(conn, session, "MODIFICATION")
    annee, vacation = _annee(conn, annee), _vacation(vacation)
    d = _minutes(debut)
    if vacation == "MATIN" and not 5 * 60 <= d < 12 * 60:
        raise ErreurHoraire("La vacation du matin commence avant 12:00 (par exemple 07:00).")
    if vacation == "APRES_MIDI" and not 12 * 60 <= d < 18 * 60:
        raise ErreurHoraire("La vacation de l'après-midi commence à 12:00 ou plus tard (par exemple 12:00).")
    p = {"debut": _hm(d), "duree_cours": _entier(duree_cours, "Durée d'un cours", 20, 120), "nb_avant": _entier(nb_avant, "Cours avant la pause", 1, 9),
         "duree_pause": _entier(duree_pause, "Durée de la pause", 5, 90), "nb_apres": _entier(nb_apres, "Cours après la pause", 0, 9),
         "recreation_apres": _entier(recreation_apres or 0, "Récréation après le cours n°", 0, 9),
         "duree_recreation": _entier(duree_recreation or 10, "Durée de la récréation", 5, 60)}
    total = p["nb_avant"] + p["nb_apres"]
    if total > MAX_COURS_PAR_JOUR:
        raise ErreurHoraire(f"Au plus {MAX_COURS_PAR_JOUR} cours par jour.")
    if p["recreation_apres"] and (p["recreation_apres"] >= total or p["recreation_apres"] == p["nb_avant"]):
        raise ErreurHoraire("La récréation doit venir après un cours qui n'est ni le dernier ni celui qui précède la pause.")
    if creneaux(p)[-1]["f"] > 23 * 60:
        raise ErreurHoraire("La journée finirait après 23:00 : réduisez la durée ou le nombre de cours.")
    trop = conn.execute("SELECT COUNT(*) FROM HORAIRE_SEANCE S JOIN HORAIRE H ON H.ID_HOR = S.ID_HOR "
                        "WHERE H.ANNEESCO = ? AND H.VACATION = ? AND S.ORDRE > ?", (annee, vacation, total)).fetchone()[0]
    if trop:
        raise ErreurHoraire(f"{trop} cours déjà placés se trouvent après le cours n° {total} : déplacez-les avant de réduire la journée.")
    avant = _cles_conflits(conn, annee)
    with conn:
        conn.execute("INSERT OR REPLACE INTO HORAIRE_PARAM (ANNEESCO, VACATION, DEBUT, DUREE_COURS, NB_AVANT, DUREE_PAUSE, NB_APRES, "
                     "RECREATION_APRES, DUREE_RECREATION, DATE_MODIF, MODIFIE_PAR) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (annee, vacation, p["debut"], p["duree_cours"], p["nb_avant"], p["duree_pause"], p["nb_apres"], p["recreation_apres"],
                      p["duree_recreation"], iso(maintenant()), session.login))
        _refuser_nouveaux_conflits(conn, annee, avant)
        journaliser(conn, session.id_user, session.login, "HORAIRE_HEURES_MODIFIEES",
                    f"{annee} | {VACATIONS[vacation]} | début {p['debut']}, cours {p['duree_cours']} min, {p['nb_avant']}+{p['nb_apres']} cours, "
                    f"pause {p['duree_pause']} min")
    return {"vacation": vacation, "creneaux": creneaux(p)}


# ================================================================== conflits
def _seances_de_l_annee(conn, annee) -> list:
    """Toutes les séances de l'année avec leur horaire, leur classe, leur cours, leur professeur et leurs heures."""
    tous = _tous_creneaux(conn, annee)
    lignes = []
    for l in conn.execute(
            "SELECT S.ID_SEANCE, S.ID_HOR, S.JOUR, S.ORDRE, S.ID_CC, H.N_CLASSE, H.VACATION, H.STATUT, K.DESI_CLASSE, C.LIBELLE AS COURS, "
            "X.MATRICULE_PROF, P.NOM, P.POSTNOM, P.PRENOM FROM HORAIRE_SEANCE S JOIN HORAIRE H ON H.ID_HOR = S.ID_HOR "
            "JOIN COURS_CLASSE X ON X.ID_CC = S.ID_CC JOIN COURS C ON C.ID_COURS = X.ID_COURS JOIN CLASSE K ON K.N_CLASSE = H.N_CLASSE "
            "LEFT JOIN PERSONNEL P ON P.MATRICULE = X.MATRICULE_PROF WHERE H.ANNEESCO = ? "
            "ORDER BY S.JOUR, H.VACATION, S.ORDRE", (annee,)):
        cr = next((c for c in tous[l["VACATION"]] if c["ordre"] == l["ORDRE"]), None)
        if cr is None:
            continue
        lignes.append({"id_seance": l["ID_SEANCE"], "id_hor": l["ID_HOR"], "jour": l["JOUR"], "ordre": l["ORDRE"], "id_cc": l["ID_CC"],
                       "n_classe": l["N_CLASSE"], "classe": l["DESI_CLASSE"], "statut": l["STATUT"], "cours": l["COURS"],
                       "matricule": l["MATRICULE_PROF"] or "", "professeur": donnees.nom_complet(l) if l["MATRICULE_PROF"] else "",
                       "debut": cr["debut"], "fin": cr["fin"], "d": cr["d"], "f": cr["f"]})
    return lignes


def _conflits_de(seances) -> list:
    """Un professeur dans deux classes (ou deux cours) qui se chevauchent le même jour."""
    par_prof = {}
    for s in seances:
        if s["matricule"]:
            par_prof.setdefault((s["matricule"], s["jour"]), []).append(s)
    conflits = []
    for (matricule, jour), liste in par_prof.items():
        liste.sort(key=lambda s: (s["d"], s["id_seance"]))
        groupe = []
        for s in liste:
            if groupe and s["d"] < max(x["f"] for x in groupe):
                groupe.append(s)
                continue
            if len(groupe) > 1:
                conflits.append((matricule, jour, groupe))
            groupe = [s]
        if len(groupe) > 1:
            conflits.append((matricule, jour, groupe))
    sortie = []
    for matricule, jour, groupe in conflits:
        endroits = " et ".join(f"{x['classe']} ({x['cours']}, {x['debut']}-{x['fin']})" for x in groupe)
        sortie.append({"matricule": matricule, "professeur": groupe[0]["professeur"], "jour": jour, "jour_nom": NOMS_JOURS[jour],
                       "seances": [{k: x[k] for k in ("id_seance", "n_classe", "classe", "cours", "debut", "fin", "ordre")} for x in groupe],
                       "message": f"{groupe[0]['professeur']} est attendu à deux endroits le {NOMS_JOURS[jour].lower()} : {endroits}."})
    sortie.sort(key=lambda c: (c["jour"], c["professeur"]))
    return sortie


def _cles_conflits(conn, annee) -> set:
    return {(c["matricule"], c["jour"], tuple(sorted(s["id_seance"] for s in c["seances"]))) for c in _conflits_de(_seances_de_l_annee(conn, annee))}


def _refuser_nouveaux_conflits(conn, annee, avant) -> None:
    """À appeler DANS la transaction : un conflit absent de `avant` annule la modification (la transaction est défaite par l'exception)."""
    for c in _conflits_de(_seances_de_l_annee(conn, annee)):
        if (c["matricule"], c["jour"], tuple(sorted(s["id_seance"] for s in c["seances"]))) not in avant:
            raise ErreurHoraire("Conflit d'horaire, modification refusée : " + c["message"])


def conflits(conn, session, annee=None) -> dict:
    """Tous les conflits de l'année (droit Lecture sur la Direction des études) + les cours placés qui n'ont pas de professeur."""
    exiger(conn, session, "LECTURE")
    annee = _annee(conn, annee)
    seances = _seances_de_l_annee(conn, annee)
    sans = [{"id_seance": s["id_seance"], "classe": s["classe"], "cours": s["cours"], "jour_nom": NOMS_JOURS[s["jour"]], "debut": s["debut"]}
            for s in seances if not s["matricule"]]
    return {"annee": annee, "conflits": _conflits_de(seances), "sans_professeur": sans}


# ================================================================== classes et horaires
def _classe(conn, session, n_classe) -> dict:
    try:
        n = int(n_classe)
    except (TypeError, ValueError):
        raise ErreurHoraire("Classe introuvable.") from None
    sections.exiger_classe(conn, session, n)
    k = conn.execute("SELECT C.N_CLASSE, C.DESI_CLASSE, C.ACTIF, N.DESI_NIVEAU, N.SECTION, O.DESI_OPTION FROM CLASSE C "
                     "JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
                     "WHERE C.N_CLASSE = ?", (n,)).fetchone()
    if not k:
        raise ErreurHoraire("Classe introuvable.")
    if k["SECTION"] != sections.SECONDAIRE:
        raise PermissionError("Accès refusé : l'élaboration horaire concerne seulement la section secondaire et humanitaire.")
    return {"n_classe": k["N_CLASSE"], "designation": k["DESI_CLASSE"], "niveau": k["DESI_NIVEAU"], "option": k["DESI_OPTION"] or "",
            "actif": bool(k["ACTIF"])}


def _horaire(conn, annee, n_classe):
    return conn.execute("SELECT * FROM HORAIRE WHERE ANNEESCO = ? AND N_CLASSE = ?", (annee, n_classe)).fetchone()


def _horaire_existant(conn, annee, n_classe):
    h = _horaire(conn, annee, n_classe)
    if not h:
        raise ErreurHoraire("Cette classe n'a pas encore d'horaire pour cette année : créez-le d'abord.")
    return h


def _fr(texte) -> str:
    try:
        return date.fromisoformat(str(texte)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(texte or "")


def classes(conn, session, annee=None) -> dict:
    """Classes du secondaire et humanitaire avec l'état de leur horaire. Un compte qui ne voit que le publié ne reçoit que les horaires publiés."""
    complet = _mode_lecture(conn, session)
    annee = _annee(conn, annee)
    conf = _conflits_de(_seances_de_l_annee(conn, annee)) if complet else []
    en_conflit = {s["n_classe"] for c in conf for s in c["seances"]}
    lignes = []
    for k in conn.execute("SELECT C.N_CLASSE, C.DESI_CLASSE, N.DESI_NIVEAU, O.DESI_OPTION FROM CLASSE C JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
                          "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION WHERE C.ACTIF = 1 AND N.SECTION = 'SECONDAIRE' "
                          "ORDER BY N.DESI_NIVEAU COLLATE NOCASE, C.DESI_CLASSE COLLATE NOCASE"):
        h = _horaire(conn, annee, k["N_CLASSE"])
        if not complet and (not h or h["STATUT"] != "PUBLIE"):
            continue
        nb = conn.execute("SELECT COUNT(*) FROM HORAIRE_SEANCE WHERE ID_HOR = ?", (h["ID_HOR"],)).fetchone()[0] if h else 0
        requis = conn.execute("SELECT COALESCE(SUM(HEURES_SEMAINE), 0) FROM COURS_CLASSE WHERE ANNEESCO = ? AND N_CLASSE = ?",
                              (annee, k["N_CLASSE"])).fetchone()[0]
        lignes.append({"n_classe": k["N_CLASSE"], "designation": k["DESI_CLASSE"], "niveau": k["DESI_NIVEAU"], "option": k["DESI_OPTION"] or "",
                       "existe": bool(h), "statut": h["STATUT"] if h else "", "vacation": VACATIONS.get(h["VACATION"], "") if h else "",
                       "nb_seances": nb, "heures_requises": requis, "conflit": k["N_CLASSE"] in en_conflit,
                       "statut_libelle": "Publié" if h and h["STATUT"] == "PUBLIE" else "Brouillon" if h else "Pas d'horaire"})
    return {"annee": annee, "classes": lignes, "complet": complet, "nb_conflits": len(conf)}


def creer_horaire(conn, session, annee, n_classe, vacation="MATIN") -> int:
    """Crée l'horaire (vide) d'une classe pour l'année, avec sa vacation (droit « Ajout »)."""
    exiger(conn, session, "AJOUT")
    annee, vacation = _annee(conn, annee), _vacation(vacation)
    k = _classe(conn, session, n_classe)
    if _horaire(conn, annee, k["n_classe"]):
        raise ErreurHoraire(f"La classe {k['designation']} a déjà un horaire pour {annee}.")
    with conn:
        cur = conn.execute("INSERT INTO HORAIRE (ANNEESCO, N_CLASSE, VACATION, DATE_ENREG, ENREGISTRE_PAR) VALUES (?,?,?,?,?)",
                           (annee, k["n_classe"], vacation, iso(maintenant()), session.login))
        journaliser(conn, session.id_user, session.login, "HORAIRE_CREE", f"{annee} | {k['designation']} | {VACATIONS[vacation]}")
    return cur.lastrowid


def changer_vacation(conn, session, annee, n_classe, vacation) -> None:
    """Fait passer la classe du matin à l'après-midi (ou l'inverse) avec tous ses cours (droit « Modification »)."""
    exiger(conn, session, "MODIFICATION")
    annee, vacation = _annee(conn, annee), _vacation(vacation)
    k = _classe(conn, session, n_classe)
    h = _horaire_existant(conn, annee, k["n_classe"])
    if h["VACATION"] == vacation:
        return
    total = {v: len([c for c in cr if c["type"] == "COURS"]) for v, cr in _tous_creneaux(conn, annee).items()}[vacation]
    if conn.execute("SELECT COUNT(*) FROM HORAIRE_SEANCE WHERE ID_HOR = ? AND ORDRE > ?", (h["ID_HOR"], total)).fetchone()[0]:
        raise ErreurHoraire(f"Cette vacation n'a que {total} cours par jour : des cours de la classe sont placés plus loin.")
    avant = _cles_conflits(conn, annee)
    with conn:
        conn.execute("UPDATE HORAIRE SET VACATION = ?, DATE_MODIF = ?, MODIFIE_PAR = ? WHERE ID_HOR = ?",
                     (vacation, iso(maintenant()), session.login, h["ID_HOR"]))
        _refuser_nouveaux_conflits(conn, annee, avant)
        journaliser(conn, session.id_user, session.login, "HORAIRE_VACATION_CHANGEE", f"{annee} | {k['designation']} | {VACATIONS[vacation]}")


def supprimer_horaire(conn, session, annee, n_classe) -> None:
    """Supprime l'horaire d'une classe (droit « Suppression »). Un horaire publié doit d'abord être retiré de la publication."""
    exiger(conn, session, "SUPPRESSION")
    annee = _annee(conn, annee)
    k = _classe(conn, session, n_classe)
    h = _horaire_existant(conn, annee, k["n_classe"])
    if h["STATUT"] == "PUBLIE":
        raise ErreurHoraire("Cet horaire est publié : retirez-le d'abord de la publication.")
    with conn:
        conn.execute("DELETE FROM HORAIRE_SEANCE WHERE ID_HOR = ?", (h["ID_HOR"],))
        conn.execute("DELETE FROM HORAIRE WHERE ID_HOR = ?", (h["ID_HOR"],))
        journaliser(conn, session.id_user, session.login, "HORAIRE_SUPPRIME", f"{annee} | {k['designation']}")


# ================================================================== la grille d'une classe
def _cours_de_la_classe(conn, annee, n_classe) -> list:
    sortie = []
    for l in conn.execute("SELECT X.ID_CC, X.HEURES_SEMAINE, X.MATRICULE_PROF, C.LIBELLE, C.ACTIF, P.NOM, P.POSTNOM, P.PRENOM, "
                          "(SELECT COUNT(*) FROM HORAIRE_SEANCE S WHERE S.ID_CC = X.ID_CC) AS PLACES "
                          "FROM COURS_CLASSE X JOIN COURS C ON C.ID_COURS = X.ID_COURS LEFT JOIN PERSONNEL P ON P.MATRICULE = X.MATRICULE_PROF "
                          "WHERE X.ANNEESCO = ? AND X.N_CLASSE = ? ORDER BY C.LIBELLE COLLATE NOCASE", (annee, n_classe)):
        sortie.append({"id_cc": l["ID_CC"], "cours": l["LIBELLE"], "actif": bool(l["ACTIF"]), "heures": l["HEURES_SEMAINE"], "places": l["PLACES"],
                       "reste": max(l["HEURES_SEMAINE"] - l["PLACES"], 0), "matricule": l["MATRICULE_PROF"] or "",
                       "professeur": donnees.nom_complet(l) if l["MATRICULE_PROF"] else ""})
    return sortie


def grille(conn, session, annee, n_classe) -> dict:
    """Horaire d'une classe : jours, créneaux de sa vacation, cases occupées, cours à placer (avec heures placées / heures par semaine),
    conflits et alertes. Un compte « publié seulement » ne reçoit que l'horaire publié."""
    complet = _mode_lecture(conn, session)
    annee = _annee(conn, annee)
    k = _classe(conn, session, n_classe)
    h = _horaire(conn, annee, k["n_classe"])
    if h and not complet and h["STATUT"] != "PUBLIE":
        h = None
    sortie = {"annee": annee, "classe": k, "complet": complet, "jours": jours(), "existe": bool(h), "horaire": None, "creneaux": [], "cases": {},
              "cours": [], "conflits": [], "alertes": [], "vacations": [{"cle": v, "libelle": lib} for v, lib in VACATIONS.items()],
              "peut_publier": False}
    if not h:
        if complet:
            sortie["cours"] = _cours_de_la_classe(conn, annee, k["n_classe"])
        return sortie
    cr = _tous_creneaux(conn, annee)[h["VACATION"]]
    sortie["creneaux"] = cr
    sortie["horaire"] = {"id": h["ID_HOR"], "vacation": h["VACATION"], "vacation_libelle": VACATIONS[h["VACATION"]], "statut": h["STATUT"],
                         "publie": h["STATUT"] == "PUBLIE", "date_pub": _fr(h["DATE_PUB"]) if h["DATE_PUB"] else "", "publie_par": h["PUBLIE_PAR"] or ""}
    seances = _seances_de_l_annee(conn, annee)
    conf = _conflits_de(seances)
    ids_en_conflit = {s["id_seance"] for c in conf for s in c["seances"]}
    for s in seances:
        if s["id_hor"] == h["ID_HOR"]:
            sortie["cases"][f"{s['jour']}-{s['ordre']}"] = {"id_seance": s["id_seance"], "id_cc": s["id_cc"], "cours": s["cours"],
                                                            "professeur": s["professeur"], "matricule": s["matricule"],
                                                            "conflit": s["id_seance"] in ids_en_conflit}
    if complet:
        sortie["cours"] = _cours_de_la_classe(conn, annee, k["n_classe"])
        sortie["conflits"] = [c for c in conf if any(x["n_classe"] == k["n_classe"] for x in c["seances"])]
        for c in sortie["cours"]:
            if c["places"] > c["heures"] > 0:
                sortie["alertes"].append(f"{c['cours']} : {c['places']} cours placés pour {c['heures']} heure(s) par semaine.")
            elif c["heures"] and c["places"] < c["heures"]:
                sortie["alertes"].append(f"{c['cours']} : {c['places']} cours placés sur {c['heures']} heure(s) par semaine.")
        for case in sortie["cases"].values():
            if not case["matricule"]:
                sortie["alertes"].append(f"{case['cours']} : aucun professeur affecté.")
        sortie["alertes"] = sorted(set(sortie["alertes"]))
        sortie["peut_publier"] = not sortie["conflits"] and bool(sortie["cases"]) and all(c["matricule"] for c in sortie["cases"].values())
    return sortie


# ================================================================== placer, retirer, déplacer
def _cours_valide(conn, annee, n_classe, id_cc):
    try:
        id_cc = int(id_cc)
    except (TypeError, ValueError):
        raise ErreurHoraire("Choisissez un cours.") from None
    l = conn.execute("SELECT X.*, C.LIBELLE, C.ACTIF FROM COURS_CLASSE X JOIN COURS C ON C.ID_COURS = X.ID_COURS WHERE X.ID_CC = ?", (id_cc,)).fetchone()
    if not l or l["ANNEESCO"] != annee or l["N_CLASSE"] != n_classe:
        raise ErreurHoraire("Ce cours n'est pas ouvert dans cette classe pour cette année.")
    if not l["ACTIF"]:
        raise ErreurHoraire(f"Le cours « {l['LIBELLE']} » est désactivé.")
    return l


def _ordre(conn, annee, h, ordre) -> int:
    n = _entier(ordre, "Numéro du cours", 1, MAX_COURS_PAR_JOUR)
    nb = len([c for c in _tous_creneaux(conn, annee)[h["VACATION"]] if c["type"] == "COURS"])
    if n > nb:
        raise ErreurHoraire(f"Cette vacation n'a que {nb} cours par jour.")
    return n


def _marquer(conn, session, h) -> None:
    conn.execute("UPDATE HORAIRE SET DATE_MODIF = ?, MODIFIE_PAR = ? WHERE ID_HOR = ?", (iso(maintenant()), session.login, h["ID_HOR"]))


def placer(conn, session, annee, n_classe, jour, ordre, id_cc) -> int:
    """Place un cours dans une case (jour + numéro du cours). Case libre : droit « Ajout » ; case occupée (le cours est remplacé) : « Modification ».
    Refusé si le professeur est déjà pris à ce moment, ou si le cours a déjà toutes ses heures de la semaine placées."""
    exiger(conn, session, "AJOUT")
    annee = _annee(conn, annee)
    k = _classe(conn, session, n_classe)
    h = _horaire_existant(conn, annee, k["n_classe"])
    j, n = _jour(jour), _ordre(conn, annee, h, ordre)
    cc = _cours_valide(conn, annee, k["n_classe"], id_cc)
    en_place = conn.execute("SELECT * FROM HORAIRE_SEANCE WHERE ID_HOR = ? AND JOUR = ? AND ORDRE = ?", (h["ID_HOR"], j, n)).fetchone()
    if en_place and en_place["ID_CC"] == cc["ID_CC"]:
        return en_place["ID_SEANCE"]
    if en_place:
        exiger(conn, session, "MODIFICATION")
    deja = conn.execute("SELECT COUNT(*) FROM HORAIRE_SEANCE WHERE ID_CC = ?", (cc["ID_CC"],)).fetchone()[0]
    if cc["HEURES_SEMAINE"] and deja >= cc["HEURES_SEMAINE"]:
        raise ErreurHoraire(f"« {cc['LIBELLE']} » a déjà ses {cc['HEURES_SEMAINE']} heure(s) de la semaine placées.")
    avant = _cles_conflits(conn, annee)
    with conn:
        if en_place:
            conn.execute("DELETE FROM HORAIRE_SEANCE WHERE ID_SEANCE = ?", (en_place["ID_SEANCE"],))
        cur = conn.execute("INSERT INTO HORAIRE_SEANCE (ID_HOR, JOUR, ORDRE, ID_CC, DATE_ENREG, ENREGISTRE_PAR) VALUES (?,?,?,?,?,?)",
                           (h["ID_HOR"], j, n, cc["ID_CC"], iso(maintenant()), session.login))
        _refuser_nouveaux_conflits(conn, annee, avant)
        _marquer(conn, session, h)
        journaliser(conn, session.id_user, session.login, "HORAIRE_SEANCE_PLACEE",
                    f"{annee} | {k['designation']} | {NOMS_JOURS[j]} cours {n} | {cc['LIBELLE']}")
    return cur.lastrowid


def _seance(conn, annee, id_seance):
    try:
        i = int(id_seance)
    except (TypeError, ValueError):
        raise ErreurHoraire("Séance introuvable.") from None
    l = conn.execute("SELECT S.*, H.ANNEESCO, H.N_CLASSE, H.VACATION, K.DESI_CLASSE, C.LIBELLE AS COURS FROM HORAIRE_SEANCE S "
                     "JOIN HORAIRE H ON H.ID_HOR = S.ID_HOR JOIN CLASSE K ON K.N_CLASSE = H.N_CLASSE JOIN COURS_CLASSE X ON X.ID_CC = S.ID_CC "
                     "JOIN COURS C ON C.ID_COURS = X.ID_COURS WHERE S.ID_SEANCE = ?", (i,)).fetchone()
    if not l or l["ANNEESCO"] != annee:
        raise ErreurHoraire("Séance introuvable.")
    return l


def retirer(conn, session, annee, id_seance) -> None:
    """Retire un cours de la grille (droit « Suppression »)."""
    exiger(conn, session, "SUPPRESSION")
    annee = _annee(conn, annee)
    s = _seance(conn, annee, id_seance)
    sections.exiger_classe(conn, session, s["N_CLASSE"])
    with conn:
        conn.execute("DELETE FROM HORAIRE_SEANCE WHERE ID_SEANCE = ?", (s["ID_SEANCE"],))
        conn.execute("UPDATE HORAIRE SET DATE_MODIF = ?, MODIFIE_PAR = ? WHERE ID_HOR = ?", (iso(maintenant()), session.login, s["ID_HOR"]))
        journaliser(conn, session.id_user, session.login, "HORAIRE_SEANCE_RETIREE",
                    f"{annee} | {s['DESI_CLASSE']} | {NOMS_JOURS[s['JOUR']]} cours {s['ORDRE']} | {s['COURS']}")


def deplacer(conn, session, annee, id_seance, jour, ordre) -> dict:
    """Déplace un cours vers une autre case de la même classe (droit « Modification »). Si la case est occupée, les deux cours sont échangés."""
    exiger(conn, session, "MODIFICATION")
    annee = _annee(conn, annee)
    s = _seance(conn, annee, id_seance)
    sections.exiger_classe(conn, session, s["N_CLASSE"])
    h = conn.execute("SELECT * FROM HORAIRE WHERE ID_HOR = ?", (s["ID_HOR"],)).fetchone()
    j, n = _jour(jour), _ordre(conn, annee, h, ordre)
    if (j, n) == (s["JOUR"], s["ORDRE"]):
        return {"echange": False}
    autre = conn.execute("SELECT * FROM HORAIRE_SEANCE WHERE ID_HOR = ? AND JOUR = ? AND ORDRE = ?", (h["ID_HOR"], j, n)).fetchone()
    avant = _cles_conflits(conn, annee)
    with conn:
        if autre:
            conn.execute("UPDATE HORAIRE_SEANCE SET ORDRE = 99 WHERE ID_SEANCE = ?", (autre["ID_SEANCE"],))
        conn.execute("UPDATE HORAIRE_SEANCE SET JOUR = ?, ORDRE = ? WHERE ID_SEANCE = ?", (j, n, s["ID_SEANCE"]))
        if autre:
            conn.execute("UPDATE HORAIRE_SEANCE SET JOUR = ?, ORDRE = ? WHERE ID_SEANCE = ?", (s["JOUR"], s["ORDRE"], autre["ID_SEANCE"]))
        _refuser_nouveaux_conflits(conn, annee, avant)
        _marquer(conn, session, h)
        journaliser(conn, session.id_user, session.login, "HORAIRE_SEANCE_DEPLACEE",
                    f"{annee} | {s['DESI_CLASSE']} | {s['COURS']} : {NOMS_JOURS[s['JOUR']]} cours {s['ORDRE']} -> {NOMS_JOURS[j]} cours {n}"
                    + (" (échange)" if autre else ""))
    return {"echange": bool(autre)}


# ================================================================== professeurs
def professeurs(conn, session) -> list:
    """Agents en service que l'on peut affecter à un cours."""
    exiger(conn, session, "LECTURE")
    return [{"matricule": p["MATRICULE"], "nom": donnees.nom_complet(p), "fonction": p["FONCTION"]}
            for p in conn.execute("SELECT * FROM PERSONNEL WHERE ACTIF = 1 ORDER BY NOM COLLATE NOCASE, POSTNOM COLLATE NOCASE, PRENOM COLLATE NOCASE")]


def affecter_professeur(conn, session, annee, id_cc, matricule) -> None:
    """Affecte (ou change, ou retire si `matricule` est vide) le professeur d'un cours de classe. Cours sans professeur : droit « Ajout » ;
    changer ou retirer : « Modification ». Refusé si le professeur est déjà pris au moment où ce cours est placé."""
    exiger(conn, session, "AJOUT")
    annee = _annee(conn, annee)
    try:
        cc = conn.execute("SELECT X.*, C.LIBELLE, K.DESI_CLASSE FROM COURS_CLASSE X JOIN COURS C ON C.ID_COURS = X.ID_COURS "
                          "JOIN CLASSE K ON K.N_CLASSE = X.N_CLASSE WHERE X.ID_CC = ?", (int(id_cc),)).fetchone()
    except (TypeError, ValueError):
        cc = None
    if not cc or cc["ANNEESCO"] != annee:
        raise ErreurHoraire("Cours introuvable.")
    k = _classe(conn, session, cc["N_CLASSE"])
    matricule = str(matricule or "").strip() or None
    if (cc["MATRICULE_PROF"] or None) == matricule:
        return
    if cc["MATRICULE_PROF"] or matricule is None:
        exiger(conn, session, "MODIFICATION")
    prof = None
    if matricule:
        prof = conn.execute("SELECT * FROM PERSONNEL WHERE MATRICULE = ?", (matricule,)).fetchone()
        if not prof:
            raise ErreurHoraire("Agent introuvable.")
        if not prof["ACTIF"]:
            raise ErreurHoraire(f"{donnees.nom_complet(prof)} : le dossier est désactivé, on ne lui attribue plus de cours.")
    avant = _cles_conflits(conn, annee)
    with conn:
        conn.execute("UPDATE COURS_CLASSE SET MATRICULE_PROF = ?, DATE_MODIF = ?, MODIFIE_PAR = ? WHERE ID_CC = ?",
                     (matricule, iso(maintenant()), session.login, cc["ID_CC"]))
        _refuser_nouveaux_conflits(conn, annee, avant)
        journaliser(conn, session.id_user, session.login, "HORAIRE_PROFESSEUR_AFFECTE" if prof else "HORAIRE_PROFESSEUR_RETIRE",
                    f"{annee} | {k['designation']} | {cc['LIBELLE']}" + (f" | {matricule} | {donnees.nom_complet(prof)}" if prof else ""))


# ================================================================== publication
def _etat_publication(conn, annee, h) -> list:
    """Raisons qui empêchent de publier l'horaire (liste vide : publiable)."""
    raisons = []
    seances = _seances_de_l_annee(conn, annee)
    propres = [s for s in seances if s["id_hor"] == h["ID_HOR"]]
    if not propres:
        raisons.append("l'horaire est vide")
    raisons += [f"{s['cours']} ({NOMS_JOURS[s['jour']]}, cours {s['ordre']}) n'a pas de professeur" for s in propres if not s["matricule"]]
    ids = {s["id_seance"] for s in propres}
    raisons += [c["message"] for c in _conflits_de(seances) if any(x["id_seance"] in ids for x in c["seances"])]
    return raisons


def publier(conn, session, annee, n_classe) -> None:
    """Publie l'horaire validé d'une classe (droit « Modification ») : refusé s'il est vide, s'il a un conflit ou un cours sans professeur."""
    exiger(conn, session, "MODIFICATION")
    annee = _annee(conn, annee)
    k = _classe(conn, session, n_classe)
    h = _horaire_existant(conn, annee, k["n_classe"])
    raisons = _etat_publication(conn, annee, h)
    if raisons:
        raise ErreurHoraire(f"Publication refusée pour {k['designation']} : " + " ; ".join(raisons) + ".")
    with conn:
        conn.execute("UPDATE HORAIRE SET STATUT = 'PUBLIE', DATE_PUB = ?, PUBLIE_PAR = ? WHERE ID_HOR = ?", (iso(maintenant()), session.login, h["ID_HOR"]))
        journaliser(conn, session.id_user, session.login, "HORAIRE_PUBLIE", f"{annee} | {k['designation']}")


def retirer_publication(conn, session, annee, n_classe) -> None:
    """Remet l'horaire en brouillon : il n'est plus visible des professeurs et des responsables (droit « Modification »)."""
    exiger(conn, session, "MODIFICATION")
    annee = _annee(conn, annee)
    k = _classe(conn, session, n_classe)
    h = _horaire_existant(conn, annee, k["n_classe"])
    if h["STATUT"] != "PUBLIE":
        raise ErreurHoraire("Cet horaire n'est pas publié.")
    with conn:
        conn.execute("UPDATE HORAIRE SET STATUT = 'BROUILLON', DATE_PUB = NULL, PUBLIE_PAR = NULL WHERE ID_HOR = ?", (h["ID_HOR"],))
        journaliser(conn, session.id_user, session.login, "HORAIRE_DEPUBLIE", f"{annee} | {k['designation']}")


def publier_tout(conn, session, annee) -> dict:
    """Publie tous les horaires brouillons qui sont publiables ; les autres sont listés avec leurs raisons."""
    exiger(conn, session, "MODIFICATION")
    annee = _annee(conn, annee)
    publies, refuses = [], []
    for h in conn.execute("SELECT H.*, K.DESI_CLASSE FROM HORAIRE H JOIN CLASSE K ON K.N_CLASSE = H.N_CLASSE "
                          "WHERE H.ANNEESCO = ? AND H.STATUT = 'BROUILLON' ORDER BY K.DESI_CLASSE", (annee,)).fetchall():
        try:
            sections.exiger_classe(conn, session, h["N_CLASSE"])
        except PermissionError:
            continue
        raisons = _etat_publication(conn, annee, h)
        if raisons:
            refuses.append({"classe": h["DESI_CLASSE"], "raisons": raisons})
        else:
            publier(conn, session, annee, h["N_CLASSE"])
            publies.append(h["DESI_CLASSE"])
    return {"publies": publies, "refuses": refuses}


# ================================================================== horaire d'un professeur
def _vue_professeur(conn, annee, matricule, publie_seulement) -> dict:
    p = conn.execute("SELECT * FROM PERSONNEL WHERE MATRICULE = ?", (matricule,)).fetchone()
    if not p:
        raise ErreurHoraire("Agent introuvable.")
    seances = [s for s in _seances_de_l_annee(conn, annee) if s["matricule"] == matricule and (s["statut"] == "PUBLIE" or not publie_seulement)]
    ids_conflit = {x["id_seance"] for c in _conflits_de(seances) for x in c["seances"]}
    lignes = {}
    for s in sorted(seances, key=lambda x: (x["d"], x["f"])):
        ligne = lignes.setdefault((s["debut"], s["fin"]), {"debut": s["debut"], "fin": s["fin"], "cases": {}})
        ligne["cases"].setdefault(s["jour"], []).append({"classe": s["classe"], "cours": s["cours"], "publie": s["statut"] == "PUBLIE",
                                                         "conflit": s["id_seance"] in ids_conflit})
    return {"annee": annee, "matricule": matricule, "professeur": donnees.nom_complet(p), "jours": jours(), "lignes": list(lignes.values()),
            "nb_seances": len(seances), "brouillon": any(s["statut"] != "PUBLIE" for s in seances)}


def liste_professeurs_horaire(conn, session, annee=None) -> dict:
    """Professeurs qui ont au moins un cours dans une classe du secondaire cette année (les horaires publiés seulement, hors direction)."""
    complet = _mode_lecture(conn, session)
    annee = _annee(conn, annee)
    sql = ("SELECT DISTINCT P.MATRICULE, P.NOM, P.POSTNOM, P.PRENOM FROM COURS_CLASSE X JOIN PERSONNEL P ON P.MATRICULE = X.MATRICULE_PROF "
           "JOIN CLASSE K ON K.N_CLASSE = X.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = K.CODE_NIVEAU WHERE X.ANNEESCO = ? AND N.SECTION = 'SECONDAIRE' ")
    if not complet:
        sql += ("AND EXISTS (SELECT 1 FROM HORAIRE_SEANCE S JOIN HORAIRE H ON H.ID_HOR = S.ID_HOR JOIN COURS_CLASSE Y ON Y.ID_CC = S.ID_CC "
                "WHERE H.ANNEESCO = X.ANNEESCO AND H.STATUT = 'PUBLIE' AND Y.MATRICULE_PROF = P.MATRICULE) ")
    sql += "ORDER BY P.NOM COLLATE NOCASE, P.POSTNOM COLLATE NOCASE, P.PRENOM COLLATE NOCASE"
    return {"annee": annee, "professeurs": [{"matricule": l["MATRICULE"], "nom": donnees.nom_complet(l)} for l in conn.execute(sql, (annee,))]}


def horaire_professeur(conn, session, annee, matricule) -> dict:
    """Horaire d'un professeur : tout pour la direction, le publié seulement pour les autres comptes."""
    complet = _mode_lecture(conn, session)
    return _vue_professeur(conn, _annee(conn, annee), str(matricule or "").strip(), not complet)


def mon_horaire(conn, session, annee=None) -> dict:
    """Horaire publié du professeur connecté (son compte est relié à son dossier d'agent)."""
    prof = notes._professeur(conn, session)
    annee = _annee(conn, annee)
    return _vue_professeur(conn, annee, prof["MATRICULE"], True)

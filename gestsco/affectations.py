"""Module « Gestion du personnel » - deuxième fonctionnalité : FONCTIONS ET AFFECTATIONS (sans interface : testable seul).

Ce que cette fonctionnalité permet :
  - déterminer les FONCTIONS (Enseignant, Secrétaire...) et les SERVICES (Administration, Discipline...) de l'école ;
  - affecter chaque agent à une fonction, dans un service et/ou avec une responsabilité (ex. « Titulaire de la 3ème A ») ;
  - enregistrer la date de début et, si nécessaire, la date de fin d'une affectation ;
  - conserver l'HISTORIQUE des changements de fonction : une affectation n'est jamais supprimée ;
  - produire la liste du personnel par fonction ou par service (à l'écran et en PDF), à la date de son choix.

Règles :
  - un agent n'a qu'UNE affectation à la fois (les périodes ne se chevauchent pas) ;
  - en affectant un agent qui a une affectation en cours SANS date de fin, celle-ci se termine automatiquement la veille du
    nouveau début : c'est ainsi qu'un changement de fonction s'enregistre (une date de fin déjà fixée n'est jamais raccourcie
    d'office : il faut la corriger) ;
  - la fonction affichée dans le dossier de l'agent (PERSONNEL.FONCTION) est celle de son affectation en cours ;
  - à l'enregistrement d'un agent (Dossier personnel), sa fonction est ajoutée à la liste si elle n'y est pas et sa première
    affectation commence à sa date d'engagement ;
  - une fonction ou un service déjà utilisé ne se supprime pas : on le désactive (il n'est plus proposé, l'historique reste).

Droits (module « personnel » ; l'Administrateur les a tous) :
  Lecture : historique, listes du personnel (consultation et impression) ; Ajout : créer une fonction ou un service, affecter un
  agent ; Modification : renommer, désactiver / réactiver, corriger ou terminer une affectation ; Suppression : retirer une
  fonction ou un service jamais utilisé.
Chaque opération est contrôlée au moment de l'action et inscrite au journal.
"""
import re
import sqlite3
from datetime import date, timedelta

import config
import donnees
from database import iso, journaliser, maintenant
from personnel import ErreurPersonnel, _formater, _ligne, _obligatoire, _texte, exiger, peut
from saisie_date import lire_date_texte

__all__ = ["peut", "exiger", "ErreurPersonnel"]

# genre -> (table, clé, libellé au singulier avec article défini, masculin ?)
GENRES = {"FONCTION": ("FONCTION_PERSONNEL", "ID_FONCTION", "La fonction", False),
          "SERVICE": ("SERVICE_PERSONNEL", "ID_SERVICE", "Le service", True)}
# Actions inscrites au journal (libellés dans audit.py)
ACTIONS_REF = {(g, op): f"{g}_{op}" for g in GENRES for op in ("AJOUT", "MODIFICATION", "ACTIVATION", "DESACTIVATION", "SUPPRESSION")}
LONGUEUR_MAX = 60
STATUTS_AFFECTATION = {"EN_COURS": "En cours", "TERMINEE": "Terminée", "A_VENIR": "À venir"}
SANS_SERVICE = "(Sans service)"
SANS_AFFECTATION = "(Sans affectation en cours)"


def _g(genre):
    if genre not in GENRES:
        raise ValueError(f"Genre inconnu : {genre}")
    return GENRES[genre]


# ================================================================== listes de choix : fonctions et services
def liste_referentiel(conn, session, genre, inclure_inactifs=True) -> list:
    """[{id, libelle, actif, nb_agents, nb_affectations}] : nb_agents = agents qui l'occupent aujourd'hui."""
    exiger(conn, session, "LECTURE")
    table, cle, _art, _m = _g(genre)
    aujourdhui = date.today().isoformat()
    resultat = []
    for l in conn.execute(f"SELECT * FROM {table} ORDER BY LIBELLE COLLATE NOCASE"):
        if not inclure_inactifs and not l["ACTIF"]:
            continue
        nb_aff = conn.execute(f"SELECT COUNT(*) FROM AFFECTATION WHERE {cle} = ?", (l[cle],)).fetchone()[0]
        nb_ag = conn.execute(f"SELECT COUNT(DISTINCT A.MATRICULE) FROM AFFECTATION A JOIN PERSONNEL P ON P.MATRICULE = A.MATRICULE "
                             f"WHERE A.{cle} = ? AND P.ACTIF = 1 AND A.DATE_DEBUT <= ? AND (A.DATE_FIN IS NULL OR A.DATE_FIN >= ?)",
                             (l[cle], aujourdhui, aujourdhui)).fetchone()[0]
        resultat.append({"id": l[cle], "libelle": l["LIBELLE"], "actif": bool(l["ACTIF"]), "nb_agents": nb_ag,
                         "nb_affectations": nb_aff})
    return resultat


def _libelle_valide(texte, genre) -> str:
    libelle = _texte(texte)
    if not libelle:
        raise ErreurPersonnel(f"Saisissez le nom {'de la fonction' if genre == 'FONCTION' else 'du service'}.")
    if len(libelle) > LONGUEUR_MAX:
        raise ErreurPersonnel(f"Le nom est trop long ({LONGUEUR_MAX} caractères au plus).")
    return libelle[0].upper() + libelle[1:]


def _existe_deja(genre):
    art = _g(genre)[2]
    return ErreurPersonnel(f"{art} existe déjà (la liste ne distingue pas majuscules et minuscules).")


def ajouter_referentiel(conn, session, genre, libelle) -> int:
    exiger(conn, session, "AJOUT")
    table, cle, _a, _m = _g(genre)
    libelle = _libelle_valide(libelle, genre)
    action = ACTIONS_REF[(genre, "AJOUT")]
    try:
        with conn:
            id_ = conn.execute(f"INSERT INTO {table} (LIBELLE) VALUES (?)", (libelle,)).lastrowid
            journaliser(conn, session.id_user, session.login, action, libelle)
    except sqlite3.IntegrityError:
        raise _existe_deja(genre) from None
    return id_


def _ligne_ref(conn, genre, id_):
    table, cle, art, _m = _g(genre)
    l = conn.execute(f"SELECT * FROM {table} WHERE {cle} = ?", (id_,)).fetchone()
    if not l:
        raise ErreurPersonnel(f"{art} est introuvable.")
    return l


def renommer_referentiel(conn, session, genre, id_, libelle):
    exiger(conn, session, "MODIFICATION")
    table, cle, _a, _m = _g(genre)
    libelle = _libelle_valide(libelle, genre)
    avant = _ligne_ref(conn, genre, id_)
    if avant["LIBELLE"] == libelle:
        return
    action = ACTIONS_REF[(genre, "MODIFICATION")]
    try:
        with conn:
            conn.execute(f"UPDATE {table} SET LIBELLE = ? WHERE {cle} = ?", (libelle, id_))
            if genre == "FONCTION":
                _synchroniser_tous(conn)                     # le dossier de chaque agent affiche le nouveau nom
            journaliser(conn, session.id_user, session.login, action, f"{avant['LIBELLE']} -> {libelle}")
    except sqlite3.IntegrityError:
        raise _existe_deja(genre) from None


def changer_activite_referentiel(conn, session, genre, id_, actif: bool):
    exiger(conn, session, "MODIFICATION")
    table, cle, _a, _m = _g(genre)
    ligne = _ligne_ref(conn, genre, id_)
    if bool(ligne["ACTIF"]) == bool(actif):
        return
    action = ACTIONS_REF[(genre, "ACTIVATION" if actif else "DESACTIVATION")]
    with conn:
        conn.execute(f"UPDATE {table} SET ACTIF = ? WHERE {cle} = ?", (1 if actif else 0, id_))
        journaliser(conn, session.id_user, session.login, action, ligne["LIBELLE"])


def supprimer_referentiel(conn, session, genre, id_):
    """Retire une fonction ou un service jamais utilisé. S'il l'a été : refus (on le désactive à la place)."""
    exiger(conn, session, "SUPPRESSION")
    table, cle, art, _m = _g(genre)
    ligne = _ligne_ref(conn, genre, id_)
    n = conn.execute(f"SELECT COUNT(*) FROM AFFECTATION WHERE {cle} = ?", (id_,)).fetchone()[0]
    if n:
        raise ErreurPersonnel(f"{art} « {ligne['LIBELLE']} » est utilisé{'' if _m else 'e'} dans {n} affectation(s) : "
                              f"il ne peut pas être supprimé{'' if _m else 'e'}. Désactivez-le{'' if _m else '-la'} : "
                              f"il ne sera plus proposé{'' if _m else 'e'} mais l'historique est conservé.")
    action = ACTIONS_REF[(genre, "SUPPRESSION")]
    with conn:
        conn.execute(f"DELETE FROM {table} WHERE {cle} = ?", (id_,))
        journaliser(conn, session.id_user, session.login, action, ligne["LIBELLE"])


def obtenir_fonction(conn, libelle, creer=True) -> sqlite3.Row:
    """Fonction de ce nom (casse ignorée) ; créée si elle n'existe pas. À appeler dans une transaction. Refuse une fonction
    désactivée. Utilisé par l'enregistrement d'un agent (Dossier personnel)."""
    libelle = _libelle_valide(libelle, "FONCTION")
    l = conn.execute("SELECT * FROM FONCTION_PERSONNEL WHERE LIBELLE = ?", (libelle,)).fetchone()
    if l is None:
        conn.execute("INSERT INTO FONCTION_PERSONNEL (LIBELLE) VALUES (?)", (libelle,))
        l = conn.execute("SELECT * FROM FONCTION_PERSONNEL WHERE LIBELLE = ?", (libelle,)).fetchone()
    elif not l["ACTIF"]:
        raise ErreurPersonnel(f"La fonction « {l['LIBELLE']} » est désactivée : réactivez-la (Fonctions et services) "
                              f"ou choisissez-en une autre.")
    return l


# ================================================================== affectations : lecture des saisies
def _date(texte, nom, obligatoire=True):
    if not _texte(texte):
        if obligatoire:
            raise ErreurPersonnel(f"Renseignez la {nom}.")
        return None
    jour = lire_date_texte(texte)
    if jour is None:
        raise ErreurPersonnel(f"La {nom} est invalide. Écrivez-la ainsi : 01/09/2026")
    return jour


def _valider(conn, saisie: dict, ancienne=None) -> dict:
    """Contrôle une saisie d'affectation. `ancienne` : ligne existante (modification) : sa fonction ou son service
    désactivés restent acceptés tant qu'on ne les change pas."""
    try:
        id_f = int(saisie.get("id_fonction"))
    except (TypeError, ValueError):
        raise ErreurPersonnel("Choisissez la fonction.") from None
    f = conn.execute("SELECT * FROM FONCTION_PERSONNEL WHERE ID_FONCTION = ?", (id_f,)).fetchone()
    if not f:
        raise ErreurPersonnel("Cette fonction n'existe pas.")
    if not f["ACTIF"] and not (ancienne and ancienne["ID_FONCTION"] == id_f):
        raise ErreurPersonnel(f"La fonction « {f['LIBELLE']} » est désactivée : choisissez-en une autre.")
    id_s = saisie.get("id_service")
    s = None
    if id_s not in (None, ""):
        s = conn.execute("SELECT * FROM SERVICE_PERSONNEL WHERE ID_SERVICE = ?", (int(id_s),)).fetchone()
        if not s:
            raise ErreurPersonnel("Ce service n'existe pas.")
        if not s["ACTIF"] and not (ancienne and ancienne["ID_SERVICE"] == s["ID_SERVICE"]):
            raise ErreurPersonnel(f"Le service « {s['LIBELLE']} » est désactivé : choisissez-en un autre.")
    resp = _texte(saisie.get("responsabilite")) or None
    if resp and len(resp) > 100:
        raise ErreurPersonnel("La responsabilité est trop longue (100 caractères au plus).")
    debut = _date(saisie.get("date_debut"), "date de début")
    fin = _date(saisie.get("date_fin"), "date de fin", obligatoire=False)
    if fin and fin < debut:
        raise ErreurPersonnel("La date de fin ne peut pas être avant la date de début.")
    motif = _texte(saisie.get("motif")) or None
    if motif and len(motif) > 200:
        raise ErreurPersonnel("Le motif est trop long (200 caractères au plus).")
    return {"fonction": f, "service": s, "ID_FONCTION": id_f, "ID_SERVICE": s["ID_SERVICE"] if s else None,
            "RESPONSABILITE": resp, "debut": debut, "fin": fin, "MOTIF": motif}


def _resume(conn, id_f, id_s, resp, debut, fin) -> str:
    f = conn.execute("SELECT LIBELLE FROM FONCTION_PERSONNEL WHERE ID_FONCTION = ?", (id_f,)).fetchone()[0]
    s = conn.execute("SELECT LIBELLE FROM SERVICE_PERSONNEL WHERE ID_SERVICE = ?", (id_s,)).fetchone()[0] if id_s else "-"
    return f"{f} | service {s} | resp. {resp or '-'} | du {_formater(debut)} au {_formater(fin) if fin else 'sans fin'}"


def _synchroniser(conn, matricule):
    """PERSONNEL.FONCTION = fonction de l'affectation en cours (sinon la dernière commencée). Sans écriture au journal :
    c'est un simple reflet de l'historique."""
    jour = date.today().isoformat()
    l = conn.execute(
        "SELECT F.LIBELLE FROM AFFECTATION A JOIN FONCTION_PERSONNEL F ON F.ID_FONCTION = A.ID_FONCTION "
        "WHERE A.MATRICULE = ? AND A.DATE_DEBUT <= ? ORDER BY (A.DATE_FIN IS NULL OR A.DATE_FIN >= ?) DESC, A.DATE_DEBUT DESC LIMIT 1",
        (matricule, jour, jour)).fetchone()
    if l:
        conn.execute("UPDATE PERSONNEL SET FONCTION = ? WHERE MATRICULE = ? AND FONCTION <> ?", (l[0], matricule, l[0]))


def _synchroniser_tous(conn):
    for m in conn.execute("SELECT MATRICULE FROM PERSONNEL").fetchall():
        _synchroniser(conn, m[0])


def rafraichir_fonctions(conn):
    """Remet à jour la fonction affichée dans chaque dossier (une affectation a pu commencer ou finir avec le temps).
    Opération interne, sans droit particulier : elle ne fait que refléter l'historique."""
    with conn:
        _synchroniser_tous(conn)


# ================================================================== affectations : écriture
def creer_initiale(conn, matricule, id_fonction, debut_iso, login):
    """Première affectation d'un agent (appelée par l'enregistrement du Dossier personnel, dans sa transaction)."""
    conn.execute("INSERT INTO AFFECTATION (MATRICULE, ID_FONCTION, DATE_DEBUT, MOTIF, DATE_ENREG, ENREGISTRE_PAR) "
                 "VALUES (?,?,?,?,?,?)", (matricule, id_fonction, debut_iso, "Engagement", iso(maintenant()), login))


def _chevauchement(conn, matricule, debut: date, fin, sauf=None):
    """Affectations de l'agent qui chevauchent [debut, fin] (fin None = sans fin), sans celle de numéro `sauf`."""
    d, f = debut.isoformat(), fin.isoformat() if fin else None
    return [e for e in conn.execute("SELECT * FROM AFFECTATION WHERE MATRICULE = ? ORDER BY DATE_DEBUT", (matricule,))
            if e["ID_AFF"] != sauf and (e["DATE_FIN"] is None or e["DATE_FIN"] >= d) and (f is None or e["DATE_DEBUT"] <= f)]


def _texte_periode(e) -> str:
    return f"du {_formater(e['DATE_DEBUT'])} au {_formater(e['DATE_FIN']) if e['DATE_FIN'] else 'sans fin'}"


def affecter(conn, session, matricule, saisie: dict) -> dict:
    """Affecte un agent (changement de fonction, de service ou de responsabilité).
    saisie : id_fonction, id_service (facultatif), responsabilite (facultative), date_debut, date_fin (facultative), motif.
    Retourne {'id_aff', 'terminees': [texte des affectations terminées automatiquement]}."""
    exiger(conn, session, "AJOUT")
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        agent = _ligne(conn, matricule)
        if not agent["ACTIF"]:
            raise ErreurPersonnel("Cet agent est désactivé : réactivez son dossier avant de l'affecter.")
        v = _valider(conn, saisie)
        if v["debut"].isoformat() < agent["DATE_ENGAGEMENT"]:
            raise ErreurPersonnel(f"L'affectation ne peut pas commencer avant l'engagement de l'agent "
                                  f"({_formater(agent['DATE_ENGAGEMENT'])}).")
        a_terminer = []
        for e in _chevauchement(conn, agent["MATRICULE"], v["debut"], v["fin"]):
            if e["DATE_DEBUT"] < v["debut"].isoformat() and e["DATE_FIN"] is None:
                a_terminer.append(e)                          # l'affectation sans fin se termine la veille du nouveau début
            else:                                             # une fin déjà fixée n'est jamais raccourcie sans qu'on le demande
                raise ErreurPersonnel(f"Cette période chevauche une affectation existante ({_texte_periode(e)}). "
                                      f"Un agent n'a qu'une affectation à la fois : corrigez les dates, ou changez d'abord la "
                                      f"date de fin de l'affectation existante (Corriger).")
        veille = (v["debut"] - timedelta(days=1)).isoformat()
        maintenant_iso = iso(maintenant())
        terminees = []
        for e in a_terminer:
            conn.execute("UPDATE AFFECTATION SET DATE_FIN = ?, DATE_MODIF = ?, MODIFIE_PAR = ? WHERE ID_AFF = ?",
                         (veille, maintenant_iso, session.login, e["ID_AFF"]))
            journaliser(conn, session.id_user, session.login, "AFFECTATION_TERMINEE",
                        f"{agent['MATRICULE']} | fin automatique (nouvelle affectation) | "
                        + _resume(conn, e["ID_FONCTION"], e["ID_SERVICE"], e["RESPONSABILITE"], e["DATE_DEBUT"], veille))
            terminees.append(_resume(conn, e["ID_FONCTION"], e["ID_SERVICE"], e["RESPONSABILITE"], e["DATE_DEBUT"], veille))
        id_aff = conn.execute(
            "INSERT INTO AFFECTATION (MATRICULE, ID_FONCTION, ID_SERVICE, RESPONSABILITE, DATE_DEBUT, DATE_FIN, MOTIF, DATE_ENREG, "
            "ENREGISTRE_PAR) VALUES (?,?,?,?,?,?,?,?,?)",
            (agent["MATRICULE"], v["ID_FONCTION"], v["ID_SERVICE"], v["RESPONSABILITE"], v["debut"].isoformat(),
             v["fin"].isoformat() if v["fin"] else None, v["MOTIF"], maintenant_iso, session.login)).lastrowid
        journaliser(conn, session.id_user, session.login, "AFFECTATION_ENREGISTREE",
                    f"{agent['MATRICULE']} | " + _resume(conn, v["ID_FONCTION"], v["ID_SERVICE"], v["RESPONSABILITE"],
                                                         v["debut"].isoformat(), v["fin"].isoformat() if v["fin"] else None))
        _synchroniser(conn, agent["MATRICULE"])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"id_aff": id_aff, "terminees": terminees}


def _ligne_aff(conn, id_aff):
    l = conn.execute("SELECT * FROM AFFECTATION WHERE ID_AFF = ?", (id_aff,)).fetchone()
    if not l:
        raise ErreurPersonnel("Affectation introuvable.")
    return l


def _saisie_de(l) -> dict:
    return {"id_fonction": l["ID_FONCTION"], "id_service": l["ID_SERVICE"], "responsabilite": l["RESPONSABILITE"],
            "date_debut": _formater(l["DATE_DEBUT"]), "date_fin": _formater(l["DATE_FIN"]) if l["DATE_FIN"] else "",
            "motif": l["MOTIF"]}


def modifier_affectation(conn, session, id_aff, saisie: dict, action="AFFECTATION_MODIFIEE") -> list:
    """Corrige une affectation (fonction, service, responsabilité, dates, motif). Retourne les champs changés."""
    exiger(conn, session, "MODIFICATION")
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        avant = _ligne_aff(conn, id_aff)
        v = _valider(conn, saisie, ancienne=avant)
        agent = _ligne(conn, avant["MATRICULE"])
        if v["debut"].isoformat() < agent["DATE_ENGAGEMENT"]:
            raise ErreurPersonnel(f"L'affectation ne peut pas commencer avant l'engagement de l'agent "
                                  f"({_formater(agent['DATE_ENGAGEMENT'])}).")
        autres = _chevauchement(conn, avant["MATRICULE"], v["debut"], v["fin"], sauf=id_aff)
        if autres:
            raise ErreurPersonnel(f"Ces dates chevauchent une autre affectation de l'agent ({_texte_periode(autres[0])}).")
        nouveau = {"ID_FONCTION": v["ID_FONCTION"], "ID_SERVICE": v["ID_SERVICE"], "RESPONSABILITE": v["RESPONSABILITE"],
                   "DATE_DEBUT": v["debut"].isoformat(), "DATE_FIN": v["fin"].isoformat() if v["fin"] else None,
                   "MOTIF": v["MOTIF"]}
        noms = {"ID_FONCTION": "fonction", "ID_SERVICE": "service", "RESPONSABILITE": "responsabilité",
                "DATE_DEBUT": "date de début", "DATE_FIN": "date de fin", "MOTIF": "motif"}
        changes = [c for c in noms if (avant[c] or None) != (nouveau[c] or None)]
        if changes:
            conn.execute("UPDATE AFFECTATION SET " + ", ".join(f"{c} = ?" for c in nouveau) + ", DATE_MODIF = ?, MODIFIE_PAR = ? "
                         "WHERE ID_AFF = ?", list(nouveau.values()) + [iso(maintenant()), session.login, id_aff])
            journaliser(conn, session.id_user, session.login, action,
                        f"{avant['MATRICULE']} | " + ", ".join(noms[c] for c in changes) + " | "
                        + _resume(conn, v["ID_FONCTION"], v["ID_SERVICE"], v["RESPONSABILITE"], nouveau["DATE_DEBUT"],
                                  nouveau["DATE_FIN"]))
            _synchroniser(conn, avant["MATRICULE"])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return [noms[c] for c in changes]


def terminer_affectation(conn, session, id_aff, date_fin, motif=None) -> list:
    """Met une date de fin à une affectation (l'agent quitte ce poste sans être réaffecté tout de suite)."""
    exiger(conn, session, "MODIFICATION")
    if not _texte(date_fin):
        raise ErreurPersonnel("Renseignez la date de fin.")
    l = _ligne_aff(conn, id_aff)
    saisie = _saisie_de(l)
    saisie["date_fin"] = date_fin
    if _texte(motif):
        saisie["motif"] = motif
    return modifier_affectation(conn, session, id_aff, saisie, action="AFFECTATION_TERMINEE")


# ================================================================== historique
def _statut(debut, fin, jour):
    if debut > jour:
        return "A_VENIR"
    return "TERMINEE" if fin and fin < jour else "EN_COURS"


def _duree(debut: str, fin_ou_jour: str) -> str:
    d, f = date.fromisoformat(debut), date.fromisoformat(fin_ou_jour)
    if f < d:
        return ""
    mois = (f.year - d.year) * 12 + f.month - d.month - (1 if f.day < d.day else 0)
    ans, mois = divmod(max(mois, 0), 12)
    morceaux = ([f"{ans} an{'s' if ans > 1 else ''}"] if ans else []) + ([f"{mois} mois"] if mois else [])
    return " ".join(morceaux) or f"{(f - d).days + 1} jour(s)"


_SELECT_AFF = ("SELECT A.*, F.LIBELLE AS FONCTION, S.LIBELLE AS SERVICE FROM AFFECTATION A "
               "JOIN FONCTION_PERSONNEL F ON F.ID_FONCTION = A.ID_FONCTION "
               "LEFT JOIN SERVICE_PERSONNEL S ON S.ID_SERVICE = A.ID_SERVICE ")


def _aff_vers_dict(l, jour: str) -> dict:
    statut = _statut(l["DATE_DEBUT"], l["DATE_FIN"], jour)
    return {"id_aff": l["ID_AFF"], "matricule": l["MATRICULE"], "id_fonction": l["ID_FONCTION"], "fonction": l["FONCTION"],
            "id_service": l["ID_SERVICE"], "service": l["SERVICE"] or "", "responsabilite": l["RESPONSABILITE"] or "",
            "date_debut": _formater(l["DATE_DEBUT"]), "date_fin": _formater(l["DATE_FIN"]) if l["DATE_FIN"] else "",
            "motif": l["MOTIF"] or "", "statut": statut, "libelle_statut": STATUTS_AFFECTATION[statut],
            "duree": _duree(l["DATE_DEBUT"], min(l["DATE_FIN"] or jour, jour)) if statut != "A_VENIR" else "",
            "enregistre_par": l["ENREGISTRE_PAR"]}


def historique_agent(conn, session, matricule) -> list:
    """Toutes les affectations de l'agent, de la plus récente à la plus ancienne."""
    exiger(conn, session, "LECTURE")
    _ligne(conn, matricule)
    jour = date.today().isoformat()
    return [_aff_vers_dict(l, jour) for l in conn.execute(
        _SELECT_AFF + "WHERE A.MATRICULE = ? ORDER BY A.DATE_DEBUT DESC, A.ID_AFF DESC", (matricule,))]


def situation_actuelle(conn, session, matricule):
    """Affectation en cours aujourd'hui (dict), ou None."""
    return next((a for a in historique_agent(conn, session, matricule) if a["statut"] == "EN_COURS"), None)


def charger_affectation(conn, session, id_aff) -> dict:
    exiger(conn, session, "LECTURE")
    l = conn.execute(_SELECT_AFF + "WHERE A.ID_AFF = ?", (id_aff,)).fetchone()
    if not l:
        raise ErreurPersonnel("Affectation introuvable.")
    return _aff_vers_dict(l, date.today().isoformat())


# ================================================================== listes du personnel
MODES = {"FONCTION": "par fonction", "SERVICE": "par service"}


def liste_personnel(conn, session, mode, id_filtre=None, jour_texte="", consultation=True) -> dict:
    """Liste du personnel EN SERVICE à une date, groupée par fonction ou par service.
    mode : 'FONCTION' ou 'SERVICE' ; id_filtre : une seule fonction / un seul service (sinon tous) ; jour_texte : date
    de la situation (vide : aujourd'hui). Les agents désactivés n'y figurent pas.
    Retourne {'mode', 'titre', 'filtre', 'jour', 'groupes': [{'libelle', 'agents': [...]}], 'total'}."""
    exiger(conn, session, "LECTURE")
    if mode not in MODES:
        raise ValueError("mode inconnu")
    jour = _date(jour_texte, "date de la situation", obligatoire=False) or date.today()
    j = jour.isoformat()
    filtre = None
    if id_filtre not in (None, ""):
        filtre = _ligne_ref(conn, mode, int(id_filtre))["LIBELLE"]
    groupes, vus = {}, set()
    for l in conn.execute(_SELECT_AFF + "JOIN PERSONNEL P ON P.MATRICULE = A.MATRICULE "
                          "WHERE P.ACTIF = 1 AND A.DATE_DEBUT <= ? AND (A.DATE_FIN IS NULL OR A.DATE_FIN >= ?)", (j, j)):
        cle_ref = l["ID_FONCTION"] if mode == "FONCTION" else l["ID_SERVICE"]
        if id_filtre not in (None, "") and cle_ref != int(id_filtre):
            continue
        libelle = l["FONCTION"] if mode == "FONCTION" else (l["SERVICE"] or SANS_SERVICE)
        agent = conn.execute("SELECT * FROM PERSONNEL WHERE MATRICULE = ?", (l["MATRICULE"],)).fetchone()
        vus.add(l["MATRICULE"])
        groupes.setdefault(libelle, []).append({
            "matricule": l["MATRICULE"], "nom_complet": donnees.nom_complet(agent), "fonction": l["FONCTION"],
            "service": l["SERVICE"] or "", "responsabilite": l["RESPONSABILITE"] or "", "depuis": _formater(l["DATE_DEBUT"]),
            "telephone": agent["TELEPHONE"]})
    if id_filtre in (None, ""):                                   # agents en service sans affectation à cette date
        for agent in conn.execute("SELECT * FROM PERSONNEL WHERE ACTIF = 1 AND DATE_ENGAGEMENT <= ?", (j,)):
            if agent["MATRICULE"] not in vus:
                groupes.setdefault(SANS_AFFECTATION, []).append({
                    "matricule": agent["MATRICULE"], "nom_complet": donnees.nom_complet(agent), "fonction": "", "service": "",
                    "responsabilite": "", "depuis": "", "telephone": agent["TELEPHONE"]})
    ordre = sorted(groupes, key=lambda g: (g in (SANS_SERVICE, SANS_AFFECTATION), donnees.sans_accents(g)))
    resultat = [{"libelle": g, "agents": sorted(groupes[g], key=lambda a: donnees.sans_accents(a["nom_complet"]))} for g in ordre]
    total = sum(len(g["agents"]) for g in resultat)
    if consultation:
        with conn:
            journaliser(conn, session.id_user, session.login, "LISTE_PERSONNEL_CONSULTEE",
                        f"{MODES[mode]} | {filtre or 'tous'} | au {jour.strftime('%d/%m/%Y')} | {total} agent(s)")
    return {"mode": mode, "titre": f"Liste du personnel {MODES[mode]}", "filtre": filtre, "jour": jour.strftime("%d/%m/%Y"),
            "groupes": resultat, "total": total}


def preparer_liste_pdf(conn, session, mode, id_filtre=None, jour_texte="") -> str:
    """Génère la liste du personnel (PDF A4) et retourne son chemin."""
    import personnel_pdf
    liste = liste_personnel(conn, session, mode, id_filtre, jour_texte, consultation=False)
    config.DOSSIER_PERSONNEL.mkdir(parents=True, exist_ok=True)
    chemin = str(config.DOSSIER_PERSONNEL / f"Liste_personnel_{MODES[mode].replace(' ', '_')}.pdf")
    personnel_pdf.generer_liste_pdf(liste, chemin, config.DOSSIER_ASSETS / "logo_recu.jpg",
                                    date_impression=maintenant().astimezone().strftime("%d/%m/%Y"))
    with conn:
        journaliser(conn, session.id_user, session.login, "LISTE_PERSONNEL_IMPRIMEE",
                    f"{MODES[mode]} | {liste['filtre'] or 'tous'} | au {liste['jour']} | {liste['total']} agent(s)")
    return chemin

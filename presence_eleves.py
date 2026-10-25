"""Présence des élèves aux cours.

- Le PROFESSEUR (page web, comme la saisie des points) pointe, pour son cours et un jour, chaque élève présent ou absent, et
  consulte les présences de son cours par classe. Il ne voit que ses cours et ses heures : pas les pointages des autres professeurs.
  Le TITULAIRE de la classe ne gère pas les présences (il pointe seulement son propre cours, comme tout professeur).
- RÈGLE DE LA JOURNÉE : plusieurs professeurs pointent la même classe le même jour. Un élève n'est PRÉSENT pour la journée que
  s'il est présent à TOUS les cours pointés ce jour-là ; absent à un seul cours pointé, il est ABSENT pour la journée (avec la
  liste des cours manqués). Aucun cours pointé : journée non renseignée.
- Le Directeur de discipline et la Directrice des études (comptes ayant le droit « Lecture » sur « Présence des élèves », ou sur
  « Direction des études ») voient la liste des élèves de TOUTES les classes, en lecture seule (écran du logiciel : module « Présence
  des élèves »).
"""
from datetime import date

import config
import cours
import donnees
import droits
import notes
from database import iso, journaliser, maintenant

ErreurPresence = notes.ErreurNotes
ERREURS = notes.ERREURS
STATUTS = {"P": "Présent", "A": "Absent"}
MAX_JOURS_HISTORIQUE = 60


def _jour(conn, annee, texte) -> date:
    """Date du cours : aujourd'hui si vide ; jamais dans le futur ; dans l'année scolaire si ses dates sont définies."""
    t = str(texte or "").strip()
    d = cours._date(t, "date du cours") if t else date.today()
    if d > date.today():
        raise ErreurPresence("On ne pointe pas la présence d'un jour qui n'est pas encore arrivé.")
    c = conn.execute("SELECT DATE_DEBUT, DATE_FIN FROM ANNEE_CALENDRIER WHERE ANNEESCO = ?", (annee,)).fetchone()
    if c and not (c["DATE_DEBUT"] <= d.isoformat() <= c["DATE_FIN"]):
        raise ErreurPresence(f"Cette date est hors de l'année scolaire {annee} "
                             f"({date.fromisoformat(c['DATE_DEBUT']).strftime('%d/%m/%Y')} - {date.fromisoformat(c['DATE_FIN']).strftime('%d/%m/%Y')}).")
    return d


def _fr(d) -> str:
    return (d if isinstance(d, date) else date.fromisoformat(d)).strftime("%d/%m/%Y")


def _statuts_jour(conn, annee, n_classe, jour_iso) -> dict:
    """{matricule: {'statut': 'P'|'A'|'', 'manques': [cours absents], 'pointes': nb de cours pointés pour lui}} pour une classe et un jour."""
    resultat = {}
    for l in conn.execute("SELECT PE.MATRICULE, PE.STATUT, C.LIBELLE FROM PRESENCE_ELEVE PE JOIN COURS_CLASSE X ON X.ID_CC = PE.ID_CC "
                          "JOIN COURS C ON C.ID_COURS = X.ID_COURS WHERE X.ANNEESCO = ? AND X.N_CLASSE = ? AND PE.DATE_COURS = ? "
                          "ORDER BY C.LIBELLE COLLATE NOCASE", (annee, n_classe, jour_iso)):
        r = resultat.setdefault(l["MATRICULE"], {"statut": "P", "manques": [], "pointes": 0})
        r["pointes"] += 1
        if l["STATUT"] == "A":
            r["statut"] = "A"
            r["manques"].append(l["LIBELLE"])
    return resultat


# ================================================================== professeur
def liste(conn, session, id_cc, jour_texte="") -> dict:
    """Les élèves de la classe pour un cours et un jour : leur pointage, et leur situation pour toute la journée."""
    prof, cc = notes._cc(conn, session, id_cc)
    d = _jour(conn, cc["ANNEESCO"], jour_texte)
    pointes = {l["MATRICULE"]: l["STATUT"] for l in conn.execute(
        "SELECT MATRICULE, STATUT FROM PRESENCE_ELEVE WHERE ID_CC = ? AND DATE_COURS = ?", (cc["ID_CC"], d.isoformat()))}
    eleves = []
    for e in notes._eleves(conn, cc):
        eleves.append({"matricule": e["MATRICULE"], "nom_complet": donnees.nom_complet(e), "sexe": e["SEXE"] or "",
                       "statut": pointes.get(e["MATRICULE"], "")})
    return {"id_cc": cc["ID_CC"], "cours": cc["COURS"], "classe": cc["DESI_CLASSE"], "option": cc["DESI_OPTION"] or "",
            "annee": cc["ANNEESCO"], "date": _fr(d), "modifiable": bool(cc["ANNEE_ACTIVE"]), "eleves": eleves,
            "presents": sum(1 for e in eleves if e["statut"] == "P"), "absents": sum(1 for e in eleves if e["statut"] == "A"),
            "non_pointes": sum(1 for e in eleves if not e["statut"])}


def _eleve_de_la_classe(conn, cc, matricule):
    if not conn.execute("SELECT 1 FROM INSCRIRE WHERE ANNEESCO = ? AND N_CLASSE = ? AND MATRICULE = ?",
                        (cc["ANNEESCO"], cc["N_CLASSE"], matricule)).fetchone():
        raise PermissionError("Accès refusé : cet élève n'est pas dans la classe de ce cours.")


def marquer(conn, session, id_cc, jour_texte, matricule, statut):
    """Pointe un élève : 'P' présent, 'A' absent, '' pour retirer le pointage (retour à « pas encore pointé »)."""
    prof, cc = notes._cc(conn, session, id_cc, ecriture=True)
    d = _jour(conn, cc["ANNEESCO"], jour_texte)
    statut = str(statut or "").strip().upper()
    if statut not in ("P", "A", ""):
        raise ErreurPresence("Choisissez présent (P) ou absent (A).")
    matricule = str(matricule or "").strip()
    _eleve_de_la_classe(conn, cc, matricule)
    avant = conn.execute("SELECT STATUT FROM PRESENCE_ELEVE WHERE ID_CC = ? AND DATE_COURS = ? AND MATRICULE = ?",
                         (cc["ID_CC"], d.isoformat(), matricule)).fetchone()
    if (avant["STATUT"] if avant else "") == statut:
        return {"statut": statut}
    with conn:
        if statut:
            conn.execute("INSERT INTO PRESENCE_ELEVE (ID_CC, DATE_COURS, MATRICULE, STATUT, DATE_MODIF, MODIFIE_PAR) VALUES (?,?,?,?,?,?) "
                         "ON CONFLICT (ID_CC, DATE_COURS, MATRICULE) DO UPDATE SET STATUT = excluded.STATUT, "
                         "DATE_MODIF = excluded.DATE_MODIF, MODIFIE_PAR = excluded.MODIFIE_PAR",
                         (cc["ID_CC"], d.isoformat(), matricule, statut, iso(maintenant()), session.login))
        else:
            conn.execute("DELETE FROM PRESENCE_ELEVE WHERE ID_CC = ? AND DATE_COURS = ? AND MATRICULE = ?",
                         (cc["ID_CC"], d.isoformat(), matricule))
        journaliser(conn, session.id_user, session.login, "PRESENCE_ELEVE_MARQUEE",
                    f"{cc['ANNEESCO']} | {cc['DESI_CLASSE']} | {cc['COURS']} | {_fr(d)} | {matricule} | "
                    f"{STATUTS.get(statut, 'pointage retiré')}")
    return {"statut": statut}


def tous_presents(conn, session, id_cc, jour_texte="") -> dict:
    """Pointe présents tous les élèves pas encore pointés (ceux déjà pointés absents restent absents)."""
    prof, cc = notes._cc(conn, session, id_cc, ecriture=True)
    d = _jour(conn, cc["ANNEESCO"], jour_texte)
    deja = {l[0] for l in conn.execute("SELECT MATRICULE FROM PRESENCE_ELEVE WHERE ID_CC = ? AND DATE_COURS = ?", (cc["ID_CC"], d.isoformat()))}
    cibles = [e["MATRICULE"] for e in notes._eleves(conn, cc) if e["MATRICULE"] not in deja]
    if cibles:
        with conn:
            for m in cibles:
                conn.execute("INSERT INTO PRESENCE_ELEVE (ID_CC, DATE_COURS, MATRICULE, STATUT, DATE_MODIF, MODIFIE_PAR) VALUES (?,?,?,?,?,?)",
                             (cc["ID_CC"], d.isoformat(), m, "P", iso(maintenant()), session.login))
            journaliser(conn, session.id_user, session.login, "PRESENCE_ELEVE_TOUS",
                        f"{cc['ANNEESCO']} | {cc['DESI_CLASSE']} | {cc['COURS']} | {_fr(d)} | {len(cibles)} élèves présents")
    return {"faits": len(cibles)}


def historique(conn, session, id_cc) -> dict:
    """Présences de son cours dans une classe : les jours pointés (les plus récents d'abord, 60 au plus) et, pour chaque élève,
    son pointage de chaque jour, ses totaux et son taux de présence à ce cours."""
    prof, cc = notes._cc(conn, session, id_cc)
    jours = [l[0] for l in conn.execute("SELECT DISTINCT DATE_COURS FROM PRESENCE_ELEVE WHERE ID_CC = ? ORDER BY DATE_COURS DESC LIMIT ?",
                                        (cc["ID_CC"], MAX_JOURS_HISTORIQUE))]
    pointage = {(l["MATRICULE"], l["DATE_COURS"]): l["STATUT"] for l in conn.execute(
        "SELECT MATRICULE, DATE_COURS, STATUT FROM PRESENCE_ELEVE WHERE ID_CC = ?", (cc["ID_CC"],))}
    eleves = []
    for e in notes._eleves(conn, cc):
        p = sum(1 for j in jours if pointage.get((e["MATRICULE"], j)) == "P")
        a = sum(1 for j in jours if pointage.get((e["MATRICULE"], j)) == "A")
        eleves.append({"matricule": e["MATRICULE"], "nom_complet": donnees.nom_complet(e), "presences": p, "absences": a,
                       "taux": round(100 * p / (p + a), 1) if p + a else None,
                       "codes": [pointage.get((e["MATRICULE"], j), "") for j in jours]})
    return {"id_cc": cc["ID_CC"], "cours": cc["COURS"], "classe": cc["DESI_CLASSE"], "annee": cc["ANNEESCO"],
            "jours": [_fr(j) for j in jours], "eleves": eleves}


# ================================================================== directions (toutes les classes)
MODULE_PRESENCE = "presence_eleves"


def peut_consulter(conn, session) -> bool:
    """Consultation de la présence de toutes les classes : l'Administrateur, un compte qui a le droit « Lecture » sur « Présence des
    élèves » (Directeur de discipline, Directrice des études) ou sur « Direction des études ». Droits relus dans la base à chaque appel."""
    return droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE_PRESENCE, "LECTURE") or cours.peut(conn, session, "LECTURE")


def _lecture(conn, session):
    if not peut_consulter(conn, session):
        raise PermissionError("Accès refusé : vous n'avez pas le droit « Lecture » sur le module « "
                              f"{config.MODULES_DROITS[MODULE_PRESENCE][0]} ».")


def lister_annees(conn, session) -> list:
    """[{annee, en_cours}] de la plus récente à la plus ancienne (pour choisir l'année à consulter)."""
    _lecture(conn, session)
    return [{"annee": l["ANNEESCO"], "en_cours": bool(l["EN_COURS"])} for l in conn.execute("SELECT * FROM ANNEE_SCO ORDER BY ANNEESCO DESC")]


def _classes_actives(conn) -> list:
    return [{"n_classe": l["N_CLASSE"], "designation": l["DESI_CLASSE"], "niveau": l["DESI_NIVEAU"], "option": l["DESI_OPTION"] or ""}
            for l in conn.execute("SELECT C.*, N.DESI_NIVEAU, O.DESI_OPTION FROM CLASSE C JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
                                  "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION WHERE C.ACTIF = 1 "
                                  "ORDER BY N.DESI_NIVEAU COLLATE NOCASE, C.ANNEE_ETUDE, C.DIVISION, C.DESI_CLASSE")]


def classes_du_jour(conn, session, annee, jour_texte="") -> dict:
    """Pour chaque classe de l'année : effectif, présents / absents / non renseignés pour la journée, cours pointés."""
    _lecture(conn, session)
    cours._annee(conn, annee)
    d = _jour(conn, annee, jour_texte)
    resultat = []
    for k in _classes_actives(conn):
        n_eleves = [r[0] for r in conn.execute("SELECT MATRICULE FROM INSCRIRE WHERE ANNEESCO = ? AND N_CLASSE = ?", (annee, k["n_classe"]))]
        if not n_eleves:
            continue
        j = _statuts_jour(conn, annee, k["n_classe"], d.isoformat())
        p = sum(1 for m in n_eleves if j.get(m, {}).get("statut") == "P")
        a = sum(1 for m in n_eleves if j.get(m, {}).get("statut") == "A")
        nb_cours = conn.execute("SELECT COUNT(DISTINCT PE.ID_CC) FROM PRESENCE_ELEVE PE JOIN COURS_CLASSE X ON X.ID_CC = PE.ID_CC "
                                "WHERE X.ANNEESCO = ? AND X.N_CLASSE = ? AND PE.DATE_COURS = ?", (annee, k["n_classe"], d.isoformat())).fetchone()[0]
        resultat.append({"n_classe": k["n_classe"], "classe": k["designation"], "niveau": k["niveau"], "option": k["option"],
                         "effectif": len(n_eleves), "presents": p, "absents": a, "non_renseignes": len(n_eleves) - p - a,
                         "cours_pointes": nb_cours})
    return {"annee": annee, "date": _fr(d), "classes": resultat,
            "totaux": {"effectif": sum(c["effectif"] for c in resultat), "presents": sum(c["presents"] for c in resultat),
                       "absents": sum(c["absents"] for c in resultat), "non_renseignes": sum(c["non_renseignes"] for c in resultat)}}


def eleves_de_la_classe(conn, session, annee, n_classe, jour_texte="") -> dict:
    """La liste des élèves d'une classe pour un jour : situation de la journée et détail cours par cours."""
    _lecture(conn, session)
    cours._annee(conn, annee)
    classe = cours._classe(conn, n_classe)
    d = _jour(conn, annee, jour_texte)
    detail = {}
    for l in conn.execute("SELECT PE.MATRICULE, PE.STATUT, C.LIBELLE FROM PRESENCE_ELEVE PE JOIN COURS_CLASSE X ON X.ID_CC = PE.ID_CC "
                          "JOIN COURS C ON C.ID_COURS = X.ID_COURS WHERE X.ANNEESCO = ? AND X.N_CLASSE = ? AND PE.DATE_COURS = ? "
                          "ORDER BY C.LIBELLE COLLATE NOCASE", (annee, n_classe, d.isoformat())):
        detail.setdefault(l["MATRICULE"], []).append({"cours": l["LIBELLE"], "statut": l["STATUT"]})
    jour = _statuts_jour(conn, annee, n_classe, d.isoformat())
    eleves = []
    for e in conn.execute("SELECT E.* FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE WHERE I.ANNEESCO = ? AND I.N_CLASSE = ? "
                          "ORDER BY E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE", (annee, n_classe)):
        j = jour.get(e["MATRICULE"])
        eleves.append({"matricule": e["MATRICULE"], "nom_complet": donnees.nom_complet(e), "sexe": e["SEXE"] or "",
                       "journee": j["statut"] if j else "", "manques": j["manques"] if j else [],
                       "cours": detail.get(e["MATRICULE"], [])})
    return {"annee": annee, "date": _fr(d), "classe": classe["DESI_CLASSE"], "eleves": eleves}


def recapitulatif_classe(conn, session, annee, n_classe, debut_texte, fin_texte) -> dict:
    """Jours présents / absents de chaque élève d'une classe sur une période (règle de la journée : présent à tous les cours pointés)."""
    _lecture(conn, session)
    cours._annee(conn, annee)
    classe = cours._classe(conn, n_classe)
    debut, fin = cours._date(debut_texte, "date de début"), cours._date(fin_texte, "date de fin")
    if fin < debut:
        raise ErreurPresence("La date de fin est avant la date de début.")
    par_jour = {}
    for l in conn.execute("SELECT PE.MATRICULE, PE.DATE_COURS, PE.STATUT FROM PRESENCE_ELEVE PE JOIN COURS_CLASSE X ON X.ID_CC = PE.ID_CC "
                          "WHERE X.ANNEESCO = ? AND X.N_CLASSE = ? AND PE.DATE_COURS BETWEEN ? AND ?",
                          (annee, n_classe, debut.isoformat(), fin.isoformat())):
        par_jour.setdefault((l["MATRICULE"], l["DATE_COURS"]), "P")
        if l["STATUT"] == "A":
            par_jour[(l["MATRICULE"], l["DATE_COURS"])] = "A"
    jours_pointes = {j for (_m, j) in par_jour}
    eleves = []
    for e in conn.execute("SELECT E.* FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE WHERE I.ANNEESCO = ? AND I.N_CLASSE = ? "
                          "ORDER BY E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE", (annee, n_classe)):
        p = sum(1 for (m, _j), s in par_jour.items() if m == e["MATRICULE"] and s == "P")
        a = sum(1 for (m, _j), s in par_jour.items() if m == e["MATRICULE"] and s == "A")
        eleves.append({"matricule": e["MATRICULE"], "nom_complet": donnees.nom_complet(e), "jours_presents": p, "jours_absents": a,
                       "taux": round(100 * p / (p + a), 1) if p + a else None})
    return {"annee": annee, "classe": classe["DESI_CLASSE"], "debut": _fr(debut), "fin": _fr(fin),
            "jours_pointes": len(jours_pointes), "eleves": eleves}

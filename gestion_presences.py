"""Direction de discipline, 1re fonctionnalité « Gestion des présences » (secondaire et humanitaire), sans interface graphique : testable seule.

Le Directeur de discipline :
  1. CONSULTE les présences saisies par les professeurs (par classe et par jour : cours pointé, professeur, présents, absents, qui a saisi et quand) ;
  2. VÉRIFIE la présence journalière des élèves (par classe : présents, absents, non renseignés, ce qui reste à vérifier) ;
  3. CONFIRME ou CORRIGE le statut de présence d'un élève pour un jour, selon les informations dont il dispose ;
  4. CONSULTE les absences par classe (sur une période) et par élève.

Règles
- Les pointages des professeurs (PRESENCE_ELEVE) ne sont JAMAIS modifiés ici. La Direction ajoute une DÉCISION (table PRESENCE_DECISION) qui se
  superpose : le « statut retenu » d'un élève pour un jour est celui de la décision active, sinon celui qui découle des pointages des professeurs.
- Règle de la journée (présence_eleves.py) : présent pour la journée seulement s'il est présent à TOUS les cours pointés ce jour-là ; absent à un
  seul cours pointé = absent pour la journée. Aucun cours pointé : « non renseigné » (l'absence n'est jamais devinée).
- CONFIRMER : la Direction valide le statut tiré des pointages (il faut donc que les professeurs aient pointé l'élève ce jour-là).
  CORRIGER : la Direction retient un autre statut (présent ou absent), avec un MOTIF obligatoire ; elle peut aussi renseigner un jour que personne n'a
  pointé. Une correction identique au statut des pointages est refusée : c'est une confirmation.
- Une confirmation est un constat à un moment donné : si un professeur modifie son pointage ensuite, la confirmation n'est plus valable (le statut
  retenu redevient celui des pointages et l'élève est signalé « à revoir »). Une correction reste en place, mais elle est signalée « pointage modifié depuis ».
- Une nouvelle décision remplace la précédente, une annulation ramène au statut des pointages : dans les deux cas l'ancienne décision reste dans la base
  (marquée annulée, avec qui, quand et pourquoi). Rien n'est supprimé.
- On décide seulement pour l'année en cours, un jour de classe (config.JOURS_DE_TRAVAIL, hors jours non travaillés), jamais dans le futur,
  jamais hors de l'année scolaire, pour un élève actif inscrit dans une classe du secondaire et humanitaire cette année-là.
- Les autres écrans (Préfecture, bulletins...) lisent toujours les pointages des professeurs : les décisions de cette page n'y changent rien.

Droits sur « Direction de discipline » (relus dans la base à chaque appel ; refus = PermissionError, jamais une donnée ; section secondaire et
humanitaire ouverte au compte) : Lecture = consulter, vérifier, chercher ; Ajout = confirmer, corriger, confirmer une classe ; Modification = annuler
une décision (non accordé par défaut au Directeur : à donner dans le Gestionnaire d'accès). Chaque consultation et chaque décision est inscrite au journal.
"""
from datetime import date

import config
import cours
import donnees
import droits
import presences
import sections
from database import iso, journaliser, maintenant

MODULE = "direction_discipline"
STATUTS = {"P": "Présent", "A": "Absent", "": "Non renseigné"}
GENRES = {"CONFIRME": "Confirmé", "CORRIGE": "Corrigé"}
MAX_RESULTATS = 60                      # recherche d'un élève
LONGUEUR_MOTIF = 300


class ErreurPresences(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== droits
def peut(conn, session, droit="LECTURE") -> bool:
    return (session is not None and sections.SECONDAIRE in sections.sections_de(conn, session)
            and (droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, droit)))


def exiger(conn, session, droit="LECTURE"):
    if not peut(conn, session, droit):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS[droit]} » "
                              f"sur « {config.MODULES_DROITS[MODULE][0]} » (section secondaire et humanitaire).")


# ================================================================== outils
def _fr(d) -> str:
    return (d if isinstance(d, date) else date.fromisoformat(d)).strftime("%d/%m/%Y")


def _annee(conn, annee) -> str:
    a = str(annee or "").strip() or donnees.annee_courante(conn)
    if not a or not conn.execute("SELECT 1 FROM ANNEE_SCO WHERE ANNEESCO = ?", (a,)).fetchone():
        raise ErreurPresences("Aucune année scolaire n'est définie : créez-la d'abord (Direction des études > Années).")
    return a


def _date(texte, nom) -> date:
    try:
        return cours._date(texte, nom)
    except cours.ErreurCours as ex:
        raise ErreurPresences(str(ex)) from None


def _jour(conn, annee, texte) -> date:
    """Jour consulté : aujourd'hui si vide ; jamais dans le futur ; dans l'année scolaire si ses dates sont définies."""
    t = str(texte or "").strip()
    d = _date(t, "date") if t else date.today()
    if d > date.today():
        raise ErreurPresences("Ce jour n'est pas encore arrivé.")
    c = conn.execute("SELECT DATE_DEBUT, DATE_FIN FROM ANNEE_CALENDRIER WHERE ANNEESCO = ?", (annee,)).fetchone()
    if c and not (c["DATE_DEBUT"] <= d.isoformat() <= c["DATE_FIN"]):
        raise ErreurPresences(f"Cette date est hors de l'année scolaire {annee} ({_fr(c['DATE_DEBUT'])} - {_fr(c['DATE_FIN'])}).")
    return d


def _motif(texte, obligatoire) -> str:
    m = " ".join(str(texte or "").split())
    if obligatoire and len(m) < 3:
        raise ErreurPresences("Indiquez le motif (quelques mots suffisent).")
    if len(m) > LONGUEUR_MOTIF:
        raise ErreurPresences(f"Le motif est trop long ({LONGUEUR_MOTIF} caractères au plus).")
    return m


def _tracer(conn, session, action, detail):
    journaliser(conn, session.id_user, session.login, action, detail)


def liste_annees(conn, session) -> list:
    exiger(conn, session)
    return [{"annee": l["ANNEESCO"], "en_cours": bool(l["EN_COURS"])} for l in conn.execute("SELECT * FROM ANNEE_SCO ORDER BY ANNEESCO DESC")]


def _classe(conn, n_classe) -> dict:
    try:
        n = int(n_classe)
    except (TypeError, ValueError):
        raise ErreurPresences("Classe introuvable.") from None
    l = conn.execute("SELECT C.N_CLASSE, C.DESI_CLASSE, O.DESI_OPTION FROM CLASSE C JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
                     "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION WHERE C.N_CLASSE = ? AND N.SECTION = 'SECONDAIRE'", (n,)).fetchone()
    if not l:
        raise ErreurPresences("Classe introuvable.")
    return {"n_classe": l["N_CLASSE"], "classe": l["DESI_CLASSE"], "option": l["DESI_OPTION"] or ""}


def _eleves_classe(conn, annee, n_classe) -> list:
    """Élèves ACTIFS inscrits dans la classe cette année-là, par ordre alphabétique."""
    return conn.execute("SELECT E.* FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE WHERE I.ANNEESCO = ? AND I.N_CLASSE = ? AND E.ACTIF = 1 "
                        "ORDER BY E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE, E.MATRICULE", (annee, n_classe)).fetchall()


def _inscription(conn, matricule, annee):
    """(élève, n_classe) d'un élève ACTIF inscrit cette année-là dans le secondaire et humanitaire ; PermissionError sinon."""
    e = conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = ?", (str(matricule or "").strip(),)).fetchone()
    if not e:
        raise ErreurPresences("Élève inconnu.")
    i = conn.execute("SELECT I.N_CLASSE FROM INSCRIRE I JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
                     "WHERE I.ANNEESCO = ? AND I.MATRICULE = ? AND N.SECTION = 'SECONDAIRE'", (annee, e["MATRICULE"])).fetchone()
    if not i:
        raise PermissionError("Accès refusé : cet élève n'est pas inscrit dans le secondaire et humanitaire cette année-là.")
    return e, i["N_CLASSE"]


# ================================================================== lecture des pointages et des décisions
def _pointages(conn, annee, debut, fin, n_classe=None, matricule=None) -> dict:
    """{(matricule, jour): {'statut': 'P'|'A', 'manques': [cours], 'cours': [{'cours', 'statut'}], 'pointes': n}} d'après les pointages des professeurs."""
    cond, param = ["X.ANNEESCO = ?", "PE.DATE_COURS BETWEEN ? AND ?"], [annee, debut, fin]
    if n_classe:
        cond.append("X.N_CLASSE = ?")
        param.append(int(n_classe))
    if matricule:
        cond.append("PE.MATRICULE = ?")
        param.append(matricule)
    resultat = {}
    for l in conn.execute("SELECT PE.MATRICULE, PE.DATE_COURS, PE.STATUT, C.LIBELLE FROM PRESENCE_ELEVE PE JOIN COURS_CLASSE X ON X.ID_CC = PE.ID_CC "
                          f"JOIN COURS C ON C.ID_COURS = X.ID_COURS WHERE {' AND '.join(cond)} ORDER BY C.LIBELLE COLLATE NOCASE", param):
        r = resultat.setdefault((l["MATRICULE"], l["DATE_COURS"]), {"statut": "P", "manques": [], "cours": [], "pointes": 0})
        r["pointes"] += 1
        r["cours"].append({"cours": l["LIBELLE"], "statut": l["STATUT"]})
        if l["STATUT"] == "A":
            r["statut"] = "A"
            r["manques"].append(l["LIBELLE"])
    return resultat


def _decisions(conn, annee, debut, fin, n_classe=None, matricule=None) -> dict:
    """{(matricule, jour): ligne} des décisions ACTIVES."""
    cond, param = ["ANNEESCO = ?", "DATE_JOUR BETWEEN ? AND ?", "ANNULE_LE IS NULL"], [annee, debut, fin]
    if n_classe:
        cond.append("N_CLASSE = ?")
        param.append(int(n_classe))
    if matricule:
        cond.append("MATRICULE = ?")
        param.append(matricule)
    return {(l["MATRICULE"], l["DATE_JOUR"]): l for l in conn.execute(f"SELECT * FROM PRESENCE_DECISION WHERE {' AND '.join(cond)}", param)}


def _retenu(pointage, decision) -> dict:
    """Statut retenu pour un élève et un jour, à partir de ses pointages et de la décision active.
    {'profs', 'statut', 'origine' ('PROFS' | 'CONFIRME' | 'CORRIGE' | ''), 'a_revoir', 'modifie_depuis'}."""
    profs = pointage["statut"] if pointage else ""
    r = {"profs": profs, "statut": profs, "origine": "PROFS" if profs else "", "a_revoir": False, "modifie_depuis": False}
    if decision is None:
        return r
    if decision["GENRE"] == "CONFIRME":
        if decision["STATUT_PROF"] == profs:
            r.update(statut=decision["STATUT"], origine="CONFIRME")
        else:
            r["a_revoir"] = True                      # les pointages ont changé depuis la confirmation : elle n'est plus valable
    else:
        r.update(statut=decision["STATUT"], origine="CORRIGE", modifie_depuis=decision["STATUT_PROF"] != profs)
    return r


def _decision_vue(decision):
    if decision is None:
        return None
    return {"id": decision["ID_DEC"], "genre": decision["GENRE"], "genre_libelle": GENRES[decision["GENRE"]], "statut": decision["STATUT"],
            "statut_prof": decision["STATUT_PROF"], "motif": decision["MOTIF"], "le": _fr(decision["DECIDE_LE"][:10]), "par": decision["DECIDE_PAR"]}


def classes(conn, session, annee=None) -> list:
    """Classes du secondaire et humanitaire qui ont des élèves actifs inscrits cette année : [{'n_classe', 'classe', 'option', 'designation'}]."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    return [{"n_classe": l["N_CLASSE"], "classe": l["DESI_CLASSE"], "option": l["DESI_OPTION"] or "",
             "designation": l["DESI_CLASSE"] + (f" · {l['DESI_OPTION']}" if l["DESI_OPTION"] else "")}
            for l in conn.execute("SELECT DISTINCT C.N_CLASSE, C.DESI_CLASSE, O.DESI_OPTION FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE "
                                  "JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
                                  "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION WHERE I.ANNEESCO = ? AND N.SECTION = 'SECONDAIRE' AND E.ACTIF = 1 "
                                  "ORDER BY C.DESI_CLASSE COLLATE NOCASE", (annee,))]


# ================================================================== 1 et 2. présences saisies et présence journalière
def journee(conn, session, annee=None, jour_texte="") -> dict:
    """Vérification de la présence journalière : pour chaque classe du secondaire et humanitaire, l'effectif et, pour le jour, les présents,
    absents et non renseignés (statut retenu), les cours pointés, les décisions et ce qu'il reste à vérifier."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    d = _jour(conn, annee, jour_texte)
    j = d.isoformat()
    pointages = _pointages(conn, annee, j, j)
    decisions = _decisions(conn, annee, j, j)
    classes = []
    for k in conn.execute("SELECT DISTINCT C.N_CLASSE, C.DESI_CLASSE, O.DESI_OPTION FROM INSCRIRE I JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE "
                          "JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
                          "WHERE I.ANNEESCO = ? AND N.SECTION = 'SECONDAIRE' ORDER BY C.DESI_CLASSE COLLATE NOCASE", (annee,)).fetchall():
        eleves = _eleves_classe(conn, annee, k["N_CLASSE"])
        if not eleves:
            continue
        c = {"n_classe": k["N_CLASSE"], "classe": k["DESI_CLASSE"], "option": k["DESI_OPTION"] or "", "effectif": len(eleves), "presents": 0, "absents": 0,
             "non_renseignes": 0, "confirmes": 0, "corriges": 0, "a_verifier": 0, "partiels": 0}
        for e in eleves:
            p, dec = pointages.get((e["MATRICULE"], j)), decisions.get((e["MATRICULE"], j))
            r = _retenu(p, dec)
            c[{"P": "presents", "A": "absents", "": "non_renseignes"}[r["statut"]]] += 1
            if r["origine"] == "CONFIRME":
                c["confirmes"] += 1
            elif r["origine"] == "CORRIGE":
                c["corriges"] += 1
            elif p:                                   # des pointages, mais aucune décision valable
                c["a_verifier"] += 1
            if p and p["manques"] and len(p["manques"]) < p["pointes"]:
                c["partiels"] += 1                    # absent à certains cours seulement : à vérifier
        c["cours_pointes"] = conn.execute("SELECT COUNT(DISTINCT PE.ID_CC) FROM PRESENCE_ELEVE PE JOIN COURS_CLASSE X ON X.ID_CC = PE.ID_CC "
                                          "WHERE X.ANNEESCO = ? AND X.N_CLASSE = ? AND PE.DATE_COURS = ?", (annee, k["N_CLASSE"], j)).fetchone()[0]
        classes.append(c)
    totaux = {cle: sum(c[cle] for c in classes) for cle in ("effectif", "presents", "absents", "non_renseignes", "confirmes", "corriges", "a_verifier", "partiels")}
    with conn:
        _tracer(conn, session, "GESTION_PRESENCES_CONSULTEE", f"journée {_fr(d)} | {annee}")
    return {"annee": annee, "date": _fr(d), "jour": j, "classes": classes, "totaux": totaux, "annee_en_cours": annee == donnees.annee_courante(conn)}


def classe_du_jour(conn, session, annee, n_classe, jour_texte="") -> dict:
    """Une classe pour un jour : les saisies des professeurs (un cours par ligne) et la situation de chaque élève (pointages, décision, statut retenu)."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    k = _classe(conn, n_classe)
    d = _jour(conn, annee, jour_texte)
    j = d.isoformat()
    eleves = _eleves_classe(conn, annee, k["n_classe"])
    pointages = _pointages(conn, annee, j, j, k["n_classe"])
    decisions = _decisions(conn, annee, j, j, k["n_classe"])
    saisies = []
    for l in conn.execute(
            "SELECT X.ID_CC, C.LIBELLE, P.NOM, P.POSTNOM, P.PRENOM, COUNT(*) AS N, SUM(CASE WHEN PE.STATUT = 'P' THEN 1 ELSE 0 END) AS PRESENTS, SUM(CASE WHEN PE.STATUT = 'A' THEN 1 ELSE 0 END) AS ABSENTS, "
            "       MAX(PE.DATE_MODIF) AS DERNIERE, MIN(PE.MODIFIE_PAR) AS PAR "
            "FROM PRESENCE_ELEVE PE JOIN COURS_CLASSE X ON X.ID_CC = PE.ID_CC JOIN COURS C ON C.ID_COURS = X.ID_COURS "
            "LEFT JOIN PERSONNEL P ON P.MATRICULE = X.MATRICULE_PROF WHERE X.ANNEESCO = ? AND X.N_CLASSE = ? AND PE.DATE_COURS = ? "
            "GROUP BY X.ID_CC, C.LIBELLE, P.NOM, P.POSTNOM, P.PRENOM ORDER BY C.LIBELLE COLLATE NOCASE", (annee, k["n_classe"], j)):
        saisies.append({"cours": l["LIBELLE"], "professeur": donnees.nom_complet(l) if l["NOM"] else "Sans professeur",
                        "pointes": l["N"], "presents": l["PRESENTS"], "absents": l["ABSENTS"], "non_pointes": max(len(eleves) - l["N"], 0),
                        "par": l["PAR"] or "", "le": (_fr(l["DERNIERE"][:10]) + " " + l["DERNIERE"][11:16]) if l["DERNIERE"] else ""})
    lignes = []
    for e in eleves:
        p, dec = pointages.get((e["MATRICULE"], j)), decisions.get((e["MATRICULE"], j))
        r = _retenu(p, dec)
        lignes.append({"matricule": e["MATRICULE"], "nom_complet": donnees.nom_complet(e), "sexe": e["SEXE"] or "",
                       "cours": p["cours"] if p else [], "manques": p["manques"] if p else [], "pointes": p["pointes"] if p else 0,
                       "partiel": bool(p and p["manques"] and len(p["manques"]) < p["pointes"]),
                       "profs": r["profs"], "statut": r["statut"], "origine": r["origine"], "a_revoir": r["a_revoir"],
                       "modifie_depuis": r["modifie_depuis"], "decision": _decision_vue(dec)})
    resume = {"effectif": len(lignes), "presents": sum(1 for x in lignes if x["statut"] == "P"), "absents": sum(1 for x in lignes if x["statut"] == "A"),
              "non_renseignes": sum(1 for x in lignes if not x["statut"]),
              "a_verifier": sum(1 for x in lignes if x["pointes"] and x["origine"] not in ("CONFIRME", "CORRIGE"))}
    with conn:
        _tracer(conn, session, "GESTION_PRESENCES_CONSULTEE", f"classe {k['classe']} | {_fr(d)} | {annee}")
    return {"annee": annee, "date": _fr(d), "jour": j, "classe": k["classe"], "n_classe": k["n_classe"], "option": k["option"], "saisies": saisies,
            "eleves": lignes, "resume": resume, "modifiable": annee == donnees.annee_courante(conn) and presences.jour_de_travail(conn, d)}


# ================================================================== 3. confirmer ou corriger
def _verifier_jour(conn, annee, jour_texte) -> date:
    if annee != donnees.annee_courante(conn):
        raise ErreurPresences(f"On ne confirme ni ne corrige que les présences de l'année en cours ({donnees.annee_courante(conn)}).")
    d = _jour(conn, annee, jour_texte)
    if not presences.jour_de_travail(conn, d):
        raise ErreurPresences(f"Le {_fr(d)} n'est pas un jour de classe.")
    return d


def _poser(conn, session, annee, e, n_classe, d, statut, genre, motif) -> bool:
    """Écrit la décision (sans valider la transaction). False si la décision active est déjà identique."""
    j = d.isoformat()
    pointage = _pointages(conn, annee, j, j, n_classe, e["MATRICULE"]).get((e["MATRICULE"], j))
    profs = pointage["statut"] if pointage else ""
    actuelle = _decisions(conn, annee, j, j, n_classe, e["MATRICULE"]).get((e["MATRICULE"], j))
    if actuelle is not None and (actuelle["GENRE"], actuelle["STATUT"], actuelle["STATUT_PROF"]) == (genre, statut, profs):
        return False
    maintenant_ = iso(maintenant())
    if actuelle is not None:
        conn.execute("UPDATE PRESENCE_DECISION SET ANNULE_LE = ?, ANNULE_PAR = ?, MOTIF_ANNULATION = ? WHERE ID_DEC = ?",
                     (maintenant_, session.login, "Remplacée par une nouvelle décision", actuelle["ID_DEC"]))
    conn.execute("INSERT INTO PRESENCE_DECISION (ANNEESCO, MATRICULE, N_CLASSE, DATE_JOUR, STATUT_PROF, STATUT, GENRE, MOTIF, DECIDE_LE, DECIDE_PAR) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?)", (annee, e["MATRICULE"], n_classe, j, profs, statut, genre, motif, maintenant_, session.login))
    return True


def _cible(conn, session, annee, matricule, jour_texte):
    exiger(conn, session, "AJOUT")
    annee = _annee(conn, annee)
    d = _verifier_jour(conn, annee, jour_texte)
    e, n_classe = _inscription(conn, matricule, annee)
    if not e["ACTIF"]:
        raise ErreurPresences("Cet élève est désactivé : sa présence ne peut plus être modifiée.")
    return annee, d, e, n_classe


def confirmer(conn, session, annee, matricule, jour_texte) -> dict:
    """La Direction confirme le statut tiré des pointages des professeurs (droit Ajout). Il faut que l'élève ait été pointé ce jour-là."""
    annee, d, e, n_classe = _cible(conn, session, annee, matricule, jour_texte)
    j = d.isoformat()
    pointage = _pointages(conn, annee, j, j, n_classe, e["MATRICULE"]).get((e["MATRICULE"], j))
    if not pointage:
        raise ErreurPresences("Aucun professeur n'a pointé cet élève ce jour-là : il n'y a rien à confirmer. Utilisez « Corriger » pour le renseigner.")
    with conn:
        change = _poser(conn, session, annee, e, n_classe, d, pointage["statut"], "CONFIRME", "")
        if change:
            _tracer(conn, session, "PRESENCE_JOUR_CONFIRMEE", f"{annee} | {_fr(d)} | {e['MATRICULE']} | {donnees.nom_complet(e)} | {STATUTS[pointage['statut']]}")
    return {"matricule": e["MATRICULE"], "statut": pointage["statut"], "change": change}


def corriger(conn, session, annee, matricule, jour_texte, statut, motif) -> dict:
    """La Direction retient un autre statut que celui des pointages, ou renseigne un jour non pointé (droit Ajout ; motif obligatoire)."""
    annee, d, e, n_classe = _cible(conn, session, annee, matricule, jour_texte)
    statut = str(statut or "").strip().upper()
    if statut not in ("P", "A"):
        raise ErreurPresences("Choisissez présent ou absent.")
    motif = _motif(motif, True)
    j = d.isoformat()
    pointage = _pointages(conn, annee, j, j, n_classe, e["MATRICULE"]).get((e["MATRICULE"], j))
    profs = pointage["statut"] if pointage else ""
    if statut == profs:
        raise ErreurPresences("Ce statut est déjà celui des pointages des professeurs : utilisez « Confirmer ».")
    with conn:
        change = _poser(conn, session, annee, e, n_classe, d, statut, "CORRIGE", motif)
        if change:
            _tracer(conn, session, "PRESENCE_JOUR_CORRIGEE",
                    f"{annee} | {_fr(d)} | {e['MATRICULE']} | {donnees.nom_complet(e)} | {STATUTS[profs]} -> {STATUTS[statut]} | {motif}")
    return {"matricule": e["MATRICULE"], "statut": statut, "change": change}


def confirmer_classe(conn, session, annee, n_classe, jour_texte) -> dict:
    """Confirme, pour une classe et un jour, tous les élèves pointés par les professeurs qui n'ont pas encore de décision valable (droit Ajout).
    Les élèves non pointés et ceux dont la décision est valable (confirmée, ou corrigée) sont laissés tels quels."""
    exiger(conn, session, "AJOUT")
    annee = _annee(conn, annee)
    k = _classe(conn, n_classe)
    d = _verifier_jour(conn, annee, jour_texte)
    j = d.isoformat()
    pointages = _pointages(conn, annee, j, j, k["n_classe"])
    decisions = _decisions(conn, annee, j, j, k["n_classe"])
    faits = 0
    with conn:
        for e in _eleves_classe(conn, annee, k["n_classe"]):
            p, dec = pointages.get((e["MATRICULE"], j)), decisions.get((e["MATRICULE"], j))
            if not p or _retenu(p, dec)["origine"] in ("CONFIRME", "CORRIGE"):
                continue
            faits += _poser(conn, session, annee, e, k["n_classe"], d, p["statut"], "CONFIRME", "")
        if faits:
            _tracer(conn, session, "PRESENCE_CLASSE_CONFIRMEE", f"{annee} | {k['classe']} | {_fr(d)} | {faits} élève(s)")
    return {"faits": faits}


def annuler(conn, session, id_dec, motif) -> dict:
    """Annule une décision active : le statut retenu redevient celui des pointages (droit Modification ; motif obligatoire). La décision reste dans la base."""
    exiger(conn, session, "MODIFICATION")
    try:
        id_dec = int(id_dec)
    except (TypeError, ValueError):
        raise ErreurPresences("Décision introuvable.") from None
    dec = conn.execute("SELECT * FROM PRESENCE_DECISION WHERE ID_DEC = ?", (id_dec,)).fetchone()
    if not dec or dec["ANNULE_LE"]:
        raise ErreurPresences("Décision introuvable ou déjà annulée.")
    if dec["ANNEESCO"] != donnees.annee_courante(conn):
        raise ErreurPresences("On n'annule que les décisions de l'année en cours.")
    motif = _motif(motif, True)
    e = conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = ?", (dec["MATRICULE"],)).fetchone()
    with conn:
        conn.execute("UPDATE PRESENCE_DECISION SET ANNULE_LE = ?, ANNULE_PAR = ?, MOTIF_ANNULATION = ? WHERE ID_DEC = ?",
                     (iso(maintenant()), session.login, motif, id_dec))
        _tracer(conn, session, "PRESENCE_JOUR_ANNULEE", f"{dec['ANNEESCO']} | {_fr(dec['DATE_JOUR'])} | {dec['MATRICULE']} | {donnees.nom_complet(e)} | "
                f"{GENRES[dec['GENRE']]} -> annulée | {motif}")
    return {"matricule": dec["MATRICULE"], "jour": dec["DATE_JOUR"]}


# ================================================================== 4. absences par classe et par élève
def _periode(conn, annee, debut_texte, fin_texte) -> tuple:
    """(début, fin) : par défaut, du début de l'année scolaire (ou du premier pointage) à aujourd'hui (ou à la fin de l'année)."""
    c = conn.execute("SELECT DATE_DEBUT, DATE_FIN FROM ANNEE_CALENDRIER WHERE ANNEESCO = ?", (annee,)).fetchone()
    aujourdhui = date.today()
    if str(debut_texte or "").strip():
        debut = _date(debut_texte, "date de début")
    else:
        premier = conn.execute("SELECT MIN(PE.DATE_COURS) FROM PRESENCE_ELEVE PE JOIN COURS_CLASSE X ON X.ID_CC = PE.ID_CC WHERE X.ANNEESCO = ?", (annee,)).fetchone()[0]
        debut = date.fromisoformat(c["DATE_DEBUT"]) if c else (date.fromisoformat(premier) if premier else aujourdhui)
    if str(fin_texte or "").strip():
        fin = _date(fin_texte, "date de fin")
    else:
        fin = min(aujourdhui, date.fromisoformat(c["DATE_FIN"])) if c else aujourdhui
    if fin < debut:
        raise ErreurPresences("La date de fin est avant la date de début.")
    return debut, fin


def _jours_retenus(pointages, decisions) -> dict:
    """{(matricule, jour): retenu} pour tous les couples qui ont un pointage ou une décision."""
    return {cle: _retenu(pointages.get(cle), decisions.get(cle)) for cle in set(pointages) | set(decisions)}


def absences_classe(conn, session, annee, n_classe, debut_texte="", fin_texte="") -> dict:
    """Absences d'une classe sur une période : pour chaque élève, jours présents et absents (statut retenu), taux de présence, jours corrigés."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    k = _classe(conn, n_classe)
    debut, fin = _periode(conn, annee, debut_texte, fin_texte)
    pointages = _pointages(conn, annee, debut.isoformat(), fin.isoformat(), k["n_classe"])
    decisions = _decisions(conn, annee, debut.isoformat(), fin.isoformat(), k["n_classe"])
    retenus = _jours_retenus(pointages, decisions)
    eleves = []
    for e in _eleves_classe(conn, annee, k["n_classe"]):
        mes = {j: r for (m, j), r in retenus.items() if m == e["MATRICULE"]}
        p = sum(1 for r in mes.values() if r["statut"] == "P")
        a = sum(1 for r in mes.values() if r["statut"] == "A")
        eleves.append({"matricule": e["MATRICULE"], "nom_complet": donnees.nom_complet(e), "sexe": e["SEXE"] or "", "jours_presents": p, "jours_absents": a,
                       "taux": round(100 * p / (p + a), 1) if p + a else None,
                       "corriges": sum(1 for r in mes.values() if r["origine"] == "CORRIGE"),
                       "repetee": a >= config.SEUIL_ABSENCES_REPETEES,
                       "dates_absence": [_fr(j) for j, r in sorted(mes.items()) if r["statut"] == "A"]})
    jours_classe = {j for (_m, j) in retenus}
    with conn:
        _tracer(conn, session, "GESTION_PRESENCES_CONSULTEE", f"absences classe {k['classe']} | {_fr(debut)} - {_fr(fin)} | {annee}")
    return {"annee": annee, "classe": k["classe"], "n_classe": k["n_classe"], "option": k["option"], "debut": debut.isoformat(), "fin": fin.isoformat(),
            "debut_fr": _fr(debut), "fin_fr": _fr(fin), "jours_pointes": len(jours_classe), "eleves": eleves,
            "total_absences": sum(x["jours_absents"] for x in eleves), "seuil": config.SEUIL_ABSENCES_REPETEES}


def chercher_eleves(conn, session, annee, texte) -> dict:
    """Élèves actifs inscrits cette année dans le secondaire et humanitaire dont le nom, le postnom, le prénom ou le matricule contient `texte`."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    texte = str(texte or "").strip()
    eleves = []
    if texte:
        for e in conn.execute(
                "SELECT E.*, C.DESI_CLASSE FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE "
                "JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU WHERE I.ANNEESCO = ? AND N.SECTION = 'SECONDAIRE' AND E.ACTIF = 1 "
                "AND (E.MATRICULE LIKE ? OR E.NOM LIKE ? OR COALESCE(E.POSTNOM, '') LIKE ? OR COALESCE(E.PRENOM, '') LIKE ?) "
                "ORDER BY E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE LIMIT ?", (annee, *([f"%{texte}%"] * 4), MAX_RESULTATS + 1)):
            eleves.append({"matricule": e["MATRICULE"], "nom_complet": donnees.nom_complet(e), "classe": e["DESI_CLASSE"]})
    with conn:
        _tracer(conn, session, "GESTION_PRESENCES_CONSULTEE", f"recherche élève « {texte[:40]} » | {annee}")
    return {"annee": annee, "texte": texte, "eleves": eleves[:MAX_RESULTATS], "tronque": len(eleves) > MAX_RESULTATS}


def absences_eleve(conn, session, annee, matricule, debut_texte="", fin_texte="") -> dict:
    """Absences d'un élève sur une période : une ligne par journée d'absence (cours manqués, statut des pointages, décision de la Direction)."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    e, n_classe = _inscription(conn, matricule, annee)
    debut, fin = _periode(conn, annee, debut_texte, fin_texte)
    m = e["MATRICULE"]
    pointages = _pointages(conn, annee, debut.isoformat(), fin.isoformat(), matricule=m)
    decisions = _decisions(conn, annee, debut.isoformat(), fin.isoformat(), matricule=m)
    retenus = _jours_retenus(pointages, decisions)
    absences, presents, corriges = [], 0, 0
    for (_m, j), r in sorted(retenus.items(), key=lambda x: x[0][1], reverse=True):
        corriges += r["origine"] == "CORRIGE"
        if r["statut"] == "P":
            presents += 1
        elif r["statut"] == "A":
            p = pointages.get((m, j))
            absences.append({"date": _fr(j), "jour": j, "manques": p["manques"] if p else [], "pointes": p["pointes"] if p else 0,
                             "profs": r["profs"], "origine": r["origine"], "a_revoir": r["a_revoir"], "modifie_depuis": r["modifie_depuis"],
                             "decision": _decision_vue(decisions.get((m, j)))})
    historique = [{"le": _fr(l["DECIDE_LE"][:10]), "date": _fr(l["DATE_JOUR"]), "genre": GENRES[l["GENRE"]], "statut": STATUTS[l["STATUT"]], "motif": l["MOTIF"],
                   "par": l["DECIDE_PAR"], "annulee": bool(l["ANNULE_LE"]), "motif_annulation": l["MOTIF_ANNULATION"] or ""}
                  for l in conn.execute("SELECT * FROM PRESENCE_DECISION WHERE ANNEESCO = ? AND MATRICULE = ? AND DATE_JOUR BETWEEN ? AND ? ORDER BY ID_DEC DESC",
                                        (annee, m, debut.isoformat(), fin.isoformat()))]
    with conn:
        _tracer(conn, session, "GESTION_PRESENCES_CONSULTEE", f"absences élève {m} | {_fr(debut)} - {_fr(fin)} | {annee}")
    return {"annee": annee, "eleve": {"matricule": m, "nom_complet": donnees.nom_complet(e)}, "classe": _classe(conn, n_classe)["classe"],
            "debut": debut.isoformat(), "fin": fin.isoformat(), "debut_fr": _fr(debut), "fin_fr": _fr(fin), "jours_presents": presents,
            "jours_absents": len(absences), "jours_corriges": corriges, "taux": round(100 * presents / (presents + len(absences)), 1) if presents + len(absences) else None,
            "absences": absences, "historique": historique}

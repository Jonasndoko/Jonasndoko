"""Direction de discipline, 2e fonctionnalité « Suivi de la conduite » (secondaire et humanitaire), sans interface graphique : testable seule.

Le Directeur de discipline :
  1. CONSULTE les observations de conduite des professeurs : la cote de conduite (E, TB, B, AB, P, M) que chaque professeur donne à chaque élève pour
     une période (table CONDUITE, saisie dans l'espace des professeurs), cours par cours, et la cote retenue (même règle que le bulletin) ;
  2. AJOUTE ses propres observations disciplinaires (texte libre, positives, négatives ou neutres) ;
  3. ENREGISTRE les incidents et les comportements inappropriés (liste du règlement scolaire : config.REGLEMENT_CONDUITE, avec gravité et points) ;
  4. SUIT les mentions positives et négatives selon le règlement scolaire (félicitations, encouragements, avertissement, blâme...), avec un
     « solde de conduite » (somme des points des entrées valables de l'année) et le signalement des élèves « à suivre » ;
  5. CONSULTE l'historique de conduite de chaque élève : cotes des professeurs période par période, toutes ses entrées (annulées comprises),
     décisions disciplinaires du Préfet qui le concernent, et le résumé de chaque année scolaire.

Règles
- Les cotes des professeurs (CONDUITE) et les décisions du Préfet ne sont JAMAIS modifiées ici : elles sont seulement lues.
- Les entrées de la Direction sont dans la table CONDUITE_OBSERVATION. Le libellé, la gravité et les points du règlement sont copiés dans chaque
  entrée : modifier le règlement (config.py) ne réécrit pas l'historique.
- Rien n'est supprimé. Une entrée enregistrée par erreur ou contestée est ANNULÉE avec un motif (qui, quand, pourquoi restent visibles) ; elle ne
  compte plus dans le solde ni dans les chiffres.
- On enregistre seulement pour l'année en cours, à une date qui n'est pas dans le futur et qui est dans l'année scolaire (si ses dates sont définies),
  pour un élève ACTIF inscrit dans une classe du secondaire et humanitaire cette année-là.
- Genres : OBSERVATION (texte libre ; nature positive, négative ou neutre au choix ; 0 point), COMPORTEMENT et INCIDENT (négatifs ; gravité et points
  du règlement ; description obligatoire), MENTION (positive ou négative selon le règlement ; points du règlement).

Droits sur « Direction de discipline » (relus dans la base à chaque appel ; refus = PermissionError, jamais une donnée ; section secondaire et
humanitaire ouverte au compte) : Lecture = consulter ; Ajout = enregistrer une observation, un comportement, un incident ou une mention ;
Modification = annuler une entrée (non accordé par défaut au Directeur : à donner dans le Gestionnaire d'accès).
Chaque consultation et chaque opération est inscrite au journal.
"""
from datetime import date

import bulletins
import config
import cours
import donnees
import droits
import notes
import sections
from database import iso, journaliser, maintenant

MODULE = "direction_discipline"
GENRES = {"OBSERVATION": "Observation disciplinaire", "COMPORTEMENT": "Comportement inapproprié", "INCIDENT": "Incident", "MENTION": "Mention"}
NATURES = {"POSITIF": "Positive", "NEGATIF": "Négative", "NEUTRE": "Neutre"}
GRAVITES = config.LIBELLE_GRAVITES
LONGUEUR_DESCRIPTION = 1000
LONGUEUR_LIEU = 100
LONGUEUR_MESURE = 300
LONGUEUR_MOTIF = 300
MAX_RESULTATS = 60
MAX_REGISTRE = 200
COTES_A_SURVEILLER = ("P", "M")           # cotes de conduite qui attirent l'attention (passable, mauvaise)


class ErreurConduite(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== droits
def peut(conn, session, droit="LECTURE") -> bool:
    return (session is not None and sections.SECONDAIRE in sections.sections_de(conn, session)
            and (droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, droit)))


def exiger(conn, session, droit="LECTURE"):
    if not peut(conn, session, droit):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS[droit]} » "
                              f"sur « {config.MODULES_DROITS[MODULE][0]} » (section secondaire et humanitaire).")


# ================================================================== règlement
def reglement() -> list:
    """Le règlement scolaire (config.REGLEMENT_CONDUITE) sous forme de liste de dictionnaires, dans l'ordre de config.py."""
    return [{"code": c, "libelle": l, "genre": g, "nature": n, "gravite": gr, "gravite_libelle": GRAVITES.get(gr, ""), "points": p}
            for c, l, g, n, gr, p in config.REGLEMENT_CONDUITE]


def _article(code) -> dict:
    for a in reglement():
        if a["code"] == code:
            return a
    raise ErreurConduite("Choisissez dans la liste du règlement scolaire.")


# ================================================================== outils
def _fr(d) -> str:
    return (d if isinstance(d, date) else date.fromisoformat(d)).strftime("%d/%m/%Y")


def _annee(conn, annee) -> str:
    a = str(annee or "").strip() or donnees.annee_courante(conn)
    if not a or not conn.execute("SELECT 1 FROM ANNEE_SCO WHERE ANNEESCO = ?", (a,)).fetchone():
        raise ErreurConduite("Aucune année scolaire n'est définie : créez-la d'abord (Direction des études > Années).")
    return a


def _date(texte, nom) -> date:
    try:
        return cours._date(texte, nom)
    except cours.ErreurCours as ex:
        raise ErreurConduite(str(ex)) from None


def _date_fait(conn, annee, texte) -> date:
    """Date des faits : aujourd'hui si vide ; jamais dans le futur ; dans l'année scolaire si ses dates sont définies."""
    t = str(texte or "").strip()
    d = _date(t, "date des faits") if t else date.today()
    if d > date.today():
        raise ErreurConduite("Cette date n'est pas encore arrivée.")
    c = conn.execute("SELECT DATE_DEBUT, DATE_FIN FROM ANNEE_CALENDRIER WHERE ANNEESCO = ?", (annee,)).fetchone()
    if c and not (c["DATE_DEBUT"] <= d.isoformat() <= c["DATE_FIN"]):
        raise ErreurConduite(f"Cette date est hors de l'année scolaire {annee} ({_fr(c['DATE_DEBUT'])} - {_fr(c['DATE_FIN'])}).")
    return d


def _texte(texte, nom, maxi, obligatoire=False, mini=1) -> str:
    t = " ".join(str(texte or "").split())
    if obligatoire and len(t) < mini:
        raise ErreurConduite(f"Renseignez {nom}." if mini <= 1 else f"Renseignez {nom} (au moins {mini} caractères).")
    if len(t) > maxi:
        raise ErreurConduite(f"{nom[0].upper() + nom[1:]} est trop long ({maxi} caractères au plus).")
    return t


def _tracer(conn, session, action, detail):
    journaliser(conn, session.id_user, session.login, action, detail)


def liste_annees(conn, session) -> list:
    exiger(conn, session)
    return [{"annee": l["ANNEESCO"], "en_cours": bool(l["EN_COURS"])} for l in conn.execute("SELECT * FROM ANNEE_SCO ORDER BY ANNEESCO DESC")]


def _classe(conn, n_classe) -> dict:
    try:
        n = int(n_classe)
    except (TypeError, ValueError):
        raise ErreurConduite("Classe introuvable.") from None
    l = conn.execute("SELECT C.N_CLASSE, C.DESI_CLASSE, O.DESI_OPTION FROM CLASSE C JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
                     "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION WHERE C.N_CLASSE = ? AND N.SECTION = 'SECONDAIRE'", (n,)).fetchone()
    if not l:
        raise ErreurConduite("Classe introuvable.")
    return {"n_classe": l["N_CLASSE"], "classe": l["DESI_CLASSE"], "option": l["DESI_OPTION"] or ""}


def _eleves_classe(conn, annee, n_classe) -> list:
    """Élèves ACTIFS inscrits dans la classe cette année-là, par ordre alphabétique."""
    return conn.execute("SELECT E.* FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE WHERE I.ANNEESCO = ? AND I.N_CLASSE = ? AND E.ACTIF = 1 "
                        "ORDER BY E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE, E.MATRICULE", (annee, n_classe)).fetchall()


def _eleve_secondaire(conn, matricule):
    """L'élève, s'il existe et a au moins une inscription dans le secondaire et humanitaire ; sinon ErreurConduite / PermissionError."""
    e = conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = ?", (str(matricule or "").strip(),)).fetchone()
    if not e:
        raise ErreurConduite("Élève inconnu.")
    if not conn.execute("SELECT 1 FROM INSCRIRE I JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
                        "WHERE I.MATRICULE = ? AND N.SECTION = 'SECONDAIRE'", (e["MATRICULE"],)).fetchone():
        raise PermissionError("Accès refusé : cet élève n'est pas du secondaire et humanitaire.")
    return e


def _inscription(conn, e, annee):
    """N° de classe d'un élève cette année-là dans le secondaire et humanitaire, ou None."""
    i = conn.execute("SELECT I.N_CLASSE FROM INSCRIRE I JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
                     "WHERE I.ANNEESCO = ? AND I.MATRICULE = ? AND N.SECTION = 'SECONDAIRE'", (annee, e["MATRICULE"])).fetchone()
    return i["N_CLASSE"] if i else None


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


def periodes(conn, session, annee=None) -> list:
    """Périodes du secondaire et humanitaire d'une année : [{'id_per', 'libelle', 'semestre'}]."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    return [{"id_per": p["ID_PER"], "libelle": p["LIBELLE"], "semestre": p["SEM"]}
            for p in conn.execute("SELECT P.ID_PER, P.LIBELLE, S.LIBELLE AS SEM FROM PERIODE_SCO P JOIN SEMESTRE_SCO S ON S.ID_SEM = P.ID_SEM "
                                  "WHERE S.ANNEESCO = ? AND S.SECTION = 'SECONDAIRE' ORDER BY P.DATE_DEBUT, P.ID_PER", (annee,))]


# ================================================================== lecture des entrées
def _vue_entree(l) -> dict:
    return {"id": l["ID_OBS"], "annee": l["ANNEESCO"], "matricule": l["MATRICULE"], "date": _fr(l["DATE_FAIT"]), "jour": l["DATE_FAIT"],
            "genre": l["GENRE"], "genre_libelle": GENRES[l["GENRE"]], "code": l["CODE"], "libelle": l["LIBELLE"],
            "nature": l["NATURE"], "nature_libelle": NATURES[l["NATURE"]], "gravite": l["GRAVITE"], "gravite_libelle": GRAVITES.get(l["GRAVITE"], ""),
            "points": l["POINTS"], "lieu": l["LIEU"], "description": l["DESCRIPTION"], "mesure": l["MESURE"],
            "par": l["ENREGISTRE_PAR"], "le": _fr(l["ENREGISTRE_LE"][:10]), "annulee": bool(l["ANNULE_LE"]),
            "annulee_par": l["ANNULE_PAR"] or "", "annulee_le": _fr(l["ANNULE_LE"][:10]) if l["ANNULE_LE"] else "",
            "motif_annulation": l["MOTIF_ANNULATION"] or ""}


def _totaux(entrees) -> dict:
    """Chiffres d'une liste d'entrées (vues) : seules les entrées valables (non annulées) comptent."""
    v = [x for x in entrees if not x["annulee"]]
    neg = sum(1 for x in v if x["nature"] == "NEGATIF")
    solde = sum(x["points"] for x in v)
    return {"observations": sum(1 for x in v if x["genre"] == "OBSERVATION"), "comportements": sum(1 for x in v if x["genre"] == "COMPORTEMENT"),
            "incidents": sum(1 for x in v if x["genre"] == "INCIDENT"),
            "mentions_positives": sum(1 for x in v if x["genre"] == "MENTION" and x["nature"] == "POSITIF"),
            "mentions_negatives": sum(1 for x in v if x["genre"] == "MENTION" and x["nature"] == "NEGATIF"),
            "negatives": neg, "positives": sum(1 for x in v if x["nature"] == "POSITIF"), "annulees": len(entrees) - len(v), "solde": solde,
            "a_suivre": solde <= config.SEUIL_SOLDE_CONDUITE or neg >= config.SEUIL_ENTREES_NEGATIVES}


def _entrees(conn, annee, n_classe=None, matricule=None, debut=None, fin=None) -> list:
    cond, param = ["ANNEESCO = ?"], [annee]
    if n_classe:
        cond.append("N_CLASSE = ?")
        param.append(int(n_classe))
    if matricule:
        cond.append("MATRICULE = ?")
        param.append(matricule)
    if debut:
        cond.append("DATE_FAIT >= ?")
        param.append(debut)
    if fin:
        cond.append("DATE_FAIT <= ?")
        param.append(fin)
    return [_vue_entree(l) for l in conn.execute(f"SELECT * FROM CONDUITE_OBSERVATION WHERE {' AND '.join(cond)} ORDER BY DATE_FAIT DESC, ID_OBS DESC", param)]


def _cotes(conn, annee, n_classe=None, matricule=None) -> list:
    """Lignes de la table CONDUITE (cotes des professeurs) pour l'année, avec le cours, le professeur et la période."""
    cond, param = ["X.ANNEESCO = ?"], [annee]
    if n_classe:
        cond.append("X.N_CLASSE = ?")
        param.append(int(n_classe))
    if matricule:
        cond.append("C.MATRICULE = ?")
        param.append(matricule)
    return conn.execute("SELECT C.ID_CC, C.ID_PER, C.MATRICULE, C.COTE, C.DATE_MODIF, K.LIBELLE AS COURS, P.NOM, P.POSTNOM, P.PRENOM "
                        "FROM CONDUITE C JOIN COURS_CLASSE X ON X.ID_CC = C.ID_CC JOIN COURS K ON K.ID_COURS = X.ID_COURS "
                        f"LEFT JOIN PERSONNEL P ON P.MATRICULE = X.MATRICULE_PROF WHERE {' AND '.join(cond)} ORDER BY K.LIBELLE COLLATE NOCASE", param).fetchall()


def _libelle_cote(code) -> str:
    return dict(notes.COTES_CONDUITE).get(code, "")


# ================================================================== 1. observations de conduite des professeurs
def observations_professeurs(conn, session, annee, n_classe, id_per="") -> dict:
    """Cotes de conduite données par les professeurs à une classe. Sans période : un tableau élèves × périodes (cote retenue). Avec une période :
    un tableau élèves × cours (la cote de chaque professeur) et la cote retenue (la plus fréquente ; à égalité, la plus faible, comme le bulletin)."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    k = _classe(conn, n_classe)
    pers = periodes(conn, session, annee)
    id_per = int(id_per) if str(id_per or "").strip().isdigit() else None
    per = next((p for p in pers if p["id_per"] == id_per), None) if id_per else None
    if id_per and per is None:
        raise ErreurConduite("Période introuvable.")
    eleves = _eleves_classe(conn, annee, k["n_classe"])
    lignes_cotes = _cotes(conn, annee, k["n_classe"])
    cours_classe = conn.execute("SELECT X.ID_CC, K.LIBELLE, P.NOM, P.POSTNOM, P.PRENOM FROM COURS_CLASSE X JOIN COURS K ON K.ID_COURS = X.ID_COURS "
                                "LEFT JOIN PERSONNEL P ON P.MATRICULE = X.MATRICULE_PROF WHERE X.ANNEESCO = ? AND X.N_CLASSE = ? "
                                "ORDER BY K.LIBELLE COLLATE NOCASE", (annee, k["n_classe"])).fetchall()
    cours_vues = [{"id_cc": c["ID_CC"], "cours": c["LIBELLE"], "professeur": donnees.nom_complet(c) if c["NOM"] else "Sans professeur"} for c in cours_classe]
    par_eleve_per = {}                                       # (matricule, id_per) -> [cotes]
    par_eleve_cc = {}                                        # (matricule, id_cc) -> cote (période choisie)
    for l in lignes_cotes:
        par_eleve_per.setdefault((l["MATRICULE"], l["ID_PER"]), []).append(l["COTE"])
        if id_per and l["ID_PER"] == id_per:
            par_eleve_cc[(l["MATRICULE"], l["ID_CC"])] = l["COTE"]
    lignes = []
    for e in eleves:
        m = e["MATRICULE"]
        ligne = {"matricule": m, "nom_complet": donnees.nom_complet(e), "sexe": e["SEXE"] or ""}
        if id_per:
            cotes = [par_eleve_cc.get((m, c["id_cc"]), "") for c in cours_vues]
            retenue = bulletins._conduite_dominante([c for c in cotes if c])
            ligne.update(cotes=cotes, nb_cotes=sum(1 for c in cotes if c), retenue=retenue, retenue_libelle=_libelle_cote(retenue),
                         a_surveiller=any(c in COTES_A_SURVEILLER for c in cotes))
        else:
            parper = [bulletins._conduite_dominante(par_eleve_per.get((m, p["id_per"]), [])) for p in pers]
            ligne.update(periodes=[{"cote": c, "libelle": _libelle_cote(c)} for c in parper],
                         a_surveiller=any(c in COTES_A_SURVEILLER for c in parper))
        lignes.append(ligne)
    with conn:
        _tracer(conn, session, "SUIVI_CONDUITE_CONSULTE", f"cotes des professeurs | {k['classe']} | {per['libelle'] if per else 'toutes périodes'} | {annee}")
    return {"annee": annee, "classe": k["classe"], "n_classe": k["n_classe"], "option": k["option"], "periodes": pers, "id_per": id_per,
            "periode": per["libelle"] if per else "", "cours": cours_vues, "eleves": lignes, "legende": [{"code": c, "libelle": l} for c, l in notes.COTES_CONDUITE],
            "nb_cotes_total": len(lignes_cotes), "a_surveiller": sum(1 for x in lignes if x["a_surveiller"])}


# ================================================================== 4. vue d'ensemble et registre
def apercu(conn, session, annee=None, n_classe="") -> dict:
    """Vue d'ensemble de l'année : une ligne par classe (effectif, observations, comportements, incidents, mentions, solde, élèves à suivre).
    Avec une classe : une ligne par élève, et la liste des élèves à suivre."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    entrees = _entrees(conn, annee)
    par_eleve = {}
    for x in entrees:
        par_eleve.setdefault(x["matricule"], []).append(x)
    if str(n_classe or "").strip():
        k = _classe(conn, n_classe)
        lignes = []
        for e in _eleves_classe(conn, annee, k["n_classe"]):
            t = _totaux(par_eleve.get(e["MATRICULE"], []))
            lignes.append({"matricule": e["MATRICULE"], "nom_complet": donnees.nom_complet(e), "sexe": e["SEXE"] or "", **t})
        res = {"annee": annee, "classe": k["classe"], "n_classe": k["n_classe"], "option": k["option"], "eleves": lignes,
               "totaux": _totaux([x for l in lignes for x in par_eleve.get(l["matricule"], [])]), "classes": None}
        trace = f"vue d'ensemble | {k['classe']} | {annee}"
    else:
        classes_ = []
        for c in classes(conn, session, annee):
            mats = [e["MATRICULE"] for e in _eleves_classe(conn, annee, c["n_classe"])]
            tous = [x for m in mats for x in par_eleve.get(m, [])]
            t = _totaux(tous)
            c = dict(c, effectif=len(mats), a_suivre_nb=sum(1 for m in mats if _totaux(par_eleve.get(m, []))["a_suivre"]), **t)
            classes_.append(c)
        res = {"annee": annee, "classe": "", "n_classe": "", "option": "", "eleves": None, "classes": classes_,
               "totaux": _totaux([x for c in classes_ for m in [e["MATRICULE"] for e in _eleves_classe(conn, annee, c["n_classe"])] for x in par_eleve.get(m, [])])}
        res["totaux"]["effectif"] = sum(c["effectif"] for c in classes_)
        res["totaux"]["a_suivre_nb"] = sum(c["a_suivre_nb"] for c in classes_)
        trace = f"vue d'ensemble | toutes les classes | {annee}"
    res.update(annee_en_cours=annee == donnees.annee_courante(conn), seuil_solde=config.SEUIL_SOLDE_CONDUITE, seuil_negatives=config.SEUIL_ENTREES_NEGATIVES)
    with conn:
        _tracer(conn, session, "SUIVI_CONDUITE_CONSULTE", trace)
    return res


def registre(conn, session, annee=None, n_classe="", genre="", nature="", debut_texte="", fin_texte="", annulees=False) -> dict:
    """Registre des entrées de la Direction (les plus récentes d'abord), filtrable par classe, genre, nature et période."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    k = _classe(conn, n_classe) if str(n_classe or "").strip() else None
    genre = genre if genre in GENRES else ""
    nature = nature if nature in NATURES else ""
    debut = _date(debut_texte, "date de début").isoformat() if str(debut_texte or "").strip() else None
    fin = _date(fin_texte, "date de fin").isoformat() if str(fin_texte or "").strip() else None
    if debut and fin and fin < debut:
        raise ErreurConduite("La date de fin est avant la date de début.")
    noms = {e["MATRICULE"]: e for e in conn.execute("SELECT * FROM ELEVE")}
    cl = {c["N_CLASSE"]: c["DESI_CLASSE"] for c in conn.execute("SELECT N_CLASSE, DESI_CLASSE FROM CLASSE")}
    toutes = conn.execute("SELECT ID_OBS, N_CLASSE FROM CONDUITE_OBSERVATION WHERE ANNEESCO = ?", (annee,)).fetchall()
    classe_de = {l["ID_OBS"]: l["N_CLASSE"] for l in toutes}
    liste = []
    for x in _entrees(conn, annee, k["n_classe"] if k else None, None, debut, fin):
        if (genre and x["genre"] != genre) or (nature and x["nature"] != nature) or (x["annulee"] and not annulees):
            continue
        e = noms.get(x["matricule"])
        x["nom_complet"] = donnees.nom_complet(e) if e else x["matricule"]
        x["classe"] = cl.get(classe_de.get(x["id"]), "")
        liste.append(x)
    valables = [x for x in _entrees(conn, annee, k["n_classe"] if k else None, None, debut, fin) if not x["annulee"]]
    with conn:
        _tracer(conn, session, "SUIVI_CONDUITE_CONSULTE", f"registre | {k['classe'] if k else 'toutes les classes'} | {annee}")
    return {"annee": annee, "entrees": liste[:MAX_REGISTRE], "tronque": len(liste) > MAX_REGISTRE, "total": len(liste), "totaux": _totaux(valables),
            "annee_en_cours": annee == donnees.annee_courante(conn)}


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
        _tracer(conn, session, "SUIVI_CONDUITE_CONSULTE", f"recherche élève « {texte[:40]} » | {annee}")
    return {"annee": annee, "texte": texte, "eleves": eleves[:MAX_RESULTATS], "tronque": len(eleves) > MAX_RESULTATS}


# ================================================================== 5. historique de conduite d'un élève
def historique_eleve(conn, session, matricule, annee=None) -> dict:
    """Historique de conduite d'un élève pour une année : cotes des professeurs période par période (avec le détail par cours), toutes ses entrées
    (annulées comprises, marquées), les décisions disciplinaires du Préfet qui le concernent, et le résumé de chacune de ses années scolaires."""
    exiger(conn, session)
    e = _eleve_secondaire(conn, matricule)
    m = e["MATRICULE"]
    inscriptions = [i for i in donnees.inscriptions(conn, m) if sections.section_de_classe(conn, i["N_CLASSE"]) == sections.SECONDAIRE]
    annees = sorted({i["ANNEESCO"] for i in inscriptions}, reverse=True)
    annee = str(annee or "").strip()
    if annee and annee not in annees:
        raise ErreurConduite("Cet élève n'était pas inscrit dans le secondaire et humanitaire cette année-là.")
    annee = annee or (donnees.annee_courante(conn) if donnees.annee_courante(conn) in annees else annees[0])
    n_classe = _inscription(conn, e, annee)
    classe = _classe(conn, n_classe)["classe"]
    # cotes des professeurs
    cotes = {}
    for l in _cotes(conn, annee, matricule=m):
        cotes.setdefault(l["ID_PER"], []).append({"cours": l["COURS"], "professeur": donnees.nom_complet(l) if l["NOM"] else "", "cote": l["COTE"],
                                                  "libelle": _libelle_cote(l["COTE"])})
    conduite = []
    for p in periodes(conn, session, annee):
        det = cotes.get(p["id_per"], [])
        retenue = bulletins._conduite_dominante([d["cote"] for d in det])
        conduite.append({"periode": p["libelle"], "semestre": p["semestre"], "cote": retenue, "libelle": _libelle_cote(retenue), "detail": det,
                         "a_surveiller": any(d["cote"] in COTES_A_SURVEILLER for d in det)})
    entrees = _entrees(conn, annee, matricule=m)
    # décisions disciplinaires du Préfet (lecture seule)
    decisions = [{"id": d["ID_DECISION"], "date": _fr(d["DATE_DECISION"]), "objet": d["OBJET"], "detail": d["DETAIL"], "annee": d["ANNEESCO"] or "",
                  "annulee": d["STATUT"] == "ANNULEE"}
                 for d in conn.execute("SELECT * FROM DECISION_PREFET WHERE MATRICULE = ? AND CATEGORIE = 'disciplinaire' "
                                       "ORDER BY DATE_DECISION DESC, ID_DECISION DESC LIMIT 20", (m,))]
    # résumé de chaque année
    resume = []
    for a in annees:
        t = _totaux(_entrees(conn, a, matricule=m))
        cl = _inscription(conn, e, a)
        resume.append({"annee": a, "classe": _classe(conn, cl)["classe"] if cl else "", "courante": a == annee, **t})
    with conn:
        _tracer(conn, session, "SUIVI_CONDUITE_CONSULTE", f"historique élève {m} | {annee}")
    return {"eleve": {"matricule": m, "nom_complet": donnees.nom_complet(e), "actif": bool(e["ACTIF"]), "sexe": e["SEXE"] or ""}, "annee": annee,
            "annees": annees, "classe": classe, "n_classe": n_classe, "conduite": conduite, "entrees": entrees, "totaux": _totaux(entrees),
            "decisions": decisions, "resume": resume,
            "modifiable": bool(e["ACTIF"]) and annee == donnees.annee_courante(conn), "seuil_solde": config.SEUIL_SOLDE_CONDUITE,
            "seuil_negatives": config.SEUIL_ENTREES_NEGATIVES}


# ================================================================== 2 et 3. enregistrer
def enregistrer(conn, session, annee, matricule, genre, code="", date_texte="", description="", lieu="", mesure="", nature="") -> dict:
    """Enregistre une observation disciplinaire, un comportement inapproprié, un incident ou une mention (droit Ajout).
    OBSERVATION : `nature` (POSITIF, NEGATIF ou NEUTRE), sans points. COMPORTEMENT, INCIDENT, MENTION : `code` du règlement scolaire
    (gravité, nature et points viennent du règlement). La description est obligatoire pour une observation, un comportement et un incident."""
    exiger(conn, session, "AJOUT")
    annee = _annee(conn, annee)
    if annee != donnees.annee_courante(conn):
        raise ErreurConduite(f"On n'enregistre que pour l'année en cours ({donnees.annee_courante(conn)}).")
    genre = str(genre or "").strip().upper()
    if genre not in GENRES:
        raise ErreurConduite("Choisissez ce que vous enregistrez : observation, comportement inapproprié, incident ou mention.")
    e = _eleve_secondaire(conn, matricule)
    n_classe = _inscription(conn, e, annee)
    if n_classe is None:
        raise PermissionError("Accès refusé : cet élève n'est pas inscrit dans le secondaire et humanitaire cette année.")
    if not e["ACTIF"]:
        raise ErreurConduite("Cet élève est désactivé : on n'enregistre plus rien à son sujet.")
    d = _date_fait(conn, annee, date_texte)
    lieu = _texte(lieu, "le lieu", LONGUEUR_LIEU)
    mesure = _texte(mesure, "la mesure prise", LONGUEUR_MESURE)
    if genre == "OBSERVATION":
        nature = str(nature or "").strip().upper()
        if nature not in NATURES:
            raise ErreurConduite("Indiquez si l'observation est positive, négative ou neutre.")
        description = _texte(description, "l'observation", LONGUEUR_DESCRIPTION, True, 5)
        code, libelle, gravite, points = "", GENRES["OBSERVATION"], "", 0
    else:
        a = _article(str(code or "").strip())
        if a["genre"] != genre:
            raise ErreurConduite("Ce choix du règlement ne correspond pas à ce que vous enregistrez.")
        code, libelle, nature, gravite, points = a["code"], a["libelle"], a["nature"], a["gravite"], a["points"]
        description = _texte(description, "les faits" if genre != "MENTION" else "le motif de la mention", LONGUEUR_DESCRIPTION, True, 5)
    with conn:
        cur = conn.execute("INSERT INTO CONDUITE_OBSERVATION (ANNEESCO, MATRICULE, N_CLASSE, DATE_FAIT, GENRE, CODE, LIBELLE, NATURE, GRAVITE, POINTS, LIEU, DESCRIPTION, "
                           "MESURE, ENREGISTRE_LE, ENREGISTRE_PAR) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (annee, e["MATRICULE"], n_classe, d.isoformat(), genre, code, libelle, nature, gravite, points, lieu, description, mesure,
                            iso(maintenant()), session.login))
        _tracer(conn, session, "CONDUITE_ENTREE_AJOUTEE",
                f"{annee} | {_fr(d)} | {e['MATRICULE']} | {donnees.nom_complet(e)} | {GENRES[genre]} | {libelle} | {NATURES[nature]} | {points:+d} point(s)")
    return {"id": cur.lastrowid, "matricule": e["MATRICULE"], "genre": genre, "nature": nature, "points": points}


def annuler(conn, session, id_obs, motif) -> dict:
    """Annule une entrée (droit Modification ; motif obligatoire) : elle ne compte plus, mais reste dans la base et dans l'historique."""
    exiger(conn, session, "MODIFICATION")
    try:
        id_obs = int(id_obs)
    except (TypeError, ValueError):
        raise ErreurConduite("Entrée introuvable.") from None
    x = conn.execute("SELECT * FROM CONDUITE_OBSERVATION WHERE ID_OBS = ?", (id_obs,)).fetchone()
    if not x or x["ANNULE_LE"]:
        raise ErreurConduite("Entrée introuvable ou déjà annulée.")
    if x["ANNEESCO"] != donnees.annee_courante(conn):
        raise ErreurConduite("On n'annule que les entrées de l'année en cours.")
    motif = _texte(motif, "le motif de l'annulation", LONGUEUR_MOTIF, True, 3)
    e = conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = ?", (x["MATRICULE"],)).fetchone()
    with conn:
        conn.execute("UPDATE CONDUITE_OBSERVATION SET ANNULE_LE = ?, ANNULE_PAR = ?, MOTIF_ANNULATION = ? WHERE ID_OBS = ?",
                     (iso(maintenant()), session.login, motif, id_obs))
        _tracer(conn, session, "CONDUITE_ENTREE_ANNULEE",
                f"{x['ANNEESCO']} | {_fr(x['DATE_FAIT'])} | {x['MATRICULE']} | {donnees.nom_complet(e)} | {x['LIBELLE']} | annulée | {motif}")
    return {"id": id_obs, "matricule": x["MATRICULE"]}

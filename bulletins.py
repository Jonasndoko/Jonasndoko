"""Calcul automatique et bulletins (logique ; la page web est dans page_professeur.py, les PDF dans bulletins_pdf.py).

Qui lance cette fonctionnalité ?
- Uniquement le PROFESSEUR TITULAIRE de la classe (table TITULAIRE_CLASSE). Les autres professeurs ne la voient pas : la page web
  n'affiche l'onglet « Bulletins » qu'à un titulaire, et chaque fonction ci-dessous relit le lien dans la base (jamais une donnée
  envoyée par le navigateur) et refuse (PermissionError) tout autre compte.
- Le titulaire AUTORISE les professeurs de sa classe à saisir une période ou l'examen d'un semestre (autorisations / definir_autorisation) ;
  sans son autorisation, rien ne se saisit. Il ne saisit ni ne modifie jamais les points des professeurs : il les consulte, calcule les
  résultats et imprime les bulletins de SA classe. Il ne gère pas les présences des élèves (réservées aux professeurs de chaque cours et
  consultées par le Directeur de discipline et la Directrice des études).
- La direction des études désigne le titulaire (Direction des études > Enseignants et classes) : droit « Modification » de la Direction des études
  (ou Administrateur). Un titulaire par classe et par année.

Règles de calcul (réglables dans config.py : SEUIL_REUSSITE, MENTIONS, NOTE_MANQUANTE)
- Cours, période : total = somme des points de l'élève ; maximum = somme des maxima des évaluations notées de l'élève
  (NOTE_MANQUANTE = « IGNOREE ») ou de toutes les évaluations de la période (« ZERO »). Pourcentage = total / maximum.
- Les professeurs saisissent un point par période et un point d'examen par semestre (notes.py). Période : somme des cours.
  Examen : somme des cours (points d'examen). Semestre : périodes + examen (config.EXAMEN_DANS_SEMESTRE). Année : somme des semestres. Le pourcentage est donc pondéré
  par les points (un cours sur 40 pèse deux fois un cours sur 20).
- Les pourcentages sont arrondis à 0,1 : ce qui est affiché fait foi pour le rang, la mention et le résultat.
- Rang : 1 pour le plus haut pourcentage ; à égalité, même rang (1, 2, 2, 4).
- Résultat : réussite si pourcentage >= SEUIL_REUSSITE. Tant qu'il manque les points d'une période de la portée demandée, le résultat est
  « EN ATTENTE » (jamais deviné). Mention : la plus haute de MENTIONS atteinte par un élève qui réussit.
- Conduite d'une période : la cote la plus fréquente parmi les cours de la classe ; à égalité, la plus faible.
"""
import re
from collections import Counter
from datetime import date

import config
import cours
import donnees
import droits
import notes
import sections
from database import journaliser

ErreurBulletins = notes.ErreurNotes
ERREURS = notes.ERREURS
RESERVE = "Cette fonctionnalité est réservée au professeur titulaire de la classe."
_ORDRE_CONDUITE = [c for c, _l in notes.COTES_CONDUITE]            # de la meilleure à la plus faible


# ================================================================== petits outils
def _nb(x):
    return None if x is None else notes._nombre(round(float(x), 2))


def _pct(obtenu, maximum):
    return round(100.0 * obtenu / maximum, 1) if maximum else None


def _fr(texte):
    try:
        return date.fromisoformat(str(texte)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return texte or ""


def mention_pour(pct):
    """Mention d'un pourcentage (chaîne vide sous le seuil de réussite ou sans pourcentage)."""
    if pct is None or pct < config.SEUIL_REUSSITE:
        return ""
    for seuil, libelle in config.MENTIONS:
        if pct >= seuil:
            return libelle
    return ""


def _classer(valeurs: dict) -> dict:
    """{cle: pourcentage} -> {cle: rang}, rang de compétition (1, 2, 2, 4). Les valeurs None ne sont pas classées."""
    ordre = sorted((v for v in valeurs.values() if v is not None), reverse=True)
    return {k: 1 + sum(1 for x in ordre if x > v) for k, v in valeurs.items() if v is not None}


def _conduite_dominante(cotes) -> str:
    cotes = [c for c in cotes if c in _ORDRE_CONDUITE]
    if not cotes:
        return ""
    n = Counter(cotes)
    plus = max(n.values())
    return max((c for c in n if n[c] == plus), key=_ORDRE_CONDUITE.index)      # à égalité, la plus faible


# ================================================================== titulaire de classe
def _annee_existe(conn, annee):
    if not conn.execute("SELECT 1 FROM ANNEE_SCO WHERE ANNEESCO = ?", (annee,)).fetchone():
        raise ErreurBulletins("Année scolaire introuvable.")


def _classe_ligne(conn, n_classe):
    try:
        n_classe = int(n_classe)
    except (TypeError, ValueError):
        raise ErreurBulletins("Classe introuvable.") from None
    l = conn.execute("SELECT K.*, N.DESI_NIVEAU, O.DESI_OPTION FROM CLASSE K JOIN NIVEAU N ON N.CODE_NIVEAU = K.CODE_NIVEAU "
                     "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = K.CODE_OPTION WHERE K.N_CLASSE = ?", (n_classe,)).fetchone()
    if not l:
        raise ErreurBulletins("Classe introuvable.")
    return l


def titulaire_de(conn, annee, n_classe):
    """Ligne PERSONNEL du titulaire de la classe pour l'année, ou None."""
    return conn.execute("SELECT P.* FROM TITULAIRE_CLASSE T JOIN PERSONNEL P ON P.MATRICULE = T.MATRICULE "
                        "WHERE T.ANNEESCO = ? AND T.N_CLASSE = ?", (annee, n_classe)).fetchone()


def designer_titulaire(conn, session, annee, n_classe, matricule):
    """Désigne (ou remplace) le professeur titulaire d'une classe pour une année. Droit « Modification » de la Direction des études."""
    cours.exiger(conn, session, "MODIFICATION")
    _annee_existe(conn, annee)
    k = _classe_ligne(conn, n_classe)
    agent = conn.execute("SELECT * FROM PERSONNEL WHERE MATRICULE = ?", (matricule,)).fetchone()
    if not agent:
        raise ErreurBulletins("Agent introuvable.")
    if not agent["ACTIF"]:
        raise ErreurBulletins("Le dossier de cet agent est désactivé.")
    ancien = titulaire_de(conn, annee, k["N_CLASSE"])
    with conn:
        conn.execute("INSERT INTO TITULAIRE_CLASSE (ANNEESCO, N_CLASSE, MATRICULE, DATE_ENREG, ENREGISTRE_PAR) VALUES (?,?,?,?,?) "
                     "ON CONFLICT (ANNEESCO, N_CLASSE) DO UPDATE SET MATRICULE = excluded.MATRICULE, DATE_ENREG = excluded.DATE_ENREG, "
                     "ENREGISTRE_PAR = excluded.ENREGISTRE_PAR",
                     (annee, k["N_CLASSE"], matricule, database_maintenant(), session.login))
        cours.synchroniser_primaire(conn, annee, k["N_CLASSE"], session.login)    # primaire : le titulaire enseigne tous les cours
        journaliser(conn, session.id_user, session.login, "TITULAIRE_DESIGNE",
                    f"{annee} | {k['DESI_CLASSE']} | {donnees.nom_complet(agent)}"
                    + (f" (remplace {donnees.nom_complet(ancien)})" if ancien and ancien["MATRICULE"] != matricule else ""))


def retirer_titulaire(conn, session, annee, n_classe):
    cours.exiger(conn, session, "MODIFICATION")
    k = _classe_ligne(conn, n_classe)
    ancien = titulaire_de(conn, annee, k["N_CLASSE"])
    if not ancien:
        raise ErreurBulletins("Cette classe n'a pas de titulaire pour cette année.")
    with conn:
        conn.execute("DELETE FROM TITULAIRE_CLASSE WHERE ANNEESCO = ? AND N_CLASSE = ?", (annee, k["N_CLASSE"]))
        cours.synchroniser_primaire(conn, annee, k["N_CLASSE"], session.login)
        journaliser(conn, session.id_user, session.login, "TITULAIRE_RETIRE", f"{annee} | {k['DESI_CLASSE']} | {donnees.nom_complet(ancien)}")


def lister_titulaires(conn, session, annee) -> dict:
    """{n_classe: {'matricule', 'nom_complet'}} pour l'année (consultation : droit Lecture de la Direction des études)."""
    cours.exiger(conn, session, "LECTURE")
    return {l["N_CLASSE"]: {"matricule": l["MATRICULE"], "nom_complet": donnees.nom_complet(l)}
            for l in conn.execute("SELECT T.N_CLASSE, P.* FROM TITULAIRE_CLASSE T JOIN PERSONNEL P ON P.MATRICULE = T.MATRICULE "
                                  "WHERE T.ANNEESCO = ?", (annee,))}


def _exiger_titulaire(conn, session, annee, n_classe):
    """Retourne (professeur, ligne CLASSE) si le compte connecté est le titulaire de cette classe cette année, sinon PermissionError."""
    prof = notes._professeur(conn, session)
    try:
        n_classe = int(n_classe)
    except (TypeError, ValueError):
        raise PermissionError(RESERVE) from None
    t = conn.execute("SELECT 1 FROM TITULAIRE_CLASSE WHERE ANNEESCO = ? AND N_CLASSE = ? AND MATRICULE = ?",
                     (str(annee or ""), n_classe, prof["MATRICULE"])).fetchone()
    if not t:
        raise PermissionError(RESERVE)
    return prof, _classe_ligne(conn, n_classe)


def acces(conn, session) -> dict:
    """La page web demande si elle doit montrer l'onglet « Bulletins » : oui seulement pour un titulaire (d'une classe, une année)."""
    prof = notes._professeur(conn, session)
    n = conn.execute("SELECT COUNT(*) FROM TITULAIRE_CLASSE WHERE MATRICULE = ?", (prof["MATRICULE"],)).fetchone()[0]
    c = conn.execute("SELECT COUNT(*) FROM COURS_CLASSE WHERE MATRICULE_PROF = ?", (prof["MATRICULE"],)).fetchone()[0]
    # « enseigne » : le compte a (ou a eu) des cours ; sinon la page ne lui montre ni « Points » ni « Présence » (titulaire seulement).
    return {"titulaire": n > 0, "enseigne": c > 0}


def mes_classes(conn, session, annee=None) -> dict:
    """Classes dont le professeur connecté est titulaire (année choisie) et structure de l'année."""
    prof = notes._professeur(conn, session)
    annees = [l[0] for l in conn.execute("SELECT DISTINCT ANNEESCO FROM TITULAIRE_CLASSE WHERE MATRICULE = ? ORDER BY ANNEESCO DESC",
                                         (prof["MATRICULE"],))]
    if not annees:
        raise PermissionError(RESERVE)
    courante = donnees.annee_courante(conn)
    if annee not in annees:
        annee = courante if courante in annees else annees[0]
    classes = [{"n_classe": l["N_CLASSE"], "designation": l["DESI_CLASSE"], "niveau": l["DESI_NIVEAU"], "option": l["DESI_OPTION"] or "",
                "nb_eleves": l["NB"]}
               for l in conn.execute("SELECT K.N_CLASSE, K.DESI_CLASSE, N.DESI_NIVEAU, O.DESI_OPTION, "
                                     "(SELECT COUNT(*) FROM INSCRIRE I WHERE I.ANNEESCO = T.ANNEESCO AND I.N_CLASSE = K.N_CLASSE) AS NB "
                                     "FROM TITULAIRE_CLASSE T JOIN CLASSE K ON K.N_CLASSE = T.N_CLASSE "
                                     "JOIN NIVEAU N ON N.CODE_NIVEAU = K.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = K.CODE_OPTION "
                                     "WHERE T.ANNEESCO = ? AND T.MATRICULE = ? ORDER BY N.DESI_NIVEAU COLLATE NOCASE, K.DESI_CLASSE",
                                     (annee, prof["MATRICULE"]))]
    for k in classes:
        k["section"] = sections.section_de_classe(conn, k["n_classe"])
        k["portees"] = _portees(conn, annee, k["section"])          # calendrier de la section : semestres, ou trimestres au primaire
        k["portee_defaut"] = portee_par_defaut(conn, annee, k["n_classe"])
    return {"professeur": donnees.nom_complet(prof), "annee": annee, "annees": annees, "classes": classes,
            "portees": _portees(conn, annee)}


def portee_par_defaut(conn, annee, n_classe) -> str:
    """Période, semestre ou année proposé d'abord au titulaire : la plus récente dont tous les élèves ont un résultat ; à défaut, la plus
    récente qui contient des points ; à défaut, la dernière. Chaîne vide si les périodes ne sont pas définies."""
    calc = calculer(conn, annee, n_classe)
    ordre = [p["cle"] for p in calc["portees"] if p["type"] != "examen"] or [p["cle"] for p in calc["portees"]]
    st = calc["stats"]
    for cle in reversed(ordre):
        if st[cle]["effectif"] and st[cle]["classes"] and not st[cle]["en_attente"]:
            return cle
    for cle in reversed(ordre):
        if st[cle]["classes"]:
            return cle
    return ordre[-1] if ordre else ""


# ================================================================== autorisation de saisie (période ou examen ouvert aux professeurs)
def autorisations(conn, session, annee, n_classe) -> dict:
    """Périodes et examens de l'année, avec pour chacun : ouvert ou fermé à la saisie des professeurs de la classe (titulaire seulement)."""
    prof, k = _exiger_titulaire(conn, session, annee, n_classe)
    ouvertes = notes.autorisees(conn, str(annee), k["N_CLASSE"])
    primaire = sections.est_primaire(conn, k["N_CLASSE"])            # primaire : rien à autoriser, tout est ouvert à l'unique enseignant
    elements = [] if primaire else [{"cle": p["cle"], "libelle": p["libelle"], "semestre": p["semestre"], "type": p["type"],
                                     "autorisee": p["cle"] in ouvertes}
                                    for p in _portees(conn, str(annee), sections.section_de_classe(conn, k["N_CLASSE"]))
                                    if p["type"] in ("periode", "examen")]
    return {"annee": str(annee), "classe": k["DESI_CLASSE"], "n_classe": k["N_CLASSE"], "primaire": primaire, "elements": elements}


def definir_autorisation(conn, session, annee, n_classe, cle, autorisee) -> dict:
    """Ouvre (autorisee vrai) ou ferme la saisie d'une période (« P<id> ») ou d'un examen (« X<id> ») dans la classe du titulaire.
    Fermer n'efface aucun point : les points déjà saisis sont conservés et comptent dans les résultats."""
    prof, k = _exiger_titulaire(conn, session, annee, n_classe)
    if sections.est_primaire(conn, k["N_CLASSE"]):
        raise ErreurBulletins("Au primaire, vous êtes l'unique enseignant de la classe : la saisie est toujours ouverte.")
    p = next((x for x in _portees(conn, str(annee), sections.section_de_classe(conn, k["N_CLASSE"]))
              if x["cle"] == str(cle or "") and x["type"] in ("periode", "examen")), None)
    if not p:
        raise ErreurBulletins("Choisissez une période ou un examen de cette année.")
    avant = p["cle"] in notes.autorisees(conn, str(annee), k["N_CLASSE"])
    autorisee = bool(autorisee)
    if avant != autorisee:
        with conn:
            if autorisee:
                conn.execute("INSERT INTO AUTORISATION_SAISIE (ANNEESCO, N_CLASSE, CLE, DATE_ENREG, ENREGISTRE_PAR) VALUES (?,?,?,?,?)",
                             (str(annee), k["N_CLASSE"], p["cle"], database_maintenant(), session.login))
            else:
                conn.execute("DELETE FROM AUTORISATION_SAISIE WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ?",
                             (str(annee), k["N_CLASSE"], p["cle"]))
            journaliser(conn, session.id_user, session.login, "SAISIE_AUTORISEE" if autorisee else "SAISIE_FERMEE",
                        f"{annee} | {k['DESI_CLASSE']} | {p['libelle']} | titulaire {donnees.nom_complet(prof)}")
    return {"cle": p["cle"], "autorisee": autorisee}


# ================================================================== structure de l'année : périodes, semestres, portées
def _portees(conn, annee, section=None) -> list:
    """Portées de calcul : chaque période (P<id>), l'examen de chaque semestre (X<id>), chaque semestre (S<id>) et l'année (A),
    dans l'ordre du calendrier. `section` : calendrier d'une section (primaire : 3 trimestres, secondaire et humanitaire : 2 semestres ;
    un « semestre » désigne ici l'un ou l'autre) ; sans section, tous les calendriers de l'année. L'examen d'un semestre est rangé dans la dernière période du semestre (EVALUATION de type EXA) :
    `periodes` donne les périodes concernées, `examens` les périodes (une par semestre) qui portent l'examen."""
    portees, periodes_annee, examens_annee = [], [], []
    for s in conn.execute("SELECT * FROM SEMESTRE_SCO WHERE ANNEESCO = ? AND (? IS NULL OR SECTION = ?) ORDER BY SECTION DESC, DATE_DEBUT",
                          (annee, section, section)):
        ids = []
        for p in conn.execute("SELECT * FROM PERIODE_SCO WHERE ID_SEM = ? ORDER BY DATE_DEBUT, ID_PER", (s["ID_SEM"],)):
            portees.append({"cle": f"P{p['ID_PER']}", "type": "periode", "libelle": p["LIBELLE"], "semestre": s["LIBELLE"],
                            "periodes": [p["ID_PER"]], "examens": []})
            ids.append(p["ID_PER"])
        examens = ids[-1:]
        if examens:
            portees.append({"cle": f"X{s['ID_SEM']}", "type": "examen", "libelle": f"Examen - {s['LIBELLE']}", "semestre": s["LIBELLE"],
                            "periodes": examens, "examens": examens})
        portees.append({"cle": f"S{s['ID_SEM']}", "type": "semestre", "libelle": s["LIBELLE"], "semestre": s["LIBELLE"], "periodes": ids,
                        "examens": examens})
        periodes_annee += ids
        examens_annee += examens
    if portees:
        portees.append({"cle": "A", "type": "annee", "libelle": f"Année {annee}", "semestre": "", "periodes": periodes_annee,
                        "examens": examens_annee})
    return portees


def _unites(p) -> list:
    """Cases de calcul d'une portée : (période, 'P') = points de la période ; (période, 'X') = examen rangé dans cette période."""
    if p["type"] == "periode":
        return [(i, "P") for i in p["periodes"]]
    if p["type"] == "examen":
        return [(i, "X") for i in p["periodes"]]
    return [(i, "P") for i in p["periodes"]] + ([(i, "X") for i in p["examens"]] if config.EXAMEN_DANS_SEMESTRE else [])


def _unites_exigees(p) -> list:
    """Cases dont l'absence rend la portée incomplète (l'examen seul ne bloque pas un semestre : les périodes décident)."""
    return [(i, "X") for i in p["periodes"]] if p["type"] == "examen" else [(i, "P") for i in p["periodes"]]


def colonnes_bulletin(portees, cle) -> list:
    """Portées affichées sur le bulletin demandé : une période seule ; un semestre = ses périodes puis le semestre ;
    l'année = toutes les périodes, chaque semestre, puis l'année."""
    p = next((x for x in portees if x["cle"] == cle), None)
    if not p:
        raise ErreurBulletins("Choisissez la période, le semestre ou l'année.")
    if p["type"] in ("periode", "examen"):
        return [p]
    par_cle = {x["cle"]: x for x in portees}
    if p["type"] == "semestre":
        examen = par_cle.get("X" + p["cle"][1:])
        return [par_cle[f"P{i}"] for i in p["periodes"]] + ([examen] if examen else []) + [p]
    cols = []
    for x in portees:
        if x["type"] == "periode":
            cols.append(x)
        elif x["type"] == "semestre":
            cols.append(x)
    return cols + [p]


# ================================================================== le calcul
def calculer(conn, annee, n_classe) -> dict:
    """Calcule tous les résultats d'une classe pour une année (sans contrôle d'identité : réservé aux fonctions de ce module).

    Retour : {'annee', 'classe', 'portees', 'cours', 'eleves', 'stats', 'alertes'}. Pour chaque élève :
      'cours'   : {id_cc: {cle: {'obtenu', 'max', 'pct'}}}   (cle : P<id>, S<id> ou A ; absent = rien à calculer)
      'portees' : {cle: {'obtenu', 'max', 'pct', 'rang', 'resultat', 'reussite', 'mention', 'complet', 'conduite'}}
    """
    k = _classe_ligne(conn, n_classe)
    portees = _portees(conn, annee, sections.section_de_classe(conn, n_classe))      # le calendrier de la section de la classe
    periodes = [p for p in portees if p["type"] == "periode"]
    unites = [(p["periodes"][0], "P") for p in periodes] + [(p["periodes"][0], "X") for p in portees if p["type"] == "examen"]
    dernieres = {i for i, g in unites if g == "X"}                    # périodes qui portent l'examen de leur semestre
    liste_cours = [{"id_cc": l["ID_CC"], "libelle": l["LIBELLE"], "heures": l["HEURES_SEMAINE"],
                    "max_periode": notes.maximum_periode_cours(conn, l),
                    "professeur": donnees.nom_complet(l) if l["MATRICULE"] else ""}
                   for l in conn.execute("SELECT X.ID_CC, X.N_CLASSE, X.HEURES_SEMAINE, X.MAX_PERIODE, C.LIBELLE, P.MATRICULE, P.NOM, P.POSTNOM, P.PRENOM FROM COURS_CLASSE X "
                                         "JOIN COURS C ON C.ID_COURS = X.ID_COURS LEFT JOIN PERSONNEL P ON P.MATRICULE = X.MATRICULE_PROF "
                                         "WHERE X.ANNEESCO = ? AND X.N_CLASSE = ? ORDER BY C.LIBELLE COLLATE NOCASE", (annee, k["N_CLASSE"]))]
    evals = {}                                                        # (id_cc, id_per, 'P' ou 'X') -> [evaluations]
    for e in conn.execute("SELECT E.* FROM EVALUATION E JOIN COURS_CLASSE X ON X.ID_CC = E.ID_CC WHERE X.ANNEESCO = ? AND X.N_CLASSE = ?",
                          (annee, k["N_CLASSE"])):
        genre = "X" if e["TYPE"] == "EXA" and e["ID_PER"] in dernieres else "P"
        evals.setdefault((e["ID_CC"], e["ID_PER"], genre), []).append(e)
    points = {(n["ID_EVAL"], n["MATRICULE"]): n["POINTS"] for n in conn.execute(
        "SELECT N.* FROM NOTE N JOIN EVALUATION E ON E.ID_EVAL = N.ID_EVAL JOIN COURS_CLASSE X ON X.ID_CC = E.ID_CC "
        "WHERE X.ANNEESCO = ? AND X.N_CLASSE = ?", (annee, k["N_CLASSE"]))}
    cotes = {}                                                        # (id_per, matricule) -> [cotes]
    for l in conn.execute("SELECT C.* FROM CONDUITE C JOIN COURS_CLASSE X ON X.ID_CC = C.ID_CC WHERE X.ANNEESCO = ? AND X.N_CLASSE = ?",
                          (annee, k["N_CLASSE"])):
        cotes.setdefault((l["ID_PER"], l["MATRICULE"]), []).append(l["COTE"])
    inscrits = conn.execute("SELECT E.* FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE WHERE I.ANNEESCO = ? AND I.N_CLASSE = ? "
                            "ORDER BY E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE",
                            (annee, k["N_CLASSE"])).fetchall()
    zero = config.NOTE_MANQUANTE == "ZERO"

    eleves, alertes, manquants = [], [], Counter()
    for e in inscrits:
        m = e["MATRICULE"]
        cellules = {}                                                 # id_cc -> {(id_per, 'P' ou 'X'): (obtenu, max)}
        for c in liste_cours:
            par_per = {}
            for id_per, genre in unites:
                obt = mx = 0.0
                for ev in evals.get((c["id_cc"], id_per, genre), []):
                    v = points.get((ev["ID_EVAL"], m))
                    if v is not None:
                        obt += v
                        mx += ev["MAXIMUM"]
                    else:
                        manquants[(m, c["id_cc"], id_per, genre)] += 1
                        if zero:
                            mx += ev["MAXIMUM"]
                if mx > 0:
                    par_per[(id_per, genre)] = (obt, mx)
            cellules[c["id_cc"]] = par_per
        el = {"matricule": m, "nom_complet": donnees.nom_complet(e), "sexe": e["SEXE"] or "", "naissance": _fr(e["DATE_NAISSANCE"]),
              "lieu_naissance": e["LIEU_NAISSANCE"] or "", "cours": {}, "portees": {}}
        for c in liste_cours:                                          # cours : périodes, puis semestres et année
            res = {}
            for p in portees:
                parts = [cellules[c["id_cc"]][u] for u in _unites(p) if u in cellules[c["id_cc"]]]
                if parts:
                    o, mx = sum(x[0] for x in parts), sum(x[1] for x in parts)
                    res[p["cle"]] = {"obtenu": _nb(o), "max": _nb(mx), "pct": _pct(o, mx)}
            el["cours"][c["id_cc"]] = res
        for p in portees:                                              # total de l'élève, toutes matières
            o = mx = 0.0
            avec_donnees = set()
            for c in liste_cours:
                for u in _unites(p):
                    if u in cellules[c["id_cc"]]:
                        o += cellules[c["id_cc"]][u][0]
                        mx += cellules[c["id_cc"]][u][1]
                        avec_donnees.add(u)
            pct = _pct(o, mx)
            complet = bool(p["periodes"]) and all(u in avec_donnees for u in _unites_exigees(p))
            conduite = _conduite_dominante(cotes.get((p["periodes"][0], m), [])) if p["type"] == "periode" else ""
            annuel = p["type"] == "annee"
            if pct is None or not complet:
                resultat, reussite = config.DECISION_ATTENTE, None
            elif pct >= config.SEUIL_REUSSITE:
                resultat, reussite = (config.DECISION_REUSSI if annuel else config.RESULTAT_REUSSI), True
            else:
                resultat, reussite = (config.DECISION_ECHEC if annuel else config.RESULTAT_ECHEC), False
            el["portees"][p["cle"]] = {"obtenu": _nb(o) if mx else None, "max": _nb(mx) if mx else None, "pct": pct, "rang": None,
                                       "resultat": resultat, "reussite": reussite, "mention": mention_pour(pct) if complet else "", "complet": complet,
                                       "conduite": conduite}
        eleves.append(el)

    stats = {}
    for p in portees:                                                  # rangs et statistiques de classe
        rangs = _classer({e["matricule"]: e["portees"][p["cle"]]["pct"] for e in eleves})
        for e in eleves:
            e["portees"][p["cle"]]["rang"] = rangs.get(e["matricule"])
        pcts = [e["portees"][p["cle"]]["pct"] for e in eleves if e["portees"][p["cle"]]["pct"] is not None]
        reussis = sum(1 for e in eleves if e["portees"][p["cle"]]["reussite"] is True)
        decides = sum(1 for e in eleves if e["portees"][p["cle"]]["reussite"] is not None)
        stats[p["cle"]] = {"effectif": len(eleves), "classes": len(pcts), "moyenne": round(sum(pcts) / len(pcts), 1) if pcts else None,
                           "reussis": reussis, "echecs": decides - reussis, "en_attente": len(eleves) - decides,
                           "taux": round(100.0 * reussis / decides, 1) if decides else None}

    # alertes : ce que le titulaire doit régler avant d'imprimer
    noms = {e["matricule"]: e["nom_complet"] for e in eleves}
    libelle_cours = {c["id_cc"]: c["libelle"] for c in liste_cours}
    libelle_unite = {(p["periodes"][0], "P"): p["libelle"] for p in periodes}
    libelle_unite.update({(p["periodes"][0], "X"): p["libelle"] for p in portees if p["type"] == "examen"})
    if not periodes:
        alertes.append("Les semestres et périodes de cette année ne sont pas encore définis (Direction des études > Années et périodes).")
    if not liste_cours:
        alertes.append("Aucun cours n'est ouvert dans cette classe pour cette année.")
    for c in liste_cours:
        if not c["professeur"]:
            alertes.append(f"{c['libelle']} : aucun professeur attribué.")
        for id_per, genre in unites:
            if (c["id_cc"], id_per, genre) not in evals:
                alertes.append(f"{c['libelle']} : aucun point en {libelle_unite[(id_per, genre)]}"
                               + (f" ({next(p['semestre'] for p in periodes if p['periodes'][0] == id_per)})" if genre == "P" else "") + ".")
    par_cours = {}
    for (m, id_cc, id_per, genre), n in manquants.items():
        par_cours.setdefault((id_cc, id_per, genre), []).append(noms[m])
    for (id_cc, id_per, genre), liste in sorted(par_cours.items(), key=lambda x: (libelle_cours[x[0][0]], x[0][1], x[0][2])):
        exemples = ", ".join(liste[:3]) + (f" et {len(liste) - 3} autre(s)" if len(liste) > 3 else "")
        alertes.append(f"{libelle_cours[id_cc]} ({libelle_unite[(id_per, genre)]}) : points manquants pour {len(liste)} élève(s) : {exemples}.")
    for e in eleves:
        for p in periodes:
            if not e["portees"][p["cle"]]["complet"] and liste_cours and all(
                    (c["id_cc"], p["periodes"][0], "P") in evals for c in liste_cours):
                alertes.append(f"{e['nom_complet']} : aucun point en {p['libelle']}.")
    return {"annee": annee, "classe": {"n_classe": k["N_CLASSE"], "designation": k["DESI_CLASSE"], "niveau": k["DESI_NIVEAU"],
                                      "option": k["DESI_OPTION"] or "", "primaire": sections.est_primaire(conn, n_classe),
                                      "annee_etude": k["ANNEE_ETUDE"] or ""},
            "portees": portees, "cours": liste_cours, "eleves": eleves, "stats": stats, "alertes": alertes}


# ================================================================== maxima des cours (fixés par le titulaire, secondaire et humanités)
def _nombre_max(x):
    return int(x) if float(x).is_integer() else round(float(x), 2)


def maxima_cours(conn, session, annee, n_classe) -> dict:
    """Les cours de la classe du titulaire avec le maximum d'une période de chacun (examen = 2 x, semestre = 4 x, année = 8 x).
    {'annee', 'classe', 'n_classe', 'modifiable', 'cours': [{id_cc, libelle, professeur, heures, maximum, fixe, avec_points, sans_examen}]}."""
    prof, k = _exiger_titulaire(conn, session, annee, n_classe)
    primaire = sections.est_primaire(conn, k["N_CLASSE"])
    lignes = conn.execute("SELECT X.*, C.LIBELLE, P.NOM, P.POSTNOM, P.PRENOM, P.MATRICULE AS MAT, "
                          "(SELECT COUNT(*) FROM NOTE N JOIN EVALUATION E ON E.ID_EVAL = N.ID_EVAL WHERE E.ID_CC = X.ID_CC) AS NB "
                          "FROM COURS_CLASSE X JOIN COURS C ON C.ID_COURS = X.ID_COURS LEFT JOIN PERSONNEL P ON P.MATRICULE = X.MATRICULE_PROF "
                          "WHERE X.ANNEESCO = ? AND X.N_CLASSE = ? ORDER BY C.LIBELLE COLLATE NOCASE", (str(annee), k["N_CLASSE"])).fetchall()
    out = []
    for l in lignes:
        m = notes.maximum_periode_cours(conn, l)
        out.append({"id_cc": l["ID_CC"], "libelle": l["LIBELLE"], "professeur": donnees.nom_complet(l) if l["MAT"] else "",
                    "heures": l["HEURES_SEMAINE"], "maximum": _nombre_max(m), "fixe": bool(l["MAX_PERIODE"]), "avec_points": l["NB"] > 0,
                    "sans_examen": m >= notes.MAXIMUM_SANS_EXAMEN})
    return {"annee": str(annee), "classe": k["DESI_CLASSE"], "n_classe": k["N_CLASSE"], "modifiable": not primaire, "cours": out}


def definir_maximum_cours(conn, session, annee, n_classe, id_cc, maximum) -> dict:
    """Le titulaire fixe le maximum d'une période pour un cours de sa classe (secondaire et humanités). L'examen vaut 2 x ce maximum.
    Refusé si un point déjà saisi dépasse le nouveau maximum. Les évaluations déjà créées du cours prennent le nouveau maximum."""
    prof, k = _exiger_titulaire(conn, session, annee, n_classe)
    if sections.est_primaire(conn, k["N_CLASSE"]):
        raise ErreurBulletins("Au primaire, les maxima ne se règlent pas ici.")
    try:
        m = round(float(str(maximum).strip().replace(",", ".")), 2)
    except ValueError:
        raise ErreurBulletins("Le maximum doit être un nombre (ex. 10, 20, 50 ou 100).") from None
    if not 0 < m <= 500:
        raise ErreurBulletins("Le maximum d'une période doit être compris entre 1 et 500.")
    cc = conn.execute("SELECT X.*, C.LIBELLE FROM COURS_CLASSE X JOIN COURS C ON C.ID_COURS = X.ID_COURS "
                      "WHERE X.ID_CC = ? AND X.ANNEESCO = ? AND X.N_CLASSE = ?", (id_cc, str(annee), k["N_CLASSE"])).fetchone()
    if not cc:
        raise PermissionError("Accès refusé : ce cours n'est pas dans votre classe.")
    for e in conn.execute("SELECT * FROM EVALUATION WHERE ID_CC = ? AND TYPE IN ('PER', 'EXA')", (cc["ID_CC"],)).fetchall():
        nouveau = m * 2 if e["TYPE"] == "EXA" else m
        haut = conn.execute("SELECT MAX(POINTS) FROM NOTE WHERE ID_EVAL = ?", (e["ID_EVAL"],)).fetchone()[0]
        if haut is not None and haut > nouveau:
            raise ErreurBulletins(f"{cc['LIBELLE']} : un élève a déjà {_nombre_max(haut)} points ; le maximum "
                                  f"{'de l’examen' if e['TYPE'] == 'EXA' else 'de la période'} ne peut pas être {_nombre_max(nouveau)}.")
    avant = notes.maximum_periode_cours(conn, cc)
    with conn:
        conn.execute("UPDATE COURS_CLASSE SET MAX_PERIODE = ?, DATE_MODIF = ?, MODIFIE_PAR = ? WHERE ID_CC = ?",
                     (m, database_maintenant(), session.login, cc["ID_CC"]))
        conn.execute("UPDATE EVALUATION SET MAXIMUM = ? WHERE ID_CC = ? AND TYPE = 'PER'", (m, cc["ID_CC"]))
        conn.execute("UPDATE EVALUATION SET MAXIMUM = ? WHERE ID_CC = ? AND TYPE = 'EXA'", (m * 2, cc["ID_CC"]))
        journaliser(conn, session.id_user, session.login, "MAXIMUM_COURS_FIXE",
                    f"{annee} | {k['DESI_CLASSE']} | {cc['LIBELLE']} | {_nombre_max(avant)} -> {_nombre_max(m)} par période | titulaire {donnees.nom_complet(prof)}")
    return {"id_cc": cc["ID_CC"], "maximum": _nombre_max(m), "sans_examen": m >= notes.MAXIMUM_SANS_EXAMEN}


# ================================================================== lecture pour la page web
def ordre_reussite(r) -> tuple:
    """Clé de tri « dans l'ordre des réussites » pour le résultat `r` d'un élève (un élément de e['portees']) : d'abord les réussites,
    puis les échecs, puis les élèves « en attente » ; dans chaque groupe, du meilleur au plus faible pourcentage (rang)."""
    groupe = 0 if r["reussite"] is True else (1 if r["reussite"] is False else 2)
    return (groupe, r["rang"] is None, r["rang"] or 0)


def resultats(conn, session, annee, n_classe, cle, ordre="reussite") -> dict:
    """Liste des élèves de la classe avec leur résultat pour une période, un examen, un semestre ou l'année.
    ordre « reussite » : réussites (du premier au dernier), puis échecs, puis « en attente » ; ordre « alpha » : alphabétique.
    La liste des élèves est toujours donnée, même quand les semestres et périodes ne sont pas encore définis (portee = None)."""
    prof, k = _exiger_titulaire(conn, session, annee, n_classe)
    calc = calculer(conn, annee, k["N_CLASSE"])
    p = next((x for x in calc["portees"] if x["cle"] == cle), None) if calc["portees"] else None
    if calc["portees"] and not p:
        raise ErreurBulletins("Choisissez la période, le semestre ou l'année.")
    lignes = []
    for e in calc["eleves"]:
        r = e["portees"][cle] if p else {"obtenu": None, "max": None, "pct": None, "rang": None, "mention": "", "resultat": "-",
                                         "reussite": None, "conduite": ""}
        lignes.append({"matricule": e["matricule"], "nom_complet": e["nom_complet"], "sexe": e["sexe"], "obtenu": r["obtenu"], "max": r["max"],
                       "pct": r["pct"], "rang": r["rang"], "mention": r["mention"], "resultat": r["resultat"], "reussite": r["reussite"],
                       "conduite": r["conduite"]})
    if ordre == "alpha" or not p:
        lignes.sort(key=lambda x: x["nom_complet"].lower())
    else:
        lignes.sort(key=lambda x: (ordre_reussite(x), x["nom_complet"].lower()))
    etat = None                                                       # primaire : pas de circuit de proclamation
    if sections.section_de_classe(conn, k["N_CLASSE"]) == sections.SECONDAIRE:
        import proclamation
        statut, valides = proclamation.etat_impression(conn, annee, k["N_CLASSE"], cle)
        for l in lignes:
            l["valide"] = l["matricule"] in valides
        etat = {"statut": statut, "imprimable": statut == "CONFIRMEE", "nb_valides": len(valides),
                "libelle": proclamation.STATUTS.get(statut, "Pas encore autorisée par la Directrice des études")}
    return {"annee": annee, "classe": calc["classe"], "portee": p, "lignes": lignes, "stats": calc["stats"][cle] if p else None, "proclamation": etat,
            "alertes": calc["alertes"], "seuil": config.SEUIL_REUSSITE, "titulaire": donnees.nom_complet(prof), "ordre": ordre}


def fiche_eleve(conn, session, annee, n_classe, matricule) -> dict:
    """Les cotes d'un élève de la classe du titulaire, dans TOUS les cours de la classe : pour chaque cours, ses points par période,
    examen, semestre et pour l'année, puis ses totaux, pourcentages, rangs et résultats. Lecture seule."""
    prof, k = _exiger_titulaire(conn, session, annee, n_classe)
    calc = calculer(conn, annee, k["N_CLASSE"])
    e = next((x for x in calc["eleves"] if x["matricule"] == str(matricule or "")), None)
    if not e:
        raise PermissionError("Accès refusé : cet élève n'est pas dans cette classe.")
    colonnes = [{"cle": p["cle"], "type": p["type"], "libelle": p["libelle"], "semestre": p["semestre"]} for p in calc["portees"]]
    return {"annee": annee, "classe": calc["classe"], "seuil": config.SEUIL_REUSSITE, "colonnes": colonnes,
            "eleve": {"matricule": e["matricule"], "nom_complet": e["nom_complet"], "sexe": e["sexe"], "naissance": e["naissance"],
                      "lieu_naissance": e["lieu_naissance"]},
            "cours": [{"id_cc": c["id_cc"], "libelle": c["libelle"], "professeur": c["professeur"], "cotes": e["cours"].get(c["id_cc"], {})}
                      for c in calc["cours"]],
            "totaux": e["portees"], "effectif": len(calc["eleves"])}


def _nom_fichier(*parties) -> str:
    base = "_".join(donnees.sans_accents(str(p)) for p in parties if p)
    return re.sub(r"[^a-z0-9._-]+", "_", base).strip("_")[:80] or "document"


def _tracer(conn, session, action, detail):
    with conn:
        journaliser(conn, session.id_user, session.login, action, detail)


# ================================================================== documents PDF (octets, nom du fichier)
def document_pdf(conn, session, genre, annee, n_classe, cle="A", matricule=None):
    """Génère un document PDF pour le titulaire. genre : 'bulletins' (toute la classe), 'bulletin' (un élève, avec `matricule`),
    'liste' (liste des résultats de la portée `cle`), 'proclamation' (proclamation de l'année). Retourne (octets, nom_du_fichier)."""
    import bulletins_pdf
    prof, k = _exiger_titulaire(conn, session, annee, n_classe)
    calc = calculer(conn, annee, k["N_CLASSE"])
    calc["titulaire"] = donnees.nom_complet(prof)
    classe = calc["classe"]["designation"]
    if genre in ("bulletins", "bulletin", "liste", "proclamation") and sections.section_de_classe(conn, k["N_CLASSE"]) == sections.SECONDAIRE:
        # Secondaire et humanitaire : impression seulement des élèves VALIDÉS d'une proclamation CONFIRMÉE par le Préfet (la consultation
        # reste libre). Le primaire n'a pas ce circuit.
        import proclamation
        if genre == "bulletin" and str(matricule or "") not in {e["matricule"] for e in calc["eleves"]}:
            raise PermissionError("Accès refusé : cet élève n'est pas dans cette classe.")
        statut, valides = proclamation.etat_impression(conn, annee, k["N_CLASSE"], cle if genre != "proclamation" else "A")
        if statut != "CONFIRMEE":
            raise ErreurBulletins(proclamation.message_blocage(statut))
        if genre == "bulletin" and str(matricule or "") not in valides:
            raise ErreurBulletins("Ce bulletin n'est pas validé : vous pouvez le consulter, pas l'imprimer.")
        if not valides:
            raise ErreurBulletins("Aucun bulletin validé : il n'y a rien à imprimer.")
        calc["eleves"] = [e for e in calc["eleves"] if e["matricule"] in valides]
    if genre in ("bulletins", "bulletin"):
        colonnes = colonnes_bulletin(calc["portees"], cle)
        if genre == "bulletin":
            eleves = [e for e in calc["eleves"] if e["matricule"] == matricule]
            if not eleves:
                raise PermissionError("Accès refusé : cet élève n'est pas dans cette classe.")
        else:
            eleves = calc["eleves"]
        if not eleves:
            raise ErreurBulletins("Aucun élève n'est inscrit dans cette classe.")
        octets = bulletins_pdf.bulletins(calc, eleves, colonnes)
        nom = _nom_fichier("bulletin", classe, annee, cle, eleves[0]["nom_complet"] if genre == "bulletin" else "")
        _tracer(conn, session, "BULLETINS_GENERES", f"{annee} | {classe} | {colonnes[-1]['libelle']} | {len(eleves)} bulletin(s) validé(s)")
    elif genre == "liste":
        p = next((x for x in calc["portees"] if x["cle"] == cle), None)
        if not p:
            raise ErreurBulletins("Choisissez la période, le semestre ou l'année.")
        octets = bulletins_pdf.liste_resultats(calc, p)
        nom = _nom_fichier("resultats", classe, annee, cle)
        _tracer(conn, session, "LISTE_RESULTATS_GENEREE", f"{annee} | {classe} | {p['libelle']}")
    elif genre == "proclamation":
        if not calc["portees"]:
            raise ErreurBulletins("Les semestres et périodes de cette année ne sont pas encore définis.")
        octets = bulletins_pdf.proclamation(calc)
        nom = _nom_fichier("proclamation", classe, annee)
        _tracer(conn, session, "PROCLAMATION_GENEREE", f"{annee} | {classe}")
    else:
        raise ErreurBulletins("Document inconnu.")
    return octets, nom + ".pdf"


def database_maintenant() -> str:
    from database import iso, maintenant
    return iso(maintenant())

"""Saisie des points par les professeurs (logique ; la page web est dans serveur_notes.py et page_professeur.py).

Règles :
- Seul un compte relié à un agent (table COMPTE_PROFESSEUR) peut utiliser ces fonctions. Le professeur ne voit et ne modifie
  que les cours qui lui sont attribués (COURS_CLASSE.MATRICULE_PROF) et les élèves inscrits dans ces classes. Le lien se lit dans
  la base à chaque appel : rien de ce que le navigateur envoie ne décide de l'identité.
- Le professeur ne saisit que : (1) les points de la PÉRIODE, un seul point par élève ; (2) les points de l'EXAMEN du semestre ; (3) la
  conduite de la période. Et seulement la période (ou l'examen) que le TITULAIRE de la classe a autorisée (table AUTORISATION_SAISIE ;
  voir bulletins.py). Il ne voit que le nom des élèves, les points de cette période et la conduite : ni total, ni pourcentage, ni les
  autres périodes. Les totaux et les bulletins sont réservés au titulaire (bulletins.py), qui ne modifie jamais les points.
- Stockage : table EVALUATION, type PER (points d'une période) ou EXA (examen, rangé dans la dernière période du semestre).
  Les anciens types INT, DEV et IG ne se saisissent plus ; leurs points déjà enregistrés restent visibles et comptés.
- Un point vide veut dire « pas de note » (absent, pas encore corrigé). Un point est entre 0 et le maximum.
- Conduite : une cote par élève et par période, donnée par le professeur du cours (codes de COTES_CONDUITE).
"""
import re
from datetime import date, timedelta

import config
import cours
import donnees
import droits
import sections
import security
from database import iso, journaliser, maintenant

TYPES = {"PER": ("Points de la période", config.MAXIMUM_PERIODE), "EXA": ("Examen du semestre", config.MAXIMUM_EXAMEN),
         "INT": ("Interrogation", 10), "DEV": ("Devoir", 20), "IG": ("Interrogation générale", 20)}     # sigle: (libellé, max)
ANCIENS_TYPES = ("INT", "DEV", "IG")    # anciennes évaluations : lecture seule
COTES_CONDUITE = (("E", "Excellente"), ("TB", "Très bonne"), ("B", "Bonne"), ("AB", "Assez bonne"), ("P", "Passable"),
                  ("M", "Mauvaise"))
ROLE_PROFESSEUR = "PROFESSEUR"


class ErreurNotes(Exception):
    """Erreur métier dont le message peut être affiché tel quel."""


ERREURS = (ErreurNotes, PermissionError)


def legende() -> dict:
    return {"types": [{"sigle": "P", "libelle": "Points de la période", "maximum": config.MAXIMUM_PERIODE},
                      {"sigle": "EX", "libelle": "Examen du semestre", "maximum": config.MAXIMUM_EXAMEN}],
            "conduite": [{"code": c, "libelle": l} for c, l in COTES_CONDUITE],
            "autres": [{"sigle": "CDT", "libelle": "Conduite de l'élève pour la période"}]}


def aujourdhui() -> date:
    """Date du jour (une fonction à part pour pouvoir la fixer dans les essais)."""
    return date.today()


def code_evaluation(type_, numero) -> str:
    """Code d'une ancienne évaluation : INT1, INT2, DEV1, IG, IG2... (4 caractères au plus)."""
    return type_ if type_ in ("IG", "EXA") and numero == 1 else f"{type_}{numero}"


# ================================================================== identité du professeur
MAXIMUM_SANS_EXAMEN = 100     # secondaire : un cours dont la période vaut au moins 100 points (atelier, laboratoire) n'a pas d'examen


def maximum_periode_cours(conn, cc):
    """Maximum d'une PÉRIODE pour ce cours de classe (ligne COURS_CLASSE) : secondaire = le maximum fixé par le titulaire de la classe,
    à défaut le maximum standard (config.MAXIMUM_PERIODE) ; primaire = le maximum standard."""
    if not sections.est_primaire(conn, cc["N_CLASSE"]) and cc["MAX_PERIODE"]:
        return float(cc["MAX_PERIODE"])
    return float(TYPES["PER"][1])


def maximum_defaut(conn, cc, cible) -> float:
    """Maximum d'une période, ou de l'examen (2 x la période) tant qu'aucun point n'a créé l'évaluation."""
    if sections.est_primaire(conn, cc["N_CLASSE"]):
        return float(TYPES[cible["type"]][1])
    m = maximum_periode_cours(conn, cc)
    return m * 2 if cible["type"] == "EXA" else m


def _exiger_examen_possible(conn, cc, cible):
    if cible["type"] == "EXA" and not sections.est_primaire(conn, cc["N_CLASSE"]) and maximum_periode_cours(conn, cc) >= MAXIMUM_SANS_EXAMEN:
        raise ErreurNotes(f"« {cc['COURS']} » (maximum {_nombre(maximum_periode_cours(conn, cc))} par période) est un cours sans examen.")


def _professeur(conn, session):
    """Ligne PERSONNEL du professeur connecté, ou PermissionError."""
    refus = PermissionError("Accès refusé : cette page est réservée aux professeurs dont le compte est relié à leur dossier d'agent.")
    if not droits._utilisateur_actif(conn, session):
        raise refus
    l = conn.execute("SELECT P.* FROM COMPTE_PROFESSEUR C JOIN PERSONNEL P ON P.MATRICULE = C.MATRICULE "
                     "WHERE C.ID_USER = ? AND P.ACTIF = 1", (session.id_user,)).fetchone()
    if not l:
        raise refus
    return l


def _cc(conn, session, id_cc, ecriture=False):
    """Cours d'une classe qui appartient au professeur connecté (sinon PermissionError). Retourne (prof, ligne COURS_CLASSE élargie)."""
    prof = _professeur(conn, session)
    try:
        id_cc = int(id_cc)
    except (TypeError, ValueError):
        raise ErreurNotes("Cours introuvable.") from None
    l = conn.execute("SELECT X.*, C.LIBELLE AS COURS, K.DESI_CLASSE, N.DESI_NIVEAU, O.DESI_OPTION, A.ACTIF AS ANNEE_ACTIVE "
                     "FROM COURS_CLASSE X JOIN COURS C ON C.ID_COURS = X.ID_COURS JOIN CLASSE K ON K.N_CLASSE = X.N_CLASSE "
                     "JOIN NIVEAU N ON N.CODE_NIVEAU = K.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = K.CODE_OPTION "
                     "JOIN ANNEE_SCO A ON A.ANNEESCO = X.ANNEESCO WHERE X.ID_CC = ?", (id_cc,)).fetchone()
    if not l or l["MATRICULE_PROF"] != prof["MATRICULE"]:
        raise PermissionError("Accès refusé : ce cours ne vous est pas attribué.")
    if ecriture and not l["ANNEE_ACTIVE"]:
        raise ErreurNotes(f"L'année {l['ANNEESCO']} est désactivée : on n'y saisit plus de points.")
    return prof, l


def _periode(conn, cc, id_per):
    """Période (avec son semestre), qui doit appartenir à l'année du cours."""
    try:
        id_per = int(id_per)
    except (TypeError, ValueError):
        raise ErreurNotes("Choisissez la période.") from None
    p = conn.execute("SELECT P.*, S.LIBELLE AS SEMESTRE, S.ANNEESCO, S.SECTION FROM PERIODE_SCO P JOIN SEMESTRE_SCO S ON S.ID_SEM = P.ID_SEM "
                     "WHERE P.ID_PER = ?", (id_per,)).fetchone()
    if not p or p["ANNEESCO"] != cc["ANNEESCO"]:
        raise ErreurNotes("Cette période n'appartient pas à l'année du cours.")
    if p["SECTION"] != sections.section_de_classe(conn, cc["N_CLASSE"]):
        raise ErreurNotes("Cette période n'appartient pas au calendrier de la section de cette classe.")
    return p


def _eleves(conn, cc) -> list:
    return conn.execute("SELECT E.* FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE WHERE I.ANNEESCO = ? AND I.N_CLASSE = ? "
                        "ORDER BY E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE",
                        (cc["ANNEESCO"], cc["N_CLASSE"])).fetchall()


# ================================================================== mes classes et le calendrier
def _fr(iso_date) -> str:
    return date.fromisoformat(iso_date).strftime("%d/%m/%Y")


def autorisees(conn, annee, n_classe) -> set:
    """Clés (« P<id> » pour une période, « X<id> » pour l'examen d'un semestre) que le titulaire de la classe a ouvertes à la saisie.
    Au primaire, le titulaire est l'unique enseignant : il n'a personne à autoriser, tout le calendrier de l'année est ouvert."""
    if sections.est_primaire(conn, n_classe):
        cles = set()
        for s in conn.execute("SELECT ID_SEM FROM SEMESTRE_SCO WHERE ANNEESCO = ? AND SECTION = ?", (annee, sections.PRIMAIRE)).fetchall():
            pers = conn.execute("SELECT ID_PER FROM PERIODE_SCO WHERE ID_SEM = ?", (s[0],)).fetchall()
            cles |= {f"P{p[0]}" for p in pers}
            if pers:
                cles.add(f"X{s[0]}")
        return cles
    return {l[0] for l in conn.execute("SELECT CLE FROM AUTORISATION_SAISIE WHERE ANNEESCO = ? AND N_CLASSE = ?", (annee, n_classe))}


def _exiger_autorisee(conn, cc, cible):
    """La saisie d'une période ou d'un examen n'est possible que si le titulaire de la classe l'a autorisée."""
    if cible["cle"] not in autorisees(conn, cc["ANNEESCO"], cc["N_CLASSE"]):
        raise ErreurNotes(f"« {cible['libelle']} » n'est pas ouvert à la saisie dans cette classe : "
                          "c'est le titulaire de la classe qui autorise la période ou l'examen à saisir.")


def _periodes_du_semestre(conn, id_sem) -> list:
    return conn.execute("SELECT * FROM PERIODE_SCO WHERE ID_SEM = ? ORDER BY DATE_DEBUT, ID_PER", (id_sem,)).fetchall()


def mes_classes(conn, session, annee=None) -> dict:
    """Ce que voit le professeur à l'ouverture : ses classes et ses cours de l'année, pour chaque classe les périodes et examens que
    le titulaire a autorisés (`autorisees`), et le calendrier de l'année (chaque semestre : ses périodes, puis son examen)."""
    prof = _professeur(conn, session)
    annees = [l[0] for l in conn.execute("SELECT DISTINCT ANNEESCO FROM COURS_CLASSE WHERE MATRICULE_PROF = ? ORDER BY ANNEESCO DESC",
                                         (prof["MATRICULE"],))]
    courante = donnees.annee_courante(conn)
    if annee not in annees:
        annee = courante if courante in annees else (annees[0] if annees else courante)
    classes = {}
    for l in conn.execute("SELECT X.ID_CC, X.N_CLASSE, X.HEURES_SEMAINE, C.LIBELLE AS COURS, K.DESI_CLASSE, N.DESI_NIVEAU, O.DESI_OPTION, "
                          "(SELECT COUNT(*) FROM INSCRIRE I WHERE I.ANNEESCO = X.ANNEESCO AND I.N_CLASSE = X.N_CLASSE) AS NB "
                          "FROM COURS_CLASSE X JOIN COURS C ON C.ID_COURS = X.ID_COURS JOIN CLASSE K ON K.N_CLASSE = X.N_CLASSE "
                          "JOIN NIVEAU N ON N.CODE_NIVEAU = K.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = K.CODE_OPTION "
                          "WHERE X.ANNEESCO = ? AND X.MATRICULE_PROF = ? ORDER BY N.DESI_NIVEAU COLLATE NOCASE, K.DESI_CLASSE, "
                          "C.LIBELLE COLLATE NOCASE", (annee, prof["MATRICULE"])):
        k = classes.setdefault(l["N_CLASSE"], {"n_classe": l["N_CLASSE"], "designation": l["DESI_CLASSE"], "niveau": l["DESI_NIVEAU"],
                                               "option": l["DESI_OPTION"] or "", "nb_eleves": l["NB"], "cours": [],
                                               "autorisees": sorted(autorisees(conn, annee, l["N_CLASSE"]))})
        k["cours"].append({"id_cc": l["ID_CC"], "cours": l["COURS"], "heures": l["HEURES_SEMAINE"]})
    semestres = []
    for s in conn.execute("SELECT * FROM SEMESTRE_SCO WHERE ANNEESCO = ? ORDER BY SECTION DESC, DATE_DEBUT", (annee,)):
        pers = _periodes_du_semestre(conn, s["ID_SEM"])
        semestres.append({"id": s["ID_SEM"], "libelle": s["LIBELLE"], "section": s["SECTION"], "periodes": [
            {"id": p["ID_PER"], "cle": f"P{p['ID_PER']}", "libelle": p["LIBELLE"], "debut": _fr(p["DATE_DEBUT"]), "fin": _fr(p["DATE_FIN"])}
            for p in pers],
            "examen": ({"id": f"X{s['ID_SEM']}", "cle": f"X{s['ID_SEM']}", "libelle": "Examen"} if pers else None)})
    for k in classes.values():                      # chaque classe suit le calendrier de sa section (trimestres au primaire)
        k["section"] = sections.section_de_classe(conn, k["n_classe"])
        k["semestres"] = [s for s in semestres if s["section"] == k["section"]]
    return {"professeur": donnees.nom_complet(prof), "annee": annee, "annees": annees, "classes": list(classes.values()),
            "semestres": semestres, "legende": legende()}


# ================================================================== ce que le professeur saisit : une période ou l'examen d'un semestre
def _cible(conn, cc, per) -> dict:
    """`per` : l'identifiant d'une période (ex. 12) ou « X<semestre> » (ex. X3) pour l'examen d'un semestre.
    Retourne la période ou l'examen à saisir, avec la ligne EVALUATION qui le porte (type, période de rangement) et sa date de fin."""
    texte = str(per if per is not None else "").strip().upper()
    if texte.startswith("X"):
        try:
            id_sem = int(texte[1:])
        except ValueError:
            raise ErreurNotes("Choisissez la période ou l'examen.") from None
        s = conn.execute("SELECT * FROM SEMESTRE_SCO WHERE ID_SEM = ? AND ANNEESCO = ? AND SECTION = ?",
                         (id_sem, cc["ANNEESCO"], sections.section_de_classe(conn, cc["N_CLASSE"]))).fetchone()
        if not s:
            raise ErreurNotes("Ce semestre n'appartient pas à l'année ni à la section de ce cours.")
        pers = _periodes_du_semestre(conn, id_sem)
        if not pers:
            raise ErreurNotes("Ce semestre n'a pas encore de période.")
        derniere = pers[-1]
        return {"genre": "X", "cle": f"X{id_sem}", "type": "EXA", "id_per": derniere["ID_PER"], "id_sem": id_sem,
                "libelle": f"Examen - {s['LIBELLE']}", "semestre": s["LIBELLE"], "fin": derniere["DATE_FIN"]}
    p = _periode(conn, cc, texte)
    return {"genre": "P", "cle": f"P{p['ID_PER']}", "type": "PER", "id_per": p["ID_PER"], "id_sem": p["ID_SEM"],
            "libelle": p["LIBELLE"], "semestre": p["SEMESTRE"], "fin": p["DATE_FIN"]}


def _evaluation_cible(conn, cc, cible):
    """Ligne EVALUATION des points de la période (ou de l'examen), ou None tant que rien n'a été saisi."""
    return conn.execute("SELECT * FROM EVALUATION WHERE ID_CC = ? AND ID_PER = ? AND TYPE = ? AND NUMERO = 1",
                        (cc["ID_CC"], cible["id_per"], cible["type"])).fetchone()


def _creer_evaluation(conn, session, cc, cible, maximum) -> int:
    """Crée la ligne EVALUATION d'une période ou d'un examen (à appeler dans une transaction ouverte)."""
    cur = conn.execute("INSERT INTO EVALUATION (ID_CC, ID_PER, TYPE, NUMERO, DATE_EVAL, MAXIMUM, DATE_ENREG, ENREGISTRE_PAR) "
                       "VALUES (?,?,?,?,?,?,?,?)", (cc["ID_CC"], cible["id_per"], cible["type"], 1, aujourdhui().isoformat(), maximum,
                                                    iso(maintenant()), session.login))
    journaliser(conn, session.id_user, session.login, "EVALUATION_AJOUT",
                f"{cc['ANNEESCO']} | {cc['DESI_CLASSE']} | {cc['COURS']} | {cible['libelle']} sur {_nombre(maximum)}")
    return cur.lastrowid


# ================================================================== la fiche de saisie
def _nombre(x):
    """Entier si possible (12.0 -> 12), sinon décimal : pour l'affichage JSON."""
    return int(x) if float(x).is_integer() else round(float(x), 2)


def fiche(conn, session, id_cc, per) -> dict:
    """Fiche de saisie d'une période (ou d'un examen) autorisée par le titulaire : les élèves de la classe, leur point pour cette seule
    période, et leur conduite. Le professeur ne voit ni le total, ni le pourcentage, ni les points des autres périodes."""
    prof, cc = _cc(conn, session, id_cc)
    cible = _cible(conn, cc, per)
    _exiger_autorisee(conn, cc, cible)
    _exiger_examen_possible(conn, cc, cible)
    e = _evaluation_cible(conn, cc, cible)
    maximum = e["MAXIMUM"] if e else maximum_defaut(conn, cc, cible)
    points = {n["MATRICULE"]: n["POINTS"] for n in conn.execute("SELECT * FROM NOTE WHERE ID_EVAL = ?", (e["ID_EVAL"],))} if e else {}
    conduites = {}
    if cible["genre"] == "P":
        conduites = {l["MATRICULE"]: l["COTE"] for l in conn.execute("SELECT * FROM CONDUITE WHERE ID_CC = ? AND ID_PER = ?",
                                                                     (cc["ID_CC"], cible["id_per"]))}
    code = "EX" if cible["genre"] == "X" else "P"
    colonne = {"id": cible["cle"], "cle": cible["cle"], "genre": cible["genre"], "code": code, "libelle": cible["libelle"],
               "type": cible["type"], "maximum": _nombre(maximum), "editable": True}
    eleves = [{"matricule": x["MATRICULE"], "nom_complet": donnees.nom_complet(x), "sexe": x["SEXE"] or "",
               "points": {cible["cle"]: None if x["MATRICULE"] not in points else _nombre(points[x["MATRICULE"]])},
               "conduite": conduites.get(x["MATRICULE"], "")} for x in _eleves(conn, cc)]
    return {"id_cc": cc["ID_CC"], "cours": cc["COURS"], "classe": cc["DESI_CLASSE"], "niveau": cc["DESI_NIVEAU"],
            "option": cc["DESI_OPTION"] or "", "annee": cc["ANNEESCO"], "professeur": donnees.nom_complet(prof),
            "periode": {"id": cible["id_per"], "cle": cible["cle"], "genre": cible["genre"], "libelle": cible["libelle"], "semestre": cible["semestre"]},
            "modifiable": bool(cc["ANNEE_ACTIVE"]), "evaluations": [colonne], "eleves": eleves, "legende": legende()}


# ================================================================== maximum, suppression
def _maximum(valeur, type_) -> float:
    if valeur in (None, ""):
        return float(TYPES[type_][1])
    try:
        m = float(str(valeur).strip().replace(",", "."))
    except ValueError:
        raise ErreurNotes("Le maximum doit être un nombre (ex. 10 ou 20).") from None
    if not 0 < m <= 1000:
        raise ErreurNotes("Le maximum doit être supérieur à 0.")
    return round(m, 2)


def definir_maximum(conn, session, id_cc, per, maximum) -> dict:
    """Fixe le maximum des points d'une période ou de l'examen d'un semestre pour ce cours (20 et 40 au départ).
    Un maximum ne peut pas être plus petit qu'un point déjà saisi. N'est plus proposé au professeur dans la page web (il ne saisit que
    les points et la conduite) : réservé à un usage interne et aux essais."""
    prof, cc = _cc(conn, session, id_cc, ecriture=True)
    cible = _cible(conn, cc, per)
    m = _maximum(maximum, cible["type"])
    e = _evaluation_cible(conn, cc, cible)
    if e:
        plus_haut = conn.execute("SELECT MAX(POINTS) FROM NOTE WHERE ID_EVAL = ?", (e["ID_EVAL"],)).fetchone()[0]
        if plus_haut is not None and plus_haut > m:
            raise ErreurNotes(f"Un élève a déjà {_nombre(plus_haut)} points : le maximum ne peut pas être {_nombre(m)}.")
        if m == e["MAXIMUM"]:
            return {"maximum": _nombre(m)}
    with conn:
        if e:
            conn.execute("UPDATE EVALUATION SET MAXIMUM = ? WHERE ID_EVAL = ?", (m, e["ID_EVAL"]))
            journaliser(conn, session.id_user, session.login, "EVALUATION_MODIFIEE",
                        f"{cc['ANNEESCO']} | {cc['DESI_CLASSE']} | {cc['COURS']} | {cible['libelle']} : maximum {_nombre(e['MAXIMUM'])} -> {_nombre(m)}")
        else:
            _creer_evaluation(conn, session, cc, cible, m)
    return {"maximum": _nombre(m)}


def _evaluation(conn, session, id_eval, ecriture=False):
    try:
        id_eval = int(id_eval)
    except (TypeError, ValueError):
        raise ErreurNotes("Évaluation introuvable.") from None
    e = conn.execute("SELECT * FROM EVALUATION WHERE ID_EVAL = ?", (id_eval,)).fetchone()
    if not e:
        _professeur(conn, session)
        raise ErreurNotes("Évaluation introuvable.")
    prof, cc = _cc(conn, session, e["ID_CC"], ecriture)
    return e, cc


def supprimer_evaluation(conn, session, id_eval):
    """Efface une colonne de points (une période, un examen ou une ancienne évaluation) avec tous ses points."""
    e, cc = _evaluation(conn, session, id_eval, ecriture=True)
    n = conn.execute("SELECT COUNT(*) FROM NOTE WHERE ID_EVAL = ?", (e["ID_EVAL"],)).fetchone()[0]
    with conn:
        conn.execute("DELETE FROM NOTE WHERE ID_EVAL = ?", (e["ID_EVAL"],))
        conn.execute("DELETE FROM EVALUATION WHERE ID_EVAL = ?", (e["ID_EVAL"],))
        journaliser(conn, session.id_user, session.login, "EVALUATION_SUPPRIMEE",
                    f"{cc['ANNEESCO']} | {cc['DESI_CLASSE']} | {cc['COURS']} | {e['TYPE']}{e['NUMERO']} | {n} point(s) effacé(s)")


# ================================================================== points
def _lire_points(texte, maximum):
    """None si vide ; sinon un nombre entre 0 et le maximum (virgule ou point accepté)."""
    t = str(texte if texte is not None else "").strip().replace(",", ".")
    if t == "":
        return None
    if not re.fullmatch(r"\d{1,4}(\.\d{1,2})?", t):
        raise ValueError("pas un nombre")
    v = round(float(t), 2)
    if v > maximum:
        raise ValueError(f"plus que le maximum ({_nombre(maximum)})")
    return v


def enregistrer_points(conn, session, id_cc, per, valeurs: dict) -> dict:
    """Points de la période (ou de l'examen) `per` ; valeurs : {matricule: texte}. Un texte vide efface le point.
    Possible seulement si le titulaire de la classe a autorisé cette période ou cet examen. Tout ou rien : si un point est invalide,
    rien n'est enregistré."""
    prof, cc = _cc(conn, session, id_cc, ecriture=True)
    cible = _cible(conn, cc, per)
    inscrits = {x["MATRICULE"]: x for x in _eleves(conn, cc)}
    for matricule in (valeurs or {}):
        if matricule not in inscrits:
            raise PermissionError("Accès refusé : cet élève n'est pas dans cette classe.")
    _exiger_autorisee(conn, cc, cible)
    _exiger_examen_possible(conn, cc, cible)
    e = _evaluation_cible(conn, cc, cible)
    maximum = e["MAXIMUM"] if e else maximum_defaut(conn, cc, cible)
    deja = {n["MATRICULE"]: n["POINTS"] for n in conn.execute("SELECT * FROM NOTE WHERE ID_EVAL = ?", (e["ID_EVAL"],))} if e else {}
    ecrire, effacer, erreurs = [], [], []
    for matricule, texte in (valeurs or {}).items():
        try:
            v = _lire_points(texte, maximum)
        except ValueError as ex:
            erreurs.append(f"{donnees.nom_complet(inscrits[matricule])} : {ex}")
            continue
        if v is None and matricule in deja:
            effacer.append(matricule)
        elif v is not None and deja.get(matricule) != v:
            ecrire.append((matricule, v))
    if erreurs:
        raise ErreurNotes("Points refusés (rien n'a été enregistré) :\n- " + "\n- ".join(erreurs[:6]) + ("\n- ..." if len(erreurs) > 6 else ""))
    if not (ecrire or effacer):
        return {"enregistres": 0, "effaces": 0}
    maintenant_iso = iso(maintenant())
    with conn:
        id_eval = e["ID_EVAL"] if e else _creer_evaluation(conn, session, cc, cible, maximum)
        for m, v in ecrire:
            conn.execute("INSERT INTO NOTE (ID_EVAL, MATRICULE, POINTS, DATE_MODIF) VALUES (?,?,?,?) "
                         "ON CONFLICT (ID_EVAL, MATRICULE) DO UPDATE SET POINTS = excluded.POINTS, DATE_MODIF = excluded.DATE_MODIF",
                         (id_eval, m, v, maintenant_iso))
        for m in effacer:
            conn.execute("DELETE FROM NOTE WHERE ID_EVAL = ? AND MATRICULE = ?", (id_eval, m))
        journaliser(conn, session.id_user, session.login, "NOTES_ENREGISTREES",
                    f"{cc['ANNEESCO']} | {cc['DESI_CLASSE']} | {cc['COURS']} | {cible['libelle']} | "
                    f"{len(ecrire)} point(s) enregistré(s), {len(effacer)} effacé(s)")
    return {"enregistres": len(ecrire), "effaces": len(effacer)}


# ================================================================== conduite
def enregistrer_conduite(conn, session, id_cc, id_per, matricule, cote):
    """Donne (ou, avec une cote vide, retire) la conduite d'un élève pour la période (si le titulaire a autorisé la période, comme les points)."""
    prof, cc = _cc(conn, session, id_cc, ecriture=True)
    cible = _cible(conn, cc, id_per)
    if cible["genre"] != "P":
        raise ErreurNotes("La conduite se donne pour une période, pas pour l'examen.")
    eleve = next((x for x in _eleves(conn, cc) if x["MATRICULE"] == matricule), None)
    if not eleve:
        raise PermissionError("Accès refusé : cet élève n'est pas dans cette classe.")
    cote = str(cote or "").strip().upper()
    if cote and cote not in dict(COTES_CONDUITE):
        raise ErreurNotes("Conduite inconnue : " + ", ".join(c for c, _l in COTES_CONDUITE) + ".")
    _exiger_autorisee(conn, cc, cible)
    with conn:
        if cote:
            conn.execute("INSERT INTO CONDUITE (ID_CC, ID_PER, MATRICULE, COTE, DATE_MODIF) VALUES (?,?,?,?,?) "
                         "ON CONFLICT (ID_CC, ID_PER, MATRICULE) DO UPDATE SET COTE = excluded.COTE, DATE_MODIF = excluded.DATE_MODIF",
                         (cc["ID_CC"], cible["id_per"], matricule, cote, iso(maintenant())))
        else:
            conn.execute("DELETE FROM CONDUITE WHERE ID_CC = ? AND ID_PER = ? AND MATRICULE = ?", (cc["ID_CC"], cible["id_per"], matricule))
        journaliser(conn, session.id_user, session.login, "CONDUITE_ENREGISTREE",
                    f"{cc['ANNEESCO']} | {cc['DESI_CLASSE']} | {cible['libelle']} | {donnees.nom_complet(eleve)} | {cote or 'retirée'}")


# ================================================================== comptes des professeurs (Administrateur)
def _login_propose(conn, agent) -> str:
    base = donnees.sans_accents(f"{agent['PRENOM'] or agent['POSTNOM'] or ''}.{agent['NOM']}")
    base = re.sub(r"[^a-z0-9._-]+", "", base.replace(" ", "")).strip("._-")[:28] or "prof"
    login, i = base, 1
    while conn.execute("SELECT 1 FROM UTILISATEUR WHERE LOGIN = ?", (login,)).fetchone():
        i += 1
        login = f"{base}{i}"
    return login


def compte_du_professeur(conn, session, matricule):
    """Identifiant du compte relié à l'agent, ou None."""
    droits.exiger_admin(conn, session)
    l = conn.execute("SELECT U.LOGIN, U.ACTIF FROM COMPTE_PROFESSEUR C JOIN UTILISATEUR U ON U.ID_USER = C.ID_USER WHERE C.MATRICULE = ?",
                     (matricule,)).fetchone()
    return {"login": l["LOGIN"], "actif": bool(l["ACTIF"])} if l else None


def creer_compte_professeur(conn, session, matricule, login=None) -> dict:
    """Crée le compte de connexion d'un agent (poste « Professeur ») avec un mot de passe provisoire qu'il devra changer.
    Réservé à l'Administrateur. Retourne {'login', 'mdp_temporaire', 'nom'}."""
    droits.exiger_admin(conn, session)
    agent = conn.execute("SELECT * FROM PERSONNEL WHERE MATRICULE = ?", (matricule,)).fetchone()
    if not agent:
        raise ErreurNotes("Agent introuvable.")
    if not agent["ACTIF"]:
        raise ErreurNotes("Le dossier de cet agent est désactivé.")
    if conn.execute("SELECT 1 FROM COMPTE_PROFESSEUR WHERE MATRICULE = ?", (matricule,)).fetchone():
        raise ErreurNotes("Cet agent a déjà un compte de connexion.")
    if not droits.role_existe(conn, ROLE_PROFESSEUR):
        import acces
        acces.creer_role(conn, session, "Professeur")
    login = (login or "").strip() or _login_propose(conn, agent)
    mdp = security.generer_mdp_temporaire(login)
    nom = donnees.nom_complet(agent)
    try:
        id_user = security.creer_utilisateur(conn, login, nom, ROLE_PROFESSEUR, mdp, doit_changer=True, id_acteur=session.id_user)
    except ValueError as e:
        raise ErreurNotes(str(e)) from None
    with conn:
        conn.execute("INSERT INTO COMPTE_PROFESSEUR (ID_USER, MATRICULE) VALUES (?,?)", (id_user, matricule))
        journaliser(conn, session.id_user, session.login, "COMPTE_PROFESSEUR_CREE", f"{matricule} | {nom} | identifiant {login}")
    return {"login": security.normaliser_login(login), "mdp_temporaire": mdp, "nom": nom}

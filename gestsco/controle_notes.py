"""Direction des études, 3e fonctionnalité : « Contrôle des notes » (sans interface graphique : testable seule).

La Directrice des études (droit « direction_etudes ») :
  - CONSULTE les notes saisies par les professeurs : pour une période (ou un examen), la situation de chaque cours de chaque classe du
    secondaire (complet, incomplet, non saisi, sans professeur), puis la fiche d'un cours : le point de chaque élève et quelques repères
    (moyenne, plus petit et plus grand point) ;
  - REPÈRE les notes manquantes : tous les cours dont des élèves n'ont pas de point pour une période échue, regroupés par professeur
    (export CSV) ;
  - VÉRIFIE les notes par élève, classe, cours, période, examen et total du semestre (tableau croisé élèves x cours x colonnes, avec les
    totaux de l'élève, toutes matières, et son rang ; mêmes calculs que les bulletins : bulletins.calculer) ;
  - DEMANDE des corrections : pour une fiche (cours + période ou examen), éventuellement pour un seul élève, elle envoie au professeur
    une demande « notes manquantes » ou « correction ». Le professeur la voit dans son espace (onglet « Corrections »), corrige LUI-MÊME
    ses points, puis marque la demande « traitée » avec sa réponse. La direction ne modifie jamais un point.

Règles :
- Seules les classes de la section « Secondaire et humanitaire » sont contrôlées (au primaire, le titulaire est l'unique enseignant).
- Droits sur « Direction des études » (relus dans la base à chaque appel) : Lecture = consulter, repérer, voir les demandes ;
  Ajout = envoyer une demande ; Modification = annuler une demande ouverte. L'Administrateur a tous les droits.
- Un point vide veut dire « pas de note » (absent, pas encore corrigé) : il est donc signalé comme manquant ; c'est le professeur qui
  justifie dans sa réponse (élève absent à l'examen, par exemple).
- Une période est « échue » quand sa date de fin est passée ; l'examen d'un semestre, quand la dernière période du semestre l'est.
  Seules les fiches échues sont « en retard ». Un cours dont le maximum de période atteint 100 points n'a pas d'examen (notes.py).
- Côté professeur : on ne voit que les demandes des cours qui lui sont attribués (lien relu dans la base à chaque appel). Il ne peut
  marquer « traitée » qu'une demande ouverte ; s'il reste des points manquants ou pour une correction, il doit écrire une réponse.
- Toute écriture est inscrite au journal.
"""
import csv
import io
from datetime import date

import config
import donnees
import droits
import bulletins
import notes
import sections
from database import iso, journaliser, maintenant
from notes import ErreurNotes

MODULE = "direction_etudes"
TYPES_DEMANDE = {"MANQUANTE": "Notes manquantes", "CORRECTION": "Correction"}
STATUTS = {"OUVERTE": "Ouverte", "TRAITEE": "Traitée", "ANNULEE": "Annulée"}
ETATS = {"COMPLET": "Complet", "INCOMPLET": "Incomplet", "NON_SAISI": "Non saisi", "SANS_PROF": "Sans professeur", "SANS_OBJET": "Sans objet"}
MOTIF_MIN, MOTIF_MAX = 5, 1000


class ErreurControle(ErreurNotes):
    """Erreur dont le message peut être affiché tel quel (sous-classe de ErreurNotes : la page des professeurs l'affiche aussi)."""


# ================================================================== droits
def peut(conn, session, droit="LECTURE") -> bool:
    """Droit sur « Direction des études » (ou Administrateur), section Secondaire et humanitaire ouverte au compte."""
    return (session is not None and sections.SECONDAIRE in sections.sections_de(conn, session)
            and (droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, droit)))


def exiger(conn, session, droit="LECTURE"):
    if not peut(conn, session, droit):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS.get(droit, droit)} » "
                              f"sur « {config.MODULES_DROITS[MODULE][0]} » (section secondaire et humanitaire).")


# ================================================================== outils
def _annee(conn, annee) -> str:
    a = str(annee or "").strip() or donnees.annee_courante(conn)
    if not a or not conn.execute("SELECT 1 FROM ANNEE_SCO WHERE ANNEESCO = ?", (a,)).fetchone():
        raise ErreurControle("Aucune année scolaire n'est définie : créez-la d'abord (Direction des études > Années).")
    return a


def liste_annees(conn) -> list:
    return [l[0] for l in conn.execute("SELECT ANNEESCO FROM ANNEE_SCO ORDER BY ANNEESCO DESC")]


def _nombre(x):
    return int(x) if float(x).is_integer() else round(float(x), 2)


def _fr(texte) -> str:
    try:
        return date.fromisoformat(str(texte)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(texte or "")


def calendrier(conn, annee) -> list:
    """Périodes puis examen de chaque semestre du secondaire pour l'année : {cle, type, id_per, id_sem, libelle, court, debut, fin, delai}.
    `delai` : A_VENIR, EN_COURS ou ECHUE (par rapport à la date du jour)."""
    aujourdhui = notes.aujourdhui().isoformat()
    sortie = []
    for s in conn.execute("SELECT * FROM SEMESTRE_SCO WHERE ANNEESCO = ? AND SECTION = 'SECONDAIRE' ORDER BY DATE_DEBUT, ID_SEM", (annee,)):
        pers = notes._periodes_du_semestre(conn, s["ID_SEM"])
        elements = [(f"P{p['ID_PER']}", "PER", p["ID_PER"], f"{s['LIBELLE']} - {p['LIBELLE']}", p["LIBELLE"], p["DATE_DEBUT"], p["DATE_FIN"])
                    for p in pers]
        if pers:
            d = pers[-1]
            elements.append((f"X{s['ID_SEM']}", "EXA", d["ID_PER"], f"Examen - {s['LIBELLE']}", "Examen", d["DATE_DEBUT"], d["DATE_FIN"]))
        for cle, type_, id_per, libelle, court, debut, fin in elements:
            delai = "A_VENIR" if debut > aujourdhui else "ECHUE" if fin < aujourdhui else "EN_COURS"
            sortie.append({"cle": cle, "type": type_, "id_per": id_per, "id_sem": s["ID_SEM"], "libelle": libelle, "court": court,
                           "debut": debut, "fin": fin, "delai": delai, "semestre": s["LIBELLE"]})
    return sortie


def _periode_par_defaut(cal) -> str:
    """La dernière période échue, sinon celle en cours, sinon la première."""
    for delai in ("ECHUE", "EN_COURS"):
        trouvees = [p["cle"] for p in cal if p["delai"] == delai]
        if trouvees:
            return trouvees[-1]
    return cal[0]["cle"] if cal else ""


def _cours_de_classe(conn, annee, n_classe=None) -> list:
    sql = ("SELECT X.ID_CC, X.ANNEESCO, X.N_CLASSE, X.MATRICULE_PROF, X.MAX_PERIODE, C.LIBELLE AS COURS, K.DESI_CLASSE, N.DESI_NIVEAU, "
           "O.DESI_OPTION, P.NOM, P.POSTNOM, P.PRENOM "
           "FROM COURS_CLASSE X JOIN COURS C ON C.ID_COURS = X.ID_COURS JOIN CLASSE K ON K.N_CLASSE = X.N_CLASSE "
           "JOIN NIVEAU N ON N.CODE_NIVEAU = K.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = K.CODE_OPTION "
           "LEFT JOIN PERSONNEL P ON P.MATRICULE = X.MATRICULE_PROF "
           "WHERE X.ANNEESCO = ? AND N.SECTION = 'SECONDAIRE' AND K.ACTIF = 1")
    params = [annee]
    if n_classe:
        sql += " AND X.N_CLASSE = ?"
        params.append(int(n_classe))
    sql += " ORDER BY N.DESI_NIVEAU COLLATE NOCASE, K.DESI_CLASSE COLLATE NOCASE, C.LIBELLE COLLATE NOCASE"
    return conn.execute(sql, params).fetchall()


class _Calcul:
    """Données de l'année lues en bloc (effectifs, points saisis, périodes ouvertes) pour établir l'état de chaque fiche sans une requête par fiche."""

    def __init__(self, conn, annee, n_classe=None):
        self.conn, self.annee = conn, annee
        self.cours = _cours_de_classe(conn, annee, n_classe)
        self.effectif = {l[0]: l[1] for l in conn.execute("SELECT N_CLASSE, COUNT(*) FROM INSCRIRE WHERE ANNEESCO = ? GROUP BY N_CLASSE", (annee,))}
        self.saisies = {(l[0], l[1], l[2]): (l[3], l[4]) for l in conn.execute(
            "SELECT E.ID_CC, E.ID_PER, E.TYPE, E.MAXIMUM, COUNT(I.MATRICULE) FROM EVALUATION E JOIN COURS_CLASSE X ON X.ID_CC = E.ID_CC "
            "LEFT JOIN NOTE N ON N.ID_EVAL = E.ID_EVAL "
            "LEFT JOIN INSCRIRE I ON I.MATRICULE = N.MATRICULE AND I.ANNEESCO = X.ANNEESCO AND I.N_CLASSE = X.N_CLASSE "
            "WHERE X.ANNEESCO = ? AND E.TYPE IN ('PER','EXA') AND E.NUMERO = 1 GROUP BY E.ID_EVAL", (annee,))}
        self._autorisees = {}

    def autorisees(self, n_classe) -> set:
        if n_classe not in self._autorisees:
            self._autorisees[n_classe] = notes.autorisees(self.conn, self.annee, n_classe)
        return self._autorisees[n_classe]

    def fiche(self, cc, cible) -> dict:
        """État d'un cours de classe pour une période ou un examen du calendrier (`cible` : élément de `calendrier`)."""
        nb = self.effectif.get(cc["N_CLASSE"], 0)
        base = float(cc["MAX_PERIODE"]) if cc["MAX_PERIODE"] else float(config.MAXIMUM_PERIODE)
        maximum_defaut = base * 2 if cible["type"] == "EXA" else base
        maximum, saisis = self.saisies.get((cc["ID_CC"], cible["id_per"], cible["type"]), (maximum_defaut, 0))
        saisis = min(saisis, nb)
        sans_examen = cible["type"] == "EXA" and base >= notes.MAXIMUM_SANS_EXAMEN
        if nb == 0 or sans_examen:
            etat = "SANS_OBJET"
        elif saisis >= nb:
            etat = "COMPLET"
        elif not cc["MATRICULE_PROF"]:
            etat = "SANS_PROF"
        elif saisis == 0:
            etat = "NON_SAISI"
        else:
            etat = "INCOMPLET"
        manquantes = 0 if etat == "SANS_OBJET" else nb - saisis
        return {"id_cc": cc["ID_CC"], "n_classe": cc["N_CLASSE"], "classe": cc["DESI_CLASSE"], "option": cc["DESI_OPTION"] or "",
                "niveau": cc["DESI_NIVEAU"], "cours": cc["COURS"], "matricule_prof": cc["MATRICULE_PROF"] or "",
                "professeur": donnees.nom_complet(cc) if cc["MATRICULE_PROF"] else "", "nb_eleves": nb, "nb_saisies": saisis,
                "nb_manquantes": manquantes, "maximum": _nombre(maximum), "etat": etat, "etat_libelle": ETATS[etat],
                "delai": cible["delai"], "retard": manquantes > 0 and cible["delai"] == "ECHUE",
                "ouverte": cible["cle"] in self.autorisees(cc["N_CLASSE"]), "cle": cible["cle"]}


# ================================================================== 1. consultation : situation par période
def synthese(conn, session, annee=None, cle="", n_classe=None) -> dict:
    """Situation des notes d'une période (ou d'un examen) : pour chaque classe du secondaire, ses cours et leur état."""
    exiger(conn, session, "LECTURE")
    annee = _annee(conn, annee)
    cal = calendrier(conn, annee)
    cle = str(cle or "").strip().upper()
    if cle not in {p["cle"] for p in cal}:
        cle = _periode_par_defaut(cal)
    cible = next((p for p in cal if p["cle"] == cle), None)
    classes, total = {}, {"fiches": 0, "complets": 0, "manquantes": 0, "en_retard": 0}
    if cible:
        calcul = _Calcul(conn, annee, n_classe)
        for cc in calcul.cours:
            f = calcul.fiche(cc, cible)
            k = classes.setdefault(cc["N_CLASSE"], {"n_classe": cc["N_CLASSE"], "designation": cc["DESI_CLASSE"], "option": f["option"],
                                                    "nb_eleves": f["nb_eleves"], "ouverte": f["ouverte"], "cours": [], "manquantes": 0,
                                                    "complets": 0, "a_controler": 0})
            k["cours"].append(f)
            if f["etat"] != "SANS_OBJET":
                k["a_controler"] += 1
                k["complets"] += f["etat"] == "COMPLET"
                k["manquantes"] += f["nb_manquantes"]
        for k in classes.values():
            k["taux"] = round(100 * k["complets"] / k["a_controler"]) if k["a_controler"] else None
            total["fiches"] += k["a_controler"]
            total["complets"] += k["complets"]
            total["manquantes"] += k["manquantes"]
            total["en_retard"] += sum(1 for f in k["cours"] if f["retard"])
    total["taux"] = round(100 * total["complets"] / total["fiches"]) if total["fiches"] else None
    return {"annee": annee, "periodes": cal, "cle": cle, "cible": cible, "classes": list(classes.values()), "total": total,
            "tous_les_etats": ETATS}


# ================================================================== 2. notes manquantes
def manquantes(conn, session, annee=None, matricule_prof="", en_cours=False) -> dict:
    """Fiches dont des élèves n'ont pas de point, pour les périodes ÉCHUES (et celles en cours si `en_cours`), regroupées par professeur.
    Les cours sans professeur forment un groupe à part."""
    exiger(conn, session, "LECTURE")
    annee = _annee(conn, annee)
    delais = ("ECHUE", "EN_COURS") if en_cours else ("ECHUE",)
    cal = [p for p in calendrier(conn, annee) if p["delai"] in delais]
    calcul = _Calcul(conn, annee)
    groupes = {}
    demandees = _ouvertes_par_fiche(conn, annee)
    for cible in cal:
        for cc in calcul.cours:
            f = calcul.fiche(cc, cible)
            if f["nb_manquantes"] <= 0:
                continue
            f["periode"] = cible["libelle"]
            f["demande_ouverte"] = (f["id_cc"], f["cle"], "MANQUANTE") in demandees
            g = groupes.setdefault(f["matricule_prof"], {"matricule": f["matricule_prof"], "nom": f["professeur"] or "Sans professeur attribué",
                                                         "fiches": [], "nb_manquantes": 0})
            g["fiches"].append(f)
            g["nb_manquantes"] += f["nb_manquantes"]
    profs = sorted(groupes.values(), key=lambda g: (g["matricule"] == "", g["nom"].lower()))
    if matricule_prof:
        profs = [g for g in profs if g["matricule"] == matricule_prof]
    return {"annee": annee, "en_cours": bool(en_cours), "professeurs": profs, "matricule_prof": matricule_prof,
            "nb_fiches": sum(len(g["fiches"]) for g in profs), "nb_manquantes": sum(g["nb_manquantes"] for g in profs),
            "nb_a_relancer": sum(1 for g in profs if g["matricule"] for f in g["fiches"] if not f["demande_ouverte"])}


def exporter_manquantes_csv(conn, session, annee=None, matricule_prof="", en_cours=False) -> str:
    r = manquantes(conn, session, annee, matricule_prof, en_cours)
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";")
    w.writerow(["Année", "Professeur", "Classe", "Cours", "Période", "Élèves", "Notes saisies", "Notes manquantes", "Demande ouverte"])
    for g in r["professeurs"]:
        for f in g["fiches"]:
            w.writerow([r["annee"], g["nom"], f["classe"], f["cours"], f["periode"], f["nb_eleves"], f["nb_saisies"], f["nb_manquantes"],
                        "oui" if f["demande_ouverte"] else "non"])
    journaliser(conn, session.id_user, session.login, "NOTES_MANQUANTES_EXPORT", f"{r['annee']} | {r['nb_fiches']} fiche(s)")
    conn.commit()
    return "﻿" + sortie.getvalue()


# ================================================================== 3. fiche d'un cours : les notes saisies
def _cours(conn, session, id_cc) -> object:
    """Ligne du cours de classe, qui doit être du secondaire et d'une section ouverte au compte."""
    try:
        id_cc = int(id_cc)
    except (TypeError, ValueError):
        raise ErreurControle("Cours introuvable.") from None
    l = conn.execute("SELECT ANNEESCO, N_CLASSE FROM COURS_CLASSE WHERE ID_CC = ?", (id_cc,)).fetchone()
    if l:
        for cc in _cours_de_classe(conn, l["ANNEESCO"], l["N_CLASSE"]):
            if cc["ID_CC"] == id_cc:
                sections.exiger_classe(conn, session, cc["N_CLASSE"])
                return cc
    raise ErreurControle("Ce cours n'existe pas, ou sa classe n'appartient pas au secondaire.")


def _cible(conn, cc, cle) -> dict:
    texte = str(cle or "").strip().upper()
    try:
        return notes._cible(conn, cc, texte[1:] if texte.startswith("P") else texte)      # notes.py : « 12 » pour une période, « X3 » pour un examen
    except ErreurNotes as ex:
        raise ErreurControle(str(ex)) from None


def fiche(conn, session, id_cc, cle) -> dict:
    """Notes saisies d'un cours pour une période ou un examen : un point par élève (ou « manquant »), repères et demandes déjà envoyées."""
    exiger(conn, session, "LECTURE")
    cc = _cours(conn, session, id_cc)
    cible = _cible(conn, cc, cle)
    cal = {p["cle"]: p for p in calendrier(conn, cc["ANNEESCO"])}
    calcul = _Calcul(conn, cc["ANNEESCO"], cc["N_CLASSE"])
    etat = calcul.fiche(cc, cal[cible["cle"]])
    e = notes._evaluation_cible(conn, cc, cible)
    points = {n["MATRICULE"]: n["POINTS"] for n in conn.execute("SELECT * FROM NOTE WHERE ID_EVAL = ?", (e["ID_EVAL"],))} if e else {}
    maximum = float(e["MAXIMUM"]) if e else float(etat["maximum"])
    eleves, valeurs = [], []
    for el in notes._eleves(conn, cc):
        p = points.get(el["MATRICULE"])
        if p is not None:
            valeurs.append(float(p))
        eleves.append({"matricule": el["MATRICULE"], "nom": donnees.nom_complet(el), "points": None if p is None else _nombre(p),
                       "pourcentage": None if p is None else round(100 * float(p) / maximum)})
    stats = None
    if valeurs:
        stats = {"moyenne": round(sum(valeurs) / len(valeurs), 1), "moyenne_pct": round(100 * sum(valeurs) / len(valeurs) / maximum),
                 "minimum": _nombre(min(valeurs)), "maximum": _nombre(max(valeurs)),
                 "sous_la_moitie": sum(1 for v in valeurs if v < maximum / 2)}
    journaliser(conn, session.id_user, session.login, "NOTES_CONSULTATION", f"{cc['ANNEESCO']} | {cc['DESI_CLASSE']} | {cc['COURS']} | {cible['libelle']}")
    conn.commit()
    return {"annee": cc["ANNEESCO"], "id_cc": cc["ID_CC"], "classe": cc["DESI_CLASSE"], "n_classe": cc["N_CLASSE"], "cours": cc["COURS"],
            "professeur": etat["professeur"], "matricule_prof": etat["matricule_prof"], "cle": cible["cle"], "periode": cible["libelle"],
            "periode_info": cal[cible["cle"]], "maximum": _nombre(maximum), "eleves": eleves, "stats": stats, "etat": etat,
            "demandes": [d for d in liste_demandes(conn, session, cc["ANNEESCO"], id_cc=cc["ID_CC"], cle=cible["cle"])],
            "peut_demander": peut(conn, session, "AJOUT") and bool(cc["MATRICULE_PROF"])}


# ================================================================== 3b. vérification : élève, classe, cours, période, examen, total semestre
VERIF_MAX_ELEVES = 80
ETATS_CASE = {"OK": "Complet", "MANQUANT": "Manquant", "PARTIEL": "Partiel", "SANS_OBJET": "Sans objet", "A_VENIR": "À venir"}


def liste_classes(conn, annee=None) -> list:
    """Classes actives du secondaire ayant au moins un cours ouvert pour l'année : {n_classe, designation, option}."""
    annee = _annee(conn, annee)
    vues = {}
    for cc in _cours_de_classe(conn, annee):
        vues.setdefault(cc["N_CLASSE"], {"n_classe": cc["N_CLASSE"], "designation": cc["DESI_CLASSE"], "option": cc["DESI_OPTION"] or ""})
    return list(vues.values())


def liste_cours(conn, annee=None, n_classe=None) -> list:
    """Cours ouverts (secondaire) de l'année, d'une classe si précisée : {id_cc, n_classe, classe, cours}."""
    annee = _annee(conn, annee)
    return [{"id_cc": cc["ID_CC"], "n_classe": cc["N_CLASSE"], "classe": cc["DESI_CLASSE"], "cours": cc["COURS"]}
            for cc in _cours_de_classe(conn, annee, n_classe or None)]


def _colonnes_verif(portees, cle) -> list:
    """Colonnes affichées : celle demandée (période P<id>, examen X<id> ou total du semestre S<id>), sinon toutes (sans l'année)."""
    utiles = [p for p in portees if p["type"] in ("periode", "examen", "semestre")]
    if not cle:
        return utiles
    choisie = [p for p in utiles if p["cle"] == cle]
    if not choisie:
        raise ErreurControle("Période, examen ou semestre inconnu pour cette année.")
    return choisie


def _delai_colonne(p, cal) -> str:
    if p["type"] == "semestre":
        fin = cal.get("X" + p["cle"][1:]) or (cal.get(f"P{p['periodes'][-1]}") if p["periodes"] else None)
        return fin["delai"] if fin else "A_VENIR"
    return cal[p["cle"]]["delai"] if p["cle"] in cal else "A_VENIR"


def _case(p, res_cours, cours, portees_par_cle, delai) -> dict:
    """Une case (élève, cours, colonne) : points obtenus, maximum, pourcentage et état (complet, manquant, partiel, sans objet, à venir)."""
    res = res_cours.get(p["cle"])
    sans_examen = cours["max_periode"] is not None and float(cours["max_periode"]) >= notes.MAXIMUM_SANS_EXAMEN
    if p["type"] == "examen" and sans_examen:
        return {"etat": "SANS_OBJET", "obtenu": None, "max": None, "pct": None, "manque": []}
    manque = []
    if p["type"] == "semestre":
        for i in p["periodes"]:
            if f"P{i}" not in res_cours:
                manque.append(portees_par_cle[f"P{i}"]["libelle"])
        x = portees_par_cle.get("X" + p["cle"][1:])
        if x and config.EXAMEN_DANS_SEMESTRE and not sans_examen and x["cle"] not in res_cours:
            manque.append("Examen")
    if res is None:
        etat = "A_VENIR" if delai == "A_VENIR" else "MANQUANT"
        return {"etat": etat, "obtenu": None, "max": None, "pct": None, "manque": manque}
    return {"etat": "PARTIEL" if manque else "OK", "obtenu": res["obtenu"], "max": res["max"], "pct": res["pct"], "manque": manque}


def verifier(conn, session, annee=None, n_classe=None, id_cc=None, recherche_eleve="", cle="") -> dict:
    """Vérification des notes : tableau croisé élèves x cours x (périodes, examens, totaux de semestre) à partir des mêmes calculs que les
    bulletins. Filtres : classe, cours, élève (nom ou matricule), colonne (période, examen ou total du semestre). Il faut au moins une
    classe, un cours ou un élève. Pour chaque élève : une ligne par cours, puis son total toutes matières avec le pourcentage et le rang
    dans la classe. Lecture seule (droit « Lecture »)."""
    exiger(conn, session, "LECTURE")
    annee = _annee(conn, annee)
    cle = str(cle or "").strip().upper()
    recherche = " ".join(str(recherche_eleve or "").split())
    if id_cc:
        cc = _cours(conn, session, id_cc)
        if cc["ANNEESCO"] != annee:
            raise ErreurControle("Ce cours n'appartient pas à l'année choisie.")
        n_classe = cc["N_CLASSE"]
    n_classe = int(n_classe) if str(n_classe or "").strip() else None
    if not (n_classe or recherche):
        raise ErreurControle("Choisissez au moins une classe, un cours ou un élève (nom ou matricule).")
    ouvertes = {k["n_classe"]: k for k in liste_classes(conn, annee)}
    if n_classe:
        if n_classe not in ouvertes:
            raise ErreurControle("Cette classe n'a pas de cours ouvert au secondaire pour cette année.")
        sections.exiger_classe(conn, session, n_classe)
        cibles = [n_classe]
    else:
        like = "%" + recherche.lower() + "%"
        trouvees = conn.execute(
            "SELECT DISTINCT I.N_CLASSE FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE WHERE I.ANNEESCO = ? AND "
            "(LOWER(E.MATRICULE) LIKE ? OR LOWER(COALESCE(E.NOM,'') || ' ' || COALESCE(E.POSTNOM,'') || ' ' || COALESCE(E.PRENOM,'')) LIKE ?)",
            (annee, like, like)).fetchall()
        cibles = [l[0] for l in trouvees if l[0] in ouvertes and sections.peut_classe(conn, session, l[0])]
    cal = {p["cle"]: p for p in calendrier(conn, annee)}
    classes, nb_eleves, nb_cases, nb_manquantes, tronque, colonnes_vues = [], 0, 0, 0, False, []
    for nc in sorted(cibles, key=lambda x: ouvertes[x]["designation"].lower()):
        calc = bulletins.calculer(conn, annee, nc)
        colonnes = _colonnes_verif(calc["portees"], cle)
        if not colonnes_vues:
            colonnes_vues = [{"cle": p["cle"], "type": p["type"], "libelle": p["libelle"], "semestre": p["semestre"],
                              "delai": _delai_colonne(p, cal)} for p in colonnes]
        par_cle = {p["cle"]: p for p in calc["portees"]}
        cours_liste = [c for c in calc["cours"] if not id_cc or c["id_cc"] == int(id_cc)]
        eleves = [e for e in calc["eleves"] if not recherche or recherche.lower() in e["matricule"].lower()
                  or recherche.lower() in e["nom_complet"].lower()]
        lignes_eleves = []
        for e in eleves:
            if nb_eleves >= VERIF_MAX_ELEVES:
                tronque = True
                break
            nb_eleves += 1
            lignes = []
            for c in cours_liste:
                cases = {p["cle"]: _case(p, e["cours"][c["id_cc"]], c, par_cle, _delai_colonne(p, cal)) for p in colonnes}
                nb_cases += sum(1 for x in cases.values() if x["etat"] != "SANS_OBJET")
                nb_manquantes += sum(1 for x in cases.values() if x["etat"] in ("MANQUANT", "PARTIEL"))
                lignes.append({"id_cc": c["id_cc"], "cours": c["libelle"], "professeur": c["professeur"], "cases": cases})
            total = {p["cle"]: {k: e["portees"][p["cle"]][k] for k in ("obtenu", "max", "pct", "rang", "resultat", "complet")} for p in colonnes}
            lignes_eleves.append({"matricule": e["matricule"], "nom": e["nom_complet"], "lignes": lignes, "total": total})
        stats = {p["cle"]: calc["stats"][p["cle"]] for p in colonnes}
        classes.append({"n_classe": nc, "designation": ouvertes[nc]["designation"], "option": ouvertes[nc]["option"], "effectif": len(calc["eleves"]),
                        "eleves": lignes_eleves, "stats": stats})
    journaliser(conn, session.id_user, session.login, "NOTES_VERIFICATION",
                f"{annee} | classe {n_classe or '*'} | cours {id_cc or '*'} | élève {recherche or '*'} | {cle or 'toutes colonnes'}")
    conn.commit()
    return {"annee": annee, "n_classe": n_classe, "id_cc": int(id_cc) if id_cc else None, "eleve": recherche, "cle": cle,
            "colonnes": colonnes_vues, "classes": classes, "nb_eleves": nb_eleves, "tronque": tronque, "max_eleves": VERIF_MAX_ELEVES,
            "nb_cases": nb_cases, "nb_manquantes": nb_manquantes, "etats": ETATS_CASE}


def exporter_verification_csv(conn, session, annee=None, n_classe=None, id_cc=None, recherche_eleve="", cle="") -> str:
    """Export CSV de la vérification : une ligne par élève et par cours, une colonne par période, examen ou total de semestre, puis une ligne
    « Total (tous les cours) » par élève avec le rang."""
    r = verifier(conn, session, annee, n_classe, id_cc, recherche_eleve, cle)
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";")
    w.writerow(["Année", "Classe", "Matricule", "Élève", "Cours"] + [c["libelle"] if c["type"] != "periode" else f"{c['semestre']} - {c['libelle']}"
                                                                      for c in r["colonnes"]] + ["Rang (dernière colonne)"])

    def texte(x):
        if x["etat"] in ("MANQUANT", "A_VENIR", "SANS_OBJET") or x.get("obtenu") is None:
            return {"MANQUANT": "manquant", "A_VENIR": "à venir", "SANS_OBJET": "sans objet"}.get(x.get("etat"), "")
        return f"{x['obtenu']}/{x['max']}" + (" (partiel)" if x["etat"] == "PARTIEL" else "")
    for k in r["classes"]:
        for e in k["eleves"]:
            for l in e["lignes"]:
                w.writerow([r["annee"], k["designation"], e["matricule"], e["nom"], l["cours"]] + [texte(l["cases"][c["cle"]]) for c in r["colonnes"]] + [""])
            tot = [("" if e["total"][c["cle"]]["obtenu"] is None else f"{e['total'][c['cle']]['obtenu']}/{e['total'][c['cle']]['max']}") for c in r["colonnes"]]
            rang = e["total"][r["colonnes"][-1]["cle"]]["rang"] if r["colonnes"] else ""
            w.writerow([r["annee"], k["designation"], e["matricule"], e["nom"], "Total (tous les cours)"] + tot + [rang or ""])
    return "\ufeff" + sortie.getvalue()


# ================================================================== 4. demandes de correction
def _ouvertes_par_fiche(conn, annee) -> set:
    return {(l[0], l[1], l[2]) for l in conn.execute(
        "SELECT ID_CC, CLE, TYPE FROM DEMANDE_CORRECTION WHERE ANNEESCO = ? AND STATUT = 'OUVERTE'", (annee,))}


def _creer(conn, session, cc, cible, type_, motif, matricule=None) -> int:
    cur = conn.execute("INSERT INTO DEMANDE_CORRECTION (ANNEESCO, ID_CC, CLE, MATRICULE, TYPE, MOTIF, DATE_DEMANDE, DEMANDE_PAR, ID_USER) "
                       "VALUES (?,?,?,?,?,?,?,?,?)", (cc["ANNEESCO"], cc["ID_CC"], cible["cle"], matricule or None, type_, motif,
                                                      iso(maintenant()), session.nom_complet or session.login, session.id_user))
    journaliser(conn, session.id_user, session.login, "CORRECTION_DEMANDEE",
                f"{cc['ANNEESCO']} | {cc['DESI_CLASSE']} | {cc['COURS']} | {cible['libelle']} | {TYPES_DEMANDE[type_]}"
                + (f" | {matricule}" if matricule else ""))
    return cur.lastrowid


def demander(conn, session, id_cc, cle, type_, motif="", matricules=()) -> dict:
    """Envoie au professeur du cours une demande de saisie (« MANQUANTE ») ou de correction (« CORRECTION ») pour une fiche. `matricules` vide :
    toute la fiche ; sinon une demande par élève (qui doit être inscrit dans la classe). Droit « Ajout ».
    Retourne {"ids": [...], "fermee": True si la saisie de la période est fermée (le titulaire de la classe doit la rouvrir)}."""
    exiger(conn, session, "AJOUT")
    type_ = str(type_ or "").strip().upper()
    if type_ not in TYPES_DEMANDE:
        raise ErreurControle("Choisissez le type de demande.")
    cc = _cours(conn, session, id_cc)
    cible = _cible(conn, cc, cle)
    if not cc["MATRICULE_PROF"]:
        raise ErreurControle(f"Aucun professeur n'est attribué à « {cc['COURS']} » en {cc['DESI_CLASSE']} : attribuez-en un d'abord "
                             "(Direction des études > Programme des classes).")
    motif = " ".join(str(motif or "").split())
    if type_ == "CORRECTION" and len(motif) < MOTIF_MIN:
        raise ErreurControle("Expliquez au professeur ce qu'il faut corriger (au moins quelques mots).")
    if len(motif) > MOTIF_MAX:
        raise ErreurControle(f"Le motif est trop long (au plus {MOTIF_MAX} caractères).")
    choisis = list(dict.fromkeys(str(m).strip() for m in matricules if str(m).strip()))
    inscrits = {e["MATRICULE"] for e in notes._eleves(conn, cc)}
    for m in choisis:
        if m not in inscrits:
            raise ErreurControle("Un des élèves choisis n'est pas inscrit dans cette classe.")
    deja = {(l[0] or "") for l in conn.execute("SELECT MATRICULE FROM DEMANDE_CORRECTION WHERE ID_CC = ? AND CLE = ? AND TYPE = ? AND STATUT = 'OUVERTE'",
                                              (cc["ID_CC"], cible["cle"], type_))}
    cibles = choisis or [""]
    if type_ == "MANQUANTE":
        etat = _Calcul(conn, cc["ANNEESCO"], cc["N_CLASSE"]).fiche(cc, next(p for p in calendrier(conn, cc["ANNEESCO"]) if p["cle"] == cible["cle"]))
        if etat["etat"] == "SANS_OBJET":
            raise ErreurControle("Cette fiche n'a pas de notes à saisir (aucun élève, ou cours sans examen).")
        if etat["nb_manquantes"] == 0:
            raise ErreurControle("Toutes les notes de cette fiche sont déjà saisies.")
        if not motif:
            motif = f"Points manquants : {etat['nb_manquantes']} élève(s) sur {etat['nb_eleves']} sans note pour « {cible['libelle']} »."
    nouveaux = [m for m in cibles if m not in deja]
    if not nouveaux:
        raise ErreurControle("Une demande ouverte existe déjà pour cette fiche : attendez la réponse du professeur ou annulez-la.")
    with conn:
        ids = [_creer(conn, session, cc, cible, type_, motif, m) for m in nouveaux]
    return {"ids": ids, "fermee": cible["cle"] not in notes.autorisees(conn, cc["ANNEESCO"], cc["N_CLASSE"]), "ignorees": len(cibles) - len(nouveaux)}


def demander_les_manquantes(conn, session, annee=None, matricule_prof="", en_cours=False) -> dict:
    """Envoie une demande « notes manquantes » pour chaque fiche en retard qui n'en a pas déjà une d'ouverte (tous les professeurs, ou un seul).
    Droit « Ajout »."""
    exiger(conn, session, "AJOUT")
    r = manquantes(conn, session, annee, matricule_prof, en_cours)
    creees = 0
    par_id = {x["ID_CC"]: x for x in _cours_de_classe(conn, r["annee"])}
    with conn:
        for g in r["professeurs"]:
            if not g["matricule"]:
                continue
            for f in g["fiches"]:
                if f["demande_ouverte"]:
                    continue
                cc = par_id[f["id_cc"]]
                cible = _cible(conn, cc, f["cle"])
                motif = f"Points manquants : {f['nb_manquantes']} élève(s) sur {f['nb_eleves']} sans note pour « {cible['libelle']} »."
                _creer(conn, session, cc, cible, "MANQUANTE", motif)
                creees += 1
    return {"creees": creees}


def _ligne_demande(conn, l, cal_cache, calcul_cache) -> dict:
    cal = cal_cache.setdefault(l["ANNEESCO"], {p["cle"]: p for p in calendrier(conn, l["ANNEESCO"])})
    periode = cal.get(l["CLE"], {}).get("libelle", l["CLE"])
    manquantes_actuelles = None
    if l["TYPE"] == "MANQUANTE" and l["CLE"] in cal and l["STATUT"] == "OUVERTE":
        calcul = calcul_cache.setdefault(l["ANNEESCO"], _Calcul(conn, l["ANNEESCO"]))
        cc = next((x for x in calcul.cours if x["ID_CC"] == l["ID_CC"]), None)
        if cc:
            manquantes_actuelles = calcul.fiche(cc, cal[l["CLE"]])["nb_manquantes"]
    return {"id": l["ID_DEMANDE"], "annee": l["ANNEESCO"], "id_cc": l["ID_CC"], "cle": l["CLE"], "periode": periode, "classe": l["DESI_CLASSE"],
            "n_classe": l["N_CLASSE"], "cours": l["COURS"], "matricule_prof": l["MATRICULE_PROF"] or "",
            "professeur": donnees.nom_complet({"NOM": l["P_NOM"], "POSTNOM": l["P_POSTNOM"], "PRENOM": l["P_PRENOM"]}) if l["MATRICULE_PROF"] else "",
            "matricule": l["MATRICULE"] or "", "eleve": donnees.nom_complet({"NOM": l["E_NOM"], "POSTNOM": l["E_POSTNOM"], "PRENOM": l["E_PRENOM"]}) if l["MATRICULE"] else "",
            "type": l["TYPE"], "type_libelle": TYPES_DEMANDE[l["TYPE"]], "motif": l["MOTIF"], "statut": l["STATUT"], "statut_libelle": STATUTS[l["STATUT"]],
            "date": _fr(l["DATE_DEMANDE"]), "par": l["DEMANDE_PAR"], "date_traitement": _fr(l["DATE_TRAITEMENT"]) if l["DATE_TRAITEMENT"] else "",
            "traite_par": l["TRAITE_PAR"] or "", "reponse": l["REPONSE"] or "", "manquantes_actuelles": manquantes_actuelles,
            "maintenant_complet": manquantes_actuelles == 0,
            "saisie_ouverte": l["CLE"] in notes.autorisees(conn, l["ANNEESCO"], l["N_CLASSE"])}


_SELECT_DEMANDE = ("SELECT D.*, X.N_CLASSE, X.MATRICULE_PROF, C.LIBELLE AS COURS, K.DESI_CLASSE, P.NOM AS P_NOM, P.POSTNOM AS P_POSTNOM, "
                   "P.PRENOM AS P_PRENOM, E.NOM AS E_NOM, E.POSTNOM AS E_POSTNOM, E.PRENOM AS E_PRENOM "
                   "FROM DEMANDE_CORRECTION D JOIN COURS_CLASSE X ON X.ID_CC = D.ID_CC JOIN COURS C ON C.ID_COURS = X.ID_COURS "
                   "JOIN CLASSE K ON K.N_CLASSE = X.N_CLASSE LEFT JOIN PERSONNEL P ON P.MATRICULE = X.MATRICULE_PROF "
                   "LEFT JOIN ELEVE E ON E.MATRICULE = D.MATRICULE ")


def liste_demandes(conn, session, annee=None, statut="", matricule_prof="", id_cc=None, cle="") -> list:
    """Demandes de l'année (les plus récentes d'abord), filtrables par statut, professeur ou fiche. Droit « Lecture »."""
    exiger(conn, session, "LECTURE")
    annee = _annee(conn, annee)
    sql, params = _SELECT_DEMANDE + "WHERE D.ANNEESCO = ?", [annee]
    if statut in STATUTS:
        sql += " AND D.STATUT = ?"
        params.append(statut)
    if matricule_prof:
        sql += " AND X.MATRICULE_PROF = ?"
        params.append(matricule_prof)
    if id_cc:
        sql += " AND D.ID_CC = ?"
        params.append(int(id_cc))
    if cle:
        sql += " AND D.CLE = ?"
        params.append(str(cle))
    sql += " ORDER BY D.ID_DEMANDE DESC"
    cal, calc = {}, {}
    return [d for d in (_ligne_demande(conn, l, cal, calc) for l in conn.execute(sql, params))
            if sections.peut_classe(conn, session, d["n_classe"])]


def annuler_demande(conn, session, id_demande) -> None:
    """La direction retire une demande encore ouverte (elle reste visible, marquée « Annulée »). Droit « Modification »."""
    exiger(conn, session, "MODIFICATION")
    l = conn.execute(_SELECT_DEMANDE + "WHERE D.ID_DEMANDE = ?", (_entier(id_demande),)).fetchone()
    if not l:
        raise ErreurControle("Demande introuvable.")
    sections.exiger_classe(conn, session, l["N_CLASSE"])
    if l["STATUT"] != "OUVERTE":
        raise ErreurControle("Seule une demande ouverte peut être annulée.")
    with conn:
        conn.execute("UPDATE DEMANDE_CORRECTION SET STATUT = 'ANNULEE', DATE_TRAITEMENT = ?, TRAITE_PAR = ? WHERE ID_DEMANDE = ?",
                     (iso(maintenant()), session.nom_complet or session.login, l["ID_DEMANDE"]))
        journaliser(conn, session.id_user, session.login, "CORRECTION_ANNULEE", f"{l['ANNEESCO']} | {l['DESI_CLASSE']} | {l['COURS']} | n° {l['ID_DEMANDE']}")


def _entier(x) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        raise ErreurControle("Demande introuvable.") from None


# ================================================================== côté professeur : voir et traiter les demandes
def mes_demandes(conn, session) -> dict:
    """Demandes de la direction pour les cours du professeur connecté : les ouvertes, puis les 30 dernières déjà traitées ou annulées."""
    prof = notes._professeur(conn, session)
    lignes = conn.execute(_SELECT_DEMANDE + "WHERE X.MATRICULE_PROF = ? ORDER BY D.ID_DEMANDE DESC", (prof["MATRICULE"],)).fetchall()
    cal, calc = {}, {}
    toutes = [_ligne_demande(conn, l, cal, calc) for l in lignes]
    ouvertes = [d for d in toutes if d["statut"] == "OUVERTE"]
    return {"nb_ouvertes": len(ouvertes), "ouvertes": ouvertes, "historique": [d for d in toutes if d["statut"] != "OUVERTE"][:30]}


def nombre_ouvertes(conn, session) -> int:
    prof = notes._professeur(conn, session)
    return conn.execute("SELECT COUNT(*) FROM DEMANDE_CORRECTION D JOIN COURS_CLASSE X ON X.ID_CC = D.ID_CC "
                        "WHERE X.MATRICULE_PROF = ? AND D.STATUT = 'OUVERTE'", (prof["MATRICULE"],)).fetchone()[0]


def traiter_demande(conn, session, id_demande, reponse="") -> dict:
    """Le professeur marque une demande ouverte de SES cours comme traitée. Une réponse est exigée pour une correction, et pour des notes
    manquantes qui le restent (élève absent, par exemple) : la direction lit cette réponse."""
    prof = notes._professeur(conn, session)
    l = conn.execute(_SELECT_DEMANDE + "WHERE D.ID_DEMANDE = ?", (_entier(id_demande),)).fetchone()
    if not l or l["MATRICULE_PROF"] != prof["MATRICULE"]:
        raise PermissionError("Accès refusé : cette demande ne concerne pas un de vos cours.")
    if l["STATUT"] != "OUVERTE":
        raise ErreurControle("Cette demande n'est plus ouverte.")
    reponse = " ".join(str(reponse or "").split())
    if len(reponse) > MOTIF_MAX:
        raise ErreurControle(f"La réponse est trop longue (au plus {MOTIF_MAX} caractères).")
    restantes = 0
    if l["TYPE"] == "MANQUANTE":
        d = _ligne_demande(conn, l, {}, {})
        restantes = d["manquantes_actuelles"] or 0
    if (l["TYPE"] == "CORRECTION" or restantes) and len(reponse) < 3:
        raise ErreurControle("Écrivez votre réponse à la direction : ce que vous avez corrigé" if l["TYPE"] == "CORRECTION"
                             else f"Il reste {restantes} note(s) manquante(s) : expliquez pourquoi (élève absent, par exemple).")
    with conn:
        conn.execute("UPDATE DEMANDE_CORRECTION SET STATUT = 'TRAITEE', DATE_TRAITEMENT = ?, TRAITE_PAR = ?, REPONSE = ? WHERE ID_DEMANDE = ?",
                     (iso(maintenant()), donnees.nom_complet(prof), reponse or None, l["ID_DEMANDE"]))
        journaliser(conn, session.id_user, session.login, "CORRECTION_TRAITEE",
                    f"{l['ANNEESCO']} | {l['DESI_CLASSE']} | {l['COURS']} | n° {l['ID_DEMANDE']}")
    return {"ok": True}

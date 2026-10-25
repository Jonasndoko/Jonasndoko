"""Direction des études, 4e fonctionnalité : « Gestion des bulletins » (sans interface graphique : testable seule).

La Directrice des études (droit « direction_etudes », section Secondaire et humanitaire) :
  - CONSULTE les bulletins calculés automatiquement (bulletins.calculer, le calcul des titulaires) : vue d'ensemble de toutes les classes,
    résultats d'une classe (rang, pourcentage, mention, résultat, conduite), bulletin d'un élève à l'écran et en PDF ;
  - VÉRIFIE les moyennes et les appréciations : chaque total, pourcentage, mention, résultat et rang est recalculé à part, à partir des
    points enregistrés, puis comparé à ce que le bulletin affiche ;
  - DÉTECTE les erreurs et les données manquantes : calendrier ou cours absents, pas de titulaire, cours sans professeur, points manquants
    ou jamais saisis, conduite non cotée, points hors barème, points d'un élève qui n'est plus inscrit, calculs incohérents. Liste filtrable
    et export CSV.
La direction ne modifie jamais un point ni un bulletin : tout se corrige chez le professeur (voir « Contrôle des notes » pour lui demander).

Règles :
- Seules les classes du secondaire et humanitaire sont concernées ; la section doit être ouverte au compte.
- Droit « Lecture » sur « Direction des études » (relu dans la base à chaque appel). L'Administrateur a tous les droits.
- Une donnée manque seulement pour une période ÉCHUE (ou en cours, si on le demande) ; l'examen d'un cours sans examen n'est pas attendu.
- Gravité « ERREUR » : bulletin faux ou impossible à établir ; « ALERTE » : à vérifier avant de publier.
- Statut d'une classe pour une période, un examen, un semestre ou l'année : BLOQUÉ (au moins une erreur), À VÉRIFIER (alerte ou
  résultat en attente), PRÊT, ou SANS OBJET (aucun élève).
- Les consultations de bulletins et les exports sont inscrits au journal.
"""
import csv
import io
import re

import bulletins
import config
import controle_notes
import donnees
import notes
import sections
from controle_notes import ErreurControle
from database import journaliser

GRAVITES = {"ERREUR": "Erreur", "ALERTE": "À vérifier"}
TYPES = {"PERIODES_NON_DEFINIES": "Calendrier non défini", "SANS_COURS": "Aucun cours ouvert", "SANS_ELEVE": "Aucun élève inscrit",
         "SANS_TITULAIRE": "Pas de titulaire", "SANS_PROFESSEUR": "Cours sans professeur", "AUCUN_POINT": "Aucun point saisi",
         "POINTS_MANQUANTS": "Points manquants", "CONDUITE_MANQUANTE": "Conduite non cotée", "POINT_HORS_BAREME": "Point hors barème",
         "NOTE_NON_INSCRIT": "Point d'un élève non inscrit", "CALCUL_INCOHERENT": "Total ou pourcentage incohérent",
         "MENTION_INCOHERENTE": "Mention incohérente", "RESULTAT_INCOHERENT": "Résultat incohérent", "RANG_INCOHERENT": "Rang incohérent"}
STATUTS = {"BLOQUE": "Bloqué", "A_VERIFIER": "À vérifier", "PRET": "Prêt", "SANS_OBJET": "Sans objet"}
TOLERANCE = 0.011
EXEMPLES = 5


# ================================================================== droits et outils
peut = controle_notes.peut
exiger = controle_notes.exiger
liste_annees = controle_notes.liste_annees


def _classes_visibles(conn, session, annee) -> list:
    return [k for k in controle_notes.liste_classes(conn, annee) if sections.peut_classe(conn, session, k["n_classe"])]


def _classe(conn, session, annee, n_classe) -> dict:
    try:
        n = int(n_classe)
    except (TypeError, ValueError):
        raise ErreurControle("Choisissez une classe.") from None
    k = next((x for x in controle_notes.liste_classes(conn, annee) if x["n_classe"] == n), None)
    if not k:
        raise ErreurControle("Cette classe n'a pas de cours ouvert au secondaire pour cette année.")
    sections.exiger_classe(conn, session, n)
    return k


def _noms(liste) -> str:
    return ", ".join(liste[:EXEMPLES]) + (f" et {len(liste) - EXEMPLES} autre(s)" if len(liste) > EXEMPLES else "")


def _portee_defaut(portees, cal) -> str:
    """La dernière période échue (son semestre si c'est l'examen), sinon celle en cours, sinon la première portée."""
    for delai in ("ECHUE", "EN_COURS"):
        trouvees = [p["cle"] for p in cal if p["delai"] == delai]
        if trouvees:
            cle = trouvees[-1]
            return "S" + cle[1:] if cle.startswith("X") and any(p["cle"] == "S" + cle[1:] for p in portees) else cle
    return portees[0]["cle"] if portees else ""


def _visibles(portees, cle):
    """Clés des portées qui concernent la portée choisie (None : toutes, pour l'année)."""
    p = next((x for x in portees if x["cle"] == cle), None)
    if not p or p["type"] == "annee":
        return None
    if p["type"] in ("periode", "examen"):
        return {cle}
    return {cle, "X" + cle[1:]} | {f"P{i}" for i in p["periodes"]}


def _pertinente(a, visibles) -> bool:
    return visibles is None or a["cle"] == "" or a["cle"] in visibles


# ================================================================== analyse d'une classe : erreurs et données manquantes
def _analyser(conn, annee, k, cal, delais) -> tuple:
    """Calcule la classe (bulletins.calculer) puis cherche les erreurs et les données manquantes. Retourne (calc, anomalies)."""
    nc, classe = k["n_classe"], k["designation"]
    calc = bulletins.calculer(conn, annee, nc)
    portees = {p["cle"]: p for p in calc["portees"]}
    anomalies = []
    delai_de = {p["cle"]: p["delai"] for p in cal}              # `cal` : liste de controle_notes.calendrier

    def ajouter(gravite, code, cle="", cours="", detail="", matricules=(), eleve=""):
        p = portees.get(cle)
        anomalies.append({"gravite": gravite, "gravite_libelle": GRAVITES[gravite], "code": code, "type_libelle": TYPES[code], "n_classe": nc,
                          "classe": classe, "cle": cle, "periode": (p["libelle"] if p else ""), "cours": cours, "detail": detail,
                          "matricules": list(matricules), "eleve": eleve})

    periodes = [p for p in calc["portees"] if p["type"] == "periode"]
    if not periodes:
        ajouter("ERREUR", "PERIODES_NON_DEFINIES", detail="Les semestres et périodes de cette année ne sont pas définis (Direction des études > Années, semestres et périodes).")
        return calc, anomalies
    eleves, cours_liste = calc["eleves"], calc["cours"]
    if not cours_liste:
        ajouter("ERREUR", "SANS_COURS", detail="Aucun cours n'est ouvert dans cette classe pour cette année.")
    if not eleves:
        ajouter("ALERTE", "SANS_ELEVE", detail="Aucun élève n'est inscrit dans cette classe.")
    if not bulletins.titulaire_de(conn, annee, nc):
        ajouter("ALERTE", "SANS_TITULAIRE", detail="Aucun professeur titulaire n'est désigné : les bulletins ne peuvent pas être imprimés par la classe.")
    for c in cours_liste:
        if not c["professeur"]:
            ajouter("ALERTE", "SANS_PROFESSEUR", cours=c["libelle"], detail="Aucun professeur n'est attribué à ce cours.")

    unites = [p for p in calc["portees"] if p["type"] in ("periode", "examen")]
    # --- données manquantes (périodes échues seulement)
    for u in unites:
        if delai_de.get(u["cle"]) not in delais:
            continue
        for c in cours_liste:
            if u["type"] == "examen" and float(c["max_periode"] or config.MAXIMUM_PERIODE) >= notes.MAXIMUM_SANS_EXAMEN:
                continue
            manquants = [e for e in eleves if u["cle"] not in e["cours"].get(c["id_cc"], {})]
            if not manquants or not eleves:
                continue
            if len(manquants) == len(eleves):
                ajouter("ERREUR", "AUCUN_POINT", u["cle"], c["libelle"], f"Aucun point saisi pour les {len(eleves)} élève(s) en « {u['libelle']} ».",
                        [e["matricule"] for e in manquants])
            else:
                ajouter("ALERTE", "POINTS_MANQUANTS", u["cle"], c["libelle"],
                        f"{len(manquants)} élève(s) sur {len(eleves)} sans point : {_noms([e['nom_complet'] for e in manquants])}.",
                        [e["matricule"] for e in manquants], _noms([e["nom_complet"] for e in manquants]))
    for p in periodes:
        if delai_de.get(p["cle"]) not in delais or not eleves:
            continue
        sans = [e for e in eleves if e["portees"][p["cle"]]["obtenu"] is not None and not e["portees"][p["cle"]]["conduite"]]
        if sans:
            ajouter("ALERTE", "CONDUITE_MANQUANTE", p["cle"], detail=f"{len(sans)} élève(s) sans cote de conduite : {_noms([e['nom_complet'] for e in sans])}.",
                    matricules=[e["matricule"] for e in sans], eleve=_noms([e["nom_complet"] for e in sans]))

    # --- points enregistrés : barème et inscriptions, puis recalcul indépendant
    dernieres = {p["periodes"][0] for p in calc["portees"] if p["type"] == "examen"}
    unite_de = {(p["periodes"][0], "X" if p["type"] == "examen" else "P"): p["cle"] for p in unites}
    inscrits = {e["matricule"]: e["nom_complet"] for e in eleves}
    noms_cours = {c["id_cc"]: c["libelle"] for c in cours_liste}
    brut = {}
    for l in conn.execute("SELECT N.MATRICULE, N.POINTS, E.ID_CC, E.ID_PER, E.TYPE, E.MAXIMUM FROM NOTE N JOIN EVALUATION E ON E.ID_EVAL = N.ID_EVAL "
                          "JOIN COURS_CLASSE X ON X.ID_CC = E.ID_CC WHERE X.ANNEESCO = ? AND X.N_CLASSE = ? AND N.POINTS IS NOT NULL", (annee, nc)):
        genre = "X" if l["TYPE"] == "EXA" and l["ID_PER"] in dernieres else "P"
        cle = unite_de.get((l["ID_PER"], genre), "")
        if l["MATRICULE"] not in inscrits:
            ajouter("ALERTE", "NOTE_NON_INSCRIT", cle, noms_cours.get(l["ID_CC"], ""), f"Un point existe pour l'élève {l['MATRICULE']}, qui n'est pas inscrit dans cette classe.",
                    [l["MATRICULE"]])
            continue
        if l["POINTS"] < 0 or l["POINTS"] > l["MAXIMUM"]:
            ajouter("ERREUR", "POINT_HORS_BAREME", cle, noms_cours.get(l["ID_CC"], ""),
                    f"{inscrits[l['MATRICULE']]} : {notes._nombre(l['POINTS'])} points pour un maximum de {notes._nombre(l['MAXIMUM'])}.",
                    [l["MATRICULE"]], inscrits[l["MATRICULE"]])
        d = brut.setdefault((l["MATRICULE"], l["ID_CC"], cle), [0.0, 0])
        d[0] += float(l["POINTS"])
        d[1] += 1
    for e in eleves:
        m = e["matricule"]
        for c in cours_liste:
            for cle in {u["cle"] for u in unites}:
                cellule = e["cours"].get(c["id_cc"], {}).get(cle)
                attendu = brut.get((m, c["id_cc"], cle))
                if (cellule is None) != (attendu is None) or (cellule and abs(cellule["obtenu"] - attendu[0]) > TOLERANCE):
                    ajouter("ERREUR", "CALCUL_INCOHERENT", cle, c["libelle"],
                            f"{e['nom_complet']} : le bulletin affiche {cellule['obtenu'] if cellule else '—'}, les points enregistrés donnent "
                            f"{notes._nombre(attendu[0]) if attendu else '—'}.", [m], e["nom_complet"])

    # --- recalcul des totaux, pourcentages, mentions, résultats et rangs
    for p in calc["portees"]:
        pcts = {}
        for e in eleves:
            t = e["portees"][p["cle"]]
            parts = [e["cours"][c["id_cc"]][p["cle"]] for c in cours_liste if p["cle"] in e["cours"].get(c["id_cc"], {})]
            o, mx = sum(x["obtenu"] for x in parts), sum(x["max"] for x in parts)
            pcts[e["matricule"]] = t["pct"]
            if t["obtenu"] is None:
                if parts:
                    ajouter("ERREUR", "CALCUL_INCOHERENT", p["cle"], detail=f"{e['nom_complet']} : total absent alors que des cours ont des points.", matricules=[e["matricule"]], eleve=e["nom_complet"])
                continue
            pct = round(100.0 * o / mx, 1) if mx else None
            if abs(o - t["obtenu"]) > TOLERANCE or abs(mx - t["max"]) > TOLERANCE or pct is None or abs(pct - t["pct"]) > TOLERANCE or pct > 100.0:
                ajouter("ERREUR", "CALCUL_INCOHERENT", p["cle"], detail=f"{e['nom_complet']} : total affiché {t['obtenu']}/{t['max']} ({t['pct']} %), recalculé "
                        f"{notes._nombre(o)}/{notes._nombre(mx)} ({pct} %).", matricules=[e["matricule"]], eleve=e["nom_complet"])
                continue
            if t["mention"] != (bulletins.mention_pour(t["pct"]) if t["complet"] else ""):
                ajouter("ERREUR", "MENTION_INCOHERENTE", p["cle"], detail=f"{e['nom_complet']} : mention « {t['mention'] or '—'} » pour {t['pct']} %.",
                        matricules=[e["matricule"]], eleve=e["nom_complet"])
            annuel = p["type"] == "annee"
            if not t["complet"]:
                attendu = config.DECISION_ATTENTE
            elif t["pct"] >= config.SEUIL_REUSSITE:
                attendu = config.DECISION_REUSSI if annuel else config.RESULTAT_REUSSI
            else:
                attendu = config.DECISION_ECHEC if annuel else config.RESULTAT_ECHEC
            if t["resultat"] != attendu:
                ajouter("ERREUR", "RESULTAT_INCOHERENT", p["cle"], detail=f"{e['nom_complet']} : résultat « {t['resultat']} » pour {t['pct']} % "
                        f"(attendu : « {attendu} »).", matricules=[e["matricule"]], eleve=e["nom_complet"])
        rangs = bulletins._classer(pcts)
        for e in eleves:
            if e["portees"][p["cle"]]["rang"] != rangs.get(e["matricule"]):
                ajouter("ERREUR", "RANG_INCOHERENT", p["cle"], detail=f"{e['nom_complet']} : rang {e['portees'][p['cle']]['rang']}, attendu {rangs.get(e['matricule'])}.",
                        matricules=[e["matricule"]], eleve=e["nom_complet"])
    anomalies.sort(key=lambda a: (a["gravite"] != "ERREUR", a["cle"] == "", a["type_libelle"], a["cours"]))
    return calc, anomalies


def _contexte(conn, session, annee, cle, en_cours) -> tuple:
    exiger(conn, session, "LECTURE")
    annee = controle_notes._annee(conn, annee)
    cal = controle_notes.calendrier(conn, annee)
    delais = ("ECHUE", "EN_COURS") if en_cours else ("ECHUE",)
    return annee, cal, delais, str(cle or "").strip().upper()


def _statut(erreurs, alertes, attente, effectif) -> str:
    if not effectif:
        return "SANS_OBJET"
    return "BLOQUE" if erreurs else "A_VERIFIER" if (alertes or attente) else "PRET"


def _portees_liste(calc) -> list:
    return [{"cle": p["cle"], "type": p["type"], "libelle": p["libelle"], "semestre": p["semestre"]} for p in calc["portees"]]


def _choisir(calc, cal, cle) -> str:
    cles = [p["cle"] for p in calc["portees"]]
    return cle if cle in cles else _portee_defaut(calc["portees"], cal)


# ================================================================== 1. vue d'ensemble : toutes les classes
def apercu(conn, session, annee=None, cle="", en_cours=False) -> dict:
    """Une ligne par classe pour une période, un examen, un semestre ou l'année (`cle`) : titulaire, effectif, moyenne, taux de réussite,
    résultats en attente, erreurs et alertes, et statut (prêt, à vérifier, bloqué)."""
    annee, cal, delais, cle = _contexte(conn, session, annee, cle, en_cours)
    lignes, portees, total = [], [], {"classes": 0, "pretes": 0, "a_verifier": 0, "bloquees": 0, "erreurs": 0, "alertes": 0}
    for k in _classes_visibles(conn, session, annee):
        calc, anomalies = _analyser(conn, annee, k, cal, delais)
        if not portees and calc["portees"]:
            portees = _portees_liste(calc)
        cle = cle if cle in {p["cle"] for p in calc["portees"]} else (cle if lignes else _choisir(calc, cal, cle))
        visibles = _visibles(calc["portees"], cle)
        mes = [a for a in anomalies if _pertinente(a, visibles)]
        erreurs, alertes = sum(a["gravite"] == "ERREUR" for a in mes), sum(a["gravite"] == "ALERTE" for a in mes)
        st = calc["stats"].get(cle) or {}
        titulaire = bulletins.titulaire_de(conn, annee, k["n_classe"])
        statut = _statut(erreurs, alertes, st.get("en_attente", 0), len(calc["eleves"]))
        lignes.append({"n_classe": k["n_classe"], "designation": k["designation"], "option": k["option"],
                       "titulaire": donnees.nom_complet(titulaire) if titulaire else "", "effectif": len(calc["eleves"]), "nb_cours": len(calc["cours"]),
                       "moyenne": st.get("moyenne"), "taux": st.get("taux"), "reussis": st.get("reussis", 0), "echecs": st.get("echecs", 0),
                       "en_attente": st.get("en_attente", 0), "erreurs": erreurs, "alertes": alertes, "statut": statut, "statut_libelle": STATUTS[statut]})
        total["classes"] += 1
        total["erreurs"] += erreurs
        total["alertes"] += alertes
        total["pretes"] += statut == "PRET"
        total["a_verifier"] += statut == "A_VERIFIER"
        total["bloquees"] += statut == "BLOQUE"
    return {"annee": annee, "cle": cle, "portees": portees, "classes": lignes, "total": total, "en_cours": bool(en_cours), "statuts": STATUTS}


# ================================================================== 2. résultats d'une classe
def resultats_classe(conn, session, annee, n_classe, cle="", en_cours=False) -> dict:
    """Résultats de la classe pour la portée choisie : une ligne par élève (total, pourcentage, rang, mention, résultat, conduite, problèmes
    relevés), moyenne de chaque cours, et erreurs ou données manquantes de la classe pour cette portée."""
    annee, cal, delais, cle = _contexte(conn, session, annee, cle, en_cours)
    k = _classe(conn, session, annee, n_classe)
    calc, anomalies = _analyser(conn, annee, k, cal, delais)
    cle = _choisir(calc, cal, cle)
    visibles = _visibles(calc["portees"], cle)
    mes = [a for a in anomalies if _pertinente(a, visibles)]
    problemes = {}
    for a in mes:
        for m in a["matricules"]:
            problemes[m] = problemes.get(m, 0) + 1
    lignes, cours = [], []
    for e in calc["eleves"]:
        t = e["portees"].get(cle)
        if not t:
            continue
        lignes.append({"matricule": e["matricule"], "nom": e["nom_complet"], "obtenu": t["obtenu"], "max": t["max"], "pct": t["pct"], "rang": t["rang"],
                       "mention": t["mention"], "resultat": t["resultat"], "reussite": t["reussite"], "conduite": t["conduite"],
                       "complet": t["complet"], "problemes": problemes.get(e["matricule"], 0), "_tri": bulletins.ordre_reussite(t)})
    lignes.sort(key=lambda x: (x["_tri"], x["nom"].lower()))
    for x in lignes:
        del x["_tri"]
    for c in calc["cours"]:
        cases = [e["cours"][c["id_cc"]][cle] for e in calc["eleves"] if cle in e["cours"].get(c["id_cc"], {})]
        pcts = [x["pct"] for x in cases if x["pct"] is not None]
        cours.append({"cours": c["libelle"], "professeur": c["professeur"], "notes": len(pcts), "moyenne": round(sum(pcts) / len(pcts), 1) if pcts else None})
    erreurs, alertes = sum(a["gravite"] == "ERREUR" for a in mes), sum(a["gravite"] == "ALERTE" for a in mes)
    st = calc["stats"].get(cle) or {}
    titulaire = bulletins.titulaire_de(conn, annee, k["n_classe"])
    journaliser(conn, session.id_user, session.login, "BULLETINS_CONSULTATION", f"{annee} | {k['designation']} | {cle}")
    conn.commit()
    return {"annee": annee, "classe": {**k, "titulaire": donnees.nom_complet(titulaire) if titulaire else "", "effectif": len(calc["eleves"])},
            "cle": cle, "portees": _portees_liste(calc), "portee": next((p["libelle"] for p in calc["portees"] if p["cle"] == cle), ""),
            "eleves": lignes, "cours": cours, "stats": st, "anomalies": mes, "erreurs": erreurs, "alertes": alertes, "seuil": config.SEUIL_REUSSITE,
            "statut": _statut(erreurs, alertes, st.get("en_attente", 0), len(calc["eleves"])), "en_cours": bool(en_cours)}


# ================================================================== 3. bulletin d'un élève
def bulletin_eleve(conn, session, annee, n_classe, matricule, cle="", en_cours=False) -> dict:
    """Bulletin d'un élève à l'écran : les colonnes du bulletin de la portée (une période ; un semestre = ses périodes, son examen puis le total ;
    l'année = tout), un point par cours et par colonne, puis ses totaux, rang, mention, résultat et conduite, et les problèmes relevés."""
    annee, cal, delais, cle = _contexte(conn, session, annee, cle, en_cours)
    k = _classe(conn, session, annee, n_classe)
    calc, anomalies = _analyser(conn, annee, k, cal, delais)
    e = next((x for x in calc["eleves"] if x["matricule"] == str(matricule or "")), None)
    if not e:
        raise ErreurControle("Cet élève n'est pas inscrit dans cette classe.")
    cle = _choisir(calc, cal, cle)
    colonnes = bulletins.colonnes_bulletin(calc["portees"], cle)
    visibles = _visibles(calc["portees"], cle)
    mes = [a for a in anomalies if _pertinente(a, visibles) and e["matricule"] in a["matricules"]]
    lignes = [{"cours": c["libelle"], "professeur": c["professeur"], "cases": {p["cle"]: e["cours"].get(c["id_cc"], {}).get(p["cle"]) for p in colonnes}}
              for c in calc["cours"]]
    journaliser(conn, session.id_user, session.login, "BULLETINS_CONSULTATION", f"{annee} | {k['designation']} | {cle} | {e['nom_complet']}")
    conn.commit()
    return {"annee": annee, "classe": k, "cle": cle, "portees": _portees_liste(calc), "effectif": len(calc["eleves"]), "seuil": config.SEUIL_REUSSITE,
            "colonnes": [{"cle": p["cle"], "type": p["type"], "libelle": p["libelle"], "semestre": p["semestre"]} for p in colonnes],
            "eleve": {"matricule": e["matricule"], "nom": e["nom_complet"], "sexe": e["sexe"], "naissance": e["naissance"], "lieu_naissance": e["lieu_naissance"]},
            "lignes": lignes, "totaux": {p["cle"]: e["portees"][p["cle"]] for p in colonnes}, "problemes": mes, "en_cours": bool(en_cours)}


def document_pdf(conn, session, annee, n_classe, cle, matricule=None):
    """Bulletin PDF d'un élève (`matricule`) ou de toute la classe, tel que le titulaire l'imprime. Retourne (octets, nom du fichier)."""
    import bulletins_pdf
    exiger(conn, session, "LECTURE")
    annee = controle_notes._annee(conn, annee)
    k = _classe(conn, session, annee, n_classe)
    calc = bulletins.calculer(conn, annee, k["n_classe"])
    titulaire = bulletins.titulaire_de(conn, annee, k["n_classe"])
    calc["titulaire"] = donnees.nom_complet(titulaire) if titulaire else ""
    try:
        colonnes = bulletins.colonnes_bulletin(calc["portees"], str(cle or "").strip().upper())
    except bulletins.ErreurBulletins as ex:
        raise ErreurControle(str(ex)) from None
    eleves = [e for e in calc["eleves"] if not matricule or e["matricule"] == matricule]
    if not eleves:
        raise ErreurControle("Aucun élève à imprimer.")
    octets = bulletins_pdf.bulletins(calc, eleves, colonnes)
    nom = bulletins._nom_fichier("bulletin", k["designation"], annee, colonnes[-1]["cle"], eleves[0]["nom_complet"] if matricule else "")
    journaliser(conn, session.id_user, session.login, "BULLETINS_CONSULTATION_PDF", f"{annee} | {k['designation']} | {colonnes[-1]['libelle']} | {len(eleves)} bulletin(s)")
    conn.commit()
    return octets, re.sub(r"\.pdf$", "", nom) + ".pdf"


# ================================================================== 4. erreurs et données manquantes
def anomalies(conn, session, annee=None, n_classe=None, cle="", gravite="", code="", en_cours=False) -> dict:
    """Erreurs et données manquantes des bulletins : toutes les classes (ou une), pour la portée choisie (`cle` vide : toutes), filtrables par
    gravité (ERREUR, ALERTE) et par type. Les plus graves d'abord."""
    annee, cal, delais, cle = _contexte(conn, session, annee, cle, en_cours)
    cibles = _classes_visibles(conn, session, annee)
    if str(n_classe or "").strip():
        cibles = [_classe(conn, session, annee, n_classe)]
    liste, portees = [], []
    for k in cibles:
        calc, trouvees = _analyser(conn, annee, k, cal, delais)
        if not portees and calc["portees"]:
            portees = _portees_liste(calc)
        visibles = _visibles(calc["portees"], cle) if cle and cle in {p["cle"] for p in calc["portees"]} else None
        liste += [a for a in trouvees if _pertinente(a, visibles)]
    nb = {g: sum(a["gravite"] == g for a in liste) for g in GRAVITES}
    par_type = {}
    for a in liste:
        par_type[a["code"]] = par_type.get(a["code"], 0) + 1
    filtrees = [a for a in liste if (not gravite or a["gravite"] == gravite) and (not code or a["code"] == code)]
    return {"annee": annee, "cle": cle, "portees": portees, "n_classe": int(n_classe) if str(n_classe or "").strip() else None, "gravite": gravite,
            "code": code, "anomalies": filtrees, "nb": nb, "total": len(liste), "par_type": [(c, TYPES[c], n) for c, n in sorted(par_type.items(), key=lambda x: -x[1])],
            "classes": _classes_visibles(conn, session, annee), "gravites": GRAVITES, "types": TYPES, "en_cours": bool(en_cours)}


def exporter_anomalies_csv(conn, session, annee=None, n_classe=None, cle="", gravite="", code="", en_cours=False) -> str:
    r = anomalies(conn, session, annee, n_classe, cle, gravite, code, en_cours)
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";")
    w.writerow(["Année", "Classe", "Gravité", "Type", "Période", "Cours", "Détail"])
    for a in r["anomalies"]:
        w.writerow([r["annee"], a["classe"], a["gravite_libelle"], a["type_libelle"], a["periode"], a["cours"], a["detail"]])
    journaliser(conn, session.id_user, session.login, "BULLETINS_ANOMALIES_EXPORT", f"{r['annee']} | {len(r['anomalies'])} ligne(s)")
    conn.commit()
    return "﻿" + sortie.getvalue()

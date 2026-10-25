"""Direction des études, 5e fonctionnalité : « Statistiques et rapports scolaires » (sans interface graphique : testable seule).

La Directrice des études (droit « direction_etudes », section Secondaire et humanitaire) consulte et imprime, pour une période, un examen, un
semestre ou l'année :
  - les MOYENNES par élève, par classe et par cours (moyenne = pourcentage des points obtenus sur les points possibles : mêmes calculs que les
    bulletins, bulletins.calculer) ;
  - le CLASSEMENT des élèves d'une classe selon les règles de l'école : rang de compétition sur le pourcentage (deux élèves au même
    pourcentage ont le même rang : 1, 2, 2, 4), les réussites d'abord, puis les échecs, puis les résultats « en attente » (bulletins.ordre_reussite) ;
  - les TAUX de réussite et d'échec (réussite : pourcentage >= config.SEUIL_REUSSITE ; taux calculé sur les élèves dont le résultat est décidé,
    les résultats « en attente » sont comptés à part) par classe, par cours et pour l'école ;
  - la COMPARAISON des résultats entre les périodes (périodes, examens, semestres, année) avec l'évolution d'une colonne à la précédente du même
    genre, par classe, par cours ou par élève ;
  - les RAPPORTS sur la performance des enseignants (moyenne et taux de réussite de leurs élèves, saisie des points) et des classes
    (classement des classes).
Tout est en lecture seule. L'impression (page imprimable) ne donne que ce que le compte est autorisé à voir : droit « Lecture » sur « Direction
des études » et classes des sections ouvertes à ce compte. Les consultations et impressions sont inscrites au journal.
"""
import bulletins
import config
import controle_notes
import donnees
import gestion_bulletins
import notes
import sections
from controle_notes import ErreurControle
from database import journaliser

peut = controle_notes.peut
exiger = controle_notes.exiger
liste_annees = controle_notes.liste_annees

NIVEAUX_COMPARAISON = {"classes": "Par classe", "cours": "Par cours (une classe)", "eleves": "Par élève (une classe)"}
GENRES_COLONNE = ("periode", "examen", "semestre", "annee")


# ================================================================== outils
def _pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def _moyenne(valeurs):
    valeurs = [v for v in valeurs if v is not None]
    return round(sum(valeurs) / len(valeurs), 1) if valeurs else None


def _rangs(valeurs: dict) -> dict:
    """Rang de compétition (1, 2, 2, 4) sur des valeurs décroissantes (les None ne sont pas classés)."""
    return bulletins._classer(valeurs)


def _classes_calculees(conn, session, annee, n_classe=None) -> list:
    """[(classe, calc)] des classes visibles du secondaire (une seule si `n_classe`) dont le calendrier est défini."""
    visibles = [k for k in controle_notes.liste_classes(conn, annee) if sections.peut_classe(conn, session, k["n_classe"])]
    if str(n_classe or "").strip():
        try:
            n = int(n_classe)
        except (TypeError, ValueError):
            raise ErreurControle("Choisissez une classe.") from None
        if n not in {k["n_classe"] for k in controle_notes.liste_classes(conn, annee)}:
            raise ErreurControle("Cette classe n'a pas de cours ouvert au secondaire pour cette année.")
        sections.exiger_classe(conn, session, n)
        visibles = [k for k in visibles if k["n_classe"] == n]
    sortie = []
    for k in visibles:
        calc = bulletins.calculer(conn, annee, k["n_classe"])
        if calc["portees"]:
            sortie.append((k, calc))
    return sortie


def _cadre(conn, session, annee, cle):
    exiger(conn, session, "LECTURE")
    annee = controle_notes._annee(conn, annee)
    return annee, controle_notes.calendrier(conn, annee), str(cle or "").strip().upper()


def _portees(calc) -> list:
    return [{"cle": p["cle"], "type": p["type"], "libelle": p["libelle"], "semestre": p["semestre"]} for p in calc["portees"]]


def _sans_examen(c) -> bool:
    return float(c["max_periode"] or config.MAXIMUM_PERIODE) >= notes.MAXIMUM_SANS_EXAMEN


# ================================================================== 1. moyennes, classement, taux, performances (une portée)
def statistiques(conn, session, annee=None, cle="", n_classe=None) -> dict:
    """Tous les chiffres d'une portée (`cle` : P<id>, X<id>, S<id> ou A ; par défaut la plus récente échue).
    Retourne : ecole (totaux), classes (moyenne, taux, classement des classes), cours (moyenne et taux par cours de classe),
    eleves (classement de la classe `n_classe`), enseignants (performance et saisie), portees (choix possibles)."""
    annee, cal, cle = _cadre(conn, session, annee, cle)
    calcs = _classes_calculees(conn, session, annee, n_classe if str(n_classe or "").strip() else None)
    if str(n_classe or "").strip():
        tous = _classes_calculees(conn, session, annee)            # les totaux de l'école portent sur toutes les classes visibles
    else:
        tous = calcs
    if not tous:
        return {"annee": annee, "cle": "", "portee": "", "portees": [], "ecole": None, "classes": [], "cours": [], "eleves": [], "enseignants": [],
                "n_classe": None, "seuil": config.SEUIL_REUSSITE, "classe": None}
    cle = gestion_bulletins._choisir(tous[0][1], cal, cle)
    portee = next(p for p in tous[0][1]["portees"] if p["cle"] == cle)
    prof_de = {c["ID_CC"]: (c["MATRICULE_PROF"] or "") for c in controle_notes._cours_de_classe(conn, annee)}
    seuil = config.SEUIL_REUSSITE
    classes, lignes_cours, profs = [], [], {}
    ecole = {"effectif": 0, "reussis": 0, "echecs": 0, "attente": 0, "pcts": []}
    for k, calc in tous:
        st = calc["stats"][cle]
        decides = st["reussis"] + st["echecs"]
        titulaire = bulletins.titulaire_de(conn, annee, k["n_classe"])
        classes.append({"n_classe": k["n_classe"], "designation": k["designation"], "option": k["option"], "effectif": st["effectif"],
                        "titulaire": donnees.nom_complet(titulaire) if titulaire else "", "moyenne": st["moyenne"], "reussis": st["reussis"],
                        "echecs": st["echecs"], "attente": st["en_attente"], "taux_reussite": _pct(st["reussis"], decides),
                        "taux_echec": _pct(st["echecs"], decides), "rang": None})
        ecole["effectif"] += st["effectif"]
        ecole["reussis"] += st["reussis"]
        ecole["echecs"] += st["echecs"]
        ecole["attente"] += st["en_attente"]
        ecole["pcts"] += [e["portees"][cle]["pct"] for e in calc["eleves"] if e["portees"][cle]["pct"] is not None]
        for c in calc["cours"]:
            cases = [(e["cours"][c["id_cc"]][cle]["pct"]) for e in calc["eleves"] if cle in e["cours"].get(c["id_cc"], {})
                     and e["cours"][c["id_cc"]][cle]["pct"] is not None]
            attendus = 0 if (portee["type"] == "examen" and _sans_examen(c)) else len(calc["eleves"])
            reussis = sum(1 for v in cases if v >= seuil)
            ligne = {"n_classe": k["n_classe"], "classe": k["designation"], "id_cc": c["id_cc"], "cours": c["libelle"], "professeur": c["professeur"],
                     "matricule_prof": prof_de.get(c["id_cc"], ""), "notes": len(cases), "attendues": attendus, "moyenne": _moyenne(cases),
                     "reussis": reussis, "echecs": len(cases) - reussis, "taux_reussite": _pct(reussis, len(cases)),
                     "taux_echec": _pct(len(cases) - reussis, len(cases)), "cases": cases}
            lignes_cours.append(ligne)
            if ligne["matricule_prof"]:
                p = profs.setdefault(ligne["matricule_prof"], {"matricule": ligne["matricule_prof"], "nom": c["professeur"], "cours": [], "cases": [],
                                                              "attendues": 0, "classes": set()})
                p["cours"].append(ligne)
                p["cases"] += cases
                p["attendues"] += attendus
                p["classes"].add(k["designation"])
    rangs = _rangs({c["n_classe"]: c["moyenne"] for c in classes})
    for c in classes:
        c["rang"] = rangs.get(c["n_classe"])
    classes.sort(key=lambda c: (c["rang"] is None, c["rang"] or 0, c["designation"].lower()))
    decides = ecole["reussis"] + ecole["echecs"]
    ecole = {"effectif": ecole["effectif"], "nb_classes": len(classes), "moyenne": _moyenne(ecole["pcts"]), "reussis": ecole["reussis"],
             "echecs": ecole["echecs"], "attente": ecole["attente"], "taux_reussite": _pct(ecole["reussis"], decides),
             "taux_echec": _pct(ecole["echecs"], decides)}
    enseignants = []
    for p in profs.values():
        reussis = sum(1 for v in p["cases"] if v >= seuil)
        enseignants.append({"matricule": p["matricule"], "nom": p["nom"], "nb_cours": len(p["cours"]), "classes": sorted(p["classes"]),
                            "moyenne": _moyenne(p["cases"]), "notes": len(p["cases"]), "attendues": p["attendues"],
                            "taux_saisie": _pct(len(p["cases"]), p["attendues"]), "reussis": reussis, "echecs": len(p["cases"]) - reussis,
                            "taux_reussite": _pct(reussis, len(p["cases"])), "cours": [{k: v for k, v in c.items() if k != "cases"} for c in p["cours"]]})
    rangs = _rangs({e["matricule"]: e["moyenne"] for e in enseignants})
    for e in enseignants:
        e["rang"] = rangs.get(e["matricule"])
    enseignants.sort(key=lambda e: (e["rang"] is None, e["rang"] or 0, e["nom"].lower()))
    cours_liste = [{k: v for k, v in c.items() if k != "cases"} for c in lignes_cours]
    visibles_cours = [c for c in cours_liste if not str(n_classe or "").strip() or c["n_classe"] == int(n_classe)]
    eleves, classe_choisie = [], None
    if str(n_classe or "").strip():
        k, calc = calcs[0]
        classe_choisie = next(c for c in classes if c["n_classe"] == k["n_classe"])
        lignes = []
        for e in calc["eleves"]:
            t = e["portees"][cle]
            lignes.append({"matricule": e["matricule"], "nom": e["nom_complet"], "sexe": e["sexe"], "obtenu": t["obtenu"], "max": t["max"], "pct": t["pct"],
                           "rang": t["rang"], "mention": t["mention"], "resultat": t["resultat"], "reussite": t["reussite"], "conduite": t["conduite"],
                           "complet": t["complet"], "_tri": bulletins.ordre_reussite(t)})
        lignes.sort(key=lambda x: (x["_tri"], x["nom"].lower()))
        for x in lignes:
            del x["_tri"]
        eleves = lignes
    journaliser(conn, session.id_user, session.login, "STATISTIQUES_CONSULTEES", f"{annee} | {portee['libelle']} | classe {n_classe or '*'}")
    conn.commit()
    return {"annee": annee, "cle": cle, "portee": portee["libelle"], "portee_type": portee["type"], "portees": _portees(tous[0][1]), "ecole": ecole,
            "classes": classes, "cours": visibles_cours, "eleves": eleves, "enseignants": enseignants,
            "n_classe": int(n_classe) if str(n_classe or "").strip() else None, "classe": classe_choisie, "seuil": seuil}


# ================================================================== 2. comparaison entre les périodes
def _delta(valeur, precedente):
    return None if valeur is None or precedente is None else round(valeur - precedente, 1)


def _avec_evolution(colonnes, valeurs: dict) -> dict:
    """{cle_colonne: valeur} -> {cle_colonne: {valeur, delta}} ; le delta est l'écart avec la colonne précédente du même genre (période,
    examen, semestre) qui a une valeur."""
    sortie, derniere = {}, {}
    for col in colonnes:
        v = valeurs.get(col["cle"])
        genre = col["type"]
        sortie[col["cle"]] = {"valeur": v, "delta": _delta(v, derniere.get(genre))}
        if v is not None:
            derniere[genre] = v
    return sortie


def comparaison(conn, session, annee=None, niveau="classes", n_classe=None) -> dict:
    """Moyennes (et taux de réussite) de chaque période, examen, semestre et de l'année, avec l'évolution d'une colonne à la précédente du même
    genre. niveau « classes » : une ligne par classe et l'école ; « cours » : les cours d'une classe ; « eleves » : les élèves d'une classe."""
    annee, cal, _cle = _cadre(conn, session, annee, "")
    niveau = niveau if niveau in NIVEAUX_COMPARAISON else "classes"
    if niveau != "classes" and not str(n_classe or "").strip():
        raise ErreurControle("Choisissez une classe pour comparer ses cours ou ses élèves.")
    tous = _classes_calculees(conn, session, annee)
    calcs = _classes_calculees(conn, session, annee, n_classe) if niveau != "classes" else tous
    if not tous:
        return {"annee": annee, "niveau": niveau, "n_classe": None, "colonnes": [], "lignes": [], "ecole": None, "niveaux": NIVEAUX_COMPARAISON}
    colonnes = [c for c in _portees(tous[0][1]) if c["type"] in GENRES_COLONNE]
    lignes = []
    if niveau == "classes":
        for k, calc in tous:
            moy = {c["cle"]: calc["stats"][c["cle"]]["moyenne"] for c in colonnes}
            taux = {c["cle"]: calc["stats"][c["cle"]]["taux"] for c in colonnes}
            lignes.append({"libelle": k["designation"] + (f" · {k['option']}" if k["option"] else ""), "moyennes": _avec_evolution(colonnes, moy),
                           "taux": taux})
        ecole_m, ecole_t = {}, {}
        for c in colonnes:
            pcts = [e["portees"][c["cle"]]["pct"] for _k, calc in tous for e in calc["eleves"] if e["portees"][c["cle"]]["pct"] is not None]
            reussis = sum(calc["stats"][c["cle"]]["reussis"] for _k, calc in tous)
            decides = reussis + sum(calc["stats"][c["cle"]]["echecs"] for _k, calc in tous)
            ecole_m[c["cle"]], ecole_t[c["cle"]] = _moyenne(pcts), _pct(reussis, decides)
        ecole = {"libelle": "Ensemble de l'école", "moyennes": _avec_evolution(colonnes, ecole_m), "taux": ecole_t}
    else:
        k, calc = calcs[0]
        ecole = None
        if niveau == "cours":
            for c in calc["cours"]:
                moy, taux = {}, {}
                for col in colonnes:
                    cases = [e["cours"][c["id_cc"]][col["cle"]]["pct"] for e in calc["eleves"] if col["cle"] in e["cours"].get(c["id_cc"], {})
                             and e["cours"][c["id_cc"]][col["cle"]]["pct"] is not None]
                    moy[col["cle"]] = _moyenne(cases)
                    taux[col["cle"]] = _pct(sum(1 for v in cases if v >= config.SEUIL_REUSSITE), len(cases))
                lignes.append({"libelle": c["libelle"], "sous": c["professeur"], "moyennes": _avec_evolution(colonnes, moy), "taux": taux})
        else:
            for e in sorted(calc["eleves"], key=lambda x: x["nom_complet"].lower()):
                moy = {col["cle"]: e["portees"][col["cle"]]["pct"] for col in colonnes}
                lignes.append({"libelle": e["nom_complet"], "sous": e["matricule"], "moyennes": _avec_evolution(colonnes, moy),
                               "taux": {col["cle"]: e["portees"][col["cle"]]["reussite"] for col in colonnes}})
    # tendance : première et dernière période avec une valeur
    for l in lignes + ([ecole] if ecole else []):
        periodes = [l["moyennes"][c["cle"]]["valeur"] for c in colonnes if c["type"] == "periode" and l["moyennes"][c["cle"]]["valeur"] is not None]
        l["tendance"] = _delta(periodes[-1], periodes[0]) if len(periodes) >= 2 else None
    journaliser(conn, session.id_user, session.login, "STATISTIQUES_COMPARAISON", f"{annee} | {niveau} | classe {n_classe or '*'}")
    conn.commit()
    return {"annee": annee, "niveau": niveau, "n_classe": int(n_classe) if str(n_classe or "").strip() else None, "colonnes": colonnes, "lignes": lignes,
            "ecole": ecole, "niveaux": NIVEAUX_COMPARAISON, "classe": (calcs[0][0]["designation"] if niveau != "classes" else "")}


def classes_disponibles(conn, session, annee=None) -> list:
    annee = controle_notes._annee(conn, annee)
    return [k for k in controle_notes.liste_classes(conn, annee) if sections.peut_classe(conn, session, k["n_classe"])]


def impression(conn, session, vue, annee=None, cle="", n_classe=None, niveau="classes") -> dict:
    """Données d'une page imprimable : la vue (« moyennes », « classement », « reussite », « comparaison », « rapports ») avec les mêmes chiffres
    que l'écran, limitée à ce que le compte peut voir. Inscrite au journal."""
    exiger(conn, session, "LECTURE")
    if vue not in ("moyennes", "classement", "reussite", "comparaison", "rapports"):
        raise ErreurControle("Choisissez ce qu'il faut imprimer.")
    if vue == "classement" and not str(n_classe or "").strip():
        raise ErreurControle("Choisissez la classe dont il faut imprimer le classement.")
    r = {"vue": vue}
    if vue == "comparaison":
        r["c"] = comparaison(conn, session, annee, niveau, n_classe)
        r["annee"] = r["c"]["annee"]
    else:
        r["s"] = statistiques(conn, session, annee, cle, n_classe if vue in ("classement", "moyennes") else None)
        r["annee"] = r["s"]["annee"]
        if vue == "moyennes" and r["s"]["n_classe"]:
            r["s"]["cours"] = [c for c in r["s"]["cours"] if c["n_classe"] == r["s"]["n_classe"]]
    journaliser(conn, session.id_user, session.login, "STATISTIQUES_IMPRIMEES", f"{r['annee']} | {vue} | classe {n_classe or '*'}")
    conn.commit()
    return r

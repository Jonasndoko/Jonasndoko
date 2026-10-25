"""Sous-menu « Préfecture » (Gestion des études et discipline) : six fonctionnalités, sans interface graphique.

  1. Tableau de bord  : vue générale de la situation scolaire (effectifs, présence du jour, classes), alertes et dossiers en attente.
  2. Suivi des élèves : le profil, le dossier scolaire, la classe et l'historique (résultats, présences) de chaque élève.
  3. Situation financière des élèves : frais dus, montants payés et dettes de chaque élève. CONSULTATION SEULE : aucun encaissement,
     aucun reçu, aucune modification (les paiements se font dans « Paiement des frais »).
  4. Décisions et rapports : le Préfet enregistre ses décisions (jamais supprimées : une décision se retire par une annulation motivée)
     et consulte les rapports que la Direction des études et la Direction de discipline lui adressent.
  5. Consultation de la discipline : présences, absences, conduite, décisions disciplinaires du Préfet et rapports de la Direction de
     discipline. CONSULTATION SEULE. Les justificatifs d'absence, les retards et les incidents ne sont pas encore enregistrés dans le
     logiciel : ils apparaîtront ici quand la Direction de discipline pourra les saisir.
  6. Consultation des études : résultats par classe et par période, bulletins des élèves et situation pédagogique (titulaire, cours,
     professeurs, points manquants). CONSULTATION SEULE : le Préfet ne saisit, ne modifie ni ne calcule aucune note (le calcul reste celui
     de bulletins.py, relu à chaque appel).

Règles :
- Le sous-menu ne concerne que la section « Secondaire et humanitaire » : il ne lit jamais une classe ou un élève du primaire.
  Un compte dont les sections ne comprennent pas le Secondaire n'y a pas accès (sections.py).
- Droit exigé : « Lecture » sur « Préfecture » (ou Administrateur), y compris pour les fonctionnalités 5 et 6. La situation financière demande en plus « Lecture » sur
  « Paiement des frais ». Enregistrer une décision demande « Ajout » sur « Préfecture », l'annuler demande « Modification ».
  Un rapport s'envoie avec « Ajout » sur le sous-menu de la direction. Les droits sont relus dans la base à chaque appel : un refus
  donne une PermissionError, jamais une donnée.
- Les consultations (tableau, dossier, situation financière, décisions et rapports, discipline, études, bulletins) et les écritures sont\n  inscrites au journal.
"""
from datetime import date, timedelta

import argent
import bulletins
import config
import donnees
import droits
import notes
import presence_eleves
import presences
import sections
from database import iso, journaliser, maintenant

MODULE = "prefecture"
JOURS_RECENTS = 30                      # fenêtre de l'alerte « absences répétées »
MAX_RESULTATS = 200                     # taille maximale de la liste du suivi

_CLASSE_SECONDAIRE = "N.SECTION = 'SECONDAIRE'"
REFUS_SECTION = "Accès refusé : ce sous-menu concerne seulement la section secondaire et humanitaire."


MAX_DECISIONS = 200                     # taille maximale des listes de décisions et de rapports
MAX_OBJET, MAX_TEXTE = 150, 4000


class ErreurPrefecture(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== droits
def peut(conn, session) -> bool:
    """Lecture sur « Préfecture » (ou Administrateur) ET section Secondaire et humanitaire ouverte au compte."""
    if session is None:
        return False
    if sections.SECONDAIRE not in sections.sections_de(conn, session):
        return False
    return droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, "LECTURE")


def exiger(conn, session):
    if not peut(conn, session):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS['LECTURE']} » "
                              f"sur « {config.MODULES_DROITS[MODULE][0]} » (section secondaire et humanitaire).")


# ================================================================== outils
def _fr(texte) -> str:
    try:
        return date.fromisoformat(str(texte)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(texte or "")


def liste_annees(conn) -> list:
    return [l[0] for l in conn.execute("SELECT ANNEESCO FROM ANNEE_SCO ORDER BY ANNEESCO DESC")]


def _annee(conn, annee):
    """L'année demandée (ou l'année en cours) ; ErreurPrefecture si elle n'existe pas ; None si l'école n'a aucune année."""
    annee = str(annee or "").strip() or donnees.annee_courante(conn)
    if annee and annee not in liste_annees(conn):
        raise ErreurPrefecture("Année scolaire inconnue.")
    return annee


def _classes_de_l_annee(conn, annee) -> list:
    """Classes du secondaire et humanitaire qui ont des élèves inscrits cette année."""
    return conn.execute(
        "SELECT C.N_CLASSE, C.DESI_CLASSE, N.DESI_NIVEAU, O.DESI_OPTION FROM CLASSE C JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
        "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
        f"WHERE {_CLASSE_SECONDAIRE} AND EXISTS (SELECT 1 FROM INSCRIRE I WHERE I.ANNEESCO = ? AND I.N_CLASSE = C.N_CLASSE) "
        "ORDER BY N.DESI_NIVEAU COLLATE NOCASE, C.ANNEE_ETUDE, C.DIVISION, C.DESI_CLASSE", (annee,)).fetchall()


def classes_pour_le_suivi(conn, session, annee=None) -> list:
    """[{n_classe, designation}] : les classes du secondaire et humanitaire de l'année (filtre de la liste du suivi)."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    if not annee:
        return []
    return [{"n_classe": k["N_CLASSE"], "designation": k["DESI_CLASSE"] + (f" · {k['DESI_OPTION']}" if k["DESI_OPTION"] else "")}
            for k in _classes_de_l_annee(conn, annee)]


# ================================================================== 1. tableau de bord
def tableau_de_bord(conn, session, annee=None) -> dict:
    """Situation scolaire du secondaire et humanitaire pour une année : effectifs, présence du jour, une ligne par classe,
    alertes (par gravité) et dossiers en attente. Lecture seule."""
    exiger(conn, session)
    annees = liste_annees(conn)
    annee = _annee(conn, annee)
    vide = {"annee": annee, "annees": annees, "aujourdhui": date.today().strftime("%d/%m/%Y"), "annee_en_cours": False,
            "effectif": {"eleves": 0, "filles": 0, "garcons": 0, "classes": 0},
            "jour": {"presents": 0, "absents": 0, "non_renseignes": 0}, "classes": [], "alertes": [], "absences_repetees": [],
            "en_attente": {"candidatures": 0, "sans_test": 0, "a_affecter": 0}, "resultats": {"reussis": 0, "echecs": 0, "en_attente": 0}}
    if not annee:
        return vide
    aujourdhui = date.today()
    en_cours = annee == donnees.annee_courante(conn)
    travail = en_cours and presences.jour_de_travail(conn, aujourdhui)
    alertes, lignes = [], []
    tot = {"eleves": 0, "filles": 0, "garcons": 0, "presents": 0, "absents": 0, "non_renseignes": 0}
    res = {"reussis": 0, "echecs": 0, "en_attente": 0}
    for k in _classes_de_l_annee(conn, annee):
        n = k["N_CLASSE"]
        nom = k["DESI_CLASSE"] + (f" · {k['DESI_OPTION']}" if k["DESI_OPTION"] else "")
        eleves = conn.execute("SELECT E.MATRICULE, E.SEXE FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE "
                              "WHERE I.ANNEESCO = ? AND I.N_CLASSE = ? AND E.ACTIF = 1", (annee, n)).fetchall()
        if not eleves:
            continue
        jour = presence_eleves._statuts_jour(conn, annee, n, aujourdhui.isoformat()) if en_cours else {}
        p = sum(1 for e in eleves if jour.get(e["MATRICULE"], {}).get("statut") == "P")
        a = sum(1 for e in eleves if jour.get(e["MATRICULE"], {}).get("statut") == "A")
        titulaire = bulletins.titulaire_de(conn, annee, n)
        nb_cours = conn.execute("SELECT COUNT(*) FROM COURS_CLASSE WHERE ANNEESCO = ? AND N_CLASSE = ?", (annee, n)).fetchone()[0]
        sans_prof = conn.execute("SELECT COUNT(*) FROM COURS_CLASSE WHERE ANNEESCO = ? AND N_CLASSE = ? AND MATRICULE_PROF IS NULL",
                                 (annee, n)).fetchone()[0]
        taux = None
        try:
            stats = bulletins.calculer(conn, annee, n)["stats"].get("A")
            if stats:
                res["reussis"] += stats["reussis"]
                res["echecs"] += stats["echecs"]
                res["en_attente"] += stats["en_attente"]
                taux = stats["taux"]
        except Exception:                      # calendrier ou cours pas encore définis : la classe n'a pas de résultat
            pass
        lignes.append({"n_classe": n, "classe": nom, "effectif": len(eleves),
                       "filles": sum(1 for e in eleves if e["SEXE"] == "F"), "garcons": sum(1 for e in eleves if e["SEXE"] == "M"),
                       "presents": p, "absents": a, "non_renseignes": len(eleves) - p - a,
                       "titulaire": donnees.nom_complet(titulaire) if titulaire else "", "cours": nb_cours, "taux_reussite": taux})
        tot["eleves"] += len(eleves)
        tot["filles"] += lignes[-1]["filles"]
        tot["garcons"] += lignes[-1]["garcons"]
        tot["presents"] += p
        tot["absents"] += a
        tot["non_renseignes"] += len(eleves) - p - a
        if not titulaire:
            alertes.append({"gravite": "haute", "texte": f"{nom} : aucun titulaire désigné."})
        if nb_cours == 0:
            alertes.append({"gravite": "haute", "texte": f"{nom} : aucun cours ouvert pour cette année."})
        elif sans_prof:
            alertes.append({"gravite": "moyenne", "texte": f"{nom} : {sans_prof} cours sans professeur."})
        if travail and p + a == 0:
            alertes.append({"gravite": "info", "texte": f"{nom} : la présence du jour n'est pas encore pointée."})
    repetees = _absences_repetees(conn, annee, aujourdhui) if en_cours else []
    if repetees:
        alertes.append({"gravite": "moyenne", "texte": f"{len(repetees)} élève(s) avec au moins {config.SEUIL_ABSENCES_REPETEES} jours "
                                                       f"d'absence ces {JOURS_RECENTS} derniers jours (voir Suivi des élèves)."})
    if tot["absents"]:
        alertes.append({"gravite": "info", "texte": f"{tot['absents']} élève(s) absent(s) aujourd'hui."})
    ordre = {"haute": 0, "moyenne": 1, "info": 2}
    alertes.sort(key=lambda x: ordre[x["gravite"]])
    sans_test, a_affecter, attente = _candidatures_en_attente(conn, annee)
    with conn:
        journaliser(conn, session.id_user, session.login, "PREFECTURE_TABLEAU_OUVERT", annee)
    return {"annee": annee, "annees": annees, "aujourdhui": aujourdhui.strftime("%d/%m/%Y"), "annee_en_cours": en_cours,
            "effectif": {"eleves": tot["eleves"], "filles": tot["filles"], "garcons": tot["garcons"], "classes": len(lignes)},
            "jour": {"presents": tot["presents"], "absents": tot["absents"], "non_renseignes": tot["non_renseignes"]},
            "classes": lignes, "alertes": alertes, "absences_repetees": repetees,
            "en_attente": {"candidatures": attente, "sans_test": sans_test, "a_affecter": a_affecter}, "resultats": res}


def _candidatures_en_attente(conn, annee) -> tuple:
    """(sans résultat de test, validées à affecter, total en attente) : candidatures du secondaire et humanitaire pour l'année."""
    l = conn.execute(
        "SELECT COUNT(*) AS T, SUM(CASE WHEN CA.NOTE_TEST IS NULL AND CA.RESULTAT_TEST IS NULL THEN 1 ELSE 0 END) AS S, "
        "SUM(CASE WHEN CA.RESULTAT_TEST = 'REUSSI' THEN 1 ELSE 0 END) AS R FROM CANDIDATURE CA JOIN CLASSE C ON C.N_CLASSE = CA.N_CLASSE "
        f"JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU WHERE CA.ANNEESCO = ? AND CA.STATUT = 'EN_ATTENTE' AND {_CLASSE_SECONDAIRE}",
        (annee,)).fetchone()
    return (l["S"] or 0, l["R"] or 0, l["T"] or 0)


def _absences_repetees(conn, annee, aujourdhui) -> list:
    """Élèves (actifs, secondaire) ayant au moins SEUIL_ABSENCES_REPETEES jours d'absence sur les JOURS_RECENTS derniers jours.
    Règle de la journée : absent à un seul cours pointé = absent pour le jour."""
    debut = (aujourdhui - timedelta(days=JOURS_RECENTS)).isoformat()
    jours = {}
    for l in conn.execute(
            "SELECT PE.MATRICULE, PE.DATE_COURS FROM PRESENCE_ELEVE PE JOIN COURS_CLASSE X ON X.ID_CC = PE.ID_CC "
            "JOIN CLASSE C ON C.N_CLASSE = X.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
            f"WHERE X.ANNEESCO = ? AND {_CLASSE_SECONDAIRE} AND PE.STATUT = 'A' AND PE.DATE_COURS BETWEEN ? AND ?",
            (annee, debut, aujourdhui.isoformat())):
        jours.setdefault(l["MATRICULE"], set()).add(l["DATE_COURS"])
    resultat = []
    for m, j in jours.items():
        if len(j) < config.SEUIL_ABSENCES_REPETEES:
            continue
        e = conn.execute("SELECT E.*, K.DESI_CLASSE FROM ELEVE E JOIN INSCRIRE I ON I.MATRICULE = E.MATRICULE AND I.ANNEESCO = ? "
                         "JOIN CLASSE K ON K.N_CLASSE = I.N_CLASSE WHERE E.MATRICULE = ? AND E.ACTIF = 1", (annee, m)).fetchone()
        if e:
            resultat.append({"matricule": m, "nom_complet": donnees.nom_complet(e), "classe": e["DESI_CLASSE"], "jours": len(j)})
    resultat.sort(key=lambda x: (-x["jours"], x["nom_complet"].lower()))
    return resultat


# ================================================================== 2. suivi des élèves
def _motif_like(texte) -> str:
    t = str(texte).strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{t}%"


def chercher_eleves(conn, session, annee=None, texte="", n_classe=None) -> dict:
    """Élèves du secondaire et humanitaire inscrits dans l'année, filtrés par nom, postnom, prénom ou matricule et/ou par classe.
    Au plus MAX_RESULTATS lignes (`tronque` indique qu'il y en a davantage)."""
    exiger(conn, session)
    annee = _annee(conn, annee)
    if not annee:
        return {"annee": None, "eleves": [], "tronque": False}
    sql = ("SELECT E.*, C.N_CLASSE, C.DESI_CLASSE, O.DESI_OPTION FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE "
           "JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
           f"LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION WHERE I.ANNEESCO = ? AND {_CLASSE_SECONDAIRE}")
    params = [annee]
    if str(n_classe or "").strip():
        try:
            params.append(int(n_classe))
        except ValueError:
            raise ErreurPrefecture("Classe inconnue.") from None
        sql += " AND C.N_CLASSE = ?"
    if str(texte or "").strip():
        motif = _motif_like(texte)
        sql += (" AND (E.NOM LIKE ? ESCAPE '\\' OR E.POSTNOM LIKE ? ESCAPE '\\' OR E.PRENOM LIKE ? ESCAPE '\\' "
                "OR E.MATRICULE LIKE ? ESCAPE '\\')")
        params += [motif] * 4
    sql += " ORDER BY E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE LIMIT ?"
    lignes = conn.execute(sql, (*params, MAX_RESULTATS + 1)).fetchall()
    return {"annee": annee, "tronque": len(lignes) > MAX_RESULTATS,
            "eleves": [{"matricule": e["MATRICULE"], "nom_complet": donnees.nom_complet(e), "sexe": e["SEXE"] or "",
                        "classe": e["DESI_CLASSE"] + (f" · {e['DESI_OPTION']}" if e["DESI_OPTION"] else ""), "actif": bool(e["ACTIF"])}
                       for e in lignes[:MAX_RESULTATS]]}


def _presences_de(conn, matricule) -> tuple:
    """({année: {'presents', 'absents'}}, [dernières journées d'absence]) d'après les pointages des professeurs."""
    par_jour = {}                                   # (année, date) -> [statut, [cours manqués]]
    for l in conn.execute("SELECT X.ANNEESCO, PE.DATE_COURS, PE.STATUT, C.LIBELLE FROM PRESENCE_ELEVE PE JOIN COURS_CLASSE X ON X.ID_CC = PE.ID_CC "
                          "JOIN COURS C ON C.ID_COURS = X.ID_COURS WHERE PE.MATRICULE = ? ORDER BY PE.DATE_COURS DESC", (matricule,)):
        j = par_jour.setdefault((l["ANNEESCO"], l["DATE_COURS"]), ["P", []])
        if l["STATUT"] == "A":
            j[0] = "A"
            j[1].append(l["LIBELLE"])
    par_annee = {}
    for (annee, _d), (statut, _c) in par_jour.items():
        r = par_annee.setdefault(annee, {"presents": 0, "absents": 0})
        r["presents" if statut == "P" else "absents"] += 1
    absences = [{"date": _fr(d), "cours": sorted(c)} for (a, d), (s, c) in sorted(par_jour.items(), key=lambda x: x[0][1], reverse=True)
                if s == "A"][:10]
    return par_annee, absences


def profil_eleve(conn, session, matricule) -> dict:
    """Le suivi complet d'un élève : profil, classe, dossier scolaire (une ligne par année), résultats de la dernière année du
    secondaire, historique des présences. PermissionError si l'élève n'est pas du secondaire et humanitaire."""
    exiger(conn, session)
    m = str(matricule or "").strip()
    e = conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = ?", (m,)).fetchone()
    if not e:
        raise ErreurPrefecture("Élève introuvable.")
    if sections.section_de_eleve(conn, m) != sections.SECONDAIRE:
        raise PermissionError(REFUS_SECTION)
    m = e["MATRICULE"]
    par_annee, absences = _presences_de(conn, m)
    dossier, detail = [], None
    inscriptions = conn.execute(
        "SELECT I.*, C.DESI_CLASSE, N.DESI_NIVEAU, N.SECTION, O.DESI_OPTION FROM INSCRIRE I JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE "
        "JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
        "WHERE I.MATRICULE = ? ORDER BY I.ANNEESCO DESC", (m,)).fetchall()
    for i in inscriptions:
        ligne = {"annee": i["ANNEESCO"], "classe": i["DESI_CLASSE"], "niveau": i["DESI_NIVEAU"], "option": i["DESI_OPTION"] or "",
                 "statut": i["STATUT"], "inscription": _fr(i["DATE_INSCRIPTION"]) if i["DATE_INSCRIPTION"] else "",
                 "pct": None, "rang": None, "effectif": None, "decision": "", "mention": "",
                 "presences": par_annee.get(i["ANNEESCO"])}
        if i["SECTION"] == sections.SECONDAIRE:
            try:
                calc = bulletins.calculer(conn, i["ANNEESCO"], i["N_CLASSE"])
                el = next((x for x in calc["eleves"] if x["matricule"] == m), None)
                if el:
                    a = el["portees"].get("A")
                    if a:
                        ligne.update(pct=a["pct"], rang=a["rang"], decision=a["resultat"], mention=a["mention"], effectif=len(calc["eleves"]))
                    if detail is None:         # la plus récente inscription du secondaire : détail par période
                        detail = {"annee": i["ANNEESCO"], "classe": i["DESI_CLASSE"], "seuil": config.SEUIL_REUSSITE, "lignes": [
                            {"libelle": p["libelle"], "type": p["type"], "pct": el["portees"][p["cle"]]["pct"],
                             "rang": el["portees"][p["cle"]]["rang"], "resultat": el["portees"][p["cle"]]["resultat"],
                             "conduite": el["portees"][p["cle"]]["conduite"]}
                            for p in calc["portees"] if el["portees"][p["cle"]]["pct"] is not None]}
            except Exception:                  # calendrier ou cours pas encore définis pour cette année
                pass
        dossier.append(ligne)
    actuelle = dossier[0] if dossier else None
    with conn:
        journaliser(conn, session.id_user, session.login, "PREFECTURE_DOSSIER_CONSULTE", m)
    return {"eleve": {"matricule": m, "nom_complet": donnees.nom_complet(e), "sexe": e["SEXE"] or "", "naissance": _fr(e["DATE_NAISSANCE"]),
                      "lieu_naissance": e["LIEU_NAISSANCE"] or "", "nationalite": e["NATIONALITE"] or "", "adresse": e["ADRESSE"] or "",
                      "telephone": e["TELEPHONE"] or "", "tuteur": e["NOM_TUTEUR"] or "", "tel_tuteur": e["TEL_TUTEUR"] or "",
                      "actif": bool(e["ACTIF"])},
            "classe_actuelle": actuelle, "dossier": dossier, "resultats": detail, "absences": absences, "seuil": config.SEUIL_REUSSITE}


# ================================================================== 3. situation financière (consultation seule)
def exiger_finances(conn, session):
    """Lecture sur « Préfecture » ET sur « Paiement des frais » (ou Administrateur) : les montants restent protégés par le droit du module Paiement."""
    exiger(conn, session)
    if not (droits.est_admin(conn, session) or droits.a_droit(conn, session, "paiement", "LECTURE")):
        raise PermissionError(f"Accès refusé : la situation financière demande le droit « {config.LIBELLE_DROITS['LECTURE']} » "
                              f"sur « {config.MODULES_DROITS['paiement'][0]} ».")


def peut_finances(conn, session) -> bool:
    try:
        exiger_finances(conn, session)
        return True
    except PermissionError:
        return False


def _montant(centimes) -> str:
    return argent.formater(centimes)


def _ligne_devises(totaux) -> list:
    """{devise: (dû, payé, reste)} -> [{devise, du, paye, reste}] (montants déjà formatés), triées par devise."""
    return [{"devise": d, "du": _montant(t[0]), "paye": _montant(t[1]), "reste": _montant(t[2]), "reste_brut": t[2]}
            for d, t in sorted(totaux.items())]


def situation_financiere(conn, session, annee=None, texte="", n_classe=None, filtre="") -> dict:
    """Situation financière des élèves du secondaire et humanitaire pour une année : totaux par devise (dû, payé, reste), nombre d'élèves
    en règle et avec dette, puis une ligne par élève. `filtre` : '' (tous), 'dette' (avec dette) ou 'regle' (en règle).
    Un élève a une dette s'il lui reste un montant à payer cette année, ou s'il doit encore quelque chose d'une autre année.
    Consultation seule : aucune écriture, sauf la trace au journal."""
    exiger_finances(conn, session)
    annee = _annee(conn, annee)
    filtre = filtre if filtre in ("dette", "regle") else ""
    vide = {"annee": annee, "annees": liste_annees(conn), "filtre": filtre, "eleves": [], "tronque": False,
            "resume": {"eleves": 0, "en_regle": 0, "avec_dette": 0, "devises": [], "autres_annees": []}}
    if not annee:
        return vide
    sql = ("SELECT E.*, C.N_CLASSE, C.DESI_CLASSE, O.DESI_OPTION FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE "
           "JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
           f"LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION WHERE I.ANNEESCO = ? AND {_CLASSE_SECONDAIRE}")
    params = [annee]
    if str(n_classe or "").strip():
        try:
            params.append(int(n_classe))
        except ValueError:
            raise ErreurPrefecture("Classe inconnue.") from None
        sql += " AND C.N_CLASSE = ?"
    if str(texte or "").strip():
        motif = _motif_like(texte)
        sql += (" AND (E.NOM LIKE ? ESCAPE '\\' OR E.POSTNOM LIKE ? ESCAPE '\\' OR E.PRENOM LIKE ? ESCAPE '\\' "
                "OR E.MATRICULE LIKE ? ESCAPE '\\')")
        params += [motif] * 4
    sql += " ORDER BY E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE"
    total, en_regle, avec_dette = {}, 0, 0
    autres = {}
    lignes = []
    for e in conn.execute(sql, params).fetchall():
        m = e["MATRICULE"]
        du_eleve = donnees.totaux_par_devise(donnees.situation(conn, m, annee, e["N_CLASSE"]))
        anterieures = [(a, d, r) for a, d, r in donnees.dettes(conn, m) if a != annee]
        dette_annee = any(t[2] for t in du_eleve.values())
        dette = dette_annee or bool(anterieures)
        for d, t in du_eleve.items():
            cumul = total.get(d, (0, 0, 0))
            total[d] = (cumul[0] + t[0], cumul[1] + t[1], cumul[2] + t[2])
        for _a, d, r in anterieures:
            autres[d] = autres.get(d, 0) + r
        if dette:
            avec_dette += 1
        else:
            en_regle += 1
        if (filtre == "dette" and not dette) or (filtre == "regle" and dette):
            continue
        lignes.append({"matricule": m, "nom_complet": donnees.nom_complet(e), "actif": bool(e["ACTIF"]),
                       "classe": e["DESI_CLASSE"] + (f" · {e['DESI_OPTION']}" if e["DESI_OPTION"] else ""),
                       "devises": _ligne_devises(du_eleve), "rien_a_payer": not du_eleve, "dette": dette,
                       "autres_annees": [{"annee": a, "devise": d, "reste": _montant(r)} for a, d, r in anterieures]})
    with conn:
        journaliser(conn, session.id_user, session.login, "PREFECTURE_FINANCES_CONSULTEES", annee)
    return {"annee": annee, "annees": vide["annees"], "filtre": filtre, "tronque": len(lignes) > MAX_RESULTATS,
            "eleves": lignes[:MAX_RESULTATS],
            "resume": {"eleves": en_regle + avec_dette, "en_regle": en_regle, "avec_dette": avec_dette,
                       "devises": _ligne_devises(total),
                       "autres_annees": [{"devise": d, "reste": _montant(r)} for d, r in sorted(autres.items())]}}


def finances_eleve(conn, session, matricule, annee=None) -> dict:
    """Le détail financier d'un élève : une ligne par frais (dû, payé, reste, statut), totaux par devise et dettes des autres années."""
    exiger_finances(conn, session)
    m = str(matricule or "").strip()
    e = conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = ?", (m,)).fetchone()
    if not e:
        raise ErreurPrefecture("Élève introuvable.")
    if sections.section_de_eleve(conn, m) != sections.SECONDAIRE:
        raise PermissionError(REFUS_SECTION)
    m = e["MATRICULE"]
    inscriptions = donnees.inscriptions(conn, m)
    annees = [i["ANNEESCO"] for i in inscriptions]
    if str(annee or "").strip() not in annees:
        courante = donnees.annee_courante(conn)
        annee = courante if courante in annees else (annees[0] if annees else "")
    insc = next((i for i in inscriptions if i["ANNEESCO"] == annee), None)
    lignes = donnees.situation(conn, m, annee, insc["N_CLASSE"]) if insc else []
    frais = [{"designation": l.designation, "devise": l.devise, "du": _montant(l.du), "paye": _montant(min(l.paye, l.du)),
              "reste": _montant(l.reste), "statut": l.statut, "mode": l.mode} for l in lignes]
    anterieures = [{"annee": a, "devise": d, "reste": _montant(r)} for a, d, r in donnees.dettes(conn, m) if a != annee]
    with conn:
        journaliser(conn, session.id_user, session.login, "PREFECTURE_FINANCE_ELEVE_CONSULTEE", m)
    return {"eleve": {"matricule": m, "nom_complet": donnees.nom_complet(e), "actif": bool(e["ACTIF"])}, "annee": annee, "annees": annees,
            "classe": (insc["DESI_CLASSE"] + (f" · {insc['DESI_OPTION']}" if insc["DESI_OPTION"] else "")) if insc else "",
            "frais": frais, "totaux": _ligne_devises(donnees.totaux_par_devise(lignes)), "autres_annees": anterieures,
            "en_regle": not any(l.reste for l in lignes) and not anterieures}


# ================================================================== 4. décisions du Préfet et rapports des responsables
def peut_ecrire(conn, session, droit) -> bool:
    """« Ajout » ou « Modification » sur « Préfecture » (ou Administrateur), section secondaire ouverte au compte."""
    return peut(conn, session) and (droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, droit))


def _date_saisie(texte) -> str:
    """'2026-10-19' ou '19/10/2026' -> '2026-10-19'. ErreurPrefecture si ce n'est pas une date, ou si elle est dans le futur."""
    t = str(texte or "").strip()
    try:
        if "/" in t:
            j, mo, a = t.split("/")
            d = date(int(a), int(mo), int(j))
        else:
            d = date.fromisoformat(t)
    except ValueError:
        raise ErreurPrefecture("Date invalide.") from None
    if d > date.today():
        raise ErreurPrefecture("La date ne peut pas être dans le futur.")
    return d.isoformat()


def _texte(valeur, nom, maximum, obligatoire=True) -> str:
    t = " ".join(str(valeur or "").split()) if maximum == MAX_OBJET else str(valeur or "").strip()
    if obligatoire and not t:
        raise ErreurPrefecture(f"{nom} : champ obligatoire.")
    if len(t) > maximum:
        raise ErreurPrefecture(f"{nom} : {maximum} caractères au maximum.")
    return t


def enregistrer_decision(conn, session, date_decision, categorie, objet, detail="", annee=None, matricule="") -> int:
    """Enregistre une décision du Préfet (droit « Ajout »). `matricule` (facultatif) : l'élève concerné, du secondaire et humanitaire.
    Renvoie le numéro de la décision."""
    exiger(conn, session)
    if not peut_ecrire(conn, session, "AJOUT"):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS['AJOUT']} » "
                              f"sur « {config.MODULES_DROITS[MODULE][0]} ».")
    jour = _date_saisie(date_decision)
    if categorie not in dict(config.CATEGORIES_DECISION):
        raise ErreurPrefecture("Catégorie de décision inconnue.")
    objet = _texte(objet, "Objet", MAX_OBJET)
    detail = _texte(detail, "Détail", MAX_TEXTE, obligatoire=False)
    annee = _annee(conn, annee)
    m = str(matricule or "").strip()
    if m:
        e = conn.execute("SELECT MATRICULE FROM ELEVE WHERE MATRICULE = ?", (m,)).fetchone()
        if not e:
            raise ErreurPrefecture("Élève introuvable : vérifiez le matricule.")
        if sections.section_de_eleve(conn, e["MATRICULE"]) != sections.SECONDAIRE:
            raise PermissionError(REFUS_SECTION)
        m = e["MATRICULE"]
    with conn:
        cur = conn.execute("INSERT INTO DECISION_PREFET (DATE_DECISION, CATEGORIE, OBJET, DETAIL, ANNEESCO, MATRICULE, DATE_ENREG, ENREGISTRE_PAR) "
                           "VALUES (?,?,?,?,?,?,?,?)", (jour, categorie, objet, detail, annee or None, m or None,
                                                         iso(maintenant()), session.login))
        numero = cur.lastrowid
        journaliser(conn, session.id_user, session.login, "PREFECTURE_DECISION_ENREGISTREE", f"N° {numero} ({categorie}){' : ' + m if m else ''}")
    return numero


def annuler_decision(conn, session, id_decision, motif) -> None:
    """Retire une décision (droit « Modification ») : elle reste dans la liste, marquée « Annulée », avec le motif, l'auteur et la date."""
    exiger(conn, session)
    if not peut_ecrire(conn, session, "MODIFICATION"):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS['MODIFICATION']} » "
                              f"sur « {config.MODULES_DROITS[MODULE][0]} ».")
    motif = _texte(motif, "Motif de l'annulation", MAX_TEXTE)
    if len(motif) < 5:
        raise ErreurPrefecture("Motif de l'annulation : donnez au moins quelques mots.")
    try:
        numero = int(id_decision)
    except (TypeError, ValueError):
        raise ErreurPrefecture("Décision introuvable.") from None
    d = conn.execute("SELECT STATUT FROM DECISION_PREFET WHERE ID_DECISION = ?", (numero,)).fetchone()
    if not d:
        raise ErreurPrefecture("Décision introuvable.")
    if d["STATUT"] != "EN_VIGUEUR":
        raise ErreurPrefecture("Cette décision est déjà annulée.")
    with conn:
        conn.execute("UPDATE DECISION_PREFET SET STATUT = 'ANNULEE', DATE_ANNUL = ?, ANNULE_PAR = ?, MOTIF_ANNUL = ? WHERE ID_DECISION = ?",
                     (iso(maintenant()), session.login, motif, numero))
        journaliser(conn, session.id_user, session.login, "PREFECTURE_DECISION_ANNULEE", f"N° {numero}")


def liste_decisions(conn, session, annee="", categorie="") -> dict:
    """Décisions du Préfet (les plus récentes d'abord), filtrées par année scolaire et/ou catégorie. Au plus MAX_DECISIONS lignes."""
    exiger(conn, session)
    sql = ("SELECT D.*, E.NOM, E.POSTNOM, E.PRENOM FROM DECISION_PREFET D LEFT JOIN ELEVE E ON E.MATRICULE = D.MATRICULE WHERE 1 = 1")
    params = []
    if str(annee or "").strip():
        sql += " AND D.ANNEESCO = ?"
        params.append(str(annee).strip())
    if categorie in dict(config.CATEGORIES_DECISION):
        sql += " AND D.CATEGORIE = ?"
        params.append(categorie)
    sql += " ORDER BY D.DATE_DECISION DESC, D.ID_DECISION DESC LIMIT ?"
    libelles = dict(config.CATEGORIES_DECISION)
    lignes = conn.execute(sql, (*params, MAX_DECISIONS + 1)).fetchall()
    return {"tronque": len(lignes) > MAX_DECISIONS, "decisions": [
        {"id": d["ID_DECISION"], "date": _fr(d["DATE_DECISION"]), "categorie": libelles.get(d["CATEGORIE"], d["CATEGORIE"]),
         "objet": d["OBJET"], "detail": d["DETAIL"], "annee": d["ANNEESCO"] or "", "matricule": d["MATRICULE"] or "",
         "eleve": donnees.nom_complet(d) if d["MATRICULE"] else "", "annulee": d["STATUT"] == "ANNULEE",
         "enregistre_par": d["ENREGISTRE_PAR"], "date_annulation": _fr(d["DATE_ANNUL"]) if d["DATE_ANNUL"] else "",
         "annule_par": d["ANNULE_PAR"] or "", "motif": d["MOTIF_ANNUL"] or ""} for d in lignes[:MAX_DECISIONS]]}


def _espace_rapport(espace) -> str:
    if espace not in config.FONCTIONNALITES_DIRECTIONS:
        raise ErreurPrefecture("Espace inconnu.")
    return espace


def peut_rapport(conn, session, espace, droit="LECTURE") -> bool:
    """Droit sur le sous-menu de la direction (Lecture pour voir ses rapports, Ajout pour en envoyer), section secondaire ouverte."""
    if session is None or espace not in config.FONCTIONNALITES_DIRECTIONS:
        return False
    if sections.SECONDAIRE not in sections.sections_de(conn, session):
        return False
    return droits.est_admin(conn, session) or droits.a_droit(conn, session, espace, droit)


def deposer_rapport(conn, session, espace, titre, contenu, date_rapport=None, annee=None) -> int:
    """Une direction envoie un rapport au Préfet (droit « Ajout » sur son sous-menu). Renvoie le numéro du rapport."""
    espace = _espace_rapport(espace)
    if not peut_rapport(conn, session, espace, "AJOUT"):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS['AJOUT']} » "
                              f"sur « {config.MODULES_DROITS[espace][0]} ».")
    jour = _date_saisie(date_rapport) if str(date_rapport or "").strip() else date.today().isoformat()
    titre = _texte(titre, "Titre", MAX_OBJET)
    contenu = _texte(contenu, "Rapport", MAX_TEXTE)
    annee = _annee(conn, annee)
    with conn:
        cur = conn.execute("INSERT INTO RAPPORT_RESPONSABLE (ESPACE, TITRE, CONTENU, DATE_RAPPORT, ANNEESCO, DATE_ENREG, ID_USER, AUTEUR) "
                           "VALUES (?,?,?,?,?,?,?,?)", (espace, titre, contenu, jour, annee or None, iso(maintenant()),
                                                         session.id_user, session.nom_complet))
        numero = cur.lastrowid
        journaliser(conn, session.id_user, session.login, "RAPPORT_ENVOYE_AU_PREFET", f"N° {numero} ({espace})")
    return numero


def _rapports(conn, espace="", annee="") -> list:
    sql = "SELECT * FROM RAPPORT_RESPONSABLE WHERE 1 = 1"
    params = []
    if espace in config.FONCTIONNALITES_DIRECTIONS:
        sql += " AND ESPACE = ?"
        params.append(espace)
    if str(annee or "").strip():
        sql += " AND ANNEESCO = ?"
        params.append(str(annee).strip())
    sql += " ORDER BY DATE_RAPPORT DESC, ID_RAPPORT DESC LIMIT ?"
    titres = {cle: titre for cle, titre, _r in config.SOUS_MENUS_ETUDES}
    return [{"id": r["ID_RAPPORT"], "espace": r["ESPACE"], "direction": titres.get(r["ESPACE"], r["ESPACE"]), "titre": r["TITRE"],
             "contenu": r["CONTENU"], "date": _fr(r["DATE_RAPPORT"]), "annee": r["ANNEESCO"] or "", "auteur": r["AUTEUR"]}
            for r in conn.execute(sql, (*params, MAX_DECISIONS)).fetchall()]


def rapports_des_responsables(conn, session, espace="", annee="") -> list:
    """Rapports reçus par le Préfet (lecture seule), du plus récent au plus ancien ; filtrables par direction et par année."""
    exiger(conn, session)
    with conn:
        journaliser(conn, session.id_user, session.login, "PREFECTURE_RAPPORTS_CONSULTES", espace or "toutes les directions")
    return _rapports(conn, espace, annee)


def rapports_de_la_direction(conn, session, espace) -> list:
    """Les rapports déjà envoyés par une direction (Lecture sur son sous-menu)."""
    espace = _espace_rapport(espace)
    if not peut_rapport(conn, session, espace):
        raise PermissionError("Accès refusé : ce sous-menu ne vous est pas ouvert.")
    return _rapports(conn, espace)


# ================================================================== outils des fonctionnalités 5 et 6
def _selection_eleves(conn, annee, texte="", n_classe=None) -> list:
    """Élèves du secondaire et humanitaire inscrits dans l'année (lignes ELEVE + classe), filtrés par nom, postnom, prénom ou matricule
    et/ou par classe, dans l'ordre alphabétique. Sans limite : l'appelant tronque après ses calculs."""
    sql = ("SELECT E.*, C.N_CLASSE, C.DESI_CLASSE, O.DESI_OPTION FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE "
           "JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
           f"LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION WHERE I.ANNEESCO = ? AND {_CLASSE_SECONDAIRE}")
    params = [annee]
    if str(n_classe or "").strip():
        try:
            params.append(int(n_classe))
        except ValueError:
            raise ErreurPrefecture("Classe inconnue.") from None
        sql += " AND C.N_CLASSE = ?"
    if str(texte or "").strip():
        sql += (" AND (E.NOM LIKE ? ESCAPE '\\' OR E.POSTNOM LIKE ? ESCAPE '\\' OR E.PRENOM LIKE ? ESCAPE '\\' "
                "OR E.MATRICULE LIKE ? ESCAPE '\\')")
        params += [_motif_like(texte)] * 4
    sql += " ORDER BY E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE"
    return conn.execute(sql, params).fetchall()


def _eleve_du_secondaire(conn, matricule):
    """La ligne ELEVE ; ErreurPrefecture si le matricule est inconnu, PermissionError si l'élève n'est pas du secondaire et humanitaire."""
    m = str(matricule or "").strip()
    e = conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = ?", (m,)).fetchone()
    if not e:
        raise ErreurPrefecture("Élève introuvable.")
    if sections.section_de_eleve(conn, m) != sections.SECONDAIRE:
        raise PermissionError(REFUS_SECTION)
    return e


def _classe_du_secondaire(conn, n_classe):
    """La ligne de la classe ; ErreurPrefecture si elle est inconnue, PermissionError si elle n'est pas du secondaire et humanitaire."""
    try:
        n = int(n_classe)
    except (TypeError, ValueError):
        raise ErreurPrefecture("Classe inconnue.") from None
    k = conn.execute("SELECT C.N_CLASSE, C.DESI_CLASSE, N.SECTION, O.DESI_OPTION FROM CLASSE C JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
                     "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION WHERE C.N_CLASSE = ?", (n,)).fetchone()
    if not k:
        raise ErreurPrefecture("Classe inconnue.")
    if k["SECTION"] != sections.SECONDAIRE:
        raise PermissionError(REFUS_SECTION)
    return k


def _nom_classe(k) -> str:
    return k["DESI_CLASSE"] + (f" · {k['DESI_OPTION']}" if k["DESI_OPTION"] else "")


def _annee_de_l_eleve(conn, inscriptions, annee) -> str:
    """L'année demandée si l'élève y est inscrit ; sinon l'année en cours si elle y figure, sinon la plus récente."""
    annees = [i["ANNEESCO"] for i in inscriptions]
    if str(annee or "").strip() not in annees:
        courante = donnees.annee_courante(conn)
        annee = courante if courante in annees else (annees[0] if annees else "")
    return str(annee).strip()


# ================================================================== 5. consultation de la discipline
FILTRES_DISCIPLINE = ("absents", "repetees")


def _jours_absence(conn, annee) -> dict:
    """{matricule: {dates}} : journées d'absence de l'année. Règle de la journée : absent à un seul cours pointé = absent pour le jour."""
    jours = {}
    for l in conn.execute("SELECT PE.MATRICULE, PE.DATE_COURS FROM PRESENCE_ELEVE PE JOIN COURS_CLASSE X ON X.ID_CC = PE.ID_CC "
                          "WHERE X.ANNEESCO = ? AND PE.STATUT = 'A'", (annee,)):
        jours.setdefault(l["MATRICULE"], set()).add(l["DATE_COURS"])
    return jours


def _conduites_recentes(conn, annee) -> dict:
    """{matricule: cote} : la conduite de la dernière période renseignée (cote la plus fréquente parmi les cours ; à égalité, la plus faible)."""
    cotes, debuts = {}, {}
    for l in conn.execute("SELECT C.MATRICULE, C.ID_PER, C.COTE, P.DATE_DEBUT FROM CONDUITE C JOIN COURS_CLASSE X ON X.ID_CC = C.ID_CC "
                          "JOIN PERIODE_SCO P ON P.ID_PER = C.ID_PER WHERE X.ANNEESCO = ?", (annee,)):
        cotes.setdefault((l["MATRICULE"], l["ID_PER"]), []).append(l["COTE"])
        debuts[l["ID_PER"]] = l["DATE_DEBUT"]
    derniere = {}
    for (m, per), liste in cotes.items():
        cote = bulletins._conduite_dominante(liste)
        if cote and (m not in derniere or (debuts[per], per) > derniere[m][0]):
            derniere[m] = ((debuts[per], per), cote)
    return {m: v[1] for m, v in derniere.items()}


def consultation_discipline(conn, session, annee=None, texte="", n_classe=None, filtre="") -> dict:
    """Vue de la discipline du secondaire et humanitaire pour une année : chiffres (présents et absents aujourd'hui, absences répétées,
    décisions disciplinaires), une ligne par élève (jours d'absence de l'année et des JOURS_RECENTS derniers jours, conduite de la dernière
    période), décisions disciplinaires du Préfet et rapports de la Direction de discipline. `filtre` : '' (tous), 'absents' (absents
    aujourd'hui) ou 'repetees' (absences répétées). Lecture seule : aucune écriture, sauf la trace au journal."""
    exiger(conn, session)
    annees = liste_annees(conn)
    annee = _annee(conn, annee)
    filtre = filtre if filtre in FILTRES_DISCIPLINE else ""
    vide = {"annee": annee, "annees": annees, "filtre": filtre, "annee_en_cours": False, "aujourdhui": date.today().strftime("%d/%m/%Y"),
            "resume": {"eleves": 0, "presents": 0, "absents": 0, "non_renseignes": 0, "absences_repetees": 0, "decisions": 0},
            "eleves": [], "tronque": False, "decisions": [], "rapports": []}
    if not annee:
        return vide
    aujourdhui = date.today()
    en_cours = annee == donnees.annee_courante(conn)
    debut = (aujourdhui - timedelta(days=JOURS_RECENTS)).isoformat()
    jours = _jours_absence(conn, annee)
    conduites = _conduites_recentes(conn, annee)
    libelles = dict(notes.COTES_CONDUITE)
    statut_jour = {}
    if en_cours:
        for l in conn.execute("SELECT PE.MATRICULE, PE.STATUT FROM PRESENCE_ELEVE PE JOIN COURS_CLASSE X ON X.ID_CC = PE.ID_CC "
                              "WHERE X.ANNEESCO = ? AND PE.DATE_COURS = ?", (annee, aujourdhui.isoformat())):
            if l["STATUT"] == "A":
                statut_jour[l["MATRICULE"]] = "A"
            else:
                statut_jour.setdefault(l["MATRICULE"], "P")
    resume = {"eleves": 0, "presents": 0, "absents": 0, "non_renseignes": 0, "absences_repetees": 0}
    lignes = []
    for e in _selection_eleves(conn, annee, texte, n_classe):
        m = e["MATRICULE"]
        j = jours.get(m, set())
        recents = sum(1 for d in j if debut <= d <= aujourdhui.isoformat())
        jour = statut_jour.get(m, "")
        repetee = recents >= config.SEUIL_ABSENCES_REPETEES
        if e["ACTIF"]:
            resume["eleves"] += 1
            resume["absences_repetees"] += 1 if repetee else 0
            if en_cours:
                resume["presents" if jour == "P" else ("absents" if jour == "A" else "non_renseignes")] += 1
        if (filtre == "absents" and jour != "A") or (filtre == "repetees" and not repetee):
            continue
        cote = conduites.get(m, "")
        lignes.append({"matricule": m, "nom_complet": donnees.nom_complet(e), "actif": bool(e["ACTIF"]),
                       "classe": e["DESI_CLASSE"] + (f" · {e['DESI_OPTION']}" if e["DESI_OPTION"] else ""),
                       "jour": jour, "absences_annee": len(j), "absences_recentes": recents, "repetee": repetee,
                       "conduite": cote, "conduite_libelle": libelles.get(cote, "")})
    decisions = liste_decisions(conn, session, annee, "disciplinaire")["decisions"]
    resume["decisions"] = sum(1 for d in decisions if not d["annulee"])
    with conn:
        journaliser(conn, session.id_user, session.login, "PREFECTURE_DISCIPLINE_CONSULTEE", annee)
    return {"annee": annee, "annees": annees, "filtre": filtre, "annee_en_cours": en_cours, "aujourdhui": aujourdhui.strftime("%d/%m/%Y"),
            "resume": resume, "eleves": lignes[:MAX_RESULTATS], "tronque": len(lignes) > MAX_RESULTATS,
            "decisions": decisions[:10], "rapports": _rapports(conn, "direction_discipline", annee)[:10]}


def discipline_eleve(conn, session, matricule, annee=None) -> dict:
    """La discipline d'un élève pour une année : présences et absences (journées, cours manqués), conduite période par période et décisions
    disciplinaires du Préfet qui le concernent (toutes années). PermissionError si l'élève n'est pas du secondaire et humanitaire."""
    exiger(conn, session)
    e = _eleve_du_secondaire(conn, matricule)
    m = e["MATRICULE"]
    inscriptions = [i for i in donnees.inscriptions(conn, m) if sections.section_de_classe(conn, i["N_CLASSE"]) == sections.SECONDAIRE]
    annee = _annee_de_l_eleve(conn, inscriptions, annee)
    insc = next((i for i in inscriptions if i["ANNEESCO"] == annee), None)
    par_jour = {}                                   # date -> [statut, [cours manqués]]
    for l in conn.execute("SELECT PE.DATE_COURS, PE.STATUT, C.LIBELLE FROM PRESENCE_ELEVE PE JOIN COURS_CLASSE X ON X.ID_CC = PE.ID_CC "
                          "JOIN COURS C ON C.ID_COURS = X.ID_COURS WHERE PE.MATRICULE = ? AND X.ANNEESCO = ? ORDER BY PE.DATE_COURS DESC",
                          (m, annee)):
        j = par_jour.setdefault(l["DATE_COURS"], ["P", []])
        if l["STATUT"] == "A":
            j[0] = "A"
            j[1].append(l["LIBELLE"])
    absences = [{"date": _fr(d), "cours": sorted(c)} for d, (s, c) in sorted(par_jour.items(), reverse=True) if s == "A"]
    cotes = {}
    for l in conn.execute("SELECT C.ID_PER, C.COTE FROM CONDUITE C JOIN COURS_CLASSE X ON X.ID_CC = C.ID_CC "
                          "WHERE X.ANNEESCO = ? AND C.MATRICULE = ?", (annee, m)):
        cotes.setdefault(l["ID_PER"], []).append(l["COTE"])
    libelles = dict(notes.COTES_CONDUITE)
    conduite = []
    for p in conn.execute("SELECT P.ID_PER, P.LIBELLE, S.LIBELLE AS SEM FROM PERIODE_SCO P JOIN SEMESTRE_SCO S ON S.ID_SEM = P.ID_SEM "
                          "WHERE S.ANNEESCO = ? AND S.SECTION = 'SECONDAIRE' ORDER BY P.DATE_DEBUT, P.ID_PER", (annee,)):
        cote = bulletins._conduite_dominante(cotes.get(p["ID_PER"], []))
        conduite.append({"periode": p["LIBELLE"], "semestre": p["SEM"], "cote": cote, "libelle": libelles.get(cote, ""),
                         "nb_cours": len(cotes.get(p["ID_PER"], []))})
    decisions = [{"id": d["ID_DECISION"], "date": _fr(d["DATE_DECISION"]), "objet": d["OBJET"], "detail": d["DETAIL"], "annee": d["ANNEESCO"] or "",
                  "annulee": d["STATUT"] == "ANNULEE"}
                 for d in conn.execute("SELECT * FROM DECISION_PREFET WHERE MATRICULE = ? AND CATEGORIE = 'disciplinaire' "
                                       "ORDER BY DATE_DECISION DESC, ID_DECISION DESC LIMIT ?", (m, MAX_DECISIONS))]
    with conn:
        journaliser(conn, session.id_user, session.login, "PREFECTURE_DISCIPLINE_ELEVE_CONSULTEE", m)
    return {"eleve": {"matricule": m, "nom_complet": donnees.nom_complet(e), "actif": bool(e["ACTIF"])}, "annee": annee,
            "annees": [i["ANNEESCO"] for i in inscriptions], "classe": _nom_classe(insc) if insc else "",
            "jours_presents": sum(1 for s, _c in par_jour.values() if s == "P"), "jours_absents": len(absences),
            "absences": absences[:30], "conduite": conduite, "decisions": decisions}


# ================================================================== 6. consultation des études
def _stats_annuelles(calc) -> dict:
    """Statistiques de l'année scolaire d'une classe (portée « A »), ou des valeurs vides si le calendrier n'est pas défini."""
    return (calc["stats"].get("A") if calc else None) or {"moyenne": None, "taux": None, "reussis": 0, "echecs": 0, "en_attente": 0}


def consultation_etudes(conn, session, annee=None, n_classe=None, cle="") -> dict:
    """Résultats et situation pédagogique du secondaire et humanitaire pour une année. Sans classe : une ligne par classe (titulaire,
    effectif, cours, moyenne et taux de réussite de l'année, points manquants). Avec une classe : ses résultats pour une période, un
    examen, un semestre ou l'année (`cle`, par défaut l'année), ses cours avec leur professeur et la moyenne de la classe, et ce qui
    manque encore. Lecture seule : les points viennent des professeurs, le calcul est celui de bulletins.calculer."""
    exiger(conn, session)
    annees = liste_annees(conn)
    annee = _annee(conn, annee)
    resultat = {"annee": annee, "annees": annees, "classes": [], "detail": None}
    if not annee:
        return resultat
    if str(n_classe or "").strip():
        k = _classe_du_secondaire(conn, n_classe)
        try:
            calc = bulletins.calculer(conn, annee, k["N_CLASSE"])
        except Exception:                      # calendrier ou cours pas encore définis
            calc = None
        portees = calc["portees"] if calc else []
        cles = [p["cle"] for p in portees]
        cle = cle if cle in cles else ("A" if "A" in cles else (cles[0] if cles else ""))
        titulaire = bulletins.titulaire_de(conn, annee, k["N_CLASSE"])
        eleves, cours = [], []
        if calc:
            for e in calc["eleves"]:
                r = e["portees"].get(cle)
                if r:
                    eleves.append({"matricule": e["matricule"], "nom_complet": e["nom_complet"], "obtenu": r["obtenu"], "max": r["max"], "pct": r["pct"],
                                   "rang": r["rang"], "mention": r["mention"], "resultat": r["resultat"], "reussite": r["reussite"],
                                   "conduite": r["conduite"], "_tri": bulletins.ordre_reussite(r)})
            eleves.sort(key=lambda x: (x["_tri"], x["nom_complet"].lower()))
            for x in eleves:
                del x["_tri"]
            for c in calc["cours"]:
                pcts = [e["cours"][c["id_cc"]][cle]["pct"] for e in calc["eleves"] if cle in e["cours"].get(c["id_cc"], {})
                        and e["cours"][c["id_cc"]][cle]["pct"] is not None]
                cours.append({"libelle": c["libelle"], "heures": c["heures"], "professeur": c["professeur"],
                              "moyenne": round(sum(pcts) / len(pcts), 1) if pcts else None, "notes": len(pcts)})
        resultat["detail"] = {
            "n_classe": k["N_CLASSE"], "classe": _nom_classe(k), "titulaire": donnees.nom_complet(titulaire) if titulaire else "",
            "portees": [{"cle": p["cle"], "libelle": p["libelle"], "type": p["type"]} for p in portees], "cle": cle,
            "portee": next((p["libelle"] for p in portees if p["cle"] == cle), ""),
            "stats": calc["stats"].get(cle) if calc and cle else None, "seuil": config.SEUIL_REUSSITE,
            "eleves": eleves, "cours": cours, "effectif": len(eleves),
            "alertes": calc["alertes"][:30] if calc else [], "nb_alertes": len(calc["alertes"]) if calc else 0}
        trace = f"{annee} | {_nom_classe(k)}"
    else:
        for k in _classes_de_l_annee(conn, annee):
            try:
                calc = bulletins.calculer(conn, annee, k["N_CLASSE"])
            except Exception:
                calc = None
            st = _stats_annuelles(calc)
            titulaire = bulletins.titulaire_de(conn, annee, k["N_CLASSE"])
            effectif = len(calc["eleves"]) if calc else conn.execute(
                "SELECT COUNT(*) FROM INSCRIRE WHERE ANNEESCO = ? AND N_CLASSE = ?", (annee, k["N_CLASSE"])).fetchone()[0]
            resultat["classes"].append({
                "n_classe": k["N_CLASSE"], "classe": _nom_classe(k), "effectif": effectif,
                "titulaire": donnees.nom_complet(titulaire) if titulaire else "", "cours": len(calc["cours"]) if calc else 0,
                "sans_professeur": sum(1 for c in calc["cours"] if not c["professeur"]) if calc else 0,
                "moyenne": st["moyenne"], "taux": st["taux"], "reussis": st["reussis"], "echecs": st["echecs"], "en_attente": st["en_attente"],
                "alertes": len(calc["alertes"]) if calc else 0, "calendrier": bool(calc and calc["portees"])})
        trace = annee
    with conn:
        journaliser(conn, session.id_user, session.login, "PREFECTURE_ETUDES_CONSULTEES", trace)
    return resultat


def bulletin_eleve(conn, session, matricule, annee=None) -> dict:
    """Le bulletin d'un élève du secondaire et humanitaire, à l'écran et en lecture seule : ses points dans tous les cours de sa classe,
    période par période, puis ses totaux, pourcentages, rangs, mentions, conduite et résultats. Ne modifie rien."""
    exiger(conn, session)
    e = _eleve_du_secondaire(conn, matricule)
    m = e["MATRICULE"]
    inscriptions = [i for i in donnees.inscriptions(conn, m) if sections.section_de_classe(conn, i["N_CLASSE"]) == sections.SECONDAIRE]
    annee = _annee_de_l_eleve(conn, inscriptions, annee)
    insc = next((i for i in inscriptions if i["ANNEESCO"] == annee), None)
    if not insc:
        raise ErreurPrefecture("Cet élève n'a pas d'inscription au secondaire et humanitaire.")
    try:
        calc = bulletins.calculer(conn, annee, insc["N_CLASSE"])
    except Exception:
        raise ErreurPrefecture("Les résultats de cette classe ne sont pas encore calculables (semestres, périodes ou cours non définis).") from None
    el = next((x for x in calc["eleves"] if x["matricule"] == m), None)
    if not el or not calc["portees"]:
        raise ErreurPrefecture("Aucun résultat à afficher pour cette année : les semestres et périodes ne sont pas encore définis.")
    with conn:
        journaliser(conn, session.id_user, session.login, "PREFECTURE_BULLETIN_CONSULTE", f"{m} | {annee}")
    return {"eleve": {"matricule": m, "nom_complet": donnees.nom_complet(e), "actif": bool(e["ACTIF"])}, "annee": annee,
            "annees": [i["ANNEESCO"] for i in inscriptions], "classe": _nom_classe(insc), "n_classe": insc["N_CLASSE"],
            "titulaire": (lambda t: donnees.nom_complet(t) if t else "")(bulletins.titulaire_de(conn, annee, insc["N_CLASSE"])),
            "seuil": config.SEUIL_REUSSITE, "effectif": len(calc["eleves"]),
            "colonnes": [{"cle": p["cle"], "type": p["type"], "libelle": p["libelle"], "semestre": p["semestre"]} for p in calc["portees"]],
            "cours": [{"libelle": c["libelle"], "professeur": c["professeur"], "cotes": el["cours"].get(c["id_cc"], {})} for c in calc["cours"]],
            "totaux": el["portees"]}

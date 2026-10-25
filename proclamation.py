"""Proclamation des résultats (secondaire et humanitaire), sans interface graphique : testable seule.

Circuit, pour une classe et une période, un semestre ou l'année (`cle` : P<id>, X<id>, S<id> ou A) :
  1. AUTORISATION  : la Directrice des études autorise le titulaire de la classe (statut AUTORISEE).
  2. CONSULTATION  : elle consulte d'abord les bulletins calculés (le titulaire, lui, peut toujours les consulter : c'est lui qui lance
                     le calcul automatique des points).
  3. FRAIS EXIGÉS  : elle choisit les frais qu'un élève doit avoir payés pour être « en ordre » : un ou plusieurs frais (frais scolaire
                     obligatoire, autres frais si nécessaire), chacun jusqu'à une TRANCHE demandée ou en TOTALITÉ. Le logiciel calcule
                     qui est en ordre d'après les paiements enregistrés ; elle ne coche jamais « en ordre » à la main. Elle ne voit
                     aucun montant : seulement « en ordre » ou les frais qui manquent.
  4. VALIDATION    : elle valide les bulletins des élèves en ordre : ce sont eux qui seront proclamés. Elle ne peut valider qu'un élève
                     en ordre. Puis elle SOUMET la proclamation au Préfet (statut TRANSMISE) : elle ne peut plus y toucher.
  5. PRÉFET        : il consulte les validations, peut CHANGER la décision de la Directrice pour un élève (motif obligatoire, journalisé),
                     puis CONFIRME la proclamation (statut CONFIRMEE).
  6. TITULAIRE     : il n'IMPRIME que les bulletins VALIDÉS d'une proclamation CONFIRMÉE (bulletins.document_pdf). Les autres, il ne peut
                     que les consulter. Même règle pour la liste des résultats et la proclamation de l'année : seuls les élèves validés y
                     figurent.

Droits (relus dans la base à chaque appel ; refus = PermissionError) : Directrice = « Direction des études » (Lecture pour consulter,
Modification pour autoriser, choisir les frais, valider et soumettre) ; Préfet = « Préfecture » (Lecture pour consulter, Modification
pour changer une décision et confirmer). L'Administrateur a tous les droits. Section Secondaire et humanitaire seulement.
Chaque étape est inscrite au journal (qui, quand, quelle classe, quel élève, quels frais ; le motif du Préfet).
"""
import config
import controle_notes
import donnees
import droits
import bulletins
import sections
from database import iso, journaliser, maintenant

DIRECTION, PREFECTURE = "direction_etudes", "prefecture"
STATUTS = {"AUTORISEE": "Validation en cours (Directrice des études)", "TRANSMISE": "Soumise au Préfet",
           "CONFIRMEE": "Proclamation confirmée par le Préfet"}
MIN_MOTIF, MAX_MOTIF = 3, 300


class ErreurProclamation(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== droits
def peut_direction(conn, session, droit="LECTURE") -> bool:
    return controle_notes.peut(conn, session, droit)


def peut_prefet(conn, session, droit="LECTURE") -> bool:
    if session is None or sections.SECONDAIRE not in sections.sections_de(conn, session):
        return False
    return droits.est_admin(conn, session) or droits.a_droit(conn, session, PREFECTURE, droit)


def _exiger(conn, session, module, droit):
    ok = peut_direction(conn, session, droit) if module == DIRECTION else peut_prefet(conn, session, droit)
    if not ok:
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS[droit]} » "
                              f"sur « {config.MODULES_DROITS[module][0]} » (section secondaire et humanitaire).")


def _exiger_lecture(conn, session):
    if not (peut_direction(conn, session) or peut_prefet(conn, session)):
        raise PermissionError("Accès refusé : la proclamation est réservée à la Directrice des études et au Préfet.")


# ================================================================== outils
def _classe(conn, session, annee, n_classe) -> dict:
    annee = controle_notes._annee(conn, annee)
    try:
        n = int(n_classe)
    except (TypeError, ValueError):
        raise ErreurProclamation("Choisissez une classe.") from None
    k = next((x for x in controle_notes.liste_classes(conn, annee) if x["n_classe"] == n), None)
    if not k:
        raise ErreurProclamation("Cette classe n'a pas de cours ouvert au secondaire pour cette année.")
    sections.exiger_classe(conn, session, n)
    return dict(k, annee=annee)


def _portee(conn, annee, n_classe, cle) -> dict:
    cle = str(cle or "").strip().upper()
    p = next((x for x in bulletins._portees(conn, annee, sections.section_de_classe(conn, n_classe)) if x["cle"] == cle), None)
    if not p:
        raise ErreurProclamation("Choisissez la période, le semestre ou l'année.")
    return p


def _ligne(conn, annee, n_classe, cle):
    return conn.execute("SELECT * FROM PROCLAMATION WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ?", (annee, n_classe, cle)).fetchone()


def _exiger_ligne(conn, annee, n_classe, cle, *statuts):
    l = _ligne(conn, annee, n_classe, cle)
    if not l:
        raise ErreurProclamation("Le titulaire n'est pas encore autorisé pour cette classe et cette période : autorisez-le d'abord.")
    if statuts and l["STATUT"] not in statuts:
        raise ErreurProclamation(f"Cette étape n'est plus possible : la proclamation est « {STATUTS[l['STATUT']].lower()} ».")
    return l


def _libelle(p) -> str:
    return p["libelle"] if p["type"] != "periode" else f"{p['semestre']} - {p['libelle']}"


def _tracer(conn, session, action, detail):
    journaliser(conn, session.id_user, session.login, action, detail)


def _criteres(conn, annee, n_classe, cle) -> list:
    return [{"codtf": l["CODTF"], "designation": l["DESITF"], "tranche": l["TRANCHE"]} for l in conn.execute(
        "SELECT P.CODTF, F.DESITF, P.TRANCHE FROM PROCLAMATION_FRAIS P JOIN TYPE_FRAIS F ON F.CODTF = P.CODTF "
        "WHERE P.ANNEESCO = ? AND P.N_CLASSE = ? AND P.CLE = ? ORDER BY F.DESITF COLLATE NOCASE", (annee, n_classe, cle))]


def frais_disponibles(conn, session, annee, n_classe) -> list:
    """Frais que la Directrice peut exiger pour cette classe : [{codtf, designation, par_tranche, nb_tranches}] (pas les frais d'inscription,
    pas les frais réservés à une autre année d'étude). Aucun montant n'est donné."""
    _exiger_lecture(conn, session)
    k = _classe(conn, session, annee, n_classe)
    cible = donnees.cible_de_classe(conn, k["n_classe"])
    resultat = []
    for f in conn.execute("SELECT * FROM TYPE_FRAIS WHERE POUR_INSCRIPTION = 0 AND ACTIF = 1 ORDER BY DESITF COLLATE NOCASE"):
        if f["CLASSE_CIBLE"] and f["CLASSE_CIBLE"] != cible:
            continue
        tarif = conn.execute("SELECT TRANCHES FROM TARIF WHERE CODTF = ? AND ANNEESCO = ? AND N_CLASSE = ?",
                             (f["CODTF"], k["annee"], k["n_classe"])).fetchone()
        tranches = donnees.lire_tranches(tarif["TRANCHES"] if tarif else f["TRANCHES"]) if f["PAR_TRANCHE"] else ()
        resultat.append({"codtf": f["CODTF"], "designation": f["DESITF"], "par_tranche": bool(f["PAR_TRANCHE"]),
                         "nb_tranches": len(tranches or ())})
    return resultat


def en_ordre(conn, matricule, annee, n_classe, criteres) -> tuple:
    """(en_ordre, [frais qui manquent]) pour un élève. Un frais qui n'est pas dû par cet élève (pas de tarif pour sa classe, frais
    réservé à une autre année d'étude) ne l'empêche pas d'être en ordre. Tranche demandée : payé au moins jusqu'à cette tranche (la
    dernière si elle dépasse le nombre de tranches) ; vide : la totalité. Tranches mal définies : jamais « en ordre » (non évaluable)."""
    lignes = {l.codtf: l for l in donnees.situation(conn, matricule, annee, n_classe)}
    manques = []
    for c in criteres:
        l = lignes.get(c["codtf"])
        if l is None:
            continue
        if c["tranche"] is None:
            ok, texte = l.paye >= l.du, f"{l.designation} (totalité)"
        elif not l.paliers:
            ok, texte = False, f"{l.designation} (tranches mal définies)"
        else:
            palier = l.paliers[min(int(c["tranche"]), len(l.paliers)) - 1]
            ok, texte = l.paye >= palier, f"{l.designation} (tranche {c['tranche']})"
        if not ok:
            manques.append(texte)
    return (not manques), manques


# ================================================================== consultation
def apercu(conn, session, annee, n_classe, cle) -> dict:
    """La proclamation d'une classe : statut, frais exigés, et une ligne par élève (résultat, en ordre, décision). Lecture seule."""
    _exiger_lecture(conn, session)
    k = _classe(conn, session, annee, n_classe)
    annee, n = k["annee"], k["n_classe"]
    p = _portee(conn, annee, n, cle)
    cle = p["cle"]
    ligne = _ligne(conn, annee, n, cle)
    criteres = _criteres(conn, annee, n, cle)
    decisions = {l["MATRICULE"]: l for l in conn.execute(
        "SELECT * FROM VALIDATION_BULLETIN WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ?", (annee, n, cle))}
    calc = bulletins.calculer(conn, annee, n)
    eleves = []
    for e in sorted(calc["eleves"], key=lambda x: x["nom_complet"].lower()):
        r = e["portees"].get(cle) or {}
        ordre, manques = en_ordre(conn, e["matricule"], annee, n, criteres) if criteres else (None, [])
        d = decisions.get(e["matricule"])
        eleves.append({"matricule": e["matricule"], "nom_complet": e["nom_complet"], "pct": r.get("pct"), "resultat": r.get("resultat", "-"),
                       "en_ordre": ordre, "manques": manques, "valide": bool(d and d["VALIDE"]),
                       "decision": ({"origine": d["ORIGINE"], "par": d["DECIDE_PAR"], "le": d["DECIDE_LE"][:10], "motif": d["MOTIF"] or ""} if d else None)})
    statut = ligne["STATUT"] if ligne else None
    resume = {"eleves": len(eleves), "valides": sum(1 for x in eleves if x["valide"]),
              "en_ordre": sum(1 for x in eleves if x["en_ordre"]), "en_attente": sum(1 for x in eleves if x["resultat"] == "EN ATTENTE")}
    with conn:
        _tracer(conn, session, "PROCLAMATION_CONSULTEE", f"{annee} | {k['designation']} | {_libelle(p)}")
    return {"annee": annee, "n_classe": n, "classe": k["designation"], "cle": cle, "portee": _libelle(p), "statut": statut,
            "statut_libelle": STATUTS.get(statut, "Titulaire pas encore autorisé"), "criteres": criteres, "eleves": eleves, "resume": resume,
            "peut_direction": peut_direction(conn, session, "MODIFICATION"), "peut_prefet": peut_prefet(conn, session, "MODIFICATION"),
            "transmise_le": (ligne["TRANSMISE_LE"] or "")[:10] if ligne else "", "confirmee_le": (ligne["CONFIRMEE_LE"] or "")[:10] if ligne else ""}


def liste_proclamations(conn, session, annee=None) -> dict:
    """Les proclamations de l'année (toutes classes visibles) : classe, période, statut, nombre de bulletins validés."""
    _exiger_lecture(conn, session)
    annee = controle_notes._annee(conn, annee)
    lignes = []
    for l in conn.execute(
            "SELECT P.*, C.DESI_CLASSE, (SELECT COUNT(*) FROM VALIDATION_BULLETIN V WHERE V.ANNEESCO = P.ANNEESCO AND V.N_CLASSE = P.N_CLASSE "
            "AND V.CLE = P.CLE AND V.VALIDE = 1) AS NB_VALIDES FROM PROCLAMATION P JOIN CLASSE C ON C.N_CLASSE = P.N_CLASSE "
            "WHERE P.ANNEESCO = ? ORDER BY P.STATUT = 'TRANSMISE' DESC, C.DESI_CLASSE COLLATE NOCASE, P.CLE", (annee,)):
        if not sections.peut_classe(conn, session, l["N_CLASSE"]):
            continue
        try:
            p = _portee(conn, annee, l["N_CLASSE"], l["CLE"])
            libelle = _libelle(p)
        except ErreurProclamation:
            libelle = l["CLE"]
        lignes.append({"n_classe": l["N_CLASSE"], "classe": l["DESI_CLASSE"], "cle": l["CLE"], "portee": libelle, "statut": l["STATUT"],
                       "statut_libelle": STATUTS[l["STATUT"]], "valides": l["NB_VALIDES"]})
    return {"annee": annee, "annees": controle_notes.liste_annees(conn), "proclamations": lignes}


def etat_impression(conn, annee, n_classe, cle) -> tuple:
    """(statut, {matricules validés}) pour le titulaire (sans contrôle d'identité : réservé à bulletins.py, qui le fait avant).
    L'ensemble n'est rempli que si la proclamation est CONFIRMÉE par le Préfet : tant qu'elle ne l'est pas, rien ne s'imprime."""
    ligne = _ligne(conn, str(annee or ""), int(n_classe), str(cle or "").strip().upper())
    if not ligne:
        return None, set()
    if ligne["STATUT"] != "CONFIRMEE":
        return ligne["STATUT"], set()
    return "CONFIRMEE", {l["MATRICULE"] for l in conn.execute(
        "SELECT MATRICULE FROM VALIDATION_BULLETIN WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ? AND VALIDE = 1",
        (ligne["ANNEESCO"], ligne["N_CLASSE"], ligne["CLE"]))}


def message_blocage(statut) -> str:
    """Pourquoi le titulaire ne peut pas imprimer (message affiché tel quel)."""
    if statut is None:
        return "La Directrice des études n'a pas encore autorisé la proclamation de cette période : vous pouvez consulter les bulletins, pas les imprimer."
    if statut == "AUTORISEE":
        return "Les bulletins sont en cours de validation par la Directrice des études : vous pouvez les consulter, pas les imprimer."
    return "La proclamation attend la confirmation du Préfet : vous pouvez consulter les bulletins, pas les imprimer."


# ================================================================== Directrice des études
def autoriser(conn, session, annee, n_classe, cle) -> dict:
    """La Directrice autorise le titulaire de la classe pour la période, le semestre ou l'année `cle`."""
    _exiger(conn, session, DIRECTION, "MODIFICATION")
    k = _classe(conn, session, annee, n_classe)
    p = _portee(conn, k["annee"], k["n_classe"], cle)
    if _ligne(conn, k["annee"], k["n_classe"], p["cle"]):
        raise ErreurProclamation("Le titulaire est déjà autorisé pour cette classe et cette période.")
    with conn:
        conn.execute("INSERT INTO PROCLAMATION (ANNEESCO, N_CLASSE, CLE, STATUT, AUTORISEE_LE, AUTORISEE_PAR) VALUES (?,?,?,'AUTORISEE',?,?)",
                     (k["annee"], k["n_classe"], p["cle"], iso(maintenant()), session.login))
        _tracer(conn, session, "PROCLAMATION_AUTORISEE", f"{k['annee']} | {k['designation']} | {_libelle(p)}")
    return {"annee": k["annee"], "n_classe": k["n_classe"], "cle": p["cle"], "statut": "AUTORISEE"}


def definir_criteres(conn, session, annee, n_classe, cle, criteres) -> list:
    """Remplace les frais exigés : liste de {'codtf', 'tranche'} (tranche : numéro à partir de 1, ou None / vide pour la totalité).
    Au moins un frais. Seulement tant que la proclamation est « en cours de validation »."""
    _exiger(conn, session, DIRECTION, "MODIFICATION")
    k = _classe(conn, session, annee, n_classe)
    annee, n = k["annee"], k["n_classe"]
    p = _portee(conn, annee, n, cle)
    _exiger_ligne(conn, annee, n, p["cle"], "AUTORISEE")
    dispo = {f["codtf"]: f for f in frais_disponibles(conn, session, annee, n)}
    propres, vus = [], set()
    for c in criteres or []:
        codtf = str(c.get("codtf", "")).strip()
        if codtf in vus:
            continue
        if codtf not in dispo:
            raise ErreurProclamation(f"Frais inconnu ou non exigible pour cette classe : {codtf or '(vide)'}.")
        t = c.get("tranche")
        t = None if t in (None, "", 0, "0") else t
        if t is not None:
            try:
                t = int(t)
            except (TypeError, ValueError):
                raise ErreurProclamation("Tranche invalide : écrivez un numéro (1, 2, 3...) ou choisissez la totalité.") from None
            if t < 1 or not dispo[codtf]["par_tranche"]:
                raise ErreurProclamation(f"« {dispo[codtf]['designation']} » n'est pas payé par tranches : exigez-le en totalité.")
            if t > dispo[codtf]["nb_tranches"]:
                raise ErreurProclamation(f"« {dispo[codtf]['designation']} » n'a que {dispo[codtf]['nb_tranches']} tranche(s).")
        vus.add(codtf)
        propres.append((codtf, t))
    if not propres:
        raise ErreurProclamation("Choisissez au moins un frais à exiger (frais scolaire, tranche demandée ou totalité).")
    with conn:
        conn.execute("DELETE FROM PROCLAMATION_FRAIS WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ?", (annee, n, p["cle"]))
        conn.executemany("INSERT INTO PROCLAMATION_FRAIS (ANNEESCO, N_CLASSE, CLE, CODTF, TRANCHE) VALUES (?,?,?,?,?)",
                         [(annee, n, p["cle"], codtf, t) for codtf, t in propres])
        texte = " ; ".join(f"{dispo[c]['designation']} ({'tranche ' + str(t) if t else 'totalité'})" for c, t in propres)
        _tracer(conn, session, "PROCLAMATION_CRITERES", f"{annee} | {k['designation']} | {_libelle(p)} | {texte}")
    return _criteres(conn, annee, n, p["cle"])


def _eleves_de_la_classe(conn, annee, n_classe) -> dict:
    return {e["matricule"]: e for e in bulletins.calculer(conn, annee, n_classe)["eleves"]}


def valider(conn, session, annee, n_classe, cle, matricules=None) -> dict:
    """La Directrice valide les bulletins d'élèves EN ORDRE. `matricules` : liste ; None = tous les élèves en ordre de la classe.
    Un élève qui n'est pas en ordre est refusé : rien n'est alors écrit."""
    _exiger(conn, session, DIRECTION, "MODIFICATION")
    k = _classe(conn, session, annee, n_classe)
    annee, n = k["annee"], k["n_classe"]
    p = _portee(conn, annee, n, cle)
    _exiger_ligne(conn, annee, n, p["cle"], "AUTORISEE")
    criteres = _criteres(conn, annee, n, p["cle"])
    if not criteres:
        raise ErreurProclamation("Choisissez d'abord les frais exigés pour être en ordre.")
    eleves = _eleves_de_la_classe(conn, annee, n)
    if matricules is None:
        choisis = [m for m in eleves if en_ordre(conn, m, annee, n, criteres)[0]]
    else:
        choisis = list(dict.fromkeys(str(m).strip() for m in matricules if str(m).strip()))
        inconnus = [m for m in choisis if m not in eleves]
        if inconnus:
            raise ErreurProclamation("Élève hors de cette classe : " + ", ".join(inconnus) + ".")
        pas_en_ordre = [eleves[m]["nom_complet"] for m in choisis if not en_ordre(conn, m, annee, n, criteres)[0]]
        if pas_en_ordre:
            raise ErreurProclamation("Pas en ordre avec les frais exigés, bulletin non validé : " + ", ".join(pas_en_ordre) + ".")
    if not choisis:
        raise ErreurProclamation("Aucun élève à valider.")
    deja = {l["MATRICULE"] for l in conn.execute(
        "SELECT MATRICULE FROM VALIDATION_BULLETIN WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ? AND VALIDE = 1", (annee, n, p["cle"]))}
    nouveaux = [m for m in choisis if m not in deja]
    with conn:
        for m in nouveaux:
            conn.execute("INSERT INTO VALIDATION_BULLETIN (ANNEESCO, N_CLASSE, CLE, MATRICULE, VALIDE, ORIGINE, DECIDE_LE, DECIDE_PAR) "
                         "VALUES (?,?,?,?,1,'DIRECTRICE',?,?) ON CONFLICT(ANNEESCO, N_CLASSE, CLE, MATRICULE) DO UPDATE SET VALIDE = 1, "
                         "ORIGINE = 'DIRECTRICE', DECIDE_LE = excluded.DECIDE_LE, DECIDE_PAR = excluded.DECIDE_PAR, MOTIF = NULL",
                         (annee, n, p["cle"], m, iso(maintenant()), session.login))
            _tracer(conn, session, "BULLETIN_VALIDE", f"{annee} | {k['designation']} | {_libelle(p)} | {m} | {eleves[m]['nom_complet']}")
    return {"valides": len(nouveaux), "deja": len(choisis) - len(nouveaux)}


def retirer_validation(conn, session, annee, n_classe, cle, matricules) -> dict:
    """La Directrice retire la validation de bulletins (tant que la proclamation n'est pas soumise au Préfet)."""
    _exiger(conn, session, DIRECTION, "MODIFICATION")
    k = _classe(conn, session, annee, n_classe)
    annee, n = k["annee"], k["n_classe"]
    p = _portee(conn, annee, n, cle)
    _exiger_ligne(conn, annee, n, p["cle"], "AUTORISEE")
    eleves = _eleves_de_la_classe(conn, annee, n)
    retires = 0
    with conn:
        for m in dict.fromkeys(str(x).strip() for x in matricules or [] if str(x).strip()):
            if m not in eleves:
                raise ErreurProclamation(f"Élève hors de cette classe : {m}.")
            if conn.execute("UPDATE VALIDATION_BULLETIN SET VALIDE = 0, DECIDE_LE = ?, DECIDE_PAR = ?, ORIGINE = 'DIRECTRICE' "
                            "WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ? AND MATRICULE = ? AND VALIDE = 1",
                            (iso(maintenant()), session.login, annee, n, p["cle"], m)).rowcount:
                retires += 1
                _tracer(conn, session, "BULLETIN_VALIDATION_RETIREE", f"{annee} | {k['designation']} | {_libelle(p)} | {m} | {eleves[m]['nom_complet']}")
    return {"retires": retires}


def soumettre(conn, session, annee, n_classe, cle) -> dict:
    """La Directrice soumet la proclamation au Préfet : elle ne peut plus changer les frais ni les validations."""
    _exiger(conn, session, DIRECTION, "MODIFICATION")
    k = _classe(conn, session, annee, n_classe)
    annee, n = k["annee"], k["n_classe"]
    p = _portee(conn, annee, n, cle)
    _exiger_ligne(conn, annee, n, p["cle"], "AUTORISEE")
    if not _criteres(conn, annee, n, p["cle"]):
        raise ErreurProclamation("Choisissez d'abord les frais exigés pour être en ordre.")
    nb = conn.execute("SELECT COUNT(*) FROM VALIDATION_BULLETIN WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ? AND VALIDE = 1",
                      (annee, n, p["cle"])).fetchone()[0]
    if not nb:
        raise ErreurProclamation("Aucun bulletin n'est validé : validez d'abord les élèves en ordre.")
    with conn:
        conn.execute("UPDATE PROCLAMATION SET STATUT = 'TRANSMISE', TRANSMISE_LE = ?, TRANSMISE_PAR = ? WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ?",
                     (iso(maintenant()), session.login, annee, n, p["cle"]))
        _tracer(conn, session, "PROCLAMATION_SOUMISE", f"{annee} | {k['designation']} | {_libelle(p)} | {nb} bulletin(s) validé(s)")
    return {"statut": "TRANSMISE", "valides": nb}


# ================================================================== Préfet
def changer_decision(conn, session, annee, n_classe, cle, matricule, valide, motif) -> dict:
    """Le Préfet change la décision de la Directrice pour un élève (valider ou retirer la validation), avec un motif obligatoire.
    Possible quand la proclamation est soumise ou déjà confirmée. Retourne {'change': False} si l'élève était déjà dans cet état."""
    _exiger(conn, session, PREFECTURE, "MODIFICATION")
    k = _classe(conn, session, annee, n_classe)
    annee, n = k["annee"], k["n_classe"]
    p = _portee(conn, annee, n, cle)
    _exiger_ligne(conn, annee, n, p["cle"], "TRANSMISE", "CONFIRMEE")
    motif = " ".join(str(motif or "").split())
    if len(motif) < MIN_MOTIF:
        raise ErreurProclamation("Écrivez le motif de votre décision.")
    if len(motif) > MAX_MOTIF:
        raise ErreurProclamation(f"Le motif est trop long ({MAX_MOTIF} caractères au plus).")
    matricule = str(matricule or "").strip()
    eleve = _eleves_de_la_classe(conn, annee, n).get(matricule)
    if not eleve:
        raise ErreurProclamation("Cet élève n'est pas dans cette classe.")
    valide = bool(valide)
    d = conn.execute("SELECT VALIDE FROM VALIDATION_BULLETIN WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ? AND MATRICULE = ?",
                     (annee, n, p["cle"], matricule)).fetchone()
    if bool(d["VALIDE"] if d else 0) == valide:
        return {"matricule": matricule, "valide": valide, "change": False}
    with conn:
        conn.execute("INSERT INTO VALIDATION_BULLETIN (ANNEESCO, N_CLASSE, CLE, MATRICULE, VALIDE, ORIGINE, DECIDE_LE, DECIDE_PAR, MOTIF) "
                     "VALUES (?,?,?,?,?,'PREFET',?,?,?) ON CONFLICT(ANNEESCO, N_CLASSE, CLE, MATRICULE) DO UPDATE SET VALIDE = excluded.VALIDE, "
                     "ORIGINE = 'PREFET', DECIDE_LE = excluded.DECIDE_LE, DECIDE_PAR = excluded.DECIDE_PAR, MOTIF = excluded.MOTIF",
                     (annee, n, p["cle"], matricule, int(valide), iso(maintenant()), session.login, motif))
        _tracer(conn, session, "PROCLAMATION_DECISION_PREFET",
                f"{annee} | {k['designation']} | {_libelle(p)} | {matricule} | {eleve['nom_complet']} | "
                f"{'validé' if valide else 'validation retirée'} (avant : {'validé' if d and d['VALIDE'] else 'non validé'}) | motif : {motif}")
    return {"matricule": matricule, "valide": valide, "change": True}


def confirmer(conn, session, annee, n_classe, cle) -> dict:
    """Le Préfet confirme la proclamation : le titulaire peut alors imprimer les bulletins validés."""
    _exiger(conn, session, PREFECTURE, "MODIFICATION")
    k = _classe(conn, session, annee, n_classe)
    annee, n = k["annee"], k["n_classe"]
    p = _portee(conn, annee, n, cle)
    _exiger_ligne(conn, annee, n, p["cle"], "TRANSMISE")
    nb = conn.execute("SELECT COUNT(*) FROM VALIDATION_BULLETIN WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ? AND VALIDE = 1",
                      (annee, n, p["cle"])).fetchone()[0]
    if not nb:
        raise ErreurProclamation("Aucun bulletin n'est validé : il n'y a rien à proclamer.")
    with conn:
        conn.execute("UPDATE PROCLAMATION SET STATUT = 'CONFIRMEE', CONFIRMEE_LE = ?, CONFIRMEE_PAR = ? WHERE ANNEESCO = ? AND N_CLASSE = ? AND CLE = ?",
                     (iso(maintenant()), session.login, annee, n, p["cle"]))
        _tracer(conn, session, "PROCLAMATION_CONFIRMEE", f"{annee} | {k['designation']} | {_libelle(p)} | {nb} bulletin(s) validé(s)")
    return {"statut": "CONFIRMEE", "valides": nb}

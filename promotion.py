"""Direction des études, 7e fonctionnalité : « Passage en classe supérieure » (sans interface graphique : testable seule).

À la fin d'une année scolaire, la Directrice des études (droit « direction_etudes ») affecte les élèves à leur classe de l'année suivante :

  - les élèves qui ont RÉUSSI l'année (résultat annuel « ADMIS(E) », calculé comme sur les bulletins : bulletins.calculer, portée « A »)
    passent dans la classe SUPÉRIEURE ;
  - les élèves qui ont ÉCHOUÉ (« AJOURNÉ(E) ») RESTENT dans la même classe : ils y sont réinscrits avec le statut « Redoublant » ;
  - les élèves dont le résultat n'est pas encore connu (« EN ATTENTE » : il manque des points) ne sont PAS traités : on les traitera plus
    tard, dès que leur année est complète ;
  - les élèves de la dernière année des humanités (4ème) qui ont réussi ont FINI leurs études : ils ne sont inscrits nulle part.

Suite des années d'étude (section secondaire et humanitaire) :  7ème -> 8ème -> 1ère humanités -> 2ème -> 3ème -> 4ème -> fin.
  - 7ème -> 8ème, 1ère -> 2ème, 2ème -> 3ème, 3ème -> 4ème : la classe d'accueil est celle de la même division (A reste A) quand elle existe ; en
    humanités, l'OPTION reste la même. S'il y a plusieurs possibilités, la Directrice choisit.
  - 8ème -> 1ère humanités : ce sont les élèves qui choisissent leur OPTION ; la Directrice des études la SAISIT À LEUR PLACE, élève par élève
    (ou pour tous les élèves sans choix d'un seul coup). Comme une classe d'humanités porte son option, choisir la classe d'accueil revient à
    choisir l'option (et la division). Ce choix peut être saisi avant la fin de l'année ; il ne sert que si l'élève réussit. Aucune option n'est
    jamais attribuée d'office.
  - Les classes de 7ème à 4ème humanités doivent exister (Travaux techniques > Mise à jour des tables > Classes) ; l'année suivante doit être
    créée (Direction des études > Années).

Exécuter le passage d'une classe INSCRIT les élèves traités dans l'année suivante (nouvelle ligne INSCRIRE : statut « Ancien » pour un élève qui
monte, « Redoublant » pour un élève qui redouble) : leur paiement, leur présence et leurs points se rattachent donc à leur nouvelle classe.
Rien d'autre n'est modifié : l'inscription de l'année terminée, ses reçus, ses points et ses bulletins restent tels quels. L'opération est répétable
sans danger : un élève déjà traité, ou déjà inscrit dans l'année suivante, n'est jamais traité deux fois.

Annulation : la Directrice peut annuler le passage d'élèves traités par erreur, avec un motif, tant que l'élève n'a aucun paiement ni aucun point dans
sa nouvelle classe ; son inscription de l'année suivante est alors retirée (la trace de l'opération reste, marquée « Annulé »).

Droits sur « Direction des études » (relus dans la base à chaque appel) : Lecture = consulter, imprimer, exporter ; Ajout = saisir les choix de
classe d'accueil (option de 8ème) et exécuter le passage ; Modification = annuler un passage. L'Administrateur a tous les droits.
Section « Secondaire et humanitaire » seulement (le primaire n'est pas concerné). Chaque consultation et chaque écriture est inscrite au journal.
"""
import csv
import io
import re

import bulletins
import config
import controle_notes
import donnees
import sections
from controle_notes import ErreurControle, exiger, peut
from database import iso, journaliser, maintenant

__all__ = ["peut", "exiger", "ErreurPromotion"]

# année d'étude -> année d'étude suivante ; la 4ème humanités est la dernière
ETAPES = {7: 8, 8: 1, 1: 2, 2: 3, 3: 4}
DERNIERE = 4
RANG_ETAPE = {7: 0, 8: 1, 1: 2, 2: 3, 3: 4, 4: 5}
DECISIONS = {"PROMU": "Passe dans la classe supérieure", "REDOUBLE": "Redouble (reste dans la même classe)",
             "TERMINE": "A terminé ses études", "ATTENTE": "Résultat en attente : pas encore traité"}
MOTIF_MIN, MOTIF_MAX = 5, 300


class ErreurPromotion(ErreurControle):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== années
def liste_annees(conn) -> list:
    return controle_notes.liste_annees(conn)


def annee_suivante(conn, annee):
    """L'année scolaire qui suit `annee` dans la base (la plus proche), ou None si elle n'est pas encore créée."""
    l = conn.execute("SELECT MIN(ANNEESCO) FROM ANNEE_SCO WHERE ANNEESCO > ?", (annee,)).fetchone()
    return l[0] if l and l[0] else None


def _annee_source(conn, annee) -> str:
    """Année qui se termine : celle demandée, sinon l'année en cours si l'année suivante existe, sinon l'année d'avant."""
    a = str(annee or "").strip()
    if a:
        if not conn.execute("SELECT 1 FROM ANNEE_SCO WHERE ANNEESCO = ?", (a,)).fetchone():
            raise ErreurPromotion("Cette année scolaire n'existe pas.")
        return a
    courante = donnees.annee_courante(conn)
    if not courante:
        raise ErreurPromotion("Aucune année scolaire n'est définie : créez-la d'abord (Direction des études > Années).")
    if annee_suivante(conn, courante):
        return courante
    avant = conn.execute("SELECT MAX(ANNEESCO) FROM ANNEE_SCO WHERE ANNEESCO < ?", (courante,)).fetchone()[0]
    return avant or courante


# ================================================================== classes
_SQL_CLASSES = ("SELECT C.N_CLASSE, C.DESI_CLASSE, C.ANNEE_ETUDE, C.DIVISION, C.CODE_NIVEAU, C.CODE_OPTION, C.ACTIF, N.DESI_NIVEAU, O.DESI_OPTION "
                "FROM CLASSE C JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
                "WHERE N.SECTION = 'SECONDAIRE'")


def _numero(l):
    """Année d'étude (7, 8, 1, 2, 3, 4) lue dans ANNEE_ETUDE, à défaut dans la désignation de la classe."""
    m = re.search(r"\d+", l["ANNEE_ETUDE"] or l["DESI_CLASSE"] or "")
    return int(m.group()) if m else None


def _fiche_classe(l) -> dict:
    return {"n_classe": l["N_CLASSE"], "designation": l["DESI_CLASSE"], "numero": _numero(l), "division": (l["DIVISION"] or "").strip(),
            "code_niveau": l["CODE_NIVEAU"], "niveau": l["DESI_NIVEAU"], "code_option": l["CODE_OPTION"] or "", "option": l["DESI_OPTION"] or "",
            "actif": bool(l["ACTIF"])}


def _tri_classe(k) -> tuple:
    return (RANG_ETAPE.get(k["numero"], 99), k["option"].lower(), k["division"].lower(), k["designation"].lower())


def _classes(conn, actives=True) -> dict:
    """{n_classe: fiche} des classes du secondaire (actives seulement par défaut)."""
    sql = _SQL_CLASSES + (" AND C.ACTIF = 1" if actives else "")
    return {l["N_CLASSE"]: _fiche_classe(l) for l in conn.execute(sql)}


def _etape_libelle(k) -> str:
    n = k["numero"]
    if n == DERNIERE:
        return "Dernière année des humanités : fin des études si l'élève réussit"
    suivant = ETAPES.get(n)
    if suivant is None:
        return "Passage non géré pour cette classe"
    return {7: "Passe en 8ème", 8: "Passe en 1ère humanités (option à choisir)", 1: "Passe en 2ème humanités", 2: "Passe en 3ème humanités",
            3: "Passe en 4ème humanités"}[n]


def _candidates(classes: dict, k) -> list:
    """Classes d'accueil possibles d'un élève de la classe `k` qui réussit (liste de fiches, [] s'il n'y en a pas)."""
    t = ETAPES.get(k["numero"])
    if t is None:
        return []
    res = [c for c in classes.values() if c["numero"] == t and c["actif"]]
    if t in (2, 3, 4):                                           # en humanités, l'option ne change pas
        res = [c for c in res if c["code_option"] == k["code_option"]]
    return sorted(res, key=_tri_classe)


def _defaut(cands: list, k):
    """Classe d'accueil proposée d'office : jamais pour la 1ère humanités (l'option est toujours saisie) ; sinon la même division, ou la seule classe."""
    if not cands or ETAPES.get(k["numero"]) == 1:
        return None
    meme = [c for c in cands if c["division"].upper() == k["division"].upper()]
    if len(meme) == 1:
        return meme[0]["n_classe"]
    if len(cands) == 1:
        return cands[0]["n_classe"]
    return None


def _classe_source(conn, session, annee, n_classe) -> dict:
    """Classe du secondaire qui a des élèves inscrits dans l'année qui se termine, d'une section ouverte au compte."""
    try:
        n = int(n_classe)
    except (TypeError, ValueError):
        raise ErreurPromotion("Choisissez une classe.") from None
    k = _classes(conn, actives=False).get(n)
    if not k or not conn.execute("SELECT 1 FROM INSCRIRE WHERE ANNEESCO = ? AND N_CLASSE = ?", (annee, n)).fetchone():
        raise ErreurPromotion("Cette classe n'a aucun élève inscrit au secondaire pour cette année.")
    sections.exiger_classe(conn, session, n)
    return k


# ================================================================== calcul de l'état d'une classe
def _etat_classe(conn, annee, dest, k, classes) -> dict:
    """État du passage d'une classe (sans contrôle d'identité : réservé aux fonctions de ce module).
    Pour chaque élève actif : résultat annuel, décision (PROMU, REDOUBLE, TERMINE, ATTENTE), classe d'accueil, et si le passage est déjà fait."""
    n = k["n_classe"]
    fin = k["numero"] == DERNIERE
    etape = ETAPES.get(k["numero"])
    cands = _candidates(classes, k)
    defaut = _defaut(cands, k)
    ids_cands = {c["n_classe"] for c in cands}
    calc = bulletins.calculer(conn, annee, n)
    resultats = {e["matricule"]: e["portees"].get("A") for e in calc["eleves"]}
    actifs = {l["MATRICULE"]: l for l in conn.execute(
        "SELECT E.MATRICULE, E.SEXE FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE "
        "WHERE I.ANNEESCO = ? AND I.N_CLASSE = ? AND E.ACTIF = 1", (annee, n))}
    choix = {l["MATRICULE"]: l["N_CLASSE_DEST"] for l in conn.execute("SELECT MATRICULE, N_CLASSE_DEST FROM PROMOTION_CHOIX WHERE ANNEESCO = ?", (annee,))}
    faits = {l["MATRICULE"]: l for l in conn.execute(
        "SELECT * FROM PROMOTION WHERE ANNEESCO = ? AND N_CLASSE = ? AND STATUT = 'FAIT'", (annee, n))}
    deja = {}
    if dest:
        deja = {l["MATRICULE"]: l["N_CLASSE"] for l in conn.execute("SELECT MATRICULE, N_CLASSE FROM INSCRIRE WHERE ANNEESCO = ?", (dest,))}
    toutes = _classes(conn, actives=False)

    eleves = []
    for e in calc["eleves"]:
        m = e["matricule"]
        if m not in actifs:
            continue
        r = resultats.get(m)
        reussite = r["reussite"] if r else None
        f = faits.get(m)
        ligne = {"matricule": m, "nom_complet": e["nom_complet"], "sexe": e["sexe"], "pct": r["pct"] if r else None,
                 "resultat": r["resultat"] if r else config.DECISION_ATTENTE, "reussite": reussite, "fait": bool(f), "deja_inscrit": "",
                 "dest_id": None, "dest": "", "dest_option": "", "choisi": choix.get(m), "peut_choisir": False, "bloque": ""}
        if f:
            ligne["decision"], ligne["dest_id"] = f["DECISION"], f["N_CLASSE_DEST"]
        elif reussite is None:
            ligne["decision"] = "ATTENTE"
        elif reussite is False:
            ligne["decision"], ligne["dest_id"] = "REDOUBLE", n
        elif fin:
            ligne["decision"] = "TERMINE"
        else:
            ligne["decision"] = "PROMU"
        if not f and ligne["decision"] in ("PROMU", "ATTENTE"):
            choisi = choix.get(m)
            if choisi in ids_cands:
                ligne["dest_id"] = choisi
            elif ligne["decision"] == "PROMU":
                ligne["dest_id"] = defaut
            ligne["peut_choisir"] = bool(cands) and m not in deja
        if ligne["dest_id"] is not None and ligne["dest_id"] in toutes:
            d = toutes[ligne["dest_id"]]
            ligne["dest"], ligne["dest_option"] = d["designation"], d["option"]
        if not f and m in deja:
            ligne["deja_inscrit"] = toutes.get(deja[m], {}).get("designation", "")
        if not f and not ligne["deja_inscrit"]:
            if ligne["decision"] == "REDOUBLE" and not k["actif"]:
                ligne["bloque"] = f"La classe {k['designation']} est désactivée : réactivez-la pour que ses élèves puissent y redoubler."
            elif ligne["decision"] == "PROMU" and ligne["dest_id"] is None:
                ligne["bloque"] = ("Aucune classe de la classe supérieure n'est ouverte (Travaux techniques > Mise à jour des tables > Classes)." if not cands
                                   else "Classe d'accueil à choisir.")
        eleves.append(ligne)

    def nb(pred):
        return sum(1 for x in eleves if pred(x))
    a_traiter = lambda x: not x["fait"] and not x["deja_inscrit"]
    resume = {"effectif": len(eleves),
              "promus": nb(lambda x: a_traiter(x) and x["decision"] == "PROMU"),
              "redoublants": nb(lambda x: a_traiter(x) and x["decision"] == "REDOUBLE"),
              "termines": nb(lambda x: a_traiter(x) and x["decision"] == "TERMINE"),
              "attente": nb(lambda x: a_traiter(x) and x["decision"] == "ATTENTE"),
              "a_choisir": nb(lambda x: a_traiter(x) and x["decision"] == "PROMU" and x["dest_id"] is None),
              "bloques": nb(lambda x: bool(x["bloque"]) and x["decision"] != "PROMU"),
              "faits": nb(lambda x: x["fait"]), "deja": nb(lambda x: bool(x["deja_inscrit"]) and not x["fait"])}
    resume["a_faire"] = resume["promus"] + resume["redoublants"] + resume["termines"]
    for cle, decision in (("nb_monte", "PROMU"), ("nb_redouble", "REDOUBLE"), ("nb_fin", "TERMINE")):      # toutes décisions confondues (déjà traités compris)
        resume[cle] = nb(lambda x, d=decision: x["decision"] == d and not (x["deja_inscrit"] and not x["fait"]))
    return {"annee": annee, "annee_dest": dest, "classe": k, "etape": _etape_libelle(k), "eleves": eleves, "resume": resume,
            "destinations": [{"n_classe": c["n_classe"], "designation": c["designation"], "option": c["option"], "division": c["division"]} for c in cands],
            "defaut": defaut, "choix_option": etape == 1, "fin": fin}


def _eleves_traitables(etat) -> list:
    return [x for x in etat["eleves"] if not x["fait"] and not x["deja_inscrit"] and x["decision"] in ("PROMU", "REDOUBLE", "TERMINE")]


# ================================================================== 1. consultation
def apercu(conn, session, annee=None) -> dict:
    """Vue d'ensemble : pour chaque classe du secondaire qui avait des élèves dans l'année qui se termine, où en est le passage."""
    exiger(conn, session, "LECTURE")
    annee = _annee_source(conn, annee)
    dest = annee_suivante(conn, annee)
    classes = _classes(conn)
    toutes = _classes(conn, actives=False)
    presentes = [l[0] for l in conn.execute("SELECT DISTINCT N_CLASSE FROM INSCRIRE WHERE ANNEESCO = ?", (annee,))]
    lignes = []
    for n in presentes:
        k = toutes.get(n)
        if not k or not sections.peut_classe(conn, session, n):
            continue
        etat = _etat_classe(conn, annee, dest, k, classes)
        lignes.append(dict(etat["resume"], n_classe=n, designation=k["designation"], option=k["option"], etape=etat["etape"], numero=k["numero"],
                           actif=k["actif"], _tri=_tri_classe(k)))
    lignes.sort(key=lambda x: x["_tri"])
    for x in lignes:
        del x["_tri"]
    total = {c: sum(x[c] for x in lignes) for c in ("effectif", "promus", "redoublants", "termines", "attente", "a_choisir", "faits", "deja", "a_faire")}
    avertissement = ""
    if not dest:
        avertissement = (f"L'année scolaire qui suit {annee} n'est pas encore créée : vous pouvez consulter les résultats, mais le passage "
                         f"ne peut pas être exécuté (Direction des études > Années).")
    journaliser(conn, session.id_user, session.login, "PASSAGE_CONSULTE", f"{annee} | vue d'ensemble | {len(lignes)} classe(s)")
    conn.commit()
    return {"annee": annee, "annee_dest": dest, "annees": liste_annees(conn), "classes": lignes, "total": total, "avertissement": avertissement,
            "peut_ajout": peut(conn, session, "AJOUT"), "peut_modification": peut(conn, session, "MODIFICATION")}


def detail(conn, session, annee, n_classe, tracer=True) -> dict:
    """Élèves d'une classe avec leur résultat annuel, leur décision et leur classe d'accueil."""
    exiger(conn, session, "LECTURE")
    annee = _annee_source(conn, annee)
    k = _classe_source(conn, session, annee, n_classe)
    etat = _etat_classe(conn, annee, annee_suivante(conn, annee), k, _classes(conn))
    etat["peut_ajout"] = peut(conn, session, "AJOUT")
    etat["peut_modification"] = peut(conn, session, "MODIFICATION")
    if tracer:
        journaliser(conn, session.id_user, session.login, "PASSAGE_CONSULTE", f"{annee} | {k['designation']} | {len(etat['eleves'])} élève(s)")
        conn.commit()
    return etat


# ================================================================== 2. choix de la classe d'accueil (option de 8ème)
def _dest_valide(etat, valeur):
    """Numéro de classe d'accueil, contrôlé : doit faire partie des classes d'accueil possibles de la classe."""
    try:
        d = int(valeur)
    except (TypeError, ValueError):
        raise ErreurPromotion("Classe d'accueil invalide.") from None
    if d not in {c["n_classe"] for c in etat["destinations"]}:
        raise ErreurPromotion("Cette classe n'est pas une classe d'accueil possible pour les élèves de cette classe.")
    return d


def _ecrire_choix(conn, session, etat, annee, nouveaux: dict) -> dict:
    """Enregistre ({matricule: n_classe_dest ou None}) dans la transaction en cours ; retourne {'enregistres', 'retires', 'lignes'}."""
    par_eleve = {x["matricule"]: x for x in etat["eleves"]}
    noms = {c["n_classe"]: c for c in etat["destinations"]}
    enreg = retires = 0
    lignes = []
    for m, d in nouveaux.items():
        x = par_eleve.get(m)
        if x is None:
            raise ErreurPromotion("Un des élèves n'est pas dans cette classe.")
        if x["fait"] or x["deja_inscrit"]:
            raise ErreurPromotion(f"{x['nom_complet']} : son passage est déjà fait ou il est déjà inscrit dans l'année suivante.")
        if d is None:
            if conn.execute("DELETE FROM PROMOTION_CHOIX WHERE ANNEESCO = ? AND MATRICULE = ?", (annee, m)).rowcount:
                retires += 1
                lignes.append(f"{x['nom_complet']} : choix retiré")
            continue
        if x["choisi"] == d:
            continue
        conn.execute("INSERT INTO PROMOTION_CHOIX (ANNEESCO, MATRICULE, N_CLASSE_DEST, CHOISI_LE, CHOISI_PAR) VALUES (?,?,?,?,?) "
                     "ON CONFLICT(ANNEESCO, MATRICULE) DO UPDATE SET N_CLASSE_DEST = excluded.N_CLASSE_DEST, CHOISI_LE = excluded.CHOISI_LE, "
                     "CHOISI_PAR = excluded.CHOISI_PAR", (annee, m, d, iso(maintenant()), session.login))
        enreg += 1
        c = noms[d]
        lignes.append(f"{x['nom_complet']} ({m}) -> {c['designation']}" + (f" (option {c['option']})" if c["option"] else ""))
    return {"enregistres": enreg, "retires": retires, "lignes": lignes}


def enregistrer_choix(conn, session, annee, n_classe, choix: dict) -> dict:
    """La Directrice saisit la classe d'accueil d'élèves : `choix` = {matricule: n_classe de l'année suivante, ou '' pour retirer le choix}.
    Pour la 8ème, c'est la saisie de l'option choisie par l'élève (la classe de 1ère humanités porte l'option)."""
    exiger(conn, session, "AJOUT")
    annee = _annee_source(conn, annee)
    k = _classe_source(conn, session, annee, n_classe)
    etat = _etat_classe(conn, annee, annee_suivante(conn, annee), k, _classes(conn))
    if not etat["destinations"]:
        raise ErreurPromotion("Aucune classe d'accueil n'est ouverte pour cette classe (Travaux techniques > Mise à jour des tables > Classes).")
    nouveaux = {}
    for m, v in (choix or {}).items():
        v = str(v if v is not None else "").strip()
        nouveaux[str(m).strip()] = _dest_valide(etat, v) if v else None
    with conn:
        r = _ecrire_choix(conn, session, etat, annee, nouveaux)
        if r["enregistres"] or r["retires"]:
            journaliser(conn, session.id_user, session.login, "PASSAGE_CHOIX_ENREGISTRE",
                        f"{annee} | {k['designation']} | " + " ; ".join(r["lignes"]))
    return {"enregistres": r["enregistres"], "retires": r["retires"]}


def appliquer_a_tous(conn, session, annee, n_classe, n_dest) -> dict:
    """La même classe d'accueil pour tous les élèves qui n'ont pas encore de choix (et qui ne sont pas déjà traités)."""
    exiger(conn, session, "AJOUT")
    annee = _annee_source(conn, annee)
    k = _classe_source(conn, session, annee, n_classe)
    etat = _etat_classe(conn, annee, annee_suivante(conn, annee), k, _classes(conn))
    d = _dest_valide(etat, n_dest)
    nouveaux = {x["matricule"]: d for x in etat["eleves"]
                if x["peut_choisir"] and x["choisi"] is None and x["decision"] in ("PROMU", "ATTENTE") and not x["fait"]}
    if not nouveaux:
        raise ErreurPromotion("Tous les élèves de cette classe ont déjà un choix, ou n'ont pas à en avoir.")
    with conn:
        r = _ecrire_choix(conn, session, etat, annee, nouveaux)
        journaliser(conn, session.id_user, session.login, "PASSAGE_CHOIX_ENREGISTRE",
                    f"{annee} | {k['designation']} | même classe pour tous les élèves sans choix : {r['enregistres']} élève(s)")
    return {"enregistres": r["enregistres"], "retires": 0}


# ================================================================== 3. exécution du passage
def executer(conn, session, annee, n_classe) -> dict:
    """Exécute le passage de la classe : inscrit dans l'année suivante les élèves qui ont réussi (classe supérieure) et ceux qui ont échoué
    (même classe, « Redoublant »). Les élèves « en attente » et ceux déjà traités ne sont pas touchés. Tout ou rien : s'il manque la classe
    d'accueil d'un élève qui monte, rien n'est enregistré et le message nomme les élèves concernés."""
    exiger(conn, session, "AJOUT")
    annee = _annee_source(conn, annee)
    k = _classe_source(conn, session, annee, n_classe)
    dest = annee_suivante(conn, annee)
    if not dest:
        raise ErreurPromotion(f"L'année scolaire qui suit {annee} n'est pas encore créée : créez-la d'abord (Direction des études > Années).")
    etat = _etat_classe(conn, annee, dest, k, _classes(conn))
    a_traiter = _eleves_traitables(etat)
    if not a_traiter:
        raise ErreurPromotion("Aucun élève à traiter : les élèves restants ont un résultat en attente, sont déjà traités ou déjà inscrits dans l'année suivante.")
    sans_classe = [x for x in a_traiter if x["decision"] == "PROMU" and x["dest_id"] is None]
    if sans_classe:
        noms = ", ".join(x["nom_complet"] for x in sans_classe[:5]) + (f" et {len(sans_classe) - 5} autre(s)" if len(sans_classe) > 5 else "")
        raise ErreurPromotion(f"Classe d'accueil à choisir pour {len(sans_classe)} élève(s) qui réussissent : {noms}. "
                              + ("Saisissez leur option avant d'exécuter le passage." if etat["choix_option"] else "Choisissez leur classe d'accueil avant d'exécuter le passage."))
    bloques = [x for x in a_traiter if x["bloque"]]
    if bloques:
        raise ErreurPromotion(bloques[0]["bloque"])
    jour = maintenant().date().isoformat()
    promus = redoublants = termines = 0
    with conn:
        for x in a_traiter:
            m, d = x["matricule"], x["dest_id"]
            if x["decision"] == "PROMU":
                statut_insc, promus = "ANCIEN", promus + 1
            elif x["decision"] == "REDOUBLE":
                statut_insc, redoublants = "REDOUBLANT", redoublants + 1
            else:
                statut_insc, termines = None, termines + 1
            if statut_insc:
                conn.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE, DATE_INSCRIPTION, STATUT) VALUES (?,?,?,?,?)", (dest, m, d, jour, statut_insc))
            conn.execute("INSERT INTO PROMOTION (ANNEESCO, MATRICULE, N_CLASSE, ANNEESCO_DEST, N_CLASSE_DEST, DECISION, POURCENTAGE, STATUT, FAIT_LE, FAIT_PAR) "
                         "VALUES (?,?,?,?,?,?,?, 'FAIT', ?, ?) ON CONFLICT(ANNEESCO, MATRICULE) DO UPDATE SET N_CLASSE = excluded.N_CLASSE, "
                         "ANNEESCO_DEST = excluded.ANNEESCO_DEST, N_CLASSE_DEST = excluded.N_CLASSE_DEST, DECISION = excluded.DECISION, "
                         "POURCENTAGE = excluded.POURCENTAGE, STATUT = 'FAIT', FAIT_LE = excluded.FAIT_LE, FAIT_PAR = excluded.FAIT_PAR, "
                         "ANNULE_LE = NULL, ANNULE_PAR = NULL, MOTIF_ANNULATION = NULL",
                         (annee, m, k["n_classe"], dest, d if statut_insc else None, x["decision"], x["pct"], iso(maintenant()), session.login))
            conn.execute("DELETE FROM PROMOTION_CHOIX WHERE ANNEESCO = ? AND MATRICULE = ?", (annee, m))
        detail_ = ", ".join(f"{x['nom_complet']} ({x['matricule']}) : "
                            + {"PROMU": f"promu en {x['dest']}" + (f" (option {x['dest_option']})" if x["dest_option"] else ""),
                               "REDOUBLE": f"redouble en {x['dest']}", "TERMINE": "fin des études"}[x["decision"]] for x in a_traiter)
        journaliser(conn, session.id_user, session.login, "PASSAGE_EXECUTE",
                    f"{annee} -> {dest} | {k['designation']} | {promus} promu(s), {redoublants} redoublant(s), {termines} fin d'études | {detail_}")
    return {"annee": annee, "annee_dest": dest, "promus": promus, "redoublants": redoublants, "termines": termines,
            "en_attente": etat["resume"]["attente"]}


# ================================================================== 4. annulation
def annuler(conn, session, annee, n_classe, motif, matricules=None) -> dict:
    """Annule le passage d'élèves déjà traités (tous ceux de la classe, ou ceux listés), avec un motif. Refusé pour un élève qui a déjà un
    paiement ou des points dans sa nouvelle classe, ou dont l'inscription a été changée entre-temps : il est alors cité dans le message."""
    exiger(conn, session, "MODIFICATION")
    annee = _annee_source(conn, annee)
    k = _classe_source(conn, session, annee, n_classe)
    motif = " ".join(str(motif or "").split())
    if len(motif) < MOTIF_MIN:
        raise ErreurPromotion("Écrivez le motif de l'annulation.")
    if len(motif) > MOTIF_MAX:
        raise ErreurPromotion(f"Le motif est trop long ({MOTIF_MAX} caractères au plus).")
    voulus = None if matricules is None else {str(m).strip() for m in matricules}
    lignes = [l for l in conn.execute("SELECT P.*, E.NOM, E.POSTNOM, E.PRENOM FROM PROMOTION P JOIN ELEVE E ON E.MATRICULE = P.MATRICULE "
                                      "WHERE P.ANNEESCO = ? AND P.N_CLASSE = ? AND P.STATUT = 'FAIT' ORDER BY E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE",
                                      (annee, k["n_classe"]))
              if voulus is None or l["MATRICULE"] in voulus]
    if not lignes:
        raise ErreurPromotion("Aucun passage à annuler : choisissez des élèves dont le passage est fait.")
    refus, a_annuler = [], []
    for l in lignes:
        nom = donnees.nom_complet(l)
        dest = l["ANNEESCO_DEST"]
        if l["DECISION"] != "TERMINE":
            insc = conn.execute("SELECT N_CLASSE FROM INSCRIRE WHERE ANNEESCO = ? AND MATRICULE = ?", (dest, l["MATRICULE"])).fetchone()
            if not insc or insc["N_CLASSE"] != l["N_CLASSE_DEST"]:
                refus.append(f"{nom} : son inscription de {dest} a été changée depuis le passage")
                continue
            if conn.execute("SELECT 1 FROM PAIEMENT WHERE ANNEESCO = ? AND MATRICULE = ?", (dest, l["MATRICULE"])).fetchone():
                refus.append(f"{nom} : un paiement est déjà enregistré pour {dest}")
                continue
            if conn.execute("SELECT 1 FROM NOTE N JOIN EVALUATION E ON E.ID_EVAL = N.ID_EVAL JOIN COURS_CLASSE X ON X.ID_CC = E.ID_CC "
                            "WHERE X.ANNEESCO = ? AND N.MATRICULE = ?", (dest, l["MATRICULE"])).fetchone():
                refus.append(f"{nom} : des points sont déjà saisis pour {dest}")
                continue
        a_annuler.append((l, nom))
    if refus and voulus is None:
        raise ErreurPromotion("Annulation refusée, rien n'a été modifié. " + " ; ".join(refus[:5]) + (f" ; et {len(refus) - 5} autre(s)" if len(refus) > 5 else "")
                              + ". Choisissez les élèves concernés un par un pour annuler les autres.")
    if refus:
        raise ErreurPromotion("Annulation refusée, rien n'a été modifié. " + " ; ".join(refus))
    with conn:
        for l, nom in a_annuler:
            if l["DECISION"] != "TERMINE":
                conn.execute("DELETE FROM INSCRIRE WHERE ANNEESCO = ? AND MATRICULE = ?", (l["ANNEESCO_DEST"], l["MATRICULE"]))
            conn.execute("UPDATE PROMOTION SET STATUT = 'ANNULE', ANNULE_LE = ?, ANNULE_PAR = ?, MOTIF_ANNULATION = ? WHERE ANNEESCO = ? AND MATRICULE = ?",
                         (iso(maintenant()), session.login, motif, annee, l["MATRICULE"]))
        journaliser(conn, session.id_user, session.login, "PASSAGE_ANNULE",
                    f"{annee} | {k['designation']} | {len(a_annuler)} élève(s) : " + ", ".join(f"{nom} ({l['MATRICULE']})" for l, nom in a_annuler) + f" | motif : {motif}")
    return {"annules": len(a_annuler)}


# ================================================================== 5. exports et impression
def _situation(x, dest) -> str:
    if x["fait"]:
        return {"PROMU": "Passage fait", "REDOUBLE": "Redoublement enregistré", "TERMINE": "Fin des études enregistrée"}[x["decision"]]
    if x["deja_inscrit"]:
        return f"Déjà inscrit en {dest} ({x['deja_inscrit']})"
    if x["bloque"]:
        return x["bloque"]
    return "À traiter" if x["decision"] != "ATTENTE" else "Résultat en attente"


def exporter_csv(conn, session, annee, n_classe) -> str:
    """Liste de la classe (résultat annuel, décision, classe d'accueil, option) au format CSV (séparateur « ; », ouvrable avec Excel)."""
    etat = detail(conn, session, annee, n_classe, tracer=False)
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";")
    w.writerow(["Année", "Classe", "Matricule", "Élève", "Sexe", "Pourcentage", "Résultat", "Décision", "Année d'accueil", "Classe d'accueil",
                "Option", "Situation"])
    for x in etat["eleves"]:
        w.writerow([etat["annee"], etat["classe"]["designation"], x["matricule"], x["nom_complet"], x["sexe"],
                    "" if x["pct"] is None else str(x["pct"]).replace(".", ","), x["resultat"], DECISIONS[x["decision"]],
                    (etat["annee_dest"] or "") if x["decision"] != "TERMINE" else "", x["dest"], x["dest_option"], _situation(x, etat["annee_dest"])])
    journaliser(conn, session.id_user, session.login, "PASSAGE_EXPORTE", f"{etat['annee']} | {etat['classe']['designation']} | CSV")
    conn.commit()
    return "﻿" + sortie.getvalue()


def impression(conn, session, annee, n_classe) -> dict:
    """Données de la page imprimable d'une classe (même contenu que la consultation, inscrite au journal comme impression)."""
    etat = detail(conn, session, annee, n_classe, tracer=False)
    for x in etat["eleves"]:
        x["situation"] = _situation(x, etat["annee_dest"])
        x["decision_libelle"] = DECISIONS[x["decision"]]
    journaliser(conn, session.id_user, session.login, "PASSAGE_IMPRIME", f"{etat['annee']} | {etat['classe']['designation']}")
    conn.commit()
    return etat

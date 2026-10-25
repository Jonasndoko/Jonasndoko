"""Module « Tableau de bord » : vue d'ensemble GÉNÉRALE des élèves, sans aucun détail ni donnée financière.

Il montre seulement, pour l'année scolaire choisie, combien d'élèves sont EN RÈGLE et combien ne sont PAS EN RÈGLE.
Aucun montant, aucune opération, aucun nom d'élève, aucune ventilation par classe : ce module ne lit donc même pas les
reçus ni les encaissements pour les afficher (il n'en garde que le résultat « en règle / pas en règle »).

Règle (la même que le Contrôle numérique) : un élève n'est pas en règle dès qu'il lui reste un montant à payer sur un
frais de l'année choisie ou d'une année précédente ; les élèves désactivés ne sont pas comptés.

Qui le voit : l'Administrateur et les comptes à qui l'Administrateur a accordé la Lecture sur ce module
(Gestionnaire d'accès > Autorisations, ou Rôles pour tout un poste). Les droits sont relus dans la base à chaque
affichage. Un compte autorisé arrive sur le tableau de bord dès sa connexion.
"""
import config
import donnees
import droits
from database import journaliser

MODULE = "tableau"


class ErreurTableau(Exception):
    """Erreur métier dont le message peut être affiché tel quel à l'utilisateur."""


# ------------------------------------------------------------------ droits
def peut(conn, session) -> bool:
    """Administrateur, ou compte ayant la Lecture sur le module « Tableau de bord »."""
    return droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, "LECTURE")


def exiger(conn, session):
    if not peut(conn, session):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS['LECTURE']} » "
                              f"sur le module « {config.MODULES_DROITS[MODULE][0]} ».")


def journaliser_ouverture(conn, session):
    with conn:
        journaliser(conn, session.id_user, session.login, "TABLEAU_DE_BORD_OUVERT", "")


# ------------------------------------------------------------------ choix
def liste_annees(conn) -> list:
    """Années scolaires (la plus récente d'abord)."""
    return [l[0] for l in conn.execute("SELECT ANNEESCO FROM ANNEE_SCO ORDER BY ANNEESCO DESC")]


# ------------------------------------------------------------------ calcul
def _compter(conn, annee) -> tuple:
    """(inscrits, en règle, pas en règle) pour l'année scolaire. Rien d'autre n'est gardé."""
    inscrits = conn.execute(
        "SELECT I.MATRICULE FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE "
        "WHERE I.ANNEESCO = ? AND E.ACTIF = 1", (annee,)).fetchall()
    pas_en_regle = 0
    for e in inscrits:
        for ins in conn.execute("SELECT ANNEESCO, N_CLASSE FROM INSCRIRE WHERE MATRICULE = ? AND ANNEESCO <= ?",
                                (e["MATRICULE"], annee)).fetchall():
            if any(l.reste for l in donnees.situation(conn, e["MATRICULE"], ins["ANNEESCO"], ins["N_CLASSE"])):
                pas_en_regle += 1
                break
    return len(inscrits), len(inscrits) - pas_en_regle, pas_en_regle


def tableau_de_bord(conn, session, annee=None) -> dict:
    """Données du tableau de bord : l'année scolaire (par défaut l'année en cours), la liste des années et les trois
    nombres d'élèves. Rien d'autre."""
    exiger(conn, session)
    annees = liste_annees(conn)
    annee = annee or donnees.annee_courante(conn)
    if annee and annee not in annees:
        raise ErreurTableau("Année scolaire inconnue.")
    inscrits, en_regle, pas_en_regle = _compter(conn, annee) if annee else (0, 0, 0)
    return {
        "annee": annee, "annees": annees,
        "eleves": {"inscrits": inscrits, "en_regle": en_regle, "pas_en_regle": pas_en_regle,
                   "taux_en_regle": round(100 * en_regle / inscrits) if inscrits else 0},
    }


def tendances(conn, session, nombre=5) -> dict:
    """Comptes seulement, pour les graphiques en courbe et en barres : les élèves inscrits des `nombre` dernières années
    scolaires, au total et par sexe (filles / garçons), plus l'effectif du personnel actif. Aucun nom, aucun montant."""
    exiger(conn, session)
    lignes = conn.execute(
        "SELECT I.ANNEESCO AS A, COUNT(*) AS N, "
        "SUM(CASE WHEN E.SEXE = 'F' THEN 1 ELSE 0 END) AS F, SUM(CASE WHEN E.SEXE = 'M' THEN 1 ELSE 0 END) AS G "
        "FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE WHERE E.ACTIF = 1 "
        "GROUP BY I.ANNEESCO ORDER BY I.ANNEESCO DESC LIMIT ?", (nombre,)).fetchall()
    annees = [{"annee": l["A"], "inscrits": l["N"], "filles": l["F"] or 0, "garcons": l["G"] or 0}
              for l in reversed(lignes)]
    try:
        personnel = conn.execute("SELECT COUNT(*) FROM PERSONNEL WHERE ACTIF = 1").fetchone()[0]
    except Exception:                                  # table absente d'une très ancienne base
        personnel = 0
    return {"annees": annees, "personnel": personnel}


# ------------------------------------------------------------------ synthèse de l'établissement
def _eleves_inscrits(conn, annee) -> list:
    return conn.execute(
        "SELECT I.MATRICULE, I.N_CLASSE FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE "
        "WHERE I.ANNEESCO = ? AND E.ACTIF = 1", (annee,)).fetchall()


def _finances(conn, annee, eleves, frais_logiciel) -> list:
    """Situation financière générale de l'année, par devise : dû, payé, reste et taux de recouvrement (en pourcentage).
    Seulement des totaux : aucun nom d'élève. Le frais du logiciel des parents est compté à part (voir _logiciel)."""
    totaux = {}
    for e in eleves:
        for l in donnees.situation(conn, e["MATRICULE"], annee, e["N_CLASSE"]):
            if l.codtf in frais_logiciel:
                continue
            du, paye, reste = totaux.get(l.devise, (0, 0, 0))
            totaux[l.devise] = (du + l.du, paye + min(l.paye, l.du), reste + l.reste)
    return [{"devise": d, "du": du, "paye": paye, "reste": reste, "taux": round(100 * paye / du) if du else 0}
            for d, (du, paye, reste) in sorted(totaux.items())]


def _logiciel(conn, annee, eleves, frais_logiciel) -> dict:
    """Frais du logiciel des parents : combien d'élèves de l'année ont un reçu valide, et combien de codes d'accès sont utilisés."""
    inscrits = len(eleves)
    if not frais_logiciel:
        return {"configure": False, "inscrits": inscrits, "payes": 0, "taux": 0, "codes_utilises": 0}
    marques = ",".join("?" * len(frais_logiciel))
    ont_paye = {l[0] for l in conn.execute(
        f"SELECT DISTINCT MATRICULE FROM PAIEMENT WHERE ANNEESCO = ? AND STATUT = 'VALIDE' AND MATRICULE IS NOT NULL "
        f"AND CODTF IN ({marques})", (annee, *frais_logiciel))}
    payes = sum(1 for e in eleves if e["MATRICULE"] in ont_paye)
    utilises = conn.execute("SELECT COUNT(*) FROM CODE_PARENT WHERE ANNEESCO = ? AND ID_PARENT IS NOT NULL", (annee,)).fetchone()[0]
    return {"configure": True, "inscrits": inscrits, "payes": payes,
            "taux": round(100 * payes / inscrits) if inscrits else 0, "codes_utilises": utilises}


def synthese(conn, session, annee=None) -> dict:
    """Vue d'ensemble de l'établissement pour l'année : finances générales (totaux par devise) et frais du logiciel des parents.
    Seulement des totaux et des taux : aucun nom, aucun reçu, aucune opération."""
    exiger(conn, session)
    annee = annee or donnees.annee_courante(conn)
    if annee and annee not in liste_annees(conn):
        raise ErreurTableau("Année scolaire inconnue.")
    if not annee:
        return {"annee": None, "finances": [], "logiciel": _logiciel(conn, "", [], ())}
    frais_logiciel = tuple(l[0] for l in conn.execute("SELECT CODTF FROM TYPE_FRAIS WHERE POUR_APPLI_PARENTS = 1"))
    eleves = _eleves_inscrits(conn, annee)
    return {"annee": annee, "finances": _finances(conn, annee, eleves, frais_logiciel),
            "logiciel": _logiciel(conn, annee, eleves, frais_logiciel)}

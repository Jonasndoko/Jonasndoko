"""Direction des études - gestion des cours et des enseignants (sans interface : testable seul).

Ce que cette fonctionnalité permet :
  - définir le CALENDRIER SCOLAIRE : les années scolaires (avec leurs dates), leurs SEMESTRES et les PÉRIODES de chaque semestre ;
  - enregistrer les COURS par niveau, par option (quand elle s'applique) et par année d'étude (quand elle s'applique) ;
  - OUVRIR les cours dans chaque CLASSE pour une année scolaire (le « programme » de la classe) ;
  - ATTRIBUER chaque cours à un PROFESSEUR (un agent du personnel) ;
  - associer le professeur à ses classes : l'attribution d'un cours dans une classe l'associe à cette classe.

Règles :
  - un cours s'applique à une classe si le niveau est le même, si l'option est la même (cours sans option : toutes les options du
    niveau) et si l'année d'étude est la même (cours sans année d'étude : toutes celles du niveau) ;
  - une option ne se choisit que si le niveau la propose (humanités) ;
  - un cours n'est ouvert qu'une fois dans une classe pour une année ; il a UN seul professeur ; un professeur peut avoir plusieurs
    cours et plusieurs classes ;
  - le professeur est un agent en service du Gestion du personnel (dossier actif) ;
  - les semestres sont dans les dates de l'année, sans se chevaucher ; les périodes sont dans les dates de leur semestre, sans se
    chevaucher ; on ne réduit pas des dates en laissant un semestre ou une période dehors ;
  - un cours déjà ouvert dans une classe ne change plus de niveau, d'option ni d'année d'étude (on le désactive) ; un cours jamais
    utilisé peut être supprimé ; une année, un semestre ou une période se supprime seulement s'il ne contient plus rien.

Droits (module « direction_etudes », c'est-à-dire la Direction des études ; l'Administrateur les a tous) :
  Lecture : tout consulter ; Ajout : créer année, semestre, période, cours, ouvrir un cours dans une classe, attribuer un professeur
  à un cours sans professeur ; Modification : changer des dates, des noms, des heures, l'année en cours, désactiver un cours,
  changer ou retirer un professeur ; Suppression : supprimer un semestre, une période, un cours jamais utilisé, retirer un cours
  d'une classe. Chaque opération est contrôlée au moment de l'action et inscrite au journal.
"""
import re
import sqlite3
from datetime import date, timedelta

import config
import donnees
import droits
import sections
from database import iso, journaliser, maintenant
from saisie_date import lire_date_texte

MODULE = "direction_etudes"
LONGUEUR_MAX = 80
HEURES_MAX = 40
SEMESTRES_PAR_ANNEE = 2       # une année = 2 semestres (secondaire et humanitaire)
SEMESTRES_PAR_SECTION = {"SECONDAIRE": 2, "PRIMAIRE": 3}     # primaire : 3 trimestres de 2 périodes = 6 périodes
PERIODES_PAR_SECTION = {"SECONDAIRE": 4, "PRIMAIRE": 6}


def _section_calendrier(section) -> str:
    section = (section or sections.SECONDAIRE).strip().upper()
    if section not in sections.TOUTES:
        raise ErreurCours("Choisissez la section : Primaire, ou Secondaire et humanitaire.")
    return section


def mot_periode_longue(section) -> str:
    """« trimestre » au primaire, « semestre » ailleurs."""
    return "trimestre" if section == sections.PRIMAIRE else "semestre"
PERIODES_PAR_SEMESTRE = 2     # un semestre = 2 périodes, soit 4 périodes par année


class ErreurCours(Exception):
    """Erreur métier dont le message peut être affiché tel quel à l'utilisateur."""


# ================================================================== droits
def peut(conn, session, droit) -> bool:
    return droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, droit)


def exiger(conn, session, droit):
    if not peut(conn, session, droit):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS.get(droit, droit)} » "
                              f"sur le module « {config.MODULES_DROITS[MODULE][0]} ».")


# ================================================================== lecture des saisies
def _texte(valeur) -> str:
    return " ".join(str(valeur or "").split())


def _libelle(texte, nom) -> str:
    t = _texte(texte)
    if not t:
        raise ErreurCours(f"Écrivez {nom}.")
    if len(t) > LONGUEUR_MAX:
        raise ErreurCours(f"{nom[0].upper() + nom[1:]} est trop long ({LONGUEUR_MAX} caractères au plus).")
    return t[0].upper() + t[1:]


def _date(texte, nom, obligatoire=True):
    if not _texte(texte):
        if obligatoire:
            raise ErreurCours(f"Renseignez la {nom}.")
        return None
    jour = lire_date_texte(texte)
    if jour is None:
        raise ErreurCours(f"La {nom} est invalide. Écrivez-la ainsi : 07/09/2026")
    return jour


def _fr(texte_iso) -> str:
    return date.fromisoformat(texte_iso).strftime("%d/%m/%Y") if texte_iso else ""


def _heures(valeur) -> int:
    t = _texte(valeur)
    if not t:
        return 0
    if not re.fullmatch(r"\d{1,2}", t) or int(t) > HEURES_MAX:
        raise ErreurCours(f"Les heures par semaine sont un nombre entier de 0 à {HEURES_MAX}.")
    return int(t)


def lire_annee(texte) -> str:
    t = _texte(texte)
    m = re.fullmatch(r"(\d{4})\s*[-/]\s*(\d{4})", t)
    if not m or int(m.group(2)) != int(m.group(1)) + 1:
        raise ErreurCours("Une année scolaire s'écrit avec deux années qui se suivent, par exemple 2026-2027.")
    return f"{m.group(1)}-{m.group(2)}"


# ================================================================== calendrier : années
def lister_annees(conn, session) -> list:
    """[{annee, en_cours, actif, debut, fin, avec_dates, nb_semestres}] de la plus récente à la plus ancienne."""
    exiger(conn, session, "LECTURE")
    resultat = []
    for l in conn.execute("SELECT A.*, C.DATE_DEBUT, C.DATE_FIN, (SELECT COUNT(*) FROM SEMESTRE_SCO S WHERE S.ANNEESCO = A.ANNEESCO) AS NS "
                          "FROM ANNEE_SCO A LEFT JOIN ANNEE_CALENDRIER C ON C.ANNEESCO = A.ANNEESCO ORDER BY A.ANNEESCO DESC"):
        resultat.append({"annee": l["ANNEESCO"], "en_cours": bool(l["EN_COURS"]), "actif": bool(l["ACTIF"]),
                         "debut": _fr(l["DATE_DEBUT"]), "fin": _fr(l["DATE_FIN"]), "avec_dates": l["DATE_DEBUT"] is not None,
                         "nb_semestres": l["NS"]})
    return resultat


def _annee(conn, annee):
    l = conn.execute("SELECT * FROM ANNEE_SCO WHERE ANNEESCO = ?", (annee,)).fetchone()
    if not l:
        raise ErreurCours("Année scolaire introuvable.")
    return l


def _dates_annee(conn, annee):
    l = conn.execute("SELECT * FROM ANNEE_CALENDRIER WHERE ANNEESCO = ?", (annee,)).fetchone()
    if not l:
        raise ErreurCours(f"Définissez d'abord les dates de l'année {annee} (bouton « Définir les dates »).")
    return date.fromisoformat(l["DATE_DEBUT"]), date.fromisoformat(l["DATE_FIN"])


def _verifier_dates_annee(annee, debut: date, fin: date):
    a1, a2 = int(annee[:4]), int(annee[5:])
    if fin <= debut:
        raise ErreurCours("La date de fin de l'année est avant sa date de début.")
    if debut.year != a1 or fin.year != a2:
        raise ErreurCours(f"L'année {annee} commence en {a1} et finit en {a2} : vérifiez les dates.")
    if (fin - debut).days > 400:
        raise ErreurCours("Une année scolaire ne dépasse pas 13 mois.")


def creer_annee(conn, session, annee_texte, debut_texte, fin_texte, en_cours=False) -> str:
    """Crée une année scolaire avec ses dates (ou ajoute les dates à une année déjà créée sans dates). Retourne l'année."""
    exiger(conn, session, "AJOUT")
    annee = lire_annee(annee_texte)
    debut, fin = _date(debut_texte, "date de début"), _date(fin_texte, "date de fin")
    _verifier_dates_annee(annee, debut, fin)
    existe = conn.execute("SELECT 1 FROM ANNEE_SCO WHERE ANNEESCO = ?", (annee,)).fetchone()
    if conn.execute("SELECT 1 FROM ANNEE_CALENDRIER WHERE ANNEESCO = ?", (annee,)).fetchone():
        raise ErreurCours(f"L'année {annee} a déjà ses dates : utilisez « Modifier les dates ».")
    try:
        with conn:
            if not existe:
                conn.execute("INSERT INTO ANNEE_SCO (ANNEESCO, EN_COURS, ACTIF) VALUES (?, 0, 1)", (annee,))
            conn.execute("INSERT INTO ANNEE_CALENDRIER (ANNEESCO, DATE_DEBUT, DATE_FIN) VALUES (?,?,?)",
                         (annee, debut.isoformat(), fin.isoformat()))
            if en_cours:
                conn.execute("UPDATE ANNEE_SCO SET EN_COURS = CASE WHEN ANNEESCO = ? THEN 1 ELSE 0 END", (annee,))
            journaliser(conn, session.id_user, session.login, "ANNEE_SCOLAIRE_CREEE",
                        f"{annee} | du {debut.strftime('%d/%m/%Y')} au {fin.strftime('%d/%m/%Y')}"
                        + (" | année en cours" if en_cours else "") + (" | dates ajoutées à une année existante" if existe else ""))
    except sqlite3.IntegrityError as erreur:
        raise ErreurCours(f"Enregistrement impossible : {erreur}") from None
    return annee


def modifier_dates_annee(conn, session, annee, debut_texte, fin_texte):
    exiger(conn, session, "MODIFICATION")
    _annee(conn, annee)
    ancien = _dates_annee(conn, annee)
    debut, fin = _date(debut_texte, "date de début"), _date(fin_texte, "date de fin")
    _verifier_dates_annee(annee, debut, fin)
    hors = conn.execute("SELECT LIBELLE FROM SEMESTRE_SCO WHERE ANNEESCO = ? AND (DATE_DEBUT < ? OR DATE_FIN > ?) LIMIT 1",
                        (annee, debut.isoformat(), fin.isoformat())).fetchone()
    if hors:
        raise ErreurCours(f"Le semestre « {hors['LIBELLE']} » sortirait de l'année : corrigez d'abord ses dates.")
    with conn:
        conn.execute("UPDATE ANNEE_CALENDRIER SET DATE_DEBUT = ?, DATE_FIN = ? WHERE ANNEESCO = ?",
                     (debut.isoformat(), fin.isoformat(), annee))
        journaliser(conn, session.id_user, session.login, "ANNEE_SCOLAIRE_MODIFIEE",
                    f"{annee} | dates : {ancien[0].strftime('%d/%m/%Y')} - {ancien[1].strftime('%d/%m/%Y')} -> "
                    f"{debut.strftime('%d/%m/%Y')} - {fin.strftime('%d/%m/%Y')}")


def definir_annee_en_cours(conn, session, annee):
    """Une seule année est « en cours » à la fois."""
    exiger(conn, session, "MODIFICATION")
    ligne = _annee(conn, annee)
    if not ligne["ACTIF"]:
        raise ErreurCours("Cette année scolaire est désactivée : réactivez-la d'abord (Travaux techniques).")
    with conn:
        conn.execute("UPDATE ANNEE_SCO SET EN_COURS = CASE WHEN ANNEESCO = ? THEN 1 ELSE 0 END", (annee,))
        journaliser(conn, session.id_user, session.login, "ANNEE_SCOLAIRE_MODIFIEE", f"{annee} | devient l'année en cours")


# ================================================================== calendrier : semestres et périodes
def _chevauche(conn, table, colonne_parent, parent, debut: date, fin: date, sauf=None, cle="ID_SEM"):
    return conn.execute(f"SELECT * FROM {table} WHERE {colonne_parent} = ? AND DATE_DEBUT <= ? AND DATE_FIN >= ? "
                        f"AND {cle} <> ?", (parent, fin.isoformat(), debut.isoformat(), sauf or -1)).fetchone()


def _valider_semestre(conn, annee, libelle, debut: date, fin: date, sauf=None, section=sections.SECONDAIRE):
    d_an, f_an = _dates_annee(conn, annee)
    if fin < debut:
        raise ErreurCours("La date de fin du semestre est avant sa date de début.")
    if debut < d_an or fin > f_an:
        raise ErreurCours(f"Le semestre doit rester dans l'année scolaire ({d_an.strftime('%d/%m/%Y')} - {f_an.strftime('%d/%m/%Y')}).")
    autre = conn.execute("SELECT * FROM SEMESTRE_SCO WHERE ANNEESCO = ? AND SECTION = ? AND DATE_DEBUT <= ? AND DATE_FIN >= ? AND ID_SEM <> ?",
                         (annee, section, fin.isoformat(), debut.isoformat(), sauf or -1)).fetchone()     # le primaire et le secondaire ont chacun leur calendrier
    if autre:
        raise ErreurCours(f"Ces dates se chevauchent avec « {autre['LIBELLE']} » ({_fr(autre['DATE_DEBUT'])} - {_fr(autre['DATE_FIN'])}).")
    if conn.execute("SELECT 1 FROM SEMESTRE_SCO WHERE ANNEESCO = ? AND LIBELLE = ? COLLATE NOCASE AND ID_SEM <> ?",
                    (annee, libelle, sauf or -1)).fetchone():
        raise ErreurCours(f"Un semestre ou trimestre « {libelle} » existe déjà dans l'année {annee}.")


def ajouter_semestre(conn, session, annee, libelle, debut_texte, fin_texte, section=sections.SECONDAIRE) -> int:
    """Ajoute un semestre (secondaire et humanitaire : 2 par année) ou un trimestre (primaire : 3 par année) au calendrier de la section."""
    exiger(conn, session, "AJOUT")
    _annee(conn, annee)
    section = _section_calendrier(section)
    mot = mot_periode_longue(section)
    libelle = _libelle(libelle, f"le nom du {mot}")
    debut, fin = _date(debut_texte, "date de début"), _date(fin_texte, "date de fin")
    maximum = SEMESTRES_PAR_SECTION[section]
    if conn.execute("SELECT COUNT(*) FROM SEMESTRE_SCO WHERE ANNEESCO = ? AND SECTION = ?", (annee, section)).fetchone()[0] >= maximum:
        raise ErreurCours(f"Pour la section {sections.libelle(section)}, une année scolaire a {maximum} {mot}s : l'année {annee} les a déjà.")
    _valider_semestre(conn, annee, libelle, debut, fin, section=section)
    with conn:
        cur = conn.execute("INSERT INTO SEMESTRE_SCO (ANNEESCO, LIBELLE, DATE_DEBUT, DATE_FIN, SECTION) VALUES (?,?,?,?,?)",
                           (annee, libelle, debut.isoformat(), fin.isoformat(), section))
        journaliser(conn, session.id_user, session.login, "SEMESTRE_AJOUT",
                    f"{annee} | {sections.libelle(section)} | {libelle} | {debut.strftime('%d/%m/%Y')} - {fin.strftime('%d/%m/%Y')}")
    return cur.lastrowid


def _semestre(conn, id_sem):
    l = conn.execute("SELECT * FROM SEMESTRE_SCO WHERE ID_SEM = ?", (id_sem,)).fetchone()
    if not l:
        raise ErreurCours("Semestre introuvable.")
    return l


def modifier_semestre(conn, session, id_sem, libelle, debut_texte, fin_texte):
    exiger(conn, session, "MODIFICATION")
    s = _semestre(conn, id_sem)
    libelle = _libelle(libelle, "le nom du semestre")
    debut, fin = _date(debut_texte, "date de début"), _date(fin_texte, "date de fin")
    _valider_semestre(conn, s["ANNEESCO"], libelle, debut, fin, sauf=id_sem, section=s["SECTION"])
    hors = conn.execute("SELECT LIBELLE FROM PERIODE_SCO WHERE ID_SEM = ? AND (DATE_DEBUT < ? OR DATE_FIN > ?) LIMIT 1",
                        (id_sem, debut.isoformat(), fin.isoformat())).fetchone()
    if hors:
        raise ErreurCours(f"La période « {hors['LIBELLE']} » sortirait du semestre : corrigez d'abord ses dates.")
    with conn:
        conn.execute("UPDATE SEMESTRE_SCO SET LIBELLE = ?, DATE_DEBUT = ?, DATE_FIN = ? WHERE ID_SEM = ?",
                     (libelle, debut.isoformat(), fin.isoformat(), id_sem))
        journaliser(conn, session.id_user, session.login, "SEMESTRE_MODIFICATION",
                    f"{s['ANNEESCO']} | {s['LIBELLE']} -> {libelle} | {debut.strftime('%d/%m/%Y')} - {fin.strftime('%d/%m/%Y')}")


def supprimer_semestre(conn, session, id_sem):
    exiger(conn, session, "SUPPRESSION")
    s = _semestre(conn, id_sem)
    if conn.execute("SELECT 1 FROM PERIODE_SCO WHERE ID_SEM = ?", (id_sem,)).fetchone():
        raise ErreurCours("Ce semestre contient des périodes : supprimez-les d'abord.")
    with conn:
        conn.execute("DELETE FROM SEMESTRE_SCO WHERE ID_SEM = ?", (id_sem,))
        journaliser(conn, session.id_user, session.login, "SEMESTRE_SUPPRESSION", f"{s['ANNEESCO']} | {s['LIBELLE']}")


def _valider_periode(conn, sem, libelle, debut: date, fin: date, sauf=None):
    d_s, f_s = date.fromisoformat(sem["DATE_DEBUT"]), date.fromisoformat(sem["DATE_FIN"])
    if fin < debut:
        raise ErreurCours("La date de fin de la période est avant sa date de début.")
    if debut < d_s or fin > f_s:
        raise ErreurCours(f"La période doit rester dans le semestre « {sem['LIBELLE']} » ({d_s.strftime('%d/%m/%Y')} - {f_s.strftime('%d/%m/%Y')}).")
    autre = _chevauche(conn, "PERIODE_SCO", "ID_SEM", sem["ID_SEM"], debut, fin, sauf, "ID_PER")
    if autre:
        raise ErreurCours(f"Ces dates se chevauchent avec « {autre['LIBELLE']} » ({_fr(autre['DATE_DEBUT'])} - {_fr(autre['DATE_FIN'])}).")
    if conn.execute("SELECT 1 FROM PERIODE_SCO WHERE ID_SEM = ? AND LIBELLE = ? COLLATE NOCASE AND ID_PER <> ?",
                    (sem["ID_SEM"], libelle, sauf or -1)).fetchone():
        raise ErreurCours(f"Une période « {libelle} » existe déjà dans ce semestre.")


def ajouter_periode(conn, session, id_sem, libelle, debut_texte, fin_texte) -> int:
    exiger(conn, session, "AJOUT")
    sem = _semestre(conn, id_sem)
    libelle = _libelle(libelle, "le nom de la période")
    debut, fin = _date(debut_texte, "date de début"), _date(fin_texte, "date de fin")
    if conn.execute("SELECT COUNT(*) FROM PERIODE_SCO WHERE ID_SEM = ?", (id_sem,)).fetchone()[0] >= PERIODES_PAR_SEMESTRE:
        raise ErreurCours(f"Un semestre a {PERIODES_PAR_SEMESTRE} périodes : « {sem['LIBELLE']} » les a déjà.")
    _valider_periode(conn, sem, libelle, debut, fin)
    with conn:
        cur = conn.execute("INSERT INTO PERIODE_SCO (ID_SEM, LIBELLE, DATE_DEBUT, DATE_FIN) VALUES (?,?,?,?)",
                           (id_sem, libelle, debut.isoformat(), fin.isoformat()))
        journaliser(conn, session.id_user, session.login, "PERIODE_AJOUT",
                    f"{sem['ANNEESCO']} | {sem['LIBELLE']} | {libelle} | {debut.strftime('%d/%m/%Y')} - {fin.strftime('%d/%m/%Y')}")
    return cur.lastrowid


def _periode(conn, id_per):
    l = conn.execute("SELECT P.*, S.ANNEESCO, S.LIBELLE AS SEMESTRE FROM PERIODE_SCO P JOIN SEMESTRE_SCO S ON S.ID_SEM = P.ID_SEM "
                     "WHERE P.ID_PER = ?", (id_per,)).fetchone()
    if not l:
        raise ErreurCours("Période introuvable.")
    return l


def modifier_periode(conn, session, id_per, libelle, debut_texte, fin_texte):
    exiger(conn, session, "MODIFICATION")
    p = _periode(conn, id_per)
    libelle = _libelle(libelle, "le nom de la période")
    debut, fin = _date(debut_texte, "date de début"), _date(fin_texte, "date de fin")
    _valider_periode(conn, _semestre(conn, p["ID_SEM"]), libelle, debut, fin, sauf=id_per)
    with conn:
        conn.execute("UPDATE PERIODE_SCO SET LIBELLE = ?, DATE_DEBUT = ?, DATE_FIN = ? WHERE ID_PER = ?",
                     (libelle, debut.isoformat(), fin.isoformat(), id_per))
        journaliser(conn, session.id_user, session.login, "PERIODE_MODIFICATION",
                    f"{p['ANNEESCO']} | {p['SEMESTRE']} | {p['LIBELLE']} -> {libelle} | "
                    f"{debut.strftime('%d/%m/%Y')} - {fin.strftime('%d/%m/%Y')}")


def supprimer_periode(conn, session, id_per):
    exiger(conn, session, "SUPPRESSION")
    p = _periode(conn, id_per)
    if conn.execute("SELECT 1 FROM EVALUATION WHERE ID_PER = ? UNION SELECT 1 FROM CONDUITE WHERE ID_PER = ?", (id_per, id_per)).fetchone():
        raise ErreurCours("Des points ou des conduites sont déjà enregistrés pour cette période : on ne la supprime pas.")
    with conn:
        conn.execute("DELETE FROM PERIODE_SCO WHERE ID_PER = ?", (id_per,))
        journaliser(conn, session.id_user, session.login, "PERIODE_SUPPRESSION", f"{p['ANNEESCO']} | {p['SEMESTRE']} | {p['LIBELLE']}")


def _partager(debut: date, fin: date) -> tuple:
    """Coupe [debut, fin] en deux parties consécutives de durées presque égales : ((d1, f1), (d2, f2))."""
    n = (fin - debut).days + 1
    f1 = debut + timedelta(days=n // 2 - 1)
    return (debut, f1), (f1 + timedelta(days=1), fin)


def _partager_en(debut: date, fin: date, n: int) -> list:
    """Partage [debut, fin] en n parts consécutives presque égales : [(début, fin), ...]."""
    total = (fin - debut).days + 1
    parts, courant = [], debut
    for i in range(n):
        longueur = total // n + (1 if i < total % n else 0)
        parts.append((courant, courant + timedelta(days=longueur - 1)))
        courant = courant + timedelta(days=longueur)
    return parts


def generer_structure_standard(conn, session, annee, section=sections.SECONDAIRE) -> dict:
    """Crée le calendrier standard d'une section, en partageant les dates de l'année en parts presque égales (à corriger ensuite si besoin) :
    secondaire et humanitaire = 2 semestres de 2 périodes (4 périodes) ; primaire = 3 trimestres de 2 périodes (6 périodes).
    Seulement pour une section qui n'a encore aucun semestre/trimestre dans l'année. Retourne {'semestres': n, 'periodes': n}."""
    exiger(conn, session, "AJOUT")
    _annee(conn, annee)
    section = _section_calendrier(section)
    mot = mot_periode_longue(section)
    debut, fin = _dates_annee(conn, annee)
    if conn.execute("SELECT 1 FROM SEMESTRE_SCO WHERE ANNEESCO = ? AND SECTION = ?", (annee, section)).fetchone():
        raise ErreurCours(f"L'année {annee} a déjà des {mot}s pour la section {sections.libelle(section)} : la structure standard ne "
                          "s'applique qu'à un calendrier vide.")
    if section == sections.PRIMAIRE:
        noms_sem = ("1er trimestre", "2ème trimestre", "3ème trimestre")
        noms_per = (("1ère période", "2ème période"), ("3ème période", "4ème période"), ("5ème période", "6ème période"))
    else:
        noms_sem = ("1er semestre", "2ème semestre")
        noms_per = (("1ère période", "2ème période"), ("3ème période", "4ème période"))
    with conn:
        for (d, f), nom, noms in zip(_partager_en(debut, fin, len(noms_sem)), noms_sem, noms_per):
            id_sem = conn.execute("INSERT INTO SEMESTRE_SCO (ANNEESCO, LIBELLE, DATE_DEBUT, DATE_FIN, SECTION) VALUES (?,?,?,?,?)",
                                  (annee, nom, d.isoformat(), f.isoformat(), section)).lastrowid
            for (pd, pf), nom_p in zip(_partager_en(d, f, 2), noms):
                conn.execute("INSERT INTO PERIODE_SCO (ID_SEM, LIBELLE, DATE_DEBUT, DATE_FIN) VALUES (?,?,?,?)",
                             (id_sem, nom_p, pd.isoformat(), pf.isoformat()))
        journaliser(conn, session.id_user, session.login, "STRUCTURE_STANDARD_GENEREE",
                    f"{annee} | {sections.libelle(section)} | {len(noms_sem)} {mot}s, {len(noms_sem) * 2} périodes")
    return {"semestres": len(noms_sem), "periodes": len(noms_sem) * 2}


def calendrier_annee(conn, session, annee, section=None) -> dict:
    """{'annee', 'debut', 'fin', 'avec_dates', 'semestres': [{id, libelle, section, debut, fin, periodes: [{id, libelle, debut, fin}]}]}.
    Les semestres (secondaire et humanitaire) et les trimestres (primaire) sont dans la même liste, chacun avec sa `section` ;
    `section` filtre sur une section."""
    exiger(conn, session, "LECTURE")
    _annee(conn, annee)
    c = conn.execute("SELECT * FROM ANNEE_CALENDRIER WHERE ANNEESCO = ?", (annee,)).fetchone()
    semestres = []
    for s in conn.execute("SELECT * FROM SEMESTRE_SCO WHERE ANNEESCO = ? AND (? IS NULL OR SECTION = ?) ORDER BY SECTION DESC, DATE_DEBUT",
                          (annee, section, section)):
        periodes = [{"id": p["ID_PER"], "libelle": p["LIBELLE"], "debut": _fr(p["DATE_DEBUT"]), "fin": _fr(p["DATE_FIN"])}
                    for p in conn.execute("SELECT * FROM PERIODE_SCO WHERE ID_SEM = ? ORDER BY DATE_DEBUT", (s["ID_SEM"],))]
        semestres.append({"id": s["ID_SEM"], "libelle": s["LIBELLE"], "section": s["SECTION"], "debut": _fr(s["DATE_DEBUT"]),
                          "fin": _fr(s["DATE_FIN"]), "periodes": periodes})
    return {"annee": annee, "debut": _fr(c["DATE_DEBUT"]) if c else "", "fin": _fr(c["DATE_FIN"]) if c else "",
            "avec_dates": c is not None, "semestres": semestres}


# ================================================================== cours (par niveau, option, année d'étude)
def choix_cours(conn, session) -> dict:
    """Listes de choix pour les écrans : {'niveaux': [{code, libelle, options: [{code, libelle}], annees_etude: [..]}]}."""
    exiger(conn, session, "LECTURE")
    niveaux = []
    for n in conn.execute("SELECT * FROM NIVEAU WHERE ACTIF = 1 ORDER BY DESI_NIVEAU COLLATE NOCASE"):
        options = [{"code": o["CODE_OPTION"], "libelle": o["DESI_OPTION"]} for o in conn.execute(
            "SELECT O.* FROM OPTION_SCO O JOIN POSSEDE P ON P.CODE_OPTION = O.CODE_OPTION WHERE P.CODE_NIVEAU = ? AND O.ACTIF = 1 "
            "ORDER BY O.DESI_OPTION COLLATE NOCASE", (n["CODE_NIVEAU"],))]
        annees = [a[0] for a in conn.execute("SELECT DISTINCT ANNEE_ETUDE FROM CLASSE WHERE CODE_NIVEAU = ? AND ACTIF = 1 "
                                             "AND ANNEE_ETUDE IS NOT NULL ORDER BY ANNEE_ETUDE", (n["CODE_NIVEAU"],))]
        niveaux.append({"code": n["CODE_NIVEAU"], "libelle": n["DESI_NIVEAU"], "options": options, "annees_etude": annees})
    return {"niveaux": niveaux}


def _valider_cours(conn, saisie: dict, sauf=None) -> dict:
    libelle = _libelle(saisie.get("libelle"), "le nom du cours")
    niveau = _texte(saisie.get("code_niveau"))
    if not conn.execute("SELECT 1 FROM NIVEAU WHERE CODE_NIVEAU = ?", (niveau,)).fetchone():
        raise ErreurCours("Choisissez le niveau du cours.")
    option = _texte(saisie.get("code_option")) or None
    if option and not conn.execute("SELECT 1 FROM POSSEDE WHERE CODE_NIVEAU = ? AND CODE_OPTION = ?", (niveau, option)).fetchone():
        raise ErreurCours(f"L'option {option} n'est pas proposée au niveau {niveau} : les options ne concernent que les humanités.")
    annee_etude = _texte(saisie.get("annee_etude")) or None
    if annee_etude and not conn.execute("SELECT 1 FROM CLASSE WHERE CODE_NIVEAU = ? AND LOWER(ANNEE_ETUDE) = LOWER(?)",
                                        (niveau, annee_etude)).fetchone():
        raise ErreurCours(f"Aucune classe du niveau {niveau} n'est de la « {annee_etude} » : créez d'abord la classe (Travaux techniques).")
    if conn.execute("SELECT 1 FROM COURS WHERE LIBELLE = ? COLLATE NOCASE AND CODE_NIVEAU = ? AND COALESCE(CODE_OPTION, '') = ? "
                    "AND COALESCE(ANNEE_ETUDE, '') = ? AND ID_COURS <> ?",
                    (libelle, niveau, option or "", annee_etude or "", sauf or -1)).fetchone():
        raise ErreurCours("Ce cours existe déjà pour ce niveau, cette option et cette année d'étude.")
    return {"libelle": libelle, "niveau": niveau, "option": option, "annee_etude": annee_etude,
            "heures": _heures(saisie.get("heures_semaine"))}


def _description(v) -> str:
    return " | ".join(p for p in (v["libelle"], v["niveau"], v["option"], v["annee_etude"], f"{v['heures']} h/semaine") if p)


def ajouter_cours(conn, session, saisie: dict) -> int:
    """saisie : libelle, code_niveau, code_option (facultatif), annee_etude (facultatif), heures_semaine."""
    exiger(conn, session, "AJOUT")
    v = _valider_cours(conn, saisie)
    try:
        with conn:
            cur = conn.execute("INSERT INTO COURS (LIBELLE, CODE_NIVEAU, CODE_OPTION, ANNEE_ETUDE, HEURES_SEMAINE, DATE_ENREG, ENREGISTRE_PAR) "
                               "VALUES (?,?,?,?,?,?,?)", (v["libelle"], v["niveau"], v["option"], v["annee_etude"], v["heures"],
                                                          iso(maintenant()), session.login))
            journaliser(conn, session.id_user, session.login, "COURS_AJOUT", _description(v))
    except sqlite3.IntegrityError as erreur:
        raise ErreurCours(f"Enregistrement impossible : {erreur}") from None
    return cur.lastrowid


def _cours(conn, id_cours):
    l = conn.execute("SELECT * FROM COURS WHERE ID_COURS = ?", (id_cours,)).fetchone()
    if not l:
        raise ErreurCours("Cours introuvable.")
    return l


def _nb_classes(conn, id_cours) -> int:
    return conn.execute("SELECT COUNT(*) FROM COURS_CLASSE WHERE ID_COURS = ?", (id_cours,)).fetchone()[0]


def modifier_cours(conn, session, id_cours, saisie: dict):
    """Le nom et les heures se changent toujours ; le niveau, l'option et l'année d'étude seulement tant que le cours n'est
    ouvert dans aucune classe."""
    exiger(conn, session, "MODIFICATION")
    c = _cours(conn, id_cours)
    v = _valider_cours(conn, saisie, sauf=id_cours)
    if _nb_classes(conn, id_cours) and (v["niveau"], v["option"], v["annee_etude"]) != (c["CODE_NIVEAU"], c["CODE_OPTION"], c["ANNEE_ETUDE"]):
        raise ErreurCours("Ce cours est déjà ouvert dans des classes : son niveau, son option et son année d'étude ne changent plus. "
                          "Désactivez-le et créez-en un nouveau.")
    with conn:
        conn.execute("UPDATE COURS SET LIBELLE=?, CODE_NIVEAU=?, CODE_OPTION=?, ANNEE_ETUDE=?, HEURES_SEMAINE=? WHERE ID_COURS=?",
                     (v["libelle"], v["niveau"], v["option"], v["annee_etude"], v["heures"], id_cours))
        journaliser(conn, session.id_user, session.login, "COURS_MODIFICATION", f"{c['LIBELLE']} -> {_description(v)}")


def changer_activite_cours(conn, session, id_cours, actif: bool):
    exiger(conn, session, "MODIFICATION")
    c = _cours(conn, id_cours)
    if bool(c["ACTIF"]) == actif:
        return
    with conn:
        conn.execute("UPDATE COURS SET ACTIF = ? WHERE ID_COURS = ?", (1 if actif else 0, id_cours))
        journaliser(conn, session.id_user, session.login, "COURS_ACTIVATION" if actif else "COURS_DESACTIVATION", c["LIBELLE"])


def supprimer_cours(conn, session, id_cours):
    exiger(conn, session, "SUPPRESSION")
    c = _cours(conn, id_cours)
    if _nb_classes(conn, id_cours):
        raise ErreurCours("Ce cours est ouvert dans des classes : on ne le supprime pas, on le désactive.")
    with conn:
        conn.execute("DELETE FROM COURS WHERE ID_COURS = ?", (id_cours,))
        journaliser(conn, session.id_user, session.login, "COURS_SUPPRESSION", c["LIBELLE"])


_SELECT_COURS = ("SELECT C.*, N.DESI_NIVEAU, O.DESI_OPTION, (SELECT COUNT(*) FROM COURS_CLASSE X WHERE X.ID_COURS = C.ID_COURS) AS NB "
                 "FROM COURS C JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION ")


def _cours_vers_dict(l) -> dict:
    return {"id": l["ID_COURS"], "libelle": l["LIBELLE"], "code_niveau": l["CODE_NIVEAU"], "niveau": l["DESI_NIVEAU"],
            "code_option": l["CODE_OPTION"] or "", "option": l["DESI_OPTION"] or "", "annee_etude": l["ANNEE_ETUDE"] or "",
            "heures": l["HEURES_SEMAINE"], "actif": bool(l["ACTIF"]), "nb_classes": l["NB"]}


def lister_cours(conn, session, code_niveau=None, recherche="", inclure_inactifs=True) -> list:
    exiger(conn, session, "LECTURE")
    cond, params = [], []
    if code_niveau:
        cond.append("C.CODE_NIVEAU = ?")
        params.append(code_niveau)
    if not inclure_inactifs:
        cond.append("C.ACTIF = 1")
    liste = [_cours_vers_dict(l) for l in conn.execute(
        _SELECT_COURS + ("WHERE " + " AND ".join(cond) + " " if cond else "") + "ORDER BY N.DESI_NIVEAU COLLATE NOCASE, C.ANNEE_ETUDE, "
        "C.LIBELLE COLLATE NOCASE", params)]
    terme = donnees.sans_accents(_texte(recherche))
    if terme:
        liste = [c for c in liste if terme in donnees.sans_accents(f"{c['libelle']} {c['niveau']} {c['option']} {c['annee_etude']}")]
    return liste


# ================================================================== classes et programme
def lister_classes(conn, session) -> list:
    """Classes actives : [{n_classe, designation, code_niveau, niveau, code_option, option, annee_etude}]."""
    exiger(conn, session, "LECTURE")
    return [{"n_classe": l["N_CLASSE"], "designation": l["DESI_CLASSE"], "code_niveau": l["CODE_NIVEAU"], "niveau": l["DESI_NIVEAU"],
             "code_option": l["CODE_OPTION"] or "", "option": l["DESI_OPTION"] or "", "annee_etude": l["ANNEE_ETUDE"] or ""}
            for l in conn.execute("SELECT C.*, N.DESI_NIVEAU, O.DESI_OPTION FROM CLASSE C JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
                                  "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION WHERE C.ACTIF = 1 "
                                  "ORDER BY N.DESI_NIVEAU COLLATE NOCASE, C.ANNEE_ETUDE, C.DIVISION, C.DESI_CLASSE")]


def _classe(conn, n_classe):
    l = conn.execute("SELECT * FROM CLASSE WHERE N_CLASSE = ?", (n_classe,)).fetchone()
    if not l:
        raise ErreurCours("Classe introuvable.")
    return l


def _applicable(c, classe) -> bool:
    return (c["CODE_NIVEAU"] == classe["CODE_NIVEAU"] and (not c["CODE_OPTION"] or c["CODE_OPTION"] == classe["CODE_OPTION"])
            and (not c["ANNEE_ETUDE"] or (c["ANNEE_ETUDE"] or "").lower() == (classe["ANNEE_ETUDE"] or "").lower()))


def _verifier_annee_ouverte(conn, annee):
    ligne = _annee(conn, annee)
    if not ligne["ACTIF"]:
        raise ErreurCours(f"L'année {annee} est désactivée.")
    return ligne


def _ligne_cc(l) -> dict:
    return {"id": l["ID_CC"], "id_cours": l["ID_COURS"], "cours": l["COURS"], "heures": l["HEURES_SEMAINE"],
            "matricule": l["MATRICULE_PROF"] or "", "professeur": donnees.nom_complet(l) if l["MATRICULE_PROF"] else "",
            "n_classe": l["N_CLASSE"], "classe": l["DESI_CLASSE"], "niveau": l["DESI_NIVEAU"], "option": l["DESI_OPTION"] or "",
            "annee": l["ANNEESCO"], "cours_actif": bool(l["COURS_ACTIF"])}


_SELECT_CC = ("SELECT X.*, C.LIBELLE AS COURS, C.ACTIF AS COURS_ACTIF, K.DESI_CLASSE, N.DESI_NIVEAU, O.DESI_OPTION, "
              "P.NOM, P.POSTNOM, P.PRENOM FROM COURS_CLASSE X JOIN COURS C ON C.ID_COURS = X.ID_COURS "
              "JOIN CLASSE K ON K.N_CLASSE = X.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = K.CODE_NIVEAU "
              "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = K.CODE_OPTION LEFT JOIN PERSONNEL P ON P.MATRICULE = X.MATRICULE_PROF ")


def programme_classe(conn, session, annee, n_classe) -> dict:
    """Cours ouverts dans la classe pour l'année, et cours applicables pas encore ouverts.
    {'classe': {...}, 'cours': [ligne_cc], 'a_ouvrir': [{id_cours, libelle, heures}]}."""
    exiger(conn, session, "LECTURE")
    _annee(conn, annee)
    classe = _classe(conn, n_classe)
    lignes = [_ligne_cc(l) for l in conn.execute(_SELECT_CC + "WHERE X.ANNEESCO = ? AND X.N_CLASSE = ? ORDER BY C.LIBELLE COLLATE NOCASE",
                                                 (annee, n_classe))]
    ouverts = {l["id_cours"] for l in lignes}
    a_ouvrir = [{"id_cours": c["ID_COURS"], "libelle": c["LIBELLE"], "heures": c["HEURES_SEMAINE"]}
                for c in conn.execute("SELECT * FROM COURS WHERE ACTIF = 1 ORDER BY LIBELLE COLLATE NOCASE")
                if _applicable(c, classe) and c["ID_COURS"] not in ouverts]
    return {"classe": {"n_classe": classe["N_CLASSE"], "designation": classe["DESI_CLASSE"]}, "cours": lignes, "a_ouvrir": a_ouvrir}


def ouvrir_cours(conn, session, annee, n_classe, ids_cours=None) -> int:
    """Ouvre des cours dans la classe pour l'année (`ids_cours` : liste, ou None = tous les cours applicables pas encore ouverts).
    Les heures par semaine viennent du cours. Retourne le nombre de cours ouverts."""
    exiger(conn, session, "AJOUT")
    _verifier_annee_ouverte(conn, annee)
    classe = _classe(conn, n_classe)
    if not classe["ACTIF"]:
        raise ErreurCours("Cette classe est désactivée.")
    deja = {l[0] for l in conn.execute("SELECT ID_COURS FROM COURS_CLASSE WHERE ANNEESCO = ? AND N_CLASSE = ?", (annee, n_classe))}
    if ids_cours is None:
        cibles = [c for c in conn.execute("SELECT * FROM COURS WHERE ACTIF = 1") if _applicable(c, classe) and c["ID_COURS"] not in deja]
    else:
        cibles = []
        for i in ids_cours:
            c = _cours(conn, i)
            if not c["ACTIF"]:
                raise ErreurCours(f"Le cours « {c['LIBELLE']} » est désactivé.")
            if not _applicable(c, classe):
                raise ErreurCours(f"Le cours « {c['LIBELLE']} » ne s'applique pas à la classe {classe['DESI_CLASSE']} "
                                  f"(niveau, option ou année d'étude différents).")
            if i in deja:
                raise ErreurCours(f"Le cours « {c['LIBELLE']} » est déjà ouvert dans cette classe.")
            cibles.append(c)
    if not cibles:
        return 0
    with conn:
        for c in cibles:
            conn.execute("INSERT INTO COURS_CLASSE (ANNEESCO, N_CLASSE, ID_COURS, HEURES_SEMAINE, DATE_ENREG, ENREGISTRE_PAR) "
                         "VALUES (?,?,?,?,?,?)", (annee, n_classe, c["ID_COURS"], c["HEURES_SEMAINE"], iso(maintenant()), session.login))
        journaliser(conn, session.id_user, session.login, "COURS_OUVERT_CLASSE",
                    f"{annee} | {classe['DESI_CLASSE']} | {len(cibles)} cours : " + ", ".join(c["LIBELLE"] for c in cibles)[:300])
        synchroniser_primaire(conn, annee, n_classe, session.login)       # primaire : les nouveaux cours vont au titulaire
    return len(cibles)


def synchroniser_primaire(conn, annee, n_classe, login="SYSTEME"):
    """Au PRIMAIRE le titulaire est l'unique enseignant de sa classe : tous les cours ouverts de la classe lui sont attribués (et
    retirés si la classe n'a plus de titulaire). Sans effet pour une classe du secondaire ou des humanités. À appeler dans la
    transaction de l'appelant. Retourne le nombre de cours modifiés."""
    if not sections.est_primaire(conn, n_classe):
        return 0
    t = conn.execute("SELECT MATRICULE FROM TITULAIRE_CLASSE WHERE ANNEESCO = ? AND N_CLASSE = ?", (annee, n_classe)).fetchone()
    matricule = t["MATRICULE"] if t else None
    n = conn.execute("UPDATE COURS_CLASSE SET MATRICULE_PROF = ?, DATE_MODIF = ?, MODIFIE_PAR = ? "
                     "WHERE ANNEESCO = ? AND N_CLASSE = ? AND COALESCE(MATRICULE_PROF, '') <> COALESCE(?, '')",
                     (matricule, iso(maintenant()), login, annee, n_classe, matricule)).rowcount
    return n


def _cc(conn, id_cc):
    l = conn.execute(_SELECT_CC + "WHERE X.ID_CC = ?", (id_cc,)).fetchone()
    if not l:
        raise ErreurCours("Ce cours n'est pas ouvert dans cette classe.")
    return l


def modifier_heures(conn, session, id_cc, heures):
    exiger(conn, session, "MODIFICATION")
    l = _cc(conn, id_cc)
    h = _heures(heures)
    with conn:
        conn.execute("UPDATE COURS_CLASSE SET HEURES_SEMAINE = ?, DATE_MODIF = ?, MODIFIE_PAR = ? WHERE ID_CC = ?",
                     (h, iso(maintenant()), session.login, id_cc))
        journaliser(conn, session.id_user, session.login, "COURS_HEURES_MODIFIEES",
                    f"{l['ANNEESCO']} | {l['DESI_CLASSE']} | {l['COURS']} | {l['HEURES_SEMAINE']} -> {h} h/semaine")


def retirer_cours_de_classe(conn, session, id_cc):
    """Retire un cours d'une classe (sans toucher au cours lui-même). Si un professeur y était attribué, l'attribution disparaît."""
    exiger(conn, session, "SUPPRESSION")
    l = _cc(conn, id_cc)
    if conn.execute("SELECT 1 FROM EVALUATION WHERE ID_CC = ? UNION SELECT 1 FROM CONDUITE WHERE ID_CC = ?", (id_cc, id_cc)).fetchone():
        raise ErreurCours("Des points sont déjà saisis pour ce cours dans cette classe : on ne le retire pas.")
    with conn:
        conn.execute("DELETE FROM COURS_CLASSE WHERE ID_CC = ?", (id_cc,))
        journaliser(conn, session.id_user, session.login, "COURS_RETIRE_CLASSE",
                    f"{l['ANNEESCO']} | {l['DESI_CLASSE']} | {l['COURS']}"
                    + (f" | professeur : {donnees.nom_complet(l)}" if l["MATRICULE_PROF"] else ""))


# ================================================================== professeurs
def _professeur_valide(conn, matricule):
    p = conn.execute("SELECT * FROM PERSONNEL WHERE MATRICULE = ?", (matricule,)).fetchone()
    if not p:
        raise ErreurCours("Agent introuvable.")
    if not p["ACTIF"]:
        raise ErreurCours(f"{donnees.nom_complet(p)} : le dossier est désactivé, on ne lui attribue plus de cours.")
    return p


def attribuer_professeur(conn, session, ids_cc, matricule) -> dict:
    """Attribue le professeur `matricule` aux cours ouverts `ids_cc` (liste d'identifiants COURS_CLASSE), ou retire le professeur
    si `matricule` est vide. Le droit « Ajout » suffit pour un cours sans professeur ; changer ou retirer un professeur demande
    « Modification ». Un professeur déjà attribué au même cours est laissé tel quel. Retourne {'faits': n, 'inchanges': n}."""
    ids_cc = list(ids_cc or [])
    if not ids_cc:
        raise ErreurCours("Choisissez au moins un cours dans la liste.")
    matricule = _texte(matricule) or None
    prof = _professeur_valide(conn, matricule) if matricule else None
    lignes = [_cc(conn, i) for i in ids_cc]
    for l in lignes:
        if sections.est_primaire(conn, l["N_CLASSE"]):
            raise ErreurCours(f"Classe {l['DESI_CLASSE']} (primaire) : le titulaire est l'unique enseignant de la classe. Ses cours lui sont "
                              "attribués automatiquement ; pour changer d'enseignant, désignez un autre titulaire "
                              "(Direction des études > Enseignants et classes).")
    faits, inchanges = [], 0
    for l in lignes:
        if (l["MATRICULE_PROF"] or None) == matricule:
            inchanges += 1
            continue
        exiger(conn, session, "MODIFICATION" if (l["MATRICULE_PROF"] or matricule is None) else "AJOUT")
        if not l["COURS_ACTIF"] and matricule:
            raise ErreurCours(f"Le cours « {l['COURS']} » est désactivé.")
        faits.append(l)
    if faits:
        with conn:
            for l in faits:
                conn.execute("UPDATE COURS_CLASSE SET MATRICULE_PROF = ?, DATE_MODIF = ?, MODIFIE_PAR = ? WHERE ID_CC = ?",
                             (matricule, iso(maintenant()), session.login, l["ID_CC"]))
            if prof:
                resume = ", ".join(f"{l['COURS']} ({l['DESI_CLASSE']})" for l in faits)[:300]
                journaliser(conn, session.id_user, session.login, "PROFESSEUR_ATTRIBUE",
                            f"{matricule} | {donnees.nom_complet(prof)} | {faits[0]['ANNEESCO']} | {len(faits)} cours : {resume}")
            else:
                resume = ", ".join(f"{l['COURS']} ({l['DESI_CLASSE']}) : {donnees.nom_complet(l)}" for l in faits)[:300]
                journaliser(conn, session.id_user, session.login, "PROFESSEUR_RETIRE", f"{faits[0]['ANNEESCO']} | {len(faits)} cours : {resume}")
    return {"faits": len(faits), "inchanges": inchanges}


def lister_professeurs(conn, session, annee, recherche="", seulement_enseignants=False) -> list:
    """Agents en service avec leur charge de l'année : [{matricule, nom_complet, fonction, nb_cours, nb_classes, heures}]."""
    exiger(conn, session, "LECTURE")
    _annee(conn, annee)
    charges = {l["MATRICULE_PROF"]: l for l in conn.execute(
        "SELECT MATRICULE_PROF, COUNT(*) AS NC, COUNT(DISTINCT N_CLASSE) AS NK, SUM(HEURES_SEMAINE) AS H FROM COURS_CLASSE "
        "WHERE ANNEESCO = ? AND MATRICULE_PROF IS NOT NULL GROUP BY MATRICULE_PROF", (annee,))}
    terme = donnees.sans_accents(_texte(recherche))
    liste = []
    for p in conn.execute("SELECT * FROM PERSONNEL WHERE ACTIF = 1 ORDER BY NOM COLLATE NOCASE, POSTNOM, PRENOM"):
        c = charges.get(p["MATRICULE"])
        if seulement_enseignants and not c:
            continue
        nom = donnees.nom_complet(p)
        if terme and terme not in donnees.sans_accents(f"{p['MATRICULE']} {nom} {p['FONCTION'] or ''}"):
            continue
        liste.append({"matricule": p["MATRICULE"], "nom_complet": nom, "fonction": p["FONCTION"] or "",
                      "nb_cours": c["NC"] if c else 0, "nb_classes": c["NK"] if c else 0, "heures": (c["H"] or 0) if c else 0})
    return liste


def classes_du_professeur(conn, session, annee, matricule) -> dict:
    """Les classes et cours d'un professeur pour une année : {'lignes': [ligne_cc], 'nb_classes', 'nb_cours', 'heures'}."""
    exiger(conn, session, "LECTURE")
    _annee(conn, annee)
    p = conn.execute("SELECT 1 FROM PERSONNEL WHERE MATRICULE = ?", (matricule,)).fetchone()
    if not p:
        raise ErreurCours("Agent introuvable.")
    lignes = [_ligne_cc(l) for l in conn.execute(
        _SELECT_CC + "WHERE X.ANNEESCO = ? AND X.MATRICULE_PROF = ? ORDER BY N.DESI_NIVEAU COLLATE NOCASE, K.DESI_CLASSE, "
        "C.LIBELLE COLLATE NOCASE", (annee, matricule))]
    return {"lignes": lignes, "nb_classes": len({l["n_classe"] for l in lignes}), "nb_cours": len(lignes),
            "heures": sum(l["heures"] for l in lignes)}

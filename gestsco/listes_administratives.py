"""Secrétariat, 4e fonctionnalité « Listes et rapports administratifs » (secondaire et humanitaire), sans interface graphique : testable seule.

La secrétaire GÉNÈRE et IMPRIME (PDF) ou EXPORTE (CSV) :
- la liste des élèves par classe, option et année scolaire (une page ou plus par classe, avec l'effectif, les garçons et les filles) ;
- la liste des dossiers incomplets par classe, option et année scolaire (avec le tuteur et son téléphone, pour pouvoir le relancer).

Un dossier est « incomplet » au sens du Secrétariat (secretariat.py) : la secrétaire n'a pas (ou plus) déclaré le dossier complet. Rien n'est
calculé ici : aucune pièce n'est exigée, et ces listes ne modifient rien.

Sélection : élèves INSCRITS dans l'année choisie (l'année en cours par défaut), classes de la section Secondaire et humanitaire seulement.
Les élèves désactivés n'y figurent pas, sauf si on le demande (`desactives=True`) : utile pour la liste d'une année passée, dont certains
élèves ont quitté l'école depuis. La liste des dossiers incomplets ne porte jamais sur les élèves désactivés (il n'y a plus rien à compléter).

La liste des élèves (pas celle des dossiers incomplets, propre au Secrétariat) est aussi offerte à la Direction des études, à la Direction de
discipline et à la Préfecture : même contenu (sans l'état du dossier), mêmes filtres, impression PDF et export CSV.

Droits (relus dans la base à chaque appel ; refus = PermissionError, jamais une donnée) : « Lecture » sur le module de l'espace qui demande la
liste (« Secrétariat », « Direction des études », « Direction de discipline » ou « Préfecture ») pour consulter, imprimer et exporter.
Chaque consultation, impression et exportation est inscrite au journal (avec l'espace demandeur).
"""
import csv
import io
from datetime import datetime

import config
import donnees
import droits
import secretariat
import sections
from database import journaliser

GENRES = (("eleves", "Liste des élèves"), ("incomplets", "Dossiers incomplets"))
TITRES = {"eleves": "Liste des élèves", "incomplets": "Liste des dossiers incomplets"}
ESPACES = {"dossier_eleve": "Le Secrétariat", "direction_etudes": "La Direction des études",
           "direction_discipline": "La Direction de discipline", "prefecture": "La Préfecture"}
SANS_OPTION = "-"                        # valeur du filtre « classes sans option »
MAX_ELEVES = 5000                        # garde-fou : une école n'atteint pas ce nombre


class ErreurListes(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== droits et outils
def _espace(espace) -> str:
    if espace not in ESPACES:
        raise ErreurListes("Espace inconnu.")
    return espace


def peut(conn, session, droit="LECTURE", espace="dossier_eleve") -> bool:
    """Droit demandé sur le module de l'espace (Secrétariat par défaut) ET section Secondaire et humanitaire ouverte au compte."""
    espace = _espace(espace)
    if espace == "dossier_eleve":
        return secretariat.peut(conn, session, droit)
    if session is None or sections.SECONDAIRE not in sections.sections_de(conn, session):
        return False
    return droits.est_admin(conn, session) or droits.a_droit(conn, session, espace, droit)


def exiger(conn, session, droit="LECTURE", espace="dossier_eleve"):
    if not peut(conn, session, droit, espace):
        if espace == "dossier_eleve":
            secretariat.exiger(conn, session, droit)
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS[droit]} » "
                              f"sur « {config.MODULES_DROITS[espace][0]} » (section secondaire et humanitaire).")


def _fr(texte) -> str:
    texte = str(texte or "")
    return f"{texte[8:10]}/{texte[5:7]}/{texte[0:4]}" if len(texte) >= 10 and texte[4] == "-" else texte


def _genre(genre, espace="dossier_eleve") -> str:
    """Les dossiers incomplets ne concernent que le Secrétariat : les autres espaces n'ont que la liste des élèves."""
    return genre if genre in dict(GENRES) and (genre == "eleves" or espace == "dossier_eleve") else "eleves"


# ================================================================== filtres
def annees(conn, session, espace="dossier_eleve") -> list:
    """Années scolaires où des élèves du secondaire et humanitaire sont inscrits (la plus récente d'abord) ; l'année en cours y figure toujours."""
    exiger(conn, session, espace=espace)
    liste = [l["ANNEESCO"] for l in conn.execute(
        "SELECT DISTINCT I.ANNEESCO FROM INSCRIRE I JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
        "WHERE N.SECTION = 'SECONDAIRE' ORDER BY I.ANNEESCO DESC")]
    courante = donnees.annee_courante(conn)
    if courante and courante not in liste:
        liste.insert(0, courante)
    return liste


def filtres(conn, session, annee=None, espace="dossier_eleve") -> dict:
    """Classes et options de l'année (celles qui ont des élèves inscrits) : {'annee', 'classes': [...], 'options': [(code, libellé)], 'sans_option': bool}."""
    exiger(conn, session, espace=espace)
    annee = str(annee or "").strip() or donnees.annee_courante(conn) or ""
    classes, options = [], {}
    for l in conn.execute(
            "SELECT DISTINCT C.N_CLASSE, C.DESI_CLASSE, C.CODE_OPTION, O.DESI_OPTION FROM INSCRIRE I JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE "
            "JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
            "WHERE I.ANNEESCO = ? AND N.SECTION = 'SECONDAIRE' ORDER BY C.DESI_CLASSE COLLATE NOCASE", (annee,)):
        classes.append({"n_classe": l["N_CLASSE"], "designation": l["DESI_CLASSE"], "code_option": l["CODE_OPTION"] or "",
                        "option": l["DESI_OPTION"] or ""})
        if l["CODE_OPTION"]:
            options[l["CODE_OPTION"]] = l["DESI_OPTION"] or l["CODE_OPTION"]
    return {"annee": annee, "classes": classes, "options": sorted(options.items(), key=lambda x: x[1].lower()),
            "sans_option": any(not k["code_option"] for k in classes)}


# ================================================================== les listes
def _nettoyer(annee, n_classe, option) -> tuple:
    n_classe = int(n_classe) if str(n_classe or "").strip().isdigit() else None
    return str(annee or "").strip(), n_classe, str(option or "").strip()


def _lire(conn, annee, genre, n_classe, option, desactives) -> dict:
    """Construit la liste (sans contrôle de droit ni journal : l'appelant les a faits)."""
    cond = ["I.ANNEESCO = ?", "N.SECTION = 'SECONDAIRE'"]
    param = [annee]
    if genre == "incomplets" or not desactives:
        cond.append("E.ACTIF = 1")
    if genre == "incomplets":
        cond.append("COALESCE(D.COMPLET, 0) = 0")
    if n_classe:
        cond.append("I.N_CLASSE = ?")
        param.append(n_classe)
    if option == SANS_OPTION:
        cond.append("COALESCE(C.CODE_OPTION, '') = ''")
    elif option:
        cond.append("C.CODE_OPTION = ?")
        param.append(option)
    lignes = conn.execute(
        "SELECT E.MATRICULE, E.NOM, E.POSTNOM, E.PRENOM, E.SEXE, E.DATE_NAISSANCE, E.NOM_TUTEUR, E.TEL_TUTEUR, E.ACTIF, "
        "       C.N_CLASSE, C.DESI_CLASSE, O.DESI_OPTION, COALESCE(D.COMPLET, 0) AS COMPLET "
        "FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE "
        "JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
        "LEFT JOIN DOSSIER_ELEVE D ON D.MATRICULE = E.MATRICULE "
        f"WHERE {' AND '.join(cond)} "
        "ORDER BY C.DESI_CLASSE COLLATE NOCASE, C.N_CLASSE, E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE, E.MATRICULE "
        f"LIMIT {MAX_ELEVES}", param).fetchall()
    classes, par_classe = [], {}
    for l in lignes:
        k = par_classe.get(l["N_CLASSE"])
        if k is None:
            k = par_classe[l["N_CLASSE"]] = {"n_classe": l["N_CLASSE"], "classe": l["DESI_CLASSE"], "option": l["DESI_OPTION"] or "",
                                            "eleves": [], "total": 0, "garcons": 0, "filles": 0, "complets": 0, "incomplets": 0}
            classes.append(k)
        k["eleves"].append({
            "n": len(k["eleves"]) + 1, "matricule": l["MATRICULE"],
            "nom_complet": " ".join(x for x in (l["NOM"], l["POSTNOM"], l["PRENOM"]) if x), "sexe": l["SEXE"] or "",
            "naissance": _fr(l["DATE_NAISSANCE"]), "tuteur": l["NOM_TUTEUR"] or "", "tel_tuteur": l["TEL_TUTEUR"] or "",
            "complet": bool(l["COMPLET"]), "desactive": not l["ACTIF"]})
        k["total"] += 1
        k["garcons"] += l["SEXE"] == "M"
        k["filles"] += l["SEXE"] == "F"
        k["complets" if l["COMPLET"] else "incomplets"] += 1
    resume = {"classes": len(classes)}
    for cle in ("total", "garcons", "filles", "complets", "incomplets"):
        resume[cle] = sum(k[cle] for k in classes)
    return {"annee": annee, "genre": genre, "titre": TITRES[genre], "n_classe": n_classe, "option": option, "desactives": bool(desactives),
            "classes": classes, "resume": resume}


def liste(conn, session, genre="eleves", annee=None, n_classe=None, option="", desactives=False, journaliser_=True, espace="dossier_eleve") -> dict:
    """Liste des élèves (`genre` = « eleves ») ou des dossiers incomplets (« incomplets »), regroupée par classe.
    Retourne {'annee', 'genre', 'titre', 'classes': [{'n_classe', 'classe', 'option', 'eleves': [...], 'total', 'garcons', 'filles',
    'complets', 'incomplets'}], 'resume': {...}}. Filtres : classe (numéro), option (code, ou « - » pour les classes sans option)."""
    exiger(conn, session, espace=espace)
    genre = _genre(genre, espace)
    annee, n_classe, option = _nettoyer(annee, n_classe, option)
    annee = annee or donnees.annee_courante(conn) or ""
    if not annee:
        return {"espace": espace, "annee": "", "genre": genre, "titre": TITRES[genre], "n_classe": n_classe, "option": option, "desactives": bool(desactives),
                "classes": [], "resume": {"classes": 0, "total": 0, "garcons": 0, "filles": 0, "complets": 0, "incomplets": 0}}
    resultat = _lire(conn, annee, genre, n_classe, option, desactives)
    resultat["espace"] = espace
    if journaliser_:
        _tracer(conn, session, "LISTE_ADMIN_CONSULTEE", _detail(resultat))
    return resultat


def _detail(r) -> str:
    return (f"{r['titre']} | {r['annee']} | classe {r['n_classe'] or 'toutes'} | option {r['option'] or 'toutes'}"
            + (" | désactivés inclus" if r["desactives"] and r["genre"] == "eleves" else "") + f" | {r['resume']['total']} élève(s)"
            + (f" | espace {r['espace']}" if r.get("espace", "dossier_eleve") != "dossier_eleve" else ""))


def _tracer(conn, session, action, detail):
    with conn:
        journaliser(conn, session.id_user, session.login, action, detail)


# ================================================================== exportation CSV
def exporter_csv(conn, session, genre="eleves", annee=None, n_classe=None, option="", desactives=False, espace="dossier_eleve") -> tuple:
    """(texte CSV, nom du fichier) : une ligne par élève, séparateur « ; » (s'ouvre dans Excel)."""
    exiger(conn, session, espace=espace)
    r = liste(conn, session, genre, annee, n_classe, option, desactives, journaliser_=False, espace=espace)
    if not r["resume"]["total"]:
        raise ErreurListes("Aucun élève ne correspond : rien à exporter.")
    secr = espace == "dossier_eleve"
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";")
    w.writerow(["Année scolaire", "Classe", "Option", "N°", "Matricule", "Nom, postnom et prénom", "Sexe", "Date de naissance"]
               + (["Dossier"] if secr else []) + ["Tuteur", "Téléphone du tuteur", "Remarque"])
    for k in r["classes"]:
        for e in k["eleves"]:
            w.writerow([r["annee"], k["classe"], k["option"], e["n"], e["matricule"], e["nom_complet"], e["sexe"], e["naissance"]]
                       + (["Complet" if e["complet"] else "Incomplet"] if secr else [])
                       + [e["tuteur"], e["tel_tuteur"], "Désactivé" if e["desactive"] else ""])
    _tracer(conn, session, "LISTE_ADMIN_EXPORTEE", _detail(r) + " | CSV")
    return sortie.getvalue(), _nom_fichier(r, "csv")


# ================================================================== impression PDF
def _nom_fichier(r, extension) -> str:
    import bulletins
    classe = next((k["classe"] for k in r["classes"]), "") if r["n_classe"] else "toutes_classes"
    return bulletins._nom_fichier(r["titre"], r["annee"], classe, r["option"] if r["option"] != SANS_OPTION else "sans_option") + "." + extension


def document_pdf(conn, session, genre="eleves", annee=None, n_classe=None, option="", desactives=False, espace="dossier_eleve") -> tuple:
    """(octets PDF, nom du fichier) de la liste : une page au moins par classe, effectifs en pied de classe."""
    import listes_administratives_pdf
    exiger(conn, session, espace=espace)
    r = liste(conn, session, genre, annee, n_classe, option, desactives, journaliser_=False, espace=espace)
    if not r["resume"]["total"]:
        raise ErreurListes("Aucun élève ne correspond : rien à imprimer.")
    with open(config.DOSSIER_ASSETS / "logo_recu.jpg", "rb") as f:
        jpeg = f.read()
    octets = listes_administratives_pdf.generer(r, jpeg, datetime.now().strftime("%d/%m/%Y"))
    _tracer(conn, session, "LISTE_ADMIN_IMPRIMEE", _detail(r) + " | PDF")
    return octets, _nom_fichier(r, "pdf")

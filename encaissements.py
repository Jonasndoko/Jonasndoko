"""Module « Encaissement des fonds perçus ».

Un enregistrement d'encaissement = un percepteur déclare, à une date et dans une devise, le montant qu'il a
ENCAISSÉ et le montant qu'il a VERSÉ. L'ÉCART (calculé par le système, jamais saisi) = encaissé - versé :
positif = manquant, négatif = excédent.

Droits (module « encaissement », réglables dans le Gestionnaire d'accès ; l'Administrateur a tous les droits ici) :
- Lecture      : consulter la liste des encaissements et le rapport global ;
- Ajout        : enregistrer un encaissement ;
- Modification : corriger un encaissement ;
- Suppression  : supprimer un encaissement.
Chaque opération est contrôlée dans la base au moment de l'action et inscrite au journal.

Le rapport global d'une date regroupe, pour TOUS les percepteurs, les reçus de paiement par type de frais, puis les
encaissements / versements / écarts enregistrés ce jour-là.
"""
from datetime import date, datetime

import argent
import config
import droits
from database import iso, journaliser, maintenant
from paiements import _bornes_utc, lire_date

MODULE = "encaissement"


class ErreurEncaissement(Exception):
    """Erreur métier dont le message peut être affiché tel quel à l'utilisateur."""


# ------------------------------------------------------------------ droits
def peut(conn, session, droit) -> bool:
    """Vrai si le compte a ce droit sur le module (l'Administrateur les a tous, comme pour l'ouverture du module)."""
    return droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, droit)


def exiger(conn, session, droit):
    if not peut(conn, session, droit):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS.get(droit, droit)} » "
                              f"sur le module « {config.MODULES_DROITS[MODULE][0]} ».")


# ------------------------------------------------------------------ listes de choix
def liste_percepteurs(conn) -> list:
    """[(n_perc, nom complet)] des percepteurs dont le compte est actif (pour la liste déroulante)."""
    return [(l["N_PERC"], l["NOM_COMPLET"]) for l in conn.execute(
        "SELECT P.N_PERC, U.NOM_COMPLET FROM PERCEPTEUR P JOIN UTILISATEUR U ON U.ID_USER = P.ID_USER "
        "WHERE U.ACTIF = 1 ORDER BY U.NOM_COMPLET COLLATE NOCASE")]


def liste_devises(conn, inclure=None) -> list:
    """[(code, 'CODE - désignation')] des devises actives (+ `inclure` : une devise déjà utilisée, même désactivée)."""
    return [(l["CODE_DEVISE"], f"{l['CODE_DEVISE']} - {l['DESI_DEVISE']}") for l in conn.execute(
        "SELECT CODE_DEVISE, DESI_DEVISE FROM DEVISE WHERE ACTIF = 1 OR CODE_DEVISE = ? ORDER BY CODE_DEVISE", (inclure,))]


# ------------------------------------------------------------------ calculs et lecture des saisies
def calculer_ecart(encaisse: int, verse: int) -> int:
    """Écart = montant encaissé - montant versé (en centimes)."""
    return int(encaisse) - int(verse)


def etiquette_ecart(ecart: int) -> str:
    if ecart > 0:
        return "Manquant"
    if ecart < 0:
        return "Excédent"
    return "Aucun écart"


def lire_montant(texte, nom="montant", zero_permis=False) -> int:
    """'1 250,50' -> 125050. Lève ErreurEncaissement (message affichable) si vide, invalide ou nul."""
    if not (texte or "").strip():
        raise ErreurEncaissement(f"Saisissez le {nom}.")
    try:
        centimes = argent.vers_centimes(texte)
    except ValueError as erreur:
        raise ErreurEncaissement(f"Le {nom} est invalide. {erreur}") from None
    if centimes == 0 and not zero_permis:
        raise ErreurEncaissement(f"Le {nom} doit être supérieur à zéro.")
    return centimes


def _lire_jour(jour) -> date:
    if isinstance(jour, date):
        return jour
    try:
        return lire_date(jour)
    except Exception as erreur:                       # ErreurPaiement : même message de date
        raise ErreurEncaissement(str(erreur)) from None


def _controler(conn, jour, n_perc, code_devise, encaisse, verse, devise_actuelle=None, perc_actuel=None):
    """Contrôles communs à l'ajout et à la modification. Retourne la date."""
    jour = _lire_jour(jour)
    if jour > datetime.now().date():
        raise ErreurEncaissement("La date ne peut pas être dans le futur.")
    perc = conn.execute("SELECT U.ACTIF FROM PERCEPTEUR P JOIN UTILISATEUR U ON U.ID_USER = P.ID_USER "
                        "WHERE P.N_PERC = ?", (n_perc,)).fetchone() if n_perc is not None else None
    if not perc:
        raise ErreurEncaissement("Choisissez un percepteur dans la liste.")
    if not perc["ACTIF"] and n_perc != perc_actuel:
        raise ErreurEncaissement("Ce percepteur est désactivé : aucun encaissement ne peut lui être attribué.")
    dev = conn.execute("SELECT ACTIF FROM DEVISE WHERE CODE_DEVISE = ?", (code_devise,)).fetchone() if code_devise else None
    if not dev:
        raise ErreurEncaissement("Choisissez la devise.")
    if not dev["ACTIF"] and code_devise != devise_actuelle:
        raise ErreurEncaissement("Cette devise est désactivée : elle ne peut plus être utilisée.")
    if not isinstance(encaisse, int) or encaisse <= 0:
        raise ErreurEncaissement("Le montant encaissé doit être supérieur à zéro.")
    if not isinstance(verse, int) or verse < 0:
        raise ErreurEncaissement("Le montant versé ne peut pas être négatif.")
    return jour


def _detail(n_enc, nom_perc, jour, code_devise, encaisse, verse, ecart) -> str:
    return (f"N°{n_enc} | {nom_perc} | {jour.isoformat()} | encaissé {argent.formater(encaisse)} {code_devise} | "
            f"versé {argent.formater(verse)} | écart {argent.formater(ecart)}")


def _nom_percepteur(conn, n_perc) -> str:
    l = conn.execute("SELECT U.NOM_COMPLET FROM PERCEPTEUR P JOIN UTILISATEUR U ON U.ID_USER = P.ID_USER "
                     "WHERE P.N_PERC = ?", (n_perc,)).fetchone()
    return l["NOM_COMPLET"] if l else f"percepteur {n_perc}"


# ------------------------------------------------------------------ écriture
def enregistrer(conn, session, n_perc, jour, code_devise, encaisse, verse) -> int:
    """Enregistre un encaissement et retourne son numéro. L'écart est calculé ici."""
    exiger(conn, session, "AJOUT")
    jour = _controler(conn, jour, n_perc, code_devise, encaisse, verse)
    ecart = calculer_ecart(encaisse, verse)
    with conn:
        n_enc = conn.execute(
            "INSERT INTO ENCAISSEMENT (DATE_ENC, N_PERC, CODE_DEVISE, MONT_ENCAISSE, MONT_VERSE, ECART, SAISI_PAR, DATE_SAISIE) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (jour.isoformat(), n_perc, code_devise, encaisse, verse, ecart, session.login, iso(maintenant()))).lastrowid
        journaliser(conn, session.id_user, session.login, "ENCAISSEMENT_ENREGISTRE",
                    _detail(n_enc, _nom_percepteur(conn, n_perc), jour, code_devise, encaisse, verse, ecart))
    return n_enc


def modifier(conn, session, n_enc, n_perc, jour, code_devise, encaisse, verse):
    """Corrige un encaissement existant (l'écart est recalculé)."""
    exiger(conn, session, "MODIFICATION")
    ancien = conn.execute("SELECT * FROM ENCAISSEMENT WHERE N_ENC = ?", (n_enc,)).fetchone()
    if not ancien:
        raise ErreurEncaissement("Cet encaissement n'existe plus.")
    jour = _controler(conn, jour, n_perc, code_devise, encaisse, verse, devise_actuelle=ancien["CODE_DEVISE"],
                      perc_actuel=ancien["N_PERC"])
    ecart = calculer_ecart(encaisse, verse)
    with conn:
        conn.execute("UPDATE ENCAISSEMENT SET DATE_ENC = ?, N_PERC = ?, CODE_DEVISE = ?, MONT_ENCAISSE = ?, "
                     "MONT_VERSE = ?, ECART = ? WHERE N_ENC = ?",
                     (jour.isoformat(), n_perc, code_devise, encaisse, verse, ecart, n_enc))
        avant = _detail(n_enc, _nom_percepteur(conn, ancien["N_PERC"]), date.fromisoformat(ancien["DATE_ENC"]),
                        ancien["CODE_DEVISE"], ancien["MONT_ENCAISSE"], ancien["MONT_VERSE"], ancien["ECART"])
        apres = _detail(n_enc, _nom_percepteur(conn, n_perc), jour, code_devise, encaisse, verse, ecart)
        journaliser(conn, session.id_user, session.login, "ENCAISSEMENT_MODIFIE", f"avant : {avant} || après : {apres}")


def supprimer(conn, session, n_enc):
    """Supprime un encaissement (rien d'autre n'en dépend). L'opération reste inscrite au journal."""
    exiger(conn, session, "SUPPRESSION")
    l = conn.execute("SELECT * FROM ENCAISSEMENT WHERE N_ENC = ?", (n_enc,)).fetchone()
    if not l:
        raise ErreurEncaissement("Cet encaissement n'existe plus.")
    with conn:
        conn.execute("DELETE FROM ENCAISSEMENT WHERE N_ENC = ?", (n_enc,))
        journaliser(conn, session.id_user, session.login, "ENCAISSEMENT_SUPPRIME",
                    _detail(n_enc, _nom_percepteur(conn, l["N_PERC"]), date.fromisoformat(l["DATE_ENC"]),
                            l["CODE_DEVISE"], l["MONT_ENCAISSE"], l["MONT_VERSE"], l["ECART"]))


# ------------------------------------------------------------------ lecture
def _ligne(l) -> dict:
    return {
        "n_enc": l["N_ENC"], "n_perc": l["N_PERC"], "percepteur": l["NOM_COMPLET"], "devise": l["CODE_DEVISE"],
        "jour": date.fromisoformat(l["DATE_ENC"]), "date_txt": date.fromisoformat(l["DATE_ENC"]).strftime("%d/%m/%Y"),
        "encaisse": l["MONT_ENCAISSE"], "verse": l["MONT_VERSE"], "ecart": l["ECART"],
        "encaisse_txt": argent.formater(l["MONT_ENCAISSE"]), "verse_txt": argent.formater(l["MONT_VERSE"]),
        "ecart_txt": argent.formater(l["ECART"]), "nature_ecart": etiquette_ecart(l["ECART"]),
    }


def charger(conn, session, n_enc) -> dict:
    """Un encaissement (pour pré-remplir le formulaire de modification)."""
    exiger(conn, session, "LECTURE")
    l = conn.execute("SELECT E.*, U.NOM_COMPLET FROM ENCAISSEMENT E JOIN PERCEPTEUR P ON P.N_PERC = E.N_PERC "
                     "JOIN UTILISATEUR U ON U.ID_USER = P.ID_USER WHERE E.N_ENC = ?", (n_enc,)).fetchone()
    if not l:
        raise ErreurEncaissement("Cet encaissement n'existe plus.")
    return _ligne(l)


def lister(conn, session, jour=None) -> list:
    """Encaissements enregistrés (ceux de la date `jour` si elle est donnée), du plus récent au plus ancien."""
    exiger(conn, session, "LECTURE")
    filtre, param = ("WHERE E.DATE_ENC = ? ", (jour.isoformat(),)) if jour else ("", ())
    return [_ligne(l) for l in conn.execute(
        "SELECT E.*, U.NOM_COMPLET FROM ENCAISSEMENT E JOIN PERCEPTEUR P ON P.N_PERC = E.N_PERC "
        "JOIN UTILISATEUR U ON U.ID_USER = P.ID_USER " + filtre +
        "ORDER BY E.DATE_ENC DESC, U.NOM_COMPLET COLLATE NOCASE, E.N_ENC DESC", param)]


# ------------------------------------------------------------------ rapport global
def rapport_global(conn, session, jour) -> dict:
    """Rapport de TOUS les percepteurs pour la date `jour` :
    - `groupes` : un groupe par type de frais, une ligne par percepteur (nombre de reçus et montants par devise) ;
    - `versements` : les encaissements enregistrés ce jour-là (encaissé, versé, écart), par percepteur ;
    - `totaux_versements` : encaissé, versé et écart par devise.
    Seuls les reçus VALIDES sont comptés."""
    exiger(conn, session, "LECTURE")
    jour = _lire_jour(jour)
    debut, fin = _bornes_utc(jour)

    lignes = conn.execute(
        "SELECT P.CODTF, F.DESITF, P.N_PERC, U.NOM_COMPLET, P.CODE_DEVISE, "
        "       COUNT(*) AS NB, SUM(P.MONT_PAYE) AS TOTAL "
        "FROM PAIEMENT P JOIN TYPE_FRAIS F ON F.CODTF = P.CODTF "
        "JOIN PERCEPTEUR PE ON PE.N_PERC = P.N_PERC JOIN UTILISATEUR U ON U.ID_USER = PE.ID_USER "
        "WHERE P.STATUT = 'VALIDE' AND P.DATE_PAY >= ? AND P.DATE_PAY < ? "
        "GROUP BY P.CODTF, F.DESITF, P.N_PERC, U.NOM_COMPLET, P.CODE_DEVISE "
        "ORDER BY P.CODTF, U.NOM_COMPLET COLLATE NOCASE, P.CODE_DEVISE",
        (debut, fin)).fetchall()
    nb_annules = conn.execute("SELECT COUNT(*) FROM PAIEMENT WHERE STATUT = 'ANNULE' AND DATE_PAY >= ? AND DATE_PAY < ?",
                              (debut, fin)).fetchone()[0]

    groupes, generaux, percepteurs_recus = {}, {}, {}
    nb_recus = 0
    for l in lignes:
        g = groupes.setdefault(l["CODTF"], {
            "type_frais": l["DESITF"],
            "lignes": {}, "totaux": {}, "nb_recus": 0})
        ligne = g["lignes"].setdefault(l["N_PERC"], {"n_perc": l["N_PERC"], "percepteur": l["NOM_COMPLET"],
                                                     "nb_recus": 0, "montants": {}})
        ligne["nb_recus"] += l["NB"]
        ligne["montants"][l["CODE_DEVISE"]] = ligne["montants"].get(l["CODE_DEVISE"], 0) + l["TOTAL"]
        g["totaux"][l["CODE_DEVISE"]] = g["totaux"].get(l["CODE_DEVISE"], 0) + l["TOTAL"]
        g["nb_recus"] += l["NB"]
        generaux[l["CODE_DEVISE"]] = generaux.get(l["CODE_DEVISE"], 0) + l["TOTAL"]
        percepteurs_recus[l["N_PERC"]] = l["NOM_COMPLET"]
        nb_recus += l["NB"]
    liste_groupes = []
    for g in groupes.values():
        liste_lignes = []
        for x in g["lignes"].values():
            x["montant_txt"] = "  ;  ".join(f"{argent.formater(c)} {d}" for d, c in sorted(x["montants"].items()))
            liste_lignes.append(x)
        g["lignes"] = liste_lignes
        g["totaux"] = sorted(g["totaux"].items())
        liste_groupes.append(g)

    versements = lister(conn, session, jour)
    versements.sort(key=lambda v: (v["percepteur"].lower(), v["n_enc"]))
    totaux_v = {}
    for v in versements:
        t = totaux_v.setdefault(v["devise"], [0, 0, 0])
        t[0] += v["encaisse"]
        t[1] += v["verse"]
        t[2] += v["ecart"]
    percepteurs_versement = {v["n_perc"] for v in versements}
    return {
        "date_txt": jour.strftime("%d/%m/%Y"), "jour": jour, "edite_le": datetime.now().strftime("%d/%m/%Y à %H:%M"),
        "groupes": liste_groupes, "totaux": sorted(generaux.items()), "nb_recus": nb_recus, "nb_annules": nb_annules,
        "versements": versements, "nb_encaissements": len(versements),
        "totaux_versements": [(d, t[0], t[1], t[2]) for d, t in sorted(totaux_v.items())],
        "sans_versement": sorted(nom for n, nom in percepteurs_recus.items() if n not in percepteurs_versement),
    }


def rapport_vide(rapport) -> bool:
    return not rapport["nb_recus"] and not rapport["nb_encaissements"]


def preparer_rapport_pdf(conn, session, jour) -> str:
    """Génère le PDF du rapport global et retourne son chemin."""
    import encaissement_pdf
    rapport = rapport_global(conn, session, jour)                  # vérifie le droit Lecture
    if rapport_vide(rapport):
        raise ErreurEncaissement("Rien à imprimer à cette date : aucun paiement ni encaissement enregistré.")
    config.DOSSIER_RECUS.mkdir(parents=True, exist_ok=True)
    chemin = str(config.DOSSIER_RECUS / f"Rapport_global_{rapport['jour'].isoformat()}.pdf")
    encaissement_pdf.generer_rapport_global_pdf(rapport, chemin, config.DOSSIER_ASSETS / "logo_recu.jpg")
    with conn:
        journaliser(conn, session.id_user, session.login, "RAPPORT_GLOBAL_IMPRIME",
                    f"{rapport['jour'].isoformat()} | {rapport['nb_recus']} reçu(s) | "
                    f"{rapport['nb_encaissements']} encaissement(s) | total {argent.resume_totaux(rapport['totaux'])}")
    return chemin

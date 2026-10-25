"""Module « Carte » : carte d'élève (recto : logo, nom de l'école, photo, informations ; verso : QR code).

L'utilisateur saisit le nom de l'élève : ses informations s'affichent (matricule, sexe, nationalité, adresse...). On peut
prendre sa photo avec la caméra (ou importer un fichier JPEG), puis imprimer la carte.

Droits (Gestionnaire d'accès > Autorisations) : Lecture (voir la fiche, imprimer la carte), Ajout (première photo),
Modification (remplacer la photo), Suppression (retirer la photo). L'Administrateur a tous les droits.
"""
from datetime import datetime

import config
import donnees
import droits
import identite
import sections
from database import iso, journaliser, maintenant

MODULE = "carte"
TAILLE_MAX_PHOTO = 600 * 1024               # octets
LIBELLE_SEXE = {"M": "Masculin", "F": "Féminin"}


class ErreurCarte(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ------------------------------------------------------------------ droits
def peut(conn, session, droit) -> bool:
    """Vrai si le compte a ce droit sur le module (l'Administrateur les a tous)."""
    return droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, droit)


def exiger(conn, session, droit):
    if not peut(conn, session, droit):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS.get(droit, droit)} » "
                              f"sur le module « {config.MODULES_DROITS[MODULE][0]} ».")


# ------------------------------------------------------------------ fiche de l'élève
def _date_fr(texte):
    try:
        return datetime.strptime(texte, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return ""


def fiche(conn, session, matricule) -> dict:
    """Informations affichées et imprimées sur la carte. Le code QR est attribué s'il manque."""
    exiger(conn, session, "LECTURE")
    e = donnees.get_eleve(conn, matricule)
    if e is None:
        raise ErreurCarte("Élève introuvable.")
    sections.exiger_carte(conn, session, matricule)            # pas de carte au primaire ; section ouverte au compte
    annee = donnees.annee_courante(conn)
    insc = next((i for i in donnees.inscriptions(conn, matricule) if i["ANNEESCO"] == annee), None)
    return {
        "matricule": e["MATRICULE"], "nom": e["NOM"], "postnom": e["POSTNOM"] or "", "prenom": e["PRENOM"] or "",
        "nom_complet": donnees.nom_complet(e), "sexe": e["SEXE"] or "", "sexe_txt": LIBELLE_SEXE.get(e["SEXE"], ""),
        "naissance": _date_fr(e["DATE_NAISSANCE"]), "lieu_naissance": e["LIEU_NAISSANCE"] or "",
        "nationalite": e["NATIONALITE"] or "", "adresse": e["ADRESSE"] or "", "telephone": e["TELEPHONE"] or "",
        "tuteur": e["NOM_TUTEUR"] or "", "tel_tuteur": e["TEL_TUTEUR"] or "", "actif": bool(e["ACTIF"]),
        "classe": insc["DESI_CLASSE"] if insc else "", "option": (insc["DESI_OPTION"] or "") if insc else "",
        "niveau": insc["DESI_NIVEAU"] if insc else "", "annee": annee or "",
        "code_qr": identite.assurer_code_qr(conn, matricule), "a_photo": a_photo(conn, matricule),
    }


def journaliser_consultation(conn, session, matricule):
    """Inscrit au journal l'ouverture de la fiche d'un élève dans le module Carte (traçabilité : qui a consulté quel dossier)."""
    with conn:
        journaliser(conn, session.id_user, session.login, "FICHE_CARTE_CONSULTEE", matricule)


# ------------------------------------------------------------------ photo
def a_photo(conn, matricule) -> bool:
    return conn.execute("SELECT 1 FROM PHOTO_ELEVE WHERE MATRICULE = ?", (matricule,)).fetchone() is not None


def lire_photo(conn, session, matricule):
    """JPEG de l'élève, ou None."""
    exiger(conn, session, "LECTURE")
    sections.exiger_carte(conn, session, matricule)
    ligne = conn.execute("SELECT PHOTO FROM PHOTO_ELEVE WHERE MATRICULE = ?", (matricule,)).fetchone()
    return bytes(ligne["PHOTO"]) if ligne else None


def enregistrer_photo(conn, session, matricule, jpeg: bytes):
    """Enregistre (ou remplace) la photo. Ajout si l'élève n'en a pas encore, Modification s'il en a une."""
    existe = a_photo(conn, matricule)
    exiger(conn, session, "MODIFICATION" if existe else "AJOUT")
    if donnees.get_eleve(conn, matricule) is None:
        raise ErreurCarte("Élève introuvable.")
    sections.exiger_carte(conn, session, matricule)
    if not jpeg or jpeg[:2] != b"\xff\xd8":
        raise ErreurCarte("La photo doit être une image JPEG.")
    if len(jpeg) > TAILLE_MAX_PHOTO:
        raise ErreurCarte("La photo est trop lourde (600 Ko au maximum). Reprenez-la avec la caméra.")
    with conn:
        conn.execute("INSERT OR REPLACE INTO PHOTO_ELEVE (MATRICULE, PHOTO, DATE_PHOTO, PRIS_PAR) VALUES (?,?,?,?)",
                     (matricule, jpeg, iso(maintenant()), session.login))
        journaliser(conn, session.id_user, session.login, "PHOTO_REMPLACEE" if existe else "PHOTO_ENREGISTREE",
                    f"{matricule} | {len(jpeg)} octets")


def supprimer_photo(conn, session, matricule):
    exiger(conn, session, "SUPPRESSION")
    sections.exiger_carte(conn, session, matricule)
    if not a_photo(conn, matricule):
        raise ErreurCarte("Cet élève n'a pas de photo.")
    with conn:
        conn.execute("DELETE FROM PHOTO_ELEVE WHERE MATRICULE = ?", (matricule,))
        journaliser(conn, session.id_user, session.login, "PHOTO_SUPPRIMEE", matricule)


# ------------------------------------------------------------------ impression
def preparer_carte_pdf(conn, session, matricule, a4=True) -> str:
    """Génère le PDF de la carte (recto + verso) et retourne son chemin.
    a4=True : une feuille A4 avec le recto et le verso côte à côte (imprimante ordinaire) ;
    a4=False : 2 pages au format de la carte (54 x 85,6 mm), pour une imprimante de cartes."""
    import carte_pdf
    f = fiche(conn, session, matricule)                       # vérifie le droit Lecture
    if not f["actif"]:
        raise ErreurCarte("Cet élève est désactivé : sa carte ne peut pas être imprimée.")
    config.DOSSIER_RECUS.mkdir(parents=True, exist_ok=True)
    nom = identite.nom_de_fichier(f["matricule"])
    chemin = str(config.DOSSIER_RECUS / f"Carte_{nom}{'' if a4 else '_carte'}.pdf")
    carte_pdf.generer(f, lire_photo(conn, session, matricule), chemin, config.DOSSIER_ASSETS / "logo_recu.jpg", a4=a4)
    with conn:
        journaliser(conn, session.id_user, session.login, "CARTE_IMPRIMEE",
                    f"{f['matricule']} | {'A4' if a4 else 'format carte'} | photo : {'oui' if f['a_photo'] else 'non'}")
    return chemin

"""Sections de l'école : PRIMAIRE, et SECONDAIRE (secondaire et humanitaire), dans un seul logiciel.

- La section d'une classe est celle de son NIVEAU (colonne NIVEAU.SECTION, choisie par l'Administrateur quand il crée le niveau).
- Chaque compte a une ou plusieurs sections ouvertes (table SECTION_UTILISATEUR, réglée par l'Administrateur dans le Gestionnaire d'accès
  > Autorisations). Sans aucune ligne, le compte garde l'accès à TOUTES les sections (comptes créés avant la version 0.36).
  L'Administrateur voit toujours tout.
- Un compte ne voit, n'enregistre et n'imprime que les élèves, candidats, classes et reçus des sections qui lui sont ouvertes.
  Les fonctions des autres modules appellent `exiger_classe` / `exiger_eleve` (jamais une donnée envoyée par l'écran) et filtrent leurs
  listes avec `filtre_classes`.
- La carte d'élève n'existe pas au primaire (`exiger_carte`).
- Au primaire, le titulaire est l'unique enseignant de sa classe (voir bulletins.py et cours.py).
"""
import droits
from database import journaliser

PRIMAIRE = "PRIMAIRE"
SECONDAIRE = "SECONDAIRE"
SECTIONS = ((PRIMAIRE, "Primaire"), (SECONDAIRE, "Secondaire et humanitaire"))
LIBELLES = dict(SECTIONS)
TOUTES = frozenset(LIBELLES)
REFUS_SECTION = "Accès refusé : cette classe appartient à une section de l'école qui ne vous est pas ouverte."
REFUS_CARTE = "La carte d'élève n'existe pas pour la section primaire."


class ErreurSection(Exception):
    """Erreur dont le message peut être affiché tel quel."""


def libelle(section) -> str:
    return LIBELLES.get(section, str(section or ""))


# ================================================================== sections d'un compte
def sections_de(conn, session) -> frozenset:
    """Sections ouvertes au compte connecté (relues dans la base à chaque appel)."""
    if session is None or not droits._utilisateur_actif(conn, session):
        return frozenset()
    if droits.est_admin(conn, session):
        return TOUTES
    lignes = {l[0] for l in conn.execute("SELECT SECTION FROM SECTION_UTILISATEUR WHERE ID_USER = ?", (session.id_user,))}
    return frozenset(lignes) & TOUTES or TOUTES


def sections_explicites(conn, id_user) -> frozenset:
    """Sections cochées pour un compte (vide : aucune restriction)."""
    return frozenset(l[0] for l in conn.execute("SELECT SECTION FROM SECTION_UTILISATEUR WHERE ID_USER = ?", (id_user,))) & TOUTES


def definir_sections(conn, session, id_user, sections) -> frozenset:
    """Remplace les sections ouvertes à un compte (Administrateur seulement). Cocher les deux sections revient à ne rien restreindre."""
    droits.exiger_admin(conn, session)
    cible = conn.execute("SELECT LOGIN FROM UTILISATEUR WHERE ID_USER = ?", (id_user,)).fetchone()
    if not cible:
        raise ErreurSection("Compte introuvable.")
    choisies = frozenset(sections or ()) & TOUTES
    if not choisies:
        raise ErreurSection("Cochez au moins une section : Primaire, Secondaire et humanitaire, ou les deux.")
    with conn:
        conn.execute("DELETE FROM SECTION_UTILISATEUR WHERE ID_USER = ?", (id_user,))
        if choisies != TOUTES:
            conn.executemany("INSERT INTO SECTION_UTILISATEUR (ID_USER, SECTION) VALUES (?, ?)", [(id_user, s) for s in sorted(choisies)])
        journaliser(conn, session.id_user, session.login, "SECTIONS_UTILISATEUR_MODIFIEES",
                    f"{cible['LOGIN']} | " + ", ".join(libelle(s) for s in sorted(choisies)))
    return choisies


def resume(conn, id_user) -> str:
    """Texte court pour les listes : « Toutes les sections » ou la liste cochée."""
    s = sections_explicites(conn, id_user)
    return "Toutes les sections" if not s or s == TOUTES else ", ".join(libelle(x) for x in sorted(s))


# ================================================================== section d'une classe, d'un élève
def section_de_classe(conn, n_classe):
    """PRIMAIRE ou SECONDAIRE ; None si la classe n'existe pas."""
    try:
        n_classe = int(n_classe)
    except (TypeError, ValueError):
        return None
    l = conn.execute("SELECT N.SECTION FROM CLASSE C JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU WHERE C.N_CLASSE = ?", (n_classe,)).fetchone()
    return l[0] if l else None


def est_primaire(conn, n_classe) -> bool:
    return section_de_classe(conn, n_classe) == PRIMAIRE


def section_de_eleve(conn, matricule):
    """Section de la classe la plus récente de l'élève ; None s'il n'a aucune inscription."""
    l = conn.execute("SELECT N.SECTION FROM INSCRIRE I JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
                     "WHERE I.MATRICULE = ? ORDER BY I.ANNEESCO DESC LIMIT 1", (str(matricule or ""),)).fetchone()
    return l[0] if l else None


def peut_classe(conn, session, n_classe) -> bool:
    section = section_de_classe(conn, n_classe)
    return section is not None and section in sections_de(conn, session)


def exiger_classe(conn, session, n_classe):
    """PermissionError si la classe n'existe pas ou appartient à une section fermée à ce compte. Retourne la section."""
    section = section_de_classe(conn, n_classe)
    if section is None or section not in sections_de(conn, session):
        raise PermissionError(REFUS_SECTION)
    return section


def peut_eleve(conn, session, matricule) -> bool:
    section = section_de_eleve(conn, matricule)
    return section is None or section in sections_de(conn, session)        # sans inscription : pas de section à protéger


def exiger_eleve(conn, session, matricule):
    if not peut_eleve(conn, session, matricule):
        raise PermissionError("Accès refusé : cet élève appartient à une section de l'école qui ne vous est pas ouverte.")


def exiger_carte(conn, session, matricule):
    """La carte n'existe pas au primaire ; et la section de l'élève doit être ouverte au compte."""
    exiger_eleve(conn, session, matricule)
    if section_de_eleve(conn, matricule) == PRIMAIRE:
        raise PermissionError(REFUS_CARTE)


def a_une_section_avec_carte(conn, session) -> bool:
    return SECONDAIRE in sections_de(conn, session)


# ================================================================== filtres pour les listes
def filtre_classes(conn, session, colonne="N_CLASSE"):
    """(fragment SQL, paramètres) à ajouter dans un WHERE : `colonne` doit être une classe d'une section ouverte au compte.
    Aucune restriction (fragment vide) quand les deux sections sont ouvertes."""
    ouvertes = sections_de(conn, session)
    if ouvertes == TOUTES:
        return "", ()
    if not ouvertes:
        return f"{colonne} IN (SELECT 0)", ()
    marques = ",".join("?" for _ in ouvertes)
    return (f"{colonne} IN (SELECT C.N_CLASSE FROM CLASSE C JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU WHERE N.SECTION IN ({marques}))",
            tuple(sorted(ouvertes)))

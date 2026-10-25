"""Modules du menu principal et règle d'arrivée après la connexion (sans interface graphique : testable seul).

Un compte qui n'a accès qu'à UN SEUL module (par exemple un Percepteur) n'a pas besoin du menu principal :
après la connexion il arrive directement dans le contenu de son module et voit ses fonctionnalités (onglets).
Un compte qui a accès à plusieurs modules (ou à aucun) voit le menu principal, comme avant.
Les droits sont relus dans la base à chaque appel : si l'Administrateur change les droits, l'effet est immédiat.
"""
import config
import droits
import sections

def _espace_ouvert(espace):
    """Règle d'accès d'un module qui est un espace de config.ESPACES_MODULES : le droit de Lecture de l'espace (relu à chaque appel)."""
    return lambda conn, s: espace in [c for c, _t in sous_menus_ouverts(conn, s)]


# (clé, titre, description, règle d'accès (conn, session) -> bool)
MODULES = [
    # Première ligne
    ("paiement", "Paiement des frais",
     "", lambda conn, s: droits.a_droit(conn, s, "paiement", "LECTURE")),
    ("encaissement", "Encaissement des fonds perçus",
     "", lambda conn, s: droits.est_admin(conn, s) or droits.a_droit(conn, s, "encaissement", "LECTURE")),
    ("controle", "Contrôle numérique",
     "", lambda conn, s: droits.est_admin(conn, s) or droits.a_droit(conn, s, "controle", "LECTURE")),
    # Deuxième ligne
    ("carte", "Carte",           # pas de carte au primaire : le module n'apparaît pas pour un compte limité à cette section
     "", lambda conn, s: (droits.est_admin(conn, s) or droits.a_droit(conn, s, "carte", "LECTURE"))
                         and sections.a_une_section_avec_carte(conn, s)),
    # L'inscription est une fonctionnalité du Secrétariat (onglet « Inscription ») : sa tuile n'apparaît à part que pour un compte
    # qui n'a pas accès au Secrétariat.
    ("inscription", "Inscription",
     "", lambda conn, s: (droits.est_admin(conn, s) or droits.a_droit(conn, s, "inscription", "LECTURE"))
                         and "dossier_eleve" not in [c for c, _t in sous_menus_ouverts(conn, s)]),
    # Directeur de discipline / Directrice des études : seulement la présence des élèves (la Direction des études la consulte aussi dans son espace)
    ("presence_eleves", "Présence des élèves",
     "", lambda conn, s: droits.a_droit(conn, s, "presence_eleves", "LECTURE")),
    # Espace Études, Espace Discipline, Préfecture, Secrétariat : un module chacun (config.ESPACES_MODULES), section Secondaire seulement.
    # Chaque module s'ouvre avec le droit de Lecture de son espace (l'Administrateur les a tous).
    *[(cle_module, titre, "", _espace_ouvert(espace)) for espace, (cle_module, titre, _g) in config.ESPACES_MODULES.items()],
    ("personnel", "Gestion du personnel",
     "", lambda conn, s: droits.est_admin(conn, s) or droits.a_droit(conn, s, "personnel", "LECTURE")),
    ("travaux", "Travaux techniques",
     "", lambda conn, s: droits.est_admin(conn, s)),
    ("acces", "Gestionnaire d'accès",
     "", lambda conn, s: droits.est_admin(conn, s)),
    # Troisième ligne : l'Administrateur, ou un compte à qui il a accordé la Lecture (Gestionnaire d'accès)
    ("audit", "Traçabilité et audit",
     "", lambda conn, s: droits.est_admin(conn, s) or droits.a_droit(conn, s, "audit", "LECTURE")),
]


def sous_menus_ouverts(conn, session) -> list:
    """[(clé, titre)] des espaces (config.SOUS_MENUS_ETUDES : Préfecture, Direction des études, Direction de discipline, Secrétariat) ouverts à ce compte (l'Administrateur les voit tous).
    Le module concerne seulement la section Secondaire et humanitaire : un compte limité au Primaire ne le voit pas."""
    if session is None:
        return []
    if sections.SECONDAIRE not in sections.sections_de(conn, session):      # module réservé à la section Secondaire et humanitaire
        return []
    admin = droits.est_admin(conn, session)
    return [(cle, titre) for cle, titre, _role in config.SOUS_MENUS_ETUDES if admin or droits.a_droit(conn, session, cle, "LECTURE")]


def modules_ouverts(conn, session) -> list:
    """Clés des modules ouverts à ce compte, dans l'ordre du menu."""
    if session is None:
        return []
    return [m[0] for m in MODULES if m[3](conn, session)]


def module_direct(conn, session):
    """Clé du module à ouvrir directement après la connexion, ou None s'il faut afficher le menu principal
    (plusieurs modules, ou aucun)."""
    ouverts = modules_ouverts(conn, session)
    return ouverts[0] if len(ouverts) == 1 else None


def menu_utile(conn, session) -> bool:
    """Le menu principal n'a de sens que si le compte a le choix entre plusieurs modules."""
    if session is not None:
        import tableau                       # le tableau de bord est l'accueil : on doit pouvoir y revenir
        if tableau.peut(conn, session):
            return True
    return module_direct(conn, session) is None

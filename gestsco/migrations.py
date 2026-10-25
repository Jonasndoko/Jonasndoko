"""Mise à jour des tables : compare la base à la structure attendue par le programme et la met à niveau.

- Ne supprime JAMAIS une table, une colonne ni une ligne : ce qui est inconnu est conservé et signalé.
- Les modifications délicates (reconstruction d'une table, conversion de données) sont des « migrations »
  numérotées, appliquées une seule fois dans l'ordre (numéro mémorisé dans la base : PRAGMA user_version).
- Cette mise à jour est lancée automatiquement à l'ouverture de la base, et manuellement par
  l'administrateur (Travaux techniques > Mise à jour des tables).

Pour une future version : ajouter la nouvelle table/colonne dans database.SCHEMA ; s'il faut aussi convertir
des données, ajouter une migration à MIGRATIONS et augmenter VERSION_SCHEMA.
"""
import sqlite3
from dataclasses import dataclass, field

import config
import database
import droits

TABLES_ESSENTIELLES = ("UTILISATEUR", "JOURNAL")


class ErreurMiseAJour(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== migrations numérotées
def _table_existe(conn, nom) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (nom,)).fetchone() is not None


def _mig_postes(conn):
    """v1 : les 7 postes. Les anciens noms de rôle sont convertis et la liste figée de rôles
    (CHECK) est retirée de la table UTILISATEUR, qui est reconstruite si nécessaire."""
    if not _table_existe(conn, "UTILISATEUR"):
        return
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='UTILISATEUR'").fetchone()[0]
    conversion = "CASE ROLE " + " ".join(f"WHEN '{a}' THEN '{n}'" for a, n in config.ANCIENS_ROLES.items()) + " ELSE ROLE END"
    if "CHECK (ROLE IN" not in sql:
        with conn:
            conn.execute(f"UPDATE UTILISATEUR SET ROLE = {conversion}")
        return
    conn.commit()
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.execute("PRAGMA foreign_keys = OFF")                       # procédure officielle de reconstruction SQLite
    try:
        conn.executescript("BEGIN;" + database.SCHEMA_UTILISATEUR.replace("UTILISATEUR", "UTILISATEUR_NEW") + f"""
            INSERT INTO UTILISATEUR_NEW (ID_USER, LOGIN, NOM_COMPLET, ROLE, MDP_HASH, ACTIF,
                                         DOIT_CHANGER_MDP, DATE_CREATION, DERNIERE_CONNEXION)
            SELECT ID_USER, LOGIN, NOM_COMPLET, {conversion}, MDP_HASH, ACTIF,
                   DOIT_CHANGER_MDP, DATE_CREATION, DERNIERE_CONNEXION FROM UTILISATEUR;
            DROP TABLE UTILISATEUR;
            ALTER TABLE UTILISATEUR_NEW RENAME TO UTILISATEUR;
            COMMIT;""")
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys = {'ON' if fk else 'OFF'}")


def _mig_droits_initiaux(conn):
    """v2 : chaque compte existant reçoit les droits par défaut de son poste (une seule fois :
    les retraits décidés ensuite par l'administrateur ne sont jamais rétablis)."""
    with conn:
        for u in conn.execute("SELECT ID_USER, ROLE FROM UTILISATEUR").fetchall():
            droits.remplacer_droits(conn, u["ID_USER"], droits.droits_config(u["ROLE"]))


def _mig_droits_des_roles(conn):
    """v3 : droits de base de chaque rôle (table ROLE_DROIT, réglable dans le Gestionnaire d'accès) ;
    le droit « Impression » n'existe plus (duplicata et rapport journalier sont ouverts à tout le module)."""
    with conn:
        for role in config.ROLES:
            if not conn.execute("SELECT 1 FROM ROLE_DROIT WHERE ROLE = ?", (role,)).fetchone():
                droits.remplacer_droits_role(conn, role, droits.droits_config(role))
        conn.execute("DELETE FROM DROIT WHERE DROIT = 'IMPRESSION'")
        conn.execute("DELETE FROM ROLE_DROIT WHERE DROIT = 'IMPRESSION'")


def _mig_identite(conn):
    """v4 : chaque élève reçoit un code QR unique (index unique créé ici : la colonne vient d'être ajoutée)."""
    import identite
    identite.attribuer_aux_eleves_existants(conn)
    with conn:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS IDX_ELEVE_QR ON ELEVE (CODE_QR)")


def _mig_frais_et_classes(conn):
    """v5 : (1) le montant et la devise d'un type de frais sont repris des tarifs existants, seulement quand cela ne
    change rien à ce que les élèves doivent (le même montant dans TOUTES les classes actives, pour la dernière année
    où le frais a des tarifs) ; (2) l'année d'étude et la division des classes sont lues dans leur désignation
    (« 7ème A » -> 7ème + A). La désignation d'une classe existante n'est jamais modifiée."""
    import re
    with conn:
        nb_classes = conn.execute("SELECT COUNT(*) FROM CLASSE WHERE ACTIF = 1").fetchone()[0]
        for t in conn.execute("SELECT CODTF FROM TYPE_FRAIS WHERE MONTANT IS NULL").fetchall():
            annee = conn.execute("SELECT MAX(ANNEESCO) FROM TARIF WHERE CODTF = ?", (t["CODTF"],)).fetchone()[0]
            if not annee:
                continue
            valeurs = conn.execute(
                "SELECT DISTINCT T.MONTANT, T.CODE_DEVISE FROM TARIF T JOIN CLASSE C ON C.N_CLASSE = T.N_CLASSE "
                "WHERE T.CODTF = ? AND T.ANNEESCO = ? AND C.ACTIF = 1", (t["CODTF"], annee)).fetchall()
            couvertes = conn.execute(
                "SELECT COUNT(*) FROM TARIF T JOIN CLASSE C ON C.N_CLASSE = T.N_CLASSE "
                "WHERE T.CODTF = ? AND T.ANNEESCO = ? AND C.ACTIF = 1", (t["CODTF"], annee)).fetchone()[0]
            if len(valeurs) == 1 and nb_classes and couvertes == nb_classes:
                conn.execute("UPDATE TYPE_FRAIS SET MONTANT = ?, CODE_DEVISE = ? WHERE CODTF = ?",
                             (valeurs[0]["MONTANT"], valeurs[0]["CODE_DEVISE"], t["CODTF"]))
        for c in conn.execute("SELECT N_CLASSE, DESI_CLASSE FROM CLASSE WHERE ANNEE_ETUDE IS NULL").fetchall():
            mots = c["DESI_CLASSE"].split()
            if not mots:
                continue
            division = mots[-1] if len(mots) > 1 and re.fullmatch(r"[A-Za-z0-9]{1,3}", mots[-1]) and mots[-1].isupper() else None
            conn.execute("UPDATE CLASSE SET ANNEE_ETUDE = ?, DIVISION = ? WHERE N_CLASSE = ?", (mots[0], division, c["N_CLASSE"]))


def _mig_tranches_libres(conn):
    """v6 : les tranches ne sont plus des pourcentages (table TRANCHE, 12 tranches au plus) mais le montant de CHAQUE
    tranche, en nombre libre, rattaché au type de frais et à chaque tarif de classe (colonnes TRANCHES). Les anciennes
    tranches en % sont converties en montants pour chaque type de frais et chaque tarif : les paliers de paiement restent
    exactement les mêmes, donc rien ne change pour les élèves ni pour les reçus déjà émis. La table TRANCHE est
    supprimée seulement si TOUT son contenu a été converti (sinon elle est conservée pour être revue à la main)."""
    if not _table_existe(conn, "TRANCHE"):
        return

    def montants(parts, montant):
        resultat, cumul, avant = [], 0, 0
        for pourcent in parts:
            cumul += pourcent
            palier = montant if cumul == 100 else montant * cumul // 100
            if palier > avant:
                resultat.append(palier - avant)
                avant = palier
        return ";".join(str(m) for m in resultat)

    non_converties = 0
    with conn:
        for t in conn.execute("SELECT DISTINCT CODTF FROM TRANCHE").fetchall():
            parts = [l[0] for l in conn.execute("SELECT POURCENT FROM TRANCHE WHERE CODTF = ? ORDER BY N_TRANCHE",
                                                (t["CODTF"],))]
            if sum(parts) != 100:                       # tranches incomplètes : le frais était déjà inutilisable, on garde la trace
                non_converties += len(parts)
                continue
            f = conn.execute("SELECT MONTANT FROM TYPE_FRAIS WHERE CODTF = ?", (t["CODTF"],)).fetchone()
            if f and f["MONTANT"]:
                conn.execute("UPDATE TYPE_FRAIS SET TRANCHES = ? WHERE CODTF = ?", (montants(parts, f["MONTANT"]), t["CODTF"]))
            for tarif in conn.execute("SELECT N_CLASSE, ANNEESCO, MONTANT FROM TARIF WHERE CODTF = ?", (t["CODTF"],)).fetchall():
                conn.execute("UPDATE TARIF SET TRANCHES = ? WHERE CODTF = ? AND N_CLASSE = ? AND ANNEESCO = ?",
                             (montants(parts, tarif["MONTANT"]), t["CODTF"], tarif["N_CLASSE"], tarif["ANNEESCO"]))
        if not non_converties:
            conn.execute("DROP TABLE TRANCHE")


def _mig_paiement_candidat(conn):
    """v7 : un reçu peut être établi sans matricule (frais d'inscription payés par un candidat pas encore élève) : la
    colonne MATRICULE de PAIEMENT devient facultative et la colonne NOM_PAYEUR garde le nom du candidat. SQLite ne sait pas
    retirer « NOT NULL » : la table est reconstruite (procédure officielle), tous les reçus sont recopiés tels quels."""
    if not _table_existe(conn, "PAIEMENT"):
        return
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='PAIEMENT'").fetchone()[0]
    if "MATRICULE TEXT NOT NULL" not in " ".join(sql.split()):
        return                                                          # déjà au nouveau format
    colonnes = [c[1] for c in conn.execute("PRAGMA table_info(PAIEMENT)").fetchall()]
    conn.commit()
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")                      # CANDIDATURE pointe vers PAIEMENT : ne pas réécrire ses liens
    try:
        liste = ", ".join(colonnes)
        conn.executescript("BEGIN;" + database.SCHEMA_PAIEMENT.replace("PAIEMENT", "PAIEMENT_NEW", 1) + f"""
            INSERT INTO PAIEMENT_NEW ({liste}) SELECT {liste} FROM PAIEMENT;
            DROP TABLE PAIEMENT;
            ALTER TABLE PAIEMENT_NEW RENAME TO PAIEMENT;
            COMMIT;""")
        conn.executescript(database.SCHEMA)                             # recrée l'index et les déclencheurs de PAIEMENT
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute(f"PRAGMA foreign_keys = {'ON' if fk else 'OFF'}")


def _mig_affectations_initiales(conn):
    """v8 : les agents déjà enregistrés (fonction écrite à la main) reçoivent leur première affectation : la fonction est
    ajoutée à la liste des fonctions et l'affectation commence à la date d'engagement. Rien n'est supprimé."""
    if not _table_existe(conn, "PERSONNEL"):
        return
    with conn:
        for a in conn.execute("SELECT MATRICULE, FONCTION, DATE_ENGAGEMENT, DATE_ENREG FROM PERSONNEL").fetchall():
            if conn.execute("SELECT 1 FROM AFFECTATION WHERE MATRICULE = ?", (a["MATRICULE"],)).fetchone():
                continue
            conn.execute("INSERT OR IGNORE INTO FONCTION_PERSONNEL (LIBELLE) VALUES (?)", (a["FONCTION"],))
            id_f = conn.execute("SELECT ID_FONCTION FROM FONCTION_PERSONNEL WHERE LIBELLE = ?", (a["FONCTION"],)).fetchone()[0]
            conn.execute("INSERT INTO AFFECTATION (MATRICULE, ID_FONCTION, DATE_DEBUT, MOTIF, DATE_ENREG, ENREGISTRE_PAR) "
                         "VALUES (?,?,?,?,?,?)", (a["MATRICULE"], id_f, a["DATE_ENGAGEMENT"], "Engagement", a["DATE_ENREG"], "SYSTEME"))


def _mig_evaluation_periode(conn):
    """v9 : saisie des points par période et par examen. La liste des types d'évaluation (CHECK) accepte désormais « PER » (points
    d'une période) : SQLite ne sait pas modifier un CHECK, la table EVALUATION est reconstruite (procédure officielle) et toutes
    les évaluations et tous les points sont conservés tels quels."""
    if not _table_existe(conn, "EVALUATION"):
        return
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='EVALUATION'").fetchone()[0]
    if "'PER'" in sql:
        return                                                          # déjà au nouveau format
    colonnes = [c[1] for c in conn.execute("PRAGMA table_info(EVALUATION)").fetchall()]
    conn.commit()
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")                      # NOTE pointe vers EVALUATION : ne pas réécrire ses liens
    try:
        liste = ", ".join(colonnes)
        conn.executescript("BEGIN;" + database.SCHEMA_EVALUATION.replace("EVALUATION", "EVALUATION_NEW", 1) + f"""
            INSERT INTO EVALUATION_NEW ({liste}) SELECT {liste} FROM EVALUATION;
            DROP TABLE EVALUATION;
            ALTER TABLE EVALUATION_NEW RENAME TO EVALUATION;
            COMMIT;""")
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute(f"PRAGMA foreign_keys = {'ON' if fk else 'OFF'}")


def _mig_presence_directions(conn):
    """v10 : le droit « Présence des élèves » (consultation) est accordé par défaut à la Directrice des études et au nouveau poste
    Directeur de discipline : droits de base des deux postes, et comptes existants de la Directrice des études (une seule fois)."""
    with conn:
        for role in ("DIRECTRICE_ETUDES", "DIRECTEUR_DISCIPLINE"):
            conn.execute("INSERT OR IGNORE INTO ROLE_DROIT (ROLE, MODULE, DROIT) VALUES (?, 'presence_eleves', 'LECTURE')", (role,))
        for u in conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE ROLE = 'DIRECTRICE_ETUDES'").fetchall():
            conn.execute("INSERT OR IGNORE INTO DROIT (ID_USER, MODULE, DROIT) VALUES (?, 'presence_eleves', 'LECTURE')", (u["ID_USER"],))


def _mig_etudes_discipline(conn):
    """v12 : module « Gestion des études et discipline ». Le droit de Lecture de son sous-menu est accordé par défaut à chaque poste
    concerné (Préfet, Directrice des études, Directeur de discipline, Secrétaire) : droits de base du poste, et comptes existants
    (une seule fois : les retraits décidés ensuite par l'Administrateur ne sont jamais rétablis)."""
    with conn:
        for cle, _titre, role in config.SOUS_MENUS_ETUDES:
            conn.execute("INSERT OR IGNORE INTO ROLE_DROIT (ROLE, MODULE, DROIT) VALUES (?, ?, 'LECTURE')", (role, cle))
            for u in conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE ROLE = ?", (role,)).fetchall():
                conn.execute("INSERT OR IGNORE INTO DROIT (ID_USER, MODULE, DROIT) VALUES (?, ?, 'LECTURE')", (u["ID_USER"], cle))


FRAIS_OBLIGATOIRES = (("EXETAT", "Frais de l'examen d'État", "HUM4"), ("DISSERT", "Frais de dissertation", "HUM4"),
                      ("ENAFEP", "Frais de l'ENAFEP", "PRIM6"), ("TENASSOP", "Frais du TENASSOP", "SEC8"))


def _mig_frais_obligatoires(conn):
    """v15 : frais obligatoires réservés à une année d'étude : examen d'État et dissertation (4ème humanités), ENAFEP (6ème primaire),
    TENASSOP (8ème secondaire). Créés sans montant : l'Administrateur fixe le montant (Travaux techniques > Mise à jour des tables >
    Types de frais, ou Tarifs pour un montant par classe) ; tant qu'il n'y en a pas, rien n'est dû. Un code déjà utilisé n'est pas modifié."""
    with conn:
        for code, designation, cible in FRAIS_OBLIGATOIRES:
            conn.execute("INSERT OR IGNORE INTO TYPE_FRAIS (CODTF, DESITF, CLASSE_CIBLE) VALUES (?, ?, ?)", (code, designation, cible))


def _mig_sections(conn):
    """v11 : sections de l'école. Les niveaux déjà enregistrés dont le code ou la désignation commence par « prim » passent en
    section PRIMAIRE ; tous les autres restent en SECONDAIRE (secondaire et humanitaire). L'Administrateur peut corriger chaque niveau
    (Travaux techniques > Mise à jour des tables > Niveaux). Les comptes existants gardent l'accès à toutes les sections."""
    with conn:
        for n in conn.execute("SELECT CODE_NIVEAU, DESI_NIVEAU FROM NIVEAU").fetchall():
            texte = f"{n['CODE_NIVEAU']} {n['DESI_NIVEAU']}".strip().lower()
            if texte.startswith("prim") or " prim" in texte:
                conn.execute("UPDATE NIVEAU SET SECTION = 'PRIMAIRE' WHERE CODE_NIVEAU = ?", (n["CODE_NIVEAU"],))


def _mig_prefecture_decisions(conn):
    """v13 : décisions et rapports. Le Préfet peut enregistrer et annuler ses décisions (Ajout, Modification sur « Préfecture »), la
    Directrice des études et le Directeur de discipline peuvent envoyer un rapport (Ajout sur leur sous-menu) : droits de base des
    postes, et comptes existants (une seule fois : les retraits décidés ensuite par l'Administrateur ne sont jamais rétablis)."""
    accords = (("PREFET", "prefecture", ("AJOUT", "MODIFICATION")), ("DIRECTRICE_ETUDES", "direction_etudes", ("AJOUT",)),
               ("DIRECTEUR_DISCIPLINE", "direction_discipline", ("AJOUT",)))
    with conn:
        for role, module, droits_ in accords:
            for d in droits_:
                conn.execute("INSERT OR IGNORE INTO ROLE_DROIT (ROLE, MODULE, DROIT) VALUES (?, ?, ?)", (role, module, d))
                for u in conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE ROLE = ?", (role,)).fetchall():
                    conn.execute("INSERT OR IGNORE INTO DROIT (ID_USER, MODULE, DROIT) VALUES (?, ?, ?)", (u["ID_USER"], module, d))


def _mig_horaire_direction(conn):
    """v14 : élaboration horaire. La Directrice des études peut modifier et retirer des cours de l'horaire (Modification, Suppression sur
    « Direction des études ») : droits de base du poste, et comptes existants (une seule fois : les retraits décidés ensuite par
    l'Administrateur ne sont jamais rétablis)."""
    with conn:
        for d in ("MODIFICATION", "SUPPRESSION"):
            conn.execute("INSERT OR IGNORE INTO ROLE_DROIT (ROLE, MODULE, DROIT) VALUES ('DIRECTRICE_ETUDES', 'direction_etudes', ?)", (d,))
            for u in conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE ROLE = 'DIRECTRICE_ETUDES'").fetchall():
                conn.execute("INSERT OR IGNORE INTO DROIT (ID_USER, MODULE, DROIT) VALUES (?, 'direction_etudes', ?)", (u["ID_USER"], d))


def _mig_secretariat_dossier(conn):
    """v16 : Secrétariat. La secrétaire décide qu'un dossier d'élève est complet (Modification sur « Secrétariat ») : droit de base du
    poste, et comptes existants (une seule fois : les retraits décidés ensuite par l'Administrateur ne sont jamais rétablis)."""
    with conn:
        conn.execute("INSERT OR IGNORE INTO ROLE_DROIT (ROLE, MODULE, DROIT) VALUES ('SECRETAIRE', 'dossier_eleve', 'MODIFICATION')")
        for u in conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE ROLE = 'SECRETAIRE'").fetchall():
            conn.execute("INSERT OR IGNORE INTO DROIT (ID_USER, MODULE, DROIT) VALUES (?, 'dossier_eleve', 'MODIFICATION')", (u["ID_USER"],))


def _mig_renvoi(conn):
    """v17 : renvoi d'élèves. Les tables RENVOI et MATRICULE_LIBRE sont créées avec le reste de la structure ; le Préfet a déjà le droit
    « Modification » sur « Préfecture » (migration 13) : rien d'autre à faire. Les élèves déjà désactivés ne sont pas considérés comme renvoyés."""


def _mig_gestion_scolaire_supprimee(conn):
    """v18 : le module « Gestion scolaire » n'existe plus, ses fonctionnalités sont dans la Direction des études. Les droits déjà accordés sur
    « Gestion scolaire » (comptes et rôles) sont reportés tels quels sur « Direction des études » (Lecture, Ajout, Modification, Suppression),
    puis les anciennes lignes sont supprimées : personne ne perd le droit de gérer les cours, et personne n'en gagne d'autre."""
    with conn:
        for table, cle in (("DROIT", "ID_USER"), ("ROLE_DROIT", "ROLE")):
            conn.execute(f"INSERT OR IGNORE INTO {table} ({cle}, MODULE, DROIT) "
                         f"SELECT {cle}, 'direction_etudes', DROIT FROM {table} WHERE MODULE = 'gestion_scolaire'")
            conn.execute(f"DELETE FROM {table} WHERE MODULE = 'gestion_scolaire'")


@dataclass(frozen=True)
class Migration:
    version: int
    phase: str          # "avant" : avant la création des tables manquantes ; "apres" : après
    titre: str
    fonction: object
    fraiche: bool = False   # True : s'applique aussi à une base toute neuve


MIGRATIONS = (
    Migration(1, "avant", "Nouveaux postes (préfet, administrateur, secrétaire, intendant, percepteur, contrôleur, "
                          "directrice des études)", _mig_postes),
    Migration(2, "apres", "Droits d'accès initiaux des comptes existants", _mig_droits_initiaux),
    Migration(3, "apres", "Droits de base des rôles", _mig_droits_des_roles, fraiche=True),
    Migration(4, "apres", "Code QR de chaque élève", _mig_identite, fraiche=True),
    Migration(5, "apres", "Montant et devise des types de frais, année d'étude et division des classes",
              _mig_frais_et_classes),
    Migration(6, "apres", "Tranches libres : montant de chaque tranche, par type de frais et par tarif de classe",
              _mig_tranches_libres),
    Migration(7, "apres", "Paiement des frais d'inscription par un candidat sans matricule", _mig_paiement_candidat),
    Migration(8, "apres", "Première affectation des agents déjà enregistrés (fonctions et affectations)",
              _mig_affectations_initiales),
    Migration(9, "avant", "Saisie des points par période et par examen (type d'évaluation « PER »)", _mig_evaluation_periode),
    Migration(10, "apres", "Présence des élèves : droit de consultation de la Directrice des études et du Directeur de discipline",
              _mig_presence_directions),
    Migration(11, "apres", "Sections de l'école : primaire, et secondaire et humanitaire (section de chaque niveau)", _mig_sections),
    Migration(12, "apres", "Module « Gestion des études et discipline » : droit de Lecture de chaque sous-menu pour le poste concerné",
              _mig_etudes_discipline),
    Migration(13, "apres", "Préfecture : droits pour enregistrer les décisions du Préfet et envoyer les rapports des responsables",
              _mig_prefecture_decisions),
    Migration(14, "apres", "Direction des études : droits de modification et de suppression pour l'élaboration horaire",
              _mig_horaire_direction),
    Migration(15, "apres", "Frais obligatoires par année d'étude : examen d'État et dissertation (4ème humanités), ENAFEP (6ème primaire), "
                           "TENASSOP (8ème secondaire)", _mig_frais_obligatoires),
    Migration(16, "apres", "Secrétariat : état « dossier complet » de chaque élève, décidé par la secrétaire (droit de modification)",
              _mig_secretariat_dossier),
    Migration(17, "apres", "Renvoi d'élèves : tables des renvois et des matricules libérés", _mig_renvoi, fraiche=True),
    Migration(18, "apres", "Module « Gestion scolaire » supprimé : ses droits passent à la Direction des études",
              _mig_gestion_scolaire_supprimee, fraiche=True),
)
VERSION_SCHEMA = MIGRATIONS[-1].version


# ================================================================== structure attendue / réelle
def _objets(conn):
    """{'tables': {nom: [colonnes]}, 'index': {noms}, 'declencheurs': {noms}} de la base ouverte."""
    tables = {}
    for l in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        tables[l[0]] = [tuple(c) for c in conn.execute(f'PRAGMA table_info("{l[0]}")').fetchall()]
    noms = lambda genre: {l[0] for l in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%'", (genre,)).fetchall()}
    return {"tables": tables, "index": noms("index"), "declencheurs": noms("trigger")}


def structure_attendue() -> dict:
    """Structure que le programme exige, obtenue en construisant le schéma complet dans une base vide."""
    ref = sqlite3.connect(":memory:")
    try:
        ref.executescript(database.SCHEMA)
        return _objets(ref)
    finally:
        ref.close()


# ================================================================== analyse
@dataclass
class EtatTable:
    nom: str
    statut: str                       # OK | MANQUANTE | COLONNES_MANQUANTES | INCONNUE
    nb_lignes: int = 0
    manquantes: list = field(default_factory=list)
    en_trop: list = field(default_factory=list)

    @property
    def libelle_statut(self) -> str:
        return {"OK": "À jour", "MANQUANTE": "À créer", "COLONNES_MANQUANTES": "Colonnes à ajouter",
                "INCONNUE": "Inconnue (conservée)"}[self.statut]


@dataclass
class Analyse:
    version_actuelle: int
    version_cible: int
    tables: list
    objets_manquants: list            # [("index"|"déclencheur", nom)]
    migrations: list                  # titres des migrations en attente
    bloquants: list                   # problèmes qu'une mise à jour automatique ne peut pas régler

    @property
    def a_faire(self) -> bool:
        return bool(self.migrations or self.objets_manquants
                    or any(t.statut in ("MANQUANTE", "COLONNES_MANQUANTES") for t in self.tables))

    def lignes_a_faire(self) -> list:
        """Ce que la mise à jour va faire, en français."""
        lignes = [f"Migration {m}" for m in self.migrations]
        for t in self.tables:
            if t.statut == "MANQUANTE":
                lignes.append(f"Créer la table {t.nom}")
            elif t.statut == "COLONNES_MANQUANTES":
                lignes.append(f"Ajouter à {t.nom} : " + ", ".join(t.manquantes))
        lignes += [f"Créer {genre} {nom}" for genre, nom in self.objets_manquants]
        return lignes


def _definition_colonne(col):
    """(cid, nom, type, notnull, défaut, pk) -> texte SQL pour ALTER TABLE ADD COLUMN, ou None si impossible."""
    _, nom, type_, notnull, defaut, pk = col
    if pk:
        return None
    if notnull and defaut is None:
        return None                   # SQLite refuse d'ajouter une colonne NOT NULL sans valeur par défaut
    texte = f'"{nom}" {type_ or ""}'.rstrip()
    if defaut is not None:
        texte += f" DEFAULT {defaut}"
    if notnull:
        texte += " NOT NULL"
    return texte


def analyser(conn) -> Analyse:
    attendu, reel = structure_attendue(), _objets(conn)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    existait = "UTILISATEUR" in reel["tables"]

    tables, bloquants = [], []
    for nom, colonnes in attendu["tables"].items():
        if nom not in reel["tables"]:
            tables.append(EtatTable(nom, "MANQUANTE"))
            continue
        noms_reels = {c[1] for c in reel["tables"][nom]}
        manquantes = [c for c in colonnes if c[1] not in noms_reels]
        nb = conn.execute(f'SELECT COUNT(*) FROM "{nom}"').fetchone()[0]
        for c in manquantes:
            if _definition_colonne(c) is None:
                bloquants.append(f"La colonne {nom}.{c[1]} ne peut pas être ajoutée automatiquement "
                                 f"(à signaler au développeur).")
        tables.append(EtatTable(nom, "COLONNES_MANQUANTES" if manquantes else "OK", nb,
                                [c[1] for c in manquantes],
                                sorted(noms_reels - {c[1] for c in colonnes})))
    for nom in sorted(set(reel["tables"]) - set(attendu["tables"])):
        tables.append(EtatTable(nom, "INCONNUE", conn.execute(f'SELECT COUNT(*) FROM "{nom}"').fetchone()[0]))

    manquants = [("l'index", n) for n in sorted(attendu["index"] - reel["index"])]
    manquants += [("le déclencheur", n) for n in sorted(attendu["declencheurs"] - reel["declencheurs"])]
    en_attente = [m.titre for m in MIGRATIONS if m.version > version and (existait or m.fraiche)]
    if version > VERSION_SCHEMA:
        bloquants.append(f"Cette base a été créée par une version plus récente du programme "
                         f"(structure n° {version}, ce programme connaît le n° {VERSION_SCHEMA}). "
                         f"Installez la dernière version du programme.")
    return Analyse(version, VERSION_SCHEMA, tables, manquants, en_attente, bloquants)


# ================================================================== vérification d'intégrité
def verifier_integrite(conn) -> list:
    """Liste de (contrôle, réussi ?, détail)."""
    resultats = []
    lignes = [l[0] for l in conn.execute("PRAGMA integrity_check").fetchall()]
    ok = lignes == ["ok"]
    resultats.append(("Structure interne du fichier de base de données", ok,
                      "Aucune anomalie." if ok else " ; ".join(lignes[:3])))
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    resultats.append(("Liens entre les tables (références)", not violations,
                      "Aucune anomalie." if not violations else f"{len(violations)} lien(s) cassé(s), "
                      f"par exemple dans la table {violations[0][0]}."))
    if _table_existe(conn, "JOURNAL"):
        chaine_ok, id_log = database.verifier_journal(conn)
        resultats.append(("Journal des opérations (chaîne d'empreintes)", chaine_ok,
                          "Aucune anomalie." if chaine_ok else f"Modification détectée à partir de la ligne {id_log}."))
    return resultats


# ================================================================== mise à jour
def _fichier_de_la_base(conn) -> str:
    return conn.execute("PRAGMA database_list").fetchone()["file"] or ""


def mettre_a_jour(conn, chemin=None, session=None, sauvegarder=True) -> list:
    """Met la structure à niveau. Retourne la liste des actions effectuées (vide si tout était déjà à jour).
    Avant toute modification d'une base qui contient déjà des données, une sauvegarde de sécurité est créée."""
    analyse = analyser(conn)
    if analyse.bloquants and analyse.version_actuelle > VERSION_SCHEMA:
        raise ErreurMiseAJour(analyse.bloquants[-1])
    if not analyse.a_faire:
        return []

    existait = _table_existe(conn, "UTILISATEUR")
    version = analyse.version_actuelle
    actions = []

    if existait and sauvegarder and (chemin or _fichier_de_la_base(conn)):
        try:
            import sauvegarde
            fichier = sauvegarde.sauvegarde_securite(conn, "Avant-miseajour")
            actions.append(f"Sauvegarde de sécurité créée : {fichier.name}")
        except Exception as erreur:                      # une sauvegarde ratée ne doit pas bloquer l'ouverture
            actions.append(f"Sauvegarde de sécurité impossible ({erreur}) : mise à jour poursuivie")

    en_attente = [m for m in MIGRATIONS if m.version > version and (existait or m.fraiche)]
    try:
        for m in (m for m in en_attente if m.phase == "avant"):
            m.fonction(conn)
            actions.append(f"Migration {m.version} : {m.titre}")
        conn.commit()
        conn.executescript(database.SCHEMA)               # crée tables, index et déclencheurs manquants
        for t in analyse.tables:
            if t.statut == "MANQUANTE":
                actions.append(f"Table créée : {t.nom}")
        actions += [f"Créé : {genre} {nom}" for genre, nom in analyse.objets_manquants
                    if not any(t.statut == "MANQUANTE" for t in analyse.tables)]
        attendu = structure_attendue()["tables"]
        reel = _objets(conn)["tables"]
        for nom, colonnes in attendu.items():
            presentes = {c[1] for c in reel.get(nom, [])}
            for c in colonnes:
                definition = _definition_colonne(c)
                if c[1] not in presentes and definition:
                    if getattr(conn, "backend", "") == "postgresql":       # type, valeur par défaut et nom au format PostgreSQL
                        import sqlpg
                        definition = sqlpg.definition_colonne_pg(c[1], c[2], c[4], bool(c[3]))
                    conn.execute(f'ALTER TABLE "{nom}" ADD COLUMN {definition}')
                    actions.append(f"Colonne ajoutée : {nom}.{c[1]}")
        conn.commit()
        for m in (m for m in en_attente if m.phase == "apres"):
            m.fonction(conn)
            actions.append(f"Migration {m.version} : {m.titre}")
        conn.execute(f"PRAGMA user_version = {VERSION_SCHEMA}")
        if existait:
            with conn:
                database.journaliser(conn, session.id_user if session else None,
                                     session.login if session else "SYSTEME", "STRUCTURE_MISE_A_JOUR",
                                     f"version {version} -> {VERSION_SCHEMA} | " + " ; ".join(actions)[:600])
    except BaseException as erreur:
        conn.rollback()
        if isinstance(erreur, sqlite3.Error):
            raise ErreurMiseAJour(f"La mise à jour des tables a échoué : {erreur}. "
                                  f"Vos données n'ont pas été supprimées.") from erreur
        raise
    return actions


# ================================================================== accès réservé à l'administrateur (écran Travaux techniques)
def analyse_admin(conn, session) -> Analyse:
    droits.exiger_admin(conn, session)
    return analyser(conn)


def mise_a_jour_manuelle(conn, session) -> list:
    droits.exiger_admin(conn, session)
    return mettre_a_jour(conn, session=session)


def controle_integrite(conn, session) -> list:
    droits.exiger_admin(conn, session)
    resultats = verifier_integrite(conn)
    with conn:
        database.journaliser(conn, session.id_user, session.login, "INTEGRITE_VERIFIEE",
                             "OK" if all(r[1] for r in resultats) else "ANOMALIES DETECTEES")
    return resultats

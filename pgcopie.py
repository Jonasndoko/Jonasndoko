"""Copie de toute la base entre SQLite et PostgreSQL (dans les deux sens).

  - importer(conn_pg, source_sqlite) : fichier SQLite -> PostgreSQL. Sert à la migration (migrer_vers_postgresql.py) et à la
    restauration d'une sauvegarde .csfbak lorsque l'application tourne sur PostgreSQL ;
  - exporter(conn_pg, cible_sqlite)  : PostgreSQL -> fichier SQLite. Sert à la sauvegarde : l'archive .csfbak contient toujours
    un fichier college.db, donc les sauvegardes restent lisibles par toutes les versions et passent d'un moteur à l'autre.

Les données sont copiées telles quelles (clés, dates, empreintes du journal) : la chaîne du journal reste valide.
"""
import sqlite3

import database
import sqlpg


class ErreurCopie(Exception):
    """Erreur dont le message peut être affiché tel quel."""


def ordre_tables(reg) -> list:
    """Noms des tables, parents avant enfants (d'après les clés étrangères)."""
    reste = {t.nom: {fk.table_ref for fk in t.cles_etrangeres if fk.table_ref != t.nom} for t in reg.tables.values()}
    ordre = []
    while reste:
        libres = sorted(n for n, deps in reste.items() if not (deps - set(ordre)))
        if not libres:
            raise ErreurCopie("Cycle entre les clés étrangères : " + ", ".join(sorted(reste)))
        for n in libres:
            ordre.append(n)
            del reste[n]
    return ordre


def _existe_sqlite(src, nom) -> bool:
    return src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (nom,)).fetchone() is not None


def _controler(table, colonne, valeur, type_pg, repere) -> str:
    """Texte du problème si SQLite contient ici une valeur que PostgreSQL refuserait (typage libre de SQLite), sinon ''."""
    if valeur is None:
        return ""
    if type_pg == "BIGINT" and not (isinstance(valeur, int) and not isinstance(valeur, bool)):
        return f"{table}.{colonne} (ligne {repere}) : « {str(valeur)[:40]} » n'est pas un nombre entier"
    if type_pg == "DOUBLE PRECISION" and not isinstance(valeur, (int, float)):
        return f"{table}.{colonne} (ligne {repere}) : « {str(valeur)[:40]} » n'est pas un nombre"
    if type_pg in ("TEXT", "CITEXT"):
        if isinstance(valeur, (bytes, bytearray)):
            return f"{table}.{colonne} (ligne {repere}) : contenu binaire dans une colonne de texte"
        if isinstance(valeur, str) and "\x00" in valeur:
            return f"{table}.{colonne} (ligne {repere}) : caractère nul (\\x00) dans un texte"
    return ""


def importer(conn, src, vider=True, rapport=None) -> dict:
    """Copie le contenu de `src` (connexion sqlite3 à la structure à jour) dans la base PostgreSQL `conn`.
    Une seule transaction : tout ou rien. Retourne {table: nombre de lignes copiées}."""
    reg = sqlpg.registre()
    if reg is None:
        raise ErreurCopie("Le schéma de l'application n'est pas chargé.")
    rapport = rapport or (lambda texte: None)
    tables = ordre_tables(reg)
    noms_pg = [t.lower() for t in tables]
    conn.commit()
    conn._begin(immediat=True)                                     # un seul écrivain pendant toute la copie
    copiees = {}
    try:
        for t in noms_pg:                                          # déclencheurs coupés : on copie à l'identique (pas de nouvelle règle)
            conn._sql(f"ALTER TABLE {t} DISABLE TRIGGER USER")
        conn._sql("SET CONSTRAINTS ALL DEFERRED")
        if vider:
            conn._sql("TRUNCATE " + ", ".join(noms_pg) + " RESTART IDENTITY")
        for nom in tables:
            if not _existe_sqlite(src, nom):
                rapport(f"  {nom}: absente de la source (ignorée)")
                copiees[nom] = 0
                continue
            t = reg.tables[nom]
            colonnes_src = {c[1].upper() for c in src.execute(f'PRAGMA table_info("{nom}")')}
            colonnes = [c for c in t.colonnes if c.nom in colonnes_src]
            liste = ", ".join(f'"{c.nom}"' for c in colonnes)
            types = [sqlpg.type_pg(c.type_sqlite, c.nocase) for c in colonnes]
            lignes, problemes = [], []
            for repere, l in enumerate(src.execute(f'SELECT {liste} FROM "{nom}"'), 1):
                valeurs = tuple(l)
                for c, tp, v in zip(colonnes, types, valeurs):
                    p = _controler(nom, c.nom, v, tp, repere)
                    if p:
                        problemes.append(p)
                lignes.append(valeurs)
            if problemes:
                raise ErreurCopie("Données que PostgreSQL refuse (corrigez-les dans la base SQLite puis recommencez) :\n  "
                                  + "\n  ".join(problemes[:20]) + (f"\n  ... et {len(problemes) - 20} autre(s)" if len(problemes) > 20 else ""))
            if lignes:
                sql = (f"INSERT INTO {nom.lower()} ({', '.join(c.nom.lower() for c in colonnes)}) "
                       f"VALUES ({', '.join(['%s'] * len(colonnes))})")
                try:
                    with conn._pg.cursor() as cur:
                        for debut in range(0, len(lignes), 500):
                            cur.executemany(sql, lignes[debut:debut + 500])
                except conn._erreur_pg as erreur:
                    raise ErreurCopie(f"Copie de la table {nom} refusée par PostgreSQL : {erreur}") from erreur
            copiees[nom] = len(lignes)
            rapport(f"  {nom}: {len(lignes)} ligne(s)")
        _recaler_identites(conn, src, reg)
        for t in noms_pg:
            conn._sql(f"ALTER TABLE {t} ENABLE TRIGGER USER")
        version = src.execute("PRAGMA user_version").fetchone()[0]
        conn.execute(f"PRAGMA user_version = {int(version)}")
        conn.commit()                                              # les clés étrangères différées sont contrôlées ici
    except BaseException:
        conn.rollback()
        raise
    return copiees


def _recaler_identites(conn, src, reg):
    """Place chaque compteur automatique après la plus grande clé (ou après le dernier numéro jamais attribué sous SQLite)."""
    vus = {}
    if _existe_sqlite(src, "sqlite_sequence"):
        vus = {l[0].upper(): l[1] for l in src.execute("SELECT name, seq FROM sqlite_sequence")}
    for table, colonne in reg.identites.items():
        maxi = conn._sql(f"SELECT COALESCE(MAX({colonne.lower()}), 0) FROM {table.lower()}").fetchone()[0]
        valeur = max(int(maxi), int(vus.get(table, 0) or 0))
        if valeur >= 1:
            conn._sql("SELECT setval(pg_get_serial_sequence(%s, %s), %s, true)", (table.lower(), colonne.lower(), valeur))


def exporter(conn, cible) -> dict:
    """Écrit la base PostgreSQL dans `cible` (connexion sqlite3 vide) : instantané cohérent, même si d'autres l'utilisent."""
    reg = sqlpg.registre()
    tables = ordre_tables(reg)
    cible.executescript(database.SCHEMA)
    cible.execute("PRAGMA foreign_keys = OFF")
    cible.execute("DROP TRIGGER IF EXISTS CANDIDATURE_EXIGE_PAIEMENT")   # recréé après la copie : une candidature dont le reçu a été annulé depuis reste valable
    copiees = {}
    conn.commit()
    conn._sql("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
    try:
        for nom in tables:
            colonnes = [c.nom for c in reg.tables[nom].colonnes]
            lignes = conn._sql(f"SELECT {', '.join(c.lower() for c in colonnes)} FROM {nom.lower()}").fetchall()
            if lignes:
                cible.executemany(f'INSERT INTO "{nom}" ({", ".join(colonnes)}) VALUES ({", ".join("?" * len(colonnes))})',
                                  [tuple(bytes(v) if isinstance(v, memoryview) else v for v in l) for l in lignes])
            copiees[nom] = len(lignes)
        version = conn.version_structure()
    finally:
        conn._sql("ROLLBACK")
    cible.executescript(database.SCHEMA)                           # remet le déclencheur retiré plus haut
    cible.execute(f"PRAGMA user_version = {int(version)}")
    cible.commit()
    return copiees


def comparer(conn, src) -> list:
    """Compare nombre de lignes et totaux financiers entre la source SQLite et PostgreSQL. Retourne la liste des écarts (vide = identique)."""
    reg = sqlpg.registre()
    ecarts = []
    for nom in ordre_tables(reg):
        a = src.execute(f'SELECT COUNT(*) FROM "{nom}"').fetchone()[0] if _existe_sqlite(src, nom) else 0
        b = conn.execute(f'SELECT COUNT(*) FROM "{nom}"').fetchone()[0]
        if a != b:
            ecarts.append(f"{nom} : {a} ligne(s) dans la source, {b} dans PostgreSQL")
    if _existe_sqlite(src, "PAIEMENT"):
        req = "SELECT CODE_DEVISE, STATUT, SUM(MONT_PAYE) FROM PAIEMENT GROUP BY CODE_DEVISE, STATUT ORDER BY 1, 2"
        a = [tuple(l) for l in src.execute(req)]
        b = [tuple(l) for l in conn.execute(req)]
        if a != b:
            ecarts.append(f"Totaux des reçus différents : source {a} / PostgreSQL {b}")
    ok, id_log = database.verifier_journal(conn)
    if not ok:
        ecarts.append(f"Journal : chaîne d'empreintes rompue à la ligne {id_log}")
    return ecarts

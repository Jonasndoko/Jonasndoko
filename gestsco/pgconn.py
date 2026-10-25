"""Connexion PostgreSQL qui se comporte comme un `sqlite3.Connection` pour le reste de GESTSCO.

Le programme parle « SQLite » partout (placeholders ?, lignes lisibles par nom, lastrowid, PRAGMA, sqlite_master,
`with conn:`, `BEGIN IMMEDIATE`, exceptions sqlite3...). Ce module fait la traduction (voir sqlpg.py pour le SQL) et reproduit
les comportements dont l'application dépend :

  - transactions : comme sqlite3, une transaction s'ouvre avant le premier INSERT/UPDATE/DELETE et `commit()` la ferme ;
    chaque instruction d'écriture est isolée par un SAVEPOINT (SQLite annule l'instruction fautive et laisse la transaction
    ouverte ; PostgreSQL, lui, l'abandonnerait entièrement) ;
  - `BEGIN IMMEDIATE` : verrou consultatif global (un seul écrivain à la fois, comme le verrou d'écriture de SQLite) ;
  - `with conn:` valide ou annule, mais NE FERME PAS la connexion (psycopg la fermerait) ;
  - erreurs : IntegrityError / OperationalError de `sqlite3`, avec les messages de SQLite (« UNIQUE constraint failed:
    TABLE.COLONNE »...) que le code analyse pour afficher un message clair ;
  - lignes : accès par nom sans tenir compte de la casse (PostgreSQL met les noms en minuscules), par position, `keys()` ;
  - nombres : SUM()/AVG() de PostgreSQL (NUMERIC) reviennent en int/float, pas en Decimal ; les booléens Python en 0/1 ;
  - PRAGMA : foreign_keys, defer_foreign_keys, user_version (table gestsco_meta), table_info, foreign_key_list,
    foreign_key_check, integrity_check, database_list.

Le pilote `psycopg` (v3) n'est importé qu'à l'ouverture d'une connexion : le reste du module est testable sans lui.
"""
import hashlib
import re
import sqlite3
import uuid

import sqlpg

CLE_VERROU_ECRITURE = 7204001           # verrou consultatif : un seul écrivain à la fois (équivalent de BEGIN IMMEDIATE)
TABLE_META = "gestsco_meta"


# ============================================================================ exceptions (compatibles sqlite3)
class ErreurIntegrite(sqlite3.IntegrityError):
    pass


class ErreurOperationnelle(sqlite3.OperationalError):
    pass


class ErreurBase(sqlite3.DatabaseError):
    pass


def convertir_erreur(e) -> Exception:
    """Erreur du pilote -> exception `sqlite3` avec un message de la forme de SQLite."""
    code = getattr(e, "sqlstate", None) or ""
    diag = getattr(e, "diag", None)
    primaire = (getattr(diag, "message_primary", None) or str(e)).strip()
    table = (getattr(diag, "table_name", None) or "").upper()
    if code == "23505":                                           # unique_violation
        cles = re.search(r"Key \((.*?)\)=", getattr(diag, "message_detail", None) or "", re.S)
        if cles:
            texte = ", ".join(f"{table}.{c.strip().upper()}" for c in cles.group(1).split(",")) if table else cles.group(1).upper()
        else:
            texte = table
        return ErreurIntegrite(f"UNIQUE constraint failed: {texte}")
    if code == "23503":                                           # foreign_key_violation
        return ErreurIntegrite("FOREIGN KEY constraint failed")
    if code == "23502":                                           # not_null_violation
        colonne = (getattr(diag, "column_name", None) or "").upper()
        return ErreurIntegrite(f"NOT NULL constraint failed: {table}.{colonne}")
    if code == "23514":                                           # check_violation
        return ErreurIntegrite(f"CHECK constraint failed: {getattr(diag, 'constraint_name', None) or primaire}")
    if code.startswith("23"):                                     # 23000 : déclencheurs (RAISE(ABORT, ...) de SQLite)
        return ErreurIntegrite(primaire)
    if code in ("42P01", "42703"):                                # table ou colonne inconnue
        return ErreurOperationnelle(f"no such table or column: {primaire}")
    if code[:2] in ("08", "53", "57", "40", "55") or code == "":  # connexion, ressources, verrous, annulation
        return ErreurOperationnelle(primaire)
    return ErreurBase(primaire)


# ============================================================================ lignes
class Ligne(tuple):
    """Ligne de résultat : par position, ou par nom (sans tenir compte de la casse), comme `sqlite3.Row`."""

    def __new__(cls, valeurs, noms, index):
        self = super().__new__(cls, valeurs)
        self._noms = noms
        self._index = index
        return self

    def __getitem__(self, cle):
        if isinstance(cle, str):
            try:
                return tuple.__getitem__(self, self._index[cle.lower()])
            except KeyError:
                raise IndexError("No item with that key") from None
        return tuple.__getitem__(self, cle)

    def keys(self):
        return list(self._noms)


class Curseur:
    """Résultat d'une requête (lu en entier) : fetchone / fetchall / itération, lastrowid, rowcount."""

    def __init__(self, lignes=(), noms=(), rowcount=-1, lastrowid=None):
        self._noms = [n.upper() for n in noms]
        index = {}
        for i, n in enumerate(self._noms):
            index.setdefault(n.lower(), i)
        self._lignes = [Ligne(l, self._noms, index) for l in lignes]
        self._pos = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self.description = [(n, None, None, None, None, None, None) for n in self._noms] if noms else None

    def fetchone(self):
        if self._pos >= len(self._lignes):
            return None
        self._pos += 1
        return self._lignes[self._pos - 1]

    def fetchmany(self, n=1):
        sortie = self._lignes[self._pos:self._pos + n]
        self._pos += len(sortie)
        return sortie

    def fetchall(self):
        sortie = self._lignes[self._pos:]
        self._pos = len(self._lignes)
        return sortie

    def __iter__(self):
        while True:
            l = self.fetchone()
            if l is None:
                return
            yield l

    def close(self):
        pass


# ============================================================================ connexion
_RE_PRAGMA = re.compile(r"\s*PRAGMA\s+(\w+)\s*(?:=\s*([^\s;]+)|\(\s*\"?(\w+)\"?\s*\))?\s*;?\s*$", re.I)
_RE_INSERT = re.compile(r"\s*INSERT\s+(?:OR\s+\w+\s+)?INTO\s+\"?(\w+)\"?", re.I)
_RE_CREATION = re.compile(r"\s*CREATE\s+(?:UNIQUE\s+)?(TABLE|INDEX|TRIGGER)\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)\"?", re.I)
_RE_DROP_TRIGGER = re.compile(r"\s*DROP\s+TRIGGER\s+(?:IF\s+EXISTS\s+)?\"?(\w+)\"?\s*;?\s*$", re.I)


def _valeur(p):
    return int(p) if isinstance(p, bool) else p                  # SQLite range True/False comme 1/0 ; PostgreSQL refuserait


class Connexion:
    """Imite `sqlite3.Connection` au-dessus d'une connexion psycopg (mode autocommit : les transactions sont gérées ici)."""
    backend = "postgresql"
    _erreur_pg = Exception                                         # remplacé par psycopg.Error à l'ouverture

    def __init__(self, pg, identifiant="postgresql", schema_app=None):
        self._pg = pg
        self.identifiant = identifiant
        self._fk = 1
        self._meta_prete = False
        self.row_factory = None                                    # ignoré : les lignes sont toujours des `Ligne`
        self._schema = schema_app or sqlpg.registre()

    # ------------------------------------------------------------ transactions
    @property
    def in_transaction(self) -> bool:
        return int(self._pg.info.transaction_status) != 0         # 0 = IDLE

    def _sql(self, texte, params=None):
        """Instruction brute (sans traduction), erreurs converties."""
        try:
            return self._pg.execute(texte, params)
        except self._erreur_pg as e:
            raise convertir_erreur(e) from None

    def commit(self):
        if self.in_transaction:
            try:
                self._pg.execute("COMMIT")
            except self._erreur_pg as e:                           # ex. clé étrangère différée violée au COMMIT
                try:
                    self._pg.execute("ROLLBACK")
                except self._erreur_pg:
                    pass
                raise convertir_erreur(e) from None

    def rollback(self):
        if self.in_transaction:
            try:
                self._pg.execute("ROLLBACK")
            except self._erreur_pg as e:
                raise convertir_erreur(e) from None

    def close(self):
        try:
            self.rollback()
        finally:
            self._pg.close()

    def __enter__(self):
        return self

    def __exit__(self, type_, valeur, trace):
        if type_ is None:
            self.commit()
        else:
            self.rollback()
        return False

    def _begin(self, immediat=False):
        if not self.in_transaction:
            self._sql("BEGIN")
        if immediat:
            self._sql("SELECT pg_advisory_xact_lock(%s)", (CLE_VERROU_ECRITURE,))

    # ------------------------------------------------------------ exécution
    def execute(self, sql, params=()):
        m = sql.lstrip()
        mot = m[:12].split(None, 1)[0].upper().rstrip(";") if m else ""
        if mot == "PRAGMA":
            return self._pragma(sql)
        if mot in ("BEGIN", "COMMIT", "END", "ROLLBACK"):
            if mot == "BEGIN":
                self._begin(immediat=bool(re.match(r"BEGIN\s+IMMEDIATE", m, re.I)))
            elif mot == "ROLLBACK":
                self.rollback()
            else:
                self.commit()
            return Curseur()
        if mot in ("CREATE", "DROP", "ALTER"):
            return self._ddl(sql)
        params = tuple(_valeur(p) for p in params) if params else None
        pg_sql = sqlpg.traduire(sql, params is not None)
        ecriture = mot in ("INSERT", "UPDATE", "DELETE", "REPLACE", "TRUNCATE")
        colonne_id = None
        if ecriture and mot in ("INSERT", "REPLACE") and "RETURNING" not in pg_sql.upper():
            r = _RE_INSERT.match(sql) or re.match(r"\s*REPLACE\s+INTO\s+\"?(\w+)\"?", sql, re.I)
            reg = self._schema
            colonne_id = reg.identites.get(r.group(1).upper()) if (r and reg) else None
            if colonne_id:
                pg_sql += f" RETURNING {colonne_id.lower()}"
        return self._lancer(pg_sql, params, ecriture, colonne_id)

    def _lancer(self, pg_sql, params, ecriture, colonne_id=None):
        if ecriture:
            self._begin()                                          # comme sqlite3 : transaction ouverte avant l'écriture
        isole = ecriture and self.in_transaction
        try:
            if isole:
                self._pg.execute("SAVEPOINT gestsco_instr")
            try:
                cur = self._pg.execute(pg_sql, params)
                lignes = cur.fetchall() if cur.description else []
                noms = [c.name for c in cur.description] if cur.description else []
                rowcount = cur.rowcount
            except self._erreur_pg:
                if isole:
                    self._pg.execute("ROLLBACK TO SAVEPOINT gestsco_instr")   # annule l'instruction, garde la transaction
                    self._pg.execute("RELEASE SAVEPOINT gestsco_instr")
                    isole = False
                raise
            if isole:
                self._pg.execute("RELEASE SAVEPOINT gestsco_instr")
        except self._erreur_pg as e:
            raise convertir_erreur(e) from None
        if colonne_id:
            return Curseur([], [], rowcount, lignes[-1][0] if lignes else None)
        return Curseur(lignes, noms, rowcount)

    def executemany(self, sql, sequence):
        total = 0
        for params in sequence:
            total += max(self.execute(sql, params).rowcount, 0)
        c = Curseur()
        c.rowcount = total
        return c

    def cursor(self):
        return _CurseurLegacy(self)

    # ------------------------------------------------------------ DDL
    def _ddl(self, sql) -> Curseur:
        m = _RE_DROP_TRIGGER.match(sql)
        if m:
            d = self._schema.declencheurs.get(m.group(1).upper()) if self._schema else None
            if d:
                self._sql(f"DROP TRIGGER IF EXISTS {d.nom.lower()} ON {d.table.lower()}")
            return Curseur()
        if _RE_CREATION.match(sql):
            self._creer_objets(sqlpg.decouper_instructions(sql))
            return Curseur()
        texte, lit = sqlpg.masquer(sql.strip().rstrip(";"))
        self._sql(sqlpg.demasquer(texte, lit))
        return Curseur()

    def _tables_existantes(self) -> set:
        return {l[0].upper() for l in self._sql(
            "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = current_schema() AND c.relkind = 'r'").fetchall()}

    def _creer_objets(self, instructions):
        """Crée ce que ces instructions SQLite décrivent, d'après le schéma complet de l'application (la forme PostgreSQL
        de chaque objet vient de sqlpg). Un nom absent du schéma (table temporaire d'une reconstruction SQLite) est ignoré."""
        reg = self._schema
        tables, index, declencheurs = set(), set(), set()
        for i in instructions:
            m = _RE_CREATION.match(i)
            if not m:
                continue
            genre, nom = m.group(1).upper(), m.group(2).upper()
            {"TABLE": tables, "INDEX": index, "TRIGGER": declencheurs}[genre].add(nom)
        existantes = self._tables_existantes()
        nouvelles = [reg.tables[t] for t in reg.tables if t in tables and t not in existantes]
        for t in nouvelles:
            self._sql(t.texte_pg)
        for t in nouvelles:
            for s in sqlpg.sql_cles_etrangeres(t):
                self._sql(s)
        for nom, i in reg.index.items():
            if nom in index or any(t.nom == i.table for t in nouvelles):
                self._sql(i.texte_pg)
        for nom, d in reg.declencheurs.items():
            if nom in declencheurs or any(t.nom == d.table for t in nouvelles):
                for s in d.texte_pg:
                    self._sql(s)

    def executescript(self, script):
        self.commit()
        instructions = sqlpg.decouper_instructions(script)
        if any(_RE_CREATION.match(i) for i in instructions):
            self._creer_objets(instructions)
        else:
            for i in instructions:
                if not re.match(r"\s*(BEGIN|COMMIT)\b", i, re.I):
                    self.execute(i)
        return Curseur()

    # ------------------------------------------------------------ PRAGMA
    def _meta(self):
        if not self._meta_prete:
            self._sql(f"CREATE TABLE IF NOT EXISTS {TABLE_META} (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL)")
            self._meta_prete = True

    def version_structure(self) -> int:
        self._meta()
        l = self._sql(f"SELECT valeur FROM {TABLE_META} WHERE cle = 'user_version'").fetchone()
        return int(l[0]) if l else 0

    def _pragma(self, sql) -> Curseur:
        m = _RE_PRAGMA.match(sql)
        if not m:
            return Curseur()
        nom, valeur, argument = m.group(1).lower(), m.group(2), m.group(3)
        if nom == "foreign_keys":
            if valeur is not None:
                self._fk = 1 if valeur.upper() in ("1", "ON", "TRUE") else 0
                return Curseur()
            return Curseur([(self._fk,)], ["foreign_keys"])
        if nom == "defer_foreign_keys":
            if valeur is not None and valeur.upper() in ("1", "ON", "TRUE") and self.in_transaction:
                self._sql("SET CONSTRAINTS ALL DEFERRED")
            return Curseur()
        if nom == "user_version":
            if valeur is not None:
                self._meta()
                self._sql(f"INSERT INTO {TABLE_META} (cle, valeur) VALUES ('user_version', %s) "
                          f"ON CONFLICT (cle) DO UPDATE SET valeur = EXCLUDED.valeur", (str(int(valeur)),))
                return Curseur()
            return Curseur([(self.version_structure(),)], ["user_version"])
        if nom == "integrity_check":
            return Curseur([("ok",)], ["integrity_check"])
        if nom == "database_list":
            return Curseur([(0, "main", self.identifiant)], ["seq", "name", "file"])
        if nom == "table_info" and argument:
            return self._table_info(argument)
        if nom == "foreign_key_list" and argument:
            return self._fk_list(argument)
        if nom == "foreign_key_check":
            return self._fk_check()
        return Curseur()                                           # legacy_alter_table, etc. : sans objet

    def _table_info(self, table) -> Curseur:
        types = {"bigint": "INTEGER", "integer": "INTEGER", "smallint": "INTEGER", "double precision": "REAL",
                 "bytea": "BLOB", "numeric": "NUMERIC"}
        lignes = self._sql(
            "SELECT a.attnum - 1, upper(a.attname), format_type(a.atttypid, a.atttypmod), a.attnotnull, "
            "pg_get_expr(d.adbin, d.adrelid), "
            "EXISTS (SELECT 1 FROM pg_index x WHERE x.indrelid = a.attrelid AND x.indisprimary AND a.attnum = ANY (x.indkey)) "
            "FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
            "WHERE a.attrelid = to_regclass(%s) AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum",
            (table.lower(),)).fetchall()
        sortie = [(i, n, types.get(t, "TEXT"), int(nn), d, int(pk)) for i, n, t, nn, d, pk in lignes]
        return Curseur(sortie, ["cid", "name", "type", "notnull", "dflt_value", "pk"])

    def _liens(self, table=None):
        """[(table enfant, id, seq, table parent, colonne enfant, colonne parent, suppression)] des clés étrangères."""
        filtre, params = ("AND con.conrelid = to_regclass(%s)", (table.lower(),)) if table else ("", None)
        actions = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}
        lignes = self._sql(
            "SELECT upper(cr.relname), con.oid::bigint, k.n - 1, upper(rc.relname), upper(a.attname), upper(fa.attname), "
            "con.confdeltype FROM pg_constraint con JOIN pg_class cr ON cr.oid = con.conrelid "
            "JOIN pg_class rc ON rc.oid = con.confrelid "
            "CROSS JOIN LATERAL unnest(con.conkey, con.confkey) WITH ORDINALITY AS k(c, fc, n) "
            "JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.c "
            "JOIN pg_attribute fa ON fa.attrelid = con.confrelid AND fa.attnum = k.fc "
            "JOIN pg_namespace n ON n.oid = cr.relnamespace "
            f"WHERE con.contype = 'f' AND n.nspname = current_schema() {filtre} ORDER BY con.oid, k.n", params).fetchall()
        return [(e, i, s, p, ce, cp, actions.get(d, "NO ACTION")) for e, i, s, p, ce, cp, d in lignes]

    def _fk_list(self, table) -> Curseur:
        rangs, sortie = {}, []
        for _, ident, seq, parent, ce, cp, sup in self._liens(table):
            rang = rangs.setdefault(ident, len(rangs))
            sortie.append((rang, seq, parent, ce, cp, "NO ACTION", sup, "NONE"))
        return Curseur(sortie, ["id", "seq", "table", "from", "to", "on_update", "on_delete", "match"])

    def _fk_check(self) -> Curseur:
        """Lignes dont la clé étrangère ne trouve pas de parent : [(table, rowid, table parente, n° du lien)]."""
        groupes = {}
        for enfant, ident, _, parent, ce, cp, _ in self._liens():
            groupes.setdefault((enfant, ident, parent), []).append((ce, cp))
        sortie = []
        for numero, ((enfant, _, parent), cols) in enumerate(groupes.items()):
            non_nul = " AND ".join(f"c.{ce.lower()} IS NOT NULL" for ce, _ in cols)
            lien = " AND ".join(f"p.{cp.lower()} = c.{ce.lower()}" for ce, cp in cols)
            for (rid,) in self._sql(f"SELECT c.ctid::text FROM {enfant.lower()} c WHERE {non_nul} "
                                    f"AND NOT EXISTS (SELECT 1 FROM {parent.lower()} p WHERE {lien}) LIMIT 1000").fetchall():
                sortie.append((enfant, rid, parent, numero))
        return Curseur(sortie, ["table", "rowid", "parent", "fkid"])


class _CurseurLegacy:
    """`conn.cursor()` : mêmes méthodes, résultat du dernier execute."""

    def __init__(self, conn):
        self._conn, self._c = conn, Curseur()

    def execute(self, sql, params=()):
        self._c = self._conn.execute(sql, params)
        return self

    def executemany(self, sql, sequence):
        self._c = self._conn.executemany(sql, sequence)
        return self

    def __getattr__(self, nom):
        return getattr(self._c, nom)

    def __iter__(self):
        return iter(self._c)


# ============================================================================ ouverture
def schema_de(chemin) -> str:
    """Nom du schéma PostgreSQL isolé pour un chemin de base de test (GESTSCO_PG_ISOLER=1) : un schéma par base, comme un fichier."""
    if str(chemin) == ":memory:":                                  # base en mémoire = base neuve à chaque ouverture
        return "t_" + uuid.uuid4().hex[:16]
    return "t_" + hashlib.sha1(str(chemin).encode("utf-8")).hexdigest()[:16]


def nettoyer_url(url: str) -> str:
    """URL sans mot de passe (pour l'affichage et les clés de cache)."""
    return re.sub(r"(://[^:/@]+):[^@]*@", r"\1@", url)


def connecter_pg(url: str, schema_sql: str, schema=None) -> Connexion:
    """Ouvre PostgreSQL (psycopg v3). `schema_sql` : le schéma SQLite de l'application (database.SCHEMA), source de vérité.
    `schema` : nom d'un schéma PostgreSQL à utiliser (tests) ; sinon `public`."""
    try:
        import psycopg
    except ImportError as erreur:
        raise ImportError("Le pilote PostgreSQL est absent : pip install \"psycopg[binary]>=3.2\"") from erreur
    from psycopg.adapt import Loader

    class _Nombre(Loader):                                        # SUM()/AVG() : NUMERIC -> int ou float (pas de Decimal)
        def load(self, data):
            t = bytes(data).decode()
            try:
                return int(t)
            except ValueError:
                return float(t)

    try:
        pg = psycopg.connect(url, autocommit=True)
    except psycopg.Error as erreur:
        raise ErreurOperationnelle(f"Connexion à PostgreSQL impossible : {erreur}") from erreur
    pg.adapters.register_loader("numeric", _Nombre)
    reg = sqlpg.enregistrer(schema_sql)
    conn = Connexion(pg, nettoyer_url(url) + (f"#{schema}" if schema else ""), reg)
    conn._erreur_pg = psycopg.Error
    conn._sql("CREATE EXTENSION IF NOT EXISTS citext")             # clés insensibles à la casse (COLLATE NOCASE de SQLite)
    if schema:
        conn._sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        conn._sql(f"SET search_path TO {schema}, public")
    return conn

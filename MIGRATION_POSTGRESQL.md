# Migration de GESTSCO vers PostgreSQL

GESTSCO fonctionne maintenant sur **SQLite (par défaut, comme avant)** ou sur **PostgreSQL**. Le moteur se choisit avec une
variable d'environnement, sans modifier le code :

| `GESTSCO_DATABASE_URL` | Moteur utilisé |
|---|---|
| non définie | fichier SQLite `college.db` (comportement inchangé) |
| `postgresql://utilisateur:motdepasse@hôte:5432/gestsco` | PostgreSQL |

(`DATABASE_URL` est aussi lue si `GESTSCO_DATABASE_URL` est absente.)

## Ce qui a été ajouté

| Fichier | Rôle |
|---|---|
| `sqlpg.py` | Traduction du SQL SQLite → PostgreSQL (requêtes et schéma : types, `AUTOINCREMENT`, `COLLATE NOCASE`, `GLOB`, `INSERT OR …`, déclencheurs, ordre des `NULL`…) |
| `pgconn.py` | Connexion qui se comporte comme `sqlite3.Connection` : le reste du programme n'a pas besoin de savoir quel moteur est utilisé |
| `pgcopie.py` | Copie complète SQLite ⇄ PostgreSQL (migration, sauvegarde, restauration) |
| `migrer_vers_postgresql.py` | Outil de migration en ligne de commande, avec vérification |
| `test_postgresql.py` | Tests (34) |

Adaptations ponctuelles : `database.connecter`, `config.url_postgresql`, `migrations.py` (ajout de colonne),
`sauvegarde.py`, `renvoi.py`, `reinitialisation.py`, `gestion_presences.py` et `encaissements.py` (deux requêtes
`GROUP BY` incomplètes, acceptées par SQLite mais refusées par PostgreSQL), `requirements.txt`.

## 1. Préparer PostgreSQL (version 13 ou plus)

```sql
CREATE ROLE gestsco LOGIN PASSWORD 'un-mot-de-passe-solide';
CREATE DATABASE gestsco OWNER gestsco ENCODING 'UTF8';
```

L'application a besoin de l'extension `citext` (matricules et identifiants insensibles à la casse, comme `COLLATE NOCASE`).
Depuis PostgreSQL 13 elle est « de confiance » : le propriétaire de la base peut l'installer, et GESTSCO le fait seul
(`CREATE EXTENSION IF NOT EXISTS citext`). Si votre hébergeur l'interdit, faites-le une fois en administrateur :
`\c gestsco` puis `CREATE EXTENSION citext;`.

## 2. Installer le pilote

```
pip install -r requirements.txt
```

## 3. Migrer les données

**Faites d'abord une sauvegarde** (Travaux techniques > Sauvegarde, ou copiez `college.db`). L'outil ne modifie jamais le
fichier SQLite : il travaille sur une copie.

```
python migrer_vers_postgresql.py --url postgresql://gestsco:motdepasse@localhost:5432/gestsco --source /chemin/college.db
```

L'outil : met la copie à niveau si elle est ancienne → crée la structure dans PostgreSQL → copie tout **en une seule
transaction (tout ou rien)** → recale les compteurs automatiques → **compare** la source et PostgreSQL (nombre de lignes de
chaque table, totaux des reçus par devise et statut, chaîne d'empreintes du journal). Il se termine par
« Vérification réussie » ou liste les écarts (code de sortie ≠ 0).

Si une base PostgreSQL contient déjà des données, l'outil refuse sans `--ecraser`.
Si SQLite contient une valeur que PostgreSQL refuse (texte dans une colonne numérique, caractère nul…), l'outil l'indique
avec la table, la colonne et le numéro de ligne, et ne copie rien.

## 4. Lancer l'application sur PostgreSQL

```
export GESTSCO_DATABASE_URL=postgresql://gestsco:motdepasse@localhost:5432/gestsco   # Windows : set ...
python main.py        # ou le serveur web
```

Pour **revenir** à SQLite : supprimez la variable. Le fichier `college.db` d'origine est intact (mais ne contient pas
ce qui a été saisi depuis dans PostgreSQL ; pour le récupérer, faites une sauvegarde `.csfbak` depuis PostgreSQL et restaurez-la
sous SQLite).

## Sauvegardes

L'écran **Sauvegarde / Restauration** continue de fonctionner à l'identique. L'archive `.csfbak` contient toujours un fichier
`college.db` (SQLite) : une sauvegarde faite sous PostgreSQL peut être restaurée sous SQLite, et inversement. Pour les
sauvegardes d'exploitation d'un serveur, ajoutez `pg_dump` (planifié) : c'est l'outil de référence de PostgreSQL.

## Différences à connaître

- **Écritures simultanées** : `BEGIN IMMEDIATE` (numéros de reçu, d'arrivée…) devient un verrou consultatif PostgreSQL : un seul
  enregistrement de ce type à la fois, comme sous SQLite. Les lectures ne bloquent personne.
- **Une instruction qui échoue** n'abandonne pas la transaction (SAVEPOINT par instruction), comme sous SQLite.
- **Tri des accents** : SQLite trie par code de caractère, PostgreSQL selon la langue de la base (ex. `fr_FR.UTF-8`) : l'ordre
  alphabétique des noms accentués est donc plus naturel, mais peut différer de l'ancien.
- **Suppression avec données liées** (Travaux techniques > Référentiels) identifie les lignes par `ctid` (équivalent de `rowid`) ;
  ces identifiants changent si une autre session modifie la ligne entre l'aperçu et la suppression (l'opération échoue alors
  proprement).
- **Connexions** : une connexion par requête web, sans « pool ». Pour un trafic soutenu, placez PgBouncer devant PostgreSQL.
- **`sessions_web.db`** (sessions des pages web, quelques lignes éphémères) reste un petit fichier SQLite local : il n'est pas
  concerné par la migration.
- La structure est contrôlée **une fois par processus** au premier accès (pas à chaque requête).

## Vérifier l'installation

Sans serveur PostgreSQL (traduction de toutes les requêtes du programme, schéma, couche de compatibilité) :

```
python -m unittest test_postgresql -v
```

Avec un serveur de test (migration réelle SQLite → PostgreSQL → SQLite) :

```
GESTSCO_TEST_PG_URL=postgresql://postgres:pw@localhost/gestsco_test python -m unittest test_postgresql -v
```

Pour rejouer **toute** la suite de tests du programme sur PostgreSQL (un schéma PostgreSQL isolé par base de test) :

```
GESTSCO_DATABASE_URL=postgresql://postgres:pw@localhost/gestsco_test GESTSCO_PG_ISOLER=1 python -m unittest test_acces_web
```

> **État de validation.** Ces tests ont été écrits et exécutés dans un environnement sans serveur PostgreSQL : le test
> d'intégration ci-dessus et la suite complète sur PostgreSQL n'ont donc **pas encore été exécutés**. Lancez-les sur un serveur
> de test avant de migrer les données de production ; les anomalies éventuelles se corrigent dans `sqlpg.py` / `pgconn.py`.

"""Migre la base GESTSCO (fichier SQLite college.db) vers PostgreSQL.

    python migrer_vers_postgresql.py --url postgresql://gestsco:motdepasse@localhost:5432/gestsco [--source chemin/college.db]

Ce que fait l'outil :
  1. travaille sur une COPIE du fichier SQLite (l'original n'est jamais modifié) et la met à niveau si elle est ancienne ;
  2. crée la structure dans PostgreSQL (tables, index, déclencheurs, clés étrangères) ;
  3. copie toutes les données en une seule transaction (tout ou rien), clés et empreintes du journal comprises ;
  4. recale les compteurs automatiques, puis COMPARE la source et PostgreSQL (lignes par table, totaux des reçus,
     chaîne d'empreintes du journal) et affiche le résultat.

Une base PostgreSQL qui contient déjà des données n'est écrasée qu'avec --ecraser.
"""
import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import config
import database
import migrations
import pgconn
import pgcopie


def migrer(url, source, ecraser=False, sortie=print) -> int:
    source = Path(source)
    if not source.is_file():
        sortie(f"Fichier introuvable : {source}")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        copie = Path(tmp) / "college.db"
        shutil.copyfile(source, copie)                             # l'original reste intact
        src = sqlite3.connect(copie)
        src.row_factory = sqlite3.Row
        try:
            ok = [l[0] for l in src.execute("PRAGMA integrity_check")]
            if ok != ["ok"]:
                sortie("La base SQLite est abîmée : " + " ; ".join(ok[:3]))
                return 2
            src.execute("PRAGMA foreign_keys = ON")
            actions = migrations.mettre_a_jour(src, sauvegarder=False)
            if actions:
                sortie("Structure SQLite mise à niveau (sur la copie) : " + " ; ".join(actions)[:300])
            conn = pgconn.connecter_pg(url, database.SCHEMA)
            try:
                migrations.mettre_a_jour(conn, chemin=conn.identifiant)
                deja = conn.execute("SELECT COUNT(*) FROM ELEVE").fetchone()[0] + conn.execute(
                    "SELECT COUNT(*) FROM PAIEMENT").fetchone()[0]
                comptes = conn.execute("SELECT COUNT(*) FROM JOURNAL").fetchone()[0]
                if (deja or comptes > 1) and not ecraser:
                    sortie("La base PostgreSQL contient déjà des données. Relancez avec --ecraser pour les remplacer.")
                    return 3
                sortie(f"Copie vers {conn.identifiant} ...")
                copiees = pgcopie.importer(conn, src, vider=True, rapport=sortie)
                sortie(f"{sum(copiees.values())} ligne(s) copiées dans {len(copiees)} tables. Vérification ...")
                ecarts = pgcopie.comparer(conn, src)
                if ecarts:
                    sortie("ÉCARTS DÉTECTÉS :\n  " + "\n  ".join(ecarts))
                    return 4
                sortie("Vérification réussie : mêmes nombres de lignes, mêmes totaux de reçus, journal intact.")
                sortie("Étape suivante : définir GESTSCO_DATABASE_URL pour lancer l'application sur PostgreSQL.")
                return 0
            finally:
                conn.close()
        finally:
            src.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Migration de GESTSCO : SQLite -> PostgreSQL")
    p.add_argument("--url", default=config.url_postgresql(), help="adresse PostgreSQL (ou variable GESTSCO_DATABASE_URL)")
    p.add_argument("--source", default=str(config.FICHIER_BD), help="fichier SQLite à migrer (défaut : %(default)s)")
    p.add_argument("--ecraser", action="store_true", help="remplace les données déjà présentes dans PostgreSQL")
    a = p.parse_args(argv)
    if not a.url:
        p.error("adresse PostgreSQL manquante (--url ou GESTSCO_DATABASE_URL)")
    try:
        return migrer(a.url, a.source, a.ecraser)
    except (pgcopie.ErreurCopie, migrations.ErreurMiseAJour, sqlite3.Error, ImportError) as erreur:
        print(f"Migration interrompue, rien n'a été copié : {erreur}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

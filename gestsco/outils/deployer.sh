#!/bin/bash
# Mise à jour de la version web depuis GitHub (PythonAnywhere : Consoles > Bash).
# Usage :  bash outils/deployer.sh            -> dernière version publiée
#          bash outils/deployer.sh v0.58      -> une version précise (retour arrière)
# La base de données est hors du dossier du programme (CSF_DATA_DIR) : elle n'est jamais touchée.
set -euo pipefail
cd "$(dirname "$0")/.."
CIBLE="${1:-}"
git fetch --tags origin
if [ -z "$CIBLE" ]; then
  CIBLE=$(git tag --list 'v[0-9]*' --sort=-v:refname | head -n1)
  [ -n "$CIBLE" ] || { echo "Aucune version publiée."; exit 1; }
fi
echo "Version actuelle : $(git describe --tags --always)"
echo "Version cible    : $CIBLE"
# Sauvegarde de sécurité de la base avant de changer le code (si CSF_DATA_DIR est défini)
if [ -n "${CSF_DATA_DIR:-}" ] && [ -f "$CSF_DATA_DIR/college.db" ]; then
  cp "$CSF_DATA_DIR/college.db" "$CSF_DATA_DIR/college_avant_$(date +%Y%m%d_%H%M%S).db"
  echo "Copie de sécurité de la base faite."
fi
git checkout --quiet "$CIBLE"
pip install --user -q -r requirements.txt
touch wsgi.py   # demande le rechargement à l'hébergeur ; sinon : onglet Web > Reload
echo "Terminé. Si le site ne change pas : onglet Web > Reload."

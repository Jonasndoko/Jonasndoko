# Gérer les versions de GESTSCO avec GitHub

Le dossier du programme **est** le dépôt Git. Les données de l'école (`college.db`, sauvegardes `.csfbak`, `donnees_gestisc/`) sont
exclues par `.gitignore` : elles ne vont jamais sur GitHub. **Mettez le dépôt en privé** (le code contient la logique de l'école).

## 1. Une seule fois : créer le dépôt
1. Sur github.com : **New repository** > nom `gestsco` > **Private** > ne cochez rien d'autre > Create.
2. Dans le dossier du programme (Git doit être installé) :
```
git init -b main
git add -A
git commit -m "Version 1.0 : base du dépôt"
git tag -a v1.0 -m "Version 1.0"
git remote add origin https://github.com/VOTRE-COMPTE/gestsco.git
git push -u origin main --tags
```
3. (Facultatif) pour que GitHub fabrique le fichier `.csfupd` signé à chaque version : dépôt > **Settings > Secrets and variables >
   Actions > New repository secret** > nom `GESTSCO_CLE_MAJ`, valeur = votre clé de mise à jour (8 caractères ou plus).

## 2. Chaque fois que vous changez le programme
```
git add -A
git commit -m "Phrase qui décrit le changement"        # ces phrases alimentent l'historique (CHANGELOG.md)
python outils/version.py monter minor                    # 1.0 -> 1.1  (ou major : 2.0, patch : 1.0.1, ou un numéro : 1.5)
python outils/version.py publier                         # envoie sur GitHub
```
- Chaque envoi lance les **tests** (onglet *Actions*). Une étiquette de version lance en plus la **publication** : tests, puis
  « Release » GitHub avec l'historique et le fichier `gestsco_X.Y.csfupd` (si le secret est défini). L'empreinte à communiquer
  avec la clé est écrite dans la Release.
- `python outils/version.py etat` : version, état du dépôt, alerte si des données sont suivies par erreur.
  `python outils/version.py liste` : versions publiées. `python outils/version.py paquet` : fabrique le `.csfupd` sur votre PC.

## 3. Mettre la version web à jour (PythonAnywhere)
Première fois, dans **Consoles > Bash** (dépôt privé : créez un *token* GitHub en lecture seule et utilisez-le comme mot de passe) :
```
git clone https://github.com/VOTRE-COMPTE/gestsco.git ~/gestsco
```
Puis, à chaque nouvelle version :
```
cd ~/gestsco && bash outils/deployer.sh            # dernière version publiée
```
Le script copie la base par sécurité (si `CSF_DATA_DIR` est défini), place le code sur la version voulue, installe les
dépendances et demande le rechargement. Sinon : onglet **Web > Reload**.

**Retour arrière** : `bash outils/deployer.sh v1.0`. Si la base a été transformée par une version plus récente, restaurez aussi la
sauvegarde « Avant-mise-à-jour » (Travaux techniques > Restauration).

## 4. Deux voies de mise à jour, au choix
- **GitHub** (ci-dessus) : pour vous, qui avez accès à la console de l'hébergeur.
- **Fichier `.csfupd`** (déjà dans le programme, Travaux techniques > Mise à jour du programme) : pour l'Administrateur de l'école,
  sans console ; signé avec la clé, avec sauvegarde de sécurité et retour arrière. Téléchargez-le depuis la Release GitHub.

## Bonnes habitudes
- Ne modifiez jamais le code directement sur le serveur : modifiez chez vous, `commit`, `monter`, `publier`, puis `deployer.sh`.
- Avant `monter`, tout doit être enregistré (`git commit`) : l'outil refuse sinon.
- Ne mettez jamais de mot de passe, de clé ou de base réelle dans un commit. Si cela arrive, changez le secret tout de suite.

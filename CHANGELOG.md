# Historique des versions

## 1.4

- Le module « Gestion scolaire » est supprimé : ses fonctionnalités deviennent des onglets de la Direction des études (Gestion des études et discipline > Espace Études) : « Années et périodes », « Cours », « Programme des classes », « Enseignants et classes » (titulaire de classe, compte du professeur) et « Présence des élèves ». Les écrans et le droit « Gestion scolaire » disparaissent du menu principal, du Gestionnaire d'accès, du tableau de bord et de la recherche du journal.
- Les droits correspondants sont ceux de « Direction des études » (Lecture, Ajout, Modification, Suppression) : la Directrice des études gère maintenant les cours et les enseignants. Base déjà installée : la migration n° 18 (automatique au démarrage) reporte les droits déjà accordés sur « Gestion scolaire », pour les comptes et pour les rôles, vers « Direction des études ».
- Le module « Présence des élèves » reste, pour le Directeur de discipline (qui n'a pas accès à la Direction des études).
- Les adresses `/m/gestion_scolaire/...` disparaissent ; les actions se font sous `/m/etudes_discipline/direction_etudes/gestion/...`. Logiciel Windows : seul « Présence des élèves » subsiste ; les cours et enseignants se gèrent en ligne.

## 1.3

- Le module Inscription devient une fonctionnalité du Secrétariat (onglet « 2. Inscription ») : formulaire, liste d'attente, validation et affectation s'affichent dans le cadre du Secrétariat. Les adresses `/m/inscription/...` et les règles (reçu, test d'admission, affectation) ne changent pas.
- La tuile « Inscription » du menu principal disparaît pour les comptes qui ont accès au Secrétariat ; elle reste pour les autres comptes qui ont le droit d'inscription.
- Le rôle Secrétaire reçoit par défaut les droits Lecture, Ajout et Modification sur « Inscription » (bases créées à partir de cette version). Base déjà installée : Gestionnaire d'accès > Rôles > Secrétaire, cocher les droits et « appliquer aussi aux comptes existants ».

## 1.2

- Liste des élèves par classe, option et année scolaire dans la Direction des études, la Direction de discipline, la Préfecture et le Secrétariat : consultation à l'écran, impression PDF et export CSV, avec les effectifs de garçons et de filles. Chaque espace est limité à son propre droit de Lecture (relu à chaque requête) et à la section Secondaire et humanitaire ; les dossiers incomplets restent propres au Secrétariat. Chaque consultation, impression et exportation est inscrite au journal avec l'espace demandeur.

## 1.1

- Direction des études, 7e fonctionnalité « Passage en classe supérieure » : en fin d'année, les élèves qui ont réussi (résultat annuel « ADMIS(E) ») sont inscrits dans la classe supérieure de l'année suivante ; ceux qui ont échoué restent dans la même classe (statut « Redoublant ») ; ceux dont le résultat est en attente ne sont pas traités ; les élèves de 4ème humanités qui réussissent ont terminé leurs études.
- Élèves de 8ème : la Direction des études saisit à leur place l'option choisie (classe de 1ère humanités), élève par élève ou pour tous les élèves sans choix ; aucune option n'est attribuée d'office.
- Annulation d'un passage (motif obligatoire), liste imprimable et export CSV, chaque opération inscrite au journal. Nouvelles tables PROMOTION et PROMOTION_CHOIX (créées automatiquement au démarrage).

## 1.0

- Version de départ du dépôt GitHub (restauration et mise à jour du programme en ligne, PostgreSQL).


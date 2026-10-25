# Mettre GESTSCO en ligne (version web)

La version web (`app_web.py`) tourne avec Flask et la même base SQLite que le logiciel Windows. Elle remplace le serveur local
`serveur_notes.py` (qui reste utilisable). **Rien n'est déployé tant que vous n'avez pas fait les étapes ci-dessous** : je n'ai pas accès à un compte d'hébergement.

**Modules disponibles en ligne** : Paiement des frais (v0.39), Encaissement des fonds perçus (v0.40), Inscription (v0.41), Carte (v0.42), Contrôle numérique (v0.43), Application mobile de contrôle (v0.44, installable v0.45), Gestion du personnel (v0.46), Travaux techniques (v0.47, en partie), Présence des élèves (v0.48), Gestionnaire d'accès (v0.49), Traçabilité et audit (v0.50) et Espace professeurs. Les autres modules affichent « en cours de migration » et restent dans le logiciel Windows (voir `FEUILLE_DE_ROUTE.md`).

## 1. Essayer sur votre ordinateur
Double-cliquez `Lancer_Web.bat`, ouvrez http://127.0.0.1:5000. Code d'installation de l'essai : `essai-local`.

**Gestion du personnel en ligne (v0.46)** : trois fonctionnalités, comme dans le logiciel Windows. *Dossier personnel* (nouvel agent, modification, désactivation, documents numérisés PDF/JPEG/PNG de 5 Mo au plus, fiche PDF), *Fonctions et affectations* (listes de fonctions et de services, historique des affectations, liste du personnel en PDF), *Présence et absence* (pointage du jour, jours non travaillés, permissions et congés, états récapitulatifs en PDF).
Droits sur « Gestion du personnel » (Gestionnaire d'accès) : **Lecture** ouvre le module, consulte et imprime ; **Ajout** enregistre un agent, joint un document, affecte, pointe, accorde une permission ou un congé ; **Modification** corrige, désactive, corrige un pointage, annule une autorisation ; **Suppression** retire un document, un pointage ou un jour non travaillé.
Les documents sont gardés dans la base (`college.db`) : sauvegardez-la. Les dossiers du personnel sont des données personnelles : n'y mettez que des données fictives pour l'essai. Flask 3.1 ou plus récent est maintenant exigé (`pip install --user -r requirements.txt`).

**Travaux techniques en ligne (v0.47)** : réservé à l'**Administrateur** (contrôlé à chaque action, chaque opération est inscrite au journal). Quatre fonctionnalités :
- *Mise à jour des tables* : années, niveaux, options, classes, devises, types de frais, tarifs, élèves, inscriptions, percepteurs, paiements, encaissements. Ajouter, modifier, désactiver / réactiver, supprimer. Une donnée utilisée ailleurs n'est supprimée qu'après un aperçu de ce qui en dépend et une confirmation ; si un reçu en dépend, la suppression est refusée (désactivez plutôt). Un reçu ne se supprime jamais : il s'**annule** avec un motif.
- *Structure de la base* : analyse, mise à jour (sauvegarde de sécurité faite avant), contrôle d'intégrité. Cette mise à jour est aussi faite automatiquement au démarrage.
- *Authentification et mots de passe* : état des comptes, **code de récupération** (affiché une seule fois à l'Administrateur, valable 2 minutes, usage unique), mot de passe provisoire, déblocage, journal. L'utilisateur saisit son code sur la page publique `/mot-de-passe-oublie` (lien « Mot de passe oublié ? » sur l'écran de connexion).
- *Sauvegarde* : crée une copie complète (.csfbak) et la fait **télécharger** : faites-le régulièrement, une sauvegarde laissée sur le serveur ne protège pas d'une panne de l'hébergeur.

**Gestionnaire d'accès en ligne (v0.49)** : réservé à l'**Administrateur** (contrôlé à chaque action, chaque opération est inscrite au journal). Trois fonctionnalités, comme dans le logiciel Windows :
- *Utilisateurs* : créer un compte (identifiant, nom, rôle) -> mot de passe provisoire affiché **une seule fois** (à dire de vive voix, à changer à la première connexion) ; modifier (nom, rôle, état) ; activer / désactiver ; nouveau mot de passe provisoire ; débloquer. Garde-fous : pas de changement de son propre rôle ni de désactivation de son propre compte, et il reste toujours un Administrateur actif.
- *Rôles* : les 8 postes de base et ceux que vous créez ; droits de base de chaque rôle (matrice Lecture / Ajout / Modification / Suppression par module), avec l'option « appliquer aussi aux comptes existants » ; suppression d'un rôle créé, tant qu'aucun compte ne l'utilise.
- *Autorisations* : droits de chaque utilisateur module par module, sections de l'école qui lui sont ouvertes (Primaire, Secondaire et humanitaire), rétablissement des droits de base de son rôle. L'effet est immédiat, même pour une personne déjà connectée. Rien n'est enregistré si une partie du formulaire est invalide.

**Traçabilité et audit en ligne (v0.50)** : consultation seule, ouverte à l'**Administrateur** et aux comptes à qui il a accordé la **Lecture** sur « Traçabilité et audit » (Gestionnaire d'accès > Autorisations ou Rôles). Le droit est relu à chaque page : le retirer coupe l'accès tout de suite. Six onglets :
- *Journal des activités* : qui a fait quoi, quand ; filtres période, utilisateur, catégorie, texte, « opérations financières seulement ».
- *Opérations financières* : paiements, reçus, annulations, encaissements, remises et écarts, avec totaux par devise ; un clic sur la référence ouvre la fiche (qui, quand, toutes les traces).
- *Contrôles* : intégrité du journal (chaîne d'empreintes : toute modification après coup se voit) et concordance entre le journal et les tables financières.
- *Contrôle et audit financier* : reçus, rapprochement encaissé / remis, annulations, corrections, rapports journaliers imprimés et anomalies classées par gravité, avec piste de vérification. Il ne s'exécute qu'au clic sur « Lancer le contrôle ».
- *Recherche et filtrage des traces* : par utilisateur, période, module, type d'action, n° de reçu, matricule.
- *Rapports d'audit* : général, financier, anomalies ou complet ; consultables à l'écran, **PDF** (A4 paysage, cases de signature) et **CSV** (Excel).
Les filtres sont dans l'adresse de la page : la recherche affichée est exactement celle qui est exportée. Un export est fabriqué, envoyé au navigateur, puis **effacé du serveur**. L'ouverture du module, les contrôles, les recherches sur un reçu ou un élève et chaque exportation sont inscrits au journal (on peut donc savoir qui a consulté l'audit). Ces exports contiennent des données d'élèves et de paiements : conservez-les comme des documents confidentiels.

**Tableau de bord en ligne (v0.51)** : page d'accueil de l'**Administrateur** et des comptes à qui il a accordé la Lecture sur « Tableau de bord » (adresse `/tableau-de-bord`, le menu des modules reste à `/menu`). Il montre des **élèves** de l'année choisie (total, en règle, pas en règle), le personnel actif, trois graphiques (évolution du nombre d'élèves, situation des élèves, filles et garçons par année) et les accès rapides. Aucun nom, aucun montant. Les droits sont relus à chaque affichage ; chaque ouverture est inscrite au journal.

**Restauration en ligne (v0.58)** : 5e onglet de Travaux techniques (Administrateur seulement). On choisit une sauvegarde rangée sur le serveur ou on envoie un fichier `.csfbak` (200 Mo au plus ; contrôle de l'empreinte, de l'intégrité et de la structure avant d'être accepté, rien n'est remplacé à cette étape). L'écran d'examen montre le contenu ; la restauration exige de taper `RESTAURER` et de ressaisir son mot de passe. Une sauvegarde de sécurité « Avant-restauration » est faite juste avant, la base est remplacée en bloc (tout ou rien), l'opération est inscrite au journal et **tous les utilisateurs sont déconnectés**. Pour annuler une restauration, restaurez la sauvegarde « Avant-restauration ».

**Mise à jour du programme en ligne (v0.58)** : 6e onglet de Travaux techniques (Administrateur seulement). Le fichier `.csfupd` est préparé par le développeur (`python miseajour.py creer mise_a_jour.csfupd`, il contient maintenant aussi le dossier `templates`). On l'envoie avec la **clé de mise à jour** (communiquée séparément) : contrôle de la signature, des empreintes et des chemins, affichage de la version et de l'empreinte à comparer. L'installation exige la clé et le mot de passe de l'Administrateur ; elle fait une sauvegarde de sécurité de la base (« Avant-mise-a-jour »), garde les 3 dernières versions du programme et remet l'ancienne version en place au moindre problème. Le retour à une version gardée est aussi proposé (refusé si la base a déjà été transformée : restaurez alors « Avant-mise-a-jour »). **Après l'installation, rechargez l'application** chez l'hébergeur (PythonAnywhere : onglet Web > Reload) ; la structure de la base se met à jour au démarrage. Cela suppose que le dossier du programme soit modifiable par l'application : sinon, copiez les fichiers à la main. *Attention* : une ancienne version du programme (avant 0.58) refuse un fichier contenant `templates`.

**Pas encore en ligne** (à faire dans le logiciel Windows) : *Réinitialisation* et *Données d'essai*. Elles remplacent la base ou le programme en cours d'utilisation : elles demandent une procédure propre à l'hébergeur (étape 8 de `FEUILLE_DE_ROUTE.md`).

**Cours, enseignants et présence des élèves, dans la Direction des études (v1.4)** : le module « Gestion scolaire » n'existe plus ; ses fonctionnalités sont des onglets de l'espace Direction des études (Gestion des études et discipline > Espace Études). Les droits « Lecture / Ajout / Modification / Suppression » de « Direction des études » sont contrôlés à chaque action (l'Administrateur et la Directrice des études les ont tous), et chaque opération est inscrite au journal. *Base déjà installée* : au démarrage, la migration n° 18 reporte les droits déjà accordés sur « Gestion scolaire » (comptes et rôles) vers « Direction des études » ; attention, un compte qui avait la Lecture de « Gestion scolaire » ouvre donc aussi les autres onglets de la Direction des études. Fonctionnalités :
- *Cours et enseignants* : **Années et périodes** (années scolaires, semestres ou trimestres selon la section, périodes, structure standard) ; **Cours** (par niveau, option, année d'étude) ; **Programme des classes** (ouvrir les cours d'une classe, attribuer un professeur, régler les heures, retirer) ; **Enseignants et classes** (charge de chaque professeur, titulaire de classe, et, pour l'Administrateur, création du compte de connexion du professeur : identifiant et mot de passe provisoire affichés une seule fois).
- *Présence des élèves* : consultation seule de toutes les classes (situation du jour, détail par élève, récapitulatif d'une période), dans l'espace Direction des études. Le module « Présence des élèves » reste en plus pour le Directeur de discipline et la Directrice des études : leur tuile s'ouvre directement sur cette page.

Le professeur créé ici se connecte sur la page `/professeur` de votre site (pas sur la connexion du personnel). Le pointage de présence se fait par les professeurs sur cette même page.

**Passage en classe supérieure (v1.1)** : onglet « Passage en classe supérieure » de l'espace Direction des études (Directrice des études et Administrateur). Avant de l'utiliser : l'année scolaire suivante doit être créée (Direction des études > Années) et les classes de 7ème à 4ème humanités doivent exister (Travaux techniques > Mise à jour des tables > Classes). On choisit l'année qui se termine, on ouvre une classe, puis :
- les élèves qui ont **réussi** montent dans la classe supérieure (même division, même option en humanités) ; ceux qui ont **échoué** restent dans la même classe (« Redoublant ») ; ceux au résultat « en attente » ne sont pas traités ;
- **8ème** : on saisit l'option choisie par chaque élève (en choisissant sa classe de 1ère humanités), ou la même pour tous les élèves sans choix ; le bouton « Exécuter » reste bloqué tant qu'un élève qui réussit n'a pas d'option ;
- **Exécuter le passage** inscrit les élèves dans l'année suivante ; l'opération est annulable (motif obligatoire) tant que l'élève n'a ni paiement ni point dans sa nouvelle classe.
Droits sur « Direction des études » : **Lecture** consulter, imprimer, exporter ; **Ajout** saisir les options et exécuter ; **Modification** annuler. Deux tables (PROMOTION, PROMOTION_CHOIX) sont créées toutes seules au redémarrage après la mise à jour.

**Liste des élèves par classe et année scolaire (v1.2)** : onglet « Liste des élèves » de la Direction des études, de la Direction de discipline et de la Préfecture (le Secrétariat la garde dans « Listes et rapports administratifs »). On choisit l'année, la classe et l'option, puis on consulte, on imprime (PDF) ou on exporte (CSV). Droit de **Lecture** sur le module de l'espace (« Direction des études », « Direction de discipline », « Préfecture », « Secrétariat ») ; aucun nouveau droit à accorder, aucune table nouvelle.

**Inscription dans le Secrétariat (v1.3)** : l'inscription est l'onglet « Inscription » de l'espace Secrétariat (Gestion des études et discipline). Elle garde son propre droit dans le Gestionnaire d'accès (**Lecture** liste d'attente, **Ajout** formulaire, **Modification** test d'admission et affectation). Le rôle Secrétaire reçoit ces trois droits par défaut sur une base neuve ; sur une base déjà installée, allez dans Gestionnaire d'accès > Rôles > Secrétaire, cochez-les et choisissez « appliquer aussi aux comptes existants ». Un compte qui a le droit d'inscription sans avoir le Secrétariat garde la tuile « Inscription » dans le menu.

**Versions et GitHub** : le suivi des versions, la publication et la mise à jour depuis GitHub sont décrits dans `GITHUB.md`.

## 2. Hébergement gratuit (essai)
Piste : **PythonAnywhere** (offre gratuite « Beginner »). Vérifiez les conditions actuelles sur leur site avant de vous engager :
une seule application web, 512 Mo de disque, application à renouveler régulièrement (ils demandent de cliquer pour la prolonger), adresse `votrenom.pythonanywhere.com` en HTTPS.
La base SQLite se conserve sur le disque de votre compte, ce qu'il faut pour GESTSCO. Les offres « gratuites » de Render ou Fly.io n'ont pas de disque durable : la base serait effacée à chaque redémarrage, ne les utilisez pas.

Étapes :
1. Créez un compte, onglet **Files** : envoyez le contenu du dossier `gestsco` (ou **Consoles > Bash** puis `unzip`).
2. **Consoles > Bash** : `pip install --user -r requirements.txt`
3. Onglet **Web > Add a new web app > Manual configuration** (Python 3.10 ou plus récent).
4. Dans « Code », **Source code** = le dossier envoyé ; ouvrez le fichier WSGI et remplacez son contenu par :
   ```python
   import os, sys
   sys.path.insert(0, "/home/VOTRENOM/gestsco")
   os.environ["GESTISC_CODE_INSTALL"] = "choisissez-un-long-code-secret"
   os.environ["CSF_DATA_DIR"] = "/home/VOTRENOM/donnees_gestisc"
   os.environ["GESTISC_PROXY"] = "1"          # à garder si l'hébergeur place un proxy devant l'application (adresse réelle du client, HTTPS)
   from wsgi import application
   ```
5. Créez le dossier `donnees_gestisc` (Files), cliquez **Reload**, ouvrez votre adresse : la page « Premier démarrage » crée l'Administrateur (avec le code ci-dessus).
6. Ensuite, retirez `GESTISC_CODE_INSTALL` du fichier WSGI.
7. Créez les comptes dans le **Gestionnaire d'accès** en ligne (voir ci-dessous) ou dans le logiciel Windows. Pour le paiement : un compte de poste **Percepteur** avec le droit Ajout enregistre les paiements ; les autres comptes ayant accès au module consultent, impriment les duplicata et le rapport. Pour l'inscription : le droit Ajout (secrétaire) remplit le formulaire, le droit Modification (directeur des études) enregistre le test et affecte ; **avant la première inscription, l'Administrateur doit marquer un type de frais comme « Frais d'inscription »** (Travaux techniques > Mise à jour des tables > Types de frais), sinon aucune candidature n'est acceptée.
8. Les dates et heures des reçus suivent le fuseau de l'école (Africa/Kinshasa). Pour un autre fuseau : `os.environ["GESTISC_TZ"] = "Europe/Paris"`, par exemple.

**Imprimer le reçu** : le PDF fait 80 mm de large. Sur une imprimante thermique de caisse, choisissez « Taille réelle » / 100 % (pas « Ajuster à la page ») et le papier 80 mm ; sur une imprimante A4, il s'imprime en haut de la feuille.

**Carte d'élève en ligne** : la photo se prend avec la caméra du navigateur (ordinateur, tablette ou téléphone) ; le navigateur la cadre en portrait et la réduit à 300 x 400 avant de l'envoyer. **La caméra ne marche qu'en HTTPS** (ou sur `http://localhost`) : sur PythonAnywhere c'est automatique ; sinon, le bouton « Importer… » permet d'envoyer une photo déjà prise. Au premier usage, le navigateur demande l'autorisation d'utiliser la caméra. Droits : Lecture (fiche, impression), Ajout (première photo), Modification (remplacer), Suppression (retirer). Pas de carte pour la section primaire. OpenCV (`opencv-python-headless`) est facultatif côté serveur : s'il est installé, chaque photo reçue est revérifiée et recadrée ; sinon elle est acceptée telle quelle si c'est un JPEG.

**Contrôle numérique en ligne** : deux onglets. « Liste des élèves en ordre » (année, classe, option, type de frais ; impression PDF) et « Contrôle numérique d'un élève » (statut EN ORDRE / IMPAYÉ / NON INSCRIT). Il suffit du droit Lecture sur le module ; les sections ouvertes au compte sont respectées. Chaque consultation et impression est inscrite au journal. Un frais n'a de « en ordre » que si son tarif est défini (Travaux techniques > Mise à jour des tables > Tarifs).

**Application mobile de contrôle (v0.44)** : c'est une page web installable (pas une application des magasins Android/iOS), à l'adresse `https://votre-adresse/controleur`.
- *Activation* : onglet **Application mobile** du module Contrôle numérique, visible seulement de l'Administrateur et des comptes à qui il a accordé le droit **Modification** sur « Contrôle numérique » (c'est l'autorité académique autorisée). Le bouton Activer / Couper agit tout de suite : coupée, plus personne ne peut se connecter et les téléphones déjà connectés sont refusés à leur prochaine action. Chaque activation, coupure, connexion et contrôle est inscrit au journal. L'onglet affiche aussi l'adresse de l'application en code QR.
- *Contrôleurs* : chaque contrôleur a son propre compte (Gestionnaire d'accès) avec le droit **Lecture** sur « Contrôle numérique ». Le poste « Contrôleur » n'a que le droit Paiement au départ : accordez-lui Lecture sur Contrôle numérique. Session de 60 minutes d'inactivité, prolongée par chaque contrôle.
- *Sur le téléphone* : connexion (identifiant + mot de passe) -> choix d'un type de frais ou « Tous les frais » -> scan du QR de la carte (ou saisie du matricule) -> bandeau vert EN ORDRE, rouge IMPAYÉ, orange NON INSCRIT / FRAIS NON DÛ, avec la photo de l'élève, sa classe et le détail des frais. Un QR n'est accepté que s'il a été délivré par le logiciel (une carte falsifiée est refusée).
- *Caméra* : HTTPS obligatoire. Chrome sur Android lit le QR tout seul ; si le navigateur ne sait pas, la page envoie une petite image au serveur qui lit le QR avec OpenCV (`pip install opencv-python-headless`, facultatif). Sans l'un ni l'autre, le contrôleur tape le matricule.
- *Installer (v0.45)* : l'application est une **PWA** (manifeste + service worker + icônes). **Condition : adresse en HTTPS** (sinon le navigateur ne propose pas l'installation).
  Android / Chrome : ouvrir `/controleur`, toucher **« Installer sur ce téléphone »** (ou menu ⋮ > « Installer l'application »). iPhone : **Safari** > Partager > « Sur l'écran d'accueil ». L'icône « Contrôle » s'ouvre ensuite en plein écran, sans barre d'adresse.
  Hors connexion, l'application s'ouvre et affiche « Pas de connexion » : le contrôle lui-même exige le réseau (aucune donnée d'élève n'est gardée sur le téléphone ; le service worker ne met jamais en cache `/mobile/api`).
  Après une mise à jour du logiciel, le téléphone prend la nouvelle version à la prochaine ouverture avec réseau.

## 3. Avant d'y mettre de vraies données
Cette base contient des données d'élèves (mineurs) et des paiements. Pour l'essai, **utilisez des données fictives**. Pour la vraie mise en service,
prenez un hébergement payant avec sauvegardes (VPS ou offre payante), gardez HTTPS, et faites des sauvegardes régulières de `college.db`.

## Application mobile des parents (v0.52)
Application Flutter (dossier `application_parents`, voir son `LISEZMOI.md`) qui lit la situation des enfants par ce site : frais, présences, conduite, résultats.
- **Accès** : un parent n'entre qu'avec un **code** généré quand le percepteur enregistre le paiement du « frais du logiciel des parents » (type de frais marqué dans Travaux techniques > Types de frais). 1 paiement = 1 code = 1 élève ; le code s'affiche sur la page du reçu et s'imprime sur le reçu. Un reçu annulé coupe l'accès.
- **Adresses** : page de téléchargement publique `/parents`, API `/parent/api/...` (jetons dans l'en-tête, aucune session du personnel n'y vaut).
- **Fichiers** : placez `application_parents.apk` dans le dossier des données (`CSF_DATA_DIR`), ou mettez un lien Google Play dans `GESTISC_LIEN_APPLI_PARENTS`. `GESTISC_URL_PUBLIQUE` (adresse du site) sert à imprimer le lien sur le reçu.
- **HTTPS obligatoire** : l'application refuse les connexions non chiffrées sur Android récent.

## Espace des professeurs installable (icône et nom GESTSCO)
La page `/professeur` s'installe comme une application sur le téléphone ou la tablette, avec l'icône et le nom du logiciel (GESTSCO) : à l'ouverture de la page, une carte « Installer l'application » apparaît sous la connexion (bouton d'installation sur Android/Chrome ; sur iPhone : Safari > Partager > « Sur l'écran d'accueil »). Il faut une adresse en HTTPS. L'application garde seulement la page elle-même : les notes et les données ne sont jamais enregistrées sur l'appareil (le service worker ne touche pas à `/api`).

## Espace parents en ligne (v0.59)
Les parents n'ont plus besoin d'installer d'application : ils ouvrent `https://votre-site/parents` dans le navigateur de leur téléphone ou ordinateur.
- Première visite : saisir le **code d'accès** imprimé sur le reçu du « frais du logiciel des parents », créer le compte (nom, téléphone ou e-mail, mot de passe).
- Ensuite : connexion avec le téléphone ou l'e-mail ; onglets **Frais**, **Présences**, **Conduite**, **Résultats** (mise à jour automatique toutes les 30 s) ; « Ajouter un enfant » avec un nouveau code.
- Mêmes règles qu'avant : 1 paiement = 1 code = 1 élève, reçu annulé = accès coupé, nouveau paiement à chaque année scolaire.
- Le site doit être en **HTTPS**. Déconnexion automatique après 15 minutes d'inactivité ; le jeton de session n'est gardé que pour l'onglet ouvert.
- L'application Android (dossier `application_parents`) reste facultative ; sa page de téléchargement est maintenant `/parents/application`.

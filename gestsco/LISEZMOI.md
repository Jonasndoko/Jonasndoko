## Proclamation des résultats (secondaire et humanitaire)

Circuit en cinq étapes pour une classe et une période, un semestre ou l'année (`proclamation.py`). Pages : « Direction des études >
Proclamation des résultats » et « Préfecture > Proclamation des résultats » (`templates/_etudes_proclamation.html`).

1. **Autorisation.** La Directrice des études autorise le titulaire de la classe pour la période.
2. **Frais exigés.** Elle choisit les frais qu'un élève doit avoir payés pour être « en ordre » : un ou plusieurs frais (frais scolaire
   obligatoire, autres frais si nécessaire), chacun **jusqu'à une tranche demandée** ou **en totalité**. Le logiciel calcule qui est en
   ordre d'après les paiements enregistrés ; elle ne coche jamais « en ordre » à la main et **ne voit aucun montant**.
3. **Validation.** Elle valide les bulletins des élèves en ordre (seuls ceux-là peuvent l'être), puis **soumet** la proclamation au Préfet :
   elle ne peut plus y toucher.
4. **Préfet.** Il consulte les validations, peut **changer la décision** de la Directrice pour un élève (motif obligatoire, y compris
   valider un élève qui n'est pas en ordre) puis **confirme** la proclamation. Il peut encore changer une décision après la confirmation.
5. **Titulaire.** Il **consulte** toujours les bulletins (c'est lui qui lance le calcul automatique des points) mais n'**imprime** que les
   bulletins **validés** d'une proclamation **confirmée**. Même règle pour la liste des résultats et la proclamation de l'année : seuls les
   élèves validés y figurent. La page du titulaire affiche l'état de la proclamation et « Validé / Non validé » pour chaque élève.

- Chaque période (ou semestre, ou l'année) a sa propre proclamation : tables `PROCLAMATION`, `PROCLAMATION_FRAIS`, `VALIDATION_BULLETIN`
  (créées automatiquement à la mise à jour ; aucune migration de données).
- Le primaire n'est pas concerné : ses titulaires impriment comme avant.
- Journal : `PROCLAMATION_AUTORISEE`, `PROCLAMATION_CRITERES`, `BULLETIN_VALIDE`, `BULLETIN_VALIDATION_RETIREE`, `PROCLAMATION_SOUMISE`,
  `PROCLAMATION_DECISION_PREFET` (avec l'ancien état et le motif), `PROCLAMATION_CONFIRMEE`, `PROCLAMATION_CONSULTEE`.
- Droits : Directrice = « Direction des études » (Modification pour agir) ; Préfet = « Préfecture » (Modification pour changer une
  décision et confirmer). L'impression par le titulaire ne dépend d'aucun droit supplémentaire : seulement des validations.
- Tests : `python -m unittest test_proclamation`. Les anciens tests d'impression passent par `aide_tests_proclamation.ouvrir_impression`.

## Secrétariat : dossier complet d'un élève (migration 16)

Dans « Gestion des études et discipline > Secrétariat » (`secretariat.py`, page `templates/_etudes_secretariat.html`), la liste des
**dossiers des élèves** du secondaire et humanitaire permet à la secrétaire de déclarer un dossier **complet** ou de le remettre à
**incomplet**.

- **C'est la secrétaire qui détermine qu'un dossier est complet.** L'état n'est jamais calculé : ni la photo, ni un document, ni un
  paiement ne le modifient.
- **Aucune pièce n'est obligatoire** : il n'existe pas de liste de pièces, rien ne bloque la décision, et l'état n'a aucun effet sur les
  inscriptions, les paiements, les notes ni les bulletins.
- L'état est **propre à l'élève** (pas à une année scolaire) : table `DOSSIER_ELEVE`, une ligne par élève. Pas de ligne = incomplet.
- Droits : « Lecture » sur « Secrétariat » pour consulter, **« Modification »** pour décider. La secrétaire reçoit « Modification » par
  défaut (les comptes existants la reçoivent une seule fois, à la mise à jour ; l'Administrateur peut ensuite la retirer).
- Chaque décision est inscrite au journal (`DOSSIER_ELEVE_COMPLET`, `DOSSIER_ELEVE_INCOMPLET`) avec le matricule et le nom ; la
  consultation de la liste l'est aussi (`DOSSIERS_ELEVES_CONSULTES`). Redéclarer l'état déjà en place n'écrit rien.
- Tests : `python -m unittest test_secretariat`.

### Secrétariat : Archives scolaires (3e onglet)

Onglet « Archives scolaires » (`archives_scolaires.py`, page `templates/_etudes_secretariat_archives.html`, table `ARCHIVE_SCOLAIRE`) :

- **Classer** un fichier numérisé (PDF, JPEG ou PNG, 5 Mo au plus, `config.TAILLE_MAX_ARCHIVE`) : catégorie *Bulletin*, *Dossier d'un ancien
  élève* (rattachés à un élève par son matricule) ou *Document d'une année* (sans élève). L'année est libre (AAAA-AAAA) : on peut classer
  des documents d'avant l'installation du logiciel. Le format est contrôlé sur le **contenu** du fichier ; un même fichier ne se classe pas
  deux fois pour la même année et le même élève.
- **Rechercher** par élève (nom, postnom, prénom, matricule), année scolaire et type ; case « Anciens élèves seulement » (désactivés ou
  non inscrits dans l'année en cours). Le **dossier d'un élève** montre son parcours et tous ses documents.
- La recherche retrouve aussi, **en lecture seule**, les copies de bulletins archivées dans « Bulletins scolaires » (par la classe de l'élève
  cette année-là) et les documents officiels signés par la Préfecture.
- **Rien n'est supprimé** : « Retirer » demande un motif et masque le document ; le fichier reste dans la base et dans les sauvegardes.
- Droits sur « Secrétariat » : Lecture = rechercher et ouvrir, Modification = classer (la secrétaire l'a déjà), **Suppression = retirer**
  (non accordé par défaut : Gestionnaire d'accès > Autorisations ou Rôles). Tout est inscrit au journal.
- Les fichiers sont dans `college.db` : à sauvegarder régulièrement. Ce sont des données d'élèves : traitez-les comme confidentielles.
- Tests : `python -m unittest test_archives_scolaires`.

### Secrétariat : Listes et rapports administratifs (4e onglet)

Onglet « Listes et rapports administratifs » (`listes_administratives.py`, PDF dans `listes_administratives_pdf.py`, page `templates/_etudes_secretariat_listes.html`) :

- **Liste des élèves** et **Dossiers incomplets**, par **année scolaire**, **classe** et **option** (ou « classes sans option »). Chaque classe est présentée à part, avec
  son effectif (garçons, filles, dossiers incomplets) ; la liste des dossiers incomplets ajoute le tuteur et son téléphone pour pouvoir le relancer.
- **Imprimer (PDF)** : une page au moins par classe, en-tête de l'école, pagination, date d'édition. **Exporter (CSV)** : séparateur « ; », s'ouvre dans Excel.
- Un dossier est « incomplet » tant que la secrétaire ne l'a pas déclaré complet (onglet « Dossiers des élèves ») : rien n'est calculé, aucune pièce n'est exigée.
- Élèves inscrits dans l'année choisie, section secondaire et humanitaire seulement. Les élèves désactivés n'y figurent pas ; la case « Inclure les élèves
  désactivés » (liste des élèves) permet de retrouver l'effectif d'une année passée. Les dossiers incomplets ne concernent jamais les élèves désactivés.
- Droit « Lecture » sur « Secrétariat » pour consulter, imprimer et exporter (la secrétaire l'a déjà). Ces listes ne modifient rien. Chaque consultation,
  impression et exportation est inscrite au journal (`LISTE_ADMIN_CONSULTEE`, `LISTE_ADMIN_IMPRIMEE`, `LISTE_ADMIN_EXPORTEE`).
- Tests : `python -m unittest test_listes_administratives`.

### Direction de discipline : Gestion des présences (1re fonctionnalité)

Onglet « Gestion des présences » de l'Espace Discipline (`gestion_presences.py`, page `templates/_etudes_presences.html`, table `PRESENCE_DECISION`, créée automatiquement) :

- **Présence du jour** : pour une date, chaque classe du secondaire et humanitaire avec ses présents, absents, non renseignés, les cours pointés, les décisions et
  ce qui reste **à vérifier** (dont les élèves absents à certains cours seulement). « Ouvrir » une classe montre les **saisies des professeurs** (cours, professeur,
  présents, absents, non pointés, qui a saisi et quand) puis la situation de chaque élève, cours par cours.
- **Confirmer ou corriger** : *Confirmer* valide le statut tiré des pointages ; *Corriger* retient l'autre statut (présent ou absent) avec un **motif obligatoire**, et permet
  de renseigner un jour que personne n'a pointé. « Confirmer les présences à vérifier » confirme toute une classe d'un coup (les élèves non pointés ou déjà décidés sont laissés).
- **Les pointages des professeurs ne sont jamais modifiés** : la décision s'ajoute et donne le « statut retenu ». Une nouvelle décision remplace la précédente, une annulation
  ramène aux pointages ; l'ancienne décision reste dans la base (marquée annulée : qui, quand, pourquoi). Si un professeur change son pointage après une *confirmation*, celle-ci
  n'est plus valable (« à revoir ») ; après une *correction*, la page signale « pointage modifié depuis ».
- **Absences par classe** (période au choix, par défaut de la rentrée à aujourd'hui) et **par élève** (journées d'absence, cours manqués, décisions de la Direction, taux de présence).
- Règle de la journée inchangée : présent seulement s'il est présent à tous les cours pointés ; aucun pointage = « non renseigné » (l'absence n'est jamais devinée).
- On décide pour l'année en cours, un jour de classe, jamais dans le futur, pour un élève actif du secondaire et humanitaire. Les années passées sont en consultation seule.
- Droits sur « Direction de discipline » : Lecture = consulter ; **Ajout = confirmer, corriger** (le Directeur de discipline l'a déjà) ; **Modification = annuler une décision**
  (non accordé par défaut : Gestionnaire d'accès > Autorisations ou Rôles). Tout est inscrit au journal (`GESTION_PRESENCES_CONSULTEE`, `PRESENCE_JOUR_CONFIRMEE`,
  `PRESENCE_JOUR_CORRIGEE`, `PRESENCE_CLASSE_CONFIRMEE`, `PRESENCE_JOUR_ANNULEE`).
- **À savoir** : les autres écrans (Préfecture, bulletins, présence des élèves) continuent de lire les pointages des professeurs ; les décisions de la Direction n'y apparaissent pas.
- Tests : `python -m unittest test_gestion_presences`.


### Direction de discipline : Suivi de la conduite (2e fonctionnalité)

Onglet « Suivi de la conduite » de l'Espace Discipline (`suivi_conduite.py`, page `templates/_etudes_conduite.html`, table `CONDUITE_OBSERVATION`, créée automatiquement) :
- **Vue d'ensemble** : par classe (puis par élève) les observations, comportements inappropriés, incidents, mentions positives et négatives, le **solde de conduite** et les élèves « à suivre ».
- **Observations des professeurs** : les cotes de conduite (E, TB, B, AB, P, M) données par les professeurs dans leur espace, par classe : une cote retenue par période (même règle que le bulletin), ou, pour une période, la cote de chaque professeur cours par cours. Lecture seule.
- **Observations, incidents et mentions** : registre de ce que la Direction a enregistré, filtrable (classe, genre, nature, dates, entrées annulées).
- **Historique d'un élève** : recherche, puis fiche : cotes des professeurs période par période, toutes les entrées de la Direction (annulées comprises), décisions disciplinaires du Préfet (lecture seule), résumé de chaque année ; **le formulaire d'ajout est sur cette fiche**.
- **Ce que la Direction enregistre** : observation disciplinaire (texte libre, positive, négative ou neutre, 0 point), comportement inapproprié, incident, mention positive ou négative. Les trois derniers se choisissent dans le **règlement scolaire** (`config.REGLEMENT_CONDUITE` : libellé, gravité, points) ; la description des faits est obligatoire. Libellé, gravité et points sont copiés dans l'entrée : modifier le règlement ne réécrit pas l'historique.
- **Le règlement fourni est un exemple** (barème et libellés à adapter au règlement d'ordre intérieur du collège, dans `config.py`). Un élève est « à suivre » quand son solde atteint `SEUIL_SOLDE_CONDUITE` (-5) ou qu'il cumule `SEUIL_ENTREES_NEGATIVES` (3) entrées négatives.
- Rien n'est supprimé : une entrée se **annule avec un motif** et reste visible. On n'enregistre que pour l'année en cours, une date non future, un élève actif du secondaire et humanitaire.
- Droits sur « Direction de discipline » : Lecture = consulter ; Ajout = enregistrer (accordé au Directeur de discipline) ; Modification = annuler une entrée (non accordé par défaut : Gestionnaire d'accès).
- Journal : `SUIVI_CONDUITE_CONSULTE`, `CONDUITE_ENTREE_AJOUTEE`, `CONDUITE_ENTREE_ANNULEE`. Tests : `python -m unittest test_suivi_conduite`.

## Frais obligatoires par année d'étude (examen d'État, dissertation, ENAFEP, TENASSOP)

Quatre types de frais sont créés automatiquement (migration 15) et **ne sont dus que par les élèves de leur année d'étude** :

| Code | Frais | Dû uniquement par |
|---|---|---|
| EXETAT | Frais de l'examen d'État | 4ème année des humanités |
| DISSERT | Frais de dissertation | 4ème année des humanités |
| ENAFEP | Frais de l'ENAFEP | 6ème année du primaire |
| TENASSOP | Frais du TENASSOP | 8ème année du secondaire |

- **Montants à fixer** par l'Administrateur : Travaux techniques > Mise à jour des tables > Types de frais (montant et devise, identiques pour toute
  la classe cible) ou Tarifs (montant par classe et par année). Tant qu'aucun montant n'existe, rien n'est dû.
- La colonne « Réservé à » / le champ « Frais obligatoire réservé à une année d'étude » du type de frais pilote la règle (`TYPE_FRAIS.CLASSE_CIBLE`,
  vide = toutes les classes) : l'Administrateur peut s'en servir pour d'autres frais.
- Une classe est reconnue par la section de son niveau et son année d'étude (`donnees.cible_de_classe`) : « 4ème » et « 8ème » du secondaire,
  « 6ème » du primaire (la 4ème du primaire n'est pas concernée).
- Ces frais apparaissent dans la situation financière, les dettes, les listes « élèves en ordre » et se paient comme les autres frais ;
  un paiement pour un élève d'une autre classe est refusé. Tests : `python test_frais_par_annee.py`.

## Règle de paiement : l'inscription est réservée aux candidats

Un **élève déjà inscrit (qui possède un matricule)** ne paie jamais les frais d'inscription : ils ne concernent que les **candidats** qui
souhaitent s'inscrire à l'école (bouton « Inscription » du module Paiement, reçu sans matricule).

- `paiements.enregistrer_paiement` (paiement d'un élève) **refuse** tout type de frais marqué « Frais d'inscription ».
- `donnees.situation` ne compte plus ces frais dans ce que doit un élève : ils n'apparaissent plus dans sa situation financière, ses
  dettes, les listes « élèves en ordre » ni dans l'espace parents, et il n'a plus de bouton « Payer » pour eux.
- `paiements.enregistrer_paiement_inscription` (candidat) refuse aussi un nom identique à celui d'un élève existant (nom + postnom + prénom) :
  le message donne son matricule.
- Les anciens reçus d'inscription déjà enregistrés avec un matricule restent intacts (consultables, duplicata, audit).
- Tests : `python test_inscription_reservee.py` ; les tests d'inscription utilisent désormais des reçus de candidats.

## Ajout après la version 0.57 : fonctionnalités 5 et 6 de la Préfecture

Le sous-menu **Préfecture** passe de 4 à **6 fonctionnalités** (`config.FONCTIONNALITES_PREFECTURE`, logique dans `prefecture.py`, pages
dans `templates/_etudes_prefecture.html`). Les deux nouvelles sont en **consultation seule** et demandent le droit « Lecture » sur
« Préfecture » (le Préfet l'a déjà) ; elles ne concernent que la section « Secondaire et humanitaire » :

- **Préfecture, 5. Consultation de la discipline** : chiffres du jour (présents, absents, présence non pointée), absences répétées,
  liste des élèves (jours d'absence de l'année et des 30 derniers jours, conduite de la dernière période), filtres par classe,
  « absents aujourd'hui » et « absences répétées », fiche d'un élève (absences avec les cours manqués, conduite période par période,
  décisions disciplinaires qui le concernent), décisions disciplinaires du Préfet et rapports de la Direction de discipline.
  **Limite** : les justificatifs d'absence, les retards et les incidents n'ont pas encore de table dans le logiciel (la Direction de
  discipline ne peut pas encore les saisir) : la page l'indique et les affichera quand ils existeront.
- **Préfecture, 6. Consultation des études** : une ligne par classe (titulaire, élèves, cours, moyenne, taux de réussite, réussis,
  échecs, en attente, points manquants), puis le détail d'une classe (résultats d'une période, d'un examen, d'un semestre ou de l'année
  dans l'ordre des réussites ; cours, professeurs et moyenne de la classe ; ce qui manque encore) et le **bulletin à l'écran** de
  chaque élève. Le Préfet ne saisit, ne modifie ni ne calcule aucune note : tout vient de `bulletins.calculer`, relu à chaque appel.
- Journal : `PREFECTURE_DISCIPLINE_CONSULTEE`, `PREFECTURE_DISCIPLINE_ELEVE_CONSULTEE`, `PREFECTURE_ETUDES_CONSULTEES`,
  `PREFECTURE_BULLETIN_CONSULTE`.
- Tests : `python -m unittest test_prefecture_v58 test_prefecture_v57 test_prefecture test_etudes_discipline`.

# GESTSCO - Système de Gestion Scolaire (v0.57)

## Nouveautés de la version 0.57 : écran d'accueil du module et fonctionnalités 3 et 4 de la Préfecture

Module « Gestion des études et discipline » (`web_etudes.py`, logique dans `prefecture.py`, pages `templates/etudes_accueil.html`,
`etudes_sous_menu.html`, `_etudes_prefecture.html`, `_etudes_direction.html`) :

- **Écran d'accueil à cartes** : en ouvrant le module, on voit le **Préfet des études** en haut, puis **Espace Études**, **Espace Discipline**
  et **Secrétariat** en dessous. Chacun clique sur son espace et arrive sur ses fonctionnalités ; un espace dont on n'a pas le droit reste
  grisé (« Accès non autorisé »), sans lien. Un bouton « ← Gestion des études et discipline » ramène à l'accueil. La barre latérale garde
  ses raccourcis directs.
- **Préfecture, 3. Situation financière des élèves** : frais dus, montants payés et dettes de chaque élève (secondaire et humanitaire),
  par année scolaire ; totaux par devise, nombre d'élèves en règle et avec dette ; filtres (classe, avec dette / en règle, nom ou matricule) ;
  détail par frais pour un élève, avec ses dettes d'autres années. **Consultation seule** : aucun encaissement, aucun reçu, aucune
  modification. Il faut le droit « Lecture » sur « Préfecture » **et** sur « Paiement des frais » ; sans ce dernier, la page l'indique.
- **Préfecture, 4. Décisions et rapports** : le Préfet enregistre ses décisions (date, catégorie, objet, détail, année, élève concerné
  facultatif ; droit « Ajout ») et peut les **annuler avec un motif** (droit « Modification ») : une décision n'est jamais supprimée, elle reste
  dans la liste, marquée « Annulée ». Il consulte aussi les **rapports des responsables** (lecture seule), filtrables par direction et année.
- **Rapport au Préfet** (Espace Études et Espace Discipline) : la Directrice des études et le Directeur de discipline rédigent un rapport
  (droit « Ajout » sur leur sous-menu) et retrouvent leurs rapports envoyés ; chaque direction ne voit que les siens.
- Nouvelles tables vides : `DECISION_PREFET` et `RAPPORT_RESPONSABLE` (créées automatiquement ; structure n° 13).
- **Droits par défaut** (migration 13) : le Préfet reçoit « Ajout » et « Modification » sur « Préfecture » ; la Directrice des études et le
  Directeur de discipline reçoivent « Ajout » sur leur sous-menu. Les comptes existants les reçoivent une seule fois ; l'Administrateur
  peut les retirer (Gestionnaire d'accès) et ce retrait n'est jamais rétabli.
- Journal : `PREFECTURE_FINANCES_CONSULTEES`, `PREFECTURE_FINANCE_ELEVE_CONSULTEE`, `PREFECTURE_DECISION_ENREGISTREE`,
  `PREFECTURE_DECISION_ANNULEE`, `PREFECTURE_RAPPORTS_CONSULTES`, `RAPPORT_ENVOYE_AU_PREFET`.
- Tests : `python -m unittest test_prefecture_v57 test_prefecture test_etudes_discipline`.
- Limite actuelle : ces fonctionnalités ne sont pas encore dans le logiciel Windows. Les espaces Secrétariat (et les autres fonctionnalités
  des directions) viendront ensuite.

## Nouveautés de la version 0.56 : sous-menu Préfecture

Module « Gestion des études et discipline » (`web_etudes.py`, logique dans `prefecture.py`, pages `templates/etudes_sous_menu.html` et
`templates/_etudes_prefecture.html`) :

- Le sous-menu « Dossier élève » s'appelle désormais **Secrétariat** (le droit technique `dossier_eleve` ne change pas : rien à migrer).
- Le module ne concerne que la section **Secondaire et humanitaire** : un compte limité au Primaire ne le voit pas, et aucune classe ni
  aucun élève du primaire n'y apparaît.
- **Préfecture** (droit « Lecture » sur « Préfecture », Préfet par défaut) :
  1. *Tableau de bord* : effectifs, présence du jour, alertes (classe sans titulaire, sans cours, cours sans professeur, présence non pointée,
     absences répétées), candidatures en attente, situation par classe.
  2. *Suivi des élèves* : recherche par nom, matricule ou classe ; profil, dossier scolaire par année, résultats, historique des absences.
  Lecture seule, sans aucune donnée financière ; l'ouverture du tableau et la consultation d'un dossier sont inscrites au journal.
- Réglage : `SEUIL_ABSENCES_REPETEES` dans `config.py` (3 jours d'absence sur 30 jours par défaut).
- Tests : `python -m unittest test_prefecture`.
- Limite actuelle : les fonctionnalités de la Préfecture ne sont pas encore dans le logiciel Windows (les trois autres sous-menus non plus).

## Nouveautés de la version 0.41 : le module Inscription en ligne

Le module « Inscription » est disponible dans la version web (`web_inscription.py`, pages `templates/inscription_*.html`), avec la même logique métier et les mêmes droits que dans le logiciel Windows (`inscription.py`) ; les trois onglets sont les mêmes :
- **1 Formulaire d'inscription** (droit « Ajout ») : N° du reçu des frais d'inscription, avec un bouton « Vérifier le paiement » (la saisie est conservée), identité, parcours scolaire, tuteur, classe souhaitée. Sans reçu valide (inexistant, annulé, d'un autre type de frais, déjà utilisé), rien n'est enregistré. Le candidat est mis sur la liste d'attente et sa fiche s'imprime en PDF.
- **2 Liste d'attente** (droit « Lecture ») : par classe et par ordre d'arrivée, recherche par nom, N° de candidat ou reçu, fiche PDF.
- **3 Validation et affectation** (droit « Modification ») : note du test d'admission (>= seuil : dossier validé ; sinon candidature refusée, définitivement), puis affectation à une classe : le candidat devient élève (matricule et code QR) ; avis d'admission en PDF.
- Règles propres au web : le résultat du test et l'affectation passent par une page de confirmation ; un double clic ne crée ni deux candidatures, ni deux élèves (même compte, 60 secondes) ; les sections de l'école et les droits sont revérifiés à chaque requête.
- Tests : `python -m unittest test_inscription_web`.

## Nouveautés de la version 0.40 : le module Encaissement en ligne

Le module « Encaissement des fonds perçus » est disponible dans la version web (`web_encaissement.py`), avec la même logique métier et les mêmes droits que dans le logiciel Windows (`encaissements.py`) :
- **Enregistrement** (droit « Ajout ») : percepteur, date, devise, montant encaissé, montant versé ; l'écart (encaissé - versé) est calculé par le système et affiché pendant la saisie. Une page de confirmation précède l'enregistrement.
- **Rapport global** (droit « Lecture ») : paiements de tous les percepteurs par type de frais, puis encaissements, versements et écarts de la date choisie ; impression PDF.
- Un double clic ne crée pas deux encaissements : la même saisie, faite par le même compte dans les 60 secondes, renvoie vers l'encaissement déjà enregistré.
- Comme dans le logiciel Windows, les onglets sont les mêmes (Enregistrement, Rapport global) ; la modification et la suppression d'un encaissement (droits existants) ne sont pas encore proposées à l'écran, ni sur Windows ni en ligne.
- Tests : `python -m unittest test_encaissement_web`.

## Nouveautés de la version 0.39 : le module Paiement en ligne, et un reçu « ticket de caisse »

**Module Paiement des frais, version web** (`web_paiement.py`, pages `templates/paiement_*.html`) : les quatre onglets du logiciel Windows sont disponibles dans le navigateur, avec la même logique métier (`paiements.py`, droits, sections de l'école, journal) :
- **Élève : situation et paiement** : recherche par nom ou matricule, situation de l'année (dû, payé, reste, statut, mode de paiement), dettes des années précédentes. Pour un compte Percepteur, chaque frais non soldé a sa ligne « Payer » (montant proposé = prochaine tranche, modifiable), puis une **page de confirmation** avant l'enregistrement.
- **Inscription d'un candidat** : paiement des frais d'inscription d'une personne sans matricule (le montant vient toujours du tarif, jamais du formulaire).
- **Duplicata du reçu** et **Rapport journalier de caisse** (affichage et PDF).
- Règles propres au web : un double clic ne crée pas deux reçus (le formulaire mémorise ce qui était déjà payé) ; le **reçu original** n'est réimprimable que par le percepteur qui l'a établi, pendant 30 minutes (`DELAI_ORIGINAL_MIN` dans `web_paiement.py`), ensuite seul le **duplicata** est possible ; un compte limité au primaire ou au secondaire ne voit que les élèves et les reçus de sa section.
- Les dates et heures des reçus et des rapports suivent le fuseau de l'école (Africa/Kinshasa, variable `GESTISC_TZ`) et non celui du serveur de l'hébergeur.

**Nouvelle forme du reçu** (`recu_pdf.py`) : le reçu est un **ticket de caisse de 80 mm** (papier des imprimantes thermiques), à hauteur variable, en police à chasse fixe : logo et nom de l'école, « REÇU DE PAIEMENT », numéro, date et **heure**, percepteur, élève (nom, matricule, classe, option, année), ligne « DÉSIGNATION / MONTANT », **TOTAL** en gras, **code-barres** (Code 39) du numéro de reçu, « MERCI ! ». Le duplicata porte « *** DUPLICATA *** » et la date d'impression. Le ticket n'a plus de ligne « Signature Percepteur » : le nom et le numéro du percepteur y figurent. Les autres documents (rapports, cartes, bulletins...) gardent leur forme.

Fichiers : `recu_pdf.py`, `paiements.py` (heure du reçu ; règles d'onglets partagées avec le web), `ecrans_paiement.py` (reprend ces règles de `paiements.py`), `web_paiement.py`, `app_web.py`, `templates/`, `config.py` ; tests : `test_paiement_web.py` (nouveau), `test_paiements.py`.

## Nouveautés de la version 0.38 : bulletin du primaire sur le modèle officiel, et version web (début)

**Bulletin du primaire** (`bulletin_primaire_pdf.py`) : pour une classe du primaire, le bulletin reproduit la feuille officielle : drapeau et armoiries de la RDC, « République Démocratique du Congo / Ministère de l'Enseignement primaire, secondaire et technique » (sans logo ni nom de l'école dans l'en-tête), identité (N° ID, Province, Ville, Commune, École, Code, Élève, Sexe, Naissance, Classe, N° Perm.), titre selon le degré (élémentaire 1-2, moyen 3-4, terminal 5-6), tableau des 3 trimestres (1ªP à 6ªP, examen, trimestre, total), 5 domaines de branches, sous-totaux, maxima généraux, pourcentage, place, nombre d'élèves, application, conduite, signatures, décision (passe / double), chef d'établissement.
- **Les cours de la classe doivent porter le nom des branches du modèle** (ex. « Orthographe », « Géographie », « Education civique et morale »). Les abréviations et accents sont tolérés. `cours_du_modele()` donne la liste. Une branche sans cours reste vide. « Lecture » : celui des langues congolaises doit s'appeler « Lecture (langues congolaises) ».
- Les maxima imprimés sont ceux du modèle (période = maximum de la branche, examen = 2 x, trimestre = 4 x, total = 12 x) : saisissez les points avec ces maxima.
- Province, ville, commune et code de l'école : `config.py` (`PROVINCE_BULLETIN`, `VILLE_BULLETIN`, `COMMUNE_BULLETIN`, `CODE_ECOLE_BULLETIN`) ; sinon les lignes restent à remplir à la main. « Application » et les signatures se complètent à la main.
- Le secondaire et les humanités gardent leur bulletin.

**Correction du bulletin du primaire (mise en page recopiée sur le bulletin officiel)** : les trois lignes de l'en-tête sont centrées sur l'axe de la feuille (même corps), la feuille a son cadre extérieur et l'en-tête, la rangée N° ID, l'identité et le titre sont encadrés comme sur l'original ; cases : 27 (N° ID), 9 (Code), 13 (N° Perm.) ; « ANNEE SCOLAIRE 20__ 20__ » ; colonnes aux largeurs du modèle (branches étroite, « PTS OBT. » larges) ; lignes de 10 pt ; décision, signature et notes aux positions du modèle. Test ajouté : `test_mise_en_page_conforme_au_modele`.


**Version web (début)** : voir `DEPLOIEMENT.md` et `FEUILLE_DE_ROUTE.md` (`app_web.py`, `Lancer_Web.bat`).

## Nouveautés de la version 0.37 : le primaire a 3 trimestres et 6 périodes

Le calendrier de l'année est maintenant **propre à chaque section** : secondaire et humanitaire = **2 semestres de 2 périodes** (4 périodes) ; primaire = **3 trimestres de 2 périodes** (6 périodes).

**À faire après la mise à jour (Direction des études > Années scolaires)** : les semestres déjà créés restent ceux du secondaire et humanitaire. Pour le primaire : choisissez l'année, mettez « Calendrier de la section » sur **Primaire**, puis **Structure standard** (3 trimestres de 2 périodes, dates partagées à parts égales) ou ajoutez les trimestres à la main, et corrigez les dates si besoin.

- **Écran du calendrier** : un choix « Calendrier de la section » ; les mots changent (trimestre / semestre) ; une section peut avoir au plus 3 trimestres (primaire) ou 2 semestres (secondaire). Les dates des deux sections peuvent se chevaucher.
- **Saisie des points** : un professeur ou un titulaire du primaire ne saisit que dans les périodes de son calendrier (jamais dans celles du secondaire, et inversement). Il voit « 1er trimestre - 1ère période », etc.
- **Résultats** : au primaire, un trimestre = ses 2 périodes (+ son examen) et l'année = les 6 périodes. Le rang, le pourcentage, la mention et la liste des réussites et échecs se calculent sur ce calendrier.
- **Page web du titulaire** : la liste « Résultats de » propose les périodes, trimestres et l'année de la classe choisie.
- **À confirmer** : j'ai gardé, pour chaque trimestre du primaire, un « Examen » comme pour chaque semestre du secondaire. Si le primaire n'a pas d'examen par trimestre, dites-le et je le retire pour cette section.

Fichiers modifiés : `cours.py` et `database.py` (colonne `SEMESTRE_SCO.SECTION`, calendrier par section), `notes.py`, `bulletins.py`, `page_professeur.py`, `ecrans_cours.py`, `config.py` ; tests : `test_sections.py` (trimestres), `test_audit.py`.

## Nouveautés de la version 0.36 : sections de l'école (primaire, et secondaire et humanitaire)

Un seul logiciel, une seule base, un seul jeu de matricules ; mais deux **sections**. Chaque compte ne voit que les sections qui lui sont ouvertes.

**À faire après la mise à jour (Administrateur)** :
1. *Travaux techniques > Mise à jour des tables > Niveaux* : chaque niveau a maintenant une **Section** (Primaire, ou Secondaire et humanitaire). La mise à jour classe d'office en « Primaire » les niveaux dont le code ou la désignation commence par « prim », tous les autres en « Secondaire et humanitaire » : **vérifiez-les**. Un nouveau niveau demande sa section.
2. *Gestionnaire d'accès > Autorisations* : cochez, pour chaque compte, les sections qu'il peut voir (colonne « Sections » dans la liste). Les comptes existants gardent **toutes** les sections tant que vous ne les limitez pas ; l'Administrateur voit toujours tout.

**Ce qui change selon la section** :
- **Paiement des frais** : un percepteur ne cherche, n'encaisse et ne voit dans son rapport journalier que les élèves, candidats et reçus de ses sections.
- **Inscription** : classes proposées, candidatures, liste d'attente, validation et affectation limitées à ses sections.
- **Contrôle numérique** : classes et élèves limités à ses sections.
- **Carte** : **pas de carte au primaire** (fiche, photo et impression refusées, même à l'Administrateur) ; le module « Carte » n'apparaît pas pour un compte limité au primaire.
- **Primaire : le titulaire est l'unique enseignant de sa classe.** Quand on désigne le titulaire d'une classe primaire (Direction des études > Enseignants et classes), **tous les cours de la classe lui sont attribués automatiquement** (et les cours ouverts ensuite aussi) ; changer de titulaire change l'enseignant, retirer le titulaire libère les cours. On ne peut pas attribuer un autre professeur à un cours du primaire. Il n'y a personne à autoriser : **toutes les périodes et tous les examens sont ouverts à sa saisie**, et son espace (page web) montre « Ma classe » et « Points » comme à tout titulaire qui enseigne.
- Le secondaire et les humanités fonctionnent comme avant.

**Pas encore séparé dans cette version** : Encaissement des fonds perçus, Gestion du personnel (une seule liste d'agents), tableau de bord, audit financier et listes de Gestion scolaire. Bulletins : à faire plus tard, avec les règles du primaire.

Fichiers : nouveau `sections.py` ; modifiés `database.py` (NIVEAU.SECTION, table SECTION_UTILISATEUR), `migrations.py` (migration 11), `paiements.py`, `donnees.py`, `inscription.py`, `carte.py`, `controle.py`, `modules.py`, `cours.py`, `notes.py`, `bulletins.py`, `referentiels.py`, `ecrans_acces.py`, `ecrans_paiement.py`, `ecrans_inscription.py`, `ecrans_controle.py`, `page_professeur.py`, `audit.py`, `audit_recherche.py`, `config.py` ; tests : nouveau `test_sections.py`, adaptés `test_admission.py`, `test_referentiels.py`.

## Nouveautés de la version 0.35 : l'espace du titulaire (liste des élèves, cotes, réussites et échecs)

**Problème corrigé** : un titulaire qui n'enseigne pas arrivait sur les onglets « Points » et « Présence », qui demandent de choisir un cours et une classe et restaient vides. Il ne voit plus ces onglets.

**Qui voit quoi (page web des professeurs)** :
- **Titulaire qui n'enseigne pas** : il arrive directement sur son espace (« GESTSCO - Espace du titulaire »). Pas de « Points », pas de « Présence ».
- **Titulaire qui enseigne aussi** (dans sa classe ou dans d'autres) : trois onglets, **Ma classe**, **Points**, **Présence**. Ouvert sur « Ma classe » ; « Points » et « Présence » ne concernent que les cours dont il est le professeur.
- **Professeur non titulaire** : comme avant (« Points » et « Présence »).

**Espace « Ma classe »** :
- **Élèves de la classe** : la liste des élèves de la classe dont il est titulaire (affichée même si aucun point n'est saisi, ou si les semestres et périodes ne sont pas encore créés). Un clic sur un élève (ou « Voir les cotes ») ouvre **ses cotes dans tous les cours de la classe**, par période, examen, semestre et année, avec total, pourcentage, rang, résultat et conduite ; flèches pour passer à l'élève précédent / suivant. Lecture seule.
- **Réussites et échecs** : les réussites d'abord (du meilleur au plus faible), puis les échecs, puis les élèves « en attente ». Bouton **« Imprimer la liste des réussites et des échecs (PDF) »** (même ordre). La période, le semestre ou l'année affichée au départ est la plus récente dont tous les élèves ont un résultat.
- **Semestres et périodes ouverts à la saisie des professeurs** : toujours visible sous les sélecteurs, un bloc par semestre (ses 2 périodes et son examen) avec un bouton Ouverte / Fermée pour chacun.
- **Bulletins** : pas touchés dans cette version (les boutons « Bulletins de la classe » et « PDF » par élève sont retirés de l'écran en attendant ; le calcul et les PDF existent toujours dans `bulletins.py` / `bulletins_pdf.py`). « Proclamation de l'année (PDF) » reste disponible.

Fichiers modifiés : `config.py`, `bulletins.py`, `bulletins_pdf.py`, `serveur_notes.py`, `page_professeur.py`, `test_bulletins.py`. Nouvelle demande du serveur : `bulletins/eleve` (cotes d'un élève de sa classe) ; `bulletins/resultats` accepte `ordre` (`reussite` ou `alpha`) ; `bulletins/acces` indique aussi si le compte enseigne.

## Nouveautés de la version 0.34 : rôles du titulaire, du professeur et de la discipline

**Professeur (page web, onglet « Points »)** : il ne saisit que les **points** et la **conduite** de la période (ou de l'examen du semestre) que le **titulaire de la classe** lui a autorisée. Son tableau ne montre que : *N°, nom de l'élève, la cote de la période concernée, la conduite*. Plus de colonnes INT 1 / INT 2 (anciennes évaluations), ni TOT, ni **pourcentage**, ni autres périodes, ni relevé de l'année, ni bouton « Maximum » (maximums fixes : 20 par période, 40 par examen). Les anciens points INT/DEV/IG ne sont pas effacés : ils restent en base et comptent dans les bulletins du titulaire.

**Titulaire de la classe (onglet « Ma classe »)** : il **autorise** (ouvre / ferme) chaque période et chaque examen du semestre pour les professeurs de **sa** classe ; tant que rien n'est ouvert, aucun professeur ne peut saisir. Il **ne modifie jamais** les cotes saisies par les professeurs et **ne gère pas les présences** : il gère seulement les cotes de sa classe (résultats, totaux, pourcentages, rangs, bulletins PDF). Fermer une période n'efface aucun point. Chaque ouverture / fermeture est inscrite au journal (`SAISIE_AUTORISEE`, `SAISIE_FERMEE`). L'ancienne règle « la saisie s'ouvre 7 jours avant la fin de la période » (`JOURS_SAISIE_AVANT_FIN`) n'existe plus : c'est le titulaire qui décide.

**Présence des élèves** : le professeur pointe seulement **ses heures de cours** ; il ne voit plus la colonne « Journée » (pointage des collègues), et le titulaire n'a aucune vue sur les présences. Deux postes les consultent, en **lecture seule**, pour **toutes les classes** : le nouveau poste **Directeur de discipline** et la **Directrice des études** (droit « Lecture » sur le nouveau module **« Présence des élèves »**, accordé par défaut à ces deux postes). Un compte qui n'a que ce droit arrive directement dans ce module et ne voit ni les cours, ni les enseignants, ni les points.

Base de données : nouvelle table `AUTORISATION_SAISIE` (créée toute seule) ; structure n° 10 (droits de base des deux postes, comptes existants de la Directrice des études). Compte d'essai ajouté : `essai.discipline`. Fichiers modifiés : `config.py`, `database.py`, `migrations.py`, `notes.py`, `bulletins.py`, `presence_eleves.py`, `serveur_notes.py`, `page_professeur.py`, `modules.py`, `ecrans.py`, `ecrans_gestion.py`, `ecrans_cours.py`, `essai.py`, `audit.py`, `audit_recherche.py` et les tests.

## Nouveautés de la version 0.33 : Calcul automatique et bulletins

**Qui ?** Uniquement le **professeur titulaire de la classe**. Dans la page web des professeurs, il voit un onglet supplémentaire **« Bulletins »** ; les autres professeurs ne le voient pas (l'onglet n'est même pas créé pour eux) et le serveur refuse toute demande venant d'un compte qui n'est pas titulaire de la classe demandée. Ni l'Administrateur ni un autre poste n'y accèdent par cette page.
**Désigner le titulaire** : Direction des études > Enseignants et classes > choisir l'agent, choisir la classe en bas, **« Désigner l'agent choisi titulaire de la classe ci-dessus »** (droit *Modification* du module Gestion scolaire). Un titulaire par classe et par année ; **« Retirer le titulaire »** annule. Chaque désignation est inscrite au journal.

**Ce que fait le titulaire (onglet Bulletins)** : il choisit l'année, sa classe et la période, le semestre ou l'année :
- le **tableau des résultats** de la classe, classé : points, pourcentage, rang, mention, résultat, conduite (pour une période) ;
- la liste **« À vérifier avant d'imprimer »** : cours sans professeur, sans évaluation, élèves sans point, périodes incomplètes ;
- **Bulletins de la classe (PDF)** (un bulletin par élève) ou le bulletin d'un seul élève (bouton PDF de sa ligne) ; **Liste des résultats (PDF)** ; **Proclamation de l'année (PDF)** (admis, ajournés, en attente, statistiques, signatures). Le PDF s'ouvre dans le navigateur : imprimer ou enregistrer depuis son lecteur PDF.
Chaque document généré est inscrit au journal (Traçabilité et audit).

**Règles de calcul** (réglables dans `config.py` : `SEUIL_REUSSITE`, `MENTIONS`, `NOTE_MANQUANTE`) :
- Cours et période : total = somme des points de l'élève ; maximum = somme des maxima des évaluations notées de l'élève ; pourcentage = total / maximum. Une évaluation sans point (absent, pas corrigée) est ignorée (`NOTE_MANQUANTE = "IGNOREE"`, comme la fiche de saisie) ou comptée 0 (`"ZERO"`).
- Période = somme des cours ; semestre = somme de ses périodes ; année = somme de toutes les périodes (pourcentage pondéré par les points).
- Pourcentages arrondis à 0,1 : ce qui est affiché fait foi. Rang : 1 = meilleur pourcentage, ex æquo au même rang (1, 2, 2, 4).
- Réussite si pourcentage >= 50 % (**admis(e)** / **ajourné(e)** pour l'année). Mentions : Grande distinction >= 80, Distinction >= 70, Satisfaction >= 60, Passable >= 50. Si les points d'une période manquent, le résultat reste **« EN ATTENTE »** : il n'est jamais deviné.
- Conduite d'une période : la cote la plus fréquente parmi les cours de la classe ; à égalité, la plus faible.

**Le modèle du bulletin** est entièrement dans `bulletins_pdf.py`, fonction `_page_bulletin()` : c'est la seule chose à changer pour reproduire le modèle officiel ; le calcul n'est pas touché.
Nouvelle table (créée toute seule) : `TITULAIRE_CLASSE`. Nouveaux fichiers : `bulletins.py`, `bulletins_pdf.py`, `test_bulletins.py`. Modifiés : `serveur_notes.py`, `page_professeur.py`, `ecrans_cours.py`, `database.py`, `config.py`.

## Nouveautés de la version 0.32 : Présence des élèves aux cours

**Côté professeur (même page web que la saisie des points, onglet « Présence »)** : il choisit l'année, la classe, le cours et la date (aujourd'hui par défaut, jamais dans le futur) ; la liste des élèves s'affiche et il touche **Présent** ou **Absent** pour chacun (toucher de nouveau retire le pointage). « Tous présents » pointe d'un coup ceux qui ne sont pas encore pointés. Le bouton « Présences du cours » donne, par classe, l'historique de son cours : élèves × jours (P / A), nombre de présences et d'absences, taux.

**Règle de la journée** : un élève est considéré **présent pour la journée seulement s'il est présent à tous les cours pointés ce jour-là** par les professeurs de sa classe ; absent à un seul cours, il est absent pour la journée (les cours manqués sont indiqués).

**Direction de discipline et direction des études** : Direction des études > « 2 Présence des élèves » : pour un jour, la présence de **toutes les classes** (présents, absents, non renseignés, cours pointés), la liste des élèves d'une classe avec le détail cours par cours, et un récapitulatif sur une période. Lecture seule. Cet écran s'ouvre avec le droit **Lecture sur « Gestion scolaire »** : pour le Directeur de discipline, l'Administrateur crée un rôle « Directeur de discipline » (Gestionnaire d'accès > Rôles) avec ce droit, puis un compte ; la Directrice des études a besoin du même droit.
Nouvelle table (créée automatiquement) : `PRESENCE_ELEVE`. Nouveaux fichiers : `presence_eleves.py`, `test_presence_eleves.py`.

## Changement : saisie des points par période et par examen (remplace INT / DEV / IG / EXA libres)

Le professeur ne peut plus ajouter d'interrogations, de devoirs ni d'examens à volonté. Il saisit **uniquement** :
- les **points de chaque période** : un seul point par élève, à la **fin de la période** (la saisie s'ouvre `JOURS_SAISIE_AVANT_FIN` = 7 jours avant la fin de la période, réglable dans `config.py` ; avant cette date, la page affiche la date d'ouverture et refuse l'enregistrement) ;
- les **points de l'examen** de chaque semestre (même règle, selon la fin de la dernière période du semestre) ;
- la **conduite** de la période (même ouverture).
Le **total du semestre** = période 1 + période 2 + examen est **calculé tout seul** (`EXAMEN_DANS_SEMESTRE = False` dans `config.py` pour ne compter que les deux périodes). Maximums habituels : 20 par période, 40 pour l'examen (`MAXIMUM_PERIODE`, `MAXIMUM_EXAMEN`) ; le professeur peut changer le maximum de son cours (bouton « Maximum »).
La page « Points » montre le semestre (P1, P2, EX, TOT) ; seule la colonne choisie dans « Saisir » se remplit. Le relevé de l'année montre chaque période, l'examen et le total de chaque semestre.
Bulletins : un bulletin de semestre affiche P1, P2, Examen et Semestre ; l'examen n'est jamais compté dans une période.
Base de données : nouveau type d'évaluation `PER` (structure n° 9, migration automatique avec sauvegarde de sécurité). Les anciennes évaluations INT/DEV/IG restent en lecture seule et continuent d'être comptées. Fichiers modifiés : `notes.py`, `bulletins.py`, `bulletins_pdf.py`, `serveur_notes.py`, `page_professeur.py`, `database.py`, `migrations.py`, `config.py`, `audit.py` et les tests `test_notes.py`, `test_serveur_notes.py`, `test_bulletins.py`.

## Nouveautés de la version 0.31 : Saisie des points par les professeurs (page web)

Le professeur se connecte depuis un **ordinateur, une tablette ou un téléphone** avec le navigateur, sur le Wi-Fi de l'école. Il ne voit que **ses cours et les élèves de ces classes**.
- Il choisit l'année, la classe, le cours, le semestre et la période : la liste des élèves s'affiche, avec à droite les zones de points.
- Boutons pour ajouter une **interrogation (INT)**, un **devoir (DEV)**, une **interrogation générale (IG)** ou un **examen (EXA)** ; TOT = total, CDT = conduite (liste déroulante en fin de ligne : E, TB, B, AB, P, M). La légende est affichée en bas de la page.
- Le professeur **consulte** (relevé de l'année) mais **n'imprime pas** : l'impression se fera dans une autre fonctionnalité. Chaque point enregistré est inscrit au journal.

Mise en route (Administrateur) : Direction des études > Enseignants et classes > choisir l'agent > « Créer le compte de l'agent choisi » (identifiant + mot de passe provisoire à remettre au professeur, à changer à la première connexion), puis « Démarrer le serveur » : l'adresse à taper sur le téléphone ou la tablette s'affiche. On peut aussi lancer `Lancer_Professeurs.bat`. Le trafic n'est pas chiffré : à utiliser sur le réseau de l'école, pas sur Internet. Pare-feu Windows : autoriser Python quand il le demande.
Nouvelles tables (créées automatiquement) : `COMPTE_PROFESSEUR`, `EVALUATION`, `NOTE`, `CONDUITE`. Nouveaux fichiers : `notes.py`, `notes_pdf.py`, `serveur_notes.py`, `page_professeur.py`, `Lancer_Professeurs.bat`, `test_notes.py`, `test_serveur_notes.py`, `test_presence_eleves.py`.

## Nouveautés de la version 0.30 : Gestion des cours et des enseignants (module Gestion scolaire)

Première fonctionnalité du module « Gestion scolaire », en 4 onglets :
1. **Années et périodes** : créer une année scolaire (ex. 2026-2027) avec ses dates, choisir l'année en cours, définir les semestres et les périodes : 2 semestres par année, 2 périodes par semestre, soit 4 périodes (limite appliquée ; bouton « Structure standard » : 2 semestres de 2 périodes). Les dates ne peuvent ni se chevaucher ni sortir de leur parent.
2. **Cours** : catalogue des cours par niveau, option (humanités) et année d'étude (les deux derniers sont facultatifs), avec les heures par semaine. Un cours ouvert dans des classes se désactive mais ne se supprime pas.
3. **Programme des classes** : pour une année et une classe, ouvrir les cours applicables, régler les heures, attribuer un professeur (un ou plusieurs cours à la fois) ou le retirer.
4. **Enseignants et classes** : charge de chaque agent (classes, cours, heures), liste de ses classes, association d'un professeur à une classe (il reçoit les cours encore sans professeur), détachement.

Droits (module « Gestion scolaire ») : Lecture = consulter ; Ajout = créer, ouvrir des cours, attribuer un professeur à un cours libre ; Modification = changer/retirer un professeur, heures, dates ; Suppression = supprimer / retirer un cours d'une classe. Toutes les actions sont inscrites au journal d'audit.
Nouvelles tables (créées toutes seules au démarrage, rien n'est perdu) : `ANNEE_CALENDRIER`, `SEMESTRE_SCO`, `PERIODE_SCO`, `COURS`, `COURS_CLASSE`. Nouveaux fichiers : `cours.py`, `ecrans_cours.py`, `test_cours.py` ; `ecrans_gestion.py` réécrit.

## Nouveautés de la version 0.29 : Présence et absence (Gestion du personnel)
Troisième fonctionnalité du module **Gestion du personnel**, avec trois onglets :
- **Pointage du jour** : la liste des agents pour un jour (flèches ◄ ► pour changer de jour, filtre par fonction). On choisit un ou plusieurs agents (Ctrl ou Maj + clic) puis **Présent**, **En retard** (écrire l'heure d'arrivée : les minutes de retard se calculent seules par rapport à l'heure d'ouverture) ou **Absent** (motif facultatif). **Tous présents** marque d'un clic les agents encore « non renseignés ». Un pointage se corrige en le refaisant ; **Effacer le pointage** le retire.
- **Permissions et congés** : pour l'agent choisi, la liste de ses autorisations et le total de jours de l'année ; on enregistre une permission ou un congé (nature, dates de début et de fin, motif) ou on l'annule (motif obligatoire). Les jours couverts ne sont jamais des absences ; des absences déjà marquées sur la période sont régularisées.
- **États récapitulatifs** : par période (cette semaine, ce mois, mois précédent ou dates libres), pour tout le personnel, une fonction ou un service. Par agent : jours de travail, présents, retards (et minutes), absences, jours de permission et de congé, jours non renseignés, taux de présence ; en dessous, le détail des retards et absences. **Imprimer l'état** (PDF, avec ou sans détail).
Règles : un pointage par agent et par jour ; jours de travail = lundi à vendredi (`config.py`, `JOURS_DE_TRAVAIL`) sauf les **jours non travaillés** saisis par l'école (bouton « Jours non travaillés... » du pointage : fêtes, vacances) ; jamais de pointage dans le futur ni avant l'engagement ; un jour sans pointage ni autorisation reste « non renseigné » (l'absence n'est jamais devinée) ; taux de présence = (présents + retards) / (jours de travail - permissions - congés). **Heure d'ouverture** : `HEURE_DEBUT_SERVICE` dans `config.py` (07:30 au départ).
Droits (module Gestion du personnel) : Lecture = consulter ; Ajout = pointer, accorder une autorisation, ajouter un jour non travaillé ; Modification = corriger un pointage, annuler une autorisation ; Suppression = effacer un pointage, retirer un jour non travaillé. Tout est inscrit au journal (Traçabilité et audit).
**Pointeur biométrique (plus tard)** : chaque pointage garde sa source (`MANUEL` aujourd'hui, `BIOMETRIQUE` prévu) ; le futur pointeur utilisera `presences.enregistrer_pointage(..., source="BIOMETRIQUE")` avec l'heure d'arrivée.
Nouvelles tables (créées toutes seules au démarrage, rien n'est perdu) : `PRESENCE`, `AUTORISATION_ABSENCE`, `JOUR_FERME`. Nouveaux fichiers : `presences.py`, `presences_pdf.py`, `ecrans_presences.py`, `test_presences.py`, `test_cours.py`, `test_notes.py`, `test_serveur_notes.py`, `test_presence_eleves.py`.

## Nouveautés de la version 0.28
- **Un seul écran** après la connexion : à gauche la barre latérale bleu marine (logo GESTSCO, *Tableau de bord*, *Menu principal* avec les modules ouverts au compte), à droite le **tableau de bord**.
- **Chevrons** : celui du haut de la barre latérale (et celui de la barre du haut) la replie en une colonne de pictogrammes ; celui de « Menu principal » plie la liste des modules ; celui du titre « Tableau de bord » plie tout le tableau ; chaque graphique a le sien.
- **Graphiques** : camembert (élèves en règle / pas en règle), courbe (évolution des inscriptions), barres (filles et garçons par année scolaire). Seulement des comptes : aucun nom, aucun montant.
- Nouveau nom et nouveau logo (engrenage bleu et histogramme) ; couleurs du modèle de tableau de bord.

## Lancer
1. Python 3.10 ou plus récent installé (python.org).
2. Double-clic sur **`Lancer.bat`** (ne pas ouvrir `main.py` : Windows l'ouvre dans un éditeur).
   Aucune bibliothèque externe n'est nécessaire, **sauf pour la caméra** (module Carte) : `Lancer.bat` installe
   OpenCV tout seul au premier lancement (internet requis, une seule fois). Sinon, à la main : `pip install opencv-python`.
3. **La base de données est créée automatiquement** au premier lancement (fichier `college.db` dans
   `%LOCALAPPDATA%\GESTSCO\`). Une base d'une version précédente est mise à jour toute seule,
   après une sauvegarde de sécurité automatique ; aucune donnée n'est perdue.
4. Premier lancement : l'écran « Premier démarrage » demande de créer le compte **Administrateur**.

## Les modules du menu principal
- Première ligne : **Paiement des frais**, **Encaissement des fonds perçus**, **Contrôle numérique**
- Deuxième ligne : **Carte**, **Inscription**, **Travaux techniques**, **Gestionnaire d'accès** (Administrateur)
- **Gestion scolaire** (module encore vide : ses fonctionnalités viendront ensuite) et **Gestion du personnel** (*Dossier personnel* et *Fonctions et affectations*, voir « Nouveautés de la version 0.27 ») ; ouverts à l'Administrateur ou à un compte qui a le droit Lecture
- Dernière ligne : **Traçabilité et audit** (Administrateur, ou compte à qui il accorde la Lecture)

Un module n'apparaît que si le compte y a droit. Si un module manque, demandez à l'Administrateur.

## Paiement des frais scolaires
Les 4 onglets sont toujours visibles :
1. **Consultation de la situation** - ouverte à tout compte ayant accès au module
2. **Enregistrement du paiement** (nouveau en 0.24 : boutons Enregistrer / Annuler toujours visibles, bouton **Inscription**, voir plus bas) - le SEUL soumis à vérification : poste Percepteur ET droit Ajout (sinon l'onglet est
   marqué « (réservé) » et un clic explique pourquoi)
3. **Duplicata du reçu** - ouvert à tous (reçu annulé : non imprimable)
4. **Rapport journalier de caisse** - ouvert à tous : un percepteur obtient ses propres encaissements, les autres
   choisissent un percepteur ou « Tous les percepteurs »

## Travaux techniques (Administrateur)
0. Cinq onglets : Mise à jour des tables, Sauvegarde, Restauration, Réinitialisation, **Authentification et mots de passe** (nouveau en 0.15, voir plus bas).
1. **Mise à jour des tables** : on choisit une table à gauche, on la met à jour à droite :
   *Ajouter, Modifier, Supprimer, Désactiver / Réactiver*, avec recherche. Tables : années scolaires, niveaux, options,
   options par niveau, classes, devises, types de frais, tarifs (par classe, avec tranches libres), élèves, inscriptions, percepteurs,
   paiements. Le formulaire se construit d'après les champs de la table.
   Règles : la clé (code, matricule...) ne change plus après création ; une donnée déjà utilisée ne se supprime pas (le
   message dit où elle est utilisée ; on la désactive à la place : elle n'est plus proposée mais l'historique reste) ;
   un reçu ne se modifie ni ne se supprime jamais : « Annuler le reçu » le désactive (motif obligatoire, définitif).
   Le bouton « Structure de la base... » compare la base aux tables attendues, la met à niveau et vérifie son intégrité.
2. **Sauvegarde** : fichier `.csfbak` dans le dossier des sauvegardes ou sur une clé USB. Non chiffré : le garder en lieu sûr.
3. **Restauration** : le fichier est contrôlé, une sauvegarde de sécurité est faite juste avant, puis tout le monde se reconnecte.

## Gestionnaire d'accès (Administrateur)
1. **Utilisateurs** : créer un compte (mot de passe provisoire affiché une seule fois, à changer à la 1re connexion),
   choisir son rôle, modifier, désactiver, nouveau mot de passe, débloquer.
2. **Rôles** : les 8 postes (Préfet, Administrateur, Secrétaire, Intendant, Percepteur, Contrôleur, Directrice des études, Directeur de discipline)
   et leurs droits de base (donnés à tout nouveau compte du rôle). Option : les appliquer aussi aux comptes existants.
3. **Autorisations** : les droits d'un utilisateur, module par module. Effet immédiat, même s'il est connecté.
Garde-fous : toujours au moins un Administrateur actif ; on ne peut pas se rétrograder ni se désactiver soi-même.

Droits de base au départ (modifiables) : Préfet, Administrateur, Intendant, Contrôleur : Lecture - Percepteur : Lecture +
Ajout - Secrétaire, Directrice des études : aucun.

## Données
Toutes les tables sont vides au départ : élèves, classes, options, niveaux, types de frais, etc. sont saisis par
l'Administrateur (Travaux techniques) ; les droits sont accordés dans le Gestionnaire d'accès.

## Fichiers
ecrans.py, modules.py (modules du menu et arrivée directe), ecrans_tableau.py, graphiques.py (dessin des graphiques), tableau.py (tableau de bord), ecrans_paiement.py, ecrans_travaux.py, ecrans_acces.py, composants.py, theme.py (interface)
ecrans_personnel.py, personnel.py (dossier personnel), ecrans_affectations.py, affectations.py (fonctions et affectations), personnel_pdf.py (fiche et listes du personnel), ecrans_gestion.py (gestion scolaire, vide),
ecrans_carte.py, carte.py, carte_pdf.py, camera.py, qr.py, identite.py (carte d'élève, QR code, matricule), calendrier.py, saisie_date.py (champ date avec calendrier),
ecrans_audit.py, audit.py, audit_pdf.py (traçabilité et audit : journal, historique financier, contrôles, exports),
ecrans_encaissement.py, encaissements.py, encaissement_pdf.py (encaissement des fonds perçus), ecrans_controle.py, controle.py, controle_pdf.py (contrôle numérique), referentiels.py (mise à jour des tables), acces.py, droits.py (comptes et droits), migrations.py (structure),
sauvegarde.py, security.py, recuperation.py (mot de passe oublié), database.py, config.py, donnees.py, paiements.py, argent.py, recu_pdf.py, rapport_pdf.py,
demo.py (tests uniquement)
Tests : `python test_securite.py`, `test_paiements.py`, `test_travaux.py`, `test_referentiels.py`, `test_roles_reinit.py`, `test_encaissements.py`, `test_controle.py`, `test_carte.py`, `test_dates.py`, `test_audit.py`, `test_frais.py`, `test_accueil.py`, `test_tableau.py`, `test_graphiques.py`, `test_recuperation.py`, `test_essai.py`, `test_miseajour.py`, `test_inscription.py`, `test_admission.py`, `test_personnel.py`, `test_affectations.py`, `test_modules_gestion.py`, `test_presences.py`


## Nouveautés de la version 0.7
- **Connexion** : on choisit son poste (rôle) dans une liste, puis identifiant et mot de passe. Un poste qui ne correspond pas au compte est refusé comme un mauvais mot de passe.
- **Rôles** (Gestionnaire d'accès > Rôles) : « Nouveau rôle » crée un poste ; « Supprimer le rôle » retire un rôle créé (impossible s'il est encore donné à un compte ; les 8 postes de base restent).
- **Autorisations** : Ajout, Modification, Lecture, Suppression pour *Encaissement des fonds perçus* et *Contrôle numérique*. Dans *Paiement des frais*, seuls Lecture et Ajout existent : un reçu ne se modifie ni ne se supprime.
- **Réinitialisation** (Travaux techniques > Réinitialisation, Administrateur) : vide toutes les données scolaires. Mot de passe redemandé, mot « REINITIALISER » à taper, sauvegarde de sécurité automatique juste avant, opération inscrite au journal. Option : supprimer aussi les autres comptes et les rôles créés.
- **Menu principal** : gros boutons qui remplissent tout l'écran, une ligne par groupe de 3 modules.

## Nouveautés de la version 0.8
- **Encaissement des fonds perçus** (menu principal) - 2 onglets (la « Liste des encaissements » a été supprimée en 0.9) :
  1. **Enregistrement de l'encaissement** : choisir le **percepteur** (liste des percepteurs actifs), saisir le **montant encaissé**, choisir la **devise** et la **date**, saisir le **montant versé**. L'**écart** s'affiche seul (encaissé - versé : positif = manquant, négatif = excédent). Boutons **ENREGISTRER** et **ANNULER** (efface la saisie).
  2. **Rapport global** : on saisit seulement la **date**. Boutons **CONSULTER** (affiche à l'écran), **IMPRIMER** (PDF) et **ANNULER** (efface l'écran). Le rapport regroupe **tous les percepteurs** : 1) les paiements par type de frais, 2) les encaissements, versements et écarts de la journée, avec totaux par devise. Les reçus annulés ne sont pas comptés. Un percepteur qui a des reçus ce jour-là mais aucun encaissement enregistré est signalé.
- **Droits** du module (Gestionnaire d'accès > Autorisations) : Lecture (liste + rapport), Ajout (enregistrer), Modification, Suppression. L'Administrateur a tous les droits dans ce module. Tout est inscrit au journal.
- **Base de données** : la table ENCAISSEMENT est créée automatiquement au lancement (sauvegarde de sécurité faite avant). Aucune donnée existante n'est touchée.
- **Suppression dans « Mise à jour des tables »** : quand une donnée est utilisée ailleurs (par exemple une classe qui a des tarifs et des inscriptions), le programme propose maintenant de **supprimer aussi les données liées**, en montrant ce qui sera supprimé. Cette suppression reste **refusée dès qu'un reçu de paiement en dépend** : un reçu ne se supprime jamais (même annulé). Dans ce cas : désactiver la donnée, ou repartir de zéro avec **Travaux techniques > Réinitialisation** (après des essais). La table **Encaissements** y est aussi consultable et supprimable.

## Nouveautés de la version 0.9
- **Encaissement des fonds perçus** : la fonctionnalité **Liste des encaissements** est supprimée. Il reste 2 onglets : *Enregistrement de l'encaissement* et *Rapport global*. Les encaissements restent consultables / supprimables par l'Administrateur dans Travaux techniques > Mise à jour des tables > Encaissements.
- **Contrôle numérique** (menu principal) - 2 onglets, accessibles avec le droit **Lecture** (l'Administrateur y a accès) :
  1. **Edition liste des Etudiants en Ordre** : choisir l'**année scolaire**, le **trimestre / semestre**, la **classe**, l'**option** (si la classe a des options : humanités) et le **type de frais** (la liste ne propose que les frais du trimestre / semestre choisi). La liste s'affiche aussitôt, titrée **LISTE DES ELEVES EN ORDRE AVEC LE FRAIS** + type de frais, puis la classe et l'option, avec les colonnes **N°, NOM POSTNOM ET PRENOM, SEXE** (ordre alphabétique) et **Direction des études** souligné en bas à droite. **IMPRIMER** produit le PDF (plusieurs pages si besoin) ; **ANNULER** efface les choix.
     Un élève est *en ordre* s'il est inscrit dans la classe pour l'année, actif, et si ses reçus valides pour ce frais couvrent le tarif (reçus annulés non comptés). Sans tarif défini pour le frais, personne n'est en ordre (un message l'indique).
  2. **Contrôle numérique** : saisir le **nom ou le matricule** ; les informations de l'élève (matricule, nom, sexe, année, classe, option) et son **statut** s'affichent : **EN ORDRE** (vert) ou **IMPAYÉ** (rouge), avec le détail des frais. IMPAYÉ dès qu'il reste un montant à payer sur l'année en cours ou une année précédente. Un élève non inscrit cette année et sans dette est signalé **NON INSCRIT** (orange).
  Consultations, contrôles et impressions sont inscrits au journal. Aucune modification de la base de données.


## Nouveautés de la version 0.10
- **Matricule et QR code automatiques** : quand un élève est ajouté (Travaux techniques > Mise à jour des tables > Élèves), le système lui
  attribue seul son **matricule** (numéro d'ordre d'ajout : 000001, 000002...) et son **code QR** unique. Ils ne se saisissent plus et ne
  changent jamais. Un numéro supprimé n'est jamais redonné ; après une réinitialisation, la numérotation repart de 000001. Les élèves déjà
  présents gardent leur matricule et reçoivent un QR code à la mise à jour de la base.
- **Nationalité** : nouveau champ de la fiche élève (avec le sexe et l'adresse, qui existaient déjà).
- **Module Carte** (menu principal, droit Lecture ; l'Administrateur a tous les droits) :
  1. On saisit le nom (ou le matricule) de l'élève : ses informations s'affichent (matricule, nom complet, sexe, date et lieu de naissance,
     nationalité, adresse, classe, option, année, tuteur) avec son code QR. Une information absente est signalée.
  2. **Prendre la photo** : aperçu en direct de la caméra branchée, cadre blanc = zone gardée (portrait), boutons *Capturer*, *Reprendre*,
     *Utiliser cette photo*. **Importer...** prend un fichier JPEG/PNG à la place. **Retirer** supprime la photo.
  3. **IMPRIMER LA CARTE** : PDF de la carte au format portrait (54 x 85,6 mm, hauteur supérieure à la largeur).
     *Recto* : logo et nom de l'école en haut, photo, puis juste en dessous les informations de l'élève.
     *Verso* : QR code au milieu de la carte ; en bas, le nom de l'école et sa devise.
     Case cochée : une feuille A4 avec recto et verso côte à côte (imprimante ordinaire) ; décochée : 2 pages au format de la carte.
- **Droits du module Carte** : Lecture (fiche + impression), Ajout (première photo), Modification (remplacer la photo), Suppression (retirer la photo).
- La photo est enregistrée dans la base (comprise dans les sauvegardes) ; elle disparaît avec l'élève s'il est supprimé.

## Nouveautés de la version 0.11
- **Gestionnaire d'accès > Utilisateurs** : boutons **Activer** et **Désactiver** (un seul est utilisable selon l'état du compte choisi). Un compte désactivé ne peut plus se connecter, son historique reste intact. On ne peut pas se désactiver soi-même. Journalisé.
- **Types de frais** : code, désignation, **montant** et **devise** (facultatifs : laissez-les vides quand le montant dépend de la classe), la case **Payé par tranches** et le champ **Tranches**. Le montant du type s'applique à toutes les classes ; le tableau **Tarifs** donne, pour une classe et une année, un montant (et des tranches) différents : il est prioritaire. Exemple : frais scolaire = 300 en 1ère, 2ème et 3ème, 600 en 4ème. Au premier paiement, le montant appliqué à la classe est « figé » dans Tarifs.
- **Tranches libres** : la table « Tranches de paiement » n'existe plus. Dans Types de frais ou Tarifs, vous saisissez vous-même les tranches : autant que vous voulez (jusqu'à 36), chacune avec son montant (ex. 200 ; 200 ; 100 ; 100). Le total doit faire exactement le montant dû, sinon l'enregistrement est refusé. Un frais ordinaire se paie en une seule fois ; un frais par tranches se paie tranche par tranche (ou plusieurs d'un coup). Une ancienne base est convertie automatiquement (pourcentages -> montants).
- **Classes** : une ligne par division (**1ère A, 1ère B, 1ère C, 1ère D...**). Champs : classe (année d'étude), division, niveau (primaire, secondaire, humanités), option. La désignation est composée par le système. **L'option n'existe qu'en humanités** (1ère à 4ème) et y est obligatoire ; elle est refusée ailleurs. Une même classe ne peut pas être créée deux fois.
- **Mise à jour automatique des anciennes bases** (sauvegarde de sécurité d'abord) : le montant d'un type de frais est repris des tarifs seulement s'il est identique dans toutes les classes (rien ne change pour les élèves) ; l'année d'étude et la division des classes existantes sont lues dans leur désignation, qui n'est pas modifiée.

## Nouveautés de la version 0.12
- **Dates** : partout où une date se saisit (naissance et inscription d'un élève, date de l'encaissement, date des rapports), le champ accepte la **saisie au clavier** (`jj/mm/aaaa` : les « / » s'ajoutent tout seuls ; `8/10/2026`, `08-10-2026`, `2026-10-08` sont aussi compris) **et** un **calendrier** : bouton 📅 à droite du champ, choix du mois et de l'année dans des listes, flèches ‹ › pour changer de mois, bouton « Aujourd'hui ».
- **Matricule `0001/26`** : `0001` = numéro d'ordre, `26` = année d'inscription (2 derniers chiffres de l'année où l'élève est ajouté). La numérotation **repart de 0001 chaque année** (0001/26, 0002/26... puis 0001/27). Un numéro supprimé n'est jamais redonné ; après une réinitialisation, tout repart de 0001. Les élèves existants gardent leur ancien matricule. (Dans un nom de fichier, le « / » devient « - » : `Carte_0001-26.pdf`.)
- **Trimestres / semestres supprimés** : la table « Trimestres / semestres » n'existe plus, et un type de frais n'est plus rattaché à une période. Les écrans (situation de l'élève, contrôle numérique, rapports, reçus) n'en parlent plus ; le contrôle numérique se règle sur *année + classe (+ option) + type de frais*. Une ancienne base garde sa table et sa colonne (rien n'est supprimé) mais le programme ne s'en sert plus.
- **Frais par tranches** : tout frais peut être payé par tranches (case « Payé par tranches » + montants des tranches) ; les autres se paient en une seule fois.
- **Tarifs et classes** : l'ajout d'un tarif propose la **liste des classes à cocher** (boutons « Toutes » / « Aucune ») : un même tarif (type de frais, année, montant) se crée d'un coup pour plusieurs classes, tout ou rien (si une classe a déjà ce tarif, elle est nommée et rien n'est créé). La liste des tarifs est rangée par année, type de frais et montant, avec la colonne **« Classe qui dépend de ce tarif »**. Une classe sans tarif paie le montant du type de frais.
- **Numéro de reçu `0001`** : numérotation continue (0001, 0002, ... 0010, ... 10000), d'une année à l'autre. Les anciens reçus gardent leur numéro (par exemple 2026-000001).

## Nouveautés de la version 0.13
- **Arrivée directe dans le module** : un compte qui n'a accès qu'à **un seul module** (par exemple un Percepteur, qui n'a que *Paiement des frais*, ou un Intendant) n'est plus accueilli par le gros bouton du menu principal : après la connexion (et après un changement de mot de passe), il arrive **directement dans le contenu du module** et voit ses fonctionnalités (les onglets).
- Un compte qui a accès à **plusieurs modules** (l'Administrateur par exemple), ou à aucun, voit le **menu principal** comme avant.
- Pour un compte sans menu, le bouton « Menu principal » devient **« Se déconnecter »**, et **« Mon mot de passe »** est ajouté dans la barre du haut du module.
- La règle est relue dans la base à chaque connexion : si l'Administrateur ajoute ou retire des droits (Gestionnaire d'accès > Autorisations), l'écran d'arrivée change à la connexion suivante.

## Nouveautés de la version 0.14
- **Tableau de bord** (lecture seule). **L'Administrateur choisit qui peut le voir** : Gestionnaire d'accès > Autorisations (un compte) ou Rôles (tout un poste) : ligne « Tableau de bord », case **Lecture**. L'Administrateur le voit toujours. Les droits sont relus à chaque affichage : retirer le droit agit tout de suite.
- **Premier écran à la connexion** pour tout compte autorisé (avant le menu principal et avant l'arrivée directe dans un module). Les autres comptes ne voient rien de changé.
- **Barre bleue** (nom et poste de l'utilisateur) : sur le tableau de bord, **Menu principal** (devant), **Mon mot de passe** puis **Se déconnecter** (au bout). Il n'y a plus de bouton « Tableau de bord » : l'écran s'affiche en premier à la connexion. Sur le menu : Mon mot de passe, Se déconnecter. Dans un module : « Menu principal » (ou, pour un compte qui n'a qu'un seul module : Mon mot de passe, Se déconnecter).
- **Contenu** :
  1. **Élèves** de l'année scolaire choisie : inscrits, **en ordre**, **en situation d'impayé**, et la répartition par classe. Même règle que le Contrôle numérique : impayé dès qu'il reste un montant à payer sur un frais de l'année ou d'une année précédente ; élèves désactivés non comptés.
  2. **Situation des frais de l'année**, par devise : total dû, payé, reste à payer, pourcentage payé.
  3. **Opérations financières** de la période choisie (**Du / Au**, ou « Aujourd'hui », « Ce mois », « Toutes les dates »), par devise : paiements reçus (reçus valides), reçus annulés, montants encaissés, montants versés, écart (positif : manquant, négatif : excédent), puis la **liste de toutes les opérations** (paiements, reçus annulés, encaissements : date et heure, référence, élève ou percepteur, détail, montant, devise, statut, enregistré par). La liste montre les 500 plus récentes ; les totaux portent sur toutes les opérations de la période.
- L'ouverture du tableau de bord est inscrite au journal. Aucune table n'est ajoutée ni modifiée dans la base.

## Nouveautés de la version 0.15
- **Travaux techniques > 5 Authentification et mots de passe** (Administrateur) : le gestionnaire d'authentification.
  Il affiche les règles en vigueur (longueur et complexité du mot de passe, blocage après échecs, fermeture de session),
  l'**état de chaque compte** (actif, désactivé, bloqué, mot de passe provisoire), son **code de récupération en cours**
  avec le temps qui reste, et les **dernières opérations d'authentification** (connexions, échecs, blocages, mots de passe
  changés, codes générés / utilisés / expirés). Boutons : *Générer un code de récupération*, *Annuler le code*,
  *Mot de passe provisoire*, *Débloquer*, *Actualiser*.
- **Mot de passe oublié** - comment ça se passe :
  1. L'utilisateur prévient l'Administrateur, qui **vérifie son identité**.
  2. L'Administrateur choisit son compte et clique sur **Générer un code de récupération**. Le **système** fabrique un code
     de 8 caractères (ex. `K7M4-PQXR`, sans 0, 1, I, O) qui s'affiche **une seule fois**, avec un compte à rebours. Il
     le dit de vive voix à l'utilisateur.
  3. Sur l'écran de connexion, l'utilisateur clique sur **Mot de passe oublié ?**, saisit son identifiant, le code, puis
     choisit son nouveau mot de passe (mêmes règles que d'habitude). Il peut ensuite se connecter normalement.
- **Le code disparaît après 2 minutes** (`DUREE_CODE_RECUPERATION_SEC` dans config.py) : il est effacé de l'écran et supprimé
  de la base. Il ne sert qu'une fois, un seul code existe par compte (en générer un nouveau détruit l'ancien) et il est
  détruit après 3 essais faux. Il n'est jamais enregistré en clair (seulement son empreinte) ni écrit dans le journal.
- Le code est aussi détruit si le compte change de mot de passe, reçoit un mot de passe provisoire ou est désactivé.
  Récupérer son mot de passe **lève un blocage** du compte.
- Message d'échec toujours identique (code faux, expiré, identifiant inconnu, compte désactivé) : rien n'indique si un
  code existe pour un compte. Un mot de passe trop faible ou une confirmation différente ne consomme pas le code.
- Un Administrateur ne peut pas générer un code pour son **propre** compte : s'il oublie son mot de passe, un **autre
  Administrateur** le fait. Gardez donc au moins deux comptes Administrateur.
- Base de données : la table CODE_RECUPERATION est créée automatiquement au lancement (sauvegarde de sécurité faite avant).
  Aucune donnée existante n'est touchée.


## Nouveautés de la version 0.16 : module Traçabilité et audit
Nouveau module du menu principal (3e ligne). **Il ne modifie rien** : il lit le journal de l'application et les tables
financières. Accès : l'Administrateur, ou tout compte / poste à qui il accorde la **Lecture** (Gestionnaire d'accès >
Autorisations ou Rôles, ligne « Traçabilité et audit »). Les droits sont relus à chaque action : retirer le droit agit tout de suite.

**1. Journal des activités** - toutes les actions enregistrées automatiquement pour chaque utilisateur, de la plus récente à la
plus ancienne : connexion, déconnexion (volontaire ou après inactivité), échecs de connexion, consultation d'un dossier
(situation de l'élève, reçus d'un élève, fiche de la carte, contrôle numérique), ajout / modification / suppression d'une donnée,
impression ou exportation d'un rapport (reçu, duplicata, rapports de caisse, carte, liste des élèves en ordre, sauvegarde,
exports d'audit), sécurité et administration. Filtres : **période, utilisateur, catégorie, texte** (sans tenir compte des
accents ni de la casse), « opérations financières seulement ». Un clic sur une ligne affiche son détail complet.
Les modifications et suppressions de tables (classes, frais, tarifs, devises...) montrent **ce qui a changé : ancienne valeur -> nouvelle valeur**.
Pour les **élèves**, le journal garde seulement les champs modifiés, jamais leur contenu (pas de données personnelles dans le journal).

**2. Opérations financières** - l'historique des opérations liées aux frais scolaires :
- **paiements enregistrés** : N° de reçu, élève, frais, montant, **utilisateur qui l'a enregistré** (d'après le journal) et percepteur du reçu ;
- **reçus et duplicata imprimés** (qui, quand) ; **annulations de paiement** (qui, quand, motif) ;
- **encaissements et remises de fonds** : montant encaissé, montant versé, **écart** (manquant / excédent), utilisateur qui l'a saisi ;
- encaissements **modifiés ou supprimés** (la trace reste au journal même quand la ligne a disparu de la table).
Exemple : taper le matricule ou le nom d'un élève (ou un N° de reçu) -> son paiement et le compte qui l'a enregistré.
Filtres : élève, N° de reçu, utilisateur, type d'opération, période, « écarts seulement ». Un tableau donne les totaux par devise
(paiements, annulations, net, encaissé, versé, écart). Un clic sur une opération affiche sa **fiche** et toutes ses traces du journal.
Une recherche sur un élève ou un reçu est elle-même inscrite au journal.

**3. Contrôles** - *Intégrité du journal* (chaîne d'empreintes : toute ligne modifiée ou supprimée après coup est détectée,
dernière empreinte affichée pour la noter) et *Concordance* entre le journal et les tables financières (reçu sans trace
d'enregistrement, reçu annulé sans trace d'annulation, reçu enregistré par un autre compte que son percepteur, numéros de reçu
manquants, écart d'encaissement incohérent, encaissement sans trace). Une anomalie n'est pas une preuve de fraude : elle indique où regarder.

**Exports** : **Exporter (Excel / CSV)** et **Imprimer (PDF, A4 paysage)** pour le journal et pour l'historique financier ; ils
contiennent toutes les lignes trouvées (l'écran en montre 500 au plus). Fichiers dans `%LOCALAPPDATA%\GESTSCO\audit\`.
Le PDF porte en pied de page l'état du journal (nombre de lignes, empreinte). Chaque export est inscrit au journal.

**Base de données** : aucune nouvelle table, aucune migration. Le journal n'est jamais modifié ni supprimé (verrouillé par la base).

## Nouveautés de la version 0.18 : tableau de bord simplifié (remplace sa description des versions 0.14 à 0.17)
- Le **tableau de bord ne montre plus que l'essentiel** : pour l'année scolaire choisie, le nombre d'**élèves inscrits**, d'**élèves en règle** et d'**élèves pas en règle**, avec un camembert. **Aucun détail** (ni nom d'élève, ni classe) et **aucune donnée financière** (ni montant, ni reçu, ni encaissement, ni devise).
- Les onglets Général / Élèves / Finances / Opérations, les filtres de devise et de période, la courbe, l'histogramme et les barres de frais sont **supprimés**, et le calcul qui les alimentait aussi : le module ne lit plus les reçus ni les encaissements pour les afficher. Un test vérifie que le résultat ne contient que les nombres d'élèves.
- « En règle » : l'élève n'a plus rien à payer sur l'année choisie ni sur les années précédentes (même règle que le Contrôle numérique) ; les élèves désactivés ne sont pas comptés.
- Qui le voit, premier écran à la connexion et boutons **« Retour au menu principal »** (sur le tableau de bord) et **« Retour au tableau de bord »** (sur le menu principal) : inchangés.
- Correction : la légende du camembert passe sur deux lignes quand la fenêtre est étroite au lieu de dépasser.

## Nouveautés de la version 0.19 : contrôle financier, recherche des traces, rapports d'audit
Le module **Traçabilité et audit** (Journal et audit) passe à 6 onglets ; les trois nouveaux sont réservés aux utilisateurs ayant le droit d'audit (Administrateur ou droit Lecture sur le module audit). Aucun nouveau droit ni nouvelle table.
- **4 Contrôle et audit financier** : vérifie les paiements et leurs reçus (reçu ↔ trace du journal), les montants encaissés et remis, les annulations et corrections, et les différences entre les opérations enregistrées et les rapports journaliers imprimés. Filtres : période, percepteur, devise. Les anomalies sont classées par gravité (reçu sans trace, montant différent du journal, écart de remise, trop-perçu, annulations répétées, duplicatas excessifs, rapport non conforme, etc.).
- **5 Recherche et filtrage des traces** : filtres par utilisateur, période, module, type d'action (liste dépendante du module), numéro de reçu, matricule de l'élève (un élève supprimé reste retrouvable) et texte libre ; détail de la trace et fiche du reçu ; export. Les recherches ciblées (reçu, élève) sont elles-mêmes tracées.
- **6 Génération des rapports d'audit** : rapport général (toutes les opérations), financier, anomalies financières, activité par utilisateur, opérations sensibles. Consultation à l'écran, impression PDF (A4 paysage, avec zone de signatures) ou export Excel/CSV. Chaque génération est journalisée.
- Les rapports journaliers imprimés (paiements et encaissements) inscrivent désormais au journal le nombre de reçus/encaissements et le total, ce qui permet de les rapprocher des opérations.
- Nouveaux fichiers : `audit_financier.py`, `audit_recherche.py`, `audit_rapports.py`, `ecrans_audit_financier.py`, `test_audit_financier.py` ; `audit_pdf.py`, `audit.py`, `argent.py` étendus.

## Nouveautés de la version 0.20 : frais selon la classe, tranches libres, données d'essai
- **Menu principal** : les boutons de module ont une taille fixe et plus petite (ils ne s'étirent plus à tout l'écran quand un compte n'a que 1 ou 2 modules).
- **Erreurs corrigées dans TARIF / TYPE_FRAIS / tranches** : le montant du type de frais et celui du tarif d'une classe pouvaient se contredire ; les tranches en pourcentage (table séparée, total 100 %) donnaient des arrondis faux et ne suivaient pas le tarif de la classe ; un frais « par tranches » sans tranches valides était accepté ; le tarif « figé » au premier paiement ne gardait pas les tranches. Tout est maintenant dans deux tableaux cohérents.
- **Frais qui dépendent de la classe** : un type de frais peut ne pas avoir de montant ; on le fixe alors par classe et par année dans **Tarifs** (vous cochez plusieurs classes à la fois : par exemple 1ère, 2ème et 3ème à 300, puis la 4ème à 600).
- **Tranches libres** : nombre et montant de chaque tranche au choix, par type de frais ou par classe (colonne `TRANCHES`, en centimes). Le formulaire de paiement propose la prochaine tranche ; un paiement qui ne tombe pas sur une fin de tranche est refusé avec le montant attendu.
- **Mise à jour automatique** (migration 6) : les anciennes tranches en pourcentage deviennent des montants, la table TRANCHE disparaît quand tout est converti.
- **Données d'essai** (Travaux techniques > onglet **6 Données d'essai**, Administrateur) : en un clic, **120 élèves fictifs** (minimum 100) répartis dans vos classes existantes, 5 frais d'essai `ESS-...` (dont le frais scolaire 300/600 par classe avec tranches libres), **un compte par poste** (mots de passe aléatoires montrés une fois et enregistrés dans `essai\comptes_essai.txt`) et de **vraies opérations** faites avec ces comptes : connexions (dont un échec), paiements par tranches, 3 annulations, encaissements (un corrigé, un supprimé, un avec manquant de 5,00), consultations de dossiers. Tout apparaît dans le journal et la Traçabilité et audit.
- **Suppression en un clic** (mot de passe + « SUPPRIMER ») : retire uniquement ce qui a été créé pour l'essai et ce qui s'y rattache (reçus, encaissements, comptes). Vos vraies données ne sont jamais touchées ; le compteur des matricules revient à sa valeur d'avant ; une sauvegarde de sécurité est faite avant l'installation et avant la suppression. Le journal garde les traces (il est en ajout seulement) et le contrôle financier sait qu'elles ont été retirées : aucune fausse alerte, même quand la numérotation des reçus repart de 0001.
- Nouveaux fichiers : `essai.py`, `test_essai.py` ; `donnees.py`, `paiements.py`, `referentiels.py`, `migrations.py`, `database.py`, `audit_financier.py`, `ecrans_travaux.py` étendus.

## Nouveautés de la version 0.21 : mise à jour du programme sans internet
- **Travaux techniques > 7 Mise à jour du programme** (Administrateur) : on choisit un fichier `.csfupd` (clé USB, dossier réseau, courriel), on saisit la **clé de mise à jour**, on vérifie, on installe. Le programme redémarre tout seul.
- **Sécurité** : le fichier est contrôlé AVANT toute modification : cachet HMAC avec la clé (qui n'est écrite nulle part ; elle se donne séparément, par téléphone par exemple), empreinte SHA-256 de chaque fichier, chemins et types de fichiers autorisés, version plus récente que l'installée. Un fichier fabriqué ou modifié est refusé. Mot de passe de l'Administrateur redemandé ; tout est inscrit au journal (Traçabilité et audit).
- **Filet de sécurité** : sauvegarde de la base juste avant (« Avant-mise-a-jour »), version actuelle gardée dans `ancienne_version` (les 3 dernières), et au moindre problème pendant l'installation la version précédente est remise en place. **Retour en arrière** possible depuis le même écran ; refusé si la base a déjà été transformée par la nouvelle version (il faut alors restaurer la sauvegarde « Avant-mise-a-jour »).
- Les données (base, reçus, sauvegardes) sont hors du dossier du programme : une mise à jour ne les touche jamais. La structure de la base se met à jour seule au démarrage.
- **Préparer un fichier de mise à jour** (côté développeur) : `python miseajour.py creer mise_a_jour_0.22.csfupd` (demande la clé, affiche l'empreinte à communiquer avec elle). **La toute première fois (passage à la 0.21), l'installation se fait à la main** : remplacez les fichiers du programme par ceux du zip.
- Nouveaux fichiers : `miseajour.py`, `test_miseajour.py` ; `ecrans_travaux.py`, `audit.py` étendus.

## Nouveautés de la version 0.22 : module Inscription
**Parcours** : le candidat paie à la caisse (module Paiement des frais) -> le percepteur lui remet le reçu -> il va chez le
secrétaire (ou l'utilisateur concerné) qui remplit le **formulaire d'inscription** avec le numéro du reçu -> il enregistre et
imprime la fiche -> le candidat est mis sur la **liste d'attente**.

- **Le paiement n'est pas dans le module Inscription** : il reste dans Paiement des frais. L'Administrateur marque le type de frais
  concerné : *Travaux techniques > Mise à jour des tables > Types de frais > case « Frais d'inscription »* (un frais d'inscription se
  paie en une seule fois).
- **Pas de paiement, pas de candidature** : le système refuse un reçu inexistant, annulé, d'un autre type de frais, d'une autre année,
  ou déjà utilisé pour un autre candidat. La base de données refuse aussi, même sans passer par l'écran.
- **Formulaire (1er onglet)** : identité (nom, postnom, prénom, sexe, date de naissance, lieu, nationalité, adresse, téléphone),
  ancienne école et pourcentage, doublant (oui/non), classe souhaitée, tuteur (nom, téléphone, adresse). Bouton « Vérifier le paiement »
  pour contrôler le reçu avant de remplir. Bouton « Enregistrer et imprimer » : la fiche PDF s'ouvre.
- **Liste d'attente (2e onglet)** : par ordre d'arrivée, rang calculé classe par classe, filtre par classe, recherche, réimpression de la fiche.
- **Droits du module Inscription** : Lecture (liste, réimpression), Ajout (formulaire). À accorder dans le Gestionnaire d'accès.
- **Nouvelles tables** : `CANDIDATURE` (le formulaire + statut EN_ATTENTE / ADMIS / REFUSE / RETIRE + matricule une fois admis) et la colonne
  `TYPE_FRAIS.POUR_INSCRIPTION`. Créées automatiquement à l'ouverture d'une ancienne base, sans perte. Numéro de candidature : `C0001/26`.
- **Paiement à la caisse d'un candidat qui n'est encore enregistré nulle part** : pas encore fait (voir la fin de ce fichier).

## Nouveautés de la version 0.25 : modules « Gestion scolaire » et « Gestion du personnel »
Deux gros boutons au menu principal, avec leurs droits (Lecture, Ajout, Modification, Suppression) dans le Gestionnaire d'accès. Écrans dans `ecrans_gestion.py`, prêts à recevoir les onglets.

## Nouveautés de la version 0.24 : paiement des frais d'inscription par une personne pas encore inscrite
- **Boutons Enregistrer / Annuler** de l'onglet « Enregistrement du paiement » : ils sont maintenant fixés en bas de
  l'écran (ils ne sortent plus de la fenêtre) ; les champs défilent au-dessus si l'écran est petit. Les boutons grisés
  sont aussi plus lisibles.
- **Bouton « Inscription »** (onglet 1 « Consultation », toujours visible en bas ; aussi dans l'onglet 2) : il ouvre
  l'enregistrement du paiement pour un candidat qui n'a pas de matricule. On saisit son nom, postnom, prénom, l'année et
  la classe souhaitée ; le type de frais d'inscription et son montant s'affichent tout seuls (payé en une seule fois).
  Le percepteur enregistre, imprime le reçu, et le candidat va chez le secrétaire (module Inscription) avec ce reçu.
  Le bouton du bas permet de passer de « Inscription » à « Élève déjà inscrit » et inversement.
- Prérequis : l'Administrateur a marqué un type de frais comme « frais d'inscription » et lui a donné un montant
  (Travaux techniques > Mise à jour des tables > Types de frais).
- Un même candidat ne peut pas payer deux fois les mêmes frais la même année (message avec le n° du reçu ; utiliser le
  duplicata). Le reçu d'inscription apparaît partout comme les autres reçus : rapport journalier, duplicata, audit,
  contrôle financier. Il est indiqué « (candidat) ».
- Base de données : migration automatique n° 7 (sauvegarde de sécurité faite avant ; aucun reçu n'est perdu).

## Nouveautés de la version 0.23 : Inscription, 2ème fonctionnalité « Validation et affectation »
**Parcours** : candidat sur la liste d'attente -> il passe le **test d'admission** -> on enregistre sa **note** -> s'il réussit, son
**dossier est validé** -> on l'**affecte à une classe** -> il **devient élève** : le système lui attribue son **matricule** (même
modèle que partout : `0001/26`) et son code QR, et l'inscrit dans la classe pour l'année.

- **3e onglet « Validation et affectation »** du module Inscription. Liste de tous les candidats de l'année avec leur situation :
  *Test à passer* / *Réussi - à affecter* / *Admis (élève)* / *Refusé (test échoué)*. Filtre par situation, recherche par nom,
  numéro de candidature ou matricule.
- **Étape 1 - Résultat du test** : note sur 100. **Seuil de réussite : 50** (`SEUIL_REUSSITE_TEST` dans `config.py`).
  Note >= seuil : dossier validé ; note < seuil : candidature **refusée** (définitif, elle quitte la liste d'attente).
  Une confirmation montre la note et la conséquence avant d'enregistrer ; **un résultat enregistré ne se modifie plus**.
- **Étape 2 - Affectation** : la classe proposée est la classe souhaitée, mais on peut en choisir une autre (le vœu d'origine est
  conservé). « Valider et affecter » fait, **en une seule opération tout ou rien** : création de l'élève (identité et tuteur repris
  du formulaire), matricule et code QR, inscription dans la classe (statut *Redoublant* si le candidat est doublant, sinon *Nouveau*),
  candidature passée à *ADMIS* avec son matricule. Le nouvel élève est aussitôt reconnu par Paiement des frais, Carte et Contrôle numérique.
- **Matricule** : le même compteur que partout (`0001/26`, repart de 0001 chaque année, jamais redonné). Un élève ajouté à la main
  et un candidat admis ne peuvent donc jamais recevoir le même numéro.
- **Garde-fous** : pas d'affectation sans test réussi ; pas deux fois ; classe désactivée refusée ; **reçu annulé après la candidature =
  affectation refusée** (le candidat doit repasser à la caisse) ; **même nom complet et même date de naissance qu'un élève existant =
  refusé** (évite un second matricule pour le même enfant). La base de données refuse elle aussi, sans passer par l'écran, de passer
  une candidature à ADMIS sans test réussi, matricule et classe.
- **Avis d'admission** (PDF A4) : note, classe d'affectation et matricule ; proposé après l'affectation, réimprimable depuis la liste.
- **Droits** : nouveau droit **Modification** sur le module Inscription (Gestionnaire d'accès > Autorisations ou Rôles) pour valider et affecter.
  Lecture : consulter ; Ajout : formulaire ; Modification : test et affectation. L'Administrateur a tout. Chaque opération est inscrite au
  journal (`CANDIDATURE_TEST_ENREGISTRE`, `CANDIDAT_ADMIS_AFFECTE`, `AVIS_ADMISSION_IMPRIME`) sans nom d'élève.
- **Base de données** : 7 colonnes ajoutées à `CANDIDATURE` (note, résultat, date et auteur du test, classe d'affectation, date et auteur de
  la décision) et un déclencheur. Ajoutés automatiquement à l'ouverture d'une base 0.22, après sauvegarde de sécurité ; aucune donnée perdue.
- Fichiers : `inscription.py`, `ecrans_inscription.py`, `inscription_pdf.py`, `database.py`, `config.py`, `audit.py` étendus ; `test_admission.py` nouveau.


## Nouveautés de la version 0.27 - Gestion du personnel : deux fonctionnalités
Le module a deux lignes d'onglets : en haut la **fonctionnalité** (1 Dossier personnel, 2 Fonctions et affectations), dessous ses onglets.
Le module s'ouvre sur « Dossier de l'agent » si le compte n'a pas le droit Ajout.

### 1. Dossier personnel
- **Nouvel agent** : nom, postnom, prénom, sexe, date de naissance (calendrier), adresse, téléphone, e-mail (Gmail ou autre, facultatif),
  matricule, date d'engagement, fonction et statut professionnel (Permanent, Contractuel, Vacataire, Stagiaire, Temporaire).
  **Matricule** : laissez-le vide, le système l'attribue (`P0001/26`) ; tapez-le seulement s'il existe déjà. Il est unique et ne change plus.
  **Fonction** : à choisir dans la liste des fonctions de l'école, ou à taper (une fonction nouvelle est ajoutée à la liste) ; elle devient
  la première affectation de l'agent, à sa date d'engagement. Après l'enregistrement, le programme propose d'imprimer la fiche.
- **Dossier de l'agent** : UN SEUL écran. On choisit l'agent dans la liste (recherche par matricule, nom, fonction ou téléphone, sans tenir
  compte des accents) ; à droite on **consulte et modifie** ses informations, on **joint, ouvre ou supprime ses documents administratifs
  numérisés** (PDF, JPEG ou PNG, 5 Mo au plus ; double-clic pour ouvrir) et on **voit / imprime sa fiche individuelle** (PDF d'une page).
  « Désactiver » : l'agent a quitté l'école, son dossier est conservé (réactivable). La **fonction** ne se change pas ici mais par une
  affectation (l'historique reste complet).

### 2. Fonctions et affectations
- **Fonctions et services** : on détermine la liste des fonctions (Enseignant, Secrétaire, Préfet des études...) et des services
  (Administration, Discipline, Enseignement...) : ajouter, renommer, désactiver / réactiver, supprimer. Une fonction ou un service déjà utilisé
  ne se supprime pas : on le désactive (il n'est plus proposé, l'historique reste).
- **Affectations et historique** : un seul écran par agent : situation actuelle, **historique de tous ses changements de fonction**
  (début, fin, fonction, service, responsabilité, durée, situation En cours / Terminée / À venir), et le formulaire d'une **nouvelle
  affectation** : fonction, service et/ou responsabilité (ex. « Titulaire de la 3ème A »), date de début, date de fin si nécessaire, motif.
  Règles : un agent n'a qu'une affectation à la fois ; si l'affectation en cours n'a pas de date de fin, elle se termine automatiquement la
  veille du nouveau début (c'est ainsi qu'un changement de fonction s'enregistre) ; une fin déjà fixée n'est jamais raccourcie d'office
  (bouton « Corriger »). « Terminer l'affectation choisie » met une date de fin (départ, mutation) ; « Corriger » modifie service,
  responsabilité, dates ou motif. Une affectation n'est jamais supprimée. La fonction affichée dans le dossier est celle de l'affectation en cours.
- **Liste du personnel** : **par fonction** ou **par service**, pour une fonction / un service ou pour tous, à la date choisie
  (aujourd'hui par défaut : on peut voir la situation d'une date passée). Seuls les agents en service y figurent ; ceux qui n'ont pas
  d'affectation en cours sont regroupés à part. Boutons **CONSULTER** (écran) et **IMPRIMER LA LISTE** (PDF A4, plusieurs pages si besoin).

### Droits (Gestionnaire d'accès > Autorisations, module « Gestion du personnel »)
**Lecture** : ouvrir le module, consulter les dossiers, l'historique et les listes, imprimer la fiche et les listes, ouvrir un document ;
**Ajout** : enregistrer un agent, joindre un document, créer une fonction ou un service, affecter ; **Modification** : corriger un dossier,
désactiver / réactiver un agent, une fonction ou un service, corriger ou terminer une affectation ; **Suppression** : retirer un document
joint par erreur, ou une fonction / un service jamais utilisé. Tout est inscrit au journal (Traçabilité et audit).
Les tables (PERSONNEL, DOCUMENT_PERSONNEL, FONCTION_PERSONNEL, SERVICE_PERSONNEL, AFFECTATION) sont créées automatiquement au lancement,
après une sauvegarde de sécurité. Les agents déjà enregistrés en 0.26 reçoivent leur première affectation (leur fonction, à leur date
d'engagement) : rien n'est perdu. « Réinitialisation » (Travaux techniques) vide aussi le personnel.

### Affichage sur les petits écrans (0.26)
Le contenu de chaque module s'adapte à l'écran : rien n'est coupé. Si la fenêtre est trop petite, une barre de défilement apparaît
(la molette de la souris fonctionne aussi). Les boutons du bas (Enregistrer, Annuler, Imprimer, Menu principal...) des formulaires
et listes d'Inscription et de Gestion du personnel restent toujours visibles ; ce sont les champs et les tableaux qui défilent.

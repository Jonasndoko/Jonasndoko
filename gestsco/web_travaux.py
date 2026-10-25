"""Module « Travaux techniques » en ligne (pages web), réservé à l'Administrateur. Toute la logique métier reste dans referentiels.py,
migrations.py, recuperation.py, acces.py, sauvegarde.py et droits.py, exactement comme dans le logiciel Windows : ici on ne fait que
les pages, et on re-vérifie tout côté serveur (compte Administrateur relu dans la base à chaque action, chaque opération journalisée).

Quatre fonctionnalités en ligne :
  1. Mise à jour des tables   : ajouter, modifier, supprimer (avec les données liées, après aperçu), désactiver / réactiver,
                                annuler un reçu (motif obligatoire) ;
  2. Structure de la base     : analyse, mise à jour (sauvegarde de sécurité faite avant), contrôle d'intégrité ;
  3. Authentification         : état des comptes, code de récupération (montré une seule fois, 2 minutes), mot de passe provisoire,
                                déblocage, journal ; + la page publique « Mot de passe oublié ? » où l'utilisateur saisit son code ;
  4. Sauvegarde               : création d'une copie complète de la base et téléchargement du fichier.

Restent dans le logiciel Windows (étape 8 de FEUILLE_DE_ROUTE.md) : Restauration, Réinitialisation, Données d'essai et Mise à jour du
logiciel : elles remplacent la base ou le programme en cours d'utilisation, ce qui demande une procédure propre à l'hébergeur.

Particularités de la version web :
  - la clé d'une ligne (code, matricule, n° de reçu...) voyage dans un paramètre « k » codé en JSON (jamais dans le chemin) ;
  - un secret (code de récupération, mot de passe provisoire) est affiché dans la réponse à la demande, une seule fois, jamais
    placé dans une adresse ni dans la session ; la page l'efface à la fin du délai.
"""
import json
import secrets
import threading
import zipfile
from pathlib import Path

from flask import abort, make_response, redirect, render_template, request, url_for

import acces
import config
import database
import droits
import migrations
import miseajour
import modules
import recuperation
import referentiels as ref
import sauvegarde
import security
import sessions_web
from database import lire_iso, maintenant

LIMITE_LIGNES = 500
_VERROU_SAUVEGARDE = threading.Lock()

ONGLETS = (
    ("tables", "Mise à jour des tables", "travaux_tables"),
    ("structure", "Structure de la base", "travaux_structure"),
    ("auth", "Authentification et mots de passe", "travaux_auth"),
    ("sauvegarde", "Sauvegarde", "travaux_sauvegarde"),
    ("restauration", "Restauration", "travaux_restauration"),
    ("miseajour", "Mise à jour du programme", "travaux_miseajour"),
)
TAILLE_MAX_IMPORT = 200 * 1024 * 1024          # sauvegarde envoyée par le navigateur (le reste de l'application est limité à 300 Ko)
MOT_CONFIRMATION = "RESTAURER"
TAILLE_MAX_MAJ = 100 * 1024 * 1024             # fichier de mise à jour (.csfupd) envoyé par le navigateur

MESSAGES_OK = {
    "ajoute": "Ajouté.", "modifie": "Modifié.", "inchange": "Aucun changement à enregistrer.",
    "supprime": "Supprimé.", "supprime_liees": "Supprimé, avec les données liées.",
    "desactive": "Désactivé : il n'est plus proposé, l'historique est conservé.", "reactive": "Réactivé.",
    "annule": "Reçu annulé.", "code_annule": "Code de récupération annulé.", "debloque": "Compte débloqué.",
    "sauvegarde": "Sauvegarde créée.", "importee": "Fichier contrôlé et rangé sur le serveur : vérifiez le résumé puis confirmez.", "maj": "Structure mise à jour.", "rien": "Rien à mettre à jour : tout était déjà à jour.",
}


def formater_taille(octets) -> str:
    if octets < 1024 * 1024:
        return f"{max(1, round(octets / 1024))} Ko"
    return f"{octets / (1024 * 1024):.1f}".replace(".", ",") + " Mo"


def formater_horodatage(texte) -> str:
    try:
        return lire_iso(texte).astimezone().strftime("%d/%m/%Y  %H:%M")
    except (TypeError, ValueError):
        return texte or "—"


def description_contenu(manifeste) -> str:
    c = (manifeste or {}).get("contenu") or {}
    if not c:
        return "—"
    return f"{c.get('eleves', 0)} élève(s), {c.get('paiements', 0)} paiement(s), {c.get('utilisateurs', 0)} compte(s)"


def _iso(texte) -> str:
    """'25/03/2010' -> '2010-03-25' (valeur d'un champ <input type=date>) ; tout autre texte est rendu tel quel."""
    t = (texte or "").strip()
    parties = t.split("/")
    if len(parties) == 3 and all(p.isdigit() for p in parties):
        return f"{parties[2]}-{parties[1].zfill(2)}-{parties[0].zfill(2)}"
    return t


def enregistrer(app, conn, session_courante, connecte, origine_ok):
    """Ajoute les routes /m/travaux/... et /mot-de-passe-oublie à l'application (paramètres venus d'app_web.creer_app)."""
    app.jinja_env.filters["horo"] = formater_horodatage

    # ------------------------------------------------------------------ utilitaires communs
    def acces_admin():
        s = session_courante()
        if not droits.est_admin(conn(), s):
            abort(403)
        return s

    def poster():
        if not origine_ok():
            abort(403)

    def contexte(s, onglet, **plus):
        ctx = dict(s=s, cfg=config, titre="Travaux techniques", menu_utile=modules.menu_utile(conn(), s), onglet=onglet,
                   onglets=[(c, lib, url_for(ep)) for c, lib, ep in ONGLETS], ok=MESSAGES_OK.get(request.args.get("ok", ""), ""))
        ctx.update(plus)
        return ctx

    def lire_table():
        try:
            return ref.table(request.values.get("t", ""))
        except ref.ErreurRef:
            abort(404)

    def lire_cle(t):
        """Clé de la ligne depuis le paramètre « k » (liste JSON) : on contrôle la forme avant de s'en servir."""
        try:
            k = json.loads(request.values.get("k", ""))
        except ValueError:
            abort(400)
        if (not isinstance(k, list) or len(k) != len(t.cles)
                or not all(isinstance(v, (int, str)) and not isinstance(v, bool) for v in k)):
            abort(400)
        return tuple(k)

    def cle_texte(cle) -> str:
        return json.dumps(list(cle), ensure_ascii=False, separators=(",", ":"))

    def nom_ligne(t, cle) -> str:
        for l in ref.lister(conn(), session_courante(), t.cle)["lignes"]:
            if l["cle"] == tuple(cle):
                return " - ".join(v for v in l["valeurs"][:2] if v)
        return " / ".join(str(v) for v in cle)

    @app.get("/m/travaux")
    @connecte
    def travaux_accueil():
        acces_admin()
        return redirect(url_for("travaux_tables"))

    # ================================================================== 1) mise à jour des tables
    @app.get("/m/travaux/tables")
    @connecte
    def travaux_tables():
        s = acces_admin()
        cle_t = request.args.get("t") or next(iter(ref.TABLES))
        if cle_t not in ref.TABLES:
            abort(404)
        t = ref.table(cle_t)
        q = request.args.get("q", "").strip()
        liste = ref.lister(conn(), s, t.cle, q)
        lignes = liste["lignes"]
        tronque = len(lignes) > LIMITE_LIGNES
        rows = [dict(l, k=cle_texte(l["cle"]), nom=" - ".join(v for v in l["valeurs"][:2] if v)) for l in lignes[:LIMITE_LIGNES]]
        return render_template("travaux_tables.html", **contexte(
            s, "tables", tables=list(ref.TABLES.values()), t=t, q=q, colonnes=liste["colonnes"], lignes=rows, total=len(lignes),
            tronque=tronque, limite=LIMITE_LIGNES, inactifs=sum(1 for l in lignes if l["actif"] is False)))

    def champs_formulaire(t, modification, valeurs=None, brut=None):
        """Champs du formulaire, construits d'après la description de la table (comme l'écran Windows).
        valeurs : saisie à remettre après une erreur ; brut : ligne enregistrée (modification)."""
        brut = brut or {}
        defauts = {} if modification else ref.valeurs_par_defaut(t.cle)
        resultat = []
        for c in t.champs:
            if c.auto or (c.genere and not modification):
                continue
            fige = modification and c.cle
            if valeurs is not None:
                v = valeurs.get(c.nom, [] if c.multiple else "")
            elif modification:
                v = ref.afficher_valeur(c, brut.get(c.nom)) if c.type != "oui_non" else bool(brut.get(c.nom, 0))
            else:
                v = defauts.get(c.nom, "")
            champ = dict(nom=c.nom, libelle=c.libelle, type=c.type, obligatoire=c.obligatoire, fige=fige, longueur=c.longueur,
                         multiple=c.multiple and not modification, options=[], valeur=v)
            if c.type == "oui_non":
                champ["valeur"] = bool(v) if valeurs is None else (v in (True, "1", "oui", "on"))
            elif c.type == "date":
                champ["valeur"] = _iso(str(v))
            elif c.type in ("choix", "reference"):
                if c.type == "choix":
                    paires = list(c.choix)
                else:
                    paires = ref.options(conn(), c.ref, inclure=brut.get(c.nom))
                choisis = {str(x) for x in (v if isinstance(v, list) else [v])}
                if valeurs is None and modification:
                    choisis = {str(brut.get(c.nom))}
                champ["options"] = [(str(val), lib, str(val) in choisis) for val, lib in paires]
            resultat.append(champ)
        return resultat

    def saisie_formulaire(t, modification):
        saisie = {}
        for c in t.champs:
            if c.auto or c.genere or (modification and c.cle):
                continue
            if c.type == "oui_non":
                saisie[c.nom] = request.form.get(c.nom) == "1"
            elif c.multiple and not modification:
                saisie[c.nom] = request.form.getlist(c.nom)
            else:
                saisie[c.nom] = request.form.get(c.nom, "")
        return saisie

    def page_formulaire(s, t, cle=None, valeurs=None, erreur="", code=200):
        modification = cle is not None
        brut = ref.lire(conn(), s, t.cle, cle) if modification else {}
        champs = champs_formulaire(t, modification, valeurs, brut)
        return render_template("travaux_formulaire.html", **contexte(
            s, "tables", t=t, champs=champs, modification=modification, k=cle_texte(cle) if modification else "",
            erreur=erreur)), code

    @app.get("/m/travaux/tables/nouveau")
    @connecte
    def travaux_nouveau():
        s = acces_admin()
        t = lire_table()
        if not t.peut_creer:
            abort(403)
        return page_formulaire(s, t)[0]

    @app.post("/m/travaux/tables/nouveau")
    @connecte
    def travaux_nouveau_envoyer():
        poster()
        s = acces_admin()
        t = lire_table()
        saisie = saisie_formulaire(t, False)
        try:
            ref.enregistrer(conn(), s, t.cle, saisie)
        except PermissionError:
            abort(403)
        except ref.ErreurRef as e:
            return page_formulaire(s, t, valeurs=saisie, erreur=str(e), code=400)
        return redirect(url_for("travaux_tables", t=t.cle, ok="ajoute"))

    @app.get("/m/travaux/tables/modifier")
    @connecte
    def travaux_modifier():
        s = acces_admin()
        t = lire_table()
        if not t.peut_modifier:
            abort(403)
        try:
            return page_formulaire(s, t, lire_cle(t))[0]
        except ref.ErreurRef:
            abort(404)

    @app.post("/m/travaux/tables/modifier")
    @connecte
    def travaux_modifier_envoyer():
        poster()
        s = acces_admin()
        t = lire_table()
        cle = lire_cle(t)
        saisie = saisie_formulaire(t, True)
        try:
            ref.enregistrer(conn(), s, t.cle, saisie, cle)
        except PermissionError:
            abort(403)
        except ref.ErreurRef as e:
            try:
                return page_formulaire(s, t, cle, valeurs=saisie, erreur=str(e), code=400)
            except ref.ErreurRef:
                abort(404)
        return redirect(url_for("travaux_tables", t=t.cle, ok="modifie"))

    @app.post("/m/travaux/tables/supprimer")
    @connecte
    def travaux_supprimer():
        """Première demande : suppression simple ; si la donnée est utilisée, page d'aperçu des données liées (avec confirmation)."""
        poster()
        s = acces_admin()
        t = lire_table()
        cle = lire_cle(t)
        avec_liees = request.form.get("avec_liees") == "1"
        try:
            nom = nom_ligne(t, cle)
            if avec_liees:
                ref.supprimer_avec_liees(conn(), s, t.cle, cle)
                return redirect(url_for("travaux_tables", t=t.cle, ok="supprime_liees"))
            ref.supprimer(conn(), s, t.cle, cle)
            return redirect(url_for("travaux_tables", t=t.cle, ok="supprime"))
        except PermissionError:
            abort(403)
        except ref.ErreurUtilisee as e:
            apercu = ref.apercu_suppression(conn(), s, t.cle, cle)
            return render_template("travaux_supprimer.html", **contexte(
                s, "tables", t=t, k=cle_texte(cle), nom=nom, apercu=apercu, message=str(e)))
        except ref.ErreurRef as e:
            return render_template("erreur.html", cfg=config, titre="Opération impossible", texte=str(e)), 400

    @app.post("/m/travaux/tables/etat")
    @connecte
    def travaux_etat():
        poster()
        s = acces_admin()
        t = lire_table()
        cle = lire_cle(t)
        actif = request.form.get("action") == "reactiver"
        try:
            ref.changer_etat(conn(), s, t.cle, cle, actif)
        except PermissionError:
            abort(403)
        except ref.ErreurRef as e:
            return render_template("erreur.html", cfg=config, titre="Opération impossible", texte=str(e)), 400
        return redirect(url_for("travaux_tables", t=t.cle, ok="reactive" if actif else "desactive"))

    @app.route("/m/travaux/tables/annuler-recu", methods=["GET", "POST"])
    @connecte
    def travaux_annuler_recu():
        s = acces_admin()
        t = ref.table("paiements")
        cle = lire_cle(t)
        n_recu = str(cle[0])
        erreur = ""
        if request.method == "POST":
            poster()
            try:
                ref.annuler_paiement(conn(), s, n_recu, request.form.get("motif", ""))
                return redirect(url_for("travaux_tables", t="paiements", ok="annule"))
            except PermissionError:
                abort(403)
            except ref.ErreurRef as e:
                erreur = str(e)
        return render_template("travaux_annuler.html", **contexte(s, "tables", t=t, k=cle_texte(cle), n_recu=n_recu, erreur=erreur,
                                                                   motif=request.form.get("motif", "")))

    # ================================================================== 2) structure de la base
    def page_structure(s, resultat=None, integrite=None, erreur=""):
        a = migrations.analyse_admin(conn(), s)
        total = sum(1 for t in a.tables if t.statut != "INCONNUE")
        return render_template("travaux_structure.html", **contexte(
            s, "structure", a=a, total=total, a_faire=a.lignes_a_faire() if a.a_faire else [], resultat=resultat,
            integrite=integrite, erreur=erreur))

    @app.get("/m/travaux/structure")
    @connecte
    def travaux_structure():
        return page_structure(acces_admin())

    @app.post("/m/travaux/structure/maj")
    @connecte
    def travaux_structure_maj():
        poster()
        s = acces_admin()
        try:
            actions = migrations.mise_a_jour_manuelle(conn(), s)
        except PermissionError:
            abort(403)
        except migrations.ErreurMiseAJour as e:
            return page_structure(s, erreur=str(e))
        return page_structure(s, resultat=actions or [])

    @app.post("/m/travaux/structure/integrite")
    @connecte
    def travaux_structure_integrite():
        poster()
        s = acces_admin()
        try:
            return page_structure(s, integrite=migrations.controle_integrite(conn(), s))
        except PermissionError:
            abort(403)

    # ================================================================== 3) authentification et mots de passe
    def etat_compte(c):
        if not c["ACTIF"]:
            return "Désactivé", "inactif"
        if c["BLOQUE_JUSQUA"] and lire_iso(c["BLOQUE_JUSQUA"]) > maintenant():
            return "Bloqué (trop d'échecs)", "impaye"
        return ("Mot de passe provisoire", "partiel") if c["DOIT_CHANGER_MDP"] else ("Actif", "encours")

    def page_auth(s, erreur="", code=200):
        c = conn()
        codes = recuperation.codes_en_cours(c, s)
        comptes = []
        for u in acces.lister_utilisateurs(c, s):
            etat, classe = etat_compte(u)
            reste = codes.get(u["ID_USER"], 0)
            comptes.append(dict(id=u["ID_USER"], nom=u["NOM_COMPLET"], login=u["LOGIN"], poste=droits.libelle_role(c, u["ROLE"]),
                                etat=etat, classe=classe, actif=bool(u["ACTIF"]), soi=u["ID_USER"] == s.id_user,
                                code=security.formater_duree(reste) if reste > 0 else "", derniere=u["DERNIERE_CONNEXION"]))
        journal = [dict(date=l["DATE_HEURE"], login=l["LOGIN"] or "—", action=recuperation.LIBELLES_ACTIONS.get(l["ACTION"], l["ACTION"]),
                        detail=l["DETAIL"] or "") for l in recuperation.journal_authentification(c, s)]
        regles = dict(duree=config.DUREE_CODE_RECUPERATION_SEC, essais=config.MAX_ESSAIS_CODE, mdp_min=config.LONGUEUR_MIN_MDP,
                      mdp_max=config.LONGUEUR_MAX_MDP, echecs=config.MAX_ECHECS, blocage=config.DUREE_BLOCAGE_MIN,
                      blocage_max=config.BLOCAGE_MAX_MIN // 60, inactivite=config.DELAI_INACTIVITE_MIN)
        return render_template("travaux_auth.html", **contexte(s, "auth", comptes=comptes, journal=journal, regles=regles, erreur=erreur)), code

    @app.get("/m/travaux/auth")
    @connecte
    def travaux_auth():
        return page_auth(acces_admin())[0]

    def id_compte():
        try:
            return int(request.form.get("id", ""))
        except ValueError:
            abort(400)

    def page_secret(s, id_user, titre, secret, secondes, explication, annulable):
        cible = conn().execute("SELECT LOGIN, NOM_COMPLET FROM UTILISATEUR WHERE ID_USER = ?", (id_user,)).fetchone()
        rep = make_response(render_template("travaux_secret.html", **contexte(
            s, "auth", titre_secret=titre, secret=secret, secondes=secondes, explication=explication, annulable=annulable,
            id_user=id_user, nom=cible["NOM_COMPLET"], login=cible["LOGIN"])))
        rep.headers["Cache-Control"] = "no-store, private"
        return rep

    @app.post("/m/travaux/auth/code")
    @connecte
    def travaux_auth_code():
        poster()
        s = acces_admin()
        id_user = id_compte()
        try:
            code, secondes = recuperation.generer_code(conn(), s, id_user)
        except PermissionError:
            abort(403)
        except recuperation.ErreurRecuperation as e:
            return page_auth(s, str(e), 400)
        texte = recuperation.formater_code(code)
        code = None                                                  # on ne garde pas le code en mémoire
        return page_secret(s, id_user, "Code de récupération", texte, secondes,
                           "Après avoir vérifié son identité, dites ce code à l'utilisateur, de vive voix. Il le saisit sur l'écran de "
                           "connexion (« Mot de passe oublié ? »), avec son identifiant, puis choisit son nouveau mot de passe. "
                           "Ce code ne sera plus jamais affiché.", True)

    @app.post("/m/travaux/auth/annuler-code")
    @connecte
    def travaux_auth_annuler_code():
        poster()
        s = acces_admin()
        try:
            recuperation.annuler_code(conn(), s, id_compte())
        except PermissionError:
            abort(403)
        except recuperation.ErreurRecuperation as e:
            return page_auth(s, str(e), 400)
        return redirect(url_for("travaux_auth", ok="code_annule"))

    @app.post("/m/travaux/auth/provisoire")
    @connecte
    def travaux_auth_provisoire():
        poster()
        s = acces_admin()
        id_user = id_compte()
        try:
            mdp = acces.reinitialiser_mdp(conn(), s, id_user)
        except PermissionError:
            abort(403)
        except acces.ErreurAcces as e:
            return page_auth(s, str(e), 400)
        return page_secret(s, id_user, "Nouveau mot de passe provisoire", mdp, 0,
                           "Communiquez-le à l'utilisateur, de vive voix. Il devra le changer à sa prochaine connexion. L'ancien mot de "
                           "passe ne fonctionne plus. Ce mot de passe ne sera plus jamais affiché.", False)

    @app.post("/m/travaux/auth/debloquer")
    @connecte
    def travaux_auth_debloquer():
        poster()
        s = acces_admin()
        try:
            acces.debloquer(conn(), s, id_compte())
        except PermissionError:
            abort(403)
        except acces.ErreurAcces as e:
            return page_auth(s, str(e), 400)
        return redirect(url_for("travaux_auth", ok="debloque"))

    # ---- page publique : l'utilisateur saisit le code reçu de l'Administrateur
    @app.route("/mot-de-passe-oublie", methods=["GET", "POST"])
    def mot_de_passe_oublie():
        erreur, fait = "", False
        saisie = {"login": request.form.get("login", "")}
        if request.method == "POST":
            poster()
            adresse = request.remote_addr or "?"
            if sessions_web.trop_d_echecs(adresse):
                erreur = "Trop d'essais depuis cet appareil. Patientez quelques minutes."
            else:
                try:
                    recuperation.recuperer_mdp(conn(), request.form.get("login", ""), request.form.get("code", ""),
                                               request.form.get("nouveau", ""), request.form.get("confirmation", ""))
                    fait = True
                except recuperation.ErreurRecuperation as e:
                    sessions_web.noter_echec(adresse)
                    erreur = str(e)
        return render_template("oubli.html", cfg=config, erreur=erreur, fait=fait, saisie=saisie)

    # ================================================================== 4) sauvegarde
    def page_sauvegarde(s, erreur="", code=200):
        liste = [dict(nom=b["nom"], date=b["date"], taille=formater_taille(b["taille"]), contenu=description_contenu(b["manifeste"]))
                 for b in sauvegarde.lister(sauvegarde.dossier_defaut())]
        return render_template("travaux_sauvegarde.html", **contexte(s, "sauvegarde", liste=liste, erreur=erreur)), code

    @app.get("/m/travaux/sauvegarde")
    @connecte
    def travaux_sauvegarde():
        return page_sauvegarde(acces_admin())[0]

    @app.post("/m/travaux/sauvegarde/creer")
    @connecte
    def travaux_sauvegarde_creer():
        poster()
        s = acces_admin()
        try:
            with _VERROU_SAUVEGARDE:
                sauvegarde.sauvegarder(conn(), s)
        except PermissionError:
            abort(403)
        except sauvegarde.ErreurSauvegarde as e:
            return page_sauvegarde(s, str(e), 400)
        return redirect(url_for("travaux_sauvegarde", ok="sauvegarde"))

    @app.get("/m/travaux/sauvegarde/telecharger")
    @connecte
    def travaux_sauvegarde_telecharger():
        s = acces_admin()
        nom = request.args.get("f", "")
        choisie = next((b for b in sauvegarde.lister(sauvegarde.dossier_defaut()) if b["nom"] == nom), None)      # seulement un fichier de la liste
        if choisie is None:
            abort(404)
        with open(choisie["chemin"], "rb") as f:
            contenu = f.read()
        with conn():
            database.journaliser(conn(), s.id_user, s.login, "SAUVEGARDE_TELECHARGEE", choisie["nom"])
        rep = make_response(contenu)
        rep.headers["Content-Type"] = "application/octet-stream"
        rep.headers["Content-Disposition"] = f'attachment; filename="{Path(choisie["nom"]).name}"'
        return rep

    # ================================================================== 5) restauration
    def _sauvegarde_nommee(nom):
        """Fichier de la liste des sauvegardes du serveur (jamais un chemin libre), ou None."""
        return next((b for b in sauvegarde.lister(sauvegarde.dossier_defaut()) if b["nom"] == nom), None)

    def page_restauration(s, erreur="", code=200):
        liste = [dict(nom=b["nom"], date=b["date"], taille=formater_taille(b["taille"]), contenu=description_contenu(b["manifeste"]))
                 for b in sauvegarde.lister(sauvegarde.dossier_defaut())]
        return render_template("travaux_restauration.html", **contexte(s, "restauration", liste=liste, erreur=erreur,
                                                                       taille_max=TAILLE_MAX_IMPORT // (1024 * 1024))), code

    def page_restauration_examen(s, nom, erreur="", code=200):
        choisie = _sauvegarde_nommee(nom)
        if choisie is None:
            abort(404)
        examen, probleme = None, ""
        try:
            examen = sauvegarde.examiner(choisie["chemin"])
        except sauvegarde.ErreurSauvegarde as e:
            probleme = str(e)
        examen_aff = None
        if examen:
            examen_aff = dict(examen, date_aff=formater_horodatage(examen["date"]) if examen["date"] else "")
        return render_template("travaux_restauration_examen.html", **contexte(
            s, "restauration", nom=choisie["nom"], examen=examen_aff, probleme=probleme, erreur=erreur,
            mot=MOT_CONFIRMATION)), code

    @app.get("/m/travaux/restauration")
    @connecte
    def travaux_restauration():
        return page_restauration(acces_admin())[0]

    @app.get("/m/travaux/restauration/examiner")
    @connecte
    def travaux_restauration_examiner():
        s = acces_admin()
        return page_restauration_examen(s, request.args.get("f", ""))[0]

    @app.post("/m/travaux/restauration/importer")
    @connecte
    def travaux_restauration_importer():
        poster()
        s = acces_admin()
        request.max_content_length = TAILLE_MAX_IMPORT          # limite propre à cet envoi
        envoi = request.files.get("fichier")
        if envoi is None or not envoi.filename:
            return page_restauration(s, "Choisissez un fichier de sauvegarde (.csfbak).", 400)
        if not envoi.filename.lower().endswith(config.EXTENSION_SAUVEGARDE):
            return page_restauration(s, f"Le fichier doit être une sauvegarde du programme ({config.EXTENSION_SAUVEGARDE}).", 400)
        dossier = sauvegarde.dossier_defaut()
        with _VERROU_SAUVEGARDE:
            cible = sauvegarde._nom_libre(dossier, "Importee")
            try:
                envoi.save(cible)
                sauvegarde.examiner(cible)                  # refuse tout fichier abîmé, modifié ou étranger
            except sauvegarde.ErreurSauvegarde as e:
                cible.unlink(missing_ok=True)
                return page_restauration(s, str(e), 400)
            except OSError:
                cible.unlink(missing_ok=True)
                return page_restauration(s, "Le fichier n'a pas pu être enregistré sur le serveur.", 400)
        with conn():
            database.journaliser(conn(), s.id_user, s.login, "SAUVEGARDE_IMPORTEE", cible.name)
        return redirect(url_for("travaux_restauration_examiner", f=cible.name, ok="importee"))

    @app.post("/m/travaux/restauration/restaurer")
    @connecte
    def travaux_restauration_restaurer():
        poster()
        s = acces_admin()
        nom = request.form.get("f", "")
        if _sauvegarde_nommee(nom) is None:
            abort(404)
        if request.form.get("confirmation", "").strip() != MOT_CONFIRMATION:
            return page_restauration_examen(s, nom, f"Pour confirmer, tapez exactement {MOT_CONFIRMATION}.", 400)
        ligne = conn().execute("SELECT MDP_HASH FROM UTILISATEUR WHERE ID_USER = ? AND ACTIF = 1", (s.id_user,)).fetchone()
        if not ligne or not security.verifier_mdp(request.form.get("mdp", ""), ligne["MDP_HASH"]):
            return page_restauration_examen(s, nom, "Mot de passe incorrect : restauration non faite.", 400)
        choisie = _sauvegarde_nommee(nom)
        try:
            with _VERROU_SAUVEGARDE:
                sauvegarde.restaurer(conn(), s, choisie["chemin"])
        except PermissionError:
            abort(403)
        except sauvegarde.ErreurSauvegarde as e:
            return page_restauration_examen(s, nom, str(e), 400)
        sessions_web.fermer_tout()                         # les comptes peuvent différer : tout le monde se reconnecte
        rep = make_response(redirect(url_for("connexion")))
        rep.delete_cookie("gestisc_session", path="/")
        return rep

    # ================================================================== 6) mise à jour du programme
    def dossier_maj():
        d = config.dossier_donnees() / "mises_a_jour_recues"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def fichier_maj(nom):
        """Fichier reçu (dossier réservé, nom simple) ou None : jamais un chemin libre."""
        if not nom or nom != Path(nom).name or not nom.endswith(miseajour.EXTENSION):
            return None
        chemin = dossier_maj() / nom
        return chemin if chemin.is_file() else None

    def page_maj(s, erreur="", code=200, **plus):
        archives = [dict(a, date_aff=formater_horodatage(a["date"])) for a in miseajour.lister_archives()]
        return render_template("travaux_miseajour.html", **contexte(
            s, "miseajour", erreur=erreur, version=config.VERSION, archives=archives, taille_max=TAILLE_MAX_MAJ // (1024 * 1024),
            **plus)), code

    @app.get("/m/travaux/miseajour")
    @connecte
    def travaux_miseajour():
        return page_maj(acces_admin())[0]

    @app.post("/m/travaux/miseajour/controler")
    @connecte
    def travaux_miseajour_controler():
        poster()
        s = acces_admin()
        request.max_content_length = TAILLE_MAX_MAJ
        envoi = request.files.get("fichier")
        if envoi is None or not envoi.filename or not envoi.filename.lower().endswith(miseajour.EXTENSION):
            return page_maj(s, f"Choisissez un fichier de mise à jour ({miseajour.EXTENSION}).", 400)
        cle_maj = request.form.get("cle", "")
        nom = f"maj_{maintenant().strftime('%Y%m%d-%H%M%S')}_{secrets.token_hex(3)}{miseajour.EXTENSION}"
        cible = dossier_maj() / nom
        try:
            envoi.save(cible)
            manifeste = miseajour.examiner(cible, cle_maj)
        except miseajour.ErreurMiseAJour as e:
            cible.unlink(missing_ok=True)
            with conn():
                database.journaliser(conn(), s.id_user, s.login, "MISE_A_JOUR_REFUSEE", str(e))
            return page_maj(s, str(e), 400)
        except OSError:
            cible.unlink(missing_ok=True)
            return page_maj(s, "Le fichier n'a pas pu être enregistré sur le serveur.", 400)
        return page_maj(s, controle=dict(nom=nom, version=manifeste["version"], nb=manifeste["nb_fichiers"],
                                         empreinte=manifeste["empreinte"], plus_recente=
                                         miseajour._version_tuple(manifeste["version"]) > miseajour._version_tuple(config.VERSION)))[0]

    @app.post("/m/travaux/miseajour/installer")
    @connecte
    def travaux_miseajour_installer():
        poster()
        s = acces_admin()
        nom = request.form.get("f", "")
        chemin = fichier_maj(nom)
        if chemin is None:
            return page_maj(s, "Fichier de mise à jour introuvable : envoyez-le de nouveau.", 400)
        try:
            with _VERROU_SAUVEGARDE:
                r = miseajour.installer(conn(), s, chemin, request.form.get("cle", ""), request.form.get("mdp", ""))
        except PermissionError:
            abort(403)
        except (miseajour.ErreurMiseAJour, sauvegarde.ErreurSauvegarde) as e:
            return page_maj(s, str(e), 400, controle=_controle_depuis(chemin, nom))
        chemin.unlink(missing_ok=True)
        return page_maj(s, resultat=dict(r, recharge=miseajour.recharger_web()))[0]

    def _controle_depuis(chemin, nom):
        """Résumé affiché de nouveau après un refus (l'Administrateur peut corriger la clé ou le mot de passe)."""
        try:
            with zipfile.ZipFile(chemin) as z:
                m = json.loads(z.read(miseajour.NOM_MANIFESTE).decode("utf-8"))
            return dict(nom=nom, version=m["version"], nb=len(m["fichiers"]), empreinte=miseajour.empreinte(m), plus_recente=True)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            return None

    @app.post("/m/travaux/miseajour/annuler")
    @connecte
    def travaux_miseajour_annuler():
        poster()
        s = acces_admin()
        chemin = fichier_maj(request.form.get("f", ""))
        if chemin is not None:
            chemin.unlink(missing_ok=True)
        return redirect(url_for("travaux_miseajour"))

    @app.post("/m/travaux/miseajour/revenir")
    @connecte
    def travaux_miseajour_revenir():
        poster()
        s = acces_admin()
        try:
            with _VERROU_SAUVEGARDE:
                r = miseajour.revenir(conn(), s, request.form.get("nom", ""), request.form.get("mdp", ""))
        except PermissionError:
            abort(403)
        except miseajour.ErreurMiseAJour as e:
            return page_maj(s, str(e), 400)
        return page_maj(s, resultat=dict(r, retour=True, recharge=miseajour.recharger_web()))[0]


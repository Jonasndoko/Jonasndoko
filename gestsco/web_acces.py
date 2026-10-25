"""Module « Gestionnaire d'accès » en ligne (pages web), réservé à l'Administrateur. Toute la logique métier reste dans acces.py,
droits.py et sections.py, exactement comme dans le logiciel Windows (ecrans_acces.py) : ici on ne fait que les pages, et on
re-vérifie tout côté serveur (compte Administrateur relu dans la base à chaque action, chaque opération journalisée).

Trois fonctionnalités, comme dans le logiciel Windows :
  1. Utilisateurs     : créer un compte (mot de passe provisoire), modifier (nom, rôle, état), activer / désactiver,
                        nouveau mot de passe provisoire, débloquer ;
  2. Rôles            : les 8 postes de base et ceux créés par l'Administrateur ; droits de base de chaque rôle ;
  3. Autorisations    : droits de chaque utilisateur, module par module, et sections de l'école qui lui sont ouvertes.

Particularités de la version web :
  - un mot de passe provisoire est affiché dans la réponse à la demande, une seule fois, jamais placé dans une adresse ni dans la
    session ni dans le journal ;
  - la matrice des droits voyage sous forme de cases « module:droit » ; chaque couple est revalidé par droits.normaliser.
"""
from flask import abort, make_response, redirect, render_template, request, url_for

import acces
import config
import droits
import modules
import sections
from database import lire_iso, maintenant
from web_travaux import formater_horodatage

ONGLETS = (
    ("utilisateurs", "Utilisateurs", "acces_utilisateurs"),
    ("roles", "Rôles", "acces_roles"),
    ("autorisations", "Autorisations", "acces_autorisations"),
)

MESSAGES_OK = {
    "cree": "Compte créé.", "modifie": "Compte modifié.", "active": "Compte activé.", "desactive": "Compte désactivé : il ne peut plus se connecter, son historique est conservé.",
    "debloque": "Compte débloqué.", "role_cree": "Rôle créé. Cochez ses droits de base puis enregistrez.", "role_supprime": "Rôle supprimé.",
    "droits_role": "Droits de base du rôle enregistrés.", "droits_role_appliques": "Droits de base enregistrés et appliqués aux comptes existants de ce rôle.",
    "autorisations": "Autorisations enregistrées. Effet immédiat, même pour une personne déjà connectée.",
    "defaut": "Droits de base du rôle rétablis.",
}


def enregistrer(app, conn, session_courante, connecte, origine_ok):
    """Ajoute les routes /m/acces/... à l'application (paramètres venus d'app_web.creer_app)."""
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
        ctx = dict(s=s, cfg=config, titre="Gestionnaire d'accès", menu_utile=modules.menu_utile(conn(), s), onglet=onglet,
                   onglets=[(c, lib, url_for(ep)) for c, lib, ep in ONGLETS], ok=MESSAGES_OK.get(request.args.get("ok", ""), ""),
                   erreur="")
        ctx.update(plus)
        return ctx

    def id_compte():
        try:
            return int(request.values.get("id", ""))
        except ValueError:
            abort(400)

    def lire_matrice():
        """Couples (module, droit) cochés dans le formulaire (cases « module:droit »). Une valeur mal formée -> 400."""
        accordes = set()
        for v in request.form.getlist("d"):
            module, _, droit = v.partition(":")
            if not module or not droit:
                abort(400)
            accordes.add((module, droit))
        return accordes

    def matrice(accordes):
        """Données de la matrice : colonnes (droits utilisés) et lignes (module, titre, [(valeur, coché, possible)])."""
        colonnes = [d for d in config.DROITS if any(d in p for _t, p in config.MODULES_DROITS.values())]
        lignes = [dict(titre=titre, cases=[dict(valeur=f"{m}:{d}", coche=(m, d) in accordes, possible=d in possibles) for d in colonnes])
                  for m, (titre, possibles) in config.MODULES_DROITS.items()]
        return dict(colonnes=[config.LIBELLE_DROITS[d] for d in colonnes], lignes=lignes)

    def libelle_role(code):
        return droits.libelle_role(conn(), code)

    def etat_compte(c):
        if not c["ACTIF"]:
            return "Désactivé", "inactif"
        if c["BLOQUE_JUSQUA"] and lire_iso(c["BLOQUE_JUSQUA"]) > maintenant():
            return "Bloqué (trop d'échecs)", "impaye"
        return ("Mot de passe provisoire", "partiel") if c["DOIT_CHANGER_MDP"] else ("Actif", "solde")

    def page_secret(s, id_user, titre, secret, explication):
        cible = conn().execute("SELECT LOGIN, NOM_COMPLET FROM UTILISATEUR WHERE ID_USER = ?", (id_user,)).fetchone()
        rep = make_response(render_template("acces_secret.html", **contexte(
            s, "utilisateurs", titre_secret=titre, secret=secret, explication=explication, nom=cible["NOM_COMPLET"], login=cible["LOGIN"])))
        rep.headers["Cache-Control"] = "no-store, private"
        return rep

    @app.get("/m/acces")
    @connecte
    def acces_accueil():
        acces_admin()
        return redirect(url_for("acces_utilisateurs"))

    # ================================================================== 1) utilisateurs
    def page_utilisateurs(s, erreur="", code=200, saisie=None, modifier=None):
        c = conn()
        comptes = []
        for u in acces.lister_utilisateurs(c, s):
            etat, classe = etat_compte(u)
            comptes.append(dict(id=u["ID_USER"], nom=u["NOM_COMPLET"], login=u["LOGIN"], role=u["ROLE"], poste=libelle_role(u["ROLE"]), etat=etat,
                                classe=classe, actif=bool(u["ACTIF"]), soi=u["ID_USER"] == s.id_user, derniere=u["DERNIERE_CONNEXION"]))
        cible = next((x for x in comptes if x["id"] == modifier), None) if modifier is not None else None
        if modifier is not None and cible is None:
            abort(404)
        return render_template("acces_utilisateurs.html", **contexte(
            s, "utilisateurs", comptes=comptes, roles=droits.roles(c), saisie=saisie or {}, cible=cible, erreur=erreur)), code

    @app.get("/m/acces/utilisateurs")
    @connecte
    def acces_utilisateurs():
        s = acces_admin()
        modifier = request.args.get("modifier")
        if modifier is not None:
            try:
                modifier = int(modifier)
            except ValueError:
                abort(400)
        return page_utilisateurs(s, modifier=modifier)[0]

    @app.post("/m/acces/utilisateurs/nouveau")
    @connecte
    def acces_nouveau():
        poster()
        s = acces_admin()
        f = request.form
        try:
            id_user, mdp = acces.creer_compte(conn(), s, f.get("login", ""), f.get("nom", ""), f.get("poste", ""))
        except PermissionError:
            abort(403)
        except acces.ErreurAcces as e:
            return page_utilisateurs(s, str(e), 400, saisie=dict(login=f.get("login", ""), nom=f.get("nom", ""), poste=f.get("poste", "")))
        texte, mdp = mdp, None                                       # on ne garde pas le secret en mémoire plus que nécessaire
        return page_secret(s, id_user, "Compte créé : mot de passe provisoire", texte,
                           "Communiquez-le à l'utilisateur, de vive voix. Il devra le changer à sa première connexion. "
                           "Ce mot de passe ne sera plus jamais affiché.")

    @app.post("/m/acces/utilisateurs/modifier")
    @connecte
    def acces_modifier():
        poster()
        s = acces_admin()
        id_user = id_compte()
        f = request.form
        try:
            acces.modifier_compte(conn(), s, id_user, f.get("nom", ""), f.get("poste", ""), f.get("actif") == "1")
        except PermissionError:
            abort(403)
        except acces.ErreurAcces as e:
            if str(e) == "Compte introuvable.":
                abort(404)
            return page_utilisateurs(s, str(e), 400, modifier=id_user)
        return redirect(url_for("acces_utilisateurs", ok="modifie"))

    @app.post("/m/acces/utilisateurs/etat")
    @connecte
    def acces_etat():
        poster()
        s = acces_admin()
        actif = request.form.get("actif") == "1"
        try:
            acces.changer_etat_compte(conn(), s, id_compte(), actif)
        except PermissionError:
            abort(403)
        except acces.ErreurAcces as e:
            return page_utilisateurs(s, str(e), 400)
        return redirect(url_for("acces_utilisateurs", ok="active" if actif else "desactive"))

    @app.post("/m/acces/utilisateurs/mdp")
    @connecte
    def acces_mdp():
        poster()
        s = acces_admin()
        id_user = id_compte()
        try:
            mdp = acces.reinitialiser_mdp(conn(), s, id_user)
        except PermissionError:
            abort(403)
        except acces.ErreurAcces as e:
            return page_utilisateurs(s, str(e), 400)
        return page_secret(s, id_user, "Nouveau mot de passe provisoire", mdp,
                           "Communiquez-le à l'utilisateur, de vive voix. Il devra le changer à sa prochaine connexion. L'ancien mot de "
                           "passe ne fonctionne plus. Ce mot de passe ne sera plus jamais affiché.")

    @app.post("/m/acces/utilisateurs/debloquer")
    @connecte
    def acces_debloquer():
        poster()
        s = acces_admin()
        try:
            acces.debloquer(conn(), s, id_compte())
        except PermissionError:
            abort(403)
        except acces.ErreurAcces as e:
            return page_utilisateurs(s, str(e), 400)
        return redirect(url_for("acces_utilisateurs", ok="debloque"))

    # ================================================================== 2) rôles
    def page_roles(s, choisi=None, erreur="", code=200, saisie=None, accordes=None):
        liste = acces.lister_roles(conn(), s)
        par_code = {r["role"]: r for r in liste}
        courant = par_code.get(choisi)
        lignes = [dict(code=r["role"], libelle=r["libelle"], nb=r["nb_utilisateurs"], resume=droits.resume(r["droits"]), de_base=r["de_base"])
                  for r in liste]
        return render_template("acces_roles.html", **contexte(
            s, "roles", roles=lignes, courant=courant, saisie=saisie or {}, erreur=erreur,
            matrice=matrice(accordes if accordes is not None else (courant["droits"] if courant else set())))), code

    @app.get("/m/acces/roles")
    @connecte
    def acces_roles():
        s = acces_admin()
        choisi = request.args.get("r", "")
        if choisi and not droits.role_existe(conn(), choisi):
            abort(404)
        return page_roles(s, choisi)[0]

    @app.post("/m/acces/roles/nouveau")
    @connecte
    def acces_role_nouveau():
        poster()
        s = acces_admin()
        try:
            code = acces.creer_role(conn(), s, request.form.get("libelle", ""))
        except PermissionError:
            abort(403)
        except acces.ErreurAcces as e:
            return page_roles(s, None, str(e), 400, saisie=dict(libelle=request.form.get("libelle", "")))
        return redirect(url_for("acces_roles", r=code, ok="role_cree"))

    @app.post("/m/acces/roles/supprimer")
    @connecte
    def acces_role_supprimer():
        poster()
        s = acces_admin()
        code = request.form.get("r", "")
        try:
            acces.supprimer_role(conn(), s, code)
        except PermissionError:
            abort(403)
        except acces.ErreurAcces as e:
            return page_roles(s, code if droits.role_existe(conn(), code) else None, str(e), 400)
        return redirect(url_for("acces_roles", ok="role_supprime"))

    @app.post("/m/acces/roles/droits")
    @connecte
    def acces_role_droits():
        poster()
        s = acces_admin()
        code = request.form.get("r", "")
        if not droits.role_existe(conn(), code):
            abort(404)
        accordes = lire_matrice()
        appliquer = request.form.get("appliquer") == "1"
        try:
            acces.definir_droits_role(conn(), s, code, accordes, appliquer)
        except PermissionError:
            abort(403)
        except acces.ErreurAcces as e:
            return page_roles(s, code, str(e), 400, accordes=accordes)
        return redirect(url_for("acces_roles", r=code, ok="droits_role_appliques" if appliquer else "droits_role"))

    # ================================================================== 3) autorisations
    def page_autorisations(s, choisi=None, erreur="", code=200, accordes=None, ouvertes=None):
        c = conn()
        comptes = [dict(id=u["ID_USER"], nom=u["NOM_COMPLET"], login=u["LOGIN"], poste=libelle_role(u["ROLE"]), actif=bool(u["ACTIF"]),
                        sections=sections.resume(c, u["ID_USER"]), droits=droits.resume(droits.droits_utilisateur(c, u["ID_USER"])))
                   for u in acces.lister_utilisateurs(c, s)]
        courant = next((x for x in comptes if x["id"] == choisi), None) if choisi is not None else None
        if choisi is not None and courant is None:
            abort(404)
        donnees = {}
        if courant:
            role = c.execute("SELECT ROLE FROM UTILISATEUR WHERE ID_USER = ?", (choisi,)).fetchone()["ROLE"]
            courant["admin"] = role == config.ADMINISTRATEUR
            if accordes is None:
                accordes = acces.lire_droits(c, s, choisi)
            if ouvertes is None:
                ouvertes = sections.sections_explicites(c, choisi) or sections.TOUTES
            donnees = dict(matrice=matrice(accordes), sections=[(k, lib, k in ouvertes) for k, lib in sections.SECTIONS])
        return render_template("acces_autorisations.html", **contexte(s, "autorisations", comptes=comptes, courant=courant, erreur=erreur, **donnees)), code

    @app.get("/m/acces/autorisations")
    @connecte
    def acces_autorisations():
        s = acces_admin()
        choisi = request.args.get("id")
        if choisi is not None:
            try:
                choisi = int(choisi)
            except ValueError:
                abort(400)
        return page_autorisations(s, choisi)[0]

    @app.post("/m/acces/autorisations/enregistrer")
    @connecte
    def acces_autorisations_enregistrer():
        poster()
        s = acces_admin()
        id_user = id_compte()
        accordes = lire_matrice()
        choisies = {k for k, _lib in sections.SECTIONS if k in request.form.getlist("s")}
        try:
            # tout est validé avant la première écriture : pas d'enregistrement à moitié fait
            droits.normaliser(accordes)
            if not choisies:
                raise sections.ErreurSection("Cochez au moins une section : Primaire, Secondaire et humanitaire, ou les deux.")
            sections.definir_sections(conn(), s, id_user, choisies)
            acces.definir_droits(conn(), s, id_user, accordes)
        except PermissionError:
            abort(403)
        except ValueError as e:
            return page_autorisations(s, id_user, str(e), 400, accordes=accordes, ouvertes=choisies)
        except (acces.ErreurAcces, sections.ErreurSection) as e:
            if str(e) == "Compte introuvable.":
                abort(404)
            return page_autorisations(s, id_user, str(e), 400, accordes=accordes, ouvertes=choisies)
        return redirect(url_for("acces_autorisations", id=id_user, ok="autorisations"))

    @app.post("/m/acces/autorisations/defaut")
    @connecte
    def acces_autorisations_defaut():
        poster()
        s = acces_admin()
        id_user = id_compte()
        try:
            acces.droits_par_defaut_du_poste(conn(), s, id_user)
        except PermissionError:
            abort(403)
        except acces.ErreurAcces as e:
            if str(e) == "Compte introuvable.":
                abort(404)
            return page_autorisations(s, id_user, str(e), 400)
        return redirect(url_for("acces_autorisations", id=id_user, ok="defaut"))

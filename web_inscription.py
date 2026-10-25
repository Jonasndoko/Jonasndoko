"""Module « Inscription » en ligne (pages web). Toute la logique métier reste dans inscription.py, comme dans le logiciel Windows :
ici on ne fait que les pages, et tout est re-vérifié côté serveur (droits, reçu de paiement, sections, étapes du dossier).

Trois onglets, comme dans le logiciel :
  1. Formulaire d'inscription (droit « Ajout ») : reçu des frais d'inscription (vérifiable avant d'enregistrer), identité, parcours,
     tuteur, classe souhaitée ; le candidat est mis sur la liste d'attente et sa fiche s'imprime en PDF ;
  2. Liste d'attente (droit « Lecture ») : par classe et par ordre d'arrivée, recherche, fiche PDF ;
  3. Validation et affectation (droit « Modification ») : note du test d'admission (>= seuil : dossier validé ; sinon refusé, définitif),
     puis affectation à une classe : le candidat devient élève (matricule, code QR) ; avis d'admission en PDF.

Règles propres à la version web :
  - le résultat du test et l'affectation passent par une page de confirmation (ils ne se modifient plus ensuite) ;
  - un double clic sur « Enregistrer » ne crée pas deux candidatures : le reçu ne vaut que pour un candidat, et si la même candidature
    vient d'être enregistrée par le même compte il y a moins de GARDE_DOUBLE_CLIC_S secondes, on renvoie vers elle.
"""
from datetime import timedelta

from flask import abort, make_response, redirect, render_template, request, url_for

import config
import donnees
import inscription
import modules
from database import lire_iso, maintenant
from inscription import ErreurInscription

GARDE_DOUBLE_CLIC_S = 60

ONGLETS = (("formulaire", "1   Formulaire d'inscription", "/m/inscription"),
           ("liste", "2   Liste d'attente", "/m/inscription/liste"),
           ("validation", "3   Validation et affectation", "/m/inscription/validation"))
RESERVE = {"formulaire": "Votre compte n'a pas le droit « Ajout » sur ce module.",
           "validation": "Votre compte n'a pas le droit « Modification » sur ce module."}

# Filtres de l'onglet Validation : (clé dans l'adresse, libellé, étapes affichées)
FILTRES = (("traiter", "À traiter (test ou affectation)", ("A_TESTER", "A_AFFECTER")),
           ("test", "Test à passer", ("A_TESTER",)),
           ("affecter", "Réussis, à affecter", ("A_AFFECTER",)),
           ("admis", "Admis (élèves)", ("ADMIS",)),
           ("refuses", "Refusés", ("REFUSE",)),
           ("tous", "Tous les candidats", None))
CHAMPS = ("n_recu", "nom", "postnom", "prenom", "sexe", "date_naissance", "lieu_naissance", "nationalite", "adresse", "telephone",
          "ecole_origine", "pourcent_origine", "doublant", "n_classe", "nom_tuteur", "tel_tuteur", "adresse_tuteur")


def onglets_autorises(conn, session) -> set:
    """Onglets utilisables par ce compte (droits relus dans la base) : même règle que le logiciel Windows."""
    if not inscription.peut(conn, session, "LECTURE"):
        return set()
    ouverts = {"liste"}
    if inscription.peut(conn, session, "AJOUT"):
        ouverts.add("formulaire")
    if inscription.peut(conn, session, "MODIFICATION"):
        ouverts.add("validation")
    return ouverts


def enregistrer(app, conn, session_courante, connecte, origine_ok):
    """Ajoute les routes /m/inscription/... à l'application. Les 4 derniers paramètres viennent d'app_web.creer_app."""

    # ------------------------------------------------------------------ utilitaires
    def contexte(onglet, **plus):
        s = session_courante()
        ctx = dict(s=s, cfg=config, titre="Inscription", menu_utile=modules.menu_utile(conn(), s),
                   autorises=onglets_autorises(conn(), s), onglets=ONGLETS, onglet=onglet, reserve=RESERVE)
        ctx.update(plus)
        return ctx

    def acces(onglet):
        """Session du compte, après vérification qu'il a le module et l'onglet. 403 sinon."""
        s = session_courante()
        if onglet not in onglets_autorises(conn(), s):
            abort(403)
        return s

    def poster():
        if not origine_ok():
            abort(403)

    def page(modele, onglet, statut=200, **plus):
        return make_response(render_template(modele, **contexte(onglet, **plus)), statut)

    def pdf(chemin, nom):
        with open(chemin, "rb") as f:
            rep = make_response(f.read())
        rep.headers["Content-Type"] = "application/pdf"
        rep.headers["Content-Disposition"] = f'inline; filename="{nom}"'
        return rep

    def entier(texte):
        texte = (texte or "").strip()
        return int(texte) if texte.isdigit() and len(texte) < 10 else None

    def recent(date_iso) -> bool:
        """Cette date (ISO) remonte-t-elle à moins de GARDE_DOUBLE_CLIC_S secondes ?"""
        return bool(date_iso) and lire_iso(date_iso) >= maintenant() - timedelta(seconds=GARDE_DOUBLE_CLIC_S)

    def erreur_page(e, statut=400):
        return render_template("erreur.html", cfg=config, titre="Opération impossible", texte=str(e)), statut

    # ================================================================== 1) FORMULAIRE D'INSCRIPTION
    def formulaire(statut=200, saisie=None, erreur="", succes="", recu=None, erreur_recu="", n_cand_ok=None):
        c, s = conn(), session_courante()
        classes = inscription.classes_proposees(c, s)
        avertissement = ""
        if not classes:
            avertissement = "Aucune classe active : l'Administrateur doit en ajouter une (Travaux techniques > Classes)."
        elif not inscription.types_frais_inscription(c):
            avertissement = ("Aucun type de frais n'est marqué « Frais d'inscription » : l'Administrateur doit le faire "
                             "(Travaux techniques > Types de frais). Sans cela, aucune candidature ne peut être validée.")
        saisie = saisie or {k: "" for k in CHAMPS}
        return page("inscription_formulaire.html", "formulaire", statut=statut, saisie=saisie, erreur=erreur, succes=succes,
                    recu=recu, erreur_recu=erreur_recu, classes=classes, avertissement=avertissement, n_cand_ok=n_cand_ok)

    def lire_saisie(source):
        return {k: (source.get(k) or "").strip() for k in CHAMPS}

    def saisie_metier(saisie):
        """Saisie du formulaire web -> dictionnaire attendu par inscription.enregistrer_candidature."""
        v = dict(saisie)
        v["doublant"] = {"1": True, "0": False}.get(saisie["doublant"])
        v["n_classe"] = entier(saisie["n_classe"])
        return v

    @app.get("/m/inscription")
    @connecte
    def inscription_accueil():
        s = session_courante()
        autorises = onglets_autorises(conn(), s)
        if "formulaire" not in autorises:
            if "liste" in autorises:
                return redirect(url_for("inscription_liste"))
            abort(403)
        succes, n_ok = "", None
        n = entier(request.args.get("ok"))
        if n is not None and conn().execute("SELECT 1 FROM CANDIDATURE WHERE N_CAND = ? AND ENREGISTRE_PAR = ?",
                                            (n, s.login)).fetchone():
            try:
                f = inscription.charger_candidature(conn(), s, n)
                succes = (f"Candidature {f['num_cand']} enregistrée : le candidat est sur la liste d'attente "
                          f"(position {f['rang']} dans sa classe).")
                n_ok = n
                if request.args.get("deja") == "1":
                    succes += " (Elle venait déjà d'être enregistrée : aucun doublon n'a été créé.)"
            except (ErreurInscription, PermissionError):
                pass
        return formulaire(succes=succes, n_cand_ok=n_ok)

    @app.post("/m/inscription/verifier-recu")
    @connecte
    def inscription_verifier_recu():
        poster()
        s = acces("formulaire")
        saisie = lire_saisie(request.form)
        recu, erreur_recu = None, ""
        try:
            recu = inscription.verifier_recu_pour_ecran(conn(), s, saisie["n_recu"])
        except ErreurInscription as e:
            erreur_recu = str(e)
        except PermissionError:
            abort(403)
        return formulaire(saisie=saisie, recu=recu, erreur_recu=erreur_recu)

    @app.post("/m/inscription/enregistrer")
    @connecte
    def inscription_enregistrer():
        poster()
        s = acces("formulaire")
        c = conn()
        saisie = lire_saisie(request.form)
        try:
            # double clic : la même candidature (même reçu) vient d'être enregistrée par ce compte
            if saisie["n_recu"]:
                n_recu = inscription.normaliser_recu(saisie["n_recu"])
                l = c.execute("SELECT N_CAND, DATE_ENREG FROM CANDIDATURE WHERE N_RECU = ? AND ENREGISTRE_PAR = ?",
                              (n_recu, s.login)).fetchone()
                if l and recent(l["DATE_ENREG"]):
                    return redirect(url_for("inscription_accueil", ok=l["N_CAND"], deja=1))
            r = inscription.enregistrer_candidature(c, s, saisie_metier(saisie))
        except ErreurInscription as e:
            recu, erreur_recu = None, ""
            if saisie["n_recu"]:                                  # montre aussi, sous le numéro, ce qui ne va pas avec le reçu
                try:
                    recu = inscription.verifier_recu(c, saisie["n_recu"])
                except ErreurInscription as e2:
                    erreur_recu = str(e2)
            return formulaire(400, saisie, str(e), recu=recu, erreur_recu=erreur_recu)
        except PermissionError as e:
            return formulaire(403, saisie, str(e))
        return redirect(url_for("inscription_accueil", ok=r["n_cand"]))

    # ================================================================== 2) LISTE D'ATTENTE
    @app.get("/m/inscription/liste")
    @connecte
    def inscription_liste():
        s = acces("liste")
        c = conn()
        classes = inscription.classes_proposees(c, s)
        n_classe = entier(request.args.get("classe"))
        if n_classe not in {n for n, _ in classes}:
            n_classe = None
        recherche = (request.args.get("q") or "").strip()[:80]
        erreur, liste = "", []
        try:
            liste = inscription.liste_attente(c, s, n_classe=n_classe, recherche=recherche)
        except ErreurInscription as e:
            erreur = str(e)
        except PermissionError:
            abort(403)
        return page("inscription_liste.html", "liste", liste=liste, erreur=erreur, classes=classes, n_classe=n_classe,
                    recherche=recherche, annee=donnees.annee_courante(c))

    @app.get("/m/inscription/fiche/<int:n_cand>/pdf")
    @connecte
    def inscription_fiche_pdf(n_cand):
        s = acces("liste")
        try:
            chemin = inscription.preparer_fiche_pdf(conn(), s, n_cand)
            fiche = inscription.charger_candidature(conn(), s, n_cand)
        except ErreurInscription as e:
            return erreur_page(e, 404)
        except PermissionError:
            abort(403)
        return pdf(chemin, f"Fiche_inscription_{fiche['num_cand'].replace('/', '-')}.pdf")

    # ================================================================== 3) VALIDATION ET AFFECTATION
    def charger(s, n_cand):
        """Candidature (dict) ou 404/403 : droit Lecture et section vérifiés par inscription.charger_candidature."""
        try:
            return inscription.charger_candidature(conn(), s, n_cand)
        except ErreurInscription:
            abort(404)
        except PermissionError:
            abort(403)

    def detail(n_cand, statut=200, erreur="", succes="", note=""):
        s = acces("validation")
        cand = charger(s, n_cand)
        classes = inscription.classes_proposees(conn(), s)
        defaut = cand["n_classe_affectee"] or cand["n_classe"]
        return page("inscription_decision.html", "validation", statut=statut, c=cand, erreur=erreur, succes=succes, note=note,
                    classes=classes, defaut_classe=defaut, seuil=inscription.seuil_reussite())

    @app.get("/m/inscription/validation")
    @connecte
    def inscription_validation():
        s = acces("validation")
        c = conn()
        cles = {f[0]: f for f in FILTRES}
        cle = request.args.get("filtre", "traiter")
        cle = cle if cle in cles else "traiter"
        recherche = (request.args.get("q") or "").strip()[:80]
        erreur, liste = "", []
        try:
            liste = inscription.liste_validation(c, s, recherche=recherche)
        except ErreurInscription as e:
            erreur = str(e)
        except PermissionError:
            abort(403)
        etapes = cles[cle][2]
        liste = [x for x in liste if etapes is None or x["etape"] in etapes]
        return page("inscription_validation.html", "validation", liste=liste, erreur=erreur, filtres=FILTRES,
                    filtre=cle, recherche=recherche, annee=donnees.annee_courante(c))

    @app.get("/m/inscription/validation/<int:n_cand>")
    @connecte
    def inscription_decision(n_cand):
        s = acces("validation")
        succes = ""
        ok = request.args.get("ok")
        if ok == "test":
            succes = "Résultat du test enregistré. Dossier validé : choisissez la classe puis « Valider et affecter »."
        elif ok == "refus":
            succes = "Résultat du test enregistré. Test échoué : la candidature est refusée."
        elif ok == "affecte":
            succes = "Candidat admis : c'est maintenant un élève (matricule ci-dessous)."
        return detail(n_cand, succes=succes)

    @app.post("/m/inscription/validation/<int:n_cand>/test/confirmer")
    @connecte
    def inscription_test_confirmer(n_cand):
        poster()
        s = acces("validation")
        cand = charger(s, n_cand)
        note_txt = (request.form.get("note") or "").strip()
        try:
            note = inscription.lire_note_test(note_txt)
            if cand["etape"] != "A_TESTER":
                raise ErreurInscription(f"Le test de la candidature {cand['num_cand']} ne peut plus être enregistré "
                                        f"({cand['libelle_etape'].lower()}).")
        except ErreurInscription as e:
            return detail(n_cand, 400, str(e), note=note_txt)
        seuil = inscription.seuil_reussite()
        return page("inscription_test_confirmer.html", "validation", c=cand, note=note, note_txt=note_txt, seuil=seuil,
                    reussi=note >= seuil)

    @app.post("/m/inscription/validation/<int:n_cand>/test")
    @connecte
    def inscription_test(n_cand):
        poster()
        s = acces("validation")
        charger(s, n_cand)
        note_txt = (request.form.get("note") or "").strip()
        l = conn().execute("SELECT RESULTAT_TEST, DATE_TEST, TEST_PAR FROM CANDIDATURE WHERE N_CAND = ?", (n_cand,)).fetchone()
        if l and l["RESULTAT_TEST"] and l["TEST_PAR"] == s.login and recent(l["DATE_TEST"]):     # double clic : déjà enregistré
            return redirect(url_for("inscription_decision", n_cand=n_cand, ok="test" if l["RESULTAT_TEST"] == "REUSSI" else "refus"))
        try:
            r = inscription.enregistrer_resultat_test(conn(), s, n_cand, note_txt)
        except ErreurInscription as e:
            return detail(n_cand, 400, str(e), note=note_txt)
        except PermissionError as e:
            return detail(n_cand, 403, str(e), note=note_txt)
        return redirect(url_for("inscription_decision", n_cand=n_cand, ok="test" if r["valide"] else "refus"))

    @app.post("/m/inscription/validation/<int:n_cand>/affecter/confirmer")
    @connecte
    def inscription_affecter_confirmer(n_cand):
        poster()
        s = acces("validation")
        cand = charger(s, n_cand)
        n_classe = entier(request.form.get("classe"))
        libelles = dict(inscription.classes_proposees(conn(), s))
        if cand["etape"] != "A_AFFECTER":
            return detail(n_cand, 400, f"La candidature {cand['num_cand']} ne peut pas être affectée "
                                       f"({cand['libelle_etape'].lower()}).")
        if n_classe not in libelles:
            return detail(n_cand, 400, "Choisissez la classe d'affectation.")
        return page("inscription_affecter_confirmer.html", "validation", c=cand, n_classe=n_classe, classe=libelles[n_classe])

    @app.post("/m/inscription/validation/<int:n_cand>/affecter")
    @connecte
    def inscription_affecter(n_cand):
        poster()
        s = acces("validation")
        charger(s, n_cand)
        l = conn().execute("SELECT STATUT, DATE_DECISION, DECISION_PAR FROM CANDIDATURE WHERE N_CAND = ?", (n_cand,)).fetchone()
        if l and l["STATUT"] == "ADMIS" and l["DECISION_PAR"] == s.login and recent(l["DATE_DECISION"]):   # double clic
            return redirect(url_for("inscription_decision", n_cand=n_cand, ok="affecte"))
        try:
            inscription.affecter_candidat(conn(), s, n_cand, entier(request.form.get("classe")))
        except ErreurInscription as e:
            return detail(n_cand, 400, str(e))
        except PermissionError as e:
            return detail(n_cand, 403, str(e))
        return redirect(url_for("inscription_decision", n_cand=n_cand, ok="affecte"))

    @app.get("/m/inscription/avis/<int:n_cand>/pdf")
    @connecte
    def inscription_avis_pdf(n_cand):
        s = acces("validation")
        try:
            chemin = inscription.preparer_avis_admission_pdf(conn(), s, n_cand)
            cand = inscription.charger_candidature(conn(), s, n_cand)
        except ErreurInscription as e:
            return erreur_page(e, 400)
        except PermissionError:
            abort(403)
        import identite
        return pdf(chemin, f"Avis_admission_{identite.nom_de_fichier(cand['matricule'])}.pdf")

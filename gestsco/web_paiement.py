"""Module « Paiement des frais » en ligne (pages web). Toute la logique métier reste dans paiements.py, donnees.py, sections.py et
droits.py, exactement comme dans le logiciel Windows : ici on ne fait que les pages, et on re-vérifie tout côté serveur.

Quatre onglets, comme dans le logiciel :
  - Élève : recherche, situation financière (consultation) et paiement d'un frais, ligne par ligne (percepteur seulement) ;
  - Inscription d'un candidat : paiement des frais d'inscription d'une personne qui n'a pas encore de matricule ;
  - Duplicata du reçu ;
  - Rapport journalier de caisse.

Règles propres à la version web :
  - l'enregistrement passe par une page de confirmation (équivalent de la boîte « Confirmer le paiement » du logiciel) ;
  - un double clic ne crée pas deux reçus : le formulaire de confirmation mémorise ce qui était déjà payé ; si cela a changé au
    moment d'enregistrer parce que CE paiement vient d'être enregistré, on renvoie vers son reçu au lieu d'en créer un second ;
  - le reçu ORIGINAL ne s'imprime que par le percepteur qui l'a établi, dans les DELAI_ORIGINAL_MIN minutes qui suivent
    (comme dans le logiciel, où il n'est proposé qu'au moment de l'enregistrement) ; ensuite, seul le duplicata est possible ;
  - l'accès à un élève ou à un reçu respecte les sections de l'école ouvertes au compte (primaire / secondaire et humanitaire).
"""
from datetime import datetime, timedelta

from flask import abort, make_response, redirect, render_template, request, url_for

import argent
import config
import donnees
import inscription
import modules
import paiements
import parents
import sections
from database import iso, journaliser, lire_iso, maintenant

DELAI_ORIGINAL_MIN = 30        # minutes pendant lesquelles le percepteur peut réimprimer le reçu original (bourrage de papier...)

ONGLETS = (("consultation", "Élève : situation et paiement", "/m/paiement"),
           ("paiement", "Inscription d'un candidat", "/m/paiement/inscription"),
           ("duplicata", "Duplicata du reçu", "/m/paiement/duplicata"),
           ("rapport", "Rapport journalier", "/m/paiement/rapport"))


def enregistrer(app, conn, session_courante, connecte, origine_ok):
    """Ajoute les routes /m/paiement/... à l'application. Les 4 derniers paramètres viennent d'app_web.creer_app."""
    app.jinja_env.filters["montant"] = argent.formater

    # ------------------------------------------------------------------ utilitaires
    def contexte(onglet, **plus):
        s = session_courante()
        autorises = paiements.onglets_autorises(conn(), s)
        ctx = dict(s=s, cfg=config, titre="Paiement des frais", menu_utile=modules.menu_utile(conn(), s), autorises=autorises,
                   onglets=ONGLETS, onglet=onglet, peut_payer="paiement" in autorises,
                   motif_verrou=paiements.motif_enregistrement_verrouille(s, conn()))
        ctx.update(plus)
        return ctx

    def acces(onglet):
        """Session du compte, après vérification qu'il a le module et l'onglet. 403 sinon."""
        s = session_courante()
        autorises = paiements.onglets_autorises(conn(), s)
        if onglet not in autorises:
            abort(403)
        return s

    def poster():
        if not origine_ok():
            abort(403)

    def page(modele, onglet, statut=200, **plus):
        rep = make_response(render_template(modele, **contexte(onglet, **plus)), statut)
        return rep

    def eleve_ou_404(s, matricule):
        eleve = donnees.get_eleve(conn(), matricule)
        if eleve is None:
            abort(404)
        try:
            sections.exiger_eleve(conn(), s, matricule)
        except PermissionError:
            abort(403)
        return eleve

    def recu_accessible(s, n_recu):
        """Reçu chargé, après vérification de la section de sa classe. 404 si introuvable, 403 si section fermée."""
        try:
            recu = paiements.charger_recu(conn(), n_recu)
        except paiements.ErreurPaiement:
            abort(404)
        n_classe = conn().execute("SELECT N_CLASSE FROM PAIEMENT WHERE N_RECU = ?", (n_recu,)).fetchone()["N_CLASSE"]
        try:
            sections.exiger_classe(conn(), s, n_classe)
        except PermissionError:
            abort(403)
        return recu

    def pdf(octets_chemin, nom):
        with open(octets_chemin, "rb") as f:
            rep = make_response(f.read())
        rep.headers["Content-Type"] = "application/pdf"
        rep.headers["Content-Disposition"] = f'inline; filename="{nom}"'
        return rep

    def recherche(s, terme):
        """(résultats, message) pour la zone de recherche d'élève."""
        terme = (terme or "").strip()
        if not terme:
            return [], ""
        if len(terme) < 2:
            return [], "Saisissez au moins 2 caractères."
        res = donnees.rechercher_eleves(conn(), terme, session=s)
        if not res:
            return [], f"Aucun élève trouvé pour « {terme} »."
        return res, ""

    # ================================================================== 1) ÉLÈVE : recherche, situation, paiement
    @app.get("/m/paiement")
    @connecte
    def paiement_accueil():
        s = acces("consultation")
        q = request.args.get("q", "")
        res, msg = recherche(s, q)
        if len(res) == 1:
            return redirect(url_for("paiement_eleve", matricule=res[0]["matricule"]))
        return page("paiement_recherche.html", "consultation", q=q, resultats=res, message=msg, suite="paiement_eleve",
                    action="/m/paiement", aide="Tapez le nom ou le matricule de l'élève, puis ouvrez sa situation.")

    def page_eleve(s, matricule, annee=None, erreur="", statut=200, journaliser_consultation=True):
        eleve = eleve_ou_404(s, matricule)
        c = conn()
        inscs = donnees.inscriptions(c, matricule)
        if journaliser_consultation:
            with c:
                journaliser(c, s.id_user, s.login, "SITUATION_CONSULTEE", matricule)
        annees = [i["ANNEESCO"] for i in inscs]
        courante = donnees.annee_courante(c)
        if courante and courante not in annees:
            annees.insert(0, courante)                       # pour afficher « non inscrit cette année »
        if annee not in annees:
            annee = courante if courante in annees else (annees[0] if annees else "")
        insc = next((i for i in inscs if i["ANNEESCO"] == annee), None)
        lignes = donnees.situation(c, matricule, annee, insc["N_CLASSE"]) if insc else []
        totaux = donnees.totaux_par_devise(lignes)
        return page("paiement_eleve.html", "consultation", statut=statut, eleve=eleve, nom=donnees.nom_complet(eleve),
                    annees=annees, annee=annee, insc=insc, lignes=lignes, totaux=totaux, dettes=donnees.dettes(c, matricule),
                    erreur=erreur, peut_payer_ici=bool(insc) and "paiement" in paiements.onglets_autorises(c, s),
                    statut_insc={"NOUVEAU": "Nouvel élève", "REDOUBLANT": "Redoublant", "TRANSFERT": "Transfert",
                                 "ANCIEN": "Ancien élève"}.get(insc["STATUT"], insc["STATUT"]) if insc else "")

    @app.get("/m/paiement/eleve/<path:matricule>")
    @connecte
    def paiement_eleve(matricule):
        s = acces("consultation")
        return page_eleve(s, matricule, request.args.get("annee"))

    def ligne_demandee(matricule):
        """Ligne de situation (frais + année) désignée par le formulaire, ou lève ErreurPaiement (message affichable)."""
        annee, codtf = request.form.get("annee", ""), request.form.get("codtf", "")
        insc = next((i for i in donnees.inscriptions(conn(), matricule) if i["ANNEESCO"] == annee), None)
        if not insc:
            raise paiements.ErreurPaiement(f"Cet élève n'est pas inscrit pour l'année {annee}.")
        ligne = next((l for l in donnees.situation(conn(), matricule, annee, insc["N_CLASSE"]) if l.codtf == codtf), None)
        if ligne is None:
            raise paiements.ErreurPaiement("Ce type de frais n'est pas dû par cet élève cette année.")
        return ligne

    def montant_valide(ligne):
        """Montant saisi (en centimes), contrôlé comme dans le logiciel ; lève ErreurPaiement (message affichable)."""
        try:
            centimes = argent.vers_centimes(request.form.get("montant", ""))
        except ValueError as e:
            raise paiements.ErreurPaiement(str(e)) from None
        if centimes <= 0:
            raise paiements.ErreurPaiement("Le montant doit être supérieur à zéro.")
        if ligne.reste <= 0:
            raise paiements.ErreurPaiement("Ce frais est déjà entièrement payé.")
        if centimes > ligne.reste:
            raise paiements.ErreurPaiement(f"Le montant dépasse le reste à payer ({argent.formater(ligne.reste)} {ligne.devise}).")
        paiements.verifier_palier(ligne.paliers or None, {"DESITF": ligne.designation, "PAR_TRANCHE": ligne.par_tranche},
                                  ligne.du, ligne.devise, ligne.paye, centimes)
        return centimes

    @app.post("/m/paiement/eleve/<path:matricule>/confirmer")
    @connecte
    def paiement_confirmer(matricule):
        poster()
        s = acces("paiement")
        eleve = eleve_ou_404(s, matricule)
        try:
            ligne = ligne_demandee(matricule)
            centimes = montant_valide(ligne)
        except paiements.ErreurPaiement as e:
            return page_eleve(s, matricule, request.form.get("annee"), str(e), 400, journaliser_consultation=False)
        return page("paiement_confirmer.html", "consultation", eleve=eleve, nom=donnees.nom_complet(eleve), ligne=ligne,
                    centimes=centimes, annee=ligne.annee)

    @app.post("/m/paiement/eleve/<path:matricule>/enregistrer")
    @connecte
    def paiement_enregistrer(matricule):
        poster()
        s = acces("paiement")
        eleve_ou_404(s, matricule)
        c = conn()
        try:
            ligne = ligne_demandee(matricule)
            n_perc = paiements.numero_percepteur(c, s)
            paye_vu = request.form.get("paye", "")
            if paye_vu.isdigit() and int(paye_vu) != ligne.paye:
                # ce qui était payé a changé depuis l'écran de confirmation : soit CE paiement vient d'être enregistré (double clic),
                # soit un autre paiement est passé entre-temps. On ne crée jamais un reçu « à l'aveugle ».
                try:
                    centimes = argent.vers_centimes(request.form.get("montant", ""))
                except ValueError:
                    centimes = 0
                deja = c.execute(
                    "SELECT N_RECU FROM PAIEMENT WHERE MATRICULE = ? AND ANNEESCO = ? AND CODTF = ? AND MONT_PAYE = ? "
                    "AND N_PERC = ? AND STATUT = 'VALIDE' ORDER BY NUM_SEQ DESC LIMIT 1",
                    (matricule, ligne.annee, ligne.codtf, centimes, n_perc)).fetchone()
                if deja and ligne.paye == int(paye_vu) + centimes:
                    return redirect(url_for("paiement_recu", n_recu=deja["N_RECU"]))
                raise paiements.ErreurPaiement("La situation de cet élève a changé depuis l'écran précédent (un autre paiement a été "
                                               "enregistré). Vérifiez la situation ci-dessous, puis recommencez.")
            centimes = montant_valide(ligne)
            n_recu = paiements.enregistrer_paiement(c, s, matricule, ligne.annee, ligne.codtf, centimes)
        except paiements.ErreurPaiement as e:
            return page_eleve(s, matricule, request.form.get("annee"), str(e), 400, journaliser_consultation=False)
        except PermissionError as e:
            return page_eleve(s, matricule, request.form.get("annee"), str(e), 403, journaliser_consultation=False)
        return redirect(url_for("paiement_recu", n_recu=n_recu))

    # ================================================================== reçus (page, PDF)
    @app.get("/m/paiement/recu/<n_recu>")
    @connecte
    def paiement_recu(n_recu):
        s = acces("consultation")
        recu = recu_accessible(s, n_recu)
        l = conn().execute("SELECT N_PERC, DATE_PAY FROM PAIEMENT WHERE N_RECU = ?", (n_recu,)).fetchone()
        return page("paiement_recu.html", "consultation", recu=recu, original_possible=original_possible(s, l),
                    delai_original=DELAI_ORIGINAL_MIN, lien_appli=(config.url_publique() or request.host_url.rstrip("/")) + "/parents")

    def original_possible(s, ligne) -> bool:
        """Le reçu original n'est réimprimable que par son percepteur, peu de temps après l'enregistrement."""
        try:
            if paiements.numero_percepteur(conn(), s) != ligne["N_PERC"]:
                return False
        except (paiements.ErreurPaiement, PermissionError):
            return False
        return maintenant() - lire_iso(ligne["DATE_PAY"]) <= timedelta(minutes=DELAI_ORIGINAL_MIN)

    @app.get("/m/paiement/recu/<n_recu>/pdf")
    @connecte
    def paiement_recu_pdf(n_recu):
        s = acces("consultation")
        recu_accessible(s, n_recu)
        duplicata = request.args.get("duplicata") == "1"
        if not duplicata:
            l = conn().execute("SELECT N_PERC, DATE_PAY FROM PAIEMENT WHERE N_RECU = ?", (n_recu,)).fetchone()
            if not original_possible(s, l):
                abort(403)
        try:
            chemin = paiements.preparer_pdf(conn(), s, n_recu, duplicata=duplicata)
        except paiements.ErreurPaiement as e:
            return render_template("erreur.html", cfg=config, titre="Impression impossible", texte=str(e)), 400
        except PermissionError:
            abort(403)
        return pdf(chemin, f"Recu_{n_recu}.pdf")

    # ================================================================== 2) INSCRIPTION d'un candidat
    def parametres_candidat(source):
        return {c: " ".join((source.get(c) or "").split()) for c in ("nom", "postnom", "prenom", "annee", "classe")}

    def calcul_frais_candidat(s, p):
        """(frais proposés, n_classe) d'après l'année et la classe choisies ; la classe doit être ouverte à ce compte."""
        classes = dict(inscription.classes_proposees(conn(), s))
        try:
            n_classe = int(p["classe"])
        except ValueError:
            return [], None, classes
        if n_classe not in classes or not p["annee"]:
            return [], None, classes
        return paiements.frais_inscription_pour_classe(conn(), p["annee"], n_classe), n_classe, classes

    @app.get("/m/paiement/inscription")
    @connecte
    def paiement_inscription():
        s = acces("paiement")
        p = parametres_candidat(request.args)
        courante = donnees.annee_courante(conn())
        if not p["annee"] and courante:
            p["annee"] = courante
        frais, n_classe, classes = calcul_frais_candidat(s, p)
        return page("paiement_inscription.html", "paiement", p=p, frais=frais, n_classe=n_classe,
                    classes=list(classes.items()), annees=inscription.annees_proposees(conn()),
                    sans_frais=bool(n_classe and p["annee"] and not frais), erreur="")

    @app.post("/m/paiement/inscription/confirmer")
    @connecte
    def paiement_inscription_confirmer():
        poster()
        s = acces("paiement")
        p = parametres_candidat(request.form)
        frais, n_classe, classes = calcul_frais_candidat(s, p)
        choisi = next((f for f in frais if f[0] == request.form.get("codtf")), None)
        erreur = ""
        if not p["nom"]:
            erreur = "Saisissez le nom du candidat."
        elif not n_classe:
            erreur = "Choisissez la classe dans laquelle le candidat souhaite être inscrit."
        elif choisi is None:
            erreur = "Choisissez le frais d'inscription à payer."
        if erreur:
            return page("paiement_inscription.html", "paiement", statut=400, p=p, frais=frais, n_classe=n_classe,
                        classes=list(classes.items()), annees=inscription.annees_proposees(conn()),
                        sans_frais=False, erreur=erreur)
        return page("paiement_inscription_confirmer.html", "paiement", p=p, classe_txt=classes[n_classe], choisi=choisi,
                    identite=" ".join(x for x in (p["nom"], p["postnom"], p["prenom"]) if x).upper())

    @app.post("/m/paiement/inscription/enregistrer")
    @connecte
    def paiement_inscription_enregistrer():
        poster()
        s = acces("paiement")
        p = parametres_candidat(request.form)
        frais, n_classe, classes = calcul_frais_candidat(s, p)
        choisi = next((f for f in frais if f[0] == request.form.get("codtf")), None)
        try:
            if not n_classe or choisi is None:
                raise paiements.ErreurPaiement("Choisissez l'année, la classe et le frais d'inscription.")
            # le montant vient toujours du tarif enregistré, jamais du formulaire
            n_recu = paiements.enregistrer_paiement_inscription(conn(), s, p["annee"], n_classe, choisi[0], choisi[2],
                                                                p["nom"], p["postnom"], p["prenom"])
        except (paiements.ErreurPaiement, PermissionError) as e:
            return page("paiement_inscription.html", "paiement", statut=400 if isinstance(e, paiements.ErreurPaiement) else 403,
                        p=p, frais=frais, n_classe=n_classe, classes=list(classes.items()),
                        annees=inscription.annees_proposees(conn()), sans_frais=False, erreur=str(e))
        return redirect(url_for("paiement_recu", n_recu=n_recu))

    # ================================================================== 3) DUPLICATA
    @app.get("/m/paiement/duplicata")
    @connecte
    def paiement_duplicata():
        s = acces("duplicata")
        q = request.args.get("q", "")
        res, msg = recherche(s, q)
        if len(res) == 1:
            return redirect(url_for("paiement_duplicata_eleve", matricule=res[0]["matricule"]))
        return page("paiement_recherche.html", "duplicata", q=q, resultats=res, message=msg, suite="paiement_duplicata_eleve",
                    action="/m/paiement/duplicata", aide="Cherchez l'élève dont vous voulez imprimer un duplicata de reçu.")

    @app.get("/m/paiement/duplicata/<path:matricule>")
    @connecte
    def paiement_duplicata_eleve(matricule):
        s = acces("duplicata")
        eleve = eleve_ou_404(s, matricule)
        recus = paiements.recus_eleve(conn(), matricule)
        paiements.journaliser_consultation_recus(conn(), s, matricule)
        liste = [{"n_recu": r["N_RECU"], "quand": lire_iso(r["DATE_PAY"]).astimezone().strftime("%d/%m/%Y  %H:%M"),
                  "annee": r["ANNEESCO"], "frais": r["DESITF"], "montant": f"{argent.formater(r['MONT_PAYE'])} {r['CODE_DEVISE']}",
                  "valide": r["STATUT"] == "VALIDE", "code": parents.code_du_recu(conn(), r["N_RECU"])} for r in recus]
        return page("paiement_duplicata.html", "duplicata", eleve=eleve, nom=donnees.nom_complet(eleve), recus=liste)

    # ================================================================== 4) RAPPORT JOURNALIER
    @app.get("/m/paiement/rapport")
    @connecte
    def paiement_rapport():
        s = acces("rapport")
        c = conn()
        est_percepteur = s.role == "PERCEPTEUR"
        percepteurs = [] if est_percepteur else paiements.liste_percepteurs(c)
        texte_date = request.args.get("date", "").strip() or datetime.now().strftime("%d/%m/%Y")
        n_perc = None
        if not est_percepteur and request.args.get("perc", "").isdigit():
            n_perc = int(request.args["perc"])
        rapport, erreur = None, ""
        try:
            rapport = paiements.rapport_journalier(c, s, paiements.lire_date(texte_date), n_perc)
        except paiements.ErreurPaiement as e:
            erreur = str(e)
        except PermissionError:
            abort(403)
        return page("paiement_rapport.html", "rapport", rapport=rapport, erreur=erreur, texte_date=texte_date,
                    percepteurs=percepteurs, n_perc=n_perc, est_percepteur=est_percepteur)

    @app.get("/m/paiement/rapport/pdf")
    @connecte
    def paiement_rapport_pdf():
        s = acces("rapport")
        n_perc = int(request.args["perc"]) if (s.role != "PERCEPTEUR" and request.args.get("perc", "").isdigit()) else None
        try:
            jour = paiements.lire_date(request.args.get("date", ""))
            chemin = paiements.preparer_rapport_pdf(conn(), s, jour, n_perc)
        except paiements.ErreurPaiement as e:
            return render_template("erreur.html", cfg=config, titre="Impression impossible", texte=str(e)), 400
        except PermissionError:
            abort(403)
        return pdf(chemin, f"Rapport_caisse_{jour.isoformat()}.pdf")

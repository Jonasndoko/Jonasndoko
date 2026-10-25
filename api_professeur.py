"""Routes métier de la saisie des points, communes au serveur local (serveur_notes.py) et à l'application web (app_web.py).
Aucune dépendance HTTP : (connexion, session, méthode, chemin, données) -> résultat JSON, ou (octets, nom) pour un PDF."""
import bulletins
import controle_notes
import horaires
import notes
import presence_eleves
import security


def traiter(conn, s, methode, chemin, d):
    if chemin == "mdp":
        try:
            security.changer_mdp(conn, s, str(d.get("ancien", "")), str(d.get("nouveau", "")), str(d.get("confirmation", "")))
        except ValueError as e:
            raise notes.ErreurNotes(str(e)) from None
        return {"ok": True}
    if s.doit_changer_mdp:
        raise PermissionError("Changez d'abord votre mot de passe provisoire.")
    if chemin == "classes" and methode == "GET":
        return notes.mes_classes(conn, s, d.get("annee"))
    if chemin == "fiche" and methode == "GET":
        return notes.fiche(conn, s, d.get("cc"), d.get("per"))
    # ---- calcul automatique et bulletins : réservé au professeur titulaire (bulletins.py le contrôle à chaque appel)
    if chemin == "bulletins/acces" and methode == "GET":
        return bulletins.acces(conn, s)
    if chemin == "bulletins/classes" and methode == "GET":
        return bulletins.mes_classes(conn, s, d.get("annee"))
    if chemin == "bulletins/autorisations" and methode == "GET":
        return bulletins.autorisations(conn, s, d.get("annee"), d.get("classe"))
    if chemin == "bulletins/maxima" and methode == "GET":
        return bulletins.maxima_cours(conn, s, d.get("annee"), d.get("classe"))
    if chemin == "bulletins/resultats" and methode == "GET":
        return bulletins.resultats(conn, s, d.get("annee"), d.get("classe"), d.get("portee"), str(d.get("ordre", "reussite")))
    if chemin == "bulletins/eleve" and methode == "GET":
        return bulletins.fiche_eleve(conn, s, d.get("annee"), d.get("classe"), d.get("matricule"))
    if chemin == "bulletins/pdf" and methode == "GET":
        return bulletins.document_pdf(conn, s, str(d.get("genre", "")), d.get("annee"), d.get("classe"), str(d.get("portee", "A")),
                                      d.get("matricule"))
    if chemin == "horaire/mien" and methode == "GET":
        try:
            return horaires.mon_horaire(conn, s, d.get("annee"))
        except horaires.ErreurHoraire as e:
            raise notes.ErreurNotes(str(e)) from None
    if chemin == "corrections" and methode == "GET":                 # demandes de la direction des études pour mes cours
        return controle_notes.mes_demandes(conn, s)
    if chemin == "presence/liste" and methode == "GET":
        return presence_eleves.liste(conn, s, d.get("cc"), d.get("date", ""))
    if chemin == "presence/historique" and methode == "GET":
        return presence_eleves.historique(conn, s, d.get("cc"))
    if methode == "POST":
        if chemin == "corrections/traiter":
            return controle_notes.traiter_demande(conn, s, d.get("id"), str(d.get("reponse", "")))
        if chemin == "presence/marquer":
            return presence_eleves.marquer(conn, s, d.get("cc"), d.get("date", ""), str(d.get("matricule", "")), str(d.get("statut", "")))
        if chemin == "presence/tous":
            return presence_eleves.tous_presents(conn, s, d.get("cc"), d.get("date", ""))
        if chemin == "bulletins/autoriser":
            return bulletins.definir_autorisation(conn, s, d.get("annee"), d.get("classe"), str(d.get("cle", "")),
                                                  d.get("autorisee") is True)
        if chemin == "bulletins/maximum":
            return bulletins.definir_maximum_cours(conn, s, d.get("annee"), d.get("classe"), d.get("cc"), d.get("maximum"))
        if chemin == "points":
            v = d.get("valeurs")
            if not isinstance(v, dict):
                raise notes.ErreurNotes("Requête illisible.")
            return notes.enregistrer_points(conn, s, d.get("cc"), d.get("per"), {str(k): ("" if x is None else str(x)) for k, x in v.items()})
        if chemin == "conduite":
            notes.enregistrer_conduite(conn, s, d.get("cc"), d.get("per"), str(d.get("matricule", "")), str(d.get("cote", "")))
            return {"ok": True}
    raise notes.ErreurNotes("Demande inconnue.")

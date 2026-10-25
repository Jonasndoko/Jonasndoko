"""Tests du module Inscription en ligne (web_inscription.py) : droits par onglet, vérification du reçu, enregistrement de la candidature,
liste d'attente, fiche PDF, test d'admission, affectation (le candidat devient élève), avis d'admission, double clic.
Lancer :  python -m unittest test_inscription_web"""
import os
import re
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web              # noqa: E402
import database             # noqa: E402
import demo                 # noqa: E402
import droits               # noqa: E402
import paiements            # noqa: E402
import referentiels as ref  # noqa: E402
import security             # noqa: E402
import web_inscription      # noqa: E402

MDP = "Tr@vail-Amour-2026"
AN = demo.ANNEE_COURANTE


class Base(unittest.TestCase):
    def setUp(self):
        web_inscription.GARDE_DOUBLE_CLIC_S = 60
        self.chemin = os.path.join(tempfile.mkdtemp(), "i.db")
        self.conn = database.connecter(self.chemin)
        login, mdp = demo.semer(self.conn)
        self.perc = security.authentifier(self.conn, login, mdp).session
        security.creer_utilisateur(self.conn, "admin1", "Alice Directrice", "ADMINISTRATEUR", MDP)
        self.admin_s = security.authentifier(self.conn, "admin1", MDP).session
        ref.enregistrer(self.conn, self.admin_s, "types_frais",
                        {"CODTF": "INSC", "DESITF": "Frais d'inscription", "MONTANT": "30", "CODE_DEVISE": "USD",
                         "POUR_INSCRIPTION": True}, ("INSC",))
        self.nb_payeurs = 0
        # secrétaire : Lecture + Ajout ; directrice : Lecture + Modification ; lecteur : Lecture seule ; ajout_seul : Ajout sans Lecture
        for login_, nom, role, d in (("sec1", "Sophie Secrétaire", "SECRETAIRE", {"LECTURE", "AJOUT"}),
                                     ("dir1", "Diane Directrice", "DIRECTRICE_ETUDES", {"LECTURE", "MODIFICATION"}),
                                     ("lect1", "Luc Lecteur", "SECRETAIRE", {"LECTURE"}),
                                     ("ajout1", "Axel Ajout", "SECRETAIRE", set()),
                                     ("rien1", "Rita Rien", "SECRETAIRE", set())):
            id_user = security.creer_utilisateur(self.conn, login_, nom, role, MDP)
            with self.conn:
                droits.remplacer_droits(self.conn, id_user, {("inscription", x) for x in d})
        # le Gestionnaire d'accès ajoute toujours la Lecture : un « Ajout sans Lecture » n'existe que par écriture directe en base
        with self.conn:
            self.conn.execute("INSERT INTO DROIT (ID_USER, MODULE, DROIT) SELECT ID_USER, 'inscription', 'AJOUT' FROM UTILISATEUR "
                              "WHERE LOGIN = 'ajout1'")
        self.app = app_web.creer_app(self.chemin)
        self.c = {}
        for login_ in ("admin1", "sec1", "dir1", "lect1", "ajout1", "rien1"):
            self.c[login_] = self.app.test_client()
            r = self.c[login_].post("/connexion", data={"login": login_, "mdp": MDP})
            self.assertEqual(r.status_code, 302, login_)
        self.recu = self.nouveau_recu()

    # ---- aides
    def nouveau_recu(self):
        """Un reçu de frais d'inscription valide, neuf à chaque appel."""
        self.nb_payeurs += 1
        return paiements.enregistrer_paiement_inscription(self.conn, self.perc, AN, 1, "INSC", 3000, f"Payeur{'x' * self.nb_payeurs}")

    def texte(self, r):
        return r.get_data(as_text=True)

    def nb(self, table="CANDIDATURE"):
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def donnees(self, **plus):
        d = {"n_recu": self.recu, "nom": "kalala", "postnom": "mwamba", "prenom": "joël", "sexe": "M", "date_naissance": "15/03/2012",
             "lieu_naissance": "Kinshasa", "nationalite": "Congolaise", "adresse": "Av. de la Paix 12, Lemba", "telephone": "0810000099",
             "ecole_origine": "Institut Les Lauriers", "pourcent_origine": "68,5", "doublant": "0", "n_classe": "1",
             "nom_tuteur": "Mme Kalala Rose", "tel_tuteur": "+243 82 000 00 01", "adresse_tuteur": "Av. de la Paix 12, Lemba"}
        d.update(plus)
        return d

    def candidat(self, **plus):
        """Enregistre une candidature par le web (secrétaire) et retourne son N_CAND."""
        recu = plus.pop("n_recu", None) or self.nouveau_recu()
        r = self.c["sec1"].post("/m/inscription/enregistrer", data=self.donnees(n_recu=recu, **plus))
        self.assertEqual(r.status_code, 302, self.texte(r)[:400])
        return self.conn.execute("SELECT MAX(N_CAND) FROM CANDIDATURE").fetchone()[0]

    def ligne(self, n):
        return self.conn.execute("SELECT * FROM CANDIDATURE WHERE N_CAND = ?", (n,)).fetchone()


class TestAcces(Base):
    URLS = ("/m/inscription", "/m/inscription/liste", "/m/inscription/validation", "/m/inscription/fiche/1/pdf",
            "/m/inscription/validation/1", "/m/inscription/avis/1/pdf")

    def test_non_connecte(self):
        for url in self.URLS:
            self.assertEqual(self.app.test_client().get(url).status_code, 302, url)

    def test_compte_sans_droit_refuse(self):
        for url in self.URLS:
            self.assertEqual(self.c["rien1"].get(url).status_code, 403, url)
        self.assertEqual(self.c["rien1"].post("/m/inscription/enregistrer", data=self.donnees()).status_code, 403)
        self.assertEqual(self.nb(), 0)

    def test_ajout_sans_lecture_refuse(self):
        self.assertEqual(self.c["ajout1"].get("/m/inscription").status_code, 403)
        self.assertEqual(self.c["ajout1"].post("/m/inscription/enregistrer", data=self.donnees()).status_code, 403)

    def test_l_inscription_est_un_onglet_du_secretariat(self):
        """Avec l'accès au Secrétariat, l'inscription est son onglet (plus de tuile à part) et ses pages gardent le cadre du Secrétariat."""
        page = self.texte(self.c["admin1"].get("/menu"))
        self.assertIsNone(re.search(r'<a class="entree" href="/m/inscription"', page))
        secr = self.texte(self.c["admin1"].get("/m/etudes_discipline/dossier_eleve"))
        self.assertRegex(secr, r'<a class="em-btn [^"]*" href="/m/inscription"[^>]*>.*?<span>Inscription</span></a>')
        cadre = self.texte(self.c["admin1"].get("/m/inscription"))
        for mot in ("Secrétariat", "Formulaire d&#39;inscription", "Liste d&#39;attente", "Validation et affectation", "Dossiers des élèves"):
            self.assertIn(mot, cadre, mot)

    def test_sans_acces_au_secretariat_la_tuile_reste(self):
        page = self.texte(self.c["sec1"].get("/menu"))
        tuile = re.search(r'<a class="entree" href="/m/inscription"[^>]*>(.*?)</a>', page, re.S)
        if tuile:
            self.assertNotIn("bientôt en ligne", tuile.group(1))
        cadre = self.texte(self.c["sec1"].get("/m/inscription"))
        self.assertIn("Formulaire d&#39;inscription", cadre)
        self.assertNotIn("Gestion des études et discipline", cadre)

    def test_origine_etrangere_refusee(self):
        for url in ("/m/inscription/enregistrer", "/m/inscription/verifier-recu"):
            r = self.c["sec1"].post(url, data=self.donnees(), headers={"Origin": "https://pirate.example"})
            self.assertEqual(r.status_code, 403, url)
        self.assertEqual(self.nb(), 0)

    def test_lecture_seule_voit_la_liste_pas_le_reste(self):
        r = self.c["lect1"].get("/m/inscription")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/m/inscription/liste", r.headers["Location"])
        page = self.texte(self.c["lect1"].get("/m/inscription/liste"))
        self.assertEqual(page.count("(réservé)"), 2)
        self.assertEqual(self.c["lect1"].get("/m/inscription/validation").status_code, 403)
        self.assertEqual(self.c["lect1"].post("/m/inscription/enregistrer", data=self.donnees()).status_code, 403)
        self.assertEqual(self.c["lect1"].post("/m/inscription/validation/1/test", data={"note": "80"}).status_code, 403)
        self.assertEqual(self.nb(), 0)

    def test_secretaire_n_a_pas_la_validation_directrice_n_a_pas_le_formulaire(self):
        self.assertEqual(self.c["sec1"].get("/m/inscription/validation").status_code, 403)
        self.assertEqual(self.c["sec1"].post("/m/inscription/validation/1/test", data={"note": "80"}).status_code, 403)
        self.assertEqual(self.c["dir1"].get("/m/inscription/validation").status_code, 200)
        r = self.c["dir1"].get("/m/inscription")
        self.assertEqual(r.status_code, 302)                                    # pas d'Ajout : arrive sur la liste
        self.assertEqual(self.c["dir1"].post("/m/inscription/enregistrer", data=self.donnees()).status_code, 403)
        self.assertEqual(self.nb(), 0)


class TestFormulaire(Base):
    def test_formulaire_affiche(self):
        page = self.texte(self.c["sec1"].get("/m/inscription"))
        self.assertIn("Paiement des frais d'inscription", page)
        self.assertIn("Identité du candidat", page)
        self.assertIn("Tuteur", page)

    def test_verifier_recu_valide(self):
        r = self.c["sec1"].post("/m/inscription/verifier-recu", data=self.donnees())
        self.assertEqual(r.status_code, 200)
        page = self.texte(r)
        self.assertIn("Paiement confirmé", page)
        self.assertIn('value="kalala"', page)                                     # la saisie est conservée
        self.assertEqual(self.nb(), 0)

    def test_verifier_recu_inexistant_ou_mauvais_type(self):
        page = self.texte(self.c["sec1"].post("/m/inscription/verifier-recu", data=self.donnees(n_recu="9999")))
        self.assertIn("n&#39;existe pas", page)
        autre = paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0001", AN, "MINERVAL", 1000) \
            if self.conn.execute("SELECT 1 FROM TYPE_FRAIS WHERE CODTF = 'MINERVAL'").fetchone() else None
        if autre:
            page = self.texte(self.c["sec1"].post("/m/inscription/verifier-recu", data=self.donnees(n_recu=autre)))
            self.assertIn("pas les frais d&#39;inscription", page)

    def test_enregistrement_complet(self):
        r = self.c["sec1"].post("/m/inscription/enregistrer", data=self.donnees())
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.nb(), 1)
        l = self.conn.execute("SELECT * FROM CANDIDATURE").fetchone()
        self.assertEqual((l["NOM"], l["POSTNOM"], l["PRENOM"], l["STATUT"], l["ENREGISTRE_PAR"]),
                         ("KALALA", "MWAMBA", "Joël", "EN_ATTENTE", "sec1"))
        self.assertEqual((l["POURCENT_ORIGINE"], l["DOUBLANT"], l["N_RECU"]), (68.5, 0, self.recu))
        page = self.texte(self.c["sec1"].get(r.headers["Location"]))
        self.assertIn(f"Candidature {l['NUM_CAND']} enregistrée", page)
        self.assertIn(f"/m/inscription/fiche/{l['N_CAND']}/pdf", page)
        self.assertIn("CANDIDATURE_ENREGISTREE", [x[0] for x in self.conn.execute("SELECT ACTION FROM JOURNAL")])

    def test_doublant_oui(self):
        n = self.candidat(doublant="1")
        self.assertEqual(self.ligne(n)["DOUBLANT"], 1)

    def test_erreurs_affichees_rien_enregistre_saisie_conservee(self):
        for champ, valeur, attendu in (("nom", "", "nom du candidat"), ("sexe", "", "sexe"), ("date_naissance", "31/02/2012", "invalide"),
                                       ("date_naissance", "15/03/2030", "futur"), ("pourcent_origine", "150", "entre 0 et 100"),
                                       ("doublant", "", "doublant"), ("n_classe", "", "classe"), ("tel_tuteur", "abc", "invalide"),
                                       ("nom_tuteur", "", "nom du tuteur")):
            r = self.c["sec1"].post("/m/inscription/enregistrer", data=self.donnees(**{champ: valeur}))
            self.assertEqual(r.status_code, 400, champ)
            page = self.texte(r)
            self.assertIn(attendu, page, champ)
            self.assertIn('value="Institut Les Lauriers"', page)                  # le reste de la saisie est conservé
        self.assertEqual(self.nb(), 0)

    def test_sans_recu_ou_recu_invalide_refuse(self):
        for recu, attendu in (("", "numéro du reçu"), ("9999", "n&#39;existe pas")):
            r = self.c["sec1"].post("/m/inscription/enregistrer", data=self.donnees(n_recu=recu))
            self.assertEqual(r.status_code, 400)
            self.assertIn(attendu, self.texte(r))
        self.assertEqual(self.nb(), 0)

    def test_un_recu_ne_sert_qu_une_fois(self):
        self.candidat(n_recu=self.recu)
        web_inscription.GARDE_DOUBLE_CLIC_S = 0                                   # hors délai « double clic »
        r = self.c["sec1"].post("/m/inscription/enregistrer", data=self.donnees(nom="autre"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("a déjà servi", self.texte(r))
        self.assertEqual(self.nb(), 1)

    def test_double_clic_ne_cree_pas_deux_candidatures(self):
        r1 = self.c["sec1"].post("/m/inscription/enregistrer", data=self.donnees())
        r2 = self.c["sec1"].post("/m/inscription/enregistrer", data=self.donnees())
        self.assertEqual((r1.status_code, r2.status_code), (302, 302))
        self.assertIn("deja=1", r2.headers["Location"])
        self.assertEqual(self.nb(), 1)
        self.assertIn("aucun doublon", self.texte(self.c["sec1"].get(r2.headers["Location"])))

    def test_message_succes_non_falsifiable(self):
        n = self.candidat()
        marque = "dans sa classe"
        self.assertIn(marque, self.texte(self.c["sec1"].get(f"/m/inscription?ok={n}")))
        self.assertNotIn(marque, self.texte(self.c["sec1"].get("/m/inscription?ok=99999")))
        self.assertNotIn(marque, self.texte(self.c["dir1"].get(f"/m/inscription?ok={n}", follow_redirects=True)))   # pas la candidature de ce compte

    def test_classe_inexistante_refusee(self):
        r = self.c["sec1"].post("/m/inscription/enregistrer", data=self.donnees(n_classe="99999"))
        self.assertIn(r.status_code, (400, 403))
        self.assertEqual(self.nb(), 0)


class TestListeEtFiche(Base):
    def test_liste_et_recherche(self):
        n1 = self.candidat(nom="kalala")
        n2 = self.candidat(nom="mukendi", n_classe="2")
        page = self.texte(self.c["lect1"].get("/m/inscription/liste"))
        self.assertIn("KALALA", page)
        self.assertIn("MUKENDI", page)
        self.assertIn("2 candidat(s) en attente", page)
        page = self.texte(self.c["lect1"].get("/m/inscription/liste?q=mukendi"))
        self.assertIn("MUKENDI", page)
        self.assertNotIn("KALALA", page)
        page = self.texte(self.c["lect1"].get("/m/inscription/liste?classe=2"))
        self.assertIn("MUKENDI", page)
        self.assertNotIn("KALALA", page)
        self.assertNotEqual(n1, n2)

    def test_nom_echappe(self):
        self.candidat(nom="<script>alert(1)</script>")
        page = self.texte(self.c["lect1"].get("/m/inscription/liste"))
        self.assertNotIn("<script>alert(1)", page)
        self.assertIn("&lt;SCRIPT&gt;", page)

    def test_fiche_pdf(self):
        n = self.candidat()
        r = self.c["lect1"].get(f"/m/inscription/fiche/{n}/pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Content-Type"], "application/pdf")
        self.assertTrue(r.data.startswith(b"%PDF"))
        self.assertIn("FICHE_INSCRIPTION_IMPRIMEE", [x[0] for x in self.conn.execute("SELECT ACTION FROM JOURNAL")])
        self.assertEqual(self.c["lect1"].get("/m/inscription/fiche/99999/pdf").status_code, 404)


class TestValidation(Base):
    def test_liste_validation(self):
        n = self.candidat()
        page = self.texte(self.c["dir1"].get("/m/inscription/validation"))
        self.assertIn("KALALA", page)
        self.assertIn("Test à passer", page)
        self.assertIn(f"/m/inscription/validation/{n}", page)
        self.assertNotIn("KALALA", self.texte(self.c["dir1"].get("/m/inscription/validation?filtre=admis")))

    def test_confirmation_n_enregistre_rien(self):
        n = self.candidat()
        r = self.c["dir1"].post(f"/m/inscription/validation/{n}/test/confirmer", data={"note": "72,5"})
        self.assertEqual(r.status_code, 200)
        page = self.texte(r)
        self.assertIn("DOSSIER VALIDÉ", page)
        self.assertIn("72,5", page)
        self.assertIsNone(self.ligne(n)["RESULTAT_TEST"])
        self.assertIn("ÉCHEC", self.texte(self.c["dir1"].post(f"/m/inscription/validation/{n}/test/confirmer", data={"note": "10"})))

    def test_reussite_puis_affectation_devient_eleve(self):
        n = self.candidat()
        r = self.c["dir1"].post(f"/m/inscription/validation/{n}/test", data={"note": "72,5"})
        self.assertEqual(r.status_code, 302)
        l = self.ligne(n)
        self.assertEqual((l["RESULTAT_TEST"], l["NOTE_TEST"], l["TEST_PAR"], l["STATUT"]), ("REUSSI", 72.5, "dir1", "EN_ATTENTE"))
        self.assertIn("Dossier validé", self.texte(self.c["dir1"].get(r.headers["Location"])))
        eleves = self.nb("ELEVE")
        # confirmation d'affectation : rien n'est créé
        r = self.c["dir1"].post(f"/m/inscription/validation/{n}/affecter/confirmer", data={"classe": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Confirmer l'affectation", self.texte(r))
        self.assertEqual(self.nb("ELEVE"), eleves)
        # affectation
        r = self.c["dir1"].post(f"/m/inscription/validation/{n}/affecter", data={"classe": "1"})
        self.assertEqual(r.status_code, 302)
        l = self.ligne(n)
        self.assertEqual(l["STATUT"], "ADMIS")
        self.assertTrue(l["MATRICULE"])
        self.assertEqual(self.nb("ELEVE"), eleves + 1)
        self.assertEqual(self.conn.execute("SELECT N_CLASSE FROM INSCRIRE WHERE MATRICULE = ? AND ANNEESCO = ?",
                                           (l["MATRICULE"], AN)).fetchone()[0], 1)
        self.assertTrue(self.conn.execute("SELECT CODE_QR FROM ELEVE WHERE MATRICULE = ?", (l["MATRICULE"],)).fetchone()[0])
        page = self.texte(self.c["dir1"].get(r.headers["Location"]))
        self.assertIn(l["MATRICULE"], page)
        self.assertIn(f"/m/inscription/avis/{n}/pdf", page)
        self.assertIn("CANDIDAT_ADMIS_AFFECTE", [x[0] for x in self.conn.execute("SELECT ACTION FROM JOURNAL")])
        # avis d'admission PDF
        r = self.c["dir1"].get(f"/m/inscription/avis/{n}/pdf")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data.startswith(b"%PDF"))

    def test_echec_refuse_definitivement(self):
        n = self.candidat()
        r = self.c["dir1"].post(f"/m/inscription/validation/{n}/test", data={"note": "30"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("refus", r.headers["Location"])
        self.assertEqual(self.ligne(n)["STATUT"], "REFUSE")
        web_inscription.GARDE_DOUBLE_CLIC_S = 0
        r = self.c["dir1"].post(f"/m/inscription/validation/{n}/test", data={"note": "90"})      # un résultat ne se modifie pas
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.ligne(n)["NOTE_TEST"], 30)
        r = self.c["dir1"].post(f"/m/inscription/validation/{n}/affecter", data={"classe": "1"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.nb("ELEVE") , self.conn.execute("SELECT COUNT(*) FROM ELEVE").fetchone()[0])
        self.assertNotEqual(self.ligne(n)["STATUT"], "ADMIS")

    def test_note_invalide(self):
        n = self.candidat()
        for note in ("", "abc", "101", "-5"):
            r = self.c["dir1"].post(f"/m/inscription/validation/{n}/test/confirmer", data={"note": note})
            self.assertEqual(r.status_code, 400, note)
            r = self.c["dir1"].post(f"/m/inscription/validation/{n}/test", data={"note": note})
            self.assertEqual(r.status_code, 400, note)
        self.assertIsNone(self.ligne(n)["RESULTAT_TEST"])

    def test_affectation_avant_le_test_refusee(self):
        n = self.candidat()
        for etape in ("affecter/confirmer", "affecter"):
            self.assertEqual(self.c["dir1"].post(f"/m/inscription/validation/{n}/{etape}", data={"classe": "1"}).status_code, 400, etape)
        self.assertEqual(self.ligne(n)["STATUT"], "EN_ATTENTE")

    def test_affectation_sans_classe_ou_classe_inconnue(self):
        n = self.candidat()
        self.c["dir1"].post(f"/m/inscription/validation/{n}/test", data={"note": "80"})
        for classe in ("", "abc", "99999"):
            r = self.c["dir1"].post(f"/m/inscription/validation/{n}/affecter/confirmer", data={"classe": classe})
            self.assertEqual(r.status_code, 400, classe)
        r = self.c["dir1"].post(f"/m/inscription/validation/{n}/affecter", data={"classe": "99999"})
        self.assertIn(r.status_code, (400, 403))
        self.assertEqual(self.ligne(n)["STATUT"], "EN_ATTENTE")

    def test_double_clic_test_et_affectation(self):
        n = self.candidat()
        r1 = self.c["dir1"].post(f"/m/inscription/validation/{n}/test", data={"note": "80"})
        r2 = self.c["dir1"].post(f"/m/inscription/validation/{n}/test", data={"note": "80"})
        self.assertEqual((r1.status_code, r2.status_code), (302, 302))
        eleves = self.nb("ELEVE")
        r1 = self.c["dir1"].post(f"/m/inscription/validation/{n}/affecter", data={"classe": "1"})
        r2 = self.c["dir1"].post(f"/m/inscription/validation/{n}/affecter", data={"classe": "1"})
        self.assertEqual((r1.status_code, r2.status_code), (302, 302))
        self.assertEqual(self.nb("ELEVE"), eleves + 1)

    def test_candidature_inconnue_404(self):
        for url in ("/m/inscription/validation/99999", "/m/inscription/avis/99999/pdf"):
            self.assertIn(self.c["dir1"].get(url).status_code, (400, 404), url)
        self.assertEqual(self.c["dir1"].post("/m/inscription/validation/99999/test", data={"note": "80"}).status_code, 404)

    def test_avis_refuse_si_pas_admis(self):
        n = self.candidat()
        self.assertEqual(self.c["dir1"].get(f"/m/inscription/avis/{n}/pdf").status_code, 400)

    def test_origine_etrangere_refusee_sur_les_decisions(self):
        n = self.candidat()
        for url, d in ((f"/m/inscription/validation/{n}/test/confirmer", {"note": "80"}), (f"/m/inscription/validation/{n}/test", {"note": "80"}),
                       (f"/m/inscription/validation/{n}/affecter/confirmer", {"classe": "1"}),
                       (f"/m/inscription/validation/{n}/affecter", {"classe": "1"})):
            self.assertEqual(self.c["dir1"].post(url, data=d, headers={"Origin": "https://pirate.example"}).status_code, 403, url)
        self.assertIsNone(self.ligne(n)["RESULTAT_TEST"])

    def test_administrateur_a_tous_les_onglets(self):
        for url in ("/m/inscription", "/m/inscription/liste", "/m/inscription/validation"):
            self.assertEqual(self.c["admin1"].get(url).status_code, 200, url)


if __name__ == "__main__":
    unittest.main()

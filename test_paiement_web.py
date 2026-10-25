"""Tests du module Paiement en ligne (web_paiement.py) : parcours complet, droits, sections, double clic, reçus original/duplicata, rapport.
Lancer :  python -m unittest test_paiement_web"""
import config
import datetime
import os
import re
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web         # noqa: E402
import database        # noqa: E402
import demo            # noqa: E402
import security        # noqa: E402
import web_paiement    # noqa: E402

AN, AN0 = demo.ANNEE_COURANTE, demo.ANNEE_PRECEDENTE
MDP = "Tr@vail-Amour-2026"


class Base(unittest.TestCase):
    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "p.db")
        self.conn = database.connecter(self.chemin)
        self.login, self.mdp = demo.semer(self.conn)
        security.creer_utilisateur(self.conn, "admin1", "Alice Directrice", "ADMINISTRATEUR", MDP)
        with self.conn:
            self.conn.execute("UPDATE TYPE_FRAIS SET POUR_INSCRIPTION = 1 WHERE CODTF = 'INSC'")
        self.app = app_web.creer_app(self.chemin)
        self.perc, self.admin = self.app.test_client(), self.app.test_client()
        self.entrer(self.perc, self.login, self.mdp)
        self.entrer(self.admin, "admin1", MDP)

    def entrer(self, client, login, mdp):
        self.assertEqual(client.post("/connexion", data={"login": login, "mdp": mdp}).status_code, 302)

    def texte(self, r):
        return r.get_data(as_text=True)

    def nb_paiements(self):
        return self.conn.execute("SELECT COUNT(*) FROM PAIEMENT").fetchone()[0]

    def payer(self, client, mat, codtf, montant, annee=AN, paye=None):
        """Enregistre comme le fait la page de confirmation ; `paye` = ce que la page avait affiché comme déjà payé (centimes)."""
        d = {"annee": annee, "codtf": codtf, "montant": montant}
        if paye is not None:
            d["paye"] = str(paye)
        return client.post(f"/m/paiement/eleve/{mat}/enregistrer", data=d)


class TestAcces(Base):
    def test_non_connecte(self):
        for url in ("/m/paiement", "/m/paiement/rapport", "/m/paiement/recu/0001/pdf", "/m/paiement/duplicata/CSF-0001"):
            self.assertEqual(self.app.test_client().get(url).status_code, 302, url)

    def test_menu_indique_que_le_module_est_en_ligne(self):
        # l'Administrateur voit tous les modules : « Paiement » n'est plus « bientôt en ligne »
        page = self.texte(self.admin.get("/menu"))
        tuile = re.search(r'<a class="entree" href="/m/paiement"[^>]*>(.*?)</a>', page, re.S).group(1)
        self.assertNotIn("bientôt en ligne", tuile)

    def test_compte_sans_droit_refuse(self):
        security.creer_utilisateur(self.conn, "sec1", "Marie Kabila", "SECRETAIRE", MDP)
        c = self.app.test_client()
        self.entrer(c, "sec1", MDP)
        self.assertEqual(c.get("/m/paiement").status_code, 403)
        self.assertEqual(c.get("/m/paiement/rapport").status_code, 403)
        self.assertEqual(c.get("/m/paiement/eleve/CSF-0001").status_code, 403)

    def test_administrateur_consulte_mais_ne_paie_pas(self):
        page = self.texte(self.admin.get("/m/paiement/eleve/CSF-0004"))
        self.assertIn("MUTOMBO ILUNGA Grâce", page)
        self.assertNotIn("/confirmer", page)                                   # aucun formulaire de paiement
        self.assertIn("réservé aux comptes de poste Percepteur", page)
        r = self.admin.post("/m/paiement/eleve/CSF-0004/confirmer", data={"annee": AN, "codtf": "EXAM", "montant": "15"})
        self.assertEqual(r.status_code, 403)
        r = self.payer(self.admin, "CSF-0004", "EXAM", "15")
        self.assertEqual(r.status_code, 403)
        self.assertIn("(réservé)", self.texte(self.admin.get("/m/paiement")))   # l'onglet candidat est verrouillé
        self.assertEqual(self.admin.get("/m/paiement/inscription").status_code, 403)

    def test_origine_etrangere_refusee(self):
        r = self.perc.post("/m/paiement/eleve/CSF-0004/enregistrer", data={"annee": AN, "codtf": "EXAM", "montant": "15"},
                           headers={"Origin": "https://pirate.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.nb_paiements(), 10)


class TestParcours(Base):
    def test_recherche_puis_situation(self):
        r = self.perc.get("/m/paiement?q=CSF-0004")                             # un seul résultat : on va direct à l'élève
        self.assertEqual(r.status_code, 302)
        self.assertIn("/m/paiement/eleve/CSF-0004", r.headers["Location"])
        liste = self.texte(self.perc.get("/m/paiement?q=CSF-"))
        self.assertIn("CSF-0001", liste)
        self.assertIn("CSF-0006", liste)
        self.assertIn("Aucun élève trouvé", self.texte(self.perc.get("/m/paiement?q=zzzz")))
        self.assertIn("au moins 2 caractères", self.texte(self.perc.get("/m/paiement?q=a")))
        page = self.texte(self.perc.get("/m/paiement/eleve/CSF-0001"))
        self.assertIn("Frais scolaire (minerval) 1", page)
        self.assertIn("Partiel", page)
        self.assertIn("45,00 USD", page)                                        # déjà payé
        self.assertIn("/confirmer", page)                                       # le percepteur voit les formulaires
        self.assertIn("SITUATION_CONSULTEE", [r[0] for r in self.conn.execute("SELECT ACTION FROM JOURNAL")])

    def test_matricule_avec_barre_oblique(self):
        """Les matricules créés par l'inscription ont la forme 0007/26 : le « / » ne doit pas casser les adresses (Page introuvable)."""
        mat = "0007/26"
        e = dict(self.conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = 'CSF-0004'").fetchone())
        i = dict(self.conn.execute("SELECT * FROM INSCRIRE WHERE MATRICULE = 'CSF-0004' AND ANNEESCO = ?", (AN,)).fetchone())
        e["MATRICULE"], i["MATRICULE"] = mat, mat
        if "CODE_QR" in e:
            e["CODE_QR"] = None
        with self.conn:
            for table, ligne in (("ELEVE", e), ("INSCRIRE", i)):
                self.conn.execute(f"INSERT INTO {table} ({','.join(ligne)}) VALUES ({','.join('?' * len(ligne))})", list(ligne.values()))
        self.assertEqual(self.perc.get(f"/m/paiement/eleve/{mat}").status_code, 200)
        self.assertEqual(self.perc.get(f"/m/paiement/duplicata/{mat}").status_code, 200)
        self.assertEqual(self.perc.post(f"/m/paiement/eleve/{mat}/confirmer",
                                        data={"annee": AN, "codtf": "EXAM", "montant": "15"}).status_code, 200)
        avant = self.nb_paiements()
        r = self.payer(self.perc, mat, "EXAM", "15")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.nb_paiements(), avant + 1)

    def test_dette_et_annee_precedente(self):
        page = self.texte(self.perc.get(f"/m/paiement/eleve/CSF-0002?annee={AN0}"))
        self.assertIn("Dette", page)
        self.assertIn(f"année {AN0}", page)
        self.assertIn("Frais d&#39;examen", page)

    def test_paiement_complet_avec_confirmation(self):
        avant = self.nb_paiements()
        r = self.perc.post("/m/paiement/eleve/CSF-0004/confirmer", data={"annee": AN, "codtf": "MIN1", "montant": "40"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Confirmer le paiement", self.texte(r))
        self.assertIn("40,00 USD", self.texte(r))
        self.assertEqual(self.nb_paiements(), avant)                            # la confirmation n'enregistre rien
        r = self.payer(self.perc, "CSF-0004", "MIN1", "40,00")
        self.assertEqual(r.status_code, 302)
        n_recu = r.headers["Location"].rsplit("/", 1)[1]
        self.assertEqual(self.nb_paiements(), avant + 1)
        page = self.texte(self.perc.get(r.headers["Location"]))
        self.assertIn(f"Reçu N° {n_recu} enregistré", page)
        self.assertIn("Imprimer le reçu", page)

    def test_double_clic_ne_cree_pas_deux_recus(self):
        r1 = self.payer(self.perc, "CSF-0004", "MIN1", "40", paye=0)
        r2 = self.payer(self.perc, "CSF-0004", "MIN1", "40", paye=0)            # même formulaire renvoyé : double clic
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(r1.headers["Location"], r2.headers["Location"])
        self.assertEqual(self.nb_paiements(), 11)

    def test_double_clic_sur_un_frais_en_une_fois(self):
        r1 = self.payer(self.perc, "CSF-0004", "EXAM", "15", paye=0)
        r2 = self.payer(self.perc, "CSF-0004", "EXAM", "15", paye=0)            # « déjà payé » ne doit pas masquer le double clic
        self.assertEqual(r1.headers["Location"], r2.headers["Location"])
        self.assertEqual(self.nb_paiements(), 11)

    def test_deuxieme_tranche_identique_aussitot_apres_reste_possible(self):
        self.payer(self.perc, "CSF-0004", "MIN1", "40", paye=0)
        r = self.payer(self.perc, "CSF-0004", "MIN1", "40", paye=4000)          # nouvelle confirmation : l'élève avait payé 40
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.nb_paiements(), 12)
        self.assertEqual(self.conn.execute("SELECT SUM(MONT_PAYE) FROM PAIEMENT WHERE MATRICULE = 'CSF-0004' AND CODTF = 'MIN1'").fetchone()[0], 8000)

    def test_situation_changee_depuis_la_confirmation(self):
        self.payer(self.perc, "CSF-0004", "MIN1", "40", paye=0)
        r = self.payer(self.perc, "CSF-0004", "MIN1", "40", paye=0)             # formulaire périmé, mais autre montant que le reçu existant
        self.assertEqual(r.status_code, 302)                                    # (c'est bien le même paiement : double clic)
        r = self.payer(self.perc, "CSF-0004", "MIN2", "40", paye=500)           # périmé : MIN2 n'a jamais eu 5,00 payés
        self.assertEqual(r.status_code, 400)
        self.assertIn("a changé", self.texte(r))
        self.assertEqual(self.nb_paiements(), 11)

    def test_erreurs_affichees_et_rien_enregistre(self):
        avant = self.nb_paiements()
        cas = [({"annee": AN, "codtf": "MIN1", "montant": "abc"}, "Montant invalide"),
               ({"annee": AN, "codtf": "MIN1", "montant": "0"}, "supérieur à zéro"),
               ({"annee": AN, "codtf": "MIN1", "montant": "500"}, "dépasse le reste"),
               ({"annee": AN, "codtf": "EXAM", "montant": "10"}, "une seule fois"),   # frais en une fois : pas de partiel
               ({"annee": AN, "codtf": "XXXX", "montant": "10"}, "pas dû"),
               ({"annee": "2000-2001", "codtf": "MIN1", "montant": "10"}, "pas inscrit")]
        for donnees, attendu in cas:
            for etape in ("confirmer", "enregistrer"):
                r = self.perc.post(f"/m/paiement/eleve/CSF-0004/{etape}", data=donnees)
                self.assertEqual(r.status_code, 400, (donnees, etape))
                self.assertIn(attendu, self.texte(r), (donnees, etape))
        self.assertEqual(self.nb_paiements(), avant)

    def test_frais_deja_solde(self):
        self.assertEqual(self.payer(self.perc, "CSF-0001", "EXAM", "15").status_code, 302)
        r = self.payer(self.perc, "CSF-0001", "EXAM", "15")
        self.assertEqual(r.status_code, 400)
        self.assertIn("déjà entièrement payé", self.texte(r))

    def test_eleve_inconnu_ou_recu_inconnu(self):
        self.assertEqual(self.perc.get("/m/paiement/eleve/INCONNU").status_code, 404)
        self.assertEqual(self.perc.get("/m/paiement/recu/9999").status_code, 404)
        self.assertEqual(self.perc.get("/m/paiement/recu/9999/pdf?duplicata=1").status_code, 404)

    def test_montant_jamais_pris_dans_le_formulaire_pour_un_candidat(self):
        d = {"nom": "Mbala", "postnom": "Zola", "prenom": "Eric", "annee": AN, "classe": "1", "codtf": "INSC", "montant": "1"}
        r = self.perc.post("/m/paiement/inscription/enregistrer", data=d)
        self.assertEqual(r.status_code, 302)
        n = r.headers["Location"].rsplit("/", 1)[1]
        self.assertEqual(self.conn.execute("SELECT MONT_PAYE FROM PAIEMENT WHERE N_RECU = ?", (n,)).fetchone()[0], 3000)


class TestRecus(Base):
    def nouveau_recu(self):
        r = self.payer(self.perc, "CSF-0003", "MIN1", "65")
        return r.headers["Location"].rsplit("/", 1)[1]

    def test_pdf_original_puis_duplicata(self):
        n = self.nouveau_recu()
        r = self.perc.get(f"/m/paiement/recu/{n}/pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Content-Type"], "application/pdf")
        self.assertTrue(r.data.startswith(b"%PDF-1.4"))
        d = self.perc.get(f"/m/paiement/recu/{n}/pdf?duplicata=1")
        self.assertEqual(d.status_code, 200)
        actions = [x[0] for x in self.conn.execute("SELECT ACTION FROM JOURNAL")]
        self.assertIn("RECU_IMPRIME", actions)
        self.assertIn("DUPLICATA_IMPRIME", actions)

    def test_page_du_recu_sans_percepteur_et_paiement_partiel(self):
        r = self.payer(self.perc, "CSF-0004", "MIN1", "10", paye=0)                 # 10 sur une tranche de 40
        self.assertEqual(r.status_code, 302)
        page = self.texte(self.perc.get(r.headers["Location"]))
        for attendu in ("Montant payé", "10,00", "Reste à payer (tranche)", "30,00"):
            self.assertIn(attendu, page)
        self.assertNotIn("<dt>Percepteur</dt>", page)

    def test_le_ticket_contient_les_informations_attendues(self):
        n = self.nouveau_recu()
        import io
        from pypdf import PdfReader
        t = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(self.perc.get(f"/m/paiement/recu/{n}/pdf").data)).pages)
        for attendu in (config.NOM_ECOLE, "REÇU DE PAIEMENT", n, "KABONGO TSHIALA ÉMILE", "CSF-0003", "65,00 USD",
                        "MONTANT PAYÉ", "RESTE À PAYER", "MERCI"):
            self.assertIn(attendu, t)
        t2 = PdfReader(io.BytesIO(self.perc.get(f"/m/paiement/recu/{n}/pdf?duplicata=1").data)).pages[0].extract_text()
        for interdit in ("Percepteur", "Démonstration", "DUPLICATA", "uplicata"):
            self.assertNotIn(interdit, t)
            self.assertNotIn(interdit, t2)
        self.assertEqual(t, t2)

    def test_original_refuse_a_qui_n_est_pas_le_percepteur(self):
        n = self.nouveau_recu()
        self.assertEqual(self.admin.get(f"/m/paiement/recu/{n}/pdf").status_code, 403)
        self.assertEqual(self.admin.get(f"/m/paiement/recu/{n}/pdf?duplicata=1").status_code, 200)   # duplicata ouvert
        security.creer_utilisateur(self.conn, "perc2", "Autre Percepteur", "PERCEPTEUR", MDP)
        c2 = self.app.test_client()
        self.entrer(c2, "perc2", MDP)
        self.assertEqual(c2.get(f"/m/paiement/recu/{n}/pdf").status_code, 403)
        page = self.texte(c2.get(f"/m/paiement/recu/{n}"))
        self.assertNotIn(f'href="/m/paiement/recu/{n}/pdf"', page)               # pas de bouton « Imprimer le reçu »
        self.assertIn(f'href="/m/paiement/recu/{n}/pdf?duplicata=1"', page)

    def test_original_refuse_apres_le_delai(self):
        n = self.nouveau_recu()
        ancien = web_paiement.DELAI_ORIGINAL_MIN
        web_paiement.DELAI_ORIGINAL_MIN = 0
        try:
            self.assertEqual(self.perc.get(f"/m/paiement/recu/{n}/pdf").status_code, 403)
            self.assertEqual(self.perc.get(f"/m/paiement/recu/{n}/pdf?duplicata=1").status_code, 200)
        finally:
            web_paiement.DELAI_ORIGINAL_MIN = ancien

    def test_recu_annule_non_imprimable(self):
        n = self.nouveau_recu()
        with self.conn:
            self.conn.execute("UPDATE PAIEMENT SET STATUT = 'ANNULE' WHERE N_RECU = ?", (n,))
        r = self.perc.get(f"/m/paiement/recu/{n}/pdf?duplicata=1")
        self.assertEqual(r.status_code, 400)
        self.assertIn("annulé", self.texte(r))

    def test_liste_des_recus_d_un_eleve(self):
        page = self.texte(self.admin.get("/m/paiement/duplicata/CSF-0001"))
        self.assertEqual(page.count("Imprimer le duplicata"), 6)
        self.assertIn("RECUS_ELEVE_CONSULTES", [x[0] for x in self.conn.execute("SELECT ACTION FROM JOURNAL")])
        self.assertIn("Aucun reçu enregistré", self.texte(self.admin.get("/m/paiement/duplicata/CSF-0006")))
        self.assertEqual(self.admin.get("/m/paiement/duplicata?q=CSF-0001").status_code, 302)


class TestSections(Base):
    """Un compte limité au primaire ne voit ni les élèves ni les reçus du secondaire."""
    def test_section_fermee(self):
        import sections
        self.assertEqual(sections.section_de_eleve(self.conn, "CSF-0001"), sections.SECONDAIRE)
        id_user = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = ?", (self.login,)).fetchone()[0]
        admin = security.authentifier(self.conn, "admin1", MDP).session
        sections.definir_sections(self.conn, admin, id_user, {sections.PRIMAIRE})
        n = self.perc.get("/m/paiement/eleve/CSF-0001")
        self.assertEqual(n.status_code, 403)
        self.assertEqual(self.perc.get("/m/paiement/recu/0001").status_code, 403)
        self.assertEqual(self.perc.get("/m/paiement/recu/0001/pdf?duplicata=1").status_code, 403)
        self.assertEqual(self.perc.get("/m/paiement/duplicata/CSF-0001").status_code, 403)
        self.assertEqual(self.payer(self.perc, "CSF-0004", "MIN1", "40").status_code, 403)


class TestCandidat(Base):
    donnees = {"nom": "Mbala", "postnom": "Zola", "prenom": "Eric", "annee": AN, "classe": "1"}

    def test_frais_affiches_puis_paiement(self):
        page = self.texte(self.perc.get("/m/paiement/inscription", query_string=self.donnees))
        self.assertIn("Frais d&#39;inscription", page)
        self.assertIn("30,00 USD", page)
        r = self.perc.post("/m/paiement/inscription/confirmer", data={**self.donnees, "codtf": "INSC"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("MBALA ZOLA ERIC", self.texte(r))
        r = self.perc.post("/m/paiement/inscription/enregistrer", data={**self.donnees, "codtf": "INSC"})
        self.assertEqual(r.status_code, 302)
        page = self.texte(self.perc.get(r.headers["Location"]))
        self.assertIn("Candidat", page)
        self.assertIn("MBALA ZOLA ERIC", page)
        # même candidat, mêmes frais : refusé (un seul reçu valide)
        r = self.perc.post("/m/paiement/inscription/enregistrer", data={**self.donnees, "codtf": "INSC"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("a déjà payé", self.texte(r))

    def test_champs_obligatoires(self):
        r = self.perc.post("/m/paiement/inscription/confirmer", data={**self.donnees, "nom": "", "codtf": "INSC"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("nom du candidat", self.texte(r))
        r = self.perc.post("/m/paiement/inscription/confirmer", data={**self.donnees, "classe": "", "codtf": "INSC"})
        self.assertEqual(r.status_code, 400)
        r = self.perc.post("/m/paiement/inscription/enregistrer", data={**self.donnees, "codtf": "MIN1"})   # pas un frais d'inscription
        self.assertEqual(r.status_code, 400)

    def test_recu_du_candidat_en_pdf(self):
        r = self.perc.post("/m/paiement/inscription/enregistrer", data={**self.donnees, "codtf": "INSC"})
        n = r.headers["Location"].rsplit("/", 1)[1]
        p = self.perc.get(f"/m/paiement/recu/{n}/pdf")
        self.assertEqual(p.status_code, 200)
        import io
        from pypdf import PdfReader
        t = PdfReader(io.BytesIO(p.data)).pages[0].extract_text()
        self.assertIn("CANDIDAT", t)
        self.assertIn("MBALA ZOLA ERIC", t)


class TestRapport(Base):
    def test_rapport_du_jour_et_pdf(self):
        aujourdhui = datetime.date.today().strftime("%d/%m/%Y")
        page = self.texte(self.perc.get("/m/paiement/rapport"))                  # date du jour par défaut
        self.assertIn("TOTAL GÉNÉRAL DE LA JOURNÉE", page)
        self.assertIn(aujourdhui, page)
        pdf = self.perc.get("/m/paiement/rapport/pdf", query_string={"date": aujourdhui})
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF-1.4"))

    def test_administrateur_choisit_un_percepteur(self):
        page = self.texte(self.admin.get("/m/paiement/rapport"))
        self.assertIn("Tous les percepteurs", page)
        self.assertIn("N° 1 - Percepteur Démonstration", page)
        self.assertIn("TOTAL GÉNÉRAL", self.texte(self.admin.get("/m/paiement/rapport?perc=1")))
        self.assertIn("Percepteur introuvable", self.texte(self.admin.get("/m/paiement/rapport?perc=99")))

    def test_date_invalide_et_jour_sans_paiement(self):
        self.assertIn("Date invalide", self.texte(self.perc.get("/m/paiement/rapport?date=n-importe-quoi")))
        self.assertIn("Aucun paiement encaissé", self.texte(self.perc.get("/m/paiement/rapport?date=01/01/2020")))
        r = self.perc.get("/m/paiement/rapport/pdf?date=01/01/2020")
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()

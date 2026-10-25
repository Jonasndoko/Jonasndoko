"""Tests du module Traçabilité et audit : droits, journal des activités, historique des opérations financières,
contrôles (intégrité, concordance), exports CSV / PDF.
Lancer :  python test_audit.py"""
import ast
import csv
import datetime
import os
import re
import tempfile
import unittest
from pathlib import Path

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import audit               # noqa: E402
import carte               # noqa: E402
import config              # noqa: E402
import database            # noqa: E402
import demo                # noqa: E402
import droits              # noqa: E402
import encaissements       # noqa: E402
import modules             # noqa: E402
import paiements           # noqa: E402
import referentiels as ref   # noqa: E402
import security            # noqa: E402
from audit import ErreurAudit   # noqa: E402

AUJOURDHUI = datetime.date.today()
AUJ_TXT = AUJOURDHUI.strftime("%d/%m/%Y")
DEMAIN = AUJOURDHUI + datetime.timedelta(days=1)


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(":memory:")
        self.login, self.mdp = demo.semer(self.conn)           # percepteur1 + 10 reçus enregistrés
        self.perc = security.authentifier(self.conn, self.login, self.mdp).session
        self.n_perc = paiements.numero_percepteur(self.conn, self.perc)
        security.creer_utilisateur(self.conn, "admin1", "Administrateur Test", "ADMINISTRATEUR", "Adm-Test#2026-xyz")
        self.admin = security.authentifier(self.conn, "admin1", "Adm-Test#2026-xyz").session
        security.creer_utilisateur(self.conn, "intend1", "Intendant Test", "INTENDANT", "Int-Test#2026-xyz")
        self.intendant = security.authentifier(self.conn, "intend1", "Int-Test#2026-xyz").session

    def donner(self, session, module, *accordes):
        with self.conn:
            droits.remplacer_droits(self.conn, session.id_user, {(module, d) for d in accordes})

    def actions(self, action=None):
        sql = "SELECT * FROM JOURNAL" + (" WHERE ACTION = ?" if action else "") + " ORDER BY ID_LOG"
        return self.conn.execute(sql, (action,) if action else ()).fetchall()


# ================================================================== droits
class TestDroits(Base):
    def test_sans_droit_refuse_partout(self):
        self.assertFalse(audit.peut(self.conn, self.intendant))
        for appel in (lambda: audit.journal(self.conn, self.intendant),
                      lambda: audit.historique_financier(self.conn, self.intendant),
                      lambda: audit.trace_operation(self.conn, self.intendant, "0001"),
                      lambda: audit.controle_journal(self.conn, self.intendant),
                      lambda: audit.controle_concordance(self.conn, self.intendant),
                      lambda: audit.exporter_journal(self.conn, self.intendant, "csv"),
                      lambda: audit.liste_utilisateurs(self.conn, self.intendant)):
            with self.assertRaises(PermissionError):
                appel()

    def test_percepteur_refuse(self):
        with self.assertRaises(PermissionError):
            audit.journal(self.conn, self.perc)

    def test_administrateur_toujours_autorise(self):
        self.assertTrue(audit.peut(self.conn, self.admin))
        self.assertGreater(audit.journal(self.conn, self.admin)["total"], 0)

    def test_droit_accorde_puis_retire_effet_immediat(self):
        self.donner(self.intendant, "audit", "LECTURE")
        self.assertTrue(audit.peut(self.conn, self.intendant))
        self.assertGreater(audit.journal(self.conn, self.intendant)["total"], 0)
        self.donner(self.intendant, "audit")
        with self.assertRaises(PermissionError):
            audit.journal(self.conn, self.intendant)

    def test_module_dans_le_menu(self):
        self.assertIn("audit", modules.modules_ouverts(self.conn, self.admin))
        self.assertNotIn("audit", modules.modules_ouverts(self.conn, self.intendant))
        self.donner(self.intendant, "audit", "LECTURE")
        self.assertIn("audit", modules.modules_ouverts(self.conn, self.intendant))

    def test_seule_la_lecture_existe(self):
        self.assertEqual(config.MODULES_DROITS["audit"][1], ("LECTURE",))
        with self.assertRaises(ValueError):
            droits.normaliser({("audit", "AJOUT")})

    def test_le_journal_reste_en_lecture_seule(self):
        with self.assertRaises(Exception):
            self.conn.execute("UPDATE JOURNAL SET DETAIL = 'x'")
        with self.assertRaises(Exception):
            self.conn.execute("DELETE FROM JOURNAL")


# ================================================================== catalogue
class TestCatalogue(unittest.TestCase):
    def test_toutes_les_actions_du_code_sont_cataloguees(self):
        """Filet de sécurité : une nouvelle action ajoutée au programme doit recevoir un libellé et une catégorie."""
        trouvees = set()
        for fichier in Path(__file__).parent.glob("*.py"):
            if fichier.name.startswith("test_"):
                continue
            for noeud in ast.walk(ast.parse(fichier.read_text(encoding="utf-8"))):
                if not isinstance(noeud, ast.Call) or len(noeud.args) < 3:
                    continue
                nom = noeud.func.attr if isinstance(noeud.func, ast.Attribute) else getattr(noeud.func, "id", "")
                if nom == "journaliser" and len(noeud.args) >= 4:   # journaliser(conn, id_user, login, ACTION, detail)
                    trouvees |= {c.value for c in ast.walk(noeud.args[3])
                                 if isinstance(c, ast.Constant) and isinstance(c.value, str)}
                elif nom in ("_tracer", "_journal"):           # _tracer(conn, session, ACTION, detail) : aides propres à chaque module
                    trouvees |= {c.value for c in ast.walk(noeud.args[2])
                                 if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        manquantes = sorted(a for a in trouvees if a not in audit.ACTIONS)
        self.assertEqual(manquantes, [], f"Actions du programme absentes de audit.ACTIONS : {manquantes}")
        self.assertGreater(len(trouvees), 30)                    # la recherche trouve bien les actions

    def test_chaque_action_a_une_categorie_valide(self):
        for code, (categorie, libelle) in audit.ACTIONS.items():
            self.assertIn(categorie, audit.CATEGORIES, code)
            self.assertTrue(libelle, code)
        self.assertEqual(audit.categorie_de("INCONNUE_X"), "AUTRE")
        self.assertEqual(audit.libelle_action("INCONNUE_X"), "INCONNUE_X")

    def test_actions_financieres_connues(self):
        self.assertTrue(audit.ACTIONS_FINANCIERES <= set(audit.ACTIONS))


# ================================================================== 1) journal des activités
class TestJournal(Base):
    def test_connexion_et_deconnexion_sont_tracees(self):
        security.fermer_session(self.conn, self.admin)
        security.fermer_session(self.conn, self.admin, "DECONNEXION_INACTIVITE")
        r = audit.journal(self.conn, self.admin, login="admin1", categorie="CONNEXION")
        libelles = [l["libelle"] for l in r["lignes"]]
        self.assertEqual(libelles[:2], ["Déconnexion automatique (inactivité)", "Déconnexion"])
        self.assertIn("Connexion", libelles)
        self.assertTrue(all(l["login"] == "admin1" for l in r["lignes"]))
        self.assertEqual(r["lignes"][0]["nom"], "Administrateur Test")
        self.assertEqual(r["lignes"][0]["poste"], "Administrateur")

    def test_echec_de_connexion_trace_meme_identifiant_inconnu(self):
        security.authentifier(self.conn, "fantome", "Mauvais-mdp#2026")
        r = audit.journal(self.conn, self.admin, login="fantome")
        self.assertEqual(r["lignes"][0]["libelle"], "Échec de connexion")
        self.assertIn("fantome", [l for l, _n in audit.liste_utilisateurs(self.conn, self.admin)])

    def test_ordre_recent_en_premier_et_limite(self):
        r = audit.journal(self.conn, self.admin, limite=5)
        self.assertEqual(len(r["lignes"]), 5)
        self.assertGreater(r["total"], 5)
        ids = [l["id"] for l in r["lignes"]]
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertEqual(len(audit.journal(self.conn, self.admin, limite=None)["lignes"]), r["total"])

    def test_filtre_periode(self):
        self.assertGreater(audit.journal(self.conn, self.admin, du=AUJOURDHUI, au=AUJOURDHUI)["total"], 0)
        self.assertEqual(audit.journal(self.conn, self.admin, du=DEMAIN)["total"], 0)
        self.assertEqual(audit.journal(self.conn, self.admin, au=AUJOURDHUI - datetime.timedelta(days=1))["total"], 0)
        with self.assertRaises(ErreurAudit):
            audit.journal(self.conn, self.admin, du=DEMAIN, au=AUJOURDHUI)
        with self.assertRaises(ErreurAudit):
            audit.journal(self.conn, self.admin, du="2026-01-01")

    def test_filtre_utilisateur(self):
        r = audit.journal(self.conn, self.admin, login="percepteur1")
        self.assertGreater(r["total"], 0)
        self.assertTrue(all(l["login"] == "percepteur1" for l in r["lignes"]))
        self.assertEqual(audit.journal(self.conn, self.admin, login="PERCEPTEUR1")["total"], r["total"])   # casse ignorée

    def test_filtre_categorie(self):
        r = audit.journal(self.conn, self.admin, categorie="AJOUT")
        self.assertGreater(r["total"], 0)
        self.assertTrue(all(l["categorie"] == "AJOUT" for l in r["lignes"]))
        with self.assertRaises(ErreurAudit):
            audit.journal(self.conn, self.admin, categorie="N_IMPORTE_QUOI")

    def test_categorie_autre_prend_les_codes_inconnus(self):
        with self.conn:
            database.journaliser(self.conn, None, "x", "ACTION_D_UNE_VERSION_FUTURE", "d")
        r = audit.journal(self.conn, self.admin, categorie="AUTRE")
        self.assertEqual([l["action"] for l in r["lignes"]], ["ACTION_D_UNE_VERSION_FUTURE"])
        self.assertEqual(r["lignes"][0]["libelle"], "ACTION_D_UNE_VERSION_FUTURE")

    def test_filtre_texte_sans_accents_ni_casse(self):
        security.fermer_session(self.conn, self.admin)
        for mot in ("déconnexion", "DECONNEXION", "deconnexion"):
            r = audit.journal(self.conn, self.admin, texte=mot)
            self.assertTrue(r["total"] >= 1 and all("DECONNEXION" in l["action"] for l in r["lignes"]), mot)
        detail = audit.journal(self.conn, self.admin, texte="CSF-0001 INSC")        # plusieurs mots : tous requis
        self.assertGreater(detail["total"], 0)
        self.assertTrue(all("CSF-0001" in l["detail"] for l in detail["lignes"]))
        self.assertEqual(audit.journal(self.conn, self.admin, texte="zzz-introuvable")["total"], 0)

    def test_texte_avec_caracteres_speciaux_ne_casse_rien(self):
        for texte in ("100%", "a_b", "'; DROP TABLE JOURNAL; --", "\\"):
            self.assertIsInstance(audit.journal(self.conn, self.admin, texte=texte)["total"], int)

    def test_filtre_operations_financieres(self):
        r = audit.journal(self.conn, self.admin, financier_seul=True)
        self.assertGreater(r["total"], 0)
        self.assertTrue(all(l["financier"] and l["action"] in audit.ACTIONS_FINANCIERES for l in r["lignes"]))

    def test_consultation_dun_dossier_est_tracee(self):
        carte.journaliser_consultation(self.conn, self.perc, "CSF-0001")
        paiements.journaliser_consultation_recus(self.conn, self.perc, "CSF-0002")
        r = audit.journal(self.conn, self.admin, categorie="CONSULTATION", login="percepteur1")
        libelles = {l["libelle"]: l["detail"] for l in r["lignes"]}
        self.assertEqual(libelles["Consultation de la fiche d'un élève (carte)"], "CSF-0001")
        self.assertEqual(libelles["Consultation des reçus d'un élève"], "CSF-0002")

    def test_ajout_modification_suppression_dune_donnee(self):
        ref.enregistrer(self.conn, self.admin, "niveaux", {"CODE_NIVEAU": "N9", "DESI_NIVEAU": "Neuvième", "SECTION": "SECONDAIRE"})
        ref.enregistrer(self.conn, self.admin, "niveaux", {"DESI_NIVEAU": "Neuvième année", "SECTION": "SECONDAIRE"}, ("N9",))
        ref.supprimer(self.conn, self.admin, "niveaux", ("N9",))
        ajout = audit.journal(self.conn, self.admin, categorie="AJOUT", login="admin1", texte="N9")["lignes"][0]
        modif = audit.journal(self.conn, self.admin, categorie="MODIFICATION", login="admin1", texte="N9")["lignes"][0]
        suppr = audit.journal(self.conn, self.admin, categorie="SUPPRESSION", login="admin1", texte="N9")["lignes"][0]
        self.assertIn("DESI_NIVEAU=Neuvième", ajout["detail"])                        # ce qui a été ajouté
        self.assertIn("DESI_NIVEAU : Neuvième -> Neuvième année", modif["detail"])    # avant -> après
        self.assertIn("DESI_NIVEAU=Neuvième année", suppr["detail"])                  # ce qui a été supprimé

    def test_donnees_personnelles_jamais_dans_le_journal(self):
        """Pour un élève, le journal garde quels champs ont changé, jamais leur contenu (nom, adresse, téléphone...)."""
        cle = ref.enregistrer(self.conn, self.admin, "eleves", {"NOM": "SECRETNOM", "ADRESSE": "Rue Secrète 9"})
        ref.enregistrer(self.conn, self.admin, "eleves",
                        {"NOM": "SECRETNOM", "ADRESSE": "Autre Rue Secrète 10", "TELEPHONE": "0899999999"}, cle)
        ref.supprimer(self.conn, self.admin, "eleves", cle)
        tout = " ".join(l["detail"] for l in audit.journal(self.conn, self.admin, texte=cle[0], limite=None)["lignes"])
        for secret in ("SECRETNOM", "Secrète", "0899999999"):
            self.assertNotIn(secret, tout)
        modif = audit.journal(self.conn, self.admin, categorie="MODIFICATION", texte=cle[0])["lignes"][0]
        self.assertIn("champs : ADRESSE, TELEPHONE", modif["detail"])

    def test_impression_dun_recu_tracee(self):
        paiements.preparer_pdf(self.conn, self.perc, "0001", duplicata=True)
        r = audit.journal(self.conn, self.admin, categorie="IMPRESSION", login="percepteur1")
        self.assertEqual((r["lignes"][0]["libelle"], r["lignes"][0]["detail"]), ("Impression d'un duplicata de reçu", "0001"))

    def test_ouverture_du_module_tracee(self):
        audit.journaliser_ouverture(self.conn, self.admin)
        l = audit.journal(self.conn, self.admin, login="admin1")["lignes"][0]
        self.assertEqual(l["libelle"], "Ouverture du module Traçabilité et audit")


# ================================================================== 2) opérations financières
class TestHistoriqueFinancier(Base):
    def _perc2(self):
        """Deuxième percepteur, qui enregistre un paiement."""
        security.creer_utilisateur(self.conn, "perc2", "Marie Percepteur", "PERCEPTEUR", "Marie-Test#2026-xyz")
        s = security.authentifier(self.conn, "perc2", "Marie-Test#2026-xyz").session
        self.donner(s, "paiement", "LECTURE", "AJOUT")
        return s

    def test_retrouver_le_paiement_dun_eleve_et_son_enregistreur(self):
        """Cas d'usage demandé : le paiement d'un élève et l'utilisateur qui l'a enregistré."""
        s2 = self._perc2()
        n_recu = paiements.enregistrer_paiement(self.conn, s2, "CSF-0004", "2026-2027", "INSC", 3000)
        r = audit.historique_financier(self.conn, self.admin, eleve="CSF-0004")
        self.assertEqual(len(r["operations"]), 1)
        o = r["operations"][0]
        self.assertEqual((o["type"], o["reference"], o["matricule"]), ("PAIEMENT", n_recu, "CSF-0004"))
        self.assertEqual((o["par_login"], o["par_nom"]), ("perc2", "Marie Percepteur"))
        self.assertEqual((o["montant"], o["devise"], o["statut"]), (3000, "USD", "Valide"))
        # un paiement du premier percepteur est bien attribué à lui
        autre = audit.historique_financier(self.conn, self.admin, eleve="CSF-0001")["operations"]
        self.assertTrue(autre and all(x["par_login"] == "percepteur1" for x in autre if x["type"] == "PAIEMENT"))

    def test_recherche_par_nom_sans_accents(self):
        r = audit.historique_financier(self.conn, self.admin, eleve="mbuyi kalala")
        self.assertGreater(len(r["operations"]), 0)
        self.assertTrue(all(o["matricule"] == "CSF-0001" for o in r["operations"]))
        r2 = audit.historique_financier(self.conn, self.admin, eleve="emile")             # « Émile »
        self.assertTrue(r2["operations"] and all(o["matricule"] == "CSF-0003" for o in r2["operations"]))

    def test_recherche_par_numero_de_recu(self):
        for saisie in ("0001", "1"):
            r = audit.historique_financier(self.conn, self.admin, n_recu=saisie)
            self.assertEqual([o["reference"] for o in r["operations"]], ["0001"])
        self.assertEqual(audit.historique_financier(self.conn, self.admin, n_recu="9999")["operations"], [])

    def test_eleve_introuvable(self):
        with self.assertRaises(ErreurAudit) as e:
            audit.historique_financier(self.conn, self.admin, eleve="Personne Inconnu")
        self.assertIn("Aucun élève trouvé", str(e.exception))

    def test_eleve_desactive_reste_retrouvable(self):
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET ACTIF = 0 WHERE MATRICULE = 'CSF-0001'")
        self.assertGreater(len(audit.historique_financier(self.conn, self.admin, eleve="CSF-0001")["operations"]), 0)

    def test_filtre_utilisateur_et_type(self):
        s2 = self._perc2()
        paiements.enregistrer_paiement(self.conn, s2, "CSF-0004", "2026-2027", "INSC", 3000)
        par_perc2 = audit.historique_financier(self.conn, self.admin, login="perc2")["operations"]
        self.assertEqual([o["par_login"] for o in par_perc2], ["perc2"])
        tous = audit.historique_financier(self.conn, self.admin, type_op="PAIEMENT")
        self.assertEqual(len(tous["operations"]), 11)
        self.assertTrue(all(o["type"] == "PAIEMENT" for o in tous["operations"]))
        with self.assertRaises(ErreurAudit):
            audit.historique_financier(self.conn, self.admin, type_op="INCONNU")

    def test_periode(self):
        self.assertEqual(len(audit.historique_financier(self.conn, self.admin, du=AUJOURDHUI, au=AUJOURDHUI)["operations"]), 10)
        self.assertEqual(audit.historique_financier(self.conn, self.admin, du=DEMAIN)["operations"], [])

    def test_totaux_par_devise(self):
        t = audit.historique_financier(self.conn, self.admin)["totaux"]
        self.assertEqual([x["devise"] for x in t], ["USD"])
        attendu = self.conn.execute("SELECT SUM(MONT_PAYE), COUNT(*) FROM PAIEMENT").fetchone()
        self.assertEqual((t[0]["paiements"], t[0]["paiements_nb"]), tuple(attendu))
        self.assertEqual(t[0]["net"], t[0]["paiements"])

    def test_annulation_de_paiement_qui_quand_pourquoi(self):
        ref.annuler_paiement(self.conn, self.admin, "0001", "Erreur de saisie du montant")
        r = audit.historique_financier(self.conn, self.admin, n_recu="0001")
        types = {o["type"]: o for o in r["operations"]}
        self.assertEqual(set(types), {"PAIEMENT", "ANNULATION"})
        self.assertEqual(types["PAIEMENT"]["statut"], "Annulé")
        self.assertEqual(types["PAIEMENT"]["par_login"], "percepteur1")          # qui l'avait enregistré
        self.assertEqual(types["ANNULATION"]["par_login"], "admin1")             # qui l'a annulé
        self.assertIn("Erreur de saisie du montant", types["ANNULATION"]["detail"])
        t = r["totaux"][0]
        self.assertEqual((t["annulations_nb"], t["net"]), (1, 0))
        fiche = audit.trace_operation(self.conn, self.admin, "0001")
        champs = dict(fiche["champs"])
        self.assertEqual(champs["Statut"], "ANNULÉ")
        self.assertIn("admin1", champs["Annulé par"])
        self.assertEqual(champs["Motif de l'annulation"], "Erreur de saisie du montant")
        self.assertEqual([e["action"] for e in fiche["evenements"]], ["PAIEMENT_ENREGISTRE", "PAIEMENT_ANNULE"])

    def test_filtre_annulations_par_type(self):
        ref.annuler_paiement(self.conn, self.admin, "0002", "Reçu établi pour le mauvais élève")
        r = audit.historique_financier(self.conn, self.admin, type_op="ANNULATION")
        self.assertEqual([(o["reference"], o["par_login"]) for o in r["operations"]], [("0002", "admin1")])

    def test_recu_et_duplicata_imprimes(self):
        paiements.preparer_pdf(self.conn, self.perc, "0003", duplicata=False)
        paiements.preparer_pdf(self.conn, self.perc, "0003", duplicata=True)
        r = audit.historique_financier(self.conn, self.admin, n_recu="0003")
        self.assertEqual(sorted(o["type"] for o in r["operations"]), ["DUPLICATA", "PAIEMENT", "RECU_IMPRIME"])
        self.assertTrue(all(o["matricule"] == "CSF-0001" for o in r["operations"]))
        fiche = audit.trace_operation(self.conn, self.admin, "0003")
        self.assertEqual([e["action"] for e in fiche["evenements"]],
                         ["PAIEMENT_ENREGISTRE", "RECU_IMPRIME", "DUPLICATA_IMPRIME"])

    def test_encaissement_remise_des_fonds_et_ecart(self):
        self.donner(self.intendant, "encaissement", "LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")
        n_enc = encaissements.enregistrer(self.conn, self.intendant, self.n_perc, AUJ_TXT, "USD", 25000, 24000)
        encaissements.enregistrer(self.conn, self.intendant, self.n_perc, AUJ_TXT, "USD", 10000, 10000)
        r = audit.historique_financier(self.conn, self.admin, type_op="ENCAISSEMENT")
        self.assertEqual(len(r["operations"]), 2)
        o = next(x for x in r["operations"] if x["reference"] == f"ENC-{n_enc}")
        self.assertEqual((o["montant"], o["verse"], o["ecart"], o["par_login"]), (25000, 24000, 1000, "intend1"))
        self.assertIn("manquant", o["detail"])
        # écarts seulement : le deuxième encaissement (écart nul) disparaît
        ecarts = audit.historique_financier(self.conn, self.admin, ecart_seul=True)["operations"]
        self.assertEqual([x["reference"] for x in ecarts], [f"ENC-{n_enc}"])
        t = r["totaux"][0]
        self.assertEqual((t["encaisse"], t["verse"], t["ecart"], t["encaissements_nb"]), (35000, 34000, 1000, 2))

    def test_encaissement_modifie_puis_supprime_reste_tracable(self):
        self.donner(self.intendant, "encaissement", "LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")
        n = encaissements.enregistrer(self.conn, self.intendant, self.n_perc, AUJ_TXT, "USD", 25000, 24000)
        encaissements.modifier(self.conn, self.intendant, n, self.n_perc, AUJ_TXT, "USD", 25000, 25000)
        fiche = audit.trace_operation(self.conn, self.admin, f"ENC-{n}")
        champs = dict(fiche["champs"])
        self.assertIn("aucun écart", champs["Écart (encaissé - versé)"])
        self.assertIn("intend1", champs["Enregistré par"])
        self.assertEqual([e["action"] for e in fiche["evenements"]], ["ENCAISSEMENT_ENREGISTRE", "ENCAISSEMENT_MODIFIE"])
        encaissements.supprimer(self.conn, self.intendant, n)
        types = [o["type"] for o in audit.historique_financier(self.conn, self.admin)["operations"]
                 if o["reference"] == f"ENC-{n}"]
        self.assertEqual(sorted(types), ["ENC_MODIFIE", "ENC_SUPPRIME"])               # plus dans la table : le journal reste
        supprime = audit.trace_operation(self.conn, self.admin, f"ENC-{n}")
        self.assertIn("supprimé", supprime["titre"])
        self.assertEqual([e["action"] for e in supprime["evenements"]],
                         ["ENCAISSEMENT_ENREGISTRE", "ENCAISSEMENT_MODIFIE", "ENCAISSEMENT_SUPPRIME"])

    def test_fiche_encaissement_compare_aux_recus_du_jour(self):
        self.donner(self.intendant, "encaissement", "LECTURE", "AJOUT")
        n = encaissements.enregistrer(self.conn, self.intendant, self.n_perc, AUJ_TXT, "USD", 1000, 1000)
        champs = dict(audit.trace_operation(self.conn, self.admin, f"ENC-{n}")["champs"])
        self.assertIn("10 reçu(s)", champs["Reçus valides du percepteur ce jour-là"])

    def test_trace_operation_introuvable(self):
        for ref_ in ("9999", "ENC-999", "ENC-x", ""):
            with self.assertRaises(ErreurAudit):
                audit.trace_operation(self.conn, self.admin, ref_)

    def test_recherche_ciblee_inscrite_au_journal(self):
        avant = len(self.actions("AUDIT_FINANCIER_CONSULTE"))
        audit.historique_financier(self.conn, self.admin)                               # liste générale : pas inscrite
        self.assertEqual(len(self.actions("AUDIT_FINANCIER_CONSULTE")), avant)
        audit.historique_financier(self.conn, self.admin, eleve="CSF-0001")
        lignes = self.actions("AUDIT_FINANCIER_CONSULTE")
        self.assertEqual(len(lignes), avant + 1)
        self.assertEqual(lignes[-1]["LOGIN"], "admin1")
        self.assertIn("CSF-0001", lignes[-1]["DETAIL"])

    def test_recherche_sur_eleve_n_affiche_pas_les_encaissements(self):
        self.donner(self.intendant, "encaissement", "LECTURE", "AJOUT")
        encaissements.enregistrer(self.conn, self.intendant, self.n_perc, AUJ_TXT, "USD", 1000, 900)
        types = {o["type"] for o in audit.historique_financier(self.conn, self.admin, eleve="CSF-0001")["operations"]}
        self.assertNotIn("ENCAISSEMENT", types)

    def test_limite(self):
        r = audit.historique_financier(self.conn, self.admin, limite=3)
        self.assertEqual((len(r["operations"]), r["total"]), (3, 10))


# ================================================================== 3) contrôles
class TestControles(Base):
    def test_journal_intact(self):
        e = audit.controle_journal(self.conn, self.admin)
        self.assertTrue(e["ok"])
        self.assertGreater(e["nb_lignes"], 10)
        self.assertEqual(len(e["derniere_empreinte"]), 64)
        self.assertTrue(self.actions("AUDIT_CONTROLE"))

    def test_modification_du_journal_detectee(self):
        self.conn.execute("DROP TRIGGER JOURNAL_NO_UPDATE")                             # fraude : on contourne le verrou
        with self.conn:
            self.conn.execute("UPDATE JOURNAL SET DETAIL = 'falsifié' WHERE ID_LOG = 3")
        e = audit.controle_journal(self.conn, self.admin)
        self.assertFalse(e["ok"])
        self.assertEqual(e["anomalie"], 3)

    def test_concordance_sans_anomalie(self):
        self.assertEqual(audit.controle_concordance(self.conn, self.admin), [])

    def test_concordance_recu_sans_trace_et_trou_de_numerotation(self):
        # un reçu inséré directement dans la base, hors application (aucune trace au journal, n° 0012 : le 0011 manque)
        with self.conn:
            self.conn.execute(
                "INSERT INTO PAIEMENT (N_RECU, ANNEESCO, NUM_SEQ, DATE_PAY, MATRICULE, N_CLASSE, CODTF, CODE_DEVISE, MONT_PAYE, N_PERC) "
                "VALUES ('0012','2026-2027',12,?, 'CSF-0001', 2, 'MIN2','USD', 100, ?)",
                (database.iso(database.maintenant()), self.n_perc))
        messages = " | ".join(a["message"] for a in audit.controle_concordance(self.conn, self.admin))
        self.assertIn("Reçu 0012 : aucune trace de son enregistrement", messages)
        self.assertIn("0011", messages)

    def test_concordance_reçu_annule_hors_application(self):
        with self.conn:
            self.conn.execute("UPDATE PAIEMENT SET STATUT='ANNULE', MOTIF_ANNULATION='x', DATE_ANNULATION=?, ANNULE_PAR='z' "
                              "WHERE N_RECU='0002'", (database.iso(database.maintenant()),))
        messages = " | ".join(a["message"] for a in audit.controle_concordance(self.conn, self.admin))
        self.assertIn("Reçu 0002 : annulé, mais aucune trace de l'annulation", messages)

    def test_concordance_ecart_incoherent(self):
        self.donner(self.intendant, "encaissement", "LECTURE", "AJOUT")
        n = encaissements.enregistrer(self.conn, self.intendant, self.n_perc, AUJ_TXT, "USD", 25000, 24000)
        with self.conn:
            self.conn.execute("UPDATE ENCAISSEMENT SET ECART = 0 WHERE N_ENC = ?", (n,))
        anomalies = audit.controle_concordance(self.conn, self.admin)
        self.assertEqual(len(anomalies), 1)
        self.assertIn(f"ENC-{n}", anomalies[0]["message"])
        self.assertEqual(anomalies[0]["gravite"], "ÉLEVÉE")

    def test_concordance_encaissement_sans_trace(self):
        with self.conn:
            self.conn.execute("INSERT INTO ENCAISSEMENT (DATE_ENC, N_PERC, CODE_DEVISE, MONT_ENCAISSE, MONT_VERSE, ECART, "
                              "SAISI_PAR, DATE_SAISIE) VALUES (?,?,?,?,?,?,?,?)",
                              (AUJOURDHUI.isoformat(), self.n_perc, "USD", 500, 500, 0, "intend1",
                               database.iso(database.maintenant())))
        messages = " | ".join(a["message"] for a in audit.controle_concordance(self.conn, self.admin))
        self.assertIn("aucune trace de son enregistrement", messages)

    def test_encaissement_supprime_par_l_application_n_est_pas_une_anomalie(self):
        self.donner(self.intendant, "encaissement", "LECTURE", "AJOUT", "SUPPRESSION")
        n = encaissements.enregistrer(self.conn, self.intendant, self.n_perc, AUJ_TXT, "USD", 500, 500)
        encaissements.supprimer(self.conn, self.intendant, n)
        self.assertEqual(audit.controle_concordance(self.conn, self.admin), [])

    def test_etat_journal_sert_aux_exports(self):
        e = audit.etat_journal(self.conn)
        self.assertTrue(e["ok"])
        self.assertEqual(e["nb_lignes"], self.conn.execute("SELECT COUNT(*) FROM JOURNAL").fetchone()[0])


# ================================================================== exports
class TestExports(Base):
    def test_export_csv_journal(self):
        chemin = audit.exporter_journal(self.conn, self.admin, "csv", login="percepteur1")
        self.assertTrue(chemin.endswith(".csv") and os.path.dirname(chemin) == str(config.DOSSIER_AUDIT))
        brut = open(chemin, "rb").read()
        self.assertTrue(brut.startswith(b"\xef\xbb\xbf"))                                # UTF-8 avec BOM (Excel)
        lignes = list(csv.reader(open(chemin, encoding="utf-8-sig", newline=""), delimiter=";"))
        self.assertEqual(lignes[0][0], "Date et heure")
        self.assertEqual(len(lignes) - 1, audit.journal(self.conn, self.admin, login="percepteur1", limite=None)["total"])
        self.assertTrue(all(l[1] == "percepteur1" for l in lignes[1:]))

    def test_export_csv_neutralise_les_formules(self):
        with self.conn:
            database.journaliser(self.conn, None, "=CMD()", "CONNEXION_ECHEC", "+1+1")
        chemin = audit.exporter_journal(self.conn, self.admin, "csv", login="=CMD()")
        ligne = list(csv.reader(open(chemin, encoding="utf-8-sig", newline=""), delimiter=";"))[1]
        self.assertEqual((ligne[1], ligne[6]), ("'=CMD()", "'+1+1"))

    def test_export_csv_historique_garde_les_montants_negatifs(self):
        self.donner(self.intendant, "encaissement", "LECTURE", "AJOUT")
        encaissements.enregistrer(self.conn, self.intendant, self.n_perc, AUJ_TXT, "USD", 1000, 1500)   # excédent
        chemin = audit.exporter_historique(self.conn, self.admin, "csv", type_op="ENCAISSEMENT")
        ligne = list(csv.reader(open(chemin, encoding="utf-8-sig", newline=""), delimiter=";"))[1]
        self.assertEqual(ligne[7], "-5,00")                                              # écart négatif non altéré

    def test_export_pdf_journal(self):
        chemin = audit.exporter_journal(self.conn, self.admin, "pdf")
        brut = open(chemin, "rb").read()
        self.assertTrue(brut.startswith(b"%PDF-1.4") and brut.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"/MediaBox [0 0 841.89 595.28]", brut)                            # A4 paysage

    def test_export_pdf_plusieurs_pages(self):
        with self.conn:
            for i in range(300):
                database.journaliser(self.conn, None, "x", "CONNEXION_ECHEC", f"tentative {i} " + "mot " * 40)
        chemin = audit.exporter_journal(self.conn, self.admin, "pdf", login="x")
        brut = open(chemin, "rb").read()
        pages = int(re.search(rb"/Count (\d+)", brut).group(1))
        self.assertGreater(pages, 3)
        self.assertIn(f"Page {pages} / {pages}".encode(), brut)

    def test_export_pdf_historique(self):
        ref.annuler_paiement(self.conn, self.admin, "0001", "Erreur de saisie du montant")
        chemin = audit.exporter_historique(self.conn, self.admin, "pdf")
        brut = open(chemin, "rb").read()
        self.assertTrue(brut.startswith(b"%PDF-1.4") and brut.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"Annulation", brut)

    def test_export_inscrit_au_journal(self):
        audit.exporter_journal(self.conn, self.admin, "csv", login="percepteur1")
        l = self.actions("AUDIT_EXPORTE")[-1]
        self.assertEqual(l["LOGIN"], "admin1")
        self.assertIn("CSV", l["DETAIL"])
        self.assertIn("percepteur1", l["DETAIL"])

    def test_export_vide_ou_format_inconnu_refuse(self):
        with self.assertRaises(ErreurAudit):
            audit.exporter_journal(self.conn, self.admin, "csv", du=DEMAIN)
        with self.assertRaises(ErreurAudit):
            audit.exporter_journal(self.conn, self.admin, "docx")
        with self.assertRaises(ErreurAudit):
            audit.exporter_historique(self.conn, self.admin, "csv", du=DEMAIN)

    def test_export_sans_droit_refuse(self):
        with self.assertRaises(PermissionError):
            audit.exporter_historique(self.conn, self.intendant, "csv")


if __name__ == "__main__":
    unittest.main()

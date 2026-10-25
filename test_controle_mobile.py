"""Tests de l'application mobile de contrôle (web_controle_mobile.py + controle.py) : activation par l'autorité académique, connexion,
choix du frais, contrôle par QR ou matricule, coupure en cours de route, sections, journal, lecture du QR sur le serveur.
Lancer :  python -m unittest test_controle_mobile"""
import io
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web         # noqa: E402
import database        # noqa: E402
import demo            # noqa: E402
import droits          # noqa: E402
import paiements       # noqa: E402
import qr              # noqa: E402
import qr_lecture      # noqa: E402
import security        # noqa: E402

AN = demo.ANNEE_COURANTE
MDP = "Tr@vail-Amour-2026"
H = lambda jeton: {"Authorization": "Bearer " + jeton}


class Base(unittest.TestCase):
    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "c.db")
        self.conn = database.connecter(self.chemin)
        self.login, self.mdp = demo.semer(self.conn)
        security.creer_utilisateur(self.conn, "admin1", "Alice Directrice", "ADMINISTRATEUR", MDP)
        security.creer_utilisateur(self.conn, "dir1", "Diane Études", "DIRECTRICE_ETUDES", MDP)
        security.creer_utilisateur(self.conn, "ctrl1", "Cédric Contrôleur", "CONTROLEUR", MDP)
        self.id_dir = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN='dir1'").fetchone()[0]
        self.id_ctrl = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN='ctrl1'").fetchone()[0]
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_ctrl, {("controle", "LECTURE")})
        self.app = app_web.creer_app(self.chemin)
        self.web = self.app.test_client()                      # navigateur de l'autorité (cookie)
        self.tel = self.app.test_client()                      # téléphone du contrôleur (jeton)
        self.assertEqual(self.web.post("/connexion", data={"login": "admin1", "mdp": MDP}).status_code, 302)

    def activer(self, oui=True):
        r = self.web.post("/m/controle/mobile", data={"action": "activer" if oui else "couper"})
        self.assertEqual(r.status_code, 302)

    def connexion(self, login="ctrl1", mdp=MDP):
        return self.tel.post("/mobile/api/connexion", json={"login": login, "mdp": mdp})

    def jeton(self, login="ctrl1", mdp=MDP):
        r = self.connexion(login, mdp)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()["jeton"]

    def controler(self, jeton, code, frais="TOUS"):
        return self.tel.post("/mobile/api/controle", json={"code": code, "frais": frais}, headers=H(jeton))

    def journal(self, action):
        return self.conn.execute("SELECT COUNT(*) FROM JOURNAL WHERE ACTION = ?", (action,)).fetchone()[0]

    def code_qr(self, matricule):
        """Les élèves de la démonstration n'ont pas encore de QR : le logiciel l'attribue à la première demande (identite.py)."""
        import identite
        with self.conn:
            return identite.assurer_code_qr(self.conn, matricule)

    def payer_tout(self, matricule="CSF-0001"):
        perc = security.authentifier(self.conn, self.login, self.mdp).session
        for codtf, c in (("MIN1", 4500), ("MIN2", 9000), ("EXAM", 1500)):
            paiements.enregistrer_paiement(self.conn, perc, matricule, AN, codtf, c)


class TestActivation(Base):
    def test_coupee_par_defaut(self):
        r = self.connexion()
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.get_json()["coupee"])
        self.assertEqual(self.tel.get("/controleur").status_code, 200)         # la page, elle, s'ouvre toujours

    def test_activation_par_l_administrateur(self):
        self.activer()
        self.assertEqual(self.connexion().status_code, 200)
        self.assertEqual(self.journal("CONTROLE_MOBILE_ACTIVE"), 1)
        t = self.web.get("/m/controle/mobile?fait=activer").get_data(as_text=True)
        self.assertIn("ACTIVÉE", t)
        self.assertIn("/controleur", t)
        self.assertIn("<svg", t)                                               # QR de l'adresse de l'application

    def test_autorite_sans_droit_refusee(self):
        dir_ = self.app.test_client()
        dir_.post("/connexion", data={"login": "dir1", "mdp": MDP})
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_dir, {("controle", "LECTURE")})
        self.assertEqual(dir_.get("/m/controle/mobile").status_code, 403)
        self.assertEqual(dir_.post("/m/controle/mobile", data={"action": "activer"}).status_code, 403)
        self.assertNotIn("Application mobile", dir_.get("/m/controle").get_data(as_text=True))
        self.assertFalse(controle_actif(self.conn))

    def test_autorite_avec_modification_active(self):
        dir_ = self.app.test_client()
        dir_.post("/connexion", data={"login": "dir1", "mdp": MDP})
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_dir, {("controle", "LECTURE"), ("controle", "MODIFICATION")})
        self.assertIn("Application mobile", dir_.get("/m/controle").get_data(as_text=True))
        self.assertEqual(dir_.post("/m/controle/mobile", data={"action": "activer"}).status_code, 302)
        self.assertTrue(controle_actif(self.conn))
        self.assertEqual(dir_.post("/m/controle/mobile", data={"action": "n'importe quoi"}).status_code, 400)

    def test_origine_etrangere_refusee(self):
        r = self.web.post("/m/controle/mobile", data={"action": "activer"}, headers={"Origin": "https://pirate.example"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(controle_actif(self.conn))

    def test_non_connecte(self):
        c = self.app.test_client()
        self.assertEqual(c.get("/m/controle/mobile").status_code, 302)
        self.assertEqual(c.post("/m/controle/mobile", data={"action": "activer"}).status_code, 302)

    def test_coupure_en_cours_de_route(self):
        self.activer()
        j = self.jeton()
        self.assertEqual(self.controler(j, "CSF-0001").status_code, 200)
        self.activer(False)
        r = self.controler(j, "CSF-0001")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.get_json()["coupee"])
        self.activer()                                   # réactivée : l'ancienne session a été fermée, il faut se reconnecter
        self.assertEqual(self.controler(j, "CSF-0001").status_code, 401)
        self.assertEqual(self.journal("CONTROLE_MOBILE_COUPE"), 1)


def controle_actif(conn):
    import controle
    return controle.mobile_actif(conn)


class TestConnexion(Base):
    def setUp(self):
        super().setUp()
        self.activer()

    def test_mauvais_mot_de_passe(self):
        r = self.connexion(mdp="Faux-Mot-2026!")
        self.assertEqual(r.status_code, 401)
        self.assertIn("erreur", r.get_json())

    def test_sans_droit_de_controle(self):
        r = self.connexion("dir1")
        self.assertEqual(r.status_code, 403)
        self.assertNotIn("jeton", r.get_json())

    def test_administrateur_accepte(self):
        self.assertEqual(self.connexion("admin1").status_code, 200)

    def test_api_sans_jeton_ou_mauvais_type(self):
        for url in ("/mobile/api/frais",):
            self.assertEqual(self.tel.get(url).status_code, 401)
            self.assertEqual(self.tel.get(url, headers=H("n-importe-quoi")).status_code, 401)
        import sessions_web
        j = sessions_web.ouvrir(self.id_ctrl, "PERSONNEL")                          # un jeton d'un autre type ne marche pas ici
        self.assertEqual(self.tel.get("/mobile/api/frais", headers=H(j)).status_code, 401)

    def test_deconnexion(self):
        j = self.jeton()
        self.assertEqual(self.tel.post("/mobile/api/deconnexion", headers=H(j)).status_code, 200)
        self.assertEqual(self.tel.get("/mobile/api/frais", headers=H(j)).status_code, 401)

    def test_droit_retire_effet_immediat(self):
        j = self.jeton()
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_ctrl, set())
        self.assertEqual(self.controler(j, "CSF-0001").status_code, 403)

    def test_mot_de_passe_a_changer_d_abord(self):
        security.creer_utilisateur(self.conn, "ctrl2", "Nadine Contrôleuse", "CONTROLEUR", MDP, doit_changer=True)
        i = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN='ctrl2'").fetchone()[0]
        with self.conn:
            droits.remplacer_droits(self.conn, i, {("controle", "LECTURE")})
        r = self.connexion("ctrl2")
        self.assertTrue(r.get_json()["doit_changer_mdp"])
        j = r.get_json()["jeton"]
        self.assertEqual(self.controler(j, "CSF-0001").status_code, 403)
        self.assertEqual(self.tel.get("/mobile/api/frais", headers=H(j)).status_code, 403)
        faux = self.tel.post("/mobile/api/mot-de-passe", headers=H(j), json={"ancien": "x", "nouveau": "Autre-Mdp-2027!", "confirmation": "Autre-Mdp-2027!"})
        self.assertEqual(faux.status_code, 400)                                    # erreur affichable, la session reste ouverte
        ok = self.tel.post("/mobile/api/mot-de-passe", headers=H(j), json={"ancien": MDP, "nouveau": "Autre-Mdp-2027!", "confirmation": "Autre-Mdp-2027!"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.controler(j, "CSF-0001").status_code, 200)


class TestControle(Base):
    def setUp(self):
        super().setUp()
        self.activer()
        self.j = self.jeton()

    def test_liste_des_frais(self):
        d = self.tel.get("/mobile/api/frais", headers=H(self.j)).get_json()
        codes = [c for c, _ in d["frais"]]
        self.assertEqual(sorted(codes), ["EXAM", "INSC", "MIN1", "MIN2"])

    def test_tous_les_frais_impaye(self):
        r = self.controler(self.j, "CSF-0001").get_json()
        self.assertEqual((r["statut"], r["couleur"], r["identification"]), ("IMPAYÉ", "impaye", "MATRICULE"))
        self.assertEqual(r["frais_choisi"], "Tous les frais")
        self.assertTrue(any(l["reste_positif"] for l in r["lignes"]))
        self.assertNotIn("tuteur", str(r).lower())                                  # rien de plus que la situation de l'élève

    def test_tous_les_frais_en_ordre(self):
        self.payer_tout()
        r = self.controler(self.j, "CSF-0001").get_json()
        self.assertEqual((r["statut"], r["couleur"]), ("EN ORDRE", "ordre"))

    def test_un_seul_frais(self):
        ok = self.controler(self.j, "CSF-0001", "INSC").get_json()                  # inscription payée dans la démonstration
        self.assertEqual((ok["statut"], ok["frais_choisi"]), ("EN ORDRE", "Frais d'inscription"))
        self.assertEqual(len(ok["lignes"]), 1)
        nok = self.controler(self.j, "CSF-0001", "MIN1").get_json()
        self.assertEqual(nok["statut"], "IMPAYÉ")
        self.assertEqual(len(nok["lignes"]), 1)

    def test_un_seul_frais_ne_cache_pas_ce_qui_est_dans_la_liste_web(self):
        """Mêmes résultats que la liste des élèves en ordre du module web."""
        import controle
        c = self.conn
        s = security.authentifier(c, "admin1", MDP).session
        for codtf in ("INSC", "MIN1", "EXAM"):
            liste = controle.eleves_en_ordre(c, s, AN, "8ème A", None, codtf)
            en_ordre_web = {l["matricule"] for l in liste["lignes"]}
            for (m,) in c.execute("SELECT MATRICULE FROM INSCRIRE WHERE ANNEESCO = ? AND N_CLASSE = 2", (AN,)).fetchall():
                r = self.controler(self.j, m, codtf).get_json()
                self.assertEqual(r["statut"] == "EN ORDRE", m in en_ordre_web, (m, codtf, r["statut"]))

    def test_frais_non_du_pour_la_classe(self):
        with self.conn:                                  # EXAM sans montant dans le type et sans tarif de classe : pas dû
            self.conn.execute("UPDATE TYPE_FRAIS SET MONTANT = NULL, CODE_DEVISE = NULL WHERE CODTF = 'EXAM'")
        r = self.controler(self.j, "CSF-0001", "EXAM").get_json()
        self.assertEqual((r["statut"], r["couleur"]), ("FRAIS NON DÛ", "autre"))     # jamais « en ordre » par défaut

    def test_non_inscrit(self):
        with self.conn:
            self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('CSF-0099', 'ZEBRE')")
        self.assertEqual(self.controler(self.j, "CSF-0099").get_json()["statut"], "NON INSCRIT")
        self.assertEqual(self.controler(self.j, "CSF-0099", "INSC").get_json()["statut"], "NON INSCRIT")

    def test_qr_de_la_carte(self):
        qrcode = self.code_qr("CSF-0001")
        r = self.controler(self.j, qrcode).get_json()
        self.assertEqual((r["matricule"], r["identification"]), ("CSF-0001", "QR"))

    def test_faux_qr_refuse(self):
        r = self.controler(self.j, "CSF|CSF-0001|AAAAAAAAAAAA")                     # bon matricule, mauvais code : carte falsifiée
        self.assertEqual(r.status_code, 400)
        self.assertIn("Carte non reconnue", r.get_json()["erreur"])

    def test_matricule_inconnu_et_vide(self):
        self.assertIn("introuvable", self.controler(self.j, "XYZ").get_json()["erreur"])
        self.assertEqual(self.controler(self.j, "   ").status_code, 400)
        self.assertEqual(self.controler(self.j, "A" * 200).status_code, 400)

    def test_frais_inconnu(self):
        self.assertEqual(self.controler(self.j, "CSF-0001", "BIDON").status_code, 400)

    def test_corps_illisible(self):
        r = self.tel.post("/mobile/api/controle", data="pas du json", headers=H(self.j))
        self.assertEqual(r.status_code, 400)

    def test_matricule_tape_en_minuscules_et_avec_tiret(self):
        r = self.controler(self.j, " csf-0001 ").get_json()
        self.assertEqual(r["matricule"], "CSF-0001")

    def test_matricule_format_ecole(self):
        with self.conn:
            self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('0007/26', 'KABILA')")
        self.assertEqual(self.controler(self.j, "0007-26").get_json()["matricule"], "0007/26")
        self.assertEqual(self.controler(self.j, "0007/26").get_json()["matricule"], "0007/26")

    def test_photo(self):
        self.assertIsNone(self.controler(self.j, "CSF-0001").get_json()["photo"])
        with self.conn:
            self.conn.execute("INSERT INTO PHOTO_ELEVE VALUES ('CSF-0001', ?, '2026-01-01', 'x')", (b"\xff\xd8\xff\xd9",))
        self.assertTrue(self.controler(self.j, "CSF-0001").get_json()["photo"].startswith("data:image/jpeg;base64,"))

    def test_journal(self):
        self.controler(self.j, "CSF-0001", "INSC")
        self.controler(self.j, "XYZ")                                               # un échec n'est pas un contrôle
        ligne = self.conn.execute("SELECT LOGIN, DETAIL FROM JOURNAL WHERE ACTION='CONTROLE_MOBILE'").fetchall()
        self.assertEqual(len(ligne), 1)
        self.assertEqual((ligne[0]["LOGIN"], ligne[0]["DETAIL"]), ("ctrl1", "CSF-0001 | INSC | EN ORDRE | MATRICULE"))
        self.assertEqual(self.journal("CONTROLE_MOBILE_CONNEXION"), 1)

    def test_section_fermee(self):
        with self.conn:
            self.conn.execute("UPDATE NIVEAU SET SECTION = 'PRIMAIRE' WHERE CODE_NIVEAU = 'N8'")
            self.conn.execute("INSERT INTO SECTION_UTILISATEUR (ID_USER, SECTION) VALUES (?, 'SECONDAIRE')", (self.id_ctrl,))
        self.assertEqual(self.controler(self.j, "CSF-0001").status_code, 403)

    def test_le_controle_web_n_a_pas_change(self):
        admin = self.web
        t = admin.get("/m/controle/eleve/CSF-0001").get_data(as_text=True)
        self.assertIn("IMPAYÉ", t)
        self.assertEqual(self.journal("CONTROLE_NUMERIQUE"), 1)
        self.assertEqual(self.journal("CONTROLE_MOBILE"), 0)


class TestPageEtLecteurQR(Base):
    def test_page_et_manifeste(self):
        p = self.tel.get("/controleur").get_data(as_text=True)
        self.assertIn("manifest.webmanifest", p)
        self.assertNotIn("innerHTML", p)                                            # texte du serveur toujours inséré avec textContent
        self.assertNotIn("__ECOLE__", p)
        m = self.tel.get("/controleur/manifest.webmanifest")
        self.assertEqual(m.status_code, 200)
        self.assertEqual(m.get_json()["start_url"], "/controleur")
        for ic in m.get_json()["icons"]:
            r = self.tel.get(ic["src"])
            self.assertEqual(r.status_code, 200)
            r.close()

    def test_installable_sur_le_telephone(self):
        """Critères d'installation : manifeste complet (id, nom, standalone, icônes 192/512 + maskable), service worker valide
        qui couvre /controleur, icône iPhone, bouton d'installation dans la page."""
        m = self.tel.get("/controleur/manifest.webmanifest").get_json()
        for cle in ("id", "name", "short_name", "start_url", "scope", "background_color", "theme_color"):
            self.assertTrue(m.get(cle), cle)
        self.assertEqual(m["display"], "standalone")
        tailles = {(i["sizes"], i.get("purpose")) for i in m["icons"]}
        for t in ("192x192", "512x512"):
            self.assertIn((t, "any"), tailles)
            self.assertIn((t, "maskable"), tailles)
        from PIL import Image
        for ic in m["icons"]:
            r = self.tel.get(ic["src"])
            self.assertEqual(r.headers["Content-Type"], "image/png")
            self.assertEqual("%dx%d" % Image.open(io.BytesIO(r.data)).size, ic["sizes"])
            r.close()
        sw = self.tel.get("/controleur-sw.js")
        self.assertEqual(sw.status_code, 200)
        self.assertIn("javascript", sw.headers["Content-Type"])
        self.assertEqual(sw.headers["Service-Worker-Allowed"], "/controleur")
        t = sw.get_data(as_text=True)
        self.assertIn('addEventListener("fetch"', t)
        self.assertNotIn("__VERSION__", t)
        p = self.tel.get("/controleur").get_data(as_text=True)
        for morceau in ("/controleur-sw.js", "apple-touch-icon", "controleur_180.png", "beforeinstallprompt", 'id="b-installer"'):
            self.assertIn(morceau, p)
        self.assertEqual(self.tel.get("/assets/controleur_180.png").status_code, 200)

    @unittest.skipUnless(qr_lecture.disponible(), "OpenCV absent")
    def test_lecture_du_qr_sur_le_serveur(self):
        from PIL import Image
        self.activer()
        j = self.jeton()
        qrcode = self.code_qr("CSF-0001")
        m = qr.matrice(qrcode)
        n, k, bord = len(m), 6, 5
        img = Image.new("L", ((n + 2 * bord) * k,) * 2, 255)
        for y, ligne in enumerate(m):
            for x, noir in enumerate(ligne):
                if noir:
                    img.paste(0, ((x + bord) * k, (y + bord) * k, (x + bord + 1) * k, (y + bord + 1) * k))
        tampon = io.BytesIO()
        img.convert("RGB").save(tampon, "JPEG", quality=70)
        r = self.tel.post("/mobile/api/decoder", data=tampon.getvalue(), headers={**H(j), "Content-Type": "image/jpeg"})
        self.assertEqual(r.get_json()["code"], qrcode)
        vide = io.BytesIO()
        Image.new("RGB", (200, 200), "white").save(vide, "JPEG")
        r = self.tel.post("/mobile/api/decoder", data=vide.getvalue(), headers={**H(j), "Content-Type": "image/jpeg"})
        self.assertIsNone(r.get_json()["code"])

    def test_decoder_refuse_ce_qui_n_est_pas_un_jpeg(self):
        self.activer()
        j = self.jeton()
        if qr_lecture.disponible():
            r = self.tel.post("/mobile/api/decoder", data=b"<html>", headers={**H(j), "Content-Type": "image/jpeg"})
            self.assertEqual(r.status_code, 400)
        self.assertEqual(self.tel.post("/mobile/api/decoder", data=b"x").status_code, 401)

    def test_dimensions_jpeg(self):
        from PIL import Image
        t = io.BytesIO()
        Image.new("RGB", (123, 45)).save(t, "JPEG")
        self.assertEqual(qr_lecture.dimensions_jpeg(t.getvalue()), (123, 45))
        self.assertIsNone(qr_lecture.dimensions_jpeg(b"\xff\xd8\xff\xd9"))


if __name__ == "__main__":
    unittest.main()

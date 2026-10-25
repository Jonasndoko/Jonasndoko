"""Serveur web de la saisie des points (professeurs : ordinateur, tablette ou téléphone sur le réseau de l'école).

Aucune bibliothèque externe : http.server de Python. Le serveur tourne sur l'ordinateur de l'école, soit lancé depuis le logiciel
(Direction des études > Enseignants et classes > « Démarrer le serveur »), soit seul : `python serveur_notes.py` (Lancer_Professeurs.bat).

Sécurité :
- Connexion avec l'identifiant et le mot de passe du compte « Professeur » (mêmes règles que le logiciel : blocage après échecs,
  journal, mot de passe provisoire à changer). Le navigateur reçoit un jeton aléatoire ; l'identité du professeur vient toujours de
  ce jeton et de la base, jamais d'une donnée envoyée par la page.
- Session fermée après config.DELAI_INACTIVITE_PROF_MIN minutes sans activité. Trop d'échecs depuis une même adresse : refus temporaire.
- Chaque requête ouvre sa propre connexion à la base et passe par notes.py, qui contrôle que le cours appartient au professeur.
- Le trafic du réseau de l'école n'est pas chiffré (http) : à utiliser sur le Wi-Fi de l'école, pas sur Internet.
"""
import json
import secrets
import socket
import sys
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import api_professeur
import bulletins
import config
import database
import notes
import presence_eleves
import security
from database import maintenant

TAILLE_MAX = 200_000                 # octets d'une requête
ECHECS_MAX_PAR_ADRESSE = 25          # échecs de connexion par adresse et par fenêtre
FENETRE_ECHECS = timedelta(minutes=10)
SESSIONS_MAX = 300


class _Etat:
    def __init__(self, chemin_bd):
        self.chemin_bd = chemin_bd
        self.verrou = threading.Lock()
        self.sessions = {}               # jeton -> Session
        self.echecs = {}                 # adresse -> [instants]

    def connexion(self):
        return database.connecter(self.chemin_bd)

    def _expiree(self, s):
        return maintenant() - s.derniere_activite > timedelta(minutes=config.DELAI_INACTIVITE_PROF_MIN)

    def session(self, jeton):
        with self.verrou:
            s = self.sessions.get(jeton)
            if s is None:
                return None
            if self._expiree(s):
                del self.sessions[jeton]
                return None
            s.toucher()
            return s

    def ouvrir(self, s) -> str:
        with self.verrou:
            for j in [j for j, x in self.sessions.items() if self._expiree(x)]:
                del self.sessions[j]
            if len(self.sessions) >= SESSIONS_MAX:
                raise notes.ErreurNotes("Le serveur est occupé : réessayez dans quelques minutes.")
            jeton = secrets.token_urlsafe(32)
            self.sessions[jeton] = s
            return jeton

    def fermer(self, jeton):
        with self.verrou:
            self.sessions.pop(jeton, None)

    def trop_d_echecs(self, adresse) -> bool:
        with self.verrou:
            limite = maintenant() - FENETRE_ECHECS
            l = [t for t in self.echecs.get(adresse, []) if t > limite]
            self.echecs[adresse] = l
            return len(l) >= ECHECS_MAX_PAR_ADRESSE

    def noter_echec(self, adresse):
        with self.verrou:
            self.echecs.setdefault(adresse, []).append(maintenant())


def _fabrique(etat):
    class Gestionnaire(BaseHTTPRequestHandler):
        server_version = "GESTSCO"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):        # pas de journal sur la console
            pass

        # ------------------------------------------------------------ réponses
        def _entetes_securite(self):
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                        "script-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'")

        def _repondre(self, code, corps: bytes, type_="application/json; charset=utf-8", extra=()):
            self.send_response(code)
            self.send_header("Content-Type", type_)
            self.send_header("Content-Length", str(len(corps)))
            self._entetes_securite()
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(corps)

        def _json(self, code, objet):
            self._repondre(code, json.dumps(objet, ensure_ascii=False).encode("utf-8"))

        def _erreur(self, code, message):
            self._json(code, {"erreur": message})

        # ------------------------------------------------------------ lecture de la requête
        def _jeton(self):
            h = self.headers.get("Authorization", "")
            return h[7:].strip() if h.startswith("Bearer ") else ""

        def _corps(self) -> dict:
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > TAILLE_MAX:
                raise notes.ErreurNotes("Requête trop grande.")
            if not n:
                return {}
            try:
                d = json.loads(self.rfile.read(n).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise notes.ErreurNotes("Requête illisible.") from None
            if not isinstance(d, dict):
                raise notes.ErreurNotes("Requête illisible.")
            return d

        # ------------------------------------------------------------ routes
        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                from page_professeur import PAGE
                return self._repondre(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            if u.path.startswith("/api/"):
                return self._api("GET", u.path[5:], {k: v[0] for k, v in parse_qs(u.query).items()})
            self._erreur(404, "Page introuvable.")

        def do_POST(self):
            u = urlparse(self.path)
            if not u.path.startswith("/api/"):
                return self._erreur(404, "Page introuvable.")
            try:
                donnees = self._corps()
            except notes.ErreurNotes as e:
                return self._erreur(400, str(e))
            self._api("POST", u.path[5:], donnees)

        def _api(self, methode, chemin, d):
            adresse = self.client_address[0]
            if chemin == "connexion" and methode == "POST":
                return self._connexion(adresse, d)
            jeton = self._jeton()
            s = etat.session(jeton)
            if s is None:
                return self._erreur(401, "Session expirée : reconnectez-vous.")
            conn = etat.connexion()
            try:
                resultat = self._traiter(conn, s, jeton, methode, chemin, d)
                if isinstance(resultat, tuple):                      # document PDF : (octets, nom du fichier)
                    self._repondre(200, resultat[0], "application/pdf",
                                   extra=[("Content-Disposition", f'inline; filename="{resultat[1]}"')])
                else:
                    self._json(200, resultat)
            except PermissionError as e:
                self._erreur(403, str(e))
            except (notes.ErreurNotes, ValueError) as e:
                self._erreur(400, str(e))
            except Exception as e:                                   # erreur inattendue : message neutre, détail sur la console
                print("Erreur serveur :", repr(e), file=sys.stderr)
                self._erreur(500, "Erreur du serveur.")
            finally:
                conn.close()

        def _connexion(self, adresse, d):
            if etat.trop_d_echecs(adresse):
                return self._erreur(429, "Trop d'essais depuis cet appareil. Patientez quelques minutes.")
            conn = etat.connexion()
            try:
                r = security.authentifier(conn, str(d.get("login", "")), str(d.get("mdp", "")), role=notes.ROLE_PROFESSEUR)
                if not r.ok:
                    etat.noter_echec(adresse)
                    msg = r.message
                    if r.secondes_blocage:
                        msg += f" Réessayez dans {security.formater_duree(r.secondes_blocage)}."
                    return self._erreur(401, msg)
                try:
                    notes.mes_classes(conn, r.session)               # le compte doit être relié à un agent en service
                except PermissionError as e:
                    return self._erreur(403, str(e))
                jeton = etat.ouvrir(r.session)
                self._json(200, {"jeton": jeton, "nom": r.session.nom_complet, "doit_changer_mdp": r.session.doit_changer_mdp})
            except notes.ErreurNotes as e:
                self._erreur(503, str(e))
            finally:
                conn.close()

        def _traiter(self, conn, s, jeton, methode, chemin, d):
            if chemin == "deconnexion":
                security.fermer_session(conn, s)
                etat.fermer(jeton)
                return {"ok": True}
            return api_professeur.traiter(conn, s, methode, chemin, d)

    return Gestionnaire


class Serveur:
    """Serveur en arrière-plan. `chemin_bd` : base de données (par défaut, celle du logiciel). port 0 = port libre (essais)."""

    def __init__(self, port=None, hote="0.0.0.0", chemin_bd=None):
        self.etat = _Etat(chemin_bd)
        self.httpd = ThreadingHTTPServer((hote, config.PORT_PROFESSEURS if port is None else port), _fabrique(self.etat))
        self.httpd.daemon_threads = True
        self.fil = None

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def demarrer(self):
        self.fil = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="serveur-notes")
        self.fil.start()
        return self

    def arreter(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def adresses_locales() -> list:
    """Adresses de cet ordinateur sur le réseau (à taper sur le téléphone ou la tablette). Rien n'est envoyé sur Internet."""
    trouvees = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        trouvees.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in trouvees and not ip.startswith("127."):
                trouvees.append(ip)
    except OSError:
        pass
    return trouvees


def main():
    serveur = Serveur()
    print("Saisie des points - serveur démarré. Sur le Wi-Fi de l'école, ouvrez dans le navigateur :")
    for ip in adresses_locales() or ["(adresse de cet ordinateur)"]:
        print(f"    http://{ip}:{serveur.port}")
    print("Laissez cette fenêtre ouverte. Ctrl+C pour arrêter.")
    try:
        serveur.fil = None
        serveur.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        serveur.httpd.server_close()


if __name__ == "__main__":
    main()

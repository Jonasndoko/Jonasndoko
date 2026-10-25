"""Gestionnaire de versions GESTSCO (Git + GitHub).

Utilisation, depuis le dossier du programme :

    python outils/version.py etat                  # version, état du dépôt, dernière étiquette
    python outils/version.py liste                 # versions publiées (étiquettes vX.Y)
    python outils/version.py monter minor          # 1.0 -> 1.1   (major : 1.0 -> 2.0 ; patch : 1.0 -> 1.0.1)
    python outils/version.py monter 1.5            # version choisie
    python outils/version.py publier               # envoie le code et les étiquettes sur GitHub
    python outils/version.py paquet [fichier]      # fabrique le fichier .csfupd (clé demandée, ou GESTSCO_CLE_MAJ)

« monter » : contrôle que l'arbre est propre, change VERSION dans config.py, ajoute l'entrée au CHANGELOG.md à partir des
messages de commit depuis la dernière version, fait le commit « Version X » et l'étiquette vX. Rien n'est envoyé : « publier » le fait.
Sur GitHub, l'étiquette déclenche .github/workflows/publication.yml (tests + fichier de mise à jour joint à la « Release »).
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent.parent
CONFIG = DOSSIER / "config.py"
CHANGELOG = DOSSIER / "CHANGELOG.md"
MOTIF = re.compile(r'^(VERSION\s*=\s*")([^"]+)(")', re.M)


class Erreur(Exception):
    pass


def git(*args, check=True) -> str:
    r = subprocess.run(["git", *args], cwd=DOSSIER, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise Erreur(f"git {' '.join(args)} : {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def version_actuelle() -> str:
    m = MOTIF.search(CONFIG.read_text(encoding="utf-8"))
    if not m:
        raise Erreur("VERSION introuvable dans config.py.")
    return m.group(2)


def _tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        raise Erreur(f"Numéro de version invalide : « {v} » (attendu : 0.59, 1.0, 0.58.1…).") from None


def suivante(actuelle: str, genre: str) -> str:
    """Calcule la version suivante. `genre` : major, minor, patch ou un numéro explicite."""
    t = list(_tuple(actuelle))
    if genre == "major":
        return f"{t[0] + 1}.0"
    if genre == "minor":
        return f"{t[0]}.{(t[1] if len(t) > 1 else 0) + 1}"
    if genre == "patch":
        base = (t + [0, 0])[:2]
        extra = t[2] if len(t) > 2 else 0
        return f"{base[0]}.{base[1]}.{extra + 1}"
    nouvelle = ".".join(str(x) for x in _tuple(genre))
    if _tuple(nouvelle) <= _tuple(actuelle):
        raise Erreur(f"La nouvelle version ({nouvelle}) doit être plus récente que {actuelle}.")
    return nouvelle


def derniere_etiquette():
    t = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", check=False)
    return t or None


def etiquettes() -> list:
    liste = git("tag", "--list", "v[0-9]*").split()
    return sorted(liste, key=lambda e: _tuple(e[1:]) if re.fullmatch(r"v\d+(\.\d+)*", e) else (0,))


def arbre_propre() -> bool:
    return git("status", "--porcelain") == ""


def commits_depuis(etiquette) -> list:
    plage = f"{etiquette}..HEAD" if etiquette else "HEAD"
    sortie = git("log", plage, "--no-merges", "--pretty=format:%s", check=False)
    return [l for l in sortie.splitlines() if l and not re.match(r"^Version \d", l)]


def entree_changelog(version: str, messages: list) -> str:
    corps = "\n".join(f"- {m}" for m in messages) or "- (aucun changement décrit)"
    return f"## {version} - {date.today().isoformat()}\n\n{corps}\n\n"


def ecrire_changelog(version: str, messages: list):
    entete = "# Historique des versions\n\n"
    ancien = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else entete
    if not ancien.startswith("# "):
        ancien = entete + ancien
    premiere, reste = ancien.split("\n", 1)
    CHANGELOG.write_text(premiere + "\n\n" + entree_changelog(version, messages) + reste.lstrip("\n"), encoding="utf-8")


# ----------------------------------------------------------------- commandes
def cmd_etat(_):
    print(f"Version du programme (config.py) : {version_actuelle()}")
    et = derniere_etiquette()
    print(f"Dernière version publiée         : {et or 'aucune'}")
    if et:
        print(f"Commits depuis cette version     : {len(commits_depuis(et))}")
    print(f"Branche                          : {git('rev-parse', '--abbrev-ref', 'HEAD', check=False) or '-'}")
    modifs = git("status", "--porcelain")
    print("Fichiers modifiés non enregistrés : " + (f"{len(modifs.splitlines())}" if modifs else "aucun"))
    bases = git("ls-files", "*.db", "*.csfbak", check=False)
    if bases:
        print(f"ATTENTION : des données sont suivies par Git :\n{bases}\n  -> git rm --cached <fichier>")
    print("Dépôt distant (GitHub)           : " + (git("remote", "get-url", "origin", check=False) or "non configuré"))


def cmd_liste(_):
    for e in reversed(etiquettes()):
        print(f"{e:10} {git('log', '-1', '--format=%ad  %s', '--date=short', e)}")
    if not etiquettes():
        print("Aucune version publiée.")


def cmd_monter(a):
    if not arbre_propre():
        raise Erreur("Des modifications ne sont pas enregistrées : faites d'abord « git add » et « git commit ».")
    actuelle = version_actuelle()
    nouvelle = suivante(actuelle, a.genre)
    etiquette = f"v{nouvelle}"
    if etiquette in etiquettes():
        raise Erreur(f"L'étiquette {etiquette} existe déjà.")
    messages = commits_depuis(derniere_etiquette())
    print(f"{actuelle} -> {nouvelle}\nChangements :\n" + ("\n".join(f"  - {m}" for m in messages) or "  (aucun)"))
    if a.simuler:
        return
    if not a.oui and input("Continuer ? [o/N] ").strip().lower() not in ("o", "oui", "y"):
        raise Erreur("Abandonné.")
    CONFIG.write_text(MOTIF.sub(lambda m: f'{m.group(1)}{nouvelle}{m.group(3)}', CONFIG.read_text(encoding="utf-8"), count=1),
                      encoding="utf-8")
    ecrire_changelog(nouvelle, messages)
    git("add", "config.py", "CHANGELOG.md")
    git("commit", "-m", f"Version {nouvelle}")
    git("tag", "-a", etiquette, "-m", f"Version {nouvelle}")
    print(f"Version {nouvelle} enregistrée (étiquette {etiquette}). Pour l'envoyer sur GitHub : python outils/version.py publier")


def cmd_publier(_):
    if git("remote", check=False) == "":
        raise Erreur("Aucun dépôt GitHub configuré : git remote add origin https://github.com/VOTRE-COMPTE/gestsco.git")
    git("push", "origin", "HEAD")
    git("push", "origin", "--tags")
    print("Code et étiquettes envoyés. Suivez la publication dans l'onglet Actions de GitHub.")


def cmd_paquet(a):
    sys.path.insert(0, str(DOSSIER))
    cle = os.environ.get("GESTSCO_CLE_MAJ")
    if not cle:
        import getpass
        cle = getpass.getpass("Clé de mise à jour : ")
        if cle != getpass.getpass("Retapez la clé : "):
            raise Erreur("Les deux clés sont différentes.")
    import miseajour
    sortie = a.fichier or f"gestsco_{version_actuelle()}.csfupd"
    m = miseajour.creer_paquet(sortie, cle, dossier=DOSSIER)
    print(f"Fichier créé : {sortie} | version {m['version']} | {len(m['fichiers'])} fichiers\n"
          f"Empreinte à communiquer avec la clé : {m['empreinte']}")


def main(argv=None):
    p = argparse.ArgumentParser(description="Gestionnaire de versions GESTSCO")
    s = p.add_subparsers(dest="cmd", required=True)
    s.add_parser("etat").set_defaults(f=cmd_etat)
    s.add_parser("liste").set_defaults(f=cmd_liste)
    m = s.add_parser("monter")
    m.add_argument("genre", help="major, minor, patch ou un numéro (0.60)")
    m.add_argument("--oui", action="store_true", help="ne pas demander de confirmation")
    m.add_argument("--simuler", action="store_true", help="afficher sans rien modifier")
    m.set_defaults(f=cmd_monter)
    s.add_parser("publier").set_defaults(f=cmd_publier)
    k = s.add_parser("paquet")
    k.add_argument("fichier", nargs="?")
    k.set_defaults(f=cmd_paquet)
    a = p.parse_args(argv)
    try:
        a.f(a)
    except Erreur as e:
        sys.exit(f"Erreur : {e}")


if __name__ == "__main__":
    main()

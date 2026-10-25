"""Logique du champ « date » (sans interface, donc testable seule) : lecture d'un texte, mise en forme de la frappe,
grille d'un mois. L'interface (calendrier.py) s'appuie dessus."""
import calendar
from datetime import date, datetime

MOIS = ("Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre",
        "Novembre", "Décembre")
JOURS = ("Lu", "Ma", "Me", "Je", "Ve", "Sa", "Di")
ANNEE_MIN, ANNEE_MAX = 1900, 2100
_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d")


# ================================================================== logique (sans interface)
def lire_date_texte(texte):
    """Texte saisi -> date, ou None si le texte n'est pas une date valide (entre 1900 et 2100)."""
    texte = (texte or "").strip()
    for modele in _FORMATS:
        try:
            d = datetime.strptime(texte, modele).date()
        except ValueError:
            continue
        return d if ANNEE_MIN <= d.year <= ANNEE_MAX else None
    return None


def formater_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def completer_frappe(texte: str) -> str:
    """Après une frappe : ajoute le « / » quand le jour (2 chiffres) ou le mois (2 chiffres) vient d'être complété.
    « 08 » -> « 08/ » ; « 08/10 » -> « 08/10/ ». Un texte déjà séparé à la main n'est pas modifié."""
    if len(texte) == 2 and texte.isdigit():
        return texte + "/"
    if len(texte) == 5 and texte[:2].isdigit() and texte[2] == "/" and texte[3:].isdigit():
        return texte + "/"
    return texte


def frappe_permise(texte: str) -> bool:
    """Seuls les chiffres et les séparateurs sont permis, 10 caractères au plus."""
    return len(texte) <= 10 and all(c.isdigit() or c in "/-." for c in texte)


def semaines(annee: int, mois: int) -> list:
    """Grille du mois : liste de semaines (lundi -> dimanche) ; 0 = case vide."""
    return calendar.Calendar(firstweekday=0).monthdayscalendar(annee, mois)


def decaler_mois(annee: int, mois: int, delta: int) -> tuple:
    n = annee * 12 + (mois - 1) + delta
    return n // 12, n % 12 + 1

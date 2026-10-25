"""Montants : stockés en centimes (entiers) pour éviter toute erreur d'arrondi."""
import re
from decimal import Decimal, ROUND_HALF_UP

_RE_MONTANT = re.compile(r"^\d{1,12}([.,]\d{1,2})?$")


def vers_centimes(texte: str) -> int:
    """'1 250,50' -> 125050. Lève ValueError (message affichable) si le montant est invalide."""
    propre = (texte or "").replace("\u00a0", "").replace(" ", "")
    if not _RE_MONTANT.match(propre):
        raise ValueError("Montant invalide. Exemples : 25   ou   25,50")
    return int((Decimal(propre.replace(",", ".")) * 100).to_integral_value(ROUND_HALF_UP))


def formater(centimes: int) -> str:
    """125050 -> '1 250,50'"""
    entier, cent = divmod(abs(int(centimes)), 100)
    texte = f"{entier:,}".replace(",", " ")
    return f"{'-' if centimes < 0 else ''}{texte},{cent:02d}"


def resume_totaux(paires) -> str:
    """[('USD', 12500), ('CDF', 800)] -> '125,00 USD ; 8,00 CDF' ('aucun' s'il n'y a rien). Sert aux traces du journal."""
    return " ; ".join(f"{formater(c)} {d}" for d, c in sorted(paires)) or "aucun"

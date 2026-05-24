"""Runic profile — personal rune of life (constant) and rune of the year."""

from datetime import date, datetime


def _sum_digits(n: int) -> int:
    return sum(int(d) for d in str(n))


def _reduce_to_24(n: int) -> int:
    while n > 24:
        n = _sum_digits(n)
    return max(1, n)


def life_rune_index(birth_date: date) -> int:
    """Numerological life rune: reduce all birth date digits to 1-24."""
    total = sum(int(d) for d in birth_date.strftime("%d%m%Y"))
    return _reduce_to_24(total)


def year_rune_index(birth_date: date, year: int | None = None) -> int:
    """Year rune: day + month + sum-of-year-digits, reduced to 1-24."""
    if year is None:
        year = date.today().year
    total = birth_date.day + birth_date.month + _sum_digits(year)
    return _reduce_to_24(total)


def parse_birth_date(text: str) -> date | None:
    """Accept DD.MM.YYYY, DD/MM/YYYY or DD-MM-YYYY."""
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            parsed = datetime.strptime(text.strip(), fmt).date()
            if parsed.year < 1900 or parsed > date.today():
                return None
            return parsed
        except ValueError:
            continue
    return None

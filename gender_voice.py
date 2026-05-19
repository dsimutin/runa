"""Detect user gender from a Russian first name and adjust narrator voice.

The bot's reader-friend narrator uses first-person past-tense verbs that
are grammatically gendered in Russian ('я бы шла' vs 'я бы шёл'). To make
the address feel personal, we infer the user's gender from their first
name and substitute the matching form.

Usage:
    gender = detect_gender(name)        # 'm' or 'f'
    text = gender_fmt(text, gender)     # '{шёл|шла}' → 'шёл' or 'шла'
"""

import re

MALE_NAME_EXCEPTIONS = {
    # Russian male first names that end in -а / -я
    "никита", "илья", "кузьма", "фома", "лука", "савва", "гавриил", "гаврила",
    # Ukrainian / Belarusian variants
    "микита", "микола",
}

FEMALE_NAME_EXCEPTIONS = {
    # Russian female names ending in a consonant
    "любовь", "юдифь", "эсфирь", "рахиль", "руфь",
}

# {m_form|f_form} placeholder pattern, e.g. "{шёл|шла}"
_GENDER_RE = re.compile(r"\{([^|{}]+)\|([^|{}]+)\}")


def detect_gender(name: str) -> str:
    """Return 'm' or 'f' from a first name. Defaults to 'f' for empty/unknown.

    Heuristic: names ending in -а / -я are usually female except for a small
    list of male exceptions. Names ending in a consonant or -й are usually male.
    Ambiguous nicknames (Саша, Женя, Валя) fall through to the -а/-я → female
    branch, which matches the bot's default narrator voice — no regression.
    """
    if not name:
        return "f"
    first = name.strip().split()[0].lower().replace("ё", "е")
    if not first:
        return "f"
    if first in MALE_NAME_EXCEPTIONS:
        return "m"
    if first in FEMALE_NAME_EXCEPTIONS:
        return "f"
    if first.endswith(("а", "я")):
        return "f"
    return "m"


def gender_fmt(text: str, gender: str) -> str:
    """Replace {мужская|женская} placeholders with the matching form."""
    if gender == "m":
        return _GENDER_RE.sub(lambda m: m.group(1), text)
    return _GENDER_RE.sub(lambda m: m.group(2), text)

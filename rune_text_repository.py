import random
import re
from typing import Any, Dict, List

from rune_text_data import (
    rasklad_texts,
    rune_day_texts,
    sphere_answer_texts,
)
from runes_data import NON_REVERSIBLE_RUNE_KEYS

PALETTES = {"light", "dark", "premium"}
ORIENTATIONS = {"up", "rev"}

# The blank/Wyrd rune has no entry in the compiled daily-card dataset
# (data/card_of_day_short.txt never included it — likely because it was
# written before the blank rune was added to RUNES). Without this, drawing
# Wyrd as the daily card produced an empty message body: get_daily_text
# raised KeyError, and the KeyError fallback (bot.rune_text -> legacy
# runes_interpretations, keyed 'blank' not 'wyrd') silently returned "".
# Wyrd is drawn ~1/25 times, so this was a real, if infrequent, live bug.
WYRD_DAILY_TEXT = {
    "light": (
        "Сегодня выпала пустая руна — знак того, что готового ответа пока нет, и это тоже ответ. "
        "Не торопись заполнять неизвестность первой попавшейся версией событий.\n\n"
        "Вопрос дня: Что откроется, если сегодня ты не будешь искать готовый ответ, а просто останешься с вопросом?"
    ),
    "dark": (
        "Пустая руна — сигнал не действовать вслепую. Там, где нет ясности, лучше выждать, чем занять позицию наугад.\n\n"
        "Вопрос дня: Где сегодня ты рискуешь принять решение только потому, что неизвестность неудобна?"
    ),
    "premium": (
        "Пустая руна указывает на то, что ещё не приняло форму — не пустота, а пространство до появления знака. "
        "Здесь нечего трактовать, только наблюдать.\n\n"
        "Вопрос дня: Что в твоей жизни сейчас находится в этой же точке — до формы, до имени?"
    ),
}

# Verdict-opener rotation for yes/no sphere answers.
# IMPORTANT: every phrase here must carry the SAME unambiguous polarity as
# the literal "Да."/"Нет." it replaces. This is variety of wording only —
# never hedging, never turned into "maybe". The rest of the stored text
# (reasoning) is untouched.
YES_OPENERS = [
    "Да.",
    "Да, точно.",
    "Да — можно.",
    "Да, соглашайся.",
    "Именно да.",
    "Да, это тот случай.",
    "Да, всё складывается.",
    "Да, действуй.",
]
NO_OPENERS = [
    "Нет.",
    "Нет, не сейчас.",
    "Нет — не в этом виде.",
    "Нет, не стоит.",
    "Именно нет.",
    "Нет, придержи.",
    "Нет, это не тот случай.",
    "Нет, останови здесь.",
]


def _vary_verdict_opener(text: str, is_yes: bool) -> str:
    """Swap a literal 'Да.'/'Нет.' opener for a random same-polarity variant.

    Texts that already open with an alternate phrasing (e.g. 'Сейчас —',
    'Время пришло') are left untouched — they're already varied and already
    unambiguous for their field (answer_yes vs answer_no).
    """
    prefix = "Да." if is_yes else "Нет."
    if not text.startswith(prefix):
        return text
    pool = YES_OPENERS if is_yes else NO_OPENERS
    rest = text[len(prefix):]
    return random.choice(pool) + rest

# Maps alternative rune names used inside texts → canonical name from runes_data.py
# Used to normalize text output so the name in the text matches the displayed card name.
RUNE_TEXT_NAME_FIXES: Dict[str, str] = {
    "Совило": "Соулу",
    "Совелу": "Соулу",
    "Беркана": "Беркано",
    "Ингуз": "Ингваз",
    "Тейваз": "Тивац",
}


def _normalize_rune_names_in_text(text: str) -> str:
    """Replace alternative rune names in body text with canonical names."""
    for alt, canonical in RUNE_TEXT_NAME_FIXES.items():
        text = text.replace(alt, canonical)
    return text


RUNE_KEY_ALIASES = {
    "teiwaz": "tiwaz",
    "tiwaz": "tiwaz",
    "berkana": "berkano",
    "berkano": "berkano",
    "inguz": "ingwaz",
    "ingwaz": "ingwaz",
    "blank": "wyrd",
    "wyrd": "wyrd",
}

POSITION_LABELS = {
    "past": "Прошлое",
    "present": "Настоящее",
    "future": "Будущее",
}

SPHERE_LABELS = {
    "relationships": "Отношения",
    "work": "Работа",
    "money": "Деньги",
    "health": "Здоровье",
    "decision": "Принятие решений",
    "timing": "Когда",
}

QUESTION_SPHERE_KEYWORDS = {
    "relationships": [
        "отнош", "люб", "партнер", "партнёр", "муж", "жена", "девуш", "парень",
        "бывш", "верн", "расст", "семь", "семья", "брак", "ревн", "чувств",
        "свидан", "связь", "общен",
    ],
    "work": [
        "работ", "карьер", "должност", "уволь", "началь", "коллег", "проект",
        "бизнес", "клиент", "собесед", "офис", "заказ", "дело", "команд",
        "сотруд", "ваканс",
    ],
    "money": [
        "деньг", "финанс", "доход", "зарплат", "плат", "куп", "прод", "долг",
        "инвест", "цена", "стоим", "расход", "заработ", "кредит", "прибыл",
    ],
    "health": [
        "здоров", "самочув", "энерг", "сил", "выгор", "сон", "устал", "тело",
        "ресурс", "восстанов", "болит", "болез", "леч", "врач",
    ],
    "timing": [
        "когда", "срок", "дата", "время", "скоро", "месяц", "недел", "день",
        "завтра", "сегодня", "успе", "ждать", "долго",
    ],
    "decision": [
        "стоит ли", "выб", "лучше", "или", "реш", "как поступ", "вариант",
        "соглас", "отказ", "принять", "уйти", "остаться", "делать", "начать",
    ],
}


def normalize_rune_key(rune_key: str) -> str:
    return RUNE_KEY_ALIASES.get((rune_key or "").strip().lower(), (rune_key or "").strip().lower())


def normalize_palette(palette: str) -> str:
    palette = (palette or "light").strip().lower()
    return palette if palette in PALETTES else "light"


def normalize_orientation(rune_key: str, orientation: str) -> str:
    key = normalize_rune_key(rune_key)
    if key in NON_REVERSIBLE_RUNE_KEYS:
        return "up"
    orientation = (orientation or "up").strip().lower()
    return orientation if orientation in ORIENTATIONS else "up"


def get_relationship_trio_texts(rune1_key: str, rune2_key: str, rune3_key: str, palette: str) -> Dict[str, str]:
    """Texts for 'Ты' / 'Партнёр' / 'Между вами' readings (pair & relationship spreads).

    IMPORTANT: this does NOT reuse the past/present/future spread texts.
    Those are written as position-of-a-situation narratives (they literally
    start with 'Прошлое:' / 'Настоящее:' / 'Будущее:') and made no sense
    when relabelled as a description of a person.

    'Ты' and 'Партнёр' use rune_person_texts — a dedicated set written
    specifically to describe a trait/role a person carries in a relationship
    (not a 'today' state like the daily card, not a situation stage like the
    3-card spread). 'Между вами' uses the spread's future-position text with
    its 'Будущее:' prefix stripped, since a trajectory framing genuinely fits
    'where this connection is heading'.
    """
    from rune_person_texts import get_person_text

    you_text = _normalize_rune_names_in_text(get_person_text(rune1_key, palette))
    partner_text = _normalize_rune_names_in_text(get_person_text(rune2_key, palette))
    between_raw = get_rasklad_text(rune3_key, palette, "up", "future")["text"]
    between_text = re.sub(r"^Будущее:\s*", "", between_raw)
    return {
        "you": you_text,
        "partner": partner_text,
        "between": _normalize_rune_names_in_text(between_text),
    }


def daily_texts() -> Dict[str, Any]:
    return rune_day_texts()


def random_orientation(rune_key: str) -> str:
    key = normalize_rune_key(rune_key)
    if key in NON_REVERSIBLE_RUNE_KEYS:
        return "up"
    return random.choice(["up", "rev"])


def is_reversible(rune_key: str) -> bool:
    return normalize_rune_key(rune_key) not in NON_REVERSIBLE_RUNE_KEYS


def orientation_label(orientation: str, rune_key: str = "") -> str:
    if rune_key and not is_reversible(rune_key):
        return "необратимая"
    return "прямое" if orientation == "up" else "перевёрнутое"


def orientation_symbol(rune_key: str, orientation: str) -> str:
    if not is_reversible(rune_key):
        return "◆"
    return "↑" if orientation == "up" else "↓"


def yes_no_draw(rune_key: str) -> tuple[str, str]:
    """Return visual orientation and answer polarity for a yes/no draw.

    For reversible glyphs the established behaviour remains intact: upright
    means yes and reversed means no.  A non-reversible glyph has no honest
    visual reversal, so its polarity is drawn independently while the card
    remains upright.  This prevents symmetric runes from becoming automatic
    "yes" answers.
    """
    if normalize_rune_key(rune_key) == "wyrd":
        return "up", "unknown"
    orientation = random_orientation(rune_key)
    if is_reversible(rune_key):
        return orientation, "yes" if orientation == "up" else "no"
    return orientation, random.choice(["yes", "no"])


def draw_rune_with_orientation(runes: List[Dict[str, Any]]) -> tuple[Dict[str, Any], str]:
    rune = random.choice(runes)
    return rune, random_orientation(rune.get("key", ""))


def draw_distinct_runes_with_orientations(runes: List[Dict[str, Any]], count: int = 3) -> List[tuple[Dict[str, Any], str]]:
    picked = random.sample(runes, min(count, len(runes)))
    return [(rune, random_orientation(rune.get("key", ""))) for rune in picked]


def draw_yes_no_rune(runes: List[Dict[str, Any]]) -> Dict[str, Any]:
    available = set(sphere_answer_texts().keys()) | {"wyrd"}
    eligible = [rune for rune in runes if normalize_rune_key(rune.get("key", "")) in available]
    if not eligible:
        eligible = runes
    return random.choice(eligible)


def get_daily_text(rune_key: str, palette: str, orientation: str) -> str:
    key = normalize_rune_key(rune_key)
    palette = normalize_palette(palette)
    orientation = normalize_orientation(key, orientation)
    if key == "wyrd":
        return WYRD_DAILY_TEXT.get(palette, WYRD_DAILY_TEXT["light"])
    data = daily_texts()
    rune_data = data.get(key)
    if not rune_data:
        raise KeyError(f"Daily text not found for rune: {rune_key}")
    field = f"{palette}_{orientation}"
    text = rune_data.get(field)
    if text:
        return _normalize_rune_names_in_text(text)
    raise KeyError(f"Daily text not found for rune={rune_key}, palette={palette}, orientation={orientation}")


def get_rasklad_text(rune_key: str, palette: str, orientation: str, position: str) -> Dict[str, str]:
    key = normalize_rune_key(rune_key)
    palette = normalize_palette(palette)
    orientation = normalize_orientation(key, orientation)
    position = (position or "").strip().lower()
    if position not in POSITION_LABELS:
        raise KeyError(f"Unknown spread position: {position}")

    data_key = key if key == "wyrd" else f"{key}_{orientation}"
    rune_data = rasklad_texts().get(data_key)
    if not rune_data:
        raise KeyError(f"Spread text not found for rune: {data_key}")

    palette_data = rune_data.get(palette)
    if not palette_data:
        raise KeyError(f"Spread palette not found for rune={data_key}, palette={palette}")

    text = palette_data.get(position)
    if not text:
        raise KeyError(f"Spread position not found for rune={data_key}, palette={palette}, position={position}")

    return {
        "name": _normalize_rune_names_in_text(rune_data.get("name", "")),
        "text": _normalize_rune_names_in_text(text),
        "extra": _normalize_rune_names_in_text(palette_data.get("extra", "")),
    }


def detect_question_sphere(question: str) -> str:
    """Detect the subject area without matching fragments inside other words.

    Domain spheres are deliberately preferred over the generic ``decision``
    intent.  Thus «стоит ли менять работу» is about work, while «стоит ли
    соглашаться» falls back to decision.  Timing is treated as an explicit
    intent and wins when the question contains «когда», «срок» and the like.
    """
    question_l = " ".join((question or "").lower().replace("ё", "е").split())
    if not question_l:
        return "decision"

    def matches(keyword: str) -> bool:
        keyword = keyword.replace("ё", "е")
        # Entries are intentional stems (работ-, отнош-), so allow the final
        # word to continue, but require a real word boundary at its start.
        parts = [re.escape(part) for part in keyword.split()]
        pattern = r"(?<!\w)" + r"\s+".join(parts) + r"\w*"
        return re.search(pattern, question_l, flags=re.UNICODE) is not None

    scores = {
        sphere: sum(1 for keyword in keywords if matches(keyword))
        for sphere, keywords in QUESTION_SPHERE_KEYWORDS.items()
    }
    if scores["timing"]:
        return "timing"
    domain_spheres = ("relationships", "work", "money", "health")
    best_domain = max(domain_spheres, key=lambda sphere: scores[sphere])
    if scores[best_domain]:
        return best_domain
    return "decision"


def get_sphere_answer(rune_key: str, palette: str, sphere: str, answer_kind: str) -> Dict[str, str]:
    key = normalize_rune_key(rune_key)
    palette = normalize_palette(palette)
    sphere = (sphere or "decision").strip().lower()
    if key == "wyrd":
        return {
            "short_desc": (
                "Пустая руна показывает неизвестную переменную: ситуация ещё не сложилась "
                "настолько, чтобы ответ был честно определён."
            ),
            "answer": (
                "Сейчас нет ясного «да» или «нет». Не заполняй паузу догадками: "
                "дождись новых фактов и задай вопрос снова позже."
            ),
            "sphere": sphere,
            "sphere_label": SPHERE_LABELS.get(sphere, "Принятие решений"),
            "answer_label": "Нет ясного ответа",
        }
    answer_kind = "answer_yes" if answer_kind == "yes" else "answer_no"

    data = sphere_answer_texts()
    rune_data = data.get(key)
    if not rune_data:
        raise KeyError(f"Yes/no sphere text not found for rune: {rune_key}")

    sphere_data = rune_data.get(sphere) or rune_data.get("decision")
    if not sphere_data:
        raise KeyError(f"Sphere text not found for rune={rune_key}, sphere={sphere}")

    palette_data = sphere_data.get(palette) or sphere_data.get("light")
    if not palette_data:
        raise KeyError(f"Palette text not found for rune={rune_key}, sphere={sphere}, palette={palette}")

    is_yes = answer_kind == "answer_yes"
    answer_text = _normalize_rune_names_in_text(palette_data.get(answer_kind, ""))
    answer_text = _vary_verdict_opener(answer_text, is_yes)

    return {
        "short_desc": _normalize_rune_names_in_text(palette_data.get("short_desc", "")),
        "answer": answer_text,
        "sphere": sphere,
        "sphere_label": SPHERE_LABELS.get(sphere, "Принятие решений"),
        "answer_label": "Да" if is_yes else "Нет",
    }

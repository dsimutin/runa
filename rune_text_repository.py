import random
from typing import Any, Dict, List

from rune_text_data import (
    rasklad_texts,
    rune_day_texts,
    sphere_answer_texts,
)

PALETTES = {"light", "dark", "premium"}
ORIENTATIONS = {"up", "rev"}

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
    if key == "wyrd":
        return "up"
    orientation = (orientation or "up").strip().lower()
    return orientation if orientation in ORIENTATIONS else "up"


def daily_texts() -> Dict[str, Any]:
    return rune_day_texts()


def random_orientation(rune_key: str) -> str:
    key = normalize_rune_key(rune_key)
    if key == "wyrd":
        return "up"
    return random.choice(["up", "rev"])


def orientation_label(orientation: str) -> str:
    return "прямое" if orientation == "up" else "перевёрнутое"


def draw_rune_with_orientation(runes: List[Dict[str, Any]]) -> tuple[Dict[str, Any], str]:
    rune = random.choice(runes)
    return rune, random_orientation(rune.get("key", ""))


def draw_distinct_runes_with_orientations(runes: List[Dict[str, Any]], count: int = 3) -> List[tuple[Dict[str, Any], str]]:
    picked = random.sample(runes, min(count, len(runes)))
    return [(rune, random_orientation(rune.get("key", ""))) for rune in picked]


def draw_yes_no_rune(runes: List[Dict[str, Any]]) -> Dict[str, Any]:
    available = set(sphere_answer_texts().keys())
    eligible = [rune for rune in runes if normalize_rune_key(rune.get("key", "")) in available]
    if not eligible:
        eligible = runes
    return random.choice(eligible)


def get_daily_text(rune_key: str, palette: str, orientation: str) -> str:
    key = normalize_rune_key(rune_key)
    palette = normalize_palette(palette)
    orientation = normalize_orientation(key, orientation)
    data = daily_texts()
    rune_data = data.get(key)
    if not rune_data:
        raise KeyError(f"Daily text not found for rune: {rune_key}")
    field = f"{palette}_{orientation}"
    text = rune_data.get(field)
    if text:
        return text
    if key == "wyrd":
        return rune_data[f"{palette}_up"]
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
        "name": rune_data.get("name", ""),
        "text": text,
        "extra": palette_data.get("extra", ""),
    }


def detect_question_sphere(question: str) -> str:
    question_l = (question or "").lower()
    scores: Dict[str, int] = {}
    for sphere, keywords in QUESTION_SPHERE_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in question_l)
        if score:
            scores[sphere] = score
    if not scores:
        return "decision"
    return max(scores, key=scores.get)


def get_sphere_answer(rune_key: str, palette: str, sphere: str, answer_kind: str) -> Dict[str, str]:
    key = normalize_rune_key(rune_key)
    palette = normalize_palette(palette)
    sphere = (sphere or "decision").strip().lower()
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

    return {
        "short_desc": palette_data.get("short_desc", ""),
        "answer": palette_data.get(answer_kind, ""),
        "sphere": sphere,
        "sphere_label": SPHERE_LABELS.get(sphere, "Принятие решений"),
        "answer_label": "Да" if answer_kind == "answer_yes" else "Нет",
    }

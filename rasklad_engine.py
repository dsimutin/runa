from typing import Any, Dict, List
import random

from rune_text_repository import (
    POSITION_LABELS,
    get_rasklad_text,
    orientation_symbol,
)


SPREAD_POSITIONS = ["past", "present", "future"]

RASKLAD_INTROS = {
    "light": [
        "🔮 <b>Расклад</b>",
        "🔮 <b>Три карты на твою ситуацию</b>",
        "🔮 <b>Смотрим на путь</b>",
        "🔮 <b>Что привело сюда и куда ведёт</b>",
    ],
    "dark": [
        "🔮 <b>Расклад</b>",
        "🔮 <b>Три факта по делу</b>",
        "🔮 <b>Раскладываю по позициям</b>",
        "🔮 <b>Три точки давления</b>",
    ],
    "premium": [
        "🔮 <b>Расклад</b>",
        "🔮 <b>Три слоя одной темы</b>",
        "🔮 <b>Смотрим глубже: три позиции</b>",
        "🔮 <b>Один узел, три ракурса</b>",
    ],
}

RASKLAD_SYNTHESIS_CLOSINGS = {
    "light": [
        "Три карты — это не три отдельные истории, а одна: посмотри, что тянется из прошлого в настоящее и куда это ведёт, если ничего не менять.",
        "Не старайся разложить всё по полочкам сразу. Дай себе заметить, какая из трёх карт откликается сильнее всего — с неё и начни.",
        "Прошлое объясняет, настоящее держит, будущее пока не высечено в камне. Твой следующий шаг — это и есть влияние на третью карту.",
    ],
    "dark": [
        "Смотри на связку, а не на карты по отдельности: что в прошлом создало давление, которое ты чувствуешь сейчас — и что оно готовит дальше, если не вмешаться.",
        "Будущее здесь — не приговор, а прогноз при текущем курсе. Меняешь настоящее — меняется и оно.",
        "Прошлое дало условия, настоящее — точка выбора, будущее — цена этого выбора. Смотри именно в эту сторону.",
    ],
    "premium": [
        "Три позиции — это один паттерн в трёх фазах. Спроси себя: что в этой цепочке повторяется не первый раз?",
        "Прошлое и будущее здесь — зеркала настоящего. Ключ обычно лежит не в крайних картах, а в том, что происходит с тобой прямо сейчас.",
        "Не ищи готовый ответ в третьей карте. Она показывает направление при текущей траектории — направление меняешь ты, не расклад.",
    ],
}


def generate_rasklad(
    rune_draws: List[tuple[Dict[str, Any], str]],
    question: str,
    palette: str,
    name: str = "",
) -> str:
    pool_key = palette if palette in RASKLAD_INTROS else "light"
    intro = random.choice(RASKLAD_INTROS[pool_key])
    lines = [
        intro,
        f"<i>{question}</i>",
        "",
    ]

    for index, (position, draw) in enumerate(zip(SPREAD_POSITIONS, rune_draws), start=1):
        rune, orientation = draw
        data = get_rasklad_text(rune["key"], palette, orientation, position)
        position_label = POSITION_LABELS[position]
        arrow = orientation_symbol(rune["key"], orientation)
        lines.extend(
            [
                f"{index}️⃣ <b>{position_label} — {rune['name']} {arrow}</b>",
                data["text"],
            ]
        )
        if data.get("extra"):
            lines.append(data["extra"])
        lines.append("")

    lines.append(random.choice(RASKLAD_SYNTHESIS_CLOSINGS[pool_key]))

    return "\n".join(lines).strip()

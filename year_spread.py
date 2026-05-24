"""Year spread — 12 deterministic runes for all months of the year."""

import hashlib
from datetime import date

from rune_text_repository import get_daily_text
from runes_data import RUNES

MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def _rune_for_month(user_id: int, year: int, month: int) -> dict:
    seed = f"year_spread:{user_id}:{year}:{month}"
    idx = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(RUNES)
    return RUNES[idx]


def build_year_spread(user_id: int, year: int | None = None) -> list[dict]:
    if year is None:
        year = date.today().year
    return [
        {
            "month_num": m,
            "month_name": MONTHS_RU[m - 1],
            "rune": _rune_for_month(user_id, year, m),
        }
        for m in range(1, 13)
    ]


def format_year_spread(user_id: int, palette: str, name: str, year: int | None = None) -> str:
    if year is None:
        year = date.today().year
    current_month = date.today().month if date.today().year == year else 0

    entries = build_year_spread(user_id, year)
    parts = [f"🗓 <b>{name}, твой {year} год</b>"]

    for entry in entries:
        rune = entry["rune"]
        try:
            text = get_daily_text(rune["key"], palette, "up")
            sentence = text.split(".")[0].strip()
            if len(sentence) > 110:
                sentence = sentence[:110].rsplit(" ", 1)[0] + "..."
        except KeyError:
            sentence = "..."

        marker = "▸" if entry["month_num"] == current_month else "·"
        parts.append(f"{marker} <b>{entry['month_name']}</b> — {rune['name']}\n<i>{sentence}.</i>")

    parts.append(f"<i>Расклад остаётся стабильным весь {year} год.</i>")
    return "\n\n".join(parts)

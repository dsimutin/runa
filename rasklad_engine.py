from typing import Any, Dict, List

from rune_text_repository import (
    POSITION_LABELS,
    get_rasklad_text,
    orientation_label,
)


SPREAD_POSITIONS = ["past", "present", "future"]


def generate_rasklad(
    rune_draws: List[tuple[Dict[str, Any], str]],
    question: str,
    palette: str,
    name: str = "",
) -> str:
    intro = "🔮 <b>Расклад</b>"
    lines = [
        intro,
        f"<i>{question}</i>",
        "",
    ]

    for index, (position, draw) in enumerate(zip(SPREAD_POSITIONS, rune_draws), start=1):
        rune, orientation = draw
        data = get_rasklad_text(rune["key"], palette, orientation, position)
        position_label = POSITION_LABELS[position]
        arrow = "↑" if orientation == "up" else "↓"
        lines.extend(
            [
                f"{index}️⃣ <b>{position_label} — {rune['name']} {arrow}</b>",
                data["text"],
            ]
        )
        if data.get("extra"):
            lines.append(data["extra"])
        lines.append("")

    return "\n".join(lines).strip()

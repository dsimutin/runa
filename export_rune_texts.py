from pathlib import Path

from runes_data import RUNE_FILES
from runes_interpretations import RUNE_INTERPRETATIONS

FIELDS = [
    ("short_desc", "Короткое значение"),
    ("answer_yes", "Ответ ДА"),
    ("answer_no", "Ответ НЕТ"),
    ("situation", "Ситуация"),
    ("obstacle", "Что мешает"),
    ("advice", "Совет"),
]

PALETTES = [
    ("light", "🌕 Светлая версия"),
    ("dark", "🌑 Тёмная версия"),
]


def line(text: str = "") -> str:
    return text.rstrip() + "\n"


def export_markdown() -> str:
    out: list[str] = []
    out.append(line("# Тексты всех рун"))
    out.append(line())
    out.append(line("Формат выгрузки: руна → версия колоды → блоки трактовок."))
    out.append(line())

    for key, name, image_file in RUNE_FILES:
        data = RUNE_INTERPRETATIONS.get(key, {})
        out.append(line(f"## {name}"))
        out.append(line())
        out.append(line(f"**Ключ:** `{key}`  "))
        out.append(line(f"**Файл карты:** `{image_file}`"))
        out.append(line())

        for palette_key, palette_title in PALETTES:
            palette_data = data.get(palette_key, {})
            out.append(line(f"### {palette_title}"))
            out.append(line())

            for field_key, field_title in FIELDS:
                value = palette_data.get(field_key, "").strip()
                out.append(line(f"**{field_title}:**"))
                out.append(line())
                out.append(line(value if value else "—"))
                out.append(line())

        out.append(line("---"))
        out.append(line())

    return "".join(out)


if __name__ == "__main__":
    output = Path("rune_texts_export.md")
    output.write_text(export_markdown(), encoding="utf-8")
    print(f"Готово: {output}")

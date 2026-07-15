#!/usr/bin/env python3
"""
Перекомпилирует RUNE_DAY_TEXTS_JSON_GZ_B64 в rune_text_data.py
из актуального data/card_of_day_short.txt.

Запуск: python3 recompile_texts.py
"""
import base64
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent

KEY_MAP = {
    "FEHU": "fehu", "URUZ": "uruz", "THURISAZ": "thurisaz",
    "ANSUZ": "ansuz", "RAIDO": "raido", "KENAZ": "kenaz",
    "GEBO": "gebo", "WUNJO": "wunjo", "HAGALAZ": "hagalaz",
    "NAUTHIZ": "nauthiz", "ISA": "isa", "JERA": "jera",
    "EIHWAZ": "eihwaz", "PERTHRO": "perthro", "ALGIZ": "algiz",
    "SOWILO": "sowilo", "TIWAZ": "tiwaz", "BERKANO": "berkano",
    "EHWAZ": "ehwaz", "MANNAZ": "mannaz", "LAGUZ": "laguz",
    "INGWAZ": "ingwaz", "DAGAZ": "dagaz", "OTHALA": "othala",
    "WYRD": "wyrd",
}

PREFIX_MAP = {
    "🌕 П:": "light_up",
    "🌕 ПЕР:": "light_rev",
    "🌑 П:": "dark_up",
    "🌑 ПЕР:": "dark_rev",
    "💎 П:": "premium_up",
    "💎 ПЕР:": "premium_rev",
}


def parse(path: Path) -> dict:
    txt = path.read_text(encoding="utf-8")
    section_re = re.compile(r"={30,}\n([A-Z]+)\s*—.*?\n={30,}", re.MULTILINE)
    sections = section_re.split(txt)
    result = {}
    for i in range(1, len(sections), 2):
        raw_name = sections[i].strip()
        content = sections[i + 1] if i + 1 < len(sections) else ""
        key = KEY_MAP.get(raw_name)
        if not key:
            print(f"  ⚠ Неизвестная руна: {raw_name}")
            continue
        positions = []
        for prefix, field in PREFIX_MAP.items():
            pos = content.find(prefix)
            if pos != -1:
                positions.append((pos, prefix, field))
        positions.sort()
        rune_data = {}
        for idx, (pos, prefix, field) in enumerate(positions):
            start = pos + len(prefix)
            end = positions[idx + 1][0] if idx + 1 < len(positions) else len(content)
            block = content[start:end].strip()
            block = re.sub(r"\n+", " ", block)
            block = re.sub(r"\s+", " ", block).strip()
            block = block.replace("Вопрос дня:", "\n\nВопрос дня:")
            block = block.replace("Совет на день:", "\n\nСовет на день:")
            rune_data[field] = block
        if rune_data:
            result[key] = rune_data
        else:
            print(f"  ⚠ Нет текстов для: {key}")
    return result


def compile_blob(data: dict) -> str:
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    compressed = gzip.compress(raw, compresslevel=9)
    b64 = base64.b64encode(compressed).decode("ascii")
    return "\n".join(b64[i : i + 72] for i in range(0, len(b64), 72))


def update_rune_text_data(new_blob: str) -> None:
    target = ROOT / "rune_text_data.py"
    content = target.read_text(encoding="utf-8")
    start_marker = 'RUNE_DAY_TEXTS_JSON_GZ_B64 = """\\\n'
    start_idx = content.index(start_marker) + len(start_marker)
    end_idx = content.index('\n"""\n\nRASKLAD_TEXTS_JSON_GZ_B64')
    new_content = content[:start_idx] + new_blob + content[end_idx:]
    target.write_text(new_content, encoding="utf-8")


def main():
    src = ROOT / "data" / "card_of_day_short.txt"
    if not src.exists():
        print(f"Файл не найден: {src}")
        sys.exit(1)

    print(f"Читаю {src} ...")
    data = parse(src)
    print(f"Распознано рун: {len(data)}")

    missing_fields = []
    for key, fields in data.items():
        for expected in ("light_up", "light_rev", "dark_up", "dark_rev", "premium_up", "premium_rev"):
            if expected not in fields:
                missing_fields.append(f"{key}.{expected}")
    if missing_fields:
        print(f"  ⚠ Отсутствуют поля: {', '.join(missing_fields)}")

    blob = compile_blob(data)
    update_rune_text_data(blob)
    print(f"✅ rune_text_data.py обновлён (блоб {len(blob)} символов)")
    print("\nТеперь закоммить изменения:")
    print("  git add rune_text_data.py && git commit -m 'texts: обновлены тексты руны дня' && git push")


if __name__ == "__main__":
    main()

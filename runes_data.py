RUNE_FILES = [
    ("fehu", "Феху", "01-fehu.jpg"),
    ("uruz", "Уруз", "02-uruz.jpg"),
    ("thurisaz", "Турисаз", "03-thurisaz.jpg"),
    ("ansuz", "Ансуз", "04-ansuz.jpg"),
    ("raido", "Райдо", "05-raido.jpg"),
    ("kenaz", "Кеназ", "06-kenaz.jpg"),
    ("gebo", "Гебо", "07-gebo.jpg"),
    ("wunjo", "Вуньо", "08-wunjo.jpg"),
    ("hagalaz", "Хагалаз", "09-hagalaz.jpg"),
    ("nauthiz", "Наутиз", "10-nauthiz.jpg"),
    ("isa", "Иса", "11-isa.jpg"),
    ("jera", "Йера", "12-jera.jpg"),
    ("eihwaz", "Эйваз", "13-eihwaz.jpg"),
    ("perthro", "Перт", "14-perthro.jpg"),
    ("algiz", "Альгиз", "15-algiz.jpg"),
    ("sowilo", "Соулу", "16-sowilo.jpg"),
    ("tiwaz", "Тейваз", "17-teiwaz.jpg"),
    ("berkano", "Беркана", "18-berkana.jpg"),
    ("ehwaz", "Эваз", "19-ehwaz.jpg"),
    ("mannaz", "Манназ", "20-mannaz.jpg"),
    ("laguz", "Лагуз", "21-laguz.jpg"),
    ("ingwaz", "Ингуз", "22-inguz.jpg"),
    ("dagaz", "Дагаз", "23-dagaz.jpg"),
    ("othala", "Отал", "24-othala.jpg"),
]

BLANK_RUNE = {
    "key": "wyrd",
    "name": "Пустая руна",
    "image_file": None,
    "palette_image_files": {"light": "00_light.jpg", "dark": "00_dark.jpg", "premium": "00_premium.jpg"},
}

RUNES = []
for key, name, image_file in RUNE_FILES:
    RUNES.append(
        {
            "key": key,
            "name": name,
            "image_file": image_file,
        }
    )

RUNES.append(BLANK_RUNE)

KEY_ALIASES = {
    "teiwaz": "tiwaz",
    "berkana": "berkano",
    "inguz": "ingwaz",
    "blank": "wyrd",
}

NAME_ALIASES = {
    "Одал": "Отал",
}


def normalize_key(key: str) -> str:
    key = (key or "").strip().lower()
    return KEY_ALIASES.get(key, key)


def get_rune_by_name(name: str) -> dict:
    normalized = NAME_ALIASES.get(name, name)
    for rune in RUNES:
        if rune["name"] == normalized:
            return rune
    raise KeyError(f"Rune not found: {name}")


def get_rune_by_key(key: str) -> dict:
    normalized = normalize_key(key)
    for rune in RUNES:
        if rune["key"] == normalized:
            return rune
    raise KeyError(f"Rune not found: {key}")

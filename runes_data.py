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
    ("teiwaz", "Тейваз", "17-teiwaz.jpg"),
    ("berkana", "Беркана", "18-berkana.jpg"),
    ("ehwaz", "Эваз", "19-ehwaz.jpg"),
    ("mannaz", "Манназ", "20-mannaz.jpg"),
    ("laguz", "Лагуз", "21-laguz.jpg"),
    ("inguz", "Ингуз", "22-inguz.jpg"),
    ("dagaz", "Дагаз", "23-dagaz.jpg"),
    ("othala", "Одал", "24-othala.jpg"),
]

RUNES = []
for key, name, image_file in RUNE_FILES:
    RUNES.append(
        {
            "key": key,
            "name": name,
            "image_file": image_file,
            "short_desc": "",
            "answer_no": "",
            "answer_yes": "",
            "meaning_situation": "",
            "meaning_obstacle": "",
            "meaning_advice": "",
        }
    )


def get_rune_by_name(name: str) -> dict:
    for rune in RUNES:
        if rune["name"] == name:
            return rune
    raise KeyError(f"Rune not found: {name}")


def get_rune_by_key(key: str) -> dict:
    for rune in RUNES:
        if rune["key"] == key:
            return rune
    raise KeyError(f"Rune not found: {key}")

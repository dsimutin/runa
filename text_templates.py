def format_daily_reading(name, main_name, main_desc, aux_name, aux_desc, palette):
    if palette == "dark":
        opening = f"🌑 {name}, ситуация уже просит ясности."
        meaning_title = "Что важно понять"
        action_title = "Следующий шаг"
        action = "Назови главное напряжение прямо. Один честный шаг сейчас сильнее долгого ожидания."
    else:
        opening = f"🌞 {name}, сегодня пространство говорит тише обычного."
        meaning_title = "Что это меняет"
        action_title = "Что сделать"
        action = "Убери один лишний фокус. Освободи место для главного."

    return (
        f"{opening}\n\n"
        f"{main_name}\n\n"
        f"{main_desc}\n\n"
        f"{meaning_title}\n"
        "Смотри не только на событие, а на то, куда уходит твоё внимание.\n\n"
        f"Дополнительный сигнал — {aux_name}\n\n"
        f"{aux_desc}\n\n"
        f"{action_title}\n"
        f"{action}"
    )


def format_question_reading(name, question, rune_name, answer, palette):
    if palette == "dark":
        opening = f"🌑 {name}, ответ здесь не мягкий — он точный."
        final = "Не обходи главный факт. Проверь, где ты уже знаешь решение, но тянешь с действием."
    else:
        opening = f"🌞 {name}, руна отвечает не прямо, а через внутренний сигнал."
        final = "Не торопись с выводом. Сначала отдели реальное ощущение от шума вокруг ситуации."

    return (
        f"{opening}\n\n"
        "Вопрос\n"
        f"{question}\n\n"
        "Карта\n"
        f"{rune_name}\n\n"
        "Что руна показывает\n"
        f"{answer}\n\n"
        "Главное сейчас\n"
        f"{final}"
    )

from datetime import datetime, timezone


def moon_phase_today() -> dict:
    """Returns dict with keys: phase_name (str), emoji (str), description (str)"""
    now = datetime.now(tz=timezone.utc)

    # Julian Day calculation
    a = (14 - now.month) // 12
    y = now.year + 4800 - a
    m = now.month + 12 * a - 3
    jdn = (now.day
           + (153 * m + 2) // 5
           + 365 * y
           + y // 4
           - y // 100
           + y // 400
           - 32045)
    # Fractional day offset from midnight
    day_fraction = (now.hour - 12) / 24 + now.minute / 1440 + now.second / 86400
    jd = jdn + day_fraction

    # Reference new moon: 6 January 2000, 18:14 UTC → JD 2451550.1
    reference_new_moon = 2451550.1
    synodic_period = 29.53058867

    days_since = (jd - reference_new_moon) % synodic_period

    phases = [
        (1.85,  "Новолуние",         "🌑", "Хорошее время для новых намерений — цикл только начинается."),
        (7.38,  "Луна растёт",       "🌒", "Планы набирают силу — подходящий момент для первых шагов."),
        (11.08, "Первая четверть",   "🌓", "Время решений и действий — энергия на подъёме."),
        (14.77, "Луна почти полная", "🌔", "Всё задуманное набирает ход — не тормози."),
        (16.61, "Полнолуние",        "🌕", "Пик цикла — то, что зрело, выходит на поверхность."),
        (22.15, "Луна убывает",      "🌖", "Время завершать и отпускать то, что уже отжило."),
        (25.84, "Последняя четверть","🌗", "Хорошее время для осмысления и подведения итогов."),
        (29.53, "Луна на исходе",    "🌘", "Тишина перед новым циклом — время для отдыха и интеграции."),
    ]

    for threshold, name, emoji, description in phases:
        if days_since < threshold:
            return {"phase_name": name, "emoji": emoji, "description": description}

    # Fallback (should not happen)
    return {"phase_name": "Новолуние", "emoji": "🌑", "description": "Время для новых намерений и посева смыслов."}

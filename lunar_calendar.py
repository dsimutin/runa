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
        (1.85,  "Новолуние",        "🌑", "Время для новых намерений и посева смыслов."),
        (7.38,  "Растущий серп",    "🌒", "Планы набирают силу — хорошее время для первых шагов."),
        (11.08, "Первая четверть",  "🌓", "Момент решений и преодоления первых препятствий."),
        (14.77, "Растущая луна",    "🌔", "Энергия нарастает — всё задуманное набирает ход."),
        (16.61, "Полнолуние",       "🌕", "Кульминация: то, что зрело, выходит на свет."),
        (22.15, "Убывающая луна",   "🌖", "Время отпускать и завершать незаконченное."),
        (25.84, "Последняя четверть","🌗", "Переосмысление и подведение итогов."),
        (29.53, "Убывающий серп",   "🌘", "Тишина перед новым циклом — время отдыха и интеграции."),
    ]

    for threshold, name, emoji, description in phases:
        if days_since < threshold:
            return {"phase_name": name, "emoji": emoji, "description": description}

    # Fallback (should not happen)
    return {"phase_name": "Новолуние", "emoji": "🌑", "description": "Время для новых намерений и посева смыслов."}

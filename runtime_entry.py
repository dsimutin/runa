from html import escape
from pathlib import Path

import bot
import product_runtime
import product_runtime_final
from database import set_user_palette
from human_reading import HUMAN_READING_BUTTON
from rune_states import alt_meaning

PREMIUM_DIR_CANDIDATES = ["premium", "Premium", "Премиум", "премиум"]
IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp"]
DEFAULT_PALETTE = "premium"
TOPIC_KEYWORDS = {
    "love": ["вместе", "отнош", "люб", "чувств", "он", "она", "партнер", "партнёр", "бывш", "верн", "брак", "семь"],
    "work": ["работ", "карьер", "проект", "началь", "коллег", "бизнес", "клиент", "дело", "должн"],
    "money": ["деньг", "финанс", "доход", "зарплат", "куп", "прод", "долг", "цена", "оплат", "расход"],
    "choice": ["стоит", "выбор", "выбрать", "или", "решить", "соглас", "отказ", "уйти", "остаться", "как поступ"],
    "conflict": ["ссор", "конфликт", "обид", "давит", "манипул", "разговор", "претенз", "напряж"],
    "future": ["будет", "получится", "ждет", "ждёт", "перспектив", "исход", "результат", "сложится"],
}
TOPIC_NAMES = {"love": "отношения", "work": "работа", "money": "деньги", "choice": "выбор", "conflict": "конфликт", "future": "будущее", "general": "ситуация"}
RUNE_THEME_HINTS = {
    "fehu": {"love": "смотри, есть ли реальная отдача, а не только желание получить", "work": "ресурс есть, но его нужно считать", "money": "важна выгода и сохранение ресурса", "general": "главный вопрос — что ты получаешь и что тратишь"},
    "uruz": {"love": "много притяжения, но нужна зрелая сила", "work": "энергия есть, важно не прожечь её рывком", "money": "сила решения в контроле расходов", "general": "ситуация требует силы, но не давления"},
    "thurisaz": {"love": "граница важнее красивого жеста", "work": "не входи в борьбу без необходимости", "money": "не рискуй из раздражения", "general": "сначала защита, потом действие"},
    "ansuz": {"love": "разговор покажет больше, чем догадки", "work": "решает коммуникация и ясная формулировка", "money": "проверь договорённости словами и цифрами", "general": "нужно назвать вопрос прямо"},
    "raido": {"love": "важно, движетесь ли вы в одну сторону", "work": "поможет маршрут и порядок шагов", "money": "деньги требуют плана движения", "general": "курс важнее скорости"},
    "kenaz": {"love": "проясни мотив, а не только эмоцию", "work": "видно решение, если убрать туман", "money": "сначала прозрачность условий", "general": "карта просит ясности"},
    "gebo": {"love": "главная тема — взаимность", "work": "смотри на обмен и договор", "money": "важен честный баланс оплаты и пользы", "general": "обмен должен быть равным"},
    "wunjo": {"love": "есть тепло, если не заставлять себя радоваться", "work": "ищи вариант без внутреннего сопротивления", "money": "деньги должны давать облегчение, а не зависимость", "general": "ориентир — внутреннее согласие"},
    "hagalaz": {"love": "старый сценарий может ломаться", "work": "сбой показывает слабое место системы", "money": "не держись за рискованную схему", "general": "то, что трещит, требует пересмотра"},
    "nauthiz": {"love": "не путай нужду с близостью", "work": "ресурс ограничен, сократи лишнее", "money": "режим экономии и трезвый расчёт", "general": "действуй из минимума, не из паники"},
    "isa": {"love": "пауза честнее, чем выдавленное решение", "work": "процесс замер, давить бесполезно", "money": "покупки и риски лучше отложить", "general": "сейчас важно остановиться и посмотреть"},
    "jera": {"love": "результат зависит от накопленных действий", "work": "сработает регулярность", "money": "прибыль приходит циклом, не рывком", "general": "всё дозревает постепенно"},
    "eihwaz": {"love": "связь проверяется выдержкой", "work": "нужна устойчивость под давлением", "money": "сохраняй стратегию", "general": "выигрывает тот, кто не ломается"},
    "perthro": {"love": "часть мотивов скрыта", "work": "не все условия видны", "money": "есть неизвестный фактор", "general": "картина неполная"},
    "algiz": {"love": "не открывайся там, где нет безопасности", "work": "защити позицию", "money": "сначала безопасность, потом риск", "general": "границы помогут сохранить ресурс"},
    "sowilo": {"love": "ясность появится через честность", "work": "можно выходить в видимость", "money": "сильный шанс, если всё прозрачно", "general": "энергия есть, направь её чисто"},
    "teiwaz": {"love": "нужен честный выбор, а не ожидание", "work": "решает дисциплина и позиция", "money": "поступай по правилу, а не по импульсу", "general": "выбери линию и держи её"},
    "berkana": {"love": "связь может расти, если есть забота", "work": "проект требует выращивания", "money": "рост возможен через постепенность", "general": "дай процессу здоровые условия"},
    "ehwaz": {"love": "важна синхронность двоих", "work": "ищи партнёрство и согласованный темп", "money": "проверяй, кто едет с тобой в одной упряжке", "general": "результат зависит от согласованности"},
    "mannaz": {"love": "человеческий фактор решающий", "work": "роль людей важнее схемы", "money": "смотри, кто принимает решение", "general": "поведение людей меняет исход"},
    "laguz": {"love": "эмоции сильные, но могут мутить картину", "work": "интуиция полезна, хаос — нет", "money": "не плыви за настроением", "general": "поток нужен, но с берегами"},
    "inguz": {"love": "этап либо созревает, либо просит завершения", "work": "проект близок к переходу", "money": "созрел новый цикл", "general": "что-то подходит к новой фазе"},
    "dagaz": {"love": "возможен разворот восприятия", "work": "ситуация может резко проясниться", "money": "переход к другой модели", "general": "это точка смены состояния"},
    "othala": {"love": "важны ценности, дом и чувство принадлежности", "work": "опирайся на базу и правила", "money": "капитал и основа важнее быстрых трат", "general": "сначала фундамент"},
}


async def stable_profile_ready(update, context) -> bool:
    user = update.effective_user
    if not user:
        return False
    try:
        bot.ensure_user(bot.DB_PATH, user.id, bot.user_name(update))
        profile = bot.get_user_profile(bot.DB_PATH, user.id)
        if profile and profile.get("palette") in {"light", "dark", "premium"}:
            return True
        step = (profile or {}).get("onboarding_step", 0) or 0
        if step <= 0:
            bot.start_onboarding(bot.DB_PATH, user.id)
            step = 1
        if update.effective_message:
            await update.effective_message.reply_text(product_runtime.build_onboarding_question(step, bot.user_name(update)), reply_markup=product_runtime.onboarding_keyboard(step))
        return False
    except Exception:
        bot.logger.exception("Failed to prepare profile/onboarding")
        if update.effective_message:
            await update.effective_message.reply_text("Не получилось открыть профиль. Попробуй ещё раз чуть позже.", reply_markup=bot.MAIN_KEYBOARD)
        return False


bot.ensure_profile_ready = stable_profile_ready
product_runtime.bot.ensure_profile_ready = stable_profile_ready
product_runtime_final.bot.ensure_profile_ready = stable_profile_ready


def detect_topic(question: str) -> str:
    q = (question or "").lower()
    scores = {topic: sum(1 for word in words if word in q) for topic, words in TOPIC_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "general"


def rune_topic_hint(rune: dict, topic: str) -> str:
    key = (rune.get("key") or "").lower()
    data = RUNE_THEME_HINTS.get(key, {})
    return data.get(topic) or data.get("general") or "смотри на главный смысл руны в контексте вопроса"


def safer_get_rune_image_path(rune: dict, palette: str) -> str | None:
    image_file = rune.get("image_file") or ""
    rune_key = (rune.get("key") or "").lower().strip()
    wanted = Path(image_file)
    wanted_stem = wanted.stem.lower()
    wanted_number = wanted_stem.split("-", 1)[0] if "-" in wanted_stem else ""
    wanted_name = wanted_stem.split("-", 1)[-1]
    deck_dirs = PREMIUM_DIR_CANDIDATES if palette == "premium" else [bot.DECK_DIRS.get(palette, "light")]
    folders = []
    for deck_dir in deck_dirs:
        folders.append(Path(bot.BASE_DIR) / deck_dir)
        folders.append(Path(bot.BASE_DIR) / "decks" / deck_dir)
    for folder in folders:
        exact = folder / image_file
        if exact.exists():
            return str(exact)
    for folder in folders:
        if not folder.exists() or not folder.is_dir():
            continue
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
        for p in files:
            if p.name.lower() == image_file.lower():
                return str(p)
        if rune_key:
            for p in files:
                if rune_key in p.stem.lower():
                    return str(p)
        if wanted_name:
            for p in files:
                if wanted_name in p.stem.lower():
                    return str(p)
        if wanted_number.isdigit():
            for p in files:
                stem = p.stem.lower()
                if stem == wanted_number or stem.startswith(wanted_number + "-") or stem.startswith(wanted_number + "_"):
                    return str(p)
    return None


bot.get_rune_image_path = safer_get_rune_image_path
product_runtime.bot.get_rune_image_path = safer_get_rune_image_path
product_runtime_final.bot.get_rune_image_path = safer_get_rune_image_path

_original_send_private_or_group = bot.send_private_or_group


def _needs_html(text: str) -> bool:
    return any(tag in text for tag in ("<b>", "</b>", "<i>", "</i>"))


def _strip_html(text: str) -> str:
    return text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")


async def formatted_send_private_or_group(update, context, text: str, *, image_path: str | None = None) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return
    parse_mode = "HTML" if _needs_html(text) else None
    try:
        if bot.is_private(update):
            if image_path:
                with open(image_path, "rb") as image_file:
                    await message.reply_photo(photo=image_file, caption=text, reply_markup=bot.MAIN_KEYBOARD, parse_mode=parse_mode)
            else:
                await message.reply_text(text, reply_markup=bot.MAIN_KEYBOARD, parse_mode=parse_mode)
            return
        if image_path:
            with open(image_path, "rb") as image_file:
                await context.bot.send_photo(chat_id=user.id, photo=image_file, caption=text, parse_mode=parse_mode)
        else:
            await context.bot.send_message(chat_id=user.id, text=text, parse_mode=parse_mode)
        await message.reply_text("Отправил ответ тебе в личку ✨")
    except Exception:
        bot.logger.exception("Formatted send failed; falling back to plain send")
        try:
            await _original_send_private_or_group(update, context, _strip_html(text), image_path=image_path)
        except Exception:
            if message:
                await message.reply_text("Не получилось отправить ответ. Попробуй ещё раз позже.", reply_markup=bot.MAIN_KEYBOARD)


bot.send_private_or_group = formatted_send_private_or_group
product_runtime.bot.send_private_or_group = formatted_send_private_or_group
product_runtime_final.bot.send_private_or_group = formatted_send_private_or_group


def _rune_name(rune: dict) -> str:
    return escape(rune.get("name", "Руна"))


def _safe(text: str) -> str:
    return escape((text or "").strip())


def _short(text: str, limit: int = 190) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "."


def _title(rune: dict, reversed_state: bool) -> str:
    suffix = " · обратное" if reversed_state else " · прямое"
    return f"<b>{_rune_name(rune)}{suffix}</b>"


def _interp(rune: dict, palette: str) -> dict:
    source_palette = palette if palette != "premium" else "dark"
    return bot.rune_text(rune, source_palette)


def concise_daily_text(name: str, main: dict, main_text: dict, aux: dict, aux_text: dict, palette: str, main_alt: bool, aux_alt: bool) -> str:
    main_desc = alt_meaning(main, palette) if main_alt else main_text.get("short_desc", "")
    aux_desc = alt_meaning(aux, palette) if aux_alt else aux_text.get("short_desc", "")
    return f"🌞 <b>Руна дня</b>\n\n{_title(main, main_alt)}\n{_safe(_short(main_desc, 170))}\n\n<b>Дополнительно: {_rune_name(aux)}</b>\n{_safe(_short(aux_desc, 140))}\n\nОдин понятный шаг сегодня полезнее длинного внутреннего торга."


def yes_no_label(answer: str, alt: bool, rune: dict) -> str:
    key = (rune.get("key") or "").lower()
    negative_keys = {"isa", "nauthiz", "hagalaz", "thurisaz", "perthro"}
    positive_keys = {"fehu", "wunjo", "sowilo", "gebo", "dagaz", "berkana", "inguz"}
    if alt or key in negative_keys:
        return "Скорее нет"
    if key in positive_keys:
        return "Скорее да"
    return "Да, но с условием"


def concise_question_text(name: str, question: str, rune: dict, answer: str, palette: str, alt: bool) -> str:
    topic = detect_topic(question)
    verdict = yes_no_label(answer, alt, rune)
    body = alt_meaning(rune, palette) if alt else answer
    hint = rune_topic_hint(rune, topic)
    return f"❓ <b>{verdict}</b>\n\nТема: {TOPIC_NAMES[topic]}\n<i>{_safe(_short(question, 110))}</i>\n\n{_title(rune, alt)}\n{_safe(_short(body, 145))}\n\nВ этой теме: {_safe(hint)}."


def concise_spread_text(name: str, question: str, runes: list, palette: str) -> str:
    topic = detect_topic(question)
    first, second, third = runes[0], runes[1], runes[2]
    d1 = _interp(first, palette).get("situation") or _interp(first, palette).get("short_desc") or "Это показывает основу вопроса."
    d2 = _interp(second, palette).get("obstacle") or _interp(second, palette).get("short_desc") or "Здесь главное напряжение."
    d3 = _interp(third, palette).get("advice") or _interp(third, palette).get("short_desc") or "Это ближайший вектор."
    h1 = rune_topic_hint(first, topic)
    h2 = rune_topic_hint(second, topic)
    h3 = rune_topic_hint(third, topic)
    if topic == "love":
        bridge = "В отношениях смотри на взаимное движение, а не на ожидание ответа от одного человека."
    elif topic == "work":
        bridge = "В работе решает не желание, а условия: ресурс, роль и следующий конкретный шаг."
    elif topic == "money":
        bridge = "В деньгах сначала считай риск и обязательства, потом принимай решение."
    elif topic == "choice":
        bridge = "В выборе сильнее тот вариант, который не требует постоянно себя уговаривать."
    else:
        bridge = "Смысл расклада — увидеть, где опора, где помеха и какой шаг не создаст лишнего хаоса."
    return (
        f"🔮 <b>Расклад</b>\n\n"
        f"Тема: {TOPIC_NAMES[topic]}\n<i>{_safe(_short(question, 110))}</i>\n\n"
        f"<b>1. {_rune_name(first)}</b>\n{_safe(_short(d1, 135))}\n<i>{_safe(h1)}.</i>\n\n"
        f"<b>2. {_rune_name(second)}</b>\n{_safe(_short(d2, 135))}\n<i>{_safe(h2)}.</i>\n\n"
        f"<b>3. {_rune_name(third)}</b>\n{_safe(_short(d3, 135))}\n<i>{_safe(h3)}.</i>\n\n"
        f"{bridge}"
    )


def concise_help() -> str:
    return "Что можно сделать:\n\n🌞 <b>Руна дня</b> — фокус на сегодня.\n❓ <b>Вопрос (да/нет)</b> — одна карта.\n🔮 <b>Расклад</b> — три карты по ситуации.\n🕯 <b>Личный расклад</b> — ответ человека.\n⚙️ <b>Настройки</b> — сменить колоду."


async def concise_settings_command(update, context) -> None:
    if not await stable_profile_ready(update, context):
        return
    palette = bot.get_user_palette(update)
    current = product_runtime.PALETTE_NAMES.get(palette, "Светлая")
    markup = product_runtime.InlineKeyboardMarkup([[product_runtime.InlineKeyboardButton("🌞 Светлая", callback_data="settings:deck:light")], [product_runtime.InlineKeyboardButton("🌑 Тёмная", callback_data="settings:deck:dark")], [product_runtime.InlineKeyboardButton("💠 Премиум", callback_data="settings:deck:premium")]])
    await bot.send_private_or_group(update, context, f"⚙️ Колода\n\nСейчас используется: <b>{escape(current)}</b>")
    await update.effective_message.reply_text("Выбери колоду:", reply_markup=markup)


HUMAN_READING_TEXT_FINAL = "🕯 Личный расклад\n\nНапиши вопрос одним сообщением.\n\nОтвет подготовит человек. Обычно это занимает <b>5–10 минут</b>.\nСтоимость — <b>100 ₽</b>."

product_runtime.product_daily_text = concise_daily_text
product_runtime.product_question_text = concise_question_text
product_runtime.product_build_template_rasklad = concise_spread_text
bot.build_template_rasklad = concise_spread_text
product_runtime.patched_short_help = concise_help
product_runtime.bot.short_help = concise_help
product_runtime.settings_command = concise_settings_command
product_runtime.HUMAN_READING_TEXT = HUMAN_READING_TEXT_FINAL
product_runtime_final.HUMAN_READING_TEXT = HUMAN_READING_TEXT_FINAL


async def _typing(update, context) -> None:
    chat = update.effective_chat
    if chat:
        try:
            await context.bot.send_chat_action(chat_id=chat.id, action=product_runtime.ChatAction.TYPING)
        except Exception:
            bot.logger.exception("Failed typing action")


async def stable_send_rasklad(update, context, question: str) -> None:
    if not await stable_profile_ready(update, context):
        return
    await _typing(update, context)
    palette = bot.get_user_palette(update)
    runes = bot.choose_distinct_runes(3)
    image_path = bot.get_rune_image_path(runes[2], palette)
    if not image_path:
        await bot.send_missing_image_error(update, context, runes[2], palette)
        return
    text = concise_spread_text(bot.user_name(update), question, runes, palette)
    await bot.send_private_or_group(update, context, text, image_path=image_path)


bot.send_rasklad = stable_send_rasklad
product_runtime.bot.send_rasklad = stable_send_rasklad
product_runtime_final.bot.send_rasklad = stable_send_rasklad


async def operator_free_text_or_reply(update, context) -> bool:
    if not product_runtime_final.is_operator_chat(update):
        return False
    message = update.effective_message
    text = (message.text or "").strip() if message else ""
    if not text:
        return True
    request_id = product_runtime_final.extract_request_id_from_reply(update)
    if request_id is None:
        try:
            from support_requests import get_latest_open_request
            request = get_latest_open_request(bot.DB_PATH)
            request_id = request["id"] if request else None
        except Exception:
            bot.logger.exception("Failed to find latest support request")
    if request_id is None:
        await message.reply_text("Нет открытой заявки. Дождитесь нового личного расклада.")
        return True
    try:
        from support_requests import get_request, close_request
        request = get_request(bot.DB_PATH, request_id)
        if not request or request.get("status") == "answered":
            await message.reply_text("Нет открытой заявки. Дождитесь нового личного расклада.")
            return True
        await context.bot.send_message(chat_id=request["user_id"], text=text, reply_markup=bot.MAIN_KEYBOARD)
        close_request(bot.DB_PATH, request_id)
        await message.reply_text("Готово. Ответ отправлен пользователю.")
    except Exception:
        bot.logger.exception("Failed to send operator free-text answer")
        await message.reply_text("Не получилось отправить ответ пользователю.")
    return True


async def stable_text_router(update, context):
    if await operator_free_text_or_reply(update, context):
        return
    text = (update.effective_message.text or "").strip()
    state = context.user_data.get("state")
    if text in {"/start", "старт", "меню", "Меню"}:
        context.user_data.clear()
        await update.effective_message.reply_text("Меню готово. Выбери действие ниже.", reply_markup=bot.MAIN_KEYBOARD)
        return
    if text == "🌞 Руна дня":
        context.user_data.clear()
        await _typing(update, context)
        await product_runtime.product_runa_command(update, context)
        return
    if text in {"❓ Вопрос", "❓ Задать вопрос", "❓ Вопрос (да/нет)"}:
        context.user_data.clear()
        context.user_data["state"] = bot.STATE_WAITING_ASK
        await update.effective_message.reply_text("❓ Напиши вопрос одним сообщением.", reply_markup=bot.MAIN_KEYBOARD)
        return
    if text == "🔮 Расклад":
        context.user_data.clear()
        context.user_data["state"] = bot.STATE_WAITING_RASKLAD
        await update.effective_message.reply_text("🔮 Напиши вопрос для расклада одним сообщением.", reply_markup=bot.MAIN_KEYBOARD)
        return
    if text == HUMAN_READING_BUTTON:
        context.user_data.clear()
        context.user_data["state"] = product_runtime.STATE_WAITING_HUMAN
        await bot.send_private_or_group(update, context, HUMAN_READING_TEXT_FINAL)
        return
    if text == product_runtime.SETTINGS_BUTTON:
        context.user_data.clear()
        await concise_settings_command(update, context)
        return
    if text == "ℹ️ Помощь":
        context.user_data.clear()
        await bot.send_private_or_group(update, context, concise_help())
        return
    if state == bot.STATE_WAITING_ASK:
        context.user_data.clear()
        await _typing(update, context)
        await product_runtime.product_send_one_rune_answer(update, context, text)
        return
    if state == bot.STATE_WAITING_RASKLAD:
        context.user_data.clear()
        await stable_send_rasklad(update, context, text)
        return
    if state == product_runtime.STATE_WAITING_HUMAN:
        context.user_data.clear()
        await product_runtime_final.handle_human_request(update, context, text)
        return
    await update.effective_message.reply_text("Меню готово. Выбери действие ниже.", reply_markup=bot.MAIN_KEYBOARD)


product_runtime_final.final_text_router = stable_text_router
product_runtime.product_text_router = stable_text_router
bot.text_router = stable_text_router


async def robust_onboarding_callback(update, context) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    await query.answer()
    try:
        _, step_raw, answer = query.data.split(":", 2)
        current_step = int(step_raw)
        total = len(bot.ONBOARDING_QUESTIONS)
        result = bot.save_onboarding_answer(bot.DB_PATH, user.id, answer, total)
    except Exception:
        bot.logger.exception("Onboarding callback failed")
        try:
            await query.edit_message_text("Не получилось сохранить ответ. Нажми /start и попробуй снова.")
        except Exception:
            pass
        return
    if result.get("completed") or current_step >= len(bot.ONBOARDING_QUESTIONS):
        palette = result.get("palette") or DEFAULT_PALETTE
        try:
            await query.edit_message_text(product_runtime.onboarding_result_text(palette))
        except Exception:
            bot.logger.exception("Failed to edit onboarding completion message")
        await context.bot.send_message(chat_id=user.id, text="👇 Меню готово. Выбери действие ниже.", reply_markup=bot.MAIN_KEYBOARD)
        return
    next_step = result.get("next_step", current_step + 1)
    try:
        await query.edit_message_text(product_runtime.build_onboarding_question(next_step, bot.user_name(update)), reply_markup=product_runtime.onboarding_keyboard(next_step))
    except Exception:
        await context.bot.send_message(chat_id=user.id, text=product_runtime.build_onboarding_question(next_step, bot.user_name(update)), reply_markup=product_runtime.onboarding_keyboard(next_step))


product_runtime_final.final_onboarding_callback = robust_onboarding_callback


async def shorter_reading_pause(update, context, seconds: float | None = None) -> None:
    await _typing(update, context)


product_runtime.reading_pause = shorter_reading_pause

if __name__ == "__main__":
    bot.main()

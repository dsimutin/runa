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
    bot.logger.warning("Rune image not found by safer matcher: palette=%s rune=%s image_file=%s", palette, rune_key, image_file)
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
            bot.logger.exception("Plain fallback also failed")
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
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(".,;:")
    return cut + "."


def _title(rune: dict, reversed_state: bool) -> str:
    suffix = " · обратное" if reversed_state else " · прямое"
    return f"<b>{_rune_name(rune)}{suffix}</b>"


def _interp(rune: dict, palette: str) -> dict:
    source_palette = palette if palette != "premium" else "dark"
    return bot.rune_text(rune, source_palette)


def _human_daily_lead(palette: str) -> tuple[str, str]:
    if palette == "dark":
        return "Сегодня не стоит сглаживать то, что уже внутри цепляет.", "Один честный шаг будет полезнее длинных объяснений."
    if palette == "premium":
        return "Здесь важнее не первый смысл, а то, что повторяется вокруг ситуации.", "Не добавляй новых решений, пока не понял главный узел."
    return "Сегодня лучше идти через спокойный выбор, а не через усилие.", "Достаточно одного небольшого шага, который возвращает тебе опору."


def concise_daily_text(name: str, main: dict, main_text: dict, aux: dict, aux_text: dict, palette: str, main_alt: bool, aux_alt: bool) -> str:
    lead, finish = _human_daily_lead(palette)
    main_desc = alt_meaning(main, palette) if main_alt else main_text.get("short_desc", "")
    aux_desc = alt_meaning(aux, palette) if aux_alt else aux_text.get("short_desc", "")
    return (
        f"🌞 <b>Руна дня</b>\n\n"
        f"{lead}\n\n"
        f"{_title(main, main_alt)}\n"
        f"{_safe(_short(main_desc, 180))}\n\n"
        f"<b>Дополнительно: {_rune_name(aux)}</b>\n"
        f"{_safe(_short(aux_desc, 155))}\n\n"
        f"{finish}"
    )


def concise_question_text(name: str, question: str, rune: dict, answer: str, palette: str, alt: bool) -> str:
    if palette == "dark":
        lead = "Смотрю как вопрос да/нет. Здесь ответ скорее через факт, чем через надежду."
        finish = "Проверь, не уступаешь ли ты больше, чем готов."
    elif palette == "premium":
        lead = "Смотрю как вопрос да/нет. Тут важна деталь, которую легко пропустить."
        finish = "Сначала уточни для себя, что именно ты хочешь получить этим ответом."
    else:
        lead = "Смотрю как вопрос да/нет. Ответ мягкий, но направление видно."
        finish = "Выбирай тот шаг, после которого внутри станет спокойнее."
    body = alt_meaning(rune, palette) if alt else answer
    return (
        f"❓ <b>Ответ одной картой</b>\n\n"
        f"{lead}\n\n"
        f"<i>{_safe(_short(question, 120))}</i>\n\n"
        f"{_title(rune, alt)}\n"
        f"{_safe(_short(body, 185))}\n\n"
        f"{finish}"
    )


def concise_spread_text(name: str, question: str, runes: list, palette: str) -> str:
    first, second, third = runes[0], runes[1], runes[2]
    d1 = _interp(first, palette).get("situation") or _interp(first, palette).get("short_desc") or "Это показывает основу вопроса."
    d2 = _interp(second, palette).get("obstacle") or _interp(second, palette).get("short_desc") or "Здесь главное напряжение."
    d3 = _interp(third, palette).get("advice") or _interp(third, palette).get("short_desc") or "Это ближайший вектор."
    if any(word in question.lower() for word in ["вместе", "отнош", "люб", "он", "она", "чувств"]):
        bridge = "Если коротко: смотри не на обещание, а на реальное движение друг к другу."
    else:
        bridge = "Если коротко: расклад показывает, где есть опора, где теряется ясность и какой шаг будет самым трезвым."
    return (
        f"🔮 <b>Расклад</b>\n\n"
        f"<i>{_safe(_short(question, 120))}</i>\n\n"
        f"<b>1. {_rune_name(first)}</b>\n{_safe(_short(d1, 170))}\n\n"
        f"<b>2. {_rune_name(second)}</b>\n{_safe(_short(d2, 170))}\n\n"
        f"<b>3. {_rune_name(third)}</b>\n{_safe(_short(d3, 170))}\n\n"
        f"{bridge}\n\n"
        f"Хочешь — задай уточняющий вопрос одной картой."
    )


def concise_help() -> str:
    return (
        "Что можно сделать:\n\n"
        "🌞 <b>Руна дня</b> — фокус на сегодня.\n"
        "❓ <b>Вопрос (да/нет)</b> — одна карта.\n"
        "🔮 <b>Расклад</b> — три карты по ситуации.\n"
        "🕯 <b>Личный расклад</b> — ответ человека.\n"
        "⚙️ <b>Настройки</b> — сменить колоду."
    )


async def concise_settings_command(update, context) -> None:
    if not await stable_profile_ready(update, context):
        return
    palette = bot.get_user_palette(update)
    current = product_runtime.PALETTE_NAMES.get(palette, "Светлая")
    markup = product_runtime.InlineKeyboardMarkup([
        [product_runtime.InlineKeyboardButton("🌞 Светлая", callback_data="settings:deck:light")],
        [product_runtime.InlineKeyboardButton("🌑 Тёмная", callback_data="settings:deck:dark")],
        [product_runtime.InlineKeyboardButton("💠 Премиум", callback_data="settings:deck:premium")],
    ])
    await bot.send_private_or_group(update, context, f"⚙️ Колода\n\nСейчас используется: <b>{escape(current)}</b>")
    await update.effective_message.reply_text("Выбери колоду:", reply_markup=markup)


HUMAN_READING_TEXT_FINAL = (
    "🕯 Личный расклад\n\n"
    "Напиши вопрос одним сообщением.\n\n"
    "Ответ подготовит человек. Обычно это занимает <b>5–10 минут</b>.\n"
    "Стоимость — <b>100 ₽</b>."
)


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
            from support_requests import get_request, close_request
            import sqlite3
            with sqlite3.connect(bot.DB_PATH, timeout=30) as conn:
                row = conn.execute("SELECT id FROM support_requests WHERE status != 'answered' ORDER BY id DESC LIMIT 1").fetchone()
            request_id = row[0] if row else None
        except Exception:
            bot.logger.exception("Failed to find latest support request")
    if request_id is None:
        await message.reply_text("Нет открытой заявки. Ответьте на сообщение заявки или дождитесь нового вопроса.")
        return True
    try:
        from support_requests import get_request, close_request
        request = get_request(bot.DB_PATH, request_id)
        if not request:
            await message.reply_text("Заявка не найдена.")
            return True
        if request.get("status") == "answered":
            await message.reply_text("Эта заявка уже закрыта.")
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
    if text == "🌞 Руна дня":
        context.user_data.clear()
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
    await update.effective_message.reply_text("Выбери действие кнопкой ниже.", reply_markup=bot.MAIN_KEYBOARD)


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
        bot.logger.exception("Failed to show next onboarding question")
        await context.bot.send_message(chat_id=user.id, text=product_runtime.build_onboarding_question(next_step, bot.user_name(update)), reply_markup=product_runtime.onboarding_keyboard(next_step))


product_runtime_final.final_onboarding_callback = robust_onboarding_callback


async def shorter_reading_pause(update, context, seconds: float | None = None) -> None:
    await _typing(update, context)


product_runtime.reading_pause = shorter_reading_pause


if __name__ == "__main__":
    bot.main()

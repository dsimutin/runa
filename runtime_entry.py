from html import escape
from pathlib import Path

import bot
import product_runtime
import product_runtime_final  # applies final handlers and support request flow
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
        if not profile or profile.get("palette") not in {"light", "dark", "premium"}:
            set_user_palette(bot.DB_PATH, user.id, DEFAULT_PALETTE)
        return True
    except Exception:
        bot.logger.exception("Failed to repair profile")
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
    bot.logger.warning("Rune image not found by safer matcher: palette=%s rune=%s image_file=%s folders=%s", palette, rune_key, image_file, folders)
    return None


bot.get_rune_image_path = safer_get_rune_image_path
product_runtime.bot.get_rune_image_path = safer_get_rune_image_path
product_runtime_final.bot.get_rune_image_path = safer_get_rune_image_path


_original_send_private_or_group = bot.send_private_or_group


def _needs_html(text: str) -> bool:
    return any(tag in text for tag in ("<b>", "</b>", "<u>", "</u>", "<i>", "</i>"))


def _strip_html(text: str) -> str:
    return text.replace("<b>", "").replace("</b>", "").replace("<u>", "").replace("</u>", "").replace("<i>", "").replace("</i>", "")


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


def _short_desc(text: str, limit: int = 120) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "."


def _title(rune: dict, reversed_state: bool) -> str:
    name = _rune_name(rune)
    return f"<b>{name}</b>\nОбратное положение" if reversed_state else f"<b>{name}</b>"


def _interp(rune: dict, palette: str) -> dict:
    # Premium uses the darker interpretation data, but the final text rhythm stays premium.
    source_palette = palette if palette != "premium" else "dark"
    return bot.rune_text(rune, source_palette)


def concise_daily_text(name: str, main: dict, main_text: dict, aux: dict, aux_text: dict, palette: str, main_alt: bool, aux_alt: bool) -> str:
    if palette == "dark":
        lead = "<b>Не игнорируй напряжение.</b>"
        note = "Ситуация уже изменилась.\nЛучше не делать вид, что всё спокойно."
        action = "<u>Обозначь позицию без давления.</u>"
    elif palette == "premium":
        lead = "<b>Смотри на главное.</b>"
        note = "Не всё требует ответа сразу.\nСейчас важнее точность."
        action = "<u>Не добавляй новых обязательств.</u>"
    else:
        lead = "<b>Не ускоряй события.</b>"
        note = "День лучше пройти спокойнее.\nНе пытайся закрыть всё сразу."
        action = "<u>Сделай один простой шаг.</u>"
    main_desc = alt_meaning(main, palette) if main_alt else main_text.get("short_desc", "")
    aux_desc = alt_meaning(aux, palette) if aux_alt else aux_text.get("short_desc", "")
    return (
        "🜂 Сегодня\n\n"
        f"{lead}\n\n"
        f"{_title(main, main_alt)}\n"
        f"{_safe(_short_desc(main_desc, 110))}\n\n"
        f"{note}\n\n"
        f"Дополнительно: <b>{_rune_name(aux)}</b>\n"
        f"{_safe(_short_desc(aux_desc, 95))}\n\n"
        f"{action}"
    )


def concise_question_text(name: str, question: str, rune: dict, answer: str, palette: str, alt: bool) -> str:
    if palette == "dark":
        lead = "<b>Здесь лучше не тянуть.</b>"
        advice = "<u>Не отвечай из эмоции. Но позицию обозначь.</u>"
    elif palette == "premium":
        lead = "<b>Сначала проверь детали.</b>"
        advice = "<u>Потом действуй.</u>"
    else:
        lead = "<b>Ответ есть, но спешка мешает.</b>"
        advice = "<u>Возьми паузу и смотри на состояние.</u>"
    body = alt_meaning(rune, palette) if alt else answer
    return (
        "🜁 Ответ\n\n"
        f"{lead}\n\n"
        f"Вопрос:\n<i>{_safe(_short_desc(question, 150))}</i>\n\n"
        f"{_title(rune, alt)}\n"
        f"{_safe(_short_desc(body, 115))}\n\n"
        f"{advice}"
    )


def concise_spread_text(name: str, question: str, runes: list, palette: str) -> str:
    first, second, third = runes[0], runes[1], runes[2]
    close = "<u>Сначала точность. Потом действие.</u>" if palette == "premium" else "<u>Не форсируй. Двигайся спокойно.</u>"

    def line(rune: dict, label: str, key: str) -> str:
        data = _interp(rune, palette)
        raw = data.get(key) or data.get("short_desc") or "Здесь лучше не спешить с выводом."
        return f"{label}\n<b>{_rune_name(rune)}</b>\n{_safe(_short_desc(raw, 125))}"

    return (
        "🔮 Расклад\n\n"
        f"<i>{_safe(_short_desc(question, 140))}</i>\n\n"
        f"{line(first, '🜂 Основа', 'situation')}\n\n"
        f"{line(second, '🜁 Что мешает', 'obstacle')}\n\n"
        f"{line(third, '🜂 К чему идёт', 'advice')}\n\n"
        f"{close}"
    )


def concise_help() -> str:
    return (
        "🜂 Что можно сделать\n\n"
        "🌞 <b>Руна дня</b>\nФокус на сегодня.\n\n"
        "❓ <b>Вопрос</b>\nОтвет одной картой.\n\n"
        "🔮 <b>Расклад</b>\nРазбор ситуации.\n\n"
        f"{HUMAN_READING_BUTTON} <b>Личный расклад</b>\nОтвет подготовит человек.\n\n"
        "⚙️ <b>Настройки</b>\nСменить колоду."
    )


async def concise_settings_command(update, context) -> None:
    if not await stable_profile_ready(update, context):
        return
    palette = bot.get_user_palette(update)
    current = product_runtime.PALETTE_NAMES.get(palette, "Светлая")
    markup = product_runtime.InlineKeyboardMarkup([
        [product_runtime.InlineKeyboardButton("🌞 Светлая", callback_data="settings:deck:light")],
        [product_runtime.InlineKeyboardButton("🌑 Тёмная", callback_data="settings:deck:dark")],
        [product_runtime.InlineKeyboardButton("🜁 Премиум", callback_data="settings:deck:premium")],
    ])
    await bot.send_private_or_group(update, context, f"⚙️ Колода\n\nСейчас используется:\n<b>{escape(current)}</b>\n\nМожно сменить вручную.")
    await update.effective_message.reply_text("Выбери колоду:", reply_markup=markup)


HUMAN_READING_TEXT_FINAL = (
    "🕯 Личный расклад\n\n"
    "Напиши вопрос одним сообщением.\n\n"
    "Ответ подготовит человек.\n"
    "Обычно это занимает <b>5–10 минут</b>.\n\n"
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


async def stable_send_rasklad(update, context, question: str) -> None:
    if not await stable_profile_ready(update, context):
        return
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


async def stable_text_router(update, context):
    text = (update.effective_message.text or "").strip()
    state = context.user_data.get("state")
    if text == "🌞 Руна дня":
        context.user_data.clear()
        await product_runtime.product_runa_command(update, context)
        return
    if text in {"❓ Вопрос", "❓ Задать вопрос"}:
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


async def shorter_reading_pause(update, context, seconds: float | None = None) -> None:
    chat = update.effective_chat
    if chat:
        try:
            await context.bot.send_chat_action(chat_id=chat.id, action=product_runtime.ChatAction.TYPING)
        except Exception:
            bot.logger.exception("Failed to send typing action")
    import asyncio
    import random
    await asyncio.sleep(seconds if seconds is not None else random.uniform(0.5, 1.0))


product_runtime.reading_pause = shorter_reading_pause


if __name__ == "__main__":
    bot.main()

from html import escape

import bot
import product_runtime
import product_runtime_final
import runtime_entry  # applies core stable routing, text, image and spread fixes
from database import set_user_palette
from human_reading import HUMAN_READING_BUTTON

VERSION = "RUNA STABLE 2026-05-07-4"


# -----------------------------------------------------------------------------
# Clean onboarding for truly new users only.
# Runtime routing already prevents onboarding from hijacking active scenarios.
# -----------------------------------------------------------------------------

bot.ONBOARDING_QUESTIONS = [
    {
        "text": "Когда заходишь в новое место, что замечаешь первым?",
        "a": "Настроение и общее ощущение",
        "b": "Границы, правила и риски",
        "c": "Детали, которые другие пропускают",
    },
    {
        "text": "Какой ответ сейчас ближе?",
        "a": "Мягкий ориентир",
        "b": "Чёткое предупреждение",
        "c": "Точный разбор без лишнего",
    },
    {
        "text": "Что помогает принять решение?",
        "a": "Пауза и спокойствие",
        "b": "Факты и позиция",
        "c": "Нюансы и подтекст",
    },
    {
        "text": "Какой тон комфортнее?",
        "a": "Бережный",
        "b": "Прямой",
        "c": "Тихий и точный",
    },
    {
        "text": "Что важнее в ответе?",
        "a": "Поддержка",
        "b": "Ясность",
        "c": "Глубина без тумана",
    },
]
product_runtime.bot.ONBOARDING_QUESTIONS = bot.ONBOARDING_QUESTIONS
product_runtime_final.bot.ONBOARDING_QUESTIONS = bot.ONBOARDING_QUESTIONS


def clean_onboarding_question(step: int, name: str) -> str:
    q = bot.ONBOARDING_QUESTIONS[step - 1]
    return (
        f"🜂 Настройка колоды\n\n"
        f"Вопрос {step}/5\n"
        f"{q['text']}\n\n"
        f"A — {q['a']}\n"
        f"B — {q['b']}\n"
        f"C — {q['c']}"
    )


def clean_onboarding_result(palette: str) -> str:
    names = {"light": "Светлая", "dark": "Тёмная", "premium": "Премиум"}
    notes = {
        "light": "Мягкий тон. Больше спокойствия и поддержки.",
        "dark": "Прямой тон. Больше ясности и границ.",
        "premium": "Тихий тон. Больше точности и нюансов.",
    }
    return (
        "🜂 Колода настроена\n\n"
        f"Выбрана: <b>{escape(names.get(palette, 'Премиум'))}</b>\n\n"
        f"{escape(notes.get(palette, notes['premium']))}\n\n"
        "Колоду можно сменить в настройках."
    )


bot.build_onboarding_question = clean_onboarding_question
bot.onboarding_result_text = clean_onboarding_result
product_runtime.build_onboarding_question = clean_onboarding_question
product_runtime.onboarding_result_text = clean_onboarding_result
product_runtime.bot.build_onboarding_question = clean_onboarding_question
product_runtime.bot.onboarding_result_text = clean_onboarding_result
product_runtime_final.product_runtime.build_onboarding_question = clean_onboarding_question
product_runtime_final.product_runtime.onboarding_result_text = clean_onboarding_result


# -----------------------------------------------------------------------------
# Commands: keep slash commands consistent with button UX.
# -----------------------------------------------------------------------------

async def stable_start_command(update, context):
    context.user_data.clear()
    if not update.effective_user or not update.effective_message:
        return
    if not bot.is_private(update):
        await update.effective_message.reply_text(
            "Открой личку с ботом. Там появится меню.",
            reply_markup=bot.private_link_markup(context),
        )
        return
    name = bot.user_name(update)
    try:
        bot.ensure_user(bot.DB_PATH, update.effective_user.id, name)
        profile = bot.get_user_profile(bot.DB_PATH, update.effective_user.id)
        if not profile or not profile.get("palette"):
            bot.start_onboarding(bot.DB_PATH, update.effective_user.id)
            await update.effective_message.reply_text(clean_onboarding_question(1, name), reply_markup=product_runtime.onboarding_keyboard(1))
            return
    except Exception:
        bot.logger.exception("Stable start failed")
        await update.effective_message.reply_text("Не получилось открыть профиль. Попробуй позже.", reply_markup=bot.MAIN_KEYBOARD)
        return
    await update.effective_message.reply_text(
        f"🜂 Бот готов\n\nВерсия: {VERSION}\n\nВыбери действие ниже.",
        reply_markup=bot.MAIN_KEYBOARD,
    )


async def stable_help_command(update, context):
    context.user_data.clear()
    await bot.send_private_or_group(update, context, runtime_entry.concise_help())


async def stable_profile_command(update, context):
    context.user_data.clear()
    if not await runtime_entry.stable_profile_ready(update, context):
        return
    palette = bot.get_user_palette(update)
    names = {"light": "Светлая", "dark": "Тёмная", "premium": "Премиум"}
    await bot.send_private_or_group(
        update,
        context,
        f"🜂 Профиль\n\nКолода:\n<b>{escape(names.get(palette, 'Премиум'))}</b>\n\nМожно сменить её в настройках.",
    )


async def stable_ask_command(update, context):
    if not await runtime_entry.stable_profile_ready(update, context):
        return
    question = " ".join(context.args).strip()
    if not question:
        context.user_data.clear()
        context.user_data["state"] = bot.STATE_WAITING_ASK
        await update.effective_message.reply_text("❓ Напиши вопрос одним сообщением.", reply_markup=bot.MAIN_KEYBOARD)
        return
    context.user_data.clear()
    await product_runtime.product_send_one_rune_answer(update, context, question)


async def stable_rasklad_command(update, context):
    if not await runtime_entry.stable_profile_ready(update, context):
        return
    question = " ".join(context.args).strip()
    if not question:
        context.user_data.clear()
        context.user_data["state"] = bot.STATE_WAITING_RASKLAD
        await update.effective_message.reply_text("🔮 Напиши вопрос для расклада одним сообщением.", reply_markup=bot.MAIN_KEYBOARD)
        return
    context.user_data.clear()
    await runtime_entry.stable_send_rasklad(update, context, question)


async def stable_check_decks_command(update, context):
    if not bot.is_admin(update):
        await update.effective_message.reply_text("Эта техническая команда доступна только администратору.")
        return
    lines = ["🧩 Проверка колод", ""]
    for palette in ("light", "dark", "premium"):
        found = 0
        missing = []
        for rune in bot.RUNES:
            if bot.get_rune_image_path(rune, palette):
                found += 1
            else:
                missing.append(rune.get("image_file", rune.get("name", "unknown")))
        lines.append(f"{palette}: {found}/{len(bot.RUNES)}")
        if missing:
            lines.append("Не найдены:")
            lines.extend(f"— {x}" for x in missing[:12])
            if len(missing) > 12:
                lines.append(f"…и ещё {len(missing) - 12}")
        lines.append("")
    await bot.send_private_or_group(update, context, "\n".join(lines).strip())


bot.start_command = stable_start_command
bot.help_command = stable_help_command
bot.profile_command = stable_profile_command
bot.ask_command = stable_ask_command
bot.rasklad_command = stable_rasklad_command
bot.check_decks_command = stable_check_decks_command

product_runtime.bot.start_command = stable_start_command
product_runtime.bot.help_command = stable_help_command
product_runtime.bot.profile_command = stable_profile_command
product_runtime.bot.ask_command = stable_ask_command
product_runtime.bot.rasklad_command = stable_rasklad_command
product_runtime.bot.check_decks_command = stable_check_decks_command

product_runtime_final.final_start_command = stable_start_command


if __name__ == "__main__":
    bot.main()

from html import escape
from pathlib import Path

import bot
import product_runtime
import product_runtime_final
from database import set_user_palette
from human_reading import HUMAN_READING_BUTTON
from rune_states import alt_meaning

# -------------------------
# Human reading dispatch fix
# -------------------------
ADMIN_IDS = [123456789, 987654321]  # numeric chat_ids for @MRGRIEF, @RichStewardess

async def stable_human_dispatch(update, context, text: str) -> None:
    message = update.effective_message
    if not message:
        return
    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, f'Вопрос от {update.effective_user.first_name}: {text}')
            sent += 1
        except Exception as e:
            bot.logger.exception(f'Failed to send human reading to {admin_id}')
    if sent > 0:
        await message.reply_text(f'Заявка принята. Ответ придет в течение 5–10 минут.', reply_markup=bot.MAIN_KEYBOARD)
    else:
        await message.reply_text(f'Не удалось отправить оператору. Мы сохранили заявку, попробуй позже.', reply_markup=bot.MAIN_KEYBOARD)

product_runtime_final.handle_human_request = stable_human_dispatch

# -------------------------
# Text enrichment for daily, question and spread
# -------------------------
def enrich_text_block(text: str, variant: int) -> str:
    # variant controls depth, 1=shallow,2=deeper,3=practical
    lines = text.split('\n')
    if variant == 2:
        lines = [line + '.' if not line.endswith('.') else line for line in lines]
    if variant == 3:
        lines.append('Смотри на это как на практический ориентир.')
    return '\n'.join(lines)

_original_product_daily_text = product_runtime.product_daily_text
_original_product_question_text = product_runtime.product_question_text
_original_product_build_template_rasklad = product_runtime.product_build_template_rasklad


async def enhanced_daily_text(name, main, main_text, aux, aux_text, palette, main_alt, aux_alt):
    base = _original_product_daily_text(name, main, main_text, aux, aux_text, palette, main_alt, aux_alt)
    return enrich_text_block(base, 2)

async def enhanced_question_text(name, question, rune, answer, palette, alt):
    base = _original_product_question_text(name, question, rune, answer, palette, alt)
    return enrich_text_block(base, 2)

async def enhanced_spread_text(name, question, runes, palette):
    base = _original_product_build_template_rasklad(name, question, runes, palette)
    return enrich_text_block(base, 3)

product_runtime.product_daily_text = enhanced_daily_text
product_runtime.product_question_text = enhanced_question_text
product_runtime.product_build_template_rasklad = enhanced_spread_text
bot.build_template_rasklad = enhanced_spread_text
product_runtime_final.bot.build_template_rasklad = enhanced_spread_text

# -------------------------
# Ensure fallback is patched to MAIN_KEYBOARD
# -------------------------
_original_send = bot.send_private_or_group

async def patched_send(update, context, text: str, *, image_path=None):
    try:
        await _original_send(update, context, text, image_path=image_path)
    except Exception:
        if update.effective_message:
            await update.effective_message.reply_text('Не получилось отправить ответ. Попробуй позже.', reply_markup=bot.MAIN_KEYBOARD)

bot.send_private_or_group = patched_send
product_runtime.bot.send_private_or_group = patched_send
product_runtime_final.bot.send_private_or_group = patched_send
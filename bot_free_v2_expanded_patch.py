"""Patch notes/code snippets for upgrading bot_free_v2.py.

This patch connects runes_expanded_full.py, adds human-like typing delay,
and lets user ask a follow-up after a spread.
"""

# 1. Add imports near the top of bot_free_v2.py:
# import asyncio
# from telegram.constants import ChatAction
# from runes_expanded_full import get_topic_text, get_variant

# 2. Add new state near STATE_ASK / STATE_RASKLAD:
# STATE_FOLLOWUP = 'followup'

# 3. Add these helper functions after line():

QUESTION_KEYWORDS = {
    'work': ['работ', 'проект', 'деньг', 'финанс', 'бизнес', 'клиент', 'доход', 'карьер', 'зарплат'],
    'love': ['отнош', 'любов', 'муж', 'жена', 'парень', 'девуш', 'партнер', 'партнёр', 'семь', 'бывш'],
    'health': ['здоров', 'тело', 'самочув', 'тревог', 'устал', 'энерг', 'сон', 'бол'],
    'choice': ['выбор', 'выбрать', 'решить', 'стоит ли', 'как поступить', 'переезд', 'остаться', 'уехать'],
}


def question_type(question: str) -> str:
    q = question.lower()
    for kind, words in QUESTION_KEYWORDS.items():
        if any(w in q for w in words):
            return kind
    return 'general'


def stable_index(*parts, modulo: int = 3) -> int:
    seed = '|'.join(str(p) for p in parts)
    return sum(ord(ch) for ch in seed) % modulo


def expanded_line(rune: dict, pal: str, topic: str, field: str) -> str:
    key = rune.get('key', '')
    base = line(rune, pal, field)
    return get_topic_text(key, pal, topic, field, base)


def daily_expanded(rune: dict, pal: str, user_id: int, today: str) -> str:
    idx = stable_index(user_id, today, rune.get('key', ''), modulo=3)
    return get_variant(rune.get('key', ''), pal, 'daily_variants', idx, line(rune, pal, 'short_desc'))


def aux_expanded(rune: dict, pal: str, user_id: int, today: str) -> str:
    idx = stable_index(user_id, today, rune.get('key', ''), 'aux', modulo=2)
    return get_variant(rune.get('key', ''), pal, 'aux_variants', idx, line(rune, pal, 'short_desc'))


async def thinking(update: Update, context: ContextTypes.DEFAULT_TYPE, seconds: float = 1.2):
    chat_id = update.effective_chat.id if update.effective_chat else update.effective_user.id
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        await asyncio.sleep(seconds)
    except Exception:
        pass


# 4. Upgrade runa() text to:
# today = date.today().isoformat()
# main_text = daily_expanded(main, pal, update.effective_user.id, today)
# aux_text = aux_expanded(aux, pal, update.effective_user.id, today)
# await thinking(update, context, 1.0)
# text = f'🌞 **Твоя руна дня — {main["name"]}**\n\n{main_text}\n\n**Дополнительный акцент — {aux["name"]}**\n\n{aux_text}\n\n**Что сделать сегодня**\nНе пытайся решить всё сразу. Выбери один конкретный шаг и проверь его на практике.\n\n**Главный смысл дня**\nДвигаться не быстрее, а точнее.'

# 5. Upgrade one_answer():
# topic = question_type(question)
# answer = expanded_line(rune, pal, topic, key)
# await thinking(update, context, 1.1)
# text = f'❓ **Разбираю вопрос:**\n«{question}»\n\n**Карта — {rune["name"]}**\n\n**Ответ**\n{answer}\n\n**Что дальше**\nСмотри не только на сам ответ, но и на то, какой шаг он предлагает сделать сейчас.'

# 6. Upgrade rasklad_answer():
# topic = question_type(question)
# await thinking(update, context, 1.5)
# context.user_data['last_spread'] = {'question': question, 'runes': [a['name'], b['name'], c['name']], 'topic': topic, 'palette': pal}
# context.user_data['state'] = STATE_FOLLOWUP
# text = f'🔮 **Разбираю твой вопрос:**\n«{question}»\n\n**Ситуация — {a["name"]}**\n{expanded_line(a, pal, topic, "situation")}\n\n**Препятствие — {b["name"]}**\n{expanded_line(b, pal, topic, "obstacle")}\n\n**Что поможет — {c["name"]}**\n{expanded_line(c, pal, topic, "advice")}\n\n**Если хочешь уточнить**\nНапиши обычным сообщением, что именно непонятно в раскладе. Я поясню по этим же рунам без нового расклада.'

# 7. Add followup_answer():

async def followup_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str):
    data = context.user_data.get('last_spread') or {}
    if not data:
        context.user_data.pop('state', None)
        await update.effective_message.reply_text('Я не вижу прошлого расклада. Лучше нажми 🔮 Расклад и задай вопрос заново.', reply_markup=MENU)
        return
    await thinking(update, context, 0.9)
    text = (
        f'🜂 **Уточнение по раскладу**\n\n'
        f'Ты спрашиваешь: «{question}»\n\n'
        f'Смотрю не как новый расклад, а как пояснение к уже выпавшим рунам: {", ".join(data.get("runes", []))}.\n\n'
        f'Если коротко: первая руна показывает фон ситуации, вторая — где застревание, третья — что практически сделать. '
        f'Твой уточняющий вопрос лучше всего читать через третью руну: она отвечает не “что будет”, а “какой шаг сейчас разумнее”.\n\n'
        f'Хочешь новый взгляд — нажми 🔮 Расклад и задай вопрос заново.'
    )
    context.user_data.pop('state', None)
    await send_answer(update, context, text)

# 8. In text_router(), before default fallback, add:
# if state == STATE_FOLLOWUP:
#     await followup_answer(update, context, text); return

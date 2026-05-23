"""Personal birth rune — calculated from date of birth."""
import re
import sqlite3
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import bot as _bot
from database import get_connection, ensure_schema, DatabaseError
from runes_data import RUNES
from rune_text_repository import get_daily_text

STATE_WAITING_BIRTH_DATE = "waiting_birth_date"

BIRTH_RUNE_INTERPRETATIONS = {
    "fehu": "Феху — руна изобилия и достижений. Ты умеешь создавать и накапливать. Твой путь связан с материализацией идей и бережным отношением к тому, что уже есть.",
    "uruz": "Уруз — руна силы и здоровья. В тебе живёт огромная природная сила. Ты восстанавливаешься там, где другие ломаются, и находишь энергию там, где её не видят.",
    "thurisaz": "Турисаз — руна защиты и испытания. Ты приходишь туда, где нужна сила духа. Трудности не ломают тебя — они делают тебя точнее.",
    "ansuz": "Ансуз — руна слова и мудрости. Твой дар — понимать глубже и выражать точнее. Слова, которые ты находишь, попадают в суть.",
    "raidho": "Райдо — руна пути и движения. Ты рождён для изменений и перемен. Неподвижность тебе хуже, чем неопределённость — ты в своей стихии в движении.",
    "kenaz": "Кеназ — руна знания и света. Ты умеешь освещать темноту — в себе и в других. Твой путь связан с пониманием скрытого.",
    "gebo": "Гебо — руна дара и обмена. Твоя природа — давать и получать в равных мерах. Ты создаёшь связи там, где их не было.",
    "wunjo": "Вуньо — руна радости и гармонии. Ты умеешь находить красоту в простом. Твой путь — напоминать другим, что жизнь может быть лёгкой.",
    "hagalaz": "Хагалаз — руна трансформации. Ты проходишь через разрушение и выходишь другим человеком. Твои кризисы — это твои точки роста.",
    "nauthiz": "Наутиз — руна необходимости. Ты умеешь работать в ограничениях и находить выход там, где другие сдаются.",
    "isa": "Иса — руна паузы и сосредоточения. Ты знаешь цену тишине. Твоя сила — в умении остановиться и увидеть.",
    "jera": "Йера — руна цикла и урожая. Ты понимаешь, что всему своё время. Твой путь — терпение и последовательность.",
    "eihwaz": "Эйваз — руна стойкости. Ты умеешь удерживать равновесие между мирами — видимым и невидимым, прошлым и будущим.",
    "perthro": "Перто — руна тайны и судьбы. Ты притягиваешь неожиданное. Твой путь полон случайностей, которые оказываются не случайными.",
    "algiz": "Алгиз — руна защиты и инстинкта. У тебя острое чувство опасности и способность защищать то, что важно.",
    "sowilo": "Соулу — руна солнца и победы. Ты умеешь находить путь к свету даже из самой тёмной точки. Твоя воля — твоя сила.",
    "tiwaz": "Тивац — руна справедливости. Ты живёшь по внутреннему кодексу чести. Тебе важно, чтобы всё было правильно — не по правилам, а по сути.",
    "berkano": "Беркано — руна роста и заботы. Ты умеешь создавать пространство для роста — своего и чужого. Твоя природа — питать и беречь.",
    "ehwaz": "Эваз — руна партнёрства и доверия. Ты раскрываешься в союзе. Твоя сила удваивается, когда рядом тот, кому ты доверяешь.",
    "mannaz": "Манназ — руна человека и сознания. Ты наблюдатель и исследователь. Тебе важно понимать — себя, других, мир.",
    "laguz": "Лагуз — руна потока и интуиции. Ты чувствуешь то, что нельзя объяснить. Твоя сила — в доверии к внутреннему потоку.",
    "ingwaz": "Ингваз — руна завершения и потенциала. Ты умеешь закрывать циклы и накапливать силу для нового начала.",
    "dagaz": "Дагаз — руна рассвета и прорыва. Ты живёшь между «было» и «будет». Твои переходы — твои лучшие моменты.",
    "othala": "Отал — руна рода и корней. Твоя сила приходит из того, откуда ты. Понять своё происхождение — значит понять себя.",
    "wyrd": "Пустая руна — руна судьбы. Ты пришёл в этот мир без заданного сценария. Твой путь — сама неопределённость, и в этом твоя свобода.",
}


def _sum_digits(n: int) -> int:
    return sum(int(d) for d in str(n))


def calculate_birth_rune_index(birth_date: date) -> int:
    """Reduce birth date digits to 1-25 (25 = blank/wyrd)."""
    total = _sum_digits(birth_date.day) + _sum_digits(birth_date.month) + _sum_digits(birth_date.year)
    while total > 25:
        total = _sum_digits(total)
    return total  # 1-25


def get_birth_rune(birth_date: date) -> dict:
    """Return the rune dict for a birth date."""
    idx = calculate_birth_rune_index(birth_date)
    if idx == 25:
        from runes_data import BLANK_RUNE
        return BLANK_RUNE
    return RUNES[idx - 1]  # 1-indexed → 0-indexed


def get_birth_date(db_path: str, user_id: int):
    """Return stored birth date as date object, or None."""
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            row = conn.execute("SELECT birth_date FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row and row[0]:
                return date.fromisoformat(row[0])
    except Exception:
        pass
    return None


def set_birth_date(db_path: str, user_id: int, birth_date) -> None:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            if birth_date is None:
                conn.execute("UPDATE users SET birth_date = NULL WHERE user_id = ?", (user_id,))
            else:
                conn.execute("UPDATE users SET birth_date = ? WHERE user_id = ?", (birth_date.isoformat(), user_id))
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def parse_date_input(text: str):
    """Parse DD.MM.YYYY or DD/MM/YYYY or DDMMYYYY. Returns date or None."""
    text = text.strip()
    patterns = [
        r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})",
        r"(\d{2})(\d{2})(\d{4})",
    ]
    for p in patterns:
        m = re.match(p + r"$", text)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                return date(y, mo, d)
            except ValueError:
                return None
    return None


async def birth_rune_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show birth rune. If DOB not set, ask for it."""
    if not update.effective_user or not update.effective_message:
        return
    user_id = update.effective_user.id

    stored = get_birth_date(_bot.DB_PATH, user_id)
    if stored:
        await _show_birth_rune(update, context, stored)
        return

    context.user_data["state"] = STATE_WAITING_BIRTH_DATE
    await update.effective_message.reply_text(
        "🌟 <b>Твоя личная руна</b>\n\n"
        "Введи дату рождения в формате <b>ДД.ММ.ГГГГ</b>\n"
        "<i>Например: 15.03.1990</i>",
        parse_mode=ParseMode.HTML,
    )


async def handle_birth_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle birth date text input."""
    text = (update.effective_message.text or "").strip()
    birth_date = parse_date_input(text)

    if not birth_date:
        await update.effective_message.reply_text(
            "Не распознал дату. Напиши в формате <b>ДД.ММ.ГГГГ</b>, например: 15.03.1990",
            parse_mode=ParseMode.HTML,
        )
        return

    if birth_date.year < 1900 or birth_date > date.today():
        await update.effective_message.reply_text(
            "Дата выглядит неверной. Попробуй ещё раз.",
            parse_mode=ParseMode.HTML,
        )
        return

    user_id = update.effective_user.id
    set_birth_date(_bot.DB_PATH, user_id, birth_date)
    context.user_data.pop("state", None)
    await _show_birth_rune(update, context, birth_date)


async def _show_birth_rune(update: Update, context: ContextTypes.DEFAULT_TYPE, birth_date: date) -> None:
    user_id = update.effective_user.id
    rune = get_birth_rune(birth_date)
    rune_key = rune.get("key", "wyrd")
    interpretation = BIRTH_RUNE_INTERPRETATIONS.get(rune_key, "")

    # Get user's palette for image
    from database import get_user_profile
    profile = get_user_profile(_bot.DB_PATH, user_id) or {}
    palette = profile.get("palette") or "light"

    image_path = _bot.get_rune_image_path(rune, palette)

    text = (
        f"🌟 <b>Твоя руна жизни — {rune['name']}</b>\n\n"
        f"{interpretation}\n\n"
        f"<i>Дата рождения: {birth_date.strftime('%d.%m.%Y')}</i>"
    )

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Изменить дату", callback_data="birth_rune:reset")
    ]])

    if image_path:
        await update.effective_message.reply_photo(
            photo=open(image_path, "rb"),
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    else:
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )


async def birth_rune_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "birth_rune:reset":
        user_id = update.effective_user.id
        set_birth_date(_bot.DB_PATH, user_id, None)
        context.user_data["state"] = STATE_WAITING_BIRTH_DATE
        await query.message.reply_text(
            "Введи новую дату рождения в формате <b>ДД.ММ.ГГГГ</b>",
            parse_mode=ParseMode.HTML,
        )

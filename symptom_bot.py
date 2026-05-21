"""Telegram symptom-triage bot for @healthyz_bot.

Run modes:
  - Polling (local dev): set no SYMPTOM_WEBHOOK_URL
  - Webhook (Render):    set SYMPTOM_WEBHOOK_URL=https://your-app.onrender.com
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

load_dotenv()

TOKEN = os.getenv("SYMPTOM_BOT_TOKEN", "8612652867:AAFaoodd22CDIxGidaHHLOH7sZbXf6kjrb8")
ADMIN_CHAT_ID = os.getenv("SYMPTOM_ADMIN_CHAT_ID", "")
ADMIN_USERNAME = os.getenv("SYMPTOM_ADMIN_USERNAME", "@healthyz_admin")
DB_PATH = os.getenv("SYMPTOM_DB_PATH", "symptom_bot.db")
SPREADSHEET_ID = "1412ndzec1Yy8JNk-i056de5205FXWQCioHHt6Z0MLd8"
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "")
WEBHOOK_URL = os.getenv("SYMPTOM_WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", "10001"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Conversation states ──────────────────────────────────────────────────────
(
    GENDER,
    AGE,
    RED_FLAGS,
    MAIN_COMPLAINTS,
    DETAIL_BLOCK,
    SAFETY_CHECK,
    BOOKING_SERVICE,
    BOOKING_NAME,
    BOOKING_CONTACT,
    BOOKING_REQUEST,
) = range(10)

# ── Analysis data ────────────────────────────────────────────────────────────
BASE_ANALYSES = [
    "Общий анализ крови с лейкоцитарной формулой",
    "Ферритин",
    "Витамин D 25(OH)",
    "Глюкоза натощак",
    "Инсулин натощак",
    "ТТГ",
]

BLOCK_ANALYSES: Dict[str, List[str]] = {
    "gi":              ["С-реактивный белок", "АЛТ, АСТ", "ГГТ", "Копрограмма"],
    "gi_hpylori":      ["АЛТ, АСТ", "ГГТ", "H. pylori", "Копрограмма"],
    "glucose":         ["Гликированный гемоглобин HbA1c", "Липидограмма", "АЛТ, АСТ", "Общий анализ мочи"],
    "skin_hair":       ["Витамин B12", "Общий белок", "Цинк", "АЛТ, АСТ"],
    "skin_androgens":  ["Витамин B12", "Общий белок", "Цинк", "Тестостерон общий"],
    "female_hormones": ["Пролактин", "ЛГ", "ФСГ", "Эстрадиол"],
    "androgens":       ["Пролактин", "Тестостерон общий", "ГСПГ", "ДГЭА-С"],
    "stress":          ["Витамин B12", "Магний", "Гликированный гемоглобин HbA1c", "АЛТ, АСТ"],
    "immunity":        ["С-реактивный белок", "Витамин B12", "Общий белок", "Цинк"],
    "supplements":     ["АЛТ, АСТ", "ГГТ", "Креатинин", "Витамин B12"],
    "energy":          ["Витамин B12", "АЛТ, АСТ", "Креатинин", "Общий белок"],
    "sleep":           ["Витамин B12", "Магний", "Гликированный гемоглобин HbA1c", "АЛТ, АСТ"],
}

PRIORITY_ORDER = [
    "gi", "gi_hpylori",
    "glucose",
    "skin_androgens", "skin_hair",
    "androgens", "female_hormones",
    "stress",
    "immunity",
    "supplements",
    "energy",
    "sleep",
]

# ── DB ───────────────────────────────────────────────────────────────────────

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS symptom_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                tg_name TEXT,
                gender TEXT,
                age_group TEXT,
                red_flags TEXT,
                main_complaints TEXT,
                detail_symptoms TEXT,
                medications_status TEXT,
                tags TEXT,
                final_analysis_list TEXT,
                opened_methodichka INTEGER DEFAULT 0,
                opened_booking INTEGER DEFAULT 0,
                selected_service TEXT,
                user_name TEXT,
                contact TEXT,
                user_request TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)


def upsert_user(user_id: int, data: Dict[str, Any]) -> None:
    allowed = {
        "username", "tg_name", "gender", "age_group", "red_flags",
        "main_complaints", "detail_symptoms", "medications_status",
        "tags", "final_analysis_list", "opened_methodichka",
        "opened_booking", "selected_service", "user_name",
        "contact", "user_request",
    }
    fields = {k: v for k, v in data.items() if k in allowed}
    fields["updated_at"] = datetime.utcnow().isoformat()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            existing = conn.execute(
                "SELECT user_id FROM symptom_users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if existing:
                sets = ", ".join(f"{k} = ?" for k in fields)
                conn.execute(
                    f"UPDATE symptom_users SET {sets} WHERE user_id = ?",
                    list(fields.values()) + [user_id],
                )
            else:
                fields["user_id"] = user_id
                fields["created_at"] = fields["updated_at"]
                cols = ", ".join(fields.keys())
                placeholders = ", ".join("?" for _ in fields)
                conn.execute(
                    f"INSERT INTO symptom_users ({cols}) VALUES ({placeholders})",
                    list(fields.values()),
                )
    except sqlite3.Error as exc:
        logger.warning("DB error: %s", exc)


# ── Google Sheets ────────────────────────────────────────────────────────────

def _sheets_ensure_header(ws) -> None:
    """Add header row if sheet is empty."""
    try:
        if not ws.get_all_values():
            ws.append_row([
                "user_id", "username", "tg_name", "user_name", "contact",
                "selected_service", "user_request", "gender", "age_group",
                "complaints", "analyses", "datetime",
            ])
    except Exception:
        pass


def append_to_sheets(row_data: List[str]) -> None:
    if not GOOGLE_CREDS_JSON:
        return
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.sheet1
        _sheets_ensure_header(ws)
        ws.append_row(row_data, value_input_option="USER_ENTERED")
    except Exception as exc:
        logger.warning("Google Sheets error: %s", exc)


# ── Keyboard helpers ─────────────────────────────────────────────────────────

def _ms_keyboard(
    group: str,
    options: List[tuple],
    selected: Set[str],
    done_label: str = "✅ Готово",
) -> InlineKeyboardMarkup:
    rows = []
    for label, key in options:
        check = "✅ " if key in selected else ""
        rows.append([InlineKeyboardButton(f"{check}{label}", callback_data=f"ms:{group}:{key}")])
    rows.append([InlineKeyboardButton(done_label, callback_data=f"ms_done:{group}")])
    return InlineKeyboardMarkup(rows)


def _yn_keyboard(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Да", callback_data=yes_cb),
        InlineKeyboardButton("Нет", callback_data=no_cb),
    ]])


def _btn(text: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=cb)


# ── Multi-select toggle ──────────────────────────────────────────────────────

async def ms_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 2)
    group, key = parts[1], parts[2]

    ud = context.user_data
    sels: Set[str] = set(ud.get(f"sel_{group}", []))
    none_keys: List[str] = ud.get(f"none_keys_{group}", [])

    if key in none_keys:
        sels = {key}
    else:
        # Deselect any exclusive "none" keys
        for nk in none_keys:
            sels.discard(nk)
        if key in sels:
            sels.discard(key)
        else:
            sels.add(key)

    ud[f"sel_{group}"] = list(sels)
    options = ud.get(f"opts_{group}", [])
    await query.edit_message_reply_markup(reply_markup=_ms_keyboard(group, options, sels))
    # Return None to stay in current state
    return None  # type: ignore[return-value]


# ── Analysis engine ──────────────────────────────────────────────────────────

def build_analysis_list(ud: Dict[str, Any]) -> List[str]:
    tags: Set[str] = set(ud.get("tags", []))
    result = list(BASE_ANALYSES)
    seen = set(result)

    for block in PRIORITY_ORDER:
        if block not in tags:
            continue
        for a in BLOCK_ANALYSES.get(block, []):
            if a not in seen and len(result) < 10:
                result.append(a)
                seen.add(a)
        if len(result) >= 10:
            break

    return result


def determine_tags(ud: Dict[str, Any]) -> List[str]:
    tags: Set[str] = set()
    gender = ud.get("gender", "")
    complaints = set(ud.get("main_complaints", []))

    if "fatigue" in complaints:
        tags.add("energy")
        fatigue = set(ud.get("fatigue_symptoms", []))
        if "after_food" in fatigue or "craving_sweet" in fatigue:
            tags.add("glucose")

    if "sleep" in complaints:
        tags.add("sleep")

    if "weight" in complaints:
        tags.add("glucose")

    if "gi" in complaints:
        gi = set(ud.get("gi_symptoms", []))
        if {"heartburn", "belching", "heaviness"} & gi:
            tags.add("gi_hpylori")
        else:
            tags.add("gi")

    if "skin" in complaints:
        skin = set(ud.get("skin_symptoms", []))
        if gender == "female" and {"acne", "oily_skin", "premenstrual_acne"} & skin:
            tags.add("skin_androgens")
        else:
            tags.add("skin_hair")

    if "female_cycle" in complaints and gender == "female":
        cycle = set(ud.get("female_cycle_symptoms", []))
        if {"acne_cycle", "oily_skin_cycle", "facial_hair", "irregular_cycle"} & cycle:
            tags.add("androgens")
        else:
            tags.add("female_hormones")

    if "stress" in complaints:
        tags.add("stress")

    if "immunity" in complaints:
        tags.add("immunity")

    if "supplements" in complaints:
        tags.add("supplements")

    # When full androgens panel is needed, skip the skin-only androgens set
    # (androgens panel already includes Тестостерон общий, which is the overlap)
    if "androgens" in tags:
        tags.discard("skin_androgens")

    return list(tags)


def directions_text(ud: Dict[str, Any]) -> str:
    tags = set(ud.get("tags", []))
    parts = []
    if "energy" in tags or "sleep" in tags:
        parts.append("энергия и восстановление")
    if "gi" in tags or "gi_hpylori" in tags:
        parts.append("пищеварение")
    if "glucose" in tags:
        parts.append("углеводный обмен")
    if "skin_hair" in tags or "skin_androgens" in tags:
        parts.append("кожа, волосы, ногти")
    if "androgens" in tags:
        parts.append("андрогенный фон")
    if "female_hormones" in tags:
        parts.append("женский гормональный фон")
    if "stress" in tags:
        parts.append("стресс и нервная система")
    if "immunity" in tags:
        parts.append("иммунитет")
    if "supplements" in tags:
        parts.append("безопасность БАДов")
    return ", ".join(parts) if parts else "общая оценка состояния"


# ── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    user = update.effective_user
    context.user_data["tg_name"] = user.full_name
    context.user_data["username"] = user.username or ""

    text = (
        "Здравствуйте!\n\n"
        "Я помогу вам сориентироваться, какие анализы можно сдать для первичной "
        "оценки состояния организма.\n\n"
        "Бот не ставит диагноз, не назначает лечение и не заменяет врача. "
        "Он помогает собрать жалобы и подготовиться к консультации нутрициолога или врача.\n\n"
        "Ответьте на несколько вопросов — в конце вы получите короткий список анализов."
    )
    kb = InlineKeyboardMarkup([[_btn("Начать", "begin")]])
    if update.message:
        await update.message.reply_text(text, reply_markup=kb)
    else:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    return GENDER


async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([
        [_btn("Женщина", "gender:female")],
        [_btn("Мужчина", "gender:male")],
    ])
    await query.edit_message_text("Укажите ваш пол:", reply_markup=kb)
    return GENDER


# ── Gender → Age → Red flags ──────────────────────────────────────────────────

async def gender_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["gender"] = query.data.split(":")[1]
    kb = InlineKeyboardMarkup([
        [_btn("до 18",  "age:under_18")],
        [_btn("18–25",  "age:18_25")],
        [_btn("26–35",  "age:26_35")],
        [_btn("36–45",  "age:36_45")],
        [_btn("46–55",  "age:46_55")],
        [_btn("56+",    "age:56_plus")],
    ])
    await query.edit_message_text("Укажите ваш возраст:", reply_markup=kb)
    return AGE


async def age_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    age = query.data.split(":")[1]
    context.user_data["age_group"] = age

    extra = ""
    if age == "under_18":
        extra = (
            "\n\n⚠️ Для детей и подростков анализы лучше подбирать вместе с врачом и родителями. "
            "Бот может дать только ориентировочную информацию."
        )

    options = [
        ("Сильная боль в груди", "chest_pain"),
        ("Сильная одышка", "dyspnea"),
        ("Обморок или ощущение, что сейчас потеряю сознание", "faint"),
        ("Очень сильная слабость", "severe_weakness"),
        ("Сердцебиение/неровный пульс + плохое самочувствие", "arrhythmia"),
        ("Резкая сильная боль в животе", "acute_abdomen"),
        ("Рвота кровью", "hematemesis"),
        ("Кровь в стуле", "blood_stool"),
        ("Чёрный стул", "black_stool"),
        ("Сильная необычная головная боль", "severe_headache"),
        ("Спутанность сознания", "confusion"),
        ("Высокая температура + сильная боль", "fever_pain"),
        ("Резкая потеря веса без причины", "weight_loss_flag"),
        ("Беременность + боль/кровотечение", "pregnancy_bleeding"),
        ("Мысли о самоповреждении", "self_harm_flag"),
        ("Ничего из перечисленного", "none"),
    ]
    context.user_data["opts_red_flags"] = options
    context.user_data["none_keys_red_flags"] = ["none"]
    context.user_data["sel_red_flags"] = []

    kb = _ms_keyboard("red_flags", options, set())
    await query.edit_message_text(
        f"Есть ли у вас сейчас что-то из перечисленного?{extra}\n\nМожно выбрать несколько вариантов.",
        reply_markup=kb,
    )
    return RED_FLAGS


async def red_flags_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    selected = set(context.user_data.get("sel_red_flags", []))

    if not selected:
        await query.answer("Пожалуйста, выберите хотя бы один вариант.", show_alert=True)
        return RED_FLAGS

    context.user_data["red_flags"] = list(selected)

    if selected - {"none"}:
        upsert_user(update.effective_user.id, {
            "username": context.user_data.get("username"),
            "tg_name": context.user_data.get("tg_name"),
            "gender": context.user_data.get("gender"),
            "age_group": context.user_data.get("age_group"),
            "red_flags": json.dumps(list(selected), ensure_ascii=False),
        })
        await query.edit_message_text(
            "По вашим ответам есть симптомы, которые требуют очной медицинской оценки.\n\n"
            "В этой ситуации не стоит начинать с самостоятельной сдачи анализов или "
            "нутрициологического разбора. Пожалуйста, обратитесь к врачу, в неотложную "
            "помощь или вызовите скорую, если состояние острое.\n\n"
            "После исключения острых состояний можно вернуться к разбору питания, дефицитов и анализов.",
            reply_markup=InlineKeyboardMarkup([
                [_btn("🔄 Пройти заново", "restart")],
                [_btn("💬 Связаться с Мариной после врача", "contact_marina")],
            ]),
        )
        return ConversationHandler.END

    return await _show_main_complaints(query, context)


# ── Main complaints ──────────────────────────────────────────────────────────

async def _show_main_complaints(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    gender = context.user_data.get("gender", "")
    options = [
        ("Усталость / нет энергии", "fatigue"),
        ("Плохой сон", "sleep"),
        ("Вес / отёки / тяга к сладкому", "weight"),
        ("ЖКТ / пищеварение", "gi"),
        ("Кожа / волосы / ногти", "skin"),
        ("Стресс / тревожность / раздражительность", "stress"),
        ("Частые простуды / иммунитет", "immunity"),
        ("Хочу разобраться с БАДами", "supplements"),
        ("Просто хочу профилактический чек-ап", "checkup"),
        ("У меня уже есть анализы", "has_analyses"),
    ]
    if gender == "female":
        options.insert(5, ("Женский цикл / ПМС / гормоны", "female_cycle"))

    context.user_data["opts_main"] = options
    context.user_data["none_keys_main"] = []
    context.user_data["sel_main"] = []

    kb = _ms_keyboard("main", options, set())
    await query.edit_message_text(
        "Что вас беспокоит?\n\nМожно выбрать несколько вариантов.",
        reply_markup=kb,
    )
    return MAIN_COMPLAINTS


async def main_complaints_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    selected = set(context.user_data.get("sel_main", []))

    if not selected:
        await query.answer("Пожалуйста, выберите хотя бы один вариант.", show_alert=True)
        return MAIN_COMPLAINTS

    context.user_data["main_complaints"] = list(selected)

    if "has_analyses" in selected:
        await query.edit_message_text(
            "Хотите получить список для досдачи или записаться на разбор уже имеющихся анализов?",
            reply_markup=InlineKeyboardMarkup([
                [_btn("Получить список для досдачи", "has_analyses:list")],
                [_btn("Записаться на разбор", "has_analyses:booking")],
            ]),
        )
        return DETAIL_BLOCK

    if "checkup" in selected and len(selected) == 1:
        context.user_data["tags"] = []
        context.user_data["pending_blocks"] = []
        return await _show_result(query, context)

    block_order = ["fatigue", "sleep", "weight", "gi", "skin",
                   "female_cycle", "stress", "immunity", "supplements"]
    pending = [b for b in block_order if b in selected]

    if len(pending) > 4:
        pending = pending[:4]
        context.user_data["pending_blocks"] = pending
        await query.edit_message_text(
            "Вы выбрали несколько направлений. Чтобы не делать опрос слишком длинным, "
            "уточним только основные симптомы.",
            reply_markup=InlineKeyboardMarkup([[_btn("Продолжить", "detail_continue")]]),
        )
        return DETAIL_BLOCK

    context.user_data["pending_blocks"] = pending
    return await _next_detail_block(query, context)


# ── Detail block configs ─────────────────────────────────────────────────────

DETAIL_CONFIGS: Dict[str, Any] = {
    "fatigue": {
        "text": "Что именно вы ощущаете?\n\nМожно выбрать несколько вариантов.",
        "var": "fatigue_symptoms",
        "options": [
            ("Просыпаюсь уже уставшим/уставшей", "wake_tired"),
            ("Нет сил днём", "no_energy_day"),
            ("Хочется кофе/сладкого для энергии", "craving_sweet"),
            ("Сложно концентрироваться", "poor_concentration"),
            ("Слабость после еды", "after_food"),
            ("Кружится голова", "dizziness"),
            ("Мёрзнут руки/ноги", "cold_extremities"),
            ("Быстро устаю от обычных дел", "quick_fatigue"),
        ],
    },
    "sleep": {
        "text": "Что именно происходит со сном?\n\nМожно выбрать несколько вариантов.",
        "var": "sleep_symptoms",
        "options": [
            ("Долго засыпаю", "hard_falling_asleep"),
            ("Часто просыпаюсь ночью", "night_waking"),
            ("Просыпаюсь в 3–5 утра", "early_waking"),
            ("Сон поверхностный", "light_sleep"),
            ("Утром нет бодрости", "no_morning_vigor"),
            ("Сильная сонливость днём", "daytime_sleepiness"),
            ("Ночная потливость", "night_sweats"),
            ("Хочется есть ночью", "night_hunger"),
        ],
    },
    "weight": {
        "text": "Что ближе к вашей ситуации?\n\nМожно выбрать несколько вариантов.",
        "var": "weight_symptoms",
        "options": [
            ("Вес растёт", "weight_gain"),
            ("Вес не снижается", "no_weight_loss"),
            ("Тянет на сладкое", "craving_sugar"),
            ("Хочется есть каждые 1–2 часа", "frequent_hunger"),
            ("Сонливость после еды", "postprandial_sleepiness"),
            ("Приступы переедания", "binge"),
            ("Отёки утром", "edema_morning"),
            ("Отёки вечером", "edema_evening"),
            ("Дрожь/слабость, если долго не ем", "hypoglycemia_sx"),
            ("Растёт объём талии", "waist_growth"),
        ],
    },
    "gi": {
        "text": "Что беспокоит со стороны пищеварения?\n\nМожно выбрать несколько вариантов.",
        "var": "gi_symptoms",
        "options": [
            ("Вздутие", "bloating"),
            ("Тяжесть после еды", "heaviness"),
            ("Изжога", "heartburn"),
            ("Отрыжка", "belching"),
            ("Тошнота", "nausea"),
            ("Боли в животе", "abdominal_pain"),
            ("Запор", "constipation"),
            ("Диарея", "diarrhea"),
            ("Чередование запора и диареи", "alternating"),
            ("Горечь во рту", "bitter_mouth"),
            ("Непереносимость жирной пищи", "fat_intolerance"),
            ("Урчание", "gurgling"),
            ("Слизь в стуле", "mucus_stool"),
        ],
        "safety_check": "gi",
    },
    "skin": {
        "text": "Что именно беспокоит?\n\nМожно выбрать несколько вариантов.",
        "var": "skin_symptoms",
        "options": [
            ("Выпадение волос", "hair_loss"),
            ("Ломкие волосы", "brittle_hair"),
            ("Ломкие ногти", "brittle_nails"),
            ("Сухая кожа", "dry_skin"),
            ("Акне", "acne"),
            ("Жирная кожа", "oily_skin"),
            ("Высыпания перед месячными", "premenstrual_acne"),
            ("Трещины в уголках губ", "cheilitis"),
            ("Бледность", "pallor"),
            ("Зуд кожи", "itching"),
            ("Медленно заживают ранки", "slow_healing"),
        ],
    },
    "female_cycle": {
        "text": "Что беспокоит по циклу или гормональным проявлениям?\n\nМожно выбрать несколько вариантов.",
        "var": "female_cycle_symptoms",
        "options": [
            ("Нерегулярный цикл", "irregular_cycle"),
            ("Болезненные месячные", "painful_periods"),
            ("Обильные месячные", "heavy_periods"),
            ("Скудные месячные", "light_periods"),
            ("Выраженный ПМС", "pms"),
            ("Отёки перед месячными", "premenstrual_edema"),
            ("Раздражительность перед месячными", "premenstrual_irritability"),
            ("Тяга к сладкому перед месячными", "premenstrual_craving"),
            ("Акне перед месячными", "acne_cycle"),
            ("Выпадение волос", "hair_loss_cycle"),
            ("Снижение либидо", "low_libido"),
            ("Приливы", "hot_flashes"),
            ("Ночная потливость", "night_sweats_cycle"),
            ("Планирование беременности", "pregnancy_planning"),
        ],
        "cycle_question": True,
    },
    "stress": {
        "text": "Что именно вы замечаете?\n\nМожно выбрать несколько вариантов.",
        "var": "stress_symptoms",
        "options": [
            ("Тревожность", "anxiety"),
            ("Раздражительность", "irritability"),
            ("Эмоциональные качели", "mood_swings"),
            ("Плаксивость", "tearfulness"),
            ("Напряжение в теле", "body_tension"),
            ("Панические ощущения", "panic"),
            ("Плохой сон", "poor_sleep"),
            ("Сильная реакция на стресс", "stress_reaction"),
            ("Тяга к сладкому на фоне стресса", "stress_craving"),
            ("Нет сил после работы/общения", "exhaustion"),
        ],
        "safety_check": "stress",
    },
    "immunity": {
        "text": "Что именно вас беспокоит?\n\nМожно выбрать несколько вариантов.",
        "var": "immunity_symptoms",
        "options": [
            ("Часто болею", "frequent_illness"),
            ("Долго восстанавливаюсь", "slow_recovery"),
            ("Герпес", "herpes"),
            ("Частые воспаления", "frequent_inflammation"),
            ("Долго заживают ранки", "slow_healing_immunity"),
            ("Увеличенные лимфоузлы", "lymph_nodes"),
            ("Температура держится без причины", "unexplained_fever"),
            ("Слабость после болезни", "post_illness_weakness"),
        ],
        "warning_keys": {"lymph_nodes", "unexplained_fever"},
    },
    "supplements": {
        "text": "Что ближе к вашей ситуации?\n\nМожно выбрать несколько вариантов.",
        "var": "supplements_symptoms",
        "options": [
            ("Принимаю много БАДов", "many_supplements"),
            ("Не знаю, что оставить", "dont_know_what"),
            ("Есть побочные реакции", "side_effects"),
            ("Принимаю без анализов", "without_tests"),
            ("Хочу проверить совместимость", "compatibility"),
            ("Принимаю лекарства и БАДы одновременно", "meds_and_supplements"),
            ("Хочу подобрать добавки", "want_supplements"),
            ("Боюсь навредить", "fear_harm"),
        ],
        "medications_question": True,
    },
}


async def _next_detail_block(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    pending: List[str] = context.user_data.get("pending_blocks", [])
    if not pending:
        context.user_data["tags"] = determine_tags(context.user_data)
        return await _show_result(query, context)

    block = pending[0]
    context.user_data["current_block"] = block
    cfg = DETAIL_CONFIGS[block]
    group = f"detail_{block}"

    context.user_data[f"opts_{group}"] = cfg["options"]
    context.user_data[f"none_keys_{group}"] = []
    context.user_data[f"sel_{group}"] = []

    kb = _ms_keyboard(group, cfg["options"], set())
    await query.edit_message_text(cfg["text"], reply_markup=kb)
    return DETAIL_BLOCK


async def detail_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    # Extract block name from "ms_done:detail_<block>"
    raw_group = query.data.split(":", 1)[1]          # "detail_fatigue"
    block = raw_group[len("detail_"):]                # "fatigue"
    cfg = DETAIL_CONFIGS.get(block, {})
    group = f"detail_{block}"

    selected = set(context.user_data.get(f"sel_{group}", []))
    context.user_data[cfg.get("var", f"{block}_symptoms")] = list(selected)

    # ── Immunity warning (pop block FIRST, then show warning) ────────────────
    warning_keys: Set[str] = cfg.get("warning_keys", set())
    if warning_keys & selected:
        # FIX: pop the block before showing warning so detail_continue skips it
        context.user_data["pending_blocks"] = context.user_data.get("pending_blocks", [])[1:]
        context.user_data["immunity_doctor_note"] = True
        await query.edit_message_text(
            "Эти симптомы лучше обсудить с врачом очно. "
            "Бот может дать только общий список для подготовки, но не заменяет медицинскую оценку.",
            reply_markup=InlineKeyboardMarkup([[_btn("Продолжить", "detail_continue")]]),
        )
        return DETAIL_BLOCK

    # ── GI safety check ───────────────────────────────────────────────────────
    if cfg.get("safety_check") == "gi":
        await query.edit_message_text(
            "Есть ли у вас сейчас кровь в стуле, чёрный стул, рвота кровью, "
            "резкая сильная боль в животе или необъяснимая потеря веса?",
            reply_markup=_yn_keyboard("gi_safety:yes", "gi_safety:no"),
        )
        return SAFETY_CHECK

    # ── Stress safety check ───────────────────────────────────────────────────
    if cfg.get("safety_check") == "stress":
        await query.edit_message_text(
            "Есть ли у вас мысли о самоповреждении?",
            reply_markup=_yn_keyboard("stress_safety:yes", "stress_safety:no"),
        )
        return SAFETY_CHECK

    # ── Female cycle — ask cycle status ───────────────────────────────────────
    if cfg.get("cycle_question"):
        await query.edit_message_text(
            "Цикл регулярный?",
            reply_markup=InlineKeyboardMarkup([
                [_btn("Да", "cycle:regular")],
                [_btn("Нет", "cycle:irregular")],
                [_btn("Не знаю", "cycle:unknown")],
                [_btn("Сейчас нет менструации", "cycle:no_menstruation")],
                [_btn("Беременность / ГВ", "cycle:pregnancy")],
            ]),
        )
        return DETAIL_BLOCK

    # ── Supplements — ask medications ─────────────────────────────────────────
    if cfg.get("medications_question"):
        await query.edit_message_text(
            "Принимаете ли вы сейчас лекарства?",
            reply_markup=InlineKeyboardMarkup([
                [_btn("Да",             "meds:yes")],
                [_btn("Нет",           "meds:no")],
                [_btn("Иногда",        "meds:sometimes")],
                [_btn("Не хочу отвечать", "meds:skip")],
            ]),
        )
        return DETAIL_BLOCK

    # ── No special follow-up: pop and continue ────────────────────────────────
    context.user_data["pending_blocks"] = context.user_data.get("pending_blocks", [])[1:]
    return await _next_detail_block(query, context)


# ── Safety check ─────────────────────────────────────────────────────────────

async def safety_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action, answer = query.data.split(":")

    if action == "gi_safety":
        if answer == "yes":
            await query.edit_message_text(
                "По вашим ответам есть симптомы, которые требуют очной медицинской оценки. "
                "Пожалуйста, обратитесь к врачу.",
                reply_markup=InlineKeyboardMarkup([
                    [_btn("🔄 Пройти заново", "restart")],
                    [_btn("💬 Связаться с Мариной после врача", "contact_marina")],
                ]),
            )
            return ConversationHandler.END
        context.user_data["pending_blocks"] = context.user_data.get("pending_blocks", [])[1:]
        return await _next_detail_block(query, context)

    if action == "stress_safety":
        if answer == "yes":
            await query.edit_message_text(
                "В такой ситуации важно не оставаться одному/одной. "
                "Обратитесь за срочной помощью к врачу, в кризисную службу "
                "или к близкому человеку рядом. Бот не подходит для таких состояний.",
                reply_markup=InlineKeyboardMarkup([[_btn("🔄 Пройти заново", "restart")]]),
            )
            return ConversationHandler.END
        context.user_data["pending_blocks"] = context.user_data.get("pending_blocks", [])[1:]
        return await _next_detail_block(query, context)

    return SAFETY_CHECK


# ── Detail sub-callbacks (non-toggle) ────────────────────────────────────────

async def detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "detail_continue":
        pending = context.user_data.get("pending_blocks", [])
        if pending:
            return await _next_detail_block(query, context)
        context.user_data["tags"] = determine_tags(context.user_data)
        return await _show_result(query, context)

    if data.startswith("has_analyses:"):
        if data.endswith(":booking"):
            return await _show_booking_menu(query, context)
        # :list → base analyses only
        context.user_data["tags"] = []
        context.user_data["pending_blocks"] = []
        return await _show_result(query, context)

    if data.startswith("meds:"):
        status = data.split(":")[1]
        context.user_data["medications_status"] = status
        if status in ("yes", "sometimes"):
            await query.edit_message_text(
                "Совместимость БАДов с лекарствами нужно проверять отдельно. "
                "Не отменяйте и не меняйте лекарства самостоятельно.",
                reply_markup=InlineKeyboardMarkup([[_btn("Продолжить", "meds_continue")]]),
            )
            return DETAIL_BLOCK
        context.user_data["pending_blocks"] = context.user_data.get("pending_blocks", [])[1:]
        return await _next_detail_block(query, context)

    if data == "meds_continue":
        context.user_data["pending_blocks"] = context.user_data.get("pending_blocks", [])[1:]
        return await _next_detail_block(query, context)

    if data.startswith("cycle:"):
        status = data.split(":")[1]
        context.user_data["cycle_status"] = status
        if status == "pregnancy":
            await query.edit_message_text(
                "В период беременности и грудного вскармливания анализы, питание и добавки "
                "лучше согласовывать с врачом. Бот может дать только общую ориентировочную информацию.",
                reply_markup=InlineKeyboardMarkup([[_btn("Продолжить", "cycle_continue")]]),
            )
            return DETAIL_BLOCK
        context.user_data["pending_blocks"] = context.user_data.get("pending_blocks", [])[1:]
        return await _next_detail_block(query, context)

    if data == "cycle_continue":
        context.user_data["pending_blocks"] = context.user_data.get("pending_blocks", [])[1:]
        return await _next_detail_block(query, context)

    return DETAIL_BLOCK


# ── Result ───────────────────────────────────────────────────────────────────

async def _show_result(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    tags = context.user_data.get("tags") or determine_tags(context.user_data)
    context.user_data["tags"] = tags

    final_list = build_analysis_list(context.user_data)
    context.user_data["final_analysis_list"] = final_list

    main_complaints = context.user_data.get("main_complaints", [])
    relevant = [c for c in main_complaints if c not in ("checkup", "has_analyses")]

    age_note = ""
    if context.user_data.get("age_group") == "under_18":
        age_note = "\n\n⚠️ Так как возраст до 18 лет, итоговый список лучше согласовать с врачом."

    immunity_note = ""
    if context.user_data.get("immunity_doctor_note"):
        immunity_note = "\n\n⚠️ По ряду симптомов иммунитета рекомендована очная консультация врача."

    many_note = ""
    if len(relevant) >= 3:
        many_note = (
            "\n\nВы отметили несколько групп симптомов. Чтобы не сдавать лишнее, "
            "бот сформировал стартовый список до 10 анализов. "
            "Расширенный список лучше подбирать индивидуально после анкеты или консультации."
        )

    directions = directions_text(context.user_data)
    numbered = "\n".join(f"{i}. {a}" for i, a in enumerate(final_list, 1))

    text = (
        f"По вашим ответам основные направления:\n{directions}.\n\n"
        f"Чтобы список был доступным и без лишних назначений, начните с этих анализов."
        f"{many_note}\n\n"
        f"<b>Ваш список анализов:</b>\n{numbered}\n\n"
        "После получения результатов вы сможете сравнить показатели с методичкой "
        "или обратиться за персональным разбором.\n\n"
        "Анализы важно смотреть вместе с симптомами, питанием, сном, стрессом, "
        f"циклом, лекарствами и добавками.{age_note}{immunity_note}\n\n"
        "<i>Важно: список анализов носит информационный характер и не является "
        "диагнозом или назначением лечения.</i>"
    )

    kb = InlineKeyboardMarkup([
        [_btn("📖 Открыть методичку",    "methodichka")],
        [_btn("📋 Записаться на разбор", "booking")],
        [_btn("🔄 Пройти заново",        "restart")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    upsert_user(query.from_user.id, {
        "username": context.user_data.get("username"),
        "tg_name": context.user_data.get("tg_name"),
        "gender": context.user_data.get("gender"),
        "age_group": context.user_data.get("age_group"),
        "red_flags": json.dumps(context.user_data.get("red_flags", []), ensure_ascii=False),
        "main_complaints": json.dumps(main_complaints, ensure_ascii=False),
        "detail_symptoms": json.dumps({
            k: context.user_data.get(k) for k in [
                "fatigue_symptoms", "sleep_symptoms", "weight_symptoms",
                "gi_symptoms", "skin_symptoms", "female_cycle_symptoms",
                "stress_symptoms", "immunity_symptoms", "supplements_symptoms",
            ]
        }, ensure_ascii=False),
        "tags": json.dumps(tags, ensure_ascii=False),
        "final_analysis_list": json.dumps(final_list, ensure_ascii=False),
    })

    return ConversationHandler.END


# ── Booking ───────────────────────────────────────────────────────────────────

BOOKING_TEXT = (
    "Анализы сами по себе не дают готового плана. "
    "Важно смотреть их вместе с симптомами, питанием, сном, стрессом, "
    "циклом, лекарствами и добавками.\n\n"
    "Если хотите получить персональный разбор, выберите формат:"
)

BOOKING_KB = InlineKeyboardMarkup([
    [_btn("⚡ Экспресс-навигация — 3 500 ₽",              "service:express")],
    [_btn("📊 Полный разбор «Анализы + питание» — 7 500 ₽", "service:full")],
    [_btn("🔄 Ведение 1 месяц «Перезапуск» — 19 000 ₽",    "service:monthly")],
    [_btn("💬 Задать вопрос Марине",                         "service:question")],
])

SERVICE_DESC = {
    "service:express": (
        "<b>Экспресс-навигация — 3 500 ₽</b>\n\n"
        "Подходит, если вы не понимаете, с чего начать.\n\n"
        "Входит:\n— анкета\n— консультация 60 минут\n— базовые рекомендации\n"
        "— список анализов\n— короткое резюме."
    ),
    "service:full": (
        "<b>Полный разбор «Анализы + питание» — 7 500 ₽</b>\n\n"
        "Подходит, если есть жалобы, анализы или желание получить понятный план.\n\n"
        "Входит:\n— подробная анкета\n— разбор питания\n— интерпретация анализов\n"
        "— рекомендации по питанию\n— базовые рекомендации по добавкам\n"
        "— письменный план на 4–6 недель\n— 5 дней поддержки после консультации."
    ),
    "service:monthly": (
        "<b>Ведение 1 месяц «Перезапуск» — 19 000 ₽</b>\n\n"
        "Подходит, если нужна не только консультация, но и поддержка при внедрении рекомендаций.\n\n"
        "Входит:\n— стартовая консультация\n— разбор анализов\n— план питания\n"
        "— нутрицевтический протокол\n— еженедельная корректировка\n"
        "— чат-поддержка\n— финальная мини-встреча."
    ),
    "service:question": "Отлично! Напишите ваш вопрос Марине.",
}

SERVICE_NAMES = {
    "service:express":  "Экспресс-навигация (3 500 ₽)",
    "service:full":     "Полный разбор «Анализы + питание» (7 500 ₽)",
    "service:monthly":  "Ведение 1 месяц «Перезапуск» (19 000 ₽)",
    "service:question": "Вопрос Марине",
}


async def _show_booking_menu(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    upsert_user(query.from_user.id, {"opened_booking": 1})
    await query.edit_message_text(BOOKING_TEXT, reply_markup=BOOKING_KB)
    return BOOKING_SERVICE


async def booking_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for booking_conv (called after conversation ends)."""
    query = update.callback_query
    await query.answer()
    upsert_user(query.from_user.id, {"opened_booking": 1})
    await query.message.reply_text(BOOKING_TEXT, reply_markup=BOOKING_KB)
    return BOOKING_SERVICE


async def service_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["selected_service"] = SERVICE_NAMES.get(query.data, query.data)
    desc = SERVICE_DESC.get(query.data, "")
    await query.edit_message_text(desc + "\n\nКак вас зовут?", parse_mode="HTML")
    return BOOKING_NAME


async def booking_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["user_name"] = update.message.text.strip()
    await update.message.reply_text("Укажите ваш телефон или удобный способ связи.")
    return BOOKING_CONTACT


async def booking_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["contact"] = update.message.text.strip()
    await update.message.reply_text("Коротко напишите, с каким запросом хотите обратиться.")
    return BOOKING_REQUEST


async def booking_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["user_request"] = update.message.text.strip()
    ud = context.user_data
    user_id = update.effective_user.id

    await update.message.reply_text(
        "Спасибо! Заявка отправлена.\n\nМарина свяжется с вами и подскажет дальнейшие шаги.",
        reply_markup=InlineKeyboardMarkup([[_btn("🔄 Пройти заново", "restart")]]),
    )

    upsert_user(user_id, {
        "selected_service": ud.get("selected_service"),
        "user_name": ud.get("user_name"),
        "contact": ud.get("contact"),
        "user_request": ud.get("user_request"),
        "opened_booking": 1,
    })

    analyses: List[str] = ud.get("final_analysis_list") or []
    analyses_str = "\n".join(f"• {a}" for a in analyses) if analyses else "—"
    complaints_str = ", ".join(ud.get("main_complaints") or []) or "—"

    admin_text = (
        "🔔 <b>Новая заявка из бота</b>\n\n"
        f"Имя: {ud.get('user_name', '—')}\n"
        f"Контакт: {ud.get('contact', '—')}\n"
        f"Формат: {ud.get('selected_service', '—')}\n"
        f"Запрос: {ud.get('user_request', '—')}\n"
        f"Жалобы: {complaints_str}\n\n"
        f"Список анализов:\n{analyses_str}"
    )

    if ADMIN_CHAT_ID:
        try:
            await update.get_bot().send_message(
                chat_id=int(ADMIN_CHAT_ID), text=admin_text, parse_mode="HTML"
            )
        except Exception as exc:
            logger.warning("Admin notify failed: %s", exc)

    append_to_sheets([
        str(user_id),
        ud.get("username", ""),
        ud.get("tg_name", ""),
        ud.get("user_name", ""),
        ud.get("contact", ""),
        ud.get("selected_service", ""),
        ud.get("user_request", ""),
        ud.get("gender", ""),
        ud.get("age_group", ""),
        complaints_str,
        "; ".join(analyses),
        datetime.utcnow().isoformat(),
    ])

    return ConversationHandler.END


# ── Post-conversation callbacks ───────────────────────────────────────────────

METHODICHKA_TEXT = (
    "В методичке вы сможете посмотреть, что означает каждый показатель "
    "и на что обратить внимание при подготовке к разбору.\n\n"
    "<b>Важно:</b> методичка не заменяет консультацию врача или нутрициолога. "
    "Не начинайте приём добавок только по одному показателю без учёта симптомов, "
    "питания, лекарств и противопоказаний. "
    "Если показатель выходит за пределы референсов — обсудите результат со специалистом.\n\n"
    "<b>Краткая методичка:</b>\n\n"
    "<b>ОАК с формулой</b> — общее состояние крови, признаки воспаления и анемии.\n"
    "<b>Ферритин</b> — запасы железа; низкий = усталость, выпадение волос.\n"
    "<b>Витамин D 25(OH)</b> — иммунитет, кости, настроение.\n"
    "<b>Глюкоза натощак</b> — углеводный обмен.\n"
    "<b>Инсулин натощак</b> — чувствительность к инсулину.\n"
    "<b>ТТГ</b> — щитовидная железа; вес, энергия, настроение.\n"
    "<b>Витамин B12</b> — нервная система, энергия, кроветворение.\n"
    "<b>HbA1c</b> — средний уровень глюкозы за 2–3 месяца.\n"
    "<b>АЛТ, АСТ</b> — состояние печени и мышц.\n"
    "<b>ГГТ</b> — желчевыводящие пути, печень.\n"
    "<b>Креатинин</b> — работа почек.\n"
    "<b>Общий белок</b> — достаточность белка в питании.\n"
    "<b>Цинк</b> — иммунитет, кожа, волосы, ногти.\n"
    "<b>Магний</b> — нервная система, сон, мышцы.\n"
    "<b>Липидограмма</b> — холестерин, триглицериды.\n"
    "<b>Общий анализ мочи</b> — почки, воспаление.\n"
    "<b>Копрограмма</b> — пищеварение, ферменты.\n"
    "<b>С-реактивный белок</b> — системное воспаление.\n"
    "<b>Пролактин</b> — цикл, либидо.\n"
    "<b>ЛГ / ФСГ</b> — регуляция цикла.\n"
    "<b>Эстрадиол</b> — основной женский гормон.\n"
    "<b>Тестостерон общий</b> — андрогенный фон, акне.\n"
    "<b>ГСПГ</b> — транспортный белок половых гормонов.\n"
    "<b>ДГЭА-С</b> — надпочечниковый андроген.\n"
    "<b>H. pylori</b> — связан с гастритом и язвой желудка."
)


async def methodichka_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    upsert_user(query.from_user.id, {"opened_methodichka": 1})
    await query.message.reply_text(METHODICHKA_TEXT, parse_mode="HTML")


async def prices_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    text = (
        "<b>Услуги и цены</b>\n\n"
        "<b>⚡ Экспресс-навигация — 3 500 ₽</b>\n"
        "Консультация 60 мин + базовые рекомендации + список анализов.\n\n"
        "<b>📊 Полный разбор «Анализы + питание» — 7 500 ₽</b>\n"
        "Разбор питания + анализов + план на 4–6 недель + 5 дней поддержки.\n\n"
        "<b>🔄 Ведение 1 месяц «Перезапуск» — 19 000 ₽</b>\n"
        "Консультация + план питания + протокол + еженедельная корректировка + чат."
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[_btn("📋 Записаться", "booking")]]),
        parse_mode="HTML",
    )


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kb = InlineKeyboardMarkup([
        [_btn("🔍 Пройти опрос",          "begin")],
        [_btn("📖 Открыть методичку",     "methodichka")],
        [_btn("💼 Услуги и цены",         "prices")],
        [_btn("📋 Записаться к Марине",   "booking")],
        [_btn("🔄 Пройти заново",         "restart")],
    ])
    if update.message:
        await update.message.reply_text("Главное меню:", reply_markup=kb)
    elif update.callback_query:
        await update.callback_query.edit_message_text("Главное меню:", reply_markup=kb)


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_menu(update, context)


async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await start(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Доступные команды:\n"
        "/start — начать опрос\n"
        "/menu — главное меню\n"
        "/restart — пройти заново\n"
        "/price — услуги и цены\n"
        "/contact — связаться с Мариной\n"
        "/help — помощь\n\n"
        "Бот не ставит диагноз и не назначает лечение."
    )


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "⚡ Экспресс-навигация — 3 500 ₽\n"
        "📊 Полный разбор «Анализы + питание» — 7 500 ₽\n"
        "🔄 Ведение 1 месяц «Перезапуск» — 19 000 ₽\n\n"
        "Нажмите /start чтобы пройти опрос и записаться."
    )


async def cmd_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Написать Марине напрямую: {ADMIN_USERNAME}"
    )


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Пожалуйста, выберите один из вариантов ниже.",
        reply_markup=InlineKeyboardMarkup([[_btn("🔄 Пройти заново", "restart")]]),
    )


# ── Conversation handlers ─────────────────────────────────────────────────────

# Booking conversation — entry from post-result "Записаться" button
booking_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(booking_entry, pattern="^booking$")],
    states={
        BOOKING_SERVICE: [CallbackQueryHandler(service_chosen, pattern="^service:")],
        BOOKING_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, booking_name)],
        BOOKING_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, booking_contact)],
        BOOKING_REQUEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, booking_request)],
    },
    fallbacks=[
        CommandHandler("start", start),
        CommandHandler("restart", cmd_restart),
    ],
    per_message=False,
    allow_reentry=True,
)

# Main survey conversation
main_conv = ConversationHandler(
    entry_points=[
        CommandHandler("start", start),
        CommandHandler("restart", cmd_restart),
        CallbackQueryHandler(start, pattern="^restart$"),
        CallbackQueryHandler(begin, pattern="^begin$"),
    ],
    states={
        GENDER: [
            CallbackQueryHandler(begin, pattern="^begin$"),
            CallbackQueryHandler(gender_chosen, pattern="^gender:"),
        ],
        AGE: [
            CallbackQueryHandler(age_chosen, pattern="^age:"),
        ],
        RED_FLAGS: [
            CallbackQueryHandler(ms_toggle,      pattern="^ms:red_flags:"),
            CallbackQueryHandler(red_flags_done, pattern="^ms_done:red_flags$"),
        ],
        MAIN_COMPLAINTS: [
            CallbackQueryHandler(ms_toggle,            pattern="^ms:main:"),
            CallbackQueryHandler(main_complaints_done, pattern="^ms_done:main$"),
        ],
        DETAIL_BLOCK: [
            CallbackQueryHandler(ms_toggle,     pattern=r"^ms:detail_"),
            CallbackQueryHandler(detail_done,   pattern=r"^ms_done:detail_"),
            CallbackQueryHandler(detail_callback,
                pattern=r"^(detail_continue|has_analyses:|meds:|meds_continue|cycle:|cycle_continue)"),
        ],
        SAFETY_CHECK: [
            CallbackQueryHandler(safety_answer, pattern="^(gi_safety|stress_safety):"),
        ],
        # Booking from within conversation (has_analyses:booking path)
        BOOKING_SERVICE: [CallbackQueryHandler(service_chosen, pattern="^service:")],
        BOOKING_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, booking_name)],
        BOOKING_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, booking_contact)],
        BOOKING_REQUEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, booking_request)],
    },
    fallbacks=[
        CommandHandler("start", start),
        CommandHandler("restart", cmd_restart),
        MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message),
    ],
    per_message=False,
    allow_reentry=True,
)


# ── App setup ────────────────────────────────────────────────────────────────

def build_app() -> Application:
    init_db()
    app = Application.builder().token(TOKEN).build()

    # Main survey (must be first)
    app.add_handler(main_conv)
    # Standalone booking after survey ends
    app.add_handler(booking_conv)

    # Stateless callbacks
    app.add_handler(CallbackQueryHandler(methodichka_callback, pattern="^methodichka$"))
    app.add_handler(CallbackQueryHandler(prices_callback,      pattern="^prices$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: (u.callback_query.answer(), u.callback_query.message.reply_text(
            f"Напишите Марине: {ADMIN_USERNAME}\n\n"
            "Лучше кратко указать, что вы уже обратились к врачу."
        )),
        pattern="^contact_marina$",
    ))

    app.add_handler(CommandHandler("menu",    cmd_menu))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("price",   cmd_price))
    app.add_handler(CommandHandler("contact", cmd_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    return app


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app = build_app()

    if WEBHOOK_URL:
        # ── Webhook mode (Render) ─────────────────────────────────────────────
        webhook_path = f"/webhook/{TOKEN}"
        full_url = f"{WEBHOOK_URL.rstrip('/')}{webhook_path}"
        logger.info("Starting in webhook mode: %s on port %d", full_url, PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=webhook_path,
            webhook_url=full_url,
        )
    else:
        # ── Polling mode (local dev) ──────────────────────────────────────────
        logger.info("Starting in polling mode")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

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
    "love": ["вместе", "отнош", "люб", "чувств", "партнер", "партнёр", "бывш", "верн", "брак", "семь", "пара", "нрав", "скуч", "измен"],
    "work": ["работ", "карьер", "проект", "началь", "коллег", "бизнес", "клиент", "дело", "должн", "собесед", "контракт"],
    "money": ["деньг", "финанс", "доход", "зарплат", "куп", "прод", "долг", "цена", "оплат", "расход", "прибыль", "банк"],
    "choice": ["стоит", "выбор", "выбрать", "или", "решить", "соглас", "отказ", "уйти", "остаться", "как поступ", "надо ли"],
    "conflict": ["ссор", "конфликт", "обид", "давит", "манипул", "разговор", "претенз", "напряж", "руга", "спор"],
    "future": ["будет", "получится", "ждет", "ждёт", "перспектив", "исход", "результат", "сложится", "завтра", "вечер"],
}
TOPIC_NAMES = {"love": "отношения", "work": "работа", "money": "деньги", "choice": "выбор", "conflict": "конфликт", "future": "будущее", "general": "ситуация"}
RUNE_THEME_HINTS = {
    "fehu": {
        "love": "Есть интерес, но проверь взаимность: ты не должен один вкладываться больше, чем получаешь.",
        "work": "Ресурс есть, но его надо считать. Не соглашайся на задачу без понятной выгоды или роли.",
        "money": "Деньги могут прийти через практичный шаг. Важно не распылять ресурс и не платить за эмоцию.",
        "choice": "Выбирай вариант, где есть реальная отдача, а не только красивое обещание.",
        "future": "Перспектива есть, если ты сохраняешь ресурс и не тратишь всё сразу.",
        "general": "Главный смысл — обмен: что ты получаешь, что отдаёшь и не нарушен ли баланс.",
    },
    "uruz": {
        "love": "Притяжение может быть сильным, но не путай силу с давлением. Нужна зрелость, а не борьба.",
        "work": "Сил хватит, если не брать всё на себя. Иди через один мощный шаг, а не через перегруз.",
        "money": "Решение требует контроля. Не трать на импульсе, сначала оцени запас сил и денег.",
        "choice": "Выбирай там, где чувствуешь опору, а не там, где приходится доказывать силу.",
        "conflict": "Не дави в ответ. Сила сейчас в собранности и спокойной позиции.",
        "general": "Ситуация требует силы, но сила должна быть управляемой.",
    },
    "thurisaz": {
        "love": "В отношениях сейчас важна граница. Если что-то ранит, не прячь это ради красивой картинки.",
        "work": "Не входи в борьбу без необходимости. Сначала пойми, где реальная угроза, а где эмоция.",
        "money": "Не рискуй из раздражения. Любое резкое решение может стоить дороже, чем кажется.",
        "conflict": "Это знак напряжения. Лучше остановить удар, чем потом чинить последствия.",
        "choice": "Не выбирай из злости. Дай ситуации остыть и только потом действуй.",
        "general": "Сначала защита и границы, потом действие.",
    },
    "ansuz": {
        "love": "Разговор покажет больше, чем догадки. Важно услышать не только слова, но и готовность говорить честно.",
        "work": "Решает формулировка. Чем точнее ты обозначишь задачу, тем меньше будет хаоса.",
        "money": "Проверь договорённости: сумма, сроки, условия. Устные обещания лучше уточнить.",
        "choice": "Ответ появится через разговор или ясный вопрос. Не додумывай за других.",
        "conflict": "Не повышай тон. Назови факт коротко — это сработает сильнее давления.",
        "general": "Нужно назвать вопрос прямо и убрать недосказанность.",
    },
    "raido": {
        "love": "Важно, движетесь ли вы в одну сторону. Если планы расходятся, чувства не всё удержат.",
        "work": "Поможет маршрут: кто делает, что делает и в какой срок. Без плана будет суета.",
        "money": "Деньги требуют плана движения. Не начинай трату или сделку без маршрута.",
        "choice": "Выбирай путь, где следующий шаг понятен. Если маршрута нет, решение ещё сырое.",
        "future": "События сдвинутся, если появится порядок и направление.",
        "general": "Курс важнее скорости. Сначала направление, потом движение.",
    },
    "kenaz": {
        "love": "Проясни мотив: что человек реально показывает, а что ты хочешь увидеть сам.",
        "work": "Решение видно, когда убираешь туман. Спроси прямо, что считается результатом.",
        "money": "Нужна прозрачность условий. Не соглашайся, пока не понятны цифры и обязательства.",
        "choice": "Выбирай после прояснения, а не на догадках. Сейчас свет нужен сильнее скорости.",
        "conflict": "Факт прояснит спор лучше, чем эмоции. Достань скрытую деталь наружу.",
        "general": "Карта просит ясности: увидеть, назвать, проверить.",
    },
    "gebo": {
        "love": "Главное — взаимность. Если один даёт, а второй только принимает, ответ будет слабым.",
        "work": "Смотри на договор и обмен. Участие должно быть равным или хотя бы честно оговорённым.",
        "money": "Важен баланс оплаты и пользы. Не соглашайся на обмен, где твоя часть обесценена.",
        "choice": "Выбирай там, где есть честное партнёрство, а не скрытая обязанность.",
        "future": "Перспектива держится на равном обмене. Без него всё начнёт проседать.",
        "general": "Обмен должен быть равным. Проверь, не платишь ли ты больше своей части.",
    },
    "wunjo": {
        "love": "Есть шанс на тепло, если радость настоящая, а не выдавленная ради сохранения связи.",
        "work": "Ищи вариант без внутреннего сопротивления. Там, где легче дышится, больше пользы.",
        "money": "Решение должно давать облегчение, а не новую зависимость или тревогу.",
        "choice": "Сильнее тот выбор, после которого внутри становится спокойнее и проще.",
        "future": "Ситуация может сложиться мягко, если не пытаться удержать её силой.",
        "general": "Ориентир — внутреннее согласие, а не чужое одобрение.",
    },
    "hagalaz": {
        "love": "Старый сценарий может ломаться. Это неприятно, но показывает, что уже не работает.",
        "work": "Сбой показывает слабое место системы. Чини причину, а не только последствия.",
        "money": "Не держись за рискованную схему. Лучше потерять иллюзию, чем ресурс.",
        "conflict": "Напряжение может прорваться резко. Снизь давление, пока оно не сорвало всё.",
        "future": "Поворот возможен через разрушение старого порядка. Не всё стоит спасать.",
        "general": "То, что трещит, требует пересмотра, а не косметического ремонта.",
    },
    "nauthiz": {
        "love": "Не путай нужду с близостью. Если держит страх потери, это не то же самое, что любовь.",
        "work": "Сократи лишнее. Сейчас важно выполнить минимум, а не доказывать всем свою выносливость.",
        "money": "Режим экономии и расчёт. Не добавляй обязательств, пока не закрыт базовый ресурс.",
        "choice": "Выбирай не идеальное, а жизнеспособное. Сейчас нужен минимум, который выдержишь.",
        "future": "Развитие будет медленным, пока есть дефицит сил, денег или ясности.",
        "general": "Действуй из минимума. Не расширяй ситуацию, если ресурс уже сжат.",
    },
    "isa": {
        "love": "Пауза честнее выдавленного решения. Если всё застыло, не пытайся оживить это в одиночку.",
        "work": "Процесс замер. Давить бесполезно — лучше подготовить почву и ждать сигнала.",
        "money": "Риск и крупные траты лучше отложить. Сейчас важнее сохранить, чем разогнать.",
        "choice": "Решение не созрело. Пауза сейчас не слабость, а способ не ошибиться.",
        "future": "Быстрого движения мало. Сначала нужно разморозить причину остановки.",
        "general": "Сейчас важно остановиться и посмотреть, что именно не движется.",
    },
    "jera": {
        "love": "Результат зависит от накопленных действий. Смотри не на один жест, а на повторяющийся рисунок.",
        "work": "Сработает регулярность. Быстрый рывок слабее спокойной системы.",
        "money": "Прибыль приходит циклом, не рывком. Здесь важны сроки и терпение.",
        "choice": "Выбирай то, что даст устойчивый результат, а не короткое облегчение.",
        "future": "Всё дозревает постепенно. Итог будет следствием уже посеянного.",
        "general": "Всё дозревает. Не требуй результата раньше времени.",
    },
    "eihwaz": {
        "love": "Связь проверяется выдержкой. Если она живая, она выдержит честный разговор и паузу.",
        "work": "Нужна устойчивость. Не меняй стратегию только потому, что стало тяжело.",
        "money": "Держи стратегию. Сейчас выигрывает защита долгой позиции, а не быстрый ход.",
        "conflict": "Не ломайся под давлением. Спокойная стойкость сильнее ответного удара.",
        "future": "Путь длиннее, чем хочется, но он не закрыт. Нужна выдержка.",
        "general": "Выигрывает устойчивость. Не всё решается одним движением.",
    },
    "perthro": {
        "love": "Часть мотивов скрыта. Не делай вывод, пока не увидел, что человек реально выбирает.",
        "work": "Не все условия видны. Проверь скрытые правила, роли и ожидания.",
        "money": "Есть неизвестный фактор. Не вкладывайся вслепую и не верь красивой упаковке.",
        "choice": "Картина неполная. Лучший шаг — запросить недостающую информацию.",
        "future": "Итог пока не раскрыт. Слишком рано ставить точку.",
        "general": "Картина неполная. Не принимай неизвестность за знак согласия.",
    },
    "algiz": {
        "love": "Нужна безопасность. Не открывайся глубже, чем позволяет доверие.",
        "work": "Защити позицию: обязанности, границы, документы, сроки. Это не лишняя осторожность.",
        "money": "Сначала безопасность, потом риск. Проверь защиту денег и условий.",
        "conflict": "Не впускай лишнее в личное поле. Дистанция сейчас помогает.",
        "choice": "Выбирай то, где меньше угроз для твоего ресурса и достоинства.",
        "general": "Границы сохраняют ресурс. Не открывай дверь всему подряд.",
    },
    "sowilo": {
        "love": "Ясность приходит через честность. Если связь настоящая, свет её не разрушит.",
        "work": "Можно выходить в видимость. Покажи результат, не прячь сильную сторону.",
        "money": "Шанс сильнее при прозрачности. Честные цифры работают лучше обещаний.",
        "choice": "Выбирай то, где больше ясности и силы, а не то, где меньше страха.",
        "future": "Перспектива светлая, если не искажать факты ради удобства.",
        "general": "Энергия есть. Направь её чисто и без самообмана.",
    },
    "teiwaz": {
        "love": "Нужен честный выбор. Ожидание само ничего не решит.",
        "work": "Решает дисциплина и позиция. Выигрывает тот, кто держит линию.",
        "money": "Действуй по правилу, а не по импульсу. Проверь справедливость сделки.",
        "choice": "Выбирай прямо. Полумеры будут тянуть силы и путать решение.",
        "conflict": "Не спорь ради победы. Держи принцип и не уходи в мелкую борьбу.",
        "general": "Выбери линию и держи её. Здесь важна внутренняя честность.",
    },
    "berkana": {
        "love": "Связь растёт через заботу, но не через спасательство. Важно, чтобы рост был взаимным.",
        "work": "Проект нужно выращивать. Не требуй зрелого результата от сырого процесса.",
        "money": "Рост постепенный. Маленькое вложение может дать больше, чем резкий риск.",
        "future": "Перспектива мягкая, если дать ей условия и время.",
        "choice": "Выбирай то, что можно развивать, а не то, что сразу истощает.",
        "general": "Дай процессу здоровые условия. Рост не любит давления.",
    },
    "ehwaz": {
        "love": "Важна синхронность двоих. Если темп разный, нужна честная настройка, а не догонялки.",
        "work": "Нужен согласованный темп. Проверь, кто реально едет с тобой в одной упряжке.",
        "money": "Проверь партнёрство. Деньги зависят от согласованности действий.",
        "choice": "Выбирай вариант, где можно двигаться вместе с обстоятельствами, а не тащить всё одному.",
        "future": "Движение возможно, если есть согласование и общий ритм.",
        "general": "Важна согласованность. Один человек не должен тащить всю повозку.",
    },
    "mannaz": {
        "love": "Исход зависит от поведения людей. Смотри не на идею отношений, а на зрелость участников.",
        "work": "Люди важнее схемы. Кто принимает решения — тот и меняет исход.",
        "money": "Смотри, кто принимает решение и кому это выгодно. Человеческий фактор ключевой.",
        "conflict": "Не обобщай. Здесь важны конкретные реакции конкретных людей.",
        "choice": "Выбирай с учётом себя, а не только ожиданий окружающих.",
        "general": "Человеческий фактор важен. Поведение покажет больше, чем слова.",
    },
    "laguz": {
        "love": "Эмоции сильные, но могут мутить картину. Не принимай волну за окончательную правду.",
        "work": "Интуиция полезна, хаос — нет. Сначала отдели чувство от факта.",
        "money": "Не плыви за настроением. Финансовое решение должно быть сухим и проверенным.",
        "conflict": "Эмоция может увести глубже, чем нужно. Сначала успокой воду.",
        "future": "События текут, но направление ещё меняется. Нужны берега.",
        "general": "Поток нужен с берегами. Чувствуй, но проверяй.",
    },
    "inguz": {
        "love": "Этап созрел: либо переходить глубже, либо честно завершать старую форму.",
        "work": "Проект близок к переходу. Собери результат и не растягивай финал.",
        "money": "Новый цикл созрел. Закрой старое обязательство перед новым шагом.",
        "choice": "Решение уже созревает. Не держи старое только из привычки.",
        "future": "Начинается новая фаза, но ей нужен чистый старт.",
        "general": "Что-то подходит к новой фазе. Заверши старый узел.",
    },
    "dagaz": {
        "love": "Возможен разворот восприятия. После ясного разговора всё может выглядеть иначе.",
        "work": "Ситуация проясняется. Хорошо менять подход, если старый больше не работает.",
        "money": "Переход к другой модели. Не цепляйся за прежнюю схему заработка или трат.",
        "future": "Перелом возможен. Важно заметить момент, когда дверь открывается.",
        "choice": "Выбирай обновление, если старое уже не возвращает энергию.",
        "general": "Это точка смены состояния. День может дать новый взгляд.",
    },
    "othala": {
        "love": "Важны ценности и чувство дома. Красивой связи мало, если нет общей основы.",
        "work": "Опирайся на базу: правила, опыт, структуру. Не строй всё с нуля без причины.",
        "money": "Фундамент важнее быстрых трат. Смотри на долгую ценность.",
        "choice": "Выбирай то, что укрепляет основу, а не просто даёт эмоцию на один день.",
        "future": "Будущее держится на фундаменте. Проверь, есть ли он сейчас.",
        "general": "Сначала фундамент. Без основы любые шаги будут шаткими.",
    },
}


def detect_topic(question: str) -> str:
    q = (question or "").lower()
    scores = {topic: sum(1 for word in words if word in q) for topic, words in TOPIC_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "general"


def rune_topic_hint(rune: dict, topic: str) -> str:
    data = RUNE_THEME_HINTS.get((rune.get("key") or "").lower(), {})
    return data.get(topic) or data.get("general") or "смотри на главный смысл руны"


async def stable_profile_ready(update, context) -> bool:
    user = update.effective_user
    if not user:
        return False
    try:
        bot.ensure_user(bot.DB_PATH, user.id, bot.user_name(update))
        profile = bot.get_user_profile(bot.DB_PATH, user.id)
        if profile and profile.get("palette") in {"light", "dark", "premium"}:
            return True
        set_user_palette(bot.DB_PATH, user.id, DEFAULT_PALETTE)
        return True
    except Exception:
        if update.effective_message:
            await update.effective_message.reply_text("Меню готово. Выбери действие ниже.", reply_markup=bot.MAIN_KEYBOARD)
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


def _short(text: str, limit: int = 220) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "."


def _title(rune: dict, reversed_state: bool) -> str:
    return f"<b>{_rune_name(rune)} · {'обратное' if reversed_state else 'прямое'}</b>"


def _interp(rune: dict, palette: str) -> dict:
    return bot.rune_text(rune, palette if palette != "premium" else "dark")


def daily_synthesis(main: dict, aux: dict, main_alt: bool, aux_alt: bool) -> str:
    m = (main.get("key") or "").lower()
    a = (aux.get("key") or "").lower()
    if main_alt or aux_alt:
        return "День лучше пройти внимательнее обычного: не обещай лишнего и не соглашайся автоматически."
    if m in {"gebo", "ehwaz", "mannaz"} or a in {"gebo", "ehwaz", "mannaz"}:
        return "День будет зависеть от общения и взаимности. Смотри, где есть честный обмен, а где всё держится только на тебе."
    if m in {"isa", "nauthiz", "hagalaz"} or a in {"isa", "nauthiz", "hagalaz"}:
        return "День может идти медленнее, чем хочется. Лучше сократить задачи и оставить только необходимое."
    if m in {"raido", "dagaz", "inguz"} or a in {"raido", "dagaz", "inguz"}:
        return "День подходит для перехода или решения, но двигайся по порядку: сначала направление, потом скорость."
    if m in {"sowilo", "kenaz", "ansuz"} or a in {"sowilo", "kenaz", "ansuz"}:
        return "День про ясность. Хорошо сработают разговор, честная формулировка и один открытый шаг."
    return "День лучше не перегружать. Выбери один понятный шаг и доведи его спокойно."


def concise_daily_text(name: str, main: dict, main_text: dict, aux: dict, aux_text: dict, palette: str, main_alt: bool, aux_alt: bool) -> str:
    main_desc = alt_meaning(main, palette) if main_alt else main_text.get("short_desc", "")
    aux_desc = alt_meaning(aux, palette) if aux_alt else aux_text.get("short_desc", "")
    thought = daily_synthesis(main, aux, main_alt, aux_alt)
    return f"🌞 <b>Руна дня</b>\n\n{_title(main, main_alt)}\n{_safe(_short(main_desc, 150))}\n\n<b>Дополнительно: {_rune_name(aux)}</b>\n{_safe(_short(aux_desc, 120))}\n\n<b>Мысль дня</b>\n{_safe(thought)}"


def yes_no_label(answer: str, alt: bool, rune: dict) -> str:
    key = (rune.get("key") or "").lower()
    if alt or key in {"isa", "nauthiz", "hagalaz", "thurisaz", "perthro"}:
        return "Скорее нет"
    if key in {"fehu", "wunjo", "sowilo", "gebo", "dagaz", "berkana", "inguz"}:
        return "Скорее да"
    return "Да, но с условием"


def concise_question_text(name: str, question: str, rune: dict, answer: str, palette: str, alt: bool) -> str:
    topic = detect_topic(question)
    verdict = yes_no_label(answer, alt, rune)
    body = alt_meaning(rune, palette) if alt else answer
    hint = rune_topic_hint(rune, topic)
    return f"❓ <b>{verdict}</b>\n\n<i>{_safe(_short(question, 110))}</i>\n\n{_title(rune, alt)}\n{_safe(_short(body, 130))}\n\n{_safe(hint)}"


def concise_spread_text(name: str, question: str, runes: list, palette: str) -> str:
    topic = detect_topic(question)
    first, second, third = runes[0], runes[1], runes[2]
    h1 = rune_topic_hint(first, topic)
    h2 = rune_topic_hint(second, topic)
    h3 = rune_topic_hint(third, topic)
    if topic == "love":
        bridge = "Итог: смотри на взаимность и реальные действия. Если движение есть только с одной стороны, ситуация будет буксовать."
    elif topic == "work":
        bridge = "Итог: проверь условия и свою роль. Дальше нужен один конкретный рабочий шаг, а не распыление."
    elif topic == "money":
        bridge = "Итог: сначала считай риск и обязательства. Быстрые решения сейчас слабее расчёта."
    elif topic == "choice":
        bridge = "Итог: сильнее тот вариант, который не требует постоянно себя уговаривать."
    elif topic == "conflict":
        bridge = "Итог: не усиливай давление. Сначала верни границу и только потом продолжай разговор."
    elif topic == "future":
        bridge = "Итог: будущее зависит от ближайшего шага. Не жди знака, если уже видишь слабое место."
    else:
        bridge = "Итог: не расширяй вопрос. Сначала убери главную помеху, потом действуй."
    return f"🔮 <b>Расклад</b>\n\n<i>{_safe(_short(question, 110))}</i>\n\n<b>1. {_rune_name(first)}</b>\n{_safe(h1)}\n\n<b>2. {_rune_name(second)}</b>\n{_safe(h2)}\n\n<b>3. {_rune_name(third)}</b>\n{_safe(h3)}\n\n{bridge}"


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
            pass


async def stable_send_rasklad(update, context, question: str) -> None:
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
            request_id = None
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
            pass
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

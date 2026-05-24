import os

HUMAN_READING_BUTTON = "🕯 Личный расклад"

PAYMENT_PHONE = os.getenv("PAYMENT_PHONE", "")
PAYMENT_CARD = os.getenv("PAYMENT_CARD", "")
PAYMENT_AMOUNT = os.getenv("PAYMENT_AMOUNT", "100")

HUMAN_READING_TEXT = (
    "🕯 <b>Личный расклад</b>\n\n"
    "Живой разбор от человека: вы пишете вопрос одним сообщением — "
    "получаете короткую интерпретацию с практическим выводом. "
    "Без давления и лишней мистики.\n\n"
    f"<b>Стоимость:</b> {PAYMENT_AMOUNT} ₽\n"
    "<b>Время ответа:</b> 5–10 минут после оплаты\n\n"
    "<b>💳 Реквизиты для оплаты</b>\n\n"
    f"<b>По карте:</b>\n"
    f"<code>{PAYMENT_CARD}</code>\n\n"
    f"<b>По СБП (быстро):</b>\n"
    f"<code>{PAYMENT_PHONE}</code>\n\n"
    "Любой банк → перевод по номеру карты или по номеру телефона через СБП. "
    f"Сумма ровно {PAYMENT_AMOUNT} ₽.\n\n"
    "После оплаты нажмите кнопку «Я оплатил» и пришлите вопрос следующим сообщением."
)

HUMAN_READING_PAID_PROMPT = (
    "🕯 Оплата отмечена.\n\n"
    "Напишите вопрос одним сообщением — он уйдёт человеку для разбора. "
    "Постарайтесь сформулировать ситуацию коротко и по сути."
)

HUMAN_READING_CANCEL_TEXT = "Заявка на личный расклад отменена. Можно вернуться в меню."

PAYMENT_CONFIRM_CALLBACK = "human_reading:paid"
PAYMENT_CANCEL_CALLBACK = "human_reading:cancel"

# Runa Telegram Bot (Production Ready)

Telegram-бот для рунических раскладов с поддержкой production-режима.

## Что умеет
- Руна дня
- Ответ одной руной
- Расклад (3 руны)
- Онбординг + типология
- GPT (опционально)
- Персонализация по выбранной колоде

## Режимы работы
- Polling — локально
- Webhook — продакшн

## Важно (безопасность)
- НЕ вставляй BOT_TOKEN в URL
- Используй WEBHOOK_PATH (например: /webhook)

## ENV
См. .env.example

## Запуск
```bash
pip install -r requirements.txt
python bot.py
```

## Деплой
1. Укажи BOT_TOKEN
2. Укажи WEBHOOK_URL
3. (опционально) ADMIN_IDS
4. Добавь persistent disk

## Статус
Готов к продакшну

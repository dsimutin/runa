# Runa Telegram Bot

Telegram-бот для рунических раскладов, ежедневной рассылки и премиум-функций.

## Возможности

- руна дня и ответ одной руной;
- расклады на три руны, год и взаимоотношения;
- онбординг и выбор колоды;
- ежедневные, еженедельные и ежемесячные рассылки;
- пробный период, Telegram Stars и оплата картой;
- заявки на личный расклад и операторский интерфейс.

## Локальный запуск

Требуются Python 3.11+ и PostgreSQL.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python app.py
```

Без `WEBHOOK_URL` бот запускается в polling-режиме. При заданном `WEBHOOK_URL` запускаются webhook и `/health` на порту `PORT`.

## Переменные окружения

Обязательные:

- `BOT_TOKEN` — токен Telegram-бота;
- `DATABASE_URL` — строка подключения к PostgreSQL.

Для production:

- `WEBHOOK_URL` — публичный HTTPS-адрес сервиса;
- `WEBHOOK_PATH` — путь webhook без начального `/`;
- `PORT` — порт HTTP-сервера;
- `ADMIN_IDS` — Telegram user ID администраторов через запятую.

Опционально:

- `PAYMENT_PROVIDER_TOKEN` — токен провайдера платежей картой. Без него используется ручное подтверждение;
- `GITHUB_TOKEN` — только для вспомогательного `branch_helper.py`.

Секреты нельзя добавлять в репозиторий или включать в URL webhook.

## Проверки

```bash
python -m pytest -q
ruff check .
python -m compileall -q .
```

## Развёртывание: Google Cloud VM + Neon

Бот работает на VM в polling-режиме, поэтому публичный домен, webhook и открытый входящий порт не нужны. PostgreSQL размещается в Neon; необходимые таблицы бот создаёт при первом запуске.

1. В Neon создай PostgreSQL-проект и скопируй connection string.
2. В Google Cloud создай бесплатную `e2-micro` VM в регионе `us-west1`, `us-central1` или `us-east1` с Ubuntu 22.04 или 24.04.
3. На VM клонируй репозиторий и установи Docker:

```bash
git clone https://github.com/dsimutin/runa.git
cd runa
sudo bash deploy/vm/install-docker.sh
```

4. После повторного входа по SSH создай окружение:

```bash
cp .env.example .env
nano .env
```

Обязательно заполни `BOT_TOKEN`, `DATABASE_URL` и `ADMIN_IDS`. Для Neon используй строку подключения с `sslmode=require`.

5. Запусти бота:

```bash
bash deploy/vm/deploy.sh
docker compose logs -f bot
```

Контейнер автоматически перезапускается при ошибке и после перезагрузки VM. Для обновления выполни `git pull`, затем снова `bash deploy/vm/deploy.sh`.

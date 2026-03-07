<div align="center">

# Gemini Account Manager TG

<p>
  <img src="https://img.shields.io/badge/Python-3.14-blue" alt="Python" />
  <img src="https://img.shields.io/badge/aiogram-3.x-2f7ed8" alt="aiogram" />
  <img src="https://img.shields.io/badge/Database-PostgreSQL-336791" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/ORM-SQLModel-0F766E" alt="SQLModel" />
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Ubuntu-4c9a2a" alt="Platform" />
</p>

<p><b>Менеджер Telegram-аккаунтов для личного использования.</b></p>

</div>

> [!WARNING]
> ⚠️ **Use at your own risk**: только личные аккаунты и личное использование. Возможна блокировка Telegram-аккаунта при частых запросах.

## Что умеет
- Управление Telegram-сессиями: добавление, включение/выключение, удаление.
- Мониторинг чатов: новые, удалённые, отдельно боты/каналы.
- Перехват временных вложений (TTL/спойлер) в админ-бот.
- Ответы через Gemini по префиксу `.` с учетом контекста.
- Статистика стабильности аккаунтов (почасовая/подневная).
- Настройки: автообновление, часовой пояс, перезапуск бота.
- Уведомления о новой версии: не чаще 1 раза в сутки + snooze на 7 дней.

## Стек
- Python `3.14.x`
- aiogram `3.x`
- pyrofork
- Google Gemini (`google-generativeai`)
- PostgreSQL
- SQLModel + SQLAlchemy Async

## Конфиг через .env
Проект использует переменные окружения из файла `.env` в корне проекта.

1. Скопируйте `.env.example` в `.env`.
2. Заполните токены/ключи/параметры БД.
3. Установите зависимости: `pip install -r requirements.txt`.

Ключевые переменные:
- `TOKEN_BOT`
- `GEMINI_KEY`
- `ADMIN_ID_LIST` (через запятую)
- `DB_ENGINE`, `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_ADMIN_NAME`

> Файл `.env` не должен попадать в git.

## Запуск
Windows:
- `start.bat` — запуск бота.
- `update.bat` — обновление проекта + зависимости.

Ubuntu/Linux:
- `start.sh` — запуск бота.
- `update.sh` — обновление проекта + зависимости.

## База данных
При старте бот автоматически:
- создает БД (если отсутствует),
- создает таблицы,
- применяет совместимые авто-миграции (новые поля/типы).

Рекомендуется локальная PostgreSQL. Удаленная БД возможна, но менее безопасна для сессий и чувствительных данных.

## Обновление
`update_bot.py` скачивает актуальный репозиторий (ветка `main`) и не перезаписывает локальные чувствительные данные:
- `.env`
- `.env.local`
- `data/proxy.txt`
- `data/session/`
- `data/logs/`
- `data/temp/`

## Перенос на второй ПК
1. Установить Python 3.14 и PostgreSQL (или подключиться к существующей БД).
2. Клонировать репозиторий.
3. Создать `.env` из `.env.example`.
4. Вписать `TOKEN_BOT`, `GEMINI_KEY`, `ADMIN_ID_LIST`, параметры БД.
5. Установить зависимости: `pip install -r requirements.txt`.
6. Запустить `start.bat` (Windows) или `start.sh` (Linux).

Если переносите существующие аккаунты-сессии:
- скопируйте папку `data/session/` на второй ПК,
- убедитесь, что `DB_*` в `.env` указывает на ту же БД (или перенесите данные БД отдельно).

## Важно
- Используйте только на личном устройстве.
- Не рекомендуется запуск на сторонних VDS/VPS.
- Возможны баги и нестабильная работа.
- Проект дорабатывался с использованием Codex.
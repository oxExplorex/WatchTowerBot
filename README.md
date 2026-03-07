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
- Ответы через Gemini по префиксу `.` с учётом контекста.
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

## Запуск
1. Скопировать `data/config_sample.py` в `data/config.py`.
2. Заполнить токены/ключи/параметры БД.
3. Установить зависимости: `pip install -r requirements.txt`.

Windows:
- `start.bat` — запуск бота.
- `update.bat` — обновление проекта + зависимости.

Ubuntu/Linux:
- `start.sh` — запуск бота.
- `update.sh` — обновление проекта + зависимости.

## База данных
При старте бот автоматически:
- создаёт БД (если отсутствует),
- создаёт таблицы,
- применяет совместимые авто-миграции (новые поля/типы).

Рекомендуется локальная PostgreSQL. Удалённая БД возможна, но менее безопасна для сессий/данных.

## Обновление
`update_bot.py` скачивает актуальный репозиторий (ветка `main`) и не перезаписывает локальные чувствительные данные:
- `data/config.py`
- `data/proxy.txt`
- `data/session/`
- `data/logs/`
- `data/temp/`

## Важно
- Используйте только на личном устройстве.
- Не рекомендуется запуск на сторонних VDS/VPS.
- Возможны баги и нестабильная работа.
- Проект дорабатывался с использованием Codex.
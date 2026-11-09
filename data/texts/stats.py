SETTINGS_BOT_KEYBOARD = [
    "📉 Моя статистика",
    "📊 Общая статистика",
    "⚙️ Настройки",
]

STATS_ICON_NO_DATA = "⬛"
STATS_ICON_OK = "🟩"
STATS_ICON_WARN = "🟨"
STATS_ICON_FAIL = "🟥"
STATS_RECENT_EMPTY = "• нет"
STATS_RECENT_IN_ACCOUNT = "Подробности — в карточках аккаунтов."
STATS_RECENT_ROW = "• {stamp} - {reason}"
STATS_TITLE_OWN = "<b>📉 Моя статистика</b>"
STATS_TITLE_GLOBAL = "<b>📊 Общая статистика</b>"
STATS_NO_CHECKS = "нет проверок"
STATS_CHECK_RESULT = "{percent}% ({count} проверок)"
STATS_SIZE_UNITS = ("Б", "КиБ", "МиБ", "ГиБ", "ТиБ", "ПиБ", "ЭиБ")
CHART_LABELS = {
    "title": "Состояние и время работы",
    "process": "Этот запуск: {duration}",
    "bot": "Бот · соединение с Telegram",
    "userbot": "Userbot · подключённые аккаунты",
    "now": "Сейчас: {status}",
    "ready": "соединение есть",
    "down": "нет соединения",
    "partial": "подключены {available} из {expected}",
    "all_accounts": "подключены {available} из {expected}",
    "off": "нет включённых аккаунтов",
    "stale": "нет свежих наблюдений",
    "daily": "За 24 часа · без сбоев: {percent} наблюдаемого времени",
    "no_percent": "За 24 часа · недостаточно данных для процента",
    "good": "Без сбоев ~ {duration}",
    "issues": "С перебоями ~ {duration}",
    "unknown": "Нет данных: {duration}",
    "disabled": "Выключены: {duration}",
    "units": ("д", "ч", "мин"),
    "less_minute": "меньше минуты",
    "legend": [(1, "Связь есть"), (2, "Подключена часть"), (3, "Был сбой"),
               (0, "Нет включённых аккаунтов"), (None, "Нет наблюдений")],
    "coverage": "Ячейка — час. Каждая цветная полоска — пятиминутный интервал проверок.",
    "estimate": "Время приблизительное. Нет наблюдений — не значит простой. Будущие часы пустые.",
}
CHART_LABELS_FALLBACK = {
    "title": "Connection status and runtime",
    "process": "Current process: {duration}",
    "bot": "Bot / Telegram connection",
    "userbot": "Userbot / account connections",
    "now": "Now: {status}", "ready": "connected", "down": "disconnected",
    "partial": "{available} of {expected} connected", "all_accounts": "{available} of {expected} connected",
    "off": "no enabled accounts", "stale": "no recent observations",
    "daily": "Last 24 hours / no failures: {percent} of observed active time",
    "no_percent": "Last 24 hours / insufficient data for a percentage",
    "good": "No failures ~ {duration}", "issues": "Issues ~ {duration}",
    "unknown": "No data: {duration}", "disabled": "Disabled: {duration}",
    "units": ("d", "h", "min"), "less_minute": "less than a minute",
    "legend": [(1, "Connected"), (2, "Some connected"), (3, "An error occurred"),
               (0, "No enabled accounts"), (None, "No observations")],
    "coverage": "Each cell is one hour. Each colored strip is a five-minute observation interval.",
    "estimate": "Durations are approximate. Missing data is not downtime. Future hours are empty.",
}
STATS_TEXT = (
    "{title}\n\n"
    "<b>Состояние аккаунтов</b>\n"
    "Ваши: включено {own_active}/{own_total}, подключено <b>{own_running}</b>\n"
    "Все: включено {all_active}/{all_total}, подключено <b>{all_running}</b>\n\n"
    "<b>Ваш архив личных переписок</b>\n"
    "Чатов: <b>{archive_chats}</b> · с сообщениями: {archive_chats_with_messages}\n"
    "Сообщения: <b>{archive_messages}</b> · версии: {archive_revisions}\n"
    "Изменены: {archive_edited} · удалены: {archive_deleted} · недоступны: {archive_missing}\n"
    "История проверена: {archive_history_checked}/{archive_history_chats} · до начала: {archive_history_reached}\n"
    "Вложения: {archive_media_stored} сохранено · {archive_media_pending} в очереди · {archive_media_failed} ошибок\n"
    "Файлов: {archive_media_files} · недоступно: {archive_media_unavailable} · {archive_media_size}\n"
    "Содержимое: {archive_content_size} · всего ≈ <b>{archive_total_size}</b>\n"
    "<i>Объём содержимого и файлов, без индексов БД. Файлы считаются без дублей.</i>\n\n"
    "<b>Последние сбои</b>\n"
    "{recent_failures}\n\n"
    "<i>График: итог за сутки и до 14 дней по часам. Нет наблюдений ≠ простой.</i>"
)


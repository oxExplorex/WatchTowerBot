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
    "bot": "Бот · получение событий Telegram",
    "userbot": "Userbot · подключение включённых аккаунтов",
    "legend": [(1, "Подключены все"), (2, "Подключена часть"), (3, "Ошибка / нет подключения"),
               (0, "Нет включённых аккаунтов"), (None, "Нет наблюдений")],
    "coverage": "Строка — день, столбец — час. Серая часть ячейки — время без наблюдений.",
}
CHART_LABELS_FALLBACK = {
    "bot": "Bot / Telegram polling",
    "userbot": "Userbot / enabled account connections",
    "legend": [(1, "All connected"), (2, "Some connected"), (3, "Error / disconnected"),
               (0, "No enabled accounts"), (None, "No observations")],
    "coverage": "Rows: days. Columns: hours. Gray portion: missing observations.",
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
    "<i>График: 14 дней по часам. Серый — нет наблюдений; это не процент uptime.</i>"
)


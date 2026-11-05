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
    "Сообщения: <b>{archive_messages}</b> · с отметкой редактирования: <b>{archive_edited}</b>\n"
    "Сохранённые версии: <b>{archive_revisions}</b>\n"
    "Удалены: {archive_deleted} · недоступны при проверке: {archive_missing}\n"
    "Вложения: {archive_media_stored} сохранено, {archive_media_pending} в очереди, {archive_media_failed} с ошибкой\n"
    "Начало истории достигнуто: <b>{archive_history_reached}/{archive_history_chats}</b> чатов\n\n"
    "<b>Последние сбои</b>\n"
    "{recent_failures}\n\n"
    "<i>График: 14 дней по часам. Серый — нет наблюдений. "
    "Бот — получение событий, userbot — подключение клиентов. Это не процент uptime.</i>"
)


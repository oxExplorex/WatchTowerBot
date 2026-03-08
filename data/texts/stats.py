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
STATS_RECENT_ROW = "• {stamp} - {reason}"
STATS_TITLE_OWN = "<b>📉 Моя статистика</b>"
STATS_TITLE_GLOBAL = "<b>📊 Общая статистика</b>"
STATS_TEXT = (
    "{title}\n\n"
    "<b>Состояние аккаунтов</b>\n"
    "• Ваши: <b>{own_active}/{own_total}</b> активны\n"
    "• Все: <b>{all_active}/{all_total}</b> активны\n\n"
    "<b>Надёжность</b>\n"
    "• 24ч: <b>{success_24h}%</b> (сбоев: <b>{fail_24h}</b>)\n"
    "• 14д: <b>{success_14d}%</b> (сбоев: <b>{fail_14d}</b>)\n\n"
    "<b>24ч (свежее → старее, шаг 1ч)</b>\n"
    "<blockquote>{by_hour_text}</blockquote>\n\n"
    "<b>14д (свежее → старее, шаг 1д)</b>\n"
    "<blockquote>{by_day_text}</blockquote>\n\n"
    "<b>Последние сбои</b>\n"
    "{recent_failures}\n\n"
    "Легенда: 🟩 стабильно, 🟨 редкие сбои, 🟥 частые сбои, ⬛ нет данных"
)


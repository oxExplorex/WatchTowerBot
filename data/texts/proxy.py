PROXY_USER_KEYBOARD = ["🛰 Прокси"]

PROXY_MENU_PROMPT_TEXT = (
    "<b>🌐 Gemini прокси</b>\n\n"
    "Текущий: <code>{proxy}</code>\n"
    "Статус: <b>{status}</b>\n"
    "Проверка: <code>{checked_at}</code>\n"
    "Ошибка: <code>{error}</code>\n\n"
    "Отправьте HTTP-прокси:\n"
    "• <code>ip:port:user:password</code>\n"
    "• <code>ip:port@user:password</code>\n"
    "• <code>http://user:password@ip:port</code>"
)
PROXY_SET_TEXT = "✅ Прокси сохранен"
PROXY_DISABLED_TEXT = "✅ Прокси отключен. Gemini попробует работать без него."
PROXY_INVALID_FORMAT_TEXT = "❌ Формат прокси некорректный. Поддерживаются только HTTP: ip:port:user:password, ip:port@user:password или http://user:password@ip:port"

SETTINGS_BTN_PROXY = "🌐 Прокси: {state}"
SETTINGS_BTN_PROXY_CHECK = "🧪 Проверить"
SETTINGS_BTN_PROXY_DISABLE = "🗑 Удалить"
PROXY_CHECK_OK_TEXT = "✅ Прокси работает"
PROXY_CHECK_FAIL_TEXT = "❌ Прокси не работает: {reason}"
PROXY_CHECK_SKIPPED_NO_PROXY_TEXT = "ℹ️ Прокси выключен. Проверять нечего."

GEMINI_PROXY_REQUIRED_TEXT = "ℹ️ Прокси для Gemini не задан. Пробую работать напрямую."
GEMINI_PROXY_INVALID_TEXT = "❌ Формат прокси некорректный. Обновите прокси в настройках."
GEMINI_PROXY_DOWN_TEXT = "❌ Gemini временно недоступен: прокси не отвечает."
GEMINI_PROXY_AUTO_DISABLED_TEXT = "⚠️ Gemini-прокси автоматически отключен. Причина: <code>{reason}</code>"

PROXY_STATUS_DISABLED_TEXT = "🔴 выключен"
PROXY_STATUS_OK_TEXT = "🟢 работает"
PROXY_STATUS_PENDING_TEXT = "🟡 требует проверки"
PROXY_NOT_SET_TEXT = "не задан"
PROXY_MENU_NO_DATA_TEXT = "нет данных"
PROXY_GEMINI_KEY_EMPTY_TEXT = "GEMINI_KEY пустой"

SETTINGS_PROXY_STATE_OFF_TEXT = "🔴 выключен"
SETTINGS_PROXY_STATE_OK_TEXT = "🟢 работает"
SETTINGS_PROXY_STATE_PENDING_TEXT = "🟡 не проверен"

PROXY_CHECKING_TEXT = "⏳ Проверяю прокси..."
PROXY_SET_AND_CHECK_OK_TEXT = "✅ Прокси сохранен и прошел проверку"


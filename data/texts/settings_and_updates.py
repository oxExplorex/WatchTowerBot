RESTART_BOT_W_KEYBOARD = ["🔄 Перезапуск бота"]
RESTARTING_TEXT = "Перезапускаю..."

TIMEZONE_LABELS = {
    -12: "Бейкер-Айленд",
    -11: "Паго-Паго",
    -10: "Гонолулу",
    -9: "Анкоридж",
    -8: "Лос-Анджелес",
    -7: "Денвер",
    -6: "Чикаго",
    -5: "Нью-Йорк",
    -4: "Каракас",
    -3: "Буэнос-Айрес",
    -2: "Южная Георгия",
    -1: "Азорские острова",
    0: "Лондон",
    1: "Берлин",
    2: "Киев",
    3: "Москва",
    4: "Дубай",
    5: "Карачи",
    6: "Дакка",
    7: "Новосибирск",
    8: "Шанхай",
    9: "Якутск",
    10: "Сидней",
    11: "Соломоновы о-ва",
    12: "Окленд",
    13: "Самоа",
    14: "Киритимати",
}
TIMEZONE_MENU_TEXT = (
    "<b>🕒 Часовой пояс</b>\n\n"
    "<blockquote>{tz_rows}</blockquote>\n\n"
    "Текущий: <b>{tz_label}</b>\n\n"
    "Выберите смещение:"
)
TIMEZONE_SET_TOAST = "Часовой пояс сохранён: {tz_label}"
TIMEZONE_RESET_TOAST = "Часовой пояс сброшен на +3 (Москва)"
TIMEZONE_INVALID_TOAST = "Некорректный часовой пояс"
TIMEZONE_BTN_PREFIX = "{offset}"
TIMEZONE_BTN_SELECTED = "✅ {label}"
TIMEZONE_BTN_RESET = "🔄 Сбросить до +3"

SETTINGS_MENU_TITLE = (
    "<b>Настройки</b>\n\n"
    "Версия бота: <code>{bot_version}</code>\n"
    "Статус версии: <b>{version_state}</b>\n"
    "Последняя проверка: <b>{last_check_ago}</b> мин назад\n\n"
    "Мониторинг аккаунтов: <b>{parser_status}</b>\n"
    "Gemini-ответы: <b>{gemini_status}</b>\n"
    "HTTP-прокси Gemini: <b>{proxy_status}</b>\n"
    "Текущий HTTP-прокси: <code>{current_proxy}</code>\n\n"
    "***\n\n"
    "<code>{date}</code>"
)
VERSION_STATE_UNKNOWN = "⚪ Неизвестно"
VERSION_STATE_UP_TO_DATE = "✅ Актуальная"
VERSION_STATE_UPDATE_AVAILABLE = "🆕 Доступна: {latest_version}"
AUTO_UPDATE_ON_TEXT = "🟢 Включено"
AUTO_UPDATE_OFF_TEXT = "🔴 Выключено"
SETTINGS_BTN_AUTO_UPDATE = "🤖 Автообновление: {state}"
SETTINGS_BTN_RUN_UPDATE = "⬇️ Обновить сейчас"
SETTINGS_BTN_TIMEZONE = "🕓 Часовой пояс: {tz_label}"
SETTINGS_BTN_RESTART = "♻️ Перезагрузить"
SETTINGS_BTN_CLOSE = "❌ Закрыть"
SETTINGS_BTN_CHECK_UPDATE = "🔎 Проверить обновление"
SETTINGS_TOAST_UPDATED = "✅ Настройки обновлены"
SETTINGS_UPDATE_OK_TOAST = "✅ У вас актуальная версия"
SETTINGS_UPDATE_AVAILABLE_TOAST = "🆕 Доступна новая версия: {latest_version}"
SETTINGS_UPDATE_UNKNOWN_TOAST = "⚠️ Не удалось проверить обновления"
SETTINGS_UPDATE_RUNNING_TOAST = "🚀 Запускаю обновление..."
SETTINGS_UPDATE_ALREADY_LATEST_TOAST = "✅ Обновление не требуется"
SETTINGS_UPDATE_DEBUG_TOAST = "L:{local_version} R:{remote_version}"

UPDATE_NOTIFY_TEXT = (
    "🆕 Найдена новая версия\n\n"
    "Текущая версия: <code>{current_version}</code>\n"
    "Новая версия: <code>{latest_version}</code>"
)
UPDATE_NOTIFY_BTN_UPDATE_NOW = "⬇️ Обновить сейчас"
UPDATE_NOTIFY_BTN_CLOSE = "❌ Закрыть"
UPDATE_NOTIFY_BTN_SNOOZE_WEEK = "🔕 Не уведомлять 7 дней"
UPDATE_NOTIFY_SNOOZE_TOAST = "Уведомления отключены на 7 дней"
UPDATE_NOTIFY_CLOSED_TOAST = "Оповещение закрыто"

AUTO_UPDATE_START_TEXT = (
    "🤖 Автообновление запущено\n\n"
    "Версия: <code>{from_version}</code> → <code>{to_version}</code>."
)
AUTO_UPDATE_DONE_TEXT = (
    "✅ Автообновление завершено\n\n"
    "Текущая версия: <code>{to_version}</code>.\n"
    "Перезапускаю процесс..."
)
AUTO_UPDATE_FAILED_TEXT = "❌ Автообновление не удалось. Проверьте логи."

MANUAL_UPDATE_START_TEXT = (
    "⬇️ Обновление запущено вручную\n\n"
    "Версия: <code>{from_version}</code> → <code>{to_version}</code>."
)
MANUAL_UPDATE_DONE_TEXT = (
    "✅ Обновление установлено\n\n"
    "Текущая версия: <code>{to_version}</code>.\n"
    "Перезапускаю процесс..."
)
MANUAL_UPDATE_FAILED_TEXT = "❌ Обновление не удалось. Проверьте логи."

SETTINGS_STATUS_NO_DATA_TEXT = "⚫ нет данных"
SETTINGS_PARSER_STATUS_OK_TEXT = "🟢 активен"
SETTINGS_PARSER_STATUS_STALE_TEXT = "🟡 давно не было активности"
SETTINGS_PARSER_STATUS_ERROR_TEXT = "🔴 ошибка (см. логи)"

SETTINGS_GEMINI_STATUS_KEY_MISSING_TEXT = "🔴 ключ не задан"
SETTINGS_GEMINI_STATUS_PROXY_MISSING_TEXT = "🟡 без прокси"
SETTINGS_GEMINI_STATUS_OK_TEXT = "🟢 работает"
SETTINGS_GEMINI_STATUS_PROXY_ERROR_TEXT = "🔴 ошибка прокси"
SETTINGS_GEMINI_STATUS_PENDING_TEXT = "🟡 не было проверки"


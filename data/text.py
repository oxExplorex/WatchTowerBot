EMOJI_YES_OR_NO_TEXT = ["✅", "❌"]

START_MESSAGE_TEXT = "Бот запущен. Откройте «⚙️ Настройки» для информации и управления."
NOTICE_ADMINISTRATOR_TO_ACTIVE_BOT = "Бот запущен"

APPS_COUNT_INFO_TEXT = (
    "🔧 Выберите приложение для подключения профиля\n\n"
    "Всего приложений: {_count}\n\n"
    "<code>{date}</code>"
)
ACCOUNT_COUNT_INFO_TEXT = (
    "<b>🗂 Профили доступа</b>\n\n"
    "Аккаунты: {_count}\n"
    "Приложения: {_count_apps}\n\n"
    "<code>{date}</code>"
)

ACCOUNT_EDIT_INFO_TEXT = (
    "<b>Профиль [<code>{user_id}</code>]</b>\n\n"
    "Телефон: {number}\n"
    "Статус: <b>{session_status}</b>\n\n"
    "app_id: {app_id}\n"
    "api_hash: {api_hash}\n\n"
    "Последний успешный чек: {last_update}\n\n"
    "48ч (свежее сверху, шаг 1ч):\n{hours_chart}\n\n"
    "<code>{date}</code>"
)

APPS_ADD_APP_ID_TEXT = "Введите app_id"
APPS_ADD_API_HASH_TEXT = "Введите api_hash"
APPS_ADD_NAME_TAG_TEXT = "Введите название приложения"
APPS_ADD_AGREE_TEXT = (
    "Проверьте данные перед сохранением\n\n"
    "TAG: <b>{_tag_name}</b>\n"
    "APP_ID: <code>{_app_id}</code>\n"
    "API_HASH: <code>{_api_hash}</code>"
)

ACCOUNT_CHOICE_APP_ID_TEXT = "Выберите приложение для добавления профиля"
ACCOUNT_INPUT_NUMBER_TEXT = "Введите номер в формате +79001112233 или 79001112233"
ACCOUNT_INPUT_CODE_TEXT = "Введите код подтверждения из Telegram"
ACCOUNT_INPUT_PASSWORD_TEXT = "Введите пароль 2FA"

WARNING_NOT_APP_TG_ANSWER = "❌ Выход за пределы списка"
WARNING_NOT_ACCOUNT_ANSWER = "❌ Нет аккаунтов"
WARNING_PAGE_EDGE = "❌ Это крайняя страница"
WARNING_NOT_APP_TG = (
    "❌ У вас пока нет приложений.\n"
    "Добавьте хотя бы одно через '<code>{APP_TG_BUTTON}</code>'"
)

ERROR_FORMAT_TEXT = "❌ Неверный формат"
ERROR_ALREADY_APP_TEXT = "Приложение уже существует"
ERROR_DEL_APP_TEXT = "Приложение не существует"
ERROR_NOT_FOUND_APP_ID = "Приложение не найдено"
ERROR_NOT_FOUND_ACCOUNT_ID = "Аккаунт не найден"

SUCCESS_ADD_APP_TEXT = "✅ Приложение добавлено"
SUCCESS_DEL_APP_TEXT = "✅ Приложение удалено"
SUCCESS_ADD_ACCOUNT_TEXT = (
    "✅ Профиль добавлен\n\n"
    "Важно:\n"
    "1) Проверьте настройки профиля\n"
    "2) Если профиль не стартует сразу - перезапустите бота"
)
SUCCESS_DEL_ACCOUNT_TEXT = "✅ Профиль удалён"

ACCOUNTS_USER_KEYBOARD = ["👤 Аккаунты"]
APP_TG_USER_KEYBOARD = ["📱 Приложения"]
PROXY_USER_KEYBOARD = ["🛰 Прокси"]
SETTINGS_BOT_KEYBOARD = [
    "📉 Моя статистика",
    "📊 Общая статистика",
    "⚙️ Настройки",
]
RESTART_BOT_W_KEYBOARD = ["🔄 Перезапуск бота"]

# Generic actions
ACTION_CANCEL_TEXT = "Отмена"
ACTION_CANCELLED_TEXT = "Отменено"
ACTION_CANCEL_COMMAND = "/cancel"
ACTION_CONFIRM_TEXT = "✅ Подтвердить"
ACTION_REFRESH_TEXT = "🔄 Обновить"
ACTION_BACK_TEXT = "⬅️ Назад"
ACTION_PAGE_PREV_TEXT = "◀️"
ACTION_PAGE_NEXT_TEXT = "▶️"

# Account/session texts
ACCOUNT_STATUS_ENABLED_TEXT = "✅ включен"
ACCOUNT_STATUS_DISABLED_TEXT = "⛔ выключен"
ACCOUNT_RUNTIME_ONLINE_TEXT = "🟢 online"
ACCOUNT_RUNTIME_OFFLINE_TEXT = "⚫ offline"
ACCOUNT_NO_DATA_TEXT = "нет данных"
ACCOUNT_SESSION_ENABLED_TOAST = "Профиль включен. Если не стартует автоматически, сделайте перезапуск бота."
ACCOUNT_SESSION_REMOVED_NO_FILE_TOAST = "Профиль удалён: отсутствуют файлы сессии"
ACCOUNT_SESSION_NOT_RUNNING_TOAST = "Профиль не запущен в runtime"
ACCOUNT_SESSION_RESPONDS_TOAST = "Профиль отвечает"
ACCOUNT_SESSION_INVALID_REMOVED_TOAST = "Профиль невалиден и удалён"
ACCOUNT_CHECK_ERROR_TOAST = "Ошибка проверки: {error}"
ACCOUNT_INVALID_REMOVED_TEXT = (
    "⚠️ Профиль стал невалидным и удалён.\n"
    "Запись убрана из базы и из runtime. Добавьте профиль заново."
)

ACCOUNT_ADD_SESSION_BUSY_TEXT = (
    "Файл сессии занят другим процессом. "
    "Остановите прошлую попытку и повторите вход через 1-2 секунды."
)
ACCOUNT_ADD_CODE_EXPIRED_TEXT = "Код авторизации истек. Введите номер телефона заново."
ACCOUNT_ADD_ERROR_PREFIX = "Ошибка"

# Spoiler / ttl media texts
SPOILER_STATUS_TEXT = (
    "⏳ Обнаружено временное сообщение\n"
    "Профиль: {session}\n"
    "От: {sender}\n"
    "Чат: {chat}\n\n"
    "Скачиваю медиа..."
)
SPOILER_DOWNLOAD_FAILED_TEXT = "⚠️ Временное сообщение обнаружено, но скачать медиа не удалось."
SPOILER_SAVED_CAPTION_TEXT = (
    "🕒 Временное медиа сохранено\n"
    "Профиль: {session}\n"
    "От: {sender}\n"
    "Чат: {chat}"
)
SPOILER_PROCESSING_ERROR_TEXT = "⚠️ Ошибка при обработке временного сообщения."

# Gemini helper texts
GEMINI_UNAVAILABLE_TEXT = "Gemini is unavailable. Check API key/logs."
GEMINI_THINKING_TEXT = "Thinking about your text..."
GEMINI_ANALYZING_VIDEO_TEXT = "Analyzing video..."
GEMINI_ANALYZING_AUDIO_TEXT = "Analyzing audio..."
GEMINI_ANALYZING_STICKER_TEXT = "Analyzing sticker..."
GEMINI_ANALYZING_PHOTO_TEXT = "Analyzing photo..."
GEMINI_ANALYZING_CONTENT_TEXT = "Analyzing content..."

# Proxy/restart texts
PROXY_MENU_PROMPT_TEXT = (
    "<b>🌐 Gemini прокси</b>\n\n"
    "Текущий: <code>{proxy}</code>\n"
    "Статус: <b>{status}</b>\n"
    "Последняя проверка: <code>{checked_at}</code>\n"
    "Последняя ошибка: <code>{error}</code>\n\n"
    "<blockquote>Бот может работать и без прокси, но для Gemini в вашем регионе может потребоваться VPN/HTTP-прокси.</blockquote>\n\n"
    "Отправьте новый HTTP-прокси:\n"
    "• <code>ip:port:user:password</code>\n"
    "• <code>ip:port@user:password</code>\n"
    "• <code>http://user:password@ip:port</code>\n\n"
    "Чтобы отключить прокси, отправьте <code>0</code>."
)
PROXY_SET_TEXT = "✅ Прокси сохранен и включен"
PROXY_DISABLED_TEXT = "✅ Прокси отключен. Gemini попробует работать без него."
PROXY_INVALID_FORMAT_TEXT = "❌ Формат прокси некорректный. Поддерживаются только HTTP: ip:port:user:password, ip:port@user:password или http://user:password@ip:port"
RESTARTING_TEXT = "Перезапускаю..."

# Parser/runtime notifications
PARSER_SESSION_DROPPED_TEXT = (
    "⚠️ Профиль отключён: Telegram вернул ошибку авторизации.\n"
    "Номер: <code>{number}</code>\n"
    "Запись удалена из базы. Добавьте профиль заново."
)
PARSER_UNKNOWN_ERROR_TEXT = "Ошибка"

# Chat log templates
CHAT_LOG_NEW_TEXT = "💬 {chat_name} новый чат:\n  └  <code>{chat_id}</code> {link_id} | @{username}\n"
CHAT_LOG_DELETED_TEXT = "❌ {chat_name} удалён чат:\n  └  <code>{chat_id}</code> {link_id} | @{username}\n"

# Settings/statistics
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
    "<b>⚙️ Настройки</b>\n\n"
    "Версия бота: <code>{bot_version}</code>\n"
    "Статус версии: <b>{version_state}</b>\n"
    "Последняя проверка: <b>{last_check_ago}</b> мин назад\n\n"
    "Парсер чатов: <b>{parser_status}</b>\n"
    "Gemini: <b>{gemini_status}</b>\n"
    "Прокси Gemini: <b>{proxy_status}</b>\n\n"
    "<code>{date}</code>"
)
VERSION_STATE_UNKNOWN = "⚪ Неизвестно"
VERSION_STATE_UP_TO_DATE = "✅ Актуальная"
VERSION_STATE_UPDATE_AVAILABLE = "🆕 Доступна: {latest_version}"
AUTO_UPDATE_ON_TEXT = "🟢 Включено"
AUTO_UPDATE_OFF_TEXT = "🔴 Выключено"
SETTINGS_BTN_AUTO_UPDATE = "🤖 Автообновление: {state}"
SETTINGS_BTN_RUN_UPDATE = "⬇️ Обновиться"
SETTINGS_BTN_TIMEZONE = "🕓 Часовой пояс: {tz_label}"
SETTINGS_BTN_RESTART = "♻️ Перезагрузить"
SETTINGS_BTN_CLOSE = "❌ Закрыть"
SETTINGS_BTN_CHECK_UPDATE = "🔎 Проверить"
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
# Keyboard labels
ACCOUNT_EDIT_BTN_SESSION = "Сессия {state}"
ACCOUNT_EDIT_BTN_NEW_CHATS = "Новые чаты {state}"
ACCOUNT_EDIT_BTN_DEL_CHATS = "Удалённые чаты {state}"
ACCOUNT_EDIT_BTN_BOTS = "Боты/каналы {state}"
ACCOUNT_EDIT_BTN_SPOILER_MEDIA = "TTL/спойлер-вложения {state}"
ACCOUNT_EDIT_BTN_CHECK_NOW = "🧪 Проверить сейчас"
ACCOUNT_EDIT_BTN_DELETE = "🗑 Удалить"

ACCOUNT_MENU_UNKNOWN_NAME = "Unknown"
ACCOUNT_MENU_ACTIVE_ICON = "🟢"
ACCOUNT_MENU_INACTIVE_ICON = "⛔"
ACCOUNT_MENU_TITLE = "{status} {name} [{user_id}]"

APPS_MENU_ADD = "➕ Добавить приложение"
APPS_MENU_USE = "🧩 {tag_name} [{app_id}] • профилей: {linked_count}"
APPS_MENU_DELETE = "🗑 Удалить"

SETTINGS_BTN_PROXY = "🌐 Прокси: {state}"
SETTINGS_BTN_PROXY_CHECK = "🧪 Проверить прокси"
PROXY_CHECK_OK_TEXT = "✅ Прокси работает"
PROXY_CHECK_FAIL_TEXT = "❌ Прокси не работает: {reason}"
PROXY_CHECK_SKIPPED_NO_PROXY_TEXT = "ℹ️ Прокси выключен. Проверять нечего."

GEMINI_PROXY_REQUIRED_TEXT = "ℹ️ Прокси для Gemini не задан. Пробую работать напрямую."
GEMINI_PROXY_INVALID_TEXT = "❌ Формат прокси некорректный. Обновите прокси в настройках."
GEMINI_PROXY_DOWN_TEXT = "❌ Gemini временно недоступен: прокси не отвечает."
GEMINI_PROXY_AUTO_DISABLED_TEXT = "⚠️ Gemini-прокси автоматически отключен. Причина: <code>{reason}</code>"


# Shared status/log labels (moved from code)
PARSER_LOG_NEW_CHAT_TEXT = "USER: {user_id} | Новый чат {chat_id} @{username} | {chat_name}"
PARSER_LOG_DELETED_CHAT_TEXT = "USER: {user_id} | Удалённый чат {chat_id} @{username} | {chat_name}"

PROXY_STATUS_DISABLED_TEXT = "🔴 выключен"
PROXY_STATUS_OK_TEXT = "🟢 работает"
PROXY_STATUS_PENDING_TEXT = "🟡 требует проверки"
PROXY_NOT_SET_TEXT = "не задан"
PROXY_MENU_NO_DATA_TEXT = "нет данных"
PROXY_GEMINI_KEY_EMPTY_TEXT = "GEMINI_KEY пустой"

SETTINGS_STATUS_NO_DATA_TEXT = "⚫ нет данных"
SETTINGS_PARSER_STATUS_OK_TEXT = "🟢 работает"
SETTINGS_PARSER_STATUS_STALE_TEXT = "🟡 давно не проверялся"
SETTINGS_PARSER_STATUS_ERROR_TEXT = "🔴 ошибка"

SETTINGS_GEMINI_STATUS_KEY_MISSING_TEXT = "🔴 ключ не задан"
SETTINGS_GEMINI_STATUS_PROXY_MISSING_TEXT = "🟡 без прокси"
SETTINGS_GEMINI_STATUS_OK_TEXT = "🟢 работает"
SETTINGS_GEMINI_STATUS_PROXY_ERROR_TEXT = "🔴 ошибка прокси"
SETTINGS_GEMINI_STATUS_PENDING_TEXT = "🟡 не проверен"

SETTINGS_PROXY_STATE_OFF_TEXT = "🔴 выключен"
SETTINGS_PROXY_STATE_OK_TEXT = "🟢 ok"
SETTINGS_PROXY_STATE_PENDING_TEXT = "🟡 check"

GEMINI_PROMPT_ADMIN_PLACEHOLDER = "[Здесь перечислить user_id через запятую]"

GEMINI_TEST_PROMPT_TEXT = "Привет, напиши небольшой рассказ на любую тему в пределах 1000 символов"

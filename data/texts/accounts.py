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

ACCOUNT_INPUT_NUMBER_TEXT = "Введите номер в формате +79001112233 или 79001112233"
ACCOUNT_INPUT_CODE_TEXT = "Введите код подтверждения из Telegram"
ACCOUNT_INPUT_PASSWORD_TEXT = "Введите пароль 2FA"

ACCOUNTS_USER_KEYBOARD = ["👤 Аккаунты", "🔍 Поиск чата"]
CHAT_HISTORY_SEARCH_PROMPT_TEXT = "Введите chat_id или @username"
CHAT_HISTORY_SEARCH_EMPTY_TEXT = "История по запросу не найдена"
CHAT_HISTORY_SEARCH_USAGE_TEXT = "Пример: 123456789 или @username"
CHAT_HISTORY_UNKNOWN_TEXT = "unknown"
CHAT_HISTORY_ACTION_FOUND_TEXT = "✅ чат найден"
CHAT_HISTORY_ACTION_CLEARED_TEXT = "🧹 чат очищен"
CHAT_HISTORY_ACTION_FORMAT_TEXT = "action:{action_id}"
CHAT_HISTORY_BLOCK_TITLE_TEXT = "<b>История чата</b>"
CHAT_HISTORY_QUERY_FORMAT_TEXT = "query: <code>{query}</code>"
CHAT_HISTORY_MATCHES_FORMAT_TEXT = "matches: {count}"
CHAT_HISTORY_PRESENCE_TITLE_TEXT = "<b>Сейчас в чатах</b>"
CHAT_HISTORY_PRESENCE_FOUND_FORMAT_TEXT = "user_id <code>{chat_id}</code> ({chat_label}) | есть у: {holders}"
CHAT_HISTORY_PRESENCE_MISSING_FORMAT_TEXT = "user_id <code>{chat_id}</code> ({chat_label}) | сейчас ни у одного аккаунта"
CHAT_HISTORY_EVENT_FORMAT_TEXT = "{stamp} | {action_label} | user_id <code>{chat_id}</code> | account {account_label}"

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

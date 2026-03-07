EMOJI_YES_OR_NO_TEXT = ["✅", "❌"]

START_MESSAGE_TEXT = (
    "Панель управления\n\n"
    "Версия: <code>{version}</code> ({version_status})\n\n"
    "Последняя проверка: <code>{last_check}</code> (~<code>{last_check_sec}</code> сек)\n"
)
NOTICE_ADMINISTRATOR_TO_ACTIVE_BOT = "Бот запущен"

APPS_COUNT_INFO_TEXT = "Всего приложений: {_count}\n\n<code>{date}</code>"
ACCOUNT_COUNT_INFO_TEXT = (
    "<b>Сессии Telegram</b>\n\n"
    "Аккаунты: {_count}\n"
    "Приложения: {_count_apps}\n\n"
    "<code>{date}</code>"
)

ACCOUNT_EDIT_INFO_TEXT = (
    "<b>Сессия [<code>{user_id}</code>]</b>\n\n"
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
APPS_ADD_NAME_TAG_TEXT = "Введите tag приложения"
APPS_ADD_AGREE_TEXT = (
    "Проверьте данные перед сохранением\n\n"
    "TAG: <b>{_tag_name}</b>\n"
    "APP_ID: <code>{_app_id}</code>\n"
    "API_HASH: <code>{_api_hash}</code>"
)

ACCOUNT_CHOICE_APP_ID_TEXT = "Выберите приложение"
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
    "✅ Аккаунт добавлен\n\n"
    "Важно:\n"
    "1) Проверьте настройки сессии\n"
    "2) Если сессия не стартует сразу - перезапустите бота"
)
SUCCESS_DEL_ACCOUNT_TEXT = "✅ Аккаунт удалён"

ACCOUNTS_USER_KEYBOARD = ["👤 Аккаунты"]
APP_TG_USER_KEYBOARD = ["📱 Приложения"]
PROXY_USER_KEYBOARD = ["🛰 Прокси"]
SETTINGS_BOT_KEYBOARD = [
    "📉 Моя статистика",
    "📊 Общая статистика",
]
RESTART_BOT_W_KEYBOARD = ["🔄 Перезапуск (Win)"]

# Generic actions
ACTION_CANCEL_TEXT = "Отмена"
ACTION_CANCELLED_TEXT = "Отменено"
ACTION_CONFIRM_TEXT = "✅ Подтвердить"
ACTION_REFRESH_TEXT = "🔄 Обновить"
ACTION_BACK_TEXT = "⬅️ Назад"
ACTION_PAGE_PREV_TEXT = "◀️"
ACTION_PAGE_NEXT_TEXT = "▶️"

# Account/session texts
ACCOUNT_STATUS_ENABLED_TEXT = "✅ включена"
ACCOUNT_STATUS_DISABLED_TEXT = "⛔ выключена"
ACCOUNT_RUNTIME_ONLINE_TEXT = "🟢 online"
ACCOUNT_RUNTIME_OFFLINE_TEXT = "⚫ offline"
ACCOUNT_NO_DATA_TEXT = "нет данных"
ACCOUNT_SESSION_ENABLED_TOAST = "Сессия включена. Если не стартует автоматически, сделайте перезапуск бота."
ACCOUNT_SESSION_REMOVED_NO_FILE_TOAST = "Сессия удалена: отсутствуют файлы сессии"
ACCOUNT_SESSION_NOT_RUNNING_TOAST = "Сессия не запущена в runtime"
ACCOUNT_SESSION_RESPONDS_TOAST = "Сессия отвечает"
ACCOUNT_SESSION_INVALID_REMOVED_TOAST = "Сессия невалидна и удалена"
ACCOUNT_CHECK_ERROR_TOAST = "Ошибка проверки: {error}"
ACCOUNT_INVALID_REMOVED_TEXT = (
    "⚠️ Сессия стала невалидной и удалена.\n"
    "Запись убрана из базы и из runtime. Добавьте аккаунт заново."
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
    "Сессия: {session}\n"
    "От: {sender}\n"
    "Чат: {chat}\n\n"
    "Скачиваю медиа..."
)
SPOILER_DOWNLOAD_FAILED_TEXT = "⚠️ Временное сообщение обнаружено, но скачать медиа не удалось."
SPOILER_SAVED_CAPTION_TEXT = (
    "🕒 Временное медиа сохранено\n"
    "Сессия: {session}\n"
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
    "Введите прокси для работы с Gemini\n\n"
    "Формат: {ip}:{port}:{user}:{password}\n"
    "Или отправьте 0 для отключения"
)
PROXY_SET_TEXT = "Прокси установлены"
PROXY_DISABLED_TEXT = "Прокси выключены"
PROXY_INVALID_FORMAT_TEXT = "Неверный формат прокси"
RESTARTING_TEXT = "Перезапускаю..."

# Parser/runtime notifications
PARSER_SESSION_DROPPED_TEXT = (
    "⚠️ Сессия аккаунта отключена: Telegram вернул ошибку авторизации.\n"
    "Номер: <code>{number}</code>\n"
    "Запись удалена из базы. Добавьте аккаунт заново."
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
    "{by_hour_text}\n\n"
    "<b>14д (свежее → старее, шаг 1д)</b>\n"
    "{by_day_text}\n\n"
    "<b>Последние сбои</b>\n"
    "{recent_failures}\n\n"
    "Легенда: 🟩 стабильно, 🟨 редкие сбои, 🟥 частые сбои, ⬛ нет данных"
)

# Keyboard labels
ACCOUNT_EDIT_BTN_SESSION = "Сессия {state}"
ACCOUNT_EDIT_BTN_NEW_CHATS = "Новые чаты {state}"
ACCOUNT_EDIT_BTN_DEL_CHATS = "Удалённые чаты {state}"
ACCOUNT_EDIT_BTN_BOTS = "Боты/каналы {state}"
ACCOUNT_EDIT_BTN_SPOILER_MEDIA = "TTL/спойлер-вложения {state}"
ACCOUNT_EDIT_BTN_CHECK_NOW = "🧪 Проверить сейчас"
ACCOUNT_EDIT_BTN_DELETE = "🗑 Удалить сессию"

ACCOUNT_MENU_UNKNOWN_NAME = "Unknown"
ACCOUNT_MENU_ACTIVE_ICON = "🟢"
ACCOUNT_MENU_INACTIVE_ICON = "⛔"
ACCOUNT_MENU_TITLE = "{status} {name} [{user_id}]"

APPS_MENU_ADD = "➕ Добавить приложение"
APPS_MENU_USE = "🔑 Использовать | {tag_name} [{app_id}]"
APPS_MENU_DELETE = "🗑 Удалить"

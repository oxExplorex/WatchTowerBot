SPOILER_STATUS_TEXT = (
    "⏳ <b>Сохраняю временное вложение…</b>\n\n"
    "<b>Отправитель:</b> {sender}\n"
    "<b>Чат:</b> {chat}\n"
    "<b>Аккаунт:</b> {session}"
)
SPOILER_DOWNLOAD_FAILED_TEXT = "⚠️ Временное сообщение обнаружено, но скачать медиа не удалось."
SPOILER_SAVED_CAPTION_TEXT = (
    "🕒 <b>{media} сохранено</b>\n\n"
    "<b>Отправитель:</b> {sender}\n"
    "<b>Чат:</b> {chat}\n"
    "<b>Аккаунт:</b> {session}"
)
SPOILER_MEDIA_TITLES = {
    "photo": "Временное фото",
    "video": "Временное видео",
    "video_note": "Временное видеосообщение",
}
SPOILER_PROCESSING_ERROR_TEXT = "⚠️ Ошибка при обработке временного сообщения."

PARSER_SESSION_DROPPED_TEXT = (
    "⚠️ Профиль отключён: Telegram вернул ошибку авторизации.\n"
    "Номер: <code>{number}</code>\n"
    "Запись удалена из базы. Добавьте профиль заново."
)
PARSER_UNKNOWN_ERROR_TEXT = "Ошибка"

CHAT_LOG_NEW_TEXT = "💬 {chat_name} новый чат:\n  └  <code>{chat_id}</code> {link_id} | @{username}\n"
CHAT_LOG_DELETED_TEXT = "❌ {chat_name} удалён чат:\n  └  <code>{chat_id}</code> {link_id} | @{username}\n"
PARSER_LOG_NEW_CHAT_TEXT = "USER: {user_id} | Новый чат {chat_id} @{username} | {chat_name}"
PARSER_LOG_DELETED_CHAT_TEXT = "USER: {user_id} | Удалённый чат {chat_id} @{username} | {chat_name}"


import data.text as constant_text


def get_user_log_text(action_id, chat_id, username, chat_name):
    link_id = f"tg://user?id={chat_id}"
    if action_id == 1:
        return constant_text.CHAT_LOG_NEW_TEXT.format(chat_name=chat_name, chat_id=chat_id, link_id=link_id, username=username)
    if action_id == 2:
        return constant_text.CHAT_LOG_DELETED_TEXT.format(chat_name=chat_name, chat_id=chat_id, link_id=link_id, username=username)
    return "error"

"""Edit navigation screens; replace a panel only when Telegram cannot edit it."""
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InputMediaPhoto


async def _edit_or_replace(message, text, reply_markup, *, message_id=None):
    try:
        if message_id is None:
            return await message.edit_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
        return await message.bot.edit_message_text(
            chat_id=message.chat.id, message_id=message_id, text=text,
            reply_markup=reply_markup, parse_mode="HTML",
        )
    except TelegramBadRequest as exc:
        reason = exc.message.lower()
        if "message is not modified" in reason:
            return None
        if not any(value in reason for value in (
            "message to edit not found", "message can't be edited", "message cannot be edited",
            "there is no text in the message to edit",
        )):
            raise
        panel = await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
        if "there is no text in the message to edit" in reason:
            # A photo cannot become a text message. Deliver the replacement first.
            try:
                await message.bot.delete_message(message.chat.id, message_id or message.message_id)
            except TelegramBadRequest:
                pass
        return panel


async def edit_panel(message, text, reply_markup=None):
    return await _edit_or_replace(message, text, reply_markup)


async def chart_panel(message, image, caption, reply_markup, *, edit):
    photo = BufferedInputFile(image, filename="runtime-health.png")
    if edit:
        try:
            return await message.bot.edit_message_media(
                chat_id=message.chat.id, message_id=message.message_id,
                media=InputMediaPhoto(media=photo, caption=caption, parse_mode="HTML"), reply_markup=reply_markup)
        except TelegramBadRequest as exc:
            if "message is not modified" in exc.message.lower():
                return None
            if not any(reason in exc.message.lower() for reason in (
                    "message to edit not found", "message can't be edited", "message cannot be edited")):
                raise
    return await message.answer_photo(photo, caption=caption, parse_mode="HTML", reply_markup=reply_markup)


async def remember_panel(state, message):
    await state.update_data(panel_message_id=message.message_id)


async def edit_input_panel(message, state, text, reply_markup=None):
    """Text input is a separate user message; its wizard panel stays in place."""
    data = await state.get_data()
    message_id = data.get("panel_message_id")
    if message_id is None:
        panel = await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        panel = await _edit_or_replace(message, text, reply_markup, message_id=message_id)
    if type(getattr(panel, "message_id", None)) is int:
        await remember_panel(state, panel)
    return panel


async def clear_panel_state(state):
    data = await state.get_data()
    await state.clear()
    if type(data.get("panel_message_id")) is int:
        await state.update_data(panel_message_id=data["panel_message_id"])

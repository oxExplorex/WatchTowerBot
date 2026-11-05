from keyboards.inline.navigation import navigation_keyboard


def back_inline(back_callback="panel:home"):
    return navigation_keyboard(back_callback)

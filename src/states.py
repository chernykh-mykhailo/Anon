from aiogram.fsm.state import State, StatesGroup


class Form(StatesGroup):
    writing_message = State()
    confirming_media = State()
    customizing_draw = State()
    setting_cooldown = State()

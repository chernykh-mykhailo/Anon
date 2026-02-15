from aiogram.fsm.state import State, StatesGroup


class Form(StatesGroup):
    writing_message = State()

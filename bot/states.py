from aiogram.fsm.state import State, StatesGroup


class CreateQuiz(StatesGroup):
    title = State()
    description = State()
    questions = State()
    timer = State()
    shuffle = State()


class ImportQuiz(StatesGroup):
    file = State()


class AdminState(StatesGroup):
    broadcast = State()
    broadcast_confirm = State()

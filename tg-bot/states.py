from aiogram.fsm.state import State, StatesGroup


class AddLocation(StatesGroup):
    asking_name       = State()
    asking_category   = State()
    asking_address    = State()
    asking_hours      = State()
    asking_price      = State()
    asking_promotions = State()
    asking_comment    = State()


class JoinList(StatesGroup):
    entering_code = State()


class RateVisit(StatesGroup):
    asking_rating     = State()
    asking_impression = State()

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

PAGE_SIZE = 20
MAX_LIST_ITEMS = 30

CATEGORIES = ["🍕 Кафе/Ресторан", "☕️ Кофейня", "🍺 Бар", "🎭 Культура/Музей",
               "🛍 Шоппинг", "🌿 Природа/Парк", "🎮 Развлечения", "✂️ Другое"]

STARS = {1: "⭐️", 2: "⭐️⭐️", 3: "⭐️⭐️⭐️", 4: "⭐️⭐️⭐️⭐️", 5: "⭐️⭐️⭐️⭐️⭐️"}


def format_location(row, show_author: bool = False) -> str:
    # id, list_id, added_by, added_by_name, name, category,
    # address, hours, avg_price, promotions, comment,
    # visited, rating, impression, latitude, longitude
    (loc_id, _, _, added_by_name, name, category,
     address, hours, avg_price, promotions, comment,
     visited, rating, impression, lat, lon) = row

    parts = []
    visited_mark = " ✅" if visited else ""
    if show_author:
        parts.append(f"👤 *Добавил:* {added_by_name}")
    parts.append(f"📍 *{name}*{visited_mark}")
    if category:   parts.append(f"🏷 {category}")
    if address:    parts.append(f"🗺 {address}")
    if hours:      parts.append(f"🕐 {hours}")
    if avg_price:  parts.append(f"💰 {avg_price}")
    if promotions: parts.append(f"🎁 {promotions}")
    if comment:    parts.append(f"💬 *{comment}*")
    if visited and rating:
        parts.append(f"\n🌟 *Оценка:* {STARS.get(rating, rating)}")
    if visited and impression:
        parts.append(f"📝 *Впечатление:* {impression}")
    return "\n".join(parts)


def nav_keyboard(
    index: int, total: int, loc_id: int, visited: bool, tab: str = "plan"
) -> InlineKeyboardMarkup:
    nav_row = []
    if index > 0:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"nav:{index-1}:{tab}"))
    nav_row.append(InlineKeyboardButton(text=f"{index+1} / {total}", callback_data="noop"))
    if index < total - 1:
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"nav:{index+1}:{tab}"))

    if visited:
        action_row = [
            InlineKeyboardButton(text="↩️ Не посещено", callback_data=f"unvisit:{loc_id}:{index}:{tab}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"confirm_delete:{loc_id}:{index}:{tab}"),
        ]
    else:
        action_row = [
            InlineKeyboardButton(text="✅ Посетил!", callback_data=f"start_rate:{loc_id}:{index}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"confirm_delete:{loc_id}:{index}:{tab}"),
        ]

    tabs_row = [
        InlineKeyboardButton(
            text="🗺 Куда идём" + (" ←" if tab == "plan" else ""),
            callback_data="tab:plan:0"
        ),
        InlineKeyboardButton(
            text="✅ Сходили" + (" ←" if tab == "done" else ""),
            callback_data="tab:done:0"
        ),
    ]
    list_row = [InlineKeyboardButton(text="📋 Весь список", callback_data=f"show_all:{tab}:0")]
    return InlineKeyboardMarkup(inline_keyboard=[nav_row, action_row, tabs_row, list_row])


def rating_keyboard(loc_id: int, index: int) -> InlineKeyboardMarkup:
    stars_row = [
        InlineKeyboardButton(text=f"{i}⭐", callback_data=f"rate:{loc_id}:{index}:{i}")
        for i in range(1, 6)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[stars_row])


def confirm_delete_keyboard(loc_id: int, index: int, tab: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delete:{loc_id}:{index}:{tab}"),
        InlineKeyboardButton(text="↩️ Отмена", callback_data=f"nav:{index}:{tab}"),
    ]])


def skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_field")]
    ])


def category_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=cat, callback_data=f"set_category:{cat}")]
        for cat in CATEGORIES
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def skip_impression_keyboard(loc_id: int, index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"skip_impression:{loc_id}:{index}")
    ]])


def all_list_keyboard(tab: str, page: int, total_pages: int) -> InlineKeyboardMarkup | None:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"show_all:{tab}:{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"show_all:{tab}:{page+1}"))
    rows = [nav] if nav else []
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None

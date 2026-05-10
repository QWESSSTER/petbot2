from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

MAX_LIST_ITEMS = 30  # Telegram message limit guard


def format_location(row, show_author: bool = False) -> str:
    loc_id, _, _, added_by_name, name, address, hours, avg_price, promotions, comment, visited = row
    parts = []
    visited_mark = " ✅" if visited else ""
    if show_author:
        parts.append(f"👤 *Добавил:* {added_by_name}")
    parts.append(f"📍 *{name}*{visited_mark}")
    if address:    parts.append(f"🗺 {address}")
    if hours:      parts.append(f"🕐 {hours}")
    if avg_price:  parts.append(f"💰 {avg_price}")
    if promotions: parts.append(f"🎁 {promotions}")
    if comment:    parts.append(f"💬 *{comment}*")
    return "\n".join(parts)


def nav_keyboard(
    index: int, total: int, loc_id: int, visited: bool
) -> InlineKeyboardMarkup:
    nav_row = []
    if index > 0:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"nav:{index-1}"))
    nav_row.append(InlineKeyboardButton(text=f"{index+1} / {total}", callback_data="noop"))
    if index < total - 1:
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"nav:{index+1}"))

    visited_label = "❌ Не посещено" if visited else "✅ Посещено"
    action_row = [
        InlineKeyboardButton(text=visited_label, callback_data=f"visited:{loc_id}:{index}"),
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"confirm_delete:{loc_id}:{index}"),
    ]
    list_row = [InlineKeyboardButton(text="📋 Весь список", callback_data="show_all:0")]
    return InlineKeyboardMarkup(inline_keyboard=[nav_row, action_row, list_row])


def confirm_delete_keyboard(loc_id: int, index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delete:{loc_id}:{index}"),
        InlineKeyboardButton(text="↩️ Отмена", callback_data=f"nav:{index}"),
    ]])


def skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_field")]
    ])


def all_list_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"show_all:{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"show_all:{page+1}"))
    rows = [nav] if nav else []
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None

import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext

from states import AddLocation, JoinList
from database import (
    get_or_create_list, get_user_list_id, get_locations,
    add_location_db, delete_location_db, toggle_visited_db,
    is_shared_list, join_list_db, get_list_members,
)
from formatting import (
    format_location, nav_keyboard, confirm_delete_keyboard,
    skip_keyboard, all_list_keyboard, MAX_LIST_ITEMS,
)
from ai import extract_from_image

PAGE_SIZE = 20

FIELD_ORDER = ["name", "address", "hours", "avg_price", "promotions", "comment"]

FIELD_PROMPTS = {
    "name":       ("📍 Как называется это место?",         False),
    "address":    ("🗺 Введи адрес:",                       True),
    "hours":      ("🕐 Часы работы (напр. 10:00–22:00):",  True),
    "avg_price":  ("💰 Средний чек (напр. ~1500 ₽):",      True),
    "promotions": ("🎁 Акции и предложения (кратко):",      True),
    "comment":    ("💬 Хочешь добавить комментарий?",       True),
}

FIELD_STATES = {
    "name":       AddLocation.asking_name,
    "address":    AddLocation.asking_address,
    "hours":      AddLocation.asking_hours,
    "avg_price":  AddLocation.asking_price,
    "promotions": AddLocation.asking_promotions,
    "comment":    AddLocation.asking_comment,
}


def _get_username(user) -> str:
    return user.first_name or user.username or "Пользователь"


async def _notify_members(bot: Bot, list_id: str, exclude_id: int, text: str):
    members = await get_list_members(list_id)
    tasks = [
        bot.send_message(mid, text, parse_mode="Markdown")
        for mid in members if mid != exclude_id
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            pass  # Пользователь заблокировал бота — игнорируем


async def ask_next_missing(target: Message | CallbackQuery, state: FSMContext):
    data = await state.get_data()
    loc = data.get("location", {})
    msg = target.message if isinstance(target, CallbackQuery) else target

    for field in FIELD_ORDER:
        if loc.get(field) is None:
            prompt, skippable = FIELD_PROMPTS[field]
            await state.set_state(FIELD_STATES[field])
            kb = skip_keyboard() if skippable else None
            await msg.answer(prompt, reply_markup=kb)
            return

    await finalize_location(target, state)


async def finalize_location(target: Message | CallbackQuery, state: FSMContext):
    data = await state.get_data()
    loc = data["location"]
    user_id = data["user_id"]
    username = data["username"]
    bot: Bot = target.bot

    list_id = await get_user_list_id(user_id) or await get_or_create_list(user_id, username)
    await add_location_db(list_id, user_id, username, loc)

    await _notify_members(
        bot, list_id, user_id,
        f"🔔 *{username}* добавил новое место:\n\n📍 *{loc.get('name', '—')}*"
    )

    locations = await get_locations(list_id)
    index = len(locations) - 1
    row = locations[index]
    shared = await is_shared_list(list_id)
    text = "✅ *Место сохранено!*\n\n" + format_location(row, show_author=shared)

    msg = target.message if isinstance(target, CallbackQuery) else target
    await msg.answer(
        text,
        reply_markup=nav_keyboard(index, len(locations), row[0], bool(row[10])),
        parse_mode="Markdown",
    )
    await state.clear()


def register_handlers(dp: Dispatcher):

    @dp.message(CommandStart())
    async def cmd_start(message: Message):
        user_id = message.from_user.id
        username = _get_username(message.from_user)
        list_id = await get_or_create_list(user_id, username)
        await message.answer(
            f"👋 Привет, *{username}*!\n\n"
            f"Я помогаю собирать места, которые хочется посетить.\n\n"
            f"Просто пришли *скриншот* (сторис, пост) или напиши *название места* — "
            f"я извлеку всю информацию и сохраню.\n\n"
            f"🔑 Твой код списка: `{list_id}`\n\n"
            f"*Команды:*\n"
            f"/list — листать список\n"
            f"/share — поделиться списком\n"
            f"/join — подключиться к чужому списку\n"
            f"/help — помощь\n"
            f"/cancel — отменить текущее действие",
            parse_mode="Markdown",
        )

    @dp.message(Command("help"))
    async def cmd_help(message: Message):
        await message.answer(
            "*Как пользоваться ботом:*\n\n"
            "📸 *Добавить место из фото* — пришли скриншот из Instagram/Stories, я сам распознаю название и адрес.\n\n"
            "✏️ *Добавить текстом* — просто напиши название места и я спрошу детали.\n\n"
            "📋 */list* — листать сохранённые места (◀️ / ▶️ или введи номер).\n\n"
            "🔗 */share* — получить код для совместного списка.\n\n"
            "👥 */join* — подключиться к списку друга по коду.\n\n"
            "✅ *Отметить посещённым* — кнопка в карточке места.\n\n"
            "🗑 *Удалить* — кнопка в карточке (с подтверждением).",
            parse_mode="Markdown",
        )

    @dp.message(Command("cancel"))
    async def cmd_cancel(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("❌ Действие отменено.")

    @dp.message(Command("list"))
    async def cmd_list(message: Message):
        user_id = message.from_user.id
        list_id = await get_user_list_id(user_id)
        if not list_id:
            await message.answer("Сначала запусти бота — /start")
            return
        locations = await get_locations(list_id)
        if not locations:
            await message.answer("📭 Список пуст. Пришли скриншот или название места!")
            return
        shared = await is_shared_list(list_id)
        row = locations[0]
        await message.answer(
            format_location(row, show_author=shared),
            reply_markup=nav_keyboard(0, len(locations), row[0], bool(row[10])),
            parse_mode="Markdown",
        )

    @dp.message(Command("share"))
    async def cmd_share(message: Message):
        user_id = message.from_user.id
        list_id = await get_user_list_id(user_id)
        await message.answer(
            f"🔗 Поделись этим кодом с другом:\n\n`{list_id}`\n\n"
            f"Друг пишет /join и вводит этот код — после этого вы видите общий список, "
            f"а рядом с каждым местом появляется имя того, кто его добавил.",
            parse_mode="Markdown",
        )

    @dp.message(Command("join"))
    async def cmd_join(message: Message, state: FSMContext):
        await state.set_state(JoinList.entering_code)
        await message.answer("Введи код списка:")

    @dp.message(JoinList.entering_code)
    async def process_join_code(message: Message, state: FSMContext):
        code = message.text.strip().upper()
        user_id = message.from_user.id
        username = _get_username(message.from_user)
        if await join_list_db(code, user_id, username):
            await _notify_members(
                message.bot, code, user_id,
                f"👋 *{username}* подключился к вашему общему списку!"
            )
            await message.answer(
                f"✅ Ты подключился к списку `{code}`!\nТеперь вы видите общий список.",
                parse_mode="Markdown",
            )
        else:
            await message.answer("❌ Код не найден. Проверь и попробуй снова.")
        await state.clear()

    @dp.message(F.photo)
    async def handle_photo(message: Message, state: FSMContext):
        user_id = message.from_user.id
        username = _get_username(message.from_user)

        status_msg = await message.answer("🔍 Анализирую изображение...")

        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        file_bytes = await message.bot.download_file(file.file_path)
        image_data = file_bytes.read()

        extracted, error = await extract_from_image(image_data)

        if error:
            await status_msg.edit_text(f"⚠️ {error}\n\nВведи название места вручную:")
            await state.update_data(
                location={"name": None, "address": None, "hours": None,
                           "avg_price": None, "promotions": None, "comment": None},
                user_id=user_id, username=username,
            )
            await state.set_state(AddLocation.asking_name)
            return

        found = [f"• *{k}*: {v}" for k, v in extracted.items() if v]
        missing = [k for k, v in extracted.items() if not v]
        summary = ("Вот что удалось найти:\n" + "\n".join(found)) if found else "Ничего не удалось распознать."
        if missing:
            summary += f"\n\n❓ Не нашёл: {', '.join(missing)} — спрошу отдельно."

        await status_msg.edit_text(summary, parse_mode="Markdown")
        await state.update_data(
            location={**extracted, "comment": None},
            user_id=user_id,
            username=username,
        )
        await ask_next_missing(message, state)

    @dp.message(F.text & ~F.text.startswith("/"))
    async def handle_text(message: Message, state: FSMContext):
        current = await state.get_state()
        user_id = message.from_user.id
        username = _get_username(message.from_user)

        if current is None and message.text.strip().isdigit():
            list_id = await get_user_list_id(user_id)
            if not list_id:
                return
            locations = await get_locations(list_id)
            index = int(message.text.strip()) - 1
            if 0 <= index < len(locations):
                row = locations[index]
                shared = await is_shared_list(list_id)
                await message.answer(
                    format_location(row, show_author=shared),
                    reply_markup=nav_keyboard(index, len(locations), row[0], bool(row[10])),
                    parse_mode="Markdown",
                )
            else:
                await message.answer(f"Нет места с таким номером. Всего в списке: {len(locations)}")
            return

        field_map = {
            AddLocation.asking_name.state:       "name",
            AddLocation.asking_address.state:    "address",
            AddLocation.asking_hours.state:      "hours",
            AddLocation.asking_price.state:      "avg_price",
            AddLocation.asking_promotions.state: "promotions",
            AddLocation.asking_comment.state:    "comment",
        }
        if current in field_map:
            data = await state.get_data()
            data["location"][field_map[current]] = message.text.strip()
            await state.update_data(location=data["location"])
            await ask_next_missing(message, state)
            return

        await state.update_data(
            location={"name": message.text.strip(), "address": None, "hours": None,
                       "avg_price": None, "promotions": None, "comment": None},
            user_id=user_id,
            username=username,
        )
        await ask_next_missing(message, state)

    @dp.callback_query(F.data == "skip_field")
    async def cb_skip_field(callback: CallbackQuery, state: FSMContext):
        current = await state.get_state()
        field_map = {
            AddLocation.asking_address.state:    "address",
            AddLocation.asking_hours.state:      "hours",
            AddLocation.asking_price.state:      "avg_price",
            AddLocation.asking_promotions.state: "promotions",
            AddLocation.asking_comment.state:    "comment",
        }
        if current in field_map:
            data = await state.get_data()
            data["location"][field_map[current]] = ""
            await state.update_data(location=data["location"])
            await callback.answer()
            await ask_next_missing(callback, state)

    @dp.callback_query(F.data.startswith("nav:"))
    async def cb_nav(callback: CallbackQuery):
        index = int(callback.data.split(":")[1])
        user_id = callback.from_user.id
        list_id = await get_user_list_id(user_id)
        locations = await get_locations(list_id)
        if not locations:
            await callback.answer("Список пуст")
            return
        index = max(0, min(index, len(locations) - 1))
        row = locations[index]
        shared = await is_shared_list(list_id)
        await callback.message.edit_text(
            format_location(row, show_author=shared),
            reply_markup=nav_keyboard(index, len(locations), row[0], bool(row[10])),
            parse_mode="Markdown",
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("show_all:"))
    async def cb_show_all(callback: CallbackQuery):
        page = int(callback.data.split(":")[1])
        user_id = callback.from_user.id
        list_id = await get_user_list_id(user_id)
        locations = await get_locations(list_id)
        shared = await is_shared_list(list_id)

        total_pages = max(1, (len(locations) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        start = page * PAGE_SIZE
        chunk = locations[start: start + PAGE_SIZE]

        lines = []
        for i, row in enumerate(chunk):
            real_i = start + i
            visited_mark = " ✅" if row[10] else ""
            author = f" *({row[3]})*" if shared else ""
            lines.append(f"{real_i+1}. {row[4]}{visited_mark}{author}")

        header = f"📋 *Все места:* (стр. {page+1}/{total_pages})\n\n"
        text = header + "\n".join(lines) + "\n\n_Напиши номер, чтобы открыть подробнее._"

        kb = all_list_keyboard(page, total_pages)
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        await callback.answer()

    @dp.callback_query(F.data.startswith("confirm_delete:"))
    async def cb_confirm_delete(callback: CallbackQuery):
        _, loc_id, index = callback.data.split(":")
        loc_id, index = int(loc_id), int(index)
        await callback.message.edit_reply_markup(
            reply_markup=confirm_delete_keyboard(loc_id, index)
        )
        await callback.answer("Подтверди удаление")

    @dp.callback_query(F.data.startswith("delete:"))
    async def cb_delete(callback: CallbackQuery):
        _, loc_id, index = callback.data.split(":")
        loc_id, index = int(loc_id), int(index)
        await delete_location_db(loc_id)
        user_id = callback.from_user.id
        list_id = await get_user_list_id(user_id)
        locations = await get_locations(list_id)
        if not locations:
            await callback.message.edit_text("📭 Список теперь пуст.")
            await callback.answer("Удалено")
            return
        index = min(index, len(locations) - 1)
        row = locations[index]
        shared = await is_shared_list(list_id)
        await callback.message.edit_text(
            format_location(row, show_author=shared),
            reply_markup=nav_keyboard(index, len(locations), row[0], bool(row[10])),
            parse_mode="Markdown",
        )
        await callback.answer("🗑 Место удалено")

    @dp.callback_query(F.data.startswith("visited:"))
    async def cb_visited(callback: CallbackQuery):
        _, loc_id, index = callback.data.split(":")
        loc_id, index = int(loc_id), int(index)
        is_visited = await toggle_visited_db(loc_id)
        user_id = callback.from_user.id
        list_id = await get_user_list_id(user_id)
        locations = await get_locations(list_id)
        if not locations or index >= len(locations):
            await callback.answer("Место не найдено")
            return
        row = locations[index]
        shared = await is_shared_list(list_id)
        mark = "✅ Отмечено как посещённое!" if is_visited else "↩️ Отметка снята."
        await callback.message.edit_text(
            format_location(row, show_author=shared),
            reply_markup=nav_keyboard(index, len(locations), row[0], bool(row[10])),
            parse_mode="Markdown",
        )
        await callback.answer(mark)

    @dp.callback_query(F.data == "noop")
    async def cb_noop(callback: CallbackQuery):
        await callback.answer()

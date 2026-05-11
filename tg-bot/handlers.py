import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext

from states import AddLocation, JoinList, RateVisit
from database import (
    get_or_create_list, get_user_list_id, get_locations,
    add_location_db, delete_location_db,
    mark_visited_db, unmark_visited_db,
    is_shared_list, join_list_db, get_list_members,
    get_random_unvisited, update_coordinates,
)
from formatting import (
    format_location, nav_keyboard, rating_keyboard,
    confirm_delete_keyboard, skip_keyboard, category_keyboard,
    skip_impression_keyboard, all_list_keyboard,
    PAGE_SIZE, STARS,
)
from ai import extract_from_image, lookup_place_by_name
from geocoding import geocode_address
from maps import generate_folium_html

FIELD_ORDER = ["name", "category", "address", "hours", "avg_price", "promotions", "comment"]

FIELD_PROMPTS = {
    "name":       ("📍 Как называется это место?",         False),
    "category":   ("🏷 Выбери категорию:",                 False),
    "address":    ("🗺 Введи адрес:",                       True),
    "hours":      ("🕐 Часы работы (напр. 10:00–22:00):",  True),
    "avg_price":  ("💰 Средний чек (напр. ~1500 ₽):",      True),
    "promotions": ("🎁 Акции и предложения (кратко):",      True),
    "comment":    ("💬 Хочешь добавить комментарий?",       True),
}

FIELD_STATES = {
    "name":       AddLocation.asking_name,
    "category":   AddLocation.asking_category,
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
            pass


async def _show_tab(message_or_cb: Message | CallbackQuery, tab: str, index: int = 0):
    """Show a location card for the given tab (plan/done)."""
    if isinstance(message_or_cb, CallbackQuery):
        user_id = message_or_cb.from_user.id
        send = message_or_cb.message.edit_text
    else:
        user_id = message_or_cb.from_user.id
        send = message_or_cb.answer

    list_id = await get_user_list_id(user_id)
    if not list_id:
        if isinstance(message_or_cb, CallbackQuery):
            await message_or_cb.answer("Сначала /start")
        else:
            await message_or_cb.answer("Сначала запусти бота — /start")
        return

    visited_filter = 0 if tab == "plan" else 1
    locations = await get_locations(list_id, visited=visited_filter)
    shared = await is_shared_list(list_id)

    if not locations:
        label = "📭 Список \"Куда идём\" пуст!" if tab == "plan" else "📭 Список \"Куда сходили\" пуст!"
        hint = "\n\nПришли скриншот или напиши название места." if tab == "plan" else ""
        tabs_text = label + hint
        if isinstance(message_or_cb, CallbackQuery):
            await message_or_cb.message.edit_text(tabs_text)
            await message_or_cb.answer()
        else:
            await message_or_cb.answer(tabs_text)
        return

    index = max(0, min(index, len(locations) - 1))
    row = locations[index]
    text = format_location(row, show_author=shared)
    kb = nav_keyboard(index, len(locations), row[0], bool(row[11]), tab=tab)
    if isinstance(message_or_cb, CallbackQuery):
        await message_or_cb.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        await message_or_cb.answer()
    else:
        await message_or_cb.answer(text, reply_markup=kb, parse_mode="Markdown")


async def ask_next_missing(target: Message | CallbackQuery, state: FSMContext):
    data = await state.get_data()
    loc = data.get("location", {})
    msg = target.message if isinstance(target, CallbackQuery) else target

    for field in FIELD_ORDER:
        if loc.get(field) is None:
            prompt, skippable = FIELD_PROMPTS[field]
            await state.set_state(FIELD_STATES[field])
            if field == "category":
                await msg.answer(prompt, reply_markup=category_keyboard())
            else:
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

    # Geocode address in background
    if loc.get("address"):
        coords = await geocode_address(loc["address"])
        if coords:
            loc["latitude"], loc["longitude"] = coords

    list_id = await get_user_list_id(user_id) or await get_or_create_list(user_id, username)
    await add_location_db(list_id, user_id, username, loc)

    await _notify_members(
        bot, list_id, user_id,
        f"🔔 *{username}* добавил новое место:\n\n📍 *{loc.get('name', '—')}*"
    )

    locations = await get_locations(list_id, visited=0)
    index = len(locations) - 1
    row = locations[index]
    shared = await is_shared_list(list_id)
    text = "✅ *Место сохранено!*\n\n" + format_location(row, show_author=shared)

    msg = target.message if isinstance(target, CallbackQuery) else target
    await msg.answer(
        text,
        reply_markup=nav_keyboard(index, len(locations), row[0], bool(row[11]), tab="plan"),
        parse_mode="Markdown",
    )
    await state.clear()


def register_handlers(dp: Dispatcher):

    # ─── Commands ────────────────────────────────────────────────────────────────

    @dp.message(CommandStart())
    async def cmd_start(message: Message):
        user_id = message.from_user.id
        username = _get_username(message.from_user)
        list_id = await get_or_create_list(user_id, username)
        await message.answer(
            f"👋 Привет, *{username}*!\n\n"
            f"Я помогаю собирать места, которые хочется посетить.\n\n"
            f"Пришли *скриншот* (сторис, пост) или напиши *название места* — "
            f"я извлеку информацию и сохраню.\n\n"
            f"🔑 Твой код списка: `{list_id}`\n\n"
            f"*Команды:*\n"
            f"/list — список \"Куда идём\"\n"
            f"/done — список \"Куда сходили\"\n"
            f"/random — случайное непосещённое место\n"
            f"/map — карта всех мест\n"
            f"/share — поделиться списком\n"
            f"/join — подключиться к чужому списку\n"
            f"/help — помощь\n"
            f"/cancel — отменить действие",
            parse_mode="Markdown",
        )

    @dp.message(Command("help"))
    async def cmd_help(message: Message):
        await message.answer(
            "*Как пользоваться ботом:*\n\n"
            "📸 *Добавить из фото* — пришли скриншот из Instagram/Stories.\n\n"
            "✏️ *Добавить текстом* — напиши название, я сначала поищу информацию сам, "
            "затем уточню только то, чего не нашёл.\n\n"
            "📋 */list* — места куда хочешь пойти.\n\n"
            "✅ */done* — места где уже побывал (с оценкой и впечатлением).\n\n"
            "🎲 */random* — случайное непосещённое место.\n\n"
            "🗺 */map* — интерактивная карта (HTML-файл, открывается в браузере).\n\n"
            "🔗 */share* — код для совместного списка с другом.\n\n"
            "👥 */join* — подключиться к списку друга по коду.",
            parse_mode="Markdown",
        )

    @dp.message(Command("cancel"))
    async def cmd_cancel(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("❌ Действие отменено.")

    @dp.message(Command("list"))
    async def cmd_list(message: Message):
        await _show_tab(message, tab="plan")

    @dp.message(Command("done"))
    async def cmd_done(message: Message):
        await _show_tab(message, tab="done")

    @dp.message(Command("random"))
    async def cmd_random(message: Message):
        user_id = message.from_user.id
        list_id = await get_user_list_id(user_id)
        if not list_id:
            await message.answer("Сначала запусти бота — /start")
            return
        row = await get_random_unvisited(list_id)
        if not row:
            await message.answer("📭 Нет непосещённых мест. Добавь что-нибудь!")
            return
        shared = await is_shared_list(list_id)
        locations = await get_locations(list_id, visited=0)
        index = next((i for i, r in enumerate(locations) if r[0] == row[0]), 0)
        await message.answer(
            f"🎲 *Случайное место:*\n\n" + format_location(row, show_author=shared),
            reply_markup=nav_keyboard(index, len(locations), row[0], False, tab="plan"),
            parse_mode="Markdown",
        )

    @dp.message(Command("map"))
    async def cmd_map(message: Message):
        user_id = message.from_user.id
        list_id = await get_user_list_id(user_id)
        if not list_id:
            await message.answer("Сначала запусти бота — /start")
            return
        locations = await get_locations(list_id)
        if not locations:
            await message.answer("📭 Список пуст.")
            return

        status = await message.answer("🗺 Генерирую интерактивную карту...")
        html = generate_folium_html(locations)
        if not html:
            await status.edit_text(
                "⚠️ Не удалось построить карту — адреса мест не были геокодированы.\n\n"
                "Убедись, что при добавлении мест указывал адрес (город, улица)."
            )
            return

        total = len(locations)
        geo_count = sum(1 for r in locations if r[14] is not None)
        unvisited = sum(1 for r in locations if not r[11])
        visited_count = total - unvisited

        html_bytes = html.encode("utf-8")
        doc = BufferedInputFile(html_bytes, filename="my_places_map.html")
        await status.delete()
        await message.answer_document(
            doc,
            caption=(
                f"🗺 *Интерактивная карта мест*\n\n"
                f"🟢 Хочу посетить: {unvisited}\n"
                f"🔵 Посетил: {visited_count}\n"
                f"📍 На карте: {geo_count} из {total}\n\n"
                f"_Открой файл в браузере — карту можно зумить, "
                f"приближать, кликать на метки._"
            ),
            parse_mode="Markdown",
        )

    @dp.message(Command("share"))
    async def cmd_share(message: Message):
        user_id = message.from_user.id
        list_id = await get_user_list_id(user_id)
        await message.answer(
            f"🔗 Поделись этим кодом с другом:\n\n`{list_id}`\n\n"
            f"Друг пишет /join и вводит этот код — "
            f"вы увидите общий список с именами авторов.",
            parse_mode="Markdown",
        )

    @dp.message(Command("join"))
    async def cmd_join(message: Message, state: FSMContext):
        await state.set_state(JoinList.entering_code)
        await message.answer("Введи код списка:")

    # ─── Join flow ───────────────────────────────────────────────────────────────

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

    # ─── Photo handler ───────────────────────────────────────────────────────────

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
                location={"name": None, "category": None, "address": None,
                           "hours": None, "avg_price": None, "promotions": None, "comment": None},
                user_id=user_id, username=username,
            )
            await state.set_state(AddLocation.asking_name)
            return

        found = [f"• *{k}*: {v}" for k, v in extracted.items() if v]
        missing = [k for k, v in extracted.items() if not v]
        summary = ("Вот что удалось найти:\n" + "\n".join(found)) if found else "Ничего не удалось распознать."
        if missing:
            summary += f"\n\n❓ Не нашёл: {', '.join(missing)} — спрошу отдельно."

        await status_msg.edit_text(summary, parse_mode=None)
        await state.update_data(
            location={**extracted, "category": None, "comment": None},
            user_id=user_id,
            username=username,
        )
        await ask_next_missing(message, state)

    # ─── Text handler ─────────────────────────────────────────────────────────────

    @dp.message(F.text & ~F.text.startswith("/"))
    async def handle_text(message: Message, state: FSMContext):
        current = await state.get_state()
        user_id = message.from_user.id
        username = _get_username(message.from_user)

        # Navigate by number
        if current is None and message.text.strip().isdigit():
            list_id = await get_user_list_id(user_id)
            if not list_id:
                return
            locations = await get_locations(list_id, visited=0)
            index = int(message.text.strip()) - 1
            if 0 <= index < len(locations):
                row = locations[index]
                shared = await is_shared_list(list_id)
                await message.answer(
                    format_location(row, show_author=shared),
                    reply_markup=nav_keyboard(index, len(locations), row[0], False, tab="plan"),
                    parse_mode="Markdown",
                )
            else:
                await message.answer(f"Нет места с таким номером. В списке: {len(locations)}")
            return

        # FSM: impression input
        if current == RateVisit.asking_impression.state:
            data = await state.get_data()
            loc_id = data["rating_loc_id"]
            index = data["rating_index"]
            rating = data["rating_value"]
            impression = message.text.strip()
            await mark_visited_db(loc_id, rating, impression)
            await state.clear()
            list_id = await get_user_list_id(user_id)
            locations = await get_locations(list_id, visited=1)
            idx = next((i for i, r in enumerate(locations) if r[0] == loc_id), 0)
            shared = await is_shared_list(list_id)
            row = locations[idx]
            await message.answer(
                f"🌟 Отлично! Место перемещено в \"Куда сходили\".\n\n" +
                format_location(row, show_author=shared),
                reply_markup=nav_keyboard(idx, len(locations), row[0], True, tab="done"),
                parse_mode="Markdown",
            )
            return

        # FSM: AddLocation fields
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
            field = field_map[current]
            data["location"][field] = message.text.strip()
            await state.update_data(location=data["location"])

            # Если ввели имя — пробуем найти инфо через AI
            if field == "name":
                place_name = message.text.strip()
                status_msg = await message.answer("🔍 Ищу информацию о месте...")
                extracted, error = await lookup_place_by_name(place_name)
                found = {k: v for k, v in extracted.items() if v and k != "name"}
                if found:
                    lines = [f"• {k}: {v}" for k, v in found.items()]
                    await status_msg.edit_text("Вот что нашёл:\n" + "\n".join(lines))
                    merged = {**extracted, **{k: v for k, v in data["location"].items() if v}}
                    merged["category"] = None
                    merged["comment"] = None
                    await state.update_data(location=merged)
                else:
                    await status_msg.delete()

            await ask_next_missing(message, state)
            return

        # ── New place from text: сначала ищем через AI ────────────────────────
        if current is None:
            place_name = message.text.strip()
            status_msg = await message.answer("🔍 Ищу информацию о месте...")

            extracted, error = await lookup_place_by_name(place_name)

            if error:
                await status_msg.edit_text(f"⚠️ {error}")

            # Показываем что нашли
            found = {k: v for k, v in extracted.items() if v}
            missing_fields = [k for k in ["address", "hours", "avg_price", "promotions"] if not extracted.get(k)]

            if len(found) > 1:  # нашли что-то кроме имени
                lines = [f"• *{k}*: {v}" for k, v in found.items()]
                summary = "Вот что удалось найти:\n" + "\n".join(lines)
                if missing_fields:
                    summary += f"\n\n❓ Не нашёл: {', '.join(missing_fields)} — спрошу отдельно."
                await status_msg.edit_text(summary, parse_mode=None)
            else:
                await status_msg.edit_text(
                    f"📍 Добавляю *{place_name}*\n\nНичего не нашёл автоматически — уточню детали.",
                    parse_mode="Markdown",
                )

            await state.update_data(
                location={**extracted, "category": None, "comment": None},
                user_id=user_id,
                username=username,
            )
            await ask_next_missing(message, state)

    # ─── Skip field ──────────────────────────────────────────────────────────────

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

    # ─── Category selection ──────────────────────────────────────────────────────

    @dp.callback_query(F.data.startswith("set_category:"))
    async def cb_set_category(callback: CallbackQuery, state: FSMContext):
        category = callback.data[len("set_category:"):]
        data = await state.get_data()
        data["location"]["category"] = category
        await state.update_data(location=data["location"])
        await callback.answer()
        await ask_next_missing(callback, state)

    # ─── Tab switching ───────────────────────────────────────────────────────────

    @dp.callback_query(F.data.startswith("tab:"))
    async def cb_tab(callback: CallbackQuery):
        _, tab, index = callback.data.split(":")
        await _show_tab(callback, tab=tab, index=int(index))

    # ─── Navigation ──────────────────────────────────────────────────────────────

    @dp.callback_query(F.data.startswith("nav:"))
    async def cb_nav(callback: CallbackQuery):
        parts = callback.data.split(":")
        index = int(parts[1])
        tab = parts[2] if len(parts) > 2 else "plan"
        await _show_tab(callback, tab=tab, index=index)

    # ─── Full list (paginated) ───────────────────────────────────────────────────

    @dp.callback_query(F.data.startswith("show_all:"))
    async def cb_show_all(callback: CallbackQuery):
        _, tab, page_str = callback.data.split(":")
        page = int(page_str)
        user_id = callback.from_user.id
        list_id = await get_user_list_id(user_id)
        visited_filter = 0 if tab == "plan" else 1
        locations = await get_locations(list_id, visited=visited_filter)
        shared = await is_shared_list(list_id)

        total_pages = max(1, (len(locations) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        start = page * PAGE_SIZE
        chunk = locations[start: start + PAGE_SIZE]

        label = "🗺 Куда идём" if tab == "plan" else "✅ Куда сходили"
        lines = []
        for i, row in enumerate(chunk):
            real_i = start + i
            visited_mark = " ✅" if row[11] else ""
            stars = f" {STARS.get(row[12], '')}" if row[12] else ""
            author = f" *({row[3]})*" if shared else ""
            lines.append(f"{real_i+1}. {row[4]}{visited_mark}{stars}{author}")

        text = (
            f"📋 *{label}* (стр. {page+1}/{total_pages})\n\n"
            + "\n".join(lines)
            + "\n\n_Напиши номер, чтобы открыть подробнее._"
        )
        kb = all_list_keyboard(tab, page, total_pages)
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        await callback.answer()

    # ─── Mark visited (start rating flow) ────────────────────────────────────────

    @dp.callback_query(F.data.startswith("start_rate:"))
    async def cb_start_rate(callback: CallbackQuery, state: FSMContext):
        _, loc_id, index = callback.data.split(":")
        loc_id, index = int(loc_id), int(index)
        await state.set_state(RateVisit.asking_rating)
        await state.update_data(rating_loc_id=loc_id, rating_index=index)
        await callback.message.answer(
            "🌟 *Оцени место:*\nВыбери от 1 до 5 звёзд",
            reply_markup=rating_keyboard(loc_id, index),
            parse_mode="Markdown",
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("rate:"))
    async def cb_rate(callback: CallbackQuery, state: FSMContext):
        _, loc_id, index, rating = callback.data.split(":")
        loc_id, index, rating = int(loc_id), int(index), int(rating)
        await state.update_data(rating_value=rating)
        await state.set_state(RateVisit.asking_impression)
        stars = STARS.get(rating, "")
        await callback.message.edit_text(
            f"Оценка: {stars}\n\n✍️ Напиши впечатление о месте (или пропусти):",
            reply_markup=skip_impression_keyboard(loc_id, index),
            parse_mode="Markdown",
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("skip_impression:"))
    async def cb_skip_impression(callback: CallbackQuery, state: FSMContext):
        _, loc_id, index = callback.data.split(":")
        loc_id, index = int(loc_id), int(index)
        data = await state.get_data()
        rating = data.get("rating_value", 5)
        await mark_visited_db(loc_id, rating, "")
        await state.clear()
        user_id = callback.from_user.id
        list_id = await get_user_list_id(user_id)
        locations = await get_locations(list_id, visited=1)
        idx = next((i for i, r in enumerate(locations) if r[0] == loc_id), 0)
        shared = await is_shared_list(list_id)
        row = locations[idx]
        await callback.message.edit_text(
            f"🌟 Место перемещено в \"Куда сходили\"!\n\n" +
            format_location(row, show_author=shared),
            reply_markup=nav_keyboard(idx, len(locations), row[0], True, tab="done"),
            parse_mode="Markdown",
        )
        await callback.answer()

    # ─── Unmark visited ───────────────────────────────────────────────────────────

    @dp.callback_query(F.data.startswith("unvisit:"))
    async def cb_unvisit(callback: CallbackQuery):
        parts = callback.data.split(":")
        loc_id, index = int(parts[1]), int(parts[2])
        tab = parts[3] if len(parts) > 3 else "done"
        await unmark_visited_db(loc_id)
        user_id = callback.from_user.id
        list_id = await get_user_list_id(user_id)
        locations = await get_locations(list_id, visited=0)
        idx = next((i for i, r in enumerate(locations) if r[0] == loc_id), 0)
        shared = await is_shared_list(list_id)
        if not locations:
            await callback.message.edit_text("📭 Список \"Куда идём\" пуст.")
            await callback.answer("↩️ Отметка снята")
            return
        row = locations[idx]
        await callback.message.edit_text(
            format_location(row, show_author=shared),
            reply_markup=nav_keyboard(idx, len(locations), row[0], False, tab="plan"),
            parse_mode="Markdown",
        )
        await callback.answer("↩️ Место возвращено в список \"Куда идём\"")

    # ─── Delete with confirmation ─────────────────────────────────────────────────

    @dp.callback_query(F.data.startswith("confirm_delete:"))
    async def cb_confirm_delete(callback: CallbackQuery):
        parts = callback.data.split(":")
        loc_id, index = int(parts[1]), int(parts[2])
        tab = parts[3] if len(parts) > 3 else "plan"
        await callback.message.edit_reply_markup(
            reply_markup=confirm_delete_keyboard(loc_id, index, tab)
        )
        await callback.answer("Подтверди удаление")

    @dp.callback_query(F.data.startswith("delete:"))
    async def cb_delete(callback: CallbackQuery):
        parts = callback.data.split(":")
        loc_id, index = int(parts[1]), int(parts[2])
        tab = parts[3] if len(parts) > 3 else "plan"
        await delete_location_db(loc_id)
        user_id = callback.from_user.id
        list_id = await get_user_list_id(user_id)
        visited_filter = 0 if tab == "plan" else 1
        locations = await get_locations(list_id, visited=visited_filter)
        if not locations:
            await callback.message.edit_text("📭 Список теперь пуст.")
            await callback.answer("🗑 Удалено")
            return
        index = min(index, len(locations) - 1)
        row = locations[index]
        shared = await is_shared_list(list_id)
        await callback.message.edit_text(
            format_location(row, show_author=shared),
            reply_markup=nav_keyboard(index, len(locations), row[0], bool(row[11]), tab=tab),
            parse_mode="Markdown",
        )
        await callback.answer("🗑 Место удалено")

    @dp.callback_query(F.data == "noop")
    async def cb_noop(callback: CallbackQuery):
        await callback.answer()

import secrets
import aiosqlite
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS lists (
                list_id TEXT PRIMARY KEY,
                created_by INTEGER
            );
            CREATE TABLE IF NOT EXISTS list_members (
                list_id TEXT,
                user_id INTEGER,
                username TEXT,
                PRIMARY KEY (list_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_id TEXT,
                added_by INTEGER,
                added_by_name TEXT,
                name TEXT,
                category TEXT,
                address TEXT,
                hours TEXT,
                avg_price TEXT,
                promotions TEXT,
                comment TEXT,
                visited INTEGER DEFAULT 0,
                rating INTEGER,
                impression TEXT,
                latitude REAL,
                longitude REAL
            );
            CREATE INDEX IF NOT EXISTS idx_list_members_user ON list_members(user_id);
            CREATE INDEX IF NOT EXISTS idx_list_members_list ON list_members(list_id);
            CREATE INDEX IF NOT EXISTS idx_locations_list ON locations(list_id);
        """)
        # Migrate existing DBs: add new columns if missing
        for col, typedef in [
            ("category",   "TEXT"),
            ("rating",     "INTEGER"),
            ("impression", "TEXT"),
            ("latitude",   "REAL"),
            ("longitude",  "REAL"),
        ]:
            try:
                await db.execute(f"ALTER TABLE locations ADD COLUMN {col} {typedef}")
            except Exception:
                pass
        await db.commit()


async def get_or_create_list(user_id: int, username: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT list_id FROM list_members WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            return row[0]
        list_id = secrets.token_hex(4).upper()
        await db.execute("INSERT INTO lists VALUES (?, ?)", (list_id, user_id))
        await db.execute(
            "INSERT INTO list_members VALUES (?, ?, ?)", (list_id, user_id, username)
        )
        await db.commit()
        return list_id


async def get_user_list_id(user_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT list_id FROM list_members WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else None


async def get_locations(list_id: str, visited: int | None = None) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        if visited is None:
            async with db.execute(
                "SELECT * FROM locations WHERE list_id = ?", (list_id,)
            ) as cur:
                return await cur.fetchall()
        else:
            async with db.execute(
                "SELECT * FROM locations WHERE list_id = ? AND visited = ?",
                (list_id, visited),
            ) as cur:
                return await cur.fetchall()


async def add_location_db(
    list_id: str, user_id: int, username: str, data: dict
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO locations
               (list_id, added_by, added_by_name, name, category, address, hours,
                avg_price, promotions, comment, latitude, longitude)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                list_id, user_id, username,
                data.get("name", ""),
                data.get("category", ""),
                data.get("address", ""),
                data.get("hours", ""),
                data.get("avg_price", ""),
                data.get("promotions", ""),
                data.get("comment", ""),
                data.get("latitude"),
                data.get("longitude"),
            ),
        )
        await db.commit()


async def delete_location_db(loc_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM locations WHERE id = ?", (loc_id,))
        await db.commit()


async def mark_visited_db(loc_id: int, rating: int, impression: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE locations SET visited = 1, rating = ?, impression = ? WHERE id = ?",
            (rating, impression, loc_id),
        )
        await db.commit()
    return True


async def unmark_visited_db(loc_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE locations SET visited = 0, rating = NULL, impression = NULL WHERE id = ?",
            (loc_id,),
        )
        await db.commit()
    return False


async def is_shared_list(list_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM list_members WHERE list_id = ?", (list_id,)
        ) as cur:
            row = await cur.fetchone()
    return (row[0] if row else 0) > 1


async def join_list_db(list_id: str, user_id: int, username: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM lists WHERE list_id = ?", (list_id,)
        ) as cur:
            if not await cur.fetchone():
                return False
        await db.execute("DELETE FROM list_members WHERE user_id = ?", (user_id,))
        await db.execute(
            "INSERT OR REPLACE INTO list_members VALUES (?, ?, ?)",
            (list_id, user_id, username),
        )
        await db.commit()
    return True


async def get_list_members(list_id: str) -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id FROM list_members WHERE list_id = ?", (list_id,)
        ) as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]


async def get_random_unvisited(list_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM locations WHERE list_id = ? AND visited = 0 ORDER BY RANDOM() LIMIT 1",
            (list_id,),
        ) as cur:
            return await cur.fetchone()


async def update_coordinates(loc_id: int, lat: float, lon: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE locations SET latitude = ?, longitude = ? WHERE id = ?",
            (lat, lon, loc_id),
        )
        await db.commit()

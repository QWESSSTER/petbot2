import os

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
GEMINI_API_KEY: str = os.environ["GEMINI_API_KEY"]
DB_PATH: str = os.environ.get("DB_PATH", "locations.db")

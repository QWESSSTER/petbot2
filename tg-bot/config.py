import os

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
OPENROUTER_API_KEY: str = os.environ["OPENROUTER_API_KEY"]
DB_PATH: str = os.environ.get("DB_PATH", "locations.db")

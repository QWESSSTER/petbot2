import json
import sys
import asyncio
import base64
from functools import partial
from openai import OpenAI
from config import OPENROUTER_API_KEY

_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# ─── Prompts ──────────────────────────────────────────────────────────────────

_IMAGE_PROMPT = """Извлеки информацию о заведении или локации из этого изображения.
Верни ТОЛЬКО валидный JSON без markdown и пояснений:
{"name": "…", "address": "…", "hours": "…", "avg_price": "…", "promotions": "…"}
Если поле не найдено — ставь null."""

_SEARCH_PROMPT = """Ты помощник по поиску информации о заведениях и местах.
Запрос пользователя: "{query}"

Найди 1-3 наиболее подходящих места и верни ТОЛЬКО валидный JSON-массив без markdown:
[
  {{
    "name": "точное название заведения",
    "address": "город, улица, дом",
    "hours": "часы работы или null",
    "avg_price": "средний чек или null",
    "promotions": "особенности/акции или null"
  }}
]

Правила:
- Если это сеть (несколько филиалов) — верни каждый филиал отдельным объектом с разными адресами
- Если место одно — верни массив из одного объекта
- name: точное официальное название
- address: обязательно укажи город
- Не придумывай данные — лучше null, чем неверная информация
- Если ничего не знаешь — верни пустой массив []"""

# ─── Models ───────────────────────────────────────────────────────────────────

_VISION_MODELS = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/llama-3.2-11b-vision-instruct:free",
]

_TEXT_MODELS = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "mistralai/mistral-7b-instruct:free",
]

_EMPTY = {"name": None, "address": None, "hours": None, "avg_price": None, "promotions": None}

_USER_ERROR = (
    "Произошла ошибка при анализе изображения. "
    "Попробуй ввести название места вручную. "
    "Если ошибка повторяется — обратись в поддержку."
)

# ─── Internal callers ─────────────────────────────────────────────────────────

def _call_vision(image_data: bytes) -> str:
    b64 = base64.b64encode(image_data).decode("utf-8")
    last_err = None
    for model in _VISION_MODELS:
        try:
            response = _client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": _IMAGE_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ]}],
            )
            print(f"[AI] Vision OK model={model}", file=sys.stderr)
            return response.choices[0].message.content
        except Exception as e:
            print(f"[AI] Vision model={model} failed: {type(e).__name__}: {e}", file=sys.stderr)
            last_err = e
    raise last_err


def _call_text(query: str) -> str:
    prompt = _SEARCH_PROMPT.format(query=query)
    last_err = None
    for model in _TEXT_MODELS:
        try:
            response = _client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
            print(f"[AI] Text OK model={model}", file=sys.stderr)
            return response.choices[0].message.content
        except Exception as e:
            print(f"[AI] Text model={model} failed: {type(e).__name__}: {e}", file=sys.stderr)
            last_err = e
    raise last_err


def _parse_json(text: str):
    text = text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(text)

# ─── Public API ───────────────────────────────────────────────────────────────

async def extract_from_image(image_data: bytes) -> tuple[dict, str | None]:
    """Анализирует фото. Возвращает (данные, ошибка)."""
    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, partial(_call_vision, image_data))
        return _parse_json(text), None
    except json.JSONDecodeError as e:
        print(f"[AI] Image JSON error: {e}", file=sys.stderr)
        return _EMPTY.copy(), _USER_ERROR
    except Exception as e:
        print(f"[AI] Image error: {type(e).__name__}: {e}", file=sys.stderr)
        return _EMPTY.copy(), _USER_ERROR


async def search_places(query: str) -> tuple[list[dict], str | None]:
    """Ищет места по запросу. Возвращает (список вариантов, ошибка).
    Список может быть пустым если ничего не найдено."""
    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, partial(_call_text, query))
        data = _parse_json(text)
        if not isinstance(data, list):
            # Если модель вернула объект вместо массива — оборачиваем
            data = [data] if isinstance(data, dict) and data.get("name") else []
        # Фильтруем пустые результаты
        data = [d for d in data if d.get("name")]
        return data, None
    except json.JSONDecodeError as e:
        print(f"[AI] Search JSON error: {e}", file=sys.stderr)
        return [], None  # не ошибка — просто ничего не нашли
    except Exception as e:
        print(f"[AI] Search error: {type(e).__name__}: {e}", file=sys.stderr)
        return [], "Произошла ошибка при поиске. Если повторяется — обратись в поддержку."

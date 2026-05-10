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

# ─── Prompts ─────────────────────────────────────────────────────────────────

_IMAGE_PROMPT = """Извлеки информацию о заведении или локации из этого изображения.
Верни ТОЛЬКО валидный JSON без markdown и пояснений:
{"name": "…", "address": "…", "hours": "…", "avg_price": "…", "promotions": "…"}
Если поле не найдено — ставь null."""

_TEXT_PROMPT = """Ты помощник по поиску информации о заведениях и местах.
Пользователь написал название места: "{name}"

Постарайся найти информацию об этом месте и верни ТОЛЬКО валидный JSON без markdown и пояснений:
{{"name": "…", "address": "…", "hours": "…", "avg_price": "…", "promotions": "…"}}

Правила:
- name: уточни/исправь название если знаешь точное
- address: город и улица, если знаешь
- hours: часы работы, если знаешь
- avg_price: средний чек, если знаешь
- promotions: акции или особенности, если знаешь
- Если поле неизвестно — ставь null
- Не придумывай данные — лучше null, чем неверная информация"""

# ─── Defaults ────────────────────────────────────────────────────────────────

_EMPTY: dict = {
    "name": None,
    "address": None,
    "hours": None,
    "avg_price": None,
    "promotions": None,
}

_USER_ERROR = (
    "Произошла ошибка при анализе изображения. "
    "Попробуй ещё раз или введи название места вручную. "
    "Если ошибка повторяется — обратись в поддержку."
)

_TEXT_ERROR = (
    "Произошла ошибка при поиске информации о месте. "
    "Если ошибка повторяется — обратись в поддержку."
)

# ─── Models ───────────────────────────────────────────────────────────────────

# Vision models for image analysis
_VISION_MODELS = [
    "qwen/qwen2.5-vl-72b-instruct:free",
    "meta-llama/llama-4-scout:free",
    "mistralai/pixtral-12b:free",
]

# Text models for place lookup
_TEXT_MODELS = [
    "meta-llama/llama-4-scout:free",
    "qwen/qwen2.5-72b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
]

# ─── Internal callers ────────────────────────────────────────────────────────

def _call_vision(image_data: bytes) -> str:
    b64 = base64.b64encode(image_data).decode("utf-8")
    last_err = None
    for model in _VISION_MODELS:
        try:
            response = _client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _IMAGE_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }],
            )
            text = response.choices[0].message.content
            print(f"[AI] Vision OK model={model}", file=sys.stderr)
            return text
        except Exception as e:
            print(f"[AI] Vision model={model} failed: {type(e).__name__}: {e}", file=sys.stderr)
            last_err = e
    raise last_err


def _call_text(name: str) -> str:
    prompt = _TEXT_PROMPT.format(name=name)
    last_err = None
    for model in _TEXT_MODELS:
        try:
            response = _client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.choices[0].message.content
            print(f"[AI] Text OK model={model}", file=sys.stderr)
            return text
        except Exception as e:
            print(f"[AI] Text model={model} failed: {type(e).__name__}: {e}", file=sys.stderr)
            last_err = e
    raise last_err


def _parse_json(text: str) -> dict:
    text = text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(text)

# ─── Public API ──────────────────────────────────────────────────────────────

async def extract_from_image(image_data: bytes) -> tuple[dict, str | None]:
    """Анализирует изображение и возвращает (данные, ошибка)."""
    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, partial(_call_vision, image_data))
        data = _parse_json(text)
        return data, None
    except json.JSONDecodeError as e:
        print(f"[AI] Image JSON parse error: {e}", file=sys.stderr)
        return _EMPTY.copy(), _USER_ERROR
    except Exception as e:
        print(f"[AI] Image final error: {type(e).__name__}: {e}", file=sys.stderr)
        return _EMPTY.copy(), _USER_ERROR


async def lookup_place_by_name(name: str) -> tuple[dict, str | None]:
    """Ищет информацию о месте по названию и возвращает (данные, ошибка)."""
    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, partial(_call_text, name))
        data = _parse_json(text)
        # Убеждаемся, что name не потерялся
        if not data.get("name"):
            data["name"] = name
        return data, None
    except json.JSONDecodeError as e:
        print(f"[AI] Text JSON parse error: {e}", file=sys.stderr)
        return {**_EMPTY.copy(), "name": name}, None  # не ошибка — просто ничего не нашли
    except Exception as e:
        print(f"[AI] Text final error: {type(e).__name__}: {e}", file=sys.stderr)
        return {**_EMPTY.copy(), "name": name}, _TEXT_ERROR

import json
import io
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

_PROMPT = """Извлеки информацию о заведении или локации из этого изображения.
Верни ТОЛЬКО валидный JSON без markdown и пояснений:
{"name": "…", "address": "…", "hours": "…", "avg_price": "…", "promotions": "…"}
Если поле не найдено — ставь null."""

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

# Best free vision models on OpenRouter, tried in order
_MODELS = [
    "qwen/qwen2.5-vl-72b-instruct:free",
    "meta-llama/llama-4-scout:free",
    "mistralai/pixtral-12b:free",
]


def _call_openrouter(image_data: bytes) -> str:
    b64 = base64.b64encode(image_data).decode("utf-8")

    last_err = None
    for model in _MODELS:
        try:
            response = _client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }],
            )
            text = response.choices[0].message.content
            print(f"[AI] OK with model={model}", file=sys.stderr)
            return text
        except Exception as e:
            print(f"[AI] model={model} failed: {type(e).__name__}: {e}", file=sys.stderr)
            last_err = e

    raise last_err


async def extract_from_image(image_data: bytes) -> tuple[dict, str | None]:
    """Returns (extracted_dict, error_message). error_message is None on success."""
    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, partial(_call_openrouter, image_data))
        text = text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        return data, None
    except json.JSONDecodeError as e:
        print(f"[AI] JSON parse error: {e}", file=sys.stderr)
        return _EMPTY.copy(), _USER_ERROR
    except Exception as e:
        print(f"[AI] Final error: {type(e).__name__}: {e}", file=sys.stderr)
        return _EMPTY.copy(), _USER_ERROR

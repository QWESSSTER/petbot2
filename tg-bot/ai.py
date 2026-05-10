import json
import io
import sys
import asyncio
from functools import partial
import PIL.Image
from google import genai
from google.genai import types
from config import GEMINI_API_KEY

_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options={"api_version": "v1"},
)

_PROMPT = (
    "Извлеки информацию о заведении или локации из этого изображения. "
    "Верни ТОЛЬКО валидный JSON без markdown и пояснений:\n"
    '{"name": "…", "address": "…", "hours": "…", "avg_price": "…", "promotions": "…"}\n'
    "Если поле не найдено — ставь null."
)

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

_MODELS = ["gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-2.0-flash"]


def _call_gemini(image_data: bytes) -> str:
    # Detect mime type
    image = PIL.Image.open(io.BytesIO(image_data))
    fmt = (image.format or "JPEG").upper()
    mime = f"image/{'jpeg' if fmt == 'JPEG' else fmt.lower()}"

    image_part = types.Part.from_bytes(data=image_data, mime_type=mime)

    last_err = None
    for model in _MODELS:
        try:
            response = _client.models.generate_content(
                model=model,
                contents=[_PROMPT, image_part],
            )
            print(f"[AI] OK with model={model}", file=sys.stderr)
            return response.text
        except Exception as e:
            print(f"[AI] model={model} failed: {type(e).__name__}: {e}", file=sys.stderr)
            last_err = e

    raise last_err


async def extract_from_image(image_data: bytes) -> tuple[dict, str | None]:
    """Returns (extracted_dict, error_message). error_message is None on success."""
    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, partial(_call_gemini, image_data))
        text = text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        return data, None
    except json.JSONDecodeError as e:
        print(f"[AI] JSON parse error: {e}", file=sys.stderr)
        return _EMPTY.copy(), _USER_ERROR
    except Exception as e:
        print(f"[AI] Final error: {type(e).__name__}: {e}", file=sys.stderr)
        return _EMPTY.copy(), _USER_ERROR

import json
import io
import sys
import asyncio
from functools import partial
import PIL.Image
from google import genai
from config import GEMINI_API_KEY

_client = genai.Client(api_key=GEMINI_API_KEY)

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


def _call_gemini(image: PIL.Image.Image) -> str:
    response = _client.models.generate_content(
        model="gemini-1.5-flash",
        contents=[_PROMPT, image],
    )
    return response.text


async def extract_from_image(image_data: bytes) -> tuple[dict, str | None]:
    """
    Returns (extracted_dict, error_message).
    error_message is None on success.
    """
    try:
        image = PIL.Image.open(io.BytesIO(image_data))
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, partial(_call_gemini, image))
        text = text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        return data, None
    except json.JSONDecodeError as e:
        print(f"[AI] JSON parse error: {e}", file=sys.stderr)
        return _EMPTY.copy(), _USER_ERROR
    except Exception as e:
        print(f"[AI] Error: {type(e).__name__}: {e}", file=sys.stderr)
        return _EMPTY.copy(), _USER_ERROR

import json
import io
import PIL.Image
from google import genai
from google.genai import types
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


async def extract_from_image(image_data: bytes) -> tuple[dict, str | None]:
    """
    Returns (extracted_dict, error_message).
    error_message is None on success.
    """
    try:
        image = PIL.Image.open(io.BytesIO(image_data))
        response = _client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[_PROMPT, image],
        )
        text = response.text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        return data, None
    except json.JSONDecodeError:
        return _EMPTY.copy(), "Gemini вернул неожиданный ответ — не смог распознать данные."
    except Exception as e:
        return _EMPTY.copy(), f"Ошибка при анализе изображения: {e}"

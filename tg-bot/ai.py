import json
import io
import PIL.Image
import google.generativeai as genai
from config import GEMINI_API_KEY

genai.configure(api_key=GEMINI_API_KEY)
_model = genai.GenerativeModel("gemini-1.5-flash")

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
        response = _model.generate_content([_PROMPT, image])
        text = response.text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        return data, None
    except json.JSONDecodeError:
        return _EMPTY.copy(), "Gemini вернул неожиданный ответ — не смог распознать данные."
    except Exception as e:
        return _EMPTY.copy(), f"Ошибка при анализе изображения: {e}"

import os
import re
from io import BytesIO

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types
from pypdf import PdfReader

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

# The app tries these models in order. If one is unavailable or temporarily
# rate-limited, it automatically tries the next one.
DEFAULT_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
]
MODEL_LIST = [
    model.strip()
    for model in os.getenv("GEMINI_MODELS", ",".join(DEFAULT_MODELS)).split(",")
    if model.strip()
]
MAX_CHARS = 30000

ALLOWED_LANGUAGES = {
    "Kannada": "kn",
    "Hindi": "hi",
    "Telugu": "te",
    "Tamil": "ta",
    "Marathi": "mr",
    "Malayalam": "ml",
    "Bengali": "bn",
    "Gujarati": "gu",
    "Punjabi": "pa",
    "English": "en",
}

app = FastAPI(
    title="AI Mother Tongue Curriculum Translator",
    version="1.1.0",
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")


def get_client() -> genai.Client:
    if not API_KEY:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY is missing. Add it to your .env file.",
        )
    return genai.Client(api_key=API_KEY)


def is_retryable_model_error(exc: Exception) -> bool:
    """Return True for model unavailable/rate-limit/server errors."""
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "404",
            "not_found",
            "not found",
            "429",
            "resource_exhausted",
            "rate limit",
            "500",
            "502",
            "503",
            "504",
            "unavailable",
        )
    )


def generate_with_fallback(client: genai.Client, contents, config=None):
    """Try each configured Gemini model until one succeeds."""
    errors = []

    for model in MODEL_LIST:
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            return response, model
        except Exception as exc:
            errors.append(f"{model}: {exc}")

            # Invalid request/authentication errors should be shown immediately.
            if not is_retryable_model_error(exc):
                raise

    joined = "\n".join(errors)
    raise RuntimeError(
        "All configured Gemini models failed.\n" + joined
    )


def build_translation_prompt(text: str, target_language: str) -> str:
    return f"""
You are an educational curriculum translator.

Translate the curriculum below from its original language into {target_language}.

Rules:
1. Preserve the original meaning and educational intent.
2. Preserve headings, numbered lists, bullet points, examples, formulas, units, symbols, and paragraph structure.
3. Use natural language appropriate for a student, not awkward word-for-word translation.
4. Keep internationally standard scientific, mathematical, programming, and technical terms when translating them would reduce clarity.
5. Do not add facts that are not present in the source.
6. Do not summarize or shorten the content.
7. Return ONLY the translated curriculum. Do not add commentary.

CURRICULUM:
{text}
""".strip()


@app.get("/")
async def home():
    return FileResponse("frontend/index.html")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "models": MODEL_LIST,
    }


@app.post("/api/translate")
async def translate_text(
    text: str = Form(...),
    target_language: str = Form(...),
):
    text = text.strip()

    if not text:
        raise HTTPException(status_code=400, detail="Please enter some curriculum text.")

    if target_language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported target language.")

    if len(text) > MAX_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Text is too long for the prototype. Keep it under {MAX_CHARS:,} characters.",
        )

    client = get_client()
    prompt = build_translation_prompt(text, target_language)
    # Translation does not need deep reasoning. Gemini documents
    # "minimal" as the latency-optimized level for simple requests.
    # 3.7/3.8 do not support "minimal", so use "low" for those fallbacks.
    errors = []

    for model in MODEL_LIST:
        try:
            if model in {"gemini-3.5-flash-lite", "gemini-3.6-flash"}:
                thinking_level = "minimal"
            else:
                thinking_level = "low"

            config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(
                    thinking_level=thinking_level
                )
            )

            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            used_model = model
            break

        except Exception as exc:
            errors.append(f"{model}: {exc}")
            if not is_retryable_model_error(exc):
                raise HTTPException(
                    status_code=502,
                    detail=f"Translation failed with {model}: {exc}",
                ) from exc
    else:
        raise HTTPException(
            status_code=502,
            detail="Translation failed. Tried: " + " | ".join(errors),
        )

    translated_text = (response.text or "").strip()

    if not translated_text:
        raise HTTPException(status_code=502, detail="The AI returned an empty translation.")

    return {
        "text": translated_text,
        "model": used_model,
    }


PDF_EXTRACTION_PROMPT = """
Read this educational curriculum PDF and extract all curriculum text.

Requirements:
1. Read the entire document/page content, including scanned or image-based pages.
2. Preserve the original reading order.
3. Preserve headings, subheadings, numbered lists, bullet points, examples, formulas,
   equations, units, symbols, tables, and important technical terms as accurately as possible.
4. Do not summarize, translate, or add information.
5. Return only the extracted curriculum text.
6. If a small part is genuinely unreadable, write [unclear] rather than inventing content.
""".strip()


def extract_pdf_with_gemini(client: genai.Client, data: bytes):
    """Use Gemini's native PDF understanding so scanned PDFs also work."""
    uploaded_file = client.files.upload(
        file=BytesIO(data),
        config={"mime_type": "application/pdf"},
    )

    try:
        response, used_model = generate_with_fallback(
            client,
            [PDF_EXTRACTION_PROMPT, uploaded_file],
            config=types.GenerateContentConfig(temperature=0),
        )
        return (response.text or "").strip(), used_model
    except Exception:
        # The Gemini Files API keeps uploads temporarily; the backend does not
        # need to persist the uploaded PDF locally.
        raise


@app.post("/api/extract-pdf")
async def extract_pdf(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    data = await file.read()

    # Gemini currently supports PDFs up to 50 MB.
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF is too large. Keep it under 50 MB.")

    if not data:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty.")

    client = get_client()

    # First try local extraction because it is faster and free of an AI call
    # for normal text PDFs. If there is no useful text, Gemini handles scanned
    # and image-based PDFs using native document understanding.
    try:
        reader = PdfReader(BytesIO(data))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        text = "\n\n".join(pages).strip()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read this PDF: {exc}") from exc

    if text:
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS]
            truncated = True
        else:
            truncated = False

        return {
            "filename": file.filename,
            "text": text,
            "truncated": truncated,
            "characters": len(text),
            "method": "pdf-text",
        }

    # No selectable text: send the actual PDF to Gemini instead of rejecting it.
    try:
        text, used_model = extract_pdf_with_gemini(client, data)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"AI PDF extraction failed after trying {len(MODEL_LIST)} model(s): {exc}",
        ) from exc

    if not text:
        raise HTTPException(status_code=422, detail="No readable curriculum text was found in the PDF.")

    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        truncated = True
    else:
        truncated = False

    return {
        "filename": file.filename,
        "text": text,
        "truncated": truncated,
        "characters": len(text),
        "method": "gemini-pdf",
        "model": used_model,
    }


IMAGE_MODELS = [
    model for model in MODEL_LIST
    if "flash" in model.lower() and "image" not in model.lower()
] or MODEL_LIST


def normalize_image_mime(file: UploadFile) -> str:
    """Return a Gemini-supported image MIME type based on the upload."""
    mime = (file.content_type or "").lower().split(";")[0].strip()
    allowed = {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/heic",
        "image/heif",
        "image/gif",
        "image/avif",
    }
    if mime in allowed:
        return "image/jpeg" if mime == "image/jpg" else mime

    filename = (file.filename or "").lower()
    extension_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".gif": "image/gif",
        ".avif": "image/avif",
    }
    for extension, mapped_mime in extension_map.items():
        if filename.endswith(extension):
            return mapped_mime

    return ""


@app.post("/api/extract-image")
async def extract_image(file: UploadFile = File(...)):
    mime_type = normalize_image_mime(file)
    if not mime_type:
        raise HTTPException(
            status_code=400,
            detail="Unsupported image. Please upload PNG, JPG/JPEG, WEBP, HEIC/HEIF, GIF, or AVIF.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")

    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image is too large. Keep it under 10 MB.")

    # Validate that the uploaded bytes are actually an image. This catches
    # mislabeled files before sending them to Gemini.
    try:
        from PIL import Image, UnidentifiedImageError

        image = Image.open(BytesIO(data))
        image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a valid readable image.",
        ) from exc

    client = get_client()

    prompt = """
You are an OCR engine for educational curriculum.

Read ALL visible text in this image. Return the text in natural reading order.

Rules:
1. Preserve headings and subheadings.
2. Preserve numbered lists and bullet points.
3. Preserve paragraphs, examples, formulas, equations, units, symbols, and technical terms.
4. Do not translate the text.
5. Do not summarize or explain anything.
6. Do not invent missing text.
7. If a small portion is genuinely unreadable, write [unclear].
8. Return ONLY the extracted text.
""".strip()

    errors = []
    for model in IMAGE_MODELS:
        try:
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(data=data, mime_type=mime_type),
                    prompt,
                ],
                config=types.GenerateContentConfig(temperature=0),
            )
            text = (response.text or "").strip()
            if text:
                if len(text) > MAX_CHARS:
                    text = text[:MAX_CHARS]
                return {
                    "filename": file.filename,
                    "text": text,
                    "characters": len(text),
                    "model": model,
                }
            errors.append(f"{model}: empty response")
        except Exception as exc:
            errors.append(f"{model}: {exc}")
            if not is_retryable_model_error(exc):
                raise HTTPException(
                    status_code=502,
                    detail=f"Image OCR failed with {model}: {exc}",
                ) from exc

    raise HTTPException(
        status_code=502,
        detail="Image OCR failed. Tried: " + " | ".join(errors),
    )

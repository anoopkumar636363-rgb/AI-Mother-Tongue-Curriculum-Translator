import asyncio
import json
import logging
import os
import random
import re
from html import escape as html_escape
from io import BytesIO
from pathlib import Path

import pymupdf
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types
from pydantic import BaseModel
from pypdf import PdfReader

load_dotenv(override=True)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("curriculum-translator")

# Separate Gemini API keys keep PDF/OCR traffic and normal translation traffic
# in separate quota buckets when the keys belong to separate projects.
# Both fall back to GEMINI_API_KEY so the app still works with one key.
TRANSLATION_API_KEY = (
    os.getenv("GEMINI_TRANSLATION_API_KEY")
    or os.getenv("GEMINI_API_KEY")
    or ""
).strip()
PDF_API_KEY = (
    os.getenv("GEMINI_PDF_API_KEY")
    or os.getenv("GEMINI_API_KEY")
    or ""
).strip()

DEFAULT_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
]
MODEL_LIST = [
    model.strip()
    for model in os.getenv("GEMINI_MODELS", ",".join(DEFAULT_MODELS)).split(",")
    if model.strip()
]
PDF_MODELS = [
    model.strip()
    for model in os.getenv(
        "GEMINI_PDF_MODELS",
        ",".join(DEFAULT_MODELS),
    ).split(",")
    if model.strip()
]

MAX_CHARS = 30000
MAX_LAYOUT_PDF_MB = 200
SCANNED_PDF_GEMINI_MB = 50

LAYOUT_WORKERS = max(1, int(os.getenv("LAYOUT_WORKERS", "4")))
LAYOUT_BATCH_CHARS = max(3000, int(os.getenv("LAYOUT_BATCH_CHARS", "8000")))
LAYOUT_MODEL_RETRIES = max(1, int(os.getenv("LAYOUT_MODEL_RETRIES", "2")))
LAYOUT_REQUEUE_LIMIT = max(1, int(os.getenv("LAYOUT_REQUEUE_LIMIT", "2")))
LAYOUT_REQUEST_TIMEOUT = max(30, int(os.getenv("LAYOUT_REQUEST_TIMEOUT", "120")))

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

BASE_DIR = Path(__file__).resolve().parent
FONT_DIR = BASE_DIR / "fonts"
FONT_FILES = {
    "Kannada": ("NotoSansKannada.ttf", "NotoSansKannada"),
    "Hindi": ("NotoSansDevanagari.ttf", "NotoSansDevanagari"),
    "Marathi": ("NotoSansDevanagari.ttf", "NotoSansDevanagari"),
    "Telugu": ("NotoSansTelugu.ttf", "NotoSansTelugu"),
    "Tamil": ("NotoSansTamil.ttf", "NotoSansTamil"),
    "Malayalam": ("NotoSansMalayalam.ttf", "NotoSansMalayalam"),
    "Bengali": ("NotoSansBengali.ttf", "NotoSansBengali"),
    "Gujarati": ("NotoSansGujarati.ttf", "NotoSansGujarati"),
    "Punjabi": ("NotoSansGurmukhi.ttf", "NotoSansGurmukhi"),
    "English": ("NotoSans.ttf", "NotoSans"),
}

app = FastAPI(
    title="AI Mother Tongue Curriculum Translator",
    version="1.3.0",
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")


def validate_target_language(target_language: str) -> str:
    if target_language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported target language.")
    return target_language


def get_translation_client() -> genai.Client:
    if not TRANSLATION_API_KEY:
        raise HTTPException(
            status_code=500,
            detail=(
                "Translation Gemini API key is missing. Add "
                "GEMINI_TRANSLATION_API_KEY or GEMINI_API_KEY to your .env file."
            ),
        )
    return genai.Client(api_key=TRANSLATION_API_KEY)


def get_pdf_client() -> genai.Client:
    if not PDF_API_KEY:
        raise HTTPException(
            status_code=500,
            detail=(
                "PDF Gemini API key is missing. Add "
                "GEMINI_PDF_API_KEY or GEMINI_API_KEY to your .env file."
            ),
        )
    return genai.Client(api_key=PDF_API_KEY)


def get_thinking_level(model: str) -> str:
    """Return one valid low-latency thinking level for the configured model."""
    normalized = model.lower()
    if normalized in {"gemini-3.8-flash", "gemini-3.7-flash"}:
        return "low"
    return "minimal"


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

    validate_target_language(target_language)

    if len(text) > MAX_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Text is too long for the prototype. Keep it under {MAX_CHARS:,} characters.",
        )

    client = get_translation_client()
    prompt = build_translation_prompt(text, target_language)
    errors = []

    for model in MODEL_LIST:
        try:
            config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(
                    thinking_level=get_thinking_level(model)
                )
            )
            response = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            translated_text = (response.text or "").strip()

            if not translated_text:
                raise ValueError("Gemini returned an empty translation.")

            return {
                "text": translated_text,
                "model": model,
            }

        except Exception as exc:
            errors.append(f"{model}: {exc}")
            logger.warning("Normal translation failed with %s: %s", model, exc)

            if not is_retryable_model_error(exc):
                raise HTTPException(
                    status_code=502,
                    detail=f"Translation failed with {model}: {exc}",
                ) from exc

    raise HTTPException(
        status_code=502,
        detail="Translation failed. Tried: " + " | ".join(errors),
    )


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


async def extract_pdf_with_gemini(client: genai.Client, data: bytes):
    """Use the dedicated PDF Gemini key/model pool for scanned PDFs."""
    uploaded_file = None

    try:
        uploaded_file = await asyncio.to_thread(
            client.files.upload,
            file=BytesIO(data),
            config={"mime_type": "application/pdf"},
        )

        errors = []
        for model in PDF_MODELS:
            try:
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=[PDF_EXTRACTION_PROMPT, uploaded_file],
                    config=types.GenerateContentConfig(),
                )
                text = (response.text or "").strip()
                if text:
                    return text, model

                errors.append(f"{model}: empty response")
                logger.warning("Gemini PDF extraction returned empty text with %s", model)

            except Exception as exc:
                errors.append(f"{model}: {exc}")
                logger.warning("Gemini PDF extraction failed with %s: %s", model, exc)

                if not is_retryable_model_error(exc):
                    raise

        raise RuntimeError("PDF extraction models failed: " + " | ".join(errors))

    finally:
        if uploaded_file is not None and getattr(uploaded_file, "name", None):
            try:
                await asyncio.to_thread(
                    client.files.delete,
                    name=uploaded_file.name,
                )
                logger.info("Deleted temporary Gemini file %s", uploaded_file.name)
            except Exception as cleanup_exc:
                # Cleanup must never turn an otherwise successful request into a failure.
                logger.warning(
                    "Could not delete temporary Gemini file %s: %s",
                    uploaded_file.name,
                    cleanup_exc,
                )


def extract_selectable_pdf_text(data: bytes):
    reader = PdfReader(BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages).strip()


@app.post("/api/extract-pdf")
async def extract_pdf(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    data = await file.read()

    if len(data) > MAX_LAYOUT_PDF_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"PDF is too large. Keep it under {MAX_LAYOUT_PDF_MB} MB.",
        )

    if not data:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty.")

    client = get_pdf_client()

    try:
        text = await asyncio.to_thread(extract_selectable_pdf_text, data)
    except Exception as exc:
        logger.exception("Could not extract local PDF text")
        raise HTTPException(status_code=400, detail=f"Could not read this PDF: {exc}") from exc

    if text:
        if len(text) > MAX_CHARS:
            logger.warning(
                "PDF text for %s exceeded MAX_CHARS=%d; returning truncated text",
                file.filename,
                MAX_CHARS,
            )
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

    if len(data) > SCANNED_PDF_GEMINI_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This PDF is over {SCANNED_PDF_GEMINI_MB} MB and has no selectable text. "
                "The layout-preserving translator works locally with large text PDFs, "
                "but Gemini's native PDF understanding is limited to 50 MB for scanned PDFs."
            ),
        )

    try:
        text, used_model = await extract_pdf_with_gemini(client, data)
    except Exception as exc:
        logger.exception("AI PDF extraction failed")
        raise HTTPException(
            status_code=502,
            detail=f"AI PDF extraction failed after trying {len(PDF_MODELS)} model(s): {exc}",
        ) from exc

    if not text:
        raise HTTPException(status_code=422, detail="No readable curriculum text was found in the PDF.")

    if len(text) > MAX_CHARS:
        logger.warning(
            "Gemini-extracted PDF text for %s exceeded MAX_CHARS=%d; returning truncated text",
            file.filename,
            MAX_CHARS,
        )
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


class TranslatedBlock(BaseModel):
    id: str
    text: str


class TranslatedBlocks(BaseModel):
    blocks: list[TranslatedBlock]


def extract_layout_blocks(pdf_data: bytes):
    """Extract selectable text blocks with original page rectangles and basic styling."""
    doc = pymupdf.open(stream=pdf_data, filetype="pdf")
    pages = []

    try:
        for page_number, page in enumerate(doc):
            page_blocks = []
            text_dict = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)

            for block_number, block in enumerate(text_dict.get("blocks", [])):
                if block.get("type") != 0:
                    continue

                lines = block.get("lines", [])
                line_texts = []
                spans = []

                for line in lines:
                    parts = []
                    for span in line.get("spans", []):
                        value = span.get("text", "")
                        if value:
                            parts.append(value)
                            spans.append(span)
                    if parts:
                        line_texts.append("".join(parts))

                text = "\n".join(line_texts).strip()
                if not text:
                    continue

                rect = pymupdf.Rect(block["bbox"])
                if rect.is_empty or rect.width < 1 or rect.height < 1:
                    continue

                first_span = spans[0] if spans else {}
                font_size = float(first_span.get("size", 11) or 11)
                font_flags = int(first_span.get("flags", 0) or 0)
                color_value = int(first_span.get("color", 0) or 0)
                color_hex = f"#{color_value & 0xFFFFFF:06x}"

                block_id = f"p{page_number + 1}b{block_number + 1}"
                page_blocks.append(
                    {
                        "id": block_id,
                        "page": page_number,
                        "rect": rect,
                        "text": text,
                        "font_size": max(6.0, min(font_size, 48.0)),
                        "bold": bool(font_flags & 16),
                        "italic": bool(font_flags & 2),
                        "color": color_hex,
                    }
                )

            pages.append(page_blocks)

        if not any(pages):
            raise HTTPException(
                status_code=422,
                detail=(
                    "This PDF has no selectable text. Layout-preserving mode currently "
                    "works with text-based PDFs; use Scan / Image or normal PDF translation for scanned PDFs."
                ),
            )

        return doc, pages
    except Exception:
        logger.exception("PyMuPDF layout extraction failed")
        doc.close()
        raise


def build_layout_translation_prompt(blocks, target_language: str) -> str:
    payload = [{"id": block["id"], "text": block["text"]} for block in blocks]
    return f"""
You are translating educational PDF text into {target_language}.

Translate every block while preserving the PDF's structure.

Rules:
1. Return exactly one object for every input block, using the same id.
2. Translate only the human-language text.
3. Preserve formulas, equations, numbers, units, symbols, code, URLs, variable names,
   chemical notation, and standard technical terms when translating them would reduce clarity.
4. Preserve line breaks when they are meaningful to the source.
5. Do not summarize, merge, split, reorder, or omit blocks.
6. Do not add explanations or commentary.
7. Use natural language appropriate for a student.

INPUT BLOCKS:
{json.dumps(payload, ensure_ascii=False)}
""".strip()


def split_layout_batches(blocks):
    """Split blocks into independent batches without splitting a block."""
    batches = []
    current = []
    current_chars = 0

    for block in blocks:
        size = len(block["text"])
        if current and current_chars + size > LAYOUT_BATCH_CHARS:
            batches.append(current)
            current = []
            current_chars = 0

        current.append(block)
        current_chars += size

    if current:
        batches.append(current)

    return batches


def validate_translated_batch(batch, response_text):
    """Validate Gemini's structured result before the brain accepts it."""
    parsed = TranslatedBlocks.model_validate_json(response_text)

    expected_ids = [block["id"] for block in batch]
    received_ids = [item.id for item in parsed.blocks]

    if received_ids != expected_ids:
        raise ValueError(
            "Gemini changed the PDF block structure "
            f"(expected {len(expected_ids)} blocks, received {len(received_ids)})."
        )

    if any(not item.text.strip() for item in parsed.blocks):
        raise ValueError("Gemini returned an empty translated block.")

    return {item.id: item.text for item in parsed.blocks}


async def translate_batch_with_fallback(client, batch, target_language: str):
    """Translate one batch through the configured PDF model fallback chain."""
    prompt = build_layout_translation_prompt(batch, target_language)
    last_errors = []

    for model in PDF_MODELS:
        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                thinking_level=get_thinking_level(model)
            ),
            response_mime_type="application/json",
            response_schema=TranslatedBlocks,
            max_output_tokens=20000,
        )

        for attempt in range(LAYOUT_MODEL_RETRIES):
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=config,
                    ),
                    timeout=LAYOUT_REQUEST_TIMEOUT,
                )

                response_text = (response.text or "").strip()
                if not response_text:
                    raise ValueError("Gemini returned an empty response.")

                return validate_translated_batch(batch, response_text), model

            except Exception as exc:
                last_errors.append(f"{model} attempt {attempt + 1}: {exc}")
                logger.warning(
                    "PDF translation batch failed: %s attempt %d: %s",
                    model,
                    attempt + 1,
                    exc,
                )

                if not is_retryable_model_error(exc) and not isinstance(exc, ValueError):
                    break

                if attempt < LAYOUT_MODEL_RETRIES - 1:
                    delay = min(30, 1.5 * (2 ** attempt) + random.uniform(0, 0.75))
                    await asyncio.sleep(delay)

    raise RuntimeError(
        "All configured Gemini fallback models failed for this batch. "
        + " | ".join(last_errors[-8:])
    )


async def translate_layout_blocks(client: genai.Client, blocks, target_language: str):
    """
    Translation Brain / Orchestrator.

    - Runs several independent batches concurrently.
    - Every batch uses the same model fallback chain.
    - Failed batches are requeued instead of killing the whole document.
    - A hard requeue limit prevents infinite loops.
    """
    batches = split_layout_batches(blocks)
    total_batches = len(batches)
    pending = list(enumerate(batches))
    completed = {}
    requeues = {index: 0 for index in range(total_batches)}
    semaphore = asyncio.Semaphore(LAYOUT_WORKERS)

    async def run_one(batch_index, batch):
        async with semaphore:
            return await translate_batch_with_fallback(
                client,
                batch,
                target_language,
            )

    while pending:
        tasks = [
            asyncio.create_task(run_one(batch_index, batch))
            for batch_index, batch in pending
        ]
        current = pending
        pending = []

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for (batch_index, batch), result in zip(current, results):
            if isinstance(result, Exception):
                requeues[batch_index] += 1

                if requeues[batch_index] <= LAYOUT_REQUEUE_LIMIT:
                    pending.append((batch_index, batch))
                    continue

                error_detail = str(result)
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"Translation brain could not complete batch "
                        f"{batch_index + 1}/{total_batches} after "
                        f"{LAYOUT_REQUEUE_LIMIT} requeues. "
                        f"Reason: {error_detail[-1800:]}"
                    ),
                )

            translated, used_model = result
            logger.info(
                "Translated PDF batch %d/%d with %s",
                batch_index + 1,
                total_batches,
                used_model,
            )
            completed[batch_index] = translated

        if pending:
            await asyncio.sleep(1.0)

    translated_by_id = {}
    for batch_index in range(total_batches):
        translated_by_id.update(completed[batch_index])

    return translated_by_id


def block_html(text: str) -> str:
    safe = html_escape(text, quote=False)
    return safe.replace("\n", "<br>")


def get_font_resources(target_language: str):
    filename, family = FONT_FILES[target_language]
    font_path = FONT_DIR / filename

    if not font_path.is_file():
        raise RuntimeError(
            f"Bundled font is missing: {font_path}. "
            "Run the font setup instructions in README.md."
        )

    archive = pymupdf.Archive(str(FONT_DIR))
    css = f"""
@font-face {{
    font-family: "{family}";
    src: url("{filename}");
    font-weight: 100 900;
    font-style: normal;
}}
* {{
    font-family: "{family}";
}}
""".strip()
    return archive, css


def apply_layout_translations(doc, pages, translated_by_id, target_language: str):
    """Replace original text while preserving graphics and using the target script font."""
    archive, font_css = get_font_resources(target_language)

    for page_number, blocks in enumerate(pages):
        page = doc[page_number]

        for block in blocks:
            rect = block["rect"]

            # Inset redaction by ~0.5pt to reduce the chance of erasing nearby
            # text that happens to touch a block rectangle. This is still
            # approximate because PDF text boxes can overlap other content.
            if rect.width > 1.0 and rect.height > 1.0:
                redact_rect = pymupdf.Rect(
                    rect.x0 + 0.5,
                    rect.y0 + 0.5,
                    rect.x1 - 0.5,
                    rect.y1 - 0.5,
                )
            else:
                redact_rect = rect

            page.add_redact_annot(
                redact_rect,
                fill=False,
                cross_out=False,
            )

        page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )

        for block in blocks:
            translated = translated_by_id.get(block["id"], "").strip()
            if not translated:
                continue

            font_weight = "bold" if block["bold"] else "normal"
            font_style = "italic" if block["italic"] else "normal"
            base_size = block["font_size"]

            inserted = False
            for attempt in range(3):
                font_size = base_size * (0.9 ** attempt)
                css = (
                    f'{font_css}\n'
                    f'* {{ font-size: {font_size:.2f}pt; '
                    f'font-weight: {font_weight}; '
                    f'font-style: {font_style}; '
                    f'color: {block["color"]}; '
                    "margin: 0; padding: 0; line-height: 1.15; }"
                )

                try:
                    result = page.insert_htmlbox(
                        block["rect"],
                        block_html(translated),
                        css=css,
                        archive=archive,
                        scale_low=1,
                        overlay=True,
                    )

                    if result[0] >= 0:
                        inserted = True
                        break

                    logger.warning(
                        "Translated block %s did not fit at %.1f%% font size; retrying",
                        block["id"],
                        (0.9 ** attempt) * 100,
                    )
                except Exception as exc:
                    logger.warning(
                        "Could not insert translated block %s on page %d at attempt %d: %s",
                        block["id"],
                        page_number + 1,
                        attempt + 1,
                        exc,
                    )

            if not inserted:
                logger.error(
                    "Skipping translated block %s on page %d after 3 insertion attempts",
                    block["id"],
                    page_number + 1,
                )

    return doc


def save_pdf_bytes(doc) -> bytes:
    output = BytesIO()
    doc.save(output, garbage=4, deflate=True)
    return output.getvalue()


@app.post("/api/translate-pdf")
async def translate_pdf(
    file: UploadFile = File(...),
    target_language: str = Form(...),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    validate_target_language(target_language)

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty.")

    if len(data) > MAX_LAYOUT_PDF_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"PDF is too large. Keep it under {MAX_LAYOUT_PDF_MB} MB.",
        )

    client = get_pdf_client()

    try:
        doc, pages = await asyncio.to_thread(extract_layout_blocks, data)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not parse PDF layout")
        raise HTTPException(
            status_code=400,
            detail=f"Could not read this PDF: {exc}",
        ) from exc

    all_blocks = [block for page_blocks in pages for block in page_blocks]

    try:
        translated_by_id = await translate_layout_blocks(
            client,
            all_blocks,
            target_language,
        )

        await asyncio.to_thread(
            apply_layout_translations,
            doc,
            pages,
            translated_by_id,
            target_language,
        )

        pdf_bytes = await asyncio.to_thread(save_pdf_bytes, doc)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not build the translated PDF")
        raise HTTPException(
            status_code=500,
            detail=f"Could not build the translated PDF: {exc}",
        ) from exc
    finally:
        await asyncio.to_thread(doc.close)

    original_name = re.sub(r"[^A-Za-z0-9._-]+", "-", file.filename)
    base_name = (
        re.sub(r"\.pdf$", "", original_name, flags=re.IGNORECASE).strip("-")
        or "curriculum"
    )
    safe_language = re.sub(
        r"[^A-Za-z0-9]+",
        "-",
        target_language.lower(),
    ).strip("-")
    download_name = f"{base_name}-{safe_language}-translated.pdf"

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
            "X-PDF-Pages": str(len(pages)),
            "X-PDF-Blocks": str(len(all_blocks)),
            "X-Translation-Batches": str(len(split_layout_batches(all_blocks))),
            "X-Translation-Workers": str(LAYOUT_WORKERS),
        },
    )


IMAGE_MODELS = PDF_MODELS


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


def validate_image_bytes(data: bytes):
    from PIL import Image, UnidentifiedImageError

    try:
        image = Image.open(BytesIO(data))
        image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a valid readable image.",
        ) from exc


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

    await asyncio.to_thread(validate_image_bytes, data)

    client = get_pdf_client()

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
            config = types.GenerateContentConfig()
            response = await client.aio.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(data=data, mime_type=mime_type),
                    prompt,
                ],
                config=config,
            )
            text = (response.text or "").strip()

            if text:
                if len(text) > MAX_CHARS:
                    logger.warning(
                        "Image OCR output exceeded MAX_CHARS=%d; truncating response",
                        MAX_CHARS,
                    )
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
            logger.warning("Image OCR failed with %s: %s", model, exc)

            if not is_retryable_model_error(exc):
                raise HTTPException(
                    status_code=502,
                    detail=f"Image OCR failed with {model}: {exc}",
                ) from exc

    raise HTTPException(
        status_code=502,
        detail="Image OCR failed. Tried: " + " | ".join(errors),
    )

# AI Mother Tongue Curriculum Translator

An AI-powered prototype that converts educational curriculum content into a student's mother tongue while preserving meaning, structure, and educational terminology.

## MVP features

- Paste/type curriculum text
- Upload a text-based PDF and extract its text
- Upload an image of a textbook page and let Gemini read it
- Translate into Kannada, Hindi, Telugu, Tamil, Marathi, Malayalam, Bengali, Gujarati, Punjabi, or English
- Preserve headings, bullet points, formulas, examples, and technical terms where possible
- Clean side-by-side original/translated output
- Separate Gemini workloads for normal translation vs PDF/OCR processing
- PDF/OCR traffic can use a dedicated Gemini API key

## Large PDF translation brain

The layout-preserving PDF translator supports PDFs up to **200 MB** when the PDF contains selectable text. PyMuPDF reads selectable text locally, so the full PDF is not sent to Gemini for layout translation. Scanned PDFs use Gemini's native PDF understanding through the dedicated PDF key; Google's documented PDF input limit is 50 MB.

### Separate Gemini API workloads

The app now separates:
- **Normal translation:** `GEMINI_TRANSLATION_API_KEY`
- **PDF translation / PDF extraction / image OCR:** `GEMINI_PDF_API_KEY`

For genuinely separate quota, create the second key in a separate Google AI Studio/GCP project. If either key is missing, the app falls back to `GEMINI_API_KEY`.

Google recommends the Files API for larger PDFs or documents reused across requests, and Gemini can process PDFs with native vision and structured extraction.

A translation brain splits text blocks into batches and runs multiple workers concurrently. Every worker uses the same Gemini fallback chain:

`model 1 → model 2 → model 3 → model 4`

If a model fails, the worker falls back to the next model. Failed batches can be requeued with bounded retries, and block IDs are validated before the result is accepted.

Configurable environment variables:

- `LAYOUT_WORKERS=4` — concurrent Gemini workers
- `LAYOUT_BATCH_CHARS=12000` — approximate text size per AI batch
- `LAYOUT_MODEL_RETRIES=2` — attempts per fallback model
- `LAYOUT_REQUEUE_LIMIT=2` — brain-level requeues for a failed batch
- `LAYOUT_REQUEST_TIMEOUT=120` — seconds before a model request is treated as stuck

Scanned/image-only PDFs over 50 MB still cannot use Gemini's native PDF understanding because Gemini's documented PDF input limit is 50 MB; use the existing image/OCR workflow for those documents.

## Stack

- FastAPI
- Python
- Google Gemini API via `google-genai`
- PyPDF for PDF text extraction
- HTML/CSS/JavaScript frontend

## Run locally

### 1. Create a virtual environment

```bash
python -m venv venv
venv\\Scripts\\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Add your Gemini API key

Copy `.env.example` to `.env` and add:

```
GEMINI_TRANSLATION_API_KEY=your_translation_key_here
GEMINI_PDF_API_KEY=your_pdf_key_here

# Optional backward-compatible fallback:
GEMINI_API_KEY=your_key_here
```

### 4. Start the app

```bash
uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000

## Project structure

```
backend/
  main.py
frontend/
  index.html
  style.css
  app.js
requirements.txt
.env.example
.gitignore
README.md
```

## Important

This is a hackathon prototype, not a certified translation system. Always review translated educational material before classroom use.

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
- Layout-preserving PDF output uses bundled Noto Sans fonts for Indian scripts

## Teacher / Admin dashboard

The app includes a password-protected dashboard at the top-level **Dashboard** tab.

Dashboard features:

- SQLite usage logging in `backend/data/app.db`
- Translation totals, success/failure counts, success rate, character totals, and average duration
- Counts by target language, source type, subject, grade, and Gemini model
- 7 / 30 / 90 day chart ranges
- Translations-per-language bar chart and daily line chart using Chart.js from a CDN
- Paginated event table with language, source type, and success filters
- Recent 20 events in the stats response
- CSV export
- Login/logout with the password held only in the browser's in-memory JavaScript variable

Set `ADMIN_PASSWORD` in `.env` before using the dashboard. If it is missing, admin endpoints return HTTP 503. The database stores only usage metadata and counts; it never stores document text or uploaded filenames.

The database is created automatically on application startup. `backend/data/` and SQLite database files are ignored by Git.

### Admin API

- `POST /api/admin/login` — verifies `X-Admin-Password`
- `GET /api/admin/stats?days=30` — protected dashboard aggregates
- `GET /api/admin/events?page=1&page_size=25&language=&source_type=&success=` — protected paginated event log
- `GET /api/admin/export/events.csv` — protected CSV export

All admin endpoints validate their limits and allowed filter values. Admin password comparisons use constant-time comparison and failed authentication has a short delay.

## Large PDF translation brain

The layout-preserving PDF translator supports PDFs up to **200 MB** when the PDF contains selectable text. PyMuPDF reads selectable text locally, so the full PDF is not sent to Gemini for layout translation. Scanned PDFs use Gemini's native PDF understanding through the dedicated PDF key; Google's documented PDF input limit is 50 MB.

### Separate Gemini model/key workloads

There are two model lists:

- **GEMINI_MODELS** — normal /api/translate text translation.
- **GEMINI_PDF_MODELS** — scanned-PDF extraction, layout-preserving PDF translation, and image OCR.

The PDF pipeline uses the full configured fallback chain in GEMINI_PDF_MODELS. It is not limited to a fixed number of models in the Python code.

There are also two API-key variables:

- **GEMINI_TRANSLATION_API_KEY** — normal text translation.
- **GEMINI_PDF_API_KEY** — PDF translation, PDF extraction, and image OCR.

For genuinely separate quota, create the second key in a separate Google AI Studio/GCP project. If either dedicated key is missing, the app falls back to GEMINI_API_KEY.

Google's Python SDK provides async methods under client.aio, which the API handlers use for Gemini generation. Local CPU/file work is moved off the event loop with asyncio.to_thread.

### Translation brain settings

A PDF is converted into layout-aware text blocks. Blocks are split into batches without splitting an individual block, then several batches can run concurrently.

Current defaults:

- LAYOUT_WORKERS=4 — maximum concurrent Gemini translation requests.
- LAYOUT_BATCH_CHARS=8000 — approximate text size per AI batch.
- LAYOUT_MODEL_RETRIES=2 — attempts per model in the fallback chain.
- LAYOUT_REQUEUE_LIMIT=2 — brain-level requeues for a failed batch.
- LAYOUT_REQUEST_TIMEOUT=120 — seconds before a model request is treated as stuck.

Each batch must return the same block IDs in the same order. Invalid or incomplete structured output is rejected before the result is accepted.

## Indian-script PDF fonts

PDF reconstruction does not rely on the platform's generic sans-serif font. The backend maps each target language to a script-specific bundled Noto Sans font and loads it with PyMuPDF's Archive plus CSS @font-face.

Bundled fonts:

- Noto Sans — English
- Noto Sans Devanagari — Hindi and Marathi
- Noto Sans Kannada — Kannada
- Noto Sans Telugu — Telugu
- Noto Sans Tamil — Tamil
- Noto Sans Malayalam — Malayalam
- Noto Sans Bengali — Bengali
- Noto Sans Gujarati — Gujarati
- Noto Sans Gurmukhi — Punjabi

The repository includes an automated GitHub Actions font-bundling workflow. If you clone the repository before that workflow has populated backend/fonts/, run the workflow or download the regular Noto Sans TTF files from the official Noto repository:

- https://github.com/notofonts/noto-fonts
- https://notofonts.github.io/

Place the files in backend/fonts/ using the filenames expected by backend/main.py.

Noto fonts are distributed under the SIL Open Font License; check the upstream font metadata/repository for the exact license text.

The PDF reconstruction uses a small inset for redaction rectangles to reduce accidental removal of adjacent text. It also retries an overflowing translated block at smaller font sizes up to three times. If one block still cannot fit or be inserted, that block is skipped and the rest of the document continues.

## PDF extraction cleanup

Gemini File API uploads used for scanned PDFs are deleted in a finally cleanup step after extraction. Cleanup failures are logged but never replace the original request result.

Text extracted from /api/extract-pdf is still capped at **30,000 characters** because that endpoint's response contract is unchanged. When truncation occurs, the response keeps "truncated": true and the backend logs a warning.

## Stack

- FastAPI
- Python
- Google Gemini API via google-genai
- PyPDF for local PDF text extraction
- PyMuPDF for layout-aware PDF reconstruction
- Pillow for image validation
- HTML/CSS/JavaScript frontend

## Run locally

### 1. Create a virtual environment

Windows PowerShell:

~~~powershell
python -m venv venv
venv\Scripts\activate
~~~

### 2. Install dependencies

~~~bash
pip install -r requirements.txt
~~~

### 3. Add your Gemini API keys and admin password

Copy .env.example to .env and add:

~~~env
GEMINI_TRANSLATION_API_KEY=your_translation_key_here
GEMINI_PDF_API_KEY=your_pdf_key_here

# Optional backward-compatible fallback:
GEMINI_API_KEY=your_key_here

# Required for the Teacher/Admin dashboard:
ADMIN_PASSWORD=choose_a_strong_dashboard_password
~~~

Do not commit .env or expose API keys in screenshots, source code, or GitHub.

### 4. Start the app

~~~bash
uvicorn backend.main:app --reload
~~~

Open http://127.0.0.1:8000

## Tests

Install the dependencies and run:

~~~bash
pytest
~~~

The test suite covers:

- structured translated-block validation
- layout batch splitting
- supported/unsupported target-language validation
- admin login with correct, incorrect, and missing passwords
- dashboard stats aggregation from sample SQLite events
- logging failures being ignored so they cannot break /api/translate

## Project structure

~~~
backend/
  main.py
  db.py
  routes_admin.py
  data/
    app.db
  fonts/
    NotoSans*.ttf
frontend/
  index.html
  style.css
  app.js
tests/
  test_main.py
  test_admin.py
requirements.txt
.env.example
.gitignore
README.md
~~~

## Important

This is a hackathon prototype, not a certified translation system. Always review translated educational material before classroom use.

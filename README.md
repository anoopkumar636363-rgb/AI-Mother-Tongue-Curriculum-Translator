# AI Mother Tongue Curriculum Translator

An AI-powered prototype that converts educational curriculum content into a student's mother tongue while preserving meaning, structure, and educational terminology.

## MVP features

- Paste/type curriculum text
- Upload a text-based PDF and extract its text
- Upload an image of a textbook page and let Gemini read it
- Translate into Kannada, Hindi, Telugu, Tamil, Marathi, Malayalam, Bengali, Gujarati, Punjabi, or English
- Preserve headings, bullet points, formulas, examples, and technical terms where possible
- Clean side-by-side original/translated output
- Character limit keeps the hackathon demo fast and predictable

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

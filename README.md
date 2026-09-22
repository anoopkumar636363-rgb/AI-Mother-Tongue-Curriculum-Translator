# AI Mother Tongue Curriculum Translator

An AI-powered prototype that converts educational curriculum content into a student's mother tongue while preserving meaning, structure, and educational terminology.

## Features

- Text translation
- PDF text extraction
- Layout-preserving PDF translation
- Image OCR
- Library
- Glossary
- Admin dashboard

## Setup

### 1. Create a virtual environment

Windows PowerShell:

~~~powershell
python -m venv venv
venv\Scripts\activate
~~~

### 2. Install requirements

~~~bash
pip install -r requirements.txt
~~~

### 3. Configure Gemini

Copy `.env.example` to `.env` and add your Gemini API key:

~~~text
GEMINI_API_KEY=your_gemini_api_key_here
~~~

A single `GEMINI_API_KEY` is enough for the text, PDF, and image features.

### 4. Start the app

Run from the repository root:

~~~bash
uvicorn backend.main:app --reload
~~~

Open http://127.0.0.1:8000

### 5. Run the tests

~~~bash
pytest
~~~

## Development notes

The SQLite database is created automatically when `backend.main` is imported. The app mounts the repository's `frontend` directory using a path resolved from `backend/main.py`.

Dedicated Gemini translation/PDF key variables remain supported; `GEMINI_API_KEY` is the common fallback.

## Project structure

~~~
backend/
  main.py
  config.py
  db.py
  routes_admin.py
  routes_library.py
  routes_glossary.py
  glossary.py
  fonts/
frontend/
  index.html
  style.css
  app.js
tests/
  test_main.py
  test_admin.py
  test_library.py
requirements.txt
.env.example
.gitignore
README.md
~~~

## Important

This is a hackathon prototype, not a certified translation system. Always review translated educational material before classroom use.
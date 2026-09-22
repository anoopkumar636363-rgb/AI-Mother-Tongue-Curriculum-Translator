from datetime import datetime, timezone
import json
import sqlite3

from fastapi import APIRouter, HTTPException, Query
from google.genai import types
from pydantic import BaseModel, Field

from backend.config import ALLOWED_LANGUAGES
from backend.db import get_connection
from backend.glossary import build_glossary_suggestion_prompt

router = APIRouter(prefix="/api/glossary", tags=["glossary"])


def _now():
    return datetime.now(timezone.utc).isoformat()


class GlossaryTerm(BaseModel):
    source_term: str = Field(..., min_length=1)
    target_language: str = Field(..., min_length=1)
    translated_term: str = Field(..., min_length=1)
    subject: str = ""


class GlossaryTermUpdate(BaseModel):
    source_term: str | None = Field(default=None, min_length=1)
    target_language: str | None = Field(default=None, min_length=1)
    translated_term: str | None = Field(default=None, min_length=1)
    subject: str | None = None


@router.get("")
async def list_glossary(
    language: str = Query(""),
    subject: str = Query(""),
):
    clauses = []
    params = []

    if language:
        clauses.append("target_language = ?")
        params.append(language)

    if subject:
        clauses.append("subject = ?")
        params.append(subject)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, source_term, target_language, translated_term, subject, created_at
            FROM glossary_terms
            {where}
            ORDER BY id DESC
            """,
            params,
        ).fetchall()

    return {"items": [dict(row) for row in rows]}


@router.post("", status_code=201)
async def create_glossary(item: GlossaryTerm):
    source_term = item.source_term.strip()
    target_language = item.target_language.strip()
    translated_term = item.translated_term.strip()
    subject = item.subject.strip()

    if not source_term or not target_language or not translated_term:
        raise HTTPException(
            status_code=400,
            detail="source_term, target_language, and translated_term are required.",
        )

    now = _now()

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO glossary_terms
                (source_term, target_language, translated_term, subject, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source_term, target_language, translated_term, subject, now),
            )
            row = conn.execute(
                """
                SELECT id, source_term, target_language, translated_term, subject, created_at
                FROM glossary_terms
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
            conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="A glossary term with the same source term, language, and subject already exists.",
        )

    return dict(row)


class GlossarySuggestRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=30000)
    target_language: str = Field(..., min_length=1)
    subject: str = ""


def _parse_glossary_suggestions(raw_text: str):
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise ValueError("Gemini returned empty glossary suggestions.")

    lines = raw_text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

    payload = json.loads("\n".join(lines).strip())
    if not isinstance(payload, list):
        raise ValueError("Gemini glossary response must be a JSON array.")

    suggestions = []
    seen = set()

    for item in payload:
        if not isinstance(item, dict):
            continue
        source_term = str(item.get("source_term", "")).strip()
        translated_term = str(item.get("translated_term", "")).strip()
        if not source_term or not translated_term:
            continue
        key = source_term.casefold()
        if key in seen:
            continue
        seen.add(key)
        suggestions.append({
            "source_term": source_term,
            "translated_term": translated_term,
        })

    if not suggestions:
        raise ValueError("Gemini returned no usable glossary suggestions.")

    return suggestions[:20]


@router.post("/suggest")
async def suggest_glossary(request: GlossarySuggestRequest):
    text = request.text.strip()
    target_language = request.target_language.strip()
    subject = request.subject.strip()

    if not text:
        raise HTTPException(status_code=400, detail="Curriculum text is required.")
    if target_language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported target language.")

    prompt = build_glossary_suggestion_prompt(text, target_language, subject)

    # main.py owns the existing Gemini client/model fallback chain.
    # Importing it only at request time avoids a startup circular import.
    from backend import main as main_module

    with get_connection() as conn:
        if subject:
            rows = conn.execute(
                """
                SELECT source_term
                FROM glossary_terms
                WHERE target_language = ?
                  AND (subject = '' OR subject IS NULL OR lower(subject) = lower(?))
                """,
                (target_language, subject),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT source_term
                FROM glossary_terms
                WHERE target_language = ?
                  AND (subject = '' OR subject IS NULL)
                """,
                (target_language,),
            ).fetchall()

    existing_terms = {row["source_term"].casefold() for row in rows}
    client = main_module.get_translation_client()
    errors = []

    for model in main_module.MODEL_LIST:
        try:
            config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(
                    thinking_level=main_module.get_thinking_level(model)
                ),
                response_mime_type="application/json",
            )
            response = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            suggestions = _parse_glossary_suggestions(response.text)
            suggestions = [
                item for item in suggestions
                if item["source_term"].casefold() not in existing_terms
            ]
            return {"suggestions": suggestions}

        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{model}: {exc}")
            logger.warning(
                "Glossary suggestion parsing failed with %s: %s",
                model,
                exc,
            )
            continue

        except Exception as exc:
            errors.append(f"{model}: {exc}")
            logger.warning("Glossary suggestion failed with %s: %s", model, exc)
            if not main_module.is_retryable_model_error(exc):
                raise HTTPException(
                    status_code=502,
                    detail=f"Glossary suggestion failed with {model}: {exc}",
                ) from exc

    raise HTTPException(
        status_code=502,
        detail="Could not generate glossary suggestions. Tried: " + " | ".join(errors),
    )


@router.put("/{item_id}")
async def update_glossary(item_id: int, item: GlossaryTermUpdate):
    data = item.model_dump(exclude_unset=True)

    if not data:
        raise HTTPException(status_code=400, detail="Provide at least one field to update.")

    updates = []
    values = []

    for field in ("source_term", "target_language", "translated_term", "subject"):
        if field in data:
            value = data[field]
            if isinstance(value, str):
                value = value.strip()
            if field in {"source_term", "target_language", "translated_term"} and not value:
                raise HTTPException(status_code=400, detail=f"{field} cannot be empty.")
            updates.append(f"{field} = ?")
            values.append(value)

    values.append(item_id)

    try:
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM glossary_terms WHERE id = ?",
                (item_id,),
            ).fetchone()

            if existing is None:
                raise HTTPException(status_code=404, detail="Glossary term not found.")

            conn.execute(
                f"""
                UPDATE glossary_terms
                SET {", ".join(updates)}
                WHERE id = ?
                """,
                values,
            )

            row = conn.execute(
                """
                SELECT id, source_term, target_language, translated_term, subject, created_at
                FROM glossary_terms
                WHERE id = ?
                """,
                (item_id,),
            ).fetchone()
            conn.commit()
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="A glossary term with the same source term, language, and subject already exists.",
        )

    return dict(row)


@router.delete("/{item_id}")
async def delete_glossary(item_id: int):
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM glossary_terms WHERE id = ?",
            (item_id,),
        )

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Glossary term not found.")

        conn.commit()

    return {"deleted": True, "id": item_id}

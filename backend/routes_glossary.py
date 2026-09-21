from datetime import datetime, timezone
import sqlite3

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import get_connection

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

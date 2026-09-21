import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from backend.db import get_connection
from backend.config import ALLOWED_LANGUAGES

logger = logging.getLogger("curriculum-translator")

router = APIRouter(prefix="/api/library", tags=["library"])

SOURCE_TYPES = {"text", "pdf", "image"}
MAX_TEXT = 200_000


class LibraryCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    subject: str = Field(default="", max_length=100)
    grade: str = Field(default="", max_length=50)
    target_language: str
    source_type: str
    original_text: str = Field(..., max_length=MAX_TEXT)
    translated_text: str = Field(..., max_length=MAX_TEXT)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be empty.")
        return value

    @field_validator("subject", "grade")
    @classmethod
    def trim_optional(cls, value: str) -> str:
        return value.strip()

    @field_validator("target_language")
    @classmethod
    def valid_language(cls, value: str) -> str:
        if value not in ALLOWED_LANGUAGES:
            raise ValueError("Unsupported target language.")
        return value

    @field_validator("source_type")
    @classmethod
    def valid_source_type(cls, value: str) -> str:
        if value not in SOURCE_TYPES:
            raise ValueError("Unsupported source type.")
        return value


class LibraryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    subject: str | None = Field(default=None, max_length=100)
    grade: str | None = Field(default=None, max_length=50)
    translated_text: str | None = Field(default=None, max_length=MAX_TEXT)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be empty.")
        return value


def _now():
    return datetime.now(timezone.utc).isoformat()


def _row(row):
    return dict(row) if row else None


@router.post("")
async def create_library_item(payload: LibraryCreate):
    created_at = _now()
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO translations
                (title, subject, grade, target_language, source_type,
                 original_text, translated_text, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.title,
                    payload.subject or None,
                    payload.grade or None,
                    payload.target_language,
                    payload.source_type,
                    payload.original_text,
                    payload.translated_text,
                    created_at,
                    created_at,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM translations WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return _row(row)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to save library item")
        raise HTTPException(status_code=500, detail="Could not save the teaching material.")


@router.get("/filters")
async def library_filters():
    try:
        with get_connection() as conn:
            languages = [
                row["value"] for row in conn.execute(
                    "SELECT DISTINCT target_language AS value FROM translations "
                    "WHERE target_language IS NOT NULL AND TRIM(target_language) <> '' "
                    "ORDER BY value"
                ).fetchall()
            ]
            subjects = [
                row["value"] for row in conn.execute(
                    "SELECT DISTINCT subject AS value FROM translations "
                    "WHERE subject IS NOT NULL AND TRIM(subject) <> '' "
                    "ORDER BY value"
                ).fetchall()
            ]
            grades = [
                row["value"] for row in conn.execute(
                    "SELECT DISTINCT grade AS value FROM translations "
                    "WHERE grade IS NOT NULL AND TRIM(grade) <> '' "
                    "ORDER BY value"
                ).fetchall()
            ]
        return {"languages": languages, "subjects": subjects, "grades": grades}
    except Exception:
        logger.exception("Failed to load library filters")
        raise HTTPException(status_code=500, detail="Could not load library filters.")


@router.get("")
async def list_library(
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(25, ge=1, le=50),
    q: str = Query("", max_length=200),
    language: str = Query("", max_length=100),
    subject: str = Query("", max_length=100),
    grade: str = Query("", max_length=50),
):
    if language and language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported language filter.")
    clauses = []
    params = []
    if q:
        like = f"%{q}%"
        clauses.append("(title LIKE ? OR subject LIKE ? OR translated_text LIKE ?)")
        params.extend([like, like, like])
    if language:
        clauses.append("target_language = ?")
        params.append(language)
    if subject:
        clauses.append("subject = ?")
        params.append(subject)
    if grade:
        clauses.append("grade = ?")
        params.append(grade)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    offset = (page - 1) * page_size

    try:
        with get_connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM translations{where}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT id, title, subject, grade, target_language, source_type,
                       substr(translated_text, 1, 150) AS preview,
                       created_at, updated_at
                FROM translations
                {where}
                ORDER BY updated_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
            "items": [_row(row) for row in rows],
        }
    except Exception:
        logger.exception("Failed to list library items")
        raise HTTPException(status_code=500, detail="Could not load saved materials.")


@router.get("/{item_id}")
async def get_library_item(item_id: int):
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM translations WHERE id = ?",
                (item_id,),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Saved material not found.")
        return _row(row)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to load library item %s", item_id)
        raise HTTPException(status_code=500, detail="Could not load the saved material.")


@router.put("/{item_id}")
async def update_library_item(item_id: int, payload: LibraryUpdate):
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=400, detail="No changes supplied.")

    fields = []
    params = []
    for field in ("title", "subject", "grade", "translated_text"):
        if field in values:
            fields.append(f"{field} = ?")
            params.append(values[field] if values[field] != "" else None)

    updated_at = _now()
    fields.append("updated_at = ?")
    params.append(updated_at)
    params.append(item_id)

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE translations SET {', '.join(fields)} WHERE id = ?",
                params,
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Saved material not found.")
            conn.commit()
            row = conn.execute(
                "SELECT * FROM translations WHERE id = ?",
                (item_id,),
            ).fetchone()
        return _row(row)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to update library item %s", item_id)
        raise HTTPException(status_code=500, detail="Could not update the saved material.")


@router.delete("/{item_id}")
async def delete_library_item(item_id: int):
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM translations WHERE id = ?",
                (item_id,),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Saved material not found.")
            conn.commit()
        return {"deleted": True, "id": item_id}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete library item %s", item_id)
        raise HTTPException(status_code=500, detail="Could not delete the saved material.")

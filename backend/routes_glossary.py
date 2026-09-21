import csv
import io
import logging
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from backend.config import ALLOWED_LANGUAGES
from backend.db import get_connection

router = APIRouter(prefix="/api/glossary", tags=["glossary"])
logger = logging.getLogger("curriculum-translator")

MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_PAGE_SIZE = 100
REQUIRED_CSV_COLUMNS = {
    "source_term",
    "target_language",
    "translated_term",
    "subject",
    "notes",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _clean_optional(value):
    return (value or "").strip()


class GlossaryCreate(BaseModel):
    source_term: str = Field(..., min_length=1, max_length=200)
    target_language: str
    translated_term: str = Field(..., min_length=1, max_length=200)
    subject: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=500)

    @field_validator("source_term", "translated_term")
    @classmethod
    def validate_term(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Term cannot be blank.")
        return value

    @field_validator("subject", "notes")
    @classmethod
    def strip_optional(cls, value):
        return value.strip()

    @field_validator("target_language")
    @classmethod
    def validate_language(cls, value):
        value = value.strip()
        if value not in ALLOWED_LANGUAGES:
            raise ValueError("Unsupported target language.")
        return value


class GlossaryUpdate(BaseModel):
    source_term: str | None = Field(default=None, min_length=1, max_length=200)
    target_language: str | None = None
    translated_term: str | None = Field(default=None, min_length=1, max_length=200)
    subject: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("source_term", "translated_term")
    @classmethod
    def validate_optional_term(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Term cannot be blank.")
        return value

    @field_validator("subject", "notes")
    @classmethod
    def strip_optional_fields(cls, value):
        return value.strip() if value is not None else value

    @field_validator("target_language")
    @classmethod
    def validate_optional_language(cls, value):
        if value is None:
            return value
        value = value.strip()
        if value not in ALLOWED_LANGUAGES:
            raise ValueError("Unsupported target language.")
        return value


def _get_item(conn, item_id: int):
    return conn.execute(
        """
        SELECT id, source_term, target_language, translated_term, subject, notes,
               created_at, updated_at
        FROM glossary_terms
        WHERE id = ?
        """,
        (item_id,),
    ).fetchone()


def _validate_filters(language: str, subject: str, q: str):
    if language and language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported target language filter.")
    if len(subject) > 100:
        raise HTTPException(status_code=400, detail="Subject filter is too long.")
    if len(q) > 200:
        raise HTTPException(status_code=400, detail="Search query is too long.")


@router.get("")
async def list_glossary(
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
    language: str = Query(""),
    subject: str = Query(""),
    q: str = Query(""),
):
    try:
        language = language.strip()
        subject = subject.strip()
        q = q.strip()
        _validate_filters(language, subject, q)

        clauses = []
        params = []

        if language:
            clauses.append("target_language = ?")
            params.append(language)
        if subject:
            clauses.append("subject = ?")
            params.append(subject)
        if q:
            clauses.append("(source_term LIKE ? COLLATE NOCASE OR translated_term LIKE ? COLLATE NOCASE)")
            pattern = f"%{q}%"
            params.extend([pattern, pattern])

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        offset = (page - 1) * page_size

        with get_connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM glossary_terms{where}",
                params,
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT id, source_term, target_language, translated_term, subject,
                       notes, created_at, updated_at
                FROM glossary_terms
                {where}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()

        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
            "items": [dict(row) for row in rows],
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to list glossary terms")
        raise HTTPException(status_code=500, detail="Could not load glossary terms.")


@router.get("/subjects")
async def glossary_subjects():
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT subject
                FROM glossary_terms
                WHERE TRIM(subject) <> ''
                ORDER BY subject COLLATE NOCASE ASC
                """
            ).fetchall()
        return {"subjects": [row["subject"] for row in rows]}
    except Exception:
        logger.exception("Failed to load glossary subjects")
        raise HTTPException(status_code=500, detail="Could not load glossary subjects.")


@router.post("")
async def create_glossary(item: GlossaryCreate):
    now = _now()
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO glossary_terms
                (source_term, target_language, translated_term, subject, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.source_term,
                    item.target_language,
                    item.translated_term,
                    item.subject,
                    item.notes,
                    now,
                    now,
                ),
            )
            created = _get_item(conn, cursor.lastrowid)
            conn.commit()
        return dict(created)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="A glossary term with the same source term, language, and subject already exists.",
        )
    except Exception:
        logger.exception("Failed to create glossary term")
        raise HTTPException(status_code=500, detail="Could not create glossary term.")


@router.get("/export")
async def export_glossary(
    language: str = Query(""),
    subject: str = Query(""),
    q: str = Query(""),
):
    try:
        language = language.strip()
        subject = subject.strip()
        q = q.strip()
        _validate_filters(language, subject, q)

        clauses = []
        params = []
        if language:
            clauses.append("target_language = ?")
            params.append(language)
        if subject:
            clauses.append("subject = ?")
            params.append(subject)
        if q:
            clauses.append("(source_term LIKE ? COLLATE NOCASE OR translated_term LIKE ? COLLATE NOCASE)")
            pattern = f"%{q}%"
            params.extend([pattern, pattern])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""

        with get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT source_term, target_language, translated_term, subject, notes
                FROM glossary_terms
                {where}
                ORDER BY source_term COLLATE NOCASE ASC, id ASC
                """,
                params,
            ).fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["source_term", "target_language", "translated_term", "subject", "notes"])
        for row in rows:
            writer.writerow([row[key] for key in row.keys()])

        data = output.getvalue().encode("utf-8-sig")
        return StreamingResponse(
            iter([data]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="translation-glossary.csv"'},
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to export glossary CSV")
        raise HTTPException(status_code=500, detail="Could not export glossary CSV.")

@router.put("/{item_id}")
async def update_glossary(item_id: int, item: GlossaryUpdate):
    data = item.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="Provide at least one field to update.")

    fields = []
    values = []
    allowed = {
        "source_term",
        "target_language",
        "translated_term",
        "subject",
        "notes",
    }

    for field in allowed:
        if field in data:
            fields.append(f"{field} = ?")
            values.append(data[field])

    values.append(_now())
    values.append(item_id)

    try:
        with get_connection() as conn:
            if _get_item(conn, item_id) is None:
                raise HTTPException(status_code=404, detail="Glossary term not found.")

            conn.execute(
                f"""
                UPDATE glossary_terms
                SET {", ".join(fields)}, updated_at = ?
                WHERE id = ?
                """,
                values,
            )
            updated = _get_item(conn, item_id)
            conn.commit()
        return dict(updated)
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="A glossary term with the same source term, language, and subject already exists.",
        )
    except Exception:
        logger.exception("Failed to update glossary term %s", item_id)
        raise HTTPException(status_code=500, detail="Could not update glossary term.")


@router.delete("/{item_id}")
async def delete_glossary(item_id: int):
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM glossary_terms WHERE id = ?",
                (item_id,),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Glossary term not found.")
            conn.commit()
        return {"deleted": True, "id": item_id}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete glossary term %s", item_id)
        raise HTTPException(status_code=500, detail="Could not delete glossary term.")


@router.post("/import")
async def import_glossary(file: UploadFile = File(...)):
    try:
        data = await file.read(MAX_IMPORT_BYTES + 1)
        if len(data) > MAX_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="CSV file is too large. Maximum size is 5 MB.")
        if not data:
            raise HTTPException(status_code=400, detail="The uploaded CSV is empty.")

        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail="CSV must be UTF-8 encoded. Excel UTF-8 BOM exports are supported.",
            ) from exc

        reader = csv.DictReader(io.StringIO(text))
        headers = {header.strip() for header in (reader.fieldnames or []) if header}
        missing_headers = REQUIRED_CSV_COLUMNS - headers
        if missing_headers:
            raise HTTPException(
                status_code=400,
                detail="CSV is missing required columns: " + ", ".join(sorted(missing_headers)),
            )

        added = updated = skipped = 0
        errors = []
        seen_keys = set()

        with get_connection() as conn:
            for row_number, row in enumerate(reader, start=2):
                try:
                    source_term = _clean_optional(row.get("source_term"))
                    target_language = _clean_optional(row.get("target_language"))
                    translated_term = _clean_optional(row.get("translated_term"))
                    subject = _clean_optional(row.get("subject"))
                    notes = _clean_optional(row.get("notes"))

                    reasons = []
                    if not source_term or len(source_term) > 200:
                        reasons.append("source_term must be 1-200 characters")
                    if target_language not in ALLOWED_LANGUAGES:
                        reasons.append("unsupported target_language")
                    if not translated_term or len(translated_term) > 200:
                        reasons.append("translated_term must be 1-200 characters")
                    if len(subject) > 100:
                        reasons.append("subject must be at most 100 characters")
                    if len(notes) > 500:
                        reasons.append("notes must be at most 500 characters")

                    if reasons:
                        skipped += 1
                        errors.append({"row": row_number, "reasons": reasons})
                        continue

                    key = (source_term.casefold(), target_language, subject)
                    if key in seen_keys:
                        skipped += 1
                        errors.append({"row": row_number, "reasons": ["duplicate row in CSV"]})
                        continue
                    seen_keys.add(key)

                    existing = conn.execute(
                        """
                        SELECT id, translated_term, notes
                        FROM glossary_terms
                        WHERE lower(source_term) = lower(?)
                          AND target_language = ?
                          AND subject = ?
                        """,
                        (source_term, target_language, subject),
                    ).fetchone()

                    now = _now()
                    if existing is None:
                        conn.execute(
                            """
                            INSERT INTO glossary_terms
                            (source_term, target_language, translated_term, subject, notes, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                source_term,
                                target_language,
                                translated_term,
                                subject,
                                notes,
                                now,
                                now,
                            ),
                        )
                        added += 1
                    elif (
                        existing["translated_term"] == translated_term
                        and existing["notes"] == notes
                    ):
                        skipped += 1
                    else:
                        conn.execute(
                            """
                            UPDATE glossary_terms
                            SET translated_term = ?, notes = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (translated_term, notes, now, existing["id"]),
                        )
                        updated += 1

            conn.commit()

        return {
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to import glossary CSV")
        raise HTTPException(status_code=500, detail="Could not import glossary CSV.")


@router.put("/{item_id}")
async def update_glossary(item_id: int, item: GlossaryUpdate):
    data = item.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="Provide at least one field to update.")

    fields = []
    values = []
    allowed = {
        "source_term",
        "target_language",
        "translated_term",
        "subject",
        "notes",
    }

    for field in allowed:
        if field in data:
            fields.append(f"{field} = ?")
            values.append(data[field])

    values.append(_now())
    values.append(item_id)

    try:
        with get_connection() as conn:
            if _get_item(conn, item_id) is None:
                raise HTTPException(status_code=404, detail="Glossary term not found.")

            conn.execute(
                f"""
                UPDATE glossary_terms
                SET {", ".join(fields)}, updated_at = ?
                WHERE id = ?
                """,
                values,
            )
            updated = _get_item(conn, item_id)
            conn.commit()
        return dict(updated)
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="A glossary term with the same source term, language, and subject already exists.",
        )
    except Exception:
        logger.exception("Failed to update glossary term %s", item_id)
        raise HTTPException(status_code=500, detail="Could not update glossary term.")


@router.delete("/{item_id}")
async def delete_glossary(item_id: int):
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM glossary_terms WHERE id = ?",
                (item_id,),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Glossary term not found.")
            conn.commit()
        return {"deleted": True, "id": item_id}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete glossary term %s", item_id)
        raise HTTPException(status_code=500, detail="Could not delete glossary term.")


@router.post("/import")
async def import_glossary(file: UploadFile = File(...)):
    try:
        data = await file.read(MAX_IMPORT_BYTES + 1)
        if len(data) > MAX_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="CSV file is too large. Maximum size is 5 MB.")
        if not data:
            raise HTTPException(status_code=400, detail="The uploaded CSV is empty.")

        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail="CSV must be UTF-8 encoded. Excel UTF-8 BOM exports are supported.",
            ) from exc

        reader = csv.DictReader(io.StringIO(text))
        headers = {header.strip() for header in (reader.fieldnames or []) if header}
        missing_headers = REQUIRED_CSV_COLUMNS - headers
        if missing_headers:
            raise HTTPException(
                status_code=400,
                detail="CSV is missing required columns: " + ", ".join(sorted(missing_headers)),
            )

        added = updated = skipped = 0
        errors = []
        seen_keys = set()

        with get_connection() as conn:
            for row_number, row in enumerate(reader, start=2):
                try:
                    source_term = _clean_optional(row.get("source_term"))
                    target_language = _clean_optional(row.get("target_language"))
                    translated_term = _clean_optional(row.get("translated_term"))
                    subject = _clean_optional(row.get("subject"))
                    notes = _clean_optional(row.get("notes"))

                    reasons = []
                    if not source_term or len(source_term) > 200:
                        reasons.append("source_term must be 1-200 characters")
                    if target_language not in ALLOWED_LANGUAGES:
                        reasons.append("unsupported target_language")
                    if not translated_term or len(translated_term) > 200:
                        reasons.append("translated_term must be 1-200 characters")
                    if len(subject) > 100:
                        reasons.append("subject must be at most 100 characters")
                    if len(notes) > 500:
                        reasons.append("notes must be at most 500 characters")

                    if reasons:
                        skipped += 1
                        errors.append({"row": row_number, "reasons": reasons})
                        continue

                    key = (source_term.casefold(), target_language, subject)
                    if key in seen_keys:
                        skipped += 1
                        errors.append({"row": row_number, "reasons": ["duplicate row in CSV"]})
                        continue
                    seen_keys.add(key)

                    existing = conn.execute(
                        """
                        SELECT id, translated_term, notes
                        FROM glossary_terms
                        WHERE lower(source_term) = lower(?)
                          AND target_language = ?
                          AND subject = ?
                        """,
                        (source_term, target_language, subject),
                    ).fetchone()

                    now = _now()
                    if existing is None:
                        conn.execute(
                            """
                            INSERT INTO glossary_terms
                            (source_term, target_language, translated_term, subject, notes, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                source_term,
                                target_language,
                                translated_term,
                                subject,
                                notes,
                                now,
                                now,
                            ),
                        )
                        added += 1
                    elif (
                        existing["translated_term"] == translated_term
                        and existing["notes"] == notes
                    ):
                        skipped += 1
                    else:
                        conn.execute(
                            """
                            UPDATE glossary_terms
                            SET translated_term = ?, notes = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (translated_term, notes, now, existing["id"]),
                        )
                        updated += 1

            conn.commit()

        return {
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to import glossary CSV")
        raise HTTPException(status_code=500, detail="Could not import glossary CSV.")



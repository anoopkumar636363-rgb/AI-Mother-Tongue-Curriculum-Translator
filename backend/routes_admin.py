import asyncio
import csv
import io
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.db import get_connection, table_exists

router = APIRouter(prefix="/api/admin", tags=["admin"])

SOURCE_TYPES = {"text", "pdf", "pdf-layout", "image"}
LANGUAGES = {
    "Kannada",
    "Hindi",
    "Telugu",
    "Tamil",
    "Marathi",
    "Malayalam",
    "Bengali",
    "Gujarati",
    "Punjabi",
    "English",
}
FAILURE_DELAY_SECONDS = 0.6
MAX_FILTER_LENGTH = 100


async def require_admin(x_admin_password: str | None = Header(default=None)):
    configured = os.getenv("ADMIN_PASSWORD", "").strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Admin dashboard is not configured. Set ADMIN_PASSWORD in .env.",
        )

    supplied = x_admin_password or ""
    if not secrets.compare_digest(supplied, configured):
        await asyncio.sleep(FAILURE_DELAY_SECONDS)
        raise HTTPException(status_code=401, detail="Incorrect admin password.")

    return True


@router.post("/login")
async def admin_login(x_admin_password: str | None = Header(default=None)):
    configured = os.getenv("ADMIN_PASSWORD", "").strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Admin dashboard is not configured. Set ADMIN_PASSWORD in .env.",
        )

    if not secrets.compare_digest(x_admin_password or "", configured):
        await asyncio.sleep(FAILURE_DELAY_SECONDS)
        raise HTTPException(status_code=401, detail="Incorrect admin password.")

    return {"authenticated": True}


def _date_range(days: int):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _group_counts(conn, column: str, start: str):
    # column is always selected from this module's fixed internal column names.
    rows = conn.execute(
        f"""
        SELECT COALESCE(NULLIF(TRIM({column}), ''), 'Unspecified') AS label,
               COUNT(*) AS count
        FROM translation_events
        WHERE created_at >= ?
        GROUP BY label
        ORDER BY count DESC, label ASC
        """,
        (start,),
    ).fetchall()
    return [{"label": row["label"], "count": row["count"]} for row in rows]


def _daily_series(conn, start: str, end: str):
    rows = conn.execute(
        """
        SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count
        FROM translation_events
        WHERE created_at >= ? AND created_at <= ?
        GROUP BY day
        ORDER BY day ASC
        """,
        (start, end),
    ).fetchall()
    counts = {row["day"]: row["count"] for row in rows}

    start_date = datetime.fromisoformat(start).date()
    end_date = datetime.fromisoformat(end).date()
    series = []
    current = start_date
    while current <= end_date:
        day = current.isoformat()
        series.append({"date": day, "count": counts.get(day, 0)})
        current += timedelta(days=1)
    return series


def _validate_filter(value: str, field_name: str):
    if len(value) > MAX_FILTER_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} filter is too long.",
        )


@router.get("/stats")
async def admin_stats(
    days: int = Query(30, ge=1, le=365),
    _: bool = Depends(require_admin),
):
    start, end = _date_range(days)

    with get_connection() as conn:
        summary = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(success), 0) AS successes,
                   COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END), 0) AS failures,
                   COALESCE(SUM(characters), 0) AS characters,
                   COALESCE(AVG(duration_ms), 0) AS avg_duration
            FROM translation_events
            WHERE created_at >= ? AND created_at <= ?
            """,
            (start, end),
        ).fetchone()

        recent = conn.execute(
            """
            SELECT id, created_at, source_type, target_language, subject, grade,
                   characters, model, duration_ms, success, error_message
            FROM translation_events
            ORDER BY id DESC
            LIMIT 20
            """
        ).fetchall()

        library_counts = {}
        for table, key in (
            ("translations", "translations"),
            ("glossary_terms", "glossary_terms"),
        ):
            if table_exists(conn, table):
                library_counts[key] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]

        glossary_by_language = []
        if table_exists(conn, "glossary_terms"):
            glossary_by_language = [
                {"label": row["label"], "count": row["count"]}
                for row in conn.execute(
                    """
                    SELECT COALESCE(NULLIF(TRIM(target_language), ''), 'Unspecified') AS label,
                           COUNT(*) AS count
                    FROM glossary_terms
                    GROUP BY label
                    ORDER BY count DESC, label ASC
                    """
                ).fetchall()
            ]

        total = summary["total"]
        successes = summary["successes"]

        return {
            "days": days,
            "total_translations": total,
            "successes": successes,
            "failures": summary["failures"],
            "success_rate": round((successes / total * 100), 2) if total else 0,
            "total_characters": summary["characters"],
            "average_duration_ms": round(summary["avg_duration"], 2),
            "by_target_language": _group_counts(conn, "target_language", start),
            "by_source_type": _group_counts(conn, "source_type", start),
            "by_subject": _group_counts(conn, "subject", start),
            "by_grade": _group_counts(conn, "grade", start),
            "by_model": _group_counts(conn, "model", start),
            "daily": _daily_series(conn, start, end),
            "recent_events": [dict(row) for row in recent],
            "glossary_by_language": glossary_by_language,
            **library_counts,
        }


@router.get("/events")
async def admin_events(
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(25, ge=1, le=100),
    language: str = Query(""),
    source_type: str = Query(""),
    success: str = Query(""),
    _: bool = Depends(require_admin),
):
    _validate_filter(language, "Language")
    _validate_filter(source_type, "Source type")
    _validate_filter(success, "Success")

    if language and language not in LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported language filter.")
    if source_type and source_type not in SOURCE_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported source type filter.")
    if success not in {"", "0", "1"}:
        raise HTTPException(status_code=400, detail="Success filter must be 0, 1, or empty.")

    clauses = []
    params = []

    if language:
        clauses.append("target_language = ?")
        params.append(language)
    if source_type:
        clauses.append("source_type = ?")
        params.append(source_type)
    if success:
        clauses.append("success = ?")
        params.append(int(success))

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    offset = (page - 1) * page_size

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM translation_events{where}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT id, created_at, source_type, target_language, subject, grade,
                   characters, model, duration_ms, success, error_message
            FROM translation_events
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
        "events": [dict(row) for row in rows],
    }


@router.get("/export/events.csv")
async def export_events(_: bool = Depends(require_admin)):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, source_type, target_language, subject, grade,
                   characters, model, duration_ms, success, error_message
            FROM translation_events
            ORDER BY id DESC
            """
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "created_at",
            "source_type",
            "target_language",
            "subject",
            "grade",
            "characters",
            "model",
            "duration_ms",
            "success",
            "error_message",
        ]
    )

    for row in rows:
        writer.writerow([row[key] for key in row.keys()])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="translation-events.csv"'
        },
    )

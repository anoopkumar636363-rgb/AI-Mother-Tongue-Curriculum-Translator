import contextvars
import csv
import io
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
logger = logging.getLogger("curriculum-translator")

_EVENT_CONTEXT = contextvars.ContextVar("translation_event_context", default={})


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS translation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                source_type TEXT NOT NULL CHECK(source_type IN ('text','pdf','pdf-layout','image')),
                target_language TEXT NOT NULL,
                subject TEXT,
                grade TEXT,
                characters INTEGER NOT NULL DEFAULT 0,
                model TEXT,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                success INTEGER NOT NULL CHECK(success IN (0,1)),
                error_message TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_translation_events_created_at "
            "ON translation_events(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_translation_events_language "
            "ON translation_events(target_language)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS translations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                subject TEXT,
                grade TEXT,
                target_language TEXT NOT NULL,
                source_type TEXT NOT NULL CHECK(source_type IN ('text','pdf','image')),
                original_text TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_translations_target_language "
            "ON translations(target_language)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_translations_subject "
            "ON translations(subject)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_translations_grade "
            "ON translations(grade)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_translations_created_at "
            "ON translations(created_at)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS glossary_terms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_term TEXT NOT NULL,
                target_language TEXT NOT NULL,
                translated_term TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # SQLite does not allow expressions such as lower(source_term)
        # inside a table-level UNIQUE constraint, so this unique index
        # provides the requested case-insensitive uniqueness guarantee.
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_glossary_terms_source_language_subject
            ON glossary_terms(lower(source_term), target_language, subject)
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_glossary_terms_target_language "
            "ON glossary_terms(target_language)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_glossary_terms_subject "
            "ON glossary_terms(subject)"
        )
        conn.commit()


def set_event_context(**values):
    current = dict(_EVENT_CONTEXT.get())
    current.update(values)
    _EVENT_CONTEXT.set(current)


def get_event_context():
    return dict(_EVENT_CONTEXT.get())


def record_event(
    *,
    source_type,
    created_at,
    target_language,
    subject,
    grade,
    characters,
    model,
    duration_ms,
    success,
    error_message,
):
    try:
        created_at = created_at or datetime.now(timezone.utc).isoformat()
        error_message = str(error_message)[:300] if error_message else None
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO translation_events
                (created_at, source_type, target_language, subject, grade,
                 characters, model, duration_ms, success, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    source_type,
                    target_language or "",
                    subject,
                    grade,
                    max(0, int(characters or 0)),
                    model,
                    max(0, int(duration_ms or 0)),
                    1 if success else 0,
                    error_message,
                ),
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to write translation usage event")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn, table_name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None

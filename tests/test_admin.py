import os
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend import main


@pytest.fixture
def client():
    return TestClient(main.app)


def test_admin_login_right_wrong_and_missing_password(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "correct-password")

    response = client.post(
        "/api/admin/login",
        headers={"X-Admin-Password": "correct-password"},
    )
    assert response.status_code == 200
    assert response.json() == {"authenticated": True}

    response = client.post(
        "/api/admin/login",
        headers={"X-Admin-Password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect admin password."

    response = client.post("/api/admin/login")
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect admin password."


def test_admin_stats_aggregates_sample_events(client, monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "stats-password")
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE translation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                source_type TEXT NOT NULL,
                target_language TEXT NOT NULL,
                subject TEXT,
                grade TEXT,
                characters INTEGER NOT NULL DEFAULT 0,
                model TEXT,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                success INTEGER NOT NULL,
                error_message TEXT
            )
            """
        )
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (now, "text", "Kannada", "Science", "10", 100, "model-a", 100, 1, None),
            (now, "text", "Kannada", "Science", "10", 200, "model-a", 200, 1, None),
            (now, "image", "Hindi", "Math", "9", 50, "model-b", 50, 0, "OCR failed"),
        ]
        conn.executemany(
            """
            INSERT INTO translation_events
            (created_at, source_type, target_language, subject, grade,
             characters, model, duration_ms, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.execute(
            """
            CREATE TABLE translations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                subject TEXT,
                grade TEXT,
                target_language TEXT NOT NULL,
                source_type TEXT NOT NULL,
                original_text TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO translations
            (title, subject, grade, target_language, source_type,
             original_text, translated_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Saved lesson", "Science", "10", "Kannada", "text",
                "Original", "Translated", now, now,
            ),
        )
        conn.commit()

    response = client.get(
        "/api/admin/stats?days=7",
        headers={"X-Admin-Password": "stats-password"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_translations"] == 3
    assert data["successes"] == 2
    assert data["failures"] == 1
    assert data["success_rate"] == 66.67
    assert data["total_characters"] == 350
    assert data["average_duration_ms"] == pytest.approx(116.67, abs=0.01)
    assert {"label": "Kannada", "count": 2} in data["by_target_language"]
    assert {"label": "text", "count": 2} in data["by_source_type"]
    assert {"label": "Science", "count": 2} in data["by_subject"]
    assert {"label": "10", "count": 2} in data["by_grade"]
    assert {"label": "model-a", "count": 2} in data["by_model"]
    assert len(data["daily"]) == 7
    assert len(data["recent_events"]) == 3
    assert data["translations"] == 1


def test_logging_failure_does_not_break_translate(client, monkeypatch):
    monkeypatch.setattr(main, "MODEL_LIST", ["test-model"])

    async def fake_generate_content(**kwargs):
        return SimpleNamespace(text="Translated curriculum")

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=fake_generate_content)
        )
    )
    monkeypatch.setattr(main, "get_translation_client", lambda: fake_client)

    def failing_record_event(**kwargs):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(main, "record_event", failing_record_event)

    response = client.post(
        "/api/translate",
        data={
            "text": "Photosynthesis is a process.",
            "target_language": "Kannada",
            "subject": "Science",
            "grade": "10",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "text": "Translated curriculum",
        "model": "test-model",
    }

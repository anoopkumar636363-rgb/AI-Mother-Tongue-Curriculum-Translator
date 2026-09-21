import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
    db.init_db()
    return TestClient(main.app)


def payload(index=1, language="Kannada"):
    return {
        "title": f"Science Lesson {index}",
        "subject": "Science",
        "grade": "10",
        "target_language": language,
        "source_type": "text",
        "original_text": f"Original curriculum {index}",
        "translated_text": f"Translated curriculum {index}",
    }


def test_create_read_update_delete(client):
    response = client.post("/api/library", json=payload())
    assert response.status_code == 200
    created = response.json()
    assert created["id"] > 0
    assert created["title"] == "Science Lesson 1"

    response = client.get(f"/api/library/{created['id']}")
    assert response.status_code == 200
    assert response.json()["translated_text"] == "Translated curriculum 1"

    response = client.put(
        f"/api/library/{created['id']}",
        json={"title": "Updated Lesson", "translated_text": "Updated translation"},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["title"] == "Updated Lesson"
    assert updated["translated_text"] == "Updated translation"
    assert updated["updated_at"] >= updated["created_at"]

    response = client.delete(f"/api/library/{created['id']}")
    assert response.status_code == 200
    assert response.json() == {"deleted": True, "id": created["id"]}

    assert client.get(f"/api/library/{created['id']}").status_code == 404


def test_search_and_filters(client):
    client.post("/api/library", json=payload(1, "Kannada"))
    client.post(
        "/api/library",
        json={
            **payload(2, "Hindi"),
            "subject": "Math",
            "grade": "9",
            "translated_text": "Algebra and equations",
        },
    )

    response = client.get("/api/library?q=Algebra")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["title"] == "Science Lesson 2"

    response = client.get("/api/library?language=Hindi&subject=Math&grade=9")
    assert response.status_code == 200
    assert response.json()["total"] == 1

    response = client.get("/api/library/filters")
    assert response.status_code == 200
    filters = response.json()
    assert "Kannada" in filters["languages"]
    assert "Hindi" in filters["languages"]
    assert "Science" in filters["subjects"]
    assert "Math" in filters["subjects"]
    assert "9" in filters["grades"]
    assert "10" in filters["grades"]


def test_pagination(client):
    for index in range(1, 6):
        assert client.post("/api/library", json=payload(index)).status_code == 200

    response = client.get("/api/library?page=2&page_size=2")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert data["page"] == 2
    assert data["page_size"] == 2
    assert data["total_pages"] == 3
    assert len(data["items"]) == 2
    assert "original_text" not in data["items"][0]
    assert "translated_text" not in data["items"][0]
    assert len(data["items"][0]["preview"]) <= 150


def test_validation_errors(client):
    bad_language = payload()
    bad_language["target_language"] = "Klingon"
    assert client.post("/api/library", json=bad_language).status_code == 422

    empty_title = payload()
    empty_title["title"] = "   "
    assert client.post("/api/library", json=empty_title).status_code == 422

    oversized = payload()
    oversized["original_text"] = "x" * 200_001
    assert client.post("/api/library", json=oversized).status_code == 422

    too_large_page = client.get("/api/library?page_size=51")
    assert too_large_page.status_code == 422

    bad_source = payload()
    bad_source["source_type"] = "audio"
    assert client.post("/api/library", json=bad_source).status_code == 422


def test_404s(client):
    assert client.get("/api/library/999999").status_code == 404
    assert client.put("/api/library/999999", json={"title": "Missing"}).status_code == 404
    assert client.delete("/api/library/999999").status_code == 404


def test_database_has_library_indexes(client):
    with sqlite3.connect(db.DB_PATH) as conn:
        names = {
            row[1]
            for row in conn.execute("PRAGMA index_list(translations)").fetchall()
        }
    assert "idx_translations_target_language" in names
    assert "idx_translations_subject" in names
    assert "idx_translations_grade" in names
    assert "idx_translations_created_at" in names

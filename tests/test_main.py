import pytest
from fastapi import HTTPException

from backend.main import (
    LAYOUT_BATCH_CHARS,
    split_layout_batches,
    validate_target_language,
    validate_translated_batch,
)


def test_validate_translated_batch_preserves_ids_and_rejects_empty_text():
    batch = [
        {"id": "p1b1", "text": "Hello"},
        {"id": "p1b2", "text": "World"},
    ]

    response = '{"blocks":[{"id":"p1b1","text":"ನಮಸ್ಕಾರ"},{"id":"p1b2","text":"ಜಗತ್ತು"}]}'

    assert validate_translated_batch(batch, response) == {
        "p1b1": "ನಮಸ್ಕಾರ",
        "p1b2": "ಜಗತ್ತು",
    }

    with pytest.raises(ValueError, match="empty translated block"):
        validate_translated_batch(
            batch,
            '{"blocks":[{"id":"p1b1","text":"ನಮಸ್ಕಾರ"},{"id":"p1b2","text":" "}]}' ,
        )


def test_validate_translated_batch_rejects_changed_structure():
    batch = [
        {"id": "p1b1", "text": "Hello"},
        {"id": "p1b2", "text": "World"},
    ]

    with pytest.raises(ValueError, match="changed the PDF block structure"):
        validate_translated_batch(
            batch,
            '{"blocks":[{"id":"p1b1","text":"ನಮಸ್ಕಾರ"}]}',
        )


def test_split_layout_batches_keeps_blocks_intact():
    blocks = [
        {"id": "a", "text": "a" * (LAYOUT_BATCH_CHARS - 10)},
        {"id": "b", "text": "b" * 20},
        {"id": "c", "text": "c" * 20},
    ]

    batches = split_layout_batches(blocks)

    assert [[item["id"] for item in batch] for batch in batches] == [
        ["a"],
        ["b", "c"],
    ]


@pytest.mark.parametrize(
    "language",
    [
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
    ],
)
def test_language_validation_accepts_supported_languages(language):
    assert validate_target_language(language) == language


def test_language_validation_rejects_unknown_language():
    with pytest.raises(HTTPException) as exc_info:
        validate_target_language("Klingon")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Unsupported target language."

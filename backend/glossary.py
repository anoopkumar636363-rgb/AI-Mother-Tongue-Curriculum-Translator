import re

from backend.db import get_connection


def _is_latin_script(term: str) -> bool:
    """Treat terms containing only Latin-script characters/punctuation as Latin."""
    letters = [char for char in term if char.isalpha()]
    return bool(letters) and all(("A" <= char <= "Z") or ("a" <= char <= "z") for char in letters)


def term_matches(text: str, term: str) -> bool:
    if _is_latin_script(term):
        return re.search(r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])", text, re.IGNORECASE) is not None
    return term.casefold() in text.casefold()


def get_relevant_terms(text: str, target_language: str, subject: str, limit: int = 60):
    """Return glossary entries that occur in text, with subject-specific entries preferred."""
    if not text or not target_language or limit <= 0:
        return []

    subject = (subject or "").strip()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, source_term, target_language, translated_term, subject,
                   notes, created_at, updated_at
            FROM glossary_terms
            WHERE target_language = ?
              AND (subject = ? OR subject = '')
            """,
            (target_language, subject),
        ).fetchall()

    # If both a subject-specific and global entry exist for the same source term,
    # the subject-specific entry wins.
    selected = {}
    for row in rows:
        item = dict(row)
        key = item["source_term"].casefold()
        is_specific = bool(item["subject"])
        previous = selected.get(key)
        if previous is None or (is_specific and not previous["subject"]):
            selected[key] = item

    matches = [item for item in selected.values() if term_matches(text, item["source_term"])]
    matches.sort(
        key=lambda item: (
            -len(item["source_term"]),
            0 if item["subject"] else 1,
            item["source_term"].casefold(),
        )
    )
    return matches[:limit]


def build_glossary_prompt_block(terms):
    """Turn glossary entries into a mandatory prompt block."""
    if not terms:
        return ""

    lines = [
        "GLOSSARY (mandatory): translate these terms EXACTLY as given and do not paraphrase them:"
    ]
    lines.extend(
        f"- {item['source_term']} -> {item['translated_term']}"
        for item in terms
    )
    return "\n".join(lines)


def check_glossary_missing(translated_text: str, terms):
    """Return source terms whose required translated term is absent from the output."""
    if not terms:
        return []

    output = translated_text or ""
    return [
        item["source_term"]
        for item in terms
        if item["translated_term"] not in output
    ]

from backend.db import get_connection


def get_relevant_terms(text, target_language, subject):
    if not text or not target_language:
        return []

    subject = (subject or "").strip()

    with get_connection() as conn:
        if subject:
            rows = conn.execute(
                """
                SELECT id, source_term, target_language, translated_term, subject, created_at
                FROM glossary_terms
                WHERE target_language = ?
                  AND (subject = '' OR lower(subject) = lower(?))
                ORDER BY id DESC
                """,
                (target_language, subject),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, source_term, target_language, translated_term, subject, created_at
                FROM glossary_terms
                WHERE target_language = ?
                ORDER BY id DESC
                """,
                (target_language,),
            ).fetchall()

    text_folded = text.casefold()
    return [
        dict(row)
        for row in rows
        if row["source_term"].casefold() in text_folded
    ]

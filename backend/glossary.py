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

def build_glossary_suggestion_prompt(text, target_language, subject):
    subject_context = (
        f"\nSubject: {subject.strip()}"
        if subject and subject.strip()
        else ""
    )
    return f"""
You are building a controlled terminology glossary for an educational curriculum translation system.

Read the curriculum text below.

Identify 5-20 key subject-specific, technical, scientific, or important proper-noun terms that should be translated consistently.
Do NOT choose common everyday words, generic verbs, generic adjectives, or ordinary conversational vocabulary.
Prefer terms that are likely to recur in educational material and whose translation benefits from consistency.

For every selected term:
- "source_term" must be the term as it appears in the curriculum when practical.
- "translated_term" must be a concise translation into {target_language}.
- Keep the translated term to one word or a short phrase.
- Preserve proper nouns when they should remain proper nouns in the target language.

Return ONLY a JSON array in exactly this shape:
[{{"source_term":"...","translated_term":"..."}}]

No commentary.
No Markdown.
No code fences.
No extra keys.
Valid JSON only.
{subject_context}

CURRICULUM:
{text}
""".strip()

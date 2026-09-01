from __future__ import annotations

from ..schemas.document_kb import ScopedFact

EMBEDDING_TEXT_VERSION = "1"


def build_embedding_text(fact: ScopedFact) -> str:
    """Project authoritative Fact fields into canonical embedding text version 1."""

    scope = fact.scope_type.strip()
    if fact.scope_targets:
        targets = " / ".join(target.strip() for target in fact.scope_targets)
        scope += f" | targets: {targets}"
    if fact.parent_college is not None:
        scope += f" | parent_college: {fact.parent_college.strip()}"

    section_path = (
        " > ".join(element.strip() for element in fact.section_path)
        if fact.section_path
        else "(none)"
    )
    title = fact.title.strip() or "(none)"
    return "\n".join(
        (
            f"fact_type: {fact.fact_type.strip()}",
            f"scope: {scope}",
            f"section_path: {section_path}",
            f"title: {title}",
            "text:",
            fact.text,
        )
    )

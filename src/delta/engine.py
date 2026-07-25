"""Delta engine: turns aligned element pairs into a structured, typed,
located, confidence-scored delta. Deliberately deterministic - no LLM in
this path - so the structural output is reproducible run-to-run (the LLM's
non-determinism is isolated to the chat/answer layer only; see README).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from src.canonical.model import BBox, CanonicalDocument
from src.delta.align import MatchedPair, align

UNCHANGED_TEXT_THRESHOLD = 0.995  # identical (modulo whitespace) => not a change


@dataclass
class DeltaItem:
    id: str
    change_type: str          # added | removed | modified
    category: str             # text | note | tag | dimension | table_cell | geometry
    page: int
    bbox: list[float]
    before: str | None
    after: str | None
    description: str
    confidence: float
    extra: dict = field(default_factory=dict)


def _describe(change_type: str, category: str, before: str | None, after: str | None) -> str:
    if change_type == "added":
        return f"Added {category}: \"{after}\""
    if change_type == "removed":
        return f"Removed {category}: \"{before}\""
    return f"Modified {category}: \"{before}\" -> \"{after}\""


def build_delta(doc_a: CanonicalDocument, doc_b: CanonicalDocument) -> list[DeltaItem]:
    pairs = align(doc_a, doc_b)
    items: list[DeltaItem] = []

    for pair in pairs:
        if pair.el_a is not None and pair.el_b is not None:
            same_text = pair.el_a.text.strip() == pair.el_b.text.strip()
            if same_text:
                continue  # unchanged content, not part of the delta
            confidence = round(pair.score * min(pair.el_a.confidence, pair.el_b.confidence), 3)
            items.append(DeltaItem(
                id=str(uuid.uuid4()),
                change_type="modified",
                category=pair.el_b.element_type,
                page=pair.page_index,
                bbox=pair.el_b.bbox.as_list(),
                before=pair.el_a.text,
                after=pair.el_b.text,
                description=_describe("modified", pair.el_b.element_type, pair.el_a.text, pair.el_b.text),
                confidence=confidence,
                extra={"match_score": round(pair.score, 3)},
            ))
        elif pair.el_a is not None and pair.el_b is None:
            confidence = round(0.9 * pair.el_a.confidence, 3)
            items.append(DeltaItem(
                id=str(uuid.uuid4()),
                change_type="removed",
                category=pair.el_a.element_type,
                page=pair.page_index,
                bbox=pair.el_a.bbox.as_list(),
                before=pair.el_a.text,
                after=None,
                description=_describe("removed", pair.el_a.element_type, pair.el_a.text, None),
                confidence=confidence,
            ))
        elif pair.el_b is not None and pair.el_a is None:
            confidence = round(0.9 * pair.el_b.confidence, 3)
            items.append(DeltaItem(
                id=str(uuid.uuid4()),
                change_type="added",
                category=pair.el_b.element_type,
                page=pair.page_index,
                bbox=pair.el_b.bbox.as_list(),
                before=None,
                after=pair.el_b.text,
                description=_describe("added", pair.el_b.element_type, None, pair.el_b.text),
                confidence=confidence,
            ))

    items.sort(key=lambda i: (i.page, i.bbox[1], i.bbox[0]))
    return items

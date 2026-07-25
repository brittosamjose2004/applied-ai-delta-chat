"""Retrieval over PID A, PID B, and the delta report.

Design choice: BM25 keyword retrieval (rank_bm25) instead of an embedding
index. P&ID text is dense with exact tags/numbers/codes (e.g. "26-PIT-9077")
where lexical match beats semantic similarity, and it avoids needing a
second API key/provider just for embeddings. Documented trade-off in
README: a real deployment would likely combine BM25 with embeddings for
recall on paraphrased questions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from src.canonical.model import CanonicalDocument
from src.delta.engine import DeltaItem

TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

# Generic "what changed?" style questions (the assignment's own example
# query) share almost no vocabulary with delta-report text ("Modified tag:
# ..."), so plain BM25 ranks them low or misses them entirely - verified
# live: "what changed on this sheet?" was retrieving unrelated unchanged
# PID content and the LLM concluded (wrongly) that nothing changed. This
# regex detects that question intent and forces delta-report chunks to the
# front of the ranking, since for this question type they're always the
# right source regardless of lexical overlap with the query.
CHANGE_INTENT_RE = re.compile(
    r"\bwhat\s+(has\s+)?chang|\bany\s+chang|\bdid\s+(anything|it)\s+chang|"
    r"\bdelta\b|\bdiffer\w*|\bmodif\w*|\bsummari[sz]e\b|\bcompar\w*|\bwhat.?s\s+new\b",
    re.IGNORECASE,
)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def has_change_intent(query: str) -> bool:
    return bool(CHANGE_INTENT_RE.search(query))


@dataclass
class Chunk:
    id: str
    source: str       # "pid_a" | "pid_b" | "delta_report"
    pid: str | None
    page: int
    bbox: list[float]
    text: str


class RetrievalIndex:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self._corpus_tokens = [tokenize(c.text) for c in chunks]
        self._bm25 = BM25Okapi(self._corpus_tokens) if chunks else None

    def search(self, query: str, top_k: int = 8) -> list[tuple[Chunk, float]]:
        if not self._bm25:
            return []
        scores = self._bm25.get_scores(tokenize(query))

        if has_change_intent(query):
            # Force every delta-report chunk to outrank PID content, since a
            # "what changed?" question is always answered by the delta
            # report regardless of whether the query's wording happens to
            # overlap with any individual change's description.
            boosted = [
                s + 1000.0 if c.source == "delta_report" else s
                for c, s in zip(self.chunks, scores)
            ]
            ranked = sorted(zip(self.chunks, boosted), key=lambda x: x[1], reverse=True)
            return [(c, float(s)) for c, s in ranked[:top_k]]

        ranked = sorted(zip(self.chunks, scores), key=lambda x: x[1], reverse=True)
        return [(c, float(s)) for c, s in ranked[:top_k] if s > 0]


ROW_Y_TOLERANCE = 3.0   # points; elements within this vertical band are candidates for the same row
ROW_X_GAP_MAX = 60.0    # points; only merge elements this close horizontally - a real
                        # label->value gap measured ~12pt; unrelated same-row content
                        # elsewhere on a wide P&ID sheet resumes at 69pt+ gaps (verified
                        # live against the actual equipment table)


def _row_chunks(source: str, doc: CanonicalDocument) -> list[Chunk]:
    """P&ID equipment tables put a label ("DUTY") and its value ("776 kW")
    in separate columns of the same visual row - two separate TextElements
    with near-identical y but zero vocabulary overlap. A question like
    "what is the duty of the compressor?" matches the label chunk on BM25
    but the value chunk never surfaces (verified live: 'DUTY' scored 13.77,
    the '776 NOTE 28' value chunk didn't appear in top-8 at all). Emitting
    an extra chunk that joins adjacent same-row cells' text lets a query
    match on the label and retrieve the value in the same chunk.

    Grouping by y alone is too coarse on a wide sheet - it pulls in
    unrelated content from elsewhere in the same horizontal band (verified
    live: a naive y-only merge dragged in drip-pan piping codes hundreds of
    points away into the DUTY row). ROW_X_GAP_MAX additionally requires
    elements to be horizontally adjacent, not just vertically aligned.

    Individual-element chunks stay indexed too, so nothing already working
    (specific tag/value lookups) regresses."""
    chunks: list[Chunk] = []
    for page in doc.pages:
        y_buckets: dict[int, list] = {}
        for el in page.elements:
            y_key = round(el.bbox.y0 / ROW_Y_TOLERANCE)
            y_buckets.setdefault(y_key, []).append(el)

        for els in y_buckets.values():
            if len(els) < 2:
                continue
            els_sorted = sorted(els, key=lambda e: e.bbox.x0)
            group = [els_sorted[0]]
            for el in els_sorted[1:]:
                if el.bbox.x0 - group[-1].bbox.x1 <= ROW_X_GAP_MAX:
                    group.append(el)
                else:
                    if len(group) >= 2:
                        chunks.append(_merge_row(source, doc, page.index, group))
                    group = [el]
            if len(group) >= 2:
                chunks.append(_merge_row(source, doc, page.index, group))
    return chunks


def _merge_row(source: str, doc: CanonicalDocument, page_index: int, els: list) -> Chunk:
    row_text = " ".join(e.text for e in els)
    x0 = min(e.bbox.x0 for e in els)
    y0 = min(e.bbox.y0 for e in els)
    x1 = max(e.bbox.x1 for e in els)
    y1 = max(e.bbox.y1 for e in els)
    return Chunk(
        id=f"row-{els[0].id}", source=source, pid=doc.pid, page=page_index,
        bbox=[x0, y0, x1, y1], text=row_text,
    )


def build_index(doc_a: CanonicalDocument, doc_b: CanonicalDocument, delta_items: list[DeltaItem]) -> RetrievalIndex:
    chunks: list[Chunk] = []

    for source, doc in (("pid_a", doc_a), ("pid_b", doc_b)):
        for page, el in doc.all_elements():
            chunks.append(Chunk(
                id=el.id, source=source, pid=doc.pid, page=page.index,
                bbox=el.bbox.as_list(), text=el.text,
            ))
        chunks.extend(_row_chunks(source, doc))

    for item in delta_items:
        chunks.append(Chunk(
            id=item.id, source="delta_report", pid=None, page=item.page,
            bbox=item.bbox, text=item.description,
        ))

    return RetrievalIndex(chunks)

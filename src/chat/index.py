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
# ..."), so plain BM25 ranks them low or misses them entirely — verified
# live: "what changed on this sheet?" was retrieving unrelated unchanged
# PID content and the LLM concluded (wrongly) that nothing changed. This
# regex detects that question intent and forces delta-report chunks to the
# front of the ranking, since for this question type they're always the
# right source regardless of lexical overlap with the query.
CHANGE_INTENT_RE = re.compile(
    r"\bwhat\s+(has\s+)?chang|\bwhat.?s\s+(the\s+)?diff|\bany\s+chang|\bdid\s+(anything|it)\s+chang|"
    r"\bdelta\b|\bdifferen(t|ce)\b|\bmodif(y|ied|ication)",
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


def build_index(doc_a: CanonicalDocument, doc_b: CanonicalDocument, delta_items: list[DeltaItem]) -> RetrievalIndex:
    chunks: list[Chunk] = []

    for source, doc in (("pid_a", doc_a), ("pid_b", doc_b)):
        for page, el in doc.all_elements():
            chunks.append(Chunk(
                id=el.id, source=source, pid=doc.pid, page=page.index,
                bbox=el.bbox.as_list(), text=el.text,
            ))

    for item in delta_items:
        chunks.append(Chunk(
            id=item.id, source="delta_report", pid=None, page=item.page,
            bbox=item.bbox, text=item.description,
        ))

    return RetrievalIndex(chunks)

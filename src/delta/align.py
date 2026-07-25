"""Content alignment between two revisions - the hard part of the delta
engine. Diffing is trivial once you know which element in B corresponds to
which element in A; getting *that* right, when text moves, gets re-tagged,
or shifts position slightly, is the actual problem.

Approach: score every same-page (elA, elB) candidate pair on a blend of text
similarity and spatial proximity, then greedily assign 1:1 matches
highest-score-first (a simple, deterministic stand-in for optimal bipartite
matching - documented trade-off, see README). Unmatched elements on the A
side are removals; unmatched on the B side are additions.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from src.canonical.model import CanonicalDocument, TextElement

TEXT_WEIGHT = 0.7
SPATIAL_WEIGHT = 0.3
CANDIDATE_FLOOR = 0.35  # below this, don't even consider it a candidate match


@dataclass
class MatchedPair:
    page_index: int
    el_a: TextElement | None
    el_b: TextElement | None
    score: float  # 1.0 = identical text+position; lower = weaker match


def text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def spatial_similarity(el_a: TextElement, el_b: TextElement, page_w: float, page_h: float) -> float:
    cxa, cya = el_a.bbox.center()
    cxb, cyb = el_b.bbox.center()
    diag = max((page_w ** 2 + page_h ** 2) ** 0.5, 1.0)
    dist = ((cxa - cxb) ** 2 + (cya - cyb) ** 2) ** 0.5
    return max(0.0, 1.0 - dist / diag)


def align(doc_a: CanonicalDocument, doc_b: CanonicalDocument) -> list[MatchedPair]:
    pairs: list[MatchedPair] = []
    max_pages = max(len(doc_a.pages), len(doc_b.pages))

    for pindex in range(max_pages):
        page_a = doc_a.pages[pindex] if pindex < len(doc_a.pages) else None
        page_b = doc_b.pages[pindex] if pindex < len(doc_b.pages) else None

        if page_a is None:
            for el in (page_b.elements if page_b else []):
                pairs.append(MatchedPair(pindex, None, el, 0.0))
            continue
        if page_b is None:
            for el in page_a.elements:
                pairs.append(MatchedPair(pindex, el, None, 0.0))
            continue

        page_w = max(page_a.width, page_b.width)
        page_h = max(page_a.height, page_b.height)

        candidates: list[tuple[float, TextElement, TextElement]] = []
        for el_a in page_a.elements:
            for el_b in page_b.elements:
                t_sim = text_similarity(el_a.text, el_b.text)
                s_sim = spatial_similarity(el_a, el_b, page_w, page_h)
                score = TEXT_WEIGHT * t_sim + SPATIAL_WEIGHT * s_sim
                if score >= CANDIDATE_FLOOR:
                    candidates.append((score, el_a, el_b))

        candidates.sort(key=lambda c: c[0], reverse=True)

        matched_a: set[str] = set()
        matched_b: set[str] = set()
        for score, el_a, el_b in candidates:
            if el_a.id in matched_a or el_b.id in matched_b:
                continue
            matched_a.add(el_a.id)
            matched_b.add(el_b.id)
            pairs.append(MatchedPair(pindex, el_a, el_b, score))

        for el_a in page_a.elements:
            if el_a.id not in matched_a:
                pairs.append(MatchedPair(pindex, el_a, None, 0.0))
        for el_b in page_b.elements:
            if el_b.id not in matched_b:
                pairs.append(MatchedPair(pindex, None, el_b, 0.0))

    return pairs

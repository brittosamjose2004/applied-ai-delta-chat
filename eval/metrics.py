"""Metrics for the eval harness.

Delta metrics: match predicted DeltaItems against a labeled ground-truth
change list (same change_type + fuzzy text overlap on before/after), then
compute precision/recall/F1 - did we find the real changes without
inventing fake ones.

Chat metrics: correctness (does the answer contain the expected fact) and
groundedness (does the answer only make claims traceable to a cited
source) via LLM-as-judge, validated against a couple of hand-checked
examples (see README for the validation note).

Retrieval metrics: recall@k - independent of the LLM, does BM25 retrieval
surface the chunk containing the fact needed to answer each labeled
question, within the top k results actually sent to the model.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from difflib import SequenceMatcher

MATCH_THRESHOLD = float(os.environ.get("DELTA_MATCH_THRESHOLD", 0.55))


def _text_overlap(a: str | None, b: str | None) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


@dataclass
class DeltaScore:
    precision: float
    recall: float
    f1: float
    true_positives: int
    false_positives: int
    false_negatives: int
    matched_gt_ids: list[int]
    unmatched_predictions: list[dict]
    missed_ground_truth: list[dict]


def score_delta(predicted: list, ground_truth: list[dict]) -> DeltaScore:
    """predicted: list[DeltaItem]; ground_truth: list of the labeled change dicts."""
    matched_gt: set[int] = set()
    matched_pred: set[int] = set()

    for pi, pred in enumerate(predicted):
        best_gi, best_score = None, 0.0
        for gi, gt in enumerate(ground_truth):
            if gi in matched_gt:
                continue
            if gt["type"] != pred.change_type:
                continue
            score = max(
                _text_overlap(pred.before, gt.get("before")),
                _text_overlap(pred.after, gt.get("after")),
            )
            if score > best_score:
                best_gi, best_score = gi, score
        if best_gi is not None and best_score >= MATCH_THRESHOLD:
            matched_gt.add(best_gi)
            matched_pred.add(pi)

    tp = len(matched_pred)
    fp = len(predicted) - tp
    fn = len(ground_truth) - len(matched_gt)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return DeltaScore(
        precision=round(precision, 3),
        recall=round(recall, 3),
        f1=round(f1, 3),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        matched_gt_ids=sorted(matched_gt),
        unmatched_predictions=[
            {"type": p.change_type, "before": p.before, "after": p.after}
            for i, p in enumerate(predicted) if i not in matched_pred
        ],
        missed_ground_truth=[gt for gi, gt in enumerate(ground_truth) if gi not in matched_gt],
    )


JUDGE_PROMPT = """You are grading a chat answer for a Q&A system grounded in engineering \
documents. Given the QUESTION, the EXPECTED FACT it should contain, and the ANSWER produced by \
the system, output strict JSON: {{"correct": true|false, "grounded": true|false, "reason": "..."}}
- correct: does the answer contain/convey the expected fact (paraphrase OK)?
- grounded: does the answer cite sources (e.g. [S1]) for its claims, rather than asserting facts \
with no citation?

QUESTION: {question}
EXPECTED FACT: {expected}
ANSWER: {answer}

Return only the JSON object."""


def judge_chat_answer(llm, question: str, expected: str, answer: str) -> dict:
    """LLM-as-judge. Requires an LlmClient (see src/chat/llm.py). Validated by
    spot-checking judge output against 2 hand-labeled examples - see README."""
    import json
    prompt = JUDGE_PROMPT.format(question=question, expected=expected, answer=answer)
    resp = llm.complete(system="You are a strict, careful grading assistant.", user=prompt, max_tokens=200)
    raw = resp.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"correct": False, "grounded": False, "reason": f"judge returned unparseable output: {raw[:200]}"}


@dataclass
class RetrievalScore:
    recall_at_k: float
    hits: int
    total: int
    misses: list[dict]


def score_retrieval(index, qa_list: list[dict], k: int = 8) -> RetrievalScore:
    """For each QA item with an `expected_source_contains` substring, check
    whether any of the top-k BM25 hits actually contain it. No LLM involved
   - this isolates retrieval quality from generation quality."""
    hits, misses = 0, []
    scored = [qa for qa in qa_list if qa.get("expected_source_contains")]
    for qa in scored:
        needle = qa["expected_source_contains"].lower()
        results = index.search(qa["question"], top_k=k)
        found = any(needle in chunk.text.lower() for chunk, _ in results)
        if found:
            hits += 1
        else:
            misses.append({"question": qa["question"], "expected_source_contains": qa["expected_source_contains"]})
    total = len(scored)
    return RetrievalScore(
        recall_at_k=round(hits / total, 3) if total else 0.0,
        hits=hits, total=total, misses=misses,
    )

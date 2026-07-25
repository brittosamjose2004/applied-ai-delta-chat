"""Runnable eval harness. `python -m eval.run_eval` (or `make eval`).

Prints a scorecard: delta precision/recall/F1 per sample pair, plus chat
correctness/groundedness if ANTHROPIC_API_KEY is set (skipped, visibly and
honestly, if not — no fake numbers).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from eval.metrics import judge_chat_answer, score_delta, score_retrieval
from src.chat.answer import answer_question
from src.chat.index import build_index
from src.chat.llm import default_client
from src.delta.engine import build_delta
from src.ingest.registry import ingest_pid
from src.observability.tracing import Trace

ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = ROOT / "data" / "samples"
DATASETS_DIR = Path(__file__).resolve().parent / "datasets"


def find_sample_pairs():
    for gt_path in sorted(SAMPLES_DIR.glob("*/ground_truth_delta.json")):
        yield gt_path.parent


def run_delta_eval():
    print("=" * 72)
    print("DELTA ENGINE - precision / recall / F1 vs. labeled ground truth")
    print("=" * 72)
    results = []
    for pair_dir in find_sample_pairs():
        gt = json.loads((pair_dir / "ground_truth_delta.json").read_text())
        path_a = pair_dir / gt["pid_a"]
        path_b = pair_dir / gt["pid_b"]
        doc_a = ingest_pid("PID-A", str(path_a))
        doc_b = ingest_pid("PID-B", str(path_b))
        predicted = build_delta(doc_a, doc_b)
        score = score_delta(predicted, gt["changes"])

        print(f"\nPair: {gt['pair_id']}")
        print(f"  ground truth changes: {len(gt['changes'])}  |  predicted changes: {len(predicted)}")
        print(f"  precision={score.precision}  recall={score.recall}  f1={score.f1}")
        print(f"  TP={score.true_positives} FP={score.false_positives} FN={score.false_negatives}")
        if score.missed_ground_truth:
            print("  MISSED (false negatives):")
            for m in score.missed_ground_truth:
                print(f"    - [{m['type']}] {m.get('description')}")
        if score.unmatched_predictions:
            print("  SPURIOUS (false positives):")
            for u in score.unmatched_predictions:
                print(f"    - [{u['type']}] before={u['before']!r} after={u['after']!r}")

        results.append({"pair_id": gt["pair_id"], "precision": score.precision, "recall": score.recall, "f1": score.f1})
    return results


def run_retrieval_eval():
    """LLM-independent: does BM25 retrieval surface the right chunk for each
    labeled question, within the top-k actually sent to the model."""
    print("\n" + "=" * 72)
    print("RETRIEVAL QUALITY - recall@k (BM25, no LLM involved)")
    print("=" * 72)

    results = []
    for qa_path in sorted(DATASETS_DIR.glob("*_qa.json")):
        data = json.loads(qa_path.read_text())
        pair_dir = SAMPLES_DIR / data["pair_id"]
        gt = json.loads((pair_dir / "ground_truth_delta.json").read_text())
        doc_a = ingest_pid("PID-A", str(pair_dir / gt["pid_a"]))
        doc_b = ingest_pid("PID-B", str(pair_dir / gt["pid_b"]))
        items = build_delta(doc_a, doc_b)
        index = build_index(doc_a, doc_b, items)

        score = score_retrieval(index, data["qa"], k=8)
        print(f"\nPair {data['pair_id']}: recall@8={score.recall_at_k} ({score.hits}/{score.total})")
        if score.misses:
            print("  MISSED (expected fact not in top-8 retrieved chunks):")
            for m in score.misses:
                print(f"    - Q: {m['question']!r} expected to find: {m['expected_source_contains']!r}")
        results.append({"pair_id": data["pair_id"], "recall_at_8": score.recall_at_k})
    return results


def run_chat_eval():
    print("\n" + "=" * 72)
    print("GROUNDED CHAT - correctness / groundedness (LLM-as-judge)")
    print("=" * 72)

    any_provider = any(os.environ.get(v) for v in (
        "GEMINI_API_KEY", "VERTEX_PROJECT", "NVIDIA_NIM_API_KEY", "ANTHROPIC_API_KEY",
    ))
    if not any_provider:
        print("\nSKIPPED: no LLM provider configured. Set GEMINI_API_KEY, VERTEX_PROJECT, "
              "NVIDIA_NIM_API_KEY, and/or ANTHROPIC_API_KEY in .env.")
        return None

    llm = default_client()
    results = []
    for qa_path in sorted(DATASETS_DIR.glob("*_qa.json")):
        data = json.loads(qa_path.read_text())
        pair_dir = SAMPLES_DIR / data["pair_id"]
        gt = json.loads((pair_dir / "ground_truth_delta.json").read_text())
        doc_a = ingest_pid("PID-A", str(pair_dir / gt["pid_a"]))
        doc_b = ingest_pid("PID-B", str(pair_dir / gt["pid_b"]))
        items = build_delta(doc_a, doc_b)
        index = build_index(doc_a, doc_b, items)

        correct_count, grounded_count = 0, 0
        for qa in data["qa"]:
            trace = Trace(kind="eval_chat")
            result = answer_question(qa["question"], index, trace, llm=llm)
            verdict = judge_chat_answer(llm, qa["question"], qa["expected"], result["answer"])
            correct_count += int(verdict.get("correct", False))
            grounded_count += int(verdict.get("grounded", False))
            print(f"\nQ: {qa['question']}")
            print(f"  correct={verdict.get('correct')} grounded={verdict.get('grounded')} - {verdict.get('reason', '')[:100]}")

        n = len(data["qa"])
        print(f"\nPair {data['pair_id']}: correctness={correct_count}/{n}  groundedness={grounded_count}/{n}")
        results.append({"pair_id": data["pair_id"], "correctness": correct_count / n, "groundedness": grounded_count / n})
    return results


if __name__ == "__main__":
    load_dotenv()
    delta_results = run_delta_eval()
    retrieval_results = run_retrieval_eval()
    chat_results = run_chat_eval()

    print("\n" + "=" * 72)
    print("SCORECARD SUMMARY")
    print("=" * 72)
    for r in delta_results:
        print(f"  delta[{r['pair_id']}]: P={r['precision']} R={r['recall']} F1={r['f1']}")
    for r in retrieval_results:
        print(f"  retrieval[{r['pair_id']}]: recall@8={r['recall_at_8']}")
    if chat_results:
        for r in chat_results:
            print(f"  chat[{r['pair_id']}]: correctness={r['correctness']:.2f} groundedness={r['groundedness']:.2f}")
    else:
        print("  chat: skipped (no LLM provider configured)")

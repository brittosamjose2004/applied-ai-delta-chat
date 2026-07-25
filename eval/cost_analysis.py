"""Cost/latency budget analysis (bonus). Aggregates every trace file written
under TRACE_DIR (real, observed runs — not estimates) into per-stage latency
percentiles and a cost projection, so "is this affordable/fast enough at
scale" has a real number behind it instead of a guess.

Run: python -m eval.cost_analysis  (or `make cost-report`)
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

TRACE_DIR = Path(os.environ.get("TRACE_DIR", "./traces"))


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(int(round(pct / 100 * (len(s) - 1))), len(s) - 1)
    return s[idx]


def load_traces() -> list[dict]:
    if not TRACE_DIR.exists():
        return []
    traces = []
    for path in sorted(TRACE_DIR.glob("*.json")):
        try:
            traces.append(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return traces


def analyze(traces: list[dict]) -> dict:
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for t in traces:
        by_kind[t["kind"]].append(t)

    stage_durations: dict[str, list[float]] = defaultdict(list)
    total_cost = 0.0
    total_llm_calls = 0
    failed = 0

    for t in traces:
        total_cost += t.get("total_cost_usd", 0.0)
        if t.get("failed"):
            failed += 1
        for span in t.get("spans", []):
            if span["duration_ms"] is not None:
                stage_durations[span["name"]].append(span["duration_ms"])
            if span["name"] == "llm_call":
                total_llm_calls += 1

    stage_stats = {
        name: {
            "count": len(durs),
            "p50_ms": round(_percentile(durs, 50), 1),
            "p95_ms": round(_percentile(durs, 95), 1),
            "max_ms": round(max(durs), 1),
        }
        for name, durs in stage_durations.items()
    }

    avg_cost_per_llm_call = round(total_cost / total_llm_calls, 6) if total_llm_calls else 0.0

    return {
        "total_traces": len(traces),
        "by_kind": {k: len(v) for k, v in by_kind.items()},
        "failed_traces": failed,
        "total_cost_usd_observed": round(total_cost, 6),
        "total_llm_calls": total_llm_calls,
        "avg_cost_per_llm_call_usd": avg_cost_per_llm_call,
        "stage_latency_ms": stage_stats,
        # Projections: purely `observed avg * N` — a first-order estimate, not a
        # load-tested capacity number. Flagged as such in the printed report.
        "projected_cost_per_1000_llm_calls_usd": round(avg_cost_per_llm_call * 1000, 3),
    }


def print_report(analysis: dict):
    print("=" * 72)
    print("COST / LATENCY BUDGET ANALYSIS (from observed traces/*.json)")
    print("=" * 72)
    if analysis["total_traces"] == 0:
        print("\nNo traces found yet. Run `make run`, `make chat`, or `make eval` first, "
              "then re-run this report.")
        return

    print(f"\nTraces analyzed: {analysis['total_traces']} {analysis['by_kind']}")
    print(f"Failed traces: {analysis['failed_traces']}")
    print(f"\nPer-stage latency (ms):")
    for name, s in sorted(analysis["stage_latency_ms"].items()):
        print(f"  {name:<12} n={s['count']:<4} p50={s['p50_ms']:<9} p95={s['p95_ms']:<9} max={s['max_ms']}")

    print(f"\nLLM calls observed: {analysis['total_llm_calls']}")
    print(f"Total cost observed: ${analysis['total_cost_usd_observed']}")
    print(f"Avg cost / LLM call: ${analysis['avg_cost_per_llm_call_usd']}")
    print(f"Naive projection - cost per 1,000 LLM calls: "
          f"${analysis['projected_cost_per_1000_llm_calls_usd']} "
          f"(first-order estimate: avg observed cost x 1000, not load-tested)")


if __name__ == "__main__":
    print_report(analyze(load_traces()))

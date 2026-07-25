"""Lightweight homegrown tracer (documented choice in README: no external
dependency needed to satisfy the requirement — every request writes a
self-contained JSON trace file with per-stage timing and LLM telemetry).

Usage:
    trace = Trace(request_id, kind="delta")
    with trace.span("ingest"):
        ...
    with trace.span("llm_call") as span:
        span.set(model=..., input_tokens=..., output_tokens=..., cost_usd=...)
    trace.write()
"""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TRACE_DIR = Path(os.environ.get("TRACE_DIR", "./traces"))

# Rough per-1M-token pricing used for cost estimates only (approximate; keep configurable).
MODEL_PRICING_PER_1M = {
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 0.8, "output": 4.0},
    "gemini-2.5-flash-lite": {"input": 0.1, "output": 0.4},
    "meta/llama-3.1-8b-instruct": {"input": 0.2, "output": 0.2},
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING_PER_1M.get(model)
    if not pricing:
        return 0.0
    return round(input_tokens / 1_000_000 * pricing["input"] + output_tokens / 1_000_000 * pricing["output"], 6)


@dataclass
class Span:
    name: str
    start_ts: float
    end_ts: float | None = None
    data: dict = field(default_factory=dict)
    error: str | None = None

    def set(self, **kwargs):
        self.data.update(kwargs)

    @property
    def duration_ms(self) -> float | None:
        if self.end_ts is None:
            return None
        return round((self.end_ts - self.start_ts) * 1000, 2)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "duration_ms": self.duration_ms,
            "data": self.data,
            "error": self.error,
        }


class Trace:
    def __init__(self, kind: str, request_id: str | None = None):
        self.request_id = request_id or str(uuid.uuid4())
        self.kind = kind
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.spans: list[Span] = []

    @contextmanager
    def span(self, name: str):
        s = Span(name=name, start_ts=time.perf_counter())
        self.spans.append(s)
        try:
            yield s
        except Exception as e:
            s.error = f"{type(e).__name__}: {e}"
            raise
        finally:
            s.end_ts = time.perf_counter()

    def total_cost_usd(self) -> float:
        return round(sum(s.data.get("cost_usd", 0.0) for s in self.spans), 6)

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "kind": self.kind,
            "started_at": self.started_at,
            "total_duration_ms": round(sum(s.duration_ms or 0 for s in self.spans), 2),
            "total_cost_usd": self.total_cost_usd(),
            "spans": [s.to_dict() for s in self.spans],
            "failed": any(s.error for s in self.spans),
        }

    def write(self) -> Path:
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        path = TRACE_DIR / f"{self.kind}_{self.request_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

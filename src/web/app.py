"""Minimal served UI (bonus item) — a thin HTTP layer over the same
pipeline functions the CLI calls (run_delta_pipeline / answer_question).
No new business logic lives here; it's a rendering layer only.

Run: uvicorn src.web.app:app --reload --port 8000
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.chat.answer import answer_question
from src.chat.index import RetrievalIndex, build_index
from src.delta.engine import DeltaItem, build_delta
from src.delta.report import to_json
from src.ingest.registry import ingest_pid
from src.observability.tracing import Trace

load_dotenv()

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="delta-chat")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory session cache: rebuilding the index per chat message would be
# wasteful, so we keep the last ingested pair + index around. Fine for a
# single-user demo; a multi-user deployment would key this by session id.
_state: dict = {"pid_a": None, "pid_b": None, "index": None, "items": None}


class LoadRequest(BaseModel):
    pid_a: str = "PID-A"
    path_a: str = "data/samples/pair_01_lift_gas_compressor/rev_A_native.pdf"
    pid_b: str = "PID-B"
    path_b: str = "data/samples/pair_01_lift_gas_compressor/rev_B_native.pdf"


class ChatRequest(BaseModel):
    question: str


@app.get("/")
def index_page():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.post("/api/delta")
def api_delta(req: LoadRequest):
    """Ingest both PIDs, compute the delta, cache the retrieval index for
    subsequent /api/chat calls, and return the delta report as JSON."""
    trace = Trace(kind="web_delta")
    try:
        with trace.span("ingest_a") as s:
            doc_a = ingest_pid(req.pid_a, req.path_a)
            s.set(source_format=doc_a.source_format.value, element_count=doc_a.element_count())
        with trace.span("ingest_b") as s:
            doc_b = ingest_pid(req.pid_b, req.path_b)
            s.set(source_format=doc_b.source_format.value, element_count=doc_b.element_count())
        with trace.span("delta") as s:
            items: list[DeltaItem] = build_delta(doc_a, doc_b)
            s.set(total_changes=len(items))
        with trace.span("index") as s:
            index: RetrievalIndex = build_index(doc_a, doc_b, items)
            s.set(chunk_count=len(index.chunks))

        _state.update(pid_a=req.pid_a, pid_b=req.pid_b, index=index, items=items)
        report = to_json(req.pid_a, req.pid_b, items)
        report["request_id"] = trace.request_id
        return report
    finally:
        trace.write()


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    if _state["index"] is None:
        return {"error": "No delta loaded yet. Call /api/delta first (or click 'Load sample pair' in the UI)."}

    trace = Trace(kind="web_chat")
    try:
        result = answer_question(req.question, _state["index"], trace)
        result["request_id"] = trace.request_id
        return result
    finally:
        trace.write()


@app.get("/api/health")
def health():
    return {"status": "ok", "loaded": _state["index"] is not None}

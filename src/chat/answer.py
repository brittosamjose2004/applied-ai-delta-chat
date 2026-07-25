"""Grounded answer generation: retrieve relevant chunks from PID A, PID B,
and the delta report, then force the LLM to answer only from those chunks
and cite them by source tag. Fully traced (retrieval + LLM stages)."""
from __future__ import annotations

from src.chat.index import Chunk, RetrievalIndex
from src.chat.llm import LlmClient, default_client
from src.observability.tracing import Trace, estimate_cost_usd

SYSTEM_PROMPT = """You are a grounded assistant answering questions about two revisions \
of an engineering P&ID document (PID A = base revision, PID B = revised) and a delta report \
summarizing what changed between them.

Rules:
- Answer ONLY using the numbered SOURCES provided below. Do not use outside knowledge.
- Every claim in your answer must include a citation like [S3] referencing the source number.
- If the sources don't contain enough information to answer, say so explicitly instead of guessing.
- Be concise and precise about locations (page, source document) when relevant."""


def _format_sources(hits: list[tuple[Chunk, float]]) -> str:
    lines = []
    for i, (chunk, score) in enumerate(hits, start=1):
        origin = {"pid_a": "PID A", "pid_b": "PID B", "delta_report": "Delta Report"}[chunk.source]
        lines.append(f"[S{i}] ({origin}, page {chunk.page + 1}) {chunk.text}")
    return "\n".join(lines)


def answer_question(
    query: str,
    index: RetrievalIndex,
    trace: Trace,
    llm: LlmClient | None = None,
    top_k: int = 8,
) -> dict:
    llm = llm or default_client()

    with trace.span("retrieval") as s:
        hits = index.search(query, top_k=top_k)
        s.set(query=query, hit_count=len(hits), chunk_ids=[c.id for c, _ in hits])

    if not hits:
        return {"answer": "No relevant content found in either PID or the delta report.", "citations": []}

    sources_block = _format_sources(hits)
    user_prompt = f"SOURCES:\n{sources_block}\n\nQUESTION: {query}"

    with trace.span("llm_call") as s:
        resp = llm.complete(SYSTEM_PROMPT, user_prompt, max_tokens=800)
        cost = estimate_cost_usd(resp.model, resp.input_tokens, resp.output_tokens)
        s.set(provider=resp.provider, model=resp.model, input_tokens=resp.input_tokens,
              output_tokens=resp.output_tokens, cost_usd=cost)

    citations = [
        {"tag": f"S{i}", "source": c.source, "pid": c.pid, "page": c.page, "bbox": c.bbox, "text": c.text}
        for i, (c, _) in enumerate(hits, start=1)
    ]
    return {"answer": resp.text, "citations": citations}

"""End-to-end run: ingest PID A + PID B -> delta -> report, fully traced."""
from __future__ import annotations

from src.delta.engine import build_delta
from src.delta.report import write_report
from src.ingest.registry import ingest_pid
from src.observability.logging import get_logger, log
from src.observability.tracing import Trace

logger = get_logger()


def run_delta_pipeline(pid_a: str, path_a: str, pid_b: str, path_b: str, out_dir: str) -> dict:
    trace = Trace(kind="delta")
    log(logger, "info", "delta pipeline started", request_id=trace.request_id, pid_a=pid_a, pid_b=pid_b)

    try:
        with trace.span("ingest_a") as s:
            doc_a = ingest_pid(pid_a, path_a)
            s.set(source_format=doc_a.source_format.value, element_count=doc_a.element_count())

        with trace.span("ingest_b") as s:
            doc_b = ingest_pid(pid_b, path_b)
            s.set(source_format=doc_b.source_format.value, element_count=doc_b.element_count())

        with trace.span("delta") as s:
            items = build_delta(doc_a, doc_b)
            s.set(total_changes=len(items),
                  added=sum(1 for i in items if i.change_type == "added"),
                  removed=sum(1 for i in items if i.change_type == "removed"),
                  modified=sum(1 for i in items if i.change_type == "modified"))

        with trace.span("report") as s:
            json_path, md_path, html_path = write_report(pid_a, pid_b, items, out_dir)
            s.set(json_path=str(json_path), md_path=str(md_path), html_path=str(html_path))

        log(logger, "info", "delta pipeline completed", request_id=trace.request_id,
            total_changes=len(items))
        return {
            "request_id": trace.request_id, "items": items,
            "json_path": str(json_path), "md_path": str(md_path), "html_path": str(html_path),
        }
    except Exception as e:
        log(logger, "error", f"delta pipeline failed: {e}", request_id=trace.request_id)
        raise
    finally:
        trace.write()

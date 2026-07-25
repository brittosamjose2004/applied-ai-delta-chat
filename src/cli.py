"""Single entrypoint: `python -m src.cli run|chat`

  run  --pid-a ... --path-a ... --pid-b ... --path-b ... --out ...
       ingests both PIDs, computes the delta, writes the report.

  chat --pid-a ... --path-a ... --pid-b ... --path-b ... [--ask "..."]
       ingests + computes delta, builds the retrieval index, then either
       answers one question (--ask) or drops into an interactive REPL.

  markup --pid-a ... --path-a ... --pid-b ... --path-b ... --out ...
       ingests both PIDs, computes the delta, overlays it as colored
       highlight boxes on a copy of PID B (bonus deliverable).
"""
from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv

from src.chat.answer import answer_question
from src.chat.index import build_index
from src.delta.engine import build_delta
from src.ingest.registry import ingest_pid
from src.markup.overlay import UnsupportedMarkupFormatError, render_markup
from src.observability.tracing import Trace
from src.pipeline import run_delta_pipeline


def cmd_run(args):
    result = run_delta_pipeline(args.pid_a, args.path_a, args.pid_b, args.path_b, args.out)
    print(f"Delta: {len(result['items'])} changes")
    print(f"Report (Markdown): {result['md_path']}")
    print(f"Report (HTML): {result['html_path']}")
    print(f"Report (JSON): {result['json_path']}")
    print(f"Trace request_id: {result['request_id']}")


def cmd_markup(args):
    doc_a = ingest_pid(args.pid_a, args.path_a)
    doc_b = ingest_pid(args.pid_b, args.path_b)
    items = build_delta(doc_a, doc_b)
    try:
        out_path = render_markup(args.path_b, items, args.out)
        print(f"Markup written: {out_path} ({len(items)} changes overlaid)")
    except UnsupportedMarkupFormatError as e:
        print(f"Markup skipped: {e}")


def cmd_chat(args):
    doc_a = ingest_pid(args.pid_a, args.path_a)
    doc_b = ingest_pid(args.pid_b, args.path_b)
    items = build_delta(doc_a, doc_b)
    index = build_index(doc_a, doc_b, items)

    def ask(q: str):
        trace = Trace(kind="chat")
        result = answer_question(q, index, trace)
        trace.write()
        print("\n" + result["answer"])
        print("\nCitations:")
        for c in result["citations"]:
            origin = {"pid_a": "PID A", "pid_b": "PID B", "delta_report": "Delta Report"}[c["source"]]
            print(f"  [{c['tag']}] {origin} p.{c['page']+1} - {c['text'][:70]}")
        print(f"\n(trace: {trace.request_id})")

    if args.ask:
        ask(args.ask)
        return

    print("Grounded chat over PID A, PID B, and the delta report. Ctrl+C to exit.")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        ask(q)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run")
    p_run.add_argument("--pid-a", required=True)
    p_run.add_argument("--path-a", required=True)
    p_run.add_argument("--pid-b", required=True)
    p_run.add_argument("--path-b", required=True)
    p_run.add_argument("--out", required=True)
    p_run.set_defaults(func=cmd_run)

    p_chat = sub.add_parser("chat")
    p_chat.add_argument("--pid-a", required=True)
    p_chat.add_argument("--path-a", required=True)
    p_chat.add_argument("--pid-b", required=True)
    p_chat.add_argument("--path-b", required=True)
    p_chat.add_argument("--ask", default=None)
    p_chat.set_defaults(func=cmd_chat)

    p_markup = sub.add_parser("markup")
    p_markup.add_argument("--pid-a", required=True)
    p_markup.add_argument("--path-a", required=True)
    p_markup.add_argument("--pid-b", required=True)
    p_markup.add_argument("--path-b", required=True)
    p_markup.add_argument("--out", required=True)
    p_markup.set_defaults(func=cmd_markup)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

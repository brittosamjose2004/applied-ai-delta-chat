"""Renders a delta as a machine-parseable JSON artifact plus two
human-readable formats, Markdown and HTML. All three get written to disk
on every run. The JSON version also gets indexed by the chat retrieval
layer as a source document.
"""
from __future__ import annotations

import html as html_lib
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from src.delta.engine import DeltaItem


def to_json(pid_a: str, pid_b: str, items: list[DeltaItem]) -> dict:
    counts = Counter(i.change_type for i in items)
    return {
        "pid_a": pid_a,
        "pid_b": pid_b,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_changes": len(items),
            "added": counts.get("added", 0),
            "removed": counts.get("removed", 0),
            "modified": counts.get("modified", 0),
        },
        "changes": [asdict(i) for i in items],
    }


def to_markdown(pid_a: str, pid_b: str, items: list[DeltaItem]) -> str:
    counts = Counter(i.change_type for i in items)
    lines = [
        f"# Delta Report: {pid_a} to {pid_b}",
        "",
        f"**Total changes:** {len(items)}  ",
        f"Added: {counts.get('added', 0)}, Removed: {counts.get('removed', 0)}, Modified: {counts.get('modified', 0)}",
        "",
    ]

    by_page: dict[int, list[DeltaItem]] = {}
    for it in items:
        by_page.setdefault(it.page, []).append(it)

    for page in sorted(by_page):
        lines.append(f"## Page {page + 1}")
        lines.append("")
        for it in by_page[page]:
            lines.append(f"- [{it.change_type}/{it.category}] (id `{it.id[:8]}`, confidence {it.confidence:.2f}): {it.description}")
        lines.append("")

    return "\n".join(lines)


_TAG_COLOR = {"added": "#2fbf71", "removed": "#ef5d5d", "modified": "#4c8dff"}


def to_html(pid_a: str, pid_b: str, items: list[DeltaItem]) -> str:
    counts = Counter(i.change_type for i in items)
    by_page: dict[int, list[DeltaItem]] = {}
    for it in items:
        by_page.setdefault(it.page, []).append(it)

    rows = []
    for page in sorted(by_page):
        rows.append(f'<h2>Page {page + 1}</h2><ul class="changes">')
        for it in by_page[page]:
            color = _TAG_COLOR[it.change_type]
            desc = html_lib.escape(it.description)
            rows.append(
                f'<li><span class="tag" style="background:{color}22;color:{color};'
                f'border:1px solid {color}55">{it.change_type}/{it.category}</span> '
                f'<span class="conf">conf {it.confidence:.2f}</span>: {desc}</li>'
            )
        rows.append("</ul>")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Delta Report: {html_lib.escape(pid_a)} vs {html_lib.escape(pid_b)}</title>
<style>
  body{{font:14px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;background:#0f1115;color:#e7ecf3;
       max-width:900px;margin:0 auto;padding:24px}}
  h1{{font-size:20px}} h2{{font-size:15px;color:#9aa7b8;border-top:1px solid #2a323e;padding-top:14px}}
  .summary{{display:flex;gap:10px;margin:14px 0}}
  .chip{{background:#212936;border:1px solid #2a323e;border-radius:8px;padding:6px 10px;font-size:12.5px}}
  ul.changes{{list-style:none;padding:0}}
  ul.changes li{{border-bottom:1px solid #2a323e;padding:8px 0}}
  .tag{{font-size:11px;font-weight:600;padding:2px 7px;border-radius:5px;margin-right:6px}}
  .conf{{color:#9aa7b8;font-size:12px}}
</style></head>
<body>
<h1>Delta Report: {html_lib.escape(pid_a)} to {html_lib.escape(pid_b)}</h1>
<div class="summary">
  <div class="chip">total {len(items)}</div>
  <div class="chip">added {counts.get('added', 0)}</div>
  <div class="chip">removed {counts.get('removed', 0)}</div>
  <div class="chip">modified {counts.get('modified', 0)}</div>
</div>
{''.join(rows)}
</body></html>"""


def write_report(pid_a: str, pid_b: str, items: list[DeltaItem], out_dir: str) -> tuple[Path, Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "delta_report.json"
    md_path = out / "delta_report.md"
    html_path = out / "delta_report.html"
    json_path.write_text(json.dumps(to_json(pid_a, pid_b, items), indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(pid_a, pid_b, items), encoding="utf-8")
    html_path.write_text(to_html(pid_a, pid_b, items), encoding="utf-8")
    return json_path, md_path, html_path

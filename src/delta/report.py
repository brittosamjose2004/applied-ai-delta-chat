"""Render a delta as a machine-parseable JSON artifact and a human-readable
Markdown report. Both are written to disk; the JSON is also what the chat
retrieval layer indexes as a first-class source.
"""
from __future__ import annotations

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
        f"# Delta Report — {pid_a} → {pid_b}",
        "",
        f"**Total changes:** {len(items)}  ",
        f"Added: {counts.get('added', 0)} · Removed: {counts.get('removed', 0)} · Modified: {counts.get('modified', 0)}",
        "",
    ]

    by_page: dict[int, list[DeltaItem]] = {}
    for it in items:
        by_page.setdefault(it.page, []).append(it)

    for page in sorted(by_page):
        lines.append(f"## Page {page + 1}")
        lines.append("")
        for it in by_page[page]:
            tag = {"added": "➕", "removed": "➖", "modified": "✏️"}[it.change_type]
            lines.append(f"- {tag} **[{it.change_type}/{it.category}]** (id `{it.id[:8]}`, confidence {it.confidence:.2f}) — {it.description}")
        lines.append("")

    return "\n".join(lines)


def write_report(pid_a: str, pid_b: str, items: list[DeltaItem], out_dir: str) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "delta_report.json"
    md_path = out / "delta_report.md"
    json_path.write_text(json.dumps(to_json(pid_a, pid_b, items), indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(pid_a, pid_b, items), encoding="utf-8")
    return json_path, md_path

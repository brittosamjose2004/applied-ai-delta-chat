"""Delta markup overlay (bonus): draws the computed delta back onto PID B as
colored highlight boxes — the visual artifact a human reviewer used to draw
by hand when comparing revisions.

added -> green, removed -> red (drawn at its PID-A location, since it no
longer exists on B), modified -> blue.
"""
from __future__ import annotations

import fitz  # PyMuPDF

from src.delta.engine import DeltaItem

COLOR = {
    "added": (0.18, 0.75, 0.44),     # green
    "removed": (0.94, 0.36, 0.36),   # red
    "modified": (0.30, 0.55, 1.0),   # blue
}


def render_markup(path_b: str, items: list[DeltaItem], out_path: str) -> str:
    """Overlay delta bboxes on a copy of PID B and save to out_path.
    Removed items have no location on B, so they're skipped here — a fuller
    implementation would overlay them on a rendered copy of PID A instead."""
    doc = fitz.open(path_b)

    for item in items:
        if item.change_type == "removed":
            continue  # no B-side location to draw on; see docstring
        if item.page >= len(doc):
            continue
        page = doc[item.page]
        rect = fitz.Rect(*item.bbox)
        color = COLOR[item.change_type]
        annot = page.add_rect_annot(rect)
        annot.set_colors(stroke=color)
        annot.set_border(width=1.2)
        annot.set_opacity(0.9)
        annot.update()
        page.insert_text(
            (rect.x0, max(rect.y0 - 2, 8)),
            f"{item.change_type[:3].upper()}",
            fontsize=5,
            color=color,
        )

    doc.save(out_path)
    doc.close()
    return out_path

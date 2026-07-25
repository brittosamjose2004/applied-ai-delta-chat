"""Synthesize a Rev A / Rev B document pair (+ a scanned variant) from the
source P&ID PDF, with a documented, known ground-truth delta.

Usage: python scripts/make_samples.py
"""
import json
import shutil
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parents[2]
SRC_PDF = ROOT / "Lift Gas compressor-P&ID.pdf"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "samples" / "pair_01_lift_gas_compressor"
OUT_DIR.mkdir(parents=True, exist_ok=True)

REV_A = OUT_DIR / "rev_A_native.pdf"
REV_B = OUT_DIR / "rev_B_native.pdf"
REV_A_SCAN = OUT_DIR / "rev_A_scanned.pdf"


def redact_and_replace(page, bbox, new_text, fontsize=4.3):
    """Whiteout the given bbox and insert replacement text at the same spot."""
    rect = fitz.Rect(*bbox)
    page.add_redact_annot(rect, fill=(1, 1, 1))
    page.apply_redactions()
    page.insert_text((rect.x0, rect.y1 - 1.0), new_text, fontsize=fontsize, fontname="helv", color=(0, 0, 0))


def build_rev_b():
    shutil.copy(SRC_PDF, REV_A)

    doc = fitz.open(SRC_PDF)
    page = doc[0]

    changes = []

    # 1. MODIFIED — note 5 text changed
    redact_and_replace(
        page,
        (35, 713, 189, 718),
        "OIL CHANGE BY USING PERMANENT ARRANGEMENT WITH DEDICATED PUMP.",
    )
    changes.append({
        "type": "modified", "category": "note", "page": 1,
        "location": {"bbox": [35, 713, 189, 718]},
        "before": "OIL CHANGE BY USING TEMPORARY ARRANGEMENT WITH HOSES.",
        "after": "OIL CHANGE BY USING PERMANENT ARRANGEMENT WITH DEDICATED PUMP.",
        "description": "Note 5 revised: oil change method changed from temporary hose arrangement to a permanent dedicated pump.",
    })

    # 2. REMOVED — note 8 deleted (whited out, left blank)
    rect8 = fitz.Rect(34, 731, 208, 737)
    page.add_redact_annot(rect8, fill=(1, 1, 1))
    page.apply_redactions()
    changes.append({
        "type": "removed", "category": "note", "page": 1,
        "location": {"bbox": [34, 731, 208, 737]},
        "before": "FLAME ARRESTER INCLUDES FLAME FILTER AND LOCATED AT END OF PIPE.",
        "after": None,
        "description": "Note 8 removed entirely (flame arrester note dropped from Rev B).",
    })

    # 3. MODIFIED — instrument tag renumbered, two occurrences
    for bbox in [(46.2, 35.7, 74.4, 41.5), (46.2, 76.4, 74.4, 82.2)]:
        redact_and_replace(page, bbox, "26-PIT-9099", fontsize=4.5)
    changes.append({
        "type": "modified", "category": "tag", "page": 1,
        "location": {"bbox": [46.2, 35.7, 74.4, 41.5]},
        "before": "26-PIT-9077",
        "after": "26-PIT-9099",
        "description": "Instrument tag 26-PIT-9077 renumbered to 26-PIT-9099 (appears at 2 locations on the sheet).",
    })

    # 4. MODIFIED — design pressure value changed
    redact_and_replace(
        page,
        (253, 734, 450, 739),
        "22.     DESIGN PRESSURE IN EXTERNAL SYSTEM DOWNSTREAM COMPRESSOR 265 BARG.",
        fontsize=4.3,
    )
    changes.append({
        "type": "modified", "category": "dimension", "page": 1,
        "location": {"bbox": [253, 734, 450, 739]},
        "before": "22. DESIGN PRESSURE IN EXTERNAL SYSTEM DOWNSTREAM COMPRESSOR 257 BARG.",
        "after": "22. DESIGN PRESSURE IN EXTERNAL SYSTEM DOWNSTREAM COMPRESSOR 265 BARG.",
        "description": "Design pressure downstream of compressor increased from 257 BARG to 265 BARG.",
    })

    # 5. ADDED — new note appended
    page.insert_text((253, 819), "35.", fontsize=4.3, fontname="helv", color=(0, 0, 0))
    page.insert_text((267, 819), "TEMPORARY BYPASS LINE ADDED PER FIELD CHANGE NOTICE FCN-0142.",
                      fontsize=4.3, fontname="helv", color=(0, 0, 0))
    changes.append({
        "type": "added", "category": "note", "page": 1,
        "location": {"bbox": [253, 814, 505, 820]},
        "before": None,
        "after": "35. TEMPORARY BYPASS LINE ADDED PER FIELD CHANGE NOTICE FCN-0142.",
        "description": "New note 35 added documenting a temporary bypass line per field change notice FCN-0142.",
    })

    doc.save(REV_B)
    doc.close()

    with open(OUT_DIR / "ground_truth_delta.json", "w") as f:
        json.dump({
            "pair_id": "pair_01_lift_gas_compressor",
            "pid_a": "rev_A_native.pdf",
            "pid_b": "rev_B_native.pdf",
            "changes": changes,
        }, f, indent=2)

    print(f"Wrote {REV_A}, {REV_B}, and ground_truth_delta.json with {len(changes)} changes.")


def build_scanned_variant():
    """Rasterize Rev A's page to an image and re-embed as an image-only PDF
    (no text layer) to simulate a scanned document."""
    doc = fitz.open(REV_A)
    page = doc[0]
    pix = page.get_pixmap(dpi=200)
    img_path = OUT_DIR / "_rev_A_page1.png"
    pix.save(img_path)

    scanned = fitz.open()
    img_doc = fitz.open(img_path)
    rect = fitz.Rect(0, 0, pix.width, pix.height)
    scanned_page = scanned.new_page(width=pix.width, height=pix.height)
    scanned_page.insert_image(rect, filename=str(img_path))
    scanned.save(REV_A_SCAN)
    scanned.close()
    img_doc.close()
    img_path.unlink()
    print(f"Wrote {REV_A_SCAN} (image-only, no text layer).")


def write_provenance():
    (OUT_DIR / "PROVENANCE.md").write_text(f"""# Sample pair 01 — Lift Gas Compressor P&ID

**Source document:** `Lift Gas compressor-P&ID.pdf` (provided real P&ID, single sheet).

**How this pair was synthesized** (per assignment guidance to synthesize pairs when a real
revision history isn't available):

- `rev_A_native.pdf` — unmodified copy of the source PDF. Treated as the base revision.
- `rev_B_native.pdf` — same PDF with 5 deliberate, documented edits applied via PyMuPDF
  (redact region + re-insert text at the same coordinates), representing a realistic revision:
  1 modified note, 1 removed note, 1 modified instrument tag (2 occurrences), 1 modified
  numeric value, 1 added note. Full details in `ground_truth_delta.json`.
- `rev_A_scanned.pdf` — Rev A rasterized to a 200dpi PNG and re-embedded as an image-only PDF
  (no text layer), simulating a scanned/photographed document for the OCR ingestion path.

**Ground truth:** `ground_truth_delta.json` is the labeled answer key used by the eval harness
to score the delta engine (precision/recall/F1) — it was authored by construction (we made the
edits, so we know exactly what changed), not inferred after the fact.
""")


if __name__ == "__main__":
    build_rev_b()
    build_scanned_variant()
    write_provenance()

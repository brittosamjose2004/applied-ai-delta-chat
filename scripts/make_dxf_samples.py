"""Synthesize a small DXF Rev A / Rev B pair (with ground truth) to prove
the DWG/DXF ingestion adapter end-to-end, since no real DWG/DXF sample was
provided. A synthetic DXF stands in for a CAD-exported drawing: a handful
of TEXT entities representing instrument tags and notes, edited between
revisions the same way the PDF sample pair was.
"""
import json
from pathlib import Path

import ezdxf

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "samples" / "pair_02_dxf_sample"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def make_doc(entries):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    for text, (x, y) in entries:
        msp.add_text(text, height=2.5).set_placement((x, y))
    return doc


REV_A_ENTRIES = [
    ("26-PIT-4001 SUCTION PRESSURE", (0, 100)),
    ("26-TIT-4002 DISCHARGE TEMP", (0, 90)),
    ("NOTE 1: DRAIN VALVE MANUAL OPERATION", (0, 80)),
    ("NOTE 2: INSULATION PER SPEC 4471", (0, 70)),
    ("VALVE 26-FV-4010 FAIL CLOSED", (0, 60)),
]

REV_B_ENTRIES = [
    ("26-PIT-4099 SUCTION PRESSURE", (0, 100)),   # modified: tag renumbered
    ("NOTE 1: DRAIN VALVE MANUAL OPERATION", (0, 80)),  # unchanged
    ("NOTE 2: INSULATION PER SPEC 4900", (0, 70)),  # modified: spec number changed
    ("VALVE 26-FV-4010 FAIL OPEN", (0, 60)),        # modified: fail action changed
    ("NOTE 3: NEW ISOLATION VALVE ADDED PER RFC-88", (0, 50)),  # added
    # "26-TIT-4002 DISCHARGE TEMP" removed entirely
]

GROUND_TRUTH = [
    {"type": "modified", "category": "tag", "before": "26-PIT-4001 SUCTION PRESSURE",
     "after": "26-PIT-4099 SUCTION PRESSURE", "description": "Instrument tag renumbered 26-PIT-4001 -> 26-PIT-4099."},
    {"type": "removed", "category": "text", "before": "26-TIT-4002 DISCHARGE TEMP",
     "after": None, "description": "Discharge temperature tag removed."},
    {"type": "modified", "category": "note", "before": "NOTE 2: INSULATION PER SPEC 4471",
     "after": "NOTE 2: INSULATION PER SPEC 4900", "description": "Insulation spec number changed."},
    {"type": "modified", "category": "text", "before": "VALVE 26-FV-4010 FAIL CLOSED",
     "after": "VALVE 26-FV-4010 FAIL OPEN", "description": "Valve fail-safe action changed from closed to open."},
    {"type": "added", "category": "note", "before": None,
     "after": "NOTE 3: NEW ISOLATION VALVE ADDED PER RFC-88", "description": "New note added referencing RFC-88."},
]


def main():
    rev_a = make_doc(REV_A_ENTRIES)
    rev_b = make_doc(REV_B_ENTRIES)
    rev_a.saveas(OUT_DIR / "rev_A.dxf")
    rev_b.saveas(OUT_DIR / "rev_B.dxf")

    (OUT_DIR / "ground_truth_delta.json").write_text(json.dumps({
        "pair_id": "pair_02_dxf_sample",
        "pid_a": "rev_A.dxf",
        "pid_b": "rev_B.dxf",
        "changes": GROUND_TRUTH,
    }, indent=2))

    (OUT_DIR / "PROVENANCE.md").write_text(
        "# Sample pair 02 — synthetic DXF\n\n"
        "No real DWG/DXF sample was available, so this pair is fully synthetic: "
        "built directly with `ezdxf` (scripts/make_dxf_samples.py) as a small set of "
        "TEXT entities representing instrument tags and notes, edited between "
        "revisions with the same 5-change pattern (1 modified tag, 1 removed, "
        "1 modified note, 1 modified text, 1 added note) used in the PDF sample pair. "
        "Exists to prove the DXF ingestion adapter (src/ingest/dwg.py) end-to-end, "
        "not to represent a real engineering drawing.\n"
    )
    print(f"Wrote {OUT_DIR}")


if __name__ == "__main__":
    main()

# Sample pair 01 — Lift Gas Compressor P&ID

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

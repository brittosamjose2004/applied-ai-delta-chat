# Sample pair 01 - Lift Gas Compressor P&ID

**Source document:** `Lift Gas compressor-P&ID.pdf` (provided real P&ID, single sheet).

**How this pair was synthesized** (per assignment guidance to synthesize pairs when a real
revision history isn't available):

- `rev_A_native.pdf` - unmodified copy of the source PDF. Treated as the base revision.
- `rev_B_native.pdf` - same PDF with 5 deliberate, documented edits applied via PyMuPDF
  (redact region + re-insert text at the same coordinates), representing a realistic revision:
  1 modified note, 1 removed note, 1 modified instrument tag (2 occurrences), 1 modified
  numeric value, 1 added note. Full details in `ground_truth_delta.json`.
- `rev_A_scanned.pdf` / `rev_B_scanned.pdf` - Rev A and Rev B each rasterized to a 200dpi PNG
  and re-embedded as an image-only PDF (no text layer), simulating a scanned/photographed
  document pair for the OCR ingestion path. This is a genuinely dense, stress-case page
  (~875 text elements at 9192x6498px) - running the full pipeline on it surfaced a real
  vision-OCR token-budget limitation, documented honestly in the main README's "Honest
  failure table" section rather than hidden.

**Ground truth:** `ground_truth_delta.json` is the labeled answer key used by the eval harness
to score the delta engine (precision/recall/F1) - it was authored by construction (we made the
edits, so we know exactly what changed), not inferred after the fact. It reflects the native
(non-OCR'd) content; the scanned-pair OCR output is not separately scored against it since OCR
recovers only a partial subset of this particular dense page (see README).

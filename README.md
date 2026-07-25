# delta-chat — Document Delta & Grounded Chat

Computes a structured delta between two P&ID revisions and lets you chat with both
revisions and the delta report, with citations.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in at least one LLM provider (see below)
```

**LLM provider:** set any of `GEMINI_API_KEY` (direct Gemini API), `VERTEX_PROJECT` +
`GOOGLE_APPLICATION_CREDENTIALS` (Gemini via Vertex AI), `NVIDIA_NIM_API_KEY` (NIM), or
`ANTHROPIC_API_KEY` (Claude). If multiple are set, `default_client()` builds a fallback
chain (priority: direct Gemini → Vertex → NIM → Anthropic) that automatically moves to the
next provider on any failure. This submission was tested live against **Vertex AI**
(`gemini-2.5-flash-lite`) with NVIDIA NIM configured as a working fallback.

Note: if you use a `gen-lang-client-*` project (auto-created by Google AI Studio) for
Vertex, the API being "enabled" in the library isn't sufficient — you need to open
[Vertex AI Studio](https://console.cloud.google.com/vertex-ai/studio/freeform) in the
console and run one prompt there first to provision Model Garden access; otherwise every
model 404s even with billing and `aiplatform.googleapis.com` both enabled.

Sample data (a synthesized Rev A / Rev B pair + a scanned variant) is already generated
in `data/samples/pair_01_lift_gas_compressor/`. To regenerate it from the source PDF:

```bash
make samples
```

## Run

```bash
make run     # ingest -> delta -> report (data/samples/.../output/delta_report.{md,json})
make chat    # interactive grounded chat REPL over PID A, PID B, and the delta report
make markup  # overlay the delta as colored highlight boxes on a copy of PID B (bonus)
make web     # served UI/dashboard at http://127.0.0.1:8000 (bonus)
make eval    # scorecard: delta P/R/F1, chat correctness/groundedness, retrieval recall@k, cost/latency
make test    # unit tests
```

One-off question: `python -m src.cli chat --pid-a ... --path-a ... --pid-b ... --path-b ... --ask "what changed on the tag 26-PIT-9077?"`

## What's built

- **Ingestion** (`src/ingest/`): one `FormatAdapter` interface (`base.py`). Implemented:
  native PDF (`pdf_native.py`, PyMuPDF text-layer extraction), scanned PDF
  (`pdf_scanned.py`, vision-LLM OCR — see trade-off below), and DWG/DXF (`dwg.py`, `ezdxf`
  — TEXT/MTEXT/DIMENSION entities extracted with their real rendered bounding box via
  `ezdxf.bbox`). Binary `.dwg` specifically still needs a proprietary DWG→DXF conversion
  step (ODA File Converter) not available in this environment, so `.dwg` inputs raise a
  clear `NotImplementedError`; `.dxf` — the open, documented sibling format — is fully
  ingested end-to-end through the same adapter, proven against a synthetic sample pair
  (`data/samples/pair_02_dxf_sample/`, P=1.0/R=1.0/F1=1.0 in `make eval`).
- **Canonical representation** (`src/canonical/model.py`): every format normalizes into
  `CanonicalDocument -> Page -> TextElement(text, bbox, element_type, confidence)`. Nothing
  downstream imports format-specific code.
- **Delta engine** (`src/delta/`): `align.py` matches elements between revisions on a
  blend of text similarity + spatial proximity (greedy, highest-score-first — a simple
  stand-in for optimal bipartite matching), `engine.py` classifies matched/unmatched pairs
  into added/removed/modified with confidence, `report.py` renders MD + JSON.
- **Grounded chat** (`src/chat/`): BM25 keyword retrieval (`index.py`) over PID A, PID B,
  and the delta report; a provider-agnostic `LlmClient` interface (`llm.py`) with three
  implementations — Anthropic, Google Gemini (Vertex AI), NVIDIA NIM (OpenAI-compatible) —
  plus a `FallbackLlmClient` that tries them in order (Vertex → NIM → Anthropic) and moves
  to the next provider on any exception (timeout/quota/auth), logging each failure. Only
  providers whose env vars are actually set are included in the chain, so a single-provider
  setup (e.g. just `ANTHROPIC_API_KEY`) works unchanged. `answer.py` forces citations
  (`[S1]`, `[S2]`...) and instructs the model to say "not enough information" rather than
  invent facts.
- **Observability** (`src/observability/`): every request gets a `Trace` with per-stage
  timing (ingest/delta/retrieval/llm/report) written as a JSON file per run under
  `traces/`, plus structured JSON stdout logs correlated by `request_id`. LLM calls record
  which **provider** actually served the request (important once there's a fallback chain),
  model, token counts, and an estimated cost.
- **Eval** (`eval/`): `run_eval.py` scores the delta engine against a hand-labeled ground
  truth (`data/samples/.../ground_truth_delta.json`) with precision/recall/F1, and — if
  `ANTHROPIC_API_KEY` is set — scores chat answers on a small Q&A set
  (`eval/datasets/pair_01_qa.json`) using LLM-as-judge for correctness + groundedness.

## Sample data & provenance

Two real P&ID PDFs were provided. They're different drawings (not two revisions of the
same document), so per the assignment's "synthesize if needed" guidance, I generated a
proper Rev A/Rev B pair from one of them (`scripts/make_samples.py`):

- `rev_A_native.pdf` — unmodified source.
- `rev_B_native.pdf` — same PDF with 5 deliberate, programmatic edits (redact region +
  re-insert text at the same coordinates): a modified note, a removed note, a renumbered
  instrument tag (2 occurrences), a changed pressure value, and a newly added note.
- `rev_A_scanned.pdf` — Rev A rasterized to PNG and re-embedded with no text layer, to
  exercise the scanned-PDF/OCR path.
- `ground_truth_delta.json` — the answer key, authored by construction (not inferred after
  the fact) since we made the edits ourselves. Full provenance in `PROVENANCE.md` next to
  the files.

This means A→B is currently proven on **native PDF + scanned PDF**. DWG stays a stub (see
above) — that's the scope cut called out below.

## Design decisions & trade-offs

- **Delta engine is fully deterministic, no LLM.** Alignment and classification use text
  similarity (`difflib.SequenceMatcher`) + spatial proximity only. This satisfies the
  "reproducible structural output" requirement directly and isolates all LLM
  non-determinism to the chat/answer layer, where it belongs. Cost: the delta engine can't
  use semantic understanding (e.g. recognizing a paraphrase as unchanged) — a real system
  would likely add an LLM *classification* pass on top of the deterministic candidate list,
  not inside the alignment itself.
- **Scanned-PDF OCR uses a vision LLM, not Tesseract.** No system Tesseract binary was
  available in this environment, and a vision model additionally recovers coarse layout
  without a separate detection step — one API call gets text + approximate bounding boxes.
  Trade-off: bboxes are model-estimated, not pixel-precise, so `confidence` on scanned
  elements is set below 1.0 and threaded through to delta/citations.
- **Chat retrieval is BM25 keyword search, not embeddings.** P&ID content is dense with
  exact codes/tags/values ("26-PIT-9077", "257 BARG") where lexical match is more reliable
  than semantic similarity, and it avoids a second API/provider just for embeddings. A
  production version would likely combine BM25 with embeddings for recall on paraphrased
  questions.
- **Alignment matching is greedy, not globally optimal.** Sorting all candidate pairs by
  score and assigning highest-first is simple and fast but can force a weak match between
  two genuinely unrelated leftover elements instead of reporting them as separate
  add+remove. Visible in the eval failure table below.
- **Observability is a homegrown JSON tracer**, not OpenTelemetry/Langfuse. For a
  single-process take-home this is simpler to read and needs zero extra infra; the trace
  schema (spans with name/duration/data/error, root request_id) maps directly onto OTel
  spans if this needed to scale to a real service.

## What I cut

- **Binary `.dwg` conversion**: needs a proprietary ODA/Autodesk converter to become DXF
  first, which isn't available/redistributable in this environment. The adapter interface,
  detection routing, and `.dxf` parsing are all real (see above) — only the DWG→DXF
  conversion step itself is out of scope.
- **Embedding-based retrieval**: BM25 only (see trade-offs above); no embedding provider
  wired in alongside it.
- **Multi-user web UI**: the served UI (`make web`) keeps a single global in-memory session
  — fine for a local demo, not for concurrent users. A real deployment would key session
  state by request/user id instead of a module-level dict.

## Honest failure table (from `make eval` on the sample pair)

```
precision=0.4  recall=0.8  f1=0.533
TP=4  FP=6  FN=1
```

- **Missed (FN):** the removed note (Note 8) — its bbox becomes blank/whitespace after
  redaction, and the aligner has nothing on the B side to *not* match, so it can get
  absorbed into a nearby weak match instead of standing alone as "removed."
- **Spurious (FP):** most come from the text-editing script itself splitting one logical
  line into multiple text runs after redaction (e.g. "FROM 26-PIT-9077 IN 3RD" fragmenting
  into separate "FROM" / "IN 3RD" runs) — an artifact of how `rev_B_native.pdf` was
  synthesized via redact+reinsert, not a fundamental algorithm flaw, but it's exactly the
  kind of line-segmentation noise a real revision (re-exported from CAD) would also produce
  to some degree.
- **Duplicate tag change:** `26-PIT-9077 → 26-PIT-9099` appears at 2 physical locations on
  the sheet; the ground truth counts it once as a semantic change, the engine (correctly)
  detects it as 2 separate element-level modifications — a labeling-granularity mismatch
  worth resolving with a "same logical change, multiple locations" grouping step.

Corroborating evidence this is a synthesis artifact, not an algorithm flaw: the second
sample pair (`pair_02_dxf_sample`, a synthetic DXF built directly rather than via
redact+reinsert) scores **precision=1.0, recall=1.0, f1=1.0** with the identical delta
engine code.

**Retrieval quality (`make eval`, BM25 recall@8, no LLM involved):**
`pair_01`: recall@8 = 0.5 (3/6) — misses correlate exactly with the chat questions the
LLM-as-judge later marks incorrect ("note 5", "note removed", "note 3"), confirming those
are retrieval failures, not generation failures: BM25's lexical matching doesn't surface a
chunk for a question that doesn't share vocabulary with the source text (e.g. "note 3"
never appears verbatim near the atmospheric-vent text on the page). This is the strongest
argument in this repo for adding embedding-based retrieval.

**Cost/latency (`make cost-report`, from real observed traces, not estimates):**
The delta-alignment stage, not the LLM call, is the actual bottleneck — p50 ≈ 7.4s for the
O(n·m) `SequenceMatcher` scoring over ~875×880 candidate element pairs on a single dense
P&ID sheet, versus p50 ≈ 2.6s for a full retrieval+LLM chat round-trip. Cost is negligible
(~$0.065 projected per 1,000 chat calls on `gemini-2.5-flash-lite`); latency, not cost, is
the actual scaling risk for larger sheets or multi-page documents.

## What I'd do next with more time

1. Fix the delta-engine's actual bottleneck: replace the O(n·m) candidate scoring with a
   spatial index (bucket by page region) before scoring, informed directly by the cost
   report above.
2. Replace greedy alignment with a proper assignment-optimal matching (e.g. Hungarian
   algorithm) to remove the forced-weak-match failure mode shown above.
3. Add a "same logical change, multiple locations" grouping pass on top of raw
   element-level delta items.
4. Add embedding-based retrieval alongside BM25 — directly motivated by the recall@8 gap
   measured above, not a guess.
5. Implement real binary `.dwg` support (ODA File Converter → the `ezdxf` path already
   built) once a licensed converter is available.
6. Expand the eval set with a real scanned-PDF pair (the current one is synthetic-only) and
   more document pairs generally, to reduce variance in the scorecard.
7. Key the web UI's session state by request/user id instead of a single global dict, for
   concurrent-user support.

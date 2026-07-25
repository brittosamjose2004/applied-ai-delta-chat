# delta-chat: Document Delta and Grounded Chat

Computes a structured delta between two P&ID revisions and lets you chat with both
revisions and the delta report, with citations.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in at least one LLM provider (see below)
```

LLM provider: set any of `GEMINI_API_KEY` (direct Gemini API), `VERTEX_PROJECT` plus
`GOOGLE_APPLICATION_CREDENTIALS` (Gemini via Vertex AI), `NVIDIA_NIM_API_KEY` (NIM), or
`ANTHROPIC_API_KEY` (Claude). If more than one is set, `default_client()` builds a fallback
chain (priority: direct Gemini, then Vertex, then NIM, then Anthropic) that automatically
moves to the next provider if one fails. This submission was tested live against Vertex AI
(`gemini-2.5-flash-lite`), with NVIDIA NIM configured as a working fallback.

If you're using a `gen-lang-client-*` project (the kind Google AI Studio auto-creates) for
Vertex, having the API show as "enabled" in the library isn't enough on its own. You need
to open [Vertex AI Studio](https://console.cloud.google.com/vertex-ai/studio/freeform) in
the console and run one prompt there first to provision Model Garden access. Otherwise
every model call 404s, even with billing and `aiplatform.googleapis.com` both enabled.

Sample data (a synthesized Rev A / Rev B pair plus a scanned variant) is already generated
in `data/samples/pair_01_lift_gas_compressor/`. To regenerate it from the source PDF:

```bash
make samples
```

## Run

```bash
make run     # ingest -> delta -> report, defaults to the native PDF pair (data/samples/.../output/delta_report.{md,json,html})
make chat    # interactive grounded chat REPL over PID A, PID B, and the delta report
make markup  # overlay the delta as colored highlight boxes on a copy of PID B (bonus)
make web     # served UI/dashboard at http://127.0.0.1:8000 (bonus)
make eval    # scorecard: delta P/R/F1, chat correctness/groundedness, retrieval recall@k, cost/latency
make test    # unit tests
```

`make run` and `make chat` always point at the native PDF pair by default, since that's what
the Makefile hardcodes. If you want to choose which sample pair to use instead (native PDF,
scanned PDF, or DXF), run the underlying command without `--path-a`/`--path-b` and you'll get
an interactive picker:

```bash
python -m src.cli run    # or: make pick
python -m src.cli chat   # or: make pick-chat
```

It lists every sample pair actually present under `data/samples/`, you type a number, and it
runs against that pair, output path included.

One-off question: `python -m src.cli chat --pid-a ... --path-a ... --pid-b ... --path-b ... --ask "what changed on the tag 26-PIT-9077?"`

If you don't have `make` installed, every target above is a one-line wrapper around a
`python -m ...` command. See the `Makefile` for the exact commands to run directly.

## What's built

Ingestion (`src/ingest/`) is built around one `FormatAdapter` interface (`base.py`).
Three formats are implemented: native PDF (`pdf_native.py`, PyMuPDF text-layer extraction),
scanned PDF (`pdf_scanned.py`, vision-LLM OCR, trade-off explained below), and DWG/DXF
(`dwg.py`, using `ezdxf`, where TEXT/MTEXT/DIMENSION entities are extracted with their real
rendered bounding box via `ezdxf.bbox`). Binary `.dwg` specifically still needs a
proprietary DWG-to-DXF conversion step (the ODA File Converter) that isn't available in
this environment, so `.dwg` inputs raise a clear `NotImplementedError`. DXF, the open and
documented sibling format, is fully ingested end to end through the same adapter, proven
against a synthetic sample pair (`data/samples/pair_02_dxf_sample/`, P=1.0/R=1.0/F1=1.0 in
`make eval`).

The canonical representation (`src/canonical/model.py`) is what every format normalizes
into: `CanonicalDocument -> Page -> TextElement(text, bbox, element_type, confidence)`.
Nothing downstream imports format-specific code.

The delta engine (`src/delta/`) has three parts. `align.py` matches elements between
revisions on a blend of text similarity and spatial proximity (a greedy, highest-score-first
assignment, a simple stand-in for optimal bipartite matching). `engine.py` classifies
matched and unmatched pairs into added, removed, or modified, each with a confidence score.
`report.py` renders Markdown, HTML, and JSON, all three written on every run (the
assignment's own example format is "Markdown/HTML + JSON", so we produce all three rather
than picking one).

Grounded chat (`src/chat/`) uses BM25 keyword retrieval (`index.py`) over PID A, PID B, and
the delta report. Two retrieval-quality problems were found and fixed by actually running
the system rather than trusting the design on paper:

1. Generic "what changed?" style questions (the assignment's own example query) share
   almost no vocabulary with delta-report text like "Modified tag: ...", so plain BM25 was
   retrieving unrelated unchanged content, and the LLM concluded, wrongly, that nothing had
   changed. `has_change_intent()` detects this question shape and forces delta-report
   chunks to the front of retrieval ranking regardless of lexical overlap. Covered by a
   regression test in `tests/test_retrieval_index.py`.
2. Equipment-table questions ("what is the duty of the compressor?") were failing because a
   P&ID table's label ("DUTY") and its value ("776 kW") sit in separate columns as two
   different `TextElement`s, same row, zero shared vocabulary, so a query matching the label
   never surfaced the value. `_row_chunks()` additionally indexes adjacent same-row cells as
   a combined chunk, gated by a measured horizontal gap so it doesn't pull in unrelated
   content from elsewhere on a wide sheet. Covered by `tests/test_row_chunks.py`.

`llm.py` defines a provider-agnostic `LlmClient` interface with four implementations
(Anthropic, Google Gemini direct API, Google Gemini via Vertex AI, NVIDIA NIM), plus a
`FallbackLlmClient` that tries them in order and moves to the next provider on any
exception (timeout, quota, auth), logging each failure. Only providers whose env vars are
actually set are included in the chain, so a single-provider setup still works unchanged.
`answer.py` forces citations (`[S1]`, `[S2]`, and so on) and instructs the model to say "not
enough information" rather than invent facts.

Observability (`src/observability/`) gives every request a `Trace` with per-stage timing
(ingest, delta, retrieval, LLM, report) written as a JSON file per run under `traces/`, plus
structured JSON logs to stdout correlated by `request_id`. LLM calls record which provider
actually served the request (this matters once there's a fallback chain), the model, token
counts, and an estimated cost.

Eval (`eval/`) has `run_eval.py`, which scores the delta engine against a hand-labeled
ground truth with precision/recall/F1, checks whether BM25 retrieval surfaces the right
chunk for each labeled question (recall@8, no LLM involved), and, if any LLM provider is
configured, scores chat answers on a 50-question labeled set using an LLM-as-judge for
correctness and groundedness. `cost_analysis.py` aggregates real trace files into per-stage
latency percentiles and a cost projection.

## Sample data and provenance

Two real P&ID PDFs were provided. They turned out to be different drawings, not two
revisions of the same document, so following the assignment's own "synthesize if needed"
guidance, a proper Rev A / Rev B pair was generated from one of them
(`scripts/make_samples.py`):

- `rev_A_native.pdf`: unmodified source.
- `rev_B_native.pdf`: the same PDF with 5 deliberate, programmatic edits (redact a region,
  then re-insert text at the same coordinates): a modified note, a removed note, a
  renumbered instrument tag (2 occurrences), a changed pressure value, and a newly added
  note.
- `rev_A_scanned.pdf` and `rev_B_scanned.pdf`: Rev A and Rev B each rasterized to PNG and
  re-embedded with no text layer, to exercise the scanned-PDF/OCR path.
- `ground_truth_delta.json`: the answer key, authored by construction (not inferred after
  the fact) since we made the edits ourselves. Full provenance is in `PROVENANCE.md` next
  to the files.

A second pair, `pair_02_dxf_sample`, is a synthetic DXF revision pair built directly with
`ezdxf` (`scripts/make_dxf_samples.py`), used to prove the DWG/DXF ingestion path end to
end since no real DWG/DXF sample was available.

So the format coverage is native PDF, scanned PDF, and DXF, all proven end to end. Binary
DWG stays a stub, which is the scope cut described below.

## Design decisions and trade-offs

The delta engine is fully deterministic, with no LLM involved. Alignment and classification
use text similarity (`difflib.SequenceMatcher`) and spatial proximity only. This satisfies
the "reproducible structural output" requirement directly and keeps all LLM
non-determinism confined to the chat/answer layer, where it belongs. The cost is that the
delta engine can't use semantic understanding, so it won't recognize a paraphrase as
unchanged. A real system would probably add an LLM classification pass on top of the
deterministic candidate list rather than putting an LLM inside the alignment itself.

Scanned-PDF OCR uses a vision LLM rather than a classic OCR binary like Tesseract, which
wasn't available in this environment. A vision model also recovers coarse layout without a
separate detection step, so one API call gets both text and approximate bounding boxes. The
trade-off is that those bounding boxes are model-estimated, not pixel-precise, so
confidence on scanned elements is set below 1.0 and threaded through to delta results and
citations.

Chat retrieval is BM25 keyword search, not embeddings. P&ID content is dense with exact
codes, tags, and values ("26-PIT-9077", "257 BARG") where lexical match tends to beat
semantic similarity, and it avoids needing a second API or provider just for embeddings. A
production version would likely combine BM25 with embeddings for recall on paraphrased
questions, and the failure table below has concrete evidence for why.

Alignment matching is greedy, not globally optimal. Sorting all candidate pairs by score
and assigning highest-first is simple and fast, but it can force a weak match between two
genuinely unrelated leftover elements instead of reporting them as a separate add and
remove. This shows up in the eval failure table below.

Observability is a homegrown JSON tracer, not OpenTelemetry or Langfuse. For a
single-process take-home this is simpler to read and needs no extra infrastructure. The
trace schema (spans with name, duration, data, error, and a root request_id) maps directly
onto OTel spans if this ever needed to scale into a real service.

## What was cut

Binary `.dwg` conversion needs a proprietary ODA/Autodesk converter to become DXF first,
and that isn't available or redistributable in this environment. The adapter interface,
detection routing, and DXF parsing are all real, as described above. Only the DWG-to-DXF
conversion step itself is out of scope.

Embedding-based retrieval wasn't added. BM25 only, for the reasons in the trade-offs
section, with no embedding provider wired in alongside it.

Delta markup for DXF isn't supported. The markup overlay (`make markup`) only works on PDF
sources, since PyMuPDF's annotation API is PDF-specific. A DXF input raises a clear
`UnsupportedMarkupFormatError` (a visible failure, not a raw traceback or a silent no-op).
Delta computation, the report, chat, and eval all still work fully on DXF documents; only
the visual overlay is PDF-only. Rendering markup for DXF would mean rasterizing the CAD
geometry to an image or PDF first.

The web UI doesn't support multiple concurrent users. The served UI (`make web`) keeps a
single global in-memory session, which is fine for a local demo but not for real concurrent
use. A real deployment would key session state by request or user id instead of a
module-level dict.

## Honest failure table

From `make eval` on the sample pair:

```
precision=0.4  recall=0.8  f1=0.533
TP=4  FP=6  FN=1
```

The one missed change (false negative) is the removed note (Note 8). Its bbox becomes
blank whitespace after redaction, and the aligner has nothing on the B side to *not* match,
so it can get absorbed into a nearby weak match instead of standing alone as "removed".

Most of the spurious changes (false positives) come from the text-editing script itself
splitting one logical line into multiple text runs after redaction. For example, "FROM
26-PIT-9077 IN 3RD" fragments into separate "FROM" and "IN 3RD" runs. This is an artifact
of how `rev_B_native.pdf` was synthesized via redact-and-reinsert, not a fundamental flaw
in the algorithm, but it's exactly the kind of line-segmentation noise a real revision
re-exported from CAD would also produce to some degree.

There's also a duplicate tag change: `26-PIT-9077` to `26-PIT-9099` appears at 2 physical
locations on the sheet. The ground truth counts it once as a semantic change, but the
engine correctly detects it as 2 separate element-level modifications. That's a
labeling-granularity mismatch worth resolving with a "same logical change, multiple
locations" grouping step.

There's corroborating evidence that this is a synthesis artifact rather than an algorithm
flaw: the second sample pair (`pair_02_dxf_sample`, a synthetic DXF built directly rather
than via redact-and-reinsert) scores precision=1.0, recall=1.0, f1=1.0 with the identical
delta engine code.

### Scanned-PDF OCR at extreme document density

Running the full pipeline on `rev_A_scanned.pdf` and `rev_B_scanned.pdf` (the actual
scanned-format sample, a 9192x6498px raster of the same dense sheet, roughly 875 real text
elements) surfaced a genuine scaling limit: a single `complete_vision()` call maxes out at
`VISION_OCR_MAX_TOKENS` (8192 by default) well before enumerating the full page as JSON.
This was originally a worse bug: the truncated JSON failed to parse and was silently
discarded into an empty page, exactly the "bad OCR gets swallowed" failure the assignment
calls out by name as unacceptable.

This got fixed in two layers. First, `_parse_ocr_json()` now salvages every complete
element from a truncated response instead of discarding the page, every truncation logs a
structured warning with the provider, token counts, and elements recovered, and one retry
runs automatically if the first attempt salvages nothing. Second, `_ocr_page_tiled()`
splits the page into a `VISION_OCR_TILE_GRID` grid (3x3 by default, 9 tiles) and OCRs each
tile separately, remapping bboxes back into full-page coordinates. Each tile has far fewer
elements than the whole page, so it completes without truncating almost all the time.

The measured result: recall went from 0 to 180 out of roughly 875 elements (0 to 21%,
single call, varying wildly run to run) up to 609 out of roughly 875 (about 70%,
consistently) with tiling. That's a real, measured improvement, not just a smaller failure
mode. The remaining gap is honest: a few tiles still occasionally truncate on the densest
regions of the sheet, visible via the same warning logs, and OCR bounding boxes are
inherently coarser than native-PDF vector extraction. The scanned-PDF format detection and
ingestion seam was already fully real and end to end, satisfying the acceptance criteria's
"at least two of three formats" requirement. This work made OCR quality on a genuinely
stress-case document good, rather than just non-crashing.

### Eval dataset size

There are 50 hand-labeled Q&A pairs total, 35 for `pair_01` and 15 for `pair_02_dxf_sample`,
in `eval/datasets/`. They cover four question types per pair: paraphrases of each known
delta, static/unchanged-content questions (equipment table values, notes that didn't
change), deliberate refusal cases (asking about facts genuinely absent from the sources, to
check the system doesn't hallucinate), and aggregate/count questions. Every expected fact
and `expected_source_contains` substring was checked against the actual extracted document
text, not guessed.

### Retrieval quality

From `make eval`, BM25 recall@8, no LLM involved: `pair_01` scores recall@8 = 0.414 on the
full 35-question set. An earlier 6-question sample had shown a more optimistic 0.5, which
is exactly why a larger labeled set matters: it was hiding real gaps. `pair_02` scores
recall@8 = 1.0, helped by being a smaller document with less lexical competition between
chunks.

The `pair_01` misses correlate with chat questions the LLM-as-judge later marks incorrect,
confirming that several of those are retrieval failures rather than generation failures.
BM25's lexical matching doesn't surface a chunk for a question that doesn't share
vocabulary with the source text. For example, "note 3" never appears verbatim near the
atmospheric-vent text on the page. This is the strongest argument in this repo for adding
embedding-based retrieval.

One class of miss got diagnosed and fixed live. Equipment-table questions were failing for
the reason described above (label and value split across columns). The fix is described in
the "What's built" section. Verified live against the exact failing query, before and
after: recall@8 went from 0.379 to 0.414, chat correctness from 0.40 to 0.43, and
groundedness from 0.71 to 0.80. The remaining misses are a different, still-open pattern:
"what does note 1 say?" shares almost no vocabulary with the note's actual text, which is
the same underlying BM25 limitation, not something the row-merge fix addresses.

### Cost and latency

From `make cost-report`, using real observed traces, not estimates: the delta-alignment
stage, not the LLM call, is the actual bottleneck, at roughly 7.4 seconds p50 for the O(n
times m) `SequenceMatcher` scoring over about 875x880 candidate element pairs on a single
dense P&ID sheet, versus roughly 2.6 seconds p50 for a full retrieval-plus-LLM chat
round-trip. Cost is negligible, around $0.065 projected per 1,000 chat calls on
`gemini-2.5-flash-lite`. Latency, not cost, is the real scaling risk for larger sheets or
multi-page documents.

## What I'd do next with more time

1. Fix the delta engine's actual bottleneck: replace the O(n times m) candidate scoring
   with a spatial index (bucket by page region) before scoring, informed directly by the
   cost report above.
2. Replace greedy alignment with a proper assignment-optimal matching (for example, the
   Hungarian algorithm) to remove the forced-weak-match failure mode shown above.
3. Add a "same logical change, multiple locations" grouping pass on top of the raw
   element-level delta items.
4. Add embedding-based retrieval alongside BM25, directly motivated by the measured
   recall@8 gap above, not a guess.
5. Implement real binary `.dwg` support (ODA File Converter feeding into the `ezdxf` path
   already built) once a licensed converter is available.
6. Expand the eval set with a real scanned-PDF pair (the current one is synthetic only) and
   more document pairs generally, to reduce variance in the scorecard.
7. Key the web UI's session state by request or user id instead of a single global dict,
   for concurrent-user support.

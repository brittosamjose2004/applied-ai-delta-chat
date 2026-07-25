# Demo walkthrough

## 1. Delta run

```
$ make run
```

```
{"ts": "...", "level": "INFO", "message": "delta pipeline started", "request_id": "...", "pid_a": "PID-A", "pid_b": "PID-B"}
{"ts": "...", "level": "INFO", "message": "delta pipeline completed", "request_id": "...", "total_changes": 10}
Delta: 10 changes
Report (Markdown): data\samples\pair_01_lift_gas_compressor\output\delta_report.md
Report (HTML): data\samples\pair_01_lift_gas_compressor\output\delta_report.html
Report (JSON): data\samples\pair_01_lift_gas_compressor\output\delta_report.json
Trace request_id: 172da60f-d275-4d41-9c3e-5d02e228e2e5
```

All three formats get written on every run. Markdown and HTML are both human-readable
(the assignment's own example is "Markdown/HTML + JSON", so we produce all three literally).
JSON is machine-parseable and it's also what the chat retrieval layer indexes.

Report excerpt (`delta_report.md`):

```
- [modified/note] confidence 0.99: Modified note: "22. DESIGN PRESSURE IN EXTERNAL
  SYSTEM DOWNSTREAM COMPRESSOR 257 BARG." -> "...265 BARG."
- [modified/text] confidence 0.80: Modified text: "OIL CHANGE BY USING TEMPORARY
  ARRANGEMENT WITH HOSES." -> "...PERMANENT ARRANGEMENT WITH DEDICATED PUMP."
```

The trace file (`traces/delta_<request_id>.json`) records per-stage timing: `ingest_a`,
`ingest_b`, `delta`, `report`, each with a duration and stage-specific data like element
counts, change counts, and output paths.

## 2. Grounded chat exchange

```
$ make chat
> What changed with instrument tag 26-PIT-9077?
```

The answer should be a citation-backed statement that the tag was renumbered to
26-PIT-9099, citing the delta-report entry (`[S1]`) and the underlying PID A / PID B
locations. Every claim carries a `[Sn]` citation. The CLI prints the citation list
(source, page, snippet) below the answer, and writes the trace to
`traces/chat_<request_id>.json` with retrieval and LLM stage timing plus token/cost.

## 3. Delta markup overlay (bonus)

```
$ make markup
```

Writes `rev_B_markup.pdf`, a copy of PID B with each delta item drawn as a colored,
labeled highlight box directly on the drawing (green for added, red for removed, blue
for modified). This is the visual artifact a reviewer used to draw by hand before.

## 4. Served UI (bonus)

```
$ make web
```

Opens a small dashboard at `http://127.0.0.1:8000`. There's a form to compute the delta,
which renders the same report as `make run` color-coded by change type, and a chat panel
wired to the same `/api/chat` endpoint the CLI uses underneath.

## 5. Eval scorecard

```
$ make eval
```

```
DELTA ENGINE - precision / recall / F1 vs. labeled ground truth
Pair: pair_01_lift_gas_compressor
  ground truth changes: 5  |  predicted changes: 10
  precision=0.4  recall=0.8  f1=0.533
Pair: pair_02_dxf_sample (synthetic DXF, proves the DWG/DXF adapter end to end)
  precision=1.0  recall=1.0  f1=1.0

RETRIEVAL QUALITY - recall@8 (BM25, no LLM involved, bonus)
Pair pair_01_lift_gas_compressor: recall@8=0.414 (35-question labeled set)
Pair pair_02_dxf_sample: recall@8=1.0 (15-question labeled set)

GROUNDED CHAT - correctness / groundedness (LLM-as-judge)
Pair pair_01_lift_gas_compressor: correctness=0.43  groundedness=0.80
Pair pair_02_dxf_sample: correctness=0.93  groundedness=0.87
```

(50 hand-labeled Q&A pairs total across both pairs. See `eval/datasets/`.)

A full explanation of every failure case is in `README.md` under "Honest failure table",
including how the retrieval recall@8 misses directly explain the chat correctness misses.

## 6. Cost/latency budget analysis (bonus)

```
$ make cost-report
```

Aggregates every real trace file written so far (not estimates) into per-stage latency
percentiles and a cost projection. The key finding: the delta-alignment stage, not the LLM
call, is the actual bottleneck, at roughly 7.4 seconds p50 on a dense single-sheet P&ID.
See README for the full breakdown.

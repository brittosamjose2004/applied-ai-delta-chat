# Demo walkthrough

## 1. Delta run

```
$ make run
```

```
{"ts": "...", "level": "INFO", "message": "delta pipeline started", "request_id": "...", "pid_a": "PID-A", "pid_b": "PID-B"}
{"ts": "...", "level": "INFO", "message": "delta pipeline completed", "request_id": "...", "total_changes": 10}
Delta: 10 changes
Report: data\samples\pair_01_lift_gas_compressor\output\delta_report.md
Trace request_id: 172da60f-d275-4d41-9c3e-5d02e228e2e5
```

Report excerpt (`delta_report.md`):

```
- ✏️ [modified/note] confidence 0.99 — Modified note: "22. DESIGN PRESSURE IN EXTERNAL
  SYSTEM DOWNSTREAM COMPRESSOR 257 BARG." -> "...265 BARG."
- ✏️ [modified/text] confidence 0.80 — Modified text: "OIL CHANGE BY USING TEMPORARY
  ARRANGEMENT WITH HOSES." -> "...PERMANENT ARRANGEMENT WITH DEDICATED PUMP."
```

Trace file (`traces/delta_<request_id>.json`) has per-stage timing: `ingest_a`,
`ingest_b`, `delta`, `report` — each with duration_ms and stage-specific data
(element counts, change counts, output paths).

## 2. Grounded chat exchange

```
$ make chat
> What changed with instrument tag 26-PIT-9077?
```

Expected shape of the answer: a citation-backed statement that the tag was renumbered to
26-PIT-9099, citing the delta-report entry (`[S1]`) and the underlying PID A/PID B
locations. Every claim carries a `[Sn]` citation; the CLI prints the citation list
(source, page, snippet) below the answer, plus the trace `request_id` written to
`traces/chat_<request_id>.json` with retrieval + LLM stage timing and token/cost.

## 3. Delta markup overlay (bonus)

```
$ make markup
```

Writes `rev_B_markup.pdf` — a copy of PID B with each delta item drawn as a colored,
labeled highlight box directly on the drawing (green=added, red=removed, blue=modified),
the visual artifact a reviewer used to draw by hand.

## 4. Served UI (bonus)

```
$ make web
```

Opens a small dashboard at `http://127.0.0.1:8000` — a form to compute the delta (renders
the same report as `make run`, color-coded by change type) and a chat panel wired to the
same `/api/chat` endpoint the CLI uses under the hood.

## 5. Eval scorecard

```
$ make eval
```

```
DELTA ENGINE - precision / recall / F1 vs. labeled ground truth
Pair: pair_01_lift_gas_compressor
  ground truth changes: 5  |  predicted changes: 10
  precision=0.4  recall=0.8  f1=0.533
Pair: pair_02_dxf_sample (synthetic DXF, proves the DWG/DXF adapter end-to-end)
  precision=1.0  recall=1.0  f1=1.0

RETRIEVAL QUALITY - recall@8 (BM25, no LLM involved, bonus)
Pair pair_01_lift_gas_compressor: recall@8=0.5 (3/6)

GROUNDED CHAT - correctness / groundedness (LLM-as-judge)
Pair pair_01_lift_gas_compressor: correctness=3/6  groundedness=4/6
```

Full explanation of every failure case is in `README.md` under "Honest failure table" —
including how the retrieval recall@8 misses directly explain the chat correctness misses.

## 6. Cost/latency budget analysis (bonus)

```
$ make cost-report
```

Aggregates every real trace file written so far (not estimates) into per-stage latency
percentiles and a cost projection. Key finding: the delta-alignment stage, not the LLM
call, is the actual bottleneck (~7.4s p50 on a dense single-sheet P&ID) — see README.

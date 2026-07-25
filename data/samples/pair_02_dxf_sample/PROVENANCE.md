# Sample pair 02 — synthetic DXF

No real DWG/DXF sample was available, so this pair is fully synthetic: built directly with `ezdxf` (scripts/make_dxf_samples.py) as a small set of TEXT entities representing instrument tags and notes, edited between revisions with the same 5-change pattern (1 modified tag, 1 removed, 1 modified note, 1 modified text, 1 added note) used in the PDF sample pair. Exists to prove the DXF ingestion adapter (src/ingest/dwg.py) end-to-end, not to represent a real engineering drawing.

from pathlib import Path

import pytest

from src.ingest.dwg import DwgAdapter

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "samples" / "pair_02_dxf_sample"


def test_can_handle_routes_dwg_and_dxf():
    a = DwgAdapter()
    assert a.can_handle("drawing.dwg")
    assert a.can_handle("drawing.dxf")
    assert not a.can_handle("drawing.pdf")


def test_dwg_binary_is_a_documented_stub():
    a = DwgAdapter()
    with pytest.raises(NotImplementedError):
        a.ingest("PID-X", "drawing.dwg")


@pytest.mark.skipif(not SAMPLE_DIR.exists(), reason="run scripts/make_dxf_samples.py first")
def test_dxf_ingestion_extracts_real_text_and_bbox():
    a = DwgAdapter()
    doc = a.ingest("PID-A", str(SAMPLE_DIR / "rev_A.dxf"))
    assert doc.element_count() == 5
    texts = [el.text for _, el in doc.all_elements()]
    assert any("26-PIT-4001" in t for t in texts)
    _, el = next(doc.all_elements())
    assert el.bbox.x1 > el.bbox.x0
    assert el.bbox.y1 > el.bbox.y0

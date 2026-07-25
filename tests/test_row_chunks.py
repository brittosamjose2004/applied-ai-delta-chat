import uuid

from src.canonical.model import BBox, CanonicalDocument, Page, SourceFormat, TextElement
from src.chat.index import build_index


def _doc(pid, texts_with_bbox):
    elements = [
        TextElement(id=str(uuid.uuid4()), text=t, bbox=BBox(*b), element_type="text")
        for t, b in texts_with_bbox
    ]
    page = Page(index=0, width=1200, height=1200, elements=elements)
    return CanonicalDocument(pid=pid, source_format=SourceFormat.PDF_NATIVE, source_path="x", pages=[page])


def test_adjacent_label_and_value_are_merged_into_one_row_chunk():
    # Regression: a table label ("DUTY") and its value ("776") sit in
    # separate columns of the same row with a small x-gap. Before the fix,
    # a query sharing vocabulary only with the label never retrieved the
    # value, since they were indexed as two unrelated chunks.
    doc = _doc("A", [
        ("DUTY", (10, 100, 40, 110)),
        ("776", (50, 100, 70, 110)),  # 10pt gap from label's x1=40 -> should merge
    ])
    index = build_index(doc, doc, [])
    merged = [c for c in index.chunks if c.id.startswith("row-")]
    assert any("DUTY" in c.text and "776" in c.text for c in merged)


def test_distant_same_row_content_is_not_merged():
    # Regression: naive y-only grouping pulled in unrelated content from
    # elsewhere in the same horizontal band on a wide sheet.
    doc = _doc("A", [
        ("DUTY", (10, 100, 40, 110)),
        ("776", (50, 100, 70, 110)),
        ("UNRELATED FAR AWAY NOTE", (900, 100, 950, 110)),  # far x-gap -> must not merge
    ])
    index = build_index(doc, doc, [])
    merged_texts = [c.text for c in index.chunks if c.id.startswith("row-")]
    assert not any("UNRELATED" in t and "DUTY" in t for t in merged_texts)


def test_singleton_elements_produce_no_row_chunk():
    doc = _doc("A", [("LONE ELEMENT", (10, 100, 40, 110))])
    index = build_index(doc, doc, [])
    assert not any(c.id.startswith("row-") for c in index.chunks)

import uuid

from src.canonical.model import BBox, CanonicalDocument, Page, SourceFormat, TextElement
from src.delta.engine import build_delta


def _doc(pid, texts_with_bbox):
    elements = [
        TextElement(id=str(uuid.uuid4()), text=t, bbox=BBox(*b), element_type="text")
        for t, b in texts_with_bbox
    ]
    page = Page(index=0, width=1000, height=1000, elements=elements)
    return CanonicalDocument(pid=pid, source_format=SourceFormat.PDF_NATIVE, source_path="x", pages=[page])


def test_unchanged_text_produces_no_delta():
    doc_a = _doc("A", [("HELLO WORLD", (0, 0, 50, 10))])
    doc_b = _doc("B", [("HELLO WORLD", (0, 0, 50, 10))])
    assert build_delta(doc_a, doc_b) == []


def test_added_and_removed_detected():
    # Placed far apart (in both text and position) so the aligner doesn't
    # weakly match them to each other as a "modified" pair instead.
    doc_a = _doc("A", [("KEEP ME", (0, 0, 50, 10)), ("REMOVE ME ENTIRELY", (0, 20, 50, 30))])
    doc_b = _doc("B", [("KEEP ME", (0, 0, 50, 10)), ("BRAND NEW UNRELATED NOTE", (500, 900, 600, 950))])
    items = build_delta(doc_a, doc_b)
    types = sorted((i.change_type, i.before, i.after) for i in items)
    assert ("removed", "REMOVE ME ENTIRELY", None) in types
    assert ("added", None, "BRAND NEW UNRELATED NOTE") in types


def test_modified_same_position_detected():
    doc_a = _doc("A", [("PRESSURE 257 BARG", (0, 0, 80, 10))])
    doc_b = _doc("B", [("PRESSURE 265 BARG", (0, 0, 80, 10))])
    items = build_delta(doc_a, doc_b)
    assert len(items) == 1
    assert items[0].change_type == "modified"
    assert items[0].before == "PRESSURE 257 BARG"
    assert items[0].after == "PRESSURE 265 BARG"


def test_delta_is_deterministic():
    doc_a = _doc("A", [("A ITEM", (0, 0, 50, 10)), ("B ITEM", (0, 20, 50, 30))])
    doc_b = _doc("B", [("A ITEM CHANGED", (0, 0, 50, 10)), ("C ITEM", (0, 40, 50, 50))])
    run1 = [(i.change_type, i.before, i.after) for i in build_delta(doc_a, doc_b)]
    run2 = [(i.change_type, i.before, i.after) for i in build_delta(doc_a, doc_b)]
    assert run1 == run2

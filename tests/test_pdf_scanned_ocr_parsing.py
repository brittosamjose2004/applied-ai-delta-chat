from src.ingest.pdf_scanned import _parse_ocr_json


def test_valid_complete_json_parses_normally():
    raw = '[{"text": "A", "bbox": [1, 2, 3, 4], "confidence": 0.9}]'
    items, was_truncated = _parse_ocr_json(raw)
    assert len(items) == 1
    assert was_truncated is False


def test_truncated_json_salvages_complete_elements():
    # Regression: a response cut off mid-object (hit max_tokens on a dense
    # page) used to be silently discarded into an empty page instead of
    # salvaging the elements that did complete.
    raw = (
        '[\n{"text": "A", "bbox": [1,2,3,4], "confidence": 0.9},\n'
        '{"text": "B", "bbox": [1,2,3,4], "confidence": 0.9},\n'
        '{"text": "C", "bbox": [1,2'
    )
    items, was_truncated = _parse_ocr_json(raw)
    assert was_truncated is True
    assert len(items) == 2
    assert items[0]["text"] == "A"
    assert items[1]["text"] == "B"


def test_truncated_before_any_complete_element_returns_empty_but_flagged():
    raw = '[\n{"text": "A", "bbox": [1,2'
    items, was_truncated = _parse_ocr_json(raw)
    assert was_truncated is True
    assert items == []


def test_non_json_prose_response_is_flagged_not_crashed():
    raw = "I'm sorry, I cannot process this image."
    items, was_truncated = _parse_ocr_json(raw)
    assert was_truncated is True
    assert items == []

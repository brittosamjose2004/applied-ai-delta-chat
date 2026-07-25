"""Format-agnostic canonical representation.

Every ingestion adapter (native PDF, scanned PDF, DWG, ...) normalizes its
source into this model. Nothing downstream (delta engine, chat/retrieval)
needs to know what format a document originally was.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SourceFormat(str, Enum):
    PDF_NATIVE = "pdf_native"
    PDF_SCANNED = "pdf_scanned"
    DWG = "dwg"


@dataclass
class BBox:
    """Bounding box in page/sheet coordinate space (points for PDF, model units for DWG)."""
    x0: float
    y0: float
    x1: float
    y1: float

    def as_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]

    def iou(self, other: "BBox") -> float:
        ix0, iy0 = max(self.x0, other.x0), max(self.y0, other.y0)
        ix1, iy1 = min(self.x1, other.x1), min(self.y1, other.y1)
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        inter = (ix1 - ix0) * (iy1 - iy0)
        a1 = (self.x1 - self.x0) * (self.y1 - self.y0)
        a2 = (other.x1 - other.x0) * (other.y1 - other.y0)
        union = a1 + a2 - inter
        return inter / union if union > 0 else 0.0

    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


@dataclass
class TextElement:
    """One atomic piece of content on a page/sheet: a text run, a tag, a note,
    a dimension string, a table cell, etc. This is the unit the delta engine
    aligns and diffs."""
    id: str
    text: str
    bbox: BBox
    element_type: str = "text"  # text | dimension | note | tag | table_cell | geometry
    confidence: float = 1.0     # extraction confidence (OCR/vision may be < 1.0)
    extra: dict = field(default_factory=dict)


@dataclass
class Page:
    index: int  # 0-based page/sheet number
    width: float
    height: float
    elements: list[TextElement] = field(default_factory=list)
    label: str | None = None  # e.g. "Sheet 3", revision label if detected


@dataclass
class CanonicalDocument:
    """The normalized representation of one document revision, regardless of
    source format."""
    pid: str
    source_format: SourceFormat
    source_path: str
    pages: list[Page] = field(default_factory=list)
    revision_label: str | None = None
    metadata: dict = field(default_factory=dict)

    def all_elements(self):
        for page in self.pages:
            for el in page.elements:
                yield page, el

    def element_count(self) -> int:
        return sum(len(p.elements) for p in self.pages)

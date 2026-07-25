"""Native (born-digital) PDF adapter. Extracts the real text/vector layer
directly - no OCR needed. Groups words into lines and classifies each line
into a coarse element_type using cheap regex heuristics (good enough for a
P&ID sheet; a real system would use layout/vendor conventions)."""
from __future__ import annotations

import re
import uuid

import fitz  # PyMuPDF

from src.canonical.model import BBox, CanonicalDocument, Page, SourceFormat, TextElement
from src.ingest.base import FormatAdapter

TAG_RE = re.compile(r"\b\d{2}-[A-Z]{2,5}-\d{3,5}\b")
NOTE_RE = re.compile(r"^\s*\d{1,3}\.\s")
DIM_RE = re.compile(r"\b\d+(\.\d+)?\s*(BARG|MM|IN|mm|in|\"|MMSCFD|xD)\b", re.IGNORECASE)


def classify(text: str) -> str:
    if NOTE_RE.match(text):
        return "note"
    if TAG_RE.search(text) and len(text) < 40:
        return "tag"
    if DIM_RE.search(text):
        return "dimension"
    return "text"


class NativePdfAdapter(FormatAdapter):
    format_name = "pdf_native"

    def can_handle(self, path: str) -> bool:
        if not path.lower().endswith(".pdf"):
            return False
        try:
            doc = fitz.open(path)
            # Native = has a meaningful extractable text layer on at least one page.
            has_text = any(len(page.get_text().strip()) > 20 for page in doc)
            doc.close()
            return has_text
        except Exception:
            return False

    def ingest(self, pid: str, path: str) -> CanonicalDocument:
        doc = fitz.open(path)
        pages: list[Page] = []
        for pindex, pdf_page in enumerate(doc):
            elements: list[TextElement] = []
            d = pdf_page.get_text("dict")
            for block in d["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block["lines"]:
                    text = "".join(span["text"] for span in line["spans"]).strip()
                    if not text:
                        continue
                    x0, y0, x1, y1 = line["bbox"]
                    elements.append(TextElement(
                        id=str(uuid.uuid4()),
                        text=text,
                        bbox=BBox(x0, y0, x1, y1),
                        element_type=classify(text),
                        confidence=1.0,
                    ))
            pages.append(Page(
                index=pindex,
                width=pdf_page.rect.width,
                height=pdf_page.rect.height,
                elements=elements,
            ))
        doc.close()
        return CanonicalDocument(
            pid=pid,
            source_format=SourceFormat.PDF_NATIVE,
            source_path=path,
            pages=pages,
            metadata={"page_count": len(pages)},
        )

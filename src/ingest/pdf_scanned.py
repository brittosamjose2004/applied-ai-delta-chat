"""Scanned/raster PDF adapter. No reliable text layer, so recovery uses a
vision LLM instead of a classic OCR binary (this environment has no
Tesseract install, and a vision model additionally recovers coarse layout
without a separate detector) — see README for the trade-off discussion.

The model is asked to return line-level text with an approximate bounding
box (normalized 0-1000, top-left origin) and a self-reported confidence.
Vision-based OCR bboxes are inherently approximate; confidence is stored on
every element so the delta engine and chat citations can reflect that.
"""
from __future__ import annotations

import base64
import json
import os
import uuid

import fitz  # PyMuPDF

from src.canonical.model import BBox, CanonicalDocument, Page, SourceFormat, TextElement
from src.ingest.base import FormatAdapter
from src.ingest.pdf_native import classify

OCR_PROMPT = """You are performing OCR on a scanned engineering drawing (P&ID) page image.
Return ONLY a JSON array of line-level text elements you can read, each as:
{"text": "...", "bbox": [x0, y0, x1, y1], "confidence": 0.0-1.0}
bbox is normalized to a 0-1000 x 0-1000 grid regardless of image size, top-left origin,
[x0,y0] = top-left corner, [x1,y1] = bottom-right corner of the text line.
Include instrument tags, notes, dimensions, and labels. Skip pure graphics/lines with no text.
Return strictly valid JSON, no prose, no markdown fences."""


class ScannedPdfAdapter(FormatAdapter):
    format_name = "pdf_scanned"

    def can_handle(self, path: str) -> bool:
        if not path.lower().endswith(".pdf"):
            return False
        try:
            doc = fitz.open(path)
            has_text = any(len(page.get_text().strip()) > 20 for page in doc)
            doc.close()
            return not has_text  # raster-only: no usable text layer
        except Exception:
            return False

    def ingest(self, pid: str, path: str) -> CanonicalDocument:
        doc = fitz.open(path)
        pages: list[Page] = []
        for pindex, pdf_page in enumerate(doc):
            pix = pdf_page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            page_w, page_h = pdf_page.rect.width, pdf_page.rect.height

            elements = self._ocr_page(img_bytes, page_w, page_h)
            pages.append(Page(index=pindex, width=page_w, height=page_h, elements=elements))
        doc.close()
        return CanonicalDocument(
            pid=pid,
            source_format=SourceFormat.PDF_SCANNED,
            source_path=path,
            pages=pages,
            metadata={"page_count": len(pages), "ocr_method": "vision_llm"},
        )

    def _ocr_page(self, img_bytes: bytes, page_w: float, page_h: float) -> list[TextElement]:
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        model = os.environ.get("VISION_OCR_MODEL", "claude-sonnet-4-5")
        b64 = base64.b64encode(img_bytes).decode()

        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": OCR_PROMPT},
                ],
            }],
        )
        raw = resp.content[0].text.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            items = []

        elements: list[TextElement] = []
        for item in items:
            text = (item.get("text") or "").strip()
            bbox = item.get("bbox")
            if not text or not bbox or len(bbox) != 4:
                continue
            x0, y0, x1, y1 = bbox
            # denormalize 0-1000 grid -> page point coordinates
            px0, py0 = x0 / 1000 * page_w, y0 / 1000 * page_h
            px1, py1 = x1 / 1000 * page_w, y1 / 1000 * page_h
            elements.append(TextElement(
                id=str(uuid.uuid4()),
                text=text,
                bbox=BBox(px0, py0, px1, py1),
                element_type=classify(text),
                confidence=float(item.get("confidence", 0.7)),
                extra={"ocr": "vision_llm"},
            ))
        return elements

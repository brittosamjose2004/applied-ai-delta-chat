"""Scanned/raster PDF adapter. No reliable text layer, so recovery uses a
vision LLM instead of a classic OCR binary (this environment has no
Tesseract install, and a vision model additionally recovers coarse layout
without a separate detector) — see README for the trade-off discussion.

OCR goes through the same provider-agnostic LlmClient.complete_vision()
used by chat, via default_client()'s fallback chain — not hardcoded to one
provider. A provider without vision support (e.g. the NIM model configured
here) raises NotImplementedError, which FallbackLlmClient treats like any
other failure and skips to the next provider.

The model is asked to return line-level text with an approximate bounding
box (normalized 0-1000, top-left origin) and a self-reported confidence.
Vision-based OCR bboxes are inherently approximate; confidence is stored on
every element so the delta engine and chat citations can reflect that.
"""
from __future__ import annotations

import json
import os
import uuid

import fitz  # PyMuPDF

from src.canonical.model import BBox, CanonicalDocument, Page, SourceFormat, TextElement
from src.ingest.base import FormatAdapter
from src.ingest.pdf_native import classify
from src.observability.logging import get_logger, log

logger = get_logger()

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
            page_w, page_h = pdf_page.rect.width, pdf_page.rect.height

            elements = self._ocr_page_tiled(pix, page_w, page_h)
            pages.append(Page(index=pindex, width=page_w, height=page_h, elements=elements))
        doc.close()
        return CanonicalDocument(
            pid=pid,
            source_format=SourceFormat.PDF_SCANNED,
            source_path=path,
            pages=pages,
            metadata={"page_count": len(pages), "ocr_method": "vision_llm"},
        )

    def _ocr_page_tiled(self, pix, page_w: float, page_h: float) -> list[TextElement]:
        """Split the page into a grid of tiles and OCR each separately, then
        merge with bbox offsets. A dense P&ID sheet (~875 text elements)
        blows past a single call's token budget (see git history / README —
        this used to just silently drop most of the page); each tile has
        far fewer elements, so it completes without truncating."""
        from PIL import Image
        import io

        cols, rows = _tile_grid()
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        W, H = img.size

        elements: list[TextElement] = []
        for row in range(rows):
            for col in range(cols):
                x0, x1 = W * col // cols, W * (col + 1) // cols
                y0, y1 = H * row // rows, H * (row + 1) // rows
                tile_img = img.crop((x0, y0, x1, y1))
                buf = io.BytesIO()
                tile_img.save(buf, format="PNG")

                tile_w_pts = (x1 - x0) / W * page_w
                tile_h_pts = (y1 - y0) / H * page_h
                offset_x_pts = x0 / W * page_w
                offset_y_pts = y0 / H * page_h

                tile_elements = self._ocr_image(buf.getvalue(), tile_w_pts, tile_h_pts)
                for el in tile_elements:
                    el.bbox.x0 += offset_x_pts
                    el.bbox.x1 += offset_x_pts
                    el.bbox.y0 += offset_y_pts
                    el.bbox.y1 += offset_y_pts
                elements.extend(tile_elements)
        return elements

    def _ocr_image(self, img_bytes: bytes, region_w: float, region_h: float) -> list[TextElement]:
        """OCR a single image (a full page, or one tile of one) and return
        elements with bbox in that image's own point-space (caller offsets
        into page space for tiles)."""
        from src.chat.llm import default_client

        max_tokens = int(os.environ.get("VISION_OCR_MAX_TOKENS", 8192))
        client = default_client()

        items: list = []
        was_truncated = False
        last_output_tokens = 0
        last_provider = "unknown"
        # One retry if the first attempt salvaged nothing at all — sampling
        # variance on where a dense region gets cut off means a second
        # attempt sometimes clears a truncation point earlier.
        for attempt in range(2):
            resp = client.complete_vision(img_bytes, OCR_PROMPT, max_tokens=max_tokens)
            raw = resp.text.strip()
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            items, was_truncated = _parse_ocr_json(raw)
            last_output_tokens, last_provider = resp.output_tokens, resp.provider
            if items:
                break

        if was_truncated:
            # Bad/incomplete OCR is exactly the failure category the spec calls
            # out by name — surface it loudly, don't silently return an empty
            # region. An extremely dense tile can still exceed max_tokens;
            # salvaging the complete elements we did get beats discarding
            # everything.
            log(logger, "warning",
                "vision OCR response was truncated (hit max_tokens); salvaged partial results",
                provider=last_provider, output_tokens=last_output_tokens,
                max_tokens=max_tokens, elements_recovered=len(items))

        elements: list[TextElement] = []
        for item in items:
            text = (item.get("text") or "").strip()
            bbox = item.get("bbox")
            if not text or not bbox or len(bbox) != 4:
                continue
            x0, y0, x1, y1 = bbox
            # denormalize 0-1000 grid -> this image's point coordinates
            px0, py0 = x0 / 1000 * region_w, y0 / 1000 * region_h
            px1, py1 = x1 / 1000 * region_w, y1 / 1000 * region_h
            elements.append(TextElement(
                id=str(uuid.uuid4()),
                text=text,
                bbox=BBox(px0, py0, px1, py1),
                element_type=classify(text),
                confidence=float(item.get("confidence", 0.7)),
                extra={"ocr": "vision_llm"},
            ))
        return elements


def _tile_grid() -> tuple[int, int]:
    """(cols, rows) from VISION_OCR_TILE_GRID, e.g. '3x3'. Default 3x3: a
    dense full-sheet P&ID (~875 elements) averages ~100/tile, comfortably
    under an 8192-token budget per tile. '1x1' disables tiling."""
    raw = os.environ.get("VISION_OCR_TILE_GRID", "3x3").lower()
    cols_s, _, rows_s = raw.partition("x")
    try:
        cols, rows = max(1, int(cols_s)), max(1, int(rows_s))
    except ValueError:
        cols, rows = 3, 3
    return cols, rows


def _parse_ocr_json(raw: str) -> tuple[list, bool]:
    """Parse the OCR model's JSON array; if the response was cut off mid-array
    (hit max_tokens on a dense page), salvage every complete element instead
    of discarding the whole page. Returns (items, was_truncated)."""
    try:
        return json.loads(raw), False
    except json.JSONDecodeError:
        pass

    last_close = raw.rfind("}")
    if last_close == -1 or not raw.lstrip().startswith("["):
        return [], True
    candidate = raw[:last_close + 1].rstrip()
    if candidate.endswith(","):
        candidate = candidate[:-1]
    candidate += "]"
    try:
        return json.loads(candidate), True
    except json.JSONDecodeError:
        return [], True

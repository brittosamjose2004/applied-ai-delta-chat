"""DWG/DXF adapter.

DXF (the open, documented sibling of the proprietary binary DWG format) is
parsed for real via `ezdxf`: TEXT/MTEXT/DIMENSION entities become
TextElements with their true rendered bounding box (via `ezdxf.bbox`).

True binary .dwg still needs a proprietary converter (ODA File Converter or
similar) to become DXF first — that conversion step isn't implemented here
(no such binary is redistributable/available in this environment), so
`.dwg` inputs raise a clear NotImplementedError while `.dxf` inputs are
fully ingested through the same adapter interface as every other format.
"""
from __future__ import annotations

import uuid

from src.canonical.model import BBox, CanonicalDocument, Page, SourceFormat, TextElement
from src.ingest.base import FormatAdapter
from src.ingest.pdf_native import classify

TEXT_ENTITY_TYPES = {"TEXT", "MTEXT", "DIMENSION", "ATTRIB", "ATTDEF"}


class DwgAdapter(FormatAdapter):
    format_name = "dwg"

    def can_handle(self, path: str) -> bool:
        return path.lower().endswith((".dwg", ".dxf"))

    def ingest(self, pid: str, path: str) -> CanonicalDocument:
        if path.lower().endswith(".dwg"):
            raise NotImplementedError(
                "Binary .dwg ingestion needs a proprietary DWG->DXF conversion "
                "step (e.g. the ODA File Converter), not available in this "
                "environment. Convert to .dxf first — that path is fully "
                "implemented below via ezdxf."
            )
        return self._ingest_dxf(pid, path)

    def _ingest_dxf(self, pid: str, path: str) -> CanonicalDocument:
        import ezdxf
        from ezdxf import bbox as ezdxf_bbox

        doc = ezdxf.readfile(path)
        msp = doc.modelspace()

        elements: list[TextElement] = []
        for entity in msp:
            if entity.dxftype() not in TEXT_ENTITY_TYPES:
                continue
            text = _entity_text(entity)
            if not text.strip():
                continue

            box = ezdxf_bbox.extents([entity], fast=True)
            if box.has_data:
                x0, y0 = box.extmin.x, box.extmin.y
                x1, y1 = box.extmax.x, box.extmax.y
            else:
                # fall back to a small box around the insertion point
                ip = getattr(entity.dxf, "insert", None)
                if ip is None:
                    continue
                x0, y0 = ip.x, ip.y
                x1, y1 = ip.x + max(len(text) * 2.0, 2.0), ip.y + 3.0

            elements.append(TextElement(
                id=str(uuid.uuid4()),
                text=text,
                bbox=BBox(x0, y0, x1, y1),
                element_type=classify(text),
                confidence=1.0,
                extra={"dxf_layer": entity.dxf.layer, "dxf_type": entity.dxftype()},
            ))

        extents = ezdxf_bbox.extents(msp, fast=True)
        width = (extents.extmax.x - extents.extmin.x) if extents.has_data else 1000.0
        height = (extents.extmax.y - extents.extmin.y) if extents.has_data else 1000.0

        page = Page(index=0, width=width, height=height, elements=elements)
        return CanonicalDocument(
            pid=pid,
            source_format=SourceFormat.DWG,
            source_path=path,
            pages=[page],
            metadata={"page_count": 1, "entity_count": len(elements), "dxf_version": doc.dxfversion},
        )


def _entity_text(entity) -> str:
    dxftype = entity.dxftype()
    if dxftype == "TEXT":
        return entity.dxf.text
    if dxftype == "MTEXT":
        return entity.plain_text()
    if dxftype == "DIMENSION":
        return entity.dxf.text or entity.get_measurement_text() if hasattr(entity, "get_measurement_text") else (entity.dxf.text or "")
    if dxftype in ("ATTRIB", "ATTDEF"):
        return entity.dxf.text
    return ""

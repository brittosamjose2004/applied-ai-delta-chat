from src.ingest.base import FormatAdapter, detect_and_ingest
from src.ingest.dwg import DwgAdapter
from src.ingest.pdf_native import NativePdfAdapter
from src.ingest.pdf_scanned import ScannedPdfAdapter


def default_adapters() -> list[FormatAdapter]:
    # Order matters: native-PDF detector checks for a text layer first;
    # scanned-PDF detector matches only when that layer is absent.
    return [NativePdfAdapter(), ScannedPdfAdapter(), DwgAdapter()]


def ingest_pid(pid: str, path: str):
    return detect_and_ingest(pid, path, default_adapters())

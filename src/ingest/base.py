"""FormatAdapter interface. Every ingestion format plugs in behind this one
seam and returns a CanonicalDocument. The delta engine and chat layer never
import format-specific code directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.canonical.model import CanonicalDocument


class FormatAdapter(ABC):
    """One adapter per source format. `can_handle` does cheap format
    detection (magic bytes / extension); `ingest` does the real work."""

    format_name: str

    @abstractmethod
    def can_handle(self, path: str) -> bool:
        ...

    @abstractmethod
    def ingest(self, pid: str, path: str) -> CanonicalDocument:
        ...


class UnsupportedFormatError(RuntimeError):
    pass


def detect_and_ingest(pid: str, path: str, adapters: list[FormatAdapter]) -> CanonicalDocument:
    """Resolve a PID's bytes to a CanonicalDocument by trying each registered
    adapter's detector in order. This is the single seam a 4th format plugs
    into: implement FormatAdapter, add it to the registry, done."""
    for adapter in adapters:
        if adapter.can_handle(path):
            return adapter.ingest(pid, path)
    raise UnsupportedFormatError(f"No adapter could handle: {path}")

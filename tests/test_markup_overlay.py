import pytest

from src.markup.overlay import UnsupportedMarkupFormatError, render_markup


def test_non_pdf_source_raises_clear_error_not_a_traceback():
    with pytest.raises(UnsupportedMarkupFormatError):
        render_markup("drawing.dxf", [], "out.pdf")

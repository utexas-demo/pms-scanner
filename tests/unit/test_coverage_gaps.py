"""Targeted coverage test for scanner/pdf_processor.py.

(The 003-era batch/uploader coverage tests were removed with the legacy
shims in T057; per-env equivalents live in test_batch_per_machine.py,
test_uploader_per_env.py, and the integration suites.)
"""
import os
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_pdf_processor_parses_osd_string_output(tmp_path: Path):
    """pytesseract returning a string (not dict) → _parse_osd_string path."""
    page = MagicMock()
    page.rotation = 0
    pixmap = MagicMock()
    pixmap.width = 10
    pixmap.height = 10
    pixmap.samples = b"\x80" * 300
    page.get_pixmap.return_value = pixmap

    doc = MagicMock()
    doc.__len__.return_value = 1
    doc.__enter__.return_value = doc
    doc.__exit__.return_value = False
    doc.load_page.return_value = page

    osd_string = (
        "Page number: 0\n"
        "Orientation in degrees: 90\n"
        "Rotate: 90\n"
        "Orientation confidence: 4.50\n"
    )

    with patch.dict(os.environ, {}, clear=False):
        with patch("pdf_processor.fitz.open", return_value=doc):
            with patch("pdf_processor.Image.frombytes") as mock_frombytes:
                mock_frombytes.return_value = MagicMock()
                with patch(
                    "pdf_processor.pytesseract.image_to_osd",
                    return_value=osd_string,
                ):
                    from pdf_processor import process_pdf

                    result = process_pdf(tmp_path / "test.pdf")

    _page_num, _img, uncertain, rotation = result[0]
    assert rotation == 90
    assert uncertain is False

"""Unit tests for scanner/pdf_processor.py — T012."""
import os
from unittest.mock import MagicMock, patch


def _make_mock_page(rotation: int = 0, width: int = 100, height: int = 100):
    """Return a MagicMock resembling a fitz.Page."""
    page = MagicMock()
    page.rotation = rotation
    pixmap = MagicMock()
    # pil_tobytes returns raw bytes; we'll patch PIL.Image.frombytes to return
    # a real small image in tests that need it.
    pixmap.pil_tobytes.return_value = b"\xff\xd8\xff"  # fake JPEG bytes
    pixmap.width = width
    pixmap.height = height
    pixmap.samples = b"\x80" * (width * height * 3)
    pixmap.n = 3
    page.get_pixmap.return_value = pixmap
    return page


def _make_mock_doc(pages):
    """Return a MagicMock resembling a fitz.Document."""
    doc = MagicMock()
    doc.__len__.return_value = len(pages)
    doc.__iter__.return_value = iter(pages)
    doc.__enter__.return_value = doc
    doc.__exit__.return_value = False
    doc.load_page.side_effect = lambda i: pages[i]
    return doc


def test_process_pdf_page_count(tmp_path):
    """process_pdf returns one entry per page."""
    pages = [_make_mock_page(rotation=0) for _ in range(3)]
    mock_doc = _make_mock_doc(pages)

    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}):
        with patch("pdf_processor.fitz.open", return_value=mock_doc):
            with patch("pdf_processor.Image.frombytes") as mock_frombytes:
                mock_frombytes.return_value = MagicMock()
                from pdf_processor import process_pdf
                result = process_pdf(tmp_path / "test.pdf")

    assert len(result) == 3


def test_process_pdf_rotation_applied_when_page_rotated(tmp_path):
    """Page with rotation=90 triggers correction; rotation_applied is non-zero."""
    pages = [_make_mock_page(rotation=90)]
    mock_doc = _make_mock_doc(pages)

    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}):
        with patch("pdf_processor.fitz.open", return_value=mock_doc):
            with patch("pdf_processor.Image.frombytes") as mock_frombytes:
                mock_frombytes.return_value = MagicMock()
                from pdf_processor import process_pdf
                result = process_pdf(tmp_path / "test.pdf")

    page_num, pil_image, orientation_uncertain, rotation_applied = result[0]
    assert rotation_applied == 90


def test_process_pdf_no_rotation_when_upright(tmp_path):
    """Page with rotation=0 and OSD confident upright → rotation_applied=0."""
    pages = [_make_mock_page(rotation=0)]
    mock_doc = _make_mock_doc(pages)
    osd_result = {"rotate": 0, "orientation_conf": 5.0}

    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}):
        with patch("pdf_processor.fitz.open", return_value=mock_doc):
            with patch("pdf_processor.Image.frombytes") as mock_frombytes:
                mock_frombytes.return_value = MagicMock()
                with patch("pdf_processor.pytesseract.image_to_osd", return_value=osd_result):
                    from pdf_processor import process_pdf
                    result = process_pdf(tmp_path / "test.pdf")

    page_num, pil_image, orientation_uncertain, rotation_applied = result[0]
    assert rotation_applied == 0


def test_process_pdf_pytesseract_fallback_called_when_pdf_rotation_zero(tmp_path):
    """When PDF metadata rotation=0, pytesseract OSD is called as tier-2."""
    pages = [_make_mock_page(rotation=0)]
    mock_doc = _make_mock_doc(pages)
    osd_result = {"rotate": 0, "orientation_conf": 5.0}

    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}):
        with patch("pdf_processor.fitz.open", return_value=mock_doc):
            with patch("pdf_processor.Image.frombytes") as mock_frombytes:
                mock_frombytes.return_value = MagicMock()
                with patch(
                    "pdf_processor.pytesseract.image_to_osd",
                    return_value=osd_result,
                ) as mock_osd:
                    from pdf_processor import process_pdf

                    process_pdf(tmp_path / "test.pdf")

    mock_osd.assert_called_once()


def test_process_pdf_pytesseract_not_called_when_rotation_nonzero(tmp_path):
    """When PDF metadata rotation≠0, pytesseract OSD is NOT called (tier-1 sufficient)."""
    pages = [_make_mock_page(rotation=270)]
    mock_doc = _make_mock_doc(pages)

    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}):
        with patch("pdf_processor.fitz.open", return_value=mock_doc):
            with patch("pdf_processor.Image.frombytes") as mock_frombytes:
                mock_frombytes.return_value = MagicMock()
                with patch("pdf_processor.pytesseract.image_to_osd") as mock_osd:
                    from pdf_processor import process_pdf
                    process_pdf(tmp_path / "test.pdf")

    mock_osd.assert_not_called()


def test_process_pdf_orientation_uncertain_when_both_tiers_fail(tmp_path):
    """orientation_uncertain=True when pytesseract raises and PDF rotation=0."""
    pages = [_make_mock_page(rotation=0)]
    mock_doc = _make_mock_doc(pages)

    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}):
        with patch("pdf_processor.fitz.open", return_value=mock_doc):
            with patch("pdf_processor.Image.frombytes") as mock_frombytes:
                mock_frombytes.return_value = MagicMock()
                with patch(
                    "pdf_processor.pytesseract.image_to_osd",
                    side_effect=Exception("tesseract not found"),
                ):
                    from pdf_processor import process_pdf
                    result = process_pdf(tmp_path / "test.pdf")

    page_num, pil_image, orientation_uncertain, rotation_applied = result[0]
    assert orientation_uncertain is True
    assert rotation_applied == 0


def test_process_pdf_page_num_is_one_indexed(tmp_path):
    """process_pdf returns 1-indexed page numbers."""
    pages = [_make_mock_page() for _ in range(2)]
    mock_doc = _make_mock_doc(pages)

    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}):
        with patch("pdf_processor.fitz.open", return_value=mock_doc):
            with patch("pdf_processor.Image.frombytes") as mock_frombytes:
                mock_frombytes.return_value = MagicMock()
                from pdf_processor import process_pdf
                result = process_pdf(tmp_path / "test.pdf")

    page_nums = [r[0] for r in result]
    assert page_nums == [1, 2]

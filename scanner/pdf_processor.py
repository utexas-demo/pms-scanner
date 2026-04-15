"""
PDF page extraction and orientation correction.

Two-tier orientation detection
-------------------------------
Tier 1 — PDF metadata: `page.rotation` (fitz).  Non-zero → apply correction.
Tier 2 — pytesseract OSD fallback: called only when tier-1 reports 0° rotation.
          On any tesseract failure the page is flagged orientation_uncertain=True
          and processed as-is (rotation_applied=0).
"""

import logging
from pathlib import Path

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)


def process_pdf(path: Path) -> list[tuple[int, Image.Image, bool, int]]:
    """
    Render every page of *path* to a PIL Image, correcting orientation where possible.

    Returns
    -------
    list of (page_num, pil_image, orientation_uncertain, rotation_applied)
        page_num            1-indexed
        pil_image           PIL Image after any rotation correction
        orientation_uncertain  True if neither tier could determine orientation
        rotation_applied    Degrees corrected (0, 90, 180, 270)
    """
    results: list[tuple[int, Image.Image, bool, int]] = []

    with fitz.open(str(path)) as doc:
        total = len(doc)
        logger.debug("Opened %s — %d page(s)", path.name, total)

        for idx in range(total):
            page = doc.load_page(idx)
            page_num = idx + 1

            rotation_applied, orientation_uncertain = _detect_orientation(page, page_num, path)

            pil_image = _render_page(page)

            if rotation_applied:
                pil_image = pil_image.rotate(-rotation_applied, expand=True)

            results.append((page_num, pil_image, orientation_uncertain, rotation_applied))

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_orientation(
    page: fitz.Page,
    page_num: int,
    path: Path,
) -> tuple[int, bool]:
    """
    Determine how many degrees to rotate the page to make it upright.

    Returns (rotation_applied, orientation_uncertain).
    """
    # Tier 1: PDF embedded rotation metadata
    pdf_rotation = page.rotation  # 0, 90, 180, or 270
    if pdf_rotation != 0:
        logger.debug(
            "%s p%d: tier-1 rotation=%d° from PDF metadata",
            path.name,
            page_num,
            pdf_rotation,
        )
        return pdf_rotation, False

    # Tier 2: pytesseract OSD
    rotation, uncertain = _osd_rotation(page, page_num, path)
    return rotation, uncertain


def _osd_rotation(
    page: fitz.Page,
    page_num: int,
    path: Path,
) -> tuple[int, bool]:
    """
    Use pytesseract OSD to detect rotation when PDF metadata says 0°.

    Returns (rotation_degrees, orientation_uncertain).
    """
    try:
        pil_image = _render_page(page, dpi=300)
        osd = pytesseract.image_to_osd(pil_image)
        # osd is a dict-like object with 'rotate' and 'orientation_conf' keys
        if isinstance(osd, dict):
            rotate = int(osd.get("rotate", 0))
            conf = float(osd.get("orientation_conf", 0.0))
        else:
            # image_to_osd can return a string in some versions — parse it
            rotate, conf = _parse_osd_string(str(osd))

        logger.debug(
            "%s p%d: tier-2 OSD rotate=%d° conf=%.1f",
            path.name,
            page_num,
            rotate,
            conf,
        )
        return rotate, False

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "%s p%d: OSD failed (%s) — orientation_uncertain=True",
            path.name,
            page_num,
            exc,
        )
        return 0, True


def _parse_osd_string(osd_text: str) -> tuple[int, float]:
    """Parse key-value pairs from tesseract OSD text output."""
    rotate = 0
    conf = 0.0
    for line in osd_text.splitlines():
        if "Rotate:" in line:
            try:
                rotate = int(line.split(":")[1].strip())
            except (ValueError, IndexError):
                pass
        elif "Orientation confidence:" in line:
            try:
                conf = float(line.split(":")[1].strip())
            except (ValueError, IndexError):
                pass
    return rotate, conf


def _render_page(page: fitz.Page, dpi: int = 72) -> Image.Image:
    """Render a fitz page to a PIL Image (RGB) at the given DPI."""
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom) if zoom != 1.0 else fitz.Identity
    pixmap = page.get_pixmap(matrix=matrix)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)

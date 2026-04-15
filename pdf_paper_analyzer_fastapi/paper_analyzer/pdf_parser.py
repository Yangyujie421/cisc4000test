"""Utilities for extracting plain text from PDF papers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Union

logger = logging.getLogger(__name__)

try:  # pylint: disable=wrong-import-position
    import fitz  # type: ignore
except ImportError:  # pragma: no cover - fallback handled at runtime
    fitz = None  # noqa: N816
    logger.debug("PyMuPDF 未安装，将尝试使用 pdfplumber 或文本读取。")


def parse(pdf_path: Union[str, Path]) -> str:
    """Extract text from a PDF file and return it as a single string."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    if path.suffix.lower() in {".txt", ".md"}:
        logger.info("检测到文本文件 %s，直接按 UTF-8 读取。", path)
        return path.read_text(encoding="utf-8").strip()

    if fitz is not None:
        return _parse_with_pymupdf(path)

    logger.info("PyMuPDF not available, falling back to pdfplumber.")
    return _parse_with_pdfplumber(path)


def _parse_with_pymupdf(path: Path) -> str:
    doc = fitz.open(path)  # type: ignore[attr-defined]
    try:
        text_chunks = [page.get_text("text") for page in doc]
    finally:
        doc.close()
    return "\n".join(text_chunks).strip()


def _parse_with_pdfplumber(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - preferred path is PyMuPDF
        raise RuntimeError(
            "Neither PyMuPDF nor pdfplumber is available. Please install at least one parser."
        ) from exc

    text_chunks = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text_chunks.append(page.extract_text() or "")
    return "\n".join(text_chunks).strip()


def extract_images(pdf_path: Union[str, Path], output_dir: Path, max_images: int = 50) -> List[Dict[str, Union[str, int]]]:
    """
    Extract embedded images from a PDF and save them to ``output_dir``.

    Returns a list of dictionaries with ``page`` and ``path`` for each image.
    If PyMuPDF is unavailable, the function returns an empty list.
    """
    path = Path(pdf_path)
    if path.suffix.lower() != ".pdf":
        logger.info("Skipping image extraction for non-PDF file: %s", path)
        return []

    if fitz is None:  # type: ignore[attr-defined]
        logger.warning("PyMuPDF 未安装，无法提取 PDF 图片。")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)

    images: List[Dict[str, Union[str, int]]] = []
    doc = fitz.open(path)  # type: ignore[attr-defined]
    try:
        for page_index, page in enumerate(doc, start=1):
            for img_index, img in enumerate(page.get_images(full=True), start=1):
                if len(images) >= max_images:
                    logger.info("Reached max_images=%d, stopping extraction.", max_images)
                    return images

                xref = img[0]
                try:
                    pix = fitz.Pixmap(doc, xref)  # type: ignore[attr-defined]
                except Exception as exc:  # pragma: no cover - rare decoding errors
                    logger.debug("Failed to decode image xref=%s on page %d: %s", xref, page_index, exc)
                    continue

                # Convert CMYK etc. to RGB for consistent PNG output
                if pix.n >= 5:  # type: ignore[attr-defined]
                    pix = fitz.Pixmap(fitz.csRGB, pix)  # type: ignore[attr-defined]

                filename = f"{path.stem}_p{page_index}_img{img_index}.png"
                out_path = output_dir / filename
                pix.save(out_path)  # type: ignore[attr-defined]
                images.append({"page": page_index, "path": str(out_path)})
    finally:
        doc.close()

    logger.info("Extracted %d images from %s", len(images), path.name)
    return images

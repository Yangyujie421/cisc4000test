"""DocLayout-YOLO based detector to locate figures and tables in PDF pages."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import fitz  # type: ignore
except ImportError:  # pragma: no cover - required for PDF rendering
    fitz = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class DetectionResult:
    page: int
    cls: str
    score: float
    bbox: list[int]
    crop_path: Path
    source_image: Path


def _load_model(weight_path: Path, imgsz: int) -> Any:
    try:
        from doclayout_yolo import YOLOv10  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError("doclayout_yolo is not installed.") from exc
    model = YOLOv10(str(weight_path))
    # Persist imgsz on the model for logging/debug purposes
    model._inference_imgsz = imgsz  # type: ignore[attr-defined]
    return model


def detect_layout(
    pdf_path: Path,
    output_dir: Path,
    config: dict[str, Any],
    max_pages: Optional[int] = None,
) -> dict[str, Any]:
    """
    Run DocLayout-YOLO to detect figures/tables on rendered PDF pages.

    Returns a dictionary with rendered page paths and detection crops.
    If dependencies are missing, raises ImportError for the caller to handle.
    """
    if fitz is None:
        raise ImportError("PyMuPDF is required for page rendering but is not installed.")

    model_repo = config.get("model_repo", "juliozhao/DocLayout-YOLO-DocStructBench")
    model_file = config.get("model_file", "doclayout_yolo_docstructbench_imgsz1024.pt")
    imgsz = int(config.get("imgsz", 1024))
    conf = float(config.get("conf", 0.25))
    scale = float(config.get("scale", 2.0))
    page_limit = max_pages or int(config.get("max_pages", 20))

    weight_path = _ensure_weight(model_repo, model_file)
    model = _load_model(weight_path, imgsz)

    pages_dir = output_dir / "pages"
    crops_dir = output_dir / "figures_tables"
    pages_dir.mkdir(parents=True, exist_ok=True)
    crops_dir.mkdir(parents=True, exist_ok=True)

    # Render pages
    page_images: list[tuple[int, Path]] = []
    doc = fitz.open(pdf_path)  # type: ignore[attr-defined]
    try:
        for idx, page in enumerate(doc, start=1):
            if idx > page_limit:
                break
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))  # type: ignore[attr-defined]
            img_path = pages_dir / f"page_{idx}.png"
            pix.save(img_path)
            page_images.append((idx, img_path))
    finally:
        doc.close()

    detections: list[DetectionResult] = []
    for page_num, img_path in page_images:
        res = model.predict(str(img_path), imgsz=imgsz, conf=conf, device="cpu")
        if not res:
            continue
        det = res[0]
        names = det.names
        allowed_classes = {"figure", "table", "figure_caption", "table_caption"}
        for i, box in enumerate(det.boxes):
            cls_id = int(box.cls[0])
            cls_name = names.get(cls_id, str(cls_id))
            if cls_name not in allowed_classes:
                continue
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
            score = float(box.conf[0])

            try:
                from PIL import Image
            except ImportError as exc:  # pragma: no cover
                raise ImportError("Pillow is required for cropping detected regions.") from exc

            im = Image.open(img_path).convert("RGB")
            crop = im.crop((x1, y1, x2, y2))
            crop_name = f"page{page_num}_{cls_name}_{i+1}.png"
            crop_path = crops_dir / crop_name
            crop.save(crop_path)

            detections.append(
                {
                    "page": page_num,
                    "class": cls_name,
                    "score": score,
                    "bbox": [x1, y1, x2, y2],
                    "crop_path": str(crop_path),
                    "source_image": str(img_path),
                }
            )

    return {
        "pages_dir": pages_dir,
        "crops_dir": crops_dir,
        "detections": detections,
    }


def _ensure_weight(model_repo: str, model_file: str) -> Path:
    """Download weight via HuggingFace Hub if not present locally."""
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:  # pragma: no cover
        raise ImportError("huggingface_hub is required to download DocLayout-YOLO weights.") from exc
    weight_path = hf_hub_download(repo_id=model_repo, filename=model_file)
    return Path(weight_path)

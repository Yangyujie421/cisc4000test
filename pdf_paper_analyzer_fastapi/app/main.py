"""FastAPI entry point exposing the PDF paper analyzer pipeline."""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import PROJECT_ROOT, get_config
from .models import AnalysisResponse, VideoGenerationRequest, VideoGenerationResponse, SpeedUpRequest, SpeedUpResponse
from .progress import progress_tracker
from .services import run_analysis
from .services.video_generator import run_pipeline_light, run_speed_up

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
OUTPUT_DIR = (PROJECT_ROOT / "data" / "output").resolve()

# In-memory video job store: job_id -> {"status": str, "video_path": str|None, "error": str|None}
_video_jobs: dict[str, dict[str, Any]] = {}
_video_executor = ThreadPoolExecutor(max_workers=2)

app = FastAPI(
    title="PDF Paper Analyzer API",
    description="Expose the PDF paper analysis workflow over HTTP.",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")


@app.on_event("startup")
def _validate_config() -> None:
    try:
        config = get_config()
        logger.info("Loaded configuration with %d top-level keys.", len(config))
    except FileNotFoundError as exc:
        logger.error("Configuration file missing: %s", exc)
        raise


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def serve_frontend() -> HTMLResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend page not found.")
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    request_id: str | None = Form(None),
    llm_base_url: str | None = Form(None),
    llm_api_key: str | None = Form(None),
    llm_model_name: str | None = Form(None),
) -> AnalysisResponse:
    req_id = request_id or uuid.uuid4().hex
    progress_tracker.start(req_id)
    progress_tracker.update(req_id, "接收请求", "in_progress", "开始处理上传")

    def _progress_callback(step: str, status: str, detail: str | None = None) -> None:
        progress_tracker.update(req_id, step, status, detail)

    temp_path: Path | None = None
    llm_overrides = {
        "base_url": llm_base_url or "",
        "api_key": llm_api_key or "",
        "model_name": llm_model_name or "",
    }
    llm_overrides = {key: value for key, value in llm_overrides.items() if value}
    try:
        pipeline_result, temp_path = await run_analysis(
            file,
            progress_callback=_progress_callback,
            llm_overrides=llm_overrides or None,
        )
    except ValueError as exc:
        progress_tracker.update(req_id, "处理失败", "failed", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        logger.error("Pipeline failed: %s", exc)
        progress_tracker.update(req_id, "处理失败", "failed", "配置文件缺失")
        raise HTTPException(status_code=500, detail="Pipeline configuration error.") from exc
    except Exception as exc:  # pragma: no cover - unexpected failures
        logger.error("Unexpected pipeline error: %s", exc)
        progress_tracker.update(req_id, "处理失败", "failed", str(exc))
        raise
    finally:
        if temp_path:
            background_tasks.add_task(_safe_unlink, temp_path)

    progress_tracker.update(req_id, "接收请求", "completed", "已完成处理")
    progress_snapshot = progress_tracker.get(req_id)
    payload = _serialise_pipeline_result(pipeline_result, progress_snapshot)
    return AnalysisResponse(**payload)


@app.get("/progress/{request_id}")
async def poll_progress(request_id: str) -> dict[str, Any]:
    return {"request_id": request_id, "steps": progress_tracker.get(request_id)}


# ---------------------------------------------------------------------------
# Video generation endpoints
# ---------------------------------------------------------------------------

def _run_video_job(
    job_id: str,
    bundle_path: str,
    result_dir: str,
    ref_audio: str | None,
    bg_color: str | None,
) -> None:
    """Executed in thread pool. Updates _video_jobs in place."""
    _video_jobs[job_id]["status"] = "running"

    def _cb(step: str, status: str, detail: str | None = None) -> None:
        progress_tracker.update(job_id, step, status, detail)

    try:
        video_path = run_pipeline_light(
            bundle_path=bundle_path,
            result_dir=result_dir,
            ref_audio=ref_audio,
            bg_color=bg_color,
            progress_callback=_cb,
        )
        _video_jobs[job_id]["status"] = "done"
        _video_jobs[job_id]["video_path"] = video_path
    except Exception as exc:  # noqa: BLE001
        logger.error("Video job %s failed: %s", job_id, exc)
        _video_jobs[job_id]["status"] = "failed"
        _video_jobs[job_id]["error"] = str(exc)


@app.post("/generate-video", response_model=VideoGenerationResponse)
async def generate_video(req: VideoGenerationRequest) -> VideoGenerationResponse:
    bundle = Path(req.bundle_path)
    if not bundle.exists():
        raise HTTPException(status_code=400, detail=f"bundle_path not found: {req.bundle_path}")

    result_dir = str(Path(req.run_output_dir) / "video")
    Path(result_dir).mkdir(parents=True, exist_ok=True)

    job_id = uuid.uuid4().hex
    _video_jobs[job_id] = {"status": "queued", "video_path": None, "error": None}
    progress_tracker.start(job_id)
    progress_tracker.update(job_id, "初始化", "in_progress", "视频任务已排队")

    _video_executor.submit(
        _run_video_job,
        job_id,
        req.bundle_path,
        result_dir,
        req.ref_audio,
        req.bg_color,
    )

    return VideoGenerationResponse(job_id=job_id, status="queued")


@app.get("/video-status/{job_id}", response_model=VideoGenerationResponse)
async def video_status(job_id: str) -> VideoGenerationResponse:
    job = _video_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_id not found")

    video_url: str | None = None
    if job["status"] == "done" and job.get("video_path"):
        video_url = f"/download-video?video_path={job['video_path']}"

    return VideoGenerationResponse(job_id=job_id, status=job["status"], video_url=video_url)


@app.get("/download-video")
async def download_video(video_path: str = Query(...)) -> FileResponse:
    path = Path(video_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(
        str(path),
        media_type="video/mp4",
        filename=path.name,
    )

# ---------------------------------------------------------------------------
# Speed-up video endpoints
# ---------------------------------------------------------------------------

_speedup_jobs: dict[str, dict[str, Any]] = {}


def _run_speedup_job(job_id: str, video_path: str, speed_factor: float) -> None:
    """Executed in thread pool. Updates _speedup_jobs in place."""
    _speedup_jobs[job_id]["status"] = "running"
    try:
        out_path = run_speed_up(video_path=video_path, speed_factor=speed_factor)
        _speedup_jobs[job_id]["status"] = "done"
        _speedup_jobs[job_id]["video_path"] = out_path
    except Exception as exc:  # noqa: BLE001
        logger.error("Speed-up job %s failed: %s", job_id, exc)
        _speedup_jobs[job_id]["status"] = "failed"
        _speedup_jobs[job_id]["error"] = str(exc)


@app.post("/speed-up-video", response_model=SpeedUpResponse)
async def speed_up_video(req: SpeedUpRequest) -> SpeedUpResponse:
    src = Path(req.video_path)
    if not src.exists() or not src.is_file():
        raise HTTPException(status_code=400, detail=f"video_path not found: {req.video_path}")
    if req.speed_factor <= 0:
        raise HTTPException(status_code=400, detail="speed_factor must be positive")

    job_id = uuid.uuid4().hex
    _speedup_jobs[job_id] = {"status": "queued", "video_path": None, "error": None}
    _video_executor.submit(_run_speedup_job, job_id, req.video_path, req.speed_factor)
    return SpeedUpResponse(job_id=job_id, status="queued")


@app.get("/speed-up-status/{job_id}", response_model=SpeedUpResponse)
async def speed_up_status(job_id: str) -> SpeedUpResponse:
    job = _speedup_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_id not found")

    video_url: str | None = None
    if job["status"] == "done" and job.get("video_path"):
        video_url = f"/download-video?video_path={job['video_path']}"
    return SpeedUpResponse(job_id=job_id, status=job["status"], video_url=video_url)


def _serialise_pipeline_result(
    result: dict[str, Any],
    progress: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report_paths = {
        key: str(Path(path))
        for key, path in (result.get("report_paths") or {}).items()
    }

    markdown_content: str | None = result.get("markdown_text")
    if not markdown_content:
        markdown_path = report_paths.get("markdown")
        if markdown_path:
            try:
                markdown_content = Path(markdown_path).read_text(encoding="utf-8")
            except OSError as exc:
                logger.error("Failed to read markdown report %s: %s", markdown_path, exc)

    slides = _simplify_slides(result.get("presentation_plan"))
    voice_scripts = _simplify_voice_scripts(result.get("voiceover_scripts"))
    method_assets = _simplify_method_assets(result.get("method_visuals"))
    layout_detections = _simplify_layout_detections(result.get("layout_detections"))

    return {
        "markdown_summary": markdown_content,
        "slides": slides,
        "voice_scripts": voice_scripts,
        "progress": progress or [],
        "bundle_path": result.get("presentation_bundle_path"),
        "images": result.get("images") or [],
        "method_assets": method_assets,
        "layout_detections": layout_detections,
        "run_output_dir": str(result.get("run_output_dir")) if result.get("run_output_dir") else None,
    }


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except TypeError:
        # Python <3.8 compatibility for missing_ok
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _simplify_slides(slides: Any) -> list[dict[str, Any]] | None:
    if not slides:
        return None
    simplified = []
    for entry in slides:
        try:
            page_id = int(entry.get("page_id", len(simplified) + 1))
        except (TypeError, ValueError):
            page_id = len(simplified) + 1
        title = entry.get("title") or f"第 {page_id} 页"
        hook = entry.get("hook") or title
        bullets = entry.get("bullets") or []
        if isinstance(bullets, str):
            bullets = [bullets]
        elif not isinstance(bullets, list):
            bullets = [str(bullets)]
        bullets = [str(bullet).strip() for bullet in bullets if str(bullet).strip()]
        table_asset = entry.get("table_asset")
        if isinstance(table_asset, dict):
            table_asset = [table_asset]
        elif not isinstance(table_asset, list):
            table_asset = None
        simplified.append(
            {
                "page_id": page_id,
                "title": title,
                "hook": hook,
                "bullets": bullets,
                "figure_asset": entry.get("figure_asset"),
                "table_asset": table_asset,
                "table_note": entry.get("table_note"),
                "table_markdown": entry.get("table_markdown"),
            }
        )
    return simplified or None


def _simplify_voice_scripts(voice_entries: Any) -> list[dict[str, Any]] | None:
    if not voice_entries:
        return None
    simplified = []
    for entry in voice_entries:
        try:
            page_id = int(entry.get("page_id", len(simplified) + 1))
        except (TypeError, ValueError):
            page_id = len(simplified) + 1
        simplified.append(
            {
                "page_id": page_id,
                "title": entry.get("title"),
                "voice_over": entry.get("voice_over", ""),
                "closing_sentence": entry.get("closing_sentence"),
            }
        )
    return simplified or None


def _simplify_method_assets(assets: Any) -> dict[str, Any] | None:
    if not assets:
        return None

    def _clean(entry: Any) -> dict[str, Any] | None:
        if not entry:
            return None
        return {
            "page": entry.get("page"),
            "class_name": entry.get("class") or entry.get("class_name"),
            "crop_path": entry.get("crop_path"),
            "detection_score": entry.get("detection_score"),
            "llm_score": entry.get("llm_score"),
            "reason": entry.get("reason"),
        }

    figures = assets.get("figures")
    if not figures and assets.get("figure"):
        figures = [assets.get("figure")]

    tables = assets.get("tables")
    if not tables and assets.get("table"):
        tables = [assets.get("table")]

    return {
        "figure": _clean(assets.get("figure")),
        "figures": [_clean(entry) for entry in figures if _clean(entry)] if figures else None,
        "table": _clean(assets.get("table")),
        "tables": [_clean(entry) for entry in tables if _clean(entry)] if tables else None,
    }


def _simplify_layout_detections(detections: Any) -> list[dict[str, Any]] | None:
    if not detections:
        return None
    cleaned = []
    for entry in detections:
        cleaned.append(
            {
                "page": entry.get("page"),
                "class_name": entry.get("class") or entry.get("class_name"),
                "score": entry.get("score"),
                "bbox": entry.get("bbox"),
                "crop_path": entry.get("crop_path"),
                "crop_url": entry.get("crop_url"),
                "source_image": entry.get("source_image"),
                "source_url": entry.get("source_url"),
            }
        )
    return cleaned

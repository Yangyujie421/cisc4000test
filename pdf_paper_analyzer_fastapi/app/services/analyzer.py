"""Run the analysis pipeline for uploaded PDFs."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Mapping

from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool

from ..config import PROJECT_ROOT, get_config
from paper_analyzer.pipeline import PaperAnalysisPipeline

_ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}
_READ_CHUNK_SIZE = 1024 * 1024  # 1 MiB


async def run_analysis(
    upload_file: UploadFile,
    progress_callback: Callable[[str, str, str | None], None] | None = None,
    llm_overrides: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], Path]:
    """
    Persist an uploaded file to disk and execute the analysis pipeline.

    Returns a tuple of the pipeline result and the temporary file path so the caller can clean up.
    """
    suffix = _normalise_suffix(upload_file.filename)
    if suffix not in _ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: {suffix or '<none>'}")

    if progress_callback:
        progress_callback("上传文件", "in_progress", "开始接收上传内容")

    temp_path = await _persist_upload(upload_file, suffix)

    if progress_callback:
        progress_callback("上传文件", "completed", f"已保存临时文件 {temp_path.name}")

    runtime_config = deepcopy(get_config())
    if llm_overrides:
        llm_cfg = runtime_config.setdefault("llm_api", {})
        for key, value in llm_overrides.items():
            if value:
                llm_cfg[key] = value

    pipeline = PaperAnalysisPipeline(runtime_config, PROJECT_ROOT)
    result = await run_in_threadpool(
        pipeline.run,
        temp_path,
        progress_callback,
        upload_file.filename,
    )
    return result, temp_path


def _normalise_suffix(filename: str | None) -> str:
    if not filename:
        return ".pdf"
    return Path(filename).suffix.lower() or ".pdf"


async def _persist_upload(upload_file: UploadFile, suffix: str) -> Path:
    await upload_file.seek(0)
    with NamedTemporaryFile(mode="wb", suffix=suffix, delete=False) as tmp_file:
        while True:
            chunk = await upload_file.read(_READ_CHUNK_SIZE)
            if not chunk:
                break
            tmp_file.write(chunk)
    await upload_file.close()
    return Path(tmp_file.name)

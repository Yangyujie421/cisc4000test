"""Video generation service: calls p2v pipeline_light.py as a subprocess."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

# Absolute path to the p2v src directory (contains pipeline_light.py and prompts/)
P2V_SRC_DIR = Path("/root/autodl-tmp/p2v_new/p2v/src")

# Default reference audio bundled with p2v assets
DEFAULT_REF_AUDIO = str(Path("/root/autodl-tmp/p2v_new/p2v/assets/demo/girl_en.wav"))


def run_pipeline_light(
    bundle_path: str,
    result_dir: str,
    ref_audio: Optional[str] = None,
    bg_color: Optional[str] = None,
    progress_callback: Optional[Callable[[str, str, Optional[str]], None]] = None,
) -> str:
    """Run pipeline_light.py synchronously and return the output video path.

    Parameters
    ----------
    bundle_path:
        Absolute path to ``presentation_bundle.json``.
    result_dir:
        Directory where the pipeline will write its outputs.
        The final video will be at ``result_dir/1_merage.mp4``.
    ref_audio:
        Path to a reference ``.wav`` file for F5-TTS voice cloning.
        Defaults to ``DEFAULT_REF_AUDIO``.
    bg_color:
        Optional background color for generated slides (named color or hex value).
    progress_callback:
        Optional callable ``(step, status, detail)`` used to report progress.

    Returns
    -------
    str
        Absolute path to the generated ``1_merage.mp4`` video file.

    Raises
    ------
    RuntimeError
        If the subprocess exits with a non-zero return code.
    """
    audio = ref_audio or DEFAULT_REF_AUDIO

    def _cb(step: str, status: str, detail: str | None = None) -> None:
        if progress_callback:
            progress_callback(step, status, detail)

    _cb("初始化", "in_progress", "准备视频生成参数")

    cmd = [
        sys.executable,          # same Python interpreter
        str(P2V_SRC_DIR / "pipeline_light.py"),
        "--json_file_path", bundle_path,
        "--result_dir", result_dir,
        "--ref_audio", audio,
        "--stage", '["0"]',
    ]
    if bg_color:
        cmd.extend(["--bg_color", bg_color])

    _cb("生成幻灯片", "in_progress", "正在执行 pipeline_light.py")

    proc = subprocess.run(
        cmd,
        cwd=str(P2V_SRC_DIR),   # working dir so relative prompt files resolve
        capture_output=False,    # let stdout/stderr stream to server console
        text=True,
    )

    if proc.returncode != 0:
        _cb("视频生成", "failed", f"pipeline 返回码 {proc.returncode}")
        raise RuntimeError(
            f"pipeline_light.py exited with code {proc.returncode}"
        )

    video_path = str(Path(result_dir) / "1_merage.mp4")
    _cb("视频生成", "completed", f"视频已保存：{video_path}")
    return video_path

def run_speed_up(video_path: str, speed_factor: float) -> str:
    """Speed up a video by the given factor using moviepy and return the output path.

    The output file is written alongside the source with a ``_speedNx`` suffix,
    e.g. ``1_merage_speed1.5x.mp4``.
    """
    try:
        from moviepy.editor import VideoFileClip
        import moviepy.video.fx.all as vfx
    except ImportError as exc:
        raise RuntimeError(
            "moviepy is not installed. Run: pip install moviepy"
        ) from exc

    src = Path(video_path)
    suffix = f"_speed{speed_factor}x"
    out_path = src.with_stem(src.stem + suffix)

    clip = VideoFileClip(str(src))
    try:
        fast_clip = clip.fx(vfx.speedx, factor=speed_factor)
        fast_clip.write_videofile(str(out_path), codec="libx264", audio_codec="aac")
    finally:
        clip.close()

    return str(out_path)

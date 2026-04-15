"""Pydantic models exposed by the API."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ExtractedImage(BaseModel):
    page: int = Field(..., description="Page number in the PDF (starting from 1).")
    path: str = Field(..., description="Filesystem path to the extracted image (PNG).")
    url: Optional[str] = Field(
        default=None,
        description="Public URL (served from /output) if available; otherwise None.",
    )


class SlideSummary(BaseModel):
    page_id: int = Field(..., description="Slide index starting from 1.")
    title: str = Field(..., description="Slide title.")
    hook: str = Field(..., description="Single sentence highlighting the slide's focus.")
    bullets: List[str] = Field(
        default_factory=list, description="Key points (prefixed with bullets) for this slide."
    )
    figure_asset: Optional[dict] = Field(
        default=None,
        description="Optional figure asset info for the method slide (crop_path/crop_url/page).",
    )
    table_asset: Optional[List[dict]] = Field(
        default=None,
        description="Optional table asset list for the results slide (crop_path/crop_url/page).",
    )
    table_note: Optional[str] = Field(
        default=None, description="Fallback note when no table image is available."
    )
    table_markdown: Optional[str] = Field(
        default=None, description="Fallback markdown table when no table image is available."
    )



class VoiceScript(BaseModel):
    page_id: int
    title: Optional[str] = None
    voice_over: str = Field(..., description="Full voice-over script for this slide.")
    closing_sentence: Optional[str] = Field(
        default=None, description="Optional final sentence emphasising the slide takeaway."
    )


class VisualAsset(BaseModel):
    page: int = Field(..., description="Page number containing the detected visual.")
    class_name: str = Field(..., description="Detected class, e.g., figure or table.")
    crop_path: str = Field(..., description="Path to the cropped image.")
    detection_score: Optional[float] = Field(
        default=None, description="Confidence from the layout detector."
    )
    llm_score: Optional[float] = Field(
        default=None, description="Relevance score from the method visual agent."
    )
    reason: Optional[str] = Field(default=None, description="Short LLM rationale.")


class MethodAssets(BaseModel):
    figure: Optional[VisualAsset] = None
    figures: Optional[List[VisualAsset]] = Field(
        default=None,
        description="Optional list of main method figures when more than one is needed.",
    )
    table: Optional[VisualAsset] = None
    tables: Optional[List[VisualAsset]] = Field(
        default=None,
        description="Optional list of main result tables when more than one is needed.",
    )


class LayoutDetection(BaseModel):
    page: int = Field(..., description="Page number containing the detected visual.")
    class_name: str = Field(..., description="Detected class name (figure/table).")
    score: Optional[float] = Field(default=None, description="Detection confidence score.")
    bbox: Optional[List[int]] = Field(default=None, description="[x1,y1,x2,y2] in page image coordinates.")
    crop_path: str = Field(..., description="Path to the cropped visual image.")
    crop_url: Optional[str] = Field(default=None, description="URL to access the cropped image via /output.")
    source_image: Optional[str] = Field(default=None, description="Rendered page image path.")
    source_url: Optional[str] = Field(default=None, description="Rendered page image URL.")


class ProgressStep(BaseModel):
    name: str
    status: str
    detail: Optional[str] = None


class VideoGenerationRequest(BaseModel):
    bundle_path: str = Field(..., description="Path to presentation_bundle.json")
    run_output_dir: str = Field(..., description="Root directory for this run's artifacts")
    ref_audio: Optional[str] = Field(
        default=None,
        description="Optional path to reference audio file; defaults to built-in demo audio",
    )
    bg_color: Optional[str] = Field(
        default=None,
        description="Optional slide background color (named color or hex like #FFFFFF).",
    )


class VideoGenerationResponse(BaseModel):
    job_id: str
    status: str
    video_url: Optional[str] = None

class SpeedUpRequest(BaseModel):
    video_path: str = Field(..., description="Absolute path to the source video file")
    speed_factor: float = Field(..., description="Playback speed multiplier, e.g. 1.5 means 1.5x faster")


class SpeedUpResponse(BaseModel):
    job_id: str
    status: str
    video_url: Optional[str] = None


class AnalysisResponse(BaseModel):
    """Response payload returned after a successful PDF analysis."""

    markdown_summary: Optional[str] = Field(
        default=None, description="PPT friendly markdown summary."
    )
    slides: Optional[List[SlideSummary]] = Field(
        default=None,
        description="Simplified slide pagination with page ids and bullet points.",
    )
    voice_scripts: Optional[List[VoiceScript]] = Field(
        default=None,
        description="Per-page voice-over scripts corresponding to the slide plan.",
    )
    images: List[ExtractedImage] = Field(
        default_factory=list, description="Extracted images from the PDF with their page numbers."
    )
    method_assets: Optional[MethodAssets] = Field(
        default=None,
        description="Predicted primary method figure/table chosen by the visual agent.",
    )
    layout_detections: Optional[List[LayoutDetection]] = Field(
        default=None,
        description="All detected figures/tables from DocLayout-YOLO, including crop URLs.",
    )
    progress: List[ProgressStep] = Field(
        default_factory=list, description="Processing steps that finished on the server."
    )
    bundle_path: Optional[str] = Field(
        default=None,
        description="Path to the consolidated JSON file containing markdown, slides, and voice scripts.",
    )
    run_output_dir: Optional[str] = Field(
        default=None,
        description="Root directory for this run's artifacts under data/output.",
    )

"""Top-level orchestration for the PDF paper analysis workflow."""

from __future__ import annotations

import json
from shutil import copy2
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .agent_handler import AgentHandler
from .document_structurer import structure
from .doclayout_detector import detect_layout
from .method_visual_agent import MethodVisualAgent
from .pdf_parser import extract_images, parse
from .presentation_builder import PresentationBuilder
from .report_generator import generate as generate_report

logger = logging.getLogger(__name__)


class PaperAnalysisPipeline:
    """Coordinate PDF parsing, structuring, agent calls, and report generation."""

    def __init__(self, config: dict[str, Any], project_dir: Path):
        self.config = config
        self.project_dir = project_dir

        paths_cfg = config.get("paths", {})
        self.prompt_dir = (project_dir / paths_cfg.get("prompt_dir", "prompts")).resolve()
        self.output_dir = (project_dir / paths_cfg.get("output_dir", "data/output")).resolve()
        structured_rel = paths_cfg.get("structured_output", "structured_paper.json")
        self.structured_output_name = Path(structured_rel).name

        structure_cfg = config.get("structure", {})
        self.preamble_label = structure_cfg.get("preamble_label", "metadata")
        self.section_config = structure_cfg.get("sections", {})
        active_sections = structure_cfg.get("active_sections")
        if active_sections:
            self.active_sections = [section for section in active_sections if section in self.section_config]
        else:
            self.active_sections = list(self.section_config.keys())

        self.agent_handler = AgentHandler(config.get("llm_api", {}), self.prompt_dir)
        self.presentation_cfg = config.get("presentation") or {}

        visual_cfg = config.get("visual_selection", {}) or {}
        self.visual_selection_enabled = bool(visual_cfg.get("enabled", True))
        self.visual_cfg = visual_cfg
        self.method_visual_agent: MethodVisualAgent | None = None
        if self.visual_selection_enabled:
            self.method_visual_agent = MethodVisualAgent(
                config.get("llm_api", {}),
                max_candidates_per_cls=int(visual_cfg.get("max_candidates_per_class", 5)),
                min_llm_score=float(visual_cfg.get("min_llm_score", 0.5)),
            )

    def run(
        self,
        pdf_path: Path,
        progress_callback: Callable[[str, str, str | None], None] | None = None,
        original_filename: str | None = None,
    ) -> dict[str, Any]:
        logger.info("Starting analysis pipeline for %s", pdf_path)
        base_name_raw = Path(original_filename or pdf_path.name).stem
        base_name = re.sub(r"[^A-Za-z0-9._-]+", "_", base_name_raw).strip("_") or "document"
        run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_id = f"{base_name}_{run_timestamp}"
        run_output_dir = (self.output_dir / run_id).resolve()
        run_output_dir.mkdir(parents=True, exist_ok=True)
        structured_output_path = run_output_dir / self.structured_output_name

        def _progress(step: str, status: str, detail: str | None = None) -> None:
            if progress_callback:
                progress_callback(step, status, detail)

        _progress("解析 PDF", "in_progress", "开始解析原文")
        raw_text = parse(pdf_path)
        logger.info("Parsed PDF into %d characters of text.", len(raw_text))
        _progress("解析 PDF", "completed", f"提取 {len(raw_text)} 个字符")

        images_info: list[dict[str, Any]] = []
        if pdf_path.suffix.lower() == ".pdf":
            image_output_dir = None  # 禁用内嵌图片抽取
            _progress("提取图片", "skipped", "已禁用内嵌图片提取")

        layout_detections: list[dict[str, Any]] = []
        visual_selection = None
        if self.visual_selection_enabled and self.method_visual_agent:
            layout_dir = run_output_dir / "layout"
            try:
                _progress("版面检测", "in_progress", "DocLayout-YOLO 提取图/表")
                layout_payload = detect_layout(
                    pdf_path,
                    layout_dir,
                    self.visual_cfg,
                    max_pages=self.visual_cfg.get("max_pages"),
                )
                layout_detections = layout_payload.get("detections") or []
                _progress("版面检测", "completed", f"识别图表 {len(layout_detections)} 个")
            except ImportError as exc:
                logger.warning("DocLayout-YOLO unavailable: %s", exc)
                _progress("版面检测", "skipped", "未安装 DocLayout-YOLO 或依赖")
            except Exception as exc:  # pragma: no cover
                logger.error("DocLayout-YOLO 检测失败: %s", exc)
                _progress("版面检测", "failed", "版面检测出错")

            if layout_detections:
                self._attach_caption_text(pdf_path, layout_detections)
                # attach URLs for crops/source images
                for det in layout_detections:
                    try:
                        crop_rel = Path(det["crop_path"]).resolve().relative_to(self.output_dir.resolve())
                        det["crop_url"] = f"/output/{crop_rel.as_posix()}"
                    except Exception:
                        det["crop_url"] = None
                    try:
                        src_rel = Path(det.get("source_image", "")).resolve().relative_to(self.output_dir.resolve())
                        det["source_url"] = f"/output/{src_rel.as_posix()}"
                    except Exception:
                        det["source_url"] = None
                _progress("方法主图筛选", "in_progress", "调用 LLM 评估关键图表")
                try:
                    selection = self.method_visual_agent.select(layout_detections)
                    visual_selection = {
                        "figure": _serialise_choice(selection.get("figure")),
                        "figures": _serialise_choices(selection.get("figures")),
                        "table": _serialise_choice(selection.get("table")),
                        "tables": _serialise_choices(selection.get("tables")),
                    }
                    self._persist_primary_visuals(selection, run_output_dir / "main_figure_table")
                    _progress("方法主图筛选", "completed", "已选择方法主图/主表")
                except Exception as exc:  # pragma: no cover
                    logger.error("方法主图筛选失败: %s", exc)
                    _progress("方法主图筛选", "failed", "LLM 评分出错")

        _progress("结构化章节", "in_progress", "尝试识别章节结构")
        structured_doc = structure(raw_text, self.section_config, self.preamble_label)
        abstract_text = structured_doc.get("abstract")
        filtered_doc = {
            section: structured_doc[section]
            for section in self.active_sections
            if section in structured_doc
        }

        if not filtered_doc:
            logger.warning("No configured sections were detected in the document.")
        self._persist_structured(filtered_doc, structured_output_path)
        _progress("结构化章节", "completed", f"检测到 {len(filtered_doc)} 个章节")

        _progress("章节分析", "in_progress", f"准备处理 {len(self.active_sections)} 个章节")
        analysis_results = []
        for section_name in self.active_sections:
            section_text = filtered_doc.get(section_name)
            if not section_text:
                continue

            if section_name == "introduction" and abstract_text:
                section_text = f"Abstract:\n{abstract_text}\n\nIntroduction:\n{section_text}"

            prompt_file = self._get_prompt_filename(section_name)
            logger.debug("Processing section '%s' with prompt %s", section_name, prompt_file)
            analysis_result = self.agent_handler.process_section(
                section_name, section_text, prompt_file
            )
            analysis_results.append(analysis_result)
        _progress("章节分析", "completed", f"生成 {len(analysis_results)} 份摘要")

        _progress("生成 Markdown", "in_progress", "汇总章节分析")
        report_paths = generate_report(analysis_results, run_output_dir, pdf_path, base_stem=run_id)
        logger.info("Generated report artifacts: %s", report_paths)
        if report_paths.get("markdown"):
            _progress("生成 Markdown", "completed", Path(report_paths["markdown"]).name)
        else:
            _progress("生成 Markdown", "skipped", "未生成 Markdown 文件")

        markdown_path = report_paths.get("markdown")
        markdown_text = None
        if markdown_path:
            try:
                markdown_text = Path(markdown_path).read_text(encoding="utf-8")
            except OSError as exc:
                logger.error("Failed to read markdown report %s: %s", markdown_path, exc)
                markdown_text = None
        if markdown_path and markdown_text:
            _progress("规划 PPT 分页", "in_progress", "根据 Markdown 拆分分页")
            presentation_payload = self._maybe_build_presentation(
                Path(markdown_path),
                markdown_text,
                pdf_path,
                run_output_dir,
                layout_detections,
                visual_selection,
            )
        else:
            presentation_payload = None
        if presentation_payload:
            _progress(
                "规划 PPT 分页",
                "completed",
                f"{len(presentation_payload.get('slides') or [])} 页",
            )
            if presentation_payload.get("voiceover"):
                _progress(
                    "生成口播脚本",
                    "completed",
                    f"{len(presentation_payload['voiceover'])} 段",
                )
            else:
                _progress("生成口播脚本", "skipped", "未生成口播内容")
        else:
            _progress("规划 PPT 分页", "skipped", "未生成展示结构")
            _progress("生成口播脚本", "skipped", "缺少分页结构")

        if presentation_payload:
            report_paths.update(presentation_payload.get("paths", {}))
            bundle_path_obj = presentation_payload["paths"].get("presentation_bundle")
            bundle_path = str(bundle_path_obj) if bundle_path_obj else None
        else:
            bundle_path = None

        _progress("汇总结果", "completed", "所有步骤执行完毕")

        return {
            "structured_text_path": structured_output_path,
            "report_paths": report_paths,
            "sections_detected": list(filtered_doc.keys()),
            "presentation_plan": presentation_payload.get("slides") if presentation_payload else None,
            "voiceover_scripts": presentation_payload.get("voiceover") if presentation_payload else None,
            "presentation_bundle_path": bundle_path,
            "markdown_text": markdown_text,
            "images": images_info,
            "layout_detections": layout_detections,
            "method_visuals": visual_selection,
            "run_output_dir": run_output_dir,
        }

    def _attach_caption_text(self, pdf_path: Path, detections: list[dict[str, Any]]) -> None:
        caption_classes = {"figure_caption", "table_caption"}
        captions = [det for det in detections if det.get("class") in caption_classes]
        if not captions:
            return

        try:
            import fitz  # type: ignore
        except ImportError:
            logger.warning("PyMuPDF unavailable; skipping caption text extraction.")
            return

        scale = float(self.visual_cfg.get("scale", 2.0) or 1.0)
        if scale <= 0:
            scale = 1.0

        try:
            doc = fitz.open(pdf_path)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("Failed to open PDF for caption extraction: %s", exc)
            return

        try:
            for cap in captions:
                page_num = int(cap.get("page") or 0)
                if page_num < 1 or page_num > len(doc):
                    continue
                bbox = cap.get("bbox") or []
                if len(bbox) < 4:
                    continue
                rect = fitz.Rect(
                    bbox[0] / scale,
                    bbox[1] / scale,
                    bbox[2] / scale,
                    bbox[3] / scale,
                )
                text = doc[page_num - 1].get_text("text", clip=rect).strip()
                if text:
                    cap["caption_text"] = " ".join(text.split())
        finally:
            doc.close()

        for det in detections:
            cls_name = det.get("class")
            if cls_name not in {"figure", "table"}:
                continue
            caption_cls = f"{cls_name}_caption"
            same_page = [cap for cap in captions if cap.get("class") == caption_cls and cap.get("page") == det.get("page")]
            if not same_page:
                continue
            det_bbox = det.get("bbox") or []
            if len(det_bbox) < 4:
                continue
            det_x1, det_y1, det_x2, det_y2 = det_bbox
            det_center_x = (det_x1 + det_x2) / 2

            def _score(candidate: dict[str, Any]) -> tuple[float, float]:
                bbox = candidate.get("bbox") or []
                if len(bbox) < 4:
                    return (float("inf"), float("inf"))
                cap_x1, cap_y1, cap_x2, cap_y2 = bbox
                # Vertical gap between table/figure and caption (0 if overlapping)
                if cap_y1 >= det_y2:
                    vertical_gap = cap_y1 - det_y2
                elif cap_y2 <= det_y1:
                    vertical_gap = det_y1 - cap_y2
                else:
                    vertical_gap = 0.0
                cap_center_x = (cap_x1 + cap_x2) / 2
                horizontal_gap = abs(cap_center_x - det_center_x)
                return (vertical_gap, horizontal_gap)

            best = min(same_page, key=_score)
            if best.get("caption_text"):
                det["caption_text"] = best["caption_text"]

    def _persist_primary_visuals(self, selection: dict[str, Any], output_dir: Path) -> None:
        figures = selection.get("figures") or []
        if not figures and selection.get("figure"):
            figures = [selection["figure"]]
        tables = selection.get("tables") or []
        if not tables and selection.get("table"):
            tables = [selection["table"]]
        if not figures and not tables:
            return

        output_dir.mkdir(parents=True, exist_ok=True)
        counters = {"figure": 0, "table": 0}

        def _copy(choice: Any) -> None:
            if not choice or not getattr(choice, "crop_path", None):
                return
            src = Path(choice.crop_path)
            if not src.exists():
                return
            cls_name = getattr(choice, "cls", "asset")
            if cls_name not in counters:
                counters[cls_name] = 0
            counters[cls_name] += 1
            suffix = src.suffix or ".png"
            dest_name = f"{cls_name}_{counters[cls_name]}{suffix}"
            copy2(src, output_dir / dest_name)

        for fig in figures:
            _copy(fig)
        for table in tables:
            _copy(table)

    def _persist_structured(self, structured_doc: Dict[str, str], dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(structured_doc, indent=2, ensure_ascii=False)
        dest.write_text(payload, encoding="utf-8")
        logger.info("Stored structured document at %s", dest)

    def _get_prompt_filename(self, section_name: str) -> str | None:
        try:
            section_cfg = self.section_config[section_name]
        except KeyError:
            return None
        return section_cfg.get("prompt")

    def _maybe_build_presentation(
        self,
        markdown_path: Path,
        markdown_text: str,
        pdf_path: Path,
        run_output_dir: Path,
        layout_detections: list[dict[str, Any]] | None,
        method_visuals: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not self.presentation_cfg:
            return None
        builder = PresentationBuilder(self.agent_handler, self.presentation_cfg, run_output_dir)
        return builder.build(markdown_text, markdown_path, pdf_path, layout_detections, method_visuals)


def _serialise_choice(choice: Any) -> Any:
    if not choice:
        return None
    return {
        "page": choice.page,
        "class": choice.cls,
        "crop_path": str(choice.crop_path),
        "detection_score": choice.detection_score,
        "llm_score": choice.llm_score,
        "reason": choice.reason,
    }


def _serialise_choices(choices: Any) -> list[dict[str, Any]] | None:
    if not choices:
        return None
    return [_serialise_choice(choice) for choice in choices if choice]

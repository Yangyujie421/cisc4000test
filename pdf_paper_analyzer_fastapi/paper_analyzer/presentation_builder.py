"""Utilities to derive PPT slide plans and voice-over scripts from markdown summaries."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .agent_handler import AgentHandler

logger = logging.getLogger(__name__)


class PresentationBuilder:
    """Generate PPT pagination data and voice scripts using the configured LLM."""

    def __init__(
        self,
        agent_handler: AgentHandler,
        config: Mapping[str, Any],
        output_dir: Path,
    ):
        self.agent_handler = agent_handler
        self.config = config or {}
        self.output_dir = output_dir

        self.max_slides = int(self.config.get("max_slides", 10))
        self.slides_prompt = self.config.get("slides_prompt")
        self.voice_prompt = self.config.get("voice_prompt")
        self.voice_language = self.config.get("voice_language", "中文")
        self.duration_hint = self.config.get("default_duration_seconds", "35-50")
        self.method_char_limit = int(self.config.get("method_char_limit", 800))
        self.results_char_limit = int(self.config.get("results_char_limit", 600))
        self.table_prompt = self.config.get("table_prompt", "presentation_table_prompt.txt")
        self.visual_prompt = self.config.get(
            "visual_prompt", "presentation_visual_semantic_prompt.txt"
        )

    @property
    def enabled(self) -> bool:
        has_client = getattr(self.agent_handler, "client", None) is not None
        return bool(self.slides_prompt and self.voice_prompt and has_client)

    def build(
        self,
        markdown_text: str,
        markdown_path: Path,
        pdf_path: Path,
        layout_detections: Optional[List[Dict[str, Any]]] = None,
        method_visuals: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return presentation metadata plus persisted artifact paths."""
        if not self.enabled:
            logger.info("Presentation builder disabled; missing prompt names or LLM client.")
            return None

        detections = layout_detections or []
        target_count, split_target = self._determine_slide_plan(markdown_text, detections)
        slides = self._generate_slides(markdown_text, target_count, split_target)
        slides = self._order_and_trim_slides(slides, target_count, split_target)
        candidates = self._collect_visual_candidates(detections, method_visuals)
        classification = self._classify_visuals_with_llm(candidates, markdown_text)
        slides = self._apply_visual_semantics(slides, candidates, classification)
        if not slides:
            logger.warning("LLM 未生成 PPT 分页结构，跳过口播脚本步骤。")
            return None

        voice_slides = self._generate_voiceover(slides, markdown_text)
        timestamp = datetime.now().isoformat(timespec="seconds")
        if markdown_path.parent == self.output_dir:
            bundle_name = "presentation_bundle.json"
        else:
            safe_stem = self._safe_stem(markdown_path.stem or "presentation")
            bundle_name = f"{safe_stem}_presentation_bundle.json"
        bundle_path = self.output_dir / bundle_name
        self.output_dir.mkdir(parents=True, exist_ok=True)

        bundle_payload = {
            "generated_at": timestamp,
            "source_markdown": str(markdown_path),
            "source_pdf": str(pdf_path),
            "markdown_summary_text": markdown_text,
            "slides": slides,
            "voice_scripts": voice_slides,
        }
        bundle_path.write_text(
            json.dumps(bundle_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {
            "slides": slides,
            "voiceover": voice_slides,
            "paths": {
                "presentation_bundle": bundle_path,
            },
            "bundle_payload": bundle_payload,
        }

    def _generate_slides(
        self, markdown_text: str, target_count: int, split_target: Optional[str]
    ) -> List[Dict[str, Any]]:
        response = self.agent_handler.process_section(
            "presentation_outline",
            "",
            prompt_filename=self.slides_prompt,
            prompt_variables={
                "max_slides": target_count,
                "target_slides": target_count,
                "split_target": split_target or "none",
                "markdown_content": markdown_text,
            },
        )
        payload = self._parse_json(response.get("analysis", ""), "slide outline")
        raw_slides = payload.get("slides") or []
        slides: List[Dict[str, Any]] = []
        for index, entry in enumerate(raw_slides, start=1):
            slides.append(self._normalise_slide_entry(entry, index))
        return slides

    def _determine_slide_plan(
        self, markdown_text: str, layout_detections: List[Dict[str, Any]]
    ) -> tuple[int, Optional[str]]:
        return 4, None

    def _order_and_trim_slides(
        self, slides: List[Dict[str, Any]], target_count: int, split_target: Optional[str]
    ) -> List[Dict[str, Any]]:
        if not slides:
            return []

        remaining = list(slides)
        ordered: List[Dict[str, Any]] = []

        def _pop(category: str) -> Optional[Dict[str, Any]]:
            for index, entry in enumerate(remaining):
                if self._categorize_slide(entry) == category:
                    return remaining.pop(index)
            return None

        ordered.append(_pop("intro") or remaining.pop(0))

        method_slide = _pop("method") or (remaining.pop(0) if remaining else None)
        if method_slide is None:
            method_slide = self._blank_slide("方法如何", "method")
        ordered.append(method_slide)

        if target_count == 5 and split_target == "method":
            ordered.append(_pop("method") or self._split_slide(method_slide, "方法细节"))

        results_slide = _pop("results") or (remaining.pop(0) if remaining else None)
        if results_slide is None:
            results_slide = self._blank_slide("实验结果与 Main Results", "results")
        ordered.append(results_slide)

        if target_count == 5 and split_target == "results":
            ordered.append(_pop("results") or self._split_slide(results_slide, "补充结果"))

        findings_slide = _pop("findings") or (remaining.pop(0) if remaining else None)
        if findings_slide is None:
            findings_slide = self._blank_slide("Key Findings", "findings")
        ordered.append(findings_slide)

        while len(ordered) < target_count and remaining:
            ordered.append(remaining.pop(0))

        ordered = ordered[:target_count]
        for idx, entry in enumerate(ordered, start=1):
            entry["page_id"] = idx
            category = self._categorize_slide(entry)
            entry["bullets"] = self._trim_bullets(entry.get("bullets") or [], category)
        return ordered

    @staticmethod
    def _blank_slide(title: str, role: str) -> Dict[str, Any]:
        return {
            "page_id": 0,
            "title": title,
            "role": role,
            "hook": title,
            "bullets": [],
            "transition_hint": "",
        }

    def _split_slide(self, slide: Dict[str, Any], new_title: str) -> Dict[str, Any]:
        bullets = list(slide.get("bullets") or [])
        midpoint = max(1, len(bullets) // 2)
        remainder = bullets[midpoint:] if len(bullets) > 1 else []
        slide["bullets"] = bullets[:midpoint]
        return {
            "page_id": 0,
            "title": new_title,
            "role": slide.get("role") or "content",
            "hook": new_title,
            "bullets": remainder or bullets[:1],
            "transition_hint": "",
        }

    @staticmethod
    def _trim_bullets(bullets: List[str], category: Optional[str]) -> List[str]:
        if not bullets:
            return []
        limits = {
            "intro": 3,
            "method": 5,
            "results": 2,
            "findings": 3,
        }
        limit = limits.get(category or "", len(bullets))
        return bullets[:limit]

    def _categorize_slide(self, entry: Mapping[str, Any]) -> str:
        title = str(entry.get("title") or "").lower()
        hook = str(entry.get("hook") or "").lower()
        text = f"{title} {hook}"
        if any(key in text for key in ["动机", "问题", "引言", "提出", "背景", "introduction", "motivation"]):
            return "intro"
        if any(key in text for key in ["方法", "method", "framework", "模型", "算法"]):
            return "method"
        if any(key in text for key in ["结果", "实验", "main results", "performance", "results"]):
            return "results"
        if any(key in text for key in ["key finding", "发现", "结论", "总结", "insight"]):
            return "findings"
        return "content"

    def _collect_visual_candidates(
        self,
        layout_detections: List[Dict[str, Any]],
        method_visuals: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        seen_paths: set[str] = set()

        def _add_candidate(source: str, kind: str, entry: Dict[str, Any]) -> None:
            crop_path = entry.get("crop_path")
            if not crop_path:
                return
            if crop_path in seen_paths:
                return
            seen_paths.add(crop_path)
            candidates.append(
                {
                    "id": f"cand_{len(candidates)}",
                    "kind": kind,
                    "source": source,
                    "page": entry.get("page"),
                    "crop_path": crop_path,
                    "crop_url": entry.get("crop_url") or self._lookup_crop_url(crop_path, layout_detections),
                    "caption_text": entry.get("caption_text"),
                    "detection_score": entry.get("score") or entry.get("detection_score"),
                    "llm_score": entry.get("llm_score"),
                    "reason": entry.get("reason"),
                }
            )

        if method_visuals:
            figure = method_visuals.get("figure")
            if figure:
                _add_candidate("method_visuals", "figure", figure)
            for entry in method_visuals.get("figures") or []:
                _add_candidate("method_visuals", "figure", entry)
            table = method_visuals.get("table")
            if table:
                _add_candidate("method_visuals", "table", table)
            for entry in method_visuals.get("tables") or []:
                _add_candidate("method_visuals", "table", entry)

        for entry in layout_detections:
            cls_name = entry.get("class") or entry.get("class_name")
            if cls_name == "figure":
                _add_candidate("layout", "figure", entry)
            elif cls_name == "table":
                _add_candidate("layout", "table", entry)

        return candidates

    def _classify_visuals_with_llm(
        self, candidates: List[Dict[str, Any]], markdown_text: str
    ) -> Dict[str, Any]:
        if not candidates or not self.visual_prompt or self.agent_handler.client is None:
            return {"labels": {}}

        method_excerpt = self._extract_section(
            markdown_text, ["method", "methods", "materials and methods", "方法"]
        )
        results_excerpt = self._extract_section(markdown_text, ["results", "result", "实验", "结果"])
        method_excerpt = method_excerpt[:1200]
        results_excerpt = results_excerpt[:1200]

        labels: Dict[str, Dict[str, Any]] = {}
        for entry in candidates:
            candidate_payload = {
                "id": entry["id"],
                "kind": entry["kind"],
                "page": entry.get("page"),
                "caption_text": entry.get("caption_text") or "<none>",
                "source": entry.get("source"),
            }
            image_path = None
            crop_path = entry.get("crop_path")
            if crop_path:
                path = Path(crop_path)
                if path.exists():
                    image_path = path
            response = self.agent_handler.process_section(
                "presentation_visual_semantic",
                "",
                prompt_filename=self.visual_prompt,
                prompt_variables={
                    "method_excerpt": method_excerpt,
                    "results_excerpt": results_excerpt,
                    "candidate_json": json.dumps(candidate_payload, ensure_ascii=False),
                },
                image_path=image_path,
            )
            payload = self._parse_json(response.get("analysis", ""), "visual semantic")
            semantic_label = payload.get("semantic_label") or payload.get("label")
            semantic_score = payload.get("semantic_score") or payload.get("score") or 0
            labels[str(entry["id"])] = {
                "label": semantic_label,
                "score": semantic_score,
            }

        return {"labels": labels}

    def _apply_visual_semantics(
        self,
        slides: List[Dict[str, Any]],
        candidates: List[Dict[str, Any]],
        classification: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if not slides:
            return slides
        labels = classification.get("labels") or {}

        method_index = self._find_method_slide_index(slides)
        if method_index is None:
            method_index = 1 if len(slides) > 1 else 0
        method_choice = self._pick_best_candidate(candidates, labels, "figure", "method_figure")
        if method_choice:
            slides[method_index]["figure_asset"] = self._candidate_payload(method_choice)

        result_index = self._find_results_slide_index(slides)
        if result_index is None:
            result_index = min(2, len(slides) - 1)

        main_tables = self._pick_main_result_tables(candidates, labels)
        if not main_tables:
            slides[result_index]["table_note"] = "未检测到主结果表，请手动补图"
            return slides

        slides[result_index]["table_asset"] = [
            self._candidate_payload(entry) for entry in main_tables
        ]

        return slides

    def _pick_best_candidate(
        self,
        candidates: List[Dict[str, Any]],
        labels: Dict[str, Dict[str, Any]],
        kind: str,
        target_label: str,
    ) -> Optional[Dict[str, Any]]:
        scored = []
        for entry in candidates:
            if entry.get("kind") != kind:
                continue
            info = labels.get(entry.get("id")) or {}
            if info.get("label") != target_label:
                continue
            score = float(info.get("score") or 0)
            if entry.get("source") == "method_visuals":
                score += 0.01
            scored.append((score, entry))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    def _pick_main_result_tables(
        self,
        candidates: List[Dict[str, Any]],
        labels: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        table_candidates = [
            entry
            for entry in candidates
            if entry.get("kind") == "table"
            and (labels.get(entry.get("id")) or {}).get("label") == "main_result_table"
        ]
        if not table_candidates:
            return []

        def _page_key(entry: Dict[str, Any]) -> tuple[int, float]:
            page = entry.get("page")
            try:
                page_value = int(page)
            except (TypeError, ValueError):
                page_value = 10**9
            score = float((labels.get(entry.get("id")) or {}).get("score") or 0)
            return (page_value, -score)

        table_candidates.sort(key=_page_key)
        return table_candidates[:2]

    @staticmethod
    def _candidate_payload(entry: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "page": entry.get("page"),
            "crop_path": entry.get("crop_path"),
            "crop_url": entry.get("crop_url"),
            "score": entry.get("detection_score"),
            "llm_score": entry.get("llm_score"),
            "caption_text": entry.get("caption_text"),
            "reason": entry.get("reason"),
            "source": entry.get("source"),
        }

    @staticmethod
    def _lookup_crop_url(crop_path: Optional[str], layout_detections: List[Dict[str, Any]]) -> Optional[str]:
        if not crop_path:
            return None
        for entry in layout_detections:
            if entry.get("crop_path") == crop_path:
                return entry.get("crop_url")
        return None

    @staticmethod
    def _find_results_slide_index(slides: List[Dict[str, Any]]) -> Optional[int]:
        for index, slide in enumerate(slides):
            title = str(slide.get("title") or "").lower()
            hook = str(slide.get("hook") or "").lower()
            text = f"{title} {hook}"
            if any(key in text for key in ["结果", "实验", "main results", "results"]):
                return index
        return None

    @staticmethod
    def _find_method_slide_index(slides: List[Dict[str, Any]]) -> Optional[int]:
        for index, slide in enumerate(slides):
            title = str(slide.get("title") or "").lower()
            hook = str(slide.get("hook") or "").lower()
            text = f"{title} {hook}"
            if any(key in text for key in ["方法", "method", "framework", "模型", "算法"]):
                return index
        return None

    @staticmethod
    def _find_ablation_slide_index(slides: List[Dict[str, Any]]) -> Optional[int]:
        for index, slide in enumerate(slides):
            title = str(slide.get("title") or "").lower()
            hook = str(slide.get("hook") or "").lower()
            text = f"{title} {hook}"
            if any(key in text for key in ["消融", "ablation", "补充结果", "supplementary"]):
                return index
        return None

    @staticmethod
    def _count_tables(layout_detections: List[Dict[str, Any]]) -> int:
        count = 0
        for entry in layout_detections:
            cls_name = entry.get("class") or entry.get("class_name")
            if cls_name == "table":
                count += 1
        return count

    @staticmethod
    def _extract_section(markdown_text: str, keywords: List[str]) -> str:
        if not markdown_text:
            return ""
        lines = markdown_text.splitlines()
        start = None
        level = None
        lowered = [kw.lower() for kw in keywords]
        for idx, line in enumerate(lines):
            match = re.match(r"^(#{1,6})\s*(.+)$", line.strip())
            if not match:
                continue
            title = match.group(2).strip().lower()
            if any(keyword in title for keyword in lowered):
                start = idx
                level = len(match.group(1))
                break
        if start is None:
            return ""
        content_lines: List[str] = []
        for line in lines[start + 1 :]:
            match = re.match(r"^(#{1,6})\s*(.+)$", line.strip())
            if match and level is not None and len(match.group(1)) <= level:
                break
            content_lines.append(line)
        return "\n".join(content_lines).strip()

    @staticmethod
    def _strip_markdown(text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"[`*_#>-]", " ", text)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def _generate_voiceover(self, slides: List[Dict[str, Any]], markdown_text: str) -> List[Dict[str, Any]]:
        slides_json = json.dumps({"slides": slides, "markdown_excerpt": markdown_text[:4000]}, ensure_ascii=False)
        response = self.agent_handler.process_section(
            "presentation_voiceover",
            "",
            prompt_filename=self.voice_prompt,
            prompt_variables={
                "voice_language": self.voice_language,
                "duration_hint": self.duration_hint,
                "slides_json": slides_json,
            },
        )
        payload = self._parse_json(response.get("analysis", ""), "voice-over script")
        raw_slides = payload.get("voice_slides") or payload.get("slides") or []
        return [self._normalise_voice_entry(entry) for entry in raw_slides]

    @staticmethod
    def _normalise_slide_entry(entry: Mapping[str, Any], fallback_page: int) -> Dict[str, Any]:
        try:
            page_id = int(entry.get("page_id", fallback_page))
        except (TypeError, ValueError):
            page_id = fallback_page

        content = entry.get("content")
        hook = entry.get("hook")
        if not hook:
            hook = entry.get("content") or entry.get("title") or "本页概览"
        hook = str(hook).strip()

        raw_bullets = entry.get("bullets") or entry.get("key_points") or entry.get("key_bullet_points") or []
        if isinstance(raw_bullets, str):
            bullets = [fragment.strip() for fragment in raw_bullets.splitlines() if fragment.strip()]
        else:
            bullets = [str(item).strip() for item in raw_bullets if str(item).strip()]
        if not bullets and entry.get("content"):
            bullets = [segment.strip() for segment in entry["content"].split("；") if segment.strip()]

        return {
            "page_id": page_id,
            "title": str(entry.get("title") or f"Page {page_id}").strip(),
            "role": str(entry.get("role") or "content").strip(),
            "hook": hook,
            "bullets": [PresentationBuilder._ensure_bullet_prefix(bullet) for bullet in bullets],
            "transition_hint": str(entry.get("transition_hint") or "").strip(),
            "figure_asset": entry.get("figure_asset"),
            "table_asset": PresentationBuilder._normalise_table_asset(entry.get("table_asset")),
            "table_note": entry.get("table_note"),
            "table_markdown": entry.get("table_markdown"),
        }

    @staticmethod
    def _normalise_table_asset(value: Any) -> Optional[List[Dict[str, Any]]]:
        if not value:
            return None
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
        return None

    @staticmethod
    def _ensure_bullet_prefix(text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("•"):
            return cleaned
        return f"• {cleaned}" if cleaned else cleaned

    @staticmethod
    def _normalise_voice_entry(entry: Mapping[str, Any]) -> Dict[str, Any]:
        try:
            page_id = int(entry.get("page_id", 0))
        except (TypeError, ValueError):
            page_id = 0

        def _clean(value: Optional[Any]) -> str:
            return str(value).strip() if value is not None else ""

        return {
            "page_id": page_id,
            "title": _clean(entry.get("title")),
            "voice_over": _clean(entry.get("voice_over")),
            "closing_sentence": _clean(entry.get("closing_sentence")),
        }

    @staticmethod
    def _parse_json(raw_text: str, label: str) -> Dict[str, Any]:
        cleaned = raw_text.strip()
        if not cleaned:
            logger.error("LLM 返回空字符串，无法解析 %s JSON。", label)
            return {}

        cleaned = PresentationBuilder._strip_code_fence(cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end >= start:
            snippet = cleaned[start : end + 1]
        else:
            snippet = cleaned

        try:
            return json.loads(snippet)
        except json.JSONDecodeError as exc:
            logger.error("解析 %s JSON 失败：%s\n原始内容：%s", label, exc, cleaned)
            return {}

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        if text.startswith("```"):
            closing = text.rstrip().rfind("```")
            first_newline = text.find("\n")
            if closing != -1 and first_newline != -1 and closing > first_newline:
                return text[first_newline + 1 : closing].strip()
        return text

    @staticmethod
    def _safe_stem(stem: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_") or "presentation"

"""Agent that scores detected figures/tables to pick the primary method visuals."""

from __future__ import annotations

import json
import re
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .llm_client import build_messages, create_client
from .prompts import (
    METHOD_VISUAL_SCORE_PROMPT,
    METHOD_VISUAL_TABLE_COUNT_PROMPT,
    SYSTEM_PROMPT,
    resolve_prompt,
)

logger = logging.getLogger(__name__)


@dataclass
class VisualCandidate:
    page: int
    cls: str
    score: float
    bbox: list[int]
    crop_path: Path
    source_image: Path
    caption_text: str | None = None


@dataclass
class VisualChoice:
    cls: str
    page: int
    crop_path: Path
    detection_score: float
    llm_score: float
    reason: str


class MethodVisualAgent:
    """Score visual candidates with an LLM to pick the main method figure/table."""

    def __init__(
        self,
        llm_config: Mapping[str, Any],
        max_candidates_per_cls: int = 5,
        min_llm_score: float = 0.5,
    ):
        self.max_candidates_per_cls = max_candidates_per_cls
        self.min_llm_score = min_llm_score
        try:
            self.client = create_client(llm_config)
            self.model_name = llm_config.get("model_name")
            self.system_prompt = resolve_prompt(llm_config.get("system_prompt", SYSTEM_PROMPT))
            self.timeout = llm_config.get("timeout", 60)
        except Exception as exc:  # pragma: no cover - runtime failure
            logger.warning("Failed to init LLM client for method visual agent: %s", exc)
            self.client = None
            self.model_name = None
            self.system_prompt = None
            self.timeout = 60

    def select(self, candidates: Iterable[Mapping[str, Any]]) -> Dict[str, Optional[VisualChoice]]:
        """Return best figure and table choices (may be None)."""
        parsed = [self._to_candidate(c) for c in candidates]
        figures = [c for c in parsed if c.cls == "figure"]
        tables = [c for c in parsed if c.cls == "table"]

        figure_choices = self._pick_figures(figures)
        best_figure = figure_choices[0] if figure_choices else None
        table_choices = self._pick_tables(tables)
        best_table = table_choices[0] if table_choices else None
        return {
            "figure": best_figure,
            "figures": figure_choices or None,
            "table": best_table,
            "tables": table_choices or None,
        }

    def _pick_best(self, candidates: List[VisualCandidate]) -> Optional[VisualChoice]:
        choices = self._score_candidates(candidates)
        return choices[0][1] if choices else None

    def _pick_figures(self, candidates: List[VisualCandidate]) -> List[VisualChoice]:
        choices = self._score_candidates(candidates)
        if not choices:
            return []
        return [choices[0][1]]

    def _pick_tables(self, candidates: List[VisualCandidate]) -> List[VisualChoice]:
        choices = self._score_candidates(candidates)
        if not choices:
            return []
        if len(choices) == 1 or self.client is None:
            return [choices[0][1]]

        count, selected = self._decide_table_count(choices)
        selected_choices: list[VisualChoice] = []
        if selected:
            for idx in selected:
                if 1 <= idx <= len(choices):
                    selected_choices.append(choices[idx - 1][1])
        if not selected_choices:
            selected_choices = [choices[i][1] for i in range(min(count, len(choices)))]
        return selected_choices[:2]

    def _score_candidate(self, cand: VisualCandidate) -> tuple[Optional[float], str]:
        caption_hint = f"Caption text: {cand.caption_text}" if cand.caption_text else "Caption text: <none>"
        prompt = METHOD_VISUAL_SCORE_PROMPT.format(
            cand_cls=cand.cls,
            cand_page=cand.page,
            caption_hint=caption_hint,
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=build_messages(prompt, self.system_prompt or "", image_path=cand.crop_path),
                timeout=self.timeout,
            )
            raw = response.choices[0].message.content.strip()
            parsed = self._parse_json(raw)
            if not parsed.get("is_method", False):
                return None, str(parsed.get("reason", "")).strip()
            score_val = parsed.get("score")
            try:
                score = float(score_val)
            except (TypeError, ValueError):
                score = None
            return score, str(parsed.get("reason", "")).strip()
        except Exception as exc:  # pragma: no cover - network/runtime errors
            logger.error("LLM scoring failed for %s: %s", cand.crop_path, exc)
            return None, ""

    @staticmethod
    def _to_candidate(data: Mapping[str, Any]) -> VisualCandidate:
        return VisualCandidate(
            page=int(data.get("page", 0)),
            cls=str(data.get("class") or data.get("cls") or ""),
            score=float(data.get("score") or 0.0),
            bbox=list(data.get("bbox") or []),
            crop_path=Path(data.get("crop_path")),
            source_image=Path(data.get("source_image")),
            caption_text=str(data.get("caption_text")) if data.get("caption_text") else None,
        )

    @staticmethod
    def _parse_json(raw_text: str) -> Dict[str, Any]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            closing = cleaned.rstrip().rfind("```")
            first_newline = cleaned.find("\n")
            if closing != -1 and first_newline != -1 and closing > first_newline:
                cleaned = cleaned[first_newline + 1 : closing].strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        snippet = cleaned[start : end + 1] if start != -1 and end != -1 and end >= start else cleaned
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            return {}

    def _pick_best_by_caption(self, candidates: List[VisualCandidate]) -> Optional[VisualChoice]:
        if not candidates:
            return None
        scored: list[tuple[float, VisualCandidate]] = []
        for cand in candidates:
            caption_score = self._caption_score(cand)
            if caption_score <= 0.0:
                continue
            scored.append((caption_score, cand))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        best = scored[0][1]
        return VisualChoice(
            cls=best.cls,
            page=best.page,
            crop_path=best.crop_path,
            detection_score=best.score,
            llm_score=0.0,
            reason="caption heuristic",
        )

    def _combine_scores(self, llm_score: Optional[float], caption_score: float) -> float:
        if llm_score is None:
            return caption_score
        llm_weight = 0.6
        return llm_weight * llm_score + (1 - llm_weight) * caption_score

    def _caption_score(self, cand: VisualCandidate) -> float:
        text = (cand.caption_text or "").lower()
        if not text:
            return 0.0

        if cand.cls == "figure":
            positives = ["overview", "methodology", "architecture", "framework", "pipeline", "system"]
            negatives = ["example", "case study", "visualization"]
        else:
            positives = ["outperforms", "baseline", "benchmark", "results", "performance", "accuracy", "f1", "dataset"]
            negatives = ["ablation", "sensitivity", "hyperparameter", "template", "prompt"]

        score = 0.0
        for kw in positives:
            if kw in text:
                score += 0.15
        for kw in negatives:
            if kw in text:
                score -= 0.2

        if cand.cls == "table":
            table_num = self._extract_index(text, "table")
            if table_num is not None:
                score += max(0.0, 0.12 - 0.01 * table_num)
        if cand.cls == "figure":
            fig_num = self._extract_index(text, "figure")
            if fig_num is not None:
                score += max(0.0, 0.1 - 0.01 * fig_num)

        return max(0.0, min(1.0, score))

    @staticmethod
    def _extract_index(text: str, label: str) -> Optional[int]:
        match = re.search(rf"{label}\\s*(\\d+)", text, re.IGNORECASE)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _score_candidates(self, candidates: List[VisualCandidate]) -> list[tuple[float, VisualChoice, VisualCandidate]]:
        if not candidates:
            return []
        limited = sorted(candidates, key=lambda c: c.score, reverse=True)[: self.max_candidates_per_cls]
        scored: list[tuple[float, VisualChoice, VisualCandidate]] = []
        for cand in limited:
            if self.client is None:
                score, reason = None, ""
            else:
                score, reason = self._score_candidate(cand)
            caption_score = self._caption_score(cand)
            if score is None or score < self.min_llm_score:
                if caption_score <= 0.0:
                    continue
                score = None
                reason = reason or "caption heuristic"
            combined = self._combine_scores(score, caption_score)
            scored.append(
                (
                    combined,
                    VisualChoice(
                        cls=cand.cls,
                        page=cand.page,
                        crop_path=cand.crop_path,
                        detection_score=cand.score,
                        llm_score=score or 0.0,
                        reason=reason or "",
                    ),
                    cand,
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored

    def _decide_table_count(
        self, choices: list[tuple[float, VisualChoice, VisualCandidate]]
    ) -> tuple[int, list[int]]:
        if self.client is None or len(choices) < 2:
            return 1, []
        entries = []
        for idx, (_, choice, cand) in enumerate(choices[:3], start=1):
            caption = (cand.caption_text or "").strip() or "<none>"
            entries.append(f"{idx}. page={choice.page}, caption={caption}")
        prompt = METHOD_VISUAL_TABLE_COUNT_PROMPT.format(candidates_text="\n".join(entries))
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=build_messages(prompt, self.system_prompt or ""),
                timeout=self.timeout,
            )
            raw = response.choices[0].message.content.strip()
            parsed = self._parse_json(raw)
        except Exception as exc:  # pragma: no cover - network/runtime errors
            logger.error("LLM table count decision failed: %s", exc)
            return 1, []

        count = parsed.get("count", 1)
        if count not in (1, 2):
            count = 1
        selected = parsed.get("selected") or []
        if not isinstance(selected, list):
            selected = []
        selected_idx: list[int] = []
        for item in selected:
            try:
                selected_idx.append(int(item))
            except (TypeError, ValueError):
                continue
        return count, selected_idx

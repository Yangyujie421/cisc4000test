"""Agent handler responsible for orchestrating LLM calls per section."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .llm_client import DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT, build_messages, create_client
from .prompts import get_prompt, resolve_prompt

logger = logging.getLogger(__name__)


class AgentHandler:
    """Load prompts and dispatch section analysis requests to the configured LLM."""

    def __init__(self, llm_config: Dict[str, str], prompt_dir: Path):
        self.prompt_dir = prompt_dir
        self.timeout = llm_config.get("timeout", 60)
        self.model_name = llm_config.get("model_name") or DEFAULT_MODEL
        self.system_prompt = resolve_prompt(llm_config.get("system_prompt", DEFAULT_SYSTEM_PROMPT))

        try:
            self.client = create_client(llm_config)
            logger.debug(
                "初始化 OpenAI 客户端成功，base_url=%s，model=%s",
                llm_config.get("base_url"),
                self.model_name,
            )
        except ValueError:
            self.client = None
            logger.warning("LLM 配置信息不完整，AgentHandler 将返回占位结果。")

    def process_section(
        self,
        section_name: str,
        section_text: str,
        prompt_filename: Optional[str] = None,
        prompt_variables: Optional[Mapping[str, Any]] = None,
        image_path: Optional[Path] = None,
    ) -> Dict[str, str]:
        """Run the agent for a single section and return the analysis text."""
        if prompt_filename:
            prompt = self._load_prompt(prompt_filename)
        else:
            fallback = f"{section_name}_prompt.txt"
            prompt = self._load_prompt(fallback)
        if prompt and prompt_variables:
            prompt = self._apply_template(prompt, prompt_variables)
        final_prompt = self._build_prompt(prompt, section_text)

        if self.client is None:
            logger.info("Skipping LLM call for %s (client disabled).", section_name)
            return {
                "section": section_name,
                "analysis": "LLM 未配置，返回原始文本片段：\n" + section_text[:1000],
            }

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=build_messages(final_prompt, self.system_prompt, image_path=image_path),
                timeout=self.timeout,
            )
            content = response.choices[0].message.content.strip()
        except Exception as exc:  # pragma: no cover - network errors
            logger.error("LLM request failed for section %s: %s", section_name, exc)
            content = f"LLM request failed: {exc}\nRaw section text:\n{section_text[:1000]}"

        return {"section": section_name, "analysis": content}

    def _load_prompt(self, filename: str) -> Optional[str]:
        prompt = get_prompt(filename)
        if prompt is None:
            logger.warning("Prompt not found in prompts.py: %s", filename)
            return None
        return prompt.strip()

    @staticmethod
    def _apply_template(template: str, variables: Mapping[str, Any]) -> str:
        rendered = template
        for key, value in variables.items():
            token = "{{" + str(key) + "}}"
            rendered = rendered.replace(token, str(value))
        return rendered

    @staticmethod
    def _build_prompt(prompt_template: Optional[str], section_text: str) -> str:
        if prompt_template:
            return f"{prompt_template}\n\n---\n正文片段：\n{section_text}"
        return (
            "请用中文概括以下论文片段，给出要点、数据与待解问题，保持准确简洁。\n\n"
            f"正文片段：\n{section_text}"
        )

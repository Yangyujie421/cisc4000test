"""创建并复用 OpenAI 客户端的工具模块。"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from openai import OpenAI

from .prompts import SYSTEM_PROMPT

DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_SYSTEM_PROMPT = SYSTEM_PROMPT

def create_client(llm_config: Mapping[str, Any]) -> OpenAI:
    """
    根据配置创建 OpenAI 客户端。

    配置需要包含 `api_key`，可选 `base_url`、`organization` 等。
    """
    api_key = llm_config.get("api_key")
    if not api_key:
        raise ValueError("llm_api 配置缺少 api_key。")

    base_url = llm_config.get("base_url")
    organization = llm_config.get("organization")
    max_retries = llm_config.get("max_retries", 0)

    client_kwargs: Dict[str, Any] = {
        "api_key": api_key,
        "base_url": base_url,
        "organization": organization,
    }
    if max_retries is not None:
        client_kwargs["max_retries"] = max_retries

    return OpenAI(**client_kwargs)


def build_messages(
    prompt: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    image_path: Optional[Path] = None,
) -> List[dict]:
    """
    构造聊天消息体。若提供图片路径，则使用多模态输入。
    """
    messages: List[dict] = [{"role": "system", "content": system_prompt}]

    if image_path:
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _encode_image_to_base64(image_path)}},
                ],
            }
        )
    else:
        messages.append({"role": "user", "content": prompt})

    return messages


def _encode_image_to_base64(image_path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(image_path)
    if mime_type is None:
        mime_type = "application/octet-stream"
    encoded_bytes = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded_bytes}"

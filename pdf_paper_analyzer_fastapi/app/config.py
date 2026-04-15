"""Configuration utilities for the FastAPI service."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    """
    Load the YAML configuration used by the pipeline.

    The path can be overridden via the ``PDF_ANALYZER_CONFIG`` environment variable.
    """
    config_path = Path(os.getenv("PDF_ANALYZER_CONFIG", DEFAULT_CONFIG_PATH))
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    raw_text = config_path.read_text(encoding="utf-8")
    return yaml.safe_load(raw_text) or {}


__all__ = ["get_config", "PROJECT_ROOT", "DEFAULT_CONFIG_PATH"]

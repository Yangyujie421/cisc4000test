"""Transform raw PDF text into a structured document."""

from __future__ import annotations

import logging
import re
from typing import Dict, Iterable, List, Mapping, Optional

logger = logging.getLogger(__name__)


def structure(
    raw_text: str,
    section_config: Mapping[str, Mapping[str, Optional[str]]],
    preamble_label: str = "metadata",
) -> Dict[str, str]:
    """
    Split raw text into sections based on configured regex patterns.

    Parameters
    ----------
    raw_text:
        Full text extracted from the PDF.
    section_config:
        Mapping of section name -> {"pattern": "..."} items.
    preamble_label:
        Name used for text before the first matched section.
    """
    if not raw_text.strip():
        logger.warning("Empty text received by structurer.")
        return {}

    compiled_patterns = _compile_patterns(section_config)
    current_section = preamble_label
    buckets: Dict[str, List[str]] = {current_section: []}

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            buckets.setdefault(current_section, []).append("")
            continue

        lowered = line.lower()
        matched_section = _match_section(lowered, compiled_patterns)
        if matched_section:
            current_section = matched_section
            buckets.setdefault(current_section, []).append(line)
            continue

        buckets.setdefault(current_section, []).append(line)

    structured = {
        section: "\n".join(filter(None, lines)).strip()
        for section, lines in buckets.items()
        if any(fragment.strip() for fragment in lines)
    }
    return structured


def _compile_patterns(
    section_config: Mapping[str, Mapping[str, Optional[str]]]
) -> Iterable[tuple[str, re.Pattern]]:
    compiled = []
    for section_name, cfg in section_config.items():
        pattern = cfg.get("pattern")
        if not pattern:
            continue
        compiled.append((section_name, re.compile(pattern, re.IGNORECASE)))
    return compiled


def _match_section(
    lowered_line: str, compiled_patterns: Iterable[tuple[str, re.Pattern]]
) -> Optional[str]:
    for section_name, pattern in compiled_patterns:
        if pattern.match(lowered_line):
            return section_name
    return None

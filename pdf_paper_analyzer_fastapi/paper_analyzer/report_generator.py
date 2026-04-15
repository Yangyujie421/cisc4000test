"""Generate consolidated artifacts from agent analysis results."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Mapping


def generate(
    results: Iterable[Mapping[str, str]],
    output_dir: Path,
    pdf_path: Path,
    base_stem: str | None = None,
) -> Dict[str, Path]:
    """
    Persist the aggregated analysis to disk.

    Returns a dictionary containing the generated file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = base_stem or pdf_path.stem
    use_short_names = bool(base_stem) and output_dir.name == base_stem

    structured_results = {
        "pdf_file": str(pdf_path),
        "generated_at": timestamp,
        "sections": {entry["section"]: entry["analysis"] for entry in results},
    }

    json_name = "analysis.json" if use_short_names else f"{stem}_analysis_{timestamp}.json"
    json_path = output_dir / json_name
    json_path.write_text(json.dumps(structured_results, indent=2, ensure_ascii=False), encoding="utf-8")

    md_lines = [
        f"# Analysis Report for {stem}",
        f"_Generated at {timestamp}_",
        "",
    ]
    for section, analysis in structured_results["sections"].items():
        md_lines.append(f"## {section.title()}")
        md_lines.append(analysis)
        md_lines.append("")

    md_name = "analysis.md" if use_short_names else f"{stem}_analysis_{timestamp}.md"
    md_path = output_dir / md_name
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}

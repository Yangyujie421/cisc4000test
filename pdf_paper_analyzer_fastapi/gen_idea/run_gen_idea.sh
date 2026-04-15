#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REF_DIR="/home/yangyujie/zhangzihan/pdf_paper_analyzer_fastapi/ref"
OUTPUT_DIR="$ROOT_DIR/gen_idea/output"

TASK_TEXT="仅根据这些论文找未解决的空白点，并给出3个可验证的新idea"

python "$ROOT_DIR/gen_idea/run_gen_idea.py" \
  --ref_dir "$REF_DIR" \
  --task_text "$TASK_TEXT" \
  --output_dir "$OUTPUT_DIR"

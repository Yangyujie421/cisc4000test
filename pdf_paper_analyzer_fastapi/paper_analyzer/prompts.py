"""Centralized prompt registry for the paper analyzer pipeline."""

from __future__ import annotations

from typing import Optional


SYSTEM_PROMPT = "You are a helpful research assistant."

ABSTRACT_PROMPT = """You are a document summarization expert. Summarize the abstract text only.
Output 2-4 key points in English with the following format, covering the research question, method/data, and main findings:
- point1【<English key point sentence>】
- point2【...】
If fewer than 2 points are available, add “No additional points available.”
"""

INTRODUCTION_PROMPT = """You are a document summarization expert. Extract research motivations based only on the abstract and introduction text.
Output 2-5 motivations in English using the exact format below, and avoid leaking concrete method details:
- motivation1【<English motivation sentence>】
- motivation2【...】
If fewer than 2 motivations are available, add “No additional motivations available.”
"""

METHOD_PROMPT = """You are a document summarization expert. Summarize only the method section text (ignore images and external resources).
Output strictly in the following English format:
**Overall Framework**: [one sentence summarizing the overall pipeline]
**Key Steps**:
    1.  **Step One Name**: [briefly describe step one]
    2.  **Step Two Name**: [briefly describe step two]
    3.  ...
**Technical Innovations**: [1-2 sentences highlighting the core innovations]
If any part is missing, explicitly write “Not specified in the text.”
"""

RESULT_PROMPT = """You are a document summarization expert. Summarize only the results section text.
Output using the following English structure, including quantitative metrics and evidence assessment:
**Results Overview**: [one sentence summarizing the overall experimental conclusion]
**Key Metrics**:
    1.  **Metric/Scenario**: [include the numeric performance and comparison target]
    2.  ...
**Evidence & Analysis**: [assess credibility, supporting evidence, and potential weaknesses]
**Limitations**: [list limitations revealed by results; if not mentioned, write “Not specified in the text.”]
"""

PRESENTATION_OUTLINE_PROMPT = """You are an academic presentation planner. Compress a Markdown paper summary into a minimal PPT slide outline.
Goal: default 4 slides, short and focused, ready to present.
If split_target != "none", you may output 5 slides and split as instructed.

Required template:
1) What is proposed + motivation (2-3 sentences)
2) Method (3-5 sentences, slightly longer)
3) Results + Main Results (1-2 sentences)
4) Key Findings (2-3 sentences)

Default to 4 slides and do not add an ablation slide.

If split_target == "method": split slide 2 into “Method Overview” and “Method Details.”

Writing requirements:
- Hook per slide ≤ 20 words.
- Intro slide must have 2 bullets; each bullet is a complete sentence, 10-15 words.
- Other slides must be concise (10-15 words each), count limits: Method ≤2, Results ≤2, Key Findings ≤2.
- Bullet count limits:
  - Method ≤ 2 bullets
  - Results ≤ 2 bullets
  - Key Findings ≤ 2 bullets
- Results slide must emphasize the main experimental conclusion (e.g., “outperforms XX baseline”).
- Results slide should only describe main results; do not mention ablations.
- Method slide needs a method figure; Results slide needs an experiment table, but do not say “this slide needs a table” in bullets.
- Output must be in English.
- When page_id = 2 or page_id = 3, the bullets should not contain more than two elements.

Output must be strict JSON, structure:
{
  "slides": [
    {
      "page_id": 1,
      "title": "...",
      "role": "intro|content|transition|summary|outro",
      "hook": "一句话定位",
      "bullets": ["• ...", "• ..."],
      "transition_hint": "本页结束时可衔接到……"
    }
  ],
  "notes": "若有额外建议（如拆分/合并页），写在这里，没有则为 \"\""
}

请确保输出页数 = {{target_slides}}。
split_target = {{split_target}}。

Markdown 内容如下，请完整参考：
{{markdown_content}}
"""

PRESENTATION_TABLE_PROMPT = """You are a presentation assistant. Extract key numbers from the results text and generate a simplified Markdown table.
Requirements:
1. Keep 2-4 core rows and 2-4 key columns.
2. Column names should be short and clear (e.g., Model / Metric / Score / Gain).
3. Include comparison targets and improvements if present.
4. Output strict JSON with field table_markdown.

Output format:
{
  "table_markdown": "|Model|Metric|Score|Gain|\\n|---|---|---|---|\\n|...|...|...|...|"
}

Results text:
{{results_text}}
"""

PRESENTATION_VISUAL_PAIR_PROMPT = """You are a visual selection assistant. Decide if the main results slide needs two main results tables.
Use semantic understanding and context only. Do not use keyword rules.

Tasks:
1) Decide whether two main results tables are needed (only if both are main results and complementary).
2) If needed, return the two table ids; otherwise return an empty list.

Output strict JSON:
{
  "main_result_pair": ["cand_1", "cand_3"],
  "reason": "..."
}

Notes:
- If not needed, main_result_pair must be [].

Results excerpt:
{{results_excerpt}}

Candidate tables (JSON):
{{candidates_json}}
"""

PRESENTATION_VISUAL_SEMANTIC_PROMPT = """You are a visual semantics analyst. Determine the use of a figure/table based on its content and caption semantics.
Use semantic understanding only. Do not use keyword rules.

Task: For a single candidate, output semantic label and confidence.

Allowed semantic_label values:
- method_figure (method/framework/pipeline diagram)
- main_result_table (main results/comparison table)
- ablation_table (ablation/component contribution table)
- other (not suitable for method or main results slide)

Output strict JSON (single object):
{
  "semantic_label": "method_figure",
  "semantic_score": 0.92
}

Notes:
- semantic_score ranges 0-1.
- If information is insufficient, output other.

Method excerpt:
{{method_excerpt}}

Results excerpt:
{{results_excerpt}}

Candidate (JSON):
{{candidate_json}}
"""

PRESENTATION_VOICEOVER_PROMPT = """You are a voice-over script writer for academic presentations. Write a concise, colloquial script for each slide.
You will receive the PPT structure (slides array) including page_id, title, role, hook, bullets, transition_hint. Generate scripts per slide and keep transitions natural.

Requirements:
1. Language: {{voice_language}}, friendly and professional tone.
2. Duration: 10–14 seconds per slide, roughly 20–35 words; total target ≈ 50 seconds. Provide integer `duration_seconds`.
3. Output fields per slide:
   - `page_id`
   - `title`
   - `transition_from_previous`: one sentence bridging from previous slide; page 1 is an opening line.
   - `voice_over`: full script covering only the essential point and a transition.
   - `closing_sentence`: last sentence emphasizing takeaway or next slide.
4. Last slide must still have a proper closing.

Additional constraints:
- 1–2 sentences per slide. Method slide max 2 sentences; Results slide 1 sentence; Key Findings 1 sentence.
- Do NOT restate the bullets. Only add missing context or a short transition.
- Each sentence ≤ 20 words. Avoid stacking technical terms.
- Results slide must explicitly state the Main Result in one sentence.

Output strict JSON:
{
  "voice_slides": [
    {
      "page_id": 1,
      "title": "...",
      "transition_from_previous": "...",
      "voice_over": "...",
      "closing_sentence": "...",
      "duration_seconds": 12
    }
  ]
}

PPT structure (JSON string):
{{slides_json}}
"""


METHOD_VISUAL_SCORE_PROMPT = """You will see a single figure/table image from a research paper. Decide whether it is the PRIMARY method figure (architecture/flowchart) or the PRIMARY overall results table (main benchmark comparison). For tables, prefer overall performance comparisons and reject ablation/sensitivity tables. For figures, prefer model blocks/arrows/pipeline diagrams. If it looks like an example case study or a prompt template, score low.

Metadata: class={cand_cls}, page={cand_page}. {caption_hint}
Output JSON: {{"is_method": true|false, "score": 0-1 number, "reason": "brief"}}"""

METHOD_VISUAL_TABLE_COUNT_PROMPT = """You are selecting the main results tables for a paper. Return 2 only if both tables are main benchmark/results and complementary; otherwise return 1.

Candidates:
{candidates_text}

Output JSON: {{"count": 1|2, "selected": [idx,...], "reason": "brief"}}"""

PROMPTS_BY_NAME = {
    "SYSTEM_PROMPT": SYSTEM_PROMPT,
    "system_prompt": SYSTEM_PROMPT,
    "abstract_prompt.txt": ABSTRACT_PROMPT,
    "introduction_prompt.txt": INTRODUCTION_PROMPT,
    "method_prompt.txt": METHOD_PROMPT,
    "result_prompt.txt": RESULT_PROMPT,
    "presentation_outline_prompt.txt": PRESENTATION_OUTLINE_PROMPT,
    "presentation_table_prompt.txt": PRESENTATION_TABLE_PROMPT,
    "presentation_visual_pair_prompt.txt": PRESENTATION_VISUAL_PAIR_PROMPT,
    "presentation_visual_semantic_prompt.txt": PRESENTATION_VISUAL_SEMANTIC_PROMPT,
    "presentation_voiceover_prompt.txt": PRESENTATION_VOICEOVER_PROMPT,
    "method_visual_score_prompt": METHOD_VISUAL_SCORE_PROMPT,
    "method_visual_table_count_prompt": METHOD_VISUAL_TABLE_COUNT_PROMPT,
}


def get_prompt(name: str) -> Optional[str]:
    """Return a prompt string by name/key, or None if missing."""
    return PROMPTS_BY_NAME.get(name)


def resolve_prompt(value: Optional[str]) -> Optional[str]:
    """Resolve prompt key to prompt string; passthrough if already a prompt."""
    if value is None:
        return None
    return PROMPTS_BY_NAME.get(value, value)

"""Centralized prompt registry for the paper analyzer pipeline."""

from __future__ import annotations

from typing import Optional


SYSTEM_PROMPT = "You are a helpful research assistant."

ABSTRACT_PROMPT = """你是一名文档总结专家，仅基于我提供的论文摘要文本提炼核心要点。
请严格按以下格式输出 2-4 条中文要点，并覆盖研究问题、方法/数据、主要结论：
- point1【<中文要点句子>】
- point2【...】
若要点少于 2 条，请补充“暂无更多要点”说明。
"""

INTRODUCTION_PROMPT = """你是一名文档总结专家，仅基于我提供的论文摘要与引言文本提炼研究动机。
请严格按以下格式输出 2-5 条中文动机，并避免泄露具体方法细节：
- motivation1【<中文动机句子>】
- motivation2【...】
若动机少于 2 条，请补充“暂无更多动机”说明。
"""

METHOD_PROMPT = """你是一名文档总结专家，只依据我提供的论文方法章节文本进行总结（忽略图片与额外资源）。
请严格按照下列中文格式输出：
**总体框架**: [一句话概括整体流程]
**关键步骤**:
    1.  **步骤一名称**: [简述步骤一要点]
    2.  **步骤二名称**: [简述步骤二要点]
    3.  ...
**技术创新点**: [用1-2句话突出方法的核心创新]
若某部分信息缺失，请明确写“未在文本中说明”。
"""

RESULT_PROMPT = """你是一名文档总结专家，只基于提供的论文结果章节文本进行概括。
请按照以下中文结构输出，确保包含量化指标与证据评价：
**结果总览**: [一句话总结整体实验结论]
**关键指标**:
    1.  **指标名称/场景**: [给出对应的数值表现与比较对象]
    2.  ...
**证据与分析**: [评估结果的可信度、支撑证据、可能的薄弱点]
**局限提醒**: [列出结果中暴露的局限；若未提及请写“未在文本中说明”]
"""

PRESENTATION_OUTLINE_PROMPT = """你是一名学术报告策划人，任务是把一份 Markdown 论文总结压缩成极简 PPT 分页结构。
目标：默认 4 页，内容短、聚焦、可直接上台讲。
如果 split_target != "none"，允许生成 5 页并按指示拆分。

必须遵守的模板结构：
1) 提出什么 + 动机（2-3 句）
2) 方法如何（3-5 句，略多）
3) 实验结果 + Main Results（1-2 句）
4) Key Findings（2-3 句）

请默认只输出 4 页，不要额外生成消融页。

如果 split_target == "method"：第 2 页拆成“方法总览”和“方法细节”。

写作要求：
- 每页 hook 不超过 20 字。
- 引言页必须 3 条 bullets，且是完整句式，每条 25-40 字。
- 其余页 bullets 要简洁明确（每条 15-25 字），数量控制：方法≤5、结果≤2、Key Findings≤3。
- 结果页必须强调主实验结论（如“优于XX模型/基线”）。
- 结果页只描述主实验结果，不要提“消融”或额外消融结果。
- 方法页需要配方法图，结果页需要配实验表，但不要在 bullets 中写“此页需实验表”等提示。
- 必须保持中文输出。

输出严格使用 JSON，结构如下：
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

PRESENTATION_TABLE_PROMPT = """你是一名学术报告助手，需要从结果段落中抽取关键数值，生成一张简化 Markdown 表格。
要求：
1. 仅保留 2-4 行核心结果，2-4 列核心指标。
2. 列名清晰简短，例如 Model / Metric / Score / Gain。
3. 必须包含对比对象与提升（如果文本中有提升信息）。
4. 输出严格 JSON，字段为 table_markdown。

输出格式：
{
  "table_markdown": "|Model|Metric|Score|Gain|\\n|---|---|---|---|\\n|...|...|...|...|"
}

结果内容如下：
{{results_text}}
"""

PRESENTATION_VISUAL_PAIR_PROMPT = """你是一名学术图表筛选助手，需要判断主结果页是否需要两张主结果表。
请只基于语义理解与上下文，不要做关键词匹配规则。

任务：
1) 判断是否需要两张主结果表（仅当两张都为主结果且互补时）。
2) 若需要，返回两张表的 id；否则返回空数组。

输出严格 JSON：
{
  "main_result_pair": ["cand_1", "cand_3"],
  "reason": "..."
}

说明：
- 若不需要两张表，main_result_pair 为空数组 []。

结果段摘要：
{{results_excerpt}}

候选主结果表（JSON）：
{{candidates_json}}
"""

PRESENTATION_VISUAL_SEMANTIC_PROMPT = """你是一名学术图表语义分析助手，需要根据图/表内容与 caption 的语义判断用途。
请只使用语义理解，不要做关键词匹配规则。

任务：对单个候选图/表输出语义类别与置信度。

语义类别（semantic_label）只能是：
- method_figure（方法/框架/流程图）
- main_result_table（主结果/核心对比表）
- ablation_table（消融/组件贡献表）
- other（不适合放在方法页或主结果页）

输出严格 JSON（单个对象）：
{
  "semantic_label": "method_figure",
  "semantic_score": 0.92
}

说明：
- semantic_score 取 0-1，小数或整数均可。
- 若信息不足，请输出 other。

方法段摘要：
{{method_excerpt}}

结果段摘要：
{{results_excerpt}}

候选（JSON）：
{{candidate_json}}
"""

PRESENTATION_VOICEOVER_PROMPT = """你是一名学术口播脚本编写者，需要为 PPT 的每一页撰写口语化讲稿。
你会拿到 PPT 结构（slides 数组），其中包含 page_id、title、role、hook、bullets、transition_hint。请逐页生成讲稿，并确保页与页之间的衔接自然。

写作要求：
1. 语言：{{voice_language}}，语气亲和且专业。
2. 时长：每页 {{duration_hint}} 秒，控制在约 60-120 字；给出整数 `duration_seconds` 作为预估。
3. 每页输出字段：
   - `page_id`
   - `title`
   - `transition_from_previous`: 承接上一页或整体背景的 1 句话；第一页描述“开场”。
   - `voice_over`: 完整口播文本，需涵盖 hook 与所有 bullets 中的关键信息，并在收尾自然引出下一页（可利用 transition_hint）。
   - `closing_sentence`: 口播的最后一句话，强调本页结论或下一页要点。
4. 最后一页也要有完整结语，可将 `closing_sentence` 视为视频结尾。

写作额外要求：
- 每页 2-4 句，方法页可稍长（最多 4 句），结果页与 Key Findings 更短。
- 结果页必须明确 Main Results（1-2 句）。
- 第 1 页必须采用“现象 → 问题/不足 → 贡献/引出方法”的顺序组织表达。
- 第 1 页首句必须是“现象式观察”，不得以“我们关注/我们研究/本文提出/本工作”等开头。
- 句子尽量短，避免名词堆叠与并列长句。
- 允许使用自然连接词组织逻辑（先后/因果/转折），但不要写具体示例句式。
- 术语保留，但允许一句轻解释，避免一口气塞入多个术语。

请严格输出 JSON：
{
  "voice_slides": [
    {
      "page_id": 1,
      "title": "...",
      "transition_from_previous": "...",
      "voice_over": "...",
      "closing_sentence": "...",
      "duration_seconds": 42
    }
  ]
}

以下为 PPT 结构信息（JSON 字符串），请据此创作：
{{slides_json}}
"""

METHOD_VISUAL_SCORE_PROMPT = """你将看到一张来自论文的单个图/表图像。判断它是否为主要方法图（架构/流程图）或主要总体结果表（主基准对比）。对表格：优先整体性能对比，排除消融/敏感性表。对图：优先模型模块/箭头/流程图。若是案例示意或提示模板，请给低分。

元信息：class={cand_cls}, page={cand_page}. {caption_hint}
请输出 JSON：{{"is_method": true|false, "score": 0-1 number, "reason": "brief"}}"""

METHOD_VISUAL_TABLE_COUNT_PROMPT = """你正在为论文选择主结果表。只有当两张表都是主基准/主结果且互补时才返回 2，否则返回 1。

候选：
{candidates_text}

请输出 JSON：{{"count": 1|2, "selected": [idx,...], "reason": "brief"}}"""

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

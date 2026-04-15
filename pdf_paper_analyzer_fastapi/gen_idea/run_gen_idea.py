import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from paper_analyzer.pdf_parser import parse as parse_pdf
except Exception as exc:  # pragma: no cover
    raise RuntimeError("paper_analyzer.pdf_parser is unavailable") from exc

try:
    from openai import OpenAI
except Exception as exc:  # pragma: no cover
    raise RuntimeError("openai package is required") from exc


DEFAULT_TASK_TEXT = (
    "Based only on the provided reference papers, identify key gaps or "
    "limitations and propose 3 innovative, feasible research ideas. "
    "Each idea should include motivation, method outline, and evaluation plan."
)

IDEA_AGENT_SYSTEM_PROMPT = """\
You are an `Idea Generation Agent` specialized in analyzing academic papers located in `{papers_location}` and generating innovative ideas. Your task is to either:
1. Thoroughly review research papers and generate comprehensive ideas for the given task, or
2. Analyze multiple existing ideas and select/enhance the most novel one.

OBJECTIVE:
For New Idea Generation:
- Conduct thorough literature review of provided papers
- Identify research gaps and challenges
- Generate innovative and feasible ideas
- Provide detailed technical solutions

For Idea Selection & Enhancement:
- Analyze all provided ideas
- Select the most novel and promising idea based on:
  * Technical innovation
  * Potential impact
  * Feasibility
  * Completeness
- Enhance the selected idea into a comprehensive proposal

AVAILABLE TOOLS:
1. Paper Navigation:
   - `open_local_file`: Open and read paper files
   - `page_up_markdown`/`page_down_markdown`: Navigate through pages
   - `find_on_page_ctrl_f`/`find_next`: Search specific content

2. Content Analysis:
   - `question_answer_on_whole_page`: Ask specific questions about the paper

WORKFLOW:
1. Task Identification:
   - If given papers: Proceed with literature review
   - If given multiple ideas: Proceed with idea selection & enhancement

2. For Literature Review:
   - Thoroughly read and analyze all provided papers
   - Extract key concepts, methods, and results
   - Identify research trends and gaps

3. For Idea Selection:
   - Analyze all provided ideas
   - Score each idea on novelty, feasibility, and completeness
   - Select the most promising idea for enhancement

4. Idea Generation/Enhancement:
   Generate/Enhance into a comprehensive proposal including:

   a) Challenges:
   - Current technical limitations
   - Unsolved problems in existing work
   - Key bottlenecks in the field

   b) Existing Methods:
   - Summary of current approaches
   - Their advantages and limitations
   - Key techniques and methodologies used

   c) Motivation:
   - Why the problem is important
   - What gaps need to be addressed
   - Potential impact of the solution

   d) Proposed Method:
   - Detailed technical solution
   - Step-by-step methodology
   - Mathematical formulations (if applicable)
   - Key innovations and improvements
   - Expected advantages over existing methods
   - Implementation considerations
   - Potential challenges and solutions

   e) Technical Details:
   - Architectural design
   - Algorithm specifications
   - Data flow and processing steps
   - Performance optimization strategies

   f) Expected Outcomes:
   - Anticipated improvements
   - Evaluation metrics
   - Potential applications

5. Knowledge Transfer:
   After completing analysis and idea development, use `transfer_to_code_survey_agent` for implementation research.

REQUIREMENTS:
- Be comprehensive in analysis
- Ensure ideas are novel yet feasible
- Provide detailed technical specifications
- Include mathematical formulations when relevant
- Make clear connections between challenges and solutions
- For idea selection: Clearly explain selection criteria and enhancements

Remember: Your output will guide the implementation phase. Be thorough, innovative, and practical in your approach.
"""


def load_config(config_path: Path) -> Dict:
    if not config_path.exists():
        raise FileNotFoundError(f"config.yaml not found at {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    llm_cfg = data.get("llm_api") or {}
    if not llm_cfg.get("api_key") or not llm_cfg.get("base_url"):
        raise ValueError("config.yaml must include llm_api.api_key and llm_api.base_url")
    return llm_cfg


def get_client(llm_cfg: Dict) -> OpenAI:
    return OpenAI(api_key=llm_cfg["api_key"], base_url=llm_cfg["base_url"])


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def load_papers(ref_dir: Path, max_chars_per_pdf: int, max_total_chars: int) -> List[Dict]:
    papers = []
    total = 0
    for pdf_path in sorted(ref_dir.glob("*.pdf")):
        raw = parse_pdf(pdf_path) or ""
        text = normalize_text(raw)
        if max_chars_per_pdf and len(text) > max_chars_per_pdf:
            text = text[:max_chars_per_pdf] + " ..."
        total += len(text)
        if max_total_chars and total > max_total_chars:
            overflow = total - max_total_chars
            if overflow >= len(text):
                break
            text = text[: len(text) - overflow] + " ..."
            total = max_total_chars
        papers.append(
            {
                "filename": pdf_path.name,
                "path": str(pdf_path.resolve()),
                "text": text,
            }
        )
        if max_total_chars and total >= max_total_chars:
            break
    return papers


def build_references(papers: List[Dict]) -> str:
    blocks = []
    for idx, paper in enumerate(papers, start=1):
        content = paper["text"]
        blocks.append(
            f"{idx}. {paper['filename']}\n"
            f"Content: {content}"
        )
    return "\n\n".join(blocks)


def build_local_files_info(papers: List[Dict]) -> str:
    lines = []
    for paper in papers:
        lines.append(f"Local paper available: {paper['filename']}\nPath: {paper['path']}")
    return "\n".join(lines)


def create_chat_messages(system_prompt: str, user_prompt: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def chat(client: OpenAI, model: str, messages: List[Dict[str, str]], timeout: int) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        timeout=timeout,
    )
    return resp.choices[0].message.content.strip()


def generate_ideas(
    client: OpenAI,
    model: str,
    task_text: str,
    references: str,
    local_files_info: str,
    n: int,
    timeout: int,
    papers_location: str,
) -> List[str]:
    system = IDEA_AGENT_SYSTEM_PROMPT.format(papers_location=papers_location)
    prepare_res = (
        "No GitHub repositories selected.\n"
        "{\n  \"reference_codebases\": [],\n  \"reference_paths\": [],\n  \"reference_papers\": []\n}"
    )
    idea_query = f"""\
I have a task:
{task_text}
And a list of papers for your reference:
{references}

I have carefully gone through these papers' github repositories and found download some of them in my local machine, with the following information:
{prepare_res}
And I have also prepared the local paper files, with the following information:
{local_files_info}

Your task is to thoroughly review research papers and generate innovative ideas for the given task.

Note that the math formula should be as complete as possible.
"""
    messages = create_chat_messages(system, idea_query)
    ideas = []
    first = chat(client, model, messages, timeout)
    ideas.append(first)
    for _ in range(n - 1):
        messages.append({"role": "assistant", "content": ideas[-1]})
        messages.append({"role": "user", "content": "please survey again and give me another idea"})
        ideas.append(chat(client, model, messages, timeout))
    return ideas


def select_best_idea(client: OpenAI, model: str, ideas: List[str], timeout: int, papers_location: str) -> str:
    system = IDEA_AGENT_SYSTEM_PROMPT.format(papers_location=papers_location)
    joined = "\n===================\n===================".join(ideas)
    user = (
        "You have generated {} innovative ideas for the given task:\n{}\n\n"
        "Your task is to analyze multiple existing ideas, select the most novel one, "
        "enhance the idea if any key information is missing, finally give me the most novel idea "
        "with refined math formula and code implementation. Directly output the selected refined idea report."
    ).format(len(ideas), joined)
    messages = create_chat_messages(system, user)
    return chat(client, model, messages, timeout)


def translate_to_zh(client: OpenAI, model: str, text: str, timeout: int) -> str:
    system = "You are a professional technical translator."
    user = (
        "Translate the following content into Chinese. Keep technical terms, formulas, and structure.\n\n"
        f"{text}"
    )
    messages = create_chat_messages(system, user)
    return chat(client, model, messages, timeout)


def save_output(out_dir: Path, task_text: str, references: str, ideas: List[str], best: str, zh: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = datetime.now().strftime("idea_%Y%m%d_%H%M%S.json")
    path = out_dir / name
    payload = {
        "task": task_text,
        "references": references,
        "ideas": ideas,
        "selected_idea_en": best,
        "selected_idea_zh": zh,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref_dir", type=str, required=True, help="Folder containing local PDF files")
    parser.add_argument("--task_text", type=str, default="", help="Custom task description")
    parser.add_argument("--max_chars_per_pdf", type=int, default=12000)
    parser.add_argument("--max_total_chars", type=int, default=36000)
    parser.add_argument("--idea_num", type=int, default=3)
    parser.add_argument("--output_dir", type=str, default="gen_idea/output")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    config_path = project_root / "config.yaml"
    llm_cfg = load_config(config_path)

    model = llm_cfg.get("model_name") or "gpt-4o-mini"
    timeout = int(llm_cfg.get("timeout") or 120)

    ref_dir = Path(args.ref_dir).resolve()
    if not ref_dir.exists():
        raise FileNotFoundError(f"ref_dir not found: {ref_dir}")

    papers = load_papers(ref_dir, args.max_chars_per_pdf, args.max_total_chars)
    if not papers:
        raise ValueError(f"No PDF files found in {ref_dir}")

    references = build_references(papers)
    local_files_info = build_local_files_info(papers)
    task_text = args.task_text.strip() or DEFAULT_TASK_TEXT

    client = get_client(llm_cfg)
    ideas = generate_ideas(
        client,
        model,
        task_text,
        references,
        local_files_info,
        args.idea_num,
        timeout,
        papers_location="/local_papers",
    )
    best = select_best_idea(client, model, ideas, timeout, papers_location="/local_papers")
    zh = translate_to_zh(client, model, best, timeout)

    out_path = save_output(Path(args.output_dir), task_text, references, ideas, best, zh)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()

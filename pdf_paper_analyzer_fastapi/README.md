# PDF Paper Analyzer – FastAPI Service

This folder contains a FastAPI wrapper around the original CLI workflow located in `../pdf_paper_analyzer`. It exposes a REST endpoint that accepts a PDF upload, invokes the existing pipeline, and returns the generated artifact paths.

## Quick start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Launch the API:
   ```bash
   uvicorn app.main:app --reload
   ```
3. Send a request:
   ```bash
   curl -X POST "http://127.0.0.1:8000/analyze" \
     -F "file=@/path/to/paper.pdf"
   ```
4. 打开浏览器访问 `http://127.0.0.1:8000/`，使用内置前端上传文件并查看返回结果（页面会显示生成报告的 JSON 与 Markdown 内容）。

The response includes the JSON and Markdown report locations that the pipeline writes under `data/output`.

Image assets: 当上传 PDF 时，服务会额外提取内嵌图片并保存在 `data/output/<文件名>_images/` 下，API 响应里新增 `images` 数组（含页码、路径和 `/output/...` 访问 URL），前端会直接显示可访问的图片。

Method visuals: 集成 DocLayout-YOLO 版面检测（默认开启，需要安装 `doclayout-yolo` 依赖），会渲染 PDF 页并检测 `figure/table`，再调用同样的 LLM（gpt-5-mini）打分挑选“方法核心图/表”。结果出现在响应的 `method_assets.figure/table` 字段（含页码、裁剪路径、检测置信度、LLM 评分）。
若想拿到全部检测到的图/表裁剪，可直接读取 API 响应中的 `layout_detections`（含每个裁剪的路径与 `/output/...` URL），无需前端。

每次请求的所有产物（Markdown/JSON、结构化文本、图片裁剪、版面检测结果等）都会集中存放在 `data/output/<原文件名>_<时间戳>/` 下，便于归档。

Note: generated artifacts (for example `responses/` and `data/**/output/`) are runtime outputs and are ignored by default via `.gitignore`.

## Presentation-friendly outputs

In addition to the Markdown/JSON summaries, the service now derives a PPT-ready slide plan and per-slide voice-over script:

- Slide planning prompt restructures the Markdown into 4–10 slides (title + key bullet points).
- Voice-over prompt turns each slide into一段 30–50 秒的自然讲稿。
- The API response只包含三块数据：`markdown_summary`（PPT Markdown 文本）、`slides`（分页 JSON，含 `page_id/title/hook/bullets`，每条 bullet 均含具体事实，直接可用）以及 `voice_scripts`（逐页口播稿）；同时附带 `progress` 列表和 `bundle_path`，指向单一的 `presentation_bundle.json`（位于 `data/output/<原文件名>_<时间戳>/`，其中已整合 Markdown、Slides、Voice Scripts）。
- Artifacts are stored under `data/output/<原文件名>_<时间戳>/analysis.json`, `analysis.md`, and `presentation_bundle.json` for downstream workflows.

## Configuration

The service reuses `config.yaml` from the CLI project. Override the config path by setting the `PDF_ANALYZER_CONFIG` environment variable before starting Uvicorn.

## Project layout

- `app/`: FastAPI app, models, and service logic.
- `paper_analyzer/`: Original pipeline modules reused by the API.
- `config.yaml`, `prompts/`, `data/`: Supporting assets copied from the CLI project.

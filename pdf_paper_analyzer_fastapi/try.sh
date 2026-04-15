#!/bin/sh
set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

API_URL=${API_URL:-"https://uu824848-b5b6-70f5741a.westc.gpuhub.com:8443"}
FILE_PATH=${FILE_PATH:-"$SCRIPT_DIR/GraphEval.pdf"} #设置pdf路径
REQUEST_ID=${REQUEST_ID:-""}  #自动生成
BG_COLOR=${BG_COLOR:-""} #设置背景颜色，十六进制
SPEED_FACTOR=${SPEED_FACTOR:-""} #视频加速倍数，默认为1
REF_AUDIO=${REF_AUDIO:-""} # 参考音频的路径，可不设置
OUTPUT_JSON=${OUTPUT_JSON:-""} #输出口播json的路径，可不设置
OUTPUT_VIDEO=${OUTPUT_VIDEO:-""} # 视频输出路径，可不设置
POLL_INTERVAL=${POLL_INTERVAL:-2}
POLL_TIMEOUT=${POLL_TIMEOUT:-1800}
DOWNLOAD_VIDEO=${DOWNLOAD_VIDEO:1} # 是否下载视频，1为下载
LLM_BASE_URL=${LLM_BASE_URL:-""}
LLM_API_KEY=${LLM_API_KEY:-""}
LLM_MODEL_NAME=${LLM_MODEL_NAME:-""}

usage() {
  cat <<'EOF'
Usage:
  ./try.sh [options]

Options:
  --file PATH            PDF path (default: ./GraphEval.pdf)
  --api-url URL          API base URL (default: http://127.0.0.1:8005)
  --request-id ID        Request ID (default: auto-generated)
  --bg-color COLOR       Slide background color (e.g. white, #F8FAFC)
  --speed-factor FLOAT   Optional speed factor (>0). 1 means no speed-up.
  --ref-audio PATH       Optional reference audio path.
  --output-json PATH     Save /analyze response JSON.
  --output-video PATH    Download final video to this path.
  --poll-interval SEC    Polling interval seconds (default: 2)
  --poll-timeout SEC     Polling timeout seconds (default: 1800)
  --download-video 0|1   Whether to download final video (default: 1)
  --llm-base-url URL     Optional LLM base URL override for /analyze
  --llm-api-key KEY      Optional LLM API key override for /analyze
  --llm-model-name NAME  Optional LLM model name override for /analyze
  -h, --help             Show this message

Environment variables with the same names are also supported.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --file)
      FILE_PATH=$2
      shift 2
      ;;
    --api-url)
      API_URL=$2
      shift 2
      ;;
    --request-id)
      REQUEST_ID=$2
      shift 2
      ;;
    --bg-color)
      BG_COLOR=$2
      shift 2
      ;;
    --speed-factor)
      SPEED_FACTOR=$2
      shift 2
      ;;
    --ref-audio)
      REF_AUDIO=$2
      shift 2
      ;;
    --output-json)
      OUTPUT_JSON=$2
      shift 2
      ;;
    --output-video)
      OUTPUT_VIDEO=$2
      shift 2
      ;;
    --poll-interval)
      POLL_INTERVAL=$2
      shift 2
      ;;
    --poll-timeout)
      POLL_TIMEOUT=$2
      shift 2
      ;;
    --download-video)
      DOWNLOAD_VIDEO=$2
      shift 2
      ;;
    --llm-base-url)
      LLM_BASE_URL=$2
      shift 2
      ;;
    --llm-api-key)
      LLM_API_KEY=$2
      shift 2
      ;;
    --llm-model-name)
      LLM_MODEL_NAME=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [ ! -f "$FILE_PATH" ]; then
  echo "File not found: $FILE_PATH" >&2
  exit 1
fi

if [ -z "$REQUEST_ID" ]; then
  REQUEST_ID=$(python - <<'PY'
import uuid
print(uuid.uuid4().hex)
PY
)
fi

python - "$POLL_INTERVAL" "$POLL_TIMEOUT" <<'PY'
import sys
for idx, value in enumerate(sys.argv[1:], start=1):
    try:
        num = float(value)
    except ValueError:
        raise SystemExit(f"Invalid numeric value: {value}")
    if num <= 0:
        name = "poll_interval" if idx == 1 else "poll_timeout"
        raise SystemExit(f"{name} must be > 0")
PY

if [ -n "$SPEED_FACTOR" ]; then
  python - "$SPEED_FACTOR" <<'PY'
import sys
v = float(sys.argv[1])
if v <= 0:
    raise SystemExit("speed_factor must be > 0")
PY
fi

echo "Request ID: $REQUEST_ID"
echo "API URL: $API_URL"
echo "PDF: $FILE_PATH"
[ -n "$BG_COLOR" ] && echo "Background color: $BG_COLOR"
[ -n "$SPEED_FACTOR" ] && echo "Speed factor: ${SPEED_FACTOR}x"

make_temp() {
  mktemp 2>/dev/null || mktemp -t p2vtmp
}

request_json() {
  method=$1
  url=$2
  body_file=$3
  shift 3
  status=$(curl -sS -o "$body_file" -w "%{http_code}" -X "$method" "$url" "$@")
  if [ "$status" -lt 200 ] || [ "$status" -ge 300 ]; then
    echo "Request failed: $method $url (HTTP $status)" >&2
    cat "$body_file" >&2 || true
    return 1
  fi
  return 0
}

parse_json_field() {
  file=$1
  key=$2
  python - "$file" "$key" <<'PY'
import json
import sys
from pathlib import Path

file_path = Path(sys.argv[1])
key = sys.argv[2]
data = json.loads(file_path.read_text(encoding="utf-8"))
value = data.get(key)
if value is None:
    raise SystemExit(1)
if isinstance(value, (dict, list)):
    print(json.dumps(value, ensure_ascii=False))
else:
    print(value)
PY
}

parse_job_result() {
  file=$1
  python - "$file" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(data.get("status", ""))
print(data.get("video_url") or "")
PY
}

extract_video_path_from_url() {
  video_url=$1
  python - "$video_url" <<'PY'
import sys
from urllib.parse import parse_qs, urlparse, unquote

raw = sys.argv[1]
parsed = urlparse(raw)
qs = parse_qs(parsed.query)
value = qs.get("video_path", [""])[0]
print(unquote(value))
PY
}

poll_video_job() {
  status_endpoint=$1
  job_id=$2
  label=$3

  started=$(date +%s)
  while :; do
    now=$(date +%s)
    elapsed=$((now - started))
    if [ "$elapsed" -gt "$POLL_TIMEOUT" ]; then
      echo "$label timed out after ${POLL_TIMEOUT}s (job_id=$job_id)" >&2
      return 1
    fi

    response_file=$(make_temp)
    request_json GET "$API_URL/$status_endpoint/$job_id" "$response_file"

    parsed=$(parse_job_result "$response_file")
    job_status=$(printf '%s\n' "$parsed" | sed -n '1p')
    video_url=$(printf '%s\n' "$parsed" | sed -n '2p')
    rm -f "$response_file"

    case "$job_status" in
      done)
        echo "$video_url"
        return 0
        ;;
      failed)
        echo "$label failed (job_id=$job_id)" >&2
        return 1
        ;;
      queued|running|"")
        echo "$label status: ${job_status:-unknown} (elapsed ${elapsed}s)" >&2
        sleep "$POLL_INTERVAL"
        ;;
      *)
        echo "$label status: $job_status (elapsed ${elapsed}s)" >&2
        sleep "$POLL_INTERVAL"
        ;;
    esac
  done
}

ANALYZE_FILE=$(make_temp)
VIDEO_FILE=$(make_temp)
SPEED_FILE=$(make_temp)
trap 'rm -f "$ANALYZE_FILE" "$VIDEO_FILE" "$SPEED_FILE"' EXIT

FILE_NAME=$(basename "$FILE_PATH")
set -- \
  -F "file=@${FILE_PATH};filename=${FILE_NAME}" \
  -F "request_id=${REQUEST_ID}"
[ -n "$LLM_BASE_URL" ] && set -- "$@" -F "llm_base_url=${LLM_BASE_URL}"
[ -n "$LLM_API_KEY" ] && set -- "$@" -F "llm_api_key=${LLM_API_KEY}"
[ -n "$LLM_MODEL_NAME" ] && set -- "$@" -F "llm_model_name=${LLM_MODEL_NAME}"

echo "Step 1/4: Analyze PDF ..."
request_json POST "$API_URL/analyze" "$ANALYZE_FILE" "$@"

if [ -n "$OUTPUT_JSON" ]; then
  mkdir -p "$(dirname "$OUTPUT_JSON")"
  cp "$ANALYZE_FILE" "$OUTPUT_JSON"
  echo "Analyze response saved to: $OUTPUT_JSON"
fi

bundle_path=$(parse_json_field "$ANALYZE_FILE" "bundle_path" || true)
run_output_dir=$(parse_json_field "$ANALYZE_FILE" "run_output_dir" || true)

if [ -z "$bundle_path" ] || [ -z "$run_output_dir" ]; then
  echo "Missing bundle_path or run_output_dir in /analyze response." >&2
  cat "$ANALYZE_FILE" >&2
  exit 1
fi

video_payload=$(python - "$bundle_path" "$run_output_dir" "$REF_AUDIO" "$BG_COLOR" <<'PY'
import json
import sys

bundle_path, run_output_dir, ref_audio, bg_color = sys.argv[1:]
payload = {
    "bundle_path": bundle_path,
    "run_output_dir": run_output_dir,
}
if ref_audio:
    payload["ref_audio"] = ref_audio
if bg_color:
    payload["bg_color"] = bg_color
print(json.dumps(payload, ensure_ascii=False))
PY
)

echo "Step 2/4: Submit video generation job ..."
request_json POST "$API_URL/generate-video" "$VIDEO_FILE" \
  -H "Content-Type: application/json" \
  -d "$video_payload"

video_job_id=$(parse_json_field "$VIDEO_FILE" "job_id" || true)
if [ -z "$video_job_id" ]; then
  echo "Failed to get video job_id." >&2
  cat "$VIDEO_FILE" >&2
  exit 1
fi
echo "Video job id: $video_job_id"

echo "Step 3/4: Poll video generation ..."
video_url=$(poll_video_job "video-status" "$video_job_id" "Video generation")
if [ -z "$video_url" ]; then
  echo "Video generation completed but no video_url returned." >&2
  exit 1
fi

final_video_url=$video_url
final_video_path=$(extract_video_path_from_url "$video_url")

if [ -n "$SPEED_FACTOR" ]; then
  speed_cmp=$(python - "$SPEED_FACTOR" <<'PY'
import sys
v = float(sys.argv[1])
print("same" if abs(v - 1.0) < 1e-9 else "diff")
PY
)

  if [ "$speed_cmp" = "diff" ]; then
    speed_payload=$(python - "$final_video_path" "$SPEED_FACTOR" <<'PY'
import json
import sys
video_path, speed_factor = sys.argv[1], float(sys.argv[2])
print(json.dumps({"video_path": video_path, "speed_factor": speed_factor}, ensure_ascii=False))
PY
)

    echo "Step 4/4: Submit speed-up job ..."
    request_json POST "$API_URL/speed-up-video" "$SPEED_FILE" \
      -H "Content-Type: application/json" \
      -d "$speed_payload"

    speed_job_id=$(parse_json_field "$SPEED_FILE" "job_id" || true)
    if [ -z "$speed_job_id" ]; then
      echo "Failed to get speed-up job_id." >&2
      cat "$SPEED_FILE" >&2
      exit 1
    fi
    echo "Speed-up job id: $speed_job_id"

    final_video_url=$(poll_video_job "speed-up-status" "$speed_job_id" "Speed-up")
    if [ -z "$final_video_url" ]; then
      echo "Speed-up completed but no video_url returned." >&2
      exit 1
    fi
    final_video_path=$(extract_video_path_from_url "$final_video_url")
  else
    echo "Step 4/4: speed_factor=1, skip speed-up."
  fi
else
  echo "Step 4/4: speed_factor not set, skip speed-up."
fi

echo "Final server video path: $final_video_path"
echo "Final download URL: ${API_URL}${final_video_url}"

if [ "$DOWNLOAD_VIDEO" = "1" ]; then
  if [ -z "$OUTPUT_VIDEO" ]; then
    OUTPUT_VIDEO="$run_output_dir/video/final_output.mp4"
  fi
  mkdir -p "$(dirname "$OUTPUT_VIDEO")"
  echo "Downloading final video to: $OUTPUT_VIDEO"
  curl -sS -L "${API_URL}${final_video_url}" -o "$OUTPUT_VIDEO"
  echo "Done: $OUTPUT_VIDEO"
fi

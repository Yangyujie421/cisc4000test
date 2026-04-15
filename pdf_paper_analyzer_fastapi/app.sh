#!/bin/sh
set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
LOG_FILE="$SCRIPT_DIR/app.log"
PID_FILE="$SCRIPT_DIR/app.pid"
PORT=${PORT:-6008}
CMD_PATTERN="uvicorn .*app.main:app"

kill_port() {
  if command -v lsof >/dev/null 2>&1; then
    PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
      kill $PIDS >/dev/null 2>&1 || true
      sleep 0.5
      kill -9 $PIDS >/dev/null 2>&1 || true
    fi
    return
  fi
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
    return
  fi
  if command -v ss >/dev/null 2>&1; then
    PIDS=$(ss -ltnp "sport = :$PORT" 2>/dev/null | awk -F'pid=' 'NR>1 {print $2}' | awk -F',' '{print $1}' | sort -u)
    if [ -n "$PIDS" ]; then
      kill $PIDS >/dev/null 2>&1 || true
      sleep 0.5
      kill -9 $PIDS >/dev/null 2>&1 || true
    fi
  fi
}

cd "$SCRIPT_DIR"

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" >/dev/null 2>&1; then
    echo "Stopping existing service (PID $PID)..."
    PGID=$(ps -o pgid= -p "$PID" | tr -d ' ')
    if [ -n "$PGID" ]; then
      kill -- "-$PGID" >/dev/null 2>&1 || true
    else
      kill "$PID" >/dev/null 2>&1 || true
    fi

    for _ in 1 2 3 4 5 6 7 8 9 10; do
      if pgrep -f "$CMD_PATTERN" >/dev/null 2>&1; then
        sleep 0.5
      else
        break
      fi
    done
    if pgrep -f "$CMD_PATTERN" >/dev/null 2>&1; then
      echo "Force killing lingering uvicorn processes..."
      pkill -9 -f "$CMD_PATTERN" >/dev/null 2>&1 || true
    fi
    kill_port
  fi
  rm -f "$PID_FILE"
fi

nohup uvicorn app.main:app --host 0.0.0.0 --port "$PORT" >"$LOG_FILE" 2>&1 &
PID=$!
echo "$PID" >"$PID_FILE"

echo "Service started on port 8005 (PID $PID). Logs: $LOG_FILE"

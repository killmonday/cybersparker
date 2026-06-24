#!/bin/sh
set -eu

# Kill any existing celery workers/beat to prevent name conflicts
echo "[start_celery] cleaning up existing celery workers..."
pkill -f "celery -A cybersparker worker" 2>/dev/null || true
pkill -f "celery -A cybersparker beat" 2>/dev/null || true
sleep 1

ulimit -n 65535
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"
LOG_DIR="${CELERY_LOG_DIR:-$SCRIPT_DIR/error_log/celery}"
MAIN_LOG="$LOG_DIR/worker.log"
GEVENT_LOG="$LOG_DIR/worker_gevent.log"
BEAT_LOG="$LOG_DIR/beat.log"
MAIN_CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-4}"

mkdir -p "$LOG_DIR"

# Rotate old logs to avoid ever-growing files
for f in "$MAIN_LOG" "$GEVENT_LOG" "$BEAT_LOG"; do
  if [ -f "$f" ] && [ "$(wc -c < "$f")" -gt 10485760 ]; then
    mv "$f" "${f}.old" 2>/dev/null || true
  fi
done

echo "[start_celery] main worker log: $MAIN_LOG"
echo "[start_celery] gevent worker log: $GEVENT_LOG"
echo "[start_celery] beat log: $BEAT_LOG"
echo "[start_celery] main worker concurrency: $MAIN_CONCURRENCY"

HOSTNAME=$(hostname 2>/dev/null || echo "dev")

echo "[start_celery] starting beat scheduler"
celery -A cybersparker beat \
  -l INFO >>"$BEAT_LOG" 2>&1 &
BEAT_PID=$!

echo "[start_celery] starting main worker"
celery -A cybersparker worker \
  -n "worker_main@${HOSTNAME}" \
  -c "$MAIN_CONCURRENCY" \
  -Q auto_scan,batch_scan,result_writer,maintenance,dir_scan,poc_generation \
  -l INFO >>"$MAIN_LOG" 2>&1 &
MAIN_PID=$!

echo "[start_celery] starting gevent worker"
celery -A cybersparker worker \
  -n "worker_gevent@${HOSTNAME}" \
  -P solo -c 1 \
  -Q batch_scan_gevent \
  -l INFO >>"$GEVENT_LOG" 2>&1 &
GEVENT_PID=$!

cleanup() {
  kill "$MAIN_PID" "$GEVENT_PID" "$BEAT_PID" 2>/dev/null || true
  wait "$MAIN_PID" 2>/dev/null || true
  wait "$GEVENT_PID" 2>/dev/null || true
  wait "$BEAT_PID" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

echo "[start_celery] started (main=$MAIN_PID, gevent=$GEVENT_PID, beat=$BEAT_PID)"

STATUS=0
while kill -0 "$MAIN_PID" 2>/dev/null && kill -0 "$GEVENT_PID" 2>/dev/null && kill -0 "$BEAT_PID" 2>/dev/null; do
  sleep 1
done

echo "[start_celery] a process exited, shutting down..."

if kill -0 "$MAIN_PID" 2>/dev/null; then
  wait "$GEVENT_PID" || STATUS=$?
else
  wait "$MAIN_PID" || STATUS=$?
fi

cleanup
exit "$STATUS"

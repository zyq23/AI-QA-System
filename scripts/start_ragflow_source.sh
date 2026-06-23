#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAGFLOW_DIR="${ROOT_DIR}/ragflow"
LOG_DIR="${RAGFLOW_DIR}/logs"
PID_DIR="${RAGFLOW_DIR}/run"

mkdir -p "${LOG_DIR}" "${PID_DIR}"

"${ROOT_DIR}/scripts/setup_ragflow_source.sh"
"${ROOT_DIR}/scripts/start_ragflow_base.sh"

if [[ ! -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  echo "Missing root virtualenv python: ${ROOT_DIR}/.venv/bin/python" >&2
  exit 1
fi

if [[ ! -f "${PID_DIR}/local_embedding.pid" ]] || ! kill -0 "$(cat "${PID_DIR}/local_embedding.pid")" 2>/dev/null; then
  setsid "${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/scripts/local_embedding_service.py" >"${LOG_DIR}/local_embedding.log" 2>&1 < /dev/null &
  echo $! >"${PID_DIR}/local_embedding.pid"
fi

for _ in $(seq 1 90); do
  if curl -fsS -m 2 http://127.0.0.1:6380/healthz >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

cd "${RAGFLOW_DIR}"
source .venv/bin/activate
export PYTHONPATH="${RAGFLOW_DIR}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HUB_DOWNLOAD_TIMEOUT="${HF_HUB_DOWNLOAD_TIMEOUT:-600}"
export HF_HUB_ETAG_TIMEOUT="${HF_HUB_ETAG_TIMEOUT:-120}"
export DOC_ENGINE="${DOC_ENGINE:-infinity}"
export COMPOSE_PROFILES="${COMPOSE_PROFILES:-infinity,tei-cpu,cpu}"
export RAGFLOW_LOCAL_EMBED_TIMEOUT="${RAGFLOW_LOCAL_EMBED_TIMEOUT:-180}"

python "${ROOT_DIR}/scripts/configure_ragflow_models.py"

JEMALLOC_PATH=""
if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists jemalloc; then
  JEMALLOC_PATH="$(pkg-config --variable=libdir jemalloc)/libjemalloc.so"
fi

if [[ ! -f "${PID_DIR}/task_executor.pid" ]] || ! kill -0 "$(cat "${PID_DIR}/task_executor.pid")" 2>/dev/null; then
  if [[ -n "${JEMALLOC_PATH}" && -f "${JEMALLOC_PATH}" ]]; then
    setsid env LD_PRELOAD="${JEMALLOC_PATH}" python rag/svr/task_executor.py 1 >"${LOG_DIR}/task_executor.log" 2>&1 < /dev/null &
  else
    setsid python rag/svr/task_executor.py 1 >"${LOG_DIR}/task_executor.log" 2>&1 < /dev/null &
  fi
  echo $! >"${PID_DIR}/task_executor.pid"
fi

if [[ ! -f "${PID_DIR}/ragflow_server.pid" ]] || ! kill -0 "$(cat "${PID_DIR}/ragflow_server.pid")" 2>/dev/null; then
  setsid python api/ragflow_server.py >"${LOG_DIR}/ragflow_server.log" 2>&1 < /dev/null &
  echo $! >"${PID_DIR}/ragflow_server.pid"
fi

for _ in $(seq 1 120); do
  server_ok=false
  worker_ok=false
  if [[ -f "${PID_DIR}/ragflow_server.pid" ]] && kill -0 "$(cat "${PID_DIR}/ragflow_server.pid")" 2>/dev/null; then
    server_ok=true
  fi
  if [[ -f "${PID_DIR}/task_executor.pid" ]] && kill -0 "$(cat "${PID_DIR}/task_executor.pid")" 2>/dev/null; then
    worker_ok=true
  fi
  if [[ "${server_ok}" == true ]] && [[ "${worker_ok}" == true ]] && curl -sS -m 2 http://127.0.0.1:9380/ >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "task_executor pid: $(cat "${PID_DIR}/task_executor.pid")"
echo "ragflow_server pid: $(cat "${PID_DIR}/ragflow_server.pid")"
echo "local_embedding pid: $(cat "${PID_DIR}/local_embedding.pid")"
tail -n 20 "${LOG_DIR}/ragflow_server.log" || true

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAGFLOW_DIR="${ROOT_DIR}/ragflow"
PID_DIR="${RAGFLOW_DIR}/run"

for name in ragflow_server task_executor local_embedding; do
  pid_file="${PID_DIR}/${name}.pid"
  if [[ -f "${pid_file}" ]]; then
    pid="$(cat "${pid_file}")"
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}"
    fi
    rm -f "${pid_file}"
  fi
done

if docker ps -a --format '{{.Names}}' | grep -qx 'ragflow-tei-cpu'; then
  docker rm -f ragflow-tei-cpu >/dev/null || true
fi

cd "${RAGFLOW_DIR}"
DOC_ENGINE=infinity docker compose \
  -f docker/docker-compose-base.yml \
  -f docker/docker-compose-base.mirror.yml \
  down

echo "RAGFlow source services stopped."

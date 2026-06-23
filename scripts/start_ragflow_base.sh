#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAGFLOW_DIR="${ROOT_DIR}/ragflow"

cd "${RAGFLOW_DIR}"

DOC_ENGINE=infinity docker compose \
  -f docker/docker-compose-base.yml \
  -f docker/docker-compose-base.mirror.yml \
  up -d mysql minio redis infinity

docker compose -f docker/docker-compose-base.yml -f docker/docker-compose-base.mirror.yml ps

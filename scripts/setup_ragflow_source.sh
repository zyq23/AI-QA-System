#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAGFLOW_DIR="${ROOT_DIR}/ragflow"
VENDOR_DIR="${RAGFLOW_DIR}/vendor"
WHEEL_NAME="en_core_web_sm-3.8.0-py3-none-any.whl"
WHEEL_URL="https://ghfast.top/https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/${WHEEL_NAME}"
PYTHON_VERSION="${RAGFLOW_PYTHON_VERSION:-3.13}"
PYTHON_MIRROR="${UV_PYTHON_INSTALL_MIRROR:-https://registry.npmmirror.com/-/binary/python-build-standalone/}"
PYPI_INDEX="${UV_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

mkdir -p "${VENDOR_DIR}"

if [[ ! -f "${VENDOR_DIR}/${WHEEL_NAME}" ]]; then
  curl -L --fail --retry 3 --connect-timeout 15 "${WHEEL_URL}" -o "${VENDOR_DIR}/${WHEEL_NAME}"
fi

cd "${RAGFLOW_DIR}"

UV_PYTHON_INSTALL_MIRROR="${PYTHON_MIRROR}" uv python install "${PYTHON_VERSION}"
UV_INDEX_URL="${PYPI_INDEX}" uv sync --python "${PYTHON_VERSION}" --frozen --no-install-package en-core-web-sm
uv pip install "${VENDOR_DIR}/${WHEEL_NAME}"

echo "RAGFlow source environment is ready at ${RAGFLOW_DIR}/.venv"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_NAME="${1:-yushu-qa}"

conda env create -f environment.yml -n "$ENV_NAME" || conda env update -f environment.yml -n "$ENV_NAME"
eval "$(conda shell.bash hook)"
conda activate "$ENV_NAME"
uv sync --python 3.11 --inexact
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch
python -m pip install "transformers<5" FlagEmbedding
echo "Conda environment '$ENV_NAME' is ready."

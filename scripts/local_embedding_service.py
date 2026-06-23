from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel


ROOT_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = Path(os.environ.get("LOCAL_EMBED_MODEL_DIR", ROOT_DIR / "data/models/BAAI__bge-m3"))
HOST = os.environ.get("LOCAL_EMBED_HOST", "127.0.0.1")
PORT = int(os.environ.get("LOCAL_EMBED_PORT", "6380"))
EMBED_BATCH_SIZE = int(os.environ.get("LOCAL_EMBED_BATCH_SIZE", "4"))

app = FastAPI(title="Local BGE Embedding Service")
_model = None


class EmbedRequest(BaseModel):
    inputs: str | list[str]


def get_model():
    global _model
    if _model is None:
        from FlagEmbedding import BGEM3FlagModel

        _model = BGEM3FlagModel(str(MODEL_DIR), use_fp16=False)
    return _model


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "model_dir": str(MODEL_DIR)}


@app.post("/embed")
def embed(payload: EmbedRequest) -> list[list[float]]:
    texts = payload.inputs if isinstance(payload.inputs, list) else [payload.inputs]
    model = get_model()
    results: list[list[float]] = []
    for index in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[index : index + EMBED_BATCH_SIZE]
        vectors = model.encode(batch, batch_size=min(EMBED_BATCH_SIZE, max(1, len(batch))), max_length=8192)["dense_vecs"]
        results.extend(vector.tolist() for vector in vectors)
    return results


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)

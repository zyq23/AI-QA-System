from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import hf_hub_download

from app.main import build_container


MODEL_CHOICES = {
    "embedding": "BAAI/bge-m3",
    "reranker": "BAAI/bge-reranker-v2-m3",
}

MODEL_FILES = {
    "BAAI/bge-m3": [
        ".gitattributes",
        "1_Pooling/config.json",
        "config.json",
        "config_sentence_transformers.json",
        "modules.json",
        "sentence_bert_config.json",
        "sentencepiece.bpe.model",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "colbert_linear.pt",
        "sparse_linear.pt",
        "pytorch_model.bin",
    ],
    "BAAI/bge-reranker-v2-m3": [
        ".gitattributes",
        "config.json",
        "sentencepiece.bpe.model",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "model.safetensors",
    ],
}


def download_model(repo_id: str, local_dir: Path) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    for filename in MODEL_FILES[repo_id]:
        hf_hub_download(repo_id=repo_id, filename=filename, local_dir=str(local_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description="Knowledge-base RAG maintenance CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap", help="Import files from 宇树科技知识库")
    bootstrap.add_argument("--trust-level", default="internal")
    bootstrap.add_argument("--source-type", default="bootstrap")

    subparsers.add_parser("reindex", help="Reindex all active documents")
    download_models = subparsers.add_parser("download-models", help="Download local BGE embedding and reranker models")
    download_models.add_argument("--embedding-model", default=MODEL_CHOICES["embedding"])
    download_models.add_argument("--reranker-model", default=MODEL_CHOICES["reranker"])
    args = parser.parse_args()

    container = build_container()
    if args.command == "bootstrap":
        payload = container.ingestion_service.bootstrap_directory(
            container.settings.source_documents_dir,
            source_type=args.source_type,
            trust_level=args.trust_level,
            background_tasks=None,
        )
        print(payload)
        return 0
    if args.command == "reindex":
        job_ids = container.ingestion_service.reindex_all(background_tasks=None)
        print({"job_ids": job_ids})
        return 0
    if args.command == "download-models":
        embedding_dir = container.settings.model_cache_dir / args.embedding_model.replace("/", "__")
        reranker_dir = container.settings.model_cache_dir / args.reranker_model.replace("/", "__")
        download_model(args.embedding_model, embedding_dir)
        download_model(args.reranker_model, reranker_dir)
        print(
            {
                "embedding_model": args.embedding_model,
                "embedding_dir": str(embedding_dir),
                "reranker_model": args.reranker_model,
                "reranker_dir": str(reranker_dir),
            }
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_PROD_DEFAULTS_NOTED = set()


def _is_stub_or_test_mode() -> bool:
    """Return True when the process is explicitly allowed to use stub credentials."""
    return bool(os.environ.get("USE_STUB_ML", "").lower() in ("1", "true", "yes")) or \
        os.environ.get("DISABLE_LLM", "").lower() in ("1", "true", "yes") or \
        os.environ.get("PYTEST_CURRENT_TEST", "").strip() != ""


def _prod_default_credential_error(name: str, value: str) -> ValueError | None:
    """Reject well-known default credentials unless stub/test mode is active.

    The check is per-field and stateless: in production mode every default
    credential (ADMIN_TOKEN *and* SECRET_KEY) must raise, not just the first
    one encountered.
    """
    if not _is_stub_or_test_mode() and value in ("change-me", "knowledge-qa-secret"):
        return ValueError(
            f"{name} is set to the insecure default '{value}'. "
            "Set ADMIN_TOKEN and SECRET_KEY in .env before starting in production. "
            "Override with USE_STUB_ML=1 for local dev or tests."
        )
    return None


def _prod_default_credential_note(name: str, value: str) -> str | None:
    """Emit a startup note (not fatal) when running in stub/test mode with defaults."""
    if _is_stub_or_test_mode() and value in ("change-me", "knowledge-qa-secret") and name not in _PROD_DEFAULTS_NOTED:
        _PROD_DEFAULTS_NOTED.add(name)
        return (
            f"[stub/test mode] {name} is using the default '{value}'. "
            "Override ADMIN_TOKEN/SECRET_KEY in .env for production use."
        )
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "知识库 AI 问答系统"
    admin_token: str = "change-me"
    secret_key: str = "knowledge-qa-secret"
    service_api_token: str | None = None
    robot_hmac_secret: str | None = None
    robot_signature_window_seconds: int = 300
    audit_log_retention_days: int = 365
    default_locale: str = "zh-CN"

    @field_validator("admin_token")
    @classmethod
    def _reject_default_admin_token(cls, value: str) -> str:
        err = _prod_default_credential_error("ADMIN_TOKEN", value)
        if err is not None:
            raise err
        note = _prod_default_credential_note("ADMIN_TOKEN", value)
        if note:
            print(note, file=sys.stderr)
        return value

    @field_validator("secret_key")
    @classmethod
    def _reject_default_secret_key(cls, value: str) -> str:
        err = _prod_default_credential_error("SECRET_KEY", value)
        if err is not None:
            raise err
        note = _prod_default_credential_note("SECRET_KEY", value)
        if note:
            print(note, file=sys.stderr)
        return value

    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    data_dir: Path = Field(default_factory=lambda: Path("data"))
    upload_dir: Path = Field(default_factory=lambda: Path("data/uploads"))
    chroma_dir: Path = Field(default_factory=lambda: Path("data/chroma"))
    runtime_dir: Path = Field(default_factory=lambda: Path("data/runtime"))
    model_cache_dir: Path = Field(default_factory=lambda: Path("data/models"))
    database_path: Path = Field(default_factory=lambda: Path("data/runtime/app.db"))
    source_documents_dir: Path = Field(default_factory=lambda: Path("宇树科技知识库"))
    eval_dataset_path: Path = Field(default_factory=lambda: Path("data/evals/knowledge_base_eval_cases.json"))
    eval_results_dir: Path = Field(default_factory=lambda: Path("data/evals/results"))
    eval_api_base_url: str | None = Field(default=None, validation_alias="EVAL_API_BASE_URL")

    llm_provider: str = "spark_ws"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    disable_llm: bool = False

    spark_app_id: str | None = None
    spark_api_key: str | None = None
    spark_api_secret: str | None = None
    spark_api_base: str = "wss://spark-api.xf-yun.com/x2"
    spark_model: str = "x2"
    spark_domain: str = "spark-x"
    spark_temperature: float = 0.1
    spark_max_tokens: int = 2048
    spark_thinking_type: str = "disabled"
    spark_request_timeout_seconds: int = 25
    spark_uid: str = "knowledge-qa"

    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    embedding_model_local_dir: Path | None = None
    reranker_model_local_dir: Path | None = None
    use_stub_ml: bool = False

    enable_ocr_fallback: bool = True
    ocr_language: str = "ch"
    # Optional file with one OCR anchor keyword per line; falls back to generic defaults.
    ocr_anchor_file: Path | None = None

    upload_size_limit_mb: int = 150
    chunk_target_size: int = 700
    chunk_overlap: int = 120
    retrieval_candidates: int = 20
    retrieval_context_k: int = 6
    retrieval_backend: str = "local"
    retrieval_mode: str = "fts_only"
    conversation_history_turns: int = 2
    llm_review_policy: str = "auto"

    ragflow_base_url: str | None = None
    ragflow_api_key: str | None = None
    ragflow_dataset_ids_raw: str | None = Field(default=None, validation_alias="RAGFLOW_DATASET_IDS")
    ragflow_document_ids_raw: str | None = Field(default=None, validation_alias="RAGFLOW_DOCUMENT_IDS")
    ragflow_similarity_threshold: float = 0.2
    ragflow_vector_similarity_weight: float = 0.3
    ragflow_page_size: int = 20
    ragflow_keyword: bool = True
    ragflow_highlight: bool = False
    ragflow_use_kg: bool = False
    ragflow_toc_enhance: bool = False
    ragflow_timeout_seconds: int = 20
    ragflow_fallback_to_local: bool = True
    ragflow_fallback_timeout_ms: int = 6000
    ragflow_prefer_local_grounded: bool = True
    ragflow_local_grounded_score_threshold: float = 0.55

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.upload_dir,
            self.chroma_dir,
            self.runtime_dir,
            self.model_cache_dir,
            self.eval_results_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def upload_size_limit_bytes(self) -> int:
        return self.upload_size_limit_mb * 1024 * 1024

    def _default_model_dir(self, model_name: str) -> Path:
        return self.model_cache_dir / model_name.replace("/", "__")

    @staticmethod
    def _embedding_model_ready(path: Path) -> bool:
        required = (
            path / "config.json",
            path / "tokenizer.json",
            path / "sentencepiece.bpe.model",
            path / "pytorch_model.bin",
        )
        return all(item.exists() for item in required)

    @staticmethod
    def _reranker_model_ready(path: Path) -> bool:
        required = (
            path / "config.json",
            path / "tokenizer.json",
            path / "sentencepiece.bpe.model",
            path / "model.safetensors",
        )
        return all(item.exists() for item in required)

    @property
    def resolved_embedding_model(self) -> str:
        if self.embedding_model_local_dir and self._embedding_model_ready(self.embedding_model_local_dir):
            return str(self.embedding_model_local_dir)
        default_dir = self._default_model_dir(self.embedding_model)
        if self._embedding_model_ready(default_dir):
            return str(default_dir)
        return self.embedding_model

    @property
    def resolved_reranker_model(self) -> str:
        if self.reranker_model_local_dir and self._reranker_model_ready(self.reranker_model_local_dir):
            return str(self.reranker_model_local_dir)
        default_dir = self._default_model_dir(self.reranker_model)
        if self._reranker_model_ready(default_dir):
            return str(default_dir)
        return self.reranker_model

    @staticmethod
    def _split_csv(raw: str | None) -> list[str]:
        if not raw:
            return []
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def ragflow_dataset_ids(self) -> list[str]:
        return self._split_csv(self.ragflow_dataset_ids_raw)

    @property
    def ragflow_document_ids(self) -> list[str]:
        return self._split_csv(self.ragflow_document_ids_raw)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings

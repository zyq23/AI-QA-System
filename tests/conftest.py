from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


@pytest.fixture()
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "data" / "uploads"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "data" / "chroma"))
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path / "data" / "runtime"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "data" / "runtime" / "app.db"))
    monkeypatch.setenv("SOURCE_DOCUMENTS_DIR", str(tmp_path / "kb"))
    monkeypatch.setenv("EVAL_DATASET_PATH", str(tmp_path / "data" / "evals" / "cases.json"))
    monkeypatch.setenv("EVAL_RESULTS_DIR", str(tmp_path / "data" / "evals" / "results"))
    monkeypatch.setenv("USE_STUB_ML", "true")
    monkeypatch.setenv("DISABLE_LLM", "true")
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    get_settings.cache_clear()
    return tmp_path


@pytest.fixture()
def client(app_env: Path):
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()

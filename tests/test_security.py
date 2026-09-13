from __future__ import annotations

"""Security-gate tests: production startup must refuse well-known default
credentials, while stub/test mode is allowed to run with them (with a note)."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_prod_mode_rejects_default_admin_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("USE_STUB_ML", raising=False)
    monkeypatch.delenv("DISABLE_LLM", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings(admin_token="change-me", secret_key="strong-value-xyz")
    assert "ADMIN_TOKEN" in str(exc.value)


def test_prod_mode_rejects_default_secret_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("USE_STUB_ML", raising=False)
    monkeypatch.delenv("DISABLE_LLM", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings(admin_token="strong-value-xyz", secret_key="knowledge-qa-secret")
    assert "SECRET_KEY" in str(exc.value)


def test_prod_mode_accepts_strong_credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("USE_STUB_ML", raising=False)
    monkeypatch.delenv("DISABLE_LLM", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    s = Settings(admin_token="aQ3$zOrandom", secret_key="bR7$kPrandom")
    assert s.admin_token == "aQ3$zOrandom"
    assert s.secret_key == "bR7$kPrandom"


def test_stub_mode_allows_default_credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USE_STUB_ML", "true")
    s = Settings(admin_token="change-me", secret_key="knowledge-qa-secret")
    assert s.admin_token == "change-me"

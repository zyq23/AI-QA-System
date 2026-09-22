from __future__ import annotations

import hmac
import hashlib
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _sign(secret: str, timestamp: str, body: str) -> str:
    return hmac.new(secret.encode(), f"{timestamp}:{body}".encode(), hashlib.sha256).hexdigest()


def test_robot_auth_requires_signature_when_secret_configured(app_env: Path, monkeypatch):
    monkeypatch.setenv("ROBOT_HMAC_SECRET", "test-robot-secret")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    app = create_app()
    with TestClient(app) as client:
        # No signature -> 401
        resp = client.post("/api/robot/query", json={"question": "test"})
        assert resp.status_code == 401


def test_robot_auth_valid_signature_passes(app_env: Path, monkeypatch):
    monkeypatch.setenv("ROBOT_HMAC_SECRET", "test-robot-secret")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    app = create_app()
    with TestClient(app) as client:
        ts = str(int(time.time()))
        body = '{"question": "test"}'
        sig = _sign("test-robot-secret", ts, body)
        resp = client.post(
            "/api/robot/query",
            json={"question": "test"},
            headers={"X-Robot-Timestamp": ts, "X-Robot-Signature": sig, "X-Robot-Body": body},
        )
        # Should not be 401; may be 200 or 4xx from downstream but auth passed
        assert resp.status_code != 401


def test_robot_auth_expired_timestamp_rejected(app_env: Path, monkeypatch):
    monkeypatch.setenv("ROBOT_HMAC_SECRET", "test-robot-secret")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    app = create_app()
    with TestClient(app) as client:
        ts = str(int(time.time()) - 9999)
        body = '{"question": "test"}'
        sig = _sign("test-robot-secret", ts, body)
        resp = client.post(
            "/api/robot/query",
            json={"question": "test"},
            headers={"X-Robot-Timestamp": ts, "X-Robot-Signature": sig, "X-Robot-Body": body},
        )
        assert resp.status_code == 401


def test_service_token_auth(app_env: Path, monkeypatch):
    monkeypatch.setenv("SERVICE_API_TOKEN", "svc-token-123")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    app = create_app()
    with TestClient(app) as client:
        # No token -> 401
        resp = client.post("/api/agent/query", json={"question": "test"})
        assert resp.status_code == 401
        # Valid token -> not 401
        resp = client.post(
            "/api/agent/query",
            json={"question": "test"},
            headers={"X-Service-Token": "svc-token-123"},
        )
        assert resp.status_code != 401

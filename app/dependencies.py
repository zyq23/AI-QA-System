from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Depends, HTTPException, Request, Response, status

from app.auth import COOKIE_NAME
from app.container import ServiceContainer

SERVICE_TOKEN_HEADER = "X-Service-Token"
ROBOT_SIGNATURE_HEADER = "X-Robot-Signature"
ROBOT_TIMESTAMP_HEADER = "X-Robot-Timestamp"
ROBOT_CLIENT_HEADER = "X-Robot-Client"


def get_container(request: Request) -> ServiceContainer:
    return request.app.state.container


def require_admin(request: Request, response: Response, container: ServiceContainer = Depends(get_container)) -> str:
    expected = container.settings.admin_token
    # Header or signed cookie only. URL query tokens leak into access logs and
    # browser history, so query-param auth was removed (quality-upgrade).
    provided = request.headers.get("X-Admin-Token")
    if not provided:
        cookie = request.cookies.get(COOKIE_NAME)
        if cookie:
            provided = request.app.state.admin_signer.loads(cookie)
    if provided != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin token invalid.")
    response.set_cookie(
        COOKIE_NAME,
        request.app.state.admin_signer.dumps(expected),
        httponly=True,
        samesite="lax",
    )
    return expected


def _service_token_configured(container: ServiceContainer) -> bool:
    token = container.settings.service_api_token
    # An unset/placeholder token means "auth not enforced yet" so the internal
    # single-machine verification deployment keeps working; production refuses
    # to start without a real token (see config validators).
    return bool(token) and token != "change-me"


def require_service_api_token(request: Request, container: ServiceContainer = Depends(get_container)) -> str | None:
    """Authenticate a non-admin caller against SERVICE_API_TOKEN.

    Returns the authenticated principal ("service") when a token is configured
    and valid, or None when auth is not enforced. A configured token with a
    missing/wrong value is rejected with 401 — an operator who sets the token
    expects it to be enforced.
    """
    if not _service_token_configured(container):
        return None
    expected = container.settings.service_api_token or ""
    provided = request.headers.get(SERVICE_TOKEN_HEADER) or ""
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Service token invalid.")
    return "service"


def require_robot_auth(request: Request, container: ServiceContainer = Depends(get_container)) -> str:
    """Authenticate a robot device.

    When ROBOT_HMAC_SECRET is configured the caller must send a timestamped
    HMAC over ``timestamp:body`` (replay-protected by a bounded window).
    Otherwise the request falls back to the shared service token, and if
    neither is configured auth is not enforced (single-machine verification).
    """
    secret = container.settings.robot_hmac_secret
    if secret:
        signature = request.headers.get(ROBOT_SIGNATURE_HEADER) or ""
        timestamp = request.headers.get(ROBOT_TIMESTAMP_HEADER) or ""
        if not signature or not timestamp:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Robot signature required.")
        try:
            ts = int(timestamp)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Robot timestamp invalid.")
        window = max(1, int(container.settings.robot_signature_window_seconds))
        if abs(time.time() - ts) > window:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Robot timestamp expired.")
        body = request.headers.get("X-Robot-Body") or ""
        expected = hmac.new(secret.encode("utf-8"), f"{timestamp}:{body}".encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Robot signature invalid.")
        return "robot"
    if _service_token_configured(container):
        principal = require_service_api_token(request, container)
        return principal or "service"
    return "anonymous"

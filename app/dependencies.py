from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Response, status

from app.auth import COOKIE_NAME
from app.container import ServiceContainer


def get_container(request: Request) -> ServiceContainer:
    return request.app.state.container


def require_admin(request: Request, response: Response, container: ServiceContainer = Depends(get_container)) -> str:
    expected = container.settings.admin_token
    provided = request.headers.get("X-Admin-Token") or request.query_params.get("token")
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

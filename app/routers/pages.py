from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.dependencies import get_container, require_admin
from app.routers.api_admin import build_admin_context


def build_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def home(request: Request):
        container = get_container(request)
        documents = container.repository.list_documents()
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "app_name": container.settings.app_name,
                "documents": documents,
                "document_count": len(documents),
                "source_dir": container.settings.source_documents_dir,
            },
        )

    @router.get("/admin", response_class=HTMLResponse)
    def admin(request: Request, response: Response, _: str = Depends(require_admin)):
        container = get_container(request)
        context = {
            "app_name": container.settings.app_name,
            **build_admin_context(request),
        }
        return templates.TemplateResponse(request, "admin.html", context)

    return router

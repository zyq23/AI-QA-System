"""Agent API router: /api/agent/query — same semantics as /api/chat/query.

Response mirrors ChatQueryResponse plus the decision trail (thought/tool/
observation) and agent session id, so the evaluation report can show the
reasoning process for every question.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, HTTPException, status

from app.auth import AdminSessionSigner
from app.dependencies import get_container, require_robot_auth
from app.schemas import AgentQueryRequest, AgentQueryResponse, CitationModel


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/agent", tags=["agent"])

    @router.post("/query", response_model=AgentQueryResponse)
    async def agent_query(
        request: Request,
        payload: AgentQueryRequest,
        auth_principal: str = Depends(require_robot_auth),
    ):
        container = get_container(request)
        # Enforce session ownership: only the creator of a conversation may
        # read it unless the caller holds a service/robot token.
        if payload.conversation_id and auth_principal not in ("service", "robot"):
            signer = AdminSessionSigner(container.settings.secret_key)
            # The conversation_id is stored encrypted in the cookie as
            # ``admin_session``; we decode it here to check ownership.
            cookie = request.cookies.get("admin_session")
            if cookie:
                try:
                    stored = signer.loads(cookie)
                except Exception:
                    stored = None
            else:
                stored = None
            if stored and stored != payload.conversation_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conversation ID mismatch.")
        
        result = container.agent_service.query(
            payload.question,
            payload.conversation_id,
            force_agent=payload.force_agent,
        )
        return AgentQueryResponse(
            answer=result.answer,
            grounded=result.grounded,
            conversation_id=result.conversation_id,
            session_id=result.session_id,
            latency_ms=result.latency_ms,
            intent=result.intent,
            intent_confidence=result.confidence,
            confidence_note=result.confidence_note,
            tools_used=result.tools_used,
            followup_question=result.followup_question,
            escalated=result.escalated,
            terminal_status=result.terminal_status,
            deterministic_evidence=result.deterministic_evidence,
            citations=[
                CitationModel(
                    document_id=c.get("document_id", ""),
                    version_id=c.get("version_id"),
                    chunk_id=c.get("chunk_id"),
                    file_name=c.get("file_name", ""),
                    page_or_slide=c.get("page_or_slide", ""),
                    section_path=c.get("section_path", ""),
                    snippet=c.get("snippet", ""),
                    plain_text=c.get("plain_text"),
                    markdown_text=c.get("markdown_text"),
                    trust_level=c.get("trust_level", "agent"),
                    source_type=c.get("source_type"),
                    ocr_quality=float(c.get("ocr_quality") or 0.0) if c.get("ocr_quality") is not None else None,
                    score=float(c.get("score", 0) or 0.0),
                )
                for c in result.citations
            ],
            steps=result.steps,
        )

    return router
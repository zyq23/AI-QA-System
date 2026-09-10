from __future__ import annotations

import re

from fastapi import APIRouter, Request

from app.dependencies import get_container
from app.schemas import RobotQueryRequest, RobotQueryResponse


_CLEAN_INSUFFICIENT_REPLY = "抱歉，当前知识库中没有找到相关信息，建议换个方式提问试试。"


def _clean_for_tts(text: str) -> str:
    """Clean answer text for TTS broadcasting — remove markdown, URLs, and limit length."""
    if not text:
        return ""
    # Remove control characters
    text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]", "", text)
    # Remove markdown: backticks, bold/italic, links, headers
    text = re.sub(r"`+", "", text)
    text = re.sub(r"\*{1,3}([^*]+?)\*{1,3}", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[#*_>{}\[\]|]+", " ", text)
    # Remove list prefixes like "1. " or "- " (anywhere)
    text = re.sub(r"(?:^|\s)(?:\d+[.)、]\s*|[-•]\s*)+", " ", text, flags=re.MULTILINE)
    # Normalize whitespace
    text = re.sub(r"\s{2,}", " ", text).strip()
    # Trim to suitable TTS length
    if len(text) > 150:
        text = text[:147].rstrip("，、；：,. ") + "。"
    # Ensure it ends with proper punctuation
    if text and not text.endswith(("。", "！", "？", "…", ".", "!", "?")):
        text += "。"
    return text


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/robot", tags=["robot"])

    @router.post("/query", response_model=RobotQueryResponse)
    def robot_query(request: Request, payload: RobotQueryRequest):
        container = get_container(request)
        agent_service = container.agent_service
        if agent_service is not None and agent_service.needs_agent(payload.question):
            # Complex/multi-step questions run through the Agent; simple ones keep
            # the single-turn fast path (skip_llm_rewrite + robot_mode).
            result = agent_service.query(payload.question, payload.conversation_id, force_agent=True, persist=True)
            answer = result.answer
            conversation_id = result.conversation_id
            latency_ms = result.latency_ms
            grounded = result.grounded
            answer_run_id = result.answer_run_id
            question_type = result.intent
            answer_focus = result.confidence_note
        else:
            raw = container.chat_service.answer(
                payload.question,
                payload.conversation_id,
                payload.top_k,
                skip_llm_rewrite=True,
                robot_mode=True,
            )
            answer = raw.answer
            conversation_id = raw.conversation_id
            latency_ms = raw.latency_ms
            grounded = raw.grounded
            answer_run_id = raw.answer_run_id
            question_type = raw.question_type
            answer_focus = raw.answer_focus
        tts_text = _clean_for_tts(answer) or _CLEAN_INSUFFICIENT_REPLY
        return RobotQueryResponse(
            answer=tts_text,
            conversation_id=conversation_id,
            latency_ms=latency_ms,
            grounded=grounded,
            should_speak=bool(tts_text),
            tts_text=tts_text,
            answer_run_id=answer_run_id,
            question_type=question_type,
            answer_focus=answer_focus,
        )

    return router

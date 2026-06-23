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
        raw = container.chat_service.answer(
            payload.question,
            payload.conversation_id,
            payload.top_k,
            skip_llm_rewrite=True,
            robot_mode=True,
        )
        tts_text = _clean_for_tts(raw.answer) or _CLEAN_INSUFFICIENT_REPLY
        return RobotQueryResponse(
            answer=tts_text,
            conversation_id=raw.conversation_id,
            latency_ms=raw.latency_ms,
            grounded=raw.grounded,
            should_speak=bool(tts_text),
            tts_text=tts_text,
            answer_run_id=raw.answer_run_id,
            question_type=raw.question_type,
            answer_focus=raw.answer_focus,
        )

    return router

"""Agent service: wires controller + session store + conversation persistence.

Exposes a single entry point `query()` used by both /api/agent/query and the
robot bridge. Simple questions take the single-turn fast path (existing RAG
pipeline); the Agent loop is reserved for questions the router flags as
multi-step.
"""
from __future__ import annotations

import time
from typing import Any

from app.agent.controller import AgentController
from app.agent.sessions import AgentSessionStore
from app.agent.state import AgentResult
from app.agent.tools import default_tools, BaseTool
from app.repositories import Repository
from app.services.chat import ChatService
from app.services.llm import LlmService

# Questions that need more than one retrieval step: cross-subject compares,
# math/date, explicit multi-part asks, and long instruction-wrapped queries.
_MULTI_STEP_MARKERS = ("区别", "分别", "对比", "各是", "各自", "计算", "几天", "周几", "星期几", "一起列出", "同时给出")


class AgentService:
    def __init__(
        self,
        *,
        repository: Repository,
        chat_service: ChatService,
        llm_service: LlmService,
        max_steps: int = 6,
        timeout_seconds: int = 45,
    ) -> None:
        self.repository = repository
        self.chat_service = chat_service
        self.llm_service = llm_service
        self.tools: dict[str, BaseTool] = default_tools(chat_service, repository)
        self.controller = AgentController(
            self.tools,
            llm_service,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
            chat_service=chat_service,
        )
        self.sessions = AgentSessionStore(repository)

    def needs_agent(self, question: str) -> bool:
        """Route: simple questions take the fast path, complex ones use the Agent."""
        question = question.strip()
        if any(marker in question for marker in _MULTI_STEP_MARKERS):
            return True
        # Instruction-wrapped hard questions (跳过X/只回答Y/第N页) are agent-worthy.
        if any(marker in question for marker in ("跳过", "只回答", "忽略", "定位", "第几页", "第", "页")) and len(question) >= 14:
            return True
        if len(question) >= 30:
            return True
        return False

    def query(
        self,
        question: str,
        conversation_id: str | None = None,
        *,
        force_agent: bool = False,
        persist: bool = True,
    ) -> AgentResult:
        conversation_id = self.repository.ensure_conversation(conversation_id)
        history = self.repository.get_recent_turn_context(conversation_id, 1) if persist else []

        if not force_agent and not self.needs_agent(question):
            started = time.perf_counter()
            payload = self.chat_service.answer(question, conversation_id=conversation_id)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            result = AgentResult(
                session_id="",
                conversation_id=conversation_id,
                answer=payload.answer,
                grounded=payload.grounded,
                intent="fast_path",
                confidence=1.0,
                tools_used=["fast_path"],
                citations=[
                    {
                        "file_name": h.file_name,
                        "page_or_slide": h.page_or_slide,
                        "section_path": h.section_path,
                        "snippet": h.snippet,
                        "score": round(float(h.rerank_score or h.fusion_score or 0.0), 3),
                    }
                    for h in payload.citations
                ],
                steps=[
                    {
                        "step": 1,
                        "type": "fast_path",
                        "tool": "chat.answer",
                        "args": {"question": question},
                        "observation": payload.inference_note,
                        "duration_ms": elapsed_ms,
                        "ok": True,
                    }
                ],
                latency_ms=elapsed_ms,
                confidence_note="single_turn_fast_path",
                answer_run_id=payload.answer_run_id,
            )
            if persist:
                self.repository.add_message(conversation_id, "user", question)
                self.repository.add_message(
                    conversation_id,
                    "assistant",
                    payload.answer,
                    grounded=payload.grounded,
                    citations=[self.repository.serialize_hit(h) for h in payload.citations],
                )
            return result

        # Agent path ---------------------------------------------------------
        result = self.controller.execute(question, conversation_id, history=history)
        result.session_id = self.sessions.create_session(
            conversation_id,
            intent=result.intent,
            confidence=result.confidence,
            slots={"question": question, "answer_run_id": result.answer_run_id},
        )
        for index, step in enumerate(result.steps, 1):
            self.sessions.record_step(
                result.session_id,
                index,
                step_type=step.get("type", "tool"),
                tool_name=step.get("tool"),
                thought=step.get("reason") or "",
                observation=str(step.get("observation") or "")[:2000],
                duration_ms=int(step.get("duration_ms") or 0),
            )
        status = "completed" if result.grounded else ("clarification" if result.followup_question else "no_answer")
        self.sessions.complete_session(
            result.session_id,
            status=status,
            used_tools=result.tools_used,
            intermediate={
                "answer": result.answer,
                "grounded": result.grounded,
                "confidence_note": result.confidence_note,
            },
            slots={"question": question},
        )
        if persist:
            self.repository.add_message(
                conversation_id,
                "user",
                question,
            )
            self.repository.add_message(
                conversation_id,
                "assistant",
                result.answer,
                grounded=result.grounded,
                citations=[{**c, "score": float(c.get("score") or 0.0)} for c in result.citations],
            )
        return result
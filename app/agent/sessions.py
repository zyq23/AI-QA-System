"""Agent session persistence: intent/slots/tools/intermediate state + decision trail.

Two tables (app/db.py):
- agent_sessions: one row per agent query (intent, confidence, slots, tools used)
- agent_steps:    one row per thought/tool/observation step (the evidence chain)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.repositories import Repository


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentSessionStore:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def create_session(
        self,
        conversation_id: str,
        *,
        intent: str,
        confidence: float,
        slots: dict[str, Any] | None = None,
    ) -> str:
        session_id = uuid4().hex
        now = _now()
        with self.repository.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_sessions (
                    id, conversation_id, intent, intent_confidence, slots_json,
                    used_tools_json, intermediate_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    session_id,
                    conversation_id,
                    intent,
                    float(confidence),
                    json.dumps(slots or {}, ensure_ascii=False),
                    json.dumps([], ensure_ascii=False),
                    json.dumps({}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return session_id

    def record_step(
        self,
        session_id: str,
        step_index: int,
        *,
        step_type: str,
        tool_name: str | None,
        thought: str,
        observation: str,
        duration_ms: int,
    ) -> None:
        with self.repository.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_steps (
                    id, session_id, step_index, step_type, tool_name,
                    thought, observation, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (uuid4().hex, session_id, int(step_index), step_type, tool_name, thought, observation, int(duration_ms), _now()),
            )

    def complete_session(
        self,
        session_id: str,
        *,
        status: str,
        used_tools: list[str],
        intermediate: dict[str, Any],
        slots: dict[str, Any] | None = None,
    ) -> None:
        with self.repository.db.connect() as conn:
            conn.execute(
                """
                UPDATE agent_sessions
                SET status = ?, used_tools_json = ?, intermediate_json = ?, slots_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    json.dumps(used_tools, ensure_ascii=False),
                    json.dumps(intermediate, ensure_ascii=False),
                    json.dumps(slots or {}, ensure_ascii=False),
                    _now(),
                    session_id,
                ),
            )

    def latest_session(self, conversation_id: str) -> dict[str, Any] | None:
        with self.repository.db.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_sessions WHERE conversation_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def session_steps(self, session_id: str) -> list[dict[str, Any]]:
        with self.repository.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_steps WHERE session_id = ? ORDER BY step_index",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

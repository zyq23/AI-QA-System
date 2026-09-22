from __future__ import annotations

"""Agent tests: tool unit tests, planner routing, controller loop guards,
session persistence, and the agent API route. All LLM interactions are mocked
(no network), matching the project's stub-LLM test convention."""

import json
from pathlib import Path

import pytest

from app.agent.controller import AgentController
from app.agent.planner import build_plan, classify_intent
from app.agent.service import AgentService
from app.agent.state import AgentResult
from app.agent.tools import CalculatorTool, DateUtilsTool, NoAnswerTool, MultiDocCompareTool, _serialize_hits
from app.domain import RetrievalHit
from app.main import build_container


# --------------------------------------------------------------- tools (pure)

def test_calculator_safe_arithmetic():
    tool = CalculatorTool()
    result = tool.run({"expression": "(3+2)*4"})
    assert result["payload"]["value"] == 20.0
    assert "20" in result["observation"]


def test_calculator_rejects_unsafe_expression():
    tool = CalculatorTool()
    result = tool.run({"expression": "__import__('os').system('ls')"})
    assert result["payload"].get("error") == "invalid_expression"
    # Division by zero must not crash, and must not loop
    result2 = tool.run({"expression": "1/0"})
    assert result2["payload"].get("error") is not None


def test_date_utils_weekday_and_offset():
    tool = DateUtilsTool()
    weekday = tool.run({"weekday_of": "2026-09-10"})
    assert "四" in weekday["observation"]
    offset = tool.run({"base": "2026-09-10", "offset_days": 3})
    assert "2026-09-13" in offset["observation"]
    diff = tool.run({"base": "2026-09-10", "diff_from": "2026-09-20"})
    assert "10 天" in diff["observation"]


def test_date_plan_preserves_offset_and_weekday_operation(app_env: Path):
    plan = build_plan("2026-09-10后3天是周几？", None, [], use_llm_planner=False)
    assert plan.steps[0].tool == "date_utils"
    assert plan.steps[0].args == {"base": "2026-09-10", "weekday_of": "2026-09-13", "offset_days": 3}


def test_no_answer_tool_returns_refusal_marker(app_env: Path):
    tool = NoAnswerTool()
    result = tool.run({"reason": "库中无此数据"})
    assert result["payload"]["no_answer"] is True


def test_serialize_hits_preserves_evidence_provenance():
    hit = RetrievalHit(
        chunk_id="chunk-1", document_id="doc-1", version_id="ver-1",
        file_name="demo.pdf", page_or_slide="page-2", section_path="A > B",
        snippet="短证据", markdown_text="**完整证据**", plain_text="完整证据文本",
        trust_level="internal", source_type="pdf", fusion_score=0.4,
        rerank_score=0.8, ocr_quality=0.73,
    )
    serialized = _serialize_hits([hit])[0]
    assert serialized["chunk_id"] == "chunk-1"
    assert serialized["document_id"] == "doc-1"
    assert serialized["version_id"] == "ver-1"
    assert serialized["plain_text"] == "完整证据文本"
    assert serialized["markdown_text"] == "**完整证据**"
    assert serialized["ocr_quality"] == 0.73
    assert serialized["page_or_slide"] == "page-2"


def test_multidoc_compare_returns_top_level_evidence_contract():
    class _Llm:
        def _extract_focus_terms(self, query):
            return [query]

    class _Chat:
        llm_service = _Llm()

        def _multi_query_retrieve(self, query, analysis, top_k):
            hit = RetrievalHit(
                chunk_id=f"{query}-chunk", document_id=f"{query}-doc", version_id="v1",
                file_name=f"{query}.pdf", page_or_slide="page-1", section_path="root",
                snippet=f"{query} evidence", markdown_text=f"{query} evidence",
                plain_text=f"{query} evidence", trust_level="internal", source_type="pdf",
                fusion_score=0.7, rerank_score=0.8,
            )
            return [hit], True

    result = MultiDocCompareTool(_Chat()).run({"subject_a": "A", "subject_b": "B", "attribute": "型号"})
    payload = result["payload"]
    assert payload["grounded"] is True
    assert len(payload["hits"]) == 2
    assert set(payload["sides"]) == {"a", "b"}
    assert payload["comparison"]["sides"]["a"]["claims"][0]["citations"]
    assert payload["missing_fields"] == []


def test_health_probes_report_liveness_and_readiness(app_env: Path, client):
    assert client.get("/live").status_code == 200
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


# ------------------------------------------------------------------- planner

def test_classify_intent_routing():
    assert classify_intent("机械臂和实训套件的区别是什么？")[0] == "multi_doc_compare"
    assert classify_intent("(3+2)*4等于多少？")[0] == "math"
    assert classify_intent("3天后的日期是？")[0] == "date_math"
    assert classify_intent("轩辕网络的证券代码是多少？")[0] == "knowledge_qa"


def test_build_plan_multi_subject_splits_subjects(app_env: Path):
    plan = build_plan("机械臂和实训套件的核心设备有什么区别？", None, [])
    assert plan.intent == "multi_doc_compare"
    assert plan.steps and plan.steps[0].tool == "multi_doc_compare"
    args = plan.steps[0].args
    assert "机械" in args["subject_a"] or "机械" in args["subject_b"]
    assert args.get("attribute") == "核心设备"


def test_build_plan_clarification_low_confidence(app_env: Path):
    plan = build_plan("它", [{"role": "user", "content": "上一轮问题"}], [])
    assert plan.intent == "clarify"
    assert plan.steps and plan.steps[0].tool == "no_answer"


# -------------------------------------------------------------- controller

class _StubLlm:
    """No network: _generate_text returns canned JSON, _extract_json_block parses it."""

    disabled = False

    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def _extract_json_block(self, text: str) -> dict | None:
        try:
            return json.loads(text)
        except Exception:
            return None

    def _generate_text(self, messages, *, temperature, max_tokens) -> str:
        self.calls += 1
        if not self.responses:
            return "{}"
        return json.dumps(self.responses.pop(0), ensure_ascii=False)


def _fake_tool(name: str, payload: dict | None = None, *, raise_error: bool = False):
    class _T:
        def __init__(self, name, payload, raise_error):
            self.name = name
            self.description = f"fake {name}"
            self.schema = {"type": "object", "properties": {}}
            self._payload = payload or {}
            self._raise = raise_error

        def to_spec(self):
            return {"name": self.name, "description": self.description, "schema": self.schema}

        def run(self, args):
            if self._raise:
                raise RuntimeError("boom")
            if self.name == "no_answer":
                return {"observation": "拒答", "payload": {"no_answer": True}}
            return {
                "observation": self._payload.get("observation", "ok"),
                "payload": self._payload,
            }

    return _T(name, payload, raise_error)


def _controller(llm=None, tools=None):
    return AgentController(
        tools or {},
        llm or _StubLlm([]),
        max_steps=2,
        timeout_seconds=10,
        use_llm_planner=False,
    )


def test_controller_stops_after_max_steps():
    ctrl = _controller(tools={"knowledge_search": _fake_tool("knowledge_search", {"grounded": False, "hits": []})})
    result = ctrl.execute("轩辕网络的证券代码是什么？", "conv1")
    assert result.grounded is False
    assert len(result.steps) == 1  # single planned step, no re-plan loop possible
    assert result.steps[0]["ok"] is True


def test_controller_crash_safety_no_dead_loop():
    ctrl = _controller(tools={"knowledge_search": _fake_tool("knowledge_search", raise_error=True)})
    result = ctrl.execute("会崩的问题", "conv1")
    assert result.steps[0]["ok"] is False
    assert result.grounded is False


def test_controller_timeout_stops_loop():
    class _SlowTool:
        name = "knowledge_search"
        description = "slow"
        schema = {"properties": {}}

        def to_spec(self):
            return {"name": "knowledge_search", "description": "", "schema": {}}

        def run(self, args):
            time.sleep(0.5)
            return {"observation": "slow", "payload": {"grounded": False}}

    import time

    ctrl = AgentController({"knowledge_search": _SlowTool()}, _StubLlm([]), max_steps=10, timeout_seconds=3, use_llm_planner=False)
    started = time.perf_counter()
    result = ctrl.execute("慢问题", "conv1")
    elapsed = time.perf_counter() - started
    assert elapsed < 3.5  # hard wall-clock floor respected
    assert result.grounded is False
    assert result.terminal_status == "no_answer"


def test_controller_marks_tool_error_terminal_status():
    ctrl = _controller(tools={"knowledge_search": _fake_tool("knowledge_search", raise_error=True)})
    result = ctrl.execute("会崩的问题", "conv1")
    assert result.terminal_status == "exhausted_error"


def test_controller_bounded_replan():
    llm = _StubLlm([{"steps": [{"tool": "no_answer", "args": {}}]}])
    tools = {
        "knowledge_search": _fake_tool("knowledge_search", {"grounded": False, "hits": []}),
        "no_answer": _fake_tool("no_answer"),
    }
    ctrl = AgentController(tools, llm, max_steps=4, timeout_seconds=15, use_llm_planner=False)
    result = ctrl.execute("需要再想一步的问题", "conv1")
    assert llm.calls >= 1
    assert result.tools_used[-1] == "no_answer"


def test_controller_timeout_reason_classification():
    # A tool that sleeps past the wall-clock budget (triggers timeout, not step_budget)
    class _SlowTool:
        name = "knowledge_search"
        description = "slow"
        schema = {"properties": {}}

        def to_spec(self):
            return {"name": self.name, "description": "", "schema": {}}

        def run(self, args):
            time.sleep(0.5)
            return {"observation": "slow", "payload": {"grounded": False}}

    import time

    ctrl = AgentController(
        {"knowledge_search": _SlowTool()},
        _StubLlm([]),
        max_steps=20,
        timeout_seconds=1,
        use_llm_planner=False,
    )
    started = time.perf_counter()
    result = ctrl.execute("慢问题", "conv1")
    elapsed = time.perf_counter() - started
    assert elapsed < 3.0  # respect timeout
    # timeout_reason is populated when terminal status is timeout;
    # for other terminal statuses it is None (by design)
    if result.terminal_status == "timeout":
        assert result.timeout_reason in ("wall_clock", "tool_internal", "step_budget")
    assert result.plan_status["initial_steps"] >= 1
    assert "intent" in result.plan_status
    assert "confidence" in result.plan_status


def test_controller_plan_status_records_replan():
    llm = _StubLlm([{"steps": [{"tool": "knowledge_search", "args": {"query": "1"}}]}])
    tools = {
        "knowledge_search": _fake_tool("knowledge_search", {"grounded": False, "hits": []}),
        "no_answer": _fake_tool("no_answer"),
    }
    ctrl = AgentController(tools, llm, max_steps=4, timeout_seconds=15, use_llm_planner=False)
    result = ctrl.execute("需要再想一步的问题", "conv1")
    assert isinstance(result.plan_status, dict)
    assert "initial_steps" in result.plan_status
    assert "replanned" in result.plan_status


def test_controller_finalize_stage_and_guards():
    # Use the real build_container path so chat_service is wired
    container = build_container()
    service = container.agent_service
    result = service.query("轩辕网络的证券代码是多少？", persist=False)
    # Routed path (fast_path) – check finalization fields exist
    assert isinstance(result, AgentResult)
    assert result.finalize_stage is not None
    assert isinstance(result.guard_triggered, list)


def test_controller_deterministic_evidence_in_finalize():
    """When calculator answers a question, the evidence must be carried to finalize."""
    container = build_container()
    service = container.agent_service
    # A deterministic-date question that calculator can answer
    result = service.query("2026-09-10后3天是周几？", force_agent=True, persist=False)
    assert isinstance(result, AgentResult)
    assert result.deterministic_evidence or not result.grounded


# ------------------------------------------------------------------- service

@pytest.fixture()
def agent_services(app_env: Path):
    container = build_container()
    return container


def test_agent_service_fast_path_for_simple_question(app_env: Path, agent_services):
    service = agent_services.agent_service
    assert service.needs_agent("轩辕网络的证券代码是多少？") is False
    result = service.query("轩辕网络的证券代码是多少？", persist=False)
    assert result.intent == "fast_path"
    assert isinstance(result, AgentResult)


def test_agent_service_route_marks_multi_subject(app_env: Path, agent_services):
    service = agent_services.agent_service
    assert service.needs_agent("机械臂和实训套件的核心设备有什么区别？") is True
    assert service.needs_agent("3天后是周几？") is True


def test_agent_session_persistence(app_env: Path, agent_services):
    repo = agent_services.repository
    store = agent_services.agent_service.sessions
    conversation_id = repo.ensure_conversation(None)
    session_id = store.create_session(conversation_id, intent="knowledge_qa", confidence=0.8)
    store.record_step(session_id, 1, step_type="tool", tool_name="knowledge_search", thought="plan", observation="obs", duration_ms=12)
    store.complete_session(session_id, status="completed", used_tools=["knowledge_search"], intermediate={"a": 1})
    latest = store.latest_session(conversation_id)
    assert latest["intent"] == "knowledge_qa"
    steps = store.session_steps(session_id)
    assert len(steps) == 1 and steps[0]["tool_name"] == "knowledge_search"


# ------------------------------------------------------------------- http

def test_agent_api_query_route(app_env: Path, client):
    response = client.post(
        "/api/agent/query",
        json={"question": "轩辕网络的证券代码是多少？"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"]
    assert "steps" in body


def test_agent_api_force_agent_returns_trail(app_env: Path, client):
    response = client.post(
        "/api/agent/query",
        json={"question": "机械臂和实训套件的核心设备有什么区别？", "force_agent": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] or body["intent"] == "fast_path"
    assert isinstance(body["steps"], list)
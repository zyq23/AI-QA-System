"""Plan-then-execute Agent controller (智能客服形态).

Loop contract:
- build a plan (rules, LLM-refined for ambiguous intents),
- execute the plan steps with a hard step cap and a wall-clock timeout,
- after the plan, if no grounded conclusion was reached, ONE bounded LLM
  re-plan round may extend execution (still inside the caps),
- clarification/no_answer are terminal tools; knowledge_search with strong
  grounding terminates with an answer;
- every tool call is recorded (thought/tool/observation) for the evidence chain.

Dead-loop safety: max_steps (default 6) AND timeout_seconds (default 45) are
hard caps; a step that raises is recorded and execution stops instead of
retrying forever.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from app.agent.planner import build_plan
from app.agent.state import AgentPlan, AgentResult, PlanStep, ToolCall
from app.agent.tools import BaseTool

logger = logging.getLogger(__name__)

INSUFFICIENT_MARKERS = ("当前知识库中没有找到", "未找到包含", "需要用户澄清")


class AgentController:
    def __init__(
        self,
        tools: dict[str, BaseTool],
        llm_service: Any,
        *,
        max_steps: int = 6,
        timeout_seconds: int = 45,
        use_llm_planner: bool = True,
    ) -> None:
        self.tools = tools
        self.llm_service = llm_service
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds
        self.use_llm_planner = use_llm_planner

    def tool_specs(self) -> list[dict[str, Any]]:
        return [tool.to_spec() for tool in self.tools.values()]

    # -------------------------------------------------------------- execution
    def execute(
        self,
        question: str,
        conversation_id: str,
        *,
        history: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        started = time.perf_counter()
        plan = build_plan(
            question,
            history,
            self.tool_specs(),
            llm_service=self.llm_service,
            use_llm_planner=self.use_llm_planner,
        )
        steps: list[ToolCall] = []
        citations: list[dict[str, Any]] = []

        step_index = 0
        for planned in plan.steps:
            if step_index >= self.max_steps:
                break
            if time.perf_counter() - started > self.timeout_seconds:
                break
            call = self._run_step(planned, conversation_id)
            steps.append(call)
            step_index += 1
            citations.extend(call.payload.get("hits", []) if isinstance(call.payload, dict) else [])
            observation = call.observation
            if self._is_terminal(plan, call):
                break

        # One bounded re-plan: the initial plan was too small to conclude.
        if not self._has_conclusion(steps) and step_index < self.max_steps:
            if time.perf_counter() - started < self.timeout_seconds:
                replanned = self._replan(question, steps)
                if replanned is not None:
                    for planned in replanned.steps:
                        if step_index >= self.max_steps:
                            break
                        if time.perf_counter() - started > self.timeout_seconds:
                            break
                        call = self._run_step(planned, conversation_id)
                        steps.append(call)
                        step_index += 1
                        citations.extend(call.payload.get("hits", []) if isinstance(call.payload, dict) else [])
                        if self._is_terminal(replanned, call):
                            break

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return self._finalize(question, conversation_id, plan, steps, citations, elapsed_ms)

    def _run_step(self, planned: PlanStep, conversation_id: str) -> ToolCall:
        tool = self.tools.get(planned.tool)
        step_started = time.perf_counter()
        if tool is None:
            return ToolCall(
                tool=planned.tool,
                args=planned.args,
                observation=f"工具 {planned.tool} 不存在。",
                ok=False,
                error="unknown_tool",
                duration_ms=int((time.perf_counter() - step_started) * 1000),
            )
        try:
            result = tool.run(planned.args)
            observation = str(result.get("observation") or "")
            payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
            ok = payload.get("error") is None
            return ToolCall(
                tool=planned.tool,
                args=planned.args,
                observation=observation,
                payload=payload,
                ok=ok,
                duration_ms=int((time.perf_counter() - step_started) * 1000),
            )
        except Exception as exc:  # tool crash must not loop forever
            logger.exception("Agent tool %s failed", planned.tool)
            return ToolCall(
                tool=planned.tool,
                args=planned.args,
                observation=f"工具执行异常：{exc}",
                ok=False,
                error=str(exc),
                duration_ms=int((time.perf_counter() - step_started) * 1000),
            )

    def _is_terminal(self, plan: AgentPlan, call: ToolCall) -> bool:
        if call.tool == "clarification":
            return True
        if call.tool == "no_answer":
            return True
        if call.tool in {"knowledge_search", "multi_doc_compare"}:
            if call.payload.get("grounded") and call.payload.get("hits"):
                return True
        if call.tool == "document_detail" and call.payload.get("found") and call.payload.get("excerpt"):
            # detail lookup confirms the doc content; conclude only when the
            # plan was a pure detail hunt.
            return False
        return False

    def _has_conclusion(self, steps: list[ToolCall]) -> bool:
        if not steps:
            return False
        last = steps[-1]
        if last.tool in {"clarification", "no_answer"}:
            return True
        if last.tool in {"knowledge_search", "multi_doc_compare"} and last.payload.get("grounded"):
            return True
        return False

    # ------------------------------------------------------------- replanning
    def _replan(self, question: str, steps: list[ToolCall]) -> AgentPlan | None:
        """One extra plan round after partial execution, LLM-free fallback."""
        if self.llm_service.disabled:
            return None
        observations = "\n".join(f"{i}. {s.tool}: {s.observation[:200]}" for i, s in enumerate(steps, 1))
        prompt = (
            "前一轮执行没有得出接地结论。基于已有观察，制定最多 2 步的补充计划。\n"
            f"工具：{', '.join(self.tools.keys())}\n"
            f"问题：{question}\n观察：\n{observations}\n"
            "只输出 JSON：{\"steps\": [{\"tool\": str, \"args\": {}, \"reason\": str}]}。"
        )
        try:
            payload = self.llm_service._extract_json_block(
                self.llm_service._generate_text(
                    [{"role": "system", "content": "你是重规划器，只输出 JSON。"}, {"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=200,
                )
            )
        except Exception:
            return None
        if not payload:
            return None
        known = set(self.tools)
        steps_out = [
            PlanStep(tool=str(s.get("tool")), args=s.get("args") if isinstance(s.get("args"), dict) else {})
            for s in (payload.get("steps") or [])
            if isinstance(s, dict) and str(s.get("tool")) in known
        ]
        if not steps_out:
            return None
        return AgentPlan(intent="replan", confidence=0.5, steps=steps_out, rationale="LLM 重规划")

    # -------------------------------------------------------------- finalize
    def _finalize(
        self,
        question: str,
        conversation_id: str,
        plan: AgentPlan,
        steps: list[ToolCall],
        citations: list[dict[str, Any]],
        elapsed_ms: int,
    ) -> AgentResult:
        step_records = [
            {
                "step": index,
                "type": "tool",
                "tool": call.tool,
                "args": call.args,
                "observation": call.observation,
                "duration_ms": call.duration_ms,
                "ok": call.ok,
            }
            for index, call in enumerate(steps, 1)
        ]
        tools_used = list(dict.fromkeys(call.tool for call in steps))
        followup = None
        for call in steps:
            if call.tool == "clarification":
                followup = call.payload.get("clarification_question") or call.observation
        no_answer_final = bool(steps) and steps[-1].tool == "no_answer"

        knowledge_calls = [call for call in steps if call.tool in {"knowledge_search", "multi_doc_compare", "document_detail"}]
        grounded = any(call.payload.get("grounded") for call in steps if call.tool in {"knowledge_search", "multi_doc_compare"})
        if grounded and not citations:
            for call in steps:
                citations.extend(call.payload.get("hits", []))
        all_hits = []
        for call in steps:
            for hit in call.payload.get("hits", []):
                if hit not in all_hits:
                    all_hits.append(hit)

        if followup:
            answer = followup
            grounded = False
            confidence_note = "need_clarification"
        elif no_answer_final or not grounded:
            answer = "当前知识库中没有找到相关信息。"
            grounded = False
            confidence_note = "no_grounded_evidence"
        else:
            answer = self._compose_final_answer(question, steps, knowledge_calls)
            grounded = bool(answer) and not self._signals_insufficient(answer)
            confidence_note = "grounded_evidence_chain"

        return AgentResult(
            session_id="",
            conversation_id=conversation_id,
            answer=answer,
            grounded=grounded,
            intent=plan.intent,
            confidence=plan.confidence,
            tools_used=tools_used,
            citations=all_hits[:10],
            steps=step_records,
            latency_ms=elapsed_ms,
            confidence_note=confidence_note,
            escalated=not grounded and not followup,
            followup_question=followup,
        )

    def _compose_final_answer(self, question: str, steps: list[ToolCall], knowledge_calls: list[ToolCall]) -> str:
        """Deterministic extractive composition from collected evidence, then trim."""
        from app.domain import QueryAnalysis, RetrievalHit

        hits = self._collect_hits(steps)
        if not hits:
            return ""
        llm = self.llm_service
        retrieval_hits = [
            RetrievalHit(
                chunk_id=f"agent-{index}",
                document_id="",
                version_id="",
                file_name=raw.get("file_name", ""),
                page_or_slide=raw.get("page_or_slide", ""),
                section_path="",
                snippet=(raw.get("snippet") or "")[:220],
                markdown_text=raw.get("snippet") or "",
                plain_text=raw.get("snippet") or "",
                trust_level="agent",
                source_type="agent",
                fusion_score=0.0,
                rerank_score=float(raw.get("score") or 0.0),
            )
            for index, raw in enumerate(hits, 1)
        ]
        try:
            analysis = QueryAnalysis(rewritten_query=question, question_type="factoid", answer_focus="", focus_terms=[])
            answer, _ = llm._compose_extract_answer(
                question,
                "factoid",
                analysis.answer_focus,
                [],
                retrieval_hits,
                True,
            )
            answer = (answer or "").strip()
            if answer and not self._signals_insufficient(answer):
                return answer[:260]
        except Exception:
            pass
        combined = " ".join((raw.get("snippet") or "") for raw in hits if raw.get("snippet"))
        return combined[:260]

    def _collect_hits(self, steps: list[ToolCall]) -> list[Any]:
        hits: list[Any] = []
        seen = set()
        for call in steps:
            for raw in call.payload.get("hits", []):
                key = (raw.get("file_name"), raw.get("page_or_slide"), raw.get("snippet"))
                if key not in seen:
                    seen.add(key)
                    hits.append(raw)
        return hits

    @staticmethod
    def _signals_insufficient(text: str) -> bool:
        return any(marker in text for marker in INSUFFICIENT_MARKERS)
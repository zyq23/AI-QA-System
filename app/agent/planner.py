"""Intent recognition + planning for the agent controller.

The planner is deliberately two-stage:
1. intent classifier (rules first, LLM only when rules are ambiguous) with a
   confidence score — low confidence routes to clarification instead of a hard
   answer (智能客服必备).
2. plan builder: picks tools and argument dicts for the plan-then-execute loop.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.agent.state import AgentPlan, PlanStep


class PlannerError(RuntimeError):
    pass


# ---------------------------------------------------------------- intent rules
_MULTI_SUBJECT_MARKERS = ("区别", "分别", "对比", "有什么不同", "各是", "各自", "一起列出", "同时给出")
_CALC_MARKERS = ("计算", "相乘", "相加", "乘以", "除以", "加上", "减去", "百分之")
_DATE_MARKERS = ("几天后", "多少天后", "周几", "星期几", "隔多少天", "日期", "几天前")
_CLARIFY_MARKERS = ("它", "这个", "那个", "上面说的", "刚才")
_LIST_MARKERS = ("哪些", "列举", "列出", "有哪几", "什么类型", "哪些功能")


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def classify_intent(question: str, history: list[dict[str, Any]] | None = None) -> tuple[str, float]:
    """Rule-based intent classification with a coarse confidence score."""
    text = question.strip()
    if not text:
        return "clarify", 0.9
    if _has_any(text, _MULTI_SUBJECT_MARKERS):
        return "multi_doc_compare", 0.85
    if re.search(r"\d", text) and _has_any(text, _CALC_MARKERS + ("等于多少", "等于几", "结果是")):
        return "math", 0.8
    if _has_any(text, _DATE_MARKERS):
        return "date_math", 0.75
    if _has_any(text, ("哪份资料", "哪个文件", "哪一页", "哪里提到", "出自")):
        return "document_detail", 0.7
    if _has_any(text, _CLARIFY_MARKERS) and len(text) <= 14 and history:
        return "clarify", 0.6
    if _has_any(text, _LIST_MARKERS) or _has_any(text, ("是什么", "多少", "是否", "能不能", "有没有")):
        return "knowledge_qa", 0.75
    if len(text) >= 4:
        return "knowledge_qa", 0.6
    return "clarify", 0.5


def refine_intent_with_llm(llm_service: Any, question: str, tools: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Ask the LLM to classify intent and emit a plan JSON. Returns None on failure.

    The prompt includes the tool table so the plan references real tool names.
    """
    tool_lines = "\n".join(
        f"- {t['name']}: {t['description']} 参数: {json.dumps(t['schema'].get('properties', {}), ensure_ascii=False)}"
        for t in tools
    )
    prompt = (
        "你是智能客服 Agent 的规划器。根据用户问题选择意图并制定 1-3 步工具计划。\n"
        f"可用工具：\n{tool_lines}\n"
        "只输出 JSON：{\"intent\": str, \"confidence\": 0-1, \"steps\": [{\"tool\": str, \"args\": {}, \"reason\": str}]}"
        "。如果问题含糊到无法回答，intent 填 clarify 并给一个 clarification 步骤。"
        "knowledge_search 的 args.query 必须是完整问题文本，禁止为空。\n"
        f"用户问题：{question}"
    )
    try:
        payload = llm_service._extract_json_block(
            llm_service._generate_text(
                [
                    {"role": "system", "content": "你是任务规划器，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=320,
            )
        )
    except Exception:
        return None
    if not payload or not isinstance(payload, dict):
        return None
    # Validate plan steps: tools must exist, knowledge_search/multi_doc_compare
    # args.query must be non-empty, and clarification must carry a real question;
    # a malformed LLM plan falls back to the rule plan.
    known = {t["name"] for t in tools}
    for step in payload.get("steps") or []:
        if not isinstance(step, dict) or str(step.get("tool")) not in known:
            return None
        if str(step.get("tool")) in {"knowledge_search", "multi_doc_compare"}:
            args = step.get("args")
            if not isinstance(args, dict) or not str(args.get("query") or args.get("subject_a") or "").strip():
                return None
        if str(step.get("tool")) == "clarification":
            args = step.get("args")
            if not isinstance(args, dict) or not str(args.get("question") or "").strip():
                return None
    return payload


def build_plan(
    question: str,
    history: list[dict[str, Any]] | None,
    tool_specs: list[dict[str, Any]],
    llm_service: Any | None = None,
    *,
    use_llm_planner: bool = True,
) -> AgentPlan:
    """Plan-then-execute: build the plan BEFORE running any tool.

    Rules produce a deterministic plan for high-confidence intents; the LLM
    refines intents only inside the knowledge_qa band where rules are weakest.
    """
    intent, confidence = classify_intent(question, history)
    steps: list[PlanStep] = []
    rationale = "规则意图分类"

    if intent == "multi_doc_compare":
        attribute = ""
        attr = re.search(r"(核心设备|核心组件|配置|参数|课程|专业|服务|价格|架构|定位|电话|厂家)", question)
        if attr:
            attribute = attr.group(1)
        subjects = _split_subjects(question)
        if len(subjects) >= 2:
            steps.append(
                PlanStep(
                    tool="multi_doc_compare",
                    args={"subject_a": subjects[0], "subject_b": subjects[1], "attribute": attribute},
                    reason="对比两个主题的证据",
                )
            )
        else:
            steps.append(PlanStep(tool="knowledge_search", args={"query": question, "top_k": 10}))
    elif intent == "math":
        expr = re.search(r"([\d\s+\-*/().%]{3,})", question)
        steps.append(PlanStep(tool="calculator", args={"expression": expr.group(1).strip() if expr else "0"}))
    elif intent == "date_math":
        steps.append(PlanStep(tool="date_utils", args=_build_date_args(question)))
    elif intent == "document_detail":
        doc = re.search(r"(?:哪份|哪个)(?:资料|文档|文件)", question)
        _ = doc  # source-locating questions still start with a search step
        steps.append(PlanStep(tool="knowledge_search", args={"query": question, "top_k": 10}))
        steps.append(PlanStep(tool="document_detail", args={"document": _guess_document(question)}))
    elif intent == "clarify":
        steps.append(PlanStep(tool="no_answer", args={"reason": f"问题「{question[:30]}」意图不明确，可补充上下文后再问。"}))
    else:  # knowledge_qa
        steps.append(PlanStep(tool="knowledge_search", args={"query": question, "top_k": 10}))
        if use_llm_planner and llm_service is not None and not llm_service.disabled and confidence < 0.7:
            refined = refine_intent_with_llm(llm_service, question, tool_specs)
            if refined:
                llm_intent = str(refined.get("intent") or "").strip()
                known = {spec["name"] for spec in tool_specs}
                llm_steps = [
                    PlanStep(
                        tool=str(step.get("tool")),
                        args=step.get("args") if isinstance(step.get("args"), dict) else {},
                        reason=str(step.get("reason") or ""),
                    )
                    for step in (refined.get("steps") or [])
                    if isinstance(step, dict) and str(step.get("tool")) in known
                ]
                if llm_intent and llm_steps:
                    intent, confidence = llm_intent, float(refined.get("confidence") or confidence)
                    steps = llm_steps
                    rationale = "LLM 规划器"
    return AgentPlan(intent=intent, confidence=confidence, steps=steps, rationale=rationale)


def _split_subjects(question: str) -> list[str]:
    """Split a compare question into its two subject phrases.

    The two sides may either share an attribute (``A和B的属性``) or carry
    separate attributes (``A的属性和B的属性``). Only the subject is passed to
    ``multi_doc_compare``; the planner extracts the shared attribute separately.
    """
    text = re.sub(r"[？?。！!]$", "", question.strip())
    text = re.sub(r"^(请把|把|请|请问)\s*", "", text)
    connector = re.search(r"(?:和|与|跟|及|以及)", text)
    if not connector:
        return []
    left = text[: connector.start()].strip(" 的，,、；; ")
    right = text[connector.end():].strip(" 的，,、；; ")

    # If a side explicitly has ``subject 的 attribute``, retain only the
    # subject. For shared-attribute questions this removes the right-side tail;
    # for per-side questions it removes each side's own attribute.
    def clean_side(side: str) -> str:
        side = re.sub(r"^(分别|各自|一起列出|同时给出)\s*", "", side)
        side = re.sub(r"(?:采用|使用|提供|支持)$", "", side)
        if "的" in side:
            side = side.split("的", 1)[0]
        side = re.sub(r"(?:采用|使用|提供|支持)$", "", side)
        side = re.sub(
            r"(?:核心设备|核心网关|主要设备|核心组件|设备组成|厂家电话|联系方式|生产厂家|制造商|配置|参数|价格|架构|定位|名称|指标|"
            r"视觉系统|物联|实验环境|开放实验环境|模型家族|战略|治理模式|方案年份|年份|建设内容|建设路径|"
            r"服务四项|三位一体|文化主线|算力资源|运营目标|技术方向|产品|各包含|各举|分别|有|是什么|是什么|各有哪些)$",
            "",
            side,
        )
        side = re.sub(r"(什么|哪些|哪一|哪个|如何|怎么|是多少|有什么|是|分别|分别是|分别为)$", "", side)
        return side.strip(" 的，,、；; ")

    subjects = [clean_side(left), clean_side(right)]
    return [subject for subject in subjects if len(subject) >= 2][:2]


def _build_date_args(question: str) -> dict[str, Any]:
    """Extract all supported date operations so deterministic results are complete."""
    args: dict[str, Any] = {"base": _extract_date(question)}
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", question)
    if "周几" in question or "星期几" in question:
        if dates:
            args["weekday_of"] = dates[-1]
    if dates and len(dates) >= 2 and "相隔" in question:
        args["base"], args["diff_from"] = dates[0], dates[1]
    offset = re.search(r"(?:\d{4}-\d{2}-\d{2})\s*(?:后|之后|前)\s*(\d+)\s*天|(?:\d+)\s*天\s*(?:后|之后|前)", question)
    if offset:
        number = next((group for group in offset.groups() if group is not None), None)
        days = int(number)
        if "前" in offset.group(0):
            days = -days
        args["offset_days"] = days
        if ("周几" in question or "星期几" in question) and args.get("base"):
            from datetime import date, timedelta
            base = date.fromisoformat(args["base"])
            args["weekday_of"] = (base + timedelta(days=days)).isoformat()
    return {key: value for key, value in args.items() if value is not None}


def _extract_date(question: str) -> str | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", question)
    return match.group(1) if match else None


def _guess_document(question: str) -> str:
    for keyword in ("机械臂", "实训套件", "公司介绍", "运营实施方案", "展厅", "ICT学院", "汇报"):
        if keyword in question:
            return keyword
    return ""

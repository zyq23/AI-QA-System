"""Agent tool registry: each tool is independent, unit-testable and carries a
JSON-schema description so the planner can reason over it.

Every tool returns a plain dict with "observation" (human-readable text) and
"payload" (structured data the controller and evaluator can consume).
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.domain import QueryAnalysis, RetrievalHit


@dataclass(slots=True)
class BaseTool(ABC):
    description: str = ""
    schema: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Subclasses define `name` as a plain class attribute; instances must
        # see the subclass value, not the dataclass field default.
        self.name = type(self).name  # noqa: attribute from type

    # Subclasses set `name` as a plain class attribute; it is NOT a dataclass
    # field so instances inherit the subclass value.
    name: str = "base_tool"

    @abstractmethod
    def run(self, args: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError

    def to_spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "schema": self.schema}


def _serialize_hits(hits: list[RetrievalHit], limit: int = 6) -> list[dict[str, Any]]:
    out = []
    for hit in hits[:limit]:
        quality = getattr(hit, "ocr_quality", None)
        if quality is None:
            quality = hit.raw_scores.get("ocr_quality", 1.0)
        out.append(
            {
                "chunk_id": hit.chunk_id,
                "document_id": hit.document_id,
                "version_id": hit.version_id,
                "file_name": hit.file_name,
                "page_or_slide": hit.page_or_slide,
                "section_path": hit.section_path,
                "plain_text": hit.plain_text,
                "markdown_text": hit.markdown_text,
                "snippet": (hit.snippet or hit.plain_text)[:400],
                "trust_level": hit.trust_level,
                "source_type": hit.source_type,
                "ocr_quality": round(float(quality or 0.0), 3),
                "score": round(float(hit.rerank_score or hit.fusion_score or 0.0), 3),
            }
        )
    return out


class KnowledgeSearchTool(BaseTool):
    """Search the knowledge base through the RAG pipeline and return cited evidence."""

    name = "knowledge_search"
    description = (
        "在知识库中检索与给定问题相关的证据块，返回带引用的片段（文档/页/小节）和"
        "评估后的接地结论。用于回答事实、枚举、定义类问题。"
    )
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "要检索的问题或关键词"},
            "top_k": {"type": "integer", "description": "返回证据条数，默认 6"},
        },
        "required": ["query"],
    }

    def __init__(self, chat_service: Any) -> None:
        self.chat_service = chat_service

    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            return {"observation": "缺少检索词 query。", "payload": {"grounded": False}}
        top_k = int(args.get("top_k") or 6)
        llm = self.chat_service.llm_service
        analysis = QueryAnalysis(
            rewritten_query=query,
            question_type=llm._infer_question_type(query),
            answer_focus=llm._build_answer_focus(query, llm._infer_question_type(query), llm._extract_focus_terms(query)),
            focus_terms=llm._extract_focus_terms(query),
        )
        hits, grounded = self.chat_service._multi_query_retrieve(query, analysis, top_k)
        combined = "\n".join(h.plain_text for h in hits[:6])
        return {
            "observation": (
                "检索完成：找到 " + str(len(hits)) + " 条证据，接地=" + str(grounded) + "。\n"
                + ("\n".join(f"[证据 {i}] {h.snippet}" for i, h in enumerate(hits[:4], 1)))
            ),
            "payload": {
                "grounded": grounded,
                "hits": _serialize_hits(hits),
                "combined_excerpt": combined[:1600],
            },
        }


class DocumentDetailTool(BaseTool):
    """Fetch full text slices of a document/page by name or page number."""

    name = "document_detail"
    description = (
        "按文档名（或文档名+页码/幻灯片号）取该页的全文切片。当问题明确指向某份资料"
        "（如'实训套件用户手册'）且检索不到时使用，返回该文档指定页的完整文本。"
    )
    schema = {
        "type": "object",
        "properties": {
            "document": {"type": "string", "description": "文档名关键字，如'机械臂'、'实训套件'" },
            "page": {"type": "string", "description": "页码或幻灯片号，如 docx/slide-3/page-12，可省略"},
            "limit_chars": {"type": "integer", "description": "返回最大字符数，默认 2000"},
        },
        "required": ["document"],
    }

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    @staticmethod
    def _chunk_rows(repository: Any, document_id: str, page: str, limit: int) -> list[dict[str, Any]]:
        with repository.db.connect() as conn:
            conn.row_factory = None
            if page:
                rows = conn.execute(
                    "SELECT page_or_slide, section_path, plain_text FROM chunks "
                    "WHERE document_id = ? AND (page_or_slide = ? OR section_path LIKE ?) LIMIT ?",
                    (document_id, page, f"%{page}%", limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT page_or_slide, section_path, plain_text FROM chunks "
                    "WHERE document_id = ? LIMIT ?",
                    (document_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]

    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        document = str(args.get("document") or "").strip()
        if not document:
            return {"observation": "缺少文档关键字 document。", "payload": {}}
        page = str(args.get("page") or "").strip()
        limit_chars = int(args.get("limit_chars") or 2000)
        docs = self.repository.list_documents()
        matched = [
            {"id": d.get("document_id"), "title": d.get("title")}
            for d in docs
            if document in (d.get("title") or "") or document in (d.get("canonical_name") or "")
        ]
        if not matched:
            return {"observation": f"未找到包含「{document}」的文档。", "payload": {}}
        text_parts: list[str] = []
        for doc in matched[:3]:
            for row in self._chunk_rows(self.repository, doc["id"], page, 8):
                label = row.get("page_or_slide") or row.get("section_path") or ""
                text_parts.append(f"[{label}] {row.get('plain_text') or ''}")
        if not text_parts:
            return {
                "observation": f"文档「{matched[0]['title']}」存在，但没有找到匹配页的文本。",
                "payload": {"found": True, "documents": [m["title"] for m in matched]},
            }
        excerpt = "\n".join(text_parts)[:limit_chars]
        return {
            "observation": "文档切片如下：\n" + excerpt,
            "payload": {"found": True, "documents": [m["title"] for m in matched], "excerpt": excerpt},
        }


class MultiDocCompareTool(BaseTool):
    """Compare evidence across two (or more) subjects/document clusters."""

    name = "multi_doc_compare"
    description = (
        "跨文档/跨主题对比。给定两个实体或主题（如'机械臂'vs'实训套件'），分别检索"
        "各自的证据并并列返回，用于'区别/分别/对比'类多跳问题。"
    )
    schema = {
        "type": "object",
        "properties": {
            "subject_a": {"type": "string", "description": "第一个主题/实体"},
            "subject_b": {"type": "string", "description": "第二个主题/实体"},
            "attribute": {"type": "string", "description": "要比较的属性（可选），如 核心设备/价格/架构"},
            "top_k": {"type": "integer", "description": "每个主题返回证据条数，默认 4"},
        },
        "required": ["subject_a", "subject_b"],
    }

    def __init__(self, chat_service: Any) -> None:
        self.chat_service = chat_service

    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        a = str(args.get("subject_a") or "").strip()
        b = str(args.get("subject_b") or "").strip()
        attribute = str(args.get("attribute") or "").strip()
        top_k = int(args.get("top_k") or 4)
        if not a or not b:
            return {"observation": "需要 subject_a 和 subject_b。", "payload": {}}
        llm = self.chat_service.llm_service
        sides: dict[str, dict[str, Any]] = {}
        for label, subject in (("a", a), ("b", b)):
            query = subject if not attribute else f"{subject} {attribute}"
            analysis = QueryAnalysis(
                rewritten_query=query,
                question_type="factoid",
                answer_focus=subject,
                focus_terms=llm._extract_focus_terms(query),
            )
            hits, grounded = self.chat_service._multi_query_retrieve(query, analysis, top_k)
            sides[label] = {
                "subject": subject,
                "grounded": grounded,
                "hits": _serialize_hits(hits, limit=top_k),
                "combined": "\n".join(h.plain_text for h in hits[:4])[:1200],
            }
        all_hits: list[dict[str, Any]] = []
        for side in sides.values():
            for hit in side["hits"]:
                if hit not in all_hits:
                    all_hits.append(hit)
        grounded = all(bool(side["grounded"] and side["hits"]) for side in sides.values())
        comparison = {
            "attribute": attribute,
            "sides": {
                label: {
                    "subject": side["subject"],
                    "claims": [
                        {
                            "subject": side["subject"],
                            "attribute": attribute,
                            "evidence": side["hits"],
                            "citations": side["hits"],
                        }
                    ],
                    "citations": side["hits"],
                    "grounded": bool(side["grounded"] and side["hits"]),
                }
                for label, side in sides.items()
            },
            "missing_fields": [
                label for label, side in sides.items() if not side["grounded"] or not side["hits"]
            ],
        }
        observation = "\n\n".join(
            f"【{side['subject']}】接地={side['grounded']}\n{side['combined'][:400]}" for side in sides.values()
        )
        return {
            "observation": observation,
            "payload": {
                "grounded": grounded,
                "hits": all_hits,
                "sides": sides,
                "comparison": comparison,
                "missing_fields": comparison["missing_fields"],
            },
        }


class CalculatorTool(BaseTool):
    """Safe arithmetic evaluation for numbers mentioned in a question."""

    name = "calculator"
    description = "对问题中的数值做安全的四则运算/百分比计算。当问题包含'多少+数字运算'时使用。"
    schema = {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式，如 (3+2)*4、1800*1.1"},
        },
        "required": ["expression"],
    }

    _SAFE_RE = re.compile(r"^[\d\s+\-*/().%]+$")

    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        expression = str(args.get("expression") or "").strip()
        if not expression:
            return {"observation": "缺少表达式 expression。", "payload": {}}
        if not self._SAFE_RE.fullmatch(expression):
            return {
                "observation": "表达式包含非法字符，仅支持数字与 + - * / ( ) . %。",
                "payload": {"error": "invalid_expression"},
            }
        try:
            # % is converted to /100 in the safe subset
            safe = expression.replace("%", "/100")
            value = float(eval(safe, {"__builtins__": {}}, {}))
            rendered = f"{value:g}"
            return {
                "observation": f"计算结果：{expression} = {rendered}",
                "payload": {"expression": expression, "value": value, "rendered": rendered},
            }
        except Exception as exc:
            return {"observation": f"计算失败：{exc}", "payload": {"error": str(exc)}}


class DateUtilsTool(BaseTool):
    """Date arithmetic: today/N days later/weekday of a date."""

    name = "date_utils"
    description = "日期计算：N 天后/前、某日周几、间隔多少天。当问题涉及日期、时间差、周几时使用。"
    schema = {
        "type": "object",
        "properties": {
            "base": {"type": "string", "description": "基准日期 YYYY-MM-DD，缺省为今天"},
            "offset_days": {"type": "integer", "description": "日期偏移天数（正=之后，负=之前）"},
            "weekday_of": {"type": "string", "description": "要判断星期几的日期 YYYY-MM-DD"},
            "diff_from": {"type": "string", "description": "与 base 计算间隔天数的日期 YYYY-MM-DD"},
        },
    }

    @staticmethod
    def _parse(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None

    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        base = self._parse(args.get("base")) or date.today()
        results: list[str] = []
        payload: dict[str, Any] = {"base": base.isoformat()}
        offset = args.get("offset_days")
        if offset is not None:
            target = base + timedelta(days=int(offset))
            results.append(f"{base.isoformat()} 后 {offset} 天 = {target.isoformat()}（{DateUtilsTool._weekday_cn(target)}）")
            payload["offset_result"] = target.isoformat()
        weekday_of = self._parse(args.get("weekday_of"))
        if weekday_of:
            results.append(f"{weekday_of.isoformat()} 是{DateUtilsTool._weekday_cn(weekday_of)}")
            payload["weekday"] = weekday_of.strftime("%A")
        diff_from = self._parse(args.get("diff_from"))
        if diff_from:
            days = (diff_from - base).days
            results.append(f"{base.isoformat()} 与 {diff_from.isoformat()} 相隔 {days} 天")
            payload["diff_days"] = days
        if not results:
            results.append(f"今天 = {base.isoformat()}（{DateUtilsTool._weekday_cn(base)}）")
        return {"observation": "\n".join(results), "payload": payload}

    @staticmethod
    def _weekday_cn(value: date) -> str:
        return "一二三四五六日"[value.weekday()]


class ClarificationTool(BaseTool):
    """Ask the user a follow-up question when intent confidence is low."""

    name = "clarification"
    description = "当问题意图不明确或歧义时，向用户提出澄清问题，而不是强行作答。"
    schema = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "要追问用户的问题"},
            "hints": {"type": "array", "items": {"type": "string"}, "description": "可选候选项"},
        },
        "required": ["question"],
    }

    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        question = str(args.get("question") or "")
        hints = [str(h) for h in (args.get("hints") or [])][:4]
        text = question
        if hints:
            text += "（可选项：" + " / ".join(hints) + "）"
        return {
            "observation": "需要用户澄清：" + text,
            "payload": {"clarification_question": text, "hints": hints},
        }


class NoAnswerTool(BaseTool):
    """Correctly refuse when the knowledge base has no evidence for the claim."""

    name = "no_answer"
    description = "当知识库确实没有相关证据时，使用本工具给出正确的拒答回复，避免编造。"
    schema = {"type": "object", "properties": {"reason": {"type": "string", "description": "拒答原因"}}}

    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        reason = str(args.get("reason") or "")
        return {
            "observation": "当前知识库中没有找到相关信息，因此拒答。" + (f"（{reason}）" if reason else ""),
            "payload": {"no_answer": True, "reason": reason},
        }


def default_tools(chat_service: Any, repository: Any) -> dict[str, BaseTool]:
    tools: list[BaseTool] = [
        KnowledgeSearchTool(chat_service),
        MultiDocCompareTool(chat_service),
        DocumentDetailTool(repository),
        CalculatorTool(),
        DateUtilsTool(),
        ClarificationTool(),
        NoAnswerTool(),
    ]
    return {tool.name: tool for tool in tools}
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.domain import AnswerPayload, RetrievalHit
from app.repositories import Repository
from app.services.chat import ChatService


@dataclass(slots=True)
class TurnReport:
    case_id: str
    turn_index: int
    category: str
    question: str
    passed: bool
    citation_match: bool
    section_match: bool
    keyword_match: bool
    forbidden_match: bool
    insufficient_match: bool
    grounded_match: bool
    question_type_match: bool
    direct_match: bool
    no_leak_match: bool
    concise_match: bool
    fallback_clean: bool
    reviewer_intervened: bool
    grounded: bool
    latency_ms: int
    answer_length: int
    conversation_id: str
    answer_run_id: str | None
    answer: str
    grounded_answer: str
    inference_note: str
    question_type: str
    answer_focus: str
    review_issues: list[str]
    fallback_used: bool
    top_citation_file: str | None
    top_citation_section: str | None
    expected_files: list[str]
    expected_section_keywords: list[str]
    expected_answer_keywords: list[str]
    forbidden_answer_keywords: list[str]
    max_answer_length: int | None
    expected_question_type: str | None
    expected_directness: bool | None
    expected_insufficient: bool | None
    expected_grounded: bool | None


class EvaluationService:
    def __init__(self, settings: Settings, repository: Repository, chat_service: ChatService) -> None:
        self.settings = settings
        self.repository = repository
        self.chat_service = chat_service
        self.http_client: httpx.Client | None = None

    @staticmethod
    def _payload_from_api(data: dict[str, Any]) -> AnswerPayload:
        citations = [
            RetrievalHit(
                chunk_id=f"api-{index}",
                document_id=str(item.get("document_id") or ""),
                version_id="",
                file_name=str(item.get("file_name") or ""),
                page_or_slide=str(item.get("page_or_slide") or ""),
                section_path=str(item.get("section_path") or ""),
                snippet=str(item.get("snippet") or ""),
                markdown_text=str(item.get("snippet") or ""),
                plain_text=str(item.get("snippet") or ""),
                trust_level=str(item.get("trust_level") or ""),
                source_type="api_eval",
                fusion_score=float(item.get("score") or 0.0),
                rerank_score=float(item.get("score") or 0.0),
            )
            for index, item in enumerate(data.get("citations") or [], start=1)
        ]
        return AnswerPayload(
            conversation_id=str(data.get("conversation_id") or ""),
            answer=str(data.get("answer") or ""),
            grounded_answer=str(data.get("grounded_answer") or ""),
            inference_note=str(data.get("inference_note") or ""),
            grounded=bool(data.get("grounded")),
            citations=citations,
            rewritten_query="",
            latency_ms=int(data.get("latency_ms") or 0),
            question_type=str(data.get("question_type") or "unknown"),
            answer_focus=str(data.get("answer_focus") or ""),
            answer_run_id=data.get("answer_run_id"),
            review_issues=[str(item) for item in data.get("review_issues") or []],
            reviewer_intervened=bool(data.get("reviewer_intervened")),
            fallback_used=bool(data.get("fallback_used")),
        )

    def _ask_via_api(self, question: str, conversation_id: str | None) -> AnswerPayload:
        if not self.settings.eval_api_base_url:
            raise RuntimeError("EVAL_API_BASE_URL is not configured.")
        if self.http_client is not None:
            response = self.http_client.post(
                "/api/chat/query",
                json={
                    "question": question,
                    "conversation_id": conversation_id,
                },
            )
            response.raise_for_status()
            return self._payload_from_api(response.json())
        with httpx.Client(base_url=self.settings.eval_api_base_url.rstrip("/"), timeout=180.0) as client:
            response = client.post(
                "/api/chat/query",
                json={
                    "question": question,
                    "conversation_id": conversation_id,
                },
            )
            response.raise_for_status()
            return self._payload_from_api(response.json())

    @staticmethod
    def _contains_all(text: str, keywords: list[str]) -> bool:
        return all(keyword in text for keyword in keywords)

    @staticmethod
    def _contains_none(text: str, keywords: list[str]) -> bool:
        return all(keyword not in text for keyword in keywords)

    @staticmethod
    def _has_expected_file(citations: list[Any], expected_files: list[str]) -> bool:
        if not expected_files:
            return True
        candidates = {citation.file_name for citation in citations}
        return any(file_name in candidates for file_name in expected_files)

    @staticmethod
    def _has_expected_section(citations: list[Any], section_keywords: list[str]) -> bool:
        if not section_keywords:
            return True
        for citation in citations:
            if any(keyword in citation.section_path for keyword in section_keywords):
                return True
        return False

    @staticmethod
    def _mentions_insufficient(text: str) -> bool:
        return "当前知识库没有直接证据" in text or "当前知识库中没有找到" in text

    @staticmethod
    def _is_direct(answer: str) -> bool:
        normalized = answer.strip()
        if not normalized:
            return False
        if normalized.startswith(("当前知识库没有直接证据", "当前知识库中没有找到")):
            return True
        if "\n1." in normalized or normalized.count("\n") >= 2:
            return False
        return normalized.count("。") <= 3 and len(normalized) <= 140

    @staticmethod
    def _no_source_leak(answer: str) -> bool:
        return not any(token in answer for token in ("文件", "章节", "页码", "来源"))

    @staticmethod
    def _fallback_clean(answer_payload: Any) -> bool:
        if not answer_payload.fallback_used:
            return True
        answer = answer_payload.answer.strip()
        top_snippet = answer_payload.citations[0].snippet.strip() if answer_payload.citations else ""
        if "\n1." in answer or len(answer) > 140:
            return False
        if top_snippet and len(answer) > 80 and answer in top_snippet:
            return False
        return "自动拼接" not in answer_payload.inference_note

    @staticmethod
    def _load_cases(path: Path) -> list[dict[str, Any]]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def build_failed_case_dataset(
        latest_result: dict[str, Any],
        *,
        output_path: Path,
    ) -> dict[str, Any]:
        reports = latest_result.get("reports") or []
        failed_case_ids = {str(report.get("case_id")) for report in reports if not report.get("passed")}
        if not failed_case_ids:
            raise ValueError("Latest evaluation has no failed cases.")
        source_dataset = Path(str(latest_result.get("dataset") or "")).expanduser()
        if not source_dataset.is_absolute():
            source_dataset = source_dataset.resolve()
        if not source_dataset.exists():
            raise FileNotFoundError(f"Source evaluation dataset not found: {source_dataset}")
        source_cases = EvaluationService._load_cases(source_dataset)
        selected_cases = [case for case in source_cases if str(case.get("id")) in failed_case_ids]
        if not selected_cases:
            raise ValueError("Failed cases could not be reconstructed from the source dataset.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now().astimezone().isoformat(),
            "source_dataset": str(source_dataset),
            "failed_case_ids": sorted(failed_case_ids),
            "case_count": len(selected_cases),
            "cases": selected_cases,
        }
        output_path.write_text(json.dumps(selected_cases, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "dataset_path": str(output_path),
            "case_count": len(selected_cases),
            "failed_case_ids": sorted(failed_case_ids),
            "source_dataset": str(source_dataset),
            "meta": payload,
        }

    def _evaluate_turn(
        self,
        *,
        case_id: str,
        category: str,
        turn_index: int,
        question: str,
        answer_payload: Any,
        expected_files: list[str],
        expected_section_keywords: list[str],
        expected_answer_keywords: list[str],
        forbidden_answer_keywords: list[str],
        max_answer_length: int | None,
        expected_question_type: str | None,
        expected_directness: bool | None,
        expected_insufficient: bool | None,
        expected_grounded: bool | None,
    ) -> TurnReport:
        answer_text = "\n".join(
            [
                answer_payload.answer,
                answer_payload.grounded_answer,
                answer_payload.inference_note,
            ]
        )
        citation_match = self._has_expected_file(answer_payload.citations, expected_files)
        section_match = self._has_expected_section(answer_payload.citations, expected_section_keywords)
        keyword_match = self._contains_all(answer_payload.answer, expected_answer_keywords) if expected_answer_keywords else True
        forbidden_match = (
            self._contains_none(answer_payload.answer, forbidden_answer_keywords) if forbidden_answer_keywords else True
        )
        insufficient_detected = self._mentions_insufficient(answer_payload.answer)
        insufficient_match = (
            insufficient_detected == expected_insufficient if expected_insufficient is not None else True
        )
        grounded_match = answer_payload.grounded == expected_grounded if expected_grounded is not None else True
        question_type_match = (
            answer_payload.question_type == expected_question_type if expected_question_type is not None else True
        )
        direct_detected = self._is_direct(answer_payload.answer)
        direct_match = direct_detected == expected_directness if expected_directness is not None else direct_detected
        no_leak_match = self._no_source_leak(answer_payload.answer)
        concise_match = (
            len(answer_payload.answer) <= max_answer_length if max_answer_length is not None else len(answer_payload.answer) <= 140
        )
        fallback_clean = self._fallback_clean(answer_payload)
        passed = all(
            [
                citation_match,
                section_match,
                keyword_match,
                forbidden_match,
                insufficient_match,
                grounded_match,
                question_type_match,
                direct_match,
                no_leak_match,
                concise_match,
                fallback_clean,
            ]
        )
        top_citation = answer_payload.citations[0] if answer_payload.citations else None
        return TurnReport(
            case_id=case_id,
            turn_index=turn_index,
            category=category,
            question=question,
            passed=passed,
            citation_match=citation_match,
            section_match=section_match,
            keyword_match=keyword_match,
            forbidden_match=forbidden_match,
            insufficient_match=insufficient_match,
            grounded_match=grounded_match,
            question_type_match=question_type_match,
            direct_match=direct_match,
            no_leak_match=no_leak_match,
            concise_match=concise_match,
            fallback_clean=fallback_clean,
            reviewer_intervened=answer_payload.reviewer_intervened,
            grounded=answer_payload.grounded,
            latency_ms=answer_payload.latency_ms,
            answer_length=len(answer_payload.answer),
            conversation_id=answer_payload.conversation_id,
            answer_run_id=answer_payload.answer_run_id,
            answer=answer_payload.answer,
            grounded_answer=answer_payload.grounded_answer,
            inference_note=answer_payload.inference_note,
            question_type=answer_payload.question_type,
            answer_focus=answer_payload.answer_focus,
            review_issues=list(answer_payload.review_issues),
            fallback_used=answer_payload.fallback_used,
            top_citation_file=top_citation.file_name if top_citation else None,
            top_citation_section=top_citation.section_path if top_citation else None,
            expected_files=expected_files,
            expected_section_keywords=expected_section_keywords,
            expected_answer_keywords=expected_answer_keywords,
            forbidden_answer_keywords=forbidden_answer_keywords,
            max_answer_length=max_answer_length,
            expected_question_type=expected_question_type,
            expected_directness=expected_directness,
            expected_insufficient=expected_insufficient,
            expected_grounded=expected_grounded,
        )

    def _run_case(self, case: dict[str, Any]) -> list[TurnReport]:
        reports: list[TurnReport] = []
        conversation_id: str | None = None
        turns = case.get("turns")
        if not turns:
            turns = [
                {
                    "question": case["question"],
                    "expected_files": case.get("expected_files", []),
                    "expected_section_keywords": case.get("expected_section_keywords", []),
                    "expected_answer_keywords": case.get("expected_answer_keywords", case.get("answer_keywords", [])),
                    "forbidden_answer_keywords": case.get("forbidden_answer_keywords", []),
                    "max_answer_length": case.get("max_answer_length"),
                    "expected_question_type": case.get("expected_question_type"),
                    "expected_directness": case.get("expected_directness"),
                    "expected_insufficient": case.get("expected_insufficient"),
                    "expected_grounded": case.get("expected_grounded"),
                }
            ]

        for index, turn in enumerate(turns, start=1):
            if self.settings.eval_api_base_url:
                payload = self._ask_via_api(turn["question"], conversation_id)
            else:
                payload = self.chat_service.answer(turn["question"], conversation_id=conversation_id)
            conversation_id = payload.conversation_id
            reports.append(
                self._evaluate_turn(
                    case_id=case["id"],
                    category=case["category"],
                    turn_index=index,
                    question=turn["question"],
                    answer_payload=payload,
                    expected_files=turn.get("expected_files", case.get("expected_files", [])),
                    expected_section_keywords=turn.get(
                        "expected_section_keywords",
                        case.get("expected_section_keywords", []),
                    ),
                    expected_answer_keywords=turn.get(
                        "expected_answer_keywords",
                        turn.get("answer_keywords", case.get("expected_answer_keywords", case.get("answer_keywords", []))),
                    ),
                    forbidden_answer_keywords=turn.get(
                        "forbidden_answer_keywords",
                        case.get("forbidden_answer_keywords", []),
                    ),
                    max_answer_length=turn.get("max_answer_length", case.get("max_answer_length")),
                    expected_question_type=turn.get("expected_question_type", case.get("expected_question_type")),
                    expected_directness=turn.get("expected_directness", case.get("expected_directness")),
                    expected_insufficient=turn.get("expected_insufficient", case.get("expected_insufficient")),
                    expected_grounded=turn.get("expected_grounded", case.get("expected_grounded")),
                )
            )
        return reports

    @staticmethod
    def _rate(reports: list[TurnReport], attr: str, predicate: Any | None = None) -> float | None:
        if not reports:
            return 0.0
        if predicate is None:
            matched = sum(1 for report in reports if bool(getattr(report, attr)))
            return round(matched / len(reports), 4)
        scoped = [report for report in reports if predicate(report)]
        if not scoped:
            return None
        matched = sum(1 for report in scoped if bool(getattr(report, attr)))
        return round(matched / len(scoped), 4)

    def _summarize(self, reports: list[TurnReport]) -> dict[str, Any]:
        total = len(reports)
        passed = sum(1 for report in reports if report.passed)
        quality_issue_breakdown: dict[str, int] = {}
        failed_check_breakdown = {
            "citation_match": 0,
            "section_match": 0,
            "keyword_match": 0,
            "forbidden_match": 0,
            "insufficient_match": 0,
            "grounded_match": 0,
            "question_type_match": 0,
            "direct_match": 0,
            "no_leak_match": 0,
            "concise_match": 0,
            "fallback_clean": 0,
        }
        category_breakdown: dict[str, dict[str, int]] = {}
        for report in reports:
            category_stats = category_breakdown.setdefault(report.category, {"total": 0, "passed": 0})
            category_stats["total"] += 1
            if report.passed:
                category_stats["passed"] += 1
            for issue in report.review_issues:
                quality_issue_breakdown[issue] = quality_issue_breakdown.get(issue, 0) + 1
            for key in failed_check_breakdown:
                if not getattr(report, key):
                    failed_check_breakdown[key] += 1
        return {
            "total_turns": total,
            "passed_turns": passed,
            "pass_rate": round(passed / total, 4) if total else 0.0,
            "citation_match_rate": self._rate(reports, "citation_match"),
            "keyword_match_rate": self._rate(reports, "keyword_match"),
            "direct_answer_rate": self._rate(reports, "direct_match"),
            "no_leak_rate": self._rate(reports, "no_leak_match"),
            "concise_rate": self._rate(reports, "concise_match"),
            "fallback_rate": round(sum(1 for report in reports if report.fallback_used) / total, 4) if total else 0.0,
            "fallback_clean_rate": self._rate(reports, "fallback_clean"),
            "reviewer_intervention_rate": round(
                sum(1 for report in reports if report.reviewer_intervened) / total,
                4,
            )
            if total
            else 0.0,
            "followup_resolution_rate": self._rate(
                reports,
                "passed",
                predicate=lambda report: report.expected_question_type == "followup" or report.category == "multi_turn",
            ),
            "insufficient_match_rate": self._rate(
                reports,
                "insufficient_match",
                predicate=lambda report: report.expected_insufficient is not None,
            ),
            "grounded_match_rate": self._rate(
                reports,
                "grounded_match",
                predicate=lambda report: report.expected_grounded is not None,
            ),
            "quality_issue_breakdown": dict(sorted(quality_issue_breakdown.items(), key=lambda item: item[1], reverse=True)),
            "failed_check_breakdown": failed_check_breakdown,
            "category_breakdown": category_breakdown,
            "avg_latency_ms": round(sum(report.latency_ms for report in reports) / total, 2) if total else 0.0,
            "avg_answer_length": round(sum(report.answer_length for report in reports) / total, 2) if total else 0.0,
        }

    @staticmethod
    def _formal_bucket(case: dict[str, Any], report: TurnReport) -> str:
        expected_result_mode = str(case.get("expected_result_mode") or "")
        blocking_reason = str(case.get("blocking_is_correct_if_any") or "none")
        blocked_as_expected = (
            report.expected_insufficient is True
            and report.insufficient_match
            and report.direct_match
            and report.no_leak_match
        )
        compact_answer_pass = all(
            [
                report.citation_match,
                report.keyword_match,
                report.forbidden_match,
                report.grounded_match,
                report.direct_match,
                report.no_leak_match,
                report.concise_match,
                report.fallback_clean,
            ]
        )
        if expected_result_mode == "must_block":
            if blocking_reason == "route_conflict":
                return "correct_block" if blocked_as_expected or not report.citation_match else "wrong_release"
            return "correct_block" if blocked_as_expected else "wrong_release"
        if expected_result_mode in {"must_answer", "must_answer_compact", "must_degrade"}:
            return "answer_pass" if compact_answer_pass else "wrong_block"
        return "answer_pass" if report.passed else "wrong_block"

    @classmethod
    def build_formal_summary(
        cls,
        *,
        dataset_cases: list[dict[str, Any]],
        reports: list[TurnReport],
        source_report: str | None = None,
    ) -> dict[str, Any]:
        case_by_id = {str(case.get("id")): case for case in dataset_cases}
        turn_one_reports = [report for report in reports if report.turn_index == 1]
        formal_reports: list[dict[str, Any]] = []
        bucket_counts = {
            "answer_pass": 0,
            "correct_block": 0,
            "wrong_release": 0,
            "wrong_block": 0,
        }
        must_answer_compact = 0
        must_block = 0

        for report in turn_one_reports:
            case = case_by_id.get(report.case_id, {})
            expected_result_mode = str(case.get("expected_result_mode") or "")
            if expected_result_mode == "must_answer_compact":
                must_answer_compact += 1
            elif expected_result_mode == "must_block":
                must_block += 1
            bucket = cls._formal_bucket(case, report)
            bucket_counts[bucket] += 1
            formal_reports.append(
                {
                    "id": report.case_id,
                    "expected_result_mode": expected_result_mode,
                    "blocking_is_correct_if_any": str(case.get("blocking_is_correct_if_any") or "none"),
                    "formal_bucket": bucket,
                    "grounded": report.grounded,
                    "citation_match": report.citation_match,
                    "keyword_match": report.keyword_match,
                    "question_type_match": report.question_type_match,
                    "reviewer_intervened": report.reviewer_intervened,
                    "fallback_used": report.fallback_used,
                    "top_citation_file": report.top_citation_file,
                    "top_citation_section": report.top_citation_section,
                    "answer": report.answer,
                }
            )

        return {
            "generated_at": datetime.now().astimezone().isoformat(),
            "source_report": source_report,
            "dataset": None,
            "formal_summary": {
                "total": len(turn_one_reports),
                "must_answer_compact": must_answer_compact,
                "must_block": must_block,
                "answer_pass": bucket_counts["answer_pass"],
                "correct_block": bucket_counts["correct_block"],
                "wrong_release": bucket_counts["wrong_release"],
                "wrong_block": bucket_counts["wrong_block"],
            },
            "formal_reports": formal_reports,
        }

    def run(self, dataset_path: Path | None = None, output_dir: Path | None = None) -> dict[str, Any]:
        dataset_path = dataset_path or self.settings.eval_dataset_path
        output_dir = output_dir or self.settings.eval_results_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        dataset_cases = self._load_cases(dataset_path)
        reports: list[TurnReport] = []
        for case in dataset_cases:
            reports.extend(self._run_case(case))

        summary = self._summarize(reports)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"eval_{timestamp}.json"
        payload = {
            "generated_at": datetime.now().astimezone().isoformat(),
            "dataset": str(dataset_path),
            "summary": summary,
            "reports": [asdict(report) for report in reports],
            "report_path": str(output_path),
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        formal_summary_path = output_dir / f"eval_{timestamp}_formal_summary.json"
        formal_summary = self.build_formal_summary(
            dataset_cases=dataset_cases,
            reports=reports,
            source_report=str(output_path),
        )
        formal_summary["dataset"] = str(dataset_path)
        formal_summary_path.write_text(json.dumps(formal_summary, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["formal_summary_path"] = str(formal_summary_path)
        return payload

    def run_job(self, job_id: str, dataset_path: Path | None = None, output_dir: Path | None = None) -> None:
        self.repository.update_job(job_id, status="running", message="问答验收执行中")
        try:
            payload = self.run(dataset_path=dataset_path, output_dir=output_dir)
            summary = payload["summary"]
            message = (
                f"验收完成：{summary['passed_turns']}/{summary['total_turns']} 通过，"
                f"通过率 {summary['pass_rate']:.2%}，"
                f"直接回答率 {summary['direct_answer_rate']:.2%}"
            )
            self.repository.update_job(job_id, status="completed", message=message, result=payload)
        except Exception as exc:
            self.repository.update_job(job_id, status="failed", message=str(exc), result={})
            raise

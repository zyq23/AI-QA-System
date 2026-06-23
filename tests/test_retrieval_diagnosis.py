from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.run_retrieval_diagnosis import (
    _answer_stage_blocker,
    _build_answer_stage_recommendation,
    _build_summary,
    _build_route_conflict_summary,
    _build_route_probe_summary,
    _dataset_version_snapshot,
    _index_diagnosed_entries,
    _keyword_coverage,
    _route_probe,
    _runtime_retrieval_config_snapshot,
)


def test_answer_stage_blocker_distinguishes_retrieval_failure_from_answer_gating():
    positive_case = {"expected_grounded": True}
    negative_case = {"expected_grounded": False}

    assert _answer_stage_blocker(positive_case, "none", "grounded_supported", "not_applicable") == "none"
    assert _answer_stage_blocker(positive_case, "none", "not_grounded", "not_applicable") == "grounding_insufficient"
    assert _answer_stage_blocker(positive_case, "none", "grounded_supported", "coverage_insufficient") == "coverage_insufficient"
    assert _answer_stage_blocker(positive_case, "fake_grounded", "fake_grounded", "not_applicable") == "fake_grounded"
    assert _answer_stage_blocker(positive_case, "parser_upstream", "grounded_supported", "not_applicable") == "parser_upstream"
    assert _answer_stage_blocker(negative_case, "none", "correct_negative", "not_applicable") == "none"
    assert _answer_stage_blocker(negative_case, "fake_grounded", "false_positive", "not_applicable") == "negative_grounding_mismatch"


def test_build_summary_tracks_failure_counts_and_answer_stage_blockers():
    entries = [
        {
            "question_id": "q-1",
            "failure_type": "none",
            "answer_stage_blocker": "none",
            "allow_answer_stage": True,
        },
        {
            "question_id": "q-2",
            "failure_type": "none",
            "answer_stage_blocker": "grounding_insufficient",
            "allow_answer_stage": False,
        },
        {
            "question_id": "q-3",
            "failure_type": "parser_upstream",
            "answer_stage_blocker": "parser_upstream",
            "allow_answer_stage": False,
        },
        {
            "question_id": "q-4",
            "failure_type": "coverage_insufficient",
            "answer_stage_blocker": "coverage_insufficient",
            "allow_answer_stage": False,
        },
    ]

    summary = _build_summary(entries)

    assert summary["total_cases"] == 4
    assert summary["answer_ready_cases"] == 1
    assert summary["failure_counts"] == {
        "none": 2,
        "parser_upstream": 1,
        "coverage_insufficient": 1,
    }
    assert summary["answer_stage_blocker_counts"] == {
        "none": 1,
        "grounding_insufficient": 1,
        "parser_upstream": 1,
        "coverage_insufficient": 1,
    }
    assert summary["answer_ready_question_ids"] == ["q-1"]
    assert summary["blocked_question_ids"] == ["q-2", "q-3", "q-4"]


def test_dataset_version_snapshot_exposes_p0_and_p1_sources():
    snapshot = _dataset_version_snapshot("data/evals/ppt_company_p0_8.json", "data/evals/ppt_company_p1_8.json")

    assert snapshot == {
        "P0": "data/evals/ppt_company_p0_8.json",
        "P1": "data/evals/ppt_company_p1_8.json",
    }


def test_answer_stage_recommendation_aggregates_across_datasets():
    datasets = [
        {
            "name": "P0",
            "summary": {
                "answer_ready_question_ids": ["p0-01", "p0-05"],
                "blocked_question_ids": ["p0-02"],
            },
            "questions": [
                {
                    "question_id": "p0-01",
                    "question": "已放行题",
                    "allow_answer_stage": True,
                    "failure_type": "none",
                    "answer_stage_blocker": "none",
                    "grounded_judgement": "grounded_supported",
                    "coverage_judgement": "not_applicable",
                },
                {
                    "question_id": "p0-02",
                    "question": "被阻塞题",
                    "allow_answer_stage": False,
                    "failure_type": "parser_upstream",
                    "answer_stage_blocker": "parser_upstream",
                    "grounded_judgement": "grounded_supported",
                    "coverage_judgement": "not_applicable",
                },
            ],
        },
        {
            "name": "P1",
            "summary": {
                "answer_ready_question_ids": ["p1-01"],
                "blocked_question_ids": ["p1-03", "p1-05"],
            },
            "questions": [
                {
                    "question_id": "p1-01",
                    "question": "已放行题",
                    "allow_answer_stage": True,
                    "failure_type": "none",
                    "answer_stage_blocker": "none",
                    "grounded_judgement": "grounded_supported",
                    "coverage_judgement": "sufficient",
                },
                {
                    "question_id": "p1-03",
                    "question": "阻塞题 1",
                    "allow_answer_stage": False,
                    "failure_type": "none",
                    "answer_stage_blocker": "grounding_insufficient",
                    "grounded_judgement": "not_grounded",
                    "coverage_judgement": "sufficient",
                },
                {
                    "question_id": "p1-05",
                    "question": "阻塞题 2",
                    "allow_answer_stage": False,
                    "failure_type": "none",
                    "answer_stage_blocker": "grounding_insufficient",
                    "grounded_judgement": "not_grounded",
                    "coverage_judgement": "not_applicable",
                },
            ],
        },
    ]

    recommendation = _build_answer_stage_recommendation(datasets)

    assert recommendation == {
        "answer_ready_question_ids": ["p0-01", "p0-05", "p1-01"],
        "blocked_question_ids": ["p0-02", "p1-03", "p1-05"],
        "answer_ready_case_count": 3,
        "blocked_case_count": 3,
        "dataset_breakdown": {
            "P0": {
                "answer_ready_question_ids": ["p0-01", "p0-05"],
                "blocked_question_ids": ["p0-02"],
            },
            "P1": {
                "answer_ready_question_ids": ["p1-01"],
                "blocked_question_ids": ["p1-03", "p1-05"],
            },
        },
        "answer_ready_case_details": [
            {
                "dataset": "P0",
                "question_id": "p0-01",
                "question": "已放行题",
                "failure_type": "none",
                "answer_stage_blocker": "none",
                "grounded_judgement": "grounded_supported",
                "coverage_judgement": "not_applicable",
            },
            {
                "dataset": "P1",
                "question_id": "p1-01",
                "question": "已放行题",
                "failure_type": "none",
                "answer_stage_blocker": "none",
                "grounded_judgement": "grounded_supported",
                "coverage_judgement": "sufficient",
            },
        ],
        "blocked_by_answer_stage_blocker": {
            "parser_upstream": 1,
            "grounding_insufficient": 2,
        },
        "blocked_by_failure_type": {
            "parser_upstream": 1,
            "none": 2,
        },
        "blocked_question_ids_by_answer_stage_blocker": {
            "parser_upstream": ["p0-02"],
            "grounding_insufficient": ["p1-03", "p1-05"],
        },
        "blocked_question_ids_by_failure_type": {
            "parser_upstream": ["p0-02"],
            "none": ["p1-03", "p1-05"],
        },
        "blocked_case_details": [
            {
                "dataset": "P0",
                "question_id": "p0-02",
                "question": "被阻塞题",
                "failure_type": "parser_upstream",
                "answer_stage_blocker": "parser_upstream",
                "grounded_judgement": "grounded_supported",
                "coverage_judgement": "not_applicable",
            },
            {
                "dataset": "P1",
                "question_id": "p1-03",
                "question": "阻塞题 1",
                "failure_type": "none",
                "answer_stage_blocker": "grounding_insufficient",
                "grounded_judgement": "not_grounded",
                "coverage_judgement": "sufficient",
            },
            {
                "dataset": "P1",
                "question_id": "p1-05",
                "question": "阻塞题 2",
                "failure_type": "none",
                "answer_stage_blocker": "grounding_insufficient",
                "grounded_judgement": "not_grounded",
                "coverage_judgement": "not_applicable",
            },
        ],
    }


def test_runtime_retrieval_config_snapshot_keeps_route_observability_fields():
    settings = SimpleNamespace(
        retrieval_backend="ragflow",
        retrieval_mode="hybrid",
        ragflow_prefer_local_grounded=True,
        ragflow_local_grounded_score_threshold=0.15,
        ragflow_fallback_timeout_ms=6000,
        ragflow_timeout_seconds=20,
    )

    snapshot = _runtime_retrieval_config_snapshot(settings)

    assert snapshot == {
        "retrieval_backend": "ragflow",
        "retrieval_mode": "hybrid",
        "ragflow_prefer_local_grounded": True,
        "ragflow_local_grounded_score_threshold": 0.15,
        "ragflow_fallback_timeout_ms": 6000,
        "ragflow_timeout_seconds": 20,
    }


def test_keyword_coverage_reports_matched_and_missing_keywords():
    matched, missing = _keyword_coverage(
        "通用大模型 OCR 语音识别等",
        ["通用大模型", "OCR", "知识元数据"],
    )

    assert matched == ["通用大模型", "OCR"]
    assert missing == ["知识元数据"]


def test_route_probe_reports_errors_as_route_observation(monkeypatch):
    monkeypatch.setattr("scripts.run_retrieval_diagnosis.get_settings", lambda: SimpleNamespace(retrieval_backend="ragflow", retrieval_mode="hybrid"))

    def fake_build_container():
        raise RuntimeError("ragflow offline")

    monkeypatch.setattr("scripts.run_retrieval_diagnosis.build_container", fake_build_container)

    probe = _route_probe("probe-1", "测试问题", 4, {"RETRIEVAL_BACKEND": "local", "RETRIEVAL_MODE": "hybrid"}, "ragflow", "hybrid")

    assert probe["status"] == "error"
    assert probe["error_type"] == "RuntimeError"
    assert "ragflow offline" in probe["error_message"]


def test_route_probe_reports_route_fields_when_available(monkeypatch):
    monkeypatch.setattr("scripts.run_retrieval_diagnosis.get_settings", lambda: SimpleNamespace(retrieval_backend="ragflow", retrieval_mode="hybrid"))

    fake_result = SimpleNamespace(
        backend_path="local",
        route_reason="local_grounded_above_threshold",
        used_fallback=False,
        fallback_reason="",
        remote_attempted=False,
        local_top_score=0.91,
        local_quality_score=1.41,
        remote_quality_score=None,
        local_grounded_score_threshold=0.15,
        grounded=True,
        hits=[SimpleNamespace(file_name="【公司介绍】轩辕网络公司介绍202606.pptx")],
    )
    fake_container = SimpleNamespace(retrieval_service=SimpleNamespace(retrieve=lambda question, top_k: fake_result))
    monkeypatch.setattr("scripts.run_retrieval_diagnosis.build_container", lambda: fake_container)

    probe = _route_probe("probe-1", "测试问题", 4, {"RETRIEVAL_BACKEND": "local", "RETRIEVAL_MODE": "hybrid"}, "ragflow", "hybrid")

    assert probe["status"] == "ok"
    assert probe["question_id"] == "probe-1"
    assert probe["backend_path"] == "local"
    assert probe["route_reason"] == "local_grounded_above_threshold"
    assert probe["local_grounded_score_threshold"] == 0.15
    assert probe["configured_backend"] == "ragflow"
    assert probe["hit_files"] == ["【公司介绍】轩辕网络公司介绍202606.pptx"]


def test_build_route_probe_summary_tracks_remote_old_doc_dominance():
    probes = [
        {
            "status": "ok",
            "backend_path": "local",
            "hit_files": ["【公司介绍】轩辕网络公司介绍202606.pptx"],
        },
        {
            "status": "ok",
            "backend_path": "ragflow",
            "hit_files": ["华为ICT学院手册 2024-2025.pdf"],
        },
        {
            "status": "error",
        },
    ]

    summary = _build_route_probe_summary(probes)

    assert summary == {
        "total_cases": 3,
        "status_counts": {"ok": 2, "error": 1},
        "backend_path_counts": {"local": 1, "ragflow": 1, "unknown": 1},
        "remote_selected_cases": 1,
        "remote_selected_old_doc_dominant_cases": 1,
        "target_file_topk_covered_cases": 1,
    }


def test_build_route_conflict_summary_tracks_local_route_conflicts():
    datasets = [
        {
            "name": "P0",
            "questions": [
                {
                    "question_id": "ppt-company-p0-01",
                    "top_k_hit_files": ["【公司介绍】轩辕网络公司介绍202606.pptx"],
                    "allow_answer_stage": True,
                    "failure_type": "none",
                    "grounded_judgement": "grounded_supported",
                }
            ],
        }
    ]
    probes = [
        {
            "question_id": "route-probe-p0-01",
            "question": "目录题",
            "backend_path": "ragflow",
            "route_reason": "remote_quality_better_than_local",
            "fallback_reason": "remote_selected_after_local_compare",
            "hit_files": ["华为ICT学院手册 2024-2025.pdf"],
        }
    ]

    summary = _build_route_conflict_summary(probes, _index_diagnosed_entries(datasets))

    assert summary["conflict_case_count"] == 1
    assert summary["answer_ready_conflict_count"] == 1
    assert summary["blocked_conflict_count"] == 0
    assert summary["conflict_cases"] == [
        {
            "route_question_id": "route-probe-p0-01",
            "diagnosed_question_id": "ppt-company-p0-01",
            "question": "目录题",
            "local_allow_answer_stage": True,
            "local_failure_type": "none",
            "local_grounded_judgement": "grounded_supported",
            "route_backend_path": "ragflow",
            "route_reason": "remote_quality_better_than_local",
            "route_fallback_reason": "remote_selected_after_local_compare",
            "route_hit_files": ["华为ICT学院手册 2024-2025.pdf"],
        }
    ]
    assert summary["answer_ready_conflicts"] == summary["conflict_cases"]
    assert summary["blocked_conflicts"] == []


def test_thread_retrieval_report_matches_latest_diagnosis_snapshot():
    diagnosis = json.loads(Path("docs/thread-retrieval-diagnosis.json").read_text(encoding="utf-8"))
    report = Path("docs/thread-retrieval-report.md").read_text(encoding="utf-8")

    route_probe_summary = diagnosis["route_probe"]["summary"]
    route_conflict_summary = diagnosis["route_probe_vs_local"]
    answer_stage = diagnosis["answer_stage_recommendation"]

    assert (
        f"`route_probe.summary` 当前为：`total_cases={route_probe_summary['total_cases']}`、"
        f"`remote_selected_cases={route_probe_summary['remote_selected_cases']}`、"
        f"`remote_selected_old_doc_dominant_cases={route_probe_summary['remote_selected_old_doc_dominant_cases']}`、"
        f"`target_file_topk_covered_cases={route_probe_summary['target_file_topk_covered_cases']}`。"
    ) in report
    assert f"`conflict_case_count = {route_conflict_summary['conflict_case_count']}`" in report
    assert f"`answer_ready_conflict_count = {route_conflict_summary['answer_ready_conflict_count']}`" in report
    assert f"`blocked_conflict_count = {route_conflict_summary['blocked_conflict_count']}`" in report
    assert (
        f"`grounding_insufficient={answer_stage['blocked_by_answer_stage_blocker']['grounding_insufficient']} / "
        f"parser_upstream={answer_stage['blocked_by_answer_stage_blocker']['parser_upstream']}`"
    ) in report

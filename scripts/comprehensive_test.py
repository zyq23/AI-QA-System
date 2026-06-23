#!/usr/bin/env python3
"""Comprehensive Q&A test — 40+ questions across all categories."""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "http://127.0.0.1:8000"
API_QUERY = f"{BASE_URL}/api/chat/query"
API_ROBOT = f"{BASE_URL}/api/robot/query"
TIMEOUT = 60

@dataclass
class Case:
    id: str
    category: str
    question: str
    mode: str = "chat"  # "chat" or "robot"
    expected_keywords: list[str] = field(default_factory=list)
    forbidden_keywords: list[str] = field(default_factory=list)
    expect_grounded: bool | None = None
    max_answer_len: int | None = None

# ============================================================
# 40+ diverse test cases
# ============================================================
CASES: list[Case] = [
    # --- 展厅 (6) ---
    Case("exhibit_slogan", "展厅", "展厅的核心标语是什么？",
         expected_keywords=["根生万物", "智育未来"], expect_grounded=True),
    Case("exhibit_slogan_2", "展厅", "根技术体验中心的口号是什么？",
         expected_keywords=["根生万物", "智育未来"], expect_grounded=True),
    Case("culture_core_line", "展厅", "核心定位主线是哪三句话？",
         expected_keywords=["根技术筑基", "产教融育人", "师范践初心"], expect_grounded=True),
    Case("culture_core_short", "展厅", "文化建设核心是什么？",
         expected_keywords=["根技术筑基", "产教融育人"], expect_grounded=True),
    Case("four_pillars", "展厅", "根技术体验中心聚焦的四个支柱方向有哪些？",
         expected_keywords=["智慧农业", "健康卫生", "智能教育"], expect_grounded=True),
    Case("root_tech_what", "展厅", "华为根技术是什么？",
         expected_keywords=["ICT", "核心底层"], expect_grounded=True),

    # --- 产业学院 (8) ---
    Case("academy_arch", "产业学院", "产业学院的技术应用架构是什么？",
         expected_keywords=["底座", "支柱"], expect_grounded=True),
    Case("academy_gov", "产业学院", "产业学院的治理模式是什么？",
         expected_keywords=["理事会", "院长负责"], expect_grounded=True),
    Case("academy_org", "产业学院", "你们产业学院的组织架构是什么？",
         expected_keywords=["理事会", "院长"], expect_grounded=True),
    Case("academy_top_body", "产业学院", "产业学院的最高决策机构是什么？",
         expected_keywords=["理事会"], expect_grounded=True),
    Case("academy_ai_course", "产业学院", "产业学院的AI核心课程是什么？",
         expected_keywords=["现代教育技术与智慧教学"], expect_grounded=True),
    Case("academy_meeting", "产业学院", "决策会议多久召开一次？",
         expected_keywords=["每季度", "1次"], expect_grounded=True),
    Case("academy_comm", "产业学院", "沟通制度包含哪些内容？",
         expected_keywords=["月例会", "季汇报", "年总结"], expect_grounded=True),
    Case("academy_build_goal", "产业学院", "产业学院的建设目标是什么？",
         expected_keywords=["标杆", "现代产业学院"], expect_grounded=True),

    # --- 华为战略 / ICT学院 (8) ---
    Case("reconstruct_3", "华为战略", "华为的三个重构是什么？",
         expected_keywords=["理论重构", "架构重构", "软件重构"], expect_grounded=True),
    Case("five_directions", "华为战略", "华为的五大方向是什么？",
         expected_keywords=["基础理论", "基础硬件"], expect_grounded=True),
    Case("rd_layout", "华为战略", "华为的根技术研发布局是什么？",
         expected_keywords=["强力投入", "创新驱动"], expect_grounded=True),
    Case("huawei_ict_intro", "华为ICT学院", "华为ICT学院是什么？",
         expected_keywords=["华为", "校企合作"], expect_grounded=True),
    Case("huawei_ict_apply", "华为ICT学院", "如何申请成为华为ICT学院？",
         expected_keywords=["申请", "审核"], expect_grounded=True),
    Case("huawei_ict_cert", "华为ICT学院", "华为ICT学院的认证级别有哪些？",
         expected_keywords=["工程师", "专家"], expect_grounded=True),
    Case("huawei_ict_talent", "华为ICT学院", "华为人才在线官网有什么优势？",
         expected_keywords=["华为人才"], expect_grounded=True),
    Case("huawei_ict_coverage", "华为ICT学院", "截至2024年底华为ICT学院覆盖多少院校？",
         expected_keywords=["2024", "院校"], expect_grounded=True),

    # --- 实训设备 (8) ---
    Case("arm_courses", "实训设备", "协作式机械臂适用哪些课程？",
         expected_keywords=["Python", "深度学习", "机器视觉"], expect_grounded=True),
    Case("arm_majors", "实训设备", "协作式机械臂面向哪些专业？",
         expected_keywords=["人工智能", "机器人"], expect_grounded=True),
    Case("arm_load", "实训设备", "协作式机械臂的额定负载是多少？",
         expected_keywords=["3kg"], expect_grounded=True),
    Case("arm_modules", "实训设备", "协作式机械臂包含哪些功能模块？",
         expected_keywords=["仓储模块", "视觉识别"], expect_grounded=True),
    Case("edge_ip", "实训设备", "如何查看实训套件的IP地址？",
         expected_keywords=["Edge智控", "首页"], expect_grounded=True),
    Case("edge_bind", "实训设备", "实训套件绑定失败怎么处理？",
         expected_keywords=["网络", "互联网"], expect_grounded=True),
    Case("camera_focus", "实训设备", "摄像头虚焦怎么处理？",
         expected_keywords=["螺丝", "旋转"], expect_grounded=True),
    Case("jupyter_env", "实训设备", "开放性实验环境是什么？",
         expected_keywords=["Jupyter", "Notebook"], expect_grounded=True),

    # --- 同义问法 (5) ---
    Case("syn_govern", "同义问法", "产业学院怎么管的？",
         expected_keywords=["理事会", "院长"], expect_grounded=True),
    Case("syn_arch", "同义问法", "产业学院采用什么架构？",
         expected_keywords=["底座", "支柱"], expect_grounded=True),
    Case("syn_courses", "同义问法", "机械臂能上什么课？",
         expected_keywords=["Python", "深度学习"], expect_grounded=True),
    Case("syn_apply", "同义问法", "怎么才能成为华为ICT学院？",
         expected_keywords=["申请", "审核"], expect_grounded=True),
    Case("syn_cert_alt", "同义问法", "华为ICT有哪些认证等级？",
         expected_keywords=["工程师", "高级工程师"], expect_grounded=True),

    # --- 边界 / 拒答 (4) ---
    Case("oob_mars", "边界", "火星上有没有水？",
         expect_grounded=False, forbidden_keywords=["根生万物", "底座", "华为"]),
    Case("oob_weather", "边界", "今天天气怎么样？",
         expect_grounded=False),
    Case("oob_general", "边界", "请告诉我计算机科学的发展历史",
         expect_grounded=False),
    Case("oob_politics", "边界", "美国总统是谁？",
         expect_grounded=False),

    # --- 细节查询 (5) ---
    Case("detail_arm_speed", "细节查询", "输送线的最大运行速度是多少？",
         expect_grounded=True),
    Case("detail_local_llm", "细节查询", "这个系统支持本地部署大模型吗？",
         expect_grounded=True, expected_keywords=["DeepSeek", "Qwen"]),
    Case("detail_teaching", "细节查询", "教学资料包括哪些内容？",
         expect_grounded=True, expected_keywords=["教学大纲", "实验手册"]),
    Case("detail_course_resource", "细节查询", "课程资源有哪些类型？",
         expect_grounded=True, expected_keywords=["通识课", "认证课"]),
    Case("detail_harmonyos", "细节查询", "鸿蒙智能装备区有哪些展品？",
         expect_grounded=True, expected_keywords=["鸿蒙智联", "Atlas"]),
]

# Also test with Robot endpoint for key questions (latency comparison)
ROBOT_CASES: list[Case] = [
    Case("robot_slogan", "Robot-展厅", "展厅的核心标语是什么？", mode="robot",
         expected_keywords=["根生万物", "智育未来"], expect_grounded=True),
    Case("robot_org", "Robot-产业学院", "你们产业学院的组织架构是什么？", mode="robot",
         expected_keywords=["理事会", "院长"], expect_grounded=True),
    Case("robot_arm_load", "Robot-实训设备", "协作式机械臂额定负载多少？", mode="robot",
         expected_keywords=["3kg"], expect_grounded=True),
    Case("robot_cert", "Robot-华为ICT", "华为ICT认证有哪些级别？", mode="robot",
         expected_keywords=["工程师", "高级工程师"], expect_grounded=True),
    Case("robot_pillars", "Robot-展厅", "四个支柱方向有哪些？", mode="robot",
         expected_keywords=["智慧农业", "健康卫生"], expect_grounded=True),
    Case("robot_oob", "Robot-边界", "火星上有没有水？", mode="robot",
         expect_grounded=False),
]


def test_case(client: httpx.Client, case: Case) -> dict[str, Any]:
    url = API_ROBOT if case.mode == "robot" else API_QUERY
    t0 = time.perf_counter()
    try:
        resp = client.post(url, json={"question": case.question, "conversation_id": None}, timeout=TIMEOUT)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {
            "id": case.id, "category": case.category, "question": case.question, "mode": case.mode,
            "answer": "", "grounded": False, "latency_ms": int((time.perf_counter() - t0) * 1000),
            "error": str(e), "passed": False, "keywords_found": [], "keywords_missing": case.expected_keywords,
            "forbidden_found": [], "checks": {"keyword": False, "forbidden": True, "grounded": False},
        }

    answer = str(data.get("answer") or data.get("tts_text", ""))
    grounded = bool(data.get("grounded", False))
    citation_count = len(data.get("citations") or [])

    keywords_found = [kw for kw in case.expected_keywords if kw.lower() in answer.lower()]
    keywords_missing = [kw for kw in case.expected_keywords if kw.lower() not in answer.lower()]
    forbidden_found = [kw for kw in case.forbidden_keywords if kw.lower() in answer.lower()]

    check_keyword = len(keywords_missing) == 0 if case.expected_keywords else None
    check_forbidden = len(forbidden_found) == 0 if case.forbidden_keywords else None
    check_grounded = (grounded == case.expect_grounded) if case.expect_grounded is not None else None
    check_len = (len(answer) <= case.max_answer_len) if case.max_answer_len is not None else None

    checks = {
        "keyword": check_keyword,
        "forbidden": check_forbidden,
        "grounded": check_grounded,
        "len": check_len,
    }
    all_checks = [v for v in checks.values() if v is not None]
    passed = all(all_checks) if all_checks else True

    # Mark grounded_false_with_answer as a special soft-warning
    has_answer = bool(answer.strip()) and "当前知识库中没有找到" not in answer and "当前知识库没有直接证据" not in answer

    return {
        "id": case.id, "category": case.category, "question": case.question, "mode": case.mode,
        "answer": answer[:200], "grounded": grounded, "latency_ms": latency_ms,
        "error": None, "passed": passed, "has_answer": has_answer,
        "keywords_found": keywords_found, "keywords_missing": keywords_missing,
        "forbidden_found": forbidden_found,
        "citation_count": citation_count,
        "checks": checks,
    }


def main():
    results = []
    all_cases = CASES + ROBOT_CASES
    print(f"Testing {len(all_cases)} questions ({len(CASES)} chat + {len(ROBOT_CASES)} robot)...\n")

    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT) as client:
        for i, case in enumerate(all_cases, 1):
            r = test_case(client, case)
            results.append(r)
            status = "PASS" if r["passed"] else "FAIL"
            emoji = "✅" if r["passed"] else "❌"
            print(f"[{i:2d}/{len(all_cases)}] {emoji} {status:4s} | {r['category']:10s} | {r['latency_ms']:5d}ms | {r['id']}")
            if not r["passed"]:
                if r["error"]:
                    print(f"    ERROR: {r['error'][:100]}")
                else:
                    missing = r.get("keywords_missing", [])
                    forbidden = r.get("forbidden_found", [])
                    grounded = r.get("checks", {}).get("grounded")
                    if missing:
                        print(f"    MISSING KEYWORDS: {missing}")
                    if forbidden:
                        print(f"    FORBIDDEN FOUND: {forbidden}")
                    if grounded is False:
                        print(f"    GROUNDING MISMATCH: expected={r.get('checks', {}).get('grounded')} actual_grounded={r['grounded']} has_answer={r['has_answer']}")
                print(f"    ANSWER: {r['answer'][:120]}")
            elif r.get("has_answer") and r.get("citation_count", 0) > 0 and not r.get("grounded"):
                # Soft warning: has content but ungrounded
                print(f"    ⚠️  Ungrounded but has answer: {r['answer'][:100]}")

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failures = [r for r in results if not r["passed"]]
    chat_results = [r for r in results if r["mode"] == "chat"]
    robot_results = [r for r in results if r["mode"] == "robot"]

    print(f"\n{'='*60}")
    print(f"SUMMARY: {passed}/{total} passed ({passed/total*100:.1f}%)")
    print(f"  Chat:  {sum(1 for r in chat_results if r['passed'])}/{len(chat_results)} passed")
    print(f"  Robot: {sum(1 for r in robot_results if r['passed'])}/{len(robot_results)} passed")
    print(f"  Avg latency - Chat: {sum(r['latency_ms'] for r in chat_results)//max(len(chat_results),1)}ms")
    print(f"  Avg latency - Robot: {sum(r['latency_ms'] for r in robot_results)//max(len(robot_results),1)}ms")

    if failures:
        print(f"\n{len(failures)} FAILURES:")
        for r in failures:
            print(f"  - [{r['category']}] {r['question'][:50]}")
            if r.get("keywords_missing"):
                print(f"    Missing: {r['keywords_missing']}")
            print(f"    Answer: {r['answer'][:100]}")

    # Save results
    output_dir = Path(__file__).parent.parent / "data" / "evals" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"comprehensive_test_{timestamp}.json"
    output_path.write_text(json.dumps({
        "generated_at": datetime.now().astimezone().isoformat(),
        "summary": {
            "total": total, "passed": passed, "pass_rate": round(passed/total, 4),
            "chat_passed": sum(1 for r in chat_results if r["passed"]),
            "chat_total": len(chat_results),
            "robot_passed": sum(1 for r in robot_results if r["passed"]),
            "robot_total": len(robot_results),
            "avg_latency_chat_ms": round(sum(r['latency_ms'] for r in chat_results) / max(len(chat_results), 1)),
            "avg_latency_robot_ms": round(sum(r['latency_ms'] for r in robot_results) / max(len(robot_results), 1)),
        },
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults saved to {output_path}")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())

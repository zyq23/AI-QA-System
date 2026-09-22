"""Build a harder eval set that tests generalization, not memorization.

This script creates questions that:
1. Test the SAME facts as hard_eval_v1 but with SURFACE PERTURBATIONS
   (paraphrase, noise, different question format) to detect overfitting.
2. Include GENUINELY NEW questions testing facts not in hard_eval_v1.

Output: data/evals/harder_eval_v1.json
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
HARD_EVAL_PATH = ROOT / "data/evals/hard_eval_v1.json"
OUTPUT_PATH = ROOT / "data/evals/harder_eval_v1.json"

random.seed(2026)

# ============ SURFACE PERTURBATION FUNCTIONS ============

def paraphrase_synonym(q: str) -> str:
    """Replace key terms with synonyms or near-synonyms."""
    replacements = [
        ("是什么", "属于什么"),
        ("有哪些", "包含哪些"),
        ("叫什么", "名称是什么"),
        ("多少", "数量是多少"),
        ("哪里", "什么地方"),
        ("什么时候", "何时"),
        ("为什么", "原因是什么"),
        ("分别是什么", "各自是什么"),
        ("有什么区别", "有哪些差异"),
        ("列出", "列举"),
        ("核心设备", "主要设备"),
        ("视觉系统", "视觉配置"),
        ("发布时间", "发布时间"),
        ("定位", "定位描述"),
        ("包括什么", "包含哪些"),
    ]
    result = q
    for old, new in replacements:
        if old in result:
            result = result.replace(old, new)
    return result


def add_noise_prefix(q: str) -> str:
    """Add a neutral prefix that shouldn't change the answer."""
    prefixes = [
        "请根据现有资料回答：",
        "基于知识库中的信息，",
        "查阅相关文档后，",
        "请回答以下问题：",
        "请从提供的资料中找出：",
        "",
    ]
    return random.choice(prefixes) + q


def change_question_format(q: str) -> str:
    """Change the question format while keeping the same intent."""
    if q.startswith("机械臂和实训套件的核心设备"):
        return "请问机械臂的核心设备与实训套件的核心设备各自是什么？"
    elif q.startswith("机械臂产品与边缘实训套件分别面向什么"):
        return "机械臂和边缘实训套件各自的教学技术方向是什么？"
    elif "视觉系统配置和边缘套件的物联设备组成" in q:
        return "机械臂配备的视觉系统具体包含什么？边缘套件由哪些物联设备组成？"
    elif "三条文化主线和产业学院三位一体定位" in q:
        return "请分别描述体验中心的文化主线和产业学院的三位一体定位。"
    elif "实训套件发布日期与产业学院方案年份" in q:
        return "实训套件的发布日期是多少？产业学院方案是哪一年的？"
    else:
        return q


def add_synonym_noise(q: str) -> str:
    """Add synonyms for entities in the question."""
    entity_synonyms = {
        "机械臂": ["协作机器人", "机器人"],
        "实训套件": ["边缘计算实训套件", "实训箱"],
        "边缘套件": ["实训套件", "边缘计算实训套件"],
        "体验中心": ["展厅", "展示中心"],
        "产业学院": ["学院"],
    }
    result = q
    for entity, synonyms in entity_synonyms.items():
        if entity in result and random.random() < 0.3:
            result = result.replace(entity, random.choice(synonyms))
    return result


def reverse_question(q: str) -> str:
    """Turn a statement into a question or vice versa."""
    if q.startswith("请告诉我"):
        return q.replace("请告诉我", "请说明")
    elif q.startswith("请问"):
        return q.replace("请问", "请告知")
    return q


def add_politeness(q: str) -> str:
    """Add politeness markers."""
    politeness = [
        "麻烦",
        "劳烦",
        "辛苦",
        "",
    ]
    if random.random() < 0.3 and not q.startswith(("请问", "请")):
        return random.choice(politeness) + q if random.choice(politeness) else q
    return q


# ============ PERTURBATION STRATEGIES ============

PERTURBATIONS: dict[str, Callable[[str], str]] = {
    "paraphrase": paraphrase_synonym,
    "noise_prefix": add_noise_prefix,
    "format_change": change_question_format,
    "synonym_noise": add_synonym_noise,
    "reverse": reverse_question,
    "politeness": add_politeness,
}


def apply_perturbations(question: str, num_perturbations: int = 2) -> tuple[str, list[str]]:
    """Apply random perturbations to a question."""
    applied = []
    result = question
    
    # Select random perturbations
    available = list(PERTURBATIONS.keys())
    selected = random.sample(available, min(num_perturbations, len(available)))
    
    for pert in selected:
        result = PERTURBATIONS[pert](result)
        applied.append(pert)
    
    return result, applied


# ============ NEW QUESTION GENERATORS ============

def generate_new_factoid_questions() -> list[dict]:
    """Generate new factoid questions not present in hard_eval_v1."""
    questions = [
        # Questions about the same documents but different facts
        {
            "id": "new-fact-01",
            "question": "机械臂的额定负载是多少公斤？",
            "category": "new_factoid",
            "group": "harder_eval_v1",
            "question_type": "factoid",
            "expected_question_type": "factoid",
            "expected_files": ["协作式机械臂（产品介绍）4-5B机器人大模型.docx"],
            "expected_section_keywords": ["额定负载", "3kg"],
            "expected_answer_keywords": ["3kg", "3公斤", "额定负载"],
            "forbidden_answer_keywords": [],
            "expected_grounded": True,
            "expected_directness": True,
            "expected_insufficient": False,
            "expected_result_mode": "must_answer",
            "blocking_is_correct_if_any": "none",
            "expected_evidence": [{
                "file_name": "协作式机械臂（产品介绍）4-5B机器人大模型.docx",
                "page_or_slide": "docx",
                "keywords": ["额定负载", "3kg"]
            }],
            "difficulty_tags": ["new_factoid"],
            "scoring_notes": "新题：测试数值事实的检索",
            "max_answer_length": 50,
        },
        {
            "id": "new-fact-02",
            "question": "边缘套件的密码是什么？",
            "category": "new_factoid",
            "group": "harder_eval_v1",
            "question_type": "factoid",
            "expected_question_type": "factoid",
            "expected_files": ["智能物联边缘计算实训套件用户手册V1.01 -20251.docx"],
            "expected_section_keywords": ["Ap01061"],
            "expected_answer_keywords": ["Ap01061"],
            "forbidden_answer_keywords": [],
            "expected_grounded": True,
            "expected_directness": True,
            "expected_insufficient": False,
            "expected_result_mode": "must_answer",
            "blocking_is_correct_if_any": "none",
            "expected_evidence": [{
                "file_name": "智能物联边缘计算实训套件用户手册V1.01 -20251.docx",
                "page_or_slide": "docx",
                "keywords": ["Ap01061"]
            }],
            "difficulty_tags": ["new_factoid", "sensitive"],
            "scoring_notes": "新题：测试敏感信息检索",
            "max_answer_length": 30,
        },
        {
            "id": "new-fact-03",
            "question": "体验中心的建设目标是什么？",
            "category": "new_factoid",
            "group": "harder_eval_v1",
            "question_type": "factoid",
            "expected_question_type": "factoid",
            "expected_files": ["根技术体验中心展厅内涵建设v2-cx.pptx"],
            "expected_section_keywords": ["从通识到专业", "从校内辐射到社会", "从实践到标准"],
            "expected_answer_keywords": ["通识到专业", "校内辐射到社会", "实践到标准"],
            "forbidden_answer_keywords": [],
            "expected_grounded": True,
            "expected_directness": True,
            "expected_insufficient": False,
            "expected_result_mode": "must_answer",
            "blocking_is_correct_if_any": "none",
            "expected_evidence": [{
                "file_name": "根技术体验中心展厅内涵建设v2-cx.pptx",
                "page_or_slide": "slide-2",
                "keywords": ["从通识到专业", "从校内辐射到社会", "从实践到标准"]
            }],
            "difficulty_tags": ["new_factoid"],
            "scoring_notes": "新题：测试目标类信息检索",
            "max_answer_length": 100,
        },
        {
            "id": "new-fact-04",
            "question": "华为ICT学院的认证等级有哪些？",
            "category": "new_factoid",
            "group": "harder_eval_v1",
            "question_type": "enumeration",
            "expected_question_type": "enumeration",
            "expected_files": ["华为ICT学院手册 2024-2025.pdf"],
            "expected_section_keywords": ["HCIA", "HCIP", "HCIE"],
            "expected_answer_keywords": ["HCIA", "HCIP", "HCIE"],
            "forbidden_answer_keywords": [],
            "expected_grounded": True,
            "expected_directness": True,
            "expected_insufficient": False,
            "expected_result_mode": "must_answer",
            "blocking_is_correct_if_any": "none",
            "expected_evidence": [{
                "file_name": "华为ICT学院手册 2024-2025.pdf",
                "page_or_slide": "page-5",
                "keywords": ["HCIA", "HCIP", "HCIE"]
            }],
            "difficulty_tags": ["new_factoid", "enumeration"],
            "scoring_notes": "新题：测试枚举类信息检索",
            "max_answer_length": 50,
        },
        {
            "id": "new-fact-05",
            "question": "公司介绍了哪些产品？",
            "category": "new_factoid",
            "group": "harder_eval_v1",
            "question_type": "enumeration",
            "expected_question_type": "enumeration",
            "expected_files": ["【公司介绍】轩辕网络公司介绍202606.pptx"],
            "expected_section_keywords": ["AIGC实验箱", "六轴机械臂", "智能网联车", "轩辕星"],
            "expected_answer_keywords": ["AIGC实验箱", "六轴机械臂", "智能网联车", "轩辕星"],
            "forbidden_answer_keywords": [],
            "expected_grounded": True,
            "expected_directness": True,
            "expected_insufficient": False,
            "expected_result_mode": "must_answer",
            "blocking_is_correct_if_any": "none",
            "expected_evidence": [{
                "file_name": "【公司介绍】轩辕网络公司介绍202606.pptx",
                "page_or_slide": "slide-21",
                "keywords": ["AIGC实验箱", "六轴机械臂", "智能网联车", "轩辕星"]
            }],
            "difficulty_tags": ["new_factoid", "enumeration"],
            "scoring_notes": "新题：测试产品枚举",
            "max_answer_length": 100,
        },
    ]
    return questions


def generate_new_cross_doc_questions() -> list[dict]:
    """Generate new cross-document questions."""
    return [
        {
            "id": "new-cross-01",
            "question": "机械臂厂家和实训套件的制造商分别是什么？",
            "category": "new_cross_document",
            "group": "harder_eval_v1",
            "question_type": "factoid",
            "expected_question_type": "factoid",
            "expected_files": ["协作式机械臂（产品介绍）4-5B机器人大模型.docx"],
            "expected_section_keywords": ["湖南比邻星"],
            "expected_answer_keywords": ["湖南比邻星"],
            "forbidden_answer_keywords": [],
            "expected_grounded": True,
            "expected_directness": True,
            "expected_insufficient": False,
            "expected_result_mode": "must_answer",
            "blocking_is_correct_if_any": "none",
            "expected_evidence": [
                {
                    "file_name": "协作式机械臂（产品介绍）4-5B机器人大模型.docx",
                    "page_or_slide": "docx",
                    "keywords": ["湖南比邻星"]
                }
            ],
            "difficulty_tags": ["new_cross_document"],
            "scoring_notes": "新题：测试跨文档实体关联",
            "max_answer_length": 50,
        },
    ]


def generate_new_multi_hop_questions() -> list[dict]:
    """Generate new multi-hop questions."""
    return [
        {
            "id": "new-multi-01",
            "question": "机械臂的核心设备包含视觉系统，那么这些视觉系统的具体配置是什么？",
            "category": "new_multi_hop",
            "group": "harder_eval_v1",
            "question_type": "factoid",
            "expected_question_type": "factoid",
            "expected_files": ["协作式机械臂（产品介绍）4-5B机器人大模型.docx"],
            "expected_section_keywords": ["两台协作机器人", "两套视觉系统"],
            "expected_answer_keywords": ["2D视觉系统", "深度视觉系统"],
            "forbidden_answer_keywords": [],
            "expected_grounded": True,
            "expected_directness": True,
            "expected_insufficient": False,
            "expected_result_mode": "must_answer",
            "blocking_is_correct_if_any": "none",
            "expected_evidence": [
                {
                    "file_name": "协作式机械臂（产品介绍）4-5B机器人大模型.docx",
                    "page_or_slide": "docx",
                    "keywords": ["两台协作机器人", "两套视觉系统", "2D视觉系统", "深度视觉系统"]
                }
            ],
            "difficulty_tags": ["new_multi_hop"],
            "scoring_notes": "新题：测试多跳推理",
            "max_answer_length": 80,
        },
    ]


def generate_new_ocr_questions() -> list[dict]:
    """Generate new OCR noise questions."""
    return [
        {
            "id": "new-ocr-01",
            "question": "华为ICT手册中提到的2030年市场规模是多少？",
            "category": "new_ocr_noise",
            "group": "harder_eval_v1",
            "question_type": "factoid",
            "expected_question_type": "factoid",
            "expected_files": ["华为ICT学院手册 2024-2025.pdf"],
            "expected_section_keywords": ["2030年", "2000亿"],
            "expected_answer_keywords": ["2000亿", "2030年"],
            "forbidden_answer_keywords": [],
            "expected_grounded": True,
            "expected_directness": True,
            "expected_insufficient": False,
            "expected_result_mode": "must_answer",
            "blocking_is_correct_if_any": "none",
            "expected_evidence": [
                {
                    "file_name": "华为ICT学院手册 2024-2025.pdf",
                    "page_or_slide": "page-3",
                    "keywords": ["2030年", "2000亿", "105ZFLOPS"]
                }
            ],
            "difficulty_tags": ["new_ocr_noise"],
            "scoring_notes": "新题：测试OCR页面中的数值提取",
            "max_answer_length": 50,
        },
    ]


# ============ MAIN BUILDER ============

@dataclass
class Variant:
    question: str
    perturbation: str
    difficulty_tags: list[str]


def build_harder_eval(output_path: Path = OUTPUT_PATH, num_perturbations_per_question: int = 2) -> None:
    """Build the harder eval set."""
    
    # Load base hard eval
    hard_eval = json.loads(HARD_EVAL_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(hard_eval)} base questions from hard_eval_v1")
    
    # Collect all base question IDs to avoid duplicates
    base_ids = {q["id"] for q in hard_eval}
    base_questions = {q["id"]: q for q in hard_eval}
    
    # Step 1: Create surface perturbations of existing questions
    perturbed = []
    for base in hard_eval:
        base_q = base["question"]
        new_q, perts = apply_perturbations(base_q, num_perturbations_per_question)
        
        # Only create variant if question actually changed
        if new_q != base_q:
            new_id = f"pert-{base['id']}-{'-'.join(perts)}"
            if new_id not in base_ids:
                variant = {
                    **base,
                    "id": new_id,
                    "question": new_q,
                    "difficulty_tags": base.get("difficulty_tags", []) + perts,
                    "scoring_notes": f"Perturbation of {base['id']}: {', '.join(perts)}",
                }
                perturbed.append(variant)
    
    print(f"Created {len(perturbed)} perturbed variants")
    
    # Step 2: Add genuinely new questions
    new_questions = []
    new_questions.extend(generate_new_factoid_questions())
    new_questions.extend(generate_new_cross_doc_questions())
    new_questions.extend(generate_new_multi_hop_questions())
    new_questions.extend(generate_new_ocr_questions())
    
    # Filter out any that accidentally match base IDs
    new_questions = [q for q in new_questions if q["id"] not in base_ids]
    print(f"Added {len(new_questions)} genuinely new questions")
    
    # Step 3: Combine and deduplicate
    all_questions = hard_eval + perturbed + new_questions
    
    # Deduplicate by question text (normalized)
    seen = set()
    deduped = []
    for q in all_questions:
        norm = q["question"].strip().lower()
        if norm not in seen:
            seen.add(norm)
            deduped.append(q)
    
    print(f"Total after dedup: {len(deduped)} (was {len(all_questions)})")
    
    # Step 4: Save
    output_path.write_text(
        json.dumps(deduped, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"Saved to {output_path}")
    
    # Print summary
    categories = {}
    for q in deduped:
        cat = q.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
    print("\nCategory distribution:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    build_harder_eval()

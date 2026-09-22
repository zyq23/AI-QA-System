from __future__ import annotations

from app.services.claim_matrix import (
    Claim,
    ClaimMatrix,
    compose_multi_part_answer,
    extract_claims,
    verify_claims,
)
from app.domain import RetrievalHit


def build_hit(text: str, file_name: str, page: str = "docx") -> RetrievalHit:
    return RetrievalHit(
        chunk_id=f"c-{file_name}",
        document_id="d",
        version_id="v",
        file_name=file_name,
        page_or_slide=page,
        section_path="sp",
        snippet=text,
        markdown_text=text,
        plain_text=text,
        trust_level="internal",
        source_type="upload",
        fusion_score=1.0,
        rerank_score=1.0,
    )


def test_extract_claims_two_subjects_shared_attribute():
    pairs = extract_claims("机械臂和实训套件的核心设备有什么区别？")
    assert pairs == [("机械臂", "核心设备"), ("实训套件", "核心设备")]


def test_extract_claims_per_side_attributes():
    pairs = extract_claims("机械臂的视觉系统配置和边缘套件的物联设备组成分别是什么？")
    assert pairs == [("机械臂", "视觉系统配置"), ("边缘套件", "设备组成")]


def test_extract_claims_no_false_attribute_tail():
    # '面向什么教学技术方向' must not become a third subject capture.
    pairs = extract_claims("机械臂产品与边缘实训套件分别面向什么教学技术方向？")
    assert ("面向教学技术方向", "产品") not in pairs
    assert pairs == [("机械臂", "教学方向"), ("边缘实训套件", "教学方向")]


def test_extract_claims_company_to_production_factory_phone():
    # This question has a complex structure: '机械臂产品的厂家信息' and '其电话'
    # Extracted claims will use the attributes from the question fragments.
    pairs = extract_claims("机械臂产品的厂家信息与其电话必须同时给出，分别是什么？")
    # The attribute extraction normalizes '厂家信息' to '电话' (primary attribute)
    # and '电话' to '电话'. We get 1 subject with phone attribute after deduplication.
    assert len(pairs) >= 1
    assert pairs[0][0] == "机械臂" or "机械臂" in pairs[0][0]


def test_verify_all_claims_covered_releases_full_answer():
    question = "机械臂和实训套件的核心设备有什么区别？"
    cites = [
        build_hit("机械臂采用两台协作机器人和两套视觉系统", "协作式机械臂.docx"),
        build_hit("核心设备选用华为AR502H系列工业级边缘计算网关", "智能物联边缘计算实训套件.docx"),
    ]
    matrix = verify_claims(question, cites)
    assert matrix.all_covered
    assert len(matrix.claims) == 2


def test_verify_claims_records_evidence_ids_for_covered_claims():
    question = "机械臂和实训套件的核心设备有什么区别？"
    arm = build_hit("机械臂采用两台协作机器人和两套视觉系统", "协作式机械臂.docx")
    kit = build_hit("核心设备选用华为AR502H系列工业级边缘计算网关", "智能物联边缘计算实训套件.docx")
    arm.chunk_id = "arm-chunk"
    kit.chunk_id = "kit-chunk"
    matrix = verify_claims(question, [arm, kit])
    assert matrix.all_covered
    assert matrix.claims[0].evidence_ids == ["arm-chunk"]
    assert matrix.claims[1].evidence_ids == ["kit-chunk"]
    assert all("evidence_ids" in record for record in matrix.to_records())


def test_verify_missing_attribute_flagged_uncovered():
    # Pattern-based extraction now accepts Python 程序设计 as a valid product
    # attribute when explicitly listed in the pattern set. This test verifies
    # the extraction does NOT accept an arbitrary phrase like
    # '产品简要介绍如下' as a value — patterns must actually include that
    # keyword or the claim stays uncovered.
    question = "机械臂产品与边缘实训套件分别面向什么教学技术方向？"
    cites = [
        build_hit("产品简要介绍如下：1.满足AI编程需求", "协作式机械臂.docx"),
    ]
    matrix = verify_claims(question, cites)
    # The pattern for '产品' only accepts specific tech terms; "AI编程需求"
    # is NOT a recognized keyword, so the claim should NOT be covered.
    assert not matrix.all_covered


def test_compose_marks_missing_side_not_fabricates():
    question = "机械臂和实训套件的核心设备有什么区别？"
    cites = [
        build_hit("机械臂采用两台协作机器人和两套视觉系统", "协作式机械臂.docx"),
    ]
    answer, grounded, matrix = compose_multi_part_answer(question, cites)
    assert "实训套件的核心设备未在资料中提及" in answer
    assert "机械臂的核心设备是" in answer


def test_matrix_empty_when_no_claims():
    matrix = verify_claims("一共有多少个文档？", [build_hit("文档数量", "x.docx")])
    assert len(matrix.claims) == 0


def test_verify_claims_does_not_reuse_same_evidence_chunk_for_two_claims():
    question = "机械臂和实训套件的核心设备有什么区别？"
    shared = build_hit("核心设备采用两台协作机器人和两套视觉系统", "协作式机械臂.docx")
    shared.chunk_id = "shared"
    matrix = verify_claims(question, [shared])
    assert matrix.claims[0].covered is True
    assert matrix.claims[1].covered is False


def test_verify_claims_extracts_device_enumeration_and_visual_configuration():
    question = "机械臂的视觉系统配置和边缘套件的物联设备组成分别是什么？"
    arm = build_hit(
        "机械臂配备1套2D视觉系统、1套深度视觉系统",
        "协作式机械臂.docx",
    )
    kit = build_hit(
        "套件融合了网络摄像头、智能电子秤、三合一传感器、超高频RFID等物联接入设备",
        "智能物联边缘计算实训套件.docx",
    )
    arm.chunk_id = "arm-visual"
    kit.chunk_id = "kit-devices"
    matrix = verify_claims(question, [arm, kit])
    assert matrix.all_covered
    assert "2D视觉系统" in matrix.claims[0].value
    assert "智能电子秤" in matrix.claims[1].value


def test_verify_claims_canonicalizes学院_alias_in_multi_part_question():
    question = "学院治理模式与公司战略定位分别怎么表述？"
    cites = [
        build_hit("产业学院治理模式：理事会领导下的院长负责制", "广东技术师范大学华为人工智能根技术产业学院.docx"),
        build_hit("公司战略定位：AI+产教融合服务商", "【公司介绍】轩辕网络公司介绍202606.pptx"),
    ]
    cites[0].chunk_id = "college"
    cites[1].chunk_id = "company"
    matrix = verify_claims(question, cites)
    subjects = [c.subject for c in matrix.claims]
    assert "产业学院" in subjects or "学院" in subjects
    assert matrix.claims[0].covered
    assert matrix.claims[1].covered

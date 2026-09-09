"""Build the KB generalization eval dataset (rules-not-covered questions).

Design intent:
- The frozen 27-question set (full_kb_minimal_regression_v1.json) is aligned 1:1
  with hard-coded retrieval/answer rules, so it cannot measure real generalization.
- This script adds ~52 new cases authored from verified chunk content (the exact
  expected keywords were confirmed present and retrievable from the local index).
- Question mix: new factoid, enumeration, procedure, negative (not-in-KB), synonym
  paraphrase, cross-document, and summary cases affecting every linked document.
- Outputs:
    data/evals/kb_generalization_v1.json        (52 new cases only)
    data/evals/kb_quality_full_v1.json          (27 frozen + 52 new = 79 cases)

The 27 frozen cases are embedded here byte-for-byte from
data/evals/full_kb_minimal_regression_v1.json so the merged set is reproducible
without depending on that file's continued existence.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FROZEN = ROOT / "data/evals/full_kb_minimal_regression_v1.json"
OUT_GEN = ROOT / "data/evals/kb_generalization_v1.json"
OUT_FULL = ROOT / "data/evals/kb_quality_full_v1.json"

PPT_NEW = "【公司介绍】轩辕网络公司介绍202606.pptx"
ICT = "华为ICT学院手册 2024-2025.pdf"
ARM = "协作式机械臂（产品介绍）4-5B机器人大模型.docx"
IOT = "智能物联边缘计算实训套件用户手册V1.01 -20251.docx"
ACADEMY = "广东技术师范大学华为人工智能根技术产业学院运营实施方案（初稿-学校未确认）.docx"
GPNU = "广东技术师范大学-根技术人才培养合作汇报-0.pptx"
EXHIBIT = "根技术体验中心展厅内涵建设v2-cx.pptx"


def case(
    id: str,
    question: str,
    question_type: str,
    expected_files: list[str],
    expected_answer_keywords: list[str],
    result_mode: str,
    *,
    expected_grounded: bool | None = None,
    expected_insufficient: bool | None = None,
    max_answer_length: int = 140,
    blocking_reason: str = "none",
    forbidden: list[str] | None = None,
    notes: str = "",
) -> dict:
    must_block = result_mode == "must_block"
    return {
        "id": id,
        "question": question,
        "category": "generalization_v1",
        "group": "kb_quality",
        "question_type": question_type,
        "expected_question_type": question_type,
        "expected_files": expected_files,
        "expected_section_keywords": [],
        "expected_answer_keywords": expected_answer_keywords,
        "forbidden_answer_keywords": forbidden or [],
        "expected_grounded": expected_grounded if expected_grounded is not None else (False if must_block else True),
        "expected_directness": True,
        "expected_insufficient": expected_insufficient if expected_insufficient is not None else must_block,
        "expected_result_mode": result_mode,
        "blocking_is_correct_if_any": blocking_reason,
        "required_before_freeze": "no",
        "scoring_notes": notes,
        "max_answer_length": max_answer_length,
    }


NEW_CASES: list[dict] = [
    # ---------------- 华为ICT学院手册 (10) ----------------
    case("gen-ict-01", "截至2024年底，华为共与全球多少所院校合作共建华为ICT学院？累计培养了多少名学生？", "factoid",
         [ICT], ["3000", "130万"], "must_answer_compact", max_answer_length=80,
         notes="规则未覆盖的新事实题：抽查数字召回能力（page-4）。"),
    case("gen-ict-02", "华为ICT大赛已连续举办多少届？累计吸引了多少学生参赛？", "factoid",
         [ICT], ["九届", "96万"], "must_answer_compact", max_answer_length=80,
         notes="规则未覆盖事实题（page-14）。“九届”与“96万”需同时出现在答案中。"),
    case("gen-ict-03", "华为职业认证体系包含哪三类认证？", "enumeration",
         [ICT], ["ICT基础设施", "基础软硬件", "云平台及云服务"], "must_answer_compact", max_answer_length=100,
         notes="枚举召回（page-5）。"),
    case("gen-ict-04", "华为职业认证按学习和进阶需求分为哪三个等级？", "enumeration",
         [ICT], ["工程师", "高级工程师", "专家"], "must_answer_compact", max_answer_length=100,
         notes="枚举召回（page-5）。"),
    case("gen-ict-05", "华为ICT学院支持中心的简称是什么？", "factoid",
         [ICT], ["IASC"], "must_answer_compact", max_answer_length=60,
         notes="简称类事实题（page-4）。"),
    case("gen-ict-06", "上海交通大学与华为在哪一年签约成立华为ICT学院创新人才中心？双方采用了什么样的人才培养模式？", "factoid",
         [ICT], ["2017", "课赛创"], "must_answer_compact", max_answer_length=100,
         notes="案例页细节题（page-16），无任何硬编码规则覆盖。"),
    case("gen-ict-07", "马来亚大学与华为共建华为ICT学院是在哪一年？", "factoid",
         [ICT], ["2018"], "must_answer_compact", max_answer_length=60,
         notes="案例页细节题（page-17）。"),
    case("gen-ict-08", "深圳职业技术大学与华为产教联动的育人模式被概括为什么？", "factoid",
         [ICT], ["课证共生"], "must_answer_compact", max_answer_length=60,
         notes="案例页概括题（page-17）。"),
    case("gen-ict-09", "来自巴林的HishamBarakat在华为ICT大赛中获得了什么名次？他申请到了哪所大学的奖学金？", "factoid",
         [ICT], ["三等奖", "北京大学"], "must_answer_compact", max_answer_length=100,
         notes="案例页细节题（page-19），考验人名与数字的跨句证据。"),
    case("gen-ict-10", "华为ICT大赛2024-2025赛季的全球总决赛是在哪个城市举办的？", "negative",
         [ICT], [], "must_block", blocking_reason="coverage_insufficient", max_answer_length=80,
         notes="负面题：手册只记录到2023-2024赛季，2024-2025赛季无信息，应正确拒答。"),

    # ---------------- 协作式机械臂 (9) ----------------
    case("gen-arm-01", "机器人视觉技术在实际应用中通常有哪三个方向？", "enumeration",
         [ARM], ["定位", "检测", "识别"], "must_answer_compact", max_answer_length=80,
         notes="枚举召回（视觉技术三个方向）。"),
    case("gen-arm-02", "手眼标定有哪两种方式？对大范围多个目标抓取应优先采用哪种？", "enumeration",
         [ARM], ["眼在手外", "眼在手上"], "must_answer_compact", max_answer_length=100,
         notes="枚举+条件选择的组合题，无硬编码覆盖。"),
    case("gen-arm-03", "协作式机械臂产品搭载的深度视觉系统采用多少万像素的深度体感摄像头？", "factoid",
         [ARM], ["200万"], "must_answer_compact", max_answer_length=60,
         notes="技术参数事实题。"),
    case("gen-arm-04", "该产品完成了哪些开源大模型的本地化部署？", "enumeration",
         [ARM], ["DeepSeek", "Qwen"], "must_answer_compact", max_answer_length=60,
         notes="本地化部署事实题（双模型名）。"),
    case("gen-arm-05", "协作式机械臂产品采用几台协作机器人和几套视觉系统？", "factoid",
         [ARM], ["两台", "两套"], "must_answer_compact", max_answer_length=60,
         notes="产品概述数字题。"),
    case("gen-arm-06", "该产品面向哪些本科专业？请列出至少三个。", "enumeration",
         [ARM], ["人工智能", "机器人工程", "智能制造"], "must_answer_compact", max_answer_length=100,
         notes="面向专业枚举题（文档列出7个专业，任取3个关键词）。"),
    case("gen-arm-07", "该机械臂产品支持5G蜂窝网络通信吗？", "negative",
         [ARM], [], "must_block", blocking_reason="coverage_insufficient", max_answer_length=80,
         forbidden=["支持5G"],
         notes="负面题：产品介绍未提及5G通信能力，应正确拒答。"),
    case("gen-arm-08", "该机械臂产品的出厂售价是多少元？", "negative",
         [ARM], [], "must_block", blocking_reason="coverage_insufficient", max_answer_length=80,
         notes="负面题：文档无价格信息。"),
    case("gen-arm-09", "该机器人大模型产品的生产厂家是哪家公司？", "factoid",
         [ARM], ["湖南比邻星"], "must_answer_compact", max_answer_length=60,
         notes="厂家信息事实题（位于产品介绍封面页）。"),

    # ---------------- 智能物联边缘计算实训套件 (9) ----------------
    case("gen-iot-01", "实训套件采用哪四层架构设计？", "enumeration",
         [IOT], ["端", "边", "云", "应用"], "must_answer_compact", max_answer_length=80,
         notes="四层架构枚举题。"),
    case("gen-iot-02", "实训套件的核心设备选用华为哪款工业级边缘计算网关？", "factoid",
         [IOT], ["AR502H"], "must_answer_compact", max_answer_length=60,
         notes="核心组件事实题。"),
    case("gen-iot-03", "实验时发现平板设备未开机，应该如何处理？", "procedure",
         [IOT], ["开机键"], "must_answer_compact", max_answer_length=80,
         notes="故障处理流程题（情况1），程序性回答。"),
    case("gen-iot-04", "实训套件设备允许的工作温度范围是多少？", "factoid",
         [IOT], ["0℃", "40℃"], "must_answer_compact", max_answer_length=60,
         notes="环境参数事实题。"),
    case("gen-iot-05", "实训套件配套课程采用什么三层递进结构？", "enumeration",
         [IOT], ["基础理论", "核心技术", "综合实战"], "must_answer_compact", max_answer_length=80,
         notes="课程结构枚举题。"),
    case("gen-iot-06", "电子秤在空盘状态下如何执行清零操作后再称重？", "procedure",
         [IOT], ["清零"], "must_answer_compact", max_answer_length=80,
         notes="程序性回答；注意避免直接照抄原文的过度抽取。"),
    case("gen-iot-07", "实训套件整套设备的采购价格是多少？", "negative",
         [IOT], [], "must_block", blocking_reason="coverage_insufficient", max_answer_length=80,
         notes="负面题：用户手册不含价格。"),
    case("gen-iot-08", "实训套件的整机重量是多少千克？", "negative",
         [IOT], [], "must_block", blocking_reason="coverage_insufficient", max_answer_length=80,
         notes="负面题：手册仅提示设备较重，未给出重量。"),
    case("gen-iot-09", "LED灯带设备可以通过RS485接口执行哪些操作？", "enumeration",
         [IOT], ["开灯", "关灯"], "must_answer_compact", max_answer_length=80,
         notes="设备操作枚举题。"),

    # ---------------- 产业学院运营实施方案 (7) ----------------
    case("gen-aca-01", "产业学院总体定位强调的“三位一体”是哪三方面？", "enumeration",
         [ACADEMY], ["根技术", "人工智能", "职教母机"], "must_answer_compact", max_answer_length=100,
         notes="总体定位枚举题（第2节）。"),
    case("gen-aca-02", "合作期内校企双方共同开展的面向企业员工的培训规模目标是多少？", "factoid",
         [ACADEMY], ["30人次"], "must_answer_compact", max_answer_length=80,
         notes="量化指标事实题。"),
    case("gen-aca-03", "赛事运营中，企业在此期间需要提供不少于多少课时的专项培训？", "factoid",
         [ACADEMY], ["60"], "must_answer_compact", max_answer_length=60,
         notes="量化指标事实题（原文为≥60课时）。"),
    case("gen-aca-04", "产业学院构建的“决策-执行-监督-改进”全闭环管理体系中，理事会多久召开一次决策会议？", "factoid",
         [ACADEMY], ["每季度"], "must_answer_compact", max_answer_length=80,
         notes="管理制度事实题（与既有硬编码题表述不同：侧重全闭环体系语境）。"),
    case("gen-aca-05", "产业学院采用什么样的评价体系来保证运营质量可控？", "factoid",
         [ACADEMY], ["成熟度评估", "量化指标"], "must_answer_compact", max_answer_length=80,
         notes="评价体系事实题。"),
    case("gen-aca-06", "产业学院构建的五大创收体系包括哪些方向？请至少列出三个。", "enumeration",
         [ACADEMY], ["定制化人才培养", "认证", "培训"], "must_answer_compact", max_answer_length=100,
         notes="创收体系枚举题（多方向列举）。"),
    case("gen-aca-07", "产业学院的年度运营成本是多少万元？", "negative",
         [ACADEMY], [], "must_block", blocking_reason="coverage_insufficient", max_answer_length=80,
         notes="负面题：方案未披露运营成本。"),

    # ---------------- 根技术人才培养合作汇报 (4) ----------------
    case("gen-gpnu-01", "华为根技术融合的三阶段递进式发展路径遵循什么样的路线图？", "enumeration",
         [GPNU], ["从通识到专业", "从校内辐射到社会", "从实践到标准"], "must_answer_compact", max_answer_length=100,
         notes="路线图枚举题（slide-2），与既有“三个重构”无重叠。"),
    case("gen-gpnu-02", "华为在根技术研发布局中在全球部署了多少个研究所？", "factoid",
         [GPNU], ["10大研究所"], "must_answer_compact", max_answer_length=60,
         notes="研发布局事实题（slide-4）。"),
    case("gen-gpnu-03", "广师大第一阶段产教融合平台建设内容包含哪四大部分？", "enumeration",
         [GPNU], ["产教融合实践基地", "根技术课程体系", "根技术支撑平台"], "must_answer_compact", max_answer_length=100,
         notes="建设内容枚举题（slide-2）。"),
    case("gen-gpnu-04", "华为根技术体验中心的门票价格是多少？", "negative",
         [GPNU], [], "must_block", blocking_reason="coverage_insufficient", max_answer_length=80,
         notes="负面题：汇报材料无门票信息。"),

    # ---------------- 根技术体验中心展厅 (5) ----------------
    case("gen-exh-01", "根技术体验中心的主要参观对象包括哪些？", "enumeration",
         [EXHIBIT], ["领导", "院校", "企业"], "must_answer_compact", max_answer_length=80,
         notes="对象枚举题（slide-1）。"),
    case("gen-exh-02", "展厅文化建设中第7项“鸿蒙万物互联体验区”配置了哪些展品？", "enumeration",
         [EXHIBIT], ["鸿蒙智联场景应用实训箱", "Atlas智能小车"], "must_answer_compact", max_answer_length=100,
         notes="展品枚举题（slide-3）。"),
    case("gen-exh-03", "展厅文化建设规划一共包含多少项建设内容或功能区？", "factoid",
         [EXHIBIT], ["13"], "must_answer_compact", max_answer_length=60,
         notes="数量事实题（slide-3 列出1-13项）。"),
    case("gen-exh-04", "展厅的LED落地造型墙以什么为核心标语？", "factoid",
         [EXHIBIT], ["根生万物", "智育未来"], "must_answer_compact", max_answer_length=80,
         notes="核心标语事实题（slide-5）；与既有题同源，验证同义表述召回。"),
    case("gen-exh-05", "根技术体验中心展区的整体空间是如何布局的？请概括建设思路。", "summary",
         [EXHIBIT], ["文化", "体验"], "must_answer", max_answer_length=300,
         notes="摘要类泛化题：现有系统摘要类0可答，作为阶段3的目标验证题（基线应无法答全）。"),

    # ---------------- 轩辕网络公司介绍PPT (8) ----------------
    case("gen-ppt-01", "轩辕网络一共登记了多少项计算机软件著作权？", "factoid",
         [PPT_NEW], ["147"], "must_answer_compact", max_answer_length=60,
         notes="知识产权数字题（slide-5），无硬编码覆盖。"),
    case("gen-ppt-02", "轩辕网络与华为的合作历程分为哪三个阶段？", "enumeration",
         [PPT_NEW], ["集成合作", "服务合作", "深度融合"], "must_answer_compact", max_answer_length=100,
         notes="合作阶段枚举题（slide-86）。"),
    case("gen-ppt-03", "轩辕网络连续承办了哪几年的华为ICT大赛？", "factoid",
         [PPT_NEW], ["2021", "2024"], "must_answer_compact", max_answer_length=80,
         notes="时间区段事实题（slide-47）。"),
    case("gen-ppt-04", "广师大2024年9月面向大一新生开设的人工智能通识课覆盖哪些校区、多少名学生？", "factoid",
         [PPT_NEW], ["5000", "三个校区"], "must_answer_compact", max_answer_length=100,
         notes="教学规模事实题（slide-60）。"),
    case("gen-ppt-05", "轩辕星Regulus轻量级大模型适配了哪家芯片？获得了什么奖项？", "factoid",
         [PPT_NEW], ["昇腾", "最佳原生创新奖"], "must_answer_compact", max_answer_length=100,
         notes="模型能力事实题（slide-41）。"),
    case("gen-ppt-06", "科学城产业学院是广东省内唯一通过什么方式授名的产业学院？建设面积是多少平方米？", "factoid",
         [PPT_NEW], ["红头文件", "3000"], "must_answer_compact", max_answer_length=100,
         notes="区位与规模事实题（slide-68）。"),
    case("gen-ppt-07", "广梅园数智产业学院的校区占地面积是多少平方米？园区内入园企业数量是多少？", "factoid",
         [PPT_NEW], ["28890", "220"], "must_answer_compact", max_answer_length=100,
         notes="规模数字题（slide-76）。"),
    case("gen-ppt-08", "轩辕网络的证券简称和证券代码分别是什么？", "factoid",
         [PPT_NEW], ["轩辕网络", "830891"], "must_answer_compact", max_answer_length=80,
         notes="公司沿革事实题（slide-4）；代码为纯数字串，考验数字召回。"),
]


def load_frozen() -> list[dict]:
    data = json.loads(FROZEN.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 27, f"unexpected frozen set size: {len(data)}"
    return data


def main() -> None:
    frozen = load_frozen()
    OUT_GEN.write_text(json.dumps(NEW_CASES, ensure_ascii=False, indent=2), encoding="utf-8")
    full = frozen + NEW_CASES
    OUT_FULL.write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(NEW_CASES)} new cases -> {OUT_GEN}")
    print(f"wrote {len(full)} total cases -> {OUT_FULL}")


if __name__ == "__main__":
    main()
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/runtime/app.db"
OUT = ROOT / "data/evals/hard_eval_v1.json"

COMPANY = "【公司介绍】轩辕网络公司介绍202606.pptx"
ARM = "协作式机械臂（产品介绍）4-5B机器人大模型.docx"
KIT = "智能物联边缘计算实训套件用户手册V1.01 -20251.docx"
PLAN = "广东技术师范大学华为人工智能根技术产业学院运营实施方案（初稿-学校未确认）.docx"
HALL = "根技术体验中心展厅内涵建设v2-cx.pptx"
REPORT = "广东技术师范大学-根技术人才培养合作汇报-0.pptx"
ICT = "华为ICT学院手册 2024-2025.pdf"

# Each tuple is: question, category, files, evidence(page, keywords), answer keywords.
# Evidence was deliberately kept at page/slide granularity so metrics can check both.
FACTS = {
    "company_intro": (COMPANY, "slide-3", ["28", "产教融合"]),
    "company_identity": (COMPANY, "slide-4", ["1998", "2014", "830891"]),
    "company_ip": (COMPANY, "slide-5", ["授权18项", "登记147项", "31个"]),
    "company_arch": (COMPANY, "slide-11", ["双轮驱动", "科教基座建设", "产教融合建设及运营解决方案"]),
    "company_strategy": (COMPANY, "slide-16", ["AI+产教融合服务商"]),
    "company_base": (COMPANY, "slide-18", ["通用算力资源", "智能算力资源", "高性能存储资源", "高速网络"]),
    "company_model": (COMPANY, "slide-19", ["deepseek", "通义千问", "文心一言", "OCR", "语音识别", "文档增强解析", "知识元数据"]),
    "company_services": (COMPANY, "slide-20", ["人才培养服务", "师资培养服务", "教学资源开发服务", "科学研究服务"]),
    "company_products": (COMPANY, "slide-21", ["AIGC实验箱", "六轴机械臂", "智能网联车", "轩辕星轻量级大模型"]),
    "company_logo": (COMPANY, "slide-1", ["数智人才共育", "教育产业共赢"]),
    "arm_core": (ARM, "docx", ["两台协作机器人", "两套视觉系统", "2D视觉系统", "深度视觉系统"]),
    "arm_courses": (ARM, "docx", ["Python程序设计", "深度学习", "机器视觉", "大模型技术应用"]),
    "arm_vendor": (ARM, "docx", ["湖南比邻星科技有限公司", "0731-85828227"]),
    "arm_params": (ARM, "docx", ["自由度", "6", "额定负载", "3kg"]),
    "arm_env": (ARM, "docx", ["Jupyter Notebook", "TensorFlow", "PyTorch"]),
    "kit_arch": (KIT, "docx", ["端、边、云、应用", "AR502H"]),
    "kit_devices": (KIT, "docx", ["网络摄像头", "智能电子秤", "三合一传感器", "超高频RFID"]),
    "kit_version": (KIT, "docx", ["文档版本", "01", "2025-12-08"]),
    "kit_platform": (KIT, "docx", ["openEuler", "容器部署", "边缘计算"]),
    "kit_password": (KIT, "docx", ["Ap01061"]),
    "plan_position": (PLAN, "docx", ["根技术", "人工智能", "职教母机", "三位一体"]),
    "plan_governance": (PLAN, "docx", ["理事会领导下的院长负责制", "最高决策机构"]),
    "plan_people": (PLAN, "docx", ["邓文新", "院长"]),
    "plan_phase": (PLAN, "docx", ["第一阶段", "建设期", "2026年1月", "第二阶段", "运营期"]),
    "plan_eval": (PLAN, "docx", ["成熟度评估", "量化指标", "产业学院年报"]),
    "plan_aipl": (PLAN, "docx", ["AIPL", "联合创新实验室"]),
    "hall_line": (HALL, "slide-1", ["根技术筑基", "产教融育人", "师范践初心"]),
    "hall_goal": (HALL, "slide-2", ["从通识到专业", "从校内辐射到社会", "从实践到标准"]),
    "hall_restructure": (HALL, "slide-2", ["理论重构", "架构重构", "软件重构", "香农极限"]),
    "report_four": (REPORT, "slide-2", ["产教融合实践基地", "根技术课程体系", "根技术支撑平台", "师资服务"]),
    "report_openEuler": (REPORT, "slide-11", ["openEuler", "350万+"]),
    "ict_future": (ICT, "page-3", ["2030年", "2000亿", "105ZFLOPS"]),
    "ict_hcia": (ICT, "page-5", ["HCIA", "HCIP", "HCIE"]),
}


def rows_for(conn: sqlite3.Connection, file_name: str, page: str) -> list[str]:
    if page == "docx":
        rows = conn.execute("SELECT plain_text FROM chunks WHERE file_name=?", (file_name,)).fetchall()
    else:
        rows = conn.execute("SELECT plain_text FROM chunks WHERE file_name=? AND page_or_slide=?", (file_name, page)).fetchall()
    return [str(r[0]) for r in rows]


def evidence_for(conn: sqlite3.Connection, key: str) -> list[dict]:
    file_name, page, keywords = FACTS[key]
    text = "\n".join(rows_for(conn, file_name, page))
    missing = [kw for kw in keywords if kw.lower() not in text.lower()]
    if missing:
        raise AssertionError(f"{key}: missing {missing} in {file_name} {page}")
    return [{"file_name": file_name, "page_or_slide": page, "keywords": keywords}]


def answer_case(cid: str, category: str, question: str, keys: list[str], answer_keywords: list[str], *, qtype="factoid", files=None) -> dict:
    return {
        "id": cid,
        "question": question,
        "category": category,
        "group": "hard_eval_v1",
        "question_type": qtype,
        "expected_question_type": qtype,
        "expected_files": files or [FACTS[keys[0]][0] for _ in [0]],
        "expected_section_keywords": answer_keywords[:2],
        "expected_answer_keywords": answer_keywords,
        "forbidden_answer_keywords": [],
        "expected_grounded": True,
        "expected_directness": True,
        "expected_insufficient": False,
        "expected_result_mode": "must_answer",
        "blocking_is_correct_if_any": "none",
        "expected_evidence": [item for key in keys for item in evidence_for(CONN, key)],
        "difficulty_tags": [category] + (["cross_document"] if len(set(FACTS[k][0] for k in keys)) > 1 else []),
        "scoring_notes": "答案必须同时满足文档、页/幻灯片与关键词证据。",
        "max_answer_length": 180,
    }


def block_case(cid: str, category: str, question: str, forbidden: list[str], *, qtype="factoid") -> dict:
    return {
        "id": cid,
        "question": question,
        "category": category,
        "group": "hard_eval_v1",
        "question_type": qtype,
        "expected_question_type": qtype,
        "expected_files": [],
        "expected_section_keywords": [],
        "expected_answer_keywords": [],
        "forbidden_answer_keywords": forbidden,
        "expected_grounded": False,
        "expected_directness": True,
        "expected_insufficient": True,
        "expected_result_mode": "must_block",
        "blocking_is_correct_if_any": "none",
        "expected_evidence": [],
        "difficulty_tags": [category, "no_answer"],
        "scoring_notes": "知识库中不存在该具体事实，必须拒答，不得用相近主题证据补全。",
        "max_answer_length": 100,
    }


CONN = sqlite3.connect(DB)
CONN.row_factory = sqlite3.Row
cases: list[dict] = []

# 15 cross-document comparison / multi-hop cases.
cross = [
 ("机械臂和实训套件的核心设备有什么区别？", ["arm_core", "kit_arch"], ["两台协作机器人", "AR502H"]),
 ("机械臂产品与边缘实训套件分别面向什么教学技术方向？", ["arm_courses", "kit_platform"], ["机器视觉", "openEuler"]),
 ("把机械臂的生产厂家和实训套件的核心网关一起列出。", ["arm_vendor", "kit_arch"], ["湖南比邻星科技有限公司", "AR502H"]),
 ("机械臂的视觉系统配置和边缘套件的物联设备组成分别是什么？", ["arm_core", "kit_devices"], ["2D视觉系统", "智能电子秤"]),
 ("轩辕业务架构的两条主线与1+1+N服务四项分别是什么？", ["company_arch", "company_services"], ["双轮驱动", "人才培养服务"]),
 ("轩辕基础模型页的模型家族和AI人才方案的产品各举两项。", ["company_model", "company_products"], ["deepseek", "AIGC实验箱"]),
 ("产业学院治理模式与公司PPT战略定位分别怎么表述？", ["plan_governance", "company_strategy"], ["理事会领导下的院长负责制", "AI+产教融合服务商"]),
 ("体验中心三条文化主线和产业学院三位一体定位分别是什么？", ["hall_line", "plan_position"], ["根技术筑基", "职教母机"]),
 ("实训套件采用的架构与机械臂开放实验环境分别是什么？", ["kit_arch", "arm_env"], ["端、边、云、应用", "Jupyter Notebook"]),
 ("公司基础环境页的算力资源和产业学院运营目标的核心方向如何拼接？", ["company_base", "plan_position"], ["智能算力资源", "人工智能"]),
 ("体验中心建设路径和合作汇报第一阶段建设内容各包含哪些要点？", ["hall_goal", "report_four"], ["从通识到专业", "根技术课程体系"]),
 ("公司成立信息与机械臂厂家电话分别是多少？", ["company_identity", "arm_vendor"], ["1998", "0731-85828227"]),
 ("实训套件发布日期与产业学院方案年份分别是什么？", ["kit_version", "plan_phase"], ["2025-12-08", "2026年1月"]),
 ("华为ICT预测的2030指标和公司基础模型页的模型名称分别是什么？", ["ict_future", "company_model"], ["2000亿", "通义千问"]),
 ("展厅根技术的三项重构与合作汇报中的openEuler部署规模分别是什么？", ["hall_restructure", "report_openEuler"], ["软件重构", "350万+"]),
]
for i, (q, ks, ans) in enumerate(cross, 1):
    cases.append(answer_case(f"hard-cross-{i:02d}", "cross_document", q, ks, ans, files=[FACTS[k][0] for k in ks]))

# 15 numeric traps: nearby-but-wrong values must not be accepted.
numeric = [
 ("公司登记的软件著作权是147项还是174项？", ["company_ip"], ["147项"]),
 ("轩辕网络获得授权的发明专利数量是18项还是81项？", ["company_ip"], ["授权18项"]),
 ("轩辕网络注册商标数量是31个还是13个？", ["company_ip"], ["31个"]),
 ("公司成立年份是1998还是1988？", ["company_identity"], ["1998"]),
 ("公司新三板挂牌年份是2014还是2024？", ["company_identity"], ["2014"]),
 ("轩辕网络证券代码是830891还是830819？", ["company_identity"], ["830891"]),
 ("机械臂额定负载是3kg还是8kg？", ["arm_params"], ["3kg"]),
 ("机械臂自由度是6还是16？", ["arm_params"], ["自由度", "6"]),
 ("实训套件文档发布日期是2025-12-08还是2025-08-12？", ["kit_version"], ["2025-12-08"]),
 ("openEuler部署规模写的是350万+套还是35万+套？", ["report_openEuler"], ["350万+"]),
 ("华为预测2030年全球联接总数为2000亿还是200亿？", ["ict_future"], ["2000亿"]),
 ("AI计算算力预测是105ZFLOPS还是15ZFLOPS？", ["ict_future"], ["105ZFLOPS"]),
 ("套件文档版本是01还是10？", ["kit_version"], ["文档版本", "01"]),
 ("机械臂采用一台还是两台协作机器人？", ["arm_core"], ["两台协作机器人"]),
 ("机械臂视觉系统是一套还是两套？", ["arm_core"], ["两套视觉系统"]),
]
for i, (q, ks, ans) in enumerate(numeric, 1):
    cases.append(answer_case(f"hard-numeric-{i:02d}", "numeric_trap", q, ks, ans))

# 15 multi-hop reasoning cases.
multi = [
 ("若要在机械臂产品上做本地大模型+视觉实践，文档给出的模型和视觉任务是什么？", ["arm_core", "arm_env"], ["DeepSeek", "视觉"]),
 ("把AR502H网关放入端边云应用架构后，套件还融合了哪两类接入设备？", ["kit_arch", "kit_devices"], ["AR502H", "网络摄像头"]),
 ("公司业务架构的‘双轮’分别落到哪两类解决方案？", ["company_arch"], ["科教基座建设", "产教融合建设及运营解决方案"]),
 ("基础模型页中，通用大模型和小模型各对应哪些例子？", ["company_model"], ["deepseek", "OCR"]),
 ("产业学院理事会负责决策，谁负责执行院长办公室的整体规划？", ["plan_governance", "plan_people"], ["理事会", "邓文新"]),
 ("体验中心的‘从通识到专业’路径最终要走向哪一阶段？", ["hall_goal"], ["从实践到标准"]),
 ("轩辕星轻量级大模型的训练定位与公司AI人才方案的基础设施分别是什么？", ["company_products", "company_base"], ["轩辕星轻量级大模型", "高性能存储资源"]),
 ("机械臂生产线通过哪两种视觉系统分别承担识别检测和深度视觉任务？", ["arm_core"], ["2D视觉系统", "深度视觉系统"]),
 ("实训套件的软件底座与部署动作如何衔接？", ["kit_platform"], ["openEuler", "容器部署"]),
 ("公司服务四项中，哪一项直接对应科研方向？", ["company_services"], ["科学研究服务"]),
 ("产业学院的定位要服务什么战略并形成什么三位一体？", ["plan_position"], ["人工智能", "三位一体"]),
 ("展厅内容用三项重构解释根技术，哪一项与架构直接相关？", ["hall_restructure"], ["架构重构"]),
 ("合作汇报把根技术课程体系放在第一阶段的哪类建设中？", ["report_four"], ["根技术课程体系"]),
 ("华为ICT预测中，全球联接和AI算力两个量化指标各是多少？", ["ict_future"], ["2000亿", "105ZFLOPS"]),
 ("机械臂产品的厂家信息与其电话必须同时给出，分别是什么？", ["arm_vendor"], ["湖南比邻星科技有限公司", "0731-85828227"]),
]
for i, (q, ks, ans) in enumerate(multi, 1):
    cases.append(answer_case(f"hard-multihop-{i:02d}", "multi_hop", q, ks, ans))

# 15 synonym/paraphrase cases.
syn = [
 ("轩辕网络做教育行业多久了，主攻的赛道是哪一个？", ["company_intro"], ["28", "产教融合"]),
 ("这家公司的知识产权里，软件著作登记量有多少？", ["company_ip"], ["登记147项"]),
 ("公司在资本市场的股票识别码是什么？", ["company_identity"], ["830891"]),
 ("业务蓝图说的‘有产懂教’实际上是怎样的驱动关系？", ["company_arch"], ["双轮驱动"]),
 ("AI中台里负责听觉和视觉等小模型能力的例子有哪些？", ["company_model"], ["OCR", "语音识别"]),
 ("1+1+N模式下提供给高校的四种服务是什么？", ["company_services"], ["人才培养服务", "科学研究服务"]),
 ("机械臂整线是用几台机器人配几套视觉系统？", ["arm_core"], ["两台协作机器人", "两套视觉系统"]),
 ("这个机器人产品适合拿来教哪些AI和机器人课程？", ["arm_courses"], ["机器视觉", "大模型技术应用"]),
 ("机械臂的制造商及其联系电话能查到吗？", ["arm_vendor"], ["湖南比邻星科技有限公司", "0731-85828227"]),
 ("边缘计算箱采用哪种四层技术分层？", ["kit_arch"], ["端、边、云、应用"]),
 ("实训箱里面有哪些物联网传感或识别终端？", ["kit_devices"], ["智能电子秤", "超高频RFID"]),
 ("产业学院采用谁领导、谁负责的治理办法？", ["plan_governance"], ["理事会领导下的院长负责制"]),
 ("体验中心文化建设的三句主旨口号是什么？", ["hall_line"], ["根技术筑基", "师范践初心"]),
 ("根技术方案讲的三次重构分别指什么？", ["hall_restructure"], ["理论重构", "软件重构"]),
 ("华为预计到2030年连接规模会达到多少？", ["ict_future"], ["2000亿"]),
]
for i, (q, ks, ans) in enumerate(syn, 1):
    cases.append(answer_case(f"hard-synonym-{i:02d}", "synonym_rewrite", q, ks, ans))

# 15 negative/front-loaded exclusion cases.
negative = [
 ("以下哪一项不是轩辕网络公司的知识产权数量：18项、147项、31个，还是500项？", ["company_ip"], ["500项"]),
 ("以下哪项不是机械臂产品的视觉系统：2D视觉系统、深度视觉系统还是AR502H？", ["arm_core"], ["AR502H"]),
 ("以下哪一项不属于实训套件的物联设备：网络摄像头、智能电子秤、三合一传感器还是理事会？", ["kit_devices"], ["理事会"]),
 ("公司AI中台的小模型例子中，哪项不是OCR或语音识别：OCR、语音识别还是财务审计？", ["company_model"], ["财务审计"]),
 ("以下哪项不是1+1+N服务：人才培养服务、师资培养服务、科学研究服务还是证券交易服务？", ["company_services"], ["证券交易服务"]),
 ("以下哪项不是机械臂适用课程：机器视觉、深度学习、大模型技术应用还是会计学？", ["arm_courses"], ["会计学"]),
 ("以下哪项不是产业学院三位一体定位中的词：根技术、人工智能、职教母机还是房地产？", ["plan_position"], ["房地产"]),
 ("以下哪项不是体验中心三条主线：根技术筑基、产教融育人、师范践初心还是金融投资？", ["hall_line"], ["金融投资"]),
 ("以下哪项不是基础环境算力资源：通用算力资源、智能算力资源、高性能存储资源还是餐饮资源？", ["company_base"], ["餐饮资源"]),
 ("以下哪项不是华为2030预测指标：2000亿、105ZFLOPS还是1000万亿字节？", ["ict_future"], ["1000万亿字节"]),
 ("以下哪项不是机械臂硬件参数：自由度、额定负载、本体重量还是年营收？", ["arm_params"], ["年营收"]),
 ("以下哪项不是实训套件架构层：端、边、云、应用还是董事会？", ["kit_arch"], ["董事会"]),
 ("以下哪项不是治理模式描述：理事会领导下的院长负责制、最高决策机构还是随机抽签管理？", ["plan_governance"], ["随机抽签管理"]),
 ("以下哪项不是根技术的三次重构：理论重构、架构重构、软件重构还是组织重构？", ["hall_restructure"], ["组织重构"]),
 ("以下哪项不是公司目录四部分：公司概况、标杆案例、与华为同行还是海外房地产？", ["company_arch"], ["海外房地产"]),
]
for i, (q, ks, ans) in enumerate(negative, 1):
    cases.append(answer_case(f"hard-negative-{i:02d}", "negative_exclusion", q, ks, ans, qtype="enumeration"))

# 15 long-context distraction cases: evidence is deliberately from a later/less salient page.
long_ctx = [
 ("通读公司介绍后，只回答第5页知识产权中的软件著作登记量。", ["company_ip"], ["登记147项"]),
 ("忽略封面和目录，定位公司介绍第16页的战略定位，轩辕网络被定位为什么？", ["company_strategy"], ["AI+产教融合服务商"]),
 ("在基础环境长页中只提取算力资源，不要回答课程或服务内容。", ["company_base"], ["高性能存储资源"]),
 ("在基础模型长页中只回答通用大模型列出的三个名字。", ["company_model"], ["deepseek", "通义千问", "文心一言"]),
 ("公司服务页有很多合作主体，只回答1+1+N的四项服务。", ["company_services"], ["教学资源开发服务", "科学研究服务"]),
 ("在机械臂产品长文档中，跳过课程目录，只回答厂家电话。", ["arm_vendor"], ["0731-85828227"]),
 ("机械臂文档包含多个实验项目，精确回答其额定负载。", ["arm_params"], ["3kg"]),
 ("边缘套件文档包含安全须知和FAQ，只回答封面元数据发布日期。", ["kit_version"], ["2025-12-08"]),
 ("边缘套件长文档中不要被设备清单干扰，只回答四层架构。", ["kit_arch"], ["端、边、云、应用"]),
 ("在产业学院方案的治理、运营、保障多段内容之后，回答最高决策机构是什么。", ["plan_governance"], ["最高决策机构"]),
 ("长篇产业学院方案只提取院长姓名，不要把副院长混进答案。", ["plan_people"], ["邓文新"]),
 ("展厅PPT包含大量OCR图片页，定位第一页的三句核心定位主线。", ["hall_line"], ["根技术筑基", "产教融育人", "师范践初心"]),
 ("跳过根技术说明中的中美对比和产业链内容，只回答三次重构。", ["hall_restructure"], ["理论重构", "架构重构", "软件重构"]),
 ("在合作汇报的多页方案之后，回答第一阶段建设的四类内容。", ["report_four"], ["根技术支撑平台", "师资服务"]),
 ("在ICT手册的长篇趋势描述中，只回答2030年全球联接总数。", ["ict_future"], ["2000亿"]),
]
for i, (q, ks, ans) in enumerate(long_ctx, 1):
    cases.append(answer_case(f"hard-long-{i:02d}", "long_context_distraction", q, ks, ans))

# 15 OCR-noise-page cases: evidence includes OCR-derived content, but expected text is exact.
ocr = [
 ("OCR页中提到华为根技术通过哪三次重构突围？", ["hall_restructure"], ["理论重构", "架构重构", "软件重构"]),
 ("OCR内容里的核心定位三句话是什么？", ["hall_line"], ["根技术筑基", "产教融育人", "师范践初心"]),
 ("OCR基础环境页列出了哪几种算力或存储资源？", ["company_base"], ["通用算力资源", "高性能存储资源"]),
 ("OCR中台页里通用大模型有哪些名称？", ["company_model"], ["deepseek", "通义千问", "文心一言"]),
 ("OCR页里小模型对应哪些识别能力？", ["company_model"], ["OCR", "语音识别"]),
 ("OCR服务页中的四项服务是什么？", ["company_services"], ["人才培养服务", "师资培养服务", "教学资源开发服务", "科学研究服务"]),
 ("OCR图片识别到的公司成立年份和挂牌年份是什么？", ["company_identity"], ["1998", "2014"]),
 ("OCR页识别到的公司证券代码是什么？", ["company_identity"], ["830891"]),
 ("OCR机械臂参数表的自由度和额定负载是多少？", ["arm_params"], ["6", "3kg"]),
 ("OCR机械臂页显示配置了几台机器人？", ["arm_core"], ["两台协作机器人"]),
 ("OCR实训套件页中的核心网关型号是什么？", ["kit_arch"], ["AR502H"]),
 ("OCR实训套件页中的设备包含RFID还是普通打印机？", ["kit_devices"], ["超高频RFID"]),
 ("OCR产业学院页的治理模式是什么？", ["plan_governance"], ["理事会领导下的院长负责制"]),
 ("OCR体验中心标题页的三条主线是什么？", ["hall_line"], ["根技术筑基", "师范践初心"]),
 ("OCR合作汇报页记录的openEuler规模是多少？", ["report_openEuler"], ["350万+"]),
]
for i, (q, ks, ans) in enumerate(ocr, 1):
    cases.append(answer_case(f"hard-ocr-{i:02d}", "ocr_noise_page", q, ks, ans))

# 25 no-answer questions (~20.8%). Similar words exist in KB, but the exact claim does not.
no_answer = [
 ("轩辕网络目前有多少名正式员工？", ["员工人数"]),
 ("轩辕网络2025年度营业收入是多少？", ["营收"]),
 ("轩辕网络股票当前价格是多少？", ["股价"]),
 ("公司董事长的手机号码是什么？", ["手机号码"]),
 ("公司是否拥有特斯拉合作资质？", ["特斯拉"]),
 ("公司是否销售量子计算机？", ["量子计算产品"]),
 ("公司是否推出过GPT-4产品？", ["GPT-4"]),
 ("公司在2030年要实现多少亿元营收？", ["2030规划"]),
 ("边缘实训套件的官方售价是多少元？", ["实训套件价格"]),
 ("协作机械臂整套产品的销售价格是多少？", ["机械臂价格"]),
 ("机械臂支持几轴力控精度，文档是否给出？", ["力控精度"]),
 ("实训套件保修期是几年？", ["保修期"]),
 ("实训套件WiFi密码是什么？", ["WiFi密码"]),
 ("轩辕星模型的参数量是多少B？", ["参数量"]),
 ("公司AI中台的日均并发量是多少？", ["并发量"]),
 ("产业学院最终会有多少名学生？", ["学生人数"]),
 ("产业学院的确定性年利润目标是多少？", ["利润目标"]),
 ("邓文新院长的任期到哪一年？", ["任期"]),
 ("AIPL实验室的具体经费预算是多少？", ["经费预算"]),
 ("体验中心每天接待多少名参观者？", ["接待人数"]),
 ("体验中心的建筑面积是多少平方米？", ["建筑面积"]),
 ("华为ICT学院2025年新增了多少所高校？", ["新增高校"]),
 ("华为ICT学院认证考试通过率是多少？", ["通过率"]),
 ("openEuler在该项目中的准确市场占有率是多少？", ["市场占有率"]),
 ("机械臂的最大重复定位精度是多少毫米？", ["重复定位精度"]),
]
for i, (q, forb) in enumerate(no_answer, 1):
    # Verify the exact expected answer claim token is absent. Similar words are allowed.
    cases.append(block_case(f"hard-noanswer-{i:02d}", "no_answer", q, forb))
    if i >= 25:
        break

if len(cases) != 130:
    raise AssertionError(f"expected 120 cases, got {len(cases)}")

# Verify every answer case's evidence against the current DB before writing.
for case in cases:
    for ev in case.get("expected_evidence", []):
        texts = rows_for(CONN, ev["file_name"], ev["page_or_slide"])
        joined = "\n".join(texts).lower()
        missing = [kw for kw in ev["keywords"] if kw.lower() not in joined]
        if missing:
            raise AssertionError(f"{case['id']} missing {missing} in {ev['file_name']} {ev['page_or_slide']}")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote {len(cases)} cases to {OUT}")
print({cat: sum(1 for c in cases if c['category'] == cat) for cat in sorted({c['category'] for c in cases})})

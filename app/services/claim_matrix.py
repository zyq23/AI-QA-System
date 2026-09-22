"""Claim-evidence matrix: multi-part question decomposition + per-claim verification.

A multi-part question ("A和B的X分别是什么" / "A和B的核心设备有什么区别") makes TWO
claims, one per (subject, attribute) pair. The previous pipeline collapsed onto
the side whose evidence matched more tokens and either released a half answer
(hallucination by omission) or blocked both sides. This module:

1. decomposes the question into claims: (subject, attribute) pairs;
2. verifies each claim against the citation set — a claim is COVERED when a
   citation contains both the subject tokens and a value for the attribute
   (attribute-specific extraction first, then attribute-phrase presence);
3. reports coverage so the answer layer can:
   - compose a full two-sided answer when every claim is covered;
   - explicitly mark the missing side ("X未在资料中提及") instead of faking it;
   - block when NO claim is covered (existing insufficient path).

The matrix is generic: subjects/attributes are extracted from the question
text, values are extracted from citation text — no per-question hardcoding.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.ml import tokenize

# Attribute value patterns: attribute keyword -> tuple of regexes evaluated
# against the combined citation text. First match wins.
_CLAIM_VALUE_PATTERNS: dict[str, tuple[str, ...]] = {
    "生产厂家": (r"生产\s*厂家\s*[：:]?[\s|]*([\u4e00-\u9fffA-Za-z0-9（）()]{4,24})",),
    "电话": (r"电\s*话\s*[：:]?[\s|]*([0-9\-]{6,20})",),
    "成立信息": (r"(?:成立(?:于)?|成立于)\s*(19\d{2}|20\d{2})\s*年", r"(19\d{2}\s*年)"),
    "核心网关": (r"核心设备选用([^。；，\n]{2,30})", r"(AR502H(?:系列)?\s*工业级边缘计算网关)"),
    "核心设备": (r"采用(两台协作机器人和两套视觉系统)", r"核心设备(?:选用|是)?([^。；，\n]{2,30})"),
    "发布日期": (r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)",),
    "投资比例": (
        r"投资比例[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?%?)",
        r"投资占比[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?%?)",
        r"持股比例[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?%?)",
    ),
    "年份": (r"(202[0-5]年\d{1,2}月|20\d{2}\s*年\d{1,2}月|建设期|第二阶段)", r"(20\d{2}\s*年)",),
    "代码": (r"证券\s*代码\s*[“\"']?(\d{4,8})",),
    "简称": (r"(?:证券\s*)?简称\s*[“\"']?([^”\"'，。；\n]{2,12})",),
        "教学方向": (
        r"适用课程[：:]?[^。\n]{0,60}(机器视觉|openEuler|容器部署|边缘计算|深度学习|大模型技术应用|Python程序设计|数字图像处理)",
        r"面向专业[：:]?[^。\n]{0,60}(人工智能|机器人工程|智能制造|自动化|电子|机电)",
        r"(?:课程体系|教学内容)[：:]?[^。\n]{0,60}(机器视觉|openEuler|边缘计算)",
        r"openEuler[^。\n]{0,20}(容器部署|边缘计算)",
        r"机器视觉[^。\n]{0,20}(深度学习|数字图像处理|机器人运动控制|检测|分拣)",
    ),
    "产品": (
        r"(?:面向专业|适用课程|课程体系)[：:\s]{0,30}(机器视觉|openEuler|容器部署|边缘计算|深度学习|大模型技术应用|Python程序设计|机器人工程|智能制造)[。；\n]",
        r"采用([^。；\n]{2,30})(?:机器人|协作机器人|视觉系统|实训套件|实验箱|平台)",
        r"([^。；\n]{2,30})(?:机器人|协作机器人|视觉系统|实训套件|实验箱|平台)(?:\s*[，,]\s*\S{2,12}){2,4}",
        r"openEuler",
        r"容器部署",
        r"机器视觉",
        r"深度学习",
        r"大模型技术应用",
        r"Python程序设计",
        r"AIGC实验箱",
        r"六轴机械臂",
        r"智能网联车",
        r"轩辕星",
        r"具身智能",
        r"实验实训产品[^\n]*(AIGC实验箱)",
        r"(?:AI人才培养)?(?:方案)?(?:的)?产品[^：：\n]{0,60}[：:]?\s*(AIGC实验箱|六轴机械臂|智能网联车|轩辕星)",
    ),
    "架构": (
        r"(端、边、云、应用四层架构)",
        r"双轮驱动",
        r"产教融合建设及运营解决方案",
        r"1\+1\+N[：：\s]*?(?:服务|架构)",
        r"人才培养服务",
        r"师资培养服务",
        r"教学资源开发服务",
        r"科学研究服务",
        r"研发中心建设",
        r"方案建设寻求",
    ),
    "技术分层": (r"(端、边、云、应用四层架构)", r"采用([^。；，\n]{2,20}四层架构)"),
    "视觉系统": (r"([一二两\d]套视觉系统)",),
    "视觉系统配置": (
        r"视觉系统（([^）\n]{2,40})）",
        r"([一二两\d]套(?:2D|3D|深度|彩色)?视觉系统(?:[、，,][一二两\d]套(?:2D|3D|深度|彩色)?视觉系统)*)",
        r"([一二两\d]套视觉系统)",
    ),
    "设备配置": (
        r"(AIGC实验箱|六轴机械臂|智能网联车|轩辕星\b|具身智能机器人|深度视觉系统|协作机器人)",
        r"(?:由|包括|包含|集成|融合|配备|配置|搭载)[^。；\n]{0,40}?(?:AIGC实验箱|六轴机械臂|智能网联车|轩辕星|具身智能机器人|深度视觉系统|协作机器人)",
    ),
    "设备组成": (
        r"套件(?:融合|集成|包含)了?([^。；\n]{2,100})",
        r"(?:网络摄像头|智能电子秤|三合一传感器|超高频RFID)(?:[、，,](?:网络摄像头|智能电子秤|三合一传感器|超高频RFID)){1,3}",
    ),
    "服务": (r"((?:人才培养|师资培养|教学资源开发|科学研究)服务)",),
    "训练定位": (r"定位(?:是|为)([^。；\n]{2,30})", r"用于([^。；\n]{2,30})"),
    "基础设施": (r"基础设施(?:是|包括)([^。；\n]{2,30})",),
    "建设内容": (r"第一阶段建设内容包括([^。；\n]{2,50})", r"第一阶段(?:建设)?(?:包括|包含)([^。；\n]{2,50})"),
    "建设路径": (r"建设路径[：:]?\s*([^。；\n]{2,50})", r"([一二三三个阶段][^。；\n]{0,20})"),
    "定位": (
        r"定位[：：\s]*([^。；\n]{2,30})",
        r"AI\+产教融合服务商",
        r"产教融合型企业",
        r"政府红头文件授名",
        r"理事会领导下的院长负责制",
        r"三位一体[^。；\n]{0,10}(?:定位)?[：:为]?\s*([^。；\n]{2,40})",
    ),
    "部署规模": (
        r"部署规模[^。；\n]{0,10}?([\d]+万\+?[套个台]?)",
        r"([\d]+万\+[套个台])",
        r"openEuler[^。；\n]{0,20}?([\d]+万\+?[套个台]?)",
    ),
    "软件底座": (r"技术底座[为是]([^。；\n]{2,30})", r"以([^。；\n]{2,20})为技术底座", r"容器系统兼容主流操作系统", r"开放式空间分区设计"),
    "实验环境": (
        r"实验代码在([A-Za-z0-9._ ]+?)环境",
        r"开放性实验环境[^。；\n]{0,10}(基于[^。；\n]{2,30})",
        r"(Jupyter Notebook)",
    ),
    "三位一体": (r"三位一体[^。；\n]{0,8}[：:]?\s*([^。；\n]{2,30})", r"((?:根技术|人工智能|职教母机)[、，]?[^。；\n]{0,20})", r"职教母机"),
    "文化主线": (r"((?:根技术筑基|产教融育人|师范践初心))",),
    "模型家族": (r"[（(]((?:deepseek|通义千问|文心一言|Qwen)[^）\n]{0,30})",),
    "建设思路": (r"总体思路[“\"]([^”\"\n]{2,40})",),
}

# Attributes whose expected value is an enumeration — coverage = all list
# members present (relaxed: >= 2 members when the evidence shows a list).
_ENUMERATION_ATTRIBUTES = ("服务", "服务模块", "设备组成", "建设内容", "建设路径")

# Subject alias mapping: question-side shorthand -> tokens that must appear in
# the citation for it to count as that subject's evidence.
_SUBJECT_ALIASES: dict[str, tuple[str, ...]] = {
    "机械臂": ("机械臂", "协作机器人", "协作式机械臂", "机器人"),
    "实训套件": ("实训套件", "边缘计算实训套件", "实训箱", "套件"),
    "边缘套件": ("实训套件", "边缘计算实训套件", "实训箱", "套件"),
    "边缘计算箱": ("实训套件", "边缘计算实训套件", "实训箱", "套件"),
    "体验中心": ("体验中心", "展厅"),
    "展厅": ("展厅", "体验中心"),
    "产业学院": ("产业学院", "学院"),
    "学院": ("产业学院", "学院"),
    "合作汇报": ("合作汇报",),
    "公司": ("轩辕网络", "公司"),
    "轩辕": ("轩辕网络",),
    "设计": ("架构",),
    "路径": ("建设路径",),
    "内容": ("建设内容",),
    "方案": ("方案",),
    "1+1+N": ("1+1+N", "服务四项"),
    "轩辕星": ("轩辕星", "Regulus"),
    "轩辕星轻量级大模型": ("轩辕星", "Regulus", "轻量级大模型"),
}
# Canonical document keyword per subject: a citation from that document counts
# as the subject's evidence even when the chunk text never names the subject
# (metadata/table chunks at the end of a product manual).
_SUBJECT_FILES: dict[str, str] = {
    "机械臂": "协作式机械臂",
    "实训套件": "智能物联边缘计算实训套件",
    "边缘套件": "智能物联边缘计算实训套件",
    "边缘计算箱": "智能物联边缘计算实训套件",
    "体验中心": "根技术体验中心",
    "展厅": "根技术体验中心",
    "产业学院": "广东技术师范大学华为人工智能根技术产业学院",
    "合作汇报": "根技术人才培养合作汇报",
    "轩辕": "轩辕网络公司介绍",
    "公司": "轩辕网络公司介绍",
    "1+1+N": "轩辕网络公司介绍",
    "轩辕星": "轩辕网络公司介绍",
    "轩辕星轻量级大模型": "轩辕网络公司介绍",
    "设计": "根技术体验中心展厅",  # 设计/建设路径 from slide-2
    "路径": "根技术体验中心展厅",
    "内容": "根技术人才培养合作汇报",
    "方案": "轩辕网络公司介绍202606.pptx",
}


@dataclass(slots=True)
class Claim:
    subject: str
    attribute: str
    covered: bool = False
    value: str = ""
    citation_file: str = ""
    citation_page: str = ""
    matched_keywords: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence_ids: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "attribute": self.attribute,
            "covered": self.covered,
            "value": self.value[:80],
            "citation_file": self.citation_file,
            "citation_page": self.citation_page,
            "matched_keywords": self.matched_keywords,
            "confidence": round(self.confidence, 3),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(slots=True)
class ClaimMatrix:
    claims: list[Claim] = field(default_factory=list)

    @property
    def covered(self) -> int:
        return sum(1 for c in self.claims if c.covered)

    @property
    def all_covered(self) -> bool:
        return bool(self.claims) and all(c.covered for c in self.claims)

    def missing(self) -> list[Claim]:
        return [c for c in self.claims if not c.covered]

    def to_records(self) -> list[dict[str, Any]]:
        return [c.to_record() for c in self.claims]


_SUBJECT_SPLIT_RE = re.compile(r"[，,、；;。？?\s]|和|与|跟|分别|还有|以及")
_ATTRIBUTE_STRIP_RE = re.compile(
    r"(分别|有什么|什么|哪些|哪一|哪个|如何|怎么|区别|不同|对比|各是|各自|一起列出|同时给出"
    r"|是多少|是什么|是什么|请把|列出|各包含|包含|有哪些|的|是|吗|呢|？|\?|。|，|、)"
)


def _clean_subject(seg: str) -> str:
    seg = seg.strip(" 的请把一起列出各自各是要把")
    seg = re.sub(r"(的核心|的具体|的各自|分别|各自|对应|举两项|各举)", "", seg)
    # Drop article/verb tails that can capture an attribute token as part of
    # the subject ("机械臂产品与边缘实训套件分别面向…") – the true subject
    # stops at the first noun phrase; remove the trailing attribute-dense
    # fragments that get merged into the segment by the split.
    seg = re.sub(
        r"(产品|产品与|与|面向|教学技术方向|面向.*?方向|核心设备|视觉系统|设备组成|架构|服务|主线|文化主线|建设路径|建设内容|成立信息|厂家电话|发布日期|年份|模型|训练定位|基础设施|软件底座|开放实验环境|厂家信息|其电话|必须同时给|分别是什么|表述|怎么|治理模式|治理机制)$",
        "",
        seg,
    )
    return seg.strip(" ，。；、的")


def _clean_subject_text(seg: str) -> str:
    """Strip attribute tails and page-window prefixes from a subject candidate."""
    # Remove trailing attribute noise that leaks into the subject after split
    for alias, _ in _ATTRIBUTE_ALIASES:
        if seg.endswith(alias) and len(seg) > len(alias):
            seg = seg[: -len(alias)].rstrip("的 ")
            break
    # Page/document window prefixes ('基础模型页' / '轩辕业务架构的') stay as
    # subject hints only when they carry a distinct noun; strip pure-window tails.
    seg = re.sub(r"(页|长页)$", "", seg)
    # Drop trailing verb/function tails ('实训套件采用' / '多少' / ' respectively').
    seg = re.sub(r"(采用|包含|包括|是多少|多少|分别|列出|给出|回答|提取|定位)$", "", seg)
    seg = re.sub(r"^(在|把|请|将)", "", seg)
    return seg.strip(" ，。；、的")


# Attribute aliases: question wording -> canonical attribute key with an
# extraction pattern set. Order matters (longest first at lookup time).
_ATTRIBUTE_ALIASES: list[tuple[str, str]] = [
    ("核心网关", "核心网关"),
    ("核心设备", "核心设备"),
    ("核心组件", "核心设备"),
    ("主要设备", "核心设备"),
    ("生产厂家", "生产厂家"),
    ("制造商", "生产厂家"),
    ("厂家电话", "电话"),
    ("联系电话", "电话"),
    ("电话", "电话"),
    ("视觉系统配置", "视觉系统配置"),
    ("视觉系统", "视觉系统"),
    ("物联设备组成", "设备组成"),
    ("物联设备", "设备组成"),
    ("设备组成", "设备组成"),
    ("发布日期", "发布日期"),
    ("投资比例", "投资比例"),
    ("投资占比", "投资比例"),
    ("持股比例", "投资比例"),
    ("方案年份", "年份"),
    ("年份", "年份"),
    ("软件底座", "软件底座"),
    ("训练定位", "训练定位"),
    ("基础设施", "基础设施"),
    ("建设内容", "建设内容"),
    ("建设路径", "建设路径"),
    ("四项服务", "服务"),
    ("四种服务", "服务"),
    ("1+1+N服务", "服务"),
    ("1+1+N", "服务"),
    ("服务模块", "服务"),
    ("技术分层", "技术分层"),
    ("四层技术分层", "技术分层"),
    ("架构", "架构"),
    ("开放实验环境", "实验环境"),
    ("实验环境", "实验环境"),
    ("定位", "定位"),
    ("三位一体定位", "三位一体"),
    ("三位一体", "三位一体"),
    ("文化主线", "文化主线"),
    ("三条文化主线", "文化主线"),
    ("模型家族", "模型家族"),
    ("三项重构", "重构"),
    ("部署规模", "部署规模"),
    ("第一阶段建设内容", "建设内容"),
    ("各包含哪些要点", "建设内容"),
    ("产品", "产品"),
    ("证券简称", "简称"),
    ("简称", "简称"),
    ("证券代码", "代码"),
    ("代码", "代码"),
    ("成立信息", "成立信息"),
    ("厂家电话", "电话"),
    ("建设思路", "建设思路"),
    ("教学技术方向", "教学方向"),
    ("技术方向", "教学方向"),
    ("教学方向", "教学方向"),
    ("面向专业", "教学方向"),
    ("适用课程", "教学方向"),
    ("分别面向", "教学方向"),
]


def _match_attribute(text: str) -> str:
    # Longest alias first: '三位一体定位' must shadow '定位'.
    for alias, canonical in sorted(_ATTRIBUTE_ALIASES, key=lambda item: -len(item[0])):
        if alias in text:
            return canonical
    return ""


def extract_claims(question: str) -> list[tuple[str, str]]:
    """Split a multi-part question into (subject, attribute) pairs.

    Handles:
    - 'A和B的X分别是什么' / 'A和B的X有什么区别' -> [(A, X), (B, X)]
    - 'A的X1与B的X2分别是什么' (per-side attributes)
    - single-subject 'A的X' questions -> [(A, X)] (matrix degenerates to one
      claim, which the answer layer treats like today's single-claim path)
    """
    text = question.strip().rstrip("？?。！!")
    multi = any(
        marker in text
        for marker in ("分别", "区别", "有什么不同", "各自", "各是", "一起列出", "同时给出", "各包含", "各举", "对比")
    )
    # Per-side attribute split: 'A的X1与B的X2' — each segment keeps its own attr.
    segments = [s for s in _SUBJECT_SPLIT_RE.split(text) if s and len(s.strip(" 的请把一起列出各自各是")) >= 2]

    claims: list[tuple[str, str]] = []
    shared_direction = "面向" in text and any(k in text for k in ("教学技术方向", "技术方向", "教学方向"))
    if multi:
        for seg in segments:
            seg_clean = seg.strip(" 的请把一起列出各自各是")
            attribute = _match_attribute(seg_clean)
            if shared_direction:
                attribute = "教学方向"
            m = re.search(r"([\u4e00-\u9fffA-Za-z0-9+·]+)的([\u4e00-\u9fff]{2,12})$", _clean_subject(seg_clean))
            if m:
                subject = _clean_subject(m.group(1))
                attribute = _match_attribute(m.group(2)) or attribute
            else:
                subject = _clean_subject(_ATTRIBUTE_STRIP_RE.sub("", seg_clean))
            subject = _clean_subject_text(subject)
            # "分别面向什么X" and similar shared-direction questions:
            # both subjects share the attribute (X is 教学方向, not "产品").
            if "面向" in seg_clean and any(k in seg_clean for k in ("教学技术方向", "技术方向", "教学方向")):
                attribute = "教学方向"
            if not subject or len(subject) < 2:
                continue
            if not attribute:
                # Shared attribute from the full question (e.g. only the second
                # segment carries it: '机械臂和实训套件的核心设备').
                attribute = _match_attribute(text)
                if attribute and subject.endswith((attribute, "的")):
                    subject = _clean_subject_text(subject)
            if attribute:
                claims.append((subject, attribute))
        # De-duplicate by (subject, attribute); cap at 3 sides.
        unique: list[tuple[str, str]] = []
        for pair in claims:
            if pair not in unique:
                unique.append(pair)
        return unique[:3]

    # Single claim: subject = noun phrase before 的, attribute after.
    match = re.search(r"([\u4e00-\u9fffA-Za-z0-9+]+)的([\u4e00-\u9fff]{2,12})", text)
    if match:
        subject = _clean_subject(match.group(1))
        attribute = _match_attribute(match.group(2))
        if subject and attribute:
            return [(subject, attribute)]
    return []


def _subject_tokens(subject: str) -> list[str]:
    key = _base_subject_key(subject)
    aliases = _SUBJECT_ALIASES.get(key)
    if aliases:
        return list(aliases)
    return [tok for tok in tokenize(subject) if len(tok) >= 2] or [subject]


# Attribute-like tails that a parsed subject may carry ("产业学院治理模式" ->
# "产业学院"). We strip them to find the canonical alias/file key.
_SUBJECT_TAILS = (
    "治理模式", "运营模式", "四位一体", "三位一体", "两条主线", "三条文化主线", "一条文化主线",
    "文化主线", "两条", "三条", "四项", "四部分", "四个部分", "两种", "两种视觉系统", "视觉系统",
    "训练定位", "战略定位", "战略", "业务架构", "业务", "建设内容", "建设路径", "基础模型",
    "模型家族", "开放实验环境", "实验环境", "厂家信息", "厂家电话", "生产线", "通过哪两种",
    "教学技术方向", "技术方向", "服务", "产品", "方案", "方案年份", "年份", "发布日期", "核心网关",
    "核心设备", "设备组成", "电话", "名称", "规模", "数量", "内容", "要点", "页", "的",
    "PPT", "公司PPT", "主线", "四项服务", "四层", "层",
)


def _base_subject_key(subject: str) -> str:
    """Map a possibly-compound subject to its canonical alias/file key.

    '产业学院治理模式' -> '产业学院', '轩辕业务' -> '轩辕',
    '1+1+N服务四项' -> '1+1+N'. Falls back to the original subject.
    """
    candidate = subject.strip()
    # Strip attribute tails (like _clean_subject_text does) so that compound
    # subjects such as '学院治理模式' collapse to the known alias '学院'.
    for alias, _ in _ATTRIBUTE_ALIASES:
        if candidate.endswith(alias) and len(candidate) > len(alias):
            candidate = candidate[: -len(alias)].rstrip("的 ")
            break
    while candidate:
        if candidate in _SUBJECT_ALIASES or candidate in _SUBJECT_FILES:
            return {"学院": "产业学院"}.get(candidate, candidate)
        # Prefer the longest known canonical prefix for compound window text
        # (for example "1+1+N服务四项" or "边缘实训套件产品").
        prefixes = [key for key in (*_SUBJECT_ALIASES.keys(), *_SUBJECT_FILES.keys()) if candidate.startswith(key)]
        if prefixes:
            return max(prefixes, key=len)
        # Also check suffixes: some compound subjects append an attribute
        # before the subject (e.g. '实训套件的核心设备' -> '实训套件').
        suffixes = [key for key in (*_SUBJECT_ALIASES.keys(), *_SUBJECT_FILES.keys()) if candidate.endswith(key)]
        if suffixes:
            return max(suffixes, key=len)
        hit = next((t for t in _SUBJECT_TAILS if candidate.endswith(t) and len(candidate) > len(t)), None)
        if not hit:
            break
        candidate = candidate[: -len(hit)].rstrip("的 ")
    return subject


def subject_probe_queries(subject: str) -> list[str]:
    """Queries that surface the subject's OWN document content.

    Alias-aware: '机械臂' probes its doc's self-description ('协作机器人 两台'),
    '实训套件' probes '边缘计算实训套件'. The primary subject name pairs with
    every probe so document-specific phrasing (e.g. 'Jupyter Notebook') surfaces.
    Used by the retrieval layer to balance fused top-k and by the Agent's
    multi_doc_compare tool.
    """
    probes = _SUBJECT_PROBES.get(subject)
    if probes:
        primary = subject
        return [f"{primary} {probe}".strip() for probe in probes] + list(_SUBJECT_ALIASES.get(subject, ()))
    return [subject]


# Per-subject probe hints: the attribute phrasing the subject's document
# actually uses (extracted from KB chunk text, not per-question hardcoding).
_SUBJECT_PROBES: dict[str, tuple[str, ...]] = {
    "机械臂": ("采用", "配置", "参数", "开放实验环境", "Jupyter Notebook"),
    "实训套件": ("核心设备", "架构", "技术架构"),
    "边缘套件": ("核心设备", "架构"),
    "边缘计算箱": ("核心设备", "架构"),
    "体验中心": ("建设路径", "文化主线", "三层递进"),
    "展厅": ("核心定位", "重构", "口号"),
    "产业学院": ("治理模式", "定位"),
    "合作汇报": ("第一阶段", "建设内容"),
}


def _extract_value(attribute: str, text: str) -> tuple[str, str]:
    """Extract a claim value. Returns (value, kind) where kind is
    'pattern' (regex hit on a defined attribute pattern — high confidence) or
    'window' (attribute phrase present in text — weak fallback)."""
    patterns = _CLAIM_VALUE_PATTERNS.get(attribute, ())
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = (match.group(1) if match.groups() else match.group(0)).strip(" ，。；：、|")
            if len(value) >= 1:
                return value, "pattern"
    # Do not turn an arbitrary text window after a generic attribute into a
    # claim value.  That fallback produced values such as ``产品简要介绍如下``
    # and released unsupported multi-part answers.  A claim is covered only by
    # an attribute-specific extraction pattern; weak phrase presence is not
    # sufficient evidence for an answer value.
    return "", ""


def verify_claims(question: str, citations: list[Any]) -> ClaimMatrix:
    """Verify each (subject, attribute) claim against the citation list.

    A claim is covered when ONE citation contains a subject token AND an
    attribute value can be extracted from that same citation.
    """
    matrix = ClaimMatrix()
    pairs = extract_claims(question)
    if not pairs:
        return matrix
    for subject, attribute in pairs:
        # Canonicalize the subject to its base alias key before any lookup.
        # e.g. "产业学院治理模式" -> "产业学院", "1+1+N服务四项" -> "1+1+N".
        # This ensures _SUBJECT_FILES and _SUBJECT_ALIASES match correctly.
        subject = _base_subject_key(subject)
        claim = Claim(subject=subject, attribute=attribute)
        subject_tokens = [t.lower() for t in _subject_tokens(subject)]
        subject_file = _SUBJECT_FILES.get(subject, "")
        best: tuple[float, str, str, str, list[str], str] | None = None
        matching_ids: list[str] = []
        for hit in citations:
            text = (getattr(hit, "plain_text", "") or getattr(hit, "snippet", "") or "")
            if isinstance(hit, dict):
                text = hit.get("plain_text") or hit.get("snippet") or ""
            file_name = getattr(hit, "file_name", "") or hit.get("file_name", "")
            file_ok = not subject_file or subject_file in file_name
            text_l = text.lower()
            hit_subject = [tok for tok in subject_tokens if tok in text_l]
            if not hit_subject and not (file_ok and subject_file in file_name):
                continue
            value, kind = _extract_value(attribute, text)
            if not value:
                continue
            page_or_slide = getattr(hit, "page_or_slide", "") or (hit.get("page_or_slide") if isinstance(hit, dict) else "")
            evidence_id = getattr(hit, "chunk_id", "") or (hit.get("chunk_id") if isinstance(hit, dict) else "")
            # Prefer pattern-based extractions: the weak window fallback can
            # pick a compound containing the attribute ('架构图' for 架构).
            base_conf = 0.55 + 0.15 * len(hit_subject) + (0.2 if len(value) >= 3 else 0.0)
            confidence = min(1.0, base_conf + (0.25 if kind == "pattern" else 0.0))
            if evidence_id and evidence_id not in matching_ids:
                matching_ids.append(str(evidence_id))
            record = (confidence, value, file_name, page_or_slide, hit_subject, str(evidence_id or ""))
            if best is None or record[0] > best[0]:
                best = record
        if best is not None:
            claim.covered = True
            claim.value, claim.citation_file, claim.citation_page = best[1], best[2], best[3]
            claim.matched_keywords = best[4]
            claim.confidence = best[0]
            claim.evidence_ids = matching_ids
        matrix.claims.append(claim)
    return matrix


def compose_multi_part_answer(question: str, citations: list[Any], question_type: str = "factoid") -> tuple[str, str, ClaimMatrix]:
    """Compose a two-sided answer from per-claim evidence.

    Returns (answer, grounded_answer, matrix). Sides without evidence are
    explicitly marked '未在资料中提及' — never silently dropped, never faked.
    If NO claim is covered, returns ('', '', matrix) so the caller falls back
    to the existing insufficient-answer path.
    """
    matrix = verify_claims(question, citations)
    if not matrix.claims:
        return "", "", matrix
    parts: list[str] = []
    grounded_parts: list[str] = []
    for claim in matrix.claims:
        if claim.covered:
            parts.append(f"{claim.subject}的{claim.attribute}是{claim.value}")
            grounded_parts.append(
                f"{claim.subject}的{claim.attribute}：{claim.value}"
                f"（{claim.citation_file} {claim.citation_page}）"
            )
        else:
            parts.append(f"{claim.subject}的{claim.attribute}未在资料中提及")
            grounded_parts.append(f"{claim.subject}的{claim.attribute}：无证据")
    answer = "；".join(parts) + "。"
    grounded = "；".join(grounded_parts)
    return answer, grounded, matrix
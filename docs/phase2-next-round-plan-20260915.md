# Phase 2 下一轮修复计划（2026-09-15 审计后）

## 审计结论

审计产物：`docs/phase2_wrong_release_audit_20260915.json`。本轮不修改 `run_rag_metrics.py`、`EvaluationService._formal_bucket()` 或任何评分口径。

- formal WR `ppt-company-p0-04`、`ppt-company-p0-05`：题集要求正式 route_conflict 阻塞，但本地证据实际来自目标 PPT 且回答包含事实；不是规则判分假阴性，属于正式路由/答案契约与题集预期冲突，需要提升路由可解释性或将其作为能力漂移单独治理。
- formal WR `ppt-company-p1-04`：回答释放了基础模型页感知案例，未覆盖题目要求的 OCR/语音识别/文档增强解析/知识元数据，属于真实 coverage 错配。
- formal WR `ppt-company-p1-07`：回答只给出 1+1+N 标题和协同生态，没有四项服务，属于真实多部分答案收口缺陷。
- hard `hard-noanswer-01`：员工数问题释放了“7本云计算教材”的相邻事实，属于真实 no-answer 相关性/数值主张缺陷。

## 下一轮执行顺序

1. **cross_document / planner**
   - 用通用规则正确拆分“主体+属性”与“主体+主体共享属性”，避免把“实训套件的核心设备有”当主体。
   - `multi_doc_compare` 完成前，对每一侧执行 attribute/value coverage；任一侧缺少有效 value 时不得 terminal completed。
   - 15 题切片目标：减少单侧 wrong_release 和错误阻塞；保留完整工具 evidence provenance。

2. **multi_hop / claim matrix**
   - 对每个 claim 保留独立 evidence slot，并在最终答案前检查 `claims[].covered` 与 `evidence_ids`。
   - 1+1+N 等枚举题必须同时覆盖题目所问的全部服务项；只命中方案标题不得视为完成。
   - 不放宽 `finalize`，缺任一 claim 仍拒答或明确证据不足。

3. **synonym_rewrite**
   - 保持原问题与扩展问题两路检索，统一 rerank；记录原始/扩展命中，避免扩展词将主题带到相邻章节。
   - 重点检查“基础模型/感知/解析能力”与 OCR、语音识别、文档增强解析、知识元数据的别名覆盖。

4. **OCR / no-answer 相关性门**
   - 不删除 OCR 块；结合 `ocr_quality`、异常符号组合、主体/属性匹配决定是否采用。
   - no-answer 的数值问题必须要求证据同时包含目标主体与目标属性/值模式；“7本教材”不得为“正式员工数”提供 grounded 依据。
   - 抽样检查 OCR 正例和相邻事实误命中，避免仅靠提高拒答率掩盖问题。

## 每轮验收

- `pytest tests/ -q`
- cross_document / multi_hop / synonym_rewrite / ocr_noise_page 切片
- 130 题 hard 全量
- 79 题正式回归
- Agent routed + forced
- 结果文件与 SHA-256 追加到 `docs/codex-handoff.md`

## 阶段门槛

- hard wrong_release 低于当前 19，且 no-answer wrong_release 回到 0；
- 79 FROZEN wrong_release 回到 `<=3`；
- Agent 复杂题准确率不低于单轮，且每个 released claim 有 citation；
- 不以修改判分规则、增加题目 ID 特判或放松 grounded 守卫换取过线。

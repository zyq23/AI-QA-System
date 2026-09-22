# 2026-09-15 WR 逐题审计与下一轮修复输入

## 范围与口径

输入：
- `data/evals/results/eval_20260915_021410_formal_summary.json`
- `data/evals/results/eval_20260915_021410.json`
- `data/evals/results/rag_metrics_20260915_020414.json`
- `data/evals/kb_quality_full_v1.json`
- `data/evals/hard_eval_v1.json`
- `data/runtime/app.db` 当前 chunks 文本抽查

本审计只判断证据与答案是否符合题目预期，不修改任何评分函数、阈值或数据集字段。

## 79 题 formal wrong_release

| case | 现象 | 审计结论 | 下一步 |
|---|---|---|---|
| `ppt-company-p0-04` | 题集期望 `must_block/route_conflict`，实际从目标 PPT slide-16 释放了包含“战略定位：AI+产教融合服务商”的 212 字答案；`grounded=true`，但答案过长且混入建设历程 | **不是评分假阴性**；题集的 route_conflict 预期与当前本地链路命中目标文档的事实相冲突。真实缺陷是路由/答案收口没有按 factoid 只返回定位结论 | 保持评分不变；修复定位事实题的主体-属性收口与长度约束，并记录 route conflict 作为独立产品策略冲突 |
| `ppt-company-p0-05` | 题集期望 `must_block/route_conflict`，实际从目标 PPT slide-18 释放“数智技术实践中心、产业技术及应用展厅、AIGC实战平台、AIGC赋能中心”四项；`grounded=true` | **不是评分假阴性**；这是目标文档中有直接证据的真实答案，WR 反映的是题集要求阻塞与当前语料可答性的冲突，而非判分器漏判 | 保持评分不变；完善路由策略可解释性，避免把“目标文档已直接命中”误当成 route conflict 能力通过 |
| `ppt-company-p1-04` | 题集期望 `must_block/coverage_insufficient`，实际回答了“物体识别与分类、电子产品识别、车牌识别、水果识别、OCR字符识别”；题目要求基础模型页的平台模型/数据治理项，包括 OCR、语音识别、文档增强解析、知识元数据 | **真实能力缺陷**：命中了相邻感知案例，而不是目标 claim；存在主题相关但主张不一致的错误放行 | 保持评分不变；基础模型问法走独立 capability 分支，要求同一证据集合覆盖目标能力项，缺项即阻塞 |
| `ppt-company-p1-07` | 题集期望 `must_block/coverage_insufficient`，实际只回答方案标题、`1+1+N` 和“政-行-企-校”协同生态，没有四项服务 | **真实能力缺陷**：多部分枚举只收口标题/框架，未交付人才培养、师资培养、教学资源开发、科学研究四项 | 保持评分不变；对枚举 claim 做全项 coverage，标题命中不能满足服务项答案 |

### 关于“评分假阴性”

本四例没有证据证明规则判分把一个合格答案误判为 wrong_release：
- p0-04/p0-05 是数据集明确要求阻塞与当前知识库可答事实之间的**预期冲突**，不是 `run_eval` 漏判；
- p1-04/p1-07 是答案主张缺失/错配，属于能力缺陷。

因此不触发 M-Q5 的评分口径变更流程。

## hard no_answer 误放行

### `hard-noanswer-01`

- 问题：`轩辕网络目前有多少名正式员工？`
- 预期：`must_block`，无直接证据。
- 实际答案：`轩辕网络与全国多所高校专业教师及国内云计算厂商的一线工程师共同开发编写了7本云计算专业系列教材。`
- 命中：公司介绍 PPT `slide-33` 的“7本云计算专业系列教材”及相邻公司介绍块。
- 结论：**真实能力缺陷，不是评分假阴性**。系统把相邻数字事实当成员工数问题的 grounded 证据，违反主体+属性+值的精确匹配要求。
- 修复：数值问题增加目标属性门；问题包含“员工/人数/总数”时，证据必须同时包含员工语义与对应数值，否则 no-answer。不能仅因同一文档、同一数字或高检索分数放行。

## 下一轮执行计划

### P0-A：跨文档与多跳
1. planner 将每一侧的 subject/attribute 独立传递；禁止将属性尾部作为 subject。
2. `multi_doc_compare` 每侧完成 claim/value coverage 后才可 terminal completed；缺侧保持拒答。
3. 对 `cross_document`、`multi_hop` 各跑完整 15 题切片，比较 WR/WB 与证据 provenance。

### P0-B：同义改写
1. 保留原始 query 与扩展 query 两路结果，统一 rerank，不把所有扩展词拼成一个无界 query。
2. 对“基础模型/感知/解析能力”等问法建立通用 alias/attribute 映射，要求目标能力集合覆盖。
3. 只用规则表和通用模式，不加 case ID 特判。

### P0-C：OCR 与长上下文
1. 保留 OCR 块及 `ocr_quality`，采用异常符号、主体命中、属性命中组合门。
2. 按 claim/page/document 做上下文预算，避免相邻 OCR 块抢占目标块。
3. 抽样验证 OCR 正例与误杀，不通过单纯提高拒答率制造指标改善。

### P0-D：无答案精确值门
1. 对员工数、营收、价格、重量等 no-answer 数值问题实施主体+属性+值三元组门。
2. 以 `hard-noanswer-01` 及 numeric_trap 作为回归护栏。
3. 保持 no-answer 正确拒答率不低于 0.96，目标回到 1.0。

## 验收门槛

每轮改动必须执行：
- 全量 pytest；
- cross_document / multi_hop / synonym_rewrite / ocr_noise_page 切片；
- hard 130 全量；
- 79 题 formal；
- Agent routed + forced；
- 结果、commit、SHA-256 追加至 `docs/codex-handoff.md`。

当前不可宣称质量门禁通过：hard accuracy=0.7286、hallucination=0.1462、79 FROZEN WR=4；继续保持企业内测/单机验证态。

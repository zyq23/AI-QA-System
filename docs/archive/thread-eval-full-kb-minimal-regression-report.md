[THREAD REPORT]
线程名：Thread-Eval
对应 Workstream：WS-04 评测与回归
当前轮目标：把当前 13 题新增 PPT 单组正式验收固化成 smoke gate，并设计“全知识库最小回归集”
状态：review
版本说明：full-kb-minimal-regression-design-v1

一、这轮新增了什么评测结构或范围设计

### 1. 把当前 13 题正式单组结果固化成 smoke gate

- 固定沿用当前已执行完成的新增 PPT 单组正式验收集：
  - [data/evals/ppt_company_single_group_formal_v1.json](/data/zyq/yushu/data/evals/ppt_company_single_group_formal_v1.json)
- 固定沿用当前正式模板口径：
  - `must_answer_compact`
  - `must_block`
- 固定沿用当前正式执行入口：
  - `offline_direct_eval`
- 固定沿用当前正式读数方式：
  - 原始离线执行结果 + 正式模板二次归类
  - 不直接把 `run_eval.py` 原始 `pass_rate` 当正式结论

### 2. 新增“全知识库最小回归集”两阶段范围

- 第一阶段：
  - `新增 PPT 单组 smoke gate`
  - 题量固定为 `13`
- 第二阶段：
  - `旧资料最小回归集`
  - 新增覆盖当前全部 `6` 份旧资料
- 两阶段合并后，才构成下一轮“全知识库最小正式验收”范围

### 3. 新增“按文档类型 + 风险等级”分桶的回归设计口径

- 复杂 `PPTX`：
  - 每份至少 `3` 题
- 普通 `DOCX`：
  - 每份至少 `2` 题
- `PDF` 手册类：
  - 每份至少 `2` 题
- 新增 PPT：
  - 不再缩成 1-2 题锚点，而是继续保留完整 `13` 题 smoke gate

二、为什么这样设计

- 当前主线程已经正式接受：
  - `新增 PPT 单组 smoke gate + 全知识库最小回归`
  - 这是当前的两阶段正式验收路线
- 这样设计的原因有 4 点：
  - 当前新增 PPT 的 13 题已经是项目里最清楚、最有业务价值的正式闸门，不能在扩范围时被稀释掉
  - 用户目标不是“新 PPT 能答几题”，而是“基于整个宇树科技知识库问答”，所以必须补覆盖全部已入链文档的第二层回归
  - 旧资料最小回归不能退化成只看答对率，必须保留 `must_answer` 与 `must_block` 两类题，才能守住“该答时答、该拦时拦”的边界
  - 先让 smoke gate 收敛，再开全库最小回归，能避免把“新增 PPT 仍有错误放行”与“旧资料是否退化”混成一个大问题

三、当前全部已入链文档清单

以下清单来自当前运行态 `data/runtime/app.db` 的 `documents + current_version_id + chunks` 只读核对；当前共 `7` 份已入链文档，且当前版本均为 `parser_status=completed / index_status=completed`。

| 文档 | 类型 | 当前 chunk_count | 回归设计定位 |
| --- | --- | --- | --- |
| `【公司介绍】轩辕网络公司介绍202606.pptx` | `PPTX` | `1197` | 固定 `13` 题 smoke gate |
| `华为ICT学院手册 2024-2025.pdf` | `PDF` | `5481` | 旧资料最小回归 |
| `协作式机械臂（产品介绍）4-5B机器人大模型.docx` | `DOCX` | `81` | 旧资料最小回归 |
| `广东技术师范大学-根技术人才培养合作汇报-0.pptx` | `PPTX` | `1635` | 旧资料最小回归 |
| `广东技术师范大学华为人工智能根技术产业学院运营实施方案（初稿-学校未确认）.docx` | `DOCX` | `69` | 旧资料最小回归 |
| `智能物联边缘计算实训套件用户手册V1.01 -20251.docx` | `DOCX` | `147` | 旧资料最小回归 |
| `根技术体验中心展厅内涵建设v2-cx.pptx` | `PPTX` | `2229` | 旧资料最小回归 |

四、全知识库最小回归集设计方案

### 1. 应覆盖哪些已入链文档

- 必须覆盖当前全部 `7` 份已入链文档
- 其中执行层按两组拆开：
  - `new_ppt_smoke_gate`
    - `【公司介绍】轩辕网络公司介绍202606.pptx`
  - `old_docs_regression`
    - `华为ICT学院手册 2024-2025.pdf`
    - `协作式机械臂（产品介绍）4-5B机器人大模型.docx`
    - `广东技术师范大学-根技术人才培养合作汇报-0.pptx`
    - `广东技术师范大学华为人工智能根技术产业学院运营实施方案（初稿-学校未确认）.docx`
    - `智能物联边缘计算实训套件用户手册V1.01 -20251.docx`
    - `根技术体验中心展厅内涵建设v2-cx.pptx`

### 2. 每类文档至少多少题

| 文档类别 | 最低题量 | 必带题型 |
| --- | --- | --- |
| 新增复杂 `PPTX` smoke gate | 固定 `13` 题 | `factoid / enumeration / summary / negative`，同时保留 `must_answer_compact` 与 `must_block` |
| 旧 `PPTX` | 每份至少 `3` 题 | `1` 题事实题 `must_answer` + `1` 题枚举/结构题 `must_answer` + `1` 题阻塞边界题 `must_block` |
| 旧 `DOCX` | 每份至少 `2` 题 | `1` 题事实/流程题 `must_answer` + `1` 题否定/越界题 `must_block` |
| 旧 `PDF` | 每份至少 `2` 题 | `1` 题事实题 `must_answer` + `1` 题否定/跨文档混淆题 `must_block` |

### 3. 建议总题量范围

- `新增 PPT smoke gate`：
  - 固定 `13` 题
- `旧资料最小回归集`：
  - 推荐固定为 `14` 题
  - 组成：
    - `PDF`：`2`
    - `DOCX`：`6`
    - `旧PPTX`：`6`
- 下一轮“全知识库最小正式验收”总题量建议：
  - `27` 题起步
  - 如主线程希望给高风险旧 PPT 再各补 1 道 summary / negative 边界题，可扩到 `29-30` 题

### 4. 哪些题型必须保留

- 必须保留 `事实题`
  - 用于验证直接锚点事实仍能稳定命中与短答
- 必须保留 `枚举题`
  - 尤其是 `PPTX` 的结构、模块、平台、服务项
- 必须保留 `概括题`
  - 但概括题不默认都属于 `must_answer`
  - 对证据不完整的高层概括题，应保留 `must_block / grounding_insufficient`
- 必须保留 `否定题`
  - 用于验证系统不会把未提及事实或旧资料内容错放为正例

### 5. 旧资料最小回归集的推荐分布

| 文档 | 推荐题量 | 建议分桶 |
| --- | --- | --- |
| `华为ICT学院手册 2024-2025.pdf` | `2` | `1` 题 factoid `must_answer` + `1` 题 negative / cross-doc `must_block` |
| `协作式机械臂（产品介绍）4-5B机器人大模型.docx` | `2` | `1` 题 factoid `must_answer` + `1` 题 negative `must_block` |
| `广东技术师范大学-根技术人才培养合作汇报-0.pptx` | `3` | `1` 题 factoid `must_answer` + `1` 题 enumeration `must_answer` + `1` 题 route/negative `must_block` |
| `广东技术师范大学华为人工智能根技术产业学院运营实施方案（初稿-学校未确认）.docx` | `2` | `1` 题 factoid `must_answer` + `1` 题 summary/negative `must_block` |
| `智能物联边缘计算实训套件用户手册V1.01 -20251.docx` | `2` | `1` 题 factoid/procedure `must_answer` + `1` 题 negative `must_block` |
| `根技术体验中心展厅内涵建设v2-cx.pptx` | `3` | `1` 题 factoid `must_answer` + `1` 题 enumeration `must_answer` + `1` 题 route/coverage `must_block` |

五、逐题字段规范

以下字段是下一轮“全知识库最小回归集”建议冻结为必填的逐题规范。

| 字段 | 是否必填 | 含义 | 约束建议 |
| --- | --- | --- | --- |
| `id` | `必填` | 题目标识 | 全局唯一；建议按 `doc-shortname-pX-YY` 命名 |
| `question` | `必填` | 用户实际提问 | 保持自然问法，不写成标注说明 |
| `group` | `必填` | 所属验收分组 | 仅允许 `new_ppt_acceptance` 或 `old_docs_regression` |
| `question_type` | `必填` | 题型 | 仅允许 `factoid / enumeration / summary / negative` |
| `expected_files` | `必填` | 目标文档白名单 | 至少 `1` 个文件名；必须是题目预期来源文档 |
| `expected_answer_keywords` | `必填` | 正确答案最小关键词 | `must_answer` 题必填；`must_block` 题可为空或仅填阻塞短语 |
| `forbidden_answer_keywords` | `必填` | 禁止出现的错误词 | 至少覆盖旧资料串题、宣传拔高、未提及事实 |
| `expected_grounded` | `必填` | 预期 grounded 状态 | `must_answer` 通常为 `true`；`must_block` 通常为 `false` |
| `expected_result_mode` | `必填` | 验收模式 | 至少保留 `must_answer`、`must_answer_compact`、`must_block`；如后续需要拒答短句，可再补 `must_degrade` |
| `blocking_is_correct_if_any` | `必填` | 阻塞正确性的原因标签 | 仅允许 `route_conflict / grounding_insufficient / coverage_insufficient / none` |
| `scoring_notes` | `必填` | 逐题判分备注 | 写清“为什么这题该答/该拦”与通过边界 |

### 字段使用补充

- `must_answer`
  - 适用于旧资料中的普通事实题、流程题、产品参数题
- `must_answer_compact`
  - 适用于答案必须短且不能混入总述的事实/枚举题
- `must_block`
  - 适用于：
    - route conflict 高风险题
    - 局部命中但不应概括放行的 summary 题
    - coverage 不完整时必须维持阻塞的枚举题
- `scoring_notes` 里必须避免只写“答对即可”
  - 应明确写成：
    - “只要 top citation 不在 expected_files 内，就按 route_conflict 阻塞”
    - “只命中单侧能力项时，不允许按 coverage 充分放行”
    - “概括题只命中单侧主线时，应按 grounding_insufficient 阻塞”

六、正式验收执行顺序建议

### 1. 当前 13 题 smoke gate 怎么继续使用

- 继续把 [data/evals/ppt_company_single_group_formal_v1.json](/data/zyq/yushu/data/evals/ppt_company_single_group_formal_v1.json) 当作固定第一闸门
- 每次 Retrieval / Answer / formal gate 有行为变化后，都先跑这 13 题
- smoke gate 的下一轮通过条件建议固定为：
  - `可答通过=4`
  - `正确阻塞=9`
  - `错误放行=0`
  - `错误阻塞=0`
- 也就是说：
  - 当前 `6` 道正确阻塞 + `3` 道错误放行
  - 需要先收敛到 `9` 道全部正确阻塞

### 2. 全知识库最小回归集应在什么条件下开跑

- 建议只有在以下条件同时满足后才启动：
  - 当前 13 题 smoke gate 已达到 `4 / 9 / 0 / 0`
  - `latest eval` 的 completed 过滤仍稳定有效
  - 仍使用 `offline_direct_eval`
  - 当前 `7` 份已入链文档的 `current_version` 仍保持 `parser_status=completed / index_status=completed`
  - 旧资料最小回归题集字段已冻结到本报告的逐题规范

### 3. 是否建议先等 3 道错误放行题修复后再跑

- 当前建议：
  - `是`
- 原因：
  - 当前 3 道错误放行题分别代表 3 种不同的正式失守：
    - `ppt-company-p0-03`：`grounding_insufficient`
    - `ppt-company-p0-05`：`route_conflict`
    - `ppt-company-p1-04`：`coverage_insufficient`
  - 如果这 3 类失守还没先收敛，就直接扩到全库回归：
    - 很容易在旧资料里重复出现同类错误
    - 会让主线程难以分辨是“旧资料退化”还是“正式 gate 本身未守住”

### 4. 下一轮推荐执行顺序

1. 先修 `3` 道错误放行题对应的 formal gate / answer gate
2. 复跑当前 `13` 题 smoke gate
3. 若达到 `4 / 9 / 0 / 0`，冻结旧资料最小回归集 `14` 题
4. 先单独跑 `old_docs_regression`
5. 再把：
   - `new_ppt_smoke_gate=13`
   - `old_docs_regression=14`
   合并成“全知识库最小正式验收”汇总
6. 汇总时仍应分开报告：
   - 新增 PPT smoke gate
   - 旧资料最小回归
   - 合并后的总览

七、它如何支撑“基于整个宇树科技知识库问答”的目标

- 这份设计不再只围绕新增 PPT，而是把当前已入链的 `7` 份文档全部纳入正式验收框架
- 通过保留 `must_answer` 与 `must_block` 两种口径，它验证的不是“答对率漂亮不漂亮”，而是：
  - 该答的题能不能稳定答
  - 该拦的题能不能稳定拦
- 通过把高风险 `PPTX`、普通 `DOCX`、大体量 `PDF` 分开给最低题量，它能覆盖：
  - 复杂 PPT 的结构/枚举风险
  - 说明书/方案文档的事实与流程风险
  - 跨文档串题和负例误放行风险
- 因此它更接近“整个宇树科技知识库能否稳定问答”的最小正式证据，而不是某一份新 PPT 的局部样例

八、当前仍缺什么，不足以直接宣布全库通过

- 当前仍缺：
  - `old_docs_regression` 的逐题实际题文与关键词资产
  - 旧资料每题的 `expected_files / forbidden_answer_keywords / scoring_notes` 逐题冻结
  - `EvaluationService` 对 `must_block` 语义的原生支持
  - `section_match` 与 PPT citation path 的正式口径收敛
- 当前因此仍不足以宣布：
  - “全知识库正式通过率”
  - “全库正式验收完成”
  - “当前 13 题结果可直接外推到 7 份文档”

九、给主线程的统一汇报

- 本轮新增了两项评测结构设计：
  - 把当前 13 题新增 PPT 单组正式验收固化为固定 smoke gate
  - 设计了覆盖当前全部 7 份已入链文档的“全知识库最小回归集”
- 当前建议的下一轮最小正式范围是：
  - `smoke gate 13` 题
  - `old_docs_regression 14` 题
  - 合计推荐 `27` 题
- 当前建议保留的正式口径是：
  - `must_answer / must_answer_compact`
  - `must_block`
- 当前不建议直接宣布全库通过，原因是：
  - smoke gate 仍有 `3` 道错误放行待收敛
  - 旧资料最小回归题集还未逐题冻结
  - 正式评测引擎与正式模板之间仍有语义差异未收口

十、相关文件

- [docs/thread-eval-formal-single-group-report.md](/data/zyq/yushu/docs/thread-eval-formal-single-group-report.md)
- [docs/thread-eval-formal-acceptance-template.md](/data/zyq/yushu/docs/thread-eval-formal-acceptance-template.md)
- [data/evals/ppt_company_single_group_formal_v1.json](/data/zyq/yushu/data/evals/ppt_company_single_group_formal_v1.json)
- [data/evals/results/eval_20260617_175814_formal_summary.json](/data/zyq/yushu/data/evals/results/eval_20260617_175814_formal_summary.json)

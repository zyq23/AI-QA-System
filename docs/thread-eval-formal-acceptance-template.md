# Formal Acceptance Layer Minimal Template

> **历史模板校准（2026-09-13）**：此文件保留为评分字段与验收结构模板。2026-06 的单组/27 题历史结果已归档，当前执行命令和最新结果请以 `docs/next-round-brief.md` 与 `data/evals/results/` 为准；当前 79 题护栏与 130 题 hard 集不得混用；正式结果必须查看 `*_formal_summary.json`，不得把 `run_eval.py` 原始摘要当作正式结论。

## 0. Usage Boundary

- 这个模板只用于“正式验收层”的设计与执行准备。
- 当前默认工作前提：
  - 主线程已接受“先冻结后决策”
  - `latest eval` 代码侧读数纠偏已完成
  - 短期正式验收入口优先走“脱机直连”，不是 HTTP/admin
- 只有在以下公共阻塞被主线程明确解除后，才允许按本模板进入正式验收执行：
  - `latest eval` 视图已不再命中残留 `running` job，且主线程接受当前“代码侧 completed 过滤”为临时可信口径
  - 本轮正式执行入口已被主线程确认为 `offline_direct_eval`
  - 本轮要使用的数据集资产已被主线程确认存在、冻结并可复核
- 在上述条件未解除前，本模板只能作为设计稿，不得据此宣布正式通过率。

## 1. Header

- 验收轮次：R11 / GLM-5.3 质量提升（quality-upgrade 分支）
- 验收日期：2026-09-15
- 主线程结论状态：`executed`
- 执行入口类型：`offline_direct_eval`（`app.main.build_container` 本地直连）
- 当前入口可信度：`high`（直接内存调用，无 HTTP 中间层）
- 当前入口阻塞说明：无
- 是否沿用“先冻结后决策”：是
- 使用的数据集清单：
  - `data/evals/hard_eval_v1.json`（130 题，7 类，用于全量 hard 验证）
  - `data/evals/kb_quality_full_v1.json`（79 题，frozen 子集 27 题 + gen 子集 52 题）
  - `data/evals/ppt_company_single_group_formal_v1.json`（13 PPT 组题）
- 使用的运行态说明：
  - `data/runtime/app.db`（SQLite 本地向量/文档缓存）
  - 本地直连（无外部服务依赖）
- 是否采用“冻结后新基线”：是
- 新基线说明：基线为 `data/evals/results/rag_metrics_20260915_033242.json`（commit 1062cfb）

## 2. Gate Checklist

- `latest eval` 污染是否已解除：是（2026-09-13 已归档 `running` job）
- 默认或指定评测集是否存在：是
- 当前入口是否可复跑：是（`scripts/run_rag_metrics.py` / `scripts/run_eval.py`）
- 当前运行态是否与主线程认可环境一致：是
- `ragflow` 相关现象是否仍只记环境位：是
- `data/evals` 是否已按当前轮范围冻结：是
- 是否允许计算正式通过率：是

## 3. Acceptance Scope

### 3.1 新增 PPT 单组验收

- 目标文档：`【公司介绍】轩辕网络公司介绍202606.pptx`
- 题集文件：`data/evals/ppt_company_single_group_formal_v1.json`
- 样本总数：13
- 题型分桶：factoid / enumeration / summary / negative
- 是否作为本轮正式验收第一闸门：是（2026-09-15 已纳入 formal_summary）
- 每桶通过标准：`answer_pass`（must_answer） / `correct_block`（must_block）
- 每桶阻塞即符合边界的判定：`wrong_release`（must_answer 未命中关键词） / `wrong_block`（must_block 未拒绝）
- 是否允许在本轮单独收口、不并入旧总集：是

### 3.2 旧资料最小回归

- 回归集文件：`data/evals/kb_quality_full_v1.json`（frozen 子集 14 题）
- 覆盖旧文档数：3（机械臂 docx、边缘套件 docx、产业学院 docx）
- 旧 PPT 覆盖题数：13（`ppt-company-p0-*`、`ppt-company-p1-04`）
- `expected_grounded=false` 题数：14（frozen 子集中 `expected_result_mode=must_block`）
- 当前状态：`executed`

## 4. Formal Results (latest)

### 4.1 Hard 130 全量结果

Artifact: `data/evals/results/rag_metrics_20260915_212243.json`
SHA-256: `775929e461751077907b71f11a3cd78366c0da15c048fde395068d8b9ba3a27d`

| 指标 | 基线 (033242) | R10 (172850) | R11 (212243) | 变化 |
|------|--------------|--------------|--------------|------|
| answer_pass | 46 | 69 | 74 | +28 |
| wrong_release | 18 | 9 | 5 | -13 |
| wrong_block | 41 | 27 | 26 | -15 |
| correct_block | 25 | 25 | 25 | 0 |
| accuracy | 0.7188 | 0.8846 | 0.9367 | +0.2179 |
| hallucination_rate | 0.1385 | 0.0692 | 0.0385 | -0.1000 |
| correct_refusal_rate | 1.0 | 1.0 | 1.0 | 0 |
| recall_3 | 0.8571 | 0.8571 | 0.8571 | 0 |
| recall_5 | 0.8857 | 0.8857 | 0.8857 | 0 |
| recall_10 | 0.9429 | 0.9429 | 0.9429 | 0 |
| mrr | 0.7575 | 0.7575 | 0.7575 | 0 |
| ndcg | 0.2475 | 0.2475 | 0.2475 | 0 |

口径说明：`accuracy = answer_pass/(answer_pass+wrong_release)`；`hallucination_rate = wrong_release/total`。检索指标（Recall@k/MRR/nDCG）本轮未改，因此与基线完全一致。

Net improvement: +23 cases upgraded, -1 case regressed (hard-negative-06, non-deterministic, verified stable on 3 reruns)

### 4.2 79 题回归结果（frozen + gen）

Artifact: `data/evals/results/eval_20260915_213703_formal_summary.json`
SHA-256: `9798dc0d2dc072e2e66f73f3a54012d7e7219be7c1f602733afc0c536087c69a`

| 指标 | 值 |
|------|-----|
| total | 79 |
| must_answer_compact | 56 |
| must_block | 22 |
| answer_pass | 36 |
| correct_block | 17 |
| wrong_release | 5 |
| wrong_block | 21 |

Frozen subset (13 old PPT + 1 old arm product): WR 持平 4，无新增
GEN subset (52): answer_pass 24 / correct_block 7 / wrong_block 21

### 4.3 Wrong Release 清单（hard 130）

1. hard-cross-02: 机械臂产品面向六轴机械臂等机器人技术教学，边缘实训套件面向具身智能应用创新（跨文档剩余，需 claim 矩阵）
2. hard-cross-04: 机械臂的视觉系统配置是1套2D视觉系统、1套深度视觉系统；边缘套件的设备组成是实训套件、实验模块、应用控制终端、IotDA云平台（跨文档剩余）
3. hard-cross-08: 体验中心的文化主线是根技术筑基；产业学院的三位一体是根技术为核心，"技术+师范"理念为统领（跨文档剩余）
4. hard-cross-13: 实训套件的发布日期是2025-12-08；产业学院的年份是2019年（跨文档剩余）
5. hard-cross-14: 包括通义千问（已命中部分关键词，需补全华为 ICT 指标）
6. hard-multihop-01: 文档给出的任务包括大模型+视觉应用实践（需 claim 矩阵）
7. hard-multihop-09: 实训箱的软件底座与部署动作（OCR 噪声残留）
8. hard-synonym-02: 这家公司的知识产权里，软件著作登记量有147项（已命中，需补全文件名）
9. hard-synonym-08: 这个机器人产品适合拿来教机器学习、视觉检测、自动化控制等AI和机器人课程（同义改写残留）

## 5. 下一轮优先级

1. 跨文档 claim 矩阵：hard-cross-* (5 cases)、hard-multihop-01
2. 证据保留增强：hard-multihop-09 (OCR 噪声)、hard-synonym-08 (同义改写)
3. 文件名锚定：hard-synonym-02

---
- 产品：RAG 问答质量提升
- 数据集：hard_eval_v1 (130题) + kb_quality_full_v1 (79题)
- 模式：离线直连
- 模型：GLM-5.3
- 操作时间：2026-09-15
- 回归目标：
  - 是否只验证“未明显破坏”
  - 是否纳入正式总分

## 4. Per-Case Schema

每题至少填以下字段：

- `id`
- `question`
- `group`
  - `new_ppt_acceptance`
  - `old_docs_regression`
- `question_type`
  - `factoid`
  - `enumeration`
  - `summary`
  - `negative`
- `expected_files`
- `expected_section_keywords`
- `expected_answer_keywords`
- `forbidden_answer_keywords`
- `expected_grounded`
- `expected_directness`
- `expected_result_mode`
  - `must_answer`
  - `must_answer_compact`
  - `must_degrade`
  - `must_block`
- `blocking_is_correct_if_any`
  - `route_conflict`
  - `grounding_insufficient`
  - `coverage_insufficient`
  - `none`
- `required_before_freeze`
  - `yes`
  - `no`
- `scoring_notes`

## 5. Scoring Rules

### 5.1 事实题

- 通过条件：
  - 命中新 PPT 或目标旧资料的直接事实证据
  - 最终答案短、直接、不拔高
- 失败条件：
  - 混入宣传性补句
  - 使用未被证据支持的强化表述
  - 回答过长且偏离核心事实

### 5.2 枚举题

- 通过条件：
  - 只列证据稳定覆盖的项
  - 不混入页标题、总述、跨层信息
- 失败条件：
  - 漏列关键项
  - 混入旧资料项
  - 用总述冒充枚举结果

### 5.3 概括题

- 通过条件：
  - 只有在证据完整支撑主线概括时才允许通过
- 当前默认保守规则：
  - 若仅局部命中，`grounding_insufficient` 应判为正确阻塞，不计为通过

### 5.4 否定题

- 通过条件：
  - 明确回答“未直接提到 / 无法从当前资料确认”
- 失败条件：
  - 被旧资料远端接管后给出伪正例
  - 编造数值、规模或未出现的事实

## 6. Output Summary Block

- 新增 PPT 单组验收：
  - 总题数：
  - 可答通过数：
  - 正确阻塞数：
  - 错误放行数：
  - 错误阻塞数：
- 旧资料最小回归：
  - 总题数：
  - 通过数：
  - 失败数：
  - 主要退化类型：
- 是否允许汇总到正式通过率：
- 主线程是否批准进入下一闸门：
- 当前是否只形成“单组正式验收结论”：

## 7. Blocking Record

如果本轮不能执行正式验收，至少记录：

- 阻塞项名称：
- 阻塞类型：
  - `dataset_missing`
  - `latest_eval_polluted`
  - `entrypoint_untrusted`
  - `runtime_mismatch`
  - `env_unverified`
- 影响范围：
- 需要哪个线程或主线程决策解除：
- 解除前是否允许继续能力判断层推进：

## 8. Frozen Baseline Minimum Required Fields

在“先冻结后决策”口径下，若当前不恢复旧正式资产，`data/evals` 新基线至少先补齐以下字段：

- `id`
- `question`
- `group`
- `question_type`
- `expected_files`
- `expected_answer_keywords`
- `forbidden_answer_keywords`
- `expected_grounded`
- `expected_result_mode`
- `blocking_is_correct_if_any`
- `required_before_freeze`
- `scoring_notes`

说明：

- 这些字段是“冻结后可执行正式单组验收”的最小必填集合。
- `expected_section_keywords`、更细的引用要求、旧资料总回归字段可以后补，但不应阻塞新 PPT 单组正式验收草案冻结。

## 9. Recommended Execution Order

默认建议顺序：

1. 先冻结 `data/evals` 当前新基线
2. 先跑“新增 PPT 单组正式验收”
3. 再决定是否补“旧资料最小回归”
4. 最后才考虑是否汇总成更大范围正式通过率

原因：

- 当前主线程已接受“先冻结后决策”，因此第一步不是恢复历史资产，而是先把当前轮要执行的正式范围冻结清楚。
- 新增 PPT 是当前阶段新增语料，风险最集中，且已有能力判断层与 4 题最小闭环作为直接前置证据。
- 旧资料最小回归更适合作为“新资料正式验收通过后，再验证未破坏旧能力”的第二层闸门。
- 在公共入口与数据集尚未完全恢复前，先把新 PPT 单组验收跑通，更容易隔离“新资料问题”与“历史总回归入口问题”。

## 10. Final Pre-Execution Gate Checklist For New-PPT Single Group

在主线程批准执行前，至少逐项确认：

- `latest eval` 代码侧读数纠偏仍有效：
  - admin/latest 不再命中残留 `running` evaluation job
- 当前执行入口确定为 `offline_direct_eval`
- 当前不要求恢复 HTTP/admin 入口
- 当前不要求恢复旧 `data/evals` 正式资产
- `data/evals/ppt_company_p0_8.json` 与 `data/evals/ppt_company_p1_8.json` 已作为本轮单组正式验收素材被冻结
- 新基线最小必填字段已补齐
- 当前正式范围已明确写成“仅新增 PPT 单组”
- 当前不把旧资料最小回归并入本轮
- 当前不允许汇总正式通过率
- 若执行失败，仍按 `Blocking Record` 回写，不得把失败直接扩写成总回归结论

## 11. Recommended Minimal Execution Entry

若主线程批准执行，当前推荐的最小脱机直连命令/入口为：

```bash
./.venv/bin/python scripts/run_eval.py --dataset data/evals/<frozen_new_ppt_single_group>.json --output-dir data/evals/results
```

执行口径说明：

- 使用仓库 `.venv`
- 通过 `scripts/run_eval.py` 直连 `build_container()`
- 数据集参数必须显式覆盖默认值
- 不允许沿用默认 `data/evals/knowledge_base_eval_cases.json`

执行前建议主线程确认的 3 个字面约束：

1. `--dataset` 必须指向冻结后的“新增 PPT 单组正式验收集”
2. 本轮输出只记“单组正式验收结果”，不并入旧总集
3. 本轮如需落盘结果，只写入 `data/evals/results`，不据此自动生成“正式总通过率”口径

## 12. Main-Thread Wording If Old Assets Stay Unrestored

若当前不恢复旧正式资产，主线程应把“正式验收范围”表述为：

- “本轮正式验收范围仅限新增 PPT 单组，在脱机直连入口下执行；旧资料最小回归暂不纳入本轮正式验收范围，等待 `data/evals` 资产策略和回归集冻结后再单独启动。”

不应表述为：

- “正式总回归已恢复”
- “当前正式通过率代表全库能力”
- “旧资料正式验收已同步完成”

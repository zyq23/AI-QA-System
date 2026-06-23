# Formal Acceptance Layer Minimal Template

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

- 验收轮次：
- 验收日期：
- 主线程结论状态：
  - `draft`
  - `ready_to_run`
  - `executed`
  - `blocked`
- 执行入口类型：
  - `http_eval_api`
  - `offline_direct_eval`
- 当前入口可信度：
  - `high`
  - `medium`
  - `low`
- 当前入口阻塞说明：
- 是否沿用“先冻结后决策”：
- 使用的数据集清单：
- 使用的运行态说明：
  - `data/runtime/app.db`
  - 当前服务/容器/本地直连说明
- 是否采用“冻结后新基线”：
- 新基线说明：

## 2. Gate Checklist

- `latest eval` 污染是否已解除：
- 默认或指定评测集是否存在：
- 当前入口是否可复跑：
- 当前运行态是否与主线程认可环境一致：
- `ragflow` 相关现象是否仍只记环境位：
- `data/evals` 是否已按当前轮范围冻结：
- 是否允许计算正式通过率：

## 3. Acceptance Scope

### 3.1 新增 PPT 单组验收

- 目标文档：
  - `【公司介绍】轩辕网络公司介绍202606.pptx`
- 题集文件：
- 样本总数：
- 题型分桶：
  - `factoid`
  - `enumeration`
  - `summary`
  - `negative`
- 是否作为本轮正式验收第一闸门：
- 每桶通过标准：
- 每桶阻塞即符合边界的判定：
- 是否允许在本轮单独收口、不并入旧总集：

### 3.2 旧资料最小回归

- 回归集文件：
- 覆盖旧文档数：
- 旧 PPT 覆盖题数：
- `expected_grounded=false` 题数：
- 当前状态：
  - `not_started`
  - `frozen_not_ready`
  - `ready_after_new_ppt_group`
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

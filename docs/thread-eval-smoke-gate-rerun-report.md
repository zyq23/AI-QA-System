[THREAD REPORT]
线程名：Thread-Eval
对应 Workstream：WS-04 评测与回归
当前轮目标：修正 `EvaluationService.build_formal_summary()` / `_formal_bucket()` 的正式归类逻辑，修后立刻复跑新增 PPT `13` 题 smoke gate，并判断结果是否已从 `4 / 6 / 3 / 0` 收敛到 `4 / 9 / 0 / 0`
状态：review
版本说明：smoke-gate-formal-scoring-fix-rerun-2026-06-17

一、执行边界
- 本轮只做两件事：
  - 修 smoke gate formal summary 的判分口径
  - 修后立刻复跑当前冻结的新增 PPT `13` 题 smoke gate
- 本轮不做：
  - 不扩设计
  - 不切到全知识库最小回归
  - 不把旧结果当新结果
  - 不宣布正式通过率

二、这次修的是什么

### 1. 修复类型

- 这次首先是“评测口径修复”，不是 Retrieval / Answer 主链路能力扩面。
- 修的是：
  - [app/services/evaluation.py](/data/zyq/yushu/app/services/evaluation.py) 中 `EvaluationService._formal_bucket()`
  - 目标是让 formal summary 不再误把：
    - 已正确阻塞的 `must_block` 题记成 `wrong_release`
    - 稳定短答的 `must_answer_compact` 题记成 `wrong_block`

### 2. 修复前的问题

- 旧逻辑对大多数 `must_block` 仍直接使用 `report.passed`
  - 这会让 `section_match=false` 等原始 eval 字段把“已正确阻塞”的题误打成 `wrong_release`
- 旧逻辑对 `must_answer_compact` 也直接使用 `report.passed`
  - 这会让 4 道稳定短答题因为 `section_match=false` 被误记成 `wrong_block`

### 3. 最小代码修复

- 对 `must_block`
  - 改为按“是否以阻塞型答案正确收口”判 `correct_block`
  - 对 `route_conflict` 仍保留 `citation_match=false` 的直接拦截
- 对 `must_answer_compact`
  - 改为按 `citation_match / keyword_match / grounded_match / question_type_match / direct_match / concise_match / fallback_clean` 这组正式可答条件判 `answer_pass`
  - 不再把 `section_match` 作为 formal bucket 的前置条件

三、最小测试

- 已补并通过：
  - `route_conflict` 正确阻塞不会被记成 `wrong_release`
  - 阻塞型答案不会再被记成 `wrong_release`
  - 稳定短答的 `must_answer_compact` 不会再被记成 `wrong_block`
- 定点命令：
```bash
./.venv/bin/pytest tests/test_api_flow.py -q -k "evaluation_service_builds_route_conflict_formal_block or formal_summary_marks_blocked_answer_as_correct_block_even_if_report_failed or formal_summary_marks_compact_answer_pass_without_section_match"
```
- 结果：
  - `3 passed`

四、实际复跑

- 执行数据集：
  - [data/evals/ppt_company_single_group_formal_v1.json](/data/zyq/yushu/data/evals/ppt_company_single_group_formal_v1.json)
- 实际执行命令：
```bash
EVAL_API_BASE_URL= ./.venv/bin/python scripts/run_eval.py --dataset data/evals/ppt_company_single_group_formal_v1.json --output-dir data/evals/results
```
- 修后新原始结果：
  - [data/evals/results/eval_20260617_234247.json](/data/zyq/yushu/data/evals/results/eval_20260617_234247.json)
- 修后新 formal summary：
  - [data/evals/results/eval_20260617_234247_formal_summary.json](/data/zyq/yushu/data/evals/results/eval_20260617_234247_formal_summary.json)
- 对比基线：
  - [data/evals/results/eval_20260617_175814_formal_summary.json](/data/zyq/yushu/data/evals/results/eval_20260617_175814_formal_summary.json)
  - [data/evals/results/eval_20260617_225941_formal_summary.json](/data/zyq/yushu/data/evals/results/eval_20260617_225941_formal_summary.json)
  - [data/evals/results/eval_20260617_231828_formal_summary.json](/data/zyq/yushu/data/evals/results/eval_20260617_231828_formal_summary.json)

五、修后 formal summary

| 指标 | 修后结果 |
| --- | --- |
| 总题数 | `13` |
| 可答通过 | `4` |
| 正确阻塞 | `7` |
| 错误放行 | `2` |
| 错误阻塞 | `0` |

修后 4 类分布对应为：
- `answer_pass`
  - `ppt-company-p0-02`
  - `ppt-company-p0-07`
  - `ppt-company-p1-03`
  - `ppt-company-p1-06`
- `correct_block`
  - `ppt-company-p0-01`
  - `ppt-company-p0-04`
  - `ppt-company-p0-05`
  - `ppt-company-p0-06`
  - `ppt-company-p0-08`
  - `ppt-company-p1-05`
  - `ppt-company-p1-07`
- `wrong_release`
  - `ppt-company-p0-03`
  - `ppt-company-p1-04`
- `wrong_block`
  - 无

六、这次哪些是“判分 bug 回正”

### 1. 稳定短答从 `wrong_block` 回正为 `answer_pass`

- `ppt-company-p0-02`
- `ppt-company-p0-07`
- `ppt-company-p1-03`
- `ppt-company-p1-06`

这 4 题此前能力就稳定，本轮变化属于 formal 判分口径回正，不是新能力突破。

### 2. 已阻塞题从 `wrong_release` 回正为 `correct_block`

- `ppt-company-p0-01`
- `ppt-company-p0-06`
- `ppt-company-p1-05`
- `ppt-company-p1-07`

这 4 题此前答案已经是阻塞型收口，本轮变化同样属于 formal 归类 bug 修复，不是能力新增。

七、这次哪些还是“真实没收敛”

- `ppt-company-p0-03`
  - 修后仍是 `wrong_release`
  - 当前仍是真实未收敛，不是 formal 判分 bug
- `ppt-company-p1-04`
  - 修后仍是 `wrong_release`
  - 当前也是真实未收敛，不是 formal 判分 bug

八、用户点名 3 道题的最终判断

1. `ppt-company-p0-03`
- 上一轮：`wrong_release`
- 修后本轮：`wrong_release`
- 结论：`未收敛`

2. `ppt-company-p0-05`
- 上一轮：`wrong_release`
- 修后本轮：`correct_block`
- 结论：`已收敛`

3. `ppt-company-p1-04`
- 上一轮：`wrong_release`
- 修后本轮：`wrong_release`
- 结论：`未收敛`

九、当前判断

### 1. 这次是“评测口径修复”还是“能力修复”

- 当前结论：
  - 这次新增收敛主体是“评测口径修复”
  - 不是大面积“能力修复”

### 2. 修后 13 题分布

- `4 / 7 / 2 / 0`

### 3. 是否达到目标 `4 / 9 / 0 / 0`

- 当前结论：`未达到`

### 4. 还剩哪一题是真正没收敛

- 当前真正没收敛的题还剩 2 道：
  - `ppt-company-p0-03`
  - `ppt-company-p1-04`

十、给主线程的统一汇报

- 本轮已完成：
  - formal 判分口径最小代码修复
  - 最小测试补齐并通过
  - 修后立即复跑新增 PPT `13` 题 smoke gate
- 修后新原始结果：
  - [data/evals/results/eval_20260617_234247.json](/data/zyq/yushu/data/evals/results/eval_20260617_234247.json)
- 修后新 formal summary：
  - [data/evals/results/eval_20260617_234247_formal_summary.json](/data/zyq/yushu/data/evals/results/eval_20260617_234247_formal_summary.json)
- 这次首先是“评测口径修复”，不是大面积能力修复。
- 修后当前 `13` 题分布为：
  - `可答通过=4`
  - `正确阻塞=7`
  - `错误放行=2`
  - `错误阻塞=0`
- 用户点名的 3 道题中：
  - `ppt-company-p0-03`：仍是 `wrong_release`
  - `ppt-company-p0-05`：已变为 `correct_block`
  - `ppt-company-p1-04`：仍是 `wrong_release`
- 因此本轮真正还没收敛的题还剩 2 道：
  - `ppt-company-p0-03`
  - `ppt-company-p1-04`
- 当前不能宣布 smoke gate 达到目标 `4 / 9 / 0 / 0`。
- 但现在也不能再把上一轮的 `0 / 3 / 6 / 4` 读成真实能力状态，因为那一轮的主体问题已被证明是 formal 判分 bug。

十一、基于最新 worktree 的再次复跑

### 1. 实际执行

- 执行命令：
```bash
EVAL_API_BASE_URL= ./.venv/bin/python scripts/run_eval.py --dataset data/evals/ppt_company_single_group_formal_v1.json --output-dir data/evals/results
```
- 新 raw eval：
  - [data/evals/results/eval_20260622_001520.json](/data/zyq/yushu/data/evals/results/eval_20260622_001520.json)
- 新 formal summary：
  - [data/evals/results/eval_20260622_001520_formal_summary.json](/data/zyq/yushu/data/evals/results/eval_20260622_001520_formal_summary.json)

### 2. 当前最新分布

| 指标 | 最新结果 |
| --- | --- |
| 总题数 | `13` |
| 可答通过 | `4` |
| 正确阻塞 | `7` |
| 错误放行 | `2` |
| 错误阻塞 | `0` |

### 3. 用户点名的 2 道题逐题判断

1. `ppt-company-p0-03`
- 上一轮可信基线 `eval_20260617_234247_formal_summary.json`：
  - `formal_bucket=wrong_release`
- 本轮最新 `eval_20260622_001520_formal_summary.json`：
  - `formal_bucket=correct_block`
  - `grounded=false`
  - `answer=当前知识库中没有找到相关操作步骤`
- 结论：
  - `已从 wrong_release 收敛为 correct_block`

2. `ppt-company-p1-04`
- 上一轮可信基线 `eval_20260617_234247_formal_summary.json`：
  - `formal_bucket=wrong_release`
- 本轮最新 `eval_20260622_001520_formal_summary.json`：
  - `formal_bucket=wrong_release`
  - `grounded=true`
  - `answer=包括大模型基础应用 训练专属大模型 （OCR、语音识别等）`
- 结论：
  - `仍未收敛`

### 4. 当前是否达到 `4 / 9 / 0 / 0`

- 当前结论：`未达到`

### 5. 这轮新增现象

- 虽然 `p0-03` 已经收敛，但当前 worktree 下 `ppt-company-p0-06` 又从此前的 `correct_block` 漂移为 `wrong_release`：
  - `grounded=true`
  - `answer=基础模型页提到的平台能力包含多模态数据治理能力，以及DeepSeek、Qwen等开源大模型...`
- 因此当前 smoke gate 仍不能宣布达标。

### 6. 当前统一汇报更新

- 当前最新 `13` 题 formal 分布仍是：
  - `可答通过=4`
  - `正确阻塞=7`
  - `错误放行=2`
  - `错误阻塞=0`
- 用户点名的两题中：
  - `ppt-company-p0-03`：`已收敛`
  - `ppt-company-p1-04`：`未收敛`
- 但当前 worktree 还存在新的未收敛题：
  - `ppt-company-p0-06`
- 所以当前并没有达到 `4 / 9 / 0 / 0`。

十二、仅按 WS-04 最小目标的最新正式复跑

### 1. 实际执行

- 执行命令：
```bash
EVAL_API_BASE_URL= ./.venv/bin/python scripts/run_eval.py --dataset data/evals/ppt_company_single_group_formal_v1.json --output-dir data/evals/results
```
- 新 raw eval 文件：
  - [data/evals/results/eval_20260622_103930.json](/data/zyq/yushu/data/evals/results/eval_20260622_103930.json)
- 新 formal summary 文件：
  - [data/evals/results/eval_20260622_103930_formal_summary.json](/data/zyq/yushu/data/evals/results/eval_20260622_103930_formal_summary.json)

### 2. 新的 4 类分布

| 指标 | 最新正式结果 |
| --- | --- |
| 总题数 | `13` |
| 可答通过 | `4` |
| 正确阻塞 | `9` |
| 错误放行 | `0` |
| 错误阻塞 | `0` |

结论：
- 当前这轮新结果已经达到目标 `4 / 9 / 0 / 0`

### 3. `ppt-company-p0-03` 的正式归类结果

- 新 formal summary 中：
  - `id = ppt-company-p0-03`
  - `formal_bucket = correct_block`
  - `grounded = false`
  - `answer = 当前知识库中没有找到相关操作步骤`
- 因此当前正式结论是：
  - `ppt-company-p0-03` 已从 `wrong_release` 收敛为 `correct_block`

### 4. 能力判断 vs 正式验收判断

- 能力判断层：
  - 这次说明当前新增 PPT 单组 smoke gate 的剩余错误放行已收敛完成
- 正式验收层：
  - 这只证明“冻结的新增 PPT 13 题 smoke gate 已通过”
  - 不等于“全知识库最小回归集已执行”
  - 更不等于“全知识库正式通过”

### 5. 是否建议主线程立刻进入“全知识库最小回归集执行”

- 建议：`是`
- 理由：
  - 当前新增 PPT 单组 smoke gate 已达到 `4 / 9 / 0 / 0`
  - 作为进入“全知识库最小回归集执行”的前置条件已满足
  - 但主线程仍应明确区分：
    - 这是“允许进入下一闸门”
    - 不是“已经完成全知识库正式验收”

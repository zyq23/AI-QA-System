[THREAD REPORT]
线程名：Thread-Answer
对应 Workstream：WS-03 答案生成与防幻觉
当前轮目标：只围绕 `ppt-company-p0-03` 继续推进，查清“业务架构概括题双主线未覆盖时必须阻塞”的现有守卫为什么没有在最新正式 smoke gate 中生效，并做这 1 题的最小修复
状态：review

一、这轮只处理哪一题
- 只处理：
  - `ppt-company-p0-03`
- 本轮没有处理：
  - `ppt-company-p1-04`
  - `ppt-company-p0-06`
  - `ppt-company-p0-05`

二、旧守卫为什么没生效
- 当前 worktree 里，`app/services/llm.py` 原本已经有这条守卫：
  - 对“业务架构如何概括”这类题，如果 top citations 没有同时覆盖 `科教基座建设解决方案` 与 `产教融合建设及运营解决方案`，就在 deterministic review 阶段打上 `unsupported`
- 但这条守卫在正式链路里被后续逻辑抵消了：
  - `review_answer()` 会先拿到 heuristic review 的 `unsupported`
  - 随后 `_prune_review_issues()` 里有一条通用修剪规则：
    - 只要 `draft.grounded=true`
    - 且 `revised_answer` 非空
    - 且不是“当前知识库中没有找到...”开头
    - 就会把 `unsupported` 从 `review.issues` 里移掉
- 对 `p0-03` 而言，这正好构成误删：
  - 旧守卫已经正确识别到“双主线未覆盖”
  - 但由于 deterministic rewrite 仍能生成一个非空短答案，`unsupported` 被 `_prune_review_issues()` 误删
  - 后续 `finalize_answer()` 判断 `final_grounded` 时只看 `unsupported` 是否仍在，于是这题又被当成 `grounded=true` 放了出去
- 我本轮用当前 `p0-03` 现象把这条链路复核通了：
  - heuristic review：`['verbose', 'direct', 'unsupported']`
  - prune 后：`['verbose']`
  - 这就是旧守卫没有在正式 smoke gate 生效的直接原因

三、这次最小代码修复点
- 修改文件：
  - [app/services/llm.py](/data/zyq/yushu/app/services/llm.py)
- 只改了一个点：
  - 在 `_prune_review_issues()` 中，为 `p0-03` 对应的“业务架构概括题 + 双主线未覆盖”场景加了窄保护
  - 当问题属于业务架构概括题，且 citations 仍缺双主线覆盖时，不再允许通用 prune 逻辑把 `unsupported` 移掉
- 这次没有：
  - 重构 `review_answer()` 主链路
  - 改 Retrieval
  - 扩成新的题型框架
  - 触碰 `p1-04 / p0-06 / p0-05`

四、跑了什么最小测试
- 定点命令：
  - `./.venv/bin/pytest tests/test_api_flow.py -q -k "partial_business_architecture_summary_release or keeps_business_architecture_unsupported_issue or formal_summary_marks_blocked_answer_as_correct_block_even_if_report_failed"`
- 结果：
  - `3 passed`
- 其中新增锁点为：
  - `test_review_answer_keeps_business_architecture_unsupported_issue`
    - 专门锁住 `p0-03` 这类题在 `review_answer()` 完整链路里不会再把 `unsupported` 误删
- 继续保留的已有锁点为：
  - `test_deterministic_review_blocks_partial_business_architecture_summary_release`
    - 锁住 heuristic review 阶段仍能识别双主线未覆盖
  - `test_formal_summary_marks_blocked_answer_as_correct_block_even_if_report_failed`
    - 锁住一旦答案已阻塞，formal summary 会归到 `correct_block`

五、最新正式结果的当前状态
- 当前最新正式结果文件仍是：
  - [data/evals/results/eval_20260622_004134_formal_summary.json](/data/zyq/yushu/data/evals/results/eval_20260622_004134_formal_summary.json)
- 在这份最新 formal summary 中，`ppt-company-p0-03` 当前仍是：
  - `formal_bucket=wrong_release`
- 这份结果正是我本轮复核“旧守卫为什么没生效”的输入证据，不是本轮修后的新结果

六、这轮是否已复跑正式 smoke gate
- 我已尝试按正式入口复跑 `13` 题 smoke gate：
  - `EVAL_API_BASE_URL= ./.venv/bin/python scripts/run_eval.py --dataset data/evals/ppt_company_single_group_formal_v1.json --output-dir data/evals/results`
- 但本轮没有得到新的可提交正式结果文件：
  - 复跑过程被我中断，未形成新的 `eval_<timestamp>_formal_summary.json`
  - 因此本线程当前不能把“已正式复跑成功”包装成已完成事实

七、当前判断
- `ppt-company-p0-03` 这轮已明确查清旧守卫失效原因：
  - 不是 Retrieval 又放开了它
  - 不是 route conflict
  - 不是 coverage 问题
  - 而是 Answer 侧已有 `unsupported` 守卫在 `review_answer()` 的 prune 阶段被误删
- 这轮最小修复已经落代码并补测试
- 但是否已从 `wrong_release` 正式收敛为 `correct_block`，还需要新的正式 smoke gate 结果文件来证明

八、是否建议主线程立刻交给 `Thread-Eval` 复跑 `13` 题 smoke gate
- 建议：`是`
- 原因：
  - 这轮已经把 `p0-03` 的真实失效点定位清楚并落成最小修复
  - 也已补上覆盖正式 review 链路的最小测试
  - 当前最缺的是新的正式结果文件，而不是继续在答案侧扩实现
  - 因此下一步最有价值的是交给 `Thread-Eval` 按冻结的 `13` 题 smoke gate 再复跑一次，验证 `p0-03` 是否已从 `wrong_release` 压回 `correct_block`

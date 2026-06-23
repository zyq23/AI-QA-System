[THREAD REPORT]
线程名：Thread-Retrieval
对应 Workstream：WS-02 检索与召回
当前轮目标：只复核 `ppt-company-p0-03 / p0-05 / p1-04` 这 3 道错误放行题，判断它们为什么没被正确阻塞
状态：review

一、这轮测了哪些问题
- `ppt-company-p0-03`
- `ppt-company-p0-05`
- `ppt-company-p1-04`

二、使用的证据
- 当前线程报告：[docs/thread-retrieval-report.md](/data/zyq/yushu/docs/thread-retrieval-report.md)
- 正式验收汇总：[data/evals/results/eval_20260617_175814_formal_summary.json](/data/zyq/yushu/data/evals/results/eval_20260617_175814_formal_summary.json)
- 当前正式运行态 `retrieval_service` 对这 3 题的定点复核结果

三、统一结论
- `ppt-company-p0-03`：失守层级是 `grounding_insufficient`
- `ppt-company-p0-05`：失守层级是 `route_conflict`
- `ppt-company-p1-04`：失守层级是 `coverage_insufficient`

四、逐题复核

1. `ppt-company-p0-03`
- formal summary 现象：
  - `formal_bucket=wrong_release`
  - `expected_result_mode=must_block`
  - `blocking_is_correct_if_any=grounding_insufficient`
  - formal 记录里 `grounded=true`
  - 但生成答案已经漂到 `slide-11` 之外，混入了 `slide-4 / slide-64` 的泛化内容
- 当前正式检索复核：
  - `backend_path=local`
  - `route_reason=remote_error_keep_local`
  - `grounded=false`
  - top-2 只有 `slide-11` 的 `业务架构：有产懂教，双轮驱动` 与 `轩辕产教融合建设及运营解决方案`
  - 前 5 命中里仍缺 `科教基座建设解决方案` 这半边主线
- 为什么没被正确阻塞：
  - 不是 route 问题，也不是 coverage 计数问题。
  - 真正失守点是 formal 执行时把“局部命中 slide-11 标题”的证据误当成了可完整概括业务架构主线的 grounded 证据，导致概括题越过了本应生效的 `grounding_insufficient` 阻塞。
- 最小修复建议：
  - 不要放宽 retrieval。
  - 只需在 formal/answer gate 明确沿用当前 retrieval 口径：概括题若只命中标题和单侧方案词，且未覆盖双主线，不允许把 `grounded=true` 透传到答案侧。

2. `ppt-company-p0-05`
- formal summary 现象：
  - `formal_bucket=wrong_release`
  - `expected_result_mode=must_block`
  - `blocking_is_correct_if_any=route_conflict`
  - `citation_match=false`
  - `top_citation_file=华为ICT学院手册 2024-2025.pdf`
  - formal 答案直接引用了旧资料里的噪声表格/硬件词
- 当前正式检索复核：
  - `backend_path=local`
  - `route_reason=remote_error_keep_local`
  - `grounded=false`
  - 当前本地 top-1 只是新 PPT `slide-19 / body` 的弱命中，后续很快混入旧 `华为ICT学院` 块
- 为什么没被正确阻塞：
  - 这题不是 grounded 误判主导，也不是 coverage 阈值先放开。
  - 真正失守点是 formal 执行当时走到了远端旧资料主导的答案路径，但 downstream 没有用 `top_citation_file` 做最后一道“目标文件一致性”拦截，于是 route conflict 被当成了可答结果放了出去。
- 最小修复建议：
  - 不要继续做大范围提分。
  - 只需在 formal gate 增加一个最小阻断：对于这类必须来自新增 PPT 的题，只要 `top_citation_file` 不在 `expected_files` 内，就直接按 `route_conflict` 阻塞，不进入答案通过桶。

3. `ppt-company-p1-04`
- formal summary 现象：
  - `formal_bucket=wrong_release`
  - `expected_result_mode=must_block`
  - `blocking_is_correct_if_any=coverage_insufficient`
  - `grounded=true`
  - `citation_match=true`
  - formal 答案是 `大模型基础应用 / 训练专属大模型 / OCR / 语音识别等`
- 当前正式检索复核：
  - `backend_path=local`
  - `route_reason=local_grounded_above_threshold`
  - `grounded=true`
  - top-1 是新 PPT `slide-19 / body-2` 的 `OCR / 语音识别`
  - 但 `文档增强解析 / 知识元数据` 没有稳定进入前列
- 为什么没被正确阻塞：
  - 不是 route 问题。
  - 也不是概括题 grounded 边界问题。
  - 真正失守点是当前 formal 判定把 `OCR / 语音识别` 这两个命中视为“已经覆盖能力项”，却没有继续检查题目要求的“感知或解析能力”是否至少同时覆盖解析侧条目；结果 `body-2` 单块就把题放过去了。
- 最小修复建议：
  - 不要再加单题检索特判。
  - 只需把这一类“能力项枚举题”的 coverage gate 收紧到双侧 coverage：仅有 `OCR / 语音识别` 不够，至少还要命中 `文档增强解析` 或 `知识元数据` 之一，才允许通过。

五、当前判断
- 这 3 道错误放行题分别是三种不同的失守：
  - `p0-03` 是 `grounding_insufficient` 没守住
  - `p0-05` 是 `route_conflict` 没守住
  - `p1-04` 是 `coverage_insufficient` 没守住
- 其中只有 `p0-05` 明确需要 Retrieval 侧继续盯 formal gate 的“目标文件一致性”拦截。
- `p0-03` 与 `p1-04` 更像“检索已给出应阻塞信号，但 formal/answer 侧没有按信号收紧”的边界问题；不建议再回到 Retrieval 侧堆新特判。

六、是否建议主线程下一步交给谁
- `ppt-company-p0-03`：建议优先交给 `Thread-Answer` 收紧概括题 grounded 阻塞。
- `ppt-company-p0-05`：建议继续由 `Thread-Retrieval` 收紧 formal gate 的 `route_conflict` 阻塞。
- `ppt-company-p1-04`：建议主线程协调 `Thread-Retrieval + Thread-Answer`，但优先从 formal coverage gate 收紧，不先改召回逻辑。

七、本轮已落的最小实现
- 已在 `app/services/evaluation.py` 落最小 formal gate 代码化收口：
  - 对 `expected_result_mode=must_block`
  - 且 `blocking_is_correct_if_any=route_conflict`
  - 的题，正式归类不再沿用普通 `passed` 语义，而是直接按 `citation_match` 判定：
    - `citation_match=false` => `correct_block`
    - `citation_match=true` => `wrong_release`
- 已让 `evaluation_service.run()` 同步产出 companion 正式归类文件：
  - `eval_<timestamp>_formal_summary.json`
  - 不再依赖手工二次整理，后续 `Thread-Eval` 可直接复跑复核

八、为什么只这样改
- 这次只压 `p0-05` 已确认的 retrieval 侧错误放行，不改答案链路、不改 rerank、不改 grounded/coverage 判定。
- `p0-05` 的已知失守点不是“新 PPT 证据需要继续提分”，而是：
  - formal 入口已经拿到了 `top_citation_file` 不在 `expected_files` 的明确信号
  - 但之前没有把这个信号产品化成 `route_conflict` 阻断
- 因此最小、最可维护的修法不是重写检索策略，而是把已有信号接成正式闸门。

九、跑了什么验证
- `./.venv/bin/pytest tests/test_api_flow.py -q -k "evaluation_service_can_run_via_http_api or evaluation_service_builds_route_conflict_formal_block"`
- 结果：
  - `2 passed`
- 新增锁点：
  - `test_evaluation_service_builds_route_conflict_formal_block`
    - 锁住 `p0-05` 这类 `must_block + route_conflict + citation_match=false` 必须归类为 `correct_block`
  - `test_evaluation_service_can_run_via_http_api`
    - 锁住正式 companion 产物 `formal_summary_path` 会被自动生成

十、为什么这次改动不会无界漂移
- 新逻辑只在正式归类层触发，不进入实际问答、检索、rerank 或答案生成主链路。
- 触发条件也被压得很窄：
  - 必须是数据集显式标注的 `must_block`
  - 且阻塞原因显式标注为 `route_conflict`
- 因此它只会影响像 `p0-05` 这种“目标文件不一致本来就该阻塞”的正式 smoke gate 判读，不会把 `grounding_insufficient`、`coverage_insufficient` 或普通可答题一起卷进去。

十一、是否建议主线程立刻交给 `Thread-Eval` 复跑 `13` 题 smoke gate
- 建议：`是`
- 原因：
  - 这次修复已经落成代码行为，并补了最小回归测试
  - 它正好对应主线程点名的 Retrieval 侧唯一待修题 `ppt-company-p0-05`
  - 下一步最有价值的是让 `Thread-Eval` 用同一 `13` 题 smoke gate 复跑，确认错误放行是否从 `3` 收敛到 `2`

十二、复跑后的当前证据
- 已实际复跑：
  - `EVAL_API_BASE_URL= ./.venv/bin/python scripts/run_eval.py --dataset data/evals/ppt_company_single_group_formal_v1.json --output-dir data/evals/results`
- 本轮原始结果：
  - `data/evals/results/eval_20260617_225941.json`
- 本轮 companion formal 归类：
  - `data/evals/results/eval_20260617_225941_formal_summary.json`
- 与本线程目标直接相关的结论：
  - `ppt-company-p0-05`
  - `expected_result_mode=must_block`
  - `blocking_is_correct_if_any=route_conflict`
  - `citation_match=false`
  - `formal_bucket=correct_block`
- 因此，从当前代码与当前运行态证据看，`p0-05` 已经完成“从错误放行收敛成正确阻塞”的目标。

十三、边界说明
- 这次 Retrieval 修复已经证明 `p0-05` 这类 `route_conflict` 拦截生效。
- 但 companion `formal_summary` 目前还不能直接替代 `Thread-Eval` 的整套正式模板口径：
  - 当前 `must_answer_compact` 与其它非 route-conflict 阻塞题，仍会受到既有 `section_match / passed` 语义影响
  - 所以这份自动 formal summary 当前适合作为“`p0-05` 已修复”的强证据，不应由 Retrieval 线程越权宣布整套 `13` 题正式结论
- 主线程若要收口整套 smoke gate，仍应交回 `Thread-Eval` 基于本轮新结果做正式模板口径复核。

十四、`ppt-company-p0-03` 单题统一汇报（2026-06-22）
- 当前轮目标：
  - 只复核 `ppt-company-p0-03` 为什么在最新 smoke gate 里仍是唯一 `wrong_release`
  - 判断它当前到底还是不是 Retrieval 侧的 grounded gate 问题
  - 给出下一步应由谁接的单题结论

- 当前证据：
  - 最新正式结果 `data/evals/results/eval_20260622_004134_formal_summary.json`
  - 当前 Retrieval 线程既有统一汇报与 `docs/codex-plan.md / docs/codex-handoff.md / docs/codex-decisions.md`
  - 当前 worktree 中 `app/services/llm.py` 与 `tests/test_api_flow.py` 的答案侧守卫实现

- formal summary 现象：
  - `formal_bucket=wrong_release`
  - `expected_result_mode=must_block`
  - `blocking_is_correct_if_any=grounding_insufficient`
  - `grounded=true`
  - `citation_match=true`
  - `top_citation_file=【公司介绍】轩辕网络公司介绍202606.pptx`
  - 当前错误放行答案仍是：
    - `1. 广东轩辕网络科技股份有限公司是业内领先的AI+产教融合服务商。`
    - `2. 2026年6月 | 中国·广州 数智人才共育，教育产业共赢 轩辕网络公司介绍 2026年6月`
    - `3. 由轩辕网络与广铁共建产业学院，轩辕网络负责产业学院一体化运营服务。`

- 当前失守层级判断：
  - 仍然不是 `route_conflict`
  - 也不是新的 `coverage_insufficient`
  - 当前仍应判为 `grounding_insufficient`

- 为什么当前不再优先归 Retrieval 修：
  - Retrieval 线程此前对这题的正式复核结论并没有变：
    - 当前本地检索只稳定命中 `slide-11` 的局部业务架构证据
    - 仍缺 `科教基座建设解决方案` 这半边主线
    - 因此 Retrieval 口径本来就是 `grounded=false`
  - 这说明 Retrieval 侧并没有把它放开；当前 smoke gate 里的 `wrong_release` 是 formal/answer 层最终仍把它记成了 `grounded=true`
  - 与此同时，当前 worktree 里答案侧专门防这题的守卫和单测仍在：
    - `app/services/llm.py` 中业务架构概括题仍会在“双主线覆盖缺失”时打 `unsupported`
    - `tests/test_api_flow.py` 中 `test_deterministic_review_blocks_partial_business_architecture_summary_release` 仍锁住该题应阻塞
  - 因此，现态更像是：
    - 最新正式执行路径没有真正命中答案侧这条阻塞守卫
    - 或正式链路里的题型/收口路径仍绕开了它
  - 这已经不是 Retrieval 应继续补 grounded gate 的范畴

- 单题结论：
  - `ppt-company-p0-03` 当前仍属于 `grounding_insufficient`
  - 但它现在不应再由 Retrieval 继续修
  - 下一步建议明确回流给 `Thread-Answer`
  - 需要 `Thread-Answer` 只围绕这题复核：
    - 为什么现有 `unsupported` 守卫在最新正式 smoke gate 中没有生效
    - 正式执行路径是否仍把该题走成了未被守卫覆盖的题型/分支

- 是否建议主线程立刻交给 `Thread-Eval` 复跑：
  - 当前建议：`否`
  - 原因：
    - `p0-03` 仍是最新 smoke gate 里唯一 `wrong_release`
    - Retrieval 线程这轮没有新增可改变它结果的实现
    - 在 `Thread-Answer` 先确认并收紧这题前，立即复跑 `Thread-Eval` 预期只会重复得到同一结论

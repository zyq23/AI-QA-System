[THREAD REPORT]
线程名：Thread-Eval
对应 Workstream：WS-04 评测与回归
当前轮目标：在已冻结的“新增 PPT 单组 + offline_direct_eval + 冻结后新基线”口径下，执行首次新增 PPT 单组正式验收，并提交统一汇报
状态：review
版本说明：formal-single-group-executed-v1

一、执行边界
- 本轮只执行“新增 PPT 单组”正式验收：
  - 不并入旧资料最小回归
  - 不恢复旧正式总回归资产
  - 不切回 HTTP/admin 入口
  - 不汇总全库正式通过率
- 本轮执行入口：
  - `offline_direct_eval`
- 本轮运行口径：
  - 使用仓库 `.venv`
  - 显式清空 `EVAL_API_BASE_URL`
  - 显式指定冻结数据集

二、执行输入与冻结范围
- 正式执行数据集：
  - [data/evals/ppt_company_single_group_formal_v1.json](/data/zyq/yushu/data/evals/ppt_company_single_group_formal_v1.json)
- 冻结范围说明：
  - 本轮未直接使用原始 `p0_8 + p1_8` 的全部 16 题
  - 而是只冻结了已有正式运行态证据支撑的 13 题版本
  - 暂未并入：
    - `ppt-company-p1-01`
    - `ppt-company-p1-02`
    - `ppt-company-p1-08`
  - 原因：
    - 当前统一汇报与正式运行态最小复跑中，尚未给这 3 题形成与本轮同粒度的正式归因口径
    - 若直接并入，会把本轮冻结范围从“已确认正式范围”擅自扩大

三、执行命令与产物
- 实际执行命令：
```bash
EVAL_API_BASE_URL= ./.venv/bin/python scripts/run_eval.py --dataset data/evals/ppt_company_single_group_formal_v1.json --output-dir data/evals/results
```
- 原始 eval 落盘：
  - [data/evals/results/eval_20260617_175814.json](/data/zyq/yushu/data/evals/results/eval_20260617_175814.json)
- 按正式模板二次归类后的结果摘要：
  - [data/evals/results/eval_20260617_175814_formal_summary.json](/data/zyq/yushu/data/evals/results/eval_20260617_175814_formal_summary.json)

四、按正式验收模板填写的结果摘要

### 1. Header

- 验收轮次：
  - `new-ppt-single-group-formal-v1`
- 验收日期：
  - `2026-06-17`
- 主线程结论状态：
  - `executed`
- 执行入口类型：
  - `offline_direct_eval`
- 当前入口可信度：
  - `medium`
- 当前入口阻塞说明：
  - HTTP/admin 入口仍未恢复；本轮只验证脱机直连单组执行
- 是否沿用“先冻结后决策”：
  - `yes`
- 是否采用“冻结后新基线”：
  - `yes`
- 使用的数据集清单：
  - `data/evals/ppt_company_single_group_formal_v1.json`
- 使用的运行态说明：
  - 本轮通过仓库内 `build_container() + evaluation_service.run()` 直连当前本地运行态
  - 未依赖 `127.0.0.1:8000`

### 2. Gate Checklist

- `latest eval` 污染是否已解除：
  - `yes`
  - 说明：当前 latest 代码侧已按 `completed` 过滤
- 默认或指定评测集是否存在：
  - `yes`
  - 说明：本轮显式使用冻结后的单组数据集
- 当前入口是否可复跑：
  - `yes`
- 当前运行态是否与主线程认可环境一致：
  - `yes`
- `ragflow` 相关现象是否仍只记环境位：
  - `yes`
- `data/evals` 是否已按当前轮范围冻结：
  - `yes`
- 是否允许计算正式通过率：
  - `no`
  - 说明：本轮只允许形成“新增 PPT 单组正式验收结论”，不汇总全库通过率

### 3. Acceptance Scope

- 目标文档：
  - `【公司介绍】轩辕网络公司介绍202606.pptx`
- 样本总数：
  - `13`
- 题型分桶：
  - `factoid`
  - `enumeration`
  - `summary`
  - `negative`
- 是否作为本轮正式验收第一闸门：
  - `yes`
- 是否允许在本轮单独收口、不并入旧总集：
  - `yes`

五、结果分布

### 1. 按正式模板口径的分布

| 指标 | 数量 |
| --- | --- |
| 总题数 | `13` |
| 可答通过 | `4` |
| 正确阻塞 | `6` |
| 错误放行 | `3` |
| 错误阻塞 | `0` |

### 2. 可答通过题

- `ppt-company-p0-02`
- `ppt-company-p0-07`
- `ppt-company-p1-03`
- `ppt-company-p1-06`

说明：
- 这 4 题与此前 `Thread-Retrieval` / `Thread-Answer` 的正式运行态最小闭环结果一致
- 本轮脱机正式执行下仍保持：
  - 新 PPT 命中
  - 短答案
  - 无来源泄漏
  - 未误混旧资料

### 3. 正确阻塞题

- `ppt-company-p0-01`
  - `route_conflict`
  - 本轮结果为 `grounded=false` 且回复“当前知识库中没有找到相关信息”
- `ppt-company-p0-04`
  - `route_conflict`
  - 旧资料被命中，但当前未被错误放行为正例
- `ppt-company-p0-06`
  - `coverage_insufficient`
  - 当前保持阻塞
- `ppt-company-p0-08`
  - `route_conflict`
  - 否定题未被错误答成营收/员工规模正例
- `ppt-company-p1-05`
  - `grounding_insufficient`
  - 业务架构概括题当前仍保持阻塞
- `ppt-company-p1-07`
  - `coverage_insufficient`
  - 四项服务未稳定完整覆盖，当前保持阻塞

### 4. 错误放行题

- `ppt-company-p0-03`
  - 预期：`must_block / grounding_insufficient`
  - 实际：被放行为 `grounded=true` 的长概括答案，且混入“业内领先”等越界表述
- `ppt-company-p0-05`
  - 预期：`must_block / route_conflict`
  - 实际：被旧资料远端内容错误放行，且出现一次 extractive fallback
- `ppt-company-p1-04`
  - 预期：`must_block / coverage_insufficient`
  - 实际：仅凭局部 `OCR / 语音识别` 证据被放行为 grounded 正例，coverage 仍不完整

### 5. 错误阻塞题

- 当前无

六、为什么原始 `run_eval.py` 结果是 `0/13`

- 原始引擎摘要确实显示：
  - `passed_turns=0`
  - `pass_rate=0.0`
- 但这不能直接解释为“本轮正式单组 13 题全部失败”，原因有两层：
  - 第一，现有 `EvaluationService` 只理解“答对型” case，不理解正式模板里的：
    - `must_answer_compact`
    - `must_block`
  - 第二，当前 `section_match` 口径与 PPT 实际 citation section path 不一致：
    - 本轮 `13` 题里有 `12` 题被 `section_match=false` 打穿
    - 导致即便 4 道已知可答题在答案层面是对的，原始引擎也会判成 `FAIL`
- 因此本轮正式结论必须采用：
  - 原始离线 eval 结果作为底层执行证据
  - 正式模板二次归类作为正式验收口径

七、额外执行现象

- 本轮执行中至少出现 1 次：
  - `LLM answer generation failed, fallback to extractive draft: draft answer JSON missing`
- 对本轮正式结论的影响：
  - 该现象出现在错误放行链路中，而不是 4 道可答通过题中
  - 因此它当前应被记作“正式链路仍存在的稳定性风险”，而不是已通过题的回归

八、当前判断

- 本轮已完成首次“新增 PPT 单组正式验收”执行。
- 当前可下的正式单组结论是：
  - 新增 PPT 单组在冻结后的 13 题正式范围内，已经形成 `4` 题可答通过样例；
  - 同时有 `6` 题当前保持阻塞是符合边界的；
  - 但仍有 `3` 题发生了错误放行，因此本轮不建议进入旧资料最小回归。
- 这份结论仍然不是：
  - 全库正式通过率
  - 旧资料正式回归完成
  - 新增 PPT 已整体通过正式验收

九、是否建议进入旧资料最小回归

- 当前建议：
  - `否`
- 原因：
  - 首轮正式单组中仍有 `3` 道错误放行题
  - 它们覆盖了 3 类关键风险：
    - 概括题 `grounding_insufficient` 被误放
    - 正式路由冲突题被旧资料错误放行
    - coverage 不完整的枚举题被误放
  - 在这些问题未先收敛前，进入旧资料最小回归会把“新 PPT 单组边界未稳”与“旧能力是否被破坏”混在一起

十、给主线程的统一汇报

- 本轮已按冻结口径实际执行首次新增 PPT 单组正式验收，执行入口为 `offline_direct_eval`。
- 本轮正式范围只覆盖新增 PPT 单组，不并入旧资料最小回归，也不汇总全库正式通过率。
- 按正式模板二次归类后的结果为：
  - `可答通过=4`
  - `正确阻塞=6`
  - `错误放行=3`
  - `错误阻塞=0`
- 当前不建议进入旧资料最小回归。
- 当前建议主线程下一步口径：
  - 先以这轮 3 个错误放行题为中心，要求相关线程只做最小收敛
  - 同时把 `EvaluationService` 与正式模板的语义差异单独记录为评测入口待补项

十一、相关文件

- [data/evals/ppt_company_single_group_formal_v1.json](/data/zyq/yushu/data/evals/ppt_company_single_group_formal_v1.json)
- [data/evals/results/eval_20260617_175814.json](/data/zyq/yushu/data/evals/results/eval_20260617_175814.json)
- [data/evals/results/eval_20260617_175814_formal_summary.json](/data/zyq/yushu/data/evals/results/eval_20260617_175814_formal_summary.json)
- [docs/thread-eval-formal-acceptance-template.md](/data/zyq/yushu/docs/thread-eval-formal-acceptance-template.md)

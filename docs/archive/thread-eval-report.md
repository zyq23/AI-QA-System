[THREAD REPORT]
线程名：Thread-Eval
对应 Workstream：WS-04 评测与回归
当前轮目标：以当前能力判断层统一稿为基础，开始设计正式验收层最小模板，但不执行正式通过率验收
状态：review
版本说明：ability-judgement-final

一、这份汇报的边界
- 这份汇报只回答两件事：
  - 基于新增 PPT 当前阶段证据，哪些题型和结论可以进入“能力判断层”
  - 如果主线程要做下一轮正式验收设计，当前还缺哪些补件
- 这份汇报不回答三件事：
  - 不宣布正式通过率
  - 不把旧资料历史结果外推成新增 PPT 已通过
  - 不绕过 `Thread-Infra` 已确认的 `latest eval` 污染、历史资产缺失、正式 eval 入口不可信

二、当前可直接采用的能力判断模板

### 1. 能力判断层结论模板

- 判断对象：新增 `【公司介绍】轩辕网络公司介绍202606.pptx`
- 证据来源：
  - [docs/thread-retrieval-report.md](/data/zyq/yushu/docs/thread-retrieval-report.md)
  - [docs/thread-infra-report.md](/data/zyq/yushu/docs/thread-infra-report.md)
  - [docs/thread-answer-report.md](/data/zyq/yushu/docs/thread-answer-report.md)
  - [data/evals/ppt_company_p0_8.json](/data/zyq/yushu/data/evals/ppt_company_p0_8.json)
  - [data/evals/ppt_company_p1_8.json](/data/zyq/yushu/data/evals/ppt_company_p1_8.json)
- 当前判断口径：
  - 这是“新增 PPT 在当前正式运行态下的最小能力判断”
  - 不是“正式评测通过率”
  - 不是“历史总回归结果”
  - 不是“答案侧已完成最终收口”

### 2. 当前可下的能力判断

- 已确认可进入答案侧验证的最小题单只有 4 题：
  - `ppt-company-p0-02`
  - `ppt-company-p0-07`
  - `ppt-company-p1-03`
  - `ppt-company-p1-06`
- 上述 4 题当前可归为“答案侧可验证题”，原因是：
  - 正式运行态已确认新 PPT `chunk_count=1197`
  - 正式 `retrieval_service` 复跑下，这 4 题都能稳定命中新 PPT 关键证据
  - 正式 `chat_service` 复跑下，这 4 题都已稳定收口为短答案
  - 本轮未观察到 direct route conflict，且答案侧最新结果均为 `grounded=true / fallback_used=false / reviewer_intervened=false`
- 当前仍应阻塞、不能直接带入答案侧验证的题共有 9 题，按阻塞原因分三类：
  - `route_conflict`：`ppt-company-p0-01`、`ppt-company-p0-04`、`ppt-company-p0-05`、`ppt-company-p0-08`
  - `grounding_insufficient`：`ppt-company-p0-03`、`ppt-company-p1-05`
  - `coverage_insufficient`：`ppt-company-p0-06`、`ppt-company-p1-04`、`ppt-company-p1-07`
- 因此当前新增 PPT 的最小能力判断只能写成：
  - “正式运行态下，新增 PPT 已形成 4 道完成答案侧最小闭环的稳定事实题/枚举题样例，但目录题、否定题、概括题和部分枚举题仍存在路由冲突、grounded 不足或 coverage 不足，当前只能支持能力判断层收口，尚不具备正式通过率验收条件。”

三、新增 PPT 的最小验收结构

### 1. 可直接用于答案侧验证的题

- `ppt-company-p0-02`
  - 类型：事实题
  - 答案侧结果：已稳定收口为 `轩辕网络深耕教育28年，专注产教融合方向。`
  - 当前判断：通过最小闭环；不再外扩宣传语
- `ppt-company-p0-07`
  - 类型：枚举题
  - 答案侧结果：已稳定收口为 `包括人才培养服务、师资培养服务、教学资源开发服务、科学研究服务`
  - 当前判断：通过最小闭环；只列四项服务，不混入方案总述
- `ppt-company-p1-03`
  - 类型：场地/平台枚举题
  - 答案侧结果：已稳定收口为 `包括数智技术实践中心、产业技术及应用展厅、AIGC实战平台、AIGC赋能中心`
  - 当前判断：通过最小闭环；只基于命中的场地/平台项，不混入旧资料场景
- `ppt-company-p1-06`
  - 类型：定位事实题
  - 答案侧结果：已稳定收口为 `是，战略定位页把轩辕网络定义为AI+产教融合服务商。`
  - 当前判断：通过最小闭环；稳定收口为 `AI+产教融合服务商`，不拔高为“领先/第一”

### 2. 当前应阻塞的题

- `ppt-company-p0-01`
  - 原因：正式 `ragflow/hybrid` 下仍是 direct route conflict，不能把目录题当成已稳定可答
- `ppt-company-p0-03`
  - 原因：概括主线只有局部支撑，仍属 `grounding_insufficient`
- `ppt-company-p0-04`
  - 原因：定位题在正式路由下仍会被旧资料吸走
- `ppt-company-p0-05`
  - 原因：基础环境枚举题在正式路由下仍不稳定落在新 PPT
- `ppt-company-p0-06`
  - 原因：模型/数据治理能力 coverage 仍不完整
- `ppt-company-p0-08`
  - 原因：否定题会被旧资料远端接管，当前不能安全放给答案侧
- `ppt-company-p1-04`
  - 原因：感知/解析能力枚举仍缺完整 coverage
- `ppt-company-p1-05`
  - 原因：业务架构概括题仍属 `grounding_insufficient`
- `ppt-company-p1-07`
  - 原因：`1+1+N` 四项服务在正式 top 命中中仍不稳定完整覆盖

### 3. 后续正式回归必须补的题型或资产

- 题型必须补：
  - 目录/结构枚举题
  - 否定题与“未提及”题
  - 概括题/主线总结题
  - coverage 敏感的多项枚举题
  - 易被旧资料吸走的定位题/基础环境题
- 资产必须补：
  - 新增 PPT 的正式答案期望与引用期望
  - 旧资料最小回归集
  - 能区分 `route_conflict / grounding_insufficient / coverage_insufficient` 的正式评测标注口径
  - 新增 PPT 题集从“能力判断素材”升级为“正式验收集”所需的通过/失败判定说明

四、正式验收补件清单

### 1. 环境与入口补件

- `latest eval` 污染需要先处理
  - 当前 admin latest 视图会被残留 `running` evaluation job 污染，不能作为正式验收读取口
- `data/evals` 历史资产需要补齐或明确冻结策略
  - 当前工作树只剩 `ppt_company_p0_8.json`、`ppt_company_p1_8.json`
  - 历史正式评测集和结果资产缺失，不能直接复用既有回归入口
- 正式 eval 入口当前不可直接信任
  - `EVAL_API_BASE_URL=http://127.0.0.1:8000`，但 8000 当前未启动
  - 即使保留脱机直连能力，也仍需主线程明确本轮正式验收究竟走哪条入口

### 2. 数据与标注补件

- 新增 PPT 题集需要从“能力判断素材”升级成“正式验收集”
  - 补正式参考答案
  - 补引用/证据要求
  - 补每题的通过判定标准
- 旧资料最小回归集必须恢复
  - 至少覆盖每个旧文档 1 题
  - 至少保留旧 PPT 题
  - 至少保留 1 题 `expected_grounded=false`
- 对当前阻塞题，需要补“阻塞即通过”的口径
  - 例如否定题、route conflict 题、coverage 不足题，正式验收时不能简单按“答出来了”计正例

### 3. 答案侧补件

- 当前 4 道放行题的答案侧最小闭环结果已落盘，可直接作为能力判断层证据
- 正式验收阶段仍需补的不是“这 4 题是否收口”，而是：
  - 把事实题 / 枚举题 / 概括题的评分口径显式写进正式验收模板
  - 把“应拒答/应降级/应保持阻塞”的题型判定写进正式评测口径
  - 为阻塞题补“阻塞即符合当前能力边界”的判定规则

五、下一轮主线程可直接采用的评测口径建议

### 1. 分两层，不混写

- 第一层：能力判断层
  - 只面向新增 PPT 当前阶段
  - 只报告“可放行到答案侧的题”“必须阻塞的题”“阻塞原因分布”
  - 不给通过率
- 第二层：正式验收层
  - 前提是 `latest eval` 污染、历史资产、正式入口三件事都被澄清
  - 才允许计算新增 PPT 通过情况和旧资料回归结果

### 2. 正式验收前的最小设计建议

- 新增 PPT 单独成组，不并入旧总集直接算总通过率
- 至少分成 4 个评测桶：
  - 事实题
  - 枚举题
  - 概括题
  - 否定题
- 正式报告至少分 3 类失败原因：
  - `route_conflict`
  - `grounding_insufficient`
  - `coverage_insufficient`
- 对已完成答案侧最小闭环的 4 题，下一轮可直接作为“能力判断层已闭环样例”
- 对当前 9 道阻塞题，下一轮优先做“是否仍阻塞”的状态验证，而不是先追求提分

### 3. 主线程可直接引用的结论口径

- 当前可以说：
  - “新增 PPT 已形成能力判断层统一稿：其中 4 道题已在正式运行态下完成检索到答案的最小闭环，9 道题当前仍应阻塞；当前结果只能支持阶段性能力判断，不支持正式通过率验收。”
- 当前不应说：
  - “新增 PPT 已正式通过评测”
  - “当前通过率可直接计算”
  - “旧资料历史高通过率可代表新增 PPT 已通过”

六、当前判断
- `WS-04` 当前轮目标可以记为完成了“能力判断层统一稿 + 正式补件清单收口”
- 但这不是正式验收完成
- 本报告当前已可由主线程直接作为阶段收口材料采用

七、是否建议主线程放行到下一轮统一验收设计
- 建议是
- 放行前提不是“立即算通过率”，而是：
  - 先按本报告区分能力判断层与正式验收层
  - 认可这 4 道题已完成答案侧最小闭环
  - 再由主线程决定正式验收补件的恢复顺序

八、正式验收层最小模板草案

### 1. 模板产物位置

- 已新增正式验收层最小模板草案：
  - [docs/thread-eval-formal-acceptance-template.md](/data/zyq/yushu/docs/thread-eval-formal-acceptance-template.md)

### 2. 模板的核心结构

- `Header`
  - 记录验收轮次、执行入口类型、入口可信度、数据集清单、运行态说明
- `Gate Checklist`
  - 明确 `latest eval` 污染、数据集存在性、入口可信度、运行态一致性是否已解除
- `Acceptance Scope`
  - 把“新增 PPT 单组验收”和“旧资料最小回归”拆成两个独立范围
- `Per-Case Schema`
  - 为每题补 `expected_result_mode` 与 `blocking_is_correct_if_any`
- `Scoring Rules`
  - 分事实题、枚举题、概括题、否定题定义正式验收判定
- `Output Summary Block`
  - 区分“可答通过”“正确阻塞”“错误放行”“错误阻塞”
- `Blocking Record`
  - 若本轮不能执行正式验收，要求显式写出阻塞项与影响范围

### 3. 为什么当前模板要这样设计

- 当前新增 PPT 不只是“答对几题”的问题，还包含一类“继续阻塞才是正确边界”的题。
- 因此正式验收层不能只保留“通过 / 失败”二元结果，必须显式支持：
  - `must_answer`
  - `must_answer_compact`
  - `must_degrade`
  - `must_block`
- 这也是为了避免后续把 `route_conflict / grounding_insufficient / coverage_insufficient` 误写成“统一失败”，从而丢掉当前阶段已经确认的能力边界。

九、当前缺失补件与模板字段的对应关系

| 当前缺失补件 | 对应模板字段 | 解除前模板应如何填写 |
| --- | --- | --- |
| `latest eval` 被残留 `running` job 污染 | `Gate Checklist.latest eval`、`Blocking Record` | 标记 `blocked=false?` 不可，必须记为 `未解除 / latest_eval_polluted` |
| `data/evals` 历史资产缺失 | `Header.使用的数据集清单`、`Acceptance Scope.旧资料最小回归` | 明确写“回归集缺失/未冻结”，不得假设旧回归集可直接跑 |
| 正式 eval 入口当前不可直接信任 | `Header.执行入口类型`、`Header.当前入口可信度`、`Gate Checklist.当前入口是否可复跑` | 记为 `low` 或 `blocked`，不得写成 ready |
| 新增 PPT 正式参考答案与引用期望未完全补齐 | `Per-Case Schema.expected_answer_keywords`、`scoring_notes` | 只允许作为草案，不允许执行正式通过率计算 |
| 阻塞题“阻塞即正确”的判定口径未单独落模板 | `blocking_is_correct_if_any`、`Scoring Rules` | 当前模板已预留字段，但执行前仍需主线程确认逐题口径 |
| 旧资料最小回归集尚未恢复 | `Acceptance Scope.旧资料最小回归`、`Output Summary Block` | 当前只能留空或记 `not_ready`，不能并入总分 |
| 概括题正式通过标准仍偏保守 | `Scoring Rules.summary` | 当前应维持“证据不完整则正确阻塞”，不得擅自放宽 |

十、恢复后建议先跑哪一层

### 建议顺序

1. 先冻结 `data/evals` 当前新基线
2. 先跑“新增 PPT 单组正式验收”
3. 再决定是否补“旧资料最小回归”

### 原因

- 主线程已接受“先冻结后决策”，因此当前第一步不应是默认恢复旧 `data/evals` 资产，而应先冻结本轮正式验收实际要使用的范围与字段。
- 新增 PPT 是本阶段新增语料，也是当前所有能力判断与最小闭环的直接对象，证据链最完整。
- 现有 `p0/p1` 题集、retrieval 阻塞归因、answer 最小闭环都已经围绕新 PPT 成型，最适合先转成正式验收单组。
- 旧资料最小回归当前既受历史资产缺失影响，也更适合作为“新资料正式验收跑通后，确认未破坏旧能力”的第二层闸门。
- 如果在公共入口尚未完全恢复前就先跑旧资料回归，主线程更难分辨“新 PPT 未通过”与“历史入口未恢复”的边界。

十一、脱机直连 + 冻结后新基线的正式验收草案

### 1. 当前推荐执行口径

- 正式执行入口：
  - `offline_direct_eval`
- 当前采用该口径的前提：
  - `latest eval` 代码侧读数纠偏已完成
  - `EVAL_API_BASE_URL=http://127.0.0.1:8000` 对应 HTTP 入口当前仍不可用
  - `app/services/evaluation.py` 与 `scripts/run_eval.py` 仍保留脱机直连能力
- 因此当前主线程若要进入“最小正式单组验收执行”决策，应优先决策：
  - 是否接受脱机直连作为本轮正式执行入口
  - 是否接受“新增 PPT 单组正式验收优先，旧资料总回归后置”

### 2. `data/evals` 冻结后新基线下先必填哪些字段

- 在不恢复旧正式资产的前提下，当前建议先必填：
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
- 这些字段的目的不是直接算总通过率，而是先让“新增 PPT 单组正式验收”具备可冻结、可执行、可复核的最小数据契约。

### 3. 若当前不恢复旧正式资产，主线程应如何表述“正式验收范围”

- 当前推荐表述：
  - “本轮正式验收范围仅限新增 PPT 单组，在脱机直连入口下执行；旧资料最小回归暂不纳入本轮正式验收范围，待 `data/evals` 资产策略确认与回归集冻结后再单独启动。”
- 当前不推荐表述：
  - “正式总回归已恢复”
  - “当前正式通过率代表全库能力”
  - “旧资料正式验收已同步完成”

十二、新增 PPT 单组正式验收最小执行方案

### 1. 当前建议的最小执行方案

- 执行对象：
  - 仅新增 PPT 单组
- 执行入口：
  - `offline_direct_eval`
- 执行前动作：
  - 先冻结 `data/evals` 当前新基线
  - 只确认新增 PPT 单组正式验收集，不并入旧资料最小回归
  - 用最终冻结数据集显式覆盖 `scripts/run_eval.py` 默认 dataset 参数
- 执行后期望产物：
  - 单组正式验收结果
  - 不自动升级成总回归或正式总通过率

### 2. 需要先冻结的题集/字段清单

- 题集范围：
  - 当前仅冻结“新增 PPT 单组正式验收集”
  - 来源可基于 `ppt_company_p0_8.json` 与 `ppt_company_p1_8.json` 进一步裁成正式单组版本
- 冻结前先必填字段：
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

### 3. 执行前最后 gate checklist

- `latest eval` 代码侧纠偏结果仍有效
- 当前正式入口确定为 `offline_direct_eval`
- 当前不要求恢复 HTTP/admin 入口
- 当前不要求恢复旧 `data/evals` 正式资产
- 新增 PPT 单组正式验收集已冻结
- 本轮正式范围已明确写成“仅新增 PPT 单组”
- 当前不把旧资料最小回归并入本轮
- 当前不允许汇总正式通过率

### 4. 若主线程批准执行，推荐使用的最小命令/入口

```bash
./.venv/bin/python scripts/run_eval.py --dataset data/evals/<frozen_new_ppt_single_group>.json --output-dir data/evals/results
```

补充说明：

- 当前必须显式传 `--dataset`
- 不允许沿用默认 `data/evals/knowledge_base_eval_cases.json`
- 本轮只允许把结果解释为“新增 PPT 单组正式验收结果”

十三、给主线程的统一汇报

- 当前已完成的不是正式验收执行，而是“正式验收层最小模板设计”。
- 当前模板已经能被主线程直接采用，用来：
  - 明确正式验收执行前必须先过哪些 gate
  - 区分新增 PPT 单组验收与旧资料最小回归
  - 区分“可答通过”与“正确阻塞”
  - 在“先冻结后决策”的前提下，衔接到“脱机直连 + 新增 PPT 单组正式验收优先 + 冻结后新基线”的执行草案
  - 进入“单组正式执行前最后审阅”状态
- 当前仍不能做的事：
  - 不能宣布正式通过率
  - 不能把旧资料历史结果外推到新增 PPT
  - 不能绕过 `Thread-Infra` 已确认的入口与资产阻塞直接开跑
- 当前建议主线程对外口径：
  - “新增 PPT 的能力判断层统一稿已完成，正式验收层也已补成‘脱机直连 + 单组优先 + 冻结后新基线’的执行草案；但当前正式范围仍只建议覆盖新增 PPT 单组，旧资料总回归与正式通过率汇总仍待后续资产策略与入口范围决策。”

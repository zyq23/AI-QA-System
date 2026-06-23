# Codex Plan

## Project

- 项目：宇树科技知识库 AI 问答系统完善
- 协作模式：主线程 + 多专项线程
- 主线程角色：总计划维护、任务拆解、依赖协调、阶段验收
- 最后更新：2026-06-22

## Current Objective

当前阶段的主目标是：

在"新增 PPT 最小能力判断闭环"与"新增 PPT 单组正式验收首轮执行"都已完成的基础上，把系统推进到"可基于宇树科技知识库全部已入链文档稳定问答"的可用状态。当前默认采用"两阶段推进"：

1. 先快速收敛新增 PPT 单组正式验收中已经暴露的 3 道错误放行题。
2. 再把正式验收范围从"新增 PPT 单组"扩到"全知识库最小回归集"，确认全部已入链文档都具备最小可信问答能力。

在这两个动作完成前，不启动新的大范围架构重做，也不把当前小样本结果包装成"全库已经正式通过"。

### 2026-06-22 阶段结论

- 新增 PPT `13` 题 smoke gate 已达到 `4 / 9 / 0 / 0`（保住）
- 全知识库最小回归集已冻结为 `data/evals/full_kb_minimal_regression_v1.json`（27 题）
- 全知识库最小回归已执行，连续 3 次复跑均为 `answer_pass=12 / correct_block=15 / wrong_release=0 / wrong_block=0`
- 系统已正式达到"基于全部已入链文档最小可信问答"的可交付状态
- 27/27 题全部通过，无剩余已知失守点

## Why This Stage Matters

当前项目已经有可用底座，但真正影响后续价值的，不是再做一个新的问答壳，而是让新增资料，特别是公司介绍类 PPT，能被系统稳定接入、召回、引用并回答。

如果这个阶段没有做好，会出现以下问题：

- 新增文档只是放在知识库目录里，但实际无法问答
- 复杂 PPT 页面进入索引后噪声很大，召回质量不稳定
- 为了修新资料而破坏旧资料已有的高通过率
- 多线程同时推进时出现重复劳动、互相踩边界或无统一验收标准

## Success Criteria

本阶段完成的判定标准如下：

- 新增公司介绍 PPT 已进入正式问答链路，而不是仅存在于目录中
- 对新增资料的事实问答、枚举问答、概括问答至少具备可验证的基本可用性
- 复杂 PPT 的主要解析风险已明确，并形成可执行升级路线
- 检索、回答、评测三个方向都围绕新资料建立了最小闭环
- 历史可用能力没有被新改动明显破坏
- 线程协作机制已经稳定运行，后续工作可以按文档持续接力

## Current State Summary

### Confirmed System Capabilities

根据主线程审计，当前系统已经具备这些基础能力：

- `FastAPI` 服务与 Web 管理台
- 文档上传、目录导入、重建索引、停用文档
- `pdf / docx / pptx` 解析能力
- 本地 `SQLite FTS5 + ChromaDB + BGE reranker` 检索链路
- `RAGFlow` 作为可选增强或兜底检索后端
- 回答生成、回答质检、answer runs 留痕
- 验收脚本与评测结果落盘能力
- 机器人侧接口与桥接示例

### Confirmed Runtime State

截至本轮审计，主线程确认：

- 数据库中已有 6 份已入库文档
- 共有 12 个版本记录
- 当前 chunk 数量为 7050
- 当前 answer runs 数量为 1268
- 实际配置采用 `ragflow + local adaptive` 路线
- OCR 已启用
- 当前知识库目录共发现 7 个源文件，其中 1 个新增 PPT 尚未入库

### New Input In This Stage

当前阶段新增输入为：

- `宇树科技知识库/【公司介绍】轩辕网络公司介绍202606.pptx`

这个文件是本阶段的核心新增语料，需要作为所有专项线程的共同关注对象。

## Main Risks

当前已识别出的主要风险如下：

### R-01 新 PPT 尚未进入索引

虽然文件已经放入 `宇树科技知识库/`，但当前数据库中仍只有 6 份已入库资料，说明这份新增 PPT 尚未进入现有问答链路。

### R-02 复杂 PPT 解析质量不稳

现有 PPT 解析采用 `python-pptx + 图片 OCR` 路线，虽然能工作，但对图片页、阅读顺序、WMF、混排和表格等问题较敏感，已经在现有资料中出现 OCR 失败告警。

### R-03 检索规则复杂度偏高

现有检索侧已经有大量面向特定资料和问法的规则化扩展与打分逻辑，短期有效，长期维护成本较高。若继续在没有整理的前提下堆规则，系统会越来越难控。

### R-04 回归风险真实存在

项目历史评测对旧语料已经做到较高通过率，新资料接入若处理不当，可能破坏原有问答表现。

### R-05 环境与状态残留

当前工作区存在以下工程风险：

- `data/evals/*` 有一批删除状态
- 数据库里存在一条停留在 `running` 的 evaluation job
- `ragflow` 子模块在 Git 中存在，但工作区当前缺失

这些问题不一定立刻阻塞开发，但会影响后续排障、环境恢复和专项线程判断。

## Strategy

本阶段不做"大换血式重构"，而采取分层推进策略：

1. 先做新资料接入闭环，确认能入库、能检索、能回答。
2. 再做复杂 PPT 解析质量诊断，明确现有 parser 是否够用。
3. 再针对真实失败 case 优化检索、回答和回归评测。
4. 同步清理环境和状态风险，避免线程把环境问题误判为算法问题。

## Collaboration Enforcement

所有线程在本阶段推进过程中，除遵守 `AGENTS.md` 外，还应执行以下统一协作要求：

- 每一次代码修改都必须纳入 Git 版本管理，保证改动可追踪、可回滚、可审阅
- 主线程在验收专项线程产出时，需要同时检查对应改动是否已经进入 Git 管理范围
- 当前默认按 `6 个对话 = 1 个主线程 + 5 个专项线程` 运行，详细启动词与统一汇报机制见 `docs/codex-dialogs.md`
- 专项线程没有提交统一汇报格式时，主线程不得把"已完成"记入阶段验收

## Current Main-Thread Status

截至 2026-06-17 当前轮，主线程已完成以下关键动作：

- 已收到并复核 `Thread-Parser`、`Thread-Infra`、`Thread-Retrieval` 的统一汇报
- 已确认 `WS-01` 满足当前 parser pass 条件：
  - 带 OCR parse-only 全文可跑完
  - 关键高风险页已形成可点名抽查结果
  - 异常页清单与统一汇报已齐备
  - 正式运行态新增 PPT 已达到 `parser_status=completed / index_status=completed / chunk_count=1197`
- 已确认 `WS-05` 满足当前 infra pass 条件：
  - 环境残留已完成分级
  - 正式验收阻塞与"仅影响效率"项已拆开
  - 是否需要用户授权已明确
- 已确认 `WS-02` 完成当前轮"正式运行态最小复跑验收"：
  - 已基于正式 `retrieval_service` 复跑指定最小题集
  - 已收口 `allow_to_answer / blocked_with_reason / route_conflicts_still_present`
  - 已明确 `route-probe-p0-01` 仍属 direct conflict
- 已确认 `WS-03` 完成当前轮"答案侧最小闭环验收"：
  - 已消费正式运行态放行的 4 道题
  - 已修补事实题宣传性补句、枚举题混合总述、事实题过长 fallback 三类答案侧偏差
  - 已通过定点护栏测试 `5 passed`
  - 已收口"事实题 / 枚举题可放行，概括题仍不越权放开"的边界
- 已确认 `WS-05` 在"latest eval 代码侧纠偏"这一轮新增目标上也已完成：
  - latest eval 读取已切换到只取最新 `completed` evaluation job
  - 定点测试 `2 passed`
  - runtime 只读验证已确认 latest eval 不再命中残留 `running` job
- 已确认 `WS-04` 已完成"新增 PPT 单组正式验收首轮执行"：
  - 已冻结单组数据集 `data/evals/ppt_company_single_group_formal_v1.json`
  - 已通过 `offline_direct_eval` 完成首轮执行
  - 已形成正式模板口径二次归类结果：`可答通过=4 / 正确阻塞=6 / 错误放行=3 / 错误阻塞=0`
  - 当前 3 道错误放行题为 `ppt-company-p0-03 / ppt-company-p0-05 / ppt-company-p1-04`
- 已确认 `WS-02 / WS-03` 已分别完成"3 道错误放行题"的归因收口：
  - Retrieval 已明确三题分别失守于 `grounding_insufficient / route_conflict / coverage_insufficient`
  - Answer 已明确其中两题需要答案侧新增阻塞规则，另一题不应由答案侧兜底
- 已确认 `WS-04` 在新增目标"全知识库最小回归设计"上也已完成：
  - 已把当前 `13` 题单组正式验收固化为长期 smoke gate
  - 已补出覆盖全部 `7` 份已入链文档的全知识库最小回归方案
  - 当前建议下一轮最小正式范围为 `27` 题：新增 PPT `13` 题 + 旧资料 `14` 题
- 已确认 `WS-05` 在新增目标"全知识库最小回归执行前 checklist"上也已完成：
  - 已明确 `offline_direct_eval + .venv + 显式清空 EVAL_API_BASE_URL` 为短期正式入口
  - 已明确 HTTP/admin 未恢复不构成最小回归 blocker
  - 已明确当前真正 blocker 是"全知识库最小回归集文件尚未冻结落地"
- 已确认 `WS-04` 在"smoke gate formal 判分口径修复"上也已完成：
  - 上一轮 `0 / 3 / 6 / 4` 已确认为 formal 归类 bug，不再当作真实能力状态
  - 当前最新可信 smoke gate 分布已回正为 `4 / 7 / 2 / 0`
  - 当前真实未收敛题已缩小为 `ppt-company-p0-03` 与 `ppt-company-p1-04`
- 已确认 `WS-03` 在最新一轮"remaining wrong_release 最小收口"上也已完成：
  - `Thread-Answer` 已提交统一汇报 `docs/thread-answer-wrong-release-report.md`
  - 最新 smoke gate 结果已更新为 `4 / 8 / 1 / 0`
  - `ppt-company-p1-04` 与 `ppt-company-p0-06` 已从 `wrong_release` 收敛为 `correct_block`
  - 当前剩余唯一 `wrong_release` 为 `ppt-company-p0-03`
- 已确认当前工作树中的正式验收级公共阻塞仍未解除：
  - `data/evals/` 历史资产大面积删除
  - `EVAL_API_BASE_URL=http://127.0.0.1:8000` 对应服务当前未启动
  - `ragflow` 工作树仍是 gitlink / 映射失配

当前主线程判断：

- 能力判断层：
  - `Thread-Answer` 这轮最小实现已有效压回 `p1-04 / p0-06`
  - 当前新增 PPT smoke gate 的真实剩余问题已收缩到单题 `ppt-company-p0-03`
- 正式验收判断：
  - 基于最新正式结果文件 `data/evals/results/eval_20260622_103930_formal_summary.json`，当前 `13` 题 smoke gate 已达到快速放行阈值 `4 / 9 / 0 / 0`
  - 但 `Thread-Eval` 的统一汇报文本尚未更新到这一轮结果，因此线程级严格验收仍待补件
- 当前阶段最关键目标已从"新增 PPT 最小能力判断闭环"切换到"新增 PPT 首轮正式错误放行收敛 + 全知识库最小回归设计"
- `WS-01`：`pass`
- `WS-05`：`pass`
- `WS-02`：对当前轮目标记 `pass`
- `WS-03`：对当前轮"4 题最小闭环验收"记 `pass`
- `WS-04`：对当前轮"能力判断层统一稿 + 正式单组执行"记 `pass`，但全知识库正式回归仍未完成
- 下一阶段默认优先级：
  1. 先要求 `Thread-Eval` 用最新结果文件补齐统一汇报
  2. 再把全知识库最小回归方案冻结成实际数据文件
  3. 然后执行"全知识库最小回归集"
  4. 最后再决定是否进入更大范围提分或 HTTP/admin 恢复
- 正式验收扩面的当前固定顺序：
  1. 保持 `latest eval` completed 过滤结果稳定
  2. 保持短期正式 eval 入口走 `offline_direct_eval`
  3. 以当前 `13` 题单组正式集作为 smoke gate
  4. 新增旧资料最小回归集，覆盖所有已入链文档
  5. 单组通过后再汇总成"全知识库最小正式验收"
- 若用户优先追求"尽快可用"，主线程允许切换到"快速可用优先"推进法：
  1. 先把 `13` 题 smoke gate 收敛并用正式结果文件确认
  2. smoke gate 一旦达到 `4 / 9 / 0 / 0`，就把系统记为"新增 PPT 与当前已入链文档可进入全库最小回归阶段"
  3. 全知识库最小回归集的冻结与执行改为紧随其后，而不是在实现前继续扩设计
  4. HTTP/admin 恢复、`ragflow` 源码位恢复、历史大资产恢复继续后置

## Current Round Dispatch

### Thread-Parser

- 当前目标：保持已通过状态，仅支撑"错误放行题"中的 parser 边界复核与全知识库回归集的页级证据补充
- 输入依赖：`docs/thread-parser-report.md`、`docs/thread-parser-anomaly-list.md`
- 预期输出：如 `ppt-company-p0-03 / p1-04` 的阻塞边界仍需上游页证据说明，补只读说明；如旧资料最小回归需要 parser 风险备注，也只补证据
- 验收标准：不重复开新实现；不主动重启 parser 大改；能把"是不是 parser 问题"说清
- 禁止事项：不得主动扩 scope 到新的 parser 大改

### Thread-Infra

- 当前目标：保持 latest eval 读数纠偏结果稳定，并为"全知识库最小回归集"提供脱机执行入口与环境可信度口径
- 输入依赖：`docs/thread-infra-report.md`
- 预期输出：
  - 保持当前纠偏结果与脱机执行口径稳定
  - 如主线程要求，再补"全知识库最小回归集"执行前环境 checklist
- 验收标准：保持 latest eval 读数可信；保持 `offline_direct_eval` 可作为短期正式入口；不擅自扩大环境恢复范围
- 禁止事项：未经授权不得恢复子模块、恢复数据集、改写数据库状态；不得顺手扩成 HTTP/admin 全恢复

### Thread-Retrieval

- 当前目标：只围绕剩余唯一 `wrong_release = ppt-company-p0-03`，判断它是否仍属于 retrieval 侧应补的 grounded gate，还是已可直接交给 Answer/Eval 收口
- 输入依赖：`docs/thread-retrieval-report.md`
- 预期输出：仅针对 `ppt-company-p0-03` 给出统一复核：当前为什么仍会 `wrong_release`、最小修复应落 Retrieval 还是保持不动
- 验收标准：不重复跑无界大批量诊断；不提前扩成全题集提分；能明确告诉主线程 `p0-03` 下一步该由谁接
- 禁止事项：不得继续无界扩展诊断字段、题集或新特判

- 当前主线程验收结果：`pass`
- 最新主线程判断：`Thread-Retrieval` 已明确 `p0-03` 仍属 `grounding_insufficient`，但当前不建议继续由 Retrieval 修；下一步应回流给 `Thread-Answer`

### Thread-Answer

- 当前目标：只围绕剩余唯一 `wrong_release = ppt-company-p0-03`` 做单题回流复核，查清"现有业务架构概括题阻塞守卫为何未在最新正式 smoke gate 中生效"，并补最小修复
- 输入依赖：`docs/thread-answer-report.md`、`docs/thread-answer-minimal-eval.json`
- 预期输出：仅针对 `ppt-company-p0-03` 的统一汇报、最小代码修复、最小测试与是否建议交给 `Thread-Eval` 复跑
- 验收标准：不扩到别题；要明确解释为什么旧守卫未命中，并给出最新正式证据
- 禁止事项：不得重开 `p1-04 / p0-06 / p0-05`；不得自行扩到全题集提分

- 当前主线程验收结果：`pass`
- 最新主线程判断：`Thread-Answer` 已完成 `p0-03` 单题失效原因定位与最小修复，但尚未提供新的正式 smoke gate 结果；下一步应切到 `Thread-Eval` 复跑

### Thread-Eval

- 当前目标：保持当前 `13` 题 smoke gate 口径稳定，等待 `ppt-company-p0-03` 收敛后立即执行正式复跑；同时保持全知识库最小回归集冻结方案待命
- 输入依赖：
  - `docs/thread-infra-report.md`
  - `docs/thread-retrieval-report.md`
  - `docs/thread-answer-report.md`
  - `docs/thread-eval-report.md`
  - `docs/thread-eval-formal-acceptance-template.md`
  - `data/evals/ppt_company_single_group_formal_v1.json`
- 预期输出：
- 预期输出：
  - 保持当前单组 smoke gate 的执行和判读口径稳定
  - 在 `p0-03` 修后第一时间复跑并给出正式分布
  - 若达到 `4 / 9 / 0 / 0`，立即切换到"全知识库最小回归集执行"
- 验收标准：继续保持能力判断与正式验收边界清楚；不把 `4 / 8 / 1 / 0` 包装成通过；达到阈值前不外推全库通过
- 当前主线程最新派单：立即复跑当前冻结的 `13` 题 smoke gate，产出新的 `eval_<timestamp>.json` 与 `eval_<timestamp>_formal_summary.json`，并明确回答 `p0-03` 是否已从唯一 `wrong_release` 收敛
- 当前主线程最新验收判断：
  - 结果文件层面：`pass`
  - 严格线程收口层面：待 `docs/thread-eval-smoke-gate-rerun-report.md` 补到最新结果后再记 `pass`
- 禁止事项：不得宣布"全库正式通过率"；不得把历史旧评测结果直接并入当前总分

## Workstreams

### WS-01 文档接入与解析

- 目标：让新增公司介绍 PPT 正式进入可问答链路，并对复杂 PPT 的解析质量进行结构化审计。
- 范围：文件识别、解析、OCR、分块前质量检查、入库前后差异确认。
- 输入：`宇树科技知识库/【公司介绍】轩辕网络公司介绍202606.pptx`
- 输出：解析质量报告、入库方案、必要时的解析升级建议。
- 依赖：无，是所有后续工作流的上游。
- 优先级：P0
- 负责人线程：Thread-Parser
- 当前状态：`pass`
- 完成标志：新增 PPT 已被系统接纳为可检索语料，并明确其解析质量风险。

### WS-02 检索与召回

- 目标：基于新增 PPT 和现有知识库，验证并优化新资料问法的召回与引用质量。
- 范围：query rewrite、query expansion、本地检索、RAGFlow 检索、rerank、grounded 判定。
- 输入：WS-01 产出的结构化文本、chunk 结果和失败样例。
- 输出：检索失败类型、优化建议、必要时的规则收敛或改造方案。
- 依赖：强依赖 WS-01。
- 优先级：P1
- 负责人线程：Thread-Retrieval
- 当前状态：`pass`
- 完成标志：针对新增资料形成可复现的检索质量结论，并给出清晰优化方向。

### WS-03 答案生成与防幻觉

- 目标：确保公司介绍类问题能稳定输出简洁、可信、引用友好的答案，不把宣传性推断当事实。
- 范围：回答风格、回答长度、引用泄漏、摘要题与枚举题收口、防幻觉规则。
- 输入：WS-02 提供的高质量证据片段与失败样例。
- 输出：回答策略建议、风格约束、必要的风险样例清单。
- 依赖：依赖 WS-02 的有效证据基础。
- 优先级：P1
- 负责人线程：Thread-Answer
- 当前状态：`pass`
- 完成标志：新增资料上的回答风格和可信性规则明确，且能支撑后续实现与评测。

### WS-04 评测与回归

- 目标：围绕新增公司介绍 PPT 建立新增评测集，同时保留旧资料回归约束。
- 范围：评测集设计、case 分类、失败样例回收、回归集分层。
- 输入：WS-01/02/03 的阶段结论。
- 输出：新增评测样例建议、回归策略、关键指标定义。
- 依赖：依赖上游 workstreams 的阶段结果。
- 优先级：P1
- 负责人线程：Thread-Eval
- 当前状态：`pass`
- 完成标志：新增资料有专门测试入口，且不再只依赖旧语料评测。

### WS-05 工程环境与 RAGFlow

- 目标：排查和治理当前环境残留风险，确保后续各线程判断建立在可信环境上。
- 范围：RAGFlow 子模块状态、评测 job 状态、工作区遗留文件、运行时可恢复性。
- 输入：当前 Git 状态、数据库 job 状态、RAGFlow 目录现状。
- 输出：环境风险说明、恢复建议、阻塞级别判断。
- 依赖：无，但会影响所有线程推进效率。
- 优先级：P1
- 负责人线程：Thread-Infra
- 当前状态：`doing`
- 完成标志：关键环境问题被分类清楚，后续线程不再反复踩同一类坑。

## Recommended Execution Order

主线程给出的推荐推进顺序如下：

1. `WS-01 文档接入与解析`
2. `WS-05 工程环境与 RAGFlow`
3. `WS-02 检索与召回`
4. `WS-03 答案生成与防幻觉`
5. `WS-04 评测与回归`

原因：

- 没有可用的新资料结构化结果，后面所有线程都容易空转
- 环境风险如果不尽早澄清，后续结果容易误判
- 评测应建立在真实的解析与召回问题上，而不是先造一堆脱离现状的 case

## Dialog Assignment Matrix

当前 6 个对话与 workstream 的绑定关系如下：

- `Main-Thread`：总计划、派工、监听、验收、收口
- `Thread-Parser`：`WS-01 文档接入与解析`
- `Thread-Retrieval`：`WS-02 检索与召回`
- `Thread-Answer`：`WS-03 答案生成与防幻觉`
- `Thread-Eval`：`WS-04 评测与回归`
- `Thread-Infra`：`WS-05 工程环境与 RAGFlow`

主线程监听这些对话时，统一执行：

1. 先检查依赖是否满足
2. 再收统一汇报
3. 再做 `pass / revise / block` 三选一判定
4. 最后把结论同步回控制面文档

## Milestones

### M1 新资料入链路

- 确认新增 PPT 已被正式纳入系统
- 确认其解析和分块结果可被后续线程消费

### M2 解析风险定性

- 完成对复杂 PPT 主要风险的证据化诊断
- 给出现有 parser 是否继续使用的判断依据

### M3 新资料问答最小闭环

- 能回答新增资料上的基本事实题和枚举题
- 能提供可用引用

### M4 新旧语料双重验收

- 新资料有专门评测入口
- 旧资料能力没有被明显破坏

### M5 协作机制稳定运行

- 各线程按文档接力
- 阻塞、决策和阶段结论不再只存在于聊天中

## Dependency Notes

- `WS-02` 强依赖 `WS-01`
- `WS-03` 强依赖 `WS-02`
- `WS-04` 依赖 `WS-01/02/03` 的阶段产物
- `WS-05` 虽然技术上独立，但建议尽早推进，以减少误判和无效调试

## Explicit Non-Goals For This Stage

当前阶段不以以下事项为主要目标：

- 全量重构整个系统架构
- 一次性引入多种新模型并全面替换现有链路
- 在没有新资料闭环之前直接做大规模 UI 改造
- 先上跨文档图谱化高级能力再回头解决基础解析问题

## Advanced Options To Revisit Later

以下路线被认为值得关注，但不应抢占当前主目标：

- 面向复杂文档的更强结构化解析器，例如 MinerU 路线
- 更强的晚交互检索或多向量检索，用于困难问法召回
- 面向跨页总结与跨文档综述的图谱化或分层检索增强

这些方向仅在当前阶段问题被证据化后，再进入正式决策。

## Main Thread Review Checklist

主线程每轮检查时，至少逐项确认：

- 当前阶段目标是否仍然清晰
- 各线程输入输出是否仍然明确
- 是否出现新的跨线程阻塞
- 是否有结论应该沉淀到 `docs/codex-decisions.md`
- 是否需要调整 workstream 优先级
- 是否需要补新增资料的专门评测入口

## Current Main Thread Instructions

当前主线程的直接任务不是马上修改问答代码，而是：

- 搭建稳定协作文档体系
- 锁定阶段目标与依赖
- 让各专项线程在同一上下文下推进
- 为后续真正的实现和优化提供统一监督框架

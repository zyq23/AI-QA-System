# Next Round Brief：企业级 RAG + Agent 加固（2026-09-13 双轨接力版 · 修订）

> 新窗口接入点。先读本文件，再读 `AGENTS.md`、`docs/codex-handoff.md`（Quality-Upgrade 阶段 5/6 + 2026-09-13 审查区块）、`docs/codex-decisions.md`（D-032~D-040 + D-041 双轨门禁）、`docs/agent-architecture.md`。冲突时按 `AGENTS.md > decisions > plan > handoff` 优先级。**历史阶段报告已归档至 `docs/archive/`；`docs/codex-plan.md` 主体为 6 月旧计划，当前状态以 `handoff` + 本文件为准。**
>
> 本文件 2026-09-13 起采用**双轨制**：质量轨（答得准、不编造）与生产轨（可运维、可审计、可上线）必须都过关，项目才允许称为"企业级工程化落地"。任何一轨未达标，对外口径只能是"单机/内网验证态"。

## 0. 计划审查结论（为什么修订本文件）

上一版 brief 的质量主线（claim-evidence matrix、否定/数值/OCR 收口、Agent 证据契约）方向正确，予以保留。但对照"企业级工程化落地"目标，原版存在结构性缺口：只规划了**答案质量**一个维度，未覆盖生产就绪所必需的安全、可靠性、可观测性、数据治理、成本、部署与灾备。经全项目审查（2026-09-13），确认：

- 质量现状：**未达标**。hard 集 accuracy=0.7246（目标 ≥0.90）、hallucination=0.1462（目标 ≤0.05）、wrong_release=19；79 题 FROZEN wrong_release=4（门槛 ≤3，**已越线**）。
- 生产现状：系统具备完整的单机问答与评测骨架，但缺少健康探针、结构化日志、指标端点、鉴权覆盖（robot/agent 接口无认证）、可靠后台任务（FastAPI BackgroundTasks 崩溃即丢）、schema migration、备份恢复流程、生产部署配置（README 仍指导 `--reload`）、默认凭据强校验（`ADMIN_TOKEN=change-me` 可被带到生产）。
- 结论：**计划符合质量方向但不符合"企业级"完整要求**，本版按双轨制扩写，并给出逐阶段验收门禁。

## 1. 现状一句话

RAG 检索层已达标（Recall@3=0.857 / Recall@5=0.886 / Recall@10=0.943 / MRR=0.758，无答案拒答率 1.0），但**答案层未达标**：hard 集准确率 0.725（目标 ≥0.90）、幻觉率 0.146（目标 ≤0.05）。Agent 骨架已跑通但准确率仍低于单轮（旧基线 0.515 vs 0.638，且本窗口无新 Agent 结果），需真正提升而非包装。生产轨 P0 项（鉴权/探针/可靠任务/迁移/部署基线）未启动，当前系统定性为**单机/内网验证态**。最新实测以本机 Ollama `qwen2.5:14b` 为准（见 §6），DashScope 复测更差（accuracy 0.595 / hallucination 0.246 / refusal 0.88），不作为最优基线。

## 2. 不可回退事实（质量与环境不变量）

- 模型：本机 Ollama `qwen2.5:14b`（`http://127.0.0.1:11434/v1`）。DashScope 账户欠费（Arrearage），恢复前不得假设远端模型可用，也不要把欠费误判为算法结果。
- 79 题回归护栏：最新 FROZEN wrong_release=4、GEN answer_pass=25；WR 已超过 ≤3 门槛，不能写成"未回退/达标"，必须在后续修复中压回 ≤3。
- 检索/答案关键路径：FTS(SQLite, jieba 词级+单字回并+文档名 token)、Chroma+BGE、RRF+Rerank、多查询分解+文档轮转合并、`config/retrieval_rules.json` 数据驱动规则、draft→review→finalize 反幻觉守卫。
- 评测必须 `RETRIEVAL_BACKEND=local`；`EVAL_API_BASE_URL` 必须清空（否则打到无关服务）。RAGFlow 仅现象记录（D-034），禁止当能力证据。
- 禁止：重建独立 RAG、删 finalize 守卫、加题目 ID 特判、为提指标放松 grounded、把 raw OCR / raw tool observation 当答案、无界 ReAct、跳过 git 提交、**为过线而修改判分口径**（判分口径变更必须走 D-级决策 + 人工抽样证据，见 §4 质量轨 M-Q5）。

## 3. 主要差距与方向（证据驱动，先诊断后改）

### 3.1 质量轨（M-Q 系列）

1. **M-Q1 多部分答案只收一侧**：`A 和 B 分别是什么` 只答一个主体 → 建 claim-evidence matrix：每个 claim 含 subject/attribute/value/citation_file/citation_page/matched_keywords/confidence，全部核心 claim 有证据才放行；每缺一必选项就降级或显式标注"X 未在资料中提及"，不得伪装完整回答。当前实现入口：`app/services/claim_matrix.py` + `llm.py::finalize_answer` matrix gate（约 2894-2943 行）。
2. **M-Q2 否定题**：区分 `以下哪项不是 / 除了X还 / 是否支持`；校验被排除实体、要求项、选项极性、citation claim 极性（`_compose_negative_exclusion_answer` 已有雏形，需扩展到全部否定形态）。
3. **M-Q3 数值陷阱**：目标数值须与证据精确匹配，近似值不算通过；question echo 不算回答；数值 claim 必须挂 citation（`_answer_misses_questioned_precision` 已覆盖部分场景）。
4. **M-Q4 OCR/长上下文误杀**：hard 集 wrong_block 36 题中 ocr_noise_page=11、long_context_distraction=7、multi_hop=7 为大头——`_looks_like_garbled_ocr` 与长上下文抽取把可答题误杀。保留 OCR 块与质量标记，收紧乱码判定为"信号组合"而非单一特征；命中关键词≠直接放行，同样进 matrix。
5. **M-Q5 判分有效性审计（新增）**：当前 accuracy/hallucination 全部为规则判分（`expected_answer_keywords` 严格子串包含 + expected_files 包含 + grounded 标志），无 LLM 判分。已知失真：handoff 2026-09-12 诚实记录"部分 wrong_release 实为'答案语义正确但未命中严格子串'（如 `两套。` vs 期望 `两套视觉系统`）"。**处理原则**：先对 wrong_release/wrong_block 各桶做 ≥20% 人工抽样复核，量化"判分假阴性"占比；若确属口径过严，提出同义归一方案并走决策记录（D-级）后才允许改 `run_rag_metrics.py`；若属答案真缺，回到 M-Q1~M-Q4 修能力。**禁止不经抽样就改判分**。
6. **M-Q6 答案生成层剩余瓶颈**：hard-cross-05/07 类"主体证据缺失"需要 `claim_matrix._CLAIM_VALUE_PATTERNS` 补通用 value pattern 与 alias；禁止逐题 hardcode。

### 3.2 生产轨（M-P 系列，2026-09-13 审查新增）

7. **M-P1 Agent 证据契约**（P0 正确性，跨双轨）：
   - `app/agent/tools.py::_serialize_hits` 每条 evidence 至少含 `file_name/page_or_slide/section_path/chunk_id/plain_text/score/ocr_quality`，当前丢 chunk_id/完整文本/OCR 质量。
   - `MultiDocCompareTool` payload 仅 `{sides}`，无顶层 `grounded/hits`，而 `controller.py` 只认顶层字段 → 对比题永不被 terminal/grounded 识别，citations 为空。需输出结构化 comparison（每 side claims+citations、missing_fields 显式）。
   - Agent 终答未形成/持久化 claim matrix、未回填 `answer_run_id`；`controller._pipeline_citations` 为共享实例状态，并发请求会串证据 → 必须改为请求级局部上下文。
   - calculator/date 工具结果未进入终答证据链（`_compose_final_answer` 重新走 `chat_service.answer` 独立检索）；确定性工具输出应作为 typed evidence 提交 finalize。
   - `_compose_final_answer` 调 `chat_service.answer` 不传 conversation_id，会新建会话并二次写 messages，造成上下文污染。
8. **M-P2 Agent 执行边界**：45s"硬上限"实际只在工具调用间隙检查，工具内部阻塞不可中断 → 需 per-tool deadline + 可取消执行器；终态需区分 `completed/clarification/no_answer/timeout/step_budget/exhausted_error`；replan 计划只校验工具名不校验参数 schema → 初始计划与 replan 统一走同一 JSON Schema/Pydantic 验证器。
9. **M-P3 鉴权与会话归属**：`/api/agent/query`、`/api/robot/query` 无认证，任意 `conversation_id` 可读他人会话；生产上线前必须收口（服务 token / 设备密钥 + 签名 + 时间戳防重放 + 会话属主校验）。Robot 路由还需接限流。
10. **M-P4 生产运行基线**：`/live`、`/ready`（SQLite/Chroma/模型在位）、`/healthz` 探针；统一异常处理 + 错误码 + request-id 贯穿日志/job/answer_run；启动时拒绝 `ADMIN_TOKEN=change-me` / 弱 `SECRET_KEY`；生产启动方式去 `--reload`。
11. **M-P5 数据与任务可靠性**：schema migration 机制（当前 `CREATE TABLE IF NOT EXISTS` 无法演进）；ingestion/reindex/eval 后台任务幂等（同文档单 active job、重复提交抑制）；jobs 表补 `attempt/heartbeat/owner/cancelled`；SQLite+Chroma+uploads 配对备份与恢复脚本 + 一次恢复演练。
12. **M-P6 可观测性与成本**：Prometheus `/metrics`（QPS、P95/P99、4xx/5xx/429、fallback 率、LLM/检索分阶段延迟、job 积压年龄、Agent 步数/工具失败率）；`answer_runs` 记 token 用量（当前无）；结构化 JSON 日志 + 敏感字段脱敏（Prompt/文档原文/轨迹）。

### 3.3 路由（保持）

简单 factoid→快速路径；对比→multi_doc_compare；明确文档/页码→document_detail；数学/日期→calculator/date_utils；意图不明→clarification；无证据→no_answer。低置信现走 `no_answer` 而非 clarification 的语义不一致要修正（或改代码或改文档，见 §7 文档债）。

## 4. 企业级达标线（发布门禁矩阵，全部满足才称"企业级"）

> 当前值来源：`rag_metrics_20260912_151042.json`、`eval_20260912_155138_formal_summary.json`、代码审查。**"未测量"不等于达标。**

### 门禁 G-Q：质量（hard 130 + 79 回归 + Agent）

| 指标 | 目标 | 当前 | 状态 |
|---|---|---|---|
| hard Recall@5 / @10 / MRR | ≥0.85 / ≥0.92 / 跟踪 | 0.886 / 0.943 / 0.758 | ✅ |
| hard accuracy | ≥0.90 | 0.7246 | ❌ 差 0.18 |
| hard hallucination | ≤0.05 | 0.1462（WR=19） | ❌ |
| hard correct refusal | ≥0.95 | 1.0 | ✅ |
| 79 FROZEN WR / GEN answer_pass | ≤3 / ≥20 | 4 / 25 | ❌ WR 越线 |
| Agent routed 复杂题准确率 | ≥单轮，且每 claim 有 citation | 无本窗口新结果（旧 0.515<0.638） | ❌ 未验证 |
| 判分有效性抽样复核一致率（M-Q5） | ≥0.9（人工 vs 规则） | 未执行 | ❌ 未测量 |

### 门禁 G-R：服务可靠性（需先建指标，才有证据）

| 指标 | 目标 | 当前 |
|---|---|---|
| API 可用性（月度） | ≥99.5% | 未测量（无指标端点） |
| chat P95 / P99 延迟 | ≤8s / ≤15s（本机模型下基线 avg 8.5s，须实测分位数） | 未测量 |
| 5xx 比例 | ≤0.1%；下游故障降级可见率 100% | 未测量 |
| 请求端到端 deadline 传播 | 全链路支持 | ❌ 无 |

### 门禁 G-T：异步任务与索引

| 指标 | 目标 | 当前 |
|---|---|---|
| 任务成功率 / 崩溃后可恢复 | ≥99% / lease+retry+dead-letter | ❌ BackgroundTasks 崩溃即丢 |
| 同文档重复 active job | =0（幂等） | ❌ 无 |
| SQLite/Chroma/业务计数一致性 | 自动校验脚本，偏差=0 | 手动脚本具备，无门禁化 |
| 索引新鲜度（入库→可检索） | P95 ≤10min | 未测量 |

### 门禁 G-S：安全

| 项 | 目标 | 当前 |
|---|---|---|
| 默认凭据（change-me/弱 secret） | 生产启动即拒绝 | ❌ 可带病启动 |
| robot/agent/chat 接口鉴权 | 全部认证 + 防重放 + 限流 | ❌ robot/agent 无认证 |
| 会话/轨迹属主隔离 | 不可枚举读取 | ❌ conversation_id 即可读 |
| 管理端 Cookie `secure` + CSRF | 启用 | ❌ 缺 secure，无 CSRF token |
| 提示注入防护（不可信文档/用户输入） | 有测试锁 | ❌ 无 |
| 审计日志（谁改库/跑评测/删文档） | 落库可查 | ❌ 无 |

### 门禁 G-O：可观测性与运维

| 项 | 目标 | 当前 |
|---|---|---|
| /live /ready /healthz | 存在且接编排 | ❌ 无 |
| /metrics（Prometheus）+ 告警 | 覆盖请求/依赖/任务/成本 | ❌ 无 |
| 结构化 JSON 日志 + request-id + 脱敏 | 全链路 | ❌ 零散 logger |
| trace（HTTP→检索→LLM→DB） | OTel 或最小 span | ❌ 无 |
| runbook（故障处置/恢复） | 仓库内文档 | ❌ 无 |

### 门禁 G-D：数据保护与部署

| 项 | 目标 | 当前 |
|---|---|---|
| RPO / RTO | 定义 ≤24h / ≤4h，且演练达标 | ❌ 未定义、无脚本 |
| 备份（DB+Chroma+uploads 配对） | 自动/可校验 | 仅一次手工产物 |
| 恢复演练 | 每季度一次，有记录 | ❌ 无 |
| schema migration | 版本化、可回滚 | ❌ 内嵌 SQL |
| 生产部署物（Dockerfile 或 systemd 之一） | 存在且文档化 | ❌ 仅 `--reload` 指导 |
| CI 门禁 | pytest+lint+安全扫描+评测回归 | 仅 stub-pytest |

### 门禁 G-C：成本与容量（P1，不阻塞首版上线但阻塞"企业级"宣称）

| 项 | 目标 | 当前 |
|---|---|---|
| token/请求 计量与日报 | 有 | ❌ |
| 单实例容量（并发问答） | 压测出数 | ❌ |
| 缓存命中（embedding/rerank LruCache） | 有指标 | 有缓存无指标 |

## 5. 阶段计划与每轮动作

### Phase 0（本窗口已做）：基线冻结

- 基线 commit `42e69c7`；hard 指标文件 `rag_metrics_20260912_151042.json`（sha256 `3bcb4083…`，**工作树未跟踪，下一窗口必须补提交**）；79 题 `eval_20260912_155138_formal_summary.json`（sha256 `2c1b1384…`）。
- Agent 无当前基线 → Phase 1 第一轮强制产出新 Agent routed/forced 结果后才允许引用 Agent 数字。

### Phase 1：质量 P0 + Agent 契约（M-Q1~Q4、M-P1~P2）

1. Agent 证据契约修复（工具全字段、MultiDoc 顶层 grounded、请求级 citations 隔离、answer_run_id 回填、工具结果进 finalize）。
2. 多部分/否定/数值/OCR 答案收口（matrix 通用 pattern，禁题面特判）。
3. 每轮按 §5.执行序全跑并落盘。

### Phase 2：判分有效性 + 剩余桶（M-Q5、M-Q6）

1. WR/WB 分桶人工抽样 ≥20%，量化判分失真；结论进 D-级决策。
2. 按抽样结论：修能力（回 Phase 1 手段）或修口径（需决策）。
3. 目标：hard accuracy ≥0.85（窗口内台阶）、79 WR ≤3 恢复。

### Phase 3：生产 P0（M-P3~P5）

安全启动校验、三接口鉴权+限流、健康探针、统一异常/request-id、migration 机制、后台任务幂等+租约、备份恢复脚本+演练记录、生产启动方式（Dockerfile 或 systemd）+ README 纠偏。**G-Q 未达标前可与 Phase 1/2 并行推进（无共同文件冲突的模块先行）。**

### Phase 4：生产 P1（M-P6、CI/CD）

/metrics+告警、结构化日志+脱敏、CI 扩展（lint、依赖扫描、migration/探针/恢复 smoke）、token 计量、并发压测出容量数。

### Phase 5：发布候选验收

- 对 §4 全部矩阵重测并回填"当前值"；任何 ❌ 项必须显式写"未达标/原因/证据/下一窗口方向"。
- 只有 G-Q、G-R、G-T、G-S、G-O、G-D 全绿，才允许把 AGENTS.md 状态改为"企业级生产就绪"。

### 执行序（每个改动窗口全跑，结果落盘 + handoff 追加）

```bash
# 1 单测（mock LLM，不依赖网络/模型）
EVAL_API_BASE_URL= USE_STUB_ML=true DISABLE_LLM=true ./.venv/bin/pytest tests/ -q

# 2 hard 集全链路 RAG 指标
EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python scripts/run_rag_metrics.py \
  --dataset data/evals/hard_eval_v1.json --output-dir data/evals/results --top-k 10

# 3 79 题回归（护栏）
EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python scripts/run_eval.py \
  --dataset data/evals/kb_quality_full_v1.json --output-dir data/evals/results

# 4 Agent routed 评测
EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python scripts/run_agent_eval.py \
  --dataset data/evals/hard_eval_v1.json --output-dir data/evals/results

# 5 Agent forced 压力评测
EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python scripts/run_agent_eval.py \
  --dataset data/evals/hard_eval_v1.json --output-dir data/evals/results --force-agent

# 6 生产面验收（Phase 3 起）：pytest 覆盖探针/鉴权/幂等/migration；恢复演练脚本干跑
```

每轮在 `docs/codex-handoff.md` 追加：改动、指标变化、WR/WB 变化、79 题是否回退、Agent vs 单轮、阻塞、下一步；结果文件与 commit 关联（记录 commit sha + 文件 sha256）。形成稳定架构决策时更新 `docs/codex-decisions.md`（D-041 起），并补 pytest 覆盖（matrix/对比/否定/数值/OCR/工具完整性/兜底/落库/API 轨迹/鉴权/探针/幂等/恢复）。

## 6. 结果文件索引（2026-09-13 更新）

- hard 集：`data/evals/hard_eval_v1.json`（130 题，8 桶，builder 逐条 DB 验证）
- **最新 RAG 指标（工作树实测，待提交）**：`data/evals/results/rag_metrics_20260912_151042.json`（answer_pass=50 / correct_block=25 / wrong_release=19 / wrong_block=36；accuracy=0.7246 / hallucination=0.1462 / refusal=1.0；R@5=.8857 / R@10=.9429 / MRR=.7575）。分桶短板：WR 集中在 synonym_rewrite=5、cross_document=5、multi_hop=4；WB 集中在 ocr_noise_page=11、long_context_distraction=7、multi_hop=7。
- 79 回归最新 formal summary（工作树实测，待提交）：`data/evals/results/eval_20260912_155138_formal_summary.json`（answer_pass=36 / correct_block=18 / wrong_release=4 / wrong_block=21）。旧的 `eval_20260912_043949` WR=3 已被取代。
- Agent 评测历史（仅历史参考，禁止当当前基线）：`agent_eval_20260911_053027.json`（routed）/ `051423.json`（forced）。
- 检索迭代轨迹：`data/evals/results/retrieval_local_only_r*.json`
- 规则表：`config/retrieval_rules.json`；Agent 架构说明：`docs/agent-architecture.md`（含待修订文档债，见 §7）

## 7. 文档与已知不一致债（Phase 1-3 顺手清偿，不新开大改）

- `docs/agent-architecture.md` 声称与代码不符项：timeout"硬上限"实为间隙检查；低置信规则路径实际产出 `no_answer` 而非 clarification；`agent_steps.thought` 恒空；"112+ pytest"计数过期；MultiDoc 证据收口未实现。→ 修代码时同步改文档，禁止只改文档掩盖。
- `README.md` 仍指导 `--reload` 与 `/admin?token=`（query token 已移除，D-037）→ Phase 3 部署基线时一并纠偏。
- `docs/codex-plan.md` 主体为 6 月旧计划，仅保留历史语境；workstream 新绑定的正式登记见 D-041。

## 8. 未达标项强制表述模板

任何对外汇报、AGENTS.md 更新、验收结论，未达标项必须按四件套写：**未达标 / 原因 / 证据文件 / 下一轮方向**。禁止提前宣布完成；禁止用"评测口径特殊"包装真实能力缺口，也禁止用"能力已提升"包装判分假阴性——两类都必须走 M-Q5 抽样裁决。

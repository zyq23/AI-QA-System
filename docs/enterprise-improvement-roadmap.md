# 企业级 RAG + Agent 产品化改进路线图

> 版本：v1.0（2026-09-14）  
> 适用分支：`quality-upgrade`  
> 本文是当前阶段的**执行级产品与工程计划**，用于承接 `docs/next-round-brief.md` 的双轨门禁。它不代表项目已经达标；任何“已完成”必须以代码、测试、评测结果和运行证据共同确认。

## 1. 产品定位与发布结论

### 1.1 产品定位

本项目是面向企业内部知识资产的可引用问答平台，核心价值不是通用聊天，而是：

1. 多格式企业文档接入（PDF/DOCX/PPTX/图片/OCR）；
2. 基于本地知识库的可追溯检索与回答；
3. 对复杂问题进行多步规划和证据聚合；
4. 每个核心主张都能回溯到文档、页码/幻灯片和文本块；
5. 具备评测、回归、审计、机器人接入和生产运维能力。

### 1.2 当前发布结论

当前只能发布为：

> **企业内测 / 单机验证版，不是企业级生产就绪版。**

禁止使用“已达到企业级”“可直接对外上线”“Agent 已达到生产标准”等表述。原因是质量轨和生产轨均有未通过门禁。

## 2. 当前事实基线（不可混用旧结果）

### 2.1 质量结果

证据文件：

- `data/evals/results/rag_metrics_20260914_013156.json`
- `data/evals/results/eval_20260914_013928_formal_summary.json`
- `data/evals/results/agent_eval_20260914_024914.json`
- `data/evals/results/agent_eval_20260914_031145.json`

| 链路 | 当前结果 | 目标 | 判断 |
|---|---:|---:|---|
| 单轮 hard accuracy | 0.7324 | ≥0.90 | 未达标 |
| 单轮 hard hallucination | 0.1462 | ≤0.05 | 未达标 |
| 单轮 hard wrong_release | 19 | ≤5（最终目标） | 未达标 |
| 单轮 Recall@5 | 0.8857 | ≥0.85 | 达标 |
| 单轮 Recall@10 | 0.9429 | ≥0.92 | 达标 |
| 单轮 correct refusal | 1.0 | ≥0.95 | 达标 |
| 79 题 FROZEN wrong_release | 3 | ≤3 | 达到护栏上限，不能继续回退 |
| 79 题 `kb_quality` answer_pass | 25/52 | 持续提升 | 未达标但不以 pass_rate 单独作为语义质量结论 |
| 79 题新增 PPT answer_pass | 4/13 | 继续提升 | 未达标 |
| Agent routed accuracy | 0.6825 | ≥单轮且 ≥0.90 | 未达标 |
| Agent forced accuracy | 0.6786 | ≥单轮且 ≥0.90 | 未达标 |
| Agent routed correct refusal | 0.88 | ≥0.95 | 未达标 |
| Agent forced correct refusal | 1.0 | ≥0.95 | 达标 |
| Agent citation provenance | 818/818 | 100% | 达标（报告已保留字段） |

### 2.2 单轮 hard 桶诊断

| 桶 | 总题数 | wrong_release | wrong_block | 产品判断 |
|---|---:|---:|---:|---|
| cross_document | 15 | 4 | 4 | P0：多主体主张矩阵与证据配对 |
| multi_hop | 15 | 5 | 6 | P0：多跳证据链与中间结论 |
| synonym_rewrite | 15 | 5 | 6 | P0：同义改写归一与主题保持 |
| ocr_noise_page | 15 | 2 | 11 | P0：OCR 信号组合和误杀降低 |
| long_context_distraction | 15 | 1 | 7 | P0：长上下文证据选择与干扰隔离 |
| numeric_trap | 15 | 2 | 0 | P1：精确值与近似值隔离 |
| negative_exclusion | 15 | 0 | 0 | 当前稳定，禁止无证据放宽 |
| no_answer | 25 | 0 | 0 | 当前稳定，作为安全护栏 |

### 2.3 生产工程事实

已具备：

- `/live`、`/ready`、`/healthz`；
- 默认凭据生产模式拒绝（`ADMIN_TOKEN`/`SECRET_KEY`）；
- Agent Evidence contract；
- SQLite schema migrations v1/v2；
- jobs 的 attempt/owner/heartbeat/cancelled 基础字段和 repository 测试；
- 159 个 pytest 通过（包含迁移/可靠任务测试）。

仍未闭环：

- Agent/Robot API 身份认证、会话/租户归属和防重放；
- migration 的 CI/发布接入与回滚策略；
- worker 真正接管 BackgroundTasks；
- retry/dead-letter/cancel 在实际 ingestion/evaluation 流程中生效；
- 自动备份、恢复脚本、RPO/RTO 和恢复演练；
- `/metrics`、request-id、结构化日志、trace、告警；
- Docker/systemd/Kubernetes 生产启动基线；
- token/cost 计量、容量压测和 CI 安全门禁。

## 3. 总体策略：两条轨道、四个闸门

### 3.1 质量轨 Q

目标：降低错误放行和误阻塞，提升复杂问题的完整答案率。

原则：

- 先保证每个核心主张有证据，再追求更高 answer_pass；
- 不放松 `grounded`、claim、value、yes/no、OCR 守卫换指标；
- 不增加题目 ID 特判；
- 判分口径变更必须先完成每个主要桶 ≥20% 人工抽样并记录 D 级决策；
- 任何改动都必须跑 hard、79、Agent routed/forced。

### 3.2 生产轨 P

目标：让系统可认证、可恢复、可观测、可审计、可部署。

原则：

- 单机 SQLite/Chroma 是当前验证边界，不伪装成多副本生产架构；
- BackgroundTasks 只能作为过渡适配器，最终执行必须进入持久化 job worker；
- 所有生产配置必须显式，默认密钥不得启动；
- 没有恢复演练记录，不算“有备份”；
- 没有 SLO 实测数据，不算“高可用”。

### 3.3 发布闸门

| 闸门 | 必须满足 |
|---|---|
| Q-Gate | hard accuracy/hallucination、79 护栏、Agent 复杂题质量、每主张引用 |
| S-Gate | API/Robot/Agent 鉴权、会话归属、默认凭据拒绝、CSRF/防重放、审计 |
| R-Gate | worker、lease、retry、dead-letter、幂等、取消、崩溃恢复 |
| O-Gate | health、metrics、日志、trace、告警、request-id、SLO |
| D-Gate | migration、备份、恢复、RPO/RTO、一致性校验 |
| Deploy-Gate | 正式启动物、资源限制、优雅退出、持久卷、回滚和 CI |

任一闸门未通过，发布级别最高为“企业内测”。

## 4. 分阶段执行计划

## Phase 3A：数据库迁移与任务可靠性基础（当前优先级 P0）

### 目标

把已经写入 repository 的可靠任务能力接入正式状态机，并完成 schema migration 的可发布化。

### 任务 3A-1：迁移系统收口

**输入：** `app/migrations.py`、`scripts/migrate.py`、`app/db.py`。  
**动作：**

- 将 migration status/up 纳入 CI smoke；
- 生产启动前执行 `migrate up`，应用只读当前 schema；
- 添加 migration checksum/name 校验，避免已发布 migration 被静默修改；
- 明确向前兼容策略：应用先兼容旧字段，再执行迁移，再启用新字段；
- 明确不可逆迁移的备份前置条件；
- 将现有 live DB 备份和迁移日志落盘。

**验收：**

- 新数据库从 v0 迁移至最新版本；
- 旧数据库保留 documents/chunks/jobs/answer_runs 数据；
- 迁移中途失败时 user_version 不前进；
- 二次执行幂等；
- CI 运行 migration smoke；
- 迁移状态可通过命令查看。

### 任务 3A-2：可靠 job worker

**动作：**

1. 新增 `app/services/job_worker.py`，实现：
   - `claim_job(owner)`；
   - heartbeat 定时更新；
   - 任务 deadline；
   - 有限指数退避；
   - retry_count/max_attempts；
   - dead-letter（`failed` + failure_code）；
   - cancel 检查；
   - graceful shutdown。
2. 将 `ingest_document`、`reindex_document`、`evaluation`、RAGFlow sync 统一注册为 job handler；
3. HTTP 层只负责创建幂等 job，不直接把核心执行绑定到 BackgroundTasks；
4. 开发环境可保留 BackgroundTasks adapter，但 adapter 只能调用 worker 的 `run_one(job_id)`；
5. 增加 job 状态 API：详情、取消、重试、积压统计。

**验收指标：**

- 同一个 job payload 同时提交只保留一个 active job；
- worker 崩溃后 lease 过期可重新 claim；
- 达到 max_attempts 后进入 dead-letter/failed；
- cancel 后不能再次 claim；
- 任务成功率 ≥99%；
- 24 小时积压任务不会污染 latest eval；
- 任务状态变化有 owner、attempt、heartbeat、failure_reason。

### 任务 3A-3：索引一致性

新增 `scripts/check_data_consistency.py`，至少检查：

- 当前 document version 与 chunks version 对齐；
- SQLite chunks 与 Chroma IDs 数量一致；
- 上传原文存在且 SHA256 一致；
- FTS row count 与 chunks count 一致；
- failed/processing version 是否存在 active job；
- 输出机器可读 JSON 和 exit code。

验收：正常数据 exit 0；任一偏差 exit 1，并列出 document/version/chunk 差异。

## Phase 3B：认证、会话归属与审计（P0）

### 任务 3B-1：统一身份模型

新增请求上下文 `Principal`：

```text
principal_type: admin | user | robot | service
principal_id
tenant_id
scopes
request_id
```

第一阶段不重做完整 IAM，采用可落地的三种凭证：

- Admin：`X-Admin-Token` + secure signed cookie；
- Service/Agent：`Authorization: Bearer <service-token>`；
- Robot：`X-Robot-Id`、`X-Robot-Timestamp`、`X-Robot-Nonce`、HMAC signature。

### 任务 3B-2：会话归属

- conversations 增加 `owner_type/owner_id/tenant_id`；
- agent_sessions 增加 owner/tenant/request_id；
- 读取 conversation、agent session、answer run 前校验 principal；
- 不允许仅凭 conversation_id 枚举读取；
- 管理员可按授权范围访问，普通服务只能读自己的会话。

### 任务 3B-3：安全细节

- 管理 cookie 增加 `secure`、`max_age`、`expires`；
- 管理 POST/DELETE 增加 CSRF token；
- Robot 签名校验时间窗口和 nonce 去重；
- Agent/Robot 使用独立限流和并发配额；
- 所有认证失败统一错误码，不暴露内部信息；
- 增加 `audit_logs`：登录、文档上传、停用、重建、评测、迁移、备份、恢复、取消任务。

**验收：**

- 未认证 Agent/Robot 请求返回 401；
- 错租户 conversation 返回 403/404，不泄露存在性；
- 重放 Robot 请求失败；
- 默认 token/secret 生产启动失败；
- 管理操作可按 request_id/operator 查询审计记录。

## Phase 3C：备份、恢复与数据保护（P0）

### 目标

把“有备份文件”升级为“可验证、可恢复的备份系统”。

### 实现

新增：

- `scripts/backup_runtime.py`；
- `scripts/restore_runtime.py`；
- `scripts/verify_backup.py`；
- `docs/runbooks/backup-restore.md`；
- `data/backups/manifest.json`（运行产物不必提交，但格式和校验脚本提交）。

备份包必须包含：

- SQLite 一致性快照；
- Chroma 目录；
- uploads 原文；
- migration/schema version；
- 配置非敏感快照；
- manifest、时间、commit、计数和 SHA256。

### 目标

- RPO ≤24h；
- RTO ≤4h；
- 每日自动备份；
- 备份加密并支持保留策略；
- 恢复后自动执行 integrity/foreign key/SQLite-Chroma-count consistency；
- 每季度恢复演练，落盘演练报告。

### 严禁

- 未验证备份就删除旧数据；
- 把 API key、secret、cookie 写入 manifest；
- 将真实运行数据库、上传文件或密钥备份提交 Git。

## Phase 3D：可观测性与运行 SLO（P1）

### 任务

1. `/metrics` Prometheus endpoint；
2. request-id middleware；
3. JSON structured logging；
4. latency metrics：retrieval/generate/review/finalize/total；
5. error metrics：4xx/5xx/429/timeout/fallback；
6. job metrics：queued/running/failed/dead-letter/oldest age；
7. Agent metrics：steps/tool failure/replan/terminal status；
8. token/cost metrics（本地模型先记录 token 估算和耗时）；
9. 可选 OpenTelemetry span；
10. 告警规则与 `docs/runbooks/incident-response.md`。

### SLO 初始值

| SLO | 目标 |
|---|---:|
| API 月可用性 | ≥99.5% |
| Chat P95 | ≤8s（本地模型基线需压测校准） |
| Chat P99 | ≤15s |
| 5xx | ≤0.1% |
| 任务完成率 | ≥99% |
| 索引新鲜度 P95 | ≤10min |
| 备份成功率 | 100%/日 |

“未测量”不等于通过。

## Phase 3E：答案质量升级（与生产轨并行）

### Q1：claim-evidence matrix v2

- 一个 claim 必须对应 subject/attribute/value/file/page/chunk/confidence；
- 多主体问题按主体输出，不允许只拼一个自然语言段落；
- comparison 输出 A/B/missing_fields；
- 工具计算结果作为 typed evidence；
- 最终答案与 answer_run、Agent session、citation matrix 关联。

### Q2：按桶修复顺序

1. cross_document：多文档轮转 + 每主体证据配额；
2. multi_hop：中间结论结构化，禁止只拿最后一跳；
3. synonym_rewrite：同义词归一仅进入通用 query normalization，不加题目特判；
4. OCR：质量分数 + 文本信号组合，减少 11 个 wrong_block；
5. long_context：证据窗口、章节/页聚合、干扰惩罚；
6. numeric/negative：只做回归保护，不轻易放宽。

### Q3：评测有效性

- wrong_release 和 wrong_block 各主桶抽样 ≥20%；
- 规则结果、人工结论、原因标签三者同时落盘；
- 新增 `semantic_diagnostic`，但不替换正式 hard 指标；
- 只有形成 D 级决策后才能调整正式判分。

## 5. 每个阶段的 Definition of Done

每项工作必须同时具备：

1. 代码实现；
2. 单元/API/故障测试；
3. 运行命令和结果文件；
4. 失败和回滚说明；
5. `docs/codex-handoff.md` 追加记录；
6. 稳定路线同步 `docs/codex-decisions.md`；
7. Git commit 可定位；
8. 未达标项按“未达标/原因/证据/下一步”记录。

## 6. 推荐提交顺序

每个独立阶段使用独立 commit，建议：

1. `feat(migration): version sqlite schema and add migration smoke`
2. `feat(worker): claim lease retry dead-letter and idempotency`
3. `feat(auth): principal ownership and robot signature`
4. `feat(backup): verified backup restore and consistency check`
5. `feat(observability): metrics request-id structured logs and SLO`
6. `feat(answer): claim matrix v2 and bucket fixes`
7. `test(release): full gate artifacts and release decision`

禁止将未验证的多个生产维度混在一个不可回滚的大 commit 中。

## 7. 下一窗口固定执行清单

```bash
# Unit + migration + reliability
EVAL_API_BASE_URL= USE_STUB_ML=true DISABLE_LLM=true ./.venv/bin/pytest tests/ -q
./.venv/bin/python scripts/migrate.py status
./.venv/bin/python scripts/check_data_consistency.py

# Quality gate (local evidence path)
EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python scripts/run_rag_metrics.py \
  --dataset data/evals/hard_eval_v1.json --output-dir data/evals/results --top-k 10
EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python scripts/run_eval.py \
  --dataset data/evals/kb_quality_full_v1.json --output-dir data/evals/results
EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python scripts/run_agent_eval.py \
  --dataset data/evals/hard_eval_v1.json --output-dir data/evals/results
EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python scripts/run_agent_eval.py \
  --dataset data/evals/hard_eval_v1.json --output-dir data/evals/results --force-agent
```

## 8. 当前明确不做的事

- 不另起一套 RAG 底座；
- 不把 RAGFlow现象当正式能力证据；
- 不为单个题目添加硬编码答案；
- 不在没有抽样证据时修改评分口径；
- 不在 worker/备份/鉴权没有完成前宣称生产就绪；
- 不为追求 accuracy 放松错误放行防线；
- 不在没有用户授权时删除运行数据库、恢复 RAGFlow 源码或清理历史资产。

## 审查结论

`docs/next-round-brief.md` 当前计划“正确性主线”基本合理，但不能单独支撑“企业级工程化落地”。需要修订为双轨计划：

- **质量轨**：继续解决 hard 集准确率、幻觉率、错误放行/误阻塞和 Agent 证据闭环；当前 hard accuracy=0.7246、hallucination=0.1462、wrong_release=19，79 题 frozen wrong_release=4，均明确为未达标。
- **生产轨**：补齐安全、可靠性、可观测性、数据治理、成本、部署、灾备、CI/CD 和 SLO；在生产轨 P0 未完成前，只能称为单机/内网验证态，不能称为企业级生产就绪。

## 拟修改的文档范围

1. **重写 `docs/next-round-brief.md` 的现行计划部分**
   - 保留当前结果、模型/评测环境不变量、RAGFlow D-034 限制和禁止事项。
   - 新增“企业级定义与发布门禁”，明确：质量门禁、可靠性门禁、安全门禁、运维门禁、数据治理门禁必须分别通过；不是只看 accuracy。
   - 将目标拆成阶段和可验收产物，避免把设计目标误写成已具备能力。

2. **新增企业级目标矩阵和 SLO/SLA 草案**
   - 质量：hard R@5/R@10、MRR、accuracy、hallucination、correct refusal；79 题非回退；Agent 复杂题相对单轮质量、每 claim citation、轨迹完整率。
   - 服务：可用性、P95/P99 延迟、4xx/5xx、429、LLM/RAGFlow 超时、fallback 率。
   - 异步任务：任务成功率、积压年龄、重试/死信、索引新鲜度、一致性校验成功率。
   - 数据保护：RPO/RTO、备份成功率、恢复演练通过率、SQLite/向量/原文计数一致性。
   - 安全：默认凭据拒绝、Robot/Agent 鉴权、会话归属、CSRF、审计覆盖、密钥轮换。
   - 每项写清当前值、目标值、证据文件、责任模块和未达标处理方式。

3. **新增/重排工作流**
   - `WS-QA`：答案收口与 claim-evidence matrix，覆盖多部分、跨文档、多跳、否定、数值、OCR、长上下文；禁止题目 ID 特判和放松 grounded 守卫。
   - `WS-Agent`：统一 Evidence/Claim/Comparison contract；修复 MultiDocCompare 顶层 grounding/citations 丢失、工具证据字段不完整、Agent 未持久化 matrix/answer_run_id、共享 `_pipeline_citations` 并发污染、calculator/date 结果未进入最终证据链。
   - `WS-Eval`：扩展指标有效性和 Agent 评测，报告 plan/schema 合法率、工具成功率、超时/重规划、轨迹完整率、每 claim citation、复杂题与单轮 flip cases；区分规则判分和模型生成，不把关键词子串当作完整语义质量的唯一证据。
   - `WS-Runtime`：生产运行基线，包含健康探针、统一错误码/request-id、结构化日志、Prometheus/OpenTelemetry、端到端 deadline、依赖隔离、限流/配额、CI 门禁。
   - `WS-Reliability`：可靠后台任务、migration、幂等、lease/heartbeat/retry/dead-letter/cancel、SQLite/Chroma/原文一致性、备份恢复演练。
   - `WS-Security`：默认密钥拒绝、Robot/Agent 认证与防重放、会话/租户归属、RBAC、CSRF/CORS、提示注入防护、敏感轨迹脱敏和审计。
   - `WS-Deploy`：Docker/systemd/Kubernetes 之一的生产启动基线，禁止 `--reload`，补资源限制、优雅退出、探针、持久卷、版本/回滚说明。

4. **将执行顺序改为“先冻结基线，再并行质量和生产阻断项，最后发布验收”**
   - Phase 0：提交/冻结当前 hard、79、Agent 基线；验证评测环境变量和结果可追溯性。
   - Phase 1（质量 P0）：统一证据契约与 claim matrix，修复 Agent 对比/工具证据/并发隔离/终答关联；每次变更跑既定五步评测。
   - Phase 2（质量 P1）：按桶处理 cross_document、multi_hop、synonym_rewrite 的错误放行及 OCR/long-context 误阻塞；增加语义级人工抽样或独立 judge 校验，防止规则指标失真。
   - Phase 3（工程 P0）：安全启动校验、API/会话鉴权、健康/就绪探针、可靠任务模型、migration、备份恢复和生产启动方式。
   - Phase 4（工程 P1）：metrics/tracing/日志/告警、成本与 token usage、CI 安全扫描、集成/并发/故障恢复测试。
   - Phase 5：发布候选验收；只有所有门禁达到目标，才允许“企业级生产就绪”；否则输出明确的未达标清单和限制。

5. **补充每轮强制验证与证据要求**
   - 保留现有 `pytest → run_rag_metrics → run_eval → Agent routed → Agent forced` 顺序。
   - 新增静态/契约测试、权限测试、并发隔离、工具超时取消、恢复演练、健康探针、migration、备份校验和部署 smoke test。
   - 每轮结果必须落盘、关联 git commit/环境快照，并追加到 handoff；不得只凭聊天汇报。
   - 不因单测通过、局部样例通过或旧结果变好而宣布企业级完成。

6. **同步控制面文档**
   - `docs/codex-handoff.md`：追加本次审查结论、当前企业级阻断项、阶段状态和证据索引。
   - `docs/codex-decisions.md`：若接受“双轨企业级门禁/生产就绪定义/新增 workstream”作为稳定路线，追加新的正式决策；不覆盖历史决策。
   - 如发现 `docs/agent-architecture.md` 与代码不一致，仅在计划中登记为必须修订项，后续按代码和测试证据更新。

## 实施约束

- 第一阶段只修改计划/控制面文档，不修改问答逻辑；避免在没有新基线的情况下扩展代码。
- 后续任何代码行为变更必须同时跑全量 pytest、hard 评测、79 题回归和 Agent routed/forced，并保存结果。
- 继续使用本机 Ollama `qwen2.5:14b` 作为正式阶段模型；RAGFlow 只做现象记录。
- 不恢复/删除用户未授权的数据、数据库状态或 RAGFlow 源码；不提交密钥和运行产物。
- 最终计划必须诚实保留当前未达标事实：质量目标与企业级生产门禁尚未通过。
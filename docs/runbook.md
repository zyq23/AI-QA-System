# Runbook — 故障处置与恢复

> 适用：本知识库问答系统（FastAPI + SQLite + Chroma + BGE）。   
> 目标：让运维在故障时能按本文档快速定位、隔离、恢复。   
> 更新：2026-09-22。

## 1. 健康检查与探针

| 端点 | 含义 | 期望返回 |
|---|---|---|
| `GET /live` | 进程存活 | `200 {"status": "ok"}` |
| `GET /ready` | 数据库可用 | `200 {"status":"ready","database":"ok"}` 或 `503` |
| `GET /healthz` | 依赖/后端在位 | `200 {"status":"ok","ready":true,"retrieval_backend":"local"}` 或 `503` |
| `GET /metrics` | 进程内指标（QPS/延迟/错误） | `200` JSON，含 `count/error_rate/p50/p95/p99` |

**判定规则**：
- `/live` 5xx ×3 → 进程或编排层问题
- `/ready` 持续的 `503 database:error` → SQLite 损坏或只读
- `/healthz` 持续 `503` → 检索后端缺失（本地 Chroma/BGE 未加载）

## 2. 常见故障与处置

### 2.1 500 Internal Server Error（API 抛错）
1. 查服务日志（`journalctl -u <service>` 或 `docker logs <container>`）。
2. 用 `X-Request-ID` 关联某次请求的完整日志链。
3. 若为 LLM 调用失败：确认 Ollama 模型在位、`http://127.0.0.1:11434/v1` 可达。
   - DashScope 欠费会返回 Arrearage，不是算法问题。
4. 若为检索失败：确认 `RETRIEVAL_BACKEND`；本地链路看 `data/runtime/app.db` + `data/chroma`。

### 2.2 429 Too Many Requests
- 进程内 `SlidingWindowLimiter` 按 IP 限流 30 req/min。
- 隔离 Nginx/ELB 层限流，勿与业务逻辑混用。
- 若误伤，调 `window_seconds`/`limit` 或按 header 分流。

### 2.3 401 / 403 鉴权失败
- 生产要求 `ADMIN_TOKEN` / `SECRET_KEY` / `SERVICE_API_TOKEN` / `ROBOT_HMAC_SECRET` 均已设置。
- 机器人签名窗口默认 300s；时钟偏移超过会 401，校准 NTP。
- 会话属主校验：`conversation_id` 必须以签名 cookie 绑定，否则 403。

### 2.4 SQLite 损坏 / 只读
1. 停止服务，备份 `data/runtime/app.db`。
2. 用 `scripts/verify_backup.py` 校验备份完整性。
3. 必要时 `VACUUM`；从最近一次 `scripts/restore_runtime.py` 恢复。
4. 恢复后确认 `/ready` 返回 `database:ok`。

### 2.5 后台任务 stuck（ingestion/eval）
- 启动时自动回收超过 24h 的 `running/queued` 任务为 `failed`。
- 手动：`UPDATE jobs SET status='failed' WHERE id='<job_id>' AND status IN ('running','queued');`
- 幂等保证：同文档依赖 active job 存在，重复提交被抑制。

### 2.6 备份与恢复演练
- 脚本：`scripts/backup_runtime.py`（DB+Chroma+uploads 配对）、`scripts/verify_backup.py`、`scripts/restore_runtime.py`。
- RPO 目标 ≤24h；RTO 目标 ≤4h。
- **每季度至少一次恢复演练**，记录到 `docs/runbook.md` 的演练记录区。

## 3. 关键环境不变量（不可回退）

- 评测必须 `RETRIEVAL_BACKEND=local` 且 `EVAL_API_BASE_URL` 为空。
- 模型：本机 Ollama `qwen2.5:14b`；DashScope 恢复前不假设可用。
- RAGFlow 仅作现象记录（D-034），不作为能力证据。
- 禁止绕开 finalize 守卫直接释放工具/检索结果。

## 4. 演练记录

| 日期 | 事件 | 处置 | 结论 |
|---|---|---|---|
| 2026-09-22 | AGENT_EVAL schema 兼容 + auth test 通过 | 更新 app/dependencies.py / api_agent / api_robot / main.py | 鉴权+metrics+日志基线就绪 |
| （空） | 尚未执行完整 RPO/RTO 恢复演练 | 待下季度 | — |

## 5. 遗留缺口（非阻塞）

- `/metrics` 尚为进程内 JSON，未接 Prometheus 采集器（若部署可裸接 text 格式）。
- 结构化日志尚需在业务代码各处显式调用 `sanitize()`。
- 生产部署物（Dockerfile / systemd）与 CI 门禁未完整落地。
- 完整 RPO/RTO 恢复演练与容量并发压测未执行。

> 本文档随发布候选验收同步更新；任何未达标项保持如实标记。
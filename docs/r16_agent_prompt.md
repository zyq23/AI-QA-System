# R16 Agent 专项工作提示词

## 当前接手状态

### 单轮链路已达标（2026-09-18 R15 收口）
- 全量 pytest：`165 passed, 7 warnings`（无回归）
- Hard 130 全量：`rag_metrics_20260918_124631.json`
  - answer_pass=78, correct_block=24, wrong_release=6, wrong_block=22
  - accuracy=0.9286, hallucination_rate=0.0462, correct_refusal_rate=0.96
  - Recall@5=0.8857, Recall@10=0.9286, MRR=0.7521
- 79 题正式回归：`eval_20260918_121835_formal_summary.json`
  - total=79, answer_pass=37, correct_block=16, wrong_release=6, wrong_block=20
  - FROZEN：新 PPT 13 题 answer_pass=4/correct_block=6/wrong_release=3（p0-01/04/05）
  - GEN：泛化 52 题 answer_pass=25（回基线）/wrong_release=2（gen-ict-10、gen-arm-08）
  - OLD：旧资料 14 题 answer_pass=8/wrong_release=1
- R16 前置条件：pytest 已通过。hard 与 79 回归已在本窗口复跑并达标。

### Agent 现状（核心问题）
- **Agent 无当前基线**。最近可信 Agent 全量为 `data/evals/results/agent_eval_20260914_015701.json`（routed，130 题，answer_pass=43/correct_block=24/wrong_release=19/wrong_block=44，accuracy=0.6935），更早为 `agent_eval_20260911_053027.json`。
- 跨文档子集上 Agent 显著劣于单轮：`agent_eval_20260915_012918.json`（cross_document 15 题）answer_pass=2/wrong_block=10，准确率 0.40。
- **失败桶分布**（9/14 routed）：cross_document WR=4/WB=6；synonym_rewrite WR=5/WB=6；multi_hop WR=4/WB=6；long_context_distraction WB=11；ocr_noise_page WB=13；no_answer 拒答率达标。
- 关键缺口：
  - `terminal_status`（timeout/step_budget/exhausted_error/completed/clarification/no_answer）未落盘到 Agent 评测结果
  - `finalize_stage`/`guard_triggered` 缺失，无法归因失败到 planner/retrieval/evidence/finalize/timeout 五段
  - `_pipeline_citations` 是共享实例状态，并发请求会串证据
  - `MultiDocCompareTool` 返回 `sides`，但 controller 检查顶层 `grounded/hits` → 终端判定永远为 false
  - `CitationModel` 缺 `chunk_id`，`_serialize_hits()` 截断 snippet 到 400 字符
  - 45s 超时只在工具调用间隙检查，工具内部阻塞不可中断
  - planner replan 校验比初始计划宽松，无 Pydantic Schema 校验

## 必须遵守的约束

1. Agent 终答必须复用生产 `ChatService.answer` 的 finalize 守卫（subject-claim、yes/no、value、negative-question、OCR、insufficient signals），禁止绕过直接释放工具结果（D-039 硬约束）。
2. 禁止把 `agent_eval_20260911_053027.json` 当作当前基线引用。
3. 禁止在 R16 加题目 ID 特判（canned answer）。
4. 禁止修改评分口径；所有收敛必须来自代码修复。
5. RAGFlow 仍受 D-034 约束，仅作现象位。
6. 每轮必须同时跑：pytest → hard metrics → 79 回归 → Agent routed → Agent forced，五项缺一不可。
7. 结果落盘 + SHA-256 + handoff 追加；形成稳定架构决策时更新 `docs/codex-decisions.md`。

## 待决决策（需主线程裁决后再执行）

1. **FROZEN 3 题 WR**（p0-01/04/05）：题集 `must_block` 阻塞预期与目标 PPT 可答事实的固有冲突，是否调整题集标注？若裁决"保留 must_block"，则该 3 题不计入 Agent 验收；若裁决"放行"，则需重新评估 WR 阈值。
2. **R16 优先级**：优先补 Agent 证据契约（M-P1）还是继续抬 hard 指标？当前 hard 已达标(0.9286/0.0462)，Agent 是下一瓶颈。
3. **cross_document 检索侧改造**：是否切换为 claim-conditioned candidate pooling 补强跨文档检索信号？当前 recall@5=0.475 是主要瓶颈。

## R16 执行序列（按序执行，前一步通过才进下一步）

### Step 0: 单轮基线（Agent 对比用）
```bash
cd /data/zyq/yushu
EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python scripts/run_rag_metrics.py --dataset data/evals/hard_eval_v1.json --output-dir data/evals/results --top-k 10
# 目标：accuracy ≥0.90, hallucination ≤0.05, correct_refusal ≥0.95, R@5≥0.85, R@10≥0.92
# 记录输出路径（形如 data/evals/results/rag_metrics_20260921_*.json）
```

### Step 1: pytest
```bash
EVAL_API_BASE_URL= USE_STUB_ML=true DISABLE_LLM=true ./.venv/bin/pytest tests/ -q
# 目标：165+ passed，无回归
```

### Step 2: 79 题正式回归
```bash
EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python scripts/run_eval.py --dataset data/evals/kb_quality_full_v1.json --output-dir data/evals/results
# 目标：FROZEN WR ≤3, GEN answer_pass ≥20，无回退
# 记录正式 summary 路径
```

### Step 3: Agent routed 全量
```bash
EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python scripts/run_agent_eval.py --dataset data/evals/hard_eval_v1.json --output-dir data/evals/results
# 目标：可答准确率 ≥ 单轮链路（Step 0 的 accuracy），每 claim 有 citation
# 记录 routed 结果路径
```

### Step 4: Agent forced 压力
```bash
EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python scripts/run_agent_eval.py --dataset data/evals/hard_eval_v1.json --output-dir data/evals/results --force-agent
# 目标：forced 幻觉率 ≤ routed 幻觉率，拒答率 1.0
# 记录 forced 结果路径
```

### Step 5: 落盘 + handoff 追加
- 计算结果文件 SHA-256
- 在 `docs/codex-handoff.md` 追加 `2026-09-21 R16` 段落，包含：改动、指标变化、WR/WB 变化、79 题是否回退、Agent vs 单轮对比、阻塞、下一步
- 若形成稳定架构决策，更新 `docs/codex-decisions.md`

## 验收门槛（R16 必须全部达标）

| 维度 | 门槛 | 当前基线 |
|---|---|---|
| pytest | 165+ passed | 165 ✓ |
| Hard accuracy | ≥0.90 | 0.9286 ✓ |
| Hard hallucination | ≤0.05 | 0.0462 ✓ |
| Hard correct_refusal | ≥0.95 | 0.96 ✓ |
| Hard Recall@5 | ≥0.85 | 0.8857 ✓ |
| 79 FROZEN WR | ≤3 | 3 ✓ |
| 79 GEN answer_pass | ≥20 | 25 ✓ |
| Agent routed accuracy | ≥ 单轮 | 待 Step 0 确认 |
| Agent forced hallucination | ≤ routed | 待 Step 0 确认 |
| Agent 有新 routed/forced 基线 | 必须生成 | ❌ 待产出 |
| Agent 结果含 terminal_status | 必须落盘 | ❌ 待补字段 |

## 禁止事项

- ❌ 禁止在未修复 M-P1 证据契约前宣称 Agent 生产就绪
- ❌ 禁止引用 2026-09-11 Agent 结果作为当前基线
- ❌ 禁止绕过 `ChatService.answer` finalize 直接从工具结果释放答案
- ❌ 禁止在 R16 追加题目 ID 特判
- ❌ 禁止修改评分口径
- ❌ 禁止用"评测口径特殊"包装真实能力缺口
- ❌ 禁止未跑 79 回归就先跑 Agent 评测
- ❌ 禁止在 handoff 追加结果前不跑 SHA-256

## 文档与接力入口

- 主接力入口：`docs/codex-handoff.md` line ~1120（R15 当前判断与下一步之后追加 R16）
- 评测脚本：`scripts/run_agent_eval.py`、`scripts/run_rag_metrics.py`、`scripts/run_eval.py`
- Agent 源码：`app/agent/{controller,service,state,tools,planner,sessions}.py`
- 单轮入口：`app/services/chat.py`、`app/services/llm.py`
- 计划任务：`docs/next-round-brief.md`（§3 Phase 1 M-Q1~Q4、M-P1~P2；§5 执行序）
- 架构说明：`docs/agent-architecture.md`（§4 当前评测数字；§6 文档债清单）
- 全局决策：`docs/codex-decisions.md`（D-039 证据契约、D-041 执行边界）
- AGENTS.md："Current Project Context" 数字快照

## 字段补齐优先级（R16 必须完成）

在 `AgentResult` / `run_agent_eval.py` per_case 中新增以下字段，使单题失败可归因到"规划-检索-证据提取-终答收口-超时"五段：

1. **terminal_status**（最高优先）：映射 `controller._terminal_status()` 的 `timeout/step_budget/exhausted_error/completed/clarification/no_answer`
2. **timeout_reason**：timeout 细分（wall_clock/tool_internal/step_budget）
3. **plan_status**：初始计划 vs replan 次数
4. **finalize_stage**：draft/review/finalize 哪一层失败
5. **guard_triggered**：哪些生产守卫被触发

## M-P1 Agent 证据契约清单（若主线程裁决优先）

- [ ] 工具全字段保留（chunk_id/plain_text/ocr_quality/score）
- [ ] MultiDocCompareTool 顶层 grounded/hits 与 controller 期望对齐
- [ ] 请求级 citations 隔离（消除共享 `_pipeline_citations`）
- [ ] answer_run_id 回填到 AgentResult 与 session 记录
- [ ] calculator/date 结果进 finalize 证据链
- [ ] CitationModel 补 chunk_id
- [ ] per-tool deadline + 可取消执行器
- [ ] replan 统一 JSON Schema/Pydantic 校验

## 跨文档检索补强（若主线程裁决优先）

- 定向切片 20 题 Recall@5 当前 0.475，目标 0.85
- 候选方案：claim-conditioned candidate pooling 补强跨文档检索信号（每 (subject, attribute) 对独立 retrieve，exact claim query 优先）
- 需与单轮 `rag_metrics` 对齐归因（单轮 cross_document 已从 0.475 改善，R15 硬指标 accuracy 0.9286）

## 交接确认清单（新窗口开始时必须逐条核对）

- [ ] 确认 pytest 通过（165+）
- [ ] 确认 hard 130 基线文件路径（rag_metrics_20260918_124631.json）
- [ ] 确认 79 回归文件路径（eval_20260918_121835_formal_summary.json）
- [ ] 确认 Agent 最近可信基线文件（agent_eval_20260914_015701.json）
- [ ] 确认 FROZEN 3 题 WR 主线程裁决状态
- [ ] 确认 R16 优先级（Agent 证据契约 vs hard 指标）
- [ ] 确认 cross_document 改造方案

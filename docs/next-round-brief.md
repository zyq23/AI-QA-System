# Next Round Brief：企业级 RAG + Agent 加固（2026-09-11）

> 新窗口接入点。先读本文件，再读 `AGENTS.md`、`docs/codex-handoff.md`（Quality-Upgrade 阶段 5/6）、`docs/codex-decisions.md`（D-032~D-039）、`docs/agent-architecture.md`。冲突时按 `AGENTS.md > decisions > plan > handoff` 优先级。

## 1. 现状一句话

RAG 检索层已达标（Recall@5=0.886 / Recall@10=0.943 / MRR=0.756，无答案拒答率 1.0），但**答案层未达标**：hard 集准确率 0.638（目标 ≥0.90）、幻觉率 0.131（目标 ≤0.05）；Agent 骨架已跑通但准确率 0.515 低于单轮，需真正提升而非包装。

## 2. 不可回退事实

- 模型：本机 Ollama `qwen2.5:14b`（`http://127.0.0.1:11434/v1`）。DashScope 账户欠费（Arrearage），恢复前不得假设远端模型可用，也不要把欠费误判为算法结果。
- 79 题回归护栏：FROZEN wrong_release ≤ 3（当前 2）、GEN answer_pass ≥ 20（当前 25）。不得回退。
- 检索/答案关键路径：FTS(SQLite, jieba 词级+单字回并+文档名 token)、Chroma+BGE、RRF+Rerank、多查询分解+文档轮转合并、`config/retrieval_rules.json` 数据驱动规则、draft→review→finalize 反幻觉守卫。
- 评测必须 `RETRIEVAL_BACKEND=local`；`EVAL_API_BASE_URL` 必须清空（否则打到无关服务）。RAGFlow 仅现象记录（D-034），禁止当能力证据。
- 禁止：重建独立 RAG、删 finalize 守卫、加题目 ID 特判、为提指标放松 grounded、把 raw OCR / raw tool observation 当答案、无界 ReAct、跳过 git 提交。

## 3. 主要差距与方向（证据驱动，先诊断后改）

1. **多部分答案只收一侧**：`A 和 B 分别是什么` 只答一个主体 → 建 claim-evidence matrix：每个 claim 含 subject/attribute/value/citation_file/citation_page/matched_keywords/confidence，全部核心 claim 有证据才放行；每缺一必选项就降级或拒答，不得伪装完整回答。
2. **否定题**：区分 `以下哪项不是 / 除了X还 / 是否支持`；校验被排除实体、要求项、选项极性、citation claim 极性。
3. **数值陷阱**：目标数值须与证据精确匹配，近似值不算通过；question echo 不算回答；数值 claim 必须挂 citation。
4. **OCR/长上下文**：保留 OCR 块与质量标记，过滤乱码/表格碎片；命中关键词≠直接放行，同样进 matrix。
5. **Agent 工具输出丢证据**：snippet 太短 → 每条 evidence 至少含 file_name/page_or_slide/section_path/chunk_id/plain_text/score/ocr_quality。
6. **multi_doc_compare 需出对比矩阵**：subject_a/subject_b 各自 claims+citations，comparison 逐属性 A/B 值，missing_fields 显式。
7. **Agent 终答必过生产守卫**：tools → structured evidence → claim extraction → claim-evidence verification → production finalize。禁止工具 observation 直接当答案。可用"初始计划+补检轮"（保持 max_steps/timeout/异常兜底）。
8. **路由**：简单 factoid→快速路径；对比→multi_doc_compare；明确文档/页码→document_detail；数学/日期→calculator/date_utils；意图不明→clarification；无证据→no_answer。

## 4. 每轮动作顺序（全跑，结果落盘+handoff 追加）

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
```

每轮在 `docs/codex-handoff.md` 追加：改动、指标变化、wrong_release/wrong_block 变化、79 题是否回退、Agent vs 单轮、阻塞、下一步。形成稳定架构决策时更新 `docs/codex-decisions.md`（D-040 起），并补充 pytest 覆盖（matrix/对比/否定/数值/OCR/工具完整性/兜底/落库/API 轨迹）。

## 5. 达标线（全部满足才算企业级阶段）

- hard：Recall@5≥0.85、Recall@10≥0.92、准确率≥0.90、幻觉率≤0.05、拒答率≥0.95
- 79：frozen WR≤3、gen answer_pass≥20、无回退
- Agent：复杂题准确率≥单轮、幻觉≤单轮、拒答≥0.95、轨迹全落库、每 claim 有 citation、兜底测试完整、API/robot 稳定

未达标项必须写：未达标 / 原因 / 证据 / 下一轮方向。禁止提前宣布完成。

## 6. 结果文件索引

- hard 集：`data/evals/hard_eval_v1.json`（130 题，8 桶，builder 逐条 DB 验证）
- RAG 指标基线：`data/evals/results/rag_metrics_20260911_032145.json`（acc 0.638 / halluc 0.131 / refusal 1.0）
- 检索迭代轨迹：`data/evals/results/retrieval_local_only_r*.json`
- Agent 评测：`agent_eval_20260911_053027.json`（routed）/ `051423.json`（forced）
- 79 回归：`data/evals/results/eval_20260911_033026_formal_summary.json`
- 80% 以上硬编码规则表：`config/retrieval_rules.json`；Agent 架构说明：`docs/agent-architecture.md`
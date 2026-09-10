# Agent 架构说明（智能客服形态）

> 本文档是 Agent 化改造的核心面试材料：架构图（文字版）、关键取舍、兜底设计，
> 以及与 LangChain / LangGraph 方案的对比。代码入口 `app/agent/`，接口
> `POST /api/agent/query`。

## 1. 一句话定位

在现有 FastAPI + RAG 底座上，把"检索→生成→审阅→收口"的单轮链路升级为
**"路由 → 计划 → 执行工具 → 证据收口"** 的 Agent 控制器：简单问题走原有快速路径，
复杂问题（跨文档对比、多跳、数值/日期计算、需澄清/拒答）进入 plan-then-execute
循环，且**最终答案必须回到生产答案管线收口**（所有防幻觉守卫复用，不给 Agent 另开
后门）。

## 2. 架构图（文字版）

```
                    ┌─────────────────────────────────────────────┐
                    │              AgentService (路由层)            │
                    │  needs_agent(question)                       │
                    │   简单 → chat_service.answer（快速路径）       │
                    │   复杂 → AgentController.execute（Agent 回路）│
                    └───────────────────┬─────────────────────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              ▼                         ▼                         ▼
   ┌────────────────────┐   ┌────────────────────┐   ┌────────────────────────┐
   │  Planner（规划器）  │──▶│  Controller（执行器）│──▶│  会话/证据持久化        │
   │  规则意图分类        │   │  max_steps=6       │   │  agent_sessions        │
   │  + 置信度阈值        │   │  timeout=45s       │   │  agent_steps（thought/ │
   │  + LLM 精化（低置信）│   │  异常兜底           │   │  tool/observation）    │
   └────────────────────┘   └─────────┬──────────┘   └────────────────────────┘
                                      │ 工具调用
              ┌───────────────────────┼──────────────────────┐
              ▼          ▼            ▼           ▼          ▼
      knowledge_search  multi_doc_compare  document_detail  calculator  date_utils
              │
              ▼
        生产答案管线 ChatService.answer（draft→review→finalize 全守卫）
              │
      clarification（低置信追问） / no_answer（正确拒答）/ 人工转接占位（escalated）
```

## 3. 关键取舍

### 3.1 为什么 plan-then-execute 而不是纯 ReAct

| 维度 | plan-then-execute（本实现） | 纯 ReAct |
|---|---|---|
| 可解释性 | 计划先行，步骤可审计（agent_steps 落库） | 决策在 thought 流里，事后难还原 |
| 步数控制 | 计划即上限，工具冒烟失败即停 | 需要额外的终止条件，易空转 |
| 与企业评估对接 | 计划/步骤天然可评分（run_agent_eval 输出决策轨迹） | 评测需从自由文本里提取动作 |
| 面试答辩点 | "先想清楚再动手，和人的工作方式一致" | "边想边做，适合探索型任务" |

知识库问答是**受约束的检索任务**：大多数问题可以在出发前定好 1-3 步计划；
纯 ReAct 的"想一步做一步"在这里只会增加延迟与 token 成本。因此选 plan-first，
但保留**一轮有界的重规划**（首轮未接地时 LLM 重规划 ≤2 步，仍在步数/超时上限内）。

### 3.2 工具边界怎么划

每个工具独立、可单测、带 JSON schema（`planner.py` 用 schema 生成工具表提示）：

- `knowledge_search`：现有 RAG 检索封装，返回带 file/page/snippet 的引用证据
- `multi_doc_compare`：跨文档对比（"机械臂 vs 实训套件"），两侧分头检索后并列
- `document_detail`：按文档/页码取全文切片（回答"哪份资料/哪一页"类问题）
- `calculator` / `date_utils`：数值与日期计算（安全 eval 白名单 + 日期偏移）
- `clarification`：置信度低时向用户追问（智能客服必备，终端工具）
- `no_answer`：正确拒答（终端工具）

边界原则：**检索类工具只产证据，不产答案**；答案永远由生产答案管线收口。
这样 Agent 的价值是"多步找证据"，而不是"绕过守卫自说自话"。

### 3.3 失败怎么兜底

- **死循环兜底**：步数上限（默认 6）+ 墙钟超时（默认 45s），两者都是硬上限；
  工具抛异常时记录 error 并停止该步，不重试、不空转
- **计划失败兜底**：LLM 规划输出非法（未知工具 / 空 query / 空澄清问题）→ 放弃该轮
  LLM 计划，回退规则计划
- **答案层兜底**：Agent 收口调用生产管线；管线拒绝释放（unsupported/守卫失败）时
  Agent 同样拒答，**不存在独立于守卫的放行路径**
- **拒答兜底**：无接地证据 → "当前知识库中没有找到相关信息"，`escalated=true`
  标记可接人工转接（当前为占位字段，可接客服工单/日志）
- **超时兜底**：执行超过墙钟仍无结论 → 按拒答处理，决策轨迹保留

### 3.4 意图识别 + 置信度

规则优先（高置信意图直接出计划，0 延迟），LLM 只精化知识问答频段
（`knowledge_qa` 且规则置信 < 0.8）。置信度低于阈值 → `clarification` 工具追问，
不硬答。`agent_sessions` 落 intent + intent_confidence，评测报告可直接看分布。

### 3.5 与 LangChain / LangGraph 方案的对比

| 维度 | 自研 Agent（本实现） | LangChain Agent | LangGraph |
|---|---|---|---|
| 依赖体积 | 0 额外依赖（复用现有 LLM 服务） | 框架抽象 + 回调复杂度 | 图编排框架 |
| 与本地 RAG 的耦合 | 直接复用 `ChatService`/`Repository` | 需要 adapter 包一层 | 需要包一层 |
| 守卫复用 | 答案必须回生产管线，守卫天然继承 | 需手动在 tool 里嵌守卫 | 图节点可挂守卫 |
| 可评测性 | 自有 `run_agent_eval.py` 输出决策轨迹 | 需自建解析器 | 需自建解析器 |
| 面试叙事 | "小步自研，每层都有 112+ pytest 覆盖" | "有生态，但抽象层掩盖了实现" | "适合复杂图，本项目用不上" |

结论：本项目 Agent 是**有界工具循环 + 复用生产守卫**的最小自研实现，不为框架
而框架；LangGraph 的图状态机在本项目的工具数量（7 个）和问题形态下是过度设计。

## 4. 当前评测数字（Agent 路径 vs 单轮链路）

`scripts/run_agent_eval.py --dataset data/evals/hard_eval_v1.json`（130 题难例集）：

| 指标 | 单轮链路基线 | Agent 模式 | 说明 |
|---|---|---|---|
| 召回 Recall@5 / @10 | 0.886 / 0.943 | 同（复用检索） | 检索层由目标一轮次迭代达标 |
| 拒答率（无答案正确拒答） | 1.0 | 0.96 | no_answer 工具兜底 |
| 平均延迟 | ~7.7s | ~5.0s | 路由让简单题走快速路径 |
| 准确率（可答题） | 0.64 | Agent v1 切片 ~0.68 | 多步证据提升跨文档/多跳 recover |
| 幻觉率（wrong_release） | 0.13 | Agent v1 0.18 | 已知限制：多部分题答案只取一侧 |

已知限制（诚实记录，面试可主动讲）：
1. **多部分题答案只取一侧**：如"机械臂和实训套件的核心设备分别是什么"，Agent 或
   单轮收口只产出其中一个主题的关键词；这是答案生成层的确定性压缩限制，不是检索
   缺证据（Recall 已达标）
2. **Agent v1 幻觉率略高于单轮**：flip 分析显示 agent-only hallucination 集中在
   "以下哪项不是"类否定题 —— Agent 证据顺序与单轮不同，生产管线的否定守卫依赖
   top 排序；已在收口时回退生产管线缓解，剩余偏差记录为已知限制
3. **LLM 规划器依赖模型质量**：本地小模型（qwen2.5:7b）输出 JSON 不稳时，规划器
   校验失败自动回退规则计划（已做），代价是复杂题退化为单步检索

## 5. 相关文件

- `app/agent/`：state / tools / planner / controller / sessions / service
- `app/routers/api_agent.py`：`POST /api/agent/query`
- `app/routers/api_robot.py`：robot 接口复用 Agent（复杂题走 Agent 回路）
- `scripts/run_agent_eval.py`：Agent 评测 + 与单轮对比
- `tests/test_agent.py`：16 条 Agent 单测（mock LLM，无网络）
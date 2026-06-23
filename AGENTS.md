# AGENTS.md

## Scope

本仓库用于建设和持续完善“基于宇树科技知识库的 AI 问答系统”。

所有进入本仓库工作的线程，在开始分析或修改之前，按以下顺序阅读：

1. `AGENTS.md`
2. `docs/codex-plan.md`
3. `docs/codex-handoff.md`
4. `docs/codex-decisions.md`

## Mission

项目目标不是做通用聊天，而是围绕本地知识库资料，构建一个可落地、可引用、可评测、可持续完善的知识库问答系统。

系统的核心目标包括：

- 支持 `pdf / docx / pptx` 等资料进入可问答链路
- 保持答案有证据、有引用、可追溯
- 对复杂文档尤其是 `PPT / 图片页 / OCR 页` 保持较高可用性
- 保留验收、回归、留痕和机器人接入能力
- 在不破坏现有可用能力的前提下逐步升级解析、检索和生成质量

## Current Project Context

基于主线程审计，截至 2026-06-16，项目已确认的状态如下：

- 当前系统不是从零开始，已具备完整的本地问答骨架
- 代码栈以 `FastAPI + SQLite FTS5 + ChromaDB + BGE + 可选 RAGFlow` 为主
- 实际运行策略是“本地检索优先，RAGFlow 作为增强或兜底”
- 当前数据库中已有 6 份已入库文档、12 个版本、7050 个 chunk、1268 条 answer runs
- `宇树科技知识库/` 目录中新增了 `【公司介绍】轩辕网络公司介绍202606.pptx`，但尚未进入现有索引链路
- 现有已入库资料主要是 PDF、DOCX、PPTX，复杂 PPT 已经暴露 OCR 和阅读顺序问题
- 历史验收结果显示旧语料已达到较高通过率，但新资料接入后能力尚未验证

## Collaboration Model

本项目采用“主线程 + 多专项线程”协作模式。

职责划分如下：

- 主线程：负责目标拆解、优先级、依赖协调、阶段验收、风险升级和决策维护
- 专项线程：负责单一方向的推进、验证、留痕和交接
- 新加入线程：默认不重做已明确决策，先读取决策与交接，再决定是否继续推进

当前默认采用 `6 个对话 = 1 个主线程对话 + 5 个专项线程对话` 的组织方式：

- `Main-Thread`：主线程总控
- `Thread-Parser`：文档接入与解析
- `Thread-Retrieval`：检索与召回
- `Thread-Answer`：答案生成与防幻觉
- `Thread-Eval`：评测与回归
- `Thread-Infra`：工程环境与运行接口

所有对话的启动词、边界、输入输出、禁止事项、统一汇报格式，统一维护在 `docs/codex-dialogs.md`。

## Source Of Truth

不同信息只在对应文件中维护，避免混写：

- 规则：`AGENTS.md`
- 总计划：`docs/codex-plan.md`
- 当前施工状态：`docs/codex-handoff.md`
- 关键决策：`docs/codex-decisions.md`

如果几份文件存在冲突，优先级如下：

1. `AGENTS.md`
2. `docs/codex-decisions.md`
3. `docs/codex-plan.md`
4. `docs/codex-handoff.md`

## Non-Negotiable Rules

- 不要绕开现有系统直接另起一套问答架构，除非主线程已明确批准路线切换
- 不要在未验证回归影响前，随意推翻现有可用链路
- 不要把没有证据支持的推断包装成事实写进答案逻辑
- 不要把临时讨论、猜测或个人偏好当成全局决策
- 不要让线程只在聊天里汇报而不更新协作文档
- 每一次代码修改都必须纳入 Git 版本管理，保证改动可追踪、可回滚、可审阅
- 不要把 `codex-plan`、`codex-handoff`、`codex-decisions` 混用
- 不要在没有说明影响范围的情况下进行跨线程大改

## Working Principles

- 优先复用现有系统能力和数据，而不是重做底座
- 优先解决真实业务阻塞，再做长期优化
- 先做证据化诊断，再做架构升级
- 先补评测入口，再做大规模行为改动
- 所有重要结论都要能被后续线程快速接手和复用

## Project Constraints

- 当前重点资料位于 `宇树科技知识库/`
- 新增公司介绍 PPT 需要进入问答链路，但不能破坏旧资料能力
- 复杂 PPT / OCR / 表格 / 图片页 是高风险区域
- 检索链路已存在较多领域规则，后续优化时要控制复杂度继续堆积
- 历史评测资产和运行环境可能存在残留状态，需要单独排查

## Thread Start Contract

每个线程开始工作前至少完成以下动作：

1. 阅读 `AGENTS.md`
2. 阅读 `docs/codex-plan.md` 中自己对应的 workstream
3. 阅读 `docs/codex-handoff.md` 中自己对应线程区块
4. 阅读 `docs/codex-decisions.md` 中与自己相关的已接受决策
5. 确认自己的任务边界、输入、输出和依赖

## Thread Update Contract

每个专项线程在 `docs/codex-handoff.md` 中更新时，至少写清以下内容：

- 当前目标
- 已完成事项
- 当前判断
- 阻塞项
- 下一步
- 相关文件或产物位置

每次更新尽量使用追加方式，避免覆盖别的线程状态。

除 `docs/codex-handoff.md` 的阶段记录外，每个专项线程向主线程汇报时，还必须提交一份符合 `docs/codex-dialogs.md` 中《统一汇报格式》的收口报告。没有统一报告的“我改好了”，主线程不得视为可验收。

## Decision Contract

以下情况必须更新 `docs/codex-decisions.md`：

- 选择了新的技术路线
- 放弃某条候选路线
- 调整了总体优先级或主链路方案
- 确认某个问题属于已知限制而非短期缺陷
- 确认某个工作线程的输出将成为其他线程的共同前提

以下情况只更新 `docs/codex-handoff.md` 即可：

- 进度推进
- 局部调试
- 临时阻塞
- 样例验证

## Planning Contract

`docs/codex-plan.md` 默认只由主线程维护，用于：

- 定义当前阶段目标
- 维护工作流拆解
- 调整优先级
- 标记依赖关系
- 更新阶段里程碑
- 维护 6 个对话的职责边界和主线程监听节奏

专项线程不应自行改写其它线程职责，也不应擅自改总优先级。

## Definition Of Done

一个任务要被标记为完成，至少满足：

- 目标功能、结论或诊断结果已经明确
- 风险、限制和未覆盖点已说明
- `docs/codex-handoff.md` 已更新
- 已向主线程提交统一汇报格式的验收材料
- 如形成稳定结论，`docs/codex-decisions.md` 已记录
- 如涉及行为变化，已考虑评测或回归验证要求

## Escalation Rules

以下情况必须升级给主线程处理：

- 需要改变总体技术路线
- 需要暂停或放弃某个 workstream
- 发现跨多个线程的共同阻塞
- 发现现有决策明显错误或失效
- 发现新资料接入将显著破坏旧资料表现

## Initial Workstream Set

当前默认工作流集合如下：

- `WS-01` 文档接入与解析
- `WS-02` 检索与召回
- `WS-03` 答案生成与防幻觉
- `WS-04` 评测与回归
- `WS-05` 工程环境与 RAGFlow

如后续需要新增 workstream，由主线程在 `docs/codex-plan.md` 中正式登记。

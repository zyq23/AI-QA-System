[THREAD REPORT]
线程名：Thread-Answer
对应 Workstream：WS-03 答案生成与防幻觉
当前轮目标：基于正式运行态已放行的 4 道题，完成答案侧最小闭环验收，明确每题是否可稳定收口，以及事实题 / 枚举题 / 概括题的最终收口边界
状态：review

一、这轮做了什么
- 只围绕主线程放行的 4 道题做正式答案侧验收：
  - `ppt-company-p0-02`
  - `ppt-company-p0-07`
  - `ppt-company-p1-03`
  - `ppt-company-p1-06`
- 先直连正式 `chat_service` 复跑，确认“检索已放行”后答案侧真实会怎么收口。
- 把复跑结果落盘到 [docs/thread-answer-minimal-eval.json](/data/zyq/yushu/docs/thread-answer-minimal-eval.json)。
- 针对复现出的答案侧偏差，在 [app/services/llm.py](/data/zyq/yushu/app/services/llm.py) 补了最小收口规则，并在 [tests/test_api_flow.py](/data/zyq/yushu/tests/test_api_flow.py) 增加对应护栏。

二、为什么这么做
- 这轮目标不是证明“全链路已通过”，而是验证这 4 道已放行题在正式答案链路里是否真的能稳定收口。
- 首轮正式复跑已经证明：只看 `allow_to_answer` 不够，答案侧仍可能出现宣传性补句、混合枚举、以及 fallback 后过长事实答案。
- 这些偏差都发生在 retrieval 已满足前提之后，属于 `WS-03` 的真实验收问题，不能回避。

三、输入与前提
- 使用的输入：
  - [docs/thread-retrieval-report.md](/data/zyq/yushu/docs/thread-retrieval-report.md)
  - [data/evals/ppt_company_p0_8.json](/data/zyq/yushu/data/evals/ppt_company_p0_8.json)
  - [data/evals/ppt_company_p1_8.json](/data/zyq/yushu/data/evals/ppt_company_p1_8.json)
  - retrieval 已阻塞题归因：`route_conflict / grounding_insufficient / coverage_insufficient`
- 依赖是否满足：
  - 满足。本轮只消费 retrieval 已在正式运行态明确放行的 4 题。
- 是否存在环境不确定项：
  - 存在。`scripts/run_eval.py` 仍受 `EVAL_API_BASE_URL=http://127.0.0.1:8000` 未启动影响，不能作为本轮正式证据入口。
  - 因此本轮证据来自仓库内正式 `chat_service` 直连复跑，而不是 HTTP eval 入口。

四、验证与证据
- 跑了什么：
  - 首轮正式 `chat_service.answer(...)` 复跑，观察最终 `answer / grounded / reviewer_intervened / fallback_used / review_issues`。
  - 定点单测：
    - `./.venv/bin/pytest tests/test_api_flow.py -q -k "company_ppt_factoid_and_enumeration_boundaries or compact_factoid_and_enumeration_answers or deterministic_review_flags_overlong_factoid_draft or finalize_answer_strips_question_echo or finalize_answer_normalizes_frequency_factoid"`
  - 修补后再次对 4 题做正式链路复跑。
- 结果是什么：
  - 首轮复跑暴露 3 类答案侧偏差：
    - `ppt-company-p0-02`：事实题会追加“成就职业教育未来”这类宣传性补句。
    - `ppt-company-p0-07`：枚举题会把“服务模块”答成“方案总述 + 服务模块”混合答案。
    - `ppt-company-p1-06`：定位事实题在云端生成缺口下会退回过长 extractive fallback。
  - 收口修补后，定点单测结果为 `5 passed`。
  - 最新正式复跑结果：
    - `ppt-company-p0-02`：`轩辕网络深耕教育28年，专注产教融合方向。`
    - `ppt-company-p0-07`：`包括人才培养服务、师资培养服务、教学资源开发服务、科学研究服务`
    - `ppt-company-p1-03`：`包括数智技术实践中心、产业技术及应用展厅、AIGC实战平台、AIGC赋能中心`
    - `ppt-company-p1-06`：`是，战略定位页把轩辕网络定义为AI+产教融合服务商。`
  - 最新 4 题共同状态：
    - `grounded=true`
    - `fallback_used=false`
    - `reviewer_intervened=false`
    - `review_issues=[]`
- 关键日志 / 文件 / 产物位置：
  - [docs/thread-answer-minimal-eval.json](/data/zyq/yushu/docs/thread-answer-minimal-eval.json)
  - [app/services/llm.py](/data/zyq/yushu/app/services/llm.py)
  - [tests/test_api_flow.py](/data/zyq/yushu/tests/test_api_flow.py)

五、当前判断
- 本线程判断：
  - 这 4 道放行题当前已满足“答案侧最小闭环可稳定收口”。
  - 其中：
    - `ppt-company-p0-02`：事实题，稳定收口。
    - `ppt-company-p0-07`：枚举题，稳定收口。
    - `ppt-company-p1-03`：枚举题，稳定收口。
    - `ppt-company-p1-06`：事实题，稳定收口。
- 风险与限制：
  - 本轮 4 题里没有概括题，因此“概括题可否稳定收口”不能由本轮放行为正例推出。
  - 对概括题，当前仍应沿用 retrieval 已给出的 `grounding_insufficient` 阻塞结论，不在答案侧越权放开。
  - `grounded_answer` 仍可能保留较长证据摘录；但对外最终 `answer` 已收口为短答案，不影响本轮答案侧验收。
- 是否达到本轮验收标准：
  - 达到。
  - 事实题、枚举题、概括题的收口边界当前已清楚：
    - 事实题：允许短事实回答，但禁止顺手补宣传性拔高。
    - 枚举题：允许短枚举回答，但必须只列证据稳定覆盖的项，不把总述、标题、跨层内容混进去。
    - 概括题：本轮不放行；在证据不完整前继续阻塞，不得高确定性概括。

六、逐题结论
- `ppt-company-p0-02`
  - 题型：事实题
  - 当前结论：可稳定收口
  - 原因：`slide-3 / body` 已直接支持 `28年 + 产教融合`，修补后不再追加宣传性补句
- `ppt-company-p0-07`
  - 题型：枚举题
  - 当前结论：可稳定收口
  - 原因：`slide-20 / body` 已连续覆盖四项服务，修补后只列服务模块，不再混入方案总述
- `ppt-company-p1-03`
  - 题型：枚举题
  - 当前结论：可稳定收口
  - 原因：`slide-18 / body` 与 `slide-21 / body` 已稳定覆盖场地/平台项，修补后不再落成实训室类偏题答案
- `ppt-company-p1-06`
  - 题型：事实题
  - 当前结论：可稳定收口
  - 原因：`slide-16 / body` 已直接支持定位表达，修补后不再走过长 fallback，也不再拔高成“领先/第一”的对外结论

七、哪些问题属于答案策略，哪些需要回流 Retrieval
- 属于答案策略的问题：
  - 事实题附带宣传性补句
  - 枚举题把页标题/方案总述和目标项混写
  - 是/否事实题在 fallback 时变成过长摘抄
- 当前不需要回流 Retrieval 的原因：
  - 这 4 题在正式运行态下都已有稳定新 PPT 证据，且本轮修补后已能稳定短答
  - 因此这轮问题不是 `candidate miss / rerank miss / route_conflict`
- 仍应回流 Retrieval 的问题类型：
  - `route_conflict`
  - `grounding_insufficient`
  - `coverage_insufficient`
  - 也就是 retrieval 已阻塞、未放行的那些题；本线程没有改写这些边界

八、对三类题型的最终收口判断
- 事实题：
  - 本轮结论：可收口，但只允许“短事实 + 直接证据”表达
  - 当前样例：`ppt-company-p0-02`、`ppt-company-p1-06`
- 枚举题：
  - 本轮结论：可收口，但必须满足“枚举项本身在证据中稳定覆盖”，且答案只列项不带总述扩写
  - 当前样例：`ppt-company-p0-07`、`ppt-company-p1-03`
- 概括题：
  - 本轮结论：不可据此放行
  - 原因：本轮 4 题里没有概括题正例，且 retrieval 对 `ppt-company-p0-03 / p1-05` 仍标注为 `grounding_insufficient`

九、建议主线程下一步怎么安排
- 建议：
  - 可把 `WS-03` 当前轮目标记为 `pass`，但结论只限于“4 道放行题的答案侧最小闭环已稳定收口”。
- 需要谁接力：
  - `Thread-Eval` 可基于本汇报把 `interim` 模板升级一版，补入答案侧最终结论。
  - `Thread-Retrieval` 暂不需要对这 4 题回流。
- 是否允许进入下一闸门：
  - 允许。
  - 但下一闸门应是“能力判断层收口升级”，不是宣布正式全链路通过。

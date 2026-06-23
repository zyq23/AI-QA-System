# [THREAD REPORT]

- 线程名：`Thread-Infra`
- 对应 workstream：`WS-05 工程环境与 RAGFlow`
- 当前轮目标：对 `ragflow` 工作树缺失、`data/evals` 删除状态、evaluation running job 残留、当前本地链路与运行接口可信度做只读分级，给主线程可直接采用的清障顺序
- 输出类型：阶段统一汇报
- 结论状态：`revise`

## 1. 本轮只读检查范围

- Git 工作树与 gitlink / `.gitmodules` 状态
- `data/evals` 与 `data/runtime` 现状
- `data/runtime/app.db` 中 jobs 残留
- 当前配置默认值与 `.env` 运行配置
- admin / eval / retrieval / ragflow 相关代码路径
- 本地接口可达性

## 2. 已确认事实

### 2.1 环境问题

- `ragflow` 当前不是普通目录缺失，而是 Git 中保留了 gitlink，但仓库不存在有效 `.gitmodules` 映射。
  - 证据：`git ls-files --stage ragflow` 显示 `160000` gitlink。
  - 证据：`git submodule status --recursive` 直接报 `fatal: no submodule mapping found in .gitmodules for path 'ragflow'`。
- 工作区当前确实存在大面积评测资产删除状态。
  - 证据：`git status --short` 中 `data/evals/*.json` 与 `data/evals/results/*.json` 大量为 `D`。
  - 当前工作树下 `data/evals/` 只剩 `ppt_company_p0_8.json`、`ppt_company_p1_8.json` 和空的 `results/` 目录。
  - 量化：当前工作树总共有 `77` 条 Git 状态项，其中 `41` 条删除、`16` 条未跟踪；仅 `data/evals` 就占了 `42` 条状态项，其中 `40` 条删除、`2` 条未跟踪。
  - 量化：`HEAD` 中 `data/evals` 原本有 `40` 个文件，而当前工作树实际只剩 `2` 个文件，正式评测资产层当前只保留了约 `5%` 的文件数。
- 运行态数据库是 `data/runtime/app.db`，不是仓库根的 `data/app.db`。
  - 证据：[app/config.py](/data/zyq/yushu/app/config.py:28) 默认 `database_path=Path("data/runtime/app.db")`。
  - 证据：`data/app.db` 里甚至没有 `jobs` 表；`data/runtime/app.db` 才有完整业务表。
- 运行态 `jobs` 中当前存在 1 条残留 `running` evaluation job。
  - 证据：`SELECT count(*) ...` 结果为 `71|7|1`，即总 job 71、evaluation 7、running evaluation 1。
  - 证据：残留 job 为 `3eaefc2254424bd6857f756b70716356`，状态 `running`，创建时间 `2026-05-28T06:47:05.865108+00:00`，数据集仍指向 `data/evals/knowledge_base_eval_cases.json`。
- admin 侧“latest eval”当前会被这条残留 `running` job 污染。
  - 证据：[app/repositories.py](/data/zyq/yushu/app/repositories.py:375) 的 `list_jobs()` 按 `updated_at DESC` 返回。
  - 证据：[app/routers/api_admin.py](/data/zyq/yushu/app/routers/api_admin.py:122) 和 [app/routers/api_admin.py](/data/zyq/yushu/app/routers/api_admin.py:170) 都是 `next((job for job in jobs if job["job_type"] == "evaluation"), None)`，不会过滤 `status=completed`。
- 当前正式运行配置仍显式启用 `ragflow/hybrid` 路线。
  - 证据：`.env` 中 `RETRIEVAL_BACKEND=ragflow`、`RETRIEVAL_MODE=hybrid`、`RAGFLOW_PREFER_LOCAL_GROUNDED=true`、`RAGFLOW_LOCAL_GROUNDED_SCORE_THRESHOLD=0.15`、`RAGFLOW_BASE_URL=http://127.0.0.1:9380`。
  - 证据：[app/main.py](/data/zyq/yushu/app/main.py:54) 起，`RETRIEVAL_BACKEND=ragflow` 时会构建 `RagflowRetrievalService`，并在满足条件时走 `AdaptiveRetrievalService`。
- `ragflow/` 工作树缺失会直接让当前仓库内的 RAGFlow 源码运维脚本失效，而不只是“少一个可选目录”。
  - 证据：`scripts/start_ragflow_source.sh`、`scripts/stop_ragflow_source.sh`、`scripts/setup_ragflow_source.sh` 都把 `${ROOT_DIR}/ragflow` 作为必需根目录，并依赖其中的 `.venv`、`docker/`、`api/ragflow_server.py`、`rag/svr/task_executor.py`。
  - 这意味着只要 `ragflow/` 不在工作树里，当前 README 中“源码跑后端 + Docker 跑依赖”的恢复路线就无法执行。
- 当前本地 HTTP 服务并没有在 `127.0.0.1:8000` 监听。
  - 证据：`curl http://127.0.0.1:8000/api/admin/documents` 连接失败。
  - 证据：`ps -ef` 未见当前仓库对应的 `uvicorn app.main:app` 进程。
- 当前 `9380` 与 `6380` 并非都不可达，因此“RAGFlow 服务完全未起”不是准确表述。
  - 证据：socket 探针显示 `127.0.0.1:8000 closed`，但 `127.0.0.1:9380 open`、`127.0.0.1:6380 open`。
  - 证据：`curl http://127.0.0.1:6380/healthz` 返回 `{"ok":true,"model_dir":"/data/zyq/yushu/data/models/BAAI__bge-m3"}`。
  - 证据：`curl http://127.0.0.1:9380/api/v1/datasets?...` 可返回 `yushu-kb-local`；对 `.env` 中配置的 dataset id 发 `/api/v1/retrieval` 也能拿到有效响应。
- 这意味着当前真正不可信的不是“RAGFlow 完全不可达”，而是“仓库内缺失 `ragflow/` 工作树，无法证明当前 9380 上跑着的服务与本仓库源码位一致”。
  - 当前更准确的定性应是：“外部 RAGFlow 服务可达，但本仓库源码运维链路失配”。
- 因为 `EVAL_API_BASE_URL=http://127.0.0.1:8000`，所以正式 eval API 入口在当前时刻不可用。
  - 证据：[app/services/evaluation.py](/data/zyq/yushu/app/services/evaluation.py:89) 的 `_ask_via_api()` 依赖 `eval_api_base_url`。
  - 证据：当前 `127.0.0.1:8000` 无服务。
- 但正式评测并非只能依赖 HTTP 服务；当前实现本身同时支持“API 模式”和“脱机直连模式”。
  - 证据：[app/services/evaluation.py](/data/zyq/yushu/app/services/evaluation.py:329) 起，`self.settings.eval_api_base_url` 存在时走 `_ask_via_api()`，否则直接走 `self.chat_service.answer(...)`。
  - 证据：[scripts/run_eval.py](/data/zyq/yushu/scripts/run_eval.py:28) 通过 `build_container()` 直接调用 `container.evaluation_service.run(...)`，并不强制要求 HTTP 服务存在。
  - 因此当前“正式 eval 不可用”的直接原因是：环境把评测路线切到了 `127.0.0.1:8000`，且该服务此刻没启动；不是评测框架本身已经失去脱机能力。
- 宿主 Python 环境与仓库 `.venv` 当前并不等价。
  - 证据：宿主 `python` 直接导入 `app.config` 会报 `ModuleNotFoundError: pydantic_settings`。
  - 证据：`./.venv/bin/python` 可正常读取 `Settings`，并能成功 `build_container()`；容器内当前实际组装的是 `AdaptiveRetrievalService`，且 `ragflow_sync_service_present=True`。
  - 因此后续线程若不用 `.venv` 跑探针，很容易把“宿主缺依赖”误判成“项目环境损坏”。

### 2.2 不应误判为算法问题的现象

- `ragflow` 工作树缺失与 `.gitmodules` 失配，属于工程环境失配，不应直接解释成远端检索算法退化。
- `9380` 可达但 `ragflow/` 工作树缺失，属于“外部服务可达 / 仓库源码不可核对”的映射失配，不应被误写成“本仓库里的 RAGFlow 已恢复到可维护状态”。
- `latest eval` 被 `running` job 污染，属于 jobs 状态管理问题，不应解释成“最近一次正式评测失败”。
- `data/evals` 历史资产删除，属于评测入口不完整，不应解释成“新 PPT 一定让旧能力回归失败”。
- `127.0.0.1:8000` 未启动导致 eval API 不可用，属于服务未启动，不应解释成“应用代码当前不可运行”。
- 宿主 `python` 缺依赖但 `.venv` 正常，属于执行环境选择问题，不应解释成“仓库虚拟环境不可用”。

## 3. 分级判断

### P0：会阻塞正式验收

- `data/evals/knowledge_base_eval_cases.json` 已不在工作树，默认正式评测入口不可直接复用。
- `latest evaluation` 取值会命中残留 `running` job，正式评测“最新结果”视图不可信。
- `EVAL_API_BASE_URL` 指向的本地服务当前未启动，基于 HTTP 的 eval 执行入口此刻不可用。
- `ragflow/` 源码位缺失会阻塞 README 记录的那条源码运维/恢复路径，导致与该路径绑定的验证动作当前无法执行。
- `ragflow` gitlink / 映射失配尚未澄清前，任何正式 `ragflow` 现象都不能作为正式能力结论证据。
- `data/evals` 删除面已是整层级别，不适合把任何当前回归现象包装成“默认正式评测入口基本还在”。

### P1：不阻塞当前方向判断，但影响效率/排障

- 工作树脏状态很重，`__pycache__`、文档更新、诊断产物、新旧线程改动混在一起，会增加后续审阅成本。
- `data/runtime/` 下存在 `server.log`、`web.log`、`uvicorn.out` 等残留日志，但当前日志内容对本轮没有直接阻塞证据。
- README 仍把 `data/evals/knowledge_base_eval_cases.json` 写成默认验收集，会让后来线程误以为默认评测入口仍可直接用。
- README 仍把“启动 RAGFlow 源码服务”写成现成路径，但当前工作树缺少 `ragflow/` 根目录，会让后来线程误以为只要执行脚本就能恢复。
- 宿主环境与仓库 `.venv` 有明显分离；若后续线程直接用系统 `python` 复现，只会引入额外噪声。

### P2：当前可视为已知前提，不必先清

- 本地模型目录和本地 Chroma / SQLite 运行态都在，说明“本地链路完全缺基础资源”这一风险当前没有证据支持。
- 当前 `data/runtime/app.db` 中已有完整历史文档、chunk、jobs 结构，说明仓库不是空壳环境。
- 当前 RAGFlow 相关外部依赖并非全灭：`9380` API 与 `6380/healthz` 都有响应，说明“远端服务可达性”与“源码位可维护性”必须分开判断。

## 4. 对其它线程的影响

### 哪些会阻塞正式验收

- `Thread-Eval`
  - 会被默认数据集缺失、latest eval 污染、API 未启动三件事同时阻塞。
- `Main-Thread`
  - 不能依据当前 admin latest eval 或历史 eval 入口直接给“正式 pass”。
- 任意线程涉及 `ragflow` 远端现象时
  - 当前都只能记“环境/路由现象位”，不能当正式能力证据。

### 哪些不阻塞当前方向判断

- `Thread-Parser`
  - 继续做 parse-only、OCR、块形态诊断不依赖 `ragflow` 工作树恢复。
- `Thread-Retrieval`
  - 继续做本地隔离副本能力判断仍然可信，但正式 `ragflow/hybrid` 现象只能做风险位记录。
- `Thread-Answer`
  - 继续固化回答约束和降级模板不受当前环境残留直接阻塞。

## 5. 当前链路可信度矩阵

| 组件 / 接口 | 当前状态 | 可信度 | 可直接用于什么 | 当前不能据此得出什么 |
| --- | --- | --- | --- | --- |
| `data/runtime/app.db` 运行态 DB | 存在，且可正常读到 `6` 份文档、`71` 条 jobs | `高` | 用于判断当前本地运行态、documents/jobs/latest 污染情况 | 不能替代正式评测通过结论 |
| `data/chroma` / Chroma collection | 目录存在，collection 可读，当前 count=`3696` | `中` | 证明本地向量库不是空的，可支撑“本地链路仍有运行态资产” | 不能仅凭 count 推断新 PPT 已正式入链 |
| 本地源目录 / upload / results 目录 | 目录都存在 | `高` | 证明基础目录结构还在，可继续做只读审计和脱机链路排查 | 不能证明默认 eval 数据集仍存在 |
| `127.0.0.1:8000` FastAPI 管理 / 对外接口 | 当前端口拒绝连接 | `低` | 可直接判定 admin API / eval API / chat HTTP 入口此刻不可用 | 不能据此推断仓库代码不可启动，只能说明当前没有进程承载 |
| `127.0.0.1:9380` RAGFlow API | 端口可达，datasets / retrieval 都有响应 | `中` | 可确认外部 RAGFlow 服务在线、`.env` 中 dataset id 可被远端识别 | 不能证明当前仓库 `ragflow/` 源码位完整，也不能证明主线程可按源码脚本恢复 |
| `127.0.0.1:6380/healthz` 本地 embedding health | 返回 `ok=true` | `中` | 可确认 RAGFlow 侧至少有一条本地 embedding 依赖在工作 | 不能证明整个 RAGFlow 源码运维链闭环正常 |
| 正式 eval API 路线 | `EVAL_API_BASE_URL=http://127.0.0.1:8000`，但 8000 未启动 | `低` | 可明确标记“当前正式 HTTP 评测入口不可用” | 不能据此否定脱机直连评测能力 |
| 脱机 `build_container() + evaluation_service.run()` 路线 | `.venv` 下可正常 build container | `中` | 可作为“恢复正式评测的备选路线”与只读核查依据 | 在默认数据集缺失、latest eval 污染未清前，仍不能当正式验收结论入口 |

### 主线程可直接采用的矩阵口径

- `高可信`
  - `data/runtime/app.db`、目录结构存在性。
- `中可信`
  - 本地 Chroma 运行态、RAGFlow 外部 API 可达性、`.venv` 下脱机容器可构建。
- `低可信`
  - 8000 上的 HTTP 管理接口、当前正式 eval API 路线、latest eval 视图。

## 6. 推荐清障顺序

1. 先由主线程确认：`data/evals` 大面积删除和 `ragflow` 缺失是否属于用户有意保留的现场，而不是本线程可自行恢复的异常。
2. 在获得授权前提下，优先清 `latest eval` 污染源。
   - 最小动作是把残留 `running` evaluation job 做只读备份后改成终态，或改 latest 选择逻辑只认 `completed`。
   - 这一步影响正式验收判断最大。
3. 再确认正式评测入口要走哪条恢复路线。
   - 方案 A：恢复默认 `data/evals/knowledge_base_eval_cases.json` 及结果资产。
   - 方案 B：主线程正式接受“当前只保留新增 PPT 能力判断层素材，正式回归后补”。
   - 方案 C：在不恢复 8000 服务的情况下，改回脱机直连评测路径；这仍需要主线程确认是否允许改变当前环境口径，但它说明“先起服务”不是唯一恢复前提。
4. 然后再处理 `ragflow` 工作树 / 映射关系。
   - 先定性这是“废弃 gitlink 残留”还是“仍计划继续使用的源码位”。
   - 只有在主线程确认仍要保留源码运维路线时，才值得恢复工作树。
   - 在此之前，不建议仅凭 `9380` 可达就宣布“RAGFlow 已恢复”；当前更准确的表述应是“外部依赖在线，但源码位失配”。
5. 最后再看是否需要重启本地服务以恢复 `/api/admin/*` 与 eval API 的即时可验证性。
6. 后续线程若要继续做只读探针，优先统一到仓库 `./.venv/bin/python` 下执行，避免把宿主缺依赖混进项目风险。

## 7. 是否建议主线程暂停某个线程动作

- 建议暂停：
  - `Thread-Eval` 的任何“正式验收 / 正式通过率”动作，直到 latest eval 与默认数据集入口被澄清。
- 不建议暂停：
  - `Thread-Parser` 的 parse-only / OCR 抽查。
  - `Thread-Retrieval` 的本地隔离诊断与现象位记录。
  - `Thread-Answer` 的规则收口。
- 有条件继续：
  - 所有涉及 `ragflow/hybrid` 的观察都继续允许做，但必须继续按“环境现象位”记录，不升级成能力结论。

## 8. 推荐主线程对外口径

- 环境问题：
  - `ragflow` 是 gitlink/映射失配。
  - `ragflow/` 缺失会让当前 README 记载的源码运维脚本整体失效。
  - `9380` / `6380` 当前可达，但这只能证明外部依赖在线，不能证明本仓库源码位可恢复。
  - `data/evals` 默认正式资产缺失。
  - latest eval 被一条 `running` job 污染。
  - eval API 当前没有服务承载，但评测框架本身仍保留脱机直连能力。
- 当前本地链路与运行接口可信度：
  - 本地 DB 和目录结构 `高可信`
  - 本地 Chroma / 外部 RAGFlow API / `.venv` 脱机容器 `中可信`
  - 8000 管理接口 / 当前正式 eval API / latest eval 视图 `低可信`
- 阻塞正式验收：
  - 是，当前正式评测入口和 latest 视图都不可信。
- 只影响效率不影响方向判断：
  - 是，Parser/Retrieval/Answer 仍可继续做能力判断层推进。
- 是否建议暂停某线程：
  - 仅建议暂停 `Thread-Eval` 的正式验收动作，不建议暂停其它线程的诊断性推进。

## 9. 相关证据文件

- [app/config.py](/data/zyq/yushu/app/config.py:28)
- [app/main.py](/data/zyq/yushu/app/main.py:54)
- [app/repositories.py](/data/zyq/yushu/app/repositories.py:375)
- [app/routers/api_admin.py](/data/zyq/yushu/app/routers/api_admin.py:122)
- [app/routers/api_admin.py](/data/zyq/yushu/app/routers/api_admin.py:170)
- [app/services/evaluation.py](/data/zyq/yushu/app/services/evaluation.py:89)
- [app/services/evaluation.py](/data/zyq/yushu/app/services/evaluation.py:329)
- [README.md](/data/zyq/yushu/README.md:163)
- [scripts/run_eval.py](/data/zyq/yushu/scripts/run_eval.py:28)
- [scripts/start_ragflow_source.sh](/data/zyq/yushu/scripts/start_ragflow_source.sh:1)

## 10. 正式验收补件恢复专项追加结论（2026-06-17）

- 当前轮目标：在不直接恢复子模块、不改写数据库、不恢复数据集的前提下，给主线程一条可执行的“正式验收补件恢复”最小路径。
- 结论状态：`review`

### 10.1 先纠偏的现场漂移

- 上轮“`data/evals` 大面积删除”结论当前需要改写为更准确口径：
  - 当前 `git status --short` 已不再显示 `data/evals/*` 的批量删除。
  - 但 `git ls-tree --name-only -r HEAD data/evals` 也只剩 `data/evals/ppt_company_p0_8.json` 与 `data/evals/ppt_company_p1_8.json`。
  - 这说明问题不再只是“工作树删除未恢复”，而是“当前仓库基线本身已经不再携带默认正式评测集与历史结果资产”。
- 上轮“`9380 / 6380` 可达”结论当前也需要降级：
  - 本轮 `curl` 对 `127.0.0.1:8000`、`127.0.0.1:9380`、`127.0.0.1:6380` 均连接失败。
  - 因此当前时刻更准确的口径是：“本地 HTTP 管理入口与此前可见的外部 RAGFlow 相关端口此刻都不可用”；不能继续把“RAGFlow 外部服务可达”写成当前事实。
- `ragflow` 缺失状态仍成立：
  - 仓库根下没有 `.gitmodules` 文件。
  - `git ls-files --stage ragflow` 当前无输出，说明这轮工作树里也没有可核对的 `ragflow` 跟踪项。
  - 对主线程的实际含义不变：当前仓库内没有可直接复用的 `ragflow/` 源码工作树与映射关系，源码运维路径仍不可作为当前恢复入口。

### 10.2 哪些是环境问题

- 默认正式评测入口仍指向 `data/evals/knowledge_base_eval_cases.json`，但当前仓库基线没有这个文件。
  - 证据：[app/config.py](/data/zyq/yushu/app/config.py:30)、[scripts/run_eval.py](/data/zyq/yushu/scripts/run_eval.py:18)、[README.md](/data/zyq/yushu/README.md:183)、[app/templates/partials/admin_shell.html](/data/zyq/yushu/app/templates/partials/admin_shell.html:30)
- `latest eval` 仍会被残留 `running` job 污染。
  - 证据：`data/runtime/app.db` 中最新 evaluation job 仍是 `3eaefc2254424bd6857f756b70716356 / running / dataset=data/evals/knowledge_base_eval_cases.json`
  - 证据：[app/repositories.py](/data/zyq/yushu/app/repositories.py:375) 与 [app/routers/api_admin.py](/data/zyq/yushu/app/routers/api_admin.py:124) 仍按“最新 evaluation job”直接取 latest，不筛 `completed`
- `.env` 仍把正式评测入口绑定到 HTTP。
  - 证据：`.env` 中 `EVAL_API_BASE_URL=http://127.0.0.1:8000`
- 当前 8000 管理口、9380、6380 端口都未提供服务。
  - 这属于运行态未起或已退出，不应混写成检索/回答能力退化。
- 当前正式运行库仍是 `data/runtime/app.db`，而不是 `data/app.db`。
  - 本轮 `jobs` 统计更新为：总 job `78`、evaluation `7`、running evaluation `1`

### 10.3 哪些会阻塞正式验收

- 会阻塞：
  - 默认正式数据集路径失效。
  - `latest eval` 视图被 `running` job 污染。
  - 当前 HTTP eval 入口不可达。
  - 当前仓库没有可直接复用的 `ragflow/` 源码恢复路径。
- 不应据此直接下的业务结论：
  - 不能说“新增 PPT 正式通过率不可算”是因为算法退化。
  - 只能说“正式验收入口与历史补件当前不完整”。

### 10.4 哪些只影响效率，不影响当前方向判断

- 工作树当前仍较脏，评审成本高，但不阻塞本轮给恢复建议。
- 宿主 Python 与仓库 `.venv` 不等价，后续若用宿主环境复现仍会引入噪声。
- `README`、admin 表单、`run_eval.py`、`Settings.eval_dataset_path` 对默认评测集的指向已经与当前仓库基线脱节，会增加后来线程误判成本。

### 10.5 正式验收补件恢复顺序建议

1. 先冻结口径，不先恢复数据。
   - 由主线程先明确：当前仓库基线只保留 `ppt_company_p0_8.json` 与 `ppt_company_p1_8.json` 是有意收缩，还是一次未完成的历史资产迁移。
   - 在未确认前，不建议任何线程擅自把“恢复历史 eval 文件”当成默认动作。
2. 先处理 `latest eval` 污染，而不是先追服务。
   - 这是影响主线程读数和后续线程误判最大的公共阻塞。
   - 如果不先处理，即使后面恢复入口，admin latest 仍可能继续显示伪“最新运行中”。
3. 再决定正式 eval 入口路线。
   - 若主线程只要求“最小可恢复正式验收入口”，优先建议脱机直连。
   - 若主线程要求“恢复既有 UI / HTTP 操作流”，才继续把 8000 入口与 admin 表单一起纳入恢复范围。
4. 再决定 `data/evals` 走“恢复历史资产”还是“正式冻结重建”。
   - 这是资产策略决策，不宜在 latest 污染未清时先做。
5. `ragflow` 最后处理。
   - 当前它既不是本轮正式验收补件的最小前置，也缺少可直接恢复的源码工作树。
   - 只有主线程明确要恢复“源码位一致性/源码运维链”时，才值得单独立项。

### 10.6 `latest eval` 污染最小处理方案

- 推荐最小方案：先改 latest 读取逻辑，只认 `job_type="evaluation" and status="completed"`。
  - 优点：
    - 不改 DB 历史状态。
    - 可保留那条 `running` job 作为现场证据。
    - 对主线程“读 latest 结论”最直接。
  - 风险：
    - 需要代码改动与回归验证。
    - admin 页面“正在运行的评测”若未来真有需要，需另行展示。
- 备选方案：在得到用户/主线程授权后，把残留 job 从 `running` 改成明确终态，并保留只读备份。
  - 优点：
    - 可以一次性清掉 DB 污染源。
  - 风险：
    - 属于直接改写数据库状态。
    - 未经授权本线程不能执行。
- 当前建议：
  - 主线程若只想最小恢复“latest eval 可读性”，优先选“代码侧 completed 过滤”。
  - 主线程若更在意运维账实一致，再单独申请 DB 更正授权。

### 10.7 `data/evals` 历史资产恢复 / 冻结策略建议

- 结论建议：当前优先推荐“先冻结、后决策”，而不是默认“立即恢复历史资产”。
- 原因：
  - 当前 `HEAD` 自身就只包含 2 个新增 PPT 能力判断数据集，说明历史资产缺失不再只是工作树脏状态。
  - 若直接恢复旧资产，等于主线程默认接受“继续沿用旧正式回归集”；这已经超出纯环境修复，属于评测资产路线决策。
- 可选策略：
  - 策略 A：历史资产恢复
    - 适用：主线程明确要恢复旧正式回归口径。
    - 需要用户/主线程批准的动作：
      - 从历史提交、外部备份或其他来源恢复 `knowledge_base_eval_cases.json` 与历史结果模板。
  - 策略 B：正式冻结旧资产，改以“新增 PPT 单组 + 旧资料最小回归集”重建
    - 适用：主线程接受当前仓库进入新的正式验收基线。
    - 需要主线程决策：
      - 哪些旧题必须作为最小回归保留。
      - 当前 2 个 PPT 数据集如何从能力判断素材升级为正式验收素材。
- 当前建议主线程采用的默认口径：
  - “在资产策略未定前，`data/evals` 当前仅可作为新增 PPT 能力判断素材来源，不可包装成已恢复的正式总验收集。”

### 10.8 正式 eval 入口应走 HTTP 还是脱机直连

- 当前结论建议：正式验收补件恢复的第一条可用入口，应优先走“脱机直连”，不是 HTTP。
- 原因：
  - 当前 `.env` 绑定的 HTTP 入口 `127.0.0.1:8000` 不可达。
  - [app/services/evaluation.py](/data/zyq/yushu/app/services/evaluation.py:350) 已明确支持 `eval_api_base_url` 为空时直连 `chat_service.answer(...)`。
  - [scripts/run_eval.py](/data/zyq/yushu/scripts/run_eval.py:28) 也是直接 `build_container()` 调评测服务。
  - 对“正式验收补件恢复”来说，先恢复一个可验证入口，比先恢复 Web 服务更小、更稳。
- 这不等于：
  - HTTP 路线被废弃。
  - 8000 服务不再需要。
- 更准确的主线程口径：
  - “短期正式验收补件优先恢复脱机直连入口；若后续需要恢复 admin/UI 操作流，再补 HTTP。”

### 10.9 哪些动作需要主线程或用户批准，哪些可以只读完成

- 可以只读完成：
  - 继续核对 `data/runtime/app.db`、jobs、配置、代码入口是否漂移。
  - 继续判断默认评测路径、admin latest 逻辑、脱机直连路径是否一致。
  - 继续形成恢复顺序、风险等级、暂停建议。
- 需要主线程批准：
  - 选择 `data/evals` 走“历史恢复”还是“冻结重建”。
  - 决定正式验收短期以脱机直连为准，还是同步追 HTTP/admin 恢复。
  - 决定是否把 `latest eval` 修复优先级放在所有公共阻塞最前。
- 需要用户明确授权后才能执行：
  - 改写 `data/runtime/app.db` 中残留 job 状态。
  - 从历史提交或外部来源恢复数据集文件。
  - 恢复 `ragflow` 子模块/源码工作树。

### 10.10 是否建议主线程暂停某个线程动作

- 建议暂停：
  - `Thread-Eval` 的任何“正式通过率 / latest eval 读取 / admin 正式验收口”动作。
- 不建议暂停：
  - `Thread-Eval` 的模板设计与补件字段设计。
  - `Thread-Parser`、`Thread-Retrieval`、`Thread-Answer` 的只读支持或能力判断层补口径。

### 10.11 主线程可直接采用的一句话结论

- 当前最小恢复路径不是“先把所有环境都起起来”，而是：
  - 先修 `latest eval` 读数污染，
  - 再由主线程决定 `data/evals` 是恢复旧资产还是冻结重建，
  - 同时把正式 eval 的短期入口切到脱机直连，
  - 最后才考虑 HTTP/admin 与 `ragflow` 源码位恢复。

## 11. `latest eval` completed 过滤落地与验证（2026-06-17）

- 当前轮目标：围绕 `latest eval` 读数污染，落地代码侧 `completed` 过滤的最小实现与验证。
- 结论状态：`review`

### 11.1 最小代码改动

- 在 [app/repositories.py](/data/zyq/yushu/app/repositories.py:389) 新增 `Repository.latest_job(...)`：
  - 直接按 `job_type` 和可选 `status` 从 DB 定向查询 `ORDER BY updated_at DESC LIMIT 1`
  - 仍沿用现有 `payload_json / result_json` 反序列化方式
- 在 [app/routers/api_admin.py](/data/zyq/yushu/app/routers/api_admin.py:124) 的 `build_admin_context()` 中：
  - 把原先“从 `list_jobs(limit=20)` 结果里取第一条 evaluation job”改为
  - `container.repository.latest_job(job_type="evaluation", status="completed")`
- 在 [app/routers/api_admin.py](/data/zyq/yushu/app/routers/api_admin.py:170) 的 `_latest_evaluation_job()` 中：
  - 同样改为直取最新 `completed` evaluation job
- 没有改动：
  - `data/runtime/app.db`
  - `data/evals/*`
  - HTTP/admin 启动链路
  - `ragflow` 相关路径

### 11.2 为什么不是只在 `list_jobs()` 结果上过滤

- 本轮实测确认：只在 `list_jobs(limit=20)` 的结果上做 `status=completed` 过滤并不够。
- 原因是：
  - 当前 runtime DB 里最近 20 条 job 主要是 `ingest_document / reindex_document`
  - 最新 completed evaluation `bc34a60dfc824656ad3a44f0199ba898` 排位已经落到这 20 条之外
  - 若先 `LIMIT 20` 再过滤，会把 latest eval 直接过滤成 `None`
- 所以最小可信修法必须是：
  - latest eval 相关路径直接定向查 `job_type='evaluation' AND status='completed'`
  - 不能继续复用截断后的通用 job 列表做二次筛选

### 11.3 影响到的代码路径说明

- 影响路径仅限 latest eval 读取：
  - admin 页面上下文 `build_admin_context()`
  - admin 侧 failed-only eval 入口与表单入口共用的 `_latest_evaluation_job()`
- 不影响：
  - `/api/admin/jobs` 的通用 job 列表展示
  - evaluation job 创建/更新逻辑
  - database schema
  - 正式 eval 执行入口本身

### 11.4 验证证据

- 定点测试：
  - `./.venv/bin/pytest tests/test_api_flow.py -q -k "repository_latest_job_skips_running_evaluation_with_newer_non_eval_jobs or admin_can_run_failed_eval_job"`
  - 结果：`2 passed`
- 新增测试覆盖：
  - [tests/test_api_flow.py](/data/zyq/yushu/tests/test_api_flow.py:181)
  - 场景：`running` evaluation 存在、且其后还有更新的非 evaluation jobs 时，`latest_job(job_type="evaluation", status="completed")` 仍能取到最新 completed evaluation
- 当前 runtime DB 的只读验证：
  - `latest_any = 3eaefc2254424bd6857f756b70716356 / running / data/evals/knowledge_base_eval_cases.json`
  - `latest_completed = bc34a60dfc824656ad3a44f0199ba898 / completed / data/evals/knowledge_base_eval_cases.json`
  - 这说明代码侧纠偏已经满足“latest eval 不再命中 running job”的目标

### 11.5 当前边界与主线程口径

- 当前可以说：
  - latest eval 读数纠偏已在代码侧完成，且不再命中 `running` evaluation job
- 当前不能说：
  - 正式 eval 入口已整体恢复
  - 历史数据集已恢复
  - 正式验收已经可以执行

## 12. 全知识库最小回归执行前入口与 Checklist（2026-06-17）

- 当前轮目标：为下一轮“全知识库最小回归”提供一个可信、最小、可执行的环境入口与 checklist。
- 结论状态：`review`

### 12.1 当前正式最小入口可信度说明

- 当前继续推荐的短期正式入口仍是 `offline_direct_eval`。
- 原因有 4 个：
  - [scripts/run_eval.py](/data/zyq/yushu/scripts/run_eval.py:25) 直接 `build_container()` 后调用 `evaluation_service.run(...)`，不依赖 `127.0.0.1:8000`
  - [app/services/evaluation.py](/data/zyq/yushu/app/services/evaluation.py:350) 明确是“有 `eval_api_base_url` 才走 HTTP；否则直连 `chat_service.answer(...)`”
  - 当前 `data/runtime/app.db`、`data/evals/results/`、仓库 `.venv`、模型目录都存在，可支撑脱机直连执行
  - 当前 `8000` 连接失败，因此先绑定 HTTP/admin 只会把最小回归入口重新绑回不可信路径
- 为什么当前不建议先绑定 HTTP/admin：
  - 当前 `.env` 仍配置 `EVAL_API_BASE_URL=http://127.0.0.1:8000`
  - 但本轮 `curl http://127.0.0.1:8000/api/admin/documents` 仍连接失败
  - 若直接用当前环境变量执行 `scripts/run_eval.py`，`EvaluationService` 会优先走 HTTP 模式，而不是脱机直连
  - 因此“短期正式最小入口可用”的准确口径不是“直接用当前 `.env` 跑”，而是“显式清空 `EVAL_API_BASE_URL` 后走脱机直连”
- `latest eval` 当前是否仍可信：
  - `是`
  - 但这个“可信”仅限于“latest eval 读数不再命中 `running` evaluation job”
  - 其可信依据是：
    - [app/repositories.py](/data/zyq/yushu/app/repositories.py:389) 已提供 `latest_job(job_type='evaluation', status='completed')`
    - [app/routers/api_admin.py](/data/zyq/yushu/app/routers/api_admin.py:125) 与 [app/routers/api_admin.py](/data/zyq/yushu/app/routers/api_admin.py:171) 已切到 latest completed evaluation
    - runtime 只读验证仍显示：
      - `latest_any = 3eaefc2254424bd6857f756b70716356 / running`
      - `latest_completed = bc34a60dfc824656ad3a44f0199ba898 / completed`

### 12.2 全知识库最小回归执行前 Checklist

#### A. 必须确认的运行入口

- `blocker`
  - 必须明确本轮入口为 `offline_direct_eval`
  - 必须显式清空 `EVAL_API_BASE_URL`
- 推荐执行口径：
  - `EVAL_API_BASE_URL= ./.venv/bin/python scripts/run_eval.py --dataset <frozen_full_kb_dataset>.json --output-dir data/evals/results`
- 说明：
  - 当前 plain `./.venv/bin/python scripts/run_eval.py ...` 在继承 `.env` 时会走 HTTP 模式，不应直接视为当前最小正式入口

#### B. 必须确认的数据路径

- `blocker`
  - 必须确认待执行数据集文件已经冻结且实际存在于 `data/evals/`
  - 当前仅已确认存在：
    - [data/evals/ppt_company_single_group_formal_v1.json](/data/zyq/yushu/data/evals/ppt_company_single_group_formal_v1.json)
  - “全知识库最小回归集”对应冻结数据集当前仍未在工作树落地，因此在它生成前，不应直接宣称“全库最小回归现在就能开跑”
- `non-blocker`
  - `data/evals/ppt_company_p0_8.json` 与 `data/evals/ppt_company_p1_8.json` 仍可作为历史能力判断素材参考，但不应被误当成下一轮全库正式冻结集

#### C. 必须确认的运行时数据库 / 结果目录

- `blocker`
  - 必须确认 runtime truth source 仍是 `data/runtime/app.db`
  - 必须确认 `data/evals/results/` 目录可写且存在
- 当前已确认：
  - `data/runtime/app.db` 存在
  - `data/evals/results/` 存在
  - 当前运行态可读到 `7` 份已入链文档
- `non-blocker`
  - `data/app.db` 仍不是当前仓库运行态判断依据；只要不误用它，就不构成最小回归 blocker

#### D. 必须确认的 Python 环境

- `blocker`
  - 必须使用仓库 `.venv`
  - 当前应以 `./.venv/bin/python` 为唯一推荐执行入口
- 当前已确认：
  - `.venv/bin/python` 存在
  - `build_container()` 可在 `.venv` 下正常读取 `Settings`
- `non-blocker`
  - 宿主 `python` 与仓库 `.venv` 仍不等价；这是风险提示，不是 `.venv` 入口本身的 blocker

#### E. 必须确认的 latest eval 读数

- `blocker`
  - 在执行前必须确认 latest eval 仍走 latest completed 读取逻辑
- 当前已确认：
  - repository 与 admin 侧 latest eval 读取都已切到 latest completed evaluation
  - 当前 latest completed eval 为 `bc34a60dfc824656ad3a44f0199ba898 / completed`
- `non-blocker`
  - DB 中残留的 `running` evaluation job 仍存在，但只要代码侧 latest completed 过滤保持稳定，就不阻塞“全知识库最小回归”的脱机执行

### 12.3 哪些项是 blocker，哪些只是风险提示

#### Blocker

- 尚未冻结并落地“全知识库最小回归集”数据文件
- 执行时若不显式清空 `EVAL_API_BASE_URL`，会被当前 `.env` 重新带回 HTTP 模式
- 若不用仓库 `.venv`，则执行环境不可信
- 若误把 `data/app.db` 当运行态真相源，会导致执行前 readiness 判断失真

#### 仅风险提示，不阻塞当前最小回归

- `127.0.0.1:8000` 仍未恢复
- HTTP/admin 全链路仍未恢复
- `ragflow` 子模块 / 源码位仍失配
- DB 中仍残留一条 `running` evaluation job
- `.env` 默认评测集路径仍指向 `data/evals/knowledge_base_eval_cases.json`

### 12.4 主线程可直接采用的环境边界说明

- 当前不影响“全知识库最小回归”最小执行的问题：
  - HTTP/admin 未恢复
  - `ragflow` 源码位未恢复
  - DB 中残留 `running` eval job 仍在
  - 历史旧 `data/evals` 总资产未恢复
- 当前若不解决，会影响后续更大范围正式验收的问题：
  - 全库回归集尚未冻结成实际数据文件
  - `run_eval.py` 仍默认继承 `.env` 中的 HTTP 入口，需要靠执行命令显式清空 `EVAL_API_BASE_URL`
  - `Settings.eval_dataset_path` 仍默认指向缺失的 `data/evals/knowledge_base_eval_cases.json`
  - `EvaluationService` 与正式模板的 `must_block` 语义差异仍是更大范围正式验收的长期待补项

### 12.5 当前是否建议主线程允许后续跑“全知识库最小回归”

- 当前建议：
  - `有条件允许`
- 条件是：
  - 先由 `Thread-Eval` 把“全知识库最小回归集”冻结成实际数据文件
  - 执行命令明确采用 `offline_direct_eval`，并显式清空 `EVAL_API_BASE_URL`
  - 执行方明确使用仓库 `.venv`
- 当前不建议把以下事项当作前置：
  - 先恢复 HTTP/admin
  - 先恢复 `ragflow` 子模块或源码位
  - 先改写 DB 中残留 `running` job 状态

### 12.6 仍需用户授权的动作

- 当前这轮为“全知识库最小回归”准备入口与 checklist，不需要新增用户授权才能完成
- 但以下动作仍需用户明确授权：
  - 改写 `data/runtime/app.db` 中残留 `running` job 状态
  - 恢复 `ragflow` 子模块 / 源码位
  - 恢复历史 `data/evals` 总资产

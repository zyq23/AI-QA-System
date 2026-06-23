[THREAD REPORT]
线程名：Thread-Parser
对应 Workstream：WS-01 文档接入与解析
当前轮目标：补齐带 OCR 的关键页 parse-only 抽查，判定新增 PPT 是否达到“可进入入库前检查”的门槛
状态：review

一、这轮做了什么
- 新增只读 parse-only 检查脚本 `scripts/inspect_ppt_parse.py`，可对单个 PPT 输出页级摘要、关键页 block 预览和 chunk 预览，不触发入库。
- 扩展 `app/parsers/pptx_parser.py` 的占位模板过滤，新增 `Double click to edit`、`Replace me` 等通用变体识别。
- 在 `app/parsers/pptx_parser.py` 增加两轮 OCR 形态治理：单图片 OCR 片段压缩、整页图片墙 OCR 聚合。
- 补充 `tests/test_parsers.py` 回归测试，覆盖 placeholder 过滤、OCR 片段压缩、整页图片墙聚合和 parse-only 摘要统计。
- 生成两份本轮审计产物：
  - `docs/thread-parser-parse-only-no-ocr.json`
  - `docs/thread-parser-parse-only-with-ocr.json`
- 形成异常页清单 `docs/thread-parser-anomaly-list.md`。

二、为什么这么做
- 当前闸门要求是“带 OCR 关键页 parse-only 抽查 + 异常页清单 + 统一汇报”，而不是直接正式入库。
- 独立只读脚本能复用现有 parser/chunker，同时避免碰 ingestion、vector store、retrieval、answer 边界。
- 先把关键页真实 block/chunk 形态沉成产物，主线程和下游线程才能据此做可靠判断。

三、输入与前提
- 使用的输入：
  - `宇树科技知识库/【公司介绍】轩辕网络公司介绍202606.pptx`
  - 当前 `python-pptx + 图片 OCR + chunker` 主线
  - 首批关键页：`slide-21/33/48/70/74/79/80/89/90`
- 依赖是否满足：
  - 满足。仓库本地 `.venv` 可用于 parser 验证和 OCR 抽查。
- 是否存在环境不确定项：
  - 存在轻度 OCR 资源格式不确定项：`slide-27` 出现 `WMF` loader warning。
  - 但本轮未触发 RAGFlow / 正式评测环境依赖。

四、验证与证据
- 跑了什么：
  - `./.venv/bin/pytest tests/test_parsers.py -q`
  - `./.venv/bin/python scripts/inspect_ppt_parse.py "宇树科技知识库/【公司介绍】轩辕网络公司介绍202606.pptx" --slides 21,33,48,70,74,79,80,89,90 --json-out docs/thread-parser-parse-only-no-ocr.json`
  - `./.venv/bin/python scripts/inspect_ppt_parse.py "宇树科技知识库/【公司介绍】轩辕网络公司介绍202606.pptx" --enable-ocr-fallback --slides 21,33,48,70,74,79,80,89,90 --json-out docs/thread-parser-parse-only-with-ocr.json`
- 结果是什么：
- 回归测试 `21 passed`
- 无 OCR 基线：`91 slides / 1329 blocks / 633 chunks / 0 warnings`
  - 带 OCR：`91 slides / 2150 blocks / 1197 chunks / 1 warning`
  - `slide-33` 已从早前的 `255 blocks / 238 chunks` 收敛到 `54 blocks / 16 chunks`
  - `slide-79` 已从 `46 blocks / 31 chunks` 收敛到 `15 blocks / 4 chunks`，数字短噪声已被压掉
  - `slide-80` 已从 `125 blocks / 122 chunks` 收敛到 `55 blocks / 35 chunks`
  - `slide-56` 与 `slide-77` 这类图片墙页分别收敛到 `32/11` 和 `38/13`
  - 当前仅剩 `slide-27` 的 `WMF` OCR warning，以及少量组织图/Logo 弱语义 OCR 残留
- 关键日志 / 文件 / 产物位置：
  - `docs/thread-parser-parse-only-no-ocr.json`
  - `docs/thread-parser-parse-only-with-ocr.json`
  - `docs/thread-parser-anomaly-list.md`

五、当前判断
- 本线程判断：
  - parser 已通过“全文 parse-only 可跑完”的第一层结构门槛。
  - placeholder/template 残留已不再是主阻塞。
  - 当前主要风险已从“图片 OCR 大面积膨胀”收敛到“少量图片页残余 OCR 弱语义块与个别格式兼容 warning”。
- 风险与限制：
  - `slide-27` 仍存在 `WMF` 图片 OCR 兼容 warning。
  - `slide-74/89` 仍有中等强度的图片 OCR 补充块，需要在入库前检查阶段继续观察。
  - 本线程仍未触碰 ingestion 主链路，也未宣布正式入库。
- 是否达到本轮验收标准：
  - 已达到。满足“全文可跑完、关键页大多数可读、异常页少数且可点名、异常不属于必然大面积污染 chunk”。

六、建议主线程下一步怎么安排
- 建议：
  - 建议主线程将 Thread-Parser 记为 `pass` 或至少放行到“入库前检查”下一闸门。
  - 入库前检查阶段继续关注 `slide-27` 的 WMF warning、`slide-74/89` 的残余 OCR 弱语义块，以及是否会影响引用粒度。
- 需要谁接力：
  - 可由主线程放行给后续入库前检查；`WS-02/03/04` 可以把本轮产物当更稳定的上游输入。
- 是否允许进入下一闸门：
  - 是。

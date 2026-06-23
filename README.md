# 知识库 AI 问答系统

基于 `FastAPI + Jinja2/HTMX + SQLite FTS5 + ChromaDB` 的知识库问答系统。当前仓库面向你本地 `宇树科技知识库/` 里的现有资料工作，不依赖宇树 G1 官方资料。

## 主要能力

- 支持 `pdf / docx / pptx` 上传、解析、分块和本地持久化索引
- SQLite FTS5 + 向量检索 + RRF 融合 + reranker 重排
- 可选接入 `RAGFlow` 作为外部解析/检索底座，保留现有回答收口与评测链路
- 支持 OpenAI 兼容接口和讯飞 Spark X2 WebSocket 生成答案
- 默认展示来源引用、页码/页号和信任级别
- 管理台支持上传、目录导入、单文档重建索引、全量重建、停用文档
- 当前目录 `宇树科技知识库/` 可直接作为系统语料导入

## 环境要求

- Python `3.11`
- 推荐使用 `conda + uv`

## Conda 初始化

```bash
bash scripts/setup_conda_env.sh
conda activate yushu-qa
```

如果你已经在现有 conda 环境中工作，也可以直接执行：

```bash
uv sync --python 3.11 --inexact
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch
python -m pip install "transformers<5" FlagEmbedding
```

## 安装

```bash
uv sync --python 3.11 --inexact
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch
python -m pip install "transformers<5" FlagEmbedding
```

如果要启用 PaddleOCR 回退：

```bash
uv sync --python 3.11 --extra ocr
```

复制环境变量模板：

```bash
cp .env.example .env
```

至少建议配置：

```env
ADMIN_TOKEN=your-admin-token
LLM_PROVIDER=spark_ws
```

如果走 OpenAI 兼容接口：

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_API_KEY=your-key
LLM_MODEL=your-model
```

如果走讯飞 Spark X2 WebSocket：

```env
LLM_PROVIDER=spark_ws
SPARK_APP_ID=your-app-id
SPARK_API_KEY=your-api-key
SPARK_API_SECRET=your-api-secret
SPARK_API_BASE=wss://spark-api.xf-yun.com/x2
SPARK_MODEL=x2
SPARK_DOMAIN=spark-x
```

当前代码会按顺序读取 `.env` 和 `../qianliyan/.env`。如果 `../qianliyan/.env` 已经配置过 Spark 凭据，这里可以不重复填写。

如果要把 `RAGFlow` 接到现有系统中，作为检索后端：

```env
RETRIEVAL_BACKEND=ragflow
RAGFLOW_BASE_URL=http://127.0.0.1:9380
RAGFLOW_API_KEY=your-ragflow-api-key
RAGFLOW_DATASET_IDS=dataset_id_1,dataset_id_2
RAGFLOW_DOCUMENT_IDS=
RAGFLOW_SOURCE_MODE=false
RAGFLOW_SOURCE_ROOT=ragflow
RAGFLOW_FALLBACK_TO_LOCAL=true
```

说明：

- `RETRIEVAL_BACKEND=local` 时，继续使用当前 `SQLite FTS5 + ChromaDB` 本地检索。
- `RETRIEVAL_BACKEND=ragflow` 时，`/api/chat/query` 仍保持不变，只是底层证据改由 `RAGFlow /api/v1/retrieval` 提供。
- `RAGFLOW_FALLBACK_TO_LOCAL=true` 时，如果 `ragflow` 服务不可用或检索报错，会自动回退到本地索引，不会中断对外问答。
- 推荐先把 `ragflow` 用于“复杂文档解析、OCR、分块、检索”，继续保留当前系统的回答收口、双智能体质检和评测接口。
- `RAGFLOW_SOURCE_MODE` 和 `RAGFLOW_SOURCE_ROOT` 当前主要用于约定本机 `ragflow/` 源码服务位置，便于运维。

如果暂时没有本地 BGE 模型或云端 LLM，可先用：

```env
USE_STUB_ML=true
DISABLE_LLM=true
```

## 运行

```bash
uv run --python 3.11 uvicorn app.main:app --reload
```

访问：

- 问答页：`http://127.0.0.1:8000/`
- 管理页：`http://127.0.0.1:8000/admin?token=你的ADMIN_TOKEN`

## 机器人接入

如果 G1 EDU 端只需要“发问题、拿短答案播报”，直接接：

- `POST /api/robot/query`

请求示例：

```json
{
  "question": "系统在资料不足时应该怎么回答？",
  "conversation_id": null,
  "top_k": 6,
  "client_id": "g1-edu-dock",
  "voice_session_id": "optional"
}
```

响应示例：

```json
{
  "answer": "当前知识库没有直接证据时，系统会明确说明证据不足，不把推断当成事实。",
  "conversation_id": "5f0c7f4e-7a0d-4ef0-b18c-6d7bc3a8b4a2",
  "latency_ms": 812,
  "grounded": true,
  "should_speak": true,
  "tts_text": "当前知识库没有直接证据时，系统会明确说明证据不足，不把推断当成事实。",
  "answer_run_id": "c8b5d6f2-9f28-4d36-9f6d-6b6a2cf38a26",
  "question_type": "factoid",
  "answer_focus": "资料不足时的回答策略"
}
```

目录 [robot_bridge](robot_bridge/README.md) 里提供了一个最小 Python 示例，可直接用于机器人端 HTTP 桥接：

```bash
python robot_bridge/bridge.py --base-url http://127.0.0.1:8000
```

如果你要更接近 G1 EDU 端的落地接法，可以直接用：

```bash
python robot_bridge/g1_client.py --base-url http://127.0.0.1:8000
```

这个示例已经包含会话复用、打断后丢弃过期回答、`jsonl` 运行日志，适合后续嵌到你现有的 ASR/TTS 客户端里。

## 问答验收

仓库内已经提供一套基于当前 `宇树科技知识库/` 资料的测试集与验收脚本：

```bash
.venv/bin/python scripts/run_eval.py
```

默认测试集位置：

```text
data/evals/knowledge_base_eval_cases.json
```

执行后会生成带时间戳的报告到：

```text
data/evals/results/
```

## 导入本地知识库

方式一：管理台点击“导入本地知识库目录”。

方式二：命令行：

```bash
uv run --python 3.11 python -m app.cli bootstrap
```

## RAGFlow 集成建议

当前仓库已经支持把 `RAGFlow` 接成可选检索后端，适合逐步迁移：

1. 用 `ragflow/` 跑文档解析、OCR、分块和检索。
2. 把目标数据集 ID 配到 `RAGFLOW_DATASET_IDS`。
3. 保留现有 `/api/chat/query`、`/api/admin/evals/run`、`answer_runs` 质检留痕不变。

这样可以先用 `RAGFlow` 提升复杂文档召回能力，尤其是 PPT/PDF 图片知识点，再继续复用当前系统已经做好的机器人回答风格控制。

### 在当前机器上启动 RAGFlow 源码服务

当前环境下更推荐“源码跑后端 + Docker 只跑基础依赖”的方式，而不是直接拉 `infiniflow/ragflow` 主镜像。

1. 启动依赖并安装源码环境：

```bash
bash scripts/start_ragflow_source.sh
```

脚本会自动完成这些事情：

- 通过 `docker.m.daocloud.io` 代理镜像启动 `mysql/minio/redis/infinity`
- 下载 `en_core_web_sm` 轮子到 `ragflow/vendor/`
- 用 `uv` 创建 `ragflow/.venv`
- 启动 `rag/svr/task_executor.py` 和 `api/ragflow_server.py`

常用控制命令：

```bash
bash scripts/stop_ragflow_source.sh
```

服务日志位置：

```text
ragflow/logs/task_executor.log
ragflow/logs/ragflow_server.log
```

基础依赖 compose 覆盖文件：

```text
ragflow/docker/docker-compose-base.mirror.yml
```

如果 `RAGFlow` 启动成功，再把你创建好的 `dataset_id` 填到 `.env`：

```env
RETRIEVAL_BACKEND=ragflow
RAGFLOW_BASE_URL=http://127.0.0.1:9380
RAGFLOW_API_KEY=your-ragflow-api-key
RAGFLOW_DATASET_IDS=dataset_id_1
RAGFLOW_SOURCE_MODE=true
RAGFLOW_SOURCE_ROOT=ragflow
RAGFLOW_FALLBACK_TO_LOCAL=true
```

## 下载本地 BGE 模型

```bash
uv sync --python 3.11 --inexact
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch
python -m pip install "transformers<5" FlagEmbedding
uv run --python 3.11 python -m app.cli download-models
```

`download-models` 现在只下载运行所需文件，不再拉取整仓库的 `onnx`/图片等附加内容。这里刻意走 CPU 版 `torch`，避免 `uv` 默认把 CUDA 依赖一并装下来；后续如果再次同步依赖，也请继续使用 `uv sync --inexact`。

## 注意

- 当前系统就是围绕这批本地知识库资料构建问答，不要求语料必须来自宇树 G1 官方文档。
- 如果后续要增加其他资料来源，只需要继续通过管理台上传或从固定目录导入。

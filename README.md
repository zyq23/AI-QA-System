# AI-QA-System

一个面向本地知识库的可追溯 AI 问答系统，适合把 `PDF / DOCX / PPTX` 等资料接入统一问答链路，并提供引用、检索、评测与运维能力。

本项目当前以 `FastAPI + SQLite FTS5 + ChromaDB` 为核心底座，支持本地检索优先、`RAGFlow` 可选增强，以及多种大模型接入方式。

## 项目目标

- 面向私有知识库做问答，而不是通用聊天
- 支持复杂文档接入，包括 `pptx`、OCR 页、图片页等
- 生成回答时尽量给出来源证据与可追溯引用
- 保留评测、回归、重建索引、机器人接入等工程化能力
- 在不破坏已有可用链路的前提下逐步提升解析、检索和回答质量

## 核心特性

- 文档接入：支持上传和目录导入 `pdf / docx / pptx`
- 解析与分块：内置多格式解析器，支持复杂 PPT 与 OCR 回退
- 混合检索：`SQLite FTS5 + 向量检索 + RRF 融合 + reranker`
- 回答生成：支持 OpenAI 兼容接口和讯飞 Spark WebSocket
- 证据引用：回答可附带来源片段、页码和可信度信号
- 管理能力：支持单文档重建、全量重建、停用文档、评测执行
- 机器人接入：提供简化的 HTTP 问答接口和桥接示例
- 可扩展后端：支持将 `RAGFlow` 接为可选检索/解析增强链路

## 技术栈

- Backend: `FastAPI`
- Template/UI: `Jinja2`
- Database: `SQLite`
- Lexical Retrieval: `SQLite FTS5`
- Vector Store: `ChromaDB`
- Embedding / Rerank: `BGE` 系列模型
- LLM Access: `OpenAI-compatible API` / `Spark WebSocket`
- Optional Enhancement: `RAGFlow`
- Test / Eval: `pytest` + repo 内置回归脚本

## 系统架构

```text
Documents
  -> Parsers (PDF / DOCX / PPTX / OCR)
  -> Chunking
  -> SQLite metadata + FTS5 index
  -> Chroma vector index

User Question
  -> Query rewrite / retrieval pipeline
  -> FTS recall + vector recall
  -> Fusion / rerank
  -> LLM answer generation
  -> Evidence-grounded response
```

默认策略是“本地检索优先，外部增强可选接入”，这样既能保持离线可控，也方便后续逐步升级复杂文档能力。

## 仓库结构

```text
app/                FastAPI 应用、解析、检索、回答、服务编排
docs/               协作记录、设计决策、阶段报告、验收材料
scripts/            启动、评测、重建索引、诊断脚本
tests/              单测与接口/检索相关测试
robot_bridge/       机器人或外部设备接入示例
data/evals/         评测集与历史评测结果
```

说明：

- 原始知识库文档目录和本地模型文件默认不随仓库上传
- 本仓库更关注“系统代码、评测资产、运行脚本和工程留痕”

## 快速开始

### 1. 环境要求

- Python `3.11`
- 推荐使用 `uv`
- 可选使用 `conda`

### 2. 安装依赖

```bash
uv sync --python 3.11 --inexact
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch
python -m pip install "transformers<5" FlagEmbedding
```

如果需要 OCR 回退：

```bash
uv sync --python 3.11 --extra ocr
```

也可以直接使用仓库提供的 conda 初始化脚本：

```bash
bash scripts/setup_conda_env.sh
conda activate yushu-qa
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

最小配置示例：

```env
ADMIN_TOKEN=your-admin-token
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_API_KEY=your-api-key
LLM_MODEL=your-model
```

如果使用讯飞 Spark：

```env
LLM_PROVIDER=spark_ws
SPARK_APP_ID=your-app-id
SPARK_API_KEY=your-api-key
SPARK_API_SECRET=your-api-secret
SPARK_API_BASE=wss://spark-api.xf-yun.com/x2
SPARK_MODEL=x2
SPARK_DOMAIN=spark-x
```

如果你暂时只想验证流程、不接真实模型：

```env
USE_STUB_ML=true
DISABLE_LLM=true
```

### 4. 启动服务

```bash
uv run --python 3.11 uvicorn app.main:app --reload
```

访问地址：

- 首页：`http://127.0.0.1:8000/`
- 管理台：`http://127.0.0.1:8000/admin?token=你的ADMIN_TOKEN`

## 文档导入

可以通过两种方式接入本地知识库：

### 管理台导入

- 上传单个文档
- 导入本地目录
- 对单文档或全量数据执行重建索引

### 命令行导入

```bash
uv run --python 3.11 python -m app.cli bootstrap
```

## 模型准备

如果需要下载本地 BGE 相关模型，可执行：

```bash
uv run --python 3.11 python -m app.cli download-models
```

`download-models` 只下载运行必需文件，不拉取整仓库附加资源。

## 检索与回答说明

当前主链路大致如下：

1. 文档解析为结构化文本块
2. 写入 SQLite 元数据与 FTS5 索引
3. 写入 Chroma 向量索引
4. 查询阶段执行词法召回与向量召回
5. 使用融合与重排策略缩小候选范围
6. 把候选证据交给 LLM 生成最终答案
7. 返回回答及相关引用信息

这套设计的重点不是“尽量回答所有问题”，而是“尽量基于知识库证据回答问题”。

## 评测与回归

仓库内已经提供评测资产与脚本：

```bash
uv run --python 3.11 python scripts/run_eval.py
```

评测数据位于：

```text
data/evals/
```

评测结果默认输出到：

```text
data/evals/results/
```

如果你要做检索链路排查，也可以使用：

```bash
uv run --python 3.11 python scripts/run_retrieval_diagnosis.py
```

## 机器人 / 外部系统接入

如果外部系统只需要“提交问题并获取可播报短答案”，可以直接调用：

- `POST /api/robot/query`

请求示例：

```json
{
  "question": "系统在资料不足时应该怎么回答？",
  "conversation_id": null,
  "top_k": 6,
  "client_id": "robot-client"
}
```

`robot_bridge/` 目录下提供了最小桥接示例：

```bash
python robot_bridge/bridge.py --base-url http://127.0.0.1:8000
```

## RAGFlow 可选集成

本项目支持把 `RAGFlow` 作为增强解析/检索后端接入，同时保留当前应用层接口与回答收口逻辑。

示例配置：

```env
RETRIEVAL_BACKEND=ragflow
RAGFLOW_BASE_URL=http://127.0.0.1:9380
RAGFLOW_API_KEY=your-ragflow-api-key
RAGFLOW_DATASET_IDS=dataset_id_1,dataset_id_2
RAGFLOW_FALLBACK_TO_LOCAL=true
```

集成思路：

- `local` 模式继续走本地 `FTS5 + ChromaDB`
- `ragflow` 模式把底层检索交给 `RAGFlow`
- 如果开启 `RAGFLOW_FALLBACK_TO_LOCAL=true`，RAGFlow 异常时会回退到本地链路

相关脚本：

```bash
bash scripts/start_ragflow_source.sh
bash scripts/stop_ragflow_source.sh
```

## 测试

运行测试：

```bash
pytest
```

或者：

```bash
uv run --python 3.11 pytest
```

## 已知限制

- 复杂 PPT、图片页、OCR 页仍然是高风险区域
- 公开仓库默认不包含原始知识库资料和本地模型文件
- 完整效果依赖你实际接入的知识库质量、检索配置和大模型能力
- 某些本地路径或脚本默认面向当前开发环境，二次部署时可能需要调整

## 适用场景

- 企业内部知识库问答
- 课程资料 / 项目资料问答
- 机器人讲解 / 展示终端问答
- 本地私有文档检索增强问答

## License

如果你准备公开长期维护，建议补充正式 `LICENSE` 文件。
当前仓库若未附带 License，默认不等于开源授权。

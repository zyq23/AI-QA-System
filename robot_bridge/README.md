
最小机器人桥接示例。这个目录不依赖 ROS2，只演示“机器人客户端如何把文本问题转发到本仓库的问答服务，再取回可播报答案”。

## 目标接口

- 服务端接口：`POST /api/robot/query`
- 机器人侧只消费：`answer`、`tts_text`、`conversation_id`

## 环境变量

```bash
export ROBOT_QA_BASE_URL=http://127.0.0.1:8000
export ROBOT_QA_TIMEOUT_SECONDS=15
export ROBOT_CLIENT_ID=g1-edu-dock
```

## 直接运行

```bash
python robot_bridge/bridge.py --base-url http://127.0.0.1:8000
```

进入交互后输入问题即可，桥接脚本会：

1. 调用 `/api/robot/query`
2. 复用返回的 `conversation_id` 保持多轮
3. 只打印 `tts_text`

## 代码中集成

```python
from robot_bridge.bridge import RobotQABridge

bridge = RobotQABridge(base_url="http://127.0.0.1:8000", client_id="g1-edu-dock")
answer = bridge.ask("这个系统资料不足时会怎么答？")
print(answer.tts_text)
```

如果后续要接到 G1 EDU 算力扩展坞上的语音客户端，通常只需要把语音识别出的文本传给 `handle_text()`，然后把返回的 `tts_text` 交给你现有的 TTS 播放层。

## G1 EDU 客户端示例

仓库里还补了一个更贴近机器人落地的示例：

- `robot_bridge/g1_client.py`

它在最小 HTTP bridge 之上多做了几件事：

1. 自动维护 `conversation_id`
2. 支持 `/reset` 重置会话
3. 支持 `/interrupt` 标记打断，旧回答回来后直接丢弃
4. 把每次问答记到 `jsonl` 日志，便于排查机器人现场问题

直接运行：

```bash
python robot_bridge/g1_client.py --base-url http://127.0.0.1:8000
```

如果你已经有自己的 ASR/TTS 客户端，可以直接嵌入：

```python
from robot_bridge.bridge import RobotQABridge
from robot_bridge.g1_client import G1RobotQAClient

bridge = RobotQABridge(base_url="http://127.0.0.1:8000", client_id="g1-edu-dock")
client = G1RobotQAClient(bridge, log_path="data/runtime/robot_bridge_events.jsonl")

def speak(text: str) -> None:
    print("tts>", text)

client.handle_asr_text("请介绍一下这个知识点", speak=speak)
```

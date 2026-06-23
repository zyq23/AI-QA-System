from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from robot_bridge.bridge import DEFAULT_FALLBACK_REPLY, RobotAnswer, RobotQABridge


SpeakCallback = Callable[[str], None]
LogCallback = Callable[[str], None]


@dataclass
class G1RobotEvent:
    event: str
    text: str
    conversation_id: str | None
    request_seq: int
    latency_ms: int
    grounded: bool
    created_at: float


class G1RobotQAClient:
    def __init__(
        self,
        bridge: RobotQABridge,
        *,
        log_path: str | Path | None = None,
        default_top_k: int | None = None,
    ) -> None:
        self.bridge = bridge
        self.default_top_k = default_top_k
        self._conversation_id: str | None = None
        self._request_seq = 0
        self._lock = threading.Lock()
        self.log_path = Path(log_path) if log_path else Path("data/runtime/robot_bridge_events.jsonl")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def conversation_id(self) -> str | None:
        with self._lock:
            return self._conversation_id

    def reset_session(self) -> None:
        with self._lock:
            self._conversation_id = None
            self._request_seq += 1

    def interrupt_current(self) -> None:
        with self._lock:
            self._request_seq += 1

    def ask(
        self,
        text: str,
        *,
        voice_session_id: str | None = None,
        top_k: int | None = None,
    ) -> RobotAnswer:
        with self._lock:
            current_seq = self._request_seq + 1
            self._request_seq = current_seq
            conversation_id = self._conversation_id
        answer = self.bridge.ask(
            text,
            conversation_id=conversation_id,
            top_k=top_k or self.default_top_k,
            voice_session_id=voice_session_id,
        )
        with self._lock:
            if current_seq != self._request_seq:
                cancelled = RobotAnswer(
                    answer="",
                    tts_text="",
                    conversation_id=self._conversation_id,
                    grounded=False,
                    latency_ms=0,
                    should_speak=False,
                    question_type=None,
                    answer_focus=None,
                    raw_payload={"cancelled": True},
                )
                self._write_event("cancelled_reply", text, cancelled, current_seq)
                return cancelled
            self._conversation_id = answer.conversation_id or self._conversation_id
        self._write_event("answer", text, answer, current_seq)
        return answer

    def handle_asr_text(
        self,
        text: str,
        *,
        speak: SpeakCallback | None = None,
        logger: LogCallback | None = None,
        voice_session_id: str | None = None,
        top_k: int | None = None,
    ) -> RobotAnswer:
        clean_text = text.strip()
        if not clean_text:
            empty = RobotAnswer(
                answer="",
                tts_text="",
                conversation_id=self.conversation_id,
                grounded=False,
                latency_ms=0,
                should_speak=False,
                question_type=None,
                answer_focus=None,
                raw_payload={"ignored": "empty"},
            )
            self._write_event("ignored_empty", clean_text, empty, self._request_seq)
            return empty
        answer = self.ask(clean_text, voice_session_id=voice_session_id, top_k=top_k)
        if logger:
            logger(f"robot answer: {answer.tts_text or DEFAULT_FALLBACK_REPLY}")
        if speak and answer.should_speak and answer.tts_text:
            speak(answer.tts_text)
        return answer

    def _write_event(self, event: str, text: str, answer: RobotAnswer, request_seq: int) -> None:
        payload = G1RobotEvent(
            event=event,
            text=text,
            conversation_id=answer.conversation_id,
            request_seq=request_seq,
            latency_ms=answer.latency_ms,
            grounded=answer.grounded,
            created_at=time.time(),
        )
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(payload), ensure_ascii=False) + "\n")


def run_demo() -> int:
    parser = argparse.ArgumentParser(description="G1 EDU style QA client demo")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--client-id", default="g1-edu-dock")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--log-path", default="data/runtime/robot_bridge_events.jsonl")
    args = parser.parse_args()

    bridge = RobotQABridge(
        base_url=args.base_url,
        timeout_seconds=args.timeout,
        client_id=args.client_id,
    )
    client = G1RobotQAClient(bridge, log_path=args.log_path, default_top_k=args.top_k)

    print("G1 QA demo ready. Input text to simulate ASR. Commands: /reset /interrupt /exit")
    while True:
        try:
            text = input("asr> ").strip()
        except EOFError:
            print()
            return 0
        if not text:
            continue
        if text.lower() in {"/exit", "exit", "quit"}:
            return 0
        if text.lower() == "/reset":
            client.reset_session()
            print("system> 会话已重置")
            continue
        if text.lower() == "/interrupt":
            client.interrupt_current()
            print("system> 已标记中断，旧回答返回后会被丢弃")
            continue
        answer = client.handle_asr_text(text, speak=lambda reply: print(f"tts> {reply}"))
        if not answer.should_speak:
            print("system> 本次回答已取消")


if __name__ == "__main__":
    raise SystemExit(run_demo())

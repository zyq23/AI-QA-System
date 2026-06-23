from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_FALLBACK_REPLY = "当前无法连接问答服务，请稍后再试。"


@dataclass
class RobotAnswer:
    answer: str
    tts_text: str
    conversation_id: str | None
    grounded: bool
    latency_ms: int
    raw_payload: dict[str, Any]
    should_speak: bool = True
    question_type: str | None = None
    answer_focus: str | None = None


def clean_tts_text(text: str) -> str:
    if not text:
        return ""
    text = text.encode("utf-8", "ignore").decode("utf-8", "ignore")
    text = re.sub(r"[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]", "", text)
    text = re.sub(r"`+", "", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[#*_>{}\[\]]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 280:
        text = text[:280].rstrip("，、；：,. ") + "。"
    return text


class RobotQABridge:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        client_id: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("ROBOT_QA_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout_seconds = float(timeout_seconds or os.getenv("ROBOT_QA_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
        self.client_id = client_id or os.getenv("ROBOT_CLIENT_ID") or "g1-edu-bridge"

    def ask(
        self,
        question: str,
        conversation_id: str | None = None,
        *,
        top_k: int | None = None,
        voice_session_id: str | None = None,
    ) -> RobotAnswer:
        payload = {
            "question": question,
            "conversation_id": conversation_id,
            "top_k": top_k,
            "client_id": self.client_id,
            "voice_session_id": voice_session_id,
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(f"{self.base_url}/api/robot/query", json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return RobotAnswer(
                answer=DEFAULT_FALLBACK_REPLY,
                tts_text=DEFAULT_FALLBACK_REPLY,
                conversation_id=conversation_id,
                grounded=False,
                latency_ms=0,
                should_speak=True,
                question_type=None,
                answer_focus=None,
                raw_payload={"error": str(exc)},
            )
        answer_text = str(data.get("answer", "")).strip()
        tts_text = clean_tts_text(str(data.get("tts_text") or answer_text or ""))
        return RobotAnswer(
            answer=answer_text,
            tts_text=tts_text or DEFAULT_FALLBACK_REPLY,
            conversation_id=data.get("conversation_id"),
            grounded=bool(data.get("grounded", False)),
            latency_ms=int(data.get("latency_ms", 0) or 0),
            should_speak=bool(data.get("should_speak", True)) and bool(tts_text or DEFAULT_FALLBACK_REPLY),
            question_type=data.get("question_type"),
            answer_focus=data.get("answer_focus"),
            raw_payload=data,
        )

    def handle_text(
        self,
        text: str,
        conversation_id: str | None = None,
        *,
        top_k: int | None = None,
        voice_session_id: str | None = None,
    ) -> tuple[str, str | None]:
        answer = self.ask(
            text,
            conversation_id,
            top_k=top_k,
            voice_session_id=voice_session_id,
        )
        return answer.tts_text, answer.conversation_id


def run_cli() -> int:
    parser = argparse.ArgumentParser(description="Minimal bridge for a robot text/voice client.")
    parser.add_argument("--base-url", default=None, help="QA service base URL, default: $ROBOT_QA_BASE_URL or http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=None, help="Request timeout in seconds")
    parser.add_argument("--client-id", default=None, help="Robot client identifier")
    parser.add_argument("--top-k", type=int, default=None, help="Optional retrieval top_k override")
    args = parser.parse_args()

    bridge = RobotQABridge(
        base_url=args.base_url,
        timeout_seconds=args.timeout,
        client_id=args.client_id,
    )
    conversation_id: str | None = None

    print("Robot QA bridge ready. Type a question and press Enter. Type /exit to quit.")
    while True:
        try:
            text = input("you> ").strip()
        except EOFError:
            print()
            return 0
        if not text:
            continue
        if text.lower() in {"/exit", "exit", "quit"}:
            return 0
        answer = bridge.ask(text, conversation_id=conversation_id, top_k=args.top_k)
        conversation_id = answer.conversation_id
        print(f"robot> {answer.tts_text}")


if __name__ == "__main__":
    raise SystemExit(run_cli())

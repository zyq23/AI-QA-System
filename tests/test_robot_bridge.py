from __future__ import annotations

from pathlib import Path

from robot_bridge.bridge import RobotAnswer, clean_tts_text
from robot_bridge.g1_client import G1RobotQAClient


def test_clean_tts_text_removes_markdown_and_caps_length():
    text = "[资料链接](https://example.com) **回答** " + ("很长" * 200)
    cleaned = clean_tts_text(text)
    assert "http" not in cleaned
    assert "[" not in cleaned
    assert len(cleaned) <= 281


def test_g1_client_interrupt_drops_stale_reply(tmp_path: Path):
    class SlowBridge:
        def ask(self, question, conversation_id=None, top_k=None, voice_session_id=None):
            client.interrupt_current()
            return RobotAnswer(
                answer="旧回答",
                tts_text="旧回答",
                conversation_id="conv-1",
                grounded=True,
                latency_ms=10,
                should_speak=True,
                question_type="factoid",
                answer_focus="测试",
                raw_payload={"question": question},
            )

    client = G1RobotQAClient(SlowBridge(), log_path=tmp_path / "events.jsonl")
    answer = client.ask("这条回答应该被取消")
    assert answer.should_speak is False
    assert answer.raw_payload["cancelled"] is True


def test_g1_client_updates_conversation_and_logs(tmp_path: Path):
    class StubBridge:
        def ask(self, question, conversation_id=None, top_k=None, voice_session_id=None):
            return RobotAnswer(
                answer="可以回答",
                tts_text="可以回答",
                conversation_id="conv-2",
                grounded=True,
                latency_ms=12,
                should_speak=True,
                question_type="factoid",
                answer_focus="问答",
                raw_payload={"question": question, "conversation_id": conversation_id},
            )

    client = G1RobotQAClient(StubBridge(), log_path=tmp_path / "events.jsonl")
    answer = client.handle_asr_text("测试一下")
    assert answer.should_speak is True
    assert client.conversation_id == "conv-2"
    log_text = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "answer" in log_text

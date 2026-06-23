from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from time import mktime
from urllib.parse import urlencode, urlparse
from wsgiref.handlers import format_date_time

import websockets
from websockets.exceptions import InvalidStatus


@dataclass(slots=True)
class SparkConfig:
    app_id: str
    api_key: str
    api_secret: str
    api_base: str
    model: str
    domain: str
    temperature: float
    max_tokens: int
    thinking_type: str
    request_timeout_seconds: int
    uid: str


class SparkError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__("Spark request failed with code {0}: {1}".format(code, message))


class SparkContentPolicyError(SparkError):
    pass


class SparkWebSocketClient:
    def __init__(self, config: SparkConfig) -> None:
        self.config = config

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        thinking_type: str | None = None,
    ) -> str:
        return asyncio.run(
            self._generate_async(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking_type=thinking_type,
            )
        )

    async def _generate_async(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None,
        max_tokens: int | None,
        thinking_type: str | None,
    ) -> str:
        request_url = self._build_authenticated_url()
        request_payload = self._build_payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_type=thinking_type,
        )
        chunks: list[str] = []
        try:
            async with websockets.connect(
                request_url,
                ping_interval=None,
                ping_timeout=None,
                open_timeout=float(self.config.request_timeout_seconds),
                close_timeout=1,
            ) as websocket:
                await websocket.send(json.dumps(request_payload, ensure_ascii=False))
                while True:
                    frame = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=float(self.config.request_timeout_seconds),
                    )
                    data = json.loads(frame)
                    header = data.get("header", {})
                    code = header.get("code", 0)
                    if code != 0:
                        message = str(header.get("message", ""))
                        if int(code) == 10019:
                            raise SparkContentPolicyError(int(code), message)
                        raise SparkError(int(code), message)
                    payload = data.get("payload", {})
                    choices = payload.get("choices", {})
                    for item in choices.get("text", []):
                        content = item.get("content")
                        if content:
                            chunks.append(content)
                    if header.get("status") == 2 or choices.get("status") == 2:
                        break
        except TimeoutError as exc:
            raise RuntimeError(
                "Spark request timed out after {0}s".format(self.config.request_timeout_seconds)
            ) from exc
        except InvalidStatus as exc:
            raise RuntimeError(self._format_handshake_error(exc)) from exc
        return "".join(chunks).strip()

    def _build_authenticated_url(self) -> str:
        parsed = urlparse(self.config.api_base)
        host = parsed.netloc
        path = parsed.path
        date = format_date_time(mktime(datetime.now().timetuple()))
        signature_origin = "host: {0}\n".format(host)
        signature_origin += "date: {0}\n".format(date)
        signature_origin += "GET {0} HTTP/1.1".format(path)
        digest = hmac.new(
            self.config.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        signature = base64.b64encode(digest).decode("utf-8")
        authorization_origin = (
            'api_key="{0}", algorithm="hmac-sha256", headers="host date request-line", '
            'signature="{1}"'
        ).format(self.config.api_key, signature)
        authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")
        query = urlencode({"authorization": authorization, "date": date, "host": host})
        return "{0}?{1}".format(self.config.api_base, query)

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None,
        max_tokens: int | None,
        thinking_type: str | None,
    ) -> dict:
        chat = {
            "domain": self.config.domain,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
        }
        effective_thinking = (thinking_type or self.config.thinking_type).strip().lower()
        if effective_thinking:
            chat["thinking"] = {"type": effective_thinking}
        return {
            "header": {"app_id": self.config.app_id, "uid": self.config.uid},
            "parameter": {"chat": chat},
            "payload": {"message": {"text": messages}},
        }

    def _format_handshake_error(self, exc: InvalidStatus) -> str:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        body = getattr(getattr(exc, "response", None), "body", b"")
        body_text = ""
        if isinstance(body, (bytes, bytearray)):
            body_text = bytes(body).decode("utf-8", errors="ignore").strip()
        elif body:
            body_text = str(body).strip()
        if status_code is not None:
            return "Spark handshake failed with HTTP {0}: {1}".format(status_code, body_text or str(exc))
        return "Spark handshake failed: {0}".format(exc)

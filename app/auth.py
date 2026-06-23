from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer


COOKIE_NAME = "admin_session"


class AdminSessionSigner:
    def __init__(self, secret_key: str) -> None:
        self.serializer = URLSafeSerializer(secret_key, salt="knowledge-qa-admin")

    def dumps(self, token: str) -> str:
        return self.serializer.dumps({"token": token})

    def loads(self, value: str) -> str | None:
        try:
            payload = self.serializer.loads(value)
        except BadSignature:
            return None
        return payload.get("token")

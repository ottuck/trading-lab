"""텔레그램 봇 메시지 전송. 토큰이 URL에 들어가므로 URL·예외 원문을 로그에 남기지 않는다."""

from typing import Any

import httpx

API_BASE = "https://api.telegram.org"


class TelegramError(Exception):
    """토큰이 빠진 요약 메시지만 담는다."""


class TelegramClient:
    def __init__(self, token: str, chat_id: str, *, http: httpx.Client | None = None) -> None:
        self._token = token
        self._chat_id = chat_id
        self._http = http or httpx.Client(timeout=10)

    def _call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            resp = self._http.post(f"{API_BASE}/bot{self._token}/{method}", json=payload or {})
        except httpx.HTTPError as exc:
            raise TelegramError(f"{method} 요청 실패: {type(exc).__name__}") from None
        body = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        if resp.status_code != 200 or not body.get("ok"):
            raise TelegramError(
                f"{method} 실패: HTTP {resp.status_code} {body.get('description', '')}"
            )
        return body["result"]

    def send(self, text: str) -> None:
        self._call(
            "sendMessage",
            {"chat_id": self._chat_id, "text": text[:4000], "disable_web_page_preview": True},
        )

    def recent_chat_ids(self) -> list[tuple[str, str]]:
        """봇에게 최근 메시지를 보낸 채팅 (채팅 ID 확인용)."""
        updates = self._call("getUpdates")
        seen: dict[str, str] = {}
        for u in updates:
            chat = (u.get("message") or u.get("channel_post") or {}).get("chat")
            if chat:
                seen[str(chat["id"])] = chat.get("username") or chat.get("title") or ""
        return list(seen.items())

"""아이디/비밀번호(.env) 로그인 + 서명된 세션 쿠키(JWT).

이 서버는 GPU 서버의 docker 를 조작하므로 로그인 페이지와 정적 파일을 뺀 모든 경로를 막는다.
WebSocket 은 미들웨어를 안 거치므로 ws_routes 에서 ws_authenticated() 로 직접 확인한다.
"""

import hmac
import time
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import WebSocket
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import ADMIN_PASSWORD, ADMIN_USERNAME, SESSION_DAYS, SESSION_SECRET

COOKIE = "vllm_admin_session"
PUBLIC_PREFIXES = ("/login", "/api/login", "/css/", "/js/", "/favicon")

# 무차별 대입 방지: IP 당 5분에 10번까지 실패 허용
_failures: dict[str, list[float]] = {}


def too_many_failures(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _failures.get(ip, []) if now - t < 300]
    _failures[ip] = recent
    return len(recent) >= 10


def check_password(ip: str, username: str, password: str) -> bool:
    ok = hmac.compare_digest(username.encode(), ADMIN_USERNAME.encode()) & hmac.compare_digest(
        password.encode(), ADMIN_PASSWORD.encode())
    if not ok:
        _failures.setdefault(ip, []).append(time.time())
    return ok


def issue_session() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": ADMIN_USERNAME, "iat": now, "exp": now + timedelta(days=SESSION_DAYS)},
                      SESSION_SECRET, algorithm="HS256")


def session_valid(token: str | None) -> bool:
    if not token:
        return False
    try:
        payload = jwt.decode(token, SESSION_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return False
    return payload.get("sub") == ADMIN_USERNAME  # 아이디를 바꾸면 기존 세션은 무효


def ws_authenticated(ws: WebSocket) -> bool:
    return session_valid(ws.cookies.get(COOKIE))


class AuthMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path.startswith(PUBLIC_PREFIXES):
            return await self.app(scope, receive, send)
        cookies = {}
        for k, v in scope.get("headers", []):
            if k == b"cookie":
                for part in v.decode("latin-1").split(";"):
                    name, _, value = part.strip().partition("=")
                    cookies[name] = value
        if session_valid(cookies.get(COOKIE)):
            return await self.app(scope, receive, send)
        if path.startswith("/api/"):
            resp = JSONResponse({"detail": "로그인이 필요합니다"}, status_code=401)
        else:
            resp = RedirectResponse("/login", status_code=303)
        return await resp(scope, receive, send)

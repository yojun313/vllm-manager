"""아이디/비밀번호(server/.env) 로그인 + 서명된 세션 쿠키(JWT).

이 서버는 GPU 서버의 docker 를 조작하므로 로그인 페이지와 정적 파일을 뺀 모든 경로를 막는다.
WebSocket 은 미들웨어를 안 거치므로 ws_routes 에서 ws_authenticated() 로 직접 확인한다.
비밀번호는 PBKDF2 해시(ADMIN_PASS_HASH)로 저장하며, 예전 방식의 평문(ADMIN_PASSWORD)도 그대로 동작한다.
"""

import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import jwt
from fastapi import WebSocket
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app import config
from app.config import SESSION_DAYS, SESSION_SECRET

logger = logging.getLogger("uvicorn.error")
COOKIE = "vllm_admin_session"
PUBLIC_PREFIXES = (
    "/login",
    "/api/login",
    "/api/auth/passkey/login",
    "/css/",
    "/js/",
    "/icons/",
    "/favicon",
    "/manifest.webmanifest",
)
SETUP_PREFIXES = (
    "/setup",
    "/api/setup",
    "/css/",
    "/js/",
    "/icons/",
    "/favicon",
    "/manifest.webmanifest",
)
PBKDF2_ITERATIONS = 310_000

_cred = {"hash": config.ADMIN_PASS_HASH, "plain": config.ADMIN_PASSWORD}


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def _verify_hash(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        got = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        )
        return hmac.compare_digest(got, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def verify_password(password: str) -> bool:
    if _cred["hash"]:
        return _verify_hash(password, _cred["hash"])
    return hmac.compare_digest(password.encode(), _cred["plain"].encode())


def _fingerprint() -> str:
    """비밀번호가 바뀌면 달라지는 값. 세션에 넣어 두어 비밀번호 변경 시 기존 세션을 무효로 만든다."""
    return hashlib.sha256((_cred["hash"] or _cred["plain"]).encode()).hexdigest()[:16]


def set_password(password: str) -> None:
    """새 비밀번호를 해시로 server/.env 에 기록하고 즉시 적용한다 (평문 항목은 삭제)."""
    hashed = hash_password(password)
    if not config.DEMO:
        config.write_env_values(
            config.SERVER_ENV_FILE, {"ADMIN_PASS_HASH": hashed, "ADMIN_PASSWORD": None}
        )
    _cred.update(hash=hashed, plain="")


# 무차별 대입 방지: IP 당 5분에 10번까지 실패 허용
_failures: dict[str, list[float]] = {}


def record_failure(ip: str) -> None:
    if ip not in _failures and len(_failures) >= 4096:
        _failures.pop(next(iter(_failures)))
    _failures.setdefault(ip, []).append(time.time())


def too_many_failures(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _failures.get(ip, []) if now - t < 300]
    _failures[ip] = recent
    return len(recent) >= 10


def check_password(ip: str, username: str, password: str) -> bool:
    ok = hmac.compare_digest(
        username.encode(), config.ADMIN_USERNAME.encode()
    ) & verify_password(password)
    if not ok:
        record_failure(ip)
    else:
        _failures.pop(ip, None)
    return ok


def issue_session() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": config.ADMIN_USERNAME,
            "pv": _fingerprint(),
            "iat": now,
            "exp": now + timedelta(days=SESSION_DAYS),
        },
        SESSION_SECRET,
        algorithm="HS256",
    )


def create_admin(username: str, password: str) -> None:
    """초기 설정: 관리자 계정을 server/.env 에 기록하고 초기 설정 상태를 끝낸다."""
    hashed = hash_password(password)
    config.write_env_values(
        config.SERVER_ENV_FILE,
        {"ADMIN_USERNAME": username, "ADMIN_PASS_HASH": hashed, "ADMIN_PASSWORD": None},
    )
    config.ADMIN_USERNAME = username
    _cred.update(hash=hashed, plain="")
    config.SETUP_MODE = False
    config.SETUP_TOKEN = ""


def session_valid(token: str | None) -> bool:
    if not token or config.SETUP_MODE:
        return False
    try:
        payload = jwt.decode(token, SESSION_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return False
    # 아이디나 비밀번호를 바꾸면 기존 세션은 무효 (pv 가 없는 예전 세션은 아이디만 확인)
    if payload.get("sub") != config.ADMIN_USERNAME:
        return False
    return payload.get("pv") in (None, _fingerprint())


def ws_authenticated(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    host = ws.headers.get("host", "").lower()
    origin_host = urlsplit(origin).netloc.lower() if origin else ""
    return (
        session_valid(ws.cookies.get(COOKIE))
        and bool(origin_host)
        and origin_host == host
    )


class AuthMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        korean = headers.get(b"accept-language", b"").lower().startswith(b"ko")
        if scope.get("method") not in {"GET", "HEAD", "OPTIONS", "TRACE"}:
            fetch_site = headers.get(b"sec-fetch-site", b"").lower()
            origin = headers.get(b"origin")
            host = headers.get(b"host", b"").decode("latin-1").lower()
            origin_host = (
                urlsplit(origin.decode("latin-1")).netloc.lower() if origin else ""
            )
            if fetch_site == b"cross-site" or (origin and origin_host != host):
                detail = (
                    "요청 출처가 올바르지 않습니다"
                    if korean
                    else "Cross-origin request refused"
                )
                resp = JSONResponse({"detail": detail}, status_code=403)
                return await resp(scope, receive, send)
        if config.SETUP_MODE:
            if path.startswith(SETUP_PREFIXES):
                return await self.app(scope, receive, send)
            if path.startswith("/api/"):
                detail = (
                    "초기 설정이 필요합니다" if korean else "Initial setup required"
                )
                return await JSONResponse({"detail": detail}, status_code=401)(
                    scope, receive, send
                )
            return await RedirectResponse("/setup", status_code=303)(
                scope, receive, send
            )
        if path.startswith(PUBLIC_PREFIXES):
            return await self.app(scope, receive, send)
        cookies = {}
        for part in headers.get(b"cookie", b"").decode("latin-1").split(";"):
            name, _, value = part.strip().partition("=")
            cookies[name] = value
        if session_valid(cookies.get(COOKIE)):
            return await self.app(scope, receive, send)
        if path.startswith("/api/"):
            detail = "로그인이 필요합니다" if korean else "Sign-in required"
            resp = JSONResponse({"detail": detail}, status_code=401)
        else:
            resp = RedirectResponse("/login", status_code=303)
        return await resp(scope, receive, send)

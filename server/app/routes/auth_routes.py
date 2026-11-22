import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import hmac
import re

from app import auth, config
from app.auth import COOKIE, check_password, issue_session, too_many_failures
from app.config import COOKIE_SECURE, SESSION_DAYS
from app.i18n import fail, tr
from app.services import passkeys

router = APIRouter()


class LoginBody(BaseModel):
    username: str
    password: str


class SetupBody(BaseModel):
    token: str
    username: str
    password: str


class PasswordBody(BaseModel):
    current: str
    new: str


def _with_session(resp: JSONResponse) -> JSONResponse:
    resp.set_cookie(
        COOKIE,
        issue_session(),
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        max_age=SESSION_DAYS * 86400,
        path="/",
    )
    return resp


@router.post("/api/login")
async def login(body: LoginBody, request: Request):
    ip = request.client.host if request.client else "?"
    if too_many_failures(ip):
        raise fail(
            request,
            429,
            "로그인 시도가 너무 많습니다. 5분 후 재시도가 가능합니다.",
            "Too many sign-in attempts. Try again in 5 minutes.",
        )
    ok = await asyncio.to_thread(
        check_password, ip, body.username.strip(), body.password
    )
    if not ok:
        await asyncio.sleep(1)  # 무차별 대입 속도 늦추기
        raise fail(
            request,
            401,
            "아이디 또는 비밀번호가 올바르지 않습니다",
            "Incorrect username or password",
        )
    return _with_session(JSONResponse({"ok": True}))


@router.post("/api/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(
        COOKIE, path="/", secure=COOKIE_SECURE, httponly=True, samesite="strict"
    )
    return resp


@router.post("/api/account/password")
async def change_password(body: PasswordBody, request: Request):
    ip = request.client.host if request.client else "?"
    if too_many_failures(ip):
        raise fail(
            request,
            429,
            "시도가 너무 많습니다. 5분 후 재시도가 가능합니다.",
            "Too many attempts. Try again in 5 minutes.",
        )
    if not await asyncio.to_thread(
        check_password, ip, config.ADMIN_USERNAME, body.current
    ):
        await asyncio.sleep(1)
        raise fail(
            request,
            403,
            "현재 비밀번호가 올바르지 않습니다",
            "The current password is incorrect",
        )
    if not body.new:
        raise fail(
            request, 400, "새 비밀번호를 입력해야 합니다", "Enter a new password"
        )
    if len(body.new) > 256:
        raise fail(request, 400, "비밀번호가 너무 깁니다", "The password is too long")
    await asyncio.to_thread(auth.set_password, body.new)
    # 다른 기기의 세션은 무효가 되고, 이 브라우저는 새 세션으로 이어간다
    return _with_session(JSONResponse({"ok": True}))


@router.post("/api/setup")
async def setup(body: SetupBody, request: Request):
    """첫 실행: 터미널에 표시된 설정 토큰으로 관리자 계정을 만든다."""
    ip = request.client.host if request.client else "?"
    if not config.SETUP_MODE:
        raise fail(
            request, 409, "이미 설정이 끝났습니다", "Setup has already been completed"
        )
    if too_many_failures(ip):
        raise fail(
            request,
            429,
            "시도가 너무 많습니다. 5분 후 재시도가 가능합니다.",
            "Too many attempts. Try again in 5 minutes.",
        )
    if not hmac.compare_digest(
        body.token.strip().encode(), config.SETUP_TOKEN.encode()
    ):
        auth._failures.setdefault(ip, []).append(__import__("time").time())
        await asyncio.sleep(1)
        raise fail(
            request,
            403,
            "설정 토큰이 올바르지 않습니다. 서버 로그에 표시된 주소를 확인해야 합니다.",
            "The setup token is incorrect. Use the address printed in the server log.",
        )
    username = body.username.strip()
    if not re.fullmatch(r"[A-Za-z0-9._@-]{1,64}", username):
        raise fail(
            request,
            400,
            "아이디는 영문, 숫자, . _ @ - 만 쓸 수 있습니다",
            "The username may contain letters, digits and . _ @ - only",
        )
    if not 1 <= len(body.password) <= 256:
        raise fail(request, 400, "비밀번호를 입력해야 합니다", "Enter a password")
    await asyncio.to_thread(auth.create_admin, username, body.password)
    return _with_session(JSONResponse({"ok": True}))


# ---------------------------------------------------------------- 패스키 (WebAuthn)
# 패스키 로그인에는 비밀번호가 필요 없다: 기기가 본인 확인(생체 인증·PIN)을 한 뒤에만 응답한다.
# 패스키를 추가할 때는 비밀번호를 다시 확인한다. 빌린 세션으로 몰래 출입구를 만들어 둘 수 없게 하기 위해서다.


class PasskeyStart(BaseModel):
    password: str


class PasskeyCredential(BaseModel):
    ticket: str
    credential: dict
    name: str = ""


class PasskeyName(BaseModel):
    name: str


class PasskeyLogin(BaseModel):
    ticket: str
    credential: dict


def _site(request: Request) -> tuple[str, str]:
    return passkeys.site(request.headers.get("origin"), request.headers.get("host"))


def _passkey_fail(
    request: Request, error: passkeys.PasskeyError, status: int = 400
) -> HTTPException:
    return HTTPException(status, tr(request, error.ko, error.en))


@router.get("/api/auth/passkeys")
async def passkey_list(request: Request):
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
    return {"passkeys": passkeys.public_list(host or None)}


@router.post("/api/auth/passkeys/options")
async def passkey_register_options(body: PasskeyStart, request: Request):
    ip = request.client.host if request.client else "?"
    if too_many_failures(ip):
        raise fail(
            request,
            429,
            "시도가 너무 많습니다. 5분 후 재시도가 가능합니다.",
            "Too many attempts. Try again in 5 minutes.",
        )
    if not await asyncio.to_thread(
        check_password, ip, config.ADMIN_USERNAME, body.password
    ):
        raise fail(
            request, 403, "비밀번호가 올바르지 않습니다", "The password is incorrect"
        )
    try:
        rp_id, _origin = _site(request)
        return passkeys.register_options(rp_id, config.ADMIN_USERNAME)
    except passkeys.PasskeyError as error:
        raise _passkey_fail(request, error) from error


@router.post("/api/auth/passkeys")
async def passkey_register(body: PasskeyCredential, request: Request):
    try:
        rp_id, origin = _site(request)
        return passkeys.register_verify(
            body.ticket, rp_id, origin, body.credential, body.name[:40]
        )
    except passkeys.PasskeyError as error:
        raise _passkey_fail(request, error) from error


@router.patch("/api/auth/passkeys/{passkey_id}")
async def passkey_rename(passkey_id: str, body: PasskeyName, request: Request):
    try:
        passkeys.rename(passkey_id, body.name[:40])
    except passkeys.PasskeyError as error:
        raise _passkey_fail(request, error, 404) from error
    return {"ok": True}


@router.delete("/api/auth/passkeys/{passkey_id}")
async def passkey_remove(passkey_id: str, request: Request):
    try:
        passkeys.remove(passkey_id)
    except passkeys.PasskeyError as error:
        raise _passkey_fail(request, error, 404) from error
    return {"ok": True}


@router.post("/api/auth/passkey/login/options")
async def passkey_login_options(request: Request):
    """공개 경로: 패스키 로그인용 챌린지. 어떤 패스키가 등록되어 있는지는 알려주지 않는다."""
    ip = request.client.host if request.client else "?"
    if too_many_failures(ip):
        raise fail(
            request,
            429,
            "로그인 시도가 너무 많습니다. 5분 후 재시도가 가능합니다.",
            "Too many sign-in attempts. Try again in 5 minutes.",
        )
    try:
        rp_id, _origin = _site(request)
        return passkeys.login_options(rp_id)
    except passkeys.PasskeyError as error:
        raise _passkey_fail(request, error) from error


@router.post("/api/auth/passkey/login")
async def passkey_login(body: PasskeyLogin, request: Request):
    ip = request.client.host if request.client else "?"
    if too_many_failures(ip) or config.SETUP_MODE:
        raise fail(
            request,
            429,
            "로그인 시도가 너무 많습니다. 5분 후 재시도가 가능합니다.",
            "Too many sign-in attempts. Try again in 5 minutes.",
        )
    try:
        rp_id, origin = _site(request)
        used = await asyncio.to_thread(
            passkeys.login_verify, body.ticket, rp_id, origin, body.credential
        )
    except passkeys.PasskeyError as error:
        auth.record_failure(ip)
        raise _passkey_fail(request, error, 401) from error
    auth.logger.info("sign-in with passkey '%s' from %s", used, ip)
    return _with_session(JSONResponse({"ok": True}))

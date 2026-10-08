import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import COOKIE, check_password, issue_session, too_many_failures
from app.config import COOKIE_SECURE, SESSION_DAYS

router = APIRouter()


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/api/login")
async def login(body: LoginBody, request: Request):
    ip = request.client.host if request.client else "?"
    if too_many_failures(ip):
        raise HTTPException(429, "로그인 시도가 너무 많습니다. 5분 뒤 다시 시도하세요.")
    if not check_password(ip, body.username.strip(), body.password):
        await asyncio.sleep(1)  # 무차별 대입 속도 늦추기
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, issue_session(), httponly=True, secure=COOKIE_SECURE,
                    samesite="strict", max_age=SESSION_DAYS * 86400, path="/")
    return resp


@router.post("/api/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/", secure=COOKIE_SECURE, httponly=True, samesite="strict")
    return resp

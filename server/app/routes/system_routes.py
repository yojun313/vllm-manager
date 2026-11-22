"""시스템 정보, 이력, 업데이트 확인."""

import asyncio
import os
import threading
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import auth, config
from app.i18n import fail
from app.services import history, models, prepare, settings, state, system

RESTART_CODE = 75  # server/start.sh 가 이 종료 코드를 보면 서버를 다시 띄운다


class SettingsBody(BaseModel):
    values: dict = {}
    public_urls: dict | None = None


router = APIRouter(prefix="/api")


@router.get("/system")
async def get_system():
    info = await asyncio.to_thread(system.info)
    info["server"]["password_hashed"] = bool(auth._cred["hash"])
    return info


@router.post("/system/update-check")
async def update_check():
    return await asyncio.to_thread(system.check_update, True)


@router.get("/history")
async def get_history(range: str = "1h"):
    return await asyncio.to_thread(history.query, range)


@router.get("/settings")
async def get_settings():
    return await asyncio.to_thread(settings.current)


@router.put("/settings")
async def put_settings(body: SettingsBody, request: Request):
    try:
        result = await asyncio.to_thread(settings.update, body.values, body.public_urls)
    except PermissionError as e:
        raise fail(
            request,
            400,
            f"폴더를 만들 수 없습니다: {e}",
            f"Could not create the folder: {e}",
        )
    except ValueError as e:
        raise fail(request, 400, f"값이 올바르지 않습니다: {e}", f"Invalid value: {e}")
    models._plan_cache.clear()
    if any(k.endswith("_IMAGE") for k in result["changed"]):
        prepare.start()  # 새로 지정한 이미지를 바로 받아 두거나 빌드한다
    state.invalidate()
    system.invalidate()
    return result


@router.post("/system/restart")
async def restart(request: Request):
    """관리 서버만 다시 시작한다. 실행 중인 모델과 진행 중인 작업은 서버와 분리되어 있어 영향을 받지 않는다."""

    def later():
        time.sleep(0.6)
        os._exit(RESTART_CODE)

    threading.Thread(target=later, daemon=True).start()
    return {"ok": True}


@router.post("/system/prepare")
async def prepare_again():
    """실행 이미지 준비를 다시 시도한다 (이미지 설정을 바꾼 뒤나 실패한 뒤)."""
    return {"started": prepare.start()}

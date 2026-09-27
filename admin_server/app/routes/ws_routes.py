"""실시간 채널. 서버 → 화면으로 계속 밀어준다:

- gpu    : 1초마다 GPU 전체(메모리 분해·사용률·온도·전력)
- state  : 2초마다 (그리고 작업 상태가 바뀌면 즉시) 컨테이너·기동 진행률·모델·작업 목록
- job    : 구독한 작업의 새 출력 줄 (기동/다운로드 로그) — 0.25초 간격
- logs   : 구독한 컨테이너의 docker logs -f 스트림

화면 → 서버 메시지: {"sub": "job", "id": 3} / {"sub": "logs", "name": "vllm-x-g0"} / {"sub": null}
AuthMiddleware 는 WebSocket 을 거르지 않으므로 여기서 직접 세션을 확인한다.
"""

import asyncio
import contextlib
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import ws_authenticated
from app.services import docker, gpu, jobs, state

router = APIRouter()


@router.websocket("/ws")
async def ws(ws: WebSocket):
    if not ws_authenticated(ws):
        await ws.close(code=1008)
        return
    await ws.accept()

    sub: dict = {"kind": None}
    send_lock = asyncio.Lock()
    log_task: asyncio.Task | None = None

    async def send(msg: dict):
        async with send_lock:
            await ws.send_json(msg)

    async def stream_container_logs(name: str):
        proc = await asyncio.create_subprocess_exec(
            "docker", "logs", "-f", "--tail", "400", name,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)

        def last_segment(raw: bytes) -> str:
            # tqdm 진행률은 \r 로 같은 줄을 덮어쓰므로 마지막 조각만 보여준다
            return raw.split(b"\r")[-1].decode("utf-8", "replace") if raw.strip(b"\r") else ""

        try:
            await send({"type": "logs", "name": name, "reset": True, "lines": []})
            batch, buf, sent_partial, last = [], b"", "", time.monotonic()
            while True:
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(8192), timeout=0.2)
                except asyncio.TimeoutError:
                    chunk = None
                eof = chunk == b""
                if chunk:
                    buf += chunk
                    *done, buf = buf.split(b"\n")
                    batch += [last_segment(d) for d in done]
                # 아직 줄바꿈이 안 온 진행 중인 줄은 partial 로 보내 화면 마지막 줄을 계속 바꿔 끼운다
                partial = last_segment(buf)
                if (batch or partial != sent_partial) and (eof or time.monotonic() - last > 0.2 or len(batch) > 200):
                    await send({"type": "logs", "name": name, "lines": batch, "partial": partial})
                    batch, sent_partial, last = [], partial, time.monotonic()
                if eof:
                    break
        finally:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()

    async def reader():
        nonlocal log_task
        while True:
            msg = await ws.receive_json()
            if log_task:
                log_task.cancel()
                log_task = None
            kind = msg.get("sub")
            if kind == "job" and jobs.get(int(msg.get("id", 0))):
                sub.update(kind="job", id=int(msg["id"]), since=0, version=-1)
            elif kind == "logs" and msg.get("name") in docker.names():
                sub.update(kind="logs", name=msg["name"])
                log_task = asyncio.create_task(stream_container_logs(msg["name"]))
            else:
                sub.update(kind=None)
            if msg.get("refresh"):
                await send({"type": "state", **await state.build()})

    async def pusher():
        last_gpu = last_state = 0.0
        job_marks: dict[int, str] = {}
        while True:
            now = time.monotonic()
            if now - last_gpu >= 1:
                last_gpu = now
                await send({"type": "gpu", "gpus": await asyncio.to_thread(gpu.snapshot)})
            marks = {j.id: j.status for j in jobs.all_jobs()}
            if now - last_state >= 2 or marks != job_marks:
                last_state, job_marks = now, marks
                await send({"type": "state", **await state.build()})
            if sub["kind"] == "job":
                job = jobs.get(sub["id"])
                if job:
                    job.refresh()
                if job and job.version != sub["version"]:
                    # 진행률 줄은 같은 줄을 덮어쓰므로 마지막 줄 하나를 겹쳐서 다시 보낸다
                    start, lines = job.read(max(0, sub["since"] - 1))
                    sub["since"], sub["version"] = job.total, job.version
                    await send({"type": "job", **job.summary(), "from": start, "lines": lines})
            await asyncio.sleep(0.25)

    tasks = [asyncio.create_task(reader()), asyncio.create_task(pusher())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks + ([log_task] if log_task else []):
            t.cancel()
        with contextlib.suppress(Exception):
            await ws.close()

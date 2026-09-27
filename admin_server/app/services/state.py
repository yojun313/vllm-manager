"""화면 전체 상태(GPU 제외): 컨테이너 + 기동 진행률, 모델 목록, 작업 목록."""

import asyncio
import time

from app.config import API_KEY_FILE, VLLM_ENV
from app.services import docker, download, gpu, jobs, models, progress

_progress_cache: dict[str, tuple[float, dict]] = {}


def _progress(c: dict, healthy: bool) -> dict:
    if healthy:
        return progress.parse("", healthy=True)
    if c["state"] != "running":
        return {"key": "stopped", "stage": "중지됨", "pct": 0, "detail": c["status"], "error": ""}
    hit = _progress_cache.get(c["name"])
    if hit and time.time() - hit[0] < 2:
        return hit[1]
    p = progress.parse(docker.logs_tail(c["name"], 800))
    _progress_cache[c["name"]] = (time.time(), p)
    return p


def job_list() -> list[dict]:
    out = []
    for j in jobs.all_jobs():
        status = j.status
        if j.kind == "pull" and (status == "running" or j.meta.get("progress") is None or
                                 j.meta["progress"].get("final") is not True):
            p = download.progress(j.id, j.target, finished=status != "running")
            if status != "running":
                p["final"] = True
            jobs.update_meta(j, progress=p)
        out.append(j.summary())
    return out


_shared = {"at": 0.0, "value": None}
_build_lock = asyncio.Lock()


async def build(max_age: float = 1.5) -> dict:
    """모든 접속자(기기·브라우저)가 같은 상태를 보도록 한 번 계산한 결과를 짧게 공유한다."""
    async with _build_lock:
        if _shared["value"] is None or time.time() - _shared["at"] > max_age:
            _shared["value"] = await _build()
            _shared["at"] = time.time()
        return _shared["value"]


def invalidate():
    _shared["at"] = 0.0


async def _build() -> dict:
    ok, err = await asyncio.to_thread(docker.docker_ok)
    containers = await asyncio.to_thread(docker.list_containers) if ok else []
    served = await asyncio.to_thread(models.served_names)

    async def enrich(c):
        c = dict(c)
        c["health"] = await asyncio.to_thread(docker.healthy, c["port"]) if c["state"] == "running" else False
        c["progress"] = await asyncio.to_thread(_progress, c, c["health"])
        c["served"] = served.get(c["model"], c["model"])
        return c

    containers = await asyncio.gather(*(enrich(c) for c in containers))
    gpus = await asyncio.to_thread(gpu.snapshot)
    total = gpus[0]["total"] if gpus else 81920
    return {
        "image": VLLM_ENV.get("VLLM_IMAGE", ""),
        "docker_ok": ok, "docker_error": "" if ok else err,
        "containers": containers,
        "models": await asyncio.to_thread(models.list_models, total),
        "jobs": await asyncio.to_thread(job_list),
        "api_key": API_KEY_FILE.exists(),
    }

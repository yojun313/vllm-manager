"""모델 켜기/끄기/다운로드. 실제 작업은 전부 ../vllm 명령으로 한다 (services/jobs.py)."""

import json
import re
import subprocess

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.config import API_KEY_FILE, VLLM_BIN, VLLM_ROOT
from app.services import docker, jobs, models, state

router = APIRouter(prefix="/api")


def _require_docker():
    ok, err = docker.docker_ok()
    if not ok:
        raise HTTPException(503, "docker 권한이 없습니다. 서버를 실행한 사용자를 docker 그룹에 추가하세요 (sudo usermod -aG docker $USER).")


class UpBody(BaseModel):
    gpus: str = ""  # "" = 자동 선택, "0", "0,1"


class PullBody(BaseModel):
    repo: str
    alias: str = ""
    force: bool = False  # 이 서버 GPU 로 못 띄우는 모델이어도 받기 (화면에서 확인받은 뒤)


def _clean_repo(repo: str) -> str:
    repo = repo.strip().removeprefix("https://huggingface.co/").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repo):
        raise HTTPException(400, "HF repo id 형식이 아닙니다 (예: Qwen/Qwen3-8B)")
    return repo


@router.get("/state")
async def get_state():
    return await state.build()


@router.post("/models/{alias}/up")
def model_up(alias: str, body: UpBody):
    _require_docker()
    if not models.exists(alias):
        raise HTTPException(404, "없는 모델입니다")
    if body.gpus and not re.fullmatch(r"\d+(,\d+)*", body.gpus):
        raise HTTPException(400, "GPU 형식이 잘못됐습니다")
    args = ["up", alias] + (["-g", body.gpus] if body.gpus else [])
    where = f"GPU {body.gpus}" if body.gpus else "GPU 자동"
    state.invalidate()
    return jobs.start("up", f"{alias} 켜기 · {where}", args, target=alias).summary()


@router.post("/containers/{name}/down")
def container_down(name: str):
    _require_docker()
    if name not in docker.names():
        raise HTTPException(404, "없는 컨테이너입니다")
    state.invalidate()
    return jobs.start("down", f"{name} 끄기", ["down", name], target=name).summary()


@router.get("/pull/check")
def pull_check(repo: str):
    """받기 전에 이 서버 GPU 로 띄울 수 있는지 (./vllm fit, HF 정보만 사용)"""
    repo = _clean_repo(repo)
    r = subprocess.run([str(VLLM_BIN), "fit", repo, "--json"], cwd=VLLM_ROOT, capture_output=True, text=True,
                       timeout=90, stdin=subprocess.DEVNULL)
    try:
        return {"repo": repo, **json.loads(r.stdout.strip().splitlines()[-1])}
    except (ValueError, IndexError):
        return {"repo": repo, "fit": "unknown", "message": (r.stderr or r.stdout).strip()[-300:] or "계산 실패"}


@router.post("/pull")
def pull(body: PullBody):
    repo = _clean_repo(body.repo)
    alias = body.alias.strip()
    if alias and not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", alias):
        raise HTTPException(400, "별칭은 소문자, 숫자, . _ - 만 쓸 수 있습니다")
    state.invalidate()
    args = ["pull", repo] + ([alias] if alias else []) + (["--force"] if body.force else [])
    return jobs.start("pull", f"{repo} 다운로드", args, target=repo).summary()


@router.delete("/models/{alias}")
def model_delete(alias: str, files: bool = False):
    _require_docker()  # 실행 중인지 확인하고, root 소유 파일은 docker 로 지우므로
    if not models.exists(alias):
        raise HTTPException(404, "없는 모델입니다")
    running = [c["name"] for c in docker.list_containers(max_age=0) if c["model"] == alias]
    if running:
        raise HTTPException(409, f"실행 중인 모델은 지울 수 없습니다. 먼저 끄세요 ({', '.join(running)})")
    args = ["rm", alias] + (["--files"] if files else [])
    title = f"{alias} 삭제" + (" (가중치 포함)" if files else "")
    state.invalidate()
    return jobs.start("rm", title, args, target=alias).summary()


@router.get("/jobs/{job_id}")
def job_detail(job_id: int, since: int = 0):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "작업이 없습니다")
    start, lines = job.read(since)
    return {**job.summary(), "from": start, "lines": lines}


@router.get("/key", response_class=PlainTextResponse)
def api_key():
    if not API_KEY_FILE.exists():
        raise HTTPException(404, "API 키가 없습니다 (./vllm key new)")
    m = re.search(r"^VLLM_API_KEY=(.+)$", API_KEY_FILE.read_text(), re.M)
    return m.group(1).strip() if m else ""

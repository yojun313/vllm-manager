"""모델 켜기/끄기/다운로드/설정. 실제 작업은 전부 ../vllm 명령으로 한다 (services/jobs.py)."""

import asyncio
import json
import re
import subprocess

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from app import config
from app.config import API_KEY_FILE, VLLM_ROOT
from app.i18n import fail, tr
from app.services import docker, hf, jobs, models, state, system

router = APIRouter(prefix="/api")


def _require_docker(request: Request):
    ok, _ = docker.docker_ok()
    if not ok:
        raise fail(
            request,
            503,
            "Docker 권한이 없습니다. 서버 실행 계정을 docker 그룹에 추가해야 합니다 (sudo usermod -aG docker $USER).",
            "No Docker access. Add the account running this server to the docker group (sudo usermod -aG docker $USER).",
        )


def _require_model(request: Request, alias: str):
    if not models.exists(alias):
        raise fail(request, 404, "없는 모델입니다", "Unknown model")


class UpBody(BaseModel):
    gpus: str = ""  # "" = 자동 선택, "0", "0,1"


class PullBody(BaseModel):
    repo: str
    alias: str = ""
    force: bool = (
        False  # 이 서버 GPU 로 못 띄우는 모델이어도 받기 (화면에서 확인받은 뒤)
    )


class ConfigBody(BaseModel):
    text: str


class KeyBody(BaseModel):
    action: str  # new | off


class ChatBody(BaseModel):
    container: str
    messages: list[dict]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None


def _clean_repo(request: Request, repo: str) -> str:
    repo = repo.strip().removeprefix("https://huggingface.co/").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repo):
        raise fail(
            request,
            400,
            "Hugging Face 저장소 형식이 아닙니다 (예: Qwen/Qwen3-8B)",
            "Not a Hugging Face repo id (example: Qwen/Qwen3-8B)",
        )
    return repo


def _vllm(*args: str, timeout: float = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(config.VLLM_BIN), *args],
        cwd=VLLM_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )


@router.get("/state")
async def get_state():
    return await state.build()


@router.post("/models/{alias}/up")
def model_up(alias: str, body: UpBody, request: Request):
    _require_docker(request)
    _require_model(request, alias)
    if body.gpus and not re.fullmatch(r"\d+(,\d+)*", body.gpus):
        raise fail(request, 400, "GPU 형식이 잘못됐습니다", "Invalid GPU selection")
    args = ["up", alias] + (["-g", body.gpus] if body.gpus else [])
    where = f"GPU {body.gpus}" if body.gpus else "GPU 자동"
    state.invalidate()
    return jobs.start(
        "up", f"{alias} 켜기 · {where}", args, target=alias, extra={"gpus": body.gpus}
    ).summary()


@router.post("/containers/{name}/down")
def container_down(name: str, request: Request):
    _require_docker(request)
    if name not in docker.names():
        raise fail(request, 404, "없는 컨테이너입니다", "Unknown container")
    state.invalidate()
    return jobs.start("down", f"{name} 끄기", ["down", name], target=name).summary()


@router.get("/pull/check")
def pull_check(repo: str, request: Request):
    """받기 전에 이 서버 GPU 로 띄울 수 있는지 (./vllm fit, HF 정보만 사용)"""
    repo = _clean_repo(request, repo)
    r = _vllm("fit", repo, "--json")
    try:
        return {"repo": repo, **json.loads(r.stdout.strip().splitlines()[-1])}
    except (ValueError, IndexError):
        return {
            "repo": repo,
            "fit": "unknown",
            "message": (r.stderr or r.stdout).strip()[-300:],
        }


@router.post("/pull")
def pull(body: PullBody, request: Request):
    repo = _clean_repo(request, body.repo)
    alias = body.alias.strip()
    if alias and not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", alias):
        raise fail(
            request,
            400,
            "별칭은 소문자, 숫자, . _ - 만 쓸 수 있습니다",
            "An alias may contain lowercase letters, digits and . _ - only",
        )
    state.invalidate()
    args = (
        ["pull", repo]
        + ([alias] if alias else [])
        + (["--force"] if body.force else [])
    )
    return jobs.start("pull", f"{repo} 다운로드", args, target=repo).summary()


@router.get("/hf/search")
def hf_search(q: str, request: Request):
    if len(q) > 100:
        raise fail(request, 400, "검색어가 너무 깁니다", "Search text is too long")
    try:
        return {"results": hf.search(q)}
    except Exception:  # noqa: BLE001 - 외부망이 막힌 서버에서는 검색만 꺼진다
        return {
            "results": [],
            "error": tr(
                request,
                "Hugging Face에 연결할 수 없습니다",
                "Could not reach Hugging Face",
            ),
        }


@router.delete("/models/{alias}")
def model_delete(alias: str, request: Request, files: bool = False):
    _require_docker(
        request
    )  # 실행 중인지 확인하고, root 소유 파일은 docker 로 지우므로
    _require_model(request, alias)
    running = [
        c["name"] for c in docker.list_containers(max_age=0) if c["model"] == alias
    ]
    if running:
        raise fail(
            request,
            409,
            f"실행 중인 모델은 지울 수 없습니다. 먼저 모델을 중지해야 합니다 ({', '.join(running)})",
            f"A running model cannot be deleted. Stop it first ({', '.join(running)})",
        )
    args = ["rm", alias] + (["--files"] if files else [])
    title = f"{alias} 삭제" + (" (가중치 포함)" if files else "")
    state.invalidate()
    return jobs.start("rm", title, args, target=alias, extra={"files": files}).summary()


@router.get("/models/{alias}/config")
def model_config(alias: str, request: Request):
    _require_model(request, alias)
    return {"alias": alias, "text": models.read_config(alias)}


@router.put("/models/{alias}/config")
def model_config_save(alias: str, body: ConfigBody, request: Request):
    _require_model(request, alias)
    problem = models.validate_config(body.text)
    if problem:
        messages = {
            "too_large": ("설정 파일이 너무 큽니다", "The config file is too large"),
            "no_model": ("`model:` 항목이 필요합니다", "A `model:` entry is required"),
            "invalid": (
                "`키: 값` 형식의 줄과 `#` 주석만 사용할 수 있습니다",
                "Only `key: value` lines and `#` comments are allowed",
            ),
        }
        raise fail(request, 400, *messages[problem])
    models.write_config(alias, body.text)
    state.invalidate()
    return {"ok": True}


@router.get("/jobs/{job_id}")
def job_detail(job_id: int, request: Request, since: int = 0):
    job = jobs.get(job_id)
    if not job:
        raise fail(request, 404, "작업이 없습니다", "Unknown job")
    start, lines = job.read(since)
    return {**job.summary(), "from": start, "lines": lines}


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: int, request: Request):
    job = jobs.get(job_id)
    if not job:
        raise fail(request, 404, "작업이 없습니다", "Unknown job")
    if job.kind != "pull":
        raise fail(
            request,
            400,
            "다운로드 작업만 취소할 수 있습니다",
            "Only downloads can be cancelled",
        )
    if not job.cancel():
        raise fail(request, 409, "이미 끝난 작업입니다", "The job has already finished")
    state.invalidate()
    return {"ok": True}


def _read_key() -> str:
    if not API_KEY_FILE.exists():
        return ""
    m = re.search(r"^VLLM_API_KEY=(.+)$", API_KEY_FILE.read_text(), re.M)
    return m.group(1).strip() if m else ""


@router.get("/key", response_class=PlainTextResponse)
def api_key(request: Request):
    key = _read_key()
    if not key:
        raise fail(request, 404, "API 키가 없습니다", "No API key is set")
    return key


@router.post("/key")
def api_key_change(body: KeyBody, request: Request):
    """API 키 새로 만들기 / 끄기. 실행 중인 모델에는 재시작해야 적용된다."""
    if body.action not in ("new", "off"):
        raise fail(request, 400, "잘못된 요청입니다", "Invalid request")
    r = _vllm("key", body.action, timeout=20)
    if r.returncode != 0:
        raise HTTPException(500, (r.stderr or r.stdout).strip()[-300:])
    state.invalidate()
    system.invalidate()
    return {"ok": True, "enabled": API_KEY_FILE.exists()}


async def _chat_stream(url: str, payload: dict, headers: dict):
    """모델 서버의 SSE 를 그대로 전달한다. 오류는 `event: error` 한 건으로 알린다."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=5)) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as r:
                if r.status_code != 200:
                    text = (await r.aread()).decode("utf-8", "replace")
                    try:
                        detail = json.loads(text)
                        detail = (
                            detail.get("message")
                            or detail.get("error", {}).get("message")
                            or text
                        )
                    except (ValueError, AttributeError):
                        detail = text
                    yield f"event: error\ndata: {json.dumps({'status': r.status_code, 'message': str(detail)[:600]})}\n\n"
                    return
                async for chunk in r.aiter_raw():
                    yield chunk
    except (httpx.HTTPError, asyncio.CancelledError) as e:
        if isinstance(e, asyncio.CancelledError):
            raise
        yield f"event: error\ndata: {json.dumps({'status': 0, 'message': str(e)[:300] or type(e).__name__})}\n\n"


@router.post("/chat")
async def chat(body: ChatBody, request: Request):
    """플레이그라운드: 실행 중인 모델에 대화 요청을 보내고 응답을 스트리밍한다. API 키는 서버가 붙인다."""
    current = await state.build()
    c = next((x for x in current["containers"] if x["name"] == body.container), None)
    if not c or not c.get("health"):
        raise fail(
            request, 409, "실행 중인 모델이 아닙니다", "The model is not running"
        )
    if (
        not body.messages
        or len(body.messages) > 200
        or len(json.dumps(body.messages)) > 2_000_000
    ):
        raise fail(
            request,
            400,
            "메시지가 비어 있거나 너무 깁니다",
            "Messages are empty or too long",
        )
    for m in body.messages:
        if m.get("role") not in ("system", "user", "assistant") or not isinstance(
            m.get("content"), str
        ):
            raise fail(
                request,
                400,
                "메시지 형식이 올바르지 않습니다",
                "Invalid message format",
            )
    payload: dict = {
        "model": c["served"],
        "messages": [
            {"role": m["role"], "content": m["content"]} for m in body.messages
        ],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if body.temperature is not None:
        payload["temperature"] = max(0.0, min(2.0, body.temperature))
    if body.top_p is not None:
        payload["top_p"] = max(0.0, min(1.0, body.top_p))
    if body.max_tokens:
        payload["max_tokens"] = max(1, min(131072, body.max_tokens))
    key = _read_key()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return StreamingResponse(
        chat_stream(
            f"http://127.0.0.1:{c['port']}/v1/chat/completions", payload, headers, c
        ),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


def chat_stream(url: str, payload: dict, headers: dict, container: dict):
    """데모 모드에서 바꿔 끼우는 지점."""
    return _chat_stream(url, payload, headers)

"""데모 모드(VLLM_DEMO=1): GPU·Docker 없이 가상 데이터로 화면 전체를 띄운다.

실제 서비스 함수(docker, nvidia-smi, 지표, 디스크)를 가상 구현으로 바꿔 끼우고, 작업 실행기(`./vllm`)는
tools/demo/fake_vllm.py 로 대체한다. 그래서 켜기·끄기·다운로드·삭제·로그·플레이그라운드가 모두
화면에서 동작하지만 실제 컨테이너나 모델에는 아무 영향이 없다. 실행: `python tools/demo.py`
"""

import asyncio
import json
import math
import random
import sys
import time
from pathlib import Path

from app import config

sys.path.insert(0, str(config.REPO_ROOT / "tools" / "demo"))
import bootlog  # noqa: E402 - 가짜 실행기와 같은 기동 로그를 쓴다

STATE = config.VLLM_ROOT / "state.json"
GPU_NAME = "NVIDIA H100 80GB HBM3"
GPU_TOTAL = 81559
GPU_COUNT = 4
READY_AFTER = bootlog.READY_AFTER

# 별칭 → (GPU 수, GPU당 필요 MiB, plan.py 형식의 설명, 가중치 바이트)
PLANS = {
    "gpt-oss-120b": (
        2,
        44749,
        "가중치 30.4 + KV 9.4 (131,072토큰 × 동시 4) + 여유 4.0 = 43.7GiB/GPU",
        65_300_000_000,
    ),
    "gpt-oss-20b": (
        1,
        22220,
        "가중치 12.8 + KV 5.7 (131,072토큰 × 동시 4) + 여유 3.1 = 21.7GiB/GPU",
        13_800_000_000,
    ),
    "qwen3-vl-8b": (
        1,
        31130,
        "가중치 16.3 + KV 8.8 (65,536토큰 × 동시 4) + 여유 5.3 = 30.4GiB/GPU",
        17_500_000_000,
    ),
    "llama-3.3-70b": (
        2,
        56730,
        "가중치 65.7 + KV 12.5 (32,768토큰 × 동시 4) + 여유 5.8 = 55.4GiB/GPU",
        141_100_000_000,
    ),
    "bge-m3": (
        1,
        5530,
        "가중치 2.1 + KV 0.7 (8,192토큰 × 동시 4) + 여유 2.6 = 5.4GiB/GPU",
        2_270_000_000,
    ),
    "music-flamingo": (
        1,
        20890,
        "가중치 15.4 + KV 1.7 (8,192토큰 × 동시 4) + 여유 3.3 = 20.4GiB/GPU",
        16_500_000_000,
    ),
    "qwen3-omni-30b": (
        2,
        73400,
        "Omni 단계별 배포 · memory-fraction 0.9 → 71.7GiB/GPU",
        70_500_000_000,
    ),
}
# 모델별 평소 부하 (초당 생성 토큰, 동시 요청)
LOAD = {
    "gpt-oss-120b": (410, 6),
    "gpt-oss-20b": (980, 9),
    "qwen3-vl-8b": (260, 3),
    "bge-m3": (0, 2),
    "music-flamingo": (140, 1),
}

REPLY = (
    "이 응답은 데모 모드에서 생성한 예시입니다. 실제 설치에서는 선택한 모델이 직접 응답합니다.\n\n"
    "This reply comes from demo mode. On a real install, the model you selected answers here, "
    "and the figures below (time to first token, tokens per second, token counts) are measured "
    "from the live stream."
)


def load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"containers": []}


def _ready(c: dict) -> bool:
    return time.time() - c["created"] >= READY_AFTER


def _wave(seed: float, period: float = 90.0, t: float | None = None) -> float:
    """0~1 사이를 천천히 오가는 값 (화면이 살아 있는 것처럼 보이도록)."""
    t = time.time() if t is None else t
    return (
        0.5 + 0.35 * math.sin(t / period + seed) + 0.15 * math.sin(t / 7.0 + seed * 3)
    )


# ---------------------------------------------------------------- docker
def list_containers(max_age: float = 1.0) -> list[dict]:
    out = []
    for c in load()["containers"]:
        age = int(time.time() - c["created"])
        out.append(
            {
                "name": c["name"],
                "gpus": c["gpus"],
                "model": c["model"],
                "port": str(c["port"]),
                "mem": c["mem"],
                "status": f"Up {age // 3600} hours"
                if age >= 3600
                else f"Up {max(age // 60, 1)} minutes"
                if age >= 60
                else f"Up {age} seconds",
                "id": c["id"],
                "state": "running",
                "created": c["created"],
                "engine": c.get("engine", "vllm"),
            }
        )
    return out


def _by_port(port: str) -> dict | None:
    return next((c for c in load()["containers"] if str(c["port"]) == str(port)), None)


def healthy(port: str) -> bool:
    c = _by_port(port)
    return bool(c and _ready(c))


def _log_lines(name: str) -> list[str]:
    c = next((x for x in load()["containers"] if x["name"] == name), None)
    return bootlog.lines(c, LOAD.get(c["model"], (200, 2))) if c else []


def logs_tail(name: str, tail: int = 400) -> str:
    return "\n".join(_log_lines(name)[-tail:])


def logs_cmd(name: str, tail: int = 400) -> list[str]:
    script = "import sys,time\nfor l in sys.argv[1:]:\n    print(l, flush=True)\ntime.sleep(3600)"
    return ["python3", "-c", script, *_log_lines(name)[-tail:]]


def image_info(image: str) -> dict:
    sizes = {"vllm": 21_400_000_000, "audio": 21_900_000_000, "omni": 24_700_000_000}
    kind = "omni" if "omni" in image else "audio" if "audio" in image else "vllm"
    return {
        "image": image,
        "present": bool(image),
        "bytes": sizes[kind] if image else 0,
        "created": "2026-10-21T03:38:12",
    }


# ---------------------------------------------------------------- GPU
def _util(i: int, containers: list[dict], t: float) -> float:
    util = 2.0
    for c in containers:
        if str(i) in c["gpus"].split(",") and t - c["created"] >= READY_AFTER:
            util += (
                62
                * _wave(i * 1.7 + len(c["name"]), 600, t)
                * (0.35 if c["model"] == "bge-m3" else 1)
            )
    if i == GPU_COUNT - 1:
        util += 38 * _wave(9.1, 400, t)
    return max(0.0, min(99.0, util))


def gpu_snapshot(max_age: float = 0.9) -> list[dict]:
    containers = load()["containers"]
    gpus = []
    for i in range(GPU_COUNT):
        idx = str(i)
        ours = []
        for c in containers:
            if idx not in c["gpus"].split(","):
                continue
            loaded = min(1.0, (time.time() - c["created"]) / (READY_AFTER * 0.6))
            ours.append(
                {
                    "name": c["name"],
                    "model": c["model"],
                    "mib": c["mem"],
                    "real": int(c["mem"] * loaded),
                }
            )
        procs = []
        if i == GPU_COUNT - 1:
            procs = [
                {
                    "pid": "418220",
                    "mib": 9876,
                    "user": "mina",
                    "label": "diffusion-train",
                    "container": False,
                    "cmd": "python train.py",
                },
                {
                    "pid": "77102",
                    "mib": 2210,
                    "user": "root",
                    "label": "triton-asr",
                    "container": True,
                    "cmd": "tritonserver",
                },
            ]
        other = sum(p["mib"] for p in procs)
        used = sum(o["real"] for o in ours) + other + 420
        reserved = sum(o["mib"] for o in ours)
        util = _util(i, containers, time.time())
        gpus.append(
            {
                "idx": idx,
                "name": GPU_NAME,
                "total": GPU_TOTAL,
                "used": used,
                "other": other,
                "ours": [
                    {"name": o["name"], "model": o["model"], "mib": o["mib"]}
                    for o in ours
                ],
                "procs": procs,
                "unlisted": 0,
                "free_new": GPU_TOTAL
                - other
                - reserved
                - int(config.VLLM_ENV.get("SAFETY_MIB") or 2048),
                "util": round(util, 1),
                "temp": round(38 + util * 0.36 + 2 * _wave(i)),
                "power": round(72 + util * 2.9 + 8 * _wave(i * 2.3, 15)),
                "power_limit": 350.0,
            }
        )
    return gpus


# ---------------------------------------------------------------- 모델·지표
def plan(path: Path, tp: int, total_mib: int) -> dict:
    from app.services import models

    gpus, need, desc, _ = PLANS.get(
        path.stem,
        (
            1,
            24000,
            "가중치 14.0 + KV 6.0 (32,768토큰 × 동시 4) + 여유 3.4 = 23.4GiB/GPU",
            0,
        ),
    )
    b = models.breakdown(desc)
    return {"need_mib": need, "desc": desc, "ctx": b.get("tokens"), "breakdown": b}


def du_bytes(d: Path) -> int:
    for alias, (_, _, _, size) in PLANS.items():
        if alias.replace("-", "").replace(".", "") in d.name.lower().replace(
            "-", ""
        ).replace(".", "").replace("_", ""):
            return size
    return 12_400_000_000


_totals: dict[str, dict] = {}


def metrics_poll(containers: list[dict]) -> dict[str, dict]:
    from app.services import metrics

    out = {}
    for c in containers:
        if not healthy(c["port"]):
            continue
        tps, conc = LOAD.get(c["model"], (220, 2))
        w = _wave(len(c["name"]) * 0.9, 500)
        acc = _totals.setdefault(
            c["name"],
            {
                "gen": random.randint(2, 9) * 1_000_000,
                "req": random.randint(4000, 22000),
                "at": time.time(),
            },
        )
        dt = time.time() - acc["at"]
        acc["at"] = time.time()
        gen_tps = round(tps * (0.45 + w), 1)
        acc["gen"] += int(gen_tps * dt)
        acc["req"] += int(dt * conc / 6)
        out[c["name"]] = {
            "running": max(0, round(conc * (0.3 + w))),
            "waiting": 1 if w > 0.93 else 0,
            "kv_usage": round(0.06 + 0.3 * w, 3),
            "gen_total": acc["gen"],
            "prompt_total": int(acc["gen"] * 3.1),
            "req_total": acc["req"],
            "gen_tps": gen_tps,
            "prompt_tps": round(gen_tps * 2.6, 1),
            "rps": round(conc * (0.3 + w) / 6, 2),
            "ttft": round(0.18 + 0.22 * w, 3),
            "latency": round(2.4 + 3.1 * w, 3),
        }
    metrics._latest.clear()
    metrics._latest.update(out)
    return out


def download_progress(job_id: int, repo: str, finished: bool) -> dict:
    from app.services import jobs

    job = jobs.get(job_id)
    total = 17_500_000_000
    elapsed = time.time() - (job.started if job else time.time())
    done = (
        total
        if finished and job and job.status == "done"
        else min(total * 0.98, elapsed * 480_000_000)
    )
    speed = 0 if finished else 480_000_000
    return {
        "done": int(done),
        "total": total,
        "pct": round(done / total * 100, 1),
        "speed": speed,
        "eta": round((total - done) / speed) if speed else None,
    }


def hf_search(query: str, limit: int = 10) -> list[dict]:
    catalog = [
        ("Qwen/Qwen3-8B", 4_812_300, 1420, "text-generation"),
        ("Qwen/Qwen3-32B", 1_950_100, 980, "text-generation"),
        ("Qwen/Qwen3-VL-8B-Instruct", 2_210_400, 760, "image-text-to-text"),
        ("openai/gpt-oss-20b", 6_930_000, 4100, "text-generation"),
        ("openai/gpt-oss-120b", 3_480_000, 4300, "text-generation"),
        ("meta-llama/Llama-3.3-70B-Instruct", 2_740_000, 2600, "text-generation"),
        ("google/gemma-3-27b-it", 1_620_000, 1700, "image-text-to-text"),
        ("BAAI/bge-m3", 9_870_000, 2500, "sentence-similarity"),
        (
            "mistralai/Mistral-Small-3.2-24B-Instruct-2506",
            890_000,
            560,
            "text-generation",
        ),
    ]
    q = query.lower().strip()
    return [
        {
            "id": i,
            "downloads": d,
            "likes": l,
            "task": t,
            "gated": i.startswith("meta-llama/"),
        }
        for i, d, l, t in catalog
        if q in i.lower()
    ][:limit]


async def chat_stream(url: str, payload: dict, headers: dict, container: dict):
    await asyncio.sleep(0.25)
    words = REPLY.split(" ")
    for i, w in enumerate(words):
        chunk = {
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": w + (" " if i < len(words) - 1 else "")},
                }
            ]
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.03)
    prompt = sum(len(m["content"]) for m in payload["messages"]) // 3 + 12
    usage = {
        "choices": [],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": len(words) * 2,
            "total_tokens": prompt + len(words) * 2,
        },
    }
    yield f"data: {json.dumps(usage)}\n\n"
    yield "data: [DONE]\n\n"


def _seed_history() -> None:
    """화면을 열자마자 차트가 보이도록 지난 24시간을 채워 둔다."""
    from app.services import history

    now = time.time()
    containers = load()["containers"]
    names = {c["name"]: c["model"] for c in containers if _ready(c)}

    def point(t: float) -> dict:
        gpus = {}
        for i in range(GPU_COUNT):
            u = _util(i, containers, t)
            base = [44700, 44700, 37100, 12600][i]
            gpus[str(i)] = {
                "util": round(u, 1),
                "mem": base + int(900 * math.sin(t / 2600 + i)),
                "total": GPU_TOTAL,
                "temp": round(38 + u * 0.36),
                "power": round(72 + u * 2.9),
            }
        models = {
            n: {
                "tps": round(
                    LOAD.get(m, (200, 2))[0] * (0.45 + _wave(len(n) * 0.9, 500, t)), 1
                ),
                "running": max(
                    0,
                    round(
                        LOAD.get(m, (200, 2))[1] * (0.3 + _wave(len(n) * 0.9, 500, t))
                    ),
                ),
                "waiting": 0,
            }
            for n, m in names.items()
        }
        return {"t": t, "gpus": gpus, "models": models}

    for k in range(history.COARSE_KEEP - 60, 0, -1):
        history._coarse.append(point(now - 3600 - k * history.COARSE_SEC))
    for k in range(history.FINE_KEEP, 0, -1):
        p = point(now - k * history.FINE_SEC)
        history._fine.append(p)
        if k % 12 == 0:
            history._coarse.append(p)


def install() -> None:
    from app.routes import model_routes
    from app.services import docker, download, gpu, hf, history, metrics, models, system

    config.VLLM_BIN = config.REPO_ROOT / "tools" / "demo" / "fake_vllm.py"
    docker.docker_ok = lambda: (True, "")
    docker.list_containers = list_containers
    docker.healthy = healthy
    docker.logs_tail = logs_tail
    docker.logs_cmd = logs_cmd
    docker.server_version = lambda: "28.5.1"
    docker.image_info = image_info
    gpu.snapshot = gpu_snapshot
    models.plan = plan
    models.du_bytes = du_bytes
    metrics.poll = metrics_poll
    download.progress = download_progress
    hf.search = hf_search
    model_routes.chat_stream = chat_stream
    system._nvidia = lambda: {"driver": "575.57.08", "cuda": "12.9"}
    system.disks = lambda: [
        {
            "paths": [
                {"key": k, "path": config.VLLM_ENV.get(k, "")}
                for k in ("MODELS_DIR", "HF_CACHE_DIR", "VLLM_CACHE_DIR")
            ],
            "total": 3_840_000_000_000,
            "used": 1_462_000_000_000,
            "free": 2_378_000_000_000,
        }
    ]
    system.check_update = lambda force=False: {
        "behind": 0,
        "error": "",
        "checked": time.time(),
    }
    system.update_status = lambda: {"behind": 0, "error": "", "checked": time.time()}
    real_info = system.info

    def info(max_age: float = 10) -> dict:
        value = real_info(max_age)
        value["host"] = {
            **value["host"],
            "name": "gpu-node-01",
            "os": "Linux-6.8.0-87-generic-x86_64",
            "cpus": 64,
            "load": [3.42, 3.1, 2.87],
            "mem_total": 540_431_955_968,
            "mem_available": 421_000_000_000,
            "uptime": 2_246_400,
        }
        value["checks"] = {**value["checks"], "hf_cli": True, "hf_token": True}
        value["app"] = {**value["app"], "root": "/home/admin/vllm-manager"}
        return value

    system.info = info
    _seed_history()

#!/usr/bin/env python3
"""데모 모드로 관리 화면을 띄운다. GPU·Docker 가 없어도 되고 실제 모델과 설정은 건드리지 않는다.

    uv run --project server python tools/demo.py            # http://127.0.0.1:7998 · demo / vllm-manager-demo
    uv run --project server python tools/demo.py --port 9000 --host 0.0.0.0

가상 GPU 4장과 예시 모델이 든 임시 폴더를 만들어 그 안에서만 동작하며, 종료하면 폴더를 지운다.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER, PASSWORD = "demo", "vllm-manager-demo"

MODELS = {
    "gpt-oss-120b": "# gpus: 2\n# 자동 생성: openai/gpt-oss-120b (gpt_oss, 가중치 60.8 GiB)\nmodel: /models/openai__gpt-oss-120b\nserved-model-name: openai/gpt-oss-120b\nmax-model-len: auto\nreasoning-parser: openai_gptoss\ntool-call-parser: openai\nenable-auto-tool-choice: true\n",
    "gpt-oss-20b": "# gpus: 1\n# 자동 생성: openai/gpt-oss-20b (gpt_oss, 가중치 12.8 GiB)\nmodel: /models/openai__gpt-oss-20b\nserved-model-name: openai/gpt-oss-20b\nmax-model-len: auto\nreasoning-parser: openai_gptoss\ntool-call-parser: openai\nenable-auto-tool-choice: true\n",
    "qwen3-vl-8b": "# gpus: 1\n# 자동 생성: Qwen/Qwen3-VL-8B-Instruct (qwen3_vl, 가중치 16.3 GiB)\nmodel: /models/Qwen__Qwen3-VL-8B-Instruct\nserved-model-name: Qwen/Qwen3-VL-8B-Instruct\nmax-model-len: auto\ntool-call-parser: hermes\nenable-auto-tool-choice: true\n",
    "llama-3.3-70b": "# gpus: 2\n# 자동 생성: meta-llama/Llama-3.3-70B-Instruct (llama, 가중치 131.4 GiB)\nmodel: /models/meta-llama__Llama-3.3-70B-Instruct\nserved-model-name: meta-llama/Llama-3.3-70B-Instruct\nmax-model-len: 32768\ntool-call-parser: llama3_json\nenable-auto-tool-choice: true\n",
    "bge-m3": "# gpus: 1\n# 자동 생성: BAAI/bge-m3 (xlm-roberta, 가중치 2.1 GiB)\nmodel: /models/BAAI__bge-m3\nserved-model-name: BAAI/bge-m3\nrunner: pooling\nmax-model-len: 8192\n",
    "music-flamingo": "# gpus: 1\n# 자동 생성: nvidia/music-flamingo-hf (audioflamingo3, 가중치 15.4 GiB)\nmodel: /models/nvidia__music-flamingo-hf\nserved-model-name: nvidia/music-flamingo-hf\nmax-model-len: auto\n",
    "qwen3-omni-30b": "# engine: vllm-omni\n# gpus: 2\n# memory-fraction: 0.9\n# deploy-config: qwen3-omni.yaml\nmodel: /models/Qwen__Qwen3-Omni-30B-A3B-Instruct\nserved-model-name: Qwen/Qwen3-Omni-30B-A3B-Instruct\n",
}
ENV = """VLLM_IMAGE=vllm/vllm-openai:v0.29.0-cu129
VLLM_AUDIO_IMAGE=local/vllm-audio:0.29.0-cu129
VLLM_OMNI_IMAGE=local/vllm-omni:0.29.0-cu129
MODELS_DIR=/data/models
HF_CACHE_DIR=/data/models/hf-cache
VLLM_CACHE_DIR=/data/models/vllm-cache
GPU_COUNT=4
GPU_IDS=
PORT_BASE=8000
BIND_ADDR=0.0.0.0
KV_CONCURRENCY=4
AUTO_KV_GIB=16
SAFETY_MIB=2048
"""


def container(alias, gpus, port, mem, age, served, engine="vllm"):
    return {
        "name": f"vllm-{alias}-g{gpus.replace(',', '-')}",
        "gpus": gpus,
        "model": alias,
        "port": port,
        "mem": mem,
        "id": os.urandom(6).hex(),
        "created": time.time() - age,
        "engine": engine,
        "served": served,
        "path": "/models/" + served.replace("/", "__"),
    }


def job(directory, job_id, kind, title, target, age, took, status, lines, **extra):
    started = time.time() - age
    meta = {
        "id": job_id,
        "kind": kind,
        "title": title,
        "target": target,
        "args": [],
        "started": started,
        "ended": started + took,
        "status": status,
        "rc": 0 if status == "done" else 1,
        **extra,
    }
    (directory / f"{job_id}.json").write_text(json.dumps(meta, ensure_ascii=False))
    (directory / f"{job_id}.log").write_text("\n".join(lines) + "\n")


def build(root: Path, starting: bool) -> None:
    (root / "models").mkdir(parents=True)
    for alias, text in MODELS.items():
        (root / "models" / f"{alias}.yaml").write_text(text, encoding="utf-8")
    (root / ".env").write_text(ENV)
    (root / "api-key.env").write_text("VLLM_API_KEY=sk-demo-3f9a1c0b7e5d42a8b6c1\n")
    containers = [
        container("gpt-oss-120b", "0,1", 8000, 44749, 93_600, "openai/gpt-oss-120b"),
        container("qwen3-vl-8b", "2", 8002, 31130, 18_420, "Qwen/Qwen3-VL-8B-Instruct"),
        container("bge-m3", "2", 8003, 5530, 262_000, "BAAI/bge-m3"),
    ]
    if starting:
        containers.append(
            container("gpt-oss-20b", "3", 8004, 22220, 17, "openai/gpt-oss-20b")
        )
    (root / "state.json").write_text(json.dumps({"containers": containers}))
    jobs = root / "data" / "jobs"
    jobs.mkdir(parents=True)
    job(
        jobs,
        1,
        "pull",
        "Qwen/Qwen3-VL-8B-Instruct 다운로드",
        "Qwen/Qwen3-VL-8B-Instruct",
        96_000,
        410,
        "done",
        [
            "▶ 필요 메모리 확인 중 (HF 정보 기준, 아직 받지 않음)",
            "   ✅ GPU 1장으로 띄울 수 있습니다 (최소 19.4 GiB)",
            "▶ 다운로드: Qwen/Qwen3-VL-8B-Instruct → /data/models/Qwen__Qwen3-VL-8B-Instruct",
            "Fetching 14 files: 100%|████████████████████| 14/14",
            "✅ 설정 파일 생성: models/qwen3-vl-8b.yaml",
        ],
        progress={
            "done": 17_500_000_000,
            "total": 17_500_000_000,
            "pct": 100.0,
            "speed": 0,
            "eta": None,
            "final": True,
        },
    )
    job(
        jobs,
        2,
        "up",
        "gpt-oss-120b 켜기 · GPU 0,1",
        "gpt-oss-120b",
        93_640,
        96,
        "done",
        [
            "▶ 메모리 계산: 가중치 30.4 + KV 9.4 (131,072토큰 × 동시 4) + 여유 4.0 = 43.7GiB/GPU",
            "▶ 모델: gpt-oss-120b | 엔진: vllm | GPU: 0,1 | 포트: 8000 | 인증: 켜짐",
            "✅ 준비 완료: vllm-gpt-oss-120b-g0-1  →  http://localhost:8000/v1",
        ],
        gpus="0,1",
    )
    job(
        jobs,
        3,
        "up",
        "llama-3.3-70b 켜기 · GPU 2,3",
        "llama-3.3-70b",
        40_100,
        4,
        "failed",
        [
            "▶ 메모리 계산: 가중치 65.7 + KV 12.5 (32,768토큰 × 동시 4) + 여유 5.8 = 55.4GiB/GPU",
            "❌ GPU2 공간 부족: 필요 55.4GiB > 여유 41.2GiB",
            "❌ 띄울 수 없습니다. 다른 GPU(-g)를 쓰거나, ./vllm down <모델> 로 공간을 비우거나, 설정의 max-model-len 을 줄이세요.",
        ],
        gpus="2,3",
    )
    job(
        jobs,
        4,
        "up",
        "qwen3-vl-8b 켜기 · GPU 2",
        "qwen3-vl-8b",
        18_470,
        52,
        "done",
        [
            "▶ 메모리 계산: 가중치 16.3 + KV 8.8 (65,536토큰 × 동시 4) + 여유 5.3 = 30.4GiB/GPU",
            "✅ 준비 완료: vllm-qwen3-vl-8b-g2  →  http://localhost:8002/v1",
        ],
        gpus="2",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="vLLM Manager demo mode")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7998)
    ap.add_argument(
        "--no-starting",
        action="store_true",
        help="do not seed a model that is still starting",
    )
    args = ap.parse_args()

    root = Path(tempfile.mkdtemp(prefix="vllm-manager-demo-"))
    build(root, not args.no_starting)
    env = {
        **os.environ,
        "VLLM_DEMO": "1",
        "VLLM_ROOT_DIR": str(root),
        "VLLM_DATA_DIR": str(root / "data"),
        "ADMIN_USERNAME": USER,
        "ADMIN_PASSWORD": PASSWORD,
        "SESSION_SECRET": os.urandom(32).hex(),
        "COOKIE_SECURE": "false",
        "PYTHONUNBUFFERED": "1",
    }
    print(
        f"vLLM Manager demo · http://{args.host}:{args.port} · {USER} / {PASSWORD}",
        flush=True,
    )
    print(
        "Nothing here touches Docker, GPUs or your real models. Ctrl+C to stop.",
        flush=True,
    )
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                args.host,
                "--port",
                str(args.port),
                "--log-level",
                "warning",
            ],
            cwd=ROOT / "server",
            env=env,
            check=False,
        )
    except KeyboardInterrupt:
        pass
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()

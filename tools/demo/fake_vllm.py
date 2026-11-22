#!/usr/bin/env python3
"""데모 모드에서 `./vllm` 대신 실행되는 가짜 실행기. 실제 Docker·GPU 는 건드리지 않고
데모 폴더의 state.json 과 models/*.yaml 만 바꾼다. (server/app/demo.py 참고)"""

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("VLLM_ROOT_DIR") or os.getcwd())
STATE = ROOT / "state.json"
MODELS = ROOT / "models"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootlog  # noqa: E402


def say(text="", wait=0.0):
    print(text, flush=True)
    if wait:
        time.sleep(wait)


def load():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"containers": []}


def save(state):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    tmp.replace(STATE)


def yaml_of(alias):
    values, meta = {}, {}
    for line in (MODELS / f"{alias}.yaml").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#\s*([a-z-]+):\s*(\S+)", line)
        if m:
            meta[m.group(1)] = m.group(2)
        m = re.match(r"^([a-z0-9-]+):\s*(.*)$", line)
        if m:
            values[m.group(1)] = m.group(2)
    return values, meta


def cmd_up(args):
    alias = args[0]
    gpus = args[args.index("-g") + 1] if "-g" in args else ""
    values, meta = yaml_of(alias)
    need = {
        "gpt-oss-120b": 44749,
        "gpt-oss-20b": 22220,
        "qwen3-vl-8b": 31130,
        "llama-3.3-70b": 56730,
        "bge-m3": 5530,
        "music-flamingo": 20890,
        "qwen3-omni-30b": 73400,
    }.get(alias, 24000)
    state = load()
    if not gpus:
        used = {}
        for c in state["containers"]:
            for g in c["gpus"].split(","):
                used[g] = used.get(g, 0) + c["mem"]
        order = sorted((str(i) for i in range(4)), key=lambda g: used.get(g, 0))
        gpus = ",".join(sorted(order[: int(meta.get("gpus", "1"))], key=int))
    name = f"vllm-{alias}-g{gpus.replace(',', '-')}"
    say(f"▶ 메모리 계산: GPU당 {need / 1024:.1f}GiB", 0.6)
    old = next((c for c in state["containers"] if c["name"] == name), None)
    taken = {c["port"] for c in state["containers"] if c["name"] != name}
    port = (
        old["port"]
        if old
        else next(
            p for p in range(8000 + int(gpus.split(",")[0]), 8100) if p not in taken
        )
    )
    if old:
        say(f"▶ 기존 {name} 교체", 0.4)
    say(f"▶ 이미지 준비 완료 (기존 이미지 사용): vllm/vllm-openai:v0.29.0-cu129", 0.4)
    say(
        f"▶ 모델: {alias} | 엔진: {meta.get('engine', 'vllm')} | GPU: {gpus} | 포트: {port} | 인증: 켜짐",
        0.3,
    )
    state["containers"] = [c for c in state["containers"] if c["name"] != name] + [
        {
            "name": name,
            "gpus": gpus,
            "model": alias,
            "port": port,
            "mem": need,
            "id": os.urandom(6).hex(),
            "created": time.time(),
            "engine": meta.get("engine", "vllm"),
            "served": values.get("served-model-name", values.get("model", alias)),
            "path": values.get("model", alias),
        }
    ]
    save(state)
    say("------------------------------------------------------------")
    say("로그 표시 중... 준비되면 자동으로 빠져나옵니다 (Ctrl+C 해도 서버는 계속 실행)")
    say("------------------------------------------------------------")
    shown = 0
    started = time.time()
    while time.time() - started < bootlog.READY_AFTER + 1:
        lines = bootlog.lines(state["containers"][-1])
        for line in lines[shown:]:
            say(line)
        shown = len(lines)
        time.sleep(0.5)
    say()
    say("============================================================")
    say(f"✅ 준비 완료: {name}  →  http://localhost:{port}/v1")
    say("============================================================")


def cmd_down(args):
    state = load()
    target = args[0] if args else ""
    for c in state["containers"]:
        if not target or target in (c["name"], c["model"]):
            say(f"▶ {c['name']} 종료", 0.5)
    state["containers"] = [
        c
        for c in state["containers"]
        if target and target not in (c["name"], c["model"])
    ]
    save(state)


def cmd_pull(args):
    rest = [a for a in args if not a.startswith("-")]
    repo = rest[0]
    alias = rest[1] if len(rest) > 1 else repo.split("/")[-1].lower()
    say("▶ 필요 메모리 확인 중 (HF 정보 기준, 아직 받지 않음)", 0.8)
    say("   ✅ GPU 1장으로 띄울 수 있습니다 (최소 19.4 GiB)", 0.4)
    say(f"▶ 다운로드: {repo} → /data/models/{repo.replace('/', '__')}")
    for pct in range(0, 101, 4):
        print(
            f"Fetching 14 files: {pct:3d}%|{'█' * (pct // 5):<20}| {pct * 14 // 100}/14",
            end="\r",
            flush=True,
        )
        time.sleep(1.4)
    say()
    (MODELS / f"{alias}.yaml").write_text(
        f"# gpus: 1\n# 자동 생성: {repo}\nmodel: /models/{repo.replace('/', '__')}\nserved-model-name: {repo}\nmax-model-len: auto\n",
        encoding="utf-8",
    )
    say(f"✅ 설정 파일 생성: models/{alias}.yaml")
    say(f"실행: ./vllm up {alias}")


def cmd_rm(args):
    alias = next(a for a in args if not a.startswith("-"))
    if "--files" in args:
        say(f"▶ 가중치 삭제: /data/models/{alias}", 1.2)
        say("✅ 16G 확보")
    (MODELS / f"{alias}.yaml").unlink(missing_ok=True)
    say(f"✅ 모델 설정 삭제: models/{alias}.yaml")


def cmd_fit(args):
    repo = args[0]
    big = any(k in repo.lower() for k in ("405b", "671b", "1t"))
    time.sleep(0.6)
    if big:
        out = {
            "fit": "no",
            "message": "GPU 4장을 다 써도 띄울 수 없습니다: 최소 GPU당 104.2 GiB 필요 > 한 장 77.6 GiB",
            "need1_mib": 426700,
            "need_all_mib": 106700,
            "cap_mib": 79511,
            "gpus": 4,
        }
    else:
        out = {
            "fit": "ok",
            "message": "GPU 1장으로 띄울 수 있습니다 (최소 19.4 GiB)",
            "need1_mib": 19870,
            "need_all_mib": 7600,
            "cap_mib": 79511,
            "gpus": 4,
        }
    say(json.dumps(out, ensure_ascii=False) if "--json" in args else out["message"])


def cmd_key(args):
    f = ROOT / "api-key.env"
    if args and args[0] == "new":
        f.write_text("VLLM_API_KEY=sk-demo-" + os.urandom(12).hex() + "\n")
    elif args and args[0] == "off":
        f.unlink(missing_ok=True)
    else:
        say(f.read_text().split("=", 1)[1].strip() if f.exists() else "")


COMMANDS = {
    "up": cmd_up,
    "down": cmd_down,
    "pull": cmd_pull,
    "rm": cmd_rm,
    "fit": cmd_fit,
    "key": cmd_key,
    "setup": lambda a: None,
}

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in COMMANDS:
        sys.exit(f"demo: unsupported command '{command}'")
    COMMANDS[command](sys.argv[2:])

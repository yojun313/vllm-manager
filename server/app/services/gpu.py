"""GPU 실시간 상태. 메모리 분해(모델별/다른 프로세스/새 모델용 여유)는 ../lib/gpufree.py 를 그대로 써서
CLI(./vllm ps, up 의 용량 검사)와 숫자가 항상 같게 한다."""

import importlib.util
import os
import pwd
import threading
import time

from app import config
from app.config import LIB_DIR, managed_gpu_ids
from app.services import docker

_spec = importlib.util.spec_from_file_location("gpufree", LIB_DIR / "gpufree.py")
gpufree = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gpufree)


_snap = {"at": 0.0, "value": []}
_snap_lock = threading.Lock()


def snapshot(max_age: float = 0.9) -> list[dict]:
    """여러 접속자와 이력 수집기가 함께 부르므로 nvidia-smi 호출은 짧게 공유한다."""
    with _snap_lock:
        if time.time() - _snap["at"] > max_age:
            _snap["value"] = _snapshot()
            _snap["at"] = time.time()
        return _snap["value"]


def _snapshot() -> list[dict]:
    containers = docker.list_containers()
    gpus = gpufree.gpu_usage(
        [(c["name"], c["gpus"], c["mem"], c["id"]) for c in containers],
        "-",
        int(config.VLLM_ENV.get("SAFETY_MIB") or 2048),
    )
    # 루트 .env 의 GPU_COUNT / GPU_IDS 로 정한 GPU 만 보여주고 선택지로 쓴다
    allowed = set(managed_gpu_ids([g["idx"] for g in gpus]))
    gpus = [g for g in gpus if g["idx"] in allowed]
    extra = {
        row[0]: row
        for row in gpufree.smi(
            "index,utilization.gpu,temperature.gpu,power.draw,power.limit"
        )
    }
    name_to_model = {c["name"]: c["model"] for c in containers}
    for g in gpus:
        idx, util, temp, power, limit = extra.get(
            g["idx"], [g["idx"], "0", "0", "0", "0"]
        )
        g["util"] = _num(util)
        g["temp"] = _num(temp)
        g["power"] = _num(power)
        g["power_limit"] = _num(limit)
        g["ours"] = [
            {"name": n, "model": name_to_model.get(n, n), "mib": m}
            for n, m in g["ours"].items()
        ]
        g["procs"] = [_describe(p) for p in g.get("procs", [])]
        # 드라이버 예약분처럼 프로세스로 잡히지 않는 사용량
        g["unlisted"] = max(0, g["other"] - sum(p["mib"] for p in g["procs"]))
    return gpus


# PID → 설명. 명령줄은 프로세스가 살아 있는 동안 바뀌지 않으므로 캐시한다.
_proc_cache: dict[str, tuple[float, dict]] = {}
_names = {"at": 0.0, "value": {}}


def _container_names() -> dict[str, str]:
    """관리 대상이 아닌 컨테이너도 이름으로 보여주기 위한 전체 ID → 이름."""
    if time.time() - _names["at"] > 10:
        try:
            r = docker.run(
                ["docker", "ps", "--no-trunc", "--format", "{{.ID}}\t{{.Names}}"],
                timeout=5,
            )
            _names["value"] = dict(
                line.split("\t", 1) for line in r.stdout.splitlines() if "\t" in line
            )
        except Exception:
            _names["value"] = {}
        _names["at"] = time.time()
    return _names["value"]


def _describe(p: dict) -> dict:
    pid = p["pid"]
    hit = _proc_cache.get(pid)
    if not hit or hit[1]["exe"] != p["exe"]:
        hit = (time.time(), {"exe": p["exe"], **_inspect(pid, p["exe"])})
        _proc_cache[pid] = hit
        if len(_proc_cache) > 256:
            for k in sorted(_proc_cache, key=lambda k: _proc_cache[k][0])[:128]:
                _proc_cache.pop(k, None)
    info = hit[1]
    container = (
        _container_names().get(p["container"], p["container"][:12])
        if p["container"]
        else ""
    )
    return {
        "pid": pid,
        "mib": p["mib"],
        "user": info["user"],
        "label": container or info["label"],
        "container": bool(container),
        "cmd": info["cmd"],
    }


def _inspect(pid: str, exe: str) -> dict:
    """사용자와 짧은 이름. 명령줄 전체는 비밀값이 섞일 수 있어 실행 파일과 스크립트만 남긴다."""
    user = ""
    try:
        user = pwd.getpwuid(os.stat(f"/proc/{pid}").st_uid).pw_name
    except (OSError, KeyError):
        pass
    args = []
    try:
        args = [
            a
            for a in open(f"/proc/{pid}/cmdline", "rb")
            .read()
            .decode(errors="replace")
            .split("\0")
            if a
        ]
    except OSError:
        pass
    prog = args[0] if args else exe
    script = ""
    for a in args[1:]:
        if a == "-m":
            continue
        if a == "-c":  # 인라인 코드는 표시하지 않는다
            script = "-c"
            break
        if not a.startswith("-"):
            script = a
            break
    cmd = " ".join(x for x in (os.path.basename(prog), script) if x)
    # /home/x/proj/.venv/bin/python → proj
    label = ""
    for path in (prog, exe, script):
        if "/.venv/" in path or "/venv/" in path:
            label = os.path.basename(path.split("/.venv/")[0].split("/venv/")[0])
            break
    if not label:
        label = (
            os.path.basename(script)
            if script and script != "-c"
            else os.path.basename(prog or exe) or f"PID {pid}"
        )
    return {"user": user, "label": label, "cmd": cmd}


def _num(v: str) -> float:
    try:
        return float(v)
    except ValueError:
        return 0.0

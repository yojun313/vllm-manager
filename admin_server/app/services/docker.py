"""docker CLI 호출. ../vllm 이 붙인 라벨(vllm-serve.*)로 우리 컨테이너만 본다.

관리 서버는 sudo 없이 docker 를 써야 한다(비밀번호 입력 불가). 권한이 없으면 화면에 안내가 뜬다.
"""

import subprocess
import time
import urllib.request
from datetime import datetime

LABEL = "vllm-serve"
_FMT = "\t".join([
    "{{.Names}}", f'{{{{.Label "{LABEL}.gpus"}}}}', f'{{{{.Label "{LABEL}.model"}}}}',
    f'{{{{.Label "{LABEL}.port"}}}}', f'{{{{.Label "{LABEL}.mem"}}}}', "{{.Status}}", "{{.ID}}", "{{.State}}",
    "{{.CreatedAt}}",
])

_cache = {"at": 0.0, "value": []}


def run(cmd: list[str], timeout: float = 20) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def docker_ok() -> tuple[bool, str]:
    # `docker info --format ...` 는 데몬 권한이 없어도 종료 코드 0 이라 믿을 수 없다 → docker ps 로 확인
    try:
        r = run(["docker", "ps", "-q", "--filter", f"label={LABEL}.gpus"], timeout=10)
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def list_containers(max_age: float = 1.0) -> list[dict]:
    """GPU 실시간 표시가 1초마다 부르므로 짧게 캐시한다."""
    if time.time() - _cache["at"] < max_age:
        return _cache["value"]
    r = run(["docker", "ps", "-a", "--filter", f"label={LABEL}.gpus", "--format", _FMT])
    out = []
    for line in r.stdout.splitlines():
        f = line.split("\t")
        if len(f) < 9:
            continue
        out.append({"name": f[0], "gpus": f[1], "model": f[2], "port": f[3],
                    "mem": int(f[4]) if f[4].isdigit() else None,
                    "status": f[5], "id": f[6], "state": f[7], "created": _epoch(f[8])})
    _cache.update(at=time.time(), value=out)
    return out


def _epoch(created: str) -> float:
    # "2026-09-27 04:10:11 +0900 KST" → epoch 초 (화면에서 기동 경과 시간 표시용)
    try:
        return datetime.strptime(created[:25], "%Y-%m-%d %H:%M:%S %z").timestamp()
    except ValueError:
        return 0.0


def invalidate():
    _cache["at"] = 0.0


def names() -> set[str]:
    return {c["name"] for c in list_containers(max_age=0)}


def logs_tail(name: str, tail: int = 400) -> str:
    r = run(["docker", "logs", "--tail", str(tail), name], timeout=20)
    return r.stdout + r.stderr


def healthy(port: str) -> bool:
    if not port or not port.isdigit():
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False

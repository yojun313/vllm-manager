"""호스트·디스크·Docker·버전 정보와 설치 상태 점검 (시스템 페이지)."""

import os
import platform
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

from app import config
from app.config import API_KEY_FILE, VLLM_ENV
from app.services import docker

_cache = {"at": 0.0, "value": None}
_update = {"at": 0.0, "behind": None, "error": ""}
_update_lock = threading.Lock()

CONFIG_KEYS = [
    "VLLM_IMAGE",
    "VLLM_AUDIO_IMAGE",
    "VLLM_OMNI_IMAGE",
    "MODELS_DIR",
    "HF_CACHE_DIR",
    "VLLM_CACHE_DIR",
    "GPU_COUNT",
    "GPU_IDS",
    "PORT_BASE",
    "BIND_ADDR",
    "KV_CONCURRENCY",
    "AUTO_KV_GIB",
    "SAFETY_MIB",
]


def _meminfo() -> dict:
    out = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            if k in ("MemTotal", "MemAvailable"):
                out[k] = int(v.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return out


def _nvidia() -> dict:
    try:
        r = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return {"driver": "", "cuda": ""}
    import re

    d = re.search(r"Driver Version:\s*([\d.]+)", r.stdout)
    c = re.search(r"CUDA Version:\s*([\d.]+)", r.stdout)
    return {"driver": d.group(1) if d else "", "cuda": c.group(1) if c else ""}


def disks() -> list[dict]:
    seen: dict[int, dict] = {}
    for key in ("MODELS_DIR", "HF_CACHE_DIR", "VLLM_CACHE_DIR"):
        path = VLLM_ENV.get(key, "")
        probe = Path(path)
        while path and not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            dev = os.stat(probe).st_dev
            usage = shutil.disk_usage(probe)
        except OSError:
            continue
        row = seen.setdefault(
            dev,
            {"paths": [], "total": usage.total, "used": usage.used, "free": usage.free},
        )
        row["paths"].append({"key": key, "path": path})
    return list(seen.values())


def _git(*args: str, timeout: float = 20) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": "ssh -oBatchMode=yes -oConnectTimeout=8",
    }
    return subprocess.run(
        ["git", "-C", str(config.REPO_ROOT), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def check_update(force: bool = False) -> dict:
    """원격 기본 브랜치보다 몇 커밋 뒤에 있는지. 네트워크를 쓰므로 6시간에 한 번만 확인한다."""
    with _update_lock:
        if force or time.time() - _update["at"] > 6 * 3600:
            _update["at"] = time.time()
            try:
                f = _git("fetch", "--quiet", "origin")
                if f.returncode != 0:
                    raise RuntimeError(f.stderr.strip()[-200:] or "git fetch failed")
                head = (
                    _git(
                        "symbolic-ref", "--short", "refs/remotes/origin/HEAD"
                    ).stdout.strip()
                    or "origin/main"
                )
                n = _git("rev-list", "--count", f"HEAD..{head}").stdout.strip()
                _update.update(behind=int(n) if n.isdigit() else None, error="")
            except Exception as e:  # noqa: BLE001
                _update.update(behind=None, error=str(e)[:200])
        return {
            "behind": _update["behind"],
            "error": _update["error"],
            "checked": _update["at"],
        }


def update_status() -> dict:
    if _update["at"] == 0:
        threading.Thread(target=check_update, daemon=True).start()
    return {
        "behind": _update["behind"],
        "error": _update["error"],
        "checked": _update["at"],
    }


def info(max_age: float = 10) -> dict:
    if _cache["value"] is not None and time.time() - _cache["at"] < max_age:
        return {**_cache["value"], "update": update_status()}
    ok, err = docker.docker_ok()
    images = (
        [
            {"role": role, **docker.image_info(VLLM_ENV.get(key, ""))}
            for role, key in (
                ("vllm", "VLLM_IMAGE"),
                ("audio", "VLLM_AUDIO_IMAGE"),
                ("omni", "VLLM_OMNI_IMAGE"),
            )
            if VLLM_ENV.get(key)
        ]
        if ok
        else []
    )
    mem = _meminfo()
    try:
        load = os.getloadavg()
    except OSError:
        load = (0.0, 0.0, 0.0)
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        uptime = 0.0
    hf_cli = bool(
        shutil.which("hf")
        or shutil.which("huggingface-cli")
        or (config.SERVICE_DIR / ".venv" / "bin" / "hf").exists()
    )
    value = {
        "app": {
            "version": config.APP_VERSION,
            "commit": config.APP_COMMIT,
            "root": str(config.REPO_ROOT),
        },
        "host": {
            "name": socket.gethostname(),
            "os": platform.platform(terse=True),
            "cpus": os.cpu_count() or 0,
            "load": [round(x, 2) for x in load],
            "mem_total": mem.get("MemTotal", 0),
            "mem_available": mem.get("MemAvailable", 0),
            "uptime": uptime,
        },
        "nvidia": _nvidia(),
        "docker": {
            "ok": ok,
            "error": "" if ok else err,
            "version": docker.server_version() if ok else "",
        },
        "images": images,
        "disks": disks(),
        "config": [{"key": k, "value": VLLM_ENV.get(k, "")} for k in CONFIG_KEYS],
        "server": {
            "host": config.HOST,
            "port": config.PORT,
            "cookie_secure": config.COOKIE_SECURE,
            "session_days": config.SESSION_DAYS,
            "password_hashed": True,
            "username": config.ADMIN_USERNAME,
        },
        "checks": {
            "docker": ok,
            "hf_cli": hf_cli,
            "hf_token": (Path.home() / ".cache/huggingface/token").exists(),
            "api_key": API_KEY_FILE.exists(),
            "images": all(i["present"] for i in images) if images else False,
        },
    }
    _cache.update(at=time.time(), value=value)
    return {**value, "update": update_status()}


def invalidate() -> None:
    _cache["at"] = 0.0

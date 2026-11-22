"""웹에서 바꾸는 설정. 루트 .env(모델 실행 설정)와 server/.env(관리 서버 설정)의 정해진 키만 다룬다.

- 실행 설정은 저장 즉시 적용된다(다음에 켜는 모델부터). `./vllm` 은 실행할 때마다 .env 를 다시 읽는다.
- 관리 서버의 주소·포트·쿠키 설정은 서버를 재시작해야 적용된다 (restart=True).
"""

import os
import re
from pathlib import Path

from app import config

_IMAGE = r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}"
_PATH = r"/[^\0\n\r'\"$`\\]{0,1023}"
_IP = r"(\d{1,3}\.){3}\d{1,3}"

# key → (파일, 종류, 검증, 재시작 필요)
SCHEMA: dict[str, dict] = {
    "MODELS_DIR": {"file": "root", "group": "storage", "type": "path", "re": _PATH},
    "HF_CACHE_DIR": {"file": "root", "group": "storage", "type": "path", "re": _PATH},
    "VLLM_CACHE_DIR": {"file": "root", "group": "storage", "type": "path", "re": _PATH},
    "GPU_IDS": {"file": "root", "group": "gpu", "type": "text", "re": r"(\d+(,\d+)*)?"},
    "GPU_COUNT": {
        "file": "root",
        "group": "gpu",
        "type": "int",
        "min": 1,
        "max": 64,
        "optional": True,
    },
    "PORT_BASE": {
        "file": "root",
        "group": "network",
        "type": "int",
        "min": 1024,
        "max": 65000,
    },
    "BIND_ADDR": {"file": "root", "group": "network", "type": "text", "re": _IP},
    "VLLM_IMAGE": {"file": "root", "group": "images", "type": "text", "re": _IMAGE},
    "VLLM_AUDIO_IMAGE": {
        "file": "root",
        "group": "images",
        "type": "text",
        "re": f"({_IMAGE})?",
    },
    "VLLM_OMNI_IMAGE": {
        "file": "root",
        "group": "images",
        "type": "text",
        "re": f"({_IMAGE})?",
    },
    "KV_CONCURRENCY": {
        "file": "root",
        "group": "memory",
        "type": "int",
        "min": 1,
        "max": 1024,
    },
    "AUTO_KV_GIB": {
        "file": "root",
        "group": "memory",
        "type": "int",
        "min": 1,
        "max": 1024,
    },
    "SAFETY_MIB": {
        "file": "root",
        "group": "memory",
        "type": "int",
        "min": 0,
        "max": 65536,
    },
    "HOST": {
        "file": "server",
        "group": "console",
        "type": "text",
        "re": _IP,
        "restart": True,
    },
    "PORT": {
        "file": "server",
        "group": "console",
        "type": "int",
        "min": 1,
        "max": 65535,
        "restart": True,
    },
    "COOKIE_SECURE": {
        "file": "server",
        "group": "console",
        "type": "bool",
        "restart": True,
    },
    "SESSION_DAYS": {
        "file": "server",
        "group": "console",
        "type": "int",
        "min": 1,
        "max": 365,
        "restart": True,
    },
}
_SERVER_DEFAULTS = {
    "HOST": "0.0.0.0",
    "PORT": "8000",
    "COOKIE_SECURE": "true",
    "SESSION_DAYS": "14",
}


def _server_env() -> dict:
    if config.DEMO or not config.SERVER_ENV_FILE.exists():
        return {}
    return config.read_env_file(config.SERVER_ENV_FILE)


def current() -> dict:
    server = {**_SERVER_DEFAULTS, **_server_env()}
    values = {}
    for key, spec in SCHEMA.items():
        values[key] = (config.VLLM_ENV if spec["file"] == "root" else server).get(
            key, ""
        )
    return {
        "values": values,
        "schema": {
            k: {f: v for f, v in s.items() if f != "re"} for k, s in SCHEMA.items()
        },
        "public_urls": dict(
            sorted(config.MODEL_PUBLIC_URLS.items(), key=lambda kv: int(kv[0]))
        ),
    }


def _clean(key: str, raw) -> str:
    spec = SCHEMA[key]
    value = (
        str(raw).strip() if not isinstance(raw, bool) else ("true" if raw else "false")
    )
    if spec["type"] == "bool":
        if value.lower() not in ("true", "false"):
            raise ValueError(key)
        return value.lower()
    if spec["type"] == "int":
        if value == "" and spec.get("optional"):
            return ""
        if (
            not re.fullmatch(r"\d{1,6}", value)
            or not spec["min"] <= int(value) <= spec["max"]
        ):
            raise ValueError(key)
        return str(int(value))
    if not re.fullmatch(spec["re"], value):
        raise ValueError(key)
    if spec["type"] == "path":
        value = os.path.normpath(value)
    return value


def update(values: dict, public_urls: dict | None = None) -> dict:
    """검증을 모두 통과한 경우에만 기록한다. 반환: {"changed": [...], "restart": bool}"""
    root, server, changed, restart = {}, {}, [], False
    before = current()["values"]
    for key, raw in values.items():
        if key not in SCHEMA:
            raise ValueError(key)
        value = _clean(key, raw)
        if value == before.get(key, ""):
            continue
        (root if SCHEMA[key]["file"] == "root" else server)[key] = value
        changed.append(key)
        restart = restart or bool(SCHEMA[key].get("restart"))
    urls = None
    if public_urls is not None:
        urls = {}
        for port, url in public_urls.items():
            url = str(url).strip()
            if not re.fullmatch(r"\d{2,5}", str(port)) or not re.fullmatch(
                r"[A-Za-z0-9._~:/?#\[\]@!&()*+,;=%-]{0,300}", url
            ):
                raise ValueError(f"MODEL_PUBLIC_URL_{port}")
            if url:
                urls[str(port)] = url
        if urls != config.MODEL_PUBLIC_URLS:
            changed.append("MODEL_PUBLIC_URLS")
    if config.DEMO:
        config.VLLM_ENV.update(root)
        if urls is not None:
            config.MODEL_PUBLIC_URLS.clear()
            config.MODEL_PUBLIC_URLS.update(urls)
        return {"changed": changed, "restart": False}
    for key in ("MODELS_DIR", "HF_CACHE_DIR", "VLLM_CACHE_DIR"):
        if key in root:
            try:
                Path(root[key]).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise PermissionError(f"{root[key]}: {e.strerror}") from e
    if root:
        config.write_env_values(config.ROOT_ENV_FILE, root)
        config.VLLM_ENV.update(root)
    if urls is not None and "MODEL_PUBLIC_URLS" in changed:
        gone = {
            f"MODEL_PUBLIC_URL_{p}": None
            for p in config.MODEL_PUBLIC_URLS
            if p not in urls
        }
        server.update(gone)
        server.update({f"MODEL_PUBLIC_URL_{p}": u for p, u in urls.items()})
        config.MODEL_PUBLIC_URLS.clear()
        config.MODEL_PUBLIC_URLS.update(urls)
    if server:
        config.write_env_values(config.SERVER_ENV_FILE, server)
    return {"changed": changed, "restart": restart}

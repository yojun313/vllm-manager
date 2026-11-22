"""경로와 설정. 관리 서버 자체 설정은 server/.env, vLLM 쪽 설정은 루트 .env 에서 읽는다."""

import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

SERVICE_DIR = Path(__file__).resolve().parent.parent  # server/
REPO_ROOT = SERVICE_DIR.parent  # 저장소 루트
# 데모 모드는 가상 모델·가짜 실행기가 든 별도 폴더를 루트로 쓴다
VLLM_ROOT = Path(os.getenv("VLLM_ROOT_DIR", "") or REPO_ROOT)
SERVER_ENV_FILE = SERVICE_DIR / ".env"
ROOT_ENV_FILE = VLLM_ROOT / ".env"

# 데모 모드: GPU·Docker 없이 가상 데이터로 화면만 띄운다 (tools/demo.py)
DEMO = os.getenv("VLLM_DEMO", "") == "1"

if not DEMO:
    load_dotenv(SERVER_ENV_FILE)

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip()
# 비밀번호는 해시(ADMIN_PASS_HASH, ./vllm configure 가 기록)를 우선하고, 예전 방식의 평문(ADMIN_PASSWORD)도 받는다
ADMIN_PASS_HASH = os.getenv("ADMIN_PASS_HASH", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
# 관리자 계정이 아직 없으면 "초기 설정" 상태로 뜬다. 터미널에 찍힌 일회용 주소(/setup?token=…)로 들어가
# 웹에서 계정을 만든다. 토큰이 있어야 하므로 포트가 외부에 열려 있어도 다른 사람이 먼저 차지할 수 없다.
SETUP_MODE = not ADMIN_USERNAME or not (ADMIN_PASS_HASH or ADMIN_PASSWORD)
SETUP_TOKEN = os.urandom(18).hex() if SETUP_MODE else ""

# 세션 서명 키. 비워두면 재시작할 때마다 새로 만들어져 모두 로그아웃된다.
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip() or os.urandom(32).hex()
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "14"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# 주소 복사에 사용할 포트별 외부 URL. 설정한 문자열 그대로 전달한다.
MODEL_PUBLIC_URLS = {
    key[len("MODEL_PUBLIC_URL_") :]: value.strip()
    for key, value in os.environ.items()
    if re.fullmatch(r"MODEL_PUBLIC_URL_\d+", key) and value.strip()
}

VLLM_BIN = VLLM_ROOT / "vllm"
CONFIG_DIR = VLLM_ROOT / "models"
LIB_DIR = REPO_ROOT / "lib"
API_KEY_FILE = VLLM_ROOT / "api-key.env"
DATA_DIR = Path(os.getenv("VLLM_DATA_DIR", "") or SERVICE_DIR / "data")


def read_env_file(path: Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
        if m:
            env[m.group(1)] = m.group(2).strip().strip("'\"")
    return env


def write_env_values(path: Path, values: dict[str, str | None]) -> None:
    """.env 의 해당 키만 바꾼다(None 이면 줄 삭제). 주석과 나머지 줄은 그대로 둔다."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    left = dict(values)
    out = []
    for line in lines:
        m = re.match(r"^([A-Z0-9_]+)=", line.strip())
        if m and m.group(1) in left:
            value = left.pop(m.group(1))
            if value is not None:
                out.append(f"{m.group(1)}={value}")
            continue
        out.append(line)
    out += [f"{k}={v}" for k, v in left.items() if v is not None]
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    tmp.replace(path)


_DEFAULT_ENV = {
    "VLLM_IMAGE": "vllm/vllm-openai:v0.29.0-cu129",
    "VLLM_AUDIO_IMAGE": "",
    "VLLM_OMNI_IMAGE": "",
    "MODELS_DIR": str(Path.home() / "vllm-models"),
    "HF_CACHE_DIR": str(Path.home() / "vllm-models" / "hf-cache"),
    "VLLM_CACHE_DIR": str(Path.home() / "vllm-models" / "vllm-cache"),
    "PORT_BASE": "8000",
    "BIND_ADDR": "0.0.0.0",
    "KV_CONCURRENCY": "4",
    "AUTO_KV_GIB": "16",
    "SAFETY_MIB": "2048",
}

if not ROOT_ENV_FILE.exists() and not DEMO:
    # 첫 실행: 감지한 GPU·경로로 기본 설정을 만든다 (이후 웹의 설정 화면이나 `./vllm configure` 로 변경)
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "setup.py"), "--ensure"], check=False
    )
VLLM_ENV = {
    **_DEFAULT_ENV,
    **(read_env_file(ROOT_ENV_FILE) if ROOT_ENV_FILE.exists() else {}),
}
SAFETY_MIB = int(VLLM_ENV.get("SAFETY_MIB") or "2048")


def managed_gpu_ids(detected: list[str]) -> list[str]:
    """루트 .env 의 GPU_IDS > GPU_COUNT > 감지된 전체 (./vllm 의 gpu_ids 와 같은 규칙)"""
    ids = VLLM_ENV.get("GPU_IDS", "").strip()
    count = VLLM_ENV.get("GPU_COUNT", "").strip()
    if ids:
        return [g for g in (x.strip() for x in ids.split(",")) if g in detected]
    if count.isdigit() and int(count) > 0:
        return detected[: int(count)]
    return detected


def _version() -> str:
    try:
        return (REPO_ROOT / "VERSION").read_text().strip()
    except OSError:
        return "dev"


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


APP_VERSION = _version()
APP_COMMIT = _commit()

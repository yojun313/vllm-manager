"""경로와 설정. 관리 서버 자체 설정은 admin_server/.env, vLLM 쪽 설정은 ../vllm.env 에서 읽는다."""

import os
import re
from pathlib import Path

from dotenv import load_dotenv

SERVICE_DIR = Path(__file__).resolve().parent.parent  # admin_server/
VLLM_ROOT = SERVICE_DIR.parent  # vllm/
load_dotenv(SERVICE_DIR / ".env")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
if not ADMIN_USERNAME or not ADMIN_PASSWORD:
    raise SystemExit("admin_server/.env 에 ADMIN_USERNAME, ADMIN_PASSWORD 를 설정하세요 (.env.example 참고)")

# 세션 서명 키. 비워두면 재시작할 때마다 새로 만들어져 모두 로그아웃된다.
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip() or os.urandom(32).hex()
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "14"))

VLLM_BIN = VLLM_ROOT / "vllm"
CONFIG_DIR = VLLM_ROOT / "models"
LIB_DIR = VLLM_ROOT / "lib"
API_KEY_FILE = VLLM_ROOT / "api-key.env"


def _read_env_file(path: Path) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m:
            env[m.group(1)] = m.group(2).strip().strip("'\"")
    return env


VLLM_ENV = _read_env_file(VLLM_ROOT / "vllm.env")
SAFETY_MIB = int(VLLM_ENV.get("SAFETY_MIB", "2048"))

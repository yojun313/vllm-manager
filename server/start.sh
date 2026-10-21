#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONUNBUFFERED=1
export BUILDKIT_PROGRESS=plain
echo "[시작] uv로 관리 서버 Python 환경을 준비합니다."
if ! command -v uv >/dev/null; then
    export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null; then
    echo "[실패] uv가 설치되어 있지 않습니다. uv 설치 후 다시 시작해야 합니다." >&2
    exit 78
fi
if ! uv sync --project "$ROOT/server" --python 3.12; then
    echo "[실패] Python 환경 준비에 실패했습니다." >&2
    exit 78
fi
echo "[완료] 관리 서버 Python 환경이 준비되었습니다."
exec "$ROOT/server/.venv/bin/python" -u "$ROOT/server/run.py"

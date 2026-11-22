#!/usr/bin/env bash
# 관리 서버 실행기. ./vllm server, systemd, PM2 가 모두 이 파일을 실행한다.
#   - 처음이면 기본 설정 파일을 만들고, uv 로 Python 환경을 맞춘 뒤 서버를 띄운다.
#   - 웹에서 "관리 서버 재시작"을 누르면 서버가 종료 코드 75 로 끝나고, 여기서 다시 띄운다.
#   - 종료 코드 78 은 설정 문제로 재시도해도 소용없다는 뜻이다 (PM2/systemd 가 반복하지 않음).
set -uo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
export PYTHONUNBUFFERED=1 BUILDKIT_PROGRESS=plain
export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null; then
    echo "[실패] uv 가 설치되어 있지 않습니다: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 78
fi
python3 "$ROOT/tools/setup.py" --ensure || exit 78
while true; do
    echo "[시작] uv 로 관리 서버 Python 환경을 준비합니다."
    if ! uv sync --quiet --project "$ROOT/server" --python 3.12; then
        echo "[실패] Python 환경 준비에 실패했습니다." >&2
        exit 78
    fi
    "$ROOT/server/.venv/bin/python" -u "$ROOT/server/run.py"
    code=$?
    [[ $code -eq 75 ]] || exit "$code"
    echo "[재시작] 요청에 따라 관리 서버를 다시 시작합니다."
done

# uv run --project server python run.py
# (어느 디렉터리에서 실행해도 되도록 이 파일 위치로 이동한 뒤 app.main:app 을 띄운다)

import os
import sys
import subprocess

import uvicorn
from dotenv import load_dotenv

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)
    sys.path.insert(0, here)
    # 포트·호스트는 .env 에서 정한다. 셸이나 pm2 에서 넘긴 환경변수가 있으면 그쪽이 우선한다.
    load_dotenv(os.path.join(here, ".env"))
    print("[시작] vLLM 실행 환경 자동 준비를 시작합니다.", flush=True)
    result = subprocess.run(
        [os.path.join(here, "..", "vllm"), "setup"],
        env={**os.environ, "VLLM_NO_SUDO": "1", "BUILDKIT_PROGRESS": "plain"},
    )
    if result.returncode:
        print(
            "[실패] 실행 환경 준비에 실패했습니다. 위 로그의 오류를 해결한 후 다시 시작해야 합니다.",
            flush=True,
        )
        sys.exit(78)
    print("[시작] 관리 웹 서버를 시작합니다.", flush=True)
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        workers=1,  # 작업(job) 목록과 WebSocket 구독이 프로세스 메모리에 있으므로 반드시 1
        log_level="warning",
        timeout_keep_alive=86400,
    )

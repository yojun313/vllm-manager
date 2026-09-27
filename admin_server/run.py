# admin_server/.venv/bin/python admin_server/run.py
# (어느 디렉터리에서 실행해도 되도록 이 파일 위치로 이동한 뒤 app.main:app 을 띄운다)

import os
import sys

import uvicorn
from dotenv import load_dotenv

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)
    sys.path.insert(0, here)
    # 포트·호스트는 .env 에서 정한다. 셸이나 pm2 에서 넘긴 환경변수가 있으면 그쪽이 우선한다.
    load_dotenv(os.path.join(here, ".env"))
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        workers=1,  # 작업(job) 목록과 WebSocket 구독이 프로세스 메모리에 있으므로 반드시 1
        log_level="warning",
        timeout_keep_alive=86400,
    )

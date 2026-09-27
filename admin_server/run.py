# admin_server/.venv/bin/python admin_server/run.py
# (어느 디렉터리에서 실행해도 되도록 이 파일 위치로 이동한 뒤 app.main:app 을 띄운다)

import os
import sys

import uvicorn

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)
    sys.path.insert(0, here)
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8021)),
        workers=1,  # 작업(job) 목록과 WebSocket 구독이 프로세스 메모리에 있으므로 반드시 1
        log_level="warning",
        timeout_keep_alive=86400,
    )

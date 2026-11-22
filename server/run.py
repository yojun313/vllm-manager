# 관리 서버 진입점. 보통 server/start.sh (./vllm server up) 가 실행한다.
# 어느 디렉터리에서 실행해도 되도록 이 파일 위치로 이동한 뒤 app.main:app 을 띄운다.

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
    from app import config  # noqa: E402 - .env 를 읽은 뒤에 가져온다

    print("[시작] 관리 웹 서버를 시작합니다.", flush=True)
    if config.SETUP_MODE:
        bar = "=" * 72
        print(
            f"\n{bar}\n 초기 설정이 필요합니다 / Initial setup required\n"
            " 브라우저에서 아래 주소를 열어 관리자 계정을 만드십시오.\n"
            " Open this address in a browser to create the admin account:\n\n"
            f"   http://<이 서버 주소 / this host>:{config.PORT}/setup?token={config.SETUP_TOKEN}\n{bar}\n",
            flush=True,
        )
    # 실행 이미지 준비(다운로드·빌드)는 서버를 띄운 뒤 백그라운드에서 진행하고 출력은 이 로그에 그대로 남긴다
    uvicorn.run(
        "app.main:app",
        host=config.HOST,
        port=config.PORT,
        workers=1,  # 작업(job) 목록과 WebSocket 구독이 프로세스 메모리에 있으므로 반드시 1
        log_level="warning",
        timeout_keep_alive=86400,
    )

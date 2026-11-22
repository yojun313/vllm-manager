"""실행 환경 준비(`./vllm setup`: GPU·Docker 확인, 이미지 다운로드·빌드)를 서버 시작 뒤 백그라운드에서 돌린다.

첫 실행에서는 이미지 준비에 몇 분~수십 분이 걸리므로 그동안에도 웹 화면을 쓸 수 있게 한다.
출력은 서버 로그(터미널, `./vllm server logs`)에 그대로 남기고, 화면에는 진행 상태만 알린다.
"""

import os
import subprocess
import threading

from app import config

status = {"state": "idle", "last": "", "error": ""}  # idle | running | done | failed
_lock = threading.Lock()


def _run():
    try:
        proc = subprocess.Popen(
            [str(config.VLLM_BIN), "setup"],
            cwd=config.VLLM_ROOT,
            env={
                **os.environ,
                "VLLM_NO_SUDO": "1",
                "BUILDKIT_PROGRESS": "plain",
                "TERM": "dumb",
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                print(line, flush=True)
                status["last"] = line[-300:]
        code = proc.wait()
    except OSError as e:
        code, status["last"] = 1, str(e)
    if code == 0:
        status.update(state="done", error="")
        print("[완료] 실행 환경 준비가 끝났습니다.", flush=True)
    else:
        status.update(state="failed", error=status["last"])
        print(
            "[실패] 실행 환경 준비에 실패했습니다. 위 로그의 오류를 해결한 뒤 관리 서버를 재시작하십시오.",
            flush=True,
        )


def start() -> bool:
    with _lock:
        if config.DEMO or status["state"] == "running":
            return False
        status.update(state="running", last="", error="")
        print("[시작] vLLM 실행 환경 자동 준비를 시작합니다.", flush=True)
        threading.Thread(target=_run, name="prepare", daemon=True).start()
        return True

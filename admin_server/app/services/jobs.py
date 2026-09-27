"""작업(job): ../vllm 명령(up/down/pull/rm)을 서버와 분리된 프로세스로 돌리고, 출력·상태를 파일에 남긴다.

- 출력은 data/jobs/<id>.log, 정보는 <id>.json 에 저장 → 서버(pm2)가 재시작돼도, 어느 기기·브라우저로 접속해도
  같은 작업 목록과 로그를 본다.
- 프로세스는 이중 fork 로 서버 프로세스 트리에서 떼어낸다 → pm2 가 서버를 재시작하며 자식 프로세스를 정리해도
  다운로드·기동이 끊기지 않는다.
- 종료 코드는 로그 마지막에 `__JOB_EXIT__ <코드>` 줄로 남긴다 (서버가 기다려줄 수 없으므로).
"""

import itertools
import json
import os
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path

from fastapi import HTTPException

from app.config import SERVICE_DIR, VLLM_BIN, VLLM_ROOT
from app.services import docker

DATA_DIR = SERVICE_DIR / "data" / "jobs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
KEEP = 40
MAX_LINES = 5000
EXIT_MARK = "__JOB_EXIT__"
_EXIT_RE = re.compile(rf"^{EXIT_MARK} (\d+)$")


class Job:
    def __init__(self, meta: dict):
        self.meta = meta
        self.id: int = meta["id"]
        self.log = DATA_DIR / f"{self.id}.log"
        # 로그 파일을 줄 단위로 읽는 상태 (진행률 \r 는 같은 줄 덮어쓰기)
        self._offset = 0
        self._buf = b""
        self._overwrite = False
        self.lines: list[str] = []
        self.dropped = 0
        self.version = 0
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 상태
    kind = property(lambda self: self.meta["kind"])
    title = property(lambda self: self.meta["title"])
    target = property(lambda self: self.meta.get("target", ""))
    started = property(lambda self: self.meta["started"])

    @property
    def status(self) -> str:
        if self.meta.get("status") in ("done", "failed"):
            return self.meta["status"]
        self.refresh()
        return self.meta.get("status", "running")

    def _alive(self) -> bool:
        pid = self.meta.get("pid")
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        # 좀비/재사용된 pid 방지: 시작 시각이 같은 프로세스인지 확인
        try:
            return int(Path(f"/proc/{pid}/stat").read_text().split()[21]) == self.meta.get("pid_start")
        except (OSError, IndexError, ValueError):
            return False

    def refresh(self):
        """로그 새 부분을 읽어 줄 목록을 갱신하고, 끝났는지 판단한다."""
        with self._lock:
            try:
                size = self.log.stat().st_size
            except FileNotFoundError:
                size = 0
            if size > self._offset:
                with open(self.log, "rb") as f:
                    f.seek(self._offset)
                    chunk = f.read(size - self._offset)
                self._offset = size
                self._feed(chunk)
            if self.meta.get("status") not in ("done", "failed") and not self._alive():
                # 프로세스가 끝났으면 버퍼에 남은 줄까지 반영하고 종료 코드를 확정
                if self._buf:
                    self._feed(b"\n")
                rc = self.meta.get("rc")
                self.meta["status"] = "done" if rc == 0 else "failed"
                self.meta.setdefault("ended", time.time())
                self.version += 1
                self._save()
                docker.invalidate()

    def _feed(self, chunk: bytes):
        self._buf += chunk
        while True:
            cuts = [i for i in (self._buf.find(b"\n"), self._buf.find(b"\r")) if i >= 0]
            if not cuts:
                break
            i = min(cuts)
            sep, line, self._buf = self._buf[i:i + 1], self._buf[:i], self._buf[i + 1:]
            text = line.decode("utf-8", "replace")
            m = _EXIT_RE.match(text.strip())
            if m:
                self.meta["rc"] = int(m.group(1))
                self.meta["ended"] = time.time()
                continue
            if text.strip() or not self._overwrite:
                if self._overwrite and self.lines:
                    self.lines[-1] = text
                else:
                    self.lines.append(text)
                    if len(self.lines) > MAX_LINES:
                        cut = len(self.lines) - MAX_LINES
                        del self.lines[:cut]
                        self.dropped += cut
            self._overwrite = sep == b"\r"
            self.version += 1

    def read(self, since: int) -> tuple[int, list[str]]:
        self.refresh()
        start = max(since, self.dropped)
        return start, self.lines[start - self.dropped:]

    @property
    def total(self) -> int:
        return self.dropped + len(self.lines)

    def launched(self) -> bool:
        """up: 용량 검사를 지나 docker run 까지 끝났는지 (./vllm 이 로그 스트리밍을 시작하면 그 뒤)"""
        self.refresh()
        return self.status != "running" or any("로그 표시 중" in l for l in self.lines[-400:])

    def _save(self):
        tmp = DATA_DIR / f"{self.id}.json.tmp"
        tmp.write_text(json.dumps(self.meta, ensure_ascii=False))
        tmp.replace(DATA_DIR / f"{self.id}.json")

    def summary(self) -> dict:
        status = self.status
        last = next((l for l in reversed(self.lines) if l.strip()), "")
        return {"id": self.id, "kind": self.kind, "title": self.title, "target": self.target,
                "status": status, "started": self.started, "ended": self.meta.get("ended"),
                "last": last[-240:], "progress": self.meta.get("progress")}


# ---------------------------------------------------------------- 목록 (파일에서 복원)
_jobs: dict[int, Job] = {}
_ids = itertools.count(1)


def _load():
    global _ids
    metas = []
    for p in DATA_DIR.glob("*.json"):
        try:
            metas.append(json.loads(p.read_text()))
        except (OSError, ValueError):
            continue
    for meta in sorted(metas, key=lambda m: m["id"]):
        _jobs[meta["id"]] = Job(meta)
    _ids = itertools.count(max(_jobs, default=0) + 1)


_load()


def all_jobs() -> list[Job]:
    return sorted(_jobs.values(), key=lambda j: j.id, reverse=True)


def get(job_id: int) -> Job | None:
    return _jobs.get(job_id)


def _prune():
    for job in all_jobs()[KEEP:]:
        if job.status == "running":
            continue
        for suffix in (".json", ".log"):
            (DATA_DIR / f"{job.id}{suffix}").unlink(missing_ok=True)
        _jobs.pop(job.id, None)


def _spawn(job_id: int, args: list[str]) -> tuple[int, int]:
    """이중 fork 로 서버와 분리해 실행하고 (pid, 시작시각) 을 돌려준다."""
    log = DATA_DIR / f"{job_id}.log"
    pidfile = DATA_DIR / f"{job_id}.pid"
    cmd = " ".join(shlex.quote(a) for a in [str(VLLM_BIN), *args])
    script = (f"( {cmd} </dev/null; echo \"{EXIT_MARK} $?\" ) >> {shlex.quote(str(log))} 2>&1 & "
              f"echo $! > {shlex.quote(str(pidfile))}")
    env = {**os.environ, "TERM": "dumb", "PYTHONUNBUFFERED": "1",
           # docker 권한이 없을 때 ./vllm 이 sudo 로 넘어가 비밀번호를 기다리며 멈추지 않도록
           "VLLM_NO_SUDO": "1",
           "PATH": f"{Path.home() / '.local/bin'}:{os.environ.get('PATH', '')}"}
    subprocess.run(["bash", "-c", script], cwd=VLLM_ROOT, env=env, start_new_session=True,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    pid = int(pidfile.read_text().strip())
    pidfile.unlink(missing_ok=True)
    try:
        pid_start = int(Path(f"/proc/{pid}/stat").read_text().split()[21])
    except (OSError, IndexError, ValueError):
        pid_start = None
    return pid, pid_start


# ./vllm up 의 "용량 검사 → docker run" 사이에 다른 up 이 끼어들면 둘 다 통과할 수 있어서,
# docker run 까지는 한 번에 하나씩만 진행한다 (그 뒤 긴 기동 대기는 동시에 해도 됨).
_start_lock = threading.Lock()


def start(kind: str, title: str, args: list[str], target: str = "", extra: dict | None = None) -> Job:
    with _start_lock:
        if kind == "up":
            pending = [j for j in all_jobs() if j.kind == "up" and j.status == "running" and not j.launched()]
            if pending:
                raise HTTPException(409, f"'{pending[0].title}' 가 용량 확인 중입니다. 몇 초 뒤 다시 시도하세요.")
        if kind in ("pull", "rm"):
            dup = [j for j in all_jobs() if j.kind == kind and j.target == target and j.status == "running"]
            if dup:
                raise HTTPException(409, f"이미 진행 중입니다: {dup[0].title}")
        # 디스크 기준으로 번호를 매긴다 (다른 서버 인스턴스가 만든 작업과도 겹치지 않도록)
        on_disk = [int(p.stem) for p in DATA_DIR.glob("*.json") if p.stem.isdigit()]
        job_id = max([next(_ids), *[i + 1 for i in on_disk]])
        meta = {"id": job_id, "kind": kind, "title": title, "target": target, "args": args,
                "started": time.time(), "status": "running", **(extra or {})}
        (DATA_DIR / f"{job_id}.log").touch()
        meta["pid"], meta["pid_start"] = _spawn(job_id, args)
        job = Job(meta)
        job._save()
        _jobs[job_id] = job
        _prune()
    docker.invalidate()
    return job


def update_meta(job: Job, **fields):
    job.meta.update(fields)
    job._save()

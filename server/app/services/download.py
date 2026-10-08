"""다운로드(./vllm pull) 진행률을 바이트 기준으로 계산한다.

hf 가 찍는 `Fetching N files: x%` 는 파일 개수 기준이라, 몇 개 안 되는 수십 GB 샤드를 받을 때는
한참 0% 에 머문다. 그래서
  전체 = HF API 의 파일 크기 합 (./vllm pull 이 제외하는 폴더는 뺌)
  받은 양 = 디스크의 완성된 파일 + 받는 중인 .incomplete 파일 크기
로 계산하고, 최근 샘플로 속도·남은 시간을 낸다. 서버가 계산해 모든 접속자에게 똑같이 보낸다.
"""

import json
import os
import time
import urllib.request
from collections import deque
from pathlib import Path

from app.config import VLLM_ENV

# ./vllm pull 의 --exclude 와 같게 유지할 것
EXCLUDE_DIRS = ("original/", "metal/", "onnx/", "openvino/")

_totals: dict[str, tuple[float, int]] = {}
_samples: dict[int, deque] = {}


def target_dir(repo: str) -> Path:
    return Path(VLLM_ENV["MODELS_DIR"]) / repo.replace("/", "__")


def total_bytes(repo: str) -> int:
    hit = _totals.get(repo)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    req = urllib.request.Request(f"https://huggingface.co/api/models/{repo}?blobs=true")
    tok = Path.home() / ".cache/huggingface/token"
    if tok.exists():
        req.add_header("Authorization", "Bearer " + tok.read_text().strip())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            info = json.loads(r.read())
        total = sum((s.get("size") or 0) for s in info.get("siblings", [])
                    if not s["rfilename"].startswith(EXCLUDE_DIRS))
    except Exception:
        total = 0
    _totals[repo] = (time.time(), total)
    return total


def local_bytes(d: Path) -> int:
    if not d.exists():
        return 0
    total = 0
    for root, dirs, files in os.walk(d):
        rel = os.path.relpath(root, d)
        if rel.startswith(".cache"):
            # 받는 중인 파일은 .cache/huggingface/download/*.incomplete 에 있다
            total += sum(_size(Path(root) / f) for f in files if f.endswith(".incomplete"))
            continue
        if (rel + "/").startswith(EXCLUDE_DIRS):
            dirs[:] = []
            continue
        total += sum(_size(Path(root) / f) for f in files)
    return total


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def progress(job_id: int, repo: str, finished: bool) -> dict:
    total = total_bytes(repo)
    done = local_bytes(target_dir(repo))
    now = time.time()
    s = _samples.setdefault(job_id, deque(maxlen=12))
    s.append((now, done))
    speed = 0.0
    if len(s) >= 2 and s[-1][0] - s[0][0] > 0:
        speed = max(0.0, (s[-1][1] - s[0][1]) / (s[-1][0] - s[0][0]))
    if finished:
        _samples.pop(job_id, None)
    pct = 100.0 if finished and total == 0 else (min(done / total * 100, 100.0) if total else None)
    eta = (total - done) / speed if speed > 0 and total > done else None
    return {"done": done, "total": total, "pct": round(pct, 1) if pct is not None else None,
            "speed": round(speed), "eta": round(eta) if eta is not None else None}

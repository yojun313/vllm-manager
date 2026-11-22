"""GPU 와 모델 서버 지표의 최근 이력. 메모리에만 보관한다(서버를 재시작하면 비워짐).

- 5초 간격으로 1시간(720개), 1분 평균으로 24시간(1440개)을 유지한다.
- 수집기는 접속자가 없어도 돌아가므로, 화면을 열면 지난 구간이 바로 보인다.
"""

import threading
import time
from collections import deque

from app.services import docker, gpu, metrics

FINE_SEC, FINE_KEEP = 5, 720
COARSE_SEC, COARSE_KEEP = 60, 1440
RANGES = {"15m": 900, "1h": 3600, "6h": 21600, "24h": 86400}

_fine: deque = deque(maxlen=FINE_KEEP)
_coarse: deque = deque(maxlen=COARSE_KEEP)
_bucket: list[dict] = []
_lock = threading.Lock()
_started = False


def collect() -> dict:
    """현재 값을 한 점으로 만든다 (데모 모드에서 바꿔 끼운다)."""
    gpus = {
        g["idx"]: {
            "util": g["util"],
            "mem": g["used"],
            "total": g["total"],
            "temp": g["temp"],
            "power": g["power"],
        }
        for g in gpu.snapshot()
    }
    models = {
        name: {"tps": m["gen_tps"], "running": m["running"], "waiting": m["waiting"]}
        for name, m in metrics.poll(docker.list_containers()).items()
    }
    return {"t": time.time(), "gpus": gpus, "models": models}


def _average(points: list[dict]) -> dict:
    out = {"t": points[-1]["t"], "gpus": {}, "models": {}}
    for kind in ("gpus", "models"):
        keys = {k for p in points for k in p[kind]}
        for k in keys:
            rows = [p[kind][k] for p in points if k in p[kind]]
            out[kind][k] = {
                f: round(sum(r[f] for r in rows) / len(rows), 2) for f in rows[0]
            }
    return out


def add(point: dict) -> None:
    with _lock:
        _fine.append(point)
        _bucket.append(point)
        if point["t"] - _bucket[0]["t"] >= COARSE_SEC:
            _coarse.append(_average(_bucket))
            _bucket.clear()


def _loop():
    while True:
        started = time.time()
        try:
            add(collect())
        except Exception:  # noqa: BLE001 - 수집 실패가 서버를 멈추지 않도록
            pass
        time.sleep(max(1.0, FINE_SEC - (time.time() - started)))


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="history", daemon=True).start()


def query(span: str, max_points: int = 180) -> dict:
    seconds = RANGES.get(span, 3600)
    with _lock:
        source = (
            list(_fine)
            if seconds <= FINE_SEC * FINE_KEEP
            else list(_coarse) + list(_bucket[-1:])
        )
    cutoff = time.time() - seconds
    points = [p for p in source if p["t"] >= cutoff]
    if len(points) > max_points:
        size = -(-len(points) // max_points)
        points = [_average(points[i : i + size]) for i in range(0, len(points), size)]
    gpus: dict[str, dict] = {}
    models: dict[str, dict] = {}
    times = [round(p["t"]) for p in points]
    for i, p in enumerate(points):
        for kind, target in (("gpus", gpus), ("models", models)):
            for key, row in p[kind].items():
                series = target.setdefault(key, {f: [None] * len(points) for f in row})
                for f, v in row.items():
                    series.setdefault(f, [None] * len(points))[i] = v
    return {
        "range": span if span in RANGES else "1h",
        "seconds": seconds,
        "t": times,
        "gpus": gpus,
        "models": models,
    }

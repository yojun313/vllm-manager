"""models/*.yaml 목록과 모델별 필요 메모리(../lib/plan.py, ./vllm up 과 같은 계산)."""

import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

from app.config import CONFIG_DIR, LIB_DIR, VLLM_ENV

_plan_cache: dict = {}
_du_cache: dict[str, tuple[float, int]] = {}


def files_dir(model: str) -> Path | None:
    """./vllm rm 의 model_files_dir 과 같은 규칙: /models/X → MODELS_DIR/X, repo id → hf-cache"""
    model = model.strip("'\"")
    if model.startswith("/models/"):
        return Path(VLLM_ENV["MODELS_DIR"]) / model[len("/models/"):]
    if "/" in model:
        return Path(VLLM_ENV["HF_CACHE_DIR"]) / "hub" / ("models--" + model.replace("/", "--"))
    return None


def du_bytes(d: Path) -> int:
    # 수십 GB 폴더라도 파일 수가 적어 빠르지만, 목록을 3초마다 만드므로 2분 캐시
    key = str(d)
    hit = _du_cache.get(key)
    if hit and time.time() - hit[0] < 120:
        return hit[1]
    total = 0
    if d.exists():
        for root, _, files in os.walk(d):
            for f in files:
                try:
                    total += os.lstat(os.path.join(root, f)).st_size
                except OSError:
                    pass
    _du_cache[key] = (time.time(), total)
    return total


def parse_yaml(path: Path) -> tuple[dict, dict, str]:
    """models/*.yaml 은 평평한 key: value 라 간단히 읽는다. (# gpus: N 같은 주석은 meta 로)"""
    y, meta = {}, {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#\s*([a-z-]+):\s*(\S+)", line)
        if m:
            meta[m.group(1)] = m.group(2)
            continue
        m = re.match(r"^([a-z0-9-]+):\s*(.*?)\s*(#.*)?$", line)
        if m:
            y[m.group(1)] = m.group(2)
    served = y.get("served-model-name", y.get("model", "")).strip("[]").split(",")[0].strip().strip("'\"")
    return y, meta, served


def served_names() -> dict[str, str]:
    return {p.stem: parse_yaml(p)[2] for p in CONFIG_DIR.glob("*.yaml")}


def exists(alias: str) -> bool:
    return "/" not in alias and (CONFIG_DIR / f"{alias}.yaml").is_file()


def plan(path: Path, tp: int, total_mib: int) -> dict:
    # HF API 를 부르는 모델도 있어 10분 캐시 (yaml 을 고치면 mtime 이 바뀌어 다시 계산)
    key = (str(path), path.stat().st_mtime, tp, total_mib)
    hit = _plan_cache.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    r = subprocess.run([sys.executable, str(LIB_DIR / "plan.py"), str(path), VLLM_ENV["MODELS_DIR"],
                        VLLM_ENV["HF_CACHE_DIR"], str(tp), str(total_mib)],
                       capture_output=True, text=True, env={**os.environ, **VLLM_ENV}, timeout=60)
    res = {}
    for line in r.stdout.splitlines():
        k, _, v = line.partition("=")
        res[k] = " ".join(shlex.split(v)) if v else ""
    p = {"need_mib": int(res.get("PLAN_NEED_MIB") or 0), "desc": res.get("PLAN_DESC", "")}
    m = re.search(r"--max-model-len (\d+)", res.get("PLAN_ARGS", ""))
    p["ctx"] = int(m.group(1)) if m else None
    _plan_cache[key] = (time.time(), p)
    return p


def list_models(total_mib: int) -> list[dict]:
    out = []
    paths = sorted(CONFIG_DIR.glob("*.yaml"))
    refs: dict[str, list[str]] = {}
    for path in paths:
        refs.setdefault(parse_yaml(path)[0].get("model", ""), []).append(path.stem)
    for path in paths:
        y, meta, served = parse_yaml(path)
        gpus = int(meta.get("gpus", "1"))
        try:
            p = plan(path, gpus, total_mib)
        except Exception as e:  # noqa: BLE001 - 한 모델 계산 실패가 목록 전체를 막지 않도록
            p = {"need_mib": 0, "desc": f"계산 실패: {e}", "ctx": None}
        d = files_dir(y.get("model", ""))
        out.append({"alias": path.stem, "model": y.get("model", ""), "served": served, "gpus": gpus,
                    "embed": y.get("runner") == "pooling", **p,
                    "files_dir": str(d) if d else "", "files_bytes": du_bytes(d) if d else 0,
                    "files_shared": [a for a in refs.get(y.get("model", ""), []) if a != path.stem]})
    return out

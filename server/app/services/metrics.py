"""실행 중인 모델 서버의 Prometheus 지표(/metrics)를 읽어 처리량과 대기열을 계산한다.

vLLM 과 vLLM-Omni 모두 같은 포트에서 /metrics 를 제공한다. 누적값(토큰 수, 요청 수)은 직전 샘플과의
차이로 초당 값을 낸다. 지표 이름은 버전에 따라 조금씩 달라 여러 이름을 함께 본다.
"""

import re
import time
import urllib.request

_LINE = re.compile(
    r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([0-9eE+.\-]+|NaN|Inf|\+Inf)$"
)
_prev: dict[str, tuple[float, dict]] = {}
_latest: dict[str, dict] = {}


def parse(text: str) -> dict[str, float]:
    """라벨을 무시하고 지표 이름별 합계를 낸다 (히스토그램의 _bucket 은 제외)."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line[0] == "#":
            continue
        m = _LINE.match(line.strip())
        if not m or m.group(1).endswith("_bucket"):
            continue
        try:
            value = float(m.group(3))
        except ValueError:
            continue
        if value != value:  # NaN
            continue
        out[m.group(1)] = out.get(m.group(1), 0.0) + value
    return out


def _pick(values: dict, *names: str) -> float | None:
    for n in names:
        if n in values:
            return values[n]
    return None


def fetch(port: str) -> dict[str, float] | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2) as r:
            return parse(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - 기동 중이거나 지표가 없는 서버
        return None


def summarize(name: str, values: dict[str, float], now: float | None = None) -> dict:
    now = now or time.time()
    cur = {
        "gen": _pick(values, "vllm:generation_tokens_total", "vllm:generation_tokens")
        or 0.0,
        "prompt": _pick(values, "vllm:prompt_tokens_total", "vllm:prompt_tokens")
        or 0.0,
        "req": _pick(values, "vllm:request_success_total", "vllm:request_success")
        or 0.0,
        "ttft_sum": _pick(values, "vllm:time_to_first_token_seconds_sum") or 0.0,
        "ttft_n": _pick(values, "vllm:time_to_first_token_seconds_count") or 0.0,
        "e2e_sum": _pick(values, "vllm:e2e_request_latency_seconds_sum") or 0.0,
        "e2e_n": _pick(values, "vllm:e2e_request_latency_seconds_count") or 0.0,
    }
    out = {
        "running": int(_pick(values, "vllm:num_requests_running") or 0),
        "waiting": int(_pick(values, "vllm:num_requests_waiting") or 0),
        "kv_usage": _pick(
            values, "vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc"
        ),
        "gen_total": int(cur["gen"]),
        "prompt_total": int(cur["prompt"]),
        "req_total": int(cur["req"]),
        "gen_tps": 0.0,
        "prompt_tps": 0.0,
        "rps": 0.0,
        "ttft": None,
        "latency": None,
    }
    prev = _prev.get(name)
    if prev and now > prev[0] and cur["gen"] >= prev[1]["gen"]:
        dt = now - prev[0]
        p = prev[1]
        out["gen_tps"] = round((cur["gen"] - p["gen"]) / dt, 1)
        out["prompt_tps"] = round((cur["prompt"] - p["prompt"]) / dt, 1)
        out["rps"] = round((cur["req"] - p["req"]) / dt, 2)
        if cur["ttft_n"] > p["ttft_n"]:
            out["ttft"] = round(
                (cur["ttft_sum"] - p["ttft_sum"]) / (cur["ttft_n"] - p["ttft_n"]), 3
            )
        if cur["e2e_n"] > p["e2e_n"]:
            out["latency"] = round(
                (cur["e2e_sum"] - p["e2e_sum"]) / (cur["e2e_n"] - p["e2e_n"]), 3
            )
    # 구간에 완료된 요청이 없으면 전체 평균을 대신 보여준다
    if out["ttft"] is None and cur["ttft_n"]:
        out["ttft"] = round(cur["ttft_sum"] / cur["ttft_n"], 3)
    if out["latency"] is None and cur["e2e_n"]:
        out["latency"] = round(cur["e2e_sum"] / cur["e2e_n"], 3)
    _prev[name] = (now, cur)
    return out


def poll(containers: list[dict]) -> dict[str, dict]:
    """실행 중인 컨테이너 전체의 지표를 한 번 읽는다 (이력 수집기가 주기적으로 호출)."""
    seen = {}
    for c in containers:
        if c.get("state") != "running" or not str(c.get("port", "")).isdigit():
            continue
        values = fetch(c["port"])
        if values is not None:
            seen[c["name"]] = summarize(c["name"], values)
    for gone in set(_prev) - set(seen):
        _prev.pop(gone, None)
    _latest.clear()
    _latest.update(seen)
    return seen


def latest() -> dict[str, dict]:
    return dict(_latest)

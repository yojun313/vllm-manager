"""vLLM 기동 로그를 읽어 '지금 몇 단계, 몇 %' 로 바꾼다.

vLLM 은 기동 진행률을 따로 알려주지 않아서 로그 문구로 판단한다. 문구가 버전마다 조금씩 달라서
정규식은 느슨하게 잡았고, 모르는 로그만 있으면 직전 단계에 머문다(틀린 %를 보여주진 않음).
전체 막대에서 각 단계가 차지하는 구간(start, end)은 대략적인 체감 시간 비율이다.
"""

import re

# (키, 이름, 시작%, 끝%, 이 단계에 들어섰다고 보는 로그 패턴)
# 패턴은 vLLM v0.29 소스의 실제 로그 문구에서 가져왔다 (버전을 올리면 한 번 확인할 것)
STAGES = [
    ("boot", "컨테이너 시작", 0, 5, r"vLLM server version|non-default args"),
    ("engine", "엔진 초기화", 5, 12, r"Initializing a V1 LLM engine|world_size=|Using .* backend"),
    ("download", "가중치 다운로드", 12, 20, r"Downloading|Fetching \d+ files"),
    ("weights", "가중치 로딩", 20, 60, r"Loading (safetensors|pt|np_cache) checkpoint shards|Multi-thread loading|Starting to load model"),
    ("compile", "torch.compile 컴파일", 60, 75, r"Dynamo bytecode transform|torch\.compile|Compiling a graph|Directly load the compiled graph"),
    ("kvcache", "KV 캐시 할당", 75, 80, r"Available KV cache memory|GPU KV cache size|kv_cache_memory_bytes config"),
    ("graphs", "CUDA 그래프 캡처", 80, 95, r"Capturing CUDA graphs|Graph capturing finished"),
    ("server", "API 서버 시작", 95, 99, r"init engine \(profile|Starting vLLM server on|Available routes are|Waiting for application startup"),
]
_RE = [(k, name, s, e, re.compile(p, re.I)) for k, name, s, e, p in STAGES]
_PCT = re.compile(r"(\d{1,3})%\s*(?:Completed\s*)?\|")
_FRACTION = re.compile(r"\|\s*(\d+)/(\d+)")
_ERROR = re.compile(r"(Traceback|Error|CUDA out of memory|RuntimeError|ValueError|exited)", re.I)


def parse(text: str, healthy: bool = False) -> dict:
    if healthy:
        return {"key": "ready", "stage": "준비 완료", "pct": 100, "detail": "", "error": ""}
    stage = None
    sub_pct = None
    detail = ""
    error = ""
    for raw in text.splitlines():
        # tqdm 진행률은 한 줄 안에 \r 로 여러 번 덮어쓰므로 마지막 조각만 본다
        line = raw.split("\r")[-1].strip()
        if not line:
            continue
        for k, name, s, e, rx in _RE:
            if rx.search(line) and (stage is None or s >= stage[2]):
                if stage is None or k != stage[0]:
                    sub_pct = None
                stage = (k, name, s, e)
                break
        if stage and stage[0] in ("weights", "graphs", "download"):
            m = _PCT.search(line)
            if m:
                sub_pct = int(m.group(1))
            else:
                f = _FRACTION.search(line)
                if f and int(f.group(2)):
                    sub_pct = int(int(f.group(1)) * 100 / int(f.group(2)))
        m = re.search(r"Model loading took ([\d.]+) GiB", line)
        if m:
            detail = f"가중치 {m.group(1)} GiB 로딩 완료"
        m = re.search(r"GPU KV cache size: ([\d,]+) tokens", line)
        if m:
            detail = f"KV 캐시 {m.group(1)} 토큰"
        if _ERROR.search(line) and "WARNING" not in line:
            error = line[-300:]
    if stage is None:
        return {"key": "boot", "stage": "컨테이너 시작", "pct": 1, "detail": detail, "error": error}
    k, name, s, e = stage
    pct = s + (e - s) * (sub_pct or 0) / 100 if sub_pct is not None else s + (e - s) * 0.3
    if sub_pct is not None:
        name = f"{name} {sub_pct}%"
    return {"key": k, "stage": name, "pct": round(min(pct, 99), 1), "detail": detail, "error": error}

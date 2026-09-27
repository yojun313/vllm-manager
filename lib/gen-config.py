#!/usr/bin/env python3
"""다운로드한 모델 폴더를 보고 vllm 용 models/<alias>.yaml 을 만든다.

사용: gen-config.py <HF repo id> <모델 폴더 또는 ""> <컨테이너 안 model 경로> <GPU 메모리 GiB>
결과 YAML 을 stdout 으로 출력한다. (호스트 python3.8 호환, 표준 라이브러리만 사용)
"""
import json
import math
import os
import re
import shlex
import sys

repo, model_dir, model_ref, gpu_gib = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])

# README 의 `vllm serve` 옵션 중 ./vllm 이 직접 관리하거나 여기서 쓸 수 없는 것
SKIP = {
    "port", "host", "tensor-parallel-size", "tp", "pipeline-parallel-size", "data-parallel-size",
    "model", "served-model-name", "api-key", "max-model-len",
    "reasoning-parser-plugin", "tool-parser-plugin",  # 모델 폴더의 .py 를 가리키는 로컬 경로라 대신 내장 파서를 쓴다
}

# README 에 파서 지정이 없을 때 model_type 으로 채우는 기본값
FAMILY = {
    "gpt_oss": {"reasoning-parser": "openai_gptoss", "tool-call-parser": "openai"},
    "qwen3": {"reasoning-parser": "qwen3", "tool-call-parser": "hermes"},
    "qwen3_moe": {"reasoning-parser": "qwen3", "tool-call-parser": "hermes"},
    "qwen3_next": {"reasoning-parser": "qwen3", "tool-call-parser": "qwen3_coder"},
    "qwen3_5": {"reasoning-parser": "qwen3", "tool-call-parser": "qwen3_coder"},
    "qwen3_5_moe": {"reasoning-parser": "qwen3", "tool-call-parser": "qwen3_coder"},
    "qwen3_vl": {"tool-call-parser": "hermes"},
    "qwen3_vl_moe": {"tool-call-parser": "hermes"},
    "qwen2_5_vl": {"tool-call-parser": "hermes"},
    "qwen2": {"tool-call-parser": "hermes"},
    "nemotron_h": {"reasoning-parser": "nemotron_v3", "tool-call-parser": "qwen3_coder"},
    "llama": {"tool-call-parser": "llama3_json"},
}


def read(name):
    p = os.path.join(model_dir, name)
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def readme_flags():
    """README 의 첫 번째 `vllm serve ...` 명령에서 옵션을 뽑는다."""
    text = read("README.md").replace("\\\n", " ")
    for line in text.splitlines():
        line = line.strip().lstrip("$").strip()
        if not line.startswith("vllm serve"):
            continue
        try:
            toks = shlex.split(line, comments=True)[2:]
        except ValueError:
            continue
        flags, i = {}, 0
        while i < len(toks):
            t = toks[i]
            if t in ("&", "&&", "|", ";"):
                break
            if t.startswith("-"):
                key, _, val = t.lstrip("-").partition("=")
                if not val and i + 1 < len(toks) and not toks[i + 1].startswith("-"):
                    val, i = toks[i + 1], i + 1
                flags[key.replace("_", "-")] = val if val else True
            i += 1
        return flags
    return {}


def yaml_scalar(v):
    if v is True:
        return "true"
    s = str(v)
    if re.fullmatch(r"-?\d+(\.\d+)?|[A-Za-z0-9_./-]+", s) and s.lower() not in ("true", "false", "null", "yes", "no"):
        return s
    return "'" + s.replace("'", "''") + "'"


cfg = {}
try:
    cfg = json.loads(read("config.json") or "{}")
except ValueError:
    pass
model_type = cfg.get("model_type", "")
archs = cfg.get("architectures") or []

# 가중치 크기로 권장 GPU 수 추정 (GPU 메모리의 75% 이상이면 2장)
# vLLM 은 폴더 최상위의 가중치만 읽는다 (original/, metal/ 등 하위 폴더 제외)
weight_bytes = 0
if model_dir:
    top = [f for f in os.listdir(model_dir) if os.path.isfile(os.path.join(model_dir, f))]
    st = [f for f in top if f.endswith(".safetensors")] or [f for f in top if f.endswith(".bin")]
    weight_bytes = sum(os.path.getsize(os.path.join(model_dir, f)) for f in st)
gpus = max(1, math.ceil(weight_bytes / 2**30 / (gpu_gib * 0.75))) if weight_bytes else 1

opts = {}
flags = readme_flags()
readme_len = flags.get("max-model-len")

# 임베딩 모델: sentence-transformers 설정이 있거나, 아키텍처가 ...Model 로 끝나는 경우
is_embed = (os.path.exists(os.path.join(model_dir, "modules.json"))
            or any(a.endswith("Model") or "Embed" in a for a in archs))
if is_embed:
    opts["runner"] = "pooling"
if "auto_map" in cfg or flags.get("trust-remote-code"):
    opts["trust-remote-code"] = True
opts["max-model-len"] = "auto"

for k, v in flags.items():
    if k not in SKIP:
        opts[k] = v
# 플러그인 파일로 등록되는 파서 이름은 플러그인 없이는 없으므로 버리고 내장 파서 기본값을 쓴다
if "reasoning-parser-plugin" in flags:
    opts.pop("reasoning-parser", None)
if "tool-parser-plugin" in flags:
    opts.pop("tool-call-parser", None)
if not is_embed:
    for k, v in FAMILY.get(model_type, {}).items():
        opts.setdefault(k, v)
    if "tool-call-parser" in opts:
        opts.setdefault("enable-auto-tool-choice", True)


out = [
    f"# gpus: {gpus}",
    f"# 자동 생성: {repo} ({model_type or '?'}, 가중치 {weight_bytes / 2**30:.1f} GiB)",
    "# max-model-len: auto = KV 캐시가 AUTO_KV_GIB(vllm.env) 안에 들어가는 가장 긴 길이로 자동 결정. 숫자로 고정해도 됨",
    "# 필요한 GPU 메모리는 ./vllm 이 자동 계산 (./vllm ls 로 확인). 동시 요청 수를 바꾸려면: # concurrency: 8",
]
if readme_len:
    out.append(f"# 모델 카드 권장 max-model-len: {readme_len}")
if flags:
    out.append("# 모델 카드의 `vllm serve` 권장 옵션을 반영했습니다. 필요하면 수정하세요.")
out += [f"model: {model_ref}", f"served-model-name: {repo}"]
out += [f"{k}: {yaml_scalar(v)}" for k, v in opts.items()]
print("\n".join(out))

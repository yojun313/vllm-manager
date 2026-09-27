#!/usr/bin/env python3
"""모델 하나를 띄우는 데 GPU 당 필요한 메모리를 계산하고, vLLM 에 넘길 메모리 옵션을 정한다.

사용: plan.py <models/x.yaml> <MODELS_DIR> <HF_CACHE_DIR> <TP> <GPU 전체 MiB>
환경변수: KV_CONCURRENCY(기본 4), AUTO_KV_GIB(기본 16)
출력: 셸에서 eval 할 PLAN_NEED_MIB / PLAN_ARGS / PLAN_DESC

필요 메모리(GPU 당) = 가중치/TP + KV 캐시 + 작업 여유(activation, CUDA graph, CUDA context)
KV 캐시 = 토큰당 KV 바이트 × max-model-len × 동시 요청 수(KV_CONCURRENCY)

vLLM 에는 --kv-cache-memory-bytes 로 KV 크기를 정확히 주고, 시작 시 여유 메모리 검사를 통과하도록
--gpu-memory-utilization 을 필요량/전체 로 맞춘다. (호스트 python3.8 호환, 표준 라이브러리만 사용)
"""
import glob
import json
import math
import os
import re
import shlex
import sys
import urllib.request

GiB = 2**30
cfg_path, models_dir, hf_cache, tp, gpu_total_mib = sys.argv[1:6]
tp, gpu_total = int(tp), int(gpu_total_mib) * 2**20
concurrency = int(os.environ.get("KV_CONCURRENCY", "4"))
auto_kv = float(os.environ.get("AUTO_KV_GIB", "16")) * GiB


def emit(need_bytes, args, desc):
    print(f"PLAN_NEED_MIB={math.ceil(need_bytes / 2**20)}")
    print(f"PLAN_ARGS={shlex.quote(' '.join(args))}")
    print(f"PLAN_DESC={shlex.quote(desc)}")
    sys.exit(0)


# ---- models/x.yaml (평평한 key: value 만 쓰므로 간단히 파싱)
yml, comments = {}, {}
for line in open(cfg_path, encoding="utf-8"):
    m = re.match(r"^#\s*([a-z-]+):\s*(\S+)", line)
    if m:
        comments[m.group(1)] = m.group(2)
        continue
    m = re.match(r"^([a-z0-9-]+):\s*(.*?)\s*(#.*)?$", line)
    if m:
        yml[m.group(1)] = m.group(2).strip("'\"")
concurrency = int(comments.get("concurrency", concurrency))
model = yml.get("model", "")


# ---- 모델 폴더(config.json, 가중치 크기) 찾기: 로컬 → hf-cache → HF API
def hf_get(url):
    req = urllib.request.Request(url)
    tok = os.path.expanduser("~/.cache/huggingface/token")
    if os.path.exists(tok):
        req.add_header("Authorization", "Bearer " + open(tok).read().strip())
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def weights_in(files_sizes):
    st = [s for f, s in files_sizes if "/" not in f and f.endswith(".safetensors")]
    return sum(st) if st else sum(s for f, s in files_sizes if "/" not in f and f.endswith(".bin"))


config, weights, source = None, 0, ""
if model.startswith("/models/"):
    d = os.path.join(models_dir, model[len("/models/"):])
    snaps = [d]
else:
    snaps = sorted(glob.glob(os.path.join(hf_cache, "hub", "models--" + model.replace("/", "--"), "snapshots", "*")))
for d in snaps:
    if os.path.exists(os.path.join(d, "config.json")):
        config = json.load(open(os.path.join(d, "config.json")))
        weights = weights_in([(f, os.path.getsize(os.path.join(d, f))) for f in os.listdir(d)
                              if os.path.isfile(os.path.join(d, f))])
        source = "local"
if config is None and "/" in model and not model.startswith("/"):
    try:
        config = hf_get(f"https://huggingface.co/{model}/resolve/main/config.json")
        info = hf_get(f"https://huggingface.co/api/models/{model}?blobs=true")
        weights = weights_in([(s["rfilename"], s.get("size") or 0) for s in info.get("siblings", [])])
        source = "HF"
    except Exception:
        config = None

# 수동 설정이 있으면 그대로 존중
if "gpu-memory-utilization" in yml:
    util = float(yml["gpu-memory-utilization"])
    emit(util * gpu_total, [], f"수동 설정 gpu-memory-utilization={util} → {util * gpu_total / GiB:.1f}GiB/GPU")
if config is None or not weights:
    emit(0.9 * gpu_total, [], "⚠️ 모델 정보를 못 읽어 자동 계산 불가 → vLLM 기본값(GPU 90%) 사용")

# ---- 토큰당 KV 바이트 (GPU 당)
c = {**config, **(config.get("text_config") or {}), **(config.get("llm_config") or {})}
n_layers = c.get("num_hidden_layers") or c.get("n_layer") or 0
heads = c.get("num_attention_heads") or 1
kv_heads = c.get("num_key_value_heads") or heads
head_dim = c.get("head_dim") or (c.get("hidden_size", 0) // heads)
hybrid = False
if c.get("layer_types"):
    # sliding window 레이어는 창 크기(수백 토큰)만 저장하므로 무시, linear/mamba 레이어는 KV 없음
    attn_layers = sum(1 for t in c["layer_types"] if t in ("full_attention", "attention"))
    hybrid = any("linear" in t or "mamba" in t for t in c["layer_types"])
elif c.get("hybrid_override_pattern"):  # Nemotron-H: '*' = attention, 'M' = mamba
    attn_layers = c["hybrid_override_pattern"].count("*")
    hybrid = True
else:
    attn_layers = n_layers
kv_dtype = 1 if yml.get("kv-cache-dtype", "auto").startswith("fp8") else 2
per_token = 2 * attn_layers * math.ceil(kv_heads / tp) * head_dim * kv_dtype

# ---- 컨텍스트 길이: 숫자로 적혀 있으면 그대로, auto 면 KV 가 AUTO_KV_GIB 안에 들어가는 가장 긴 길이
model_max = c.get("max_position_embeddings") or 32768
ml = yml.get("max-model-len", "auto")
if ml.isdigit():
    max_len = int(ml)
else:
    cands = [l for l in (model_max, 131072, 65536, 32768) if l <= model_max]
    max_len = next((l for l in cands if per_token * l * concurrency <= auto_kv), min(model_max, 32768))

kv = per_token * max_len * concurrency
if hybrid:
    kv += 1 * GiB  # mamba/linear-attention 상태(요청당 수십 MB)
w = weights / tp
multimodal = "vision_config" in config or "vision_config" in c
overhead = 2.5 * GiB + 0.05 * w + (2 * GiB if multimodal else 0)
need = w + kv + overhead

util = min(0.97, math.ceil((need / gpu_total) * 100 + 1) / 100)  # 시작 시 여유 메모리 검사용
args = ["--kv-cache-memory-bytes", str(int(kv)), "--gpu-memory-utilization", f"{util:.2f}",
        "--max-model-len", str(max_len)]
desc = (f"가중치 {w / GiB:.1f} + KV {kv / GiB:.1f} ({max_len:,}토큰 × 동시 {concurrency}) "
        f"+ 여유 {overhead / GiB:.1f} = {need / GiB:.1f}GiB/GPU")
emit(need, args, desc)

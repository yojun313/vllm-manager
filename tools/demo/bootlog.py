"""데모 모드의 가상 기동 로그. 관리 서버(app/demo.py)와 가짜 실행기(fake_vllm.py)가 함께 쓴다. 표준 라이브러리만 사용."""

import random
import time

READY_AFTER = 48  # 가상 모델이 기동을 마치는 데 걸리는 시간(초)

BOOT_LOG = [
    (0, "INFO [api_utils.py:347] vLLM server version 0.29.0, serving model {served}"),
    (
        1,
        "INFO [api_utils.py:286] non-default args: {{'host': '0.0.0.0', 'model': '{path}', 'max_model_len': {ctx}}}",
    ),
    (
        3,
        "INFO [core.py:112] Initializing a V1 LLM engine (v0.29.0) with config: model='{path}', dtype=torch.bfloat16",
    ),
    (
        5,
        "INFO [parallel_state.py:1208] world_size={tp} rank=0 local_rank=0 distributed_init_method=tcp://127.0.0.1:41233 backend=nccl",
    ),
    (7, "INFO [gpu_model_runner.py:2338] Starting to load model {path}..."),
    (
        9,
        "Loading safetensors checkpoint shards:  12% Completed | 2/17 [00:02<00:14,  1.02it/s]",
    ),
    (
        14,
        "Loading safetensors checkpoint shards:  41% Completed | 7/17 [00:07<00:10,  1.05s/it]",
    ),
    (
        19,
        "Loading safetensors checkpoint shards:  71% Completed | 12/17 [00:12<00:05,  1.04s/it]",
    ),
    (
        24,
        "Loading safetensors checkpoint shards: 100% Completed | 17/17 [00:17<00:00,  1.03s/it]",
    ),
    (25, "INFO [default_loader.py:268] Loading weights took 17.42 seconds"),
    (
        26,
        "INFO [gpu_model_runner.py:2392] Model loading took {w} GiB and 18.913 seconds",
    ),
    (28, "INFO [backends.py:539] Dynamo bytecode transform time: 6.21 s"),
    (32, "INFO [backends.py:226] Compiling a graph for dynamic shape takes 11.02 s"),
    (34, "INFO [gpu_worker.py:298] Available KV cache memory: 9.40 GiB"),
    (35, "INFO [kv_cache_utils.py:864] GPU KV cache size: 524,288 tokens"),
    (
        37,
        "Capturing CUDA graphs (mixed prefill-decode, PIECEWISE):  35% | 23/67 [00:02<00:04,  9.41it/s]",
    ),
    (
        41,
        "Capturing CUDA graphs (mixed prefill-decode, PIECEWISE): 100% | 67/67 [00:06<00:00, 10.12it/s]",
    ),
    (
        43,
        "INFO [gpu_model_runner.py:3480] Graph capturing finished in 7 secs, took 0.84 GiB",
    ),
    (45, "INFO [api_server.py:1912] Starting vLLM server on http://0.0.0.0:8000"),
    (47, "INFO:     Application startup complete."),
]
SERVE_LOG = [
    'INFO:     10.0.4.{a}:{p} - "POST /v1/chat/completions HTTP/1.1" 200 OK',
    "INFO [loggers.py:127] Engine 000: Avg prompt throughput: {pt} tokens/s, Avg generation throughput: {gt} tokens/s, Running: {r} reqs, Waiting: 0 reqs, GPU KV cache usage: {kv}%",
]


def lines(c: dict, load: tuple = (200, 2)) -> list:
    """컨테이너가 만들어진 뒤 지난 시간만큼의 로그."""
    age = time.time() - c["created"]
    fields = {
        "served": c["served"],
        "path": c["path"],
        "ctx": 131072,
        "tp": len(c["gpus"].split(",")),
        "w": "30.4",
    }
    out = [text.format(**fields) for at, text in BOOT_LOG if at <= age]
    if age >= READY_AFTER:
        rnd = random.Random(c["id"])
        gt, r = load
        for _ in range(14):
            out.append(
                SERVE_LOG[0].format(a=rnd.randint(11, 60), p=rnd.randint(40000, 60000))
            )
        out.append(
            SERVE_LOG[1].format(
                pt=round(gt * 2.4, 1),
                gt=float(gt),
                r=r,
                kv=round(rnd.uniform(8, 31), 1),
            )
        )
    return out

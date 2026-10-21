# Keep the existing CUDA 12.9 runtime; do not layer CUDA 13 wheels over it.
ARG VLLM_BASE_IMAGE=vllm/vllm-openai:v0.29.0-cu129
FROM ${VLLM_BASE_IMAGE}
ARG OMNI_REVISION=aff7d64948f6c0e81e9b3272234623044e215967
ENV VLLM_OMNI_TARGET_DEVICE=cuda
RUN apt-get update && apt-get install -y --no-install-recommends git espeak-ng ffmpeg \
    && rm -rf /var/lib/apt/lists/*
# Fail dependency resolution instead of replacing the coherent torch/CUDA stack.
RUN python3 -c 'import importlib.metadata as m; from pathlib import Path; names=[d.metadata["Name"] for d in m.distributions()]; keep=[n for n in names if n.lower() in ("torch","torchvision","torchaudio","triton","vllm") or n.lower().startswith("nvidia-")]; Path("/tmp/omni-constraints.txt").write_text("\n".join(n+"=="+m.version(n) for n in keep))'
RUN uv pip install --system --constraint /tmp/omni-constraints.txt \
    "vllm-omni @ git+https://github.com/vllm-project/vllm-omni.git@${OMNI_REVISION}"
RUN python3 -c 'import torch, torchvision, vllm, vllm_omni; assert torch.version.cuda.startswith("12."), torch.version.cuda' \
    && python3 -m vllm_omni.entrypoints.cli.main serve Qwen/Qwen3-Omni-30B-A3B-Instruct --omni --help > /dev/null
ENTRYPOINT ["python3", "-m", "vllm_omni.entrypoints.cli.main"]

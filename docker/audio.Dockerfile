ARG VLLM_BASE_IMAGE=vllm/vllm-openai:v0.29.0-cu129
FROM ${VLLM_BASE_IMAGE}
# Preserve the installed CUDA/PyTorch stack while installing vLLM's audio extras.
RUN python3 -c 'import importlib.metadata as m; from pathlib import Path; names=[d.metadata["Name"] for d in m.distributions()]; keep=[n for n in names if n.lower() in ("torch","torchvision","torchaudio","triton","vllm") or n.lower().startswith("nvidia-")]; Path("/tmp/audio-constraints.txt").write_text("\n".join(n+"=="+m.version(n) for n in keep))'
RUN uv pip install --system --constraint /tmp/audio-constraints.txt \
    "vllm[audio]==$(python3 -c 'import importlib.metadata as m; print(m.version("vllm"))')"
RUN python3 -c 'import av, scipy.signal, soundfile, soxr; import numpy as np; from vllm.multimodal.audio import resample_audio_pyav; resample_audio_pyav(np.zeros(2400, dtype=np.float32), orig_sr=24000, target_sr=16000)'

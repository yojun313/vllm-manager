# vllm-manager

A self-hosted toolkit for **managing [vLLM](https://github.com/vllm-project/vllm) and [vLLM-Omni](https://github.com/vllm-project/vllm-omni) model servers on a GPU host**. One CLI (`./vllm`) and a web console (**vLLM Control**) handle model downloads, configuration, GPU selection, container lifecycle, and logs. Serve language and multimodal models through OpenAI-compatible APIs, with per-model engine selection and GPU memory checks before starting.

Built on Docker, vLLM, and vLLM-Omni for serving, with FastAPI and uv for the web console.

<table>
  <tr>
    <td align="center" width="50%"><img src="./static/imgs/1.png" alt="Dashboard" width="100%"><br><sub>Dashboard: live GPU memory per model, running servers, memory plan per model</sub></td>
    <td align="center" width="50%"><img src="./static/imgs/2.png" alt="Models and download" width="100%"><br><sub>Fit check per GPU before starting, model download, API key</sub></td>
  </tr>
</table>

---

## 1. Features

* **Two serving engines**: choose vLLM or vLLM-Omni per model. Each server uses its own container and port; both engines can run together when GPU memory permits.
* **Declarative model configs**: model YAML files select the engine and model. vLLM uses its official `--config` format; Omni uses a separate deployment YAML for pipeline stages and GPU placement.
* **Automatic environment setup**: console startup runs `uv sync`, checks GPU and Docker access, pulls the vLLM image if missing, and builds the Omni image if missing. Setup and build output stream to the terminal and PM2 logs.
* **GPU memory planning**: estimate vLLM weights, KV cache, and working memory from the model architecture. Omni uses a configurable reservation per GPU alongside stage-specific memory settings. Starts are refused when the reservation exceeds available memory; actual inference memory still depends on the workload.
* **Download & config generation**: pull a Hugging Face repository and get a config file with the options recommended in the model card. Regular vLLM models receive an estimated fit check before downloading; Qwen3-Omni uses its stage deployment requirements instead.
* **Multi-GPU execution**: choose GPUs per run (`-g 0,1`) or select them automatically. vLLM uses tensor parallelism across the selected GPUs; Omni uses the parallelism and device mapping in its deployment profile.
* **Web console (vLLM Control)**: start / restart / stop / delete models, download models with byte-level progress, watch GPU memory / utilization / temperature / power, and follow start-up progress (weight loading, compile, CUDA graph capture) and logs live, from any browser including mobile.
* **Jobs that survive restarts**: downloads and start-ups run in processes separate from the web server, so restarting the console does not interrupt them, and every device sees the same state.
* **OpenAI-compatible APIs and API key authentication** for both engines. Supported inputs, outputs, and endpoints depend on the model and engine.

---

## 2. System Requirements

* **NVIDIA GPU and driver**. Both serving images must use a CUDA runtime compatible with the driver (see [Engine Versions](#11-engine-versions)).
* **Docker** with the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/) (`docker run --gpus` must work).
* **`hf` CLI**: `pip install -U huggingface_hub`. Gated models need `hf auth login`.
* **Python 3.8+, `bc`, `ss` (iproute2), `flock` (util-linux)** for the CLI.
* **[uv](https://docs.astral.sh/uv/) and Python 3.12** for the web console only.
* **[PM2](https://pm2.keymetrics.io/)** to keep the web console running (optional).

---

## 3. Installation

### 1) Clone

```bash
git clone https://github.com/yojun313/vllm-manager.git
cd vllm-manager
```

### 2) Configuration

```bash
cp .env.example .env
```

The root `.env` holds the serving engine settings and is not tracked by Git (`server/.env` is only for the web console login). Check these keys for your server; the full list is in the [Configuration Reference](#10-configuration-reference).

* `VLLM_IMAGE`: the base vLLM image, built for a CUDA version your driver supports.
* `VLLM_OMNI_IMAGE`: the Omni image tag to build and reuse, such as `local/vllm-omni:0.29.0-cu129`. Leave empty to skip Omni preparation at console startup.
* `MODELS_DIR`, `HF_CACHE_DIR`, `VLLM_CACHE_DIR`: where model weights and caches are stored.
* `GPU_COUNT` or `GPU_IDS`: which GPUs vllm-manager may use. Leave both empty to use every detected GPU.

Model configs in `models/` are server-specific and not part of the repository. The folder is empty after installation; add models with `./vllm pull`.

### 3) Prepare the serving environment

```bash
./vllm setup
```

This checks the host tools and GPU configuration, creates model and cache directories, pulls the base vLLM image if needed, and builds the Omni image if configured and missing. Existing images are reused. Docker pull and build output is printed directly. The web console runs this step automatically at startup. Host drivers, Docker, NVIDIA Container Toolkit, and uv must already be installed.

### 4) Start a vLLM model

```bash
# 1. Download a model (creates models/qwen3-8b.yaml)
./vllm pull Qwen/Qwen3-8B

# 2. Start it
./vllm up qwen3-8b

# 3. Send a request (use the address printed by `up`)
curl http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "Qwen/Qwen3-8B", "messages": [{"role": "user", "content": "Hello"}]}'
```

### 5) Start a vLLM-Omni model

```bash
# Create the config only; this does not download model weights
./vllm new Qwen/Qwen3-Omni-30B-A3B-Instruct qwen3-omni-30b-a3b

# Use the two-GPU deployment profile; weights download on first start
./vllm up qwen3-omni-30b-a3b -g 0,1
```

Use `pull` instead of `new` to download the weights in advance. The included Qwen3-Omni profiles require two GPUs and start with an 8,192-token context and one concurrent request. The full profile places Thinker on container GPU 0 and Talker / Code2Wav on container GPU 1. These are deployment starting points, not a guarantee that every workload fits or every hardware combination is validated.

`./vllm up` follows the start-up log until the server accepts requests, then prints the address and an example request and exits. The server keeps running in the background. The port depends on the chosen GPU and on which ports are free. If [API authentication](#8-api-authentication) is on, an `Authorization` header is required.

---

## 4. CLI Reference

```
./vllm [-n] <command> [args]
```

| Command | Description |
|---|---|
| (none) | Interactive menu to pick a model and GPUs. |
| `up <model> [-g GPU] [-p PORT] [-- engine options...]` | Start a model. If the same model already runs on the same GPUs, it is replaced. |
| `down [model\|GPU\|container]` | Stop servers. Without an argument, every server is stopped. |
| `ps` | Running servers and free memory per GPU. |
| `logs [model\|GPU\|container]` | Follow a server's log. |
| `ls` | Models and the memory each one needs. |
| `pull [repo] [alias] [--force]` | Download a model and create its config file. |
| `fit <repo>` | Only check whether a model can run on this server, without downloading. |
| `new <repo> [alias]` | Only create the config file, without downloading. |
| `rm <model> [--files]` | Delete a model config. `--files` also deletes the weights. |
| `key [new\|off]` | Show, create or remove the API key. |
| `setup` | Prepare GPU access, directories, and both serving images. Build Omni if its image is missing. |
| `omni-build` | Build or rebuild the configured Omni image with plain-text build logs. |

**Global option**

* `-n`, `--dry-run`: print the docker commands instead of running them.

**`up` options**

| Option | Description |
|---|---|
| `-g`, `--gpu` | GPUs to use, as `0`, `1` or `0,1`. For vLLM, multiple GPUs use tensor parallelism (TP). For Omni, the GPU count must match the deployment profile and stage placement is defined there. Without it, the `# gpus: N` count from the config is used and the GPUs with the most free memory are chosen. GPUs outside `GPU_COUNT` / `GPU_IDS` cannot be selected. |
| `-p`, `--port` | Host port. Without it, the first free port from `PORT_BASE + first GPU index` is used. Replacing the same model keeps its port. |
| `-- ...` | Everything after `--` is passed to the selected engine; the engine must support the options. For vLLM, CLI options override the config file, e.g. `./vllm up qwen3-8b -- --max-num-seqs 16`. |

Containers are named `vllm-<model>-g<GPUs>` (e.g. `vllm-qwen3-8b-g0`), so different models, or the same model on different GPUs, can run side by side.

---

## 5. Model Management

### Adding a model

```bash
./vllm pull Qwen/Qwen3-8B                          # alias is the lower-cased repo name (qwen3-8b)
./vllm pull https://huggingface.co/Qwen/Qwen3-8B    # URLs work too
./vllm pull Qwen/Qwen3-8B my-qwen                  # custom alias
```

`pull` works in three steps:

1. **Fit check for vLLM**: the needed memory is calculated from the Hugging Face `config.json` and file sizes only. If the model cannot run on all usable GPUs (`GPU_COUNT`) even in the lightest setting (4,096-token context, 1 concurrent request), you are asked before downloading. Outside a terminal it stops unless `--force` is given.
2. **Download** into `MODELS_DIR/<org>__<name>`, skipping folders vLLM does not use (`original/`, `metal/`, `onnx/`, `openvino/`). An interrupted download resumes with the same command.
3. **Config file**: `models/<alias>.yaml` is created (an existing file is never overwritten). Qwen3-Omni-30B-A3B checkpoints select the Omni engine and a two-GPU deployment profile; their fit status is reported as unknown rather than using the regular TP estimator.

For regular vLLM models, the generated config includes the following. It is printed after creation, so you can adjust it.

* The recommended GPU count, based on the weight size.
* The `vllm serve` options recommended in the model card.
* `trust-remote-code` (when the repo ships custom code) and embedding models (`runner: pooling`).
* Reasoning and tool-call parsers per model family (Qwen, gpt-oss, Nemotron, Llama).

### Config file format

`models/*.yaml` selects a model and serving engine. The `# engine:` comment accepts `vllm` or `vllm-omni`; omitting it selects vLLM. For vLLM, keys follow the official config file format: CLI option names without the leading `--`.

```yaml
# engine: vllm                  # serving engine (optional for vLLM)
# gpus: 1                       # vllm-manager only: recommended GPU count
# concurrency: 4                # vllm-manager only: concurrent requests for KV cache sizing (optional)
model: /models/Qwen__Qwen3-8B   # downloaded models live in /models/<folder>; a HF repo id is downloaded at start
served-model-name: Qwen/Qwen3-8B
max-model-len: auto             # or a fixed number within the model/tokenizer limit
reasoning-parser: qwen3
enable-auto-tool-choice: true
tool-call-parser: hermes
```

For vLLM, `./vllm up` manages TP, host, port, and automatically calculated memory options. Setting `gpu-memory-utilization` manually opts out of automatic memory sizing.

Ready-to-copy model configs are provided in `deploy/`:

| Example | Engine | Purpose |
|---|---|---|
| [vllm-model.yaml.example](deploy/vllm-model.yaml.example) | vLLM | Qwen3-8B text chat with reasoning and tool calling |
| [music-flamingo-model.yaml.example](deploy/music-flamingo-model.yaml.example) | vLLM | Music Flamingo audio understanding with an 8192-token context and one request for memory planning |
| [qwen3-omni-model.yaml.example](deploy/qwen3-omni-model.yaml.example) | vLLM-Omni | Qwen3-Omni with stage-specific GPU placement |

Copy an example into `models/` with a `.yaml` extension before starting it:

```bash
cp deploy/vllm-model.yaml.example models/qwen3-8b.yaml
./vllm up qwen3-8b -g 0

cp deploy/music-flamingo-model.yaml.example models/music-flamingo-hf.yaml
./vllm up music-flamingo-hf -g 0
```

Copy only when the destination config does not exist, or preserve your local settings before replacing it. Repository IDs download weights on first start. For weights downloaded with `./vllm pull`, use the corresponding `/models/<org>__<name>` path shown in the example. Music Flamingo uses the regular vLLM engine; omit `tools` and `tool_choice` from its API requests.

For Omni, the model file contains engine metadata and a reference to a deployment profile:

```yaml
# engine: vllm-omni
# gpus: 2
# memory-fraction: 0.9
# deploy-config: qwen3-omni.yaml
model: Qwen/Qwen3-Omni-30B-A3B-Instruct
```

The `deploy-config` value is a filename under `deploy/`. Stage device indices are local to the container. Use `qwen3-omni.yaml` for text and speech output, or `qwen3-omni-thinking.yaml` for a Thinker-only pipeline with text output and multimodal inputs. The Thinker-only profile also accepts Instruct weights and uses TP=2. Both profiles set the context to 8192 and concurrency to 1. See `deploy/qwen3-omni-model.yaml.example` for a model config template.

Omni 0.29 rejects global `--served-model-name` for this pipeline, so the launcher uses the engine's default API model name: the `model` value. The console displays the same name, including the container path when using local weights. Regular vLLM configs can set `served-model-name`.

### Removing a model

```bash
./vllm rm qwen3-8b            # config file only
./vllm rm qwen3-8b --files    # config and weights
```

A running model cannot be removed. Weights are kept if another config uses the same weights, or if the weight folder is not directly under `MODELS_DIR` or `HF_CACHE_DIR`.

---

## 6. GPU Memory Planning

### How much a model needs

For regular vLLM models, `./vllm up` estimates a GPU reservation from the weights, KV cache, and working memory. `./vllm ls` shows the plan.

```
Memory per GPU = weights / TP + KV cache + working memory
KV cache       = KV bytes per token × max-model-len × concurrent requests
Working memory = 2.5 GiB + 5% of the weights (+ 2 GiB for vision models)
```

* KV bytes per token come from the layer count, KV head count and head dimension in `config.json`. Sliding-window layers and linear-attention / Mamba layers are excluded.
* vLLM receives the computed KV cache size (`--kv-cache-memory-bytes`) and a matching `--gpu-memory-utilization`.
* With `max-model-len: auto`, the longest context whose KV cache fits in `AUTO_KV_GIB` (default 16 GiB) is chosen without exceeding the limits in the model and tokenizer configs. An explicit length above those limits is rejected before launch.
* Concurrent requests default to `KV_CONCURRENCY` (4): that many full-length requests fit at once. Shorter requests can run in larger numbers.
* Setting `gpu-memory-utilization` in a config disables the automatic sizing for that model.

### Omni pipeline reservations

Omni uses stage-specific memory settings in `deploy/` instead of the regular weights / TP estimator. The model config's `# memory-fraction: 0.9` reserves 90% of each selected GPU for scheduling checks. On an 80 GiB GPU, this is approximately 72 GiB per GPU, plus the free safety margin. If stage memory utilization is increased, raise the reservation to cover the sum of all stage allocations on each GPU.

The full Qwen3-Omni profile assigns Thinker to one GPU and Talker / Code2Wav to the other; the Thinker-only profile distributes Thinker across both GPUs. These reservations are estimates for scheduling, not measured peak usage. Input length and concurrency affect actual memory consumption.

### Running several models together

vLLM and Omni servers run in separate containers and can run simultaneously when the GPU reservations fit. A two-GPU Omni deployment may require stopping other large models first. Starting one model does not automatically stop unrelated models.

Before starting, the free memory of the target GPUs is checked; if it is not enough, the start is refused without changing anything. Free memory is counted per GPU process:

* Models started by vllm-manager: the larger of actual use and reservation (models still starting count with their full reservation).
* Other processes: actual use.
* `SAFETY_MIB` (default 2 GiB) is kept free on every GPU as a margin.

---

## 7. Web Console (vLLM Control)

`server/` is a FastAPI web console. Every action calls `./vllm`, so the same rules apply as on the command line.

* Full-width layout with a collapsible sidebar and a mobile menu.
* Light / dark / system theme and a compact mode.
* Settings for the GPU push interval (1 · 2 · 5 · 10 · 30 s), the model / job refresh interval (2 · 5 · 10 · 30 s), pausing GPU updates, and showing temperature / power.
* Start, restart, stop and delete vLLM and Omni models; engine and deployment profile labels with per-GPU fit checks before starting.
* Model download with byte-level progress, speed, ETA, and a confirmation for models that will not fit.
* Live memory, utilization, temperature and power for the GPUs selected by `GPU_COUNT` / `GPU_IDS`.
* Start-up progress by stage (weight loading, compile, CUDA graph capture…) and live logs.
* Username / password login.

Jobs run in processes separate from the web server, and their records and logs are stored in `server/data/jobs/`. Restarting the web server does not interrupt running downloads or start-ups, and every device and browser sees the same state.

Display settings are stored in the browser's local storage and do not affect other devices. Refresh intervals apply to the current WebSocket connection and are restored on reconnect. Pausing GPU updates still shows the initial state once on connect, and the server keeps reading the GPUs internally for fit checks. Changing settings does not cancel an open job log subscription.

### 1) Docker permission

The console must be able to use docker without sudo. Add the user that runs it to the `docker` group:

```bash
sudo usermod -aG docker $USER
```

Group changes apply to new login sessions. To use it without logging in again, run the following commands with `sg docker -c "..."`.

### 2) Environment and account

```bash
cp server/.env.example server/.env
```

The startup script prepares the Python environment with `uv sync`. Set the login account and session key in `server/.env`. Behind an HTTPS proxy the session cookie is `Secure`; only expose the console to the outside through an HTTPS proxy.

| Key | Description | Default |
|---|---|---|
| `ADMIN_USERNAME` | Login user name | (required) |
| `ADMIN_PASSWORD` | A strong login password | (required) |
| `SESSION_SECRET` | Signing key that keeps sessions across restarts. Generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`. Empty means everyone is logged out on restart. | random |
| `SESSION_DAYS` | How long a login lasts (days) | `14` |
| `COOKIE_SECURE` | Send the session cookie over HTTPS only. Set `false` only for local HTTP development. | `true` |
| `PORT` | Web server port | `8000` |
| `HOST` | Bind address. `127.0.0.1` allows access from the server only. | `0.0.0.0` |
| `MODEL_PUBLIC_URL_<port>` | What "copy address" copies for that model port, e.g. `MODEL_PUBLIC_URL_8000=llm0.example.com/v1` | `http://<current host>:<port>/v1` |

The copy-address value is used exactly as written. Restart the console and reload the page after changing it.

> **Note** The console's default `PORT` 8000 is the same as the default model port (`PORT_BASE` in the root `.env`). If models run on the same server, pick another port such as `8021`. Swagger UI (`/docs`), ReDoc (`/redoc`) and the OpenAPI schema (`/openapi.json`) are disabled.

### 3) Run

```bash
# Foreground: prepare Python dependencies and serving images, then start the console
bash server/start.sh

# Keep it running with PM2
pm2 start ecosystem.config.js
pm2 save
pm2 logs vllm
```

Startup runs `uv sync` followed by `./vllm setup`, streaming environment checks, image downloads, and Omni builds to the terminal and PM2 logs. The web server starts after preparation succeeds. Existing images are reused, and a lock prevents simultaneous setup processes from building the same images. Calling `server/run.py` directly also runs image preparation. Model weights are downloaded by `pull` or on the first model start, separately from image setup.

`ecosystem.config.js` restarts the console when `server/app/`, `run.py`, `start.sh`, `server/.env` or the root `.env` changes. Without PM2, restart the console after editing the root `.env`.

> **Important** Apps started by PM2 inherit the permissions of the PM2 daemon. A daemon that was already running before you joined the `docker` group cannot reach docker, and neither can the console. Restart the daemon with the new permissions (this restarts the other PM2 apps too):
>
> ```bash
> pm2 save                                   # save the current app list
> sg docker -c "pm2 kill && pm2 resurrect"   # restart the daemon with docker access and restore the apps
> ```

If initial environment preparation fails, the error is printed and the console exits with code 78. PM2 does not automatically restart this exit code; fix the cause and restart the app. Docker access must be available without an interactive sudo prompt.

---

## 8. API Authentication

```bash
./vllm key new    # create a key and store it in api-key.env (mode 600)
./vllm key        # show the current key
./vllm key off    # turn authentication off
```

The key applies to servers started with `./vllm up` after the change. Clients must send `Authorization: Bearer <key>`.

> **Security note** vLLM's API key only protects the `/v1`, `/v2`, `/inference` and `/cohere` paths. `/invocations`, `/pooling`, `/score`, `/pause`, `/abort_requests` and others stay open ([vLLM security docs](https://docs.vllm.ai/en/latest/usage/security.html#api-key-authentication-limitations)). When exposing models publicly, set `BIND_ADDR=127.0.0.1` in the root `.env` and put a reverse proxy in front that forwards only `/v1`.

---

## 9. Connecting Clients

Both engines provide OpenAI-compatible chat APIs under `/v1`, including `/v1/chat/completions`. For vLLM, use `served-model-name` if configured; for Omni, use the config's `model` value. Query `/v1/models` to confirm the actual names. API compatibility does not imply support for every OpenAI endpoint or identical audio/video response handling.

**curl**

```bash
curl http://<server>:<port>/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $(./vllm key)" \
  -d '{"model": "openai/gpt-oss-20b", "messages": [{"role": "user", "content": "Hello"}]}'
```

**OpenAI Python SDK**

```python
from openai import OpenAI

client = OpenAI(base_url="http://<server>:<port>/v1", api_key="<API key>")
resp = client.chat.completions.create(
    model="openai/gpt-oss-20b",
    messages=[{"role": "user", "content": "Hello"}],
)
print(resp.choices[0].message.content)
```

**Qwen3-Omni text and speech output**

The full speech pipeline accepts `modalities=["text", "audio"]`; use `["text"]` for text output only. Non-streaming responses can contain separate text and audio choices:

```python
import base64
from pathlib import Path

response = client.chat.completions.create(
    model="Qwen/Qwen3-Omni-30B-A3B-Instruct",
    messages=[{"role": "user", "content": "Introduce yourself briefly."}],
    modalities=["text", "audio"],
)
for choice in response.choices:
    if choice.message.content:
        print(choice.message.content)
    audio = getattr(choice.message, "audio", None)
    if audio and audio.data:
        Path("output.wav").write_bytes(base64.b64decode(audio.data))
```

Audio and video requests require a client that can send the model's multimodal input format. See the [vLLM multimodal input guide](https://docs.vllm.ai/en/latest/features/multimodal_inputs/) and [Qwen3-Omni serving examples](https://docs.vllm.ai/projects/vllm-omni/en/latest/user_guide/examples/online_serving/qwen3_omni/).

**Open WebUI**

Add a connection under Admin Settings → Connections → OpenAI API:

| Field | Value |
|---|---|
| URL | `http://<server>:<port>/v1` (including `/v1`) |
| Key | the output of `./vllm key` |
| Model IDs | leave empty to fetch them from the server |

If Open WebUI runs in a docker container on the same server, use the docker bridge address (usually `172.17.0.1`) instead of `localhost`.

For models without tool calling support, disable tool use in the client and omit `tools` / `tool_choice` from requests. Audio input and Omni speech output require compatible client handling; an OpenAI-compatible connection alone does not ensure that a UI forwards original music/audio or plays Omni responses.

For models served at a fixed address through a reverse proxy or gateway, pin the port with `-p`. Otherwise the port is whichever one is free at start time.

---

## 10. Configuration Reference

Keys in the root `.env`:

| Key | Description | Default |
|---|---|---|
| `VLLM_IMAGE` | Base vLLM Docker image | `vllm/vllm-openai:v0.29.0-cu129` |
| `VLLM_OMNI_IMAGE` | Omni image to build and reuse; empty skips Omni setup | `local/vllm-omni:0.29.0-cu129` |
| `MODELS_DIR` | Model weights. Mounted read-only as `/models` in the container. | `/mnt/disk/vllm` |
| `HF_CACHE_DIR` | Cache used when a config's `model` is a HF repo id | `/mnt/disk/vllm/hf-cache` |
| `VLLM_CACHE_DIR` | torch.compile / CUDA graph cache; makes restarts faster | `/mnt/disk/vllm/vllm-cache` |
| `GPU_COUNT` | Number of GPUs to use, starting from the lowest index | `2` |
| `GPU_IDS` | GPU indices to use (e.g. `0,2`); takes precedence over `GPU_COUNT` | (empty) |
| `PORT_BASE` | First model server port | `8000` |
| `BIND_ADDR` | Bind address of the model server ports | `0.0.0.0` |
| `KV_CONCURRENCY` | Concurrent requests used for KV cache sizing | `4` |
| `AUTO_KV_GIB` | KV cache limit (GiB) for `max-model-len: auto` | `16` |
| `SAFETY_MIB` | Memory kept free on every GPU (MiB) | `2048` |

If a Hugging Face token exists (`~/.cache/huggingface/token`), it is mounted read-only into the container for gated model downloads.

---

## 11. Engine Versions

Pin the vLLM version with `VLLM_IMAGE` in the root `.env`; avoid the `latest` tag.

The image tag must match the CUDA version supported by your GPU driver. vLLM's default tags (`latest`, `v0.30.0`, …) are built on CUDA 13 and need driver 580 or newer. With driver 575 (CUDA 12.9), use tags ending in `-cu129`. Available tags are listed on [Docker Hub](https://hub.docker.com/r/vllm/vllm-openai/tags).

| Tag | Status |
|---|---|
| `v0.29.0-cu129` | Recommended (current default) |
| `v0.30.0-cu129` | Broken: torch (`2.14.0+cu130`) and torchvision (`cu129`) in the image do not match, so start-up fails ([vllm#56829](https://github.com/vllm-project/vllm/issues/56829)). |

`docker/omni.Dockerfile` builds the Omni image from `VLLM_IMAGE` and pins Omni 0.29.0rc1 to commit `aff7d64948f6c0e81e9b3272234623044e215967`. Dependency constraints preserve the base image's vLLM, PyTorch, and CUDA package versions; incompatible requirements fail the build instead of replacing that stack. Changing the base version requires checking Omni compatibility as well.

Run `./vllm omni-build` to rebuild the configured Omni tag after changing the Dockerfile or its base image. Startup reuses an existing image tag, so it does not rebuild solely because source files changed. Image builds require Docker access and network connectivity.

After changing the version, check that the log lines used by the start-up progress tracker (`server/app/services/progress.py`) have not changed.

---

## 12. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Unable to find image ... locally` | The image is being pulled automatically. The first start takes a few minutes. |
| `RuntimeError: operator torchvision::nms does not exist` | torch and torchvision in the image do not match. Use the recommended tag in [Engine Versions](#11-engine-versions). |
| Start refused for lack of space | Choose other GPUs (`-g`), free memory with `./vllm down`, or lower `max-model-len` in the config. |
| `502 Bad Gateway` from a gateway | No model server is on the port the gateway forwards to. Pin the port with `-p`. |
| Setup stops because Docker is not reachable | Check the [Docker permission](#1-docker-permission) step and the PM2 daemon permissions, then restart the app. |
| Console exits with code 78 | Environment preparation failed. Read the setup / build output in `pm2 logs vllm`, fix the cause, and restart. |
| Omni startup stays at `Using model weights format` | First startup can download large weights without a progress bar in that log. Check the HF cache for growing `.incomplete` files. |
| `User-specified max_model_len ... greater than ...` | Keep the context within the model/tokenizer limit or use `max-model-len: auto`. |
| `auto` tool choice requires a parser | Disable tool use for models without tool calling support; omit `tools` and `tool_choice`. |
| Repeated `KeyboardInterrupt` in the PM2 log during start-up | PM2 watch restarts on `__pycache__` changes. Use the repository's `ecosystem.config.js` (`watch`, `ignore_watch`). |

---

## 13. Project Structure

```
vllm                       CLI
.env.example               Example root .env
.env                       Local vLLM / Omni settings (not tracked)
ecosystem.config.js        PM2 config for the web console
lib/
  plan.py                  Memory planning
  gpufree.py               Free memory per GPU
  gen-config.py            Model config generation
  launch-config.py         Runtime config without duplicate planned options
deploy/                    vLLM / Omni model config examples and Omni stage profiles
docker/
  omni.Dockerfile          CUDA-compatible Omni image build
models/                    Model configs (not tracked)
server/                    Web console (FastAPI, uv)
  start.sh                 uv environment setup and startup
  run.py                   Serving image preparation and web server
  pyproject.toml           Python dependencies
  uv.lock                  Locked dependency versions
  .env.example
  app/
    routes/                Pages, auth, model API, WebSocket
    services/              Docker, GPUs, models, jobs, download / start-up progress
    templates/
    static/
static/imgs/               README screenshots
```

Not tracked by Git: `models/*.yaml`, `api-key.env`, `.env`, `server/.env`, `server/.venv/`, `server/data/`.

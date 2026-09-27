# vllm-manager

모델마다 vLLM 설정 YAML 하나씩 두고, 스크립트 하나로 도커로 띄웁니다. 웹 관리 화면(포트 8021)도 있습니다.

**준비물:** NVIDIA 드라이버 + docker + NVIDIA Container Toolkit, `hf` CLI(`pip install -U huggingface_hub`), `uv`(웹 관리 화면용)

**처음 clone 한 뒤:**
1. `vllm.env` 에서 이미지 태그(드라이버에 맞는 CUDA 버전)와 모델 저장 경로(`MODELS_DIR` 등)를 확인
2. `./vllm pull <HF repo id>` 로 모델을 받으면 `models/<별칭>.yaml` 이 생깁니다 (`models/` 는 서버마다 달라 git 에 올리지 않음)
3. `./vllm up <별칭>` — 웹으로 쓰려면 아래 "웹 관리 화면" 참고

```bash
./vllm                          # 대화형: 모델 번호, GPU 고르면 끝
./vllm ls                       # 모델 목록 + 모델별 필요 메모리
./vllm up gpt-oss-20b -g 0      # GPU0 에 띄우기
./vllm up qwen3-vl-8b -g 0      # 공간이 남으면 같은 GPU0 에 하나 더
./vllm up qwen2.5-vl-32b -g 0,1 # GPU 2장, TP=2 자동 설정
./vllm ps                       # 실행 중인 서버 + GPU 별 남은 공간
./vllm logs gpt-oss-20b         # 로그 (모델 이름 / GPU 번호 / 컨테이너 이름)
./vllm down gpt-oss-20b         # 종료 (모델 이름 / GPU 번호, 인자 없으면 전부)
```

- GPU를 안 적으면 남은 공간이 가장 큰 GPU를 골라줍니다 (YAML 맨 위 `# gpus: N` 만큼).
- 포트는 `8000 + 첫 번째 GPU 번호`부터 비어 있는 것을 씁니다. `-p 8000` 처럼 고정할 수 있습니다.
- 같은 모델을 같은 GPU에 다시 `up` 하면 교체, 다른 모델은 공간이 있으면 옆에 같이 띄웁니다.
- 서버가 준비될 때까지 로그를 보여주고, 준비되면 curl 예시를 출력하고 끝납니다.
- 일회성 옵션은 `--` 뒤에: `./vllm up qwen3.5-9b -- --max-num-seqs 16`
- 실제로 실행하지 않고 docker 명령만 보려면 `-n`

## 웹 관리 화면 (포트 8021)

모델 켜기/끄기/재시작, 새 모델 다운로드·삭제, 실시간 GPU 메모리·기동 진행률·로그를 웹(모바일 포함)에서 봅니다.
실제 작업은 전부 `./vllm` 을 호출하므로 메모리 계산·거부 규칙이 CLI 와 똑같습니다.

### 1. docker 권한 주기 (처음 한 번)

관리 서버는 sudo 없이 docker 를 써야 합니다 (웹에서는 sudo 비밀번호를 입력할 수 없음).

```bash
sudo usermod -aG docker $USER      # docker 그룹에 추가
id -nG                             # docker 가 보이면 적용된 것. 안 보이면 다시 로그인 (또는 아래처럼 sg docker 로 실행)
```

### 2. 가상환경과 로그인 계정

```bash
uv venv admin_server/.venv --python 3.12
uv pip install --python admin_server/.venv/bin/python -r admin_server/requirements.txt

cp admin_server/.env.example admin_server/.env
vi admin_server/.env               # ADMIN_USERNAME, ADMIN_PASSWORD, SESSION_SECRET 채우기
```

### 3. 켜기

```bash
# 그냥 실행 (터미널을 닫으면 꺼짐)
sg docker -c "admin_server/.venv/bin/python admin_server/run.py"      # → http://<서버IP>:8021

# pm2 로 상시 실행 (이 저장소의 ecosystem.config.js — 코드/.env 가 바뀌면 자동 재시작)
sg docker -c "pm2 start ecosystem.config.js"
pm2 save                           # 재부팅 후에도 뜨게
```

- **왜 `sg docker -c` 인가:** pm2 로 띄운 앱은 **pm2 데몬의 권한**을 물려받습니다. docker 그룹에 추가하기 전부터
  떠 있던 pm2 데몬 밑에서는 관리 서버도 docker 를 못 씁니다. 그럴 땐 데몬을 docker 권한으로 다시 띄우세요
  (pm2 의 다른 앱도 잠깐 재시작됩니다):
  `sg docker -c "pm2 kill && pm2 resurrect"` → 다시 로그인한 뒤라면 `sg docker -c` 없이 그냥 `pm2 ...` 써도 됩니다.
- 권한이 없으면 화면 상단에 안내가 뜨고 켜기/끄기/삭제가 막힙니다 (sudo 비밀번호를 기다리며 멈추지 않도록).
- 홈의 `~/ecosystem.config.js` 처럼 다른 설정 파일에도 `vllm` 앱이 있다면 둘 중 하나로만 띄우세요 (이름이 겹침).
- 작업(다운로드·기동·삭제) 기록과 로그는 `admin_server/data/jobs/` 에 남아서, 서버가 재시작돼도 어느 기기에서나 같은 화면이 보입니다.

| 위치 | 역할 |
|---|---|
| `admin_server/app/routes/` | 페이지, 로그인, 모델 API, WebSocket(`/ws`, 실시간 푸시) |
| `admin_server/app/services/` | docker, GPU(`lib/gpufree.py` 재사용), 모델 계획(`lib/plan.py`), 작업 실행, 기동 진행률 파싱 |
| `admin_server/app/templates/`, `static/` | 화면 (Jinja 템플릿 + CSS/JS) |

기동 진행률은 vLLM 로그 문구로 단계를 판단합니다 (`services/progress.py`). vLLM 버전을 올리면 문구가 바뀌지 않았는지 한 번 확인하세요.

## 메모리 자동 계산

`up` 할 때 모델마다 필요한 GPU 메모리를 계산해서 **딱 그만큼만** 잡습니다 (`./vllm ls` 로 미리 볼 수 있음).

```
필요 메모리(GPU 당) = 가중치 / TP  +  KV 캐시  +  작업 여유(activation·CUDA graph, 2.5GiB + 가중치 5%, 비전 모델 +2GiB)
KV 캐시            = 토큰당 KV 크기(config.json 으로 계산) × max-model-len × 동시 요청 수(기본 4)
```

- vLLM 에는 `--kv-cache-memory-bytes`(KV 크기)와 그에 맞춘 `--gpu-memory-utilization` 이 자동으로 넘어갑니다.
- `max-model-len: auto` 면 KV 캐시가 16GiB(`vllm.env` 의 `AUTO_KV_GIB`) 안에 들어가는 가장 긴 컨텍스트를 고릅니다.
  gpt-oss 는 131k, Nemotron 은 262k 처럼 KV 가 작은 모델은 길게, Qwen3-VL 처럼 큰 모델은 32k 로.
- 동시 요청 수: 전체 기본값은 `vllm.env` 의 `KV_CONCURRENCY`, 모델별로는 YAML 에 `# concurrency: 8` 주석.
  "최대 길이 요청 N개"를 담는 크기라, 짧은 대화는 훨씬 많이 동시에 처리됩니다.
- **띄우기 전에 GPU 남은 공간을 검사해서 모자라면 거부합니다.** 남은 공간은 GPU 프로세스별로 계산합니다:
  다른 사람 프로세스는 실사용량, 우리가 띄운 모델은 max(실사용, 예약량) → 아직 로딩 중인 모델 몫도 빠짐.
  오차 대비로 GPU 마다 2GiB(`SAFETY_MIB`)는 남겨둡니다.
- 직접 정하고 싶으면 YAML 에 `gpu-memory-utilization: 0.5` 를 적으면 자동 계산 대신 그 값을 씁니다.

## 새 모델 추가

```bash
./vllm pull Qwen/Qwen3-8B       # /mnt/disk/vllm/Qwen__Qwen3-8B 에 다운로드 + models/qwen3-8b.yaml 자동 생성
./vllm up qwen3-8b
```

- **받기 전에 필요 메모리를 계산합니다** (HF 의 config.json·파일 크기만 사용, 아직 받지 않음).
  가장 가볍게 띄워도(컨텍스트 4k, 동시 1) GPU 전부(A100 80GB × 2)로 못 띄우는 모델이면 "그래도 받을까요?" 를 묻습니다
  (웹에서도 확인 창). 묻지 않으려면 `--force`. 받지 않고 계산만: `./vllm fit Qwen/Qwen3-235B-A22B`
- repo id 대신 `https://huggingface.co/Qwen/Qwen3-8B` URL 을 그대로 붙여넣어도 됩니다. 인자 없이 `pull` 하면 물어봅니다.
- 별칭을 바꾸려면: `./vllm pull Qwen/Qwen3-8B my-qwen`
- 중간에 끊겨도 같은 명령을 다시 실행하면 이어서 받습니다. 설정 파일이 이미 있으면 덮어쓰지 않습니다.
- gated 모델(Llama 등)은 HF 에서 승인받고 `hf auth login` 을 먼저 해두세요.
- 설정 파일은 자동으로 채워집니다: 가중치 크기로 권장 GPU 수, 모델 카드(HF 페이지)에 적힌 vLLM 실행 예시의 권장 옵션,
  `trust-remote-code`, 임베딩 여부, 모델 계열별 reasoning/tool 파서, `max-model-len: auto`.
  생성된 내용이 화면에 출력되니 한 번 훑어보고 필요하면 고치세요.
- 다운로드 없이 설정 파일만 만들려면 `./vllm new <repo>` (폴더가 없으면 up 할 때 hf-cache 로 자동 다운로드).

`models/*.yaml` 은 vLLM 공식 설정 파일(`--config`) 형식입니다. 키는 vLLM 옵션 이름에서 `--` 만 뺀 것:

```yaml
# gpus: 1                     ← ./vllm 전용 주석: 권장 GPU 수
model: Qwen/Qwen3-8B          # HF repo id 면 자동 다운로드, /models/... 면 이미 받은 폴더
served-model-name: Qwen/Qwen3-8B
max-model-len: auto           # 위 "메모리 자동 계산" 참고. 숫자로 고정해도 됨 (예: 32768)
reasoning-parser: qwen3
enable-auto-tool-choice: true
tool-call-parser: hermes
```

`--tensor-parallel-size`, `--host`, `--port`, 메모리 옵션은 스크립트가 넣으니 YAML에 적지 않아도 됩니다.

## 인증 (API 키)

```bash
./vllm key new     # 키 생성 → api-key.env (권한 600). 이후 up 하는 서버부터 인증 켜짐
./vllm key         # 현재 키 보기
./vllm key off     # 인증 끄기
```

클라이언트는 `Authorization: Bearer <키>` 헤더를 붙이면 됩니다 (OpenAI SDK는 `api_key=` 로 넘기면 됨).

> ⚠️ vLLM의 API 키는 `/v1`, `/v2`, `/inference`, `/cohere` 경로만 막습니다. `/invocations`(추론),
> `/pooling`, `/score`, `/pause`, `/abort_requests` 같은 경로는 키 없이 열려 있습니다
> ([vLLM 보안 문서](https://docs.vllm.ai/en/latest/usage/security.html#api-key-authentication-limitations)).
> 외부에 노출해야 한다면 `vllm.env` 의 `BIND_ADDR=127.0.0.1` 로 두고, 앞단에 `/v1` 만 넘기는
> 리버스 프록시(nginx 등)를 두세요. 연구실 내부망에서 쓰는 정도면 API 키만으로도 충분합니다.

## 테스트

```bash
# 키 없이 → 401 이면 인증 정상
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8001/v1/models

# 채팅 (키는 파일에서 읽음)
curl http://localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $(./vllm key)" \
  -d '{"model": "openai/gpt-oss-20b", "messages": [{"role": "user", "content": "안녕"}]}'
```


## 외부 도메인 / Open WebUI 연결

`https://llm1.knpu.re.kr` 은 이 서버가 아니라 게이트웨이 쪽 nginx 가 받아서 이 서버(192.168.0.201)로 넘깁니다.
**502 Bad Gateway** 가 나면 게이트웨이가 넘기는 포트에 서버가 없는 것입니다.
포트는 상황 따라 바뀌니 게이트웨이에 물린 모델은 `-p` 로 고정하세요:

```bash
./vllm up gpt-oss-20b -g 1 -p 8000
```

Open WebUI: **관리자 설정 → 연결 → OpenAI API → `+`**

| 항목 | 값 |
|---|---|
| URL | `https://llm1.knpu.re.kr/v1` (내부망이면 `http://192.168.0.201:8001/v1`) — 끝에 `/v1` 필수 |
| Key | `./vllm key` 로 나오는 값 |
| Model IDs | 비워두기 (자동으로 불러옴) |

Open WebUI 가 이 GPU 서버의 docker 에서 돈다면 `localhost` 대신 `http://172.17.0.1:8001/v1`.
키를 `./vllm key new` 로 바꾸면 Open WebUI 의 Key 도 같이 바꿔야 합니다.

## vLLM 업그레이드

`vllm.env` 의 `VLLM_IMAGE` 한 줄만 바꾸면 됩니다.

> ⚠️ 이 서버의 NVIDIA 드라이버는 **575 (CUDA 12.9)** 입니다. `latest` 와 `v0.30.0` 같은 기본 태그는
> CUDA 13 이미지라서 드라이버 580 이상이 필요합니다. 반드시 **`-cu129`** 로 끝나는 태그를 쓰세요
> (예: `vllm/vllm-openai:v0.29.0-cu129`). 예전 `:latest` 설정이 자꾸 깨지던 주요 원인입니다.
>
> ⚠️ **`v0.30.0-cu129` 는 쓰지 마세요.** 이미지 안에서 torch 가 `2.14.0+cu130` 으로 잘못 덮어써져
> `RuntimeError: operator torchvision::nms does not exist` 로 죽습니다
> ([vllm#56829](https://github.com/vllm-project/vllm/issues/56829)). 그래서 `v0.29.0-cu129` 로 고정해 뒀습니다.

## 경로

| 무엇 | 위치 |
|---|---|
| 이미 받아둔 모델 (컨테이너 `/models`) | `/mnt/disk/vllm/<org>__<name>` |
| HF repo id 로 자동 다운로드되는 모델 | `/mnt/disk/vllm/hf-cache` |
| torch.compile 캐시 (재시작 가속) | `/mnt/disk/vllm/vllm-cache` |
| HF 토큰 | `~/.cache/huggingface/token` (읽기 전용으로 마운트) |

`legacy/` 는 예전 compose 파일과 `start*.sh` 입니다. 새 방식을 확인한 뒤 지워도 됩니다.

git 에 올리지 않는 것 (`.gitignore`): `models/*.yaml`(서버별 모델 설정), `api-key.env`, `admin_server/.env`,
`admin_server/.venv/`, `admin_server/data/`(작업 기록).

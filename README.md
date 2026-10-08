# vllm-manager

vllm-manager는 단일 GPU 서버에서 여러 LLM을 [vLLM](https://github.com/vllm-project/vllm) OpenAI 호환 서버로 운영하기 위한 관리 도구입니다. 모델별 설정 파일과 하나의 CLI(`./vllm`)로 모델을 내려받고 실행하며, 웹 관리 콘솔에서 같은 작업을 수행할 수 있습니다.

## 목차

- [주요 기능](#주요-기능)
- [요구 사항](#요구-사항)
- [설치](#설치)
- [빠른 시작](#빠른-시작)
- [CLI 레퍼런스](#cli-레퍼런스)
- [모델 관리](#모델-관리)
- [GPU 메모리 관리](#gpu-메모리-관리)
- [웹 관리 콘솔](#웹-관리-콘솔)
- [API 인증](#api-인증)
- [클라이언트 연결](#클라이언트-연결)
- [설정 레퍼런스](#설정-레퍼런스)
- [vLLM 버전 관리](#vllm-버전-관리)
- [문제 해결](#문제-해결)
- [디렉터리 구조](#디렉터리-구조)

## 주요 기능

- **선언적 모델 설정**: 모델마다 vLLM 공식 설정 파일(`--config`) 형식의 YAML 파일 하나로 실행 옵션을 관리합니다.
- **GPU 메모리 자동 산정**: 모델 구조(`config.json`)로 필요한 메모리를 계산하여 그만큼만 할당합니다. 한 GPU에 여러 모델을 함께 실행할 수 있으며, 공간이 부족하면 실행 전에 거부합니다.
- **모델 다운로드 및 설정 자동 생성**: Hugging Face 저장소를 내려받고, 모델 카드의 권장 옵션을 반영한 설정 파일을 생성합니다. 다운로드 전에 이 서버에서 실행 가능한지 확인합니다.
- **웹 관리 콘솔**: 모델 실행·중지·삭제, 다운로드, GPU 사용량·기동 진행률·로그의 실시간 확인을 브라우저(모바일 포함)에서 수행합니다.
- **API 키 인증**: vLLM 서버에 API 키 인증을 적용합니다.

## 요구 사항

| 항목 | 비고 |
|---|---|
| NVIDIA GPU 및 드라이버 | 드라이버가 지원하는 CUDA 버전에 맞는 vLLM 이미지를 사용해야 합니다. [vLLM 버전 관리](#vllm-버전-관리) 참고 |
| Docker, [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/) | `docker run --gpus` 를 사용할 수 있어야 합니다 |
| `hf` CLI | `pip install -U huggingface_hub`. gated 모델은 `hf auth login` 필요 |
| Python 3.8 이상, `bc`, `ss`(iproute2) | CLI 에서 사용 |
| [uv](https://docs.astral.sh/uv/), Python 3.12 | 웹 관리 콘솔에서만 필요 |
| [pm2](https://pm2.keymetrics.io/) | 웹 관리 콘솔을 상시 실행할 경우 (선택) |

## 설치

```bash
git clone git@github.com:yojun313/vllm-manager.git
cd vllm-manager
```

처음 설치할 때 `cp .env.example .env`로 루트 설정 파일을 만드세요. 이 `.env`에서 vLLM 실행 설정을 관리하며 Git에서 제외됩니다. `server/.env`는 관리 화면 로그인 설정용입니다.

루트 `.env` 에서 다음 항목을 서버 환경에 맞게 확인합니다. 전체 항목은 [설정 레퍼런스](#설정-레퍼런스)를 참고하십시오.

- `VLLM_IMAGE`: GPU 드라이버가 지원하는 CUDA 버전의 이미지 태그
- `MODELS_DIR`, `HF_CACHE_DIR`, `VLLM_CACHE_DIR`: 모델 가중치와 캐시를 저장할 경로
- `GPU_COUNT` 또는 `GPU_IDS`: vllm-manager 가 사용할 GPU. 둘 다 비워두면 감지된 모든 GPU를 사용합니다.

`models/` 디렉터리의 모델 설정은 서버마다 다르므로 저장소에 포함되지 않습니다. 설치 직후에는 비어 있으며, `./vllm pull` 로 모델을 추가합니다.

## 빠른 시작

```bash
# 1. 모델 다운로드 (설정 파일 models/qwen3-8b.yaml 이 자동 생성됩니다)
./vllm pull Qwen/Qwen3-8B

# 2. 실행
./vllm up qwen3-8b

# 3. 요청 (포트는 up 이 출력한 주소를 사용합니다)
curl http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "Qwen/Qwen3-8B", "messages": [{"role": "user", "content": "안녕하세요"}]}'
```

`./vllm up` 은 서버가 요청을 받을 수 있을 때까지 기동 로그를 표시하고, 준비가 완료되면 접속 주소와 요청 예시를 출력한 뒤 종료합니다. 서버는 백그라운드에서 계속 실행됩니다. 포트는 선택된 GPU와 사용 중인 포트에 따라 달라지며, [API 인증](#api-인증)을 설정한 경우 `Authorization` 헤더가 필요합니다.

## CLI 레퍼런스

```
./vllm [-n] <명령> [인자]
```

| 명령 | 설명 |
|---|---|
| (없음) | 대화형 메뉴에서 모델과 GPU를 선택하여 실행합니다. |
| `up <모델> [-g GPU] [-p 포트] [-- vLLM 옵션...]` | 모델을 실행합니다. 같은 모델이 같은 GPU에서 실행 중이면 교체합니다. |
| `down [모델\|GPU\|컨테이너]` | 서버를 중지합니다. 인자를 생략하면 모든 서버를 중지합니다. |
| `ps` | 실행 중인 서버와 GPU별 여유 메모리를 표시합니다. |
| `logs [모델\|GPU\|컨테이너]` | 서버 로그를 실시간으로 표시합니다. |
| `ls` | 모델 목록과 모델별 필요 메모리를 표시합니다. |
| `pull [저장소] [별칭] [--force]` | 모델을 내려받고 설정 파일을 생성합니다. |
| `fit <저장소>` | 내려받지 않고 이 서버에서 실행 가능한지만 계산합니다. |
| `new <저장소> [별칭]` | 내려받지 않고 설정 파일만 생성합니다. |
| `rm <모델> [--files]` | 모델 설정을 삭제합니다. `--files` 를 지정하면 가중치 파일도 삭제합니다. |
| `key [new\|off]` | API 키를 표시·생성·삭제합니다. |

**공통 옵션**

- `-n`, `--dry-run`: 명령을 실행하지 않고 실행될 docker 명령만 출력합니다.

**`up` 옵션**

| 옵션 | 설명 |
|---|---|
| `-g`, `--gpu` | 사용할 GPU. `0`, `1`, `0,1` 형식이며, 지정한 개수만큼 텐서 병렬(TP)로 실행합니다. 생략하면 설정 파일의 `# gpus: N` 개수만큼 여유가 큰 GPU를 선택합니다. `GPU_COUNT`·`GPU_IDS` 범위 밖의 GPU는 지정할 수 없습니다. |
| `-p`, `--port` | 호스트 포트. 생략하면 `PORT_BASE + 첫 번째 GPU 번호` 부터 사용 가능한 포트를 선택합니다. 같은 모델을 교체할 때는 기존 포트를 유지합니다. |
| `-- ...` | 이후 인자는 vLLM 에 그대로 전달되며 설정 파일보다 우선합니다. 예: `./vllm up qwen3-8b -- --max-num-seqs 16` |

컨테이너 이름은 `vllm-<모델>-g<GPU>` 형식입니다(예: `vllm-qwen3-8b-g0`). 서로 다른 모델은 물론, 같은 모델도 다른 GPU에 각각 실행할 수 있습니다.

## 모델 관리

### 모델 추가

```bash
./vllm pull Qwen/Qwen3-8B                          # 별칭은 저장소 이름의 소문자 (qwen3-8b)
./vllm pull https://huggingface.co/Qwen/Qwen3-8B    # URL 도 사용할 수 있습니다
./vllm pull Qwen/Qwen3-8B my-qwen                  # 별칭 지정
```

`pull` 은 다음 순서로 동작합니다.

1. **실행 가능 여부 확인**: Hugging Face 의 `config.json` 과 파일 크기만으로 필요 메모리를 계산합니다. 가장 가벼운 조건(컨텍스트 4,096 토큰, 동시 요청 1개)으로도 사용 가능한 GPU(`GPU_COUNT`) 전부로 실행할 수 없는 모델이면 다운로드 여부를 확인합니다. 터미널이 아닌 환경에서는 `--force` 없이 중단합니다.
2. **다운로드**: `MODELS_DIR/<org>__<name>` 에 내려받습니다. vLLM 이 사용하지 않는 `original/`, `metal/`, `onnx/`, `openvino/` 는 제외합니다. 중단된 경우 같은 명령으로 이어받을 수 있습니다.
3. **설정 파일 생성**: `models/<별칭>.yaml` 을 생성합니다. 이미 있으면 덮어쓰지 않습니다.

생성되는 설정 파일에는 다음 내용이 반영됩니다. 생성 결과가 화면에 출력되므로 필요하면 수정하십시오.

- 가중치 크기로 산정한 권장 GPU 수
- 모델 카드에 기재된 `vllm serve` 권장 옵션
- `trust-remote-code`(사용자 정의 코드가 있는 경우), 임베딩 모델 여부(`runner: pooling`)
- 모델 계열별 reasoning 파서와 tool call 파서(Qwen, gpt-oss, Nemotron, Llama)

### 설정 파일 형식

`models/*.yaml` 은 vLLM 공식 설정 파일 형식입니다. 키는 vLLM CLI 옵션 이름에서 `--` 를 제외한 것입니다.

```yaml
# gpus: 1                       # vllm-manager 전용 주석: 권장 GPU 수
# concurrency: 4                # vllm-manager 전용 주석: KV 캐시 산정 시 동시 요청 수 (선택)
model: /models/Qwen__Qwen3-8B   # 받아둔 모델은 /models/<폴더>, HF 저장소 이름이면 실행 시 자동 다운로드
served-model-name: Qwen/Qwen3-8B
max-model-len: auto             # 숫자로 고정할 수 있습니다 (예: 32768)
reasoning-parser: qwen3
enable-auto-tool-choice: true
tool-call-parser: hermes
```

`--tensor-parallel-size`, `--host`, `--port` 와 메모리 관련 옵션은 `./vllm up` 이 지정하므로 설정 파일에 적지 않습니다.

### 모델 삭제

```bash
./vllm rm qwen3-8b            # 설정 파일만 삭제
./vllm rm qwen3-8b --files    # 가중치 파일까지 삭제
```

실행 중인 모델은 삭제할 수 없습니다. 다른 설정 파일이 같은 가중치를 사용하는 경우, 그리고 가중치 경로가 `MODELS_DIR` 또는 `HF_CACHE_DIR` 바로 아래가 아닌 경우에는 가중치를 삭제하지 않습니다.

## GPU 메모리 관리

### 필요 메모리 산정

`./vllm up` 은 모델마다 필요한 GPU 메모리를 계산하여 그만큼만 할당합니다. 계산 결과는 `./vllm ls` 로 확인할 수 있습니다.

```
필요 메모리(GPU당) = 가중치 / TP + KV 캐시 + 작업 메모리
KV 캐시            = 토큰당 KV 크기 × max-model-len × 동시 요청 수
작업 메모리         = 2.5 GiB + 가중치의 5% (+ 비전 모델 2 GiB)
```

- 토큰당 KV 크기는 `config.json` 의 레이어 수, KV 헤드 수, 헤드 차원으로 계산합니다. sliding window 레이어와 linear attention·Mamba 레이어는 제외합니다.
- vLLM 에는 계산된 KV 캐시 크기(`--kv-cache-memory-bytes`)와 이에 맞춘 `--gpu-memory-utilization` 이 전달됩니다.
- `max-model-len: auto` 이면 KV 캐시가 `AUTO_KV_GIB`(기본 16 GiB) 이내가 되는 가장 긴 컨텍스트를 선택합니다. 최소값은 32,768 토큰입니다.
- 동시 요청 수의 기본값은 `KV_CONCURRENCY`(기본 4)이며, 이는 최대 길이 요청을 동시에 처리할 수 있는 개수입니다. 짧은 요청은 이보다 많이 동시에 처리됩니다.
- 설정 파일에 `gpu-memory-utilization` 을 지정하면 자동 산정 대신 해당 값을 사용합니다.

### 여러 모델의 동시 실행

실행 전에 대상 GPU의 여유 메모리를 확인하고, 부족하면 아무 변경 없이 실행을 거부합니다. 여유 메모리는 GPU 프로세스 단위로 계산합니다.

- vllm-manager 가 실행한 모델: 실제 사용량과 예약량 중 큰 값 (기동 중인 모델의 예약분도 반영됩니다)
- 그 외 프로세스: 실제 사용량
- 계산 오차에 대비하여 GPU마다 `SAFETY_MIB`(기본 2 GiB)를 남깁니다.

## 웹 관리 콘솔

`server/` 는 FastAPI 기반 웹 관리 콘솔입니다. 모든 작업은 `./vllm` 을 호출하여 수행되므로 CLI 와 동일한 규칙이 적용됩니다.

**기능**

- 모델 실행·재시작·중지·삭제
- 모델 다운로드 (바이트 단위 진행률, 속도, 남은 시간 표시, 실행 불가 모델에 대한 확인)
- GPU별 메모리 사용량·사용률·온도·전력 실시간 표시 (`GPU_COUNT`·`GPU_IDS` 로 지정한 GPU)
- 모델 기동 진행률(가중치 로딩, 컴파일, CUDA graph 캡처 등 단계별)과 로그 실시간 표시
- 아이디·비밀번호 로그인

작업은 웹 서버와 분리된 프로세스에서 실행되며, 기록과 로그는 `server/data/jobs/` 에 저장됩니다. 따라서 웹 서버가 재시작되어도 진행 중인 다운로드와 기동은 중단되지 않으며, 모든 기기와 브라우저에서 같은 상태가 표시됩니다.

### 1. Docker 권한 설정

웹 관리 콘솔은 sudo 없이 docker 를 사용할 수 있어야 합니다. 실행 사용자를 `docker` 그룹에 추가합니다.

```bash
sudo usermod -aG docker $USER
```

그룹 변경은 새 로그인 세션부터 적용됩니다. 다시 로그인하지 않고 적용하려면 이후 명령을 `sg docker -c "..."` 로 실행합니다.

### 2. 가상 환경 및 계정 설정

```bash
uv sync --project server --python 3.12

cp server/.env.example server/.env
```

`server/.env` 에 로그인 계정과 세션 키를 설정합니다. 외부에서 HTTPS 프록시를 통해 접속하면 세션 쿠키에 `Secure`가 적용됩니다. 관리 서버는 HTTPS 프록시 뒤에서만 외부에 공개하세요.

| 변수 | 설명 | 기본값 |
|---|---|---|
| `ADMIN_USERNAME` | 로그인 아이디 | (필수) |
| `ADMIN_PASSWORD` | 강한 로그인 비밀번호 | (필수) |
| `SESSION_SECRET` | 재시작 후에도 세션을 유지할 서명 키. `python3 -c "import secrets; print(secrets.token_hex(32))"` 로 생성하세요. 비워두면 재시작 때마다 로그아웃됩니다. | 무작위 |
| `SESSION_DAYS` | 로그인 유지 기간(일) | `14` |
| `COOKIE_SECURE` | 세션 쿠키를 HTTPS 연결에서만 전송. 로컬 HTTP 개발에서만 `false`로 설정하세요. | `true` |
| `PORT` | 웹 서버 포트 | `8000` |
| `HOST` | 바인드 주소. `127.0.0.1` 로 지정하면 서버 내부에서만 접속할 수 있습니다. | `0.0.0.0` |
| `MODEL_PUBLIC_URL_<포트>` | 해당 모델 포트의 주소 복사 값. 예: `MODEL_PUBLIC_URL_8000=llm0.knpu.re.kr/v1`, `MODEL_PUBLIC_URL_8001=llm1.knpu.re.kr/v1` | `http://현재호스트:포트/v1` |

주소 복사 URL은 `server/.env`에 설정한 문자열 그대로 사용합니다. 변경 후 관리 서버를 재시작하고 페이지를 새로고침하세요.

> **참고** `PORT` 의 기본값 8000 은 모델 서버의 기본 포트(루트 `.env` 의 `PORT_BASE`)와 같습니다. 같은 서버에서 모델도 실행한다면 `8021` 처럼 다른 포트를 지정하십시오. FastAPI Swagger UI(`/docs`), ReDoc(`/redoc`), OpenAPI 스키마(`/openapi.json`)는 비활성화되어 있습니다.

### 3. 실행

```bash
# 포그라운드 실행
uv run --project server python server/run.py

# pm2 로 상시 실행
pm2 start ecosystem.config.js
pm2 save
```

`ecosystem.config.js` 는 `server/app/`, `run.py`, `server/.env` 와 루트 `.env` 가 변경되면 웹 서버를 자동으로 재시작하도록 설정되어 있습니다. pm2 없이 실행하는 경우 루트 `.env` 를 변경한 뒤 웹 서버를 재시작하십시오.

> **중요** pm2 로 실행한 앱은 pm2 데몬의 권한을 그대로 사용합니다. `docker` 그룹에 추가하기 전부터 실행 중이던 pm2 데몬 아래에서는 웹 관리 콘솔도 docker 에 접근할 수 없습니다. 이 경우 pm2 데몬을 새 권한으로 다시 시작하십시오. pm2 로 실행 중인 다른 앱도 함께 재시작됩니다.
>
> ```bash
> pm2 save                                   # 현재 실행 중인 앱 목록 저장
> sg docker -c "pm2 kill && pm2 resurrect"   # docker 권한으로 데몬을 다시 시작하고 앱 목록 복원
> ```

docker 에 접근할 수 없으면 화면 상단에 안내가 표시되고 실행·중지·삭제 기능이 비활성화됩니다.

## API 인증

```bash
./vllm key new    # 키를 생성하여 api-key.env 에 저장합니다 (권한 600)
./vllm key        # 현재 키를 표시합니다
./vllm key off    # 인증을 해제합니다
```

키는 이후 `./vllm up` 으로 실행하는 서버부터 적용됩니다. 클라이언트는 `Authorization: Bearer <키>` 헤더를 전송해야 합니다.

> **보안 참고** vLLM 의 API 키 인증은 `/v1`, `/v2`, `/inference`, `/cohere` 경로에만 적용됩니다. `/invocations`, `/pooling`, `/score`, `/pause`, `/abort_requests` 등은 인증 없이 접근할 수 있습니다([vLLM 보안 문서](https://docs.vllm.ai/en/latest/usage/security.html#api-key-authentication-limitations)). 외부에 공개하는 경우 루트 `.env` 의 `BIND_ADDR` 를 `127.0.0.1` 로 지정하고, `/v1` 경로만 전달하는 리버스 프록시를 앞단에 두는 것을 권장합니다.

## 클라이언트 연결

모든 서버는 OpenAI 호환 API(`/v1`)를 제공합니다. 모델 이름은 설정 파일의 `served-model-name` 입니다.

**curl**

```bash
curl http://<서버>:<포트>/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $(./vllm key)" \
  -d '{"model": "openai/gpt-oss-20b", "messages": [{"role": "user", "content": "안녕하세요"}]}'
```

**OpenAI Python SDK**

```python
from openai import OpenAI

client = OpenAI(base_url="http://<서버>:<포트>/v1", api_key="<API 키>")
resp = client.chat.completions.create(
    model="openai/gpt-oss-20b",
    messages=[{"role": "user", "content": "안녕하세요"}],
)
print(resp.choices[0].message.content)
```

**Open WebUI**

관리자 설정 → 연결 → OpenAI API 에서 연결을 추가합니다.

| 항목 | 값 |
|---|---|
| URL | `http://<서버>:<포트>/v1` (`/v1` 까지 입력) |
| Key | `./vllm key` 의 출력값 |
| Model IDs | 비워두면 서버에서 자동으로 가져옵니다 |

Open WebUI 가 같은 서버의 docker 컨테이너에서 실행 중이면 `localhost` 대신 docker 브리지 주소(일반적으로 `172.17.0.1`)를 사용합니다.

리버스 프록시나 게이트웨이를 통해 고정 주소로 제공하는 모델은 `-p` 로 포트를 고정하십시오. 포트를 지정하지 않으면 실행 시점의 사용 가능한 포트가 선택됩니다.

## 설정 레퍼런스

루트 `.env` 의 항목은 다음과 같습니다.

| 변수 | 설명 | 기본값 |
|---|---|---|
| `VLLM_IMAGE` | vLLM docker 이미지 | `vllm/vllm-openai:v0.29.0-cu129` |
| `MODELS_DIR` | 모델 가중치 저장 경로. 컨테이너에는 `/models` 로 읽기 전용 마운트됩니다. | `/mnt/disk/vllm` |
| `HF_CACHE_DIR` | 설정 파일의 `model` 이 HF 저장소 이름일 때 사용하는 캐시 | `/mnt/disk/vllm/hf-cache` |
| `VLLM_CACHE_DIR` | torch.compile·CUDA graph 캐시. 재시작 시 기동 시간을 줄입니다. | `/mnt/disk/vllm/vllm-cache` |
| `GPU_COUNT` | 사용할 GPU 수. 번호가 앞선 GPU부터 N장을 사용합니다. | `2` |
| `GPU_IDS` | 사용할 GPU 번호 목록(예: `0,2`). 지정하면 `GPU_COUNT` 보다 우선합니다. | (없음) |
| `PORT_BASE` | 모델 서버 포트 시작값 | `8000` |
| `BIND_ADDR` | 모델 서버 포트의 바인드 주소 | `0.0.0.0` |
| `KV_CONCURRENCY` | KV 캐시 산정 시 동시 요청 수 | `4` |
| `AUTO_KV_GIB` | `max-model-len: auto` 일 때 KV 캐시 상한(GiB) | `16` |
| `SAFETY_MIB` | GPU마다 남겨두는 여유 메모리(MiB) | `2048` |

Hugging Face 토큰(`~/.cache/huggingface/token`)이 있으면 컨테이너에 읽기 전용으로 마운트되어 gated 모델 다운로드에 사용됩니다.

## vLLM 버전 관리

vLLM 버전은 루트 `.env` 의 `VLLM_IMAGE` 로 고정합니다. `latest` 태그는 사용하지 않는 것을 권장합니다.

이미지 태그는 GPU 드라이버가 지원하는 CUDA 버전과 일치해야 합니다. vLLM 의 기본 태그(`latest`, `v0.30.0` 등)는 CUDA 13 기반으로 드라이버 580 이상이 필요합니다. 드라이버 575(CUDA 12.9) 환경에서는 `-cu129` 로 끝나는 태그를 사용하십시오. 사용 가능한 태그는 [Docker Hub](https://hub.docker.com/r/vllm/vllm-openai/tags)에서 확인할 수 있습니다.

| 태그 | 상태 |
|---|---|
| `v0.29.0-cu129` | 권장 (현재 기본값) |
| `v0.30.0-cu129` | 사용 불가. 이미지 내 torch(`2.14.0+cu130`)와 torchvision(`cu129`)의 버전 불일치로 기동에 실패합니다([vllm#56829](https://github.com/vllm-project/vllm/issues/56829)). |

버전을 변경한 뒤에는 기동 진행률 표시(`server/app/services/progress.py`)가 참조하는 로그 문구가 바뀌지 않았는지 확인하십시오.

## 문제 해결

| 증상 | 원인 및 해결 |
|---|---|
| `Unable to find image ... locally` | 이미지가 아직 없어 자동으로 내려받는 중입니다. 첫 실행 시 수 분이 걸립니다. |
| `RuntimeError: operator torchvision::nms does not exist` | 이미지의 torch 와 torchvision 버전이 맞지 않습니다. [vLLM 버전 관리](#vllm-버전-관리)의 권장 태그를 사용하십시오. |
| `공간 부족` 으로 실행이 거부됨 | 다른 GPU(`-g`)를 지정하거나, `./vllm down` 으로 공간을 확보하거나, 설정 파일의 `max-model-len` 을 줄이십시오. |
| 게이트웨이에서 `502 Bad Gateway` | 게이트웨이가 전달하는 포트에 모델 서버가 없습니다. `-p` 로 포트를 고정하십시오. |
| 웹 콘솔에 "docker 에 접근할 수 없습니다" 표시 | [Docker 권한 설정](#1-docker-권한-설정)과 pm2 데몬 재시작을 확인하십시오. |
| pm2 로그에 기동 중 `KeyboardInterrupt` 가 반복됨 | pm2 watch 가 `__pycache__` 변경으로 재시작하는 경우입니다. 저장소의 `ecosystem.config.js` 설정(`watch`, `ignore_watch`)을 사용하십시오. |

## 디렉터리 구조

```
vllm-manager/
├── vllm                   # CLI
├── .env.example           # 루트 .env 설정 예시
├── .env                   # vLLM 로컬 설정 (Git 제외)
├── ecosystem.config.js    # 웹 관리 콘솔 pm2 설정
├── lib/
│   ├── plan.py            # 필요 메모리 산정
│   ├── gpufree.py         # GPU별 여유 메모리 계산
│   └── gen-config.py      # 모델 설정 파일 생성
├── models/                # 모델 설정 파일 (git 제외)
└── server/                # 웹 관리 콘솔 (FastAPI, uv)
    ├── run.py
    ├── .env.example
    └── app/
        ├── routes/        # 페이지, 인증, API, WebSocket
        ├── services/      # docker, GPU, 모델, 작업, 다운로드·기동 진행률
        ├── templates/
        └── static/
```

다음 파일은 저장소에 포함되지 않습니다: `models/*.yaml`, `api-key.env`, `.env`, `server/.env`, `server/.venv/`, `server/data/`.

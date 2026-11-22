#!/usr/bin/env sh
# vLLM Manager installer.
#
#   curl -fsSL https://raw.githubusercontent.com/yojun313/vllm-manager/main/install.sh | sh
#
# What it does, in order:
#   1. checks git, curl, python3, Docker and the NVIDIA driver, and prints the one command to fix anything
#      missing (it never uses sudo itself)
#   2. installs uv (the Python manager) into your home folder if you do not have it
#   3. downloads vLLM Manager into ~/vllm-manager (or updates it if it is already there)
#   4. installs the web console's Python dependencies into ~/vllm-manager/server/.venv
#   5. asks a few questions (model folder, GPUs, port, admin login) with detected defaults
#   6. starts the web console in the background and prints its address
#
# Options (environment variables):
#   VLLM_MANAGER_DIR=/some/path    install somewhere else
#   VLLM_MANAGER_YES=1             ask nothing: detected defaults, user "admin", generated password
#   VLLM_MANAGER_NO_START=1        install and configure only, do not start the console
set -eu

REPO="${VLLM_MANAGER_REPO:-https://github.com/yojun313/vllm-manager.git}"
DIR="${VLLM_MANAGER_DIR:-$HOME/vllm-manager}"

say() { printf '%s\n' "$*"; }
step() { printf '\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mNote:\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Linux" ] || die "vLLM Manager runs on Linux with NVIDIA GPUs (on Windows, use WSL 2)."

step "Checking requirements"
missing=""
for tool in git curl python3; do
  command -v "$tool" >/dev/null 2>&1 || missing="$missing $tool"
done
if [ -n "$missing" ]; then
  say "Missing:$missing"
  if command -v apt-get >/dev/null 2>&1; then say "Install with:  sudo apt-get install -y$missing"
  elif command -v dnf >/dev/null 2>&1; then say "Install with:  sudo dnf install -y$missing"
  elif command -v pacman >/dev/null 2>&1; then say "Install with:  sudo pacman -S$missing"
  fi
  die "Install the missing tools, then run this installer again."
fi
say "git, curl and python3 are installed."

# Docker and the GPU are needed to run models, not to install. Report them now so nothing is a surprise later.
ready=1
if ! command -v docker >/dev/null 2>&1; then
  ready=0; warn "Docker is not installed. See https://docs.docker.com/engine/install/"
elif ! docker info >/dev/null 2>&1; then
  ready=0; warn "This account cannot use Docker. Run:  sudo usermod -aG docker \$USER   then sign in again."
else
  say "Docker is installed and usable."
  if ! docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q nvidia && ! command -v nvidia-ctk >/dev/null 2>&1; then
    ready=0; warn "The NVIDIA Container Toolkit is missing. See https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
  fi
fi
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  say "NVIDIA driver $(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1), $(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l | tr -d ' ') GPU(s)."
else
  ready=0; warn "No working NVIDIA driver was found (nvidia-smi). Models cannot start until one is installed."
fi
[ "$ready" = 1 ] || say "Continuing with the install. The console will show what is still missing, and so will: $DIR/vllm doctor"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  step "Installing uv (Python manager) into your home folder"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  command -v uv >/dev/null 2>&1 || die "uv was installed but is not on PATH. Open a new terminal and run this installer again."
fi

if [ -d "$DIR/.git" ]; then
  step "Updating vLLM Manager in $DIR"
  git -C "$DIR" pull --ff-only || say "Could not update automatically (local changes?). Continuing with the version on disk."
elif [ -e "$DIR" ]; then
  die "$DIR already exists and is not a vLLM Manager checkout. Set VLLM_MANAGER_DIR to another folder."
else
  step "Downloading vLLM Manager into $DIR"
  git clone --depth 1 "$REPO" "$DIR"
fi

step "Installing Python dependencies (first run takes a minute)"
cd "$DIR"
uv sync --project server --python 3.12
chmod +x vllm server/start.sh

step "Configuring"
if grep -qE '^ADMIN_(PASS_HASH|PASSWORD)=.+' server/.env 2>/dev/null && [ -f .env ]; then
  say "Already configured. Keeping your current settings (change them with: $DIR/vllm configure)."
elif [ "${VLLM_MANAGER_YES:-0}" = "1" ]; then
  python3 tools/setup.py --yes
elif [ -r /dev/tty ]; then
  python3 tools/setup.py
else
  python3 tools/setup.py --ensure
  say "No terminal to ask questions on. The console will show a one-time setup address when it starts."
fi

if [ "${VLLM_MANAGER_NO_START:-0}" = "1" ]; then
  say ""
  say "Installed. Start the console with:  $DIR/vllm server up"
  exit 0
fi

step "Starting the web console"
./vllm server restart
say ""
say "Open the address above in a browser and sign in."
say "  $DIR/vllm server status|logs|down    control the console"
say "  $DIR/vllm server enable              start it automatically at boot"
say "  $DIR/vllm doctor                     check the install"
say "  $DIR/vllm update                     get the latest version"

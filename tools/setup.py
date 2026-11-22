#!/usr/bin/env python3
"""vLLM Manager setup: writes .env (model serving) and server/.env (web console login).

    ./vllm configure            interactive: press Enter to accept each detected default
    ./vllm configure --yes      no questions: detected defaults, user "admin", generated password
    python3 tools/setup.py --ensure
                                create any missing file with defaults and ask nothing (used at startup);
                                the admin account is then created on the first-run page in the browser

Existing values are kept as the defaults, so running it again only changes what you answer differently.
Standard library only, Python 3.8+. The password is stored as a PBKDF2 hash, never in plain text.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_ENV = ROOT / ".env"
SERVER_ENV = ROOT / "server" / ".env"
PBKDF2_ITERATIONS = 310_000
AUDIO_IMAGE = "local/vllm-audio:0.29.0-cu129"
OMNI_IMAGE = "local/vllm-omni:0.29.0-cu129"
WORDS = "amber birch cedar delta ember fjord grove harbor indigo juniper kelp lumen maple nectar onyx pebble quartz river sable tundra umber violet willow zephyr".split()

BOLD, DIM, GREEN, YELLOW, RESET = (
    ("\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[0m")
    if sys.stdout.isatty()
    else ("",) * 5
)


def say(text: str = "") -> None:
    print(text, flush=True)


# ---------------------------------------------------------------- .env files
def read_env(path: Path) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
            if m:
                env[m.group(1)] = m.group(2).strip().strip("'\"")
    return env


def write_env(path: Path, template: Path, values: dict) -> None:
    """Start from the existing file (or the commented template) and replace only the given keys."""
    source = path if path.exists() else template
    lines = source.read_text(encoding="utf-8").splitlines()
    left = dict(values)
    out = []
    for line in lines:
        m = re.match(r"^([A-Z0-9_]+)=", line.strip())
        if m and m.group(1) in left:
            value = left.pop(m.group(1))
            if value is not None:
                out.append("%s=%s" % (m.group(1), value))
            continue
        out.append(line)
    out += ["%s=%s" % (k, v) for k, v in left.items() if v is not None]
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.replace(str(tmp), str(path))


# ---------------------------------------------------------------- detection
def run(cmd: list, timeout: float = 15) -> str:
    try:
        r = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=timeout,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def detect_gpus() -> list:
    rows = run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    gpus = []
    for line in rows.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            gpus.append(
                {"idx": parts[0], "name": parts[1], "mib": parts[2], "driver": parts[3]}
            )
    return gpus


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def first_free_port(start: int, avoid: range) -> int:
    port = start
    while port < start + 200 and (port in avoid or not port_free(port)):
        port += 1
    return port


def default_models_dir() -> str:
    """The roomiest of a few usual places; falls back to the home folder."""
    home = Path.home() / "vllm-models"
    best, best_free = home, 0
    for candidate in (home, Path("/data/vllm-models"), Path("/mnt/data/vllm-models")):
        probe = candidate
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            free = shutil.disk_usage(str(probe)).free
        except OSError:
            continue
        if os.access(str(probe), os.W_OK) and free > best_free * 1.5:
            best, best_free = candidate, free
    return str(best)


def local_addresses() -> list:
    out = run(["hostname", "-I"])
    return [a for a in out.split() if ":" not in a][:2]


# ---------------------------------------------------------------- password
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (PBKDF2_ITERATIONS, salt.hex(), digest.hex())


def generate_password() -> str:
    return (
        "-".join(secrets.choice(WORDS) for _ in range(4))
        + "-"
        + str(secrets.randbelow(90) + 10)
    )


def tty():
    """Questions are read from the terminal even when the installer itself is piped (curl ... | sh)."""
    if sys.stdin.isatty():
        return sys.stdin
    try:
        return open("/dev/tty")
    except OSError:
        return None


def ask(stream, question: str, default: str, check=None) -> str:
    while True:
        sys.stdout.write("%s%s%s [%s]: " % (BOLD, question, RESET, default))
        sys.stdout.flush()
        answer = stream.readline()
        if not answer:  # terminal closed
            return default
        answer = answer.strip() or default
        problem = check(answer) if check else None
        if not problem:
            return answer
        say("  %s%s%s" % (YELLOW, problem, RESET))


def ask_yes(stream, question: str, default: bool) -> bool:
    answer = ask(
        stream, question + (" (Y/n)" if default else " (y/N)"), "y" if default else "n"
    ).lower()
    return answer.startswith("y")


def ask_password() -> tuple:
    while True:
        try:
            password = getpass.getpass(
                "%sPassword%s (Enter = generate one): " % (BOLD, RESET)
            )
            if not password:
                return generate_password(), True
            if getpass.getpass("Type it again: ") != password:
                say("  %sThe two entries differ.%s" % (YELLOW, RESET))
                continue
            return password, False
        except (EOFError, KeyboardInterrupt):
            say()
            raise SystemExit("Setup cancelled.")


# ---------------------------------------------------------------- checks
def check_port(value: str):
    return (
        None
        if value.isdigit() and 1 <= int(value) <= 65535
        else "Enter a port number between 1 and 65535."
    )


def check_dir(value: str):
    if not value.startswith("/"):
        return "Enter an absolute path (starting with /)."
    probe = Path(value)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return (
        None
        if os.access(str(probe), os.W_OK)
        else "This account cannot write to %s." % probe
    )


def check_user(value: str):
    return (
        None
        if re.match(r"^[A-Za-z0-9._@-]{1,64}$", value)
        else "Use letters, digits and . _ @ - only."
    )


def gpu_check(gpus: list):
    def check(value: str):
        if value.lower() == "all":
            return None
        if not re.match(r"^\d+(,\d+)*$", value):
            return "Enter 'all' or a list such as 0,1."
        missing = [g for g in value.split(",") if g not in {x["idx"] for x in gpus}]
        return "No such GPU: %s" % ", ".join(missing) if missing and gpus else None

    return check


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description="vLLM Manager setup")
    ap.add_argument(
        "--yes",
        action="store_true",
        help="ask nothing; use detected defaults and a generated password",
    )
    ap.add_argument(
        "--ensure",
        action="store_true",
        help="only create missing files with defaults (no questions, no admin account)",
    )
    args = ap.parse_args()

    root_env, server_env = read_env(ROOT_ENV), read_env(SERVER_ENV)
    gpus = detect_gpus()
    models_dir = root_env.get("MODELS_DIR") or default_models_dir()
    port_base = int(root_env.get("PORT_BASE") or 8000)
    model_ports = range(port_base, port_base + 64)
    console_port = server_env.get("PORT") or str(first_free_port(8080, model_ports))

    if args.ensure:
        if not ROOT_ENV.exists():
            write_env(
                ROOT_ENV,
                ROOT / ".env.example",
                {
                    "MODELS_DIR": models_dir,
                    "HF_CACHE_DIR": models_dir + "/hf-cache",
                    "VLLM_CACHE_DIR": models_dir + "/vllm-cache",
                },
            )
        if not SERVER_ENV.exists():
            write_env(
                SERVER_ENV,
                ROOT / "server" / ".env.example",
                {"SESSION_SECRET": secrets.token_hex(32), "PORT": console_port},
            )
        elif not server_env.get("SESSION_SECRET"):
            write_env(
                SERVER_ENV,
                ROOT / "server" / ".env.example",
                {"SESSION_SECRET": secrets.token_hex(32)},
            )
        return

    stream = None if args.yes else tty()
    if not args.yes and stream is None:
        raise SystemExit(
            "No terminal to ask questions on. Run `./vllm configure --yes`, or finish setup in the browser."
        )

    say("%svLLM Manager setup%s" % (BOLD, RESET))
    if gpus:
        say(
            "%sDetected %d GPU(s): %s (driver %s)%s"
            % (
                DIM,
                len(gpus),
                ", ".join(sorted({g["name"] for g in gpus})),
                gpus[0]["driver"],
                RESET,
            )
        )
    else:
        say(
            "%sNo NVIDIA GPU was detected (nvidia-smi). You can still finish setup; `./vllm doctor` explains what is missing.%s"
            % (YELLOW, RESET)
        )

    current_gpus = root_env.get("GPU_IDS") or "all"
    username = server_env.get("ADMIN_USERNAME") or "admin"
    bind_all = (server_env.get("HOST") or "0.0.0.0") != "127.0.0.1"
    audio = bool(root_env.get("VLLM_AUDIO_IMAGE"))
    omni = bool(root_env.get("VLLM_OMNI_IMAGE"))
    keep_password = bool(
        server_env.get("ADMIN_PASS_HASH") or server_env.get("ADMIN_PASSWORD")
    )
    password, generated = None, False

    if stream is not None:
        say(
            "%sPress Enter to accept the value in [brackets]. Everything can be changed later in the web console.%s\n"
            % (DIM, RESET)
        )
        models_dir = ask(stream, "Folder for model weights", models_dir, check_dir)
        current_gpus = ask(
            stream,
            "GPUs to use ('all' or a list such as 0,1)",
            current_gpus,
            gpu_check(gpus),
        )
        console_port = ask(stream, "Web console port", console_port, check_port)
        bind_all = ask_yes(
            stream, "Allow access to the console from other machines", bind_all
        )
        audio = ask_yes(
            stream,
            "Add audio input support (builds an extra image on first start, a few minutes)",
            audio,
        )
        omni = ask_yes(
            stream,
            "Enable vLLM-Omni for speech-capable models (builds a large image on first start)",
            omni,
        )
        username = ask(stream, "Admin username", username, check_user)
        if not keep_password or ask_yes(stream, "Set a new admin password", False):
            password, generated = ask_password()
    elif not keep_password:
        password, generated = generate_password(), True

    for folder in (models_dir, models_dir + "/hf-cache", models_dir + "/vllm-cache"):
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise SystemExit("Could not create %s: %s" % (folder, e.strerror))
    (ROOT / "models").mkdir(exist_ok=True)

    moved = "MODELS_DIR" not in root_env or root_env.get("MODELS_DIR") != models_dir
    root_values = {
        "MODELS_DIR": models_dir,
        "GPU_IDS": "" if current_gpus.lower() == "all" else current_gpus,
        "VLLM_AUDIO_IMAGE": (root_env.get("VLLM_AUDIO_IMAGE") or AUDIO_IMAGE)
        if audio
        else "",
        "VLLM_OMNI_IMAGE": (root_env.get("VLLM_OMNI_IMAGE") or OMNI_IMAGE)
        if omni
        else "",
    }
    if moved or not root_env.get("HF_CACHE_DIR"):
        root_values["HF_CACHE_DIR"] = models_dir + "/hf-cache"
    if moved or not root_env.get("VLLM_CACHE_DIR"):
        root_values["VLLM_CACHE_DIR"] = models_dir + "/vllm-cache"
    if current_gpus.lower() != "all":
        root_values["GPU_COUNT"] = ""
    write_env(ROOT_ENV, ROOT / ".env.example", root_values)

    server_values = {
        "ADMIN_USERNAME": username,
        "PORT": console_port,
        "HOST": "0.0.0.0" if bind_all else "127.0.0.1",
        "SESSION_SECRET": server_env.get("SESSION_SECRET") or secrets.token_hex(32),
    }
    if password:
        server_values["ADMIN_PASS_HASH"] = hash_password(password)
        server_values["ADMIN_PASSWORD"] = None  # drop a legacy plain-text entry
    write_env(SERVER_ENV, ROOT / "server" / ".env.example", server_values)

    host = (local_addresses() or ["127.0.0.1"])[0] if bind_all else "127.0.0.1"
    say("\n%sSaved.%s" % (GREEN, RESET))
    say("  Console   http://%s:%s" % (host, console_port))
    say("  Username  %s" % username)
    if generated:
        say(
            "  Password  %s%s%s   %s(shown once; change it under Preferences in the console)%s"
            % (BOLD, password, RESET, DIM, RESET)
        )
    say("  Models    %s" % models_dir)
    say(
        "\nStart the console with %s./vllm server up%s (restart it if it is already running)."
        % (BOLD, RESET)
    )


if __name__ == "__main__":
    main()

"""패스키(WebAuthn) 로그인.

패스키는 사용자의 기기(휴대폰, 노트북, 보안 키)에 있고, 기기의 잠금 해제(지문, 얼굴, PIN)로 본인을 확인한다.
그래서 패스키로 로그인할 때는 비밀번호가 필요 없다. 휴대폰의 패스키로 데스크톱 브라우저에 로그인하는 것(QR 코드)은
브라우저와 운영체제가 처리한다.

서버에는 공개 키만 저장한다(data/passkeys.json, 권한 600). 챌린지는 서버 메모리에 두고 한 번만 쓸 수 있으며,
브라우저에는 그 챌린지를 가리키는 임의의 표(ticket)만 준다. RP ID 는 브라우저가 접속한 호스트 이름이라
한 주소에서 만든 패스키는 다른 주소에서 쓸 수 없다.
"""

import base64
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app import config

logger = logging.getLogger("uvicorn.error")

MAX_PASSKEYS = 20
CHALLENGE_SECONDS = 5 * 60
NAME_MAX = 40
_lock = threading.Lock()


class PasskeyError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 문구 (한국어, 영어)."""

    def __init__(self, ko: str, en: str):
        super().__init__(en)
        self.ko, self.en = ko, en


E_ADDRESS = (
    "이 주소에서는 패스키를 사용할 수 없습니다.",
    "Passkeys cannot be used at this address.",
)
E_HTTPS = (
    "패스키는 HTTPS 주소(또는 localhost)에서만 사용할 수 있습니다.",
    "Passkeys only work over HTTPS (or on localhost).",
)
E_EXPIRED = (
    "시간이 지났습니다. 다시 시도해 주십시오.",
    "That took too long. Please try again.",
)
E_FULL = (
    "패스키를 더 등록할 수 없습니다. 쓰지 않는 패스키를 삭제해 주십시오.",
    "No more passkeys can be added. Remove one you no longer use.",
)
E_REGISTER = (
    "패스키를 등록하지 못했습니다. 다시 시도해 주십시오.",
    "The passkey could not be added. Please try again.",
)
E_DUPLICATE = ("이미 등록된 패스키입니다.", "This passkey is already registered.")
E_REFUSED = ("이 패스키로는 로그인할 수 없습니다.", "This passkey cannot sign in here.")
E_MISSING = ("없는 패스키입니다.", "Unknown passkey.")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _file() -> Path:
    return config.DATA_DIR / "passkeys.json"


def _load() -> list[dict]:
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return (
        [i for i in data if isinstance(i, dict) and i.get("id")]
        if isinstance(data, list)
        else []
    )


def _save(items: list[dict]) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(items, handle)
    os.replace(tmp, path)


def site(origin: str | None, host: str | None) -> tuple[str, str]:
    """이 요청의 (RP ID, 기대하는 origin).

    Origin 헤더는 브라우저가 패스키 응답에 서명해 넣는 값이고, AuthMiddleware 가 이미 이 사이트인지 확인했다.
    RP ID 는 포트를 뺀 호스트 이름이다.
    """
    parts = urlsplit(origin or "")
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise PasskeyError(*E_ADDRESS)
    if (host or "").rsplit(":", 1)[0].strip(
        "[]"
    ).lower() != parts.hostname.lower() and (
        host or ""
    ).lower() != parts.hostname.lower():
        raise PasskeyError(*E_ADDRESS)
    rp_id = parts.hostname.lower()
    # 브라우저는 https, 또는 localhost 의 http 에서만 패스키를 허용한다. IP 주소는 RP ID 가 될 수 없다.
    if parts.scheme == "http" and rp_id != "localhost":
        raise PasskeyError(*E_HTTPS)
    return rp_id, f"{parts.scheme}://{parts.netloc}"


def public_list(rp_id: str | None = None) -> list[dict]:
    """환경설정 화면에 보여줄 내용: 이름, 날짜, 이 주소의 것인지 (키는 내보내지 않는다)."""
    return [
        {
            "id": item["id"][:16],
            "name": item.get("name") or "",
            "created": item.get("created"),
            "last_used": item.get("last_used"),
            "here": rp_id is None or item.get("rp_id") == rp_id,
            "synced": bool(item.get("backed_up")),
        }
        for item in _load()
    ]


def any_registered() -> bool:
    return bool(_load())


_pending: dict[str, tuple[bytes, float, str]] = {}


def _challenge(kind: str, challenge: bytes) -> str:
    ticket = secrets.token_urlsafe(24)
    now = time.time()
    with _lock:
        for old in [
            t for t, (_c, at, _k) in _pending.items() if now - at > CHALLENGE_SECONDS
        ]:
            del _pending[old]
        if len(_pending) > 2000:  # 로그인 화면을 열어만 두고 떠난 경우가 많을 때
            _pending.clear()
        _pending[ticket] = (challenge, now, kind)
    return ticket


def _take_challenge(kind: str, ticket: str) -> bytes:
    """챌린지는 한 번만 쓴다: 꺼내면 지워진다."""
    with _lock:
        saved = _pending.pop(ticket, None) if isinstance(ticket, str) else None
    if saved is None or saved[2] != kind or time.time() - saved[1] > CHALLENGE_SECONDS:
        raise PasskeyError(*E_EXPIRED)
    return saved[0]


# ---------------------------------------------------------------- 등록 (로그인한 상태에서, 환경설정)
def register_options(rp_id: str, username: str) -> dict:
    items = _load()
    if len(items) >= MAX_PASSKEYS:
        raise PasskeyError(*E_FULL)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name="vLLM Manager",
        user_name=username,
        user_id=f"vllm-manager:{username}".encode(),
        user_display_name=username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # 기기에 저장되는 패스키: 로그인할 때 아이디를 입력하지 않아도 된다
            resident_key=ResidentKeyRequirement.REQUIRED,
            # 기기가 본인을 확인해야 한다(생체 인증 또는 PIN)
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=_unb64(item["id"]))
            for item in items
            if item.get("rp_id") == rp_id
        ],
    )
    return {
        "ticket": _challenge("register", options.challenge),
        "options": json.loads(options_to_json(options)),
    }


def register_verify(
    ticket: str, rp_id: str, origin: str, credential: dict, name: str
) -> dict:
    challenge = _take_challenge("register", ticket)
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )
    except Exception as error:  # noqa: BLE001 - 형식이 틀린 응답도 모두 같은 거절로 처리한다
        logger.warning("passkey registration rejected: %s", type(error).__name__)
        raise PasskeyError(*E_REGISTER) from error
    record = {
        "id": _b64(verified.credential_id),
        "public_key": _b64(verified.credential_public_key),
        "sign_count": verified.sign_count,
        "rp_id": rp_id,
        "name": (name or "").strip()[:NAME_MAX] or "Passkey",
        "created": time.time(),
        "last_used": None,
        "backed_up": bool(getattr(verified, "credential_backed_up", False)),
    }
    with _lock:
        items = _load()
        if any(item["id"] == record["id"] for item in items):
            raise PasskeyError(*E_DUPLICATE)
        _save([*items, record])
    return public_list(rp_id)[-1]


def rename(short_id: str, name: str) -> None:
    with _lock:
        items = _load()
        for item in items:
            if item["id"][:16] == short_id:
                item["name"] = (
                    (name or "").strip()[:NAME_MAX] or item.get("name") or "Passkey"
                )
                _save(items)
                return
    raise PasskeyError(*E_MISSING)


def remove(short_id: str) -> None:
    with _lock:
        items = _load()
        kept = [item for item in items if item["id"][:16] != short_id]
        if len(kept) == len(items):
            raise PasskeyError(*E_MISSING)
        _save(kept)


# ---------------------------------------------------------------- 로그인 (아직 로그인하지 않은 상태)
def login_options(rp_id: str) -> dict:
    options = generate_authentication_options(
        rp_id=rp_id,
        # 허용 목록 없음: 브라우저가 이 사이트용 패스키를 모두 보여준다 (가까운 휴대폰의 것도 QR 코드로)
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return {
        "ticket": _challenge("login", options.challenge),
        "options": json.loads(options_to_json(options)),
    }


def login_verify(ticket: str, rp_id: str, origin: str, credential: dict) -> str:
    """로그인에 쓴 패스키의 이름을 돌려준다. 받아들일 수 없으면 PasskeyError."""
    challenge = _take_challenge("login", ticket)
    credential_id = str((credential or {}).get("id") or "")
    with _lock:
        items = _load()
        record = next(
            (i for i in items if i["id"] == credential_id and i.get("rp_id") == rp_id),
            None,
        )
        if record is None:
            raise PasskeyError(*E_REFUSED)
        try:
            verified = verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=rp_id,
                expected_origin=origin,
                credential_public_key=_unb64(record["public_key"]),
                credential_current_sign_count=int(record.get("sign_count") or 0),
                require_user_verification=True,
            )
        except Exception as error:  # noqa: BLE001
            logger.warning("passkey sign-in rejected: %s", type(error).__name__)
            raise PasskeyError(*E_REFUSED) from error
        record["sign_count"] = verified.new_sign_count
        record["last_used"] = time.time()
        _save(items)
        return str(record.get("name") or "")

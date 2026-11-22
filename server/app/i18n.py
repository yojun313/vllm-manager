"""API 오류 문구의 언어 선택. 화면 문구는 static/js/i18n.js 가 맡고, 서버는 오류 메시지만 두 언어로 낸다."""

from fastapi import HTTPException, Request

LANG_COOKIE = "vllm_lang"


def lang_of(request: Request | None) -> str:
    if request is None:
        return "en"
    lang = request.cookies.get(LANG_COOKIE, "")
    if lang in ("ko", "en"):
        return lang
    return (
        "ko"
        if request.headers.get("accept-language", "").lower().startswith("ko")
        else "en"
    )


def tr(request: Request | None, ko: str, en: str) -> str:
    return ko if lang_of(request) == "ko" else en


def fail(request: Request | None, status: int, ko: str, en: str) -> HTTPException:
    return HTTPException(status, tr(request, ko, en))

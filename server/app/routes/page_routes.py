"""페이지는 껍데기 HTML 만 내려주고, 데이터는 static/js 가 /api 와 /ws 로 채운다."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import config
from app.auth import COOKIE, session_valid
from app.i18n import lang_of
from app.services import passkeys

router = APIRouter()
templates = Jinja2Templates(directory=str(config.SERVICE_DIR / "app" / "templates"))


def _context(request: Request) -> dict:
    return {
        "lang": lang_of(request),
        "version": config.APP_VERSION,
        "demo": config.DEMO,
    }


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", _context(request))


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    if not config.SETUP_MODE:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "setup.html", _context(request))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if config.SETUP_MODE:
        return RedirectResponse("/setup", status_code=303)
    if session_valid(request.cookies.get(COOKIE)):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {**_context(request), "passkey": passkeys.any_registered()},
    )


@router.get("/manifest.webmanifest")
async def manifest():
    return JSONResponse(
        {
            "name": "vLLM Manager",
            "short_name": "vLLM Manager",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0a0d14",
            "theme_color": "#0a0d14",
            "icons": [
                {
                    "src": "/icons/server.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any",
                }
            ],
        },
        media_type="application/manifest+json",
    )

# app/main.py
import os
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from app.auth import AuthMiddleware
from app.routes import api_router

app = FastAPI(title="vLLM Control", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(AuthMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    print(f"[vLLM Control] Exception at {request.url.path}:\n{tb}")
    return JSONResponse(status_code=500, content={"detail": str(exc), "path": request.url.path})


class NoCacheStaticFiles(StaticFiles):
    # 화면 파일을 고치면 새로고침만으로 바로 반영되도록 캐시를 끈다
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []),
                                                  (b"cache-control", b"no-store, must-revalidate")]}
            await send(message)

        await super().__call__(scope, receive, send_wrapper)


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/js", NoCacheStaticFiles(directory=os.path.join(STATIC_DIR, "js")), name="js")
app.mount("/css", NoCacheStaticFiles(directory=os.path.join(STATIC_DIR, "css")), name="css")

app.include_router(api_router)

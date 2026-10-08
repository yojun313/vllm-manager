from fastapi import APIRouter

from .auth_routes import router as auth_router
from .model_routes import router as model_router
from .page_routes import router as page_router
from .ws_routes import router as ws_router

api_router = APIRouter()
api_router.include_router(page_router, tags=["Pages"])
api_router.include_router(auth_router, tags=["Auth"])
api_router.include_router(model_router, tags=["Models"])
api_router.include_router(ws_router, tags=["WebSocket"])

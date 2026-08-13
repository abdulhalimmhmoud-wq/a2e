"""نقطة تشغيل الخادم."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import jobs
from app.api.routes import router
from app.core.config import BASE_DIR, settings
from app.core.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("shaltot")

FRONTEND_DIST = BASE_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info("قاعدة البيانات جاهزة: %s", settings.db_path)

    # المهام اللي كانت شغالة وقت آخر إقفال بتفضل عالقة في القاعدة —
    # بنعلّمها كمتوقفة عشان تقدر تعيد تشغيلها
    stale = jobs.recover_stale_jobs()
    if stale:
        logger.warning("%d مهمة من تشغيلة سابقة اتعلّمت كمتوقفة", stale)

    if not settings.anthropic_api_key:
        logger.warning(
            "مفيش ANTHROPIC_API_KEY — الترجمة الحقيقية مش هتشتغل "
            "(التشغيل التجريبي بـ engine=echo متاح)"
        )
    yield
    jobs.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


# ---------------------------------------------------------------------------
# الواجهة المبنية (لو موجودة)
# ---------------------------------------------------------------------------
if FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """كل المسارات غير الـ API بترجع الواجهة (توجيه من جانب العميل)."""
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

else:

    @app.get("/")
    async def no_frontend():
        return {
            "message": "الخادم شغال، لكن الواجهة لسه مش مبنية.",
            "build": "cd frontend && npm install && npm run build",
            "api_docs": "/docs",
        }

"""Khởi tạo ứng dụng FastAPI.

Chạy:  uvicorn app.main:create_app --factory --reload
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .ai import build_provider
from .channels.base import ChannelHub
from .channels.bot_logic import StudentBot
from .config import Settings, get_settings
from .db import init_engine
from .migrate import upgrade_database
from .utils.timeutil import set_default_timezone
from .web import assignments, assistant, auth, bank, classes, dashboard, grading, public
from .web.deps import LoginRequired, redirect, templates
from .worker import BackgroundWorker

log = logging.getLogger("app")
APP_DIR = Path(__file__).resolve().parent


def _build_channels(settings: Settings, hub: ChannelHub, bot: StudentBot) -> None:
    if settings.telegram_enabled:
        from .channels.telegram import TelegramAdapter

        hub.register(
            TelegramAdapter(
                settings.telegram_bot_token,
                bot,
                mode=settings.telegram_mode,
                public_base_url=settings.public_base_url,
                webhook_secret=settings.telegram_webhook_secret,
            )
        )
    if settings.zalo_enabled:
        from .channels.zalo import ZaloAdapter

        hub.register(
            ZaloAdapter(
                settings.zalo_bot_token,
                bot,
                mode=settings.zalo_mode,
                public_base_url=settings.public_base_url,
                webhook_secret=settings.zalo_webhook_secret,
                bot_link=settings.zalo_bot_link,
            )
        )


def create_app(settings: Settings | None = None, *, start_background: bool = True) -> FastAPI:
    settings = settings or get_settings()
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    settings.ensure_dirs()
    set_default_timezone(settings.timezone)
    init_engine(settings.resolved_database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_migrate:
            await asyncio.to_thread(upgrade_database, settings)
        worker_task = None
        if start_background:
            _build_channels(settings, app.state.hub, app.state.bot)
            await app.state.hub.start_all()
            if settings.worker_enabled:
                worker = BackgroundWorker(settings, app.state.ai, app.state.hub)
                worker_task = asyncio.create_task(worker.run(), name="background-worker")
        log.info(
            "%s v%s sẵn sàng – AI: %s – kênh chat: %s",
            settings.app_name,
            __version__,
            app.state.ai.name,
            ", ".join(app.state.hub.adapters) or "chưa bật",
        )
        yield
        if worker_task:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
        await app.state.hub.stop_all()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.ai = build_provider(settings)
    app.state.hub = ChannelHub()
    app.state.bot = StudentBot(settings)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.get_secret_key(),
        session_cookie="troly_session",
        max_age=14 * 24 * 3600,
        same_site="lax",
    )
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    for module in (public, auth, dashboard, classes, bank, assignments, grading, assistant):
        app.include_router(module.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Chưa đăng nhập."}, status_code=401)
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return redirect(f"/login?next={quote(target)}")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        wants_json = request.url.path.startswith(("/api/", "/webhooks/")) or "application/json" in request.headers.get(
            "accept", ""
        )
        if wants_json:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return templates.TemplateResponse(
            request,
            "error.html",
            {"status": exc.status_code, "detail": exc.detail, "app_name": settings.app_name},
            status_code=exc.status_code,
        )

    return app

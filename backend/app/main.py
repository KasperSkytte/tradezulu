"""TradeZulu application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .routers import accounts, agent, auth, imports, mt5, stats, trades
from .routers import settings as settings_router
from .services.copier.service import CopierLoop

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("tradezulu")


copier_loop: CopierLoop | None = None


def _bridge_url() -> str:
    """The bridge URL, read fresh each pass so a settings change takes hold."""
    from .db import SessionLocal
    from .services.appsettings import get_app_settings

    with SessionLocal() as db:
        return str(get_app_settings(db)["mt5"].get("bridge_url", "")).strip()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if settings.secret_key_is_ephemeral:
        log.warning(
            "TZ_SECRET_KEY is not set - a random key was generated, so everyone "
            "will be logged out on restart. Set it in your .env file."
        )
    if not settings.ingest_token:
        log.warning(
            "TZ_INGEST_TOKEN is not set - the MetaTrader 5 Expert Advisor will not "
            "be able to push deals until it is."
        )
    if settings.demo_mode:
        from .demo import seed_demo_data

        seed_demo_data()
    # The copier only does work when a slave is enabled, so starting it
    # unconditionally costs a sleeping thread and nothing else.
    global copier_loop
    copier_loop = CopierLoop(_bridge_url, settings.bridge_token)
    copier_loop.start()

    log.info("TradeZulu %s ready (data dir: %s)", settings.version, settings.data_dir)
    yield
    if copier_loop is not None:
        copier_loop.stop()


app = FastAPI(
    title="TradeZulu",
    version=settings.version,
    description="A private trading journal for MetaTrader 5.",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    return response


api = APIRouter(prefix="/api")
api.include_router(auth.router)
api.include_router(accounts.router)
api.include_router(agent.router)
api.include_router(trades.router)
api.include_router(stats.router)
api.include_router(mt5.router)
api.include_router(imports.router)
api.include_router(settings_router.router)


@api.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.version, "app": settings.app_name}


app.include_router(api)


# --- static frontend --------------------------------------------------------

if settings.static_dir and settings.static_dir.is_dir():
    static_dir: Path = settings.static_dir
    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """Serve real files when they exist, otherwise hand back the SPA shell."""
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        candidate = (static_dir / full_path).resolve()
        if full_path and candidate.is_file() and static_dir in candidate.parents:
            headers = (
                {"Cache-Control": "no-cache"}
                if candidate.name in {"sw.js", "manifest.webmanifest", "index.html"}
                else {}
            )
            return FileResponse(candidate, headers=headers)

        index = static_dir / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse({"detail": "Frontend has not been built"}, status_code=404)

else:  # pragma: no cover - development convenience

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "app": settings.app_name,
            "version": settings.version,
            "docs": "/api/docs",
            "note": "No frontend build found. Set TZ_STATIC_DIR or run the Vite dev server.",
        }

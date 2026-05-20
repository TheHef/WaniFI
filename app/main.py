"""WaniFi — UniFi WAN failover monitor with Docker / host-command automation."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import is_setup_done, require_auth_redirect
from .config import APP_VERSION, log
from .db import init_db
from .routes import auth as auth_routes
from .routes import agents as agent_routes
from .routes import backup as backup_routes
from .routes import downloaders as downloader_routes
from .routes import events as events_routes
from .routes import homelab as homelab_routes
from .routes import infra as infra_routes
from .routes import network as network_routes
from .routes import integrations as integrations_routes
from .routes import manual as manual_routes
from .routes import notify as notify_routes
from .routes import notify_channels as notify_channel_routes
from .routes import emby as emby_routes
from .routes import jellyfin as jellyfin_routes
from .routes import plex as plex_routes
from .routes import qbittorrent as qb_routes
from .routes import rules as rules_routes
from .routes import openwrt as openwrt_routes
from .routes import settings as settings_routes
from .routes import stats as stats_routes
from .routes import system as system_routes
from .watcher import live_stats_loop, state, watcher_loop

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    log.info("WaniFi v%s starting", APP_VERSION)
    if not is_setup_done():
        log.warning("Admin password not set — visit /setup to initialise")
    state.task      = asyncio.create_task(watcher_loop())
    state.live_task = asyncio.create_task(live_stats_loop())
    yield
    for t in (state.task, state.live_task):
        if t:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass


app = FastAPI(lifespan=lifespan, title="WaniFi", version=APP_VERSION, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "0"
    return response

auth_routes.init(templates)

app.include_router(agent_routes.router)
app.include_router(auth_routes.router)
app.include_router(system_routes.router)
app.include_router(rules_routes.router)
app.include_router(openwrt_routes.router)
app.include_router(settings_routes.router)
app.include_router(events_routes.router)
app.include_router(manual_routes.router)
app.include_router(notify_routes.router)
app.include_router(notify_routes.test_router)
app.include_router(notify_channel_routes.router)
app.include_router(qb_routes.router)
app.include_router(qb_routes.test_router)
app.include_router(downloader_routes.router)
app.include_router(emby_routes.router)
app.include_router(emby_routes.test_router)
app.include_router(jellyfin_routes.router)
app.include_router(jellyfin_routes.test_router)
app.include_router(plex_routes.router)
app.include_router(plex_routes.test_router)
app.include_router(homelab_routes.router)
app.include_router(infra_routes.router)
app.include_router(network_routes.router)
app.include_router(integrations_routes.router)
app.include_router(stats_routes.router)
app.include_router(backup_routes.router)


def _shell(request: Request):
    redirect = require_auth_redirect(request)
    if redirect:
        return redirect
    resp = templates.TemplateResponse(
        "app.html",
        {"request": request, "version": APP_VERSION},
    )
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return _shell(request)


@app.get("/overview",      response_class=HTMLResponse)
@app.get("/rules",         response_class=HTMLResponse)
@app.get("/settings",      response_class=HTMLResponse)
@app.get("/events",        response_class=HTMLResponse)
@app.get("/notifications", response_class=HTMLResponse)
async def spa_pages(request: Request):
    return _shell(request)

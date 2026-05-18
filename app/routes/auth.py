"""Authentication routes: setup wizard, login, logout."""
import time
from collections import defaultdict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth import (
    create_session,
    destroy_session,
    is_session_valid,
    is_setup_done,
    set_admin_password,
    verify_admin_password,
)
from ..config import APP_VERSION, SESSION_MAX_AGE
from ..models import SetupIn

router = APIRouter()
_templates: Jinja2Templates | None = None

_LOGIN_WINDOW  = 300   # seconds
_LOGIN_LIMIT   = 10    # max attempts per window
_login_attempts: dict[str, list[float]] = defaultdict(list)


def init(templates: Jinja2Templates):
    global _templates
    _templates = templates


def _set_cookie(resp, token: str, request: Request):
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(
        "session", token,
        httponly=True, samesite="lax", secure=secure,
        max_age=SESSION_MAX_AGE, path="/",
    )


def _rate_limited(ip: str) -> bool:
    now = time.time()
    attempts = _login_attempts[ip]
    _login_attempts[ip] = [t for t in attempts if now - t < _LOGIN_WINDOW]
    if len(_login_attempts[ip]) >= _LOGIN_LIMIT:
        return True
    _login_attempts[ip].append(now)
    return False


@router.get("/setup")
async def setup_page(request: Request):
    if is_setup_done():
        return RedirectResponse("/login", status_code=302)
    return _templates.TemplateResponse("setup.html", {"request": request, "version": APP_VERSION})


@router.post("/setup")
async def setup_submit(payload: SetupIn, request: Request):
    if is_setup_done():
        return JSONResponse({"ok": False, "error": "Setup already completed"}, status_code=400)
    set_admin_password(payload.password)
    token = create_session()
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, token, request)
    return resp


@router.get("/login")
async def login_page(request: Request):
    if not is_setup_done():
        return RedirectResponse("/setup", status_code=302)
    if is_session_valid(request.cookies.get("session")):
        return RedirectResponse("/", status_code=302)
    return _templates.TemplateResponse("login.html", {"request": request, "version": APP_VERSION})


@router.post("/login")
async def login_submit(request: Request):
    if not is_setup_done():
        return JSONResponse({"ok": False, "error": "Not set up"}, status_code=400)
    ip = request.client.host if request.client else "unknown"
    if _rate_limited(ip):
        return JSONResponse({"ok": False, "error": "Too many attempts — try again later"}, status_code=429)
    form = await request.form()
    password = form.get("password", "")
    if not verify_admin_password(password):
        return JSONResponse({"ok": False, "error": "Invalid password"}, status_code=401)
    _login_attempts.pop(ip, None)
    token = create_session()
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, token, request)
    return resp


@router.post("/logout")
async def logout(request: Request):
    destroy_session(request.cookies.get("session"))
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("session", path="/")
    return resp

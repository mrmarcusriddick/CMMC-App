"""Single-operator local access gate; replace with organizational SSO for shared use."""
import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import get_settings

router = APIRouter()
COOKIE_NAME = "cmmc_session"
SESSION_SECONDS = 3600


def configured() -> bool:
    settings = get_settings()
    return bool(settings.app_username and len(settings.app_password) >= 24)


def signature(value: str) -> str:
    return hmac.new(get_settings().app_password.encode(), f"cmmc-session:{value}".encode(), hashlib.sha256).hexdigest()


def valid_session(token: str) -> bool:
    try:
        expires, nonce, supplied_signature = token.split(".")
        return (configured() and int(expires) > time.time()
                and hmac.compare_digest(signature(f"{expires}.{nonce}"), supplied_signature))
    except (ValueError, TypeError):
        return False


async def protect_api(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        # Browser writes must originate from this app, including login and logout.
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
            if origin != f"{request.url.scheme}://{request.url.netloc}":
                return JSONResponse({"detail": "Cross-origin writes are not allowed."}, status_code=403)
        login = request.url.path == "/api/session" and request.method == "POST"
        if not login and not valid_session(request.cookies.get(COOKIE_NAME, "")):
            return JSONResponse({"detail": "Sign in to access local records."}, status_code=401,
                                headers={"Cache-Control": "no-store"})
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class LoginRequest(BaseModel):
    username: str = Field(max_length=240)
    password: str = Field(max_length=1024)


@router.post("/api/session")
def login(body: LoginRequest, response: Response):
    if not configured():
        raise HTTPException(503, "Local sign-in has not been configured.")
    settings = get_settings()
    username_matches = hmac.compare_digest(body.username.encode(), settings.app_username.encode())
    password_matches = hmac.compare_digest(body.password.encode(), settings.app_password.encode())
    if not (username_matches and password_matches):
        raise HTTPException(401, "Username or password is incorrect.")
    value = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_hex(16)}"
    response.set_cookie(COOKIE_NAME, f"{value}.{signature(value)}", max_age=SESSION_SECONDS,
                        httponly=True, secure=settings.session_cookie_secure, samesite="strict", path="/api")
    return {"username": settings.app_username}


@router.get("/api/session")
def session_status():
    return {"username": get_settings().app_username}


@router.delete("/api/session")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/api", httponly=True, samesite="strict",
                           secure=get_settings().session_cookie_secure)
    return {"signedOut": True}

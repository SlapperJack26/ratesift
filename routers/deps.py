"""Shared authentication, cookie, and template dependencies for routers."""
import os
import re
from typing import Dict, List, Optional, Tuple
from fastapi import HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from services.auth_service import validate_session_token

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

SESSION_COOKIE_NAMES = ("quotelytics_session",)

_TEMPLATE_CACHE: Dict[str, Tuple[Tuple[float, ...], str]] = {}
_INCLUDE_PATTERN = re.compile(r'\{%\s*include\s+[\'"]([^\'"]+)[\'"]\s*%\}')


def should_set_secure_cookie(request: Optional[Request] = None) -> bool:
    """Enforces Secure flag on HTTPS requests or when APP_ENV=production / COOKIE_SECURE=true."""
    if os.getenv("APP_ENV", "").lower() == "production" or os.getenv("COOKIE_SECURE", "").lower() in ("1", "true", "yes"):
        return True
    if request is not None:
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https":
            return True
    return False


def set_session_cookies(response: Response, token: str, request: Optional[Request] = None) -> None:
    """Set HttpOnly session cookies on the response."""
    secure_flag = should_set_secure_cookie(request)
    for cookie_key in SESSION_COOKIE_NAMES:
        response.set_cookie(
            key=cookie_key,
            value=token,
            max_age=30 * 86400,
            httponly=True,
            samesite="lax",
            secure=secure_flag,
        )


def clear_session_cookies(response: Response) -> None:
    """Delete session cookies from the response."""
    for cookie_key in SESSION_COOKIE_NAMES:
        response.delete_cookie(key=cookie_key)


def get_current_user_from_request(request: Request) -> Optional[dict]:
    """Helper to extract user from session cookie or Authorization header."""
    token = request.cookies.get("quotelytics_session")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    return validate_session_token(token)


def require_user(request: Request) -> dict:
    """Requires a valid authenticated user session; raises 401 if unauthenticated."""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def ensure_dev_or_admin(request: Request) -> None:
    """Disables internal architecture/debug views in production unless accessed by an ADMIN."""
    if os.getenv("APP_ENV", "").lower() == "production":
        user = get_current_user_from_request(request)
        if not user or user.get("role") != "ADMIN":
            raise HTTPException(status_code=404, detail="Page not found.")


def serve_template(template_rel_path: str) -> HTMLResponse:
    """Serve an HTML template with component includes, cached by file mtimes."""
    full_path = os.path.join(TEMPLATES_DIR, template_rel_path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail=f"Template {template_rel_path} not found")

    main_mtime = os.path.getmtime(full_path)
    cached = _TEMPLATE_CACHE.get(template_rel_path)
    if cached is not None:
        cached_mtimes, cached_content = cached
        if cached_mtimes[0] == main_mtime and len(cached_mtimes) == 1:
            return HTMLResponse(content=cached_content)

    with open(full_path, "r", encoding="utf-8") as f:
        raw_content = f.read()

    include_mtimes: List[float] = [main_mtime]

    def _include_replacer(match):
        inc_rel = match.group(1).strip()
        inc_full = os.path.join(TEMPLATES_DIR, inc_rel)
        if os.path.exists(inc_full):
            include_mtimes.append(os.path.getmtime(inc_full))
            with open(inc_full, "r", encoding="utf-8") as inc_f:
                return inc_f.read()
        return ""

    content = _INCLUDE_PATTERN.sub(_include_replacer, raw_content)
    mtimes_tuple = tuple(include_mtimes)
    if cached is not None and cached[0] == mtimes_tuple:
        return HTMLResponse(content=cached[1])
    _TEMPLATE_CACHE[template_rel_path] = (mtimes_tuple, content)
    return HTMLResponse(content=content)

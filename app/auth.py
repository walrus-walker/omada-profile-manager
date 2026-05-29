import hashlib
import secrets
from fastapi import Request
from fastapi.responses import RedirectResponse


def _hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()


def verify_pin(submitted: str, stored: str) -> bool:
    """Compare submitted PIN against stored PIN using constant-time comparison."""
    return secrets.compare_digest(_hash_pin(submitted), _hash_pin(stored))


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


def require_auth(request: Request):
    """Return a redirect response if the request is not authenticated, else None."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=302)
    return None


def add_flash(request: Request, message: str, category: str = "info"):
    """Add a flash message to the session."""
    msgs = list(request.session.get("_flash", []))
    msgs.append({"message": message, "category": category})
    request.session["_flash"] = msgs


def pop_flash(request: Request) -> list:
    """Retrieve and clear all pending flash messages."""
    msgs = list(request.session.get("_flash", []))
    request.session["_flash"] = []
    return msgs

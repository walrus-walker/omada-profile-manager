from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app import auth, database
from app.templates_instance import templates

router = APIRouter()


@router.get("/")
def index(request: Request):
    if not auth.is_authenticated(request):
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/dashboard")
def dashboard(request: Request):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    profiles = database.get_all_profiles()
    assigned = database.get_all_profile_devices()
    clients = database.get_cached_clients()
    history = database.get_recent_history(limit=10)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "flash_messages": auth.pop_flash(request),
            "profile_count": len(profiles),
            "assigned_count": len(assigned),
            "client_count": len(clients),
            "history": history,
            "has_clients": len(clients) > 0,
        },
    )

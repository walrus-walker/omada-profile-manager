from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import auth, database
from app.config import get_settings
from app.templates_instance import templates

TIMEZONE_OPTIONS = [
    ("United States", [
        ("America/New_York",    "Eastern — New York, Miami, Atlanta"),
        ("America/Chicago",     "Central — Chicago, Dallas, Houston"),
        ("America/Denver",      "Mountain — Denver, Phoenix, Salt Lake City"),
        ("America/Los_Angeles", "Pacific — Los Angeles, Seattle, Las Vegas"),
        ("America/Anchorage",   "Alaska — Anchorage"),
        ("Pacific/Honolulu",    "Hawaii — Honolulu"),
    ]),
    ("Canada", [
        ("America/Toronto",   "Eastern — Toronto, Ottawa"),
        ("America/Winnipeg",  "Central — Winnipeg"),
        ("America/Edmonton",  "Mountain — Edmonton, Calgary"),
        ("America/Vancouver", "Pacific — Vancouver"),
    ]),
    ("Europe", [
        ("Europe/London",   "GMT/BST — London, Dublin"),
        ("Europe/Paris",    "CET — Paris, Brussels, Amsterdam"),
        ("Europe/Berlin",   "CET — Berlin, Vienna, Zurich"),
        ("Europe/Rome",     "CET — Rome, Madrid, Warsaw"),
        ("Europe/Helsinki", "EET — Helsinki, Kyiv, Bucharest"),
        ("Europe/Moscow",   "MSK — Moscow"),
    ]),
    ("Asia / Pacific", [
        ("Asia/Dubai",      "GST — Dubai, Abu Dhabi"),
        ("Asia/Kolkata",    "IST — India"),
        ("Asia/Bangkok",    "ICT — Bangkok, Hanoi, Jakarta"),
        ("Asia/Shanghai",   "CST — China, Hong Kong, Singapore"),
        ("Asia/Tokyo",      "JST — Japan, South Korea"),
        ("Australia/Sydney",   "AEST — Sydney, Melbourne"),
        ("Pacific/Auckland",   "NZST — New Zealand"),
    ]),
    ("Other", [
        ("UTC", "UTC — Coordinated Universal Time"),
    ]),
]

router = APIRouter(prefix="/settings")


@router.get("")
def settings_page(request: Request):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    s = get_settings()

    # Only expose safe config values — never show secrets
    safe_config = {
        "OMADA_BASE_URL": s.OMADA_BASE_URL,
        "OMADA_CONTROLLER_ID": s.OMADA_CONTROLLER_ID,
        "OMADA_SITE_ID": s.OMADA_SITE_ID,
        "OMADA_VERIFY_SSL": s.OMADA_VERIFY_SSL,
        "APP_PORT": s.APP_PORT,
        "DATABASE_PATH": s.DATABASE_PATH,
    }

    missing_vars = []
    if not s.OMADA_BASE_URL:
        missing_vars.append("OMADA_BASE_URL")
    if not s.OMADA_CLIENT_ID:
        missing_vars.append("OMADA_CLIENT_ID")
    if not s.OMADA_CLIENT_SECRET:
        missing_vars.append("OMADA_CLIENT_SECRET")
    if not s.OMADA_SITE_ID:
        missing_vars.append("OMADA_SITE_ID")

    current_timezone = database.get_app_timezone()

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "flash_messages": auth.pop_flash(request),
            "safe_config": safe_config,
            "missing_vars": missing_vars,
            "timezone_options": TIMEZONE_OPTIONS,
            "current_timezone": current_timezone,
        },
    )


@router.post("/timezone")
def save_timezone(request: Request, timezone: str = Form(...)):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    tz = timezone.strip()
    if tz:
        database.set_app_setting("timezone", tz)
        auth.add_flash(request, f"Timezone set to {tz}.", "success")
    else:
        auth.add_flash(request, "No timezone selected.", "error")

    return RedirectResponse(url="/settings", status_code=302)


@router.post("/dark_mode")
def save_dark_mode(request: Request, enabled: str = Form("")):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    database.set_app_setting("dark_mode", "1" if enabled == "on" else "0")
    return RedirectResponse(url="/settings", status_code=302)

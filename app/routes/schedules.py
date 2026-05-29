"""
schedules.py

Endpoints for:
  - Pause timers  (profile and device)
  - Cancel timers (profile and device)
  - Profile recurring schedules (save, toggle)
"""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import auth, database
from app.config import get_settings
from app.omada_client import OmadaClient, OmadaAPIError

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _app_tz():
    try:
        return ZoneInfo(database.get_app_timezone())
    except (ZoneInfoNotFoundError, Exception):
        return timezone.utc


def _parse_until_time(until_time: str) -> datetime:
    """
    Parse HH:MM from the <input type="time"> into a UTC datetime for today
    in the app timezone. Raises ValueError if the time is already past.
    """
    tz = _app_tz()
    now_local = datetime.now(timezone.utc).astimezone(tz)
    h, m = map(int, until_time.split(":"))
    target = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now_local:
        raise ValueError(f"Time {until_time} has already passed today.")
    return target.astimezone(timezone.utc)


def _block_target(target_type: str, target_id: str):
    """Block a profile or device immediately. Returns (success, error_str)."""
    settings = get_settings()
    omada = OmadaClient()
    try:
        if target_type == "profile":
            devices = database.get_profile_devices(int(target_id))
            for dev in devices:
                omada.block_client(settings.OMADA_SITE_ID, dev.mac)
                database.update_client_blocked(dev.mac, True)
        else:
            omada.block_client(settings.OMADA_SITE_ID, target_id)
            database.update_client_blocked(target_id, True)
        return True, ""
    except NotImplementedError:
        return False, "Block endpoint not yet confirmed — see app/omada_client.py."
    except OmadaAPIError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)


def _resume_target(target_type: str, target_id: str):
    """Unblock a profile or device immediately. Returns (success, error_str)."""
    settings = get_settings()
    omada = OmadaClient()
    try:
        if target_type == "profile":
            devices = database.get_profile_devices(int(target_id))
            for dev in devices:
                omada.unblock_client(settings.OMADA_SITE_ID, dev.mac)
                database.update_client_blocked(dev.mac, False)
        else:
            omada.unblock_client(settings.OMADA_SITE_ID, target_id)
            database.update_client_blocked(target_id, False)
        return True, ""
    except NotImplementedError:
        return False, "Unblock endpoint not yet confirmed — see app/omada_client.py."
    except OmadaAPIError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Profile timer endpoints
# ---------------------------------------------------------------------------

@router.post("/profiles/{profile_id}/pause_timer")
def profile_pause_timer(
    profile_id: int,
    request: Request,
    duration_minutes: int = Form(0),
    until_time: str = Form(""),
):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    profile = database.get_profile(profile_id)
    if not profile:
        auth.add_flash(request, "Profile not found.", "error")
        return RedirectResponse(url="/profiles", status_code=302)

    # Determine run_at
    run_at_utc: datetime | None = None
    if until_time:
        try:
            run_at_utc = _parse_until_time(until_time)
        except ValueError as exc:
            auth.add_flash(request, str(exc), "error")
            return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)
    elif duration_minutes > 0:
        run_at_utc = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
    else:
        auth.add_flash(request, "No timer duration specified.", "error")
        return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)

    # Cancel any existing pending timer for this profile
    database.cancel_scheduled_actions("profile", str(profile_id))

    # Block immediately
    success, error = _block_target("profile", str(profile_id))
    if not success:
        auth.add_flash(request, f"Pause failed: {error}", "error")
        return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)

    database.log_action("block", "profile", str(profile_id), "success", "Timer pause")

    # Schedule the resume
    database.create_scheduled_action(
        "profile", str(profile_id), "resume", run_at_utc.isoformat()
    )

    from app.worker import format_run_at
    until_str = format_run_at(run_at_utc.isoformat(), database.get_app_timezone())
    auth.add_flash(
        request,
        f'Profile "{profile.name}" paused until {until_str}.',
        "success",
    )
    return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)


@router.post("/profiles/{profile_id}/cancel_timer")
def profile_cancel_timer(profile_id: int, request: Request):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    database.cancel_scheduled_actions("profile", str(profile_id))
    success, error = _resume_target("profile", str(profile_id))
    if success:
        auth.add_flash(request, "Timer cancelled — devices resumed.", "success")
    else:
        auth.add_flash(request, f"Timer cancelled, but resume failed: {error}", "warning")
    return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)


# ---------------------------------------------------------------------------
# Device timer endpoints
# ---------------------------------------------------------------------------

@router.post("/devices/{mac}/pause_timer")
def device_pause_timer(
    mac: str,
    request: Request,
    duration_minutes: int = Form(0),
    until_time: str = Form(""),
):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    mac = mac.lower().strip()

    run_at_utc: datetime | None = None
    if until_time:
        try:
            run_at_utc = _parse_until_time(until_time)
        except ValueError as exc:
            auth.add_flash(request, str(exc), "error")
            return RedirectResponse(url="/devices", status_code=302)
    elif duration_minutes > 0:
        run_at_utc = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
    else:
        auth.add_flash(request, "No timer duration specified.", "error")
        return RedirectResponse(url="/devices", status_code=302)

    # Cancel any existing pending timer
    database.cancel_scheduled_actions("device", mac)

    # Block immediately
    success, error = _block_target("device", mac)
    if not success:
        auth.add_flash(request, f"Pause failed: {error}", "error")
        return RedirectResponse(url="/devices", status_code=302)

    database.log_action("block", "device", mac, "success", "Timer pause")

    # Schedule the resume
    database.create_scheduled_action("device", mac, "resume", run_at_utc.isoformat())

    from app.worker import format_run_at
    until_str = format_run_at(run_at_utc.isoformat(), database.get_app_timezone())
    auth.add_flash(request, f"Device paused until {until_str}.", "success")
    return RedirectResponse(url="/devices", status_code=302)


@router.post("/devices/{mac}/cancel_timer")
def device_cancel_timer(mac: str, request: Request, back_url: str = Form("")):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    mac = mac.lower().strip()
    database.cancel_scheduled_actions("device", mac)
    success, error = _resume_target("device", mac)
    if success:
        auth.add_flash(request, "Timer cancelled — device resumed.", "success")
    else:
        auth.add_flash(request, f"Timer cancelled, but resume failed: {error}", "warning")

    dest = back_url if back_url.startswith("/") else "/devices"
    return RedirectResponse(url=dest, status_code=302)


# ---------------------------------------------------------------------------
# Profile schedule endpoints
# ---------------------------------------------------------------------------

@router.post("/profiles/{profile_id}/schedule/save")
def save_profile_schedule(
    profile_id: int,
    request: Request,
    name: str = Form(""),
    enabled: str = Form("off"),
    days_of_week: list[str] = Form(default=[]),
    pause_time: str = Form(""),
    resume_time: str = Form(""),
    timezone_name: str = Form(""),
):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    profile = database.get_profile(profile_id)
    if not profile:
        auth.add_flash(request, "Profile not found.", "error")
        return RedirectResponse(url="/profiles", status_code=302)

    tz = timezone_name.strip() or database.get_app_timezone()
    days_str = ",".join(sorted(set(days_of_week)))
    is_enabled = enabled.lower() in ("on", "1", "true", "yes")

    database.upsert_profile_schedule(
        profile_id=profile_id,
        name=name.strip(),
        enabled=is_enabled,
        days_of_week=days_str,
        pause_time=pause_time.strip(),
        resume_time=resume_time.strip(),
        timezone=tz,
    )

    status = "enabled" if is_enabled else "saved (disabled)"
    auth.add_flash(request, f'Schedule {status} for "{profile.name}".', "success")
    return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)


@router.post("/profiles/{profile_id}/schedule/toggle")
def toggle_profile_schedule(profile_id: int, request: Request):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    sched = database.get_profile_schedule(profile_id)
    if not sched:
        auth.add_flash(request, "No schedule configured yet.", "warning")
        return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)

    new_state = not sched.enabled
    database.set_schedule_enabled(profile_id, new_state)
    state_str = "enabled" if new_state else "disabled"
    auth.add_flash(request, f"Schedule {state_str}.", "success")
    return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)

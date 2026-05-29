from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import auth, database
from app.config import get_settings
from app.omada_client import OmadaClient, OmadaAPIError
from app.templates_instance import templates

router = APIRouter(prefix="/profiles")


@router.get("")
def profiles_page(request: Request):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    profiles = database.get_all_profiles()

    from app.worker import next_schedule_description, format_run_at
    _tz = database.get_app_timezone()

    profile_device_counts = {}
    profile_blocked_counts = {}
    profile_timers = {}
    profile_schedules = {}
    profile_next_actions = {}

    for p in profiles:
        devices = database.get_profile_devices(p.id)
        profile_device_counts[p.id] = len(devices)
        blocked = 0
        for d in devices:
            cached = database.get_cached_client(d.mac)
            if cached and cached.blocked:
                blocked += 1
        profile_blocked_counts[p.id] = blocked

        timer = database.get_pending_timer("profile", str(p.id))
        profile_timers[p.id] = timer
        if timer:
            profile_timers[p.id].run_at_local = format_run_at(timer.run_at, _tz)

        sched = database.get_profile_schedule(p.id)
        profile_schedules[p.id] = sched
        profile_next_actions[p.id] = next_schedule_description(sched)

    return templates.TemplateResponse(
        request,
        "profiles.html",
        {
            "flash_messages": auth.pop_flash(request),
            "profiles": profiles,
            "profile_device_counts": profile_device_counts,
            "profile_blocked_counts": profile_blocked_counts,
            "profile_timers": profile_timers,
            "profile_schedules": profile_schedules,
            "profile_next_actions": profile_next_actions,
        },
    )


@router.post("/create")
def create_profile(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    name = name.strip()
    if not name:
        auth.add_flash(request, "Profile name cannot be empty.", "error")
        return RedirectResponse(url="/profiles", status_code=302)

    try:
        database.create_profile(name, description)
        auth.add_flash(request, f'Profile "{name}" created.', "success")
    except Exception as exc:
        auth.add_flash(request, f"Could not create profile: {exc}", "error")

    return RedirectResponse(url="/profiles", status_code=302)


@router.get("/{profile_id}")
def profile_detail(profile_id: int, request: Request):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    profile = database.get_profile(profile_id)
    if not profile:
        auth.add_flash(request, "Profile not found.", "error")
        return RedirectResponse(url="/profiles", status_code=302)

    devices = database.get_profile_devices(profile_id)

    # Enrich with cached Omada data where available
    enriched = []
    for d in devices:
        cached = database.get_cached_client(d.mac)
        enriched.append({
            "profile_device": d,
            "omada": cached,
        })

    from app.worker import next_schedule_description, format_run_at
    _tz = database.get_app_timezone()

    timer = database.get_pending_timer("profile", str(profile_id))
    timer_display = format_run_at(timer.run_at, _tz) if timer else None

    sched = database.get_profile_schedule(profile_id)
    next_action = next_schedule_description(sched)

    # Enrich device timers
    for entry in enriched:
        mac = entry["profile_device"].mac
        dt = database.get_pending_timer("device", mac)
        entry["timer"] = dt
        entry["timer_display"] = format_run_at(dt.run_at, _tz) if dt else None

    return templates.TemplateResponse(
        request,
        "profile_detail.html",
        {
            "flash_messages": auth.pop_flash(request),
            "profile": profile,
            "devices": enriched,
            "timer": timer,
            "timer_display": timer_display,
            "schedule": sched,
            "next_action": next_action,
            "app_timezone": _tz,
        },
    )


@router.post("/{profile_id}/rename")
def rename_profile(
    profile_id: int,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    name = name.strip()
    if not name:
        auth.add_flash(request, "Profile name cannot be empty.", "error")
        return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)

    try:
        database.update_profile(profile_id, name, description)
        auth.add_flash(request, f'Profile renamed to "{name}".', "success")
    except Exception as exc:
        auth.add_flash(request, f"Could not rename profile: {exc}", "error")

    return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)


@router.post("/{profile_id}/delete")
def delete_profile(profile_id: int, request: Request):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    profile = database.get_profile(profile_id)
    name = profile.name if profile else str(profile_id)

    try:
        database.delete_profile(profile_id)
        auth.add_flash(request, f'Profile "{name}" deleted.', "success")
    except Exception as exc:
        auth.add_flash(request, f"Could not delete profile: {exc}", "error")

    return RedirectResponse(url="/profiles", status_code=302)


@router.post("/{profile_id}/remove_device/{mac}")
def remove_device(profile_id: int, mac: str, request: Request):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    try:
        database.remove_device_from_profile(profile_id, mac)
        database.log_action("remove_device", "device", mac, "success",
                             f"Removed from profile {profile_id}")
        auth.add_flash(request, f"Device {mac} removed from profile.", "success")
    except Exception as exc:
        auth.add_flash(request, f"Could not remove device: {exc}", "error")

    return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)


def _block_unblock_profile(profile_id: int, request: Request, action: str):
    """Shared logic for block/unblock all devices in a profile."""
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    profile = database.get_profile(profile_id)
    if not profile:
        auth.add_flash(request, "Profile not found.", "error")
        return RedirectResponse(url="/profiles", status_code=302)

    settings = get_settings()
    omada = OmadaClient()
    devices = database.get_profile_devices(profile_id)

    if not devices:
        auth.add_flash(request, "No devices in this profile.", "warning")
        return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)

    success_count = 0
    error_count = 0
    not_impl = False

    # Cancel any pending profile-level timer
    database.cancel_scheduled_actions("profile", str(profile_id))

    for device in devices:
        # Cancel any per-device timers too
        database.cancel_scheduled_actions("device", device.mac)
        try:
            if action == "block":
                omada.block_client(settings.OMADA_SITE_ID, device.mac)
            else:
                omada.unblock_client(settings.OMADA_SITE_ID, device.mac)
            database.update_client_blocked(device.mac, action == "block")
            database.log_action(action, "device", device.mac, "success",
                                 f"Profile {profile_id}")
            success_count += 1
        except NotImplementedError:
            not_impl = True
            database.log_action(action, "device", device.mac, "not_implemented",
                                 f"Profile {profile_id}")
            break
        except Exception as exc:
            database.log_action(action, "device", device.mac, "error", str(exc))
            error_count += 1

    if not_impl:
        auth.add_flash(
            request,
            f"{action.capitalize()} endpoint not yet confirmed. "
            "See app/omada_client.py TODO comments.",
            "warning",
        )
    elif error_count == 0:
        auth.add_flash(
            request,
            f"{action.capitalize()}ed {success_count} device(s) in profile \"{profile.name}\".",
            "success",
        )
    else:
        auth.add_flash(
            request,
            f"{action.capitalize()}ed {success_count} device(s), {error_count} failed.",
            "warning",
        )

    return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)


@router.post("/{profile_id}/block")
def block_profile(profile_id: int, request: Request):
    return _block_unblock_profile(profile_id, request, "block")


@router.post("/{profile_id}/unblock")
def unblock_profile(profile_id: int, request: Request):
    return _block_unblock_profile(profile_id, request, "unblock")


@router.post("/{profile_id}/devices/{mac}/block")
def block_profile_device(profile_id: int, mac: str, request: Request):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    settings = get_settings()
    omada = OmadaClient()

    database.cancel_scheduled_actions("device", mac)
    try:
        omada.block_client(settings.OMADA_SITE_ID, mac)
        database.update_client_blocked(mac, True)
        database.log_action("block", "device", mac, "success")
        auth.add_flash(request, f"Blocked {mac}.", "success")
    except NotImplementedError:
        auth.add_flash(
            request,
            "Block endpoint not yet confirmed. See app/omada_client.py TODO comments.",
            "warning",
        )
    except Exception as exc:
        auth.add_flash(request, f"Block failed: {exc}", "error")

    return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)


@router.post("/{profile_id}/devices/{mac}/unblock")
def unblock_profile_device(profile_id: int, mac: str, request: Request):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    settings = get_settings()
    omada = OmadaClient()

    database.cancel_scheduled_actions("device", mac)
    try:
        omada.unblock_client(settings.OMADA_SITE_ID, mac)
        database.update_client_blocked(mac, False)
        database.log_action("unblock", "device", mac, "success")
        auth.add_flash(request, f"Unblocked {mac}.", "success")
    except NotImplementedError:
        auth.add_flash(
            request,
            "Unblock endpoint not yet confirmed. See app/omada_client.py TODO comments.",
            "warning",
        )
    except Exception as exc:
        auth.add_flash(request, f"Unblock failed: {exc}", "error")

    return RedirectResponse(url=f"/profiles/{profile_id}", status_code=302)

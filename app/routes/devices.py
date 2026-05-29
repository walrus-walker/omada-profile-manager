from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import auth, database
from app.config import get_settings
from app.omada_client import OmadaClient, OmadaAPIError
from app.templates_instance import templates

router = APIRouter(prefix="/devices")


@router.get("")
def devices_page(request: Request):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    clients = database.get_cached_clients()
    profiles = database.get_all_profiles()
    mac_profile_map = database.get_mac_profile_map()

    profile_lookup = {p.id: p for p in profiles}
    mac_profile_names: dict[str, list[str]] = {
        mac: [profile_lookup[pid].name for pid in pids if pid in profile_lookup]
        for mac, pids in mac_profile_map.items()
    }

    from app.worker import format_run_at
    _tz = database.get_app_timezone()

    device_timers: dict[str, object] = {}
    device_timer_display: dict[str, str] = {}
    for c in clients:
        t = database.get_pending_timer("device", c.mac)
        device_timers[c.mac] = t
        device_timer_display[c.mac] = format_run_at(t.run_at, _tz) if t else ""

    return templates.TemplateResponse(
        request,
        "devices.html",
        {
            "flash_messages": auth.pop_flash(request),
            "clients": clients,
            "profiles": profiles,
            "mac_profile_names": mac_profile_names,
            "device_timers": device_timers,
            "device_timer_display": device_timer_display,
        },
    )


@router.post("/refresh")
def refresh_clients(request: Request):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    settings = get_settings()
    omada = OmadaClient()

    try:
        raw_clients = omada.list_clients(settings.OMADA_SITE_ID)
        normalized = [OmadaClient.normalize_client(c) for c in raw_clients]
        database.upsert_omada_clients(normalized)
        database.log_action("refresh_clients", "site", settings.OMADA_SITE_ID, "success",
                             f"Fetched {len(normalized)} clients from Omada.")
        auth.add_flash(request, f"Refreshed {len(normalized)} clients from Omada.", "success")
    except OmadaAPIError as exc:
        database.log_action("refresh_clients", "site", settings.OMADA_SITE_ID, "error", str(exc))
        auth.add_flash(request, f"Omada API error: {exc}", "error")
    except Exception as exc:
        database.log_action("refresh_clients", "site", settings.OMADA_SITE_ID, "error", str(exc))
        auth.add_flash(request, f"Failed to refresh clients: {exc}", "error")

    return RedirectResponse(url="/devices", status_code=302)


@router.post("/{mac}/block")
def block_device(mac: str, request: Request):
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
        auth.add_flash(request, f"Device {mac} paused.", "success")
    except NotImplementedError:
        database.log_action("block", "device", mac, "not_implemented",
                             "Endpoint not confirmed")
        auth.add_flash(
            request,
            "Pause not available yet — the Omada block endpoint needs confirmation. "
            "See app/omada_client.py for TODO instructions.",
            "warning",
        )
    except OmadaAPIError as exc:
        database.log_action("block", "device", mac, "error", str(exc))
        auth.add_flash(request, f"Pause failed: {exc}", "error")
    except Exception as exc:
        database.log_action("block", "device", mac, "error", str(exc))
        auth.add_flash(request, f"Pause failed: {exc}", "error")

    return RedirectResponse(url="/devices", status_code=302)


@router.post("/{mac}/unblock")
def unblock_device(mac: str, request: Request):
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
        auth.add_flash(request, f"Device {mac} resumed.", "success")
    except NotImplementedError:
        database.log_action("unblock", "device", mac, "not_implemented",
                             "Endpoint not confirmed")
        auth.add_flash(
            request,
            "Resume not available yet — the Omada unblock endpoint needs confirmation. "
            "See app/omada_client.py for TODO instructions.",
            "warning",
        )
    except OmadaAPIError as exc:
        database.log_action("unblock", "device", mac, "error", str(exc))
        auth.add_flash(request, f"Resume failed: {exc}", "error")
    except Exception as exc:
        database.log_action("unblock", "device", mac, "error", str(exc))
        auth.add_flash(request, f"Resume failed: {exc}", "error")

    return RedirectResponse(url="/devices", status_code=302)


@router.post("/{mac}/assign")
def assign_to_profile(
    mac: str,
    request: Request,
    profile_id: int = Form(...),
    local_name: str = Form(""),
):
    redirect = auth.require_auth(request)
    if redirect:
        return redirect

    mac = mac.lower().strip()

    if not local_name:
        cached = database.get_cached_client(mac)
        if cached:
            local_name = cached.name

    try:
        database.add_device_to_profile(profile_id, mac, local_name)
        database.log_action("assign_device", "device", mac, "success",
                             f"Assigned to profile {profile_id}")
        auth.add_flash(request, f"Device {mac} added to profile.", "success")
    except Exception as exc:
        auth.add_flash(request, f"Could not assign device: {exc}", "error")

    return RedirectResponse(url="/devices", status_code=302)

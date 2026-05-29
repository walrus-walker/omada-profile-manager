"""
worker.py

Background thread that fires scheduled actions (pause timers and recurring
profile schedules). Polls the database every 30 seconds.

All state lives in the database so actions survive restarts.
"""

import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import database
from app.config import get_settings

logger = logging.getLogger("omada.worker")


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------

def _execute_block_unblock(action_str: str, target_type: str, target_id: str):
    """
    Execute a block or unblock against Omada.
    Imports omada_client here to avoid circular imports at module load.
    Returns (success: bool, error: str).
    """
    from app.omada_client import OmadaClient
    settings = get_settings()
    omada = OmadaClient()

    try:
        if target_type == "profile":
            profile_id = int(target_id)
            devices = database.get_profile_devices(profile_id)
            for dev in devices:
                if action_str == "resume":
                    omada.unblock_client(settings.OMADA_SITE_ID, dev.mac)
                    database.update_client_blocked(dev.mac, False)
                else:
                    omada.block_client(settings.OMADA_SITE_ID, dev.mac)
                    database.update_client_blocked(dev.mac, True)
        elif target_type == "device":
            if action_str == "resume":
                omada.unblock_client(settings.OMADA_SITE_ID, target_id)
                database.update_client_blocked(target_id, False)
            else:
                omada.block_client(settings.OMADA_SITE_ID, target_id)
                database.update_client_blocked(target_id, True)
        return True, ""
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Scheduled actions (timers)
# ---------------------------------------------------------------------------

def _check_due_actions():
    now_iso = datetime.now(timezone.utc).isoformat()
    due = database.get_due_scheduled_actions(now_iso)

    for action in due:
        logger.info(
            "Worker: executing action id=%s type=%s target=%s action=%s run_at=%s",
            action.id, action.target_type, action.target_id, action.action, action.run_at,
        )
        success, error = _execute_block_unblock(
            action.action, action.target_type, action.target_id
        )
        if success:
            database.complete_scheduled_action(action.id)
            database.log_action(
                f"timer_{action.action}", action.target_type, action.target_id,
                "success", f"Scheduled action id={action.id}",
            )
            logger.info("Worker: completed action id=%s", action.id)
        else:
            database.fail_scheduled_action(action.id, error)
            database.log_action(
                f"timer_{action.action}", action.target_type, action.target_id,
                "error", error[:200],
            )
            logger.error("Worker: failed action id=%s: %s", action.id, error)


# ---------------------------------------------------------------------------
# Recurring schedules
# ---------------------------------------------------------------------------

def _safe_tz(tz_name: str):
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, Exception):
        logger.warning("Worker: unknown timezone %r, falling back to UTC", tz_name)
        return timezone.utc


def _check_recurring_schedules():
    now_utc = datetime.now(timezone.utc)
    schedules = database.get_enabled_schedules()

    for sched in schedules:
        try:
            tz = _safe_tz(sched.timezone)
            now_local = now_utc.astimezone(tz)
            today_str = now_local.strftime("%Y-%m-%d")

            active_days = [
                int(d) for d in sched.days_of_week.split(",") if d.strip().isdigit()
            ]
            if now_local.weekday() not in active_days:
                continue

            # --- Pause ---
            if sched.pause_time:
                try:
                    ph, pm = map(int, sched.pause_time.split(":"))
                    pause_dt = now_local.replace(hour=ph, minute=pm, second=0, microsecond=0)
                    already_ran = (sched.last_pause_run or "").startswith(today_str)
                    if now_local >= pause_dt and not already_ran:
                        logger.info(
                            "Worker: schedule %s firing pause for profile %s",
                            sched.id, sched.profile_id,
                        )
                        _fire_schedule_action(sched, "pause")
                        database.update_schedule_last_run(
                            sched.id, "pause", now_utc.isoformat()
                        )
                except Exception as exc:
                    logger.error("Worker: pause check failed schedule %s: %s", sched.id, exc)

            # --- Resume ---
            if sched.resume_time:
                try:
                    rh, rm = map(int, sched.resume_time.split(":"))
                    resume_dt = now_local.replace(hour=rh, minute=rm, second=0, microsecond=0)
                    already_ran = (sched.last_resume_run or "").startswith(today_str)
                    if now_local >= resume_dt and not already_ran:
                        logger.info(
                            "Worker: schedule %s firing resume for profile %s",
                            sched.id, sched.profile_id,
                        )
                        _fire_schedule_action(sched, "resume")
                        database.update_schedule_last_run(
                            sched.id, "resume", now_utc.isoformat()
                        )
                except Exception as exc:
                    logger.error("Worker: resume check failed schedule %s: %s", sched.id, exc)

        except Exception as exc:
            logger.error("Worker: unexpected error for schedule %s: %s", sched.id, exc)


def _fire_schedule_action(sched, action_type: str):
    from app.omada_client import OmadaClient
    settings = get_settings()
    omada = OmadaClient()
    devices = database.get_profile_devices(sched.profile_id)

    success_count = 0
    error_count = 0
    for dev in devices:
        try:
            if action_type == "resume":
                omada.unblock_client(settings.OMADA_SITE_ID, dev.mac)
                database.update_client_blocked(dev.mac, False)
            else:
                omada.block_client(settings.OMADA_SITE_ID, dev.mac)
                database.update_client_blocked(dev.mac, True)
            success_count += 1
        except Exception as exc:
            logger.error("Worker: schedule action failed for %s: %s", dev.mac, exc)
            error_count += 1

    status = "success" if error_count == 0 else "partial"
    database.log_action(
        f"schedule_{action_type}", "profile", str(sched.profile_id),
        status, f"Schedule {sched.id}: {success_count} ok, {error_count} failed",
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def worker_loop():
    logger.info("Worker: background scheduler started (30s interval)")
    while True:
        try:
            _check_due_actions()
            _check_recurring_schedules()
        except Exception as exc:
            logger.error("Worker: top-level error: %s", exc)
        time.sleep(30)


def start_worker():
    t = threading.Thread(target=worker_loop, daemon=True, name="scheduler-worker")
    t.start()
    logger.info("Worker: scheduler thread launched")


# ---------------------------------------------------------------------------
# Schedule helpers (used by routes for display)
# ---------------------------------------------------------------------------

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def next_schedule_description(sched) -> str:
    """Return human-readable 'next action' string for a schedule, or ''."""
    if not sched or not sched.enabled:
        return ""

    active_days = [
        int(d) for d in sched.days_of_week.split(",") if d.strip().isdigit()
    ]
    if not active_days or (not sched.pause_time and not sched.resume_time):
        return ""

    tz = _safe_tz(sched.timezone)
    now_local = datetime.now(timezone.utc).astimezone(tz)

    for delta in range(8):
        candidate = now_local + timedelta(days=delta)
        if candidate.weekday() not in active_days:
            continue

        for action_label, time_str in [("Pauses", sched.pause_time), ("Resumes", sched.resume_time)]:
            if not time_str:
                continue
            try:
                h, m = map(int, time_str.split(":"))
                action_dt = candidate.replace(hour=h, minute=m, second=0, microsecond=0)
                if action_dt > now_local:
                    t_fmt = action_dt.strftime("%-I:%M %p").lstrip("0") or action_dt.strftime("%I:%M %p")
                    if delta == 0:
                        return f"{action_label} today at {t_fmt}"
                    elif delta == 1:
                        return f"{action_label} tomorrow at {t_fmt}"
                    else:
                        return f"{action_label} {action_dt.strftime('%A')} at {t_fmt}"
            except Exception:
                continue

    return ""


def format_run_at(run_at_iso: str, tz_name: str) -> str:
    """Convert a UTC ISO string to a local time string like '9:30 PM'."""
    try:
        tz = _safe_tz(tz_name)
        dt_utc = datetime.fromisoformat(run_at_iso.replace("Z", "+00:00"))
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        dt_local = dt_utc.astimezone(tz)
        return dt_local.strftime("%-I:%M %p")
    except Exception:
        return run_at_iso[:16]

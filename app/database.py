import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings
from app.models import Profile, ProfileDevice, ActionHistory, OmadaClientRecord, ScheduledAction, ProfileSchedule


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_db():
    settings = get_settings()
    conn = sqlite3.connect(settings.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL UNIQUE,
                description TEXT    NOT NULL DEFAULT '',
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS profile_devices (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                mac         TEXT    NOT NULL,
                local_name  TEXT    NOT NULL DEFAULT '',
                created_at  TEXT    NOT NULL,
                UNIQUE (profile_id, mac)
            );

            CREATE TABLE IF NOT EXISTS action_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                action       TEXT NOT NULL,
                target_type  TEXT NOT NULL,
                target_value TEXT NOT NULL,
                status       TEXT NOT NULL,
                message      TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS omada_clients (
                mac        TEXT PRIMARY KEY,
                name       TEXT NOT NULL DEFAULT '',
                ip         TEXT NOT NULL DEFAULT '',
                online     INTEGER NOT NULL DEFAULT 0,
                blocked    INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scheduled_actions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                target_type TEXT NOT NULL,
                target_id   TEXT NOT NULL,
                action      TEXT NOT NULL,
                run_at      TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                created_at  TEXT NOT NULL,
                executed_at TEXT,
                error       TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS profile_schedules (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id      INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                name            TEXT NOT NULL DEFAULT '',
                enabled         INTEGER NOT NULL DEFAULT 1,
                days_of_week    TEXT NOT NULL DEFAULT '',
                pause_time      TEXT NOT NULL DEFAULT '',
                resume_time     TEXT NOT NULL DEFAULT '',
                timezone        TEXT NOT NULL DEFAULT 'America/Chicago',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                last_pause_run  TEXT,
                last_resume_run TEXT,
                UNIQUE (profile_id)
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );
        """)


# --- Profiles ---

def get_all_profiles() -> list[Profile]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM profiles ORDER BY name"
        ).fetchall()
    return [Profile(**dict(r)) for r in rows]


def get_profile(profile_id: int) -> Optional[Profile]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM profiles WHERE id = ?", (profile_id,)
        ).fetchone()
    return Profile(**dict(row)) if row else None


def create_profile(name: str, description: str = "") -> Profile:
    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO profiles (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name.strip(), description.strip(), now, now),
        )
        profile_id = cur.lastrowid
    return get_profile(profile_id)


def update_profile(profile_id: int, name: str, description: str = "") -> Optional[Profile]:
    now = _now()
    with get_db() as conn:
        conn.execute(
            "UPDATE profiles SET name = ?, description = ?, updated_at = ? WHERE id = ?",
            (name.strip(), description.strip(), now, profile_id),
        )
    return get_profile(profile_id)


def delete_profile(profile_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))


# --- Profile Devices ---

def get_profile_devices(profile_id: int) -> list[ProfileDevice]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM profile_devices WHERE profile_id = ? ORDER BY local_name, mac",
            (profile_id,),
        ).fetchall()
    return [ProfileDevice(**dict(r)) for r in rows]


def get_all_profile_devices() -> list[ProfileDevice]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM profile_devices ORDER BY profile_id, local_name"
        ).fetchall()
    return [ProfileDevice(**dict(r)) for r in rows]


def add_device_to_profile(profile_id: int, mac: str, local_name: str = "") -> ProfileDevice:
    now = _now()
    mac = mac.lower().strip()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO profile_devices (profile_id, mac, local_name, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(profile_id, mac) DO UPDATE SET local_name = excluded.local_name""",
            (profile_id, mac, local_name.strip(), now),
        )
        device_id = cur.lastrowid
        row = conn.execute(
            "SELECT * FROM profile_devices WHERE profile_id = ? AND mac = ?",
            (profile_id, mac),
        ).fetchone()
    return ProfileDevice(**dict(row))


def remove_device_from_profile(profile_id: int, mac: str):
    mac = mac.lower().strip()
    with get_db() as conn:
        conn.execute(
            "DELETE FROM profile_devices WHERE profile_id = ? AND mac = ?",
            (profile_id, mac),
        )


def get_mac_profile_map() -> dict[str, list[int]]:
    """Return {mac: [profile_id, ...]} for all assigned devices."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT mac, profile_id FROM profile_devices"
        ).fetchall()
    result: dict[str, list[int]] = {}
    for r in rows:
        result.setdefault(r["mac"], []).append(r["profile_id"])
    return result


# --- Action History ---

def log_action(action: str, target_type: str, target_value: str, status: str, message: str = ""):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO action_history
               (action, target_type, target_value, status, message, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (action, target_type, target_value, status, message, _now()),
        )


def get_recent_history(limit: int = 50) -> list[ActionHistory]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM action_history ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [ActionHistory(**dict(r)) for r in rows]


# --- Omada Client Cache ---

def upsert_omada_clients(clients: list[dict]):
    now = _now()
    with get_db() as conn:
        # Mark every known client offline first. Devices absent from the API response
        # (e.g. powered off or paused-and-disconnected) will stay offline after the
        # upsert below, with their locally-set blocked state preserved.
        conn.execute("UPDATE omada_clients SET online = 0")
        for c in clients:
            conn.execute(
                """INSERT INTO omada_clients (mac, name, ip, online, blocked, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(mac) DO UPDATE SET
                     name = excluded.name,
                     ip = excluded.ip,
                     online = excluded.online,
                     blocked = excluded.blocked,
                     updated_at = excluded.updated_at""",
                (
                    c.get("mac", "").lower(),
                    c.get("name", ""),
                    c.get("ip", ""),
                    1 if c.get("online") else 0,
                    1 if c.get("blocked") else 0,
                    now,
                ),
            )


def update_client_blocked(mac: str, blocked: bool):
    """Update only the blocked flag in the local cache after a block/unblock action."""
    mac = mac.lower().strip()
    now = _now()
    with get_db() as conn:
        conn.execute(
            "UPDATE omada_clients SET blocked = ?, updated_at = ? WHERE mac = ?",
            (1 if blocked else 0, now, mac),
        )


def get_cached_clients() -> list[OmadaClientRecord]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM omada_clients ORDER BY name, mac"
        ).fetchall()
    return [
        OmadaClientRecord(
            mac=r["mac"],
            name=r["name"],
            ip=r["ip"],
            online=bool(r["online"]),
            blocked=bool(r["blocked"]),
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


def update_client_blocked(mac: str, blocked: bool):
    mac = mac.lower().strip()
    with get_db() as conn:
        conn.execute(
            "UPDATE omada_clients SET blocked = ? WHERE mac = ?",
            (1 if blocked else 0, mac),
        )


def get_cached_client(mac: str) -> Optional[OmadaClientRecord]:
    mac = mac.lower().strip()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM omada_clients WHERE mac = ?", (mac,)
        ).fetchone()
    if not row:
        return None
    return OmadaClientRecord(
        mac=row["mac"],
        name=row["name"],
        ip=row["ip"],
        online=bool(row["online"]),
        blocked=bool(row["blocked"]),
        updated_at=row["updated_at"],
    )


# --- Scheduled Actions ---

def _row_to_action(row) -> ScheduledAction:
    return ScheduledAction(
        id=row["id"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        action=row["action"],
        run_at=row["run_at"],
        status=row["status"],
        created_at=row["created_at"],
        executed_at=row["executed_at"],
        error=row["error"] or "",
    )


def create_scheduled_action(target_type: str, target_id: str, action: str, run_at: str) -> ScheduledAction:
    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO scheduled_actions
               (target_type, target_id, action, run_at, status, created_at, executed_at, error)
               VALUES (?, ?, ?, ?, 'pending', ?, NULL, '')""",
            (target_type, target_id, action, run_at, now),
        )
        row = conn.execute(
            "SELECT * FROM scheduled_actions WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return _row_to_action(row)


def get_pending_timer(target_type: str, target_id: str) -> Optional[ScheduledAction]:
    """Return the most recent pending scheduled action for a target."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM scheduled_actions
               WHERE target_type = ? AND target_id = ? AND status = 'pending'
               ORDER BY run_at ASC LIMIT 1""",
            (target_type, target_id),
        ).fetchone()
    return _row_to_action(row) if row else None


def get_due_scheduled_actions(now_iso: str) -> list[ScheduledAction]:
    """Return all pending actions whose run_at <= now."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM scheduled_actions
               WHERE status = 'pending' AND run_at <= ?
               ORDER BY run_at ASC""",
            (now_iso,),
        ).fetchall()
    return [_row_to_action(r) for r in rows]


def complete_scheduled_action(action_id: int):
    with get_db() as conn:
        conn.execute(
            "UPDATE scheduled_actions SET status='completed', executed_at=? WHERE id=?",
            (_now(), action_id),
        )


def fail_scheduled_action(action_id: int, error: str):
    with get_db() as conn:
        conn.execute(
            "UPDATE scheduled_actions SET status='failed', executed_at=?, error=? WHERE id=?",
            (_now(), error[:500], action_id),
        )


def cancel_scheduled_actions(target_type: str, target_id: str):
    """Cancel all pending actions for a target (called on manual resume/pause)."""
    with get_db() as conn:
        conn.execute(
            """UPDATE scheduled_actions SET status='cancelled', executed_at=?
               WHERE target_type=? AND target_id=? AND status='pending'""",
            (_now(), target_type, target_id),
        )


# --- Profile Schedules ---

def _row_to_schedule(row) -> ProfileSchedule:
    return ProfileSchedule(
        id=row["id"],
        profile_id=row["profile_id"],
        name=row["name"] or "",
        enabled=bool(row["enabled"]),
        days_of_week=row["days_of_week"] or "",
        pause_time=row["pause_time"] or "",
        resume_time=row["resume_time"] or "",
        timezone=row["timezone"] or "America/Chicago",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_pause_run=row["last_pause_run"],
        last_resume_run=row["last_resume_run"],
    )


def get_profile_schedule(profile_id: int) -> Optional[ProfileSchedule]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM profile_schedules WHERE profile_id = ?", (profile_id,)
        ).fetchone()
    return _row_to_schedule(row) if row else None


def upsert_profile_schedule(
    profile_id: int,
    name: str,
    enabled: bool,
    days_of_week: str,
    pause_time: str,
    resume_time: str,
    timezone: str,
) -> ProfileSchedule:
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO profile_schedules
               (profile_id, name, enabled, days_of_week, pause_time, resume_time, timezone,
                created_at, updated_at, last_pause_run, last_resume_run)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
               ON CONFLICT(profile_id) DO UPDATE SET
                 name = excluded.name,
                 enabled = excluded.enabled,
                 days_of_week = excluded.days_of_week,
                 pause_time = excluded.pause_time,
                 resume_time = excluded.resume_time,
                 timezone = excluded.timezone,
                 updated_at = excluded.updated_at""",
            (profile_id, name, 1 if enabled else 0, days_of_week,
             pause_time, resume_time, timezone, now, now),
        )
    return get_profile_schedule(profile_id)


def set_schedule_enabled(profile_id: int, enabled: bool):
    now = _now()
    with get_db() as conn:
        conn.execute(
            "UPDATE profile_schedules SET enabled=?, updated_at=? WHERE profile_id=?",
            (1 if enabled else 0, now, profile_id),
        )


def get_enabled_schedules() -> list[ProfileSchedule]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM profile_schedules WHERE enabled=1"
        ).fetchall()
    return [_row_to_schedule(r) for r in rows]


def update_schedule_last_run(schedule_id: int, run_type: str, timestamp: str):
    """run_type: 'pause' or 'resume'"""
    col = "last_pause_run" if run_type == "pause" else "last_resume_run"
    with get_db() as conn:
        conn.execute(
            f"UPDATE profile_schedules SET {col}=?, updated_at=? WHERE id=?",
            (timestamp, _now(), schedule_id),
        )


# --- App Settings ---

def get_app_setting(key: str, default: str = "") -> str:
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def set_app_setting(key: str, value: str):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO app_settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )


def get_app_timezone() -> str:
    return get_app_setting("timezone", "America/Chicago")

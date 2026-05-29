from dataclasses import dataclass
from typing import Optional


@dataclass
class Profile:
    id: int
    name: str
    description: str
    created_at: str
    updated_at: str


@dataclass
class ProfileDevice:
    id: int
    profile_id: int
    mac: str
    local_name: str
    created_at: str


@dataclass
class ActionHistory:
    id: int
    action: str
    target_type: str
    target_value: str
    status: str
    message: str
    created_at: str


@dataclass
class OmadaClientRecord:
    mac: str
    name: str
    ip: str
    online: bool
    blocked: bool
    updated_at: str


@dataclass
class ScheduledAction:
    id: int
    target_type: str   # 'profile' or 'device'
    target_id: str     # profile_id (str) or mac
    action: str        # 'resume' or 'pause'
    run_at: str        # ISO UTC
    status: str        # pending / completed / cancelled / failed
    created_at: str
    executed_at: Optional[str]
    error: str


@dataclass
class ProfileSchedule:
    id: int
    profile_id: int
    name: str
    enabled: bool
    days_of_week: str   # comma-separated ints, 0=Mon 6=Sun
    pause_time: str     # HH:MM 24h, empty = no pause
    resume_time: str    # HH:MM 24h, empty = no resume
    timezone: str
    created_at: str
    updated_at: str
    last_pause_run: Optional[str]
    last_resume_run: Optional[str]

from pydantic import BaseModel
from typing import Optional


class ProfileCreate(BaseModel):
    name: str
    description: Optional[str] = ""


class ProfileUpdate(BaseModel):
    name: str
    description: Optional[str] = ""


class AssignDeviceRequest(BaseModel):
    mac: str
    local_name: Optional[str] = ""
    profile_id: int

from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from enum import Enum


class OpType(Enum):
    LOGIN = "login"
    LOGOUT = "logout"
    QUERY = "query"
    CONFIG = "config"
    PLAYBACK = "playback"
    DOWNLOAD = "download"
    PTZ = "ptz"
    OTHER = "other"


@dataclass
class OperationLog:
    """操作日志"""
    log_id: str
    user: str
    op_type: OpType
    target: str = ""
    description: str = ""
    success: bool = True
    timestamp: Optional[datetime] = None
    ip: str = ""

    def to_dict(self):
        return {
            "log_id": self.log_id,
            "user": self.user,
            "op_type": self.op_type.value,
            "target": self.target,
            "description": self.description,
            "success": self.success,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "ip": self.ip
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'OperationLog':
        log = cls(
            log_id=data["log_id"],
            user=data["user"],
            op_type=OpType(data.get("op_type", "other")),
            target=data.get("target", ""),
            description=data.get("description", ""),
            success=data.get("success", True),
            ip=data.get("ip", "")
        )
        if data.get("timestamp"):
            log.timestamp = datetime.fromisoformat(data["timestamp"])
        return log


@dataclass
class AuthFailure:
    """鉴权失败记录"""
    fail_id: str
    device_id: str
    device_name: str
    user: str = ""
    reason: str = ""
    timestamp: Optional[datetime] = None
    ip: str = ""

    def to_dict(self):
        return {
            "fail_id": self.fail_id,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "user": self.user,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "ip": self.ip
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'AuthFailure':
        fail = cls(
            fail_id=data["fail_id"],
            device_id=data["device_id"],
            device_name=data["device_name"],
            user=data.get("user", ""),
            reason=data.get("reason", ""),
            ip=data.get("ip", "")
        )
        if data.get("timestamp"):
            fail.timestamp = datetime.fromisoformat(data["timestamp"])
        return fail

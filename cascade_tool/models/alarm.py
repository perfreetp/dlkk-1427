from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from enum import Enum


class AlarmLevel(Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class AlarmType(Enum):
    OFFLINE = "offline"
    AUTH_FAIL = "auth_fail"
    VIDEO_LOSS = "video_loss"
    STORAGE_FAIL = "storage_fail"
    CPU_HIGH = "cpu_high"
    CUSTOM = "custom"


@dataclass
class Alarm:
    """告警信息"""
    alarm_id: str
    source_id: str
    source_name: str
    alarm_type: AlarmType
    level: AlarmLevel
    description: str = ""
    timestamp: Optional[datetime] = None
    acked: bool = False

    def to_dict(self):
        return {
            "alarm_id": self.alarm_id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "alarm_type": self.alarm_type.value,
            "level": self.level.value,
            "description": self.description,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "acked": self.acked
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Alarm':
        alarm = cls(
            alarm_id=data["alarm_id"],
            source_id=data["source_id"],
            source_name=data["source_name"],
            alarm_type=AlarmType(data.get("alarm_type", "custom")),
            level=AlarmLevel(data.get("level", "info")),
            description=data.get("description", ""),
            acked=data.get("acked", False)
        )
        if data.get("timestamp"):
            alarm.timestamp = datetime.fromisoformat(data["timestamp"])
        return alarm

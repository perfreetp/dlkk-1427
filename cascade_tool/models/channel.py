from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from enum import Enum


class ChannelStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    FAULT = "fault"
    UNKNOWN = "unknown"


@dataclass
class Channel:
    """通道资源"""
    channel_id: str
    name: str
    parent_device_id: str = ""
    upper_channel_id: str = ""
    lower_channel_id: str = ""
    status: ChannelStatus = ChannelStatus.UNKNOWN
    manufacturer: str = ""
    resolution: str = ""
    has_audio: bool = False
    last_update: Optional[datetime] = None

    def to_dict(self):
        return {
            "channel_id": self.channel_id,
            "name": self.name,
            "parent_device_id": self.parent_device_id,
            "upper_channel_id": self.upper_channel_id,
            "lower_channel_id": self.lower_channel_id,
            "status": self.status.value,
            "manufacturer": self.manufacturer,
            "resolution": self.resolution,
            "has_audio": self.has_audio,
            "last_update": self.last_update.isoformat() if self.last_update else None
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Channel':
        ch = cls(
            channel_id=data["channel_id"],
            name=data["name"],
            parent_device_id=data.get("parent_device_id", ""),
            upper_channel_id=data.get("upper_channel_id", ""),
            lower_channel_id=data.get("lower_channel_id", ""),
            status=ChannelStatus(data.get("status", "unknown")),
            manufacturer=data.get("manufacturer", ""),
            resolution=data.get("resolution", ""),
            has_audio=data.get("has_audio", False)
        )
        if data.get("last_update"):
            ch.last_update = datetime.fromisoformat(data["last_update"])
        return ch

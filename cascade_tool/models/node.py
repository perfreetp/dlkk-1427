from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
from enum import Enum


class NodeType(Enum):
    ROOT = "root"
    PLATFORM = "platform"
    DEVICE = "device"
    CHANNEL = "channel"


class OnlineStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"
    PARTIAL = "partial"


@dataclass
class CascadeNode:
    """级联节点 - 表示级联拓扑中的一个节点（平台、设备或通道）"""
    node_id: str
    name: str
    node_type: NodeType
    parent_id: Optional[str] = None
    manufacturer: str = ""
    protocol: str = ""
    ip: str = ""
    port: int = 0
    status: OnlineStatus = OnlineStatus.UNKNOWN
    children: List['CascadeNode'] = field(default_factory=list)
    last_check: Optional[datetime] = None
    note: str = ""

    def add_child(self, child: 'CascadeNode'):
        child.parent_id = self.node_id
        self.children.append(child)

    def to_dict(self):
        return {
            "node_id": self.node_id,
            "name": self.name,
            "node_type": self.node_type.value,
            "parent_id": self.parent_id,
            "manufacturer": self.manufacturer,
            "protocol": self.protocol,
            "ip": self.ip,
            "port": self.port,
            "status": self.status.value,
            "children": [c.to_dict() for c in self.children],
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "note": self.note
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CascadeNode':
        node = cls(
            node_id=data["node_id"],
            name=data["name"],
            node_type=NodeType(data["node_type"]),
            parent_id=data.get("parent_id"),
            manufacturer=data.get("manufacturer", ""),
            protocol=data.get("protocol", ""),
            ip=data.get("ip", ""),
            port=data.get("port", 0),
            status=OnlineStatus(data.get("status", "unknown")),
            note=data.get("note", "")
        )
        if data.get("last_check"):
            node.last_check = datetime.fromisoformat(data["last_check"])
        node.children = [cls.from_dict(c) for c in data.get("children", [])]
        return node

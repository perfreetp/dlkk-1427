import random
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any

from cascade_tool.models.node import CascadeNode, NodeType, OnlineStatus
from cascade_tool.models.channel import Channel, ChannelStatus
from cascade_tool.models.alarm import Alarm, AlarmType, AlarmLevel
from cascade_tool.models.log_record import OperationLog, OpType, AuthFailure


class MockDataGenerator:
    """模拟数据生成器 - 用于生成联调测试用的模拟数据"""

    def __init__(self, seed: int = None):
        if seed is not None:
            random.seed(seed)
        self.manufacturers = ["海康威视", "大华", "宇视", "华为", "天地伟业", "科达"]
        self.protocols = ["GB28181", "ONVIF", "SDK", "RTSP"]

    def generate_topology(self, platform_count: int = 3, devices_per_platform: int = 5,
                          channels_per_device: int = 10) -> CascadeNode:
        """生成级联拓扑结构"""
        root = CascadeNode(
            node_id="ROOT-001",
            name="总平台",
            node_type=NodeType.ROOT,
            manufacturer="自研",
            protocol="GB28181",
            ip="192.168.1.100",
            port=5060,
            status=OnlineStatus.ONLINE,
            last_check=datetime.now()
        )

        for i in range(platform_count):
            platform = CascadeNode(
                node_id=f"PLAT-{i+1:03d}",
                name=f"分平台-{i+1}",
                node_type=NodeType.PLATFORM,
                manufacturer=random.choice(self.manufacturers),
                protocol=random.choice(self.protocols),
                ip=f"192.168.{10+i}.100",
                port=5060,
                status=random.choice([OnlineStatus.ONLINE, OnlineStatus.ONLINE, OnlineStatus.OFFLINE, OnlineStatus.PARTIAL]),
                last_check=datetime.now() - timedelta(minutes=random.randint(1, 60))
            )

            for j in range(devices_per_platform):
                device = CascadeNode(
                    node_id=f"DEV-{i+1:03d}-{j+1:03d}",
                    name=f"设备-{i+1}-{j+1}",
                    node_type=NodeType.DEVICE,
                    manufacturer=random.choice(self.manufacturers),
                    protocol=random.choice(self.protocols),
                    ip=f"192.168.{10+i}.{10+j}",
                    port=random.choice([554, 8000, 37777, 80]),
                    status=random.choice([OnlineStatus.ONLINE, OnlineStatus.ONLINE, OnlineStatus.ONLINE, OnlineStatus.OFFLINE]),
                    last_check=datetime.now() - timedelta(minutes=random.randint(1, 30))
                )

                for k in range(channels_per_device):
                    channel = CascadeNode(
                        node_id=f"CH-{i+1:03d}-{j+1:03d}-{k+1:03d}",
                        name=f"通道-{i+1}-{j+1}-{k+1}",
                        node_type=NodeType.CHANNEL,
                        manufacturer=random.choice(self.manufacturers),
                        status=random.choice([OnlineStatus.ONLINE, OnlineStatus.ONLINE, OnlineStatus.ONLINE, OnlineStatus.OFFLINE, OnlineStatus.UNKNOWN]),
                        last_check=datetime.now() - timedelta(minutes=random.randint(1, 15))
                    )
                    device.add_child(channel)

                platform.add_child(device)

            root.add_child(platform)

        return root

    def generate_channels(self, topology: CascadeNode) -> List[Channel]:
        """从拓扑生成通道列表，包含上下级通道编号对比数据"""
        channels = []
        for platform in topology.children:
            for device in platform.children:
                for channel_node in device.children:
                    ch = Channel(
                        channel_id=channel_node.node_id,
                        name=channel_node.name,
                        parent_device_id=device.node_id,
                        upper_channel_id=channel_node.node_id,
                        lower_channel_id=channel_node.node_id if random.random() > 0.15 else f"MISMATCH-{channel_node.node_id}",
                        status=ChannelStatus.ONLINE if channel_node.status == OnlineStatus.ONLINE else ChannelStatus.OFFLINE,
                        manufacturer=channel_node.manufacturer,
                        resolution=random.choice(["1080P", "4K", "720P", "UXGA"]),
                        has_audio=random.random() > 0.3,
                        last_update=datetime.now() - timedelta(minutes=random.randint(1, 120))
                    )
                    channels.append(ch)
        return channels

    def generate_alarms(self, count: int = 20, topology: CascadeNode = None) -> List[Alarm]:
        """生成告警列表"""
        alarms = []
        alarm_types = list(AlarmType)
        levels = list(AlarmLevel)

        sources = []
        if topology:
            def collect_nodes(node):
                sources.append((node.node_id, node.name))
                for child in node.children:
                    collect_nodes(child)
            collect_nodes(topology)

        for i in range(count):
            if sources:
                src_id, src_name = random.choice(sources)
            else:
                src_id = f"DEV-{random.randint(1, 20):03d}"
                src_name = f"设备-{random.randint(1, 20)}"

            alarm = Alarm(
                alarm_id=str(uuid.uuid4())[:8],
                source_id=src_id,
                source_name=src_name,
                alarm_type=random.choice(alarm_types),
                level=random.choice(levels),
                description=self._get_alarm_desc(random.choice(alarm_types)),
                timestamp=datetime.now() - timedelta(hours=random.randint(0, 24), minutes=random.randint(0, 60)),
                acked=random.random() > 0.6
            )
            alarms.append(alarm)

        alarms.sort(key=lambda a: a.timestamp or datetime.min, reverse=True)
        return alarms

    def _get_alarm_desc(self, alarm_type: AlarmType) -> str:
        descs = {
            AlarmType.OFFLINE: "设备离线，心跳超时",
            AlarmType.AUTH_FAIL: "鉴权失败，用户名或密码错误",
            AlarmType.VIDEO_LOSS: "视频信号丢失",
            AlarmType.STORAGE_FAIL: "存储设备异常",
            AlarmType.CPU_HIGH: "CPU使用率过高",
            AlarmType.CUSTOM: "自定义告警"
        }
        return descs.get(alarm_type, "未知告警")

    def generate_operation_logs(self, count: int = 30) -> List[OperationLog]:
        """生成操作日志"""
        logs = []
        op_types = list(OpType)
        users = ["admin", "operator", "user1", "user2", "tech_support"]

        for i in range(count):
            op_type = random.choice(op_types)
            log = OperationLog(
                log_id=f"LOG-{i+1:05d}",
                user=random.choice(users),
                op_type=op_type,
                target=f"CH-{random.randint(1, 100):03d}",
                description=self._get_op_desc(op_type),
                success=random.random() > 0.15,
                timestamp=datetime.now() - timedelta(hours=random.randint(0, 48), minutes=random.randint(0, 60)),
                ip=f"192.168.{random.randint(1, 50)}.{random.randint(1, 254)}"
            )
            logs.append(log)

        logs.sort(key=lambda l: l.timestamp or datetime.min, reverse=True)
        return logs

    def _get_op_desc(self, op_type: OpType) -> str:
        descs = {
            OpType.LOGIN: "用户登录系统",
            OpType.LOGOUT: "用户退出登录",
            OpType.QUERY: "查询设备列表",
            OpType.CONFIG: "修改设备配置参数",
            OpType.PLAYBACK: "回放历史录像",
            OpType.DOWNLOAD: "下载录像文件",
            OpType.PTZ: "云台控制操作",
            OpType.OTHER: "其他操作"
        }
        return descs.get(op_type, "未知操作")

    def generate_auth_failures(self, count: int = 10, topology: CascadeNode = None) -> List[AuthFailure]:
        """生成鉴权失败记录"""
        failures = []
        reasons = [
            "用户名或密码错误",
            "IP地址不在白名单内",
            "账号已被锁定",
            "设备认证码不匹配",
            "协议版本不兼容",
            "证书验证失败",
            "会话超时需重新认证"
        ]

        devices = []
        if topology:
            def collect_devices(node):
                if node.node_type == NodeType.DEVICE:
                    devices.append((node.node_id, node.name))
                for child in node.children:
                    collect_devices(child)
            collect_devices(topology)

        for i in range(count):
            if devices:
                dev_id, dev_name = random.choice(devices)
            else:
                dev_id = f"DEV-{random.randint(1, 20):03d}"
                dev_name = f"设备-{random.randint(1, 20)}"

            fail = AuthFailure(
                fail_id=f"AUTH-FAIL-{i+1:04d}",
                device_id=dev_id,
                device_name=dev_name,
                user=f"user{random.randint(1, 10)}",
                reason=random.choice(reasons),
                timestamp=datetime.now() - timedelta(hours=random.randint(0, 72), minutes=random.randint(0, 60)),
                ip=f"10.0.{random.randint(1, 50)}.{random.randint(1, 254)}"
            )
            failures.append(fail)

        failures.sort(key=lambda f: f.timestamp or datetime.min, reverse=True)
        return failures

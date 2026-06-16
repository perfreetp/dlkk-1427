import click
import csv
import json
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table
from typing import List, Dict, Any

from cascade_tool.config.project_config import ProjectConfig
from cascade_tool.models.node import CascadeNode, NodeType, OnlineStatus
from cascade_tool.models.channel import Channel, ChannelStatus
from cascade_tool.models.alarm import Alarm
from cascade_tool.models.log_record import AuthFailure

console = Console()
config_mgr = ProjectConfig()


@click.group()
def export_cmd():
    """导出数据与异常清单"""
    pass


@export_cmd.command("anomaly")
@click.argument("project_name")
@click.option("--format", "-f", "fmt", type=click.Choice(["csv", "json", "txt"]), default="csv", help="导出格式")
@click.option("--output", "-o", "output_file", default="", help="输出文件路径")
@click.option("--include-offline", is_flag=True, default=True, help="包含离线设备")
@click.option("--include-mismatch", is_flag=True, default=True, help="包含通道编号不匹配")
@click.option("--include-auth", is_flag=True, default=True, help="包含鉴权失败")
@click.option("--include-alarm", is_flag=True, default=True, help="包含告警")
def export_anomaly(project_name, fmt, output_file, include_offline, include_mismatch, include_auth, include_alarm):
    """导出异常清单"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    anomalies = _collect_anomalies(
        project_name,
        include_offline=include_offline,
        include_mismatch=include_mismatch,
        include_auth=include_auth,
        include_alarm=include_alarm
    )

    if not output_file:
        output_file = f"anomaly_{project_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{fmt}"

    output_path = Path(output_file)
    if not output_path.is_absolute():
        output_path = config_mgr.get_project_dir(project_name) / output_file

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        _export_csv(anomalies, output_path)
    elif fmt == "json":
        _export_json(anomalies, output_path)
    else:
        _export_txt(anomalies, output_path)

    console.print(f"[green]✓ 异常清单已导出到: {output_path}[/green]")
    console.print(f"  共 {len(anomalies)} 条异常记录")


def _collect_anomalies(project_name: str, include_offline: bool = True,
                       include_mismatch: bool = True, include_auth: bool = True,
                       include_alarm: bool = True) -> List[Dict[str, Any]]:
    """收集所有异常项"""
    anomalies = []

    topo_data = config_mgr.load_data_file(project_name, "topology.json")
    ch_data = config_mgr.load_data_file(project_name, "channels.json")
    auth_data = config_mgr.load_data_file(project_name, "auth_failures.json")
    alarm_data = config_mgr.load_data_file(project_name, "alarms.json")

    if include_offline and topo_data:
        topology = CascadeNode.from_dict(topo_data)
        anomalies.extend(_collect_offline_nodes(topology))

    if include_mismatch and ch_data:
        channels = [Channel.from_dict(d) for d in ch_data]
        anomalies.extend(_collect_channel_mismatches(channels))

    if include_auth and auth_data:
        failures = [AuthFailure.from_dict(d) for d in auth_data]
        anomalies.extend(_collect_auth_failures(failures))

    if include_alarm and alarm_data:
        alarms = [Alarm.from_dict(d) for d in alarm_data]
        anomalies.extend(_collect_alarms(alarms))

    return anomalies


def _collect_offline_nodes(node: CascadeNode) -> List[Dict[str, Any]]:
    """收集离线节点"""
    result = []

    def walk(n: CascadeNode):
        if n.node_type != NodeType.ROOT and n.status in [OnlineStatus.OFFLINE, OnlineStatus.PARTIAL]:
            result.append({
                "type": "离线节点",
                "level": n.node_type.value,
                "id": n.node_id,
                "name": n.name,
                "detail": f"状态: {n.status.value}, IP: {n.ip}, 厂商: {n.manufacturer}",
                "severity": "high" if n.status == OnlineStatus.OFFLINE else "medium",
                "time": n.last_check.isoformat() if n.last_check else ""
            })
        for child in n.children:
            walk(child)

    walk(node)
    return result


def _collect_channel_mismatches(channels: List[Channel]) -> List[Dict[str, Any]]:
    """收集通道编号不匹配"""
    result = []
    for ch in channels:
        if ch.upper_channel_id != ch.lower_channel_id:
            result.append({
                "type": "通道编号不匹配",
                "level": "channel",
                "id": ch.channel_id,
                "name": ch.name,
                "detail": f"上级编号: {ch.upper_channel_id}, 下级编号: {ch.lower_channel_id}",
                "severity": "medium",
                "time": ch.last_update.isoformat() if ch.last_update else ""
            })
    return result


def _collect_auth_failures(failures: List[AuthFailure]) -> List[Dict[str, Any]]:
    """收集鉴权失败"""
    result = []
    for f in failures:
        result.append({
            "type": "鉴权失败",
            "level": "device",
            "id": f.device_id,
            "name": f.device_name,
            "detail": f"用户: {f.user}, 原因: {f.reason}, IP: {f.ip}",
            "severity": "high",
            "time": f.timestamp.isoformat() if f.timestamp else ""
        })
    return result


def _collect_alarms(alarms: List[Alarm]) -> List[Dict[str, Any]]:
    """收集告警"""
    result = []
    for a in alarms:
        if not a.acked:
            result.append({
                "type": f"告警-{a.alarm_type.value}",
                "level": "alarm",
                "id": a.source_id,
                "name": a.source_name,
                "detail": f"级别: {a.level.value}, 描述: {a.description}",
                "severity": a.level.value,
                "time": a.timestamp.isoformat() if a.timestamp else ""
            })
    return result


def _export_csv(anomalies: List[Dict[str, Any]], output_path: Path):
    """导出 CSV"""
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["类型", "层级", "ID", "名称", "详情", "严重程度", "时间"])
        for a in anomalies:
            writer.writerow([
                a["type"],
                a["level"],
                a["id"],
                a["name"],
                a["detail"],
                a["severity"],
                a["time"]
            ])


def _export_json(anomalies: List[Dict[str, Any]], output_path: Path):
    """导出 JSON"""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(anomalies, f, indent=2, ensure_ascii=False)


def _export_txt(anomalies: List[Dict[str, Any]], output_path: Path):
    """导出纯文本"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("异常清单\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"异常总数: {len(anomalies)}\n")
        f.write("=" * 60 + "\n\n")

        for i, a in enumerate(anomalies, 1):
            f.write(f"[{i}] {a['type']}\n")
            f.write(f"    ID: {a['id']}\n")
            f.write(f"    名称: {a['name']}\n")
            f.write(f"    层级: {a['level']}\n")
            f.write(f"    严重程度: {a['severity']}\n")
            f.write(f"    详情: {a['detail']}\n")
            f.write(f"    时间: {a['time']}\n")
            f.write("-" * 40 + "\n")


@export_cmd.command("topology")
@click.argument("project_name")
@click.option("--format", "-f", "fmt", type=click.Choice(["json", "txt"]), default="json", help="导出格式")
@click.option("--output", "-o", "output_file", default="", help="输出文件路径")
def export_topology(project_name, fmt, output_file):
    """导出级联拓扑"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    topo_data = config_mgr.load_data_file(project_name, "topology.json")
    if not topo_data:
        console.print(f"[yellow]项目 '{project_name}' 尚无拓扑数据[/yellow]")
        return

    if not output_file:
        output_file = f"topology_{project_name}.{fmt}"

    output_path = Path(output_file)
    if not output_path.is_absolute():
        output_path = config_mgr.get_project_dir(project_name) / output_file

    if fmt == "json":
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(topo_data, f, indent=2, ensure_ascii=False)
    else:
        topology = CascadeNode.from_dict(topo_data)
        txt = _topology_to_text(topology)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(txt)

    console.print(f"[green]✓ 拓扑已导出到: {output_path}[/green]")


def _topology_to_text(node: CascadeNode, indent: int = 0) -> str:
    """拓扑转文本"""
    lines = []
    prefix = "  " * indent
    status_icon = "●" if node.status == OnlineStatus.ONLINE else "○"
    lines.append(f"{prefix}{status_icon} {node.name} ({node.node_id}) [{node.node_type.value}]")
    for child in node.children:
        lines.append(_topology_to_text(child, indent + 1))
    return "\n".join(lines)


@export_cmd.command("channels")
@click.argument("project_name")
@click.option("--format", "-f", "fmt", type=click.Choice(["csv", "json"]), default="csv", help="导出格式")
@click.option("--output", "-o", "output_file", default="", help="输出文件路径")
def export_channels(project_name, fmt, output_file):
    """导出通道清单"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    ch_data = config_mgr.load_data_file(project_name, "channels.json")
    if not ch_data:
        console.print(f"[yellow]项目 '{project_name}' 尚无通道数据[/yellow]")
        return

    if not output_file:
        output_file = f"channels_{project_name}.{fmt}"

    output_path = Path(output_file)
    if not output_path.is_absolute():
        output_path = config_mgr.get_project_dir(project_name) / output_file

    channels = [Channel.from_dict(d) for d in ch_data]

    if fmt == "csv":
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["通道ID", "名称", "所属设备", "上级编号", "下级编号", "状态", "厂商", "分辨率", "是否有音频"])
            for ch in channels:
                writer.writerow([
                    ch.channel_id,
                    ch.name,
                    ch.parent_device_id,
                    ch.upper_channel_id,
                    ch.lower_channel_id,
                    ch.status.value,
                    ch.manufacturer,
                    ch.resolution,
                    "是" if ch.has_audio else "否"
                ])
    else:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(ch_data, f, indent=2, ensure_ascii=False)

    console.print(f"[green]✓ 通道清单已导出到: {output_path}[/green]")
    console.print(f"  共 {len(channels)} 条通道记录")

import click
import time
import uuid
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from typing import List

from cascade_tool.config.project_config import ProjectConfig
from cascade_tool.models.alarm import Alarm, AlarmType, AlarmLevel
from cascade_tool.models.node import CascadeNode, NodeType
from cascade_tool.utils.mock_data import MockDataGenerator

console = Console()
config_mgr = ProjectConfig()


@click.group()
def tools_cmd():
    """辅助工具"""
    pass


@tools_cmd.command("alarm-sim")
@click.argument("project_name")
@click.option("--count", "-n", type=int, default=5, help="推送告警数量")
@click.option("--interval", "-i", type=float, default=1.0, help="推送间隔(秒)")
@click.option("--level", type=click.Choice(["critical", "major", "minor", "info", "all"]), default="all", help="告警级别")
@click.option("--type", "alarm_type", type=click.Choice([t.value for t in AlarmType] + ["all"]), default="all", help="告警类型")
@click.option("--save", is_flag=True, help="保存到项目告警记录中")
def alarm_sim(project_name, count, interval, level, alarm_type, save):
    """模拟告警推送"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    topo_data = config_mgr.load_data_file(project_name, "topology.json")
    if not topo_data:
        console.print(f"[yellow]项目 '{project_name}' 尚无拓扑数据，将使用随机来源[/yellow]")
        topology = None
    else:
        topology = CascadeNode.from_dict(topo_data)

    console.print(Panel(
        f"项目: {project_name}\n"
        f"推送数量: {count}\n"
        f"推送间隔: {interval}s\n"
        f"级别过滤: {level}\n"
        f"类型过滤: {alarm_type}",
        title="模拟告警推送",
        border_style="yellow"
    ))

    gen = MockDataGenerator()

    sources = []
    if topology:
        def collect_nodes(node):
            if node.node_type != NodeType.ROOT:
                sources.append((node.node_id, node.name))
            for child in node.children:
                collect_nodes(child)
        collect_nodes(topology)

    levels = [AlarmLevel.CRITICAL, AlarmLevel.MAJOR, AlarmLevel.MINOR, AlarmLevel.INFO]
    if level != "all":
        levels = [AlarmLevel(level)]

    types = list(AlarmType)
    if alarm_type != "all":
        types = [AlarmType(alarm_type)]

    import random
    generated_alarms = []

    console.print()
    console.print("[yellow]开始推送告警...[/yellow]")
    console.print()

    table = Table(title="告警推送记录", show_header=True, header_style="bold yellow")
    table.add_column("#")
    table.add_column("时间")
    table.add_column("级别")
    table.add_column("类型")
    table.add_column("来源")
    table.add_column("描述")

    with Live(table, refresh_per_second=4, console=console) as live:
        for i in range(count):
            time.sleep(interval)

            if sources:
                src_id, src_name = random.choice(sources)
            else:
                src_id = f"DEV-{random.randint(1, 100):03d}"
                src_name = f"设备-{random.randint(1, 100)}"

            selected_level = random.choice(levels)
            selected_type = random.choice(types)

            alarm = Alarm(
                alarm_id=str(uuid.uuid4())[:8],
                source_id=src_id,
                source_name=src_name,
                alarm_type=selected_type,
                level=selected_level,
                description=_get_alarm_desc(selected_type),
                timestamp=datetime.now(),
                acked=False
            )
            generated_alarms.append(alarm)

            level_str = _level_str(selected_level)
            type_str = selected_type.value

            table.add_row(
                str(i + 1),
                alarm.timestamp.strftime("%H:%M:%S"),
                level_str,
                type_str,
                f"{src_name}\n({src_id})",
                alarm.description
            )
            live.update(table)

    console.print()
    console.print(f"[green]✓ 已推送 {count} 条告警[/green]")

    if save:
        existing = config_mgr.load_data_file(project_name, "alarms.json") or []
        new_alarms = [a.to_dict() for a in generated_alarms]
        all_alarms = new_alarms + existing
        config_mgr.save_data_file(project_name, "alarms.json", all_alarms)
        console.print(f"[green]✓ 已保存到项目告警记录 (共 {len(all_alarms)} 条)[/green]")


def _get_alarm_desc(alarm_type: AlarmType) -> str:
    descs = {
        AlarmType.OFFLINE: "设备心跳超时，判定为离线",
        AlarmType.AUTH_FAIL: "鉴权失败，请检查用户名密码",
        AlarmType.VIDEO_LOSS: "视频信号丢失，请检查摄像头",
        AlarmType.STORAGE_FAIL: "存储设备读写异常",
        AlarmType.CPU_HIGH: "CPU使用率超过90%阈值",
        AlarmType.CUSTOM: "自定义告警触发"
    }
    return descs.get(alarm_type, "未知告警")


def _level_str(level: AlarmLevel) -> str:
    if level == AlarmLevel.CRITICAL:
        return "[red]严重[/red]"
    elif level == AlarmLevel.MAJOR:
        return "[orange]主要[/orange]"
    elif level == AlarmLevel.MINOR:
        return "[yellow]次要[/yellow]"
    else:
        return "[cyan]提示[/cyan]"


@tools_cmd.command("alarm-list")
@click.argument("project_name")
@click.option("--limit", "-n", type=int, default=20, help="显示数量")
@click.option("--level", type=click.Choice(["critical", "major", "minor", "info", "all"]), default="all", help="按级别过滤")
@click.option("--unacked-only", is_flag=True, help="仅显示未确认")
def alarm_list(project_name, limit, level, unacked_only):
    """查看告警列表"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    alarm_data = config_mgr.load_data_file(project_name, "alarms.json")
    if not alarm_data:
        console.print(f"[yellow]项目 '{project_name}' 暂无告警记录[/yellow]")
        return

    alarms = [Alarm.from_dict(d) for d in alarm_data]

    if level != "all":
        alarms = [a for a in alarms if a.level.value == level]
    if unacked_only:
        alarms = [a for a in alarms if not a.acked]

    total = len(alarms)
    alarms = alarms[:limit]

    console.print(Panel(
        f"总告警数: {len(alarm_data)}\n"
        f"符合条件: {total}\n"
        f"本次显示: {len(alarms)} 条",
        title="告警列表",
        border_style="yellow"
    ))

    table = Table(show_header=True, header_style="bold yellow")
    table.add_column("时间")
    table.add_column("级别")
    table.add_column("类型")
    table.add_column("来源")
    table.add_column("描述")
    table.add_column("状态")

    for alarm in alarms:
        level_str = _level_str(alarm.level)
        status_str = "[dim]已确认[/dim]" if alarm.acked else "[red]未确认[/red]"
        table.add_row(
            alarm.timestamp.strftime("%Y-%m-%d %H:%M:%S") if alarm.timestamp else "-",
            level_str,
            alarm.alarm_type.value,
            f"{alarm.source_name} ({alarm.source_id})",
            alarm.description,
            status_str
        )

    console.print(table)


@tools_cmd.command("alarm-ack")
@click.argument("project_name")
@click.option("--all", "-a", "ack_all", is_flag=True, help="确认所有告警")
@click.option("--id", "alarm_id", default="", help="确认指定告警ID")
def alarm_ack(project_name, ack_all, alarm_id):
    """确认告警"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    alarm_data = config_mgr.load_data_file(project_name, "alarms.json")
    if not alarm_data:
        console.print(f"[yellow]项目 '{project_name}' 暂无告警记录[/yellow]")
        return

    alarms = [Alarm.from_dict(d) for d in alarm_data]
    acked_count = 0

    if ack_all:
        for a in alarms:
            if not a.acked:
                a.acked = True
                acked_count += 1
    elif alarm_id:
        for a in alarms:
            if a.alarm_id == alarm_id and not a.acked:
                a.acked = True
                acked_count += 1
                break

    config_mgr.save_data_file(project_name, "alarms.json", [a.to_dict() for a in alarms])
    console.print(f"[green]✓ 已确认 {acked_count} 条告警[/green]")

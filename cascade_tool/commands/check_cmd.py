import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from typing import List, Dict, Any, Tuple

from cascade_tool.config.project_config import ProjectConfig
from cascade_tool.models.node import CascadeNode, NodeType, OnlineStatus
from cascade_tool.models.channel import Channel, ChannelStatus

console = Console()
config_mgr = ProjectConfig()


def _apply_profile(project_name: str, profile_name: str, defaults: dict) -> dict:
    """应用检查配置，命令行参数优先于profile"""
    if not profile_name:
        return defaults

    try:
        profile = config_mgr.get_check_profile(project_name, profile_name)
    except ValueError as e:
        console.print(f"[yellow]警告: {e}，使用默认参数[/yellow]")
        return defaults

    check_cfg = profile.get("check", {})

    result = defaults.copy()

    if "level" in check_cfg and defaults.get("level") == "all":
        result["level"] = check_cfg["level"]
    if "offline_only" in check_cfg and not defaults.get("offline_only"):
        result["offline_only"] = check_cfg["offline_only"]

    return result


@click.group()
def check_cmd():
    """批量检查与对照"""
    pass


@check_cmd.command("online")
@click.argument("project_name")
@click.option("--level", type=click.Choice(["platform", "device", "channel", "all"]), default="all", help="检查层级")
@click.option("--offline-only", is_flag=True, help="仅显示离线项")
@click.option("--profile", "-p", "profile_name", default="", help="使用指定检查配置")
def check_online(project_name, level, offline_only, profile_name):
    """批量检查在线率"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    params = _apply_profile(project_name, profile_name, {
        "level": level,
        "offline_only": offline_only
    })
    level = params["level"]
    offline_only = params["offline_only"]

    if profile_name:
        console.print(f"[dim]使用检查配置: {profile_name}[/dim]")

    topo_data = config_mgr.load_data_file(project_name, "topology.json")
    if not topo_data:
        console.print(f"[yellow]项目 '{project_name}' 尚无拓扑数据，请先使用 init mock 生成数据[/yellow]")
        return

    topology = CascadeNode.from_dict(topo_data)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        progress.add_task("检查在线状态...", total=None)
        stats = _collect_online_stats(topology, level)

    _print_online_summary(stats, level)

    if not offline_only or offline_only:
        _print_offline_details(topology, level, offline_only)


def _collect_online_stats(node: CascadeNode, level: str) -> Dict[str, Any]:
    """收集在线率统计"""
    stats = {
        "platform": {"total": 0, "online": 0, "offline": 0, "partial": 0, "unknown": 0},
        "device": {"total": 0, "online": 0, "offline": 0, "partial": 0, "unknown": 0},
        "channel": {"total": 0, "online": 0, "offline": 0, "partial": 0, "unknown": 0}
    }

    def walk(n: CascadeNode):
        if n.node_type == NodeType.PLATFORM:
            _count_status(stats["platform"], n.status)
        elif n.node_type == NodeType.DEVICE:
            _count_status(stats["device"], n.status)
        elif n.node_type == NodeType.CHANNEL:
            _count_status(stats["channel"], n.status)
        for child in n.children:
            walk(child)

    walk(node)
    return stats


def _count_status(counter: dict, status: OnlineStatus):
    counter["total"] += 1
    if status == OnlineStatus.ONLINE:
        counter["online"] += 1
    elif status == OnlineStatus.OFFLINE:
        counter["offline"] += 1
    elif status == OnlineStatus.PARTIAL:
        counter["partial"] += 1
    else:
        counter["unknown"] += 1


def _print_online_summary(stats: Dict[str, Any], level: str):
    """打印在线率汇总"""
    table = Table(title="在线率汇总", show_header=True, header_style="bold cyan")
    table.add_column("层级")
    table.add_column("总数", justify="right")
    table.add_column("在线", justify="right", style="green")
    table.add_column("离线", justify="right", style="red")
    table.add_column("部分", justify="right", style="yellow")
    table.add_column("未知", justify="right", style="dim")
    table.add_column("在线率", justify="right")

    level_map = {
        "platform": ("平台", stats["platform"]),
        "device": ("设备", stats["device"]),
        "channel": ("通道", stats["channel"])
    }

    display_levels = ["platform", "device", "channel"] if level == "all" else [level]

    for key in display_levels:
        name, data = level_map[key]
        total = data["total"]
        if total > 0:
            rate = data["online"] / total * 100
            rate_str = f"{rate:.1f}%"
            if rate >= 90:
                rate_str = f"[green]{rate_str}[/green]"
            elif rate >= 70:
                rate_str = f"[yellow]{rate_str}[/yellow]"
            else:
                rate_str = f"[red]{rate_str}[/red]"
        else:
            rate_str = "-"

        table.add_row(
            name,
            str(total),
            str(data["online"]),
            str(data["offline"]),
            str(data["partial"]),
            str(data["unknown"]),
            rate_str
        )

    console.print(table)


def _print_offline_details(node: CascadeNode, level: str, offline_only: bool):
    """打印离线详情"""
    items = []

    def walk(n: CascadeNode):
        include = False
        if level == "all" or level == n.node_type.value:
            if n.node_type != NodeType.ROOT:
                if not offline_only or n.status in [OnlineStatus.OFFLINE, OnlineStatus.PARTIAL]:
                    include = True

        if include:
            items.append(n)

        for child in n.children:
            walk(child)

    walk(node)

    if not items:
        if offline_only:
            console.print("[green]✓ 没有离线或异常的节点[/green]")
        return

    table = Table(title="节点状态详情", show_header=True, header_style="bold cyan")
    table.add_column("节点ID")
    table.add_column("名称")
    table.add_column("类型")
    table.add_column("厂商")
    table.add_column("状态")
    table.add_column("最后检查")

    for item in items:
        status_str = _status_str(item.status)
        table.add_row(
            item.node_id,
            item.name,
            item.node_type.value,
            item.manufacturer,
            status_str,
            item.last_check.strftime("%Y-%m-%d %H:%M:%S") if item.last_check else "-"
        )

    console.print(table)


def _status_str(status: OnlineStatus) -> str:
    if status == OnlineStatus.ONLINE:
        return "[green]在线[/green]"
    elif status == OnlineStatus.OFFLINE:
        return "[red]离线[/red]"
    elif status == OnlineStatus.PARTIAL:
        return "[yellow]部分在线[/yellow]"
    else:
        return "[dim]未知[/dim]"


@check_cmd.command("channel")
@click.argument("project_name")
@click.option("--mismatch-only", is_flag=True, help="仅显示编号不匹配的通道")
@click.option("--offline-only", is_flag=True, help="仅显示离线通道")
@click.option("--profile", "-p", "profile_name", default="", help="使用指定检查配置")
def check_channel(project_name, mismatch_only, offline_only, profile_name):
    """对比上下级通道编号"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    if profile_name:
        try:
            profile = config_mgr.get_check_profile(project_name, profile_name)
            check_cfg = profile.get("check", {})
            if not mismatch_only and check_cfg.get("mismatch_only", False):
                mismatch_only = True
            if not offline_only and check_cfg.get("offline_only", False):
                offline_only = True
            console.print(f"[dim]使用检查配置: {profile_name}[/dim]")
        except ValueError as e:
            console.print(f"[yellow]警告: {e}，使用默认参数[/yellow]")

    ch_data = config_mgr.load_data_file(project_name, "channels.json")
    if not ch_data:
        console.print(f"[yellow]项目 '{project_name}' 尚无通道数据[/yellow]")
        return

    channels = [Channel.from_dict(d) for d in ch_data]

    mismatch_count = 0
    offline_count = 0
    displayed = []

    for ch in channels:
        is_mismatch = ch.upper_channel_id != ch.lower_channel_id
        is_offline = ch.status == ChannelStatus.OFFLINE

        if is_mismatch:
            mismatch_count += 1
        if is_offline:
            offline_count += 1

        if mismatch_only and not is_mismatch:
            continue
        if offline_only and not is_offline:
            continue
        displayed.append(ch)

    console.print(Panel(
        f"总通道数: {len(channels)}\n"
        f"编号不匹配: [red]{mismatch_count}[/red] 条\n"
        f"离线通道: [red]{offline_count}[/red] 条",
        title="通道检查摘要",
        border_style="cyan"
    ))

    if not displayed:
        console.print("[green]✓ 所有通道编号一致且在线[/green]")
        return

    table = Table(title="通道对照详情", show_header=True, header_style="bold cyan")
    table.add_column("通道ID")
    table.add_column("名称")
    table.add_column("上级编号")
    table.add_column("下级编号")
    table.add_column("状态")
    table.add_column("是否匹配")

    for ch in displayed:
        match_str = "[green]✓ 匹配[/green]" if ch.upper_channel_id == ch.lower_channel_id else "[red]✗ 不匹配[/red]"
        status_str = "[green]在线[/green]" if ch.status == ChannelStatus.ONLINE else "[red]离线[/red]"
        table.add_row(
            ch.channel_id,
            ch.name,
            ch.upper_channel_id,
            ch.lower_channel_id,
            status_str,
            match_str
        )

    console.print(table)


@check_cmd.command("all")
@click.argument("project_name")
@click.option("--profile", "-p", "profile_name", default="", help="使用指定检查配置")
def check_all(project_name, profile_name):
    """执行全部检查项"""
    console.print(f"[bold cyan]=== 开始对项目 '{project_name}' 执行全部检查 ===[/bold cyan]\n")

    if profile_name:
        console.print(f"[dim]使用检查配置: {profile_name}[/dim]\n")

    click.echo()
    check_online.callback(project_name=project_name, level="all", offline_only=False, profile_name=profile_name)

    click.echo()
    check_channel.callback(project_name=project_name, mismatch_only=False, offline_only=False, profile_name=profile_name)

    console.print(f"\n[bold green]=== 全部检查完成 ===[/bold green]")

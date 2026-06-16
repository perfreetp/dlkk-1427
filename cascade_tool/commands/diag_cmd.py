import click
from rich.console import Console
from rich.table import Table
from rich.tree import Tree
from rich.panel import Panel
from rich.text import Text
from typing import List

from cascade_tool.config.project_config import ProjectConfig
from cascade_tool.models.node import CascadeNode, NodeType, OnlineStatus
from cascade_tool.models.channel import Channel, ChannelStatus
from cascade_tool.models.log_record import AuthFailure, OperationLog, OpType

console = Console()
config_mgr = ProjectConfig()


@click.group()
def diag_cmd():
    """诊断与排查"""
    pass


@diag_cmd.command("tree")
@click.argument("project_name")
@click.option("--level", type=click.Choice(["platform", "device", "channel"]), default="channel", help="显示到哪个层级")
@click.option("--status/--no-status", default=True, help="是否显示状态标记")
def show_tree(project_name, level, status):
    """按层级打印资源树"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    topo_data = config_mgr.load_data_file(project_name, "topology.json")
    if not topo_data:
        console.print(f"[yellow]项目 '{project_name}' 尚无拓扑数据[/yellow]")
        return

    topology = CascadeNode.from_dict(topo_data)
    max_depth = {"platform": 2, "device": 3, "channel": 4}[level]

    tree = _build_rich_tree(topology, max_depth, status)
    console.print(Panel(tree, title=f"级联资源树 - {project_name}", border_style="cyan"))


def _build_rich_tree(node: CascadeNode, max_depth: int, show_status: bool, current_depth: int = 1) -> Tree:
    """构建 Rich 树形结构"""
    label = _format_node_label(node, show_status)

    if current_depth == 1:
        tree = Tree(label, guide_style="dim")
    else:
        tree = Tree(label, guide_style="dim")

    if current_depth < max_depth:
        for child in node.children:
            child_tree = _build_rich_tree(child, max_depth, show_status, current_depth + 1)
            tree.add(child_tree)

    return tree


def _format_node_label(node: CascadeNode, show_status: bool) -> Text:
    """格式化节点标签"""
    text = Text()

    type_icons = {
        NodeType.ROOT: "🏠 ",
        NodeType.PLATFORM: "🖥️  ",
        NodeType.DEVICE: "📹 ",
        NodeType.CHANNEL: "📺 "
    }
    text.append(type_icons.get(node.node_type, "• "))

    text.append(f"{node.name} ", style="bold")
    text.append(f"({node.node_id})", style="dim")

    if show_status:
        if node.status == OnlineStatus.ONLINE:
            text.append(" ●", style="green")
        elif node.status == OnlineStatus.OFFLINE:
            text.append(" ●", style="red")
        elif node.status == OnlineStatus.PARTIAL:
            text.append(" ●", style="yellow")
        else:
            text.append(" ○", style="grey50")

    return text


@diag_cmd.command("auth")
@click.argument("project_name")
@click.option("--limit", "-n", type=int, default=20, help="显示最近N条记录")
@click.option("--device", "device_id", default="", help="按设备ID过滤")
@click.option("--group-by", type=click.Choice(["none", "reason", "device"]), default="none", help="按什么分组显示")
def check_auth(project_name, limit, device_id, group_by):
    """查看鉴权失败原因"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    auth_data = config_mgr.load_data_file(project_name, "auth_failures.json")
    if not auth_data:
        console.print(f"[yellow]项目 '{project_name}' 暂无鉴权失败记录[/yellow]")
        return

    failures = [AuthFailure.from_dict(d) for d in auth_data]

    if device_id:
        failures = [f for f in failures if device_id in f.device_id]

    total = len(failures)
    failures = failures[:limit]

    console.print(Panel(
        f"总记录数: {total}\n"
        f"本次显示: {len(failures)} 条",
        title="鉴权失败记录",
        border_style="red"
    ))

    if group_by == "reason":
        _print_auth_by_reason(failures)
    elif group_by == "device":
        _print_auth_by_device(failures)
    else:
        _print_auth_list(failures)


def _print_auth_list(failures: List[AuthFailure]):
    """打印鉴权失败列表"""
    table = Table(show_header=True, header_style="bold red")
    table.add_column("时间")
    table.add_column("设备ID")
    table.add_column("设备名")
    table.add_column("用户")
    table.add_column("失败原因")
    table.add_column("来源IP")

    for f in failures:
        table.add_row(
            f.timestamp.strftime("%Y-%m-%d %H:%M:%S") if f.timestamp else "-",
            f.device_id,
            f.device_name,
            f.user,
            f.reason,
            f.ip
        )

    console.print(table)


def _print_auth_by_reason(failures: List[AuthFailure]):
    """按原因分组显示"""
    from collections import Counter
    reason_counter = Counter(f.reason for f in failures)

    table = Table(title="按失败原因统计", show_header=True, header_style="bold red")
    table.add_column("失败原因")
    table.add_column("次数", justify="right")
    table.add_column("占比", justify="right")

    total = len(failures)
    for reason, count in reason_counter.most_common():
        pct = count / total * 100 if total > 0 else 0
        table.add_row(reason, str(count), f"{pct:.1f}%")

    console.print(table)


def _print_auth_by_device(failures: List[AuthFailure]):
    """按设备分组显示"""
    from collections import defaultdict
    device_map = defaultdict(list)
    for f in failures:
        device_map[f.device_id].append(f)

    table = Table(title="按设备统计", show_header=True, header_style="bold red")
    table.add_column("设备ID")
    table.add_column("设备名")
    table.add_column("失败次数", justify="right")
    table.add_column("主要原因")

    for dev_id, flist in sorted(device_map.items(), key=lambda x: len(x[1]), reverse=True):
        reasons = Counter(f.reason for f in flist)
        top_reason = reasons.most_common(1)[0][0] if reasons else "-"
        table.add_row(
            dev_id,
            flist[0].device_name,
            str(len(flist)),
            top_reason
        )

    console.print(table)


@diag_cmd.command("link")
@click.argument("project_name")
@click.argument("node_id")
def check_link(project_name, node_id):
    """链路排查 - 追溯指定节点的完整链路"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    topo_data = config_mgr.load_data_file(project_name, "topology.json")
    if not topo_data:
        console.print(f"[yellow]项目 '{project_name}' 尚无拓扑数据[/yellow]")
        return

    topology = CascadeNode.from_dict(topo_data)

    path = _find_node_path(topology, node_id)
    if not path:
        console.print(f"[red]未找到节点 '{node_id}'[/red]")
        return

    console.print(Panel(
        f"节点: {path[-1].name} ({node_id})",
        title="链路追溯",
        border_style="cyan"
    ))

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("层级")
    table.add_column("节点ID")
    table.add_column("名称")
    table.add_column("类型")
    table.add_column("厂商/协议")
    table.add_column("网络")
    table.add_column("状态")

    for i, node in enumerate(path):
        status_str = _status_str(node.status)
        net_info = f"{node.ip}:{node.port}" if node.ip else "-"
        manu_info = f"{node.manufacturer}/{node.protocol}" if node.manufacturer else "-"

        table.add_row(
            f"L{i+1}",
            node.node_id,
            node.name,
            node.node_type.value,
            manu_info,
            net_info,
            status_str
        )

    console.print(table)

    all_online = all(n.status == OnlineStatus.ONLINE for n in path)
    if all_online:
        console.print("\n[green]✓ 整条链路在线状态正常[/green]")
    else:
        offline_nodes = [n for n in path if n.status != OnlineStatus.ONLINE]
        console.print(f"\n[red]✗ 链路存在异常节点: {len(offline_nodes)} 个[/red]")
        for n in offline_nodes:
            console.print(f"  - {n.name} ({n.node_id}): {_status_str(n.status)}")


def _find_node_path(root: CascadeNode, target_id: str) -> List[CascadeNode]:
    """查找从根节点到目标节点的路径"""
    path = []

    def dfs(node) -> bool:
        path.append(node)
        if node.node_id == target_id:
            return True
        for child in node.children:
            if dfs(child):
                return True
        path.pop()
        return False

    dfs(root)
    return path


def _status_str(status: OnlineStatus) -> str:
    if status == OnlineStatus.ONLINE:
        return "[green]在线[/green]"
    elif status == OnlineStatus.OFFLINE:
        return "[red]离线[/red]"
    elif status == OnlineStatus.PARTIAL:
        return "[yellow]部分在线[/yellow]"
    else:
        return "[dim]未知[/dim]"


@diag_cmd.command("log")
@click.argument("project_name")
@click.option("--limit", "-n", type=int, default=20, help="显示最近N条")
@click.option("--user", default="", help="按用户过滤")
@click.option("--type", "op_type", type=click.Choice([t.value for t in OpType]), default=None, help="按操作类型过滤")
@click.option("--fail-only", is_flag=True, help="仅显示失败操作")
def show_logs(project_name, limit, user, op_type, fail_only):
    """回放最近操作日志"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    log_data = config_mgr.load_data_file(project_name, "operation_logs.json")
    if not log_data:
        console.print(f"[yellow]项目 '{project_name}' 暂无操作日志[/yellow]")
        return

    logs = [OperationLog.from_dict(d) for d in log_data]

    if user:
        logs = [l for l in logs if user in l.user]
    if op_type is not None:
        logs = [l for l in logs if l.op_type.value == op_type]
    if fail_only:
        logs = [l for l in logs if not l.success]

    total = len(logs)
    logs = logs[:limit]

    console.print(Panel(
        f"总记录数: {total}\n"
        f"本次显示: {len(logs)} 条",
        title="操作日志回放",
        border_style="cyan"
    ))

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("时间")
    table.add_column("用户")
    table.add_column("操作类型")
    table.add_column("目标")
    table.add_column("描述")
    table.add_column("结果")
    table.add_column("来源IP")

    for log in logs:
        result_str = "[green]成功[/green]" if log.success else "[red]失败[/red]"
        table.add_row(
            log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else "-",
            log.user,
            log.op_type.value,
            log.target,
            log.description,
            result_str,
            log.ip
        )

    console.print(table)

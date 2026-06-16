import click
from collections import Counter, defaultdict
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

    console.print(Panel(
        f"总记录数: {total}\n"
        f"分组显示: {group_by if group_by != 'none' else '不分组，显示前 ' + str(limit) + ' 条'}",
        title="鉴权失败记录",
        border_style="red"
    ))

    if group_by == "reason":
        _print_auth_by_reason(failures, limit)
    elif group_by == "device":
        _print_auth_by_device(failures, limit)
    else:
        failures_list = failures[:limit]
        _print_auth_list(failures_list)


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


def _print_auth_by_reason(failures: List[AuthFailure], limit: int = 20):
    """按原因分组显示"""
    reason_counter = Counter(f.reason for f in failures)

    table = Table(title="按失败原因统计", show_header=True, header_style="bold red")
    table.add_column("排名")
    table.add_column("失败原因")
    table.add_column("次数", justify="right")
    table.add_column("占比", justify="right")

    total = len(failures)
    for i, (reason, count) in enumerate(reason_counter.most_common(limit), 1):
        pct = count / total * 100 if total > 0 else 0
        table.add_row(str(i), reason, str(count), f"{pct:.1f}%")

    console.print(table)


def _print_auth_by_device(failures: List[AuthFailure], limit: int = 20):
    """按设备分组显示"""
    device_map = defaultdict(list)
    for f in failures:
        device_map[f.device_id].append(f)

    sorted_devices = sorted(device_map.items(), key=lambda x: len(x[1]), reverse=True)[:limit]

    table = Table(title="按设备统计（失败次数最多的设备）", show_header=True, header_style="bold red")
    table.add_column("排名")
    table.add_column("设备ID")
    table.add_column("设备名")
    table.add_column("失败次数", justify="right")
    table.add_column("主要失败原因")
    table.add_column("失败原因TOP3")

    for i, (dev_id, flist) in enumerate(sorted_devices, 1):
        reasons = Counter(f.reason for f in flist)
        top_reasons = reasons.most_common(3)
        top_reason_str = top_reasons[0][0] if top_reasons else "-"
        top3_str = ", ".join(f"{r}({c})" for r, c in top_reasons)

        table.add_row(
            str(i),
            dev_id,
            flist[0].device_name,
            str(len(flist)),
            top_reason_str,
            top3_str
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


@diag_cmd.command("healthcheck")
@click.argument("project_name")
@click.argument("node_id")
@click.option("--alarm-limit", type=int, default=5, help="显示最近告警数量")
@click.option("--auth-limit", type=int, default=5, help="显示最近鉴权失败数量")
def healthcheck(project_name, node_id, alarm_limit, auth_limit):
    """链路体检 - 整合显示节点的完整诊断信息

    输入设备或通道ID，一次性展示：上级平台链路、在线状态、
    通道编号、最近鉴权失败、未确认告警
    """
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    topo_data = config_mgr.load_data_file(project_name, "topology.json")
    ch_data = config_mgr.load_data_file(project_name, "channels.json")
    auth_data = config_mgr.load_data_file(project_name, "auth_failures.json")
    alarm_data = config_mgr.load_data_file(project_name, "alarms.json")

    if not topo_data:
        console.print(f"[yellow]项目 '{project_name}' 尚无拓扑数据[/yellow]")
        return

    topology = CascadeNode.from_dict(topo_data)

    path = _find_node_path(topology, node_id)
    if not path:
        console.print(f"[red]未找到节点 '{node_id}'[/red]")
        return

    target_node = path[-1]
    console.print()
    console.print(f"[bold cyan]═══════════════════════════════════════════════[/bold cyan]")
    console.print(f"[bold cyan]  链路体检报告: {target_node.name} ({node_id})[/bold cyan]")
    console.print(f"[bold cyan]═══════════════════════════════════════════════[/bold cyan]")
    console.print()

    _print_healthcheck_link(path)
    console.print()

    _print_healthcheck_channel_info(target_node, ch_data)
    console.print()

    device_id = _get_device_id_from_path(path)
    _print_healthcheck_auth_failures(device_id, auth_data, auth_limit)
    console.print()

    _print_healthcheck_alarms(target_node, ch_data, alarm_data, alarm_limit)
    console.print()

    _print_healthcheck_summary(path, ch_data, auth_data, alarm_data, device_id, target_node)
    console.print()


@diag_cmd.command("batch-healthcheck")
@click.argument("project_name")
@click.option("--ids", "node_ids", default="", help="逗号分隔的节点ID列表")
@click.option("--file", "id_file", default="", help="从文件读取节点ID（每行一个）")
@click.option("--output", "-o", "output_file", default="", help="输出详细报告文件路径")
@click.option("--format", "-f", "fmt", type=click.Choice(["txt", "json", "markdown"]), default="txt", help="报告格式")
def batch_healthcheck(project_name, node_ids, id_file, output_file, fmt):
    """批量链路体检 - 一次检查多个设备/通道，汇总排名

    支持逗号分隔ID或从文件读取ID，终端先输出排名汇总，
    可选输出详细报告文件
    """
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    ids = []
    if node_ids:
        ids = [i.strip() for i in node_ids.split(",") if i.strip()]
    if id_file:
        import os
        if not os.path.exists(id_file):
            console.print(f"[red]错误: 文件 '{id_file}' 不存在[/red]")
            return
        with open(id_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    ids.append(line)

    if not ids:
        console.print("[yellow]请通过 --ids 或 --file 指定要检查的节点ID[/yellow]")
        return

    topo_data = config_mgr.load_data_file(project_name, "topology.json")
    ch_data = config_mgr.load_data_file(project_name, "channels.json")
    auth_data = config_mgr.load_data_file(project_name, "auth_failures.json")
    alarm_data = config_mgr.load_data_file(project_name, "alarms.json")

    if not topo_data:
        console.print(f"[yellow]项目 '{project_name}' 尚无拓扑数据[/yellow]")
        return

    topology = CascadeNode.from_dict(topo_data)

    results = []
    not_found = []
    for nid in ids:
        path = _find_node_path(topology, nid)
        if not path:
            not_found.append(nid)
            continue
        target = path[-1]
        score, issues = _calc_health_score(path, target, ch_data, auth_data, alarm_data)
        results.append({
            "node_id": nid,
            "name": target.name,
            "node_type": target.node_type.value,
            "status": target.status.value,
            "score": score,
            "issue_count": len(issues),
            "issues": issues,
            "path": [n.node_id for n in path]
        })

    results.sort(key=lambda x: (-x["score"], x["node_id"]))

    console.print()
    console.print(f"[bold cyan]═══════════════════════════════════════════════[/bold cyan]")
    console.print(f"[bold cyan]  批量体检汇总 - {project_name}[/bold cyan]")
    console.print(f"[bold cyan]═══════════════════════════════════════════════[/bold cyan]")
    console.print()
    console.print(f"  检查节点: {len(ids)} 个, 成功: {len(results)} 个, 未找到: {len(not_found)} 个")
    console.print()

    if not_found:
        console.print(f"  [yellow]未找到节点: {', '.join(not_found)}[/yellow]")
        console.print()

    if results:
        table = Table(show_header=True, header_style="bold yellow")
        table.add_column("排名", width=6)
        table.add_column("节点ID")
        table.add_column("名称")
        table.add_column("类型")
        table.add_column("状态")
        table.add_column("问题数", justify="right")
        table.add_column("风险分", justify="right")
        table.add_column("主要问题")

        level_styles = {
            "online": "[green]",
            "offline": "[red]",
            "partial": "[yellow]",
            "unknown": "[dim]"
        }

        for i, r in enumerate(results, 1):
            status_str = level_styles.get(r["status"], "") + r["status"] + "[/]"
            top_issue = r["issues"][0]["category"] if r["issues"] else "-"
            score_color = "[red]" if r["score"] >= 3 else ("[yellow]" if r["score"] >= 1 else "[green]")
            score_str = score_color + str(r["score"]) + "[/]"
            table.add_row(
                str(i),
                r["node_id"],
                r["name"],
                r["node_type"],
                status_str,
                str(r["issue_count"]),
                score_str,
                top_issue
            )

        console.print(table)

    if output_file:
        from cascade_tool.commands.report_cmd import _build_healthcheck_report
        import json
        from datetime import datetime
        from pathlib import Path

        report_data = {
            "title": f"{project_name} 批量体检报告",
            "project": project_name,
            "generated_at": datetime.now().isoformat(),
            "total_checked": len(ids),
            "found": len(results),
            "not_found": not_found,
            "summary_rank": [
                {
                    "rank": i + 1,
                    "node_id": r["node_id"],
                    "name": r["name"],
                    "node_type": r["node_type"],
                    "status": r["status"],
                    "issue_count": r["issue_count"],
                    "score": r["score"]
                }
                for i, r in enumerate(results)
            ],
            "details": []
        }

        for r in results:
            detail = _build_healthcheck_report(topology, r["node_id"], ch_data, auth_data, alarm_data)
            report_data["details"].append(detail)

        output_path = Path(output_file)
        if not output_path.is_absolute():
            output_path = config_mgr.get_project_dir(project_name) / output_file
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if fmt == "json":
            content = json.dumps(report_data, indent=2, ensure_ascii=False, default=str)
        elif fmt == "markdown":
            content = _batch_report_to_markdown(report_data)
        else:
            content = _batch_report_to_txt(report_data)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        console.print()
        console.print(f"[green]✓ 详细报告已生成: {output_path}[/green]")

    console.print()


def _calc_health_score(path: List[CascadeNode], target: CascadeNode,
                       ch_data: list, auth_data: list, alarm_data: list) -> tuple:
    """计算体检健康评分和问题列表
    返回 (score, issues)，分数越高问题越严重
    """
    from cascade_tool.models.channel import Channel
    from cascade_tool.models.alarm import Alarm

    score = 0
    issues = []

    link_offline = [n for n in path if n.status != OnlineStatus.ONLINE]
    if link_offline:
        score += len(link_offline) * 2
        issues.append({"category": "链路异常", "detail": f"{len(link_offline)} 个节点离线", "severity": "high"})

    device_id = ""
    for node in reversed(path):
        if node.node_type == NodeType.DEVICE:
            device_id = node.node_id
            break

    if ch_data and (target.node_type == NodeType.CHANNEL or target.node_type == NodeType.DEVICE):
        channels = [Channel.from_dict(d) for d in ch_data]
        if target.node_type == NodeType.DEVICE:
            dev_channels = [c for c in channels if c.parent_device_id == target.node_id]
            mismatched = [c for c in dev_channels if c.upper_channel_id != c.lower_channel_id]
            offline_ch = [c for c in dev_channels if c.status != ChannelStatus.ONLINE]
            if mismatched:
                score += len(mismatched) * 1
                issues.append({"category": "通道编号", "detail": f"{len(mismatched)} 个不匹配", "severity": "medium"})
            if offline_ch:
                score += len(offline_ch) * 1
        elif target.node_type == NodeType.CHANNEL:
            matched = [c for c in channels if c.channel_id == target.node_id]
            if matched and matched[0].upper_channel_id != matched[0].lower_channel_id:
                score += 2
                issues.append({"category": "通道编号", "detail": "上下级不一致", "severity": "high"})
            if matched and matched[0].status != ChannelStatus.ONLINE:
                score += 1

    if auth_data and device_id:
        failures = [AuthFailure.from_dict(d) for d in auth_data]
        dev_failures = [f for f in failures if f.device_id == device_id]
        if dev_failures:
            score += min(len(dev_failures), 5)
            issues.append({"category": "鉴权失败", "detail": f"{len(dev_failures)} 次", "severity": "high"})

    if alarm_data:
        alarms = [Alarm.from_dict(d) for d in alarm_data]
        related_source_ids = {target.node_id}
        if target.node_type == NodeType.DEVICE and ch_data:
            channels = [Channel.from_dict(d) for d in ch_data]
            dev_channels = [c for c in channels if c.parent_device_id == target.node_id]
            for ch in dev_channels:
                related_source_ids.add(ch.channel_id)
        related_unacked = [a for a in alarms if not a.acked and a.source_id in related_source_ids]
        if related_unacked:
            score += min(len(related_unacked), 3)
            issues.append({"category": "未确认告警", "detail": f"{len(related_unacked)} 条", "severity": "medium"})

    return score, issues


def _batch_report_to_txt(report: dict) -> str:
    """批量体检报告 - TXT 格式"""
    lines = []
    lines.append("=" * 70)
    lines.append(report["title"])
    lines.append("=" * 70)
    lines.append(f"项目: {report['project']}")
    lines.append(f"生成时间: {report['generated_at']}")
    lines.append(f"检查节点: {report['total_checked']} 个")
    lines.append(f"找到: {report['found']} 个, 未找到: {len(report['not_found'])} 个")
    if report["not_found"]:
        lines.append(f"未找到节点: {', '.join(report['not_found'])}")
    lines.append("")

    lines.append("【排名汇总】")
    lines.append("-" * 50)
    for r in report["summary_rank"]:
        sev = "高" if r["score"] >= 3 else ("中" if r["score"] >= 1 else "低")
        lines.append(f"  {r['rank']}. [{sev}] {r['name']} ({r['node_id']}) - {r['issue_count']} 个问题, 风险分 {r['score']}")
    lines.append("")

    lines.append("【详细结果】")
    lines.append("-" * 50)
    for i, d in enumerate(report["details"], 1):
        if not d.get("found"):
            continue
        lines.append(f"  #{i} {d['node_name']} ({d['node_id']})")
        lines.append(f"     类型: {d['node_type']}, 层级: {d['cascade_levels']} 级")
        if d.get("issues"):
            for issue in d["issues"]:
                sev = "严重" if issue["severity"] == "high" else "一般"
                lines.append(f"     - [{sev}] {issue['category']}: {issue['detail']}")
        else:
            lines.append("     - 无异常")
        lines.append("")

    lines.append("=" * 70)
    lines.append("报告结束")
    lines.append("=" * 70)
    return "\n".join(lines)


def _batch_report_to_markdown(report: dict) -> str:
    """批量体检报告 - Markdown 格式"""
    lines = []
    lines.append(f"# {report['title']}")
    lines.append("")
    lines.append(f"- **项目**: {report['project']}")
    lines.append(f"- **生成时间**: {report['generated_at']}")
    lines.append(f"- **检查节点**: {report['total_checked']} 个")
    lines.append(f"- **找到**: {report['found']} 个, **未找到**: {len(report['not_found'])} 个")
    if report["not_found"]:
        lines.append(f"- **未找到节点**: {', '.join(report['not_found'])}")
    lines.append("")

    lines.append("## 排名汇总")
    lines.append("")
    lines.append("| 排名 | 节点名称 | 节点ID | 类型 | 状态 | 问题数 | 风险分 |")
    lines.append("|------|----------|--------|------|------|--------|--------|")
    for r in report["summary_rank"]:
        status_icon = "🟢" if r["status"] == "online" else ("🔴" if r["status"] == "offline" else "⚪")
        score_color = "🔴" if r["score"] >= 3 else ("🟡" if r["score"] >= 1 else "🟢")
        lines.append(f"| {r['rank']} | {r['name']} | {r['node_id']} | {r['node_type']} | {status_icon} {r['status']} | {r['issue_count']} | {score_color} {r['score']} |")
    lines.append("")

    lines.append("## 详细结果")
    lines.append("")
    for i, d in enumerate(report["details"], 1):
        if not d.get("found"):
            continue
        lines.append(f"### {i}. {d['node_name']} ({d['node_id']})")
        lines.append("")
        lines.append(f"- **类型**: {d['node_type']}")
        lines.append(f"- **级联层级**: {d['cascade_levels']} 级")
        lines.append("")
        if d.get("issues"):
            lines.append("**发现问题**:")
            lines.append("")
            for issue in d["issues"]:
                sev = "🔴 严重" if issue["severity"] == "high" else "🟡 一般"
                lines.append(f"- {sev} **{issue['category']}**: {issue['detail']}")
            lines.append("")
        else:
            lines.append("✅ 无异常")
            lines.append("")

    lines.append("---")
    lines.append("*报告由级联联调工具自动生成*")
    return "\n".join(lines)


def _get_device_id_from_path(path: List[CascadeNode]) -> str:
    """从链路中获取设备ID（往上找最近的设备节点）"""
    for node in reversed(path):
        if node.node_type == NodeType.DEVICE:
            return node.node_id
    return ""


def _print_healthcheck_link(path: List[CascadeNode]):
    """打印链路部分"""
    console.print("[bold yellow]【1/5】级联链路[/bold yellow]")

    table = Table(show_header=True, header_style="bold cyan", show_lines=True)
    table.add_column("层级", width=6)
    table.add_column("节点ID")
    table.add_column("名称")
    table.add_column("类型")
    table.add_column("厂商/协议")
    table.add_column("网络地址")
    table.add_column("状态", width=10)

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


def _print_healthcheck_channel_info(target_node: CascadeNode, ch_data: list):
    """打印通道编号对照信息"""
    console.print("[bold yellow]【2/5】通道编号对照[/bold yellow]")

    if target_node.node_type != NodeType.CHANNEL and target_node.node_type != NodeType.DEVICE:
        if target_node.node_type == NodeType.PLATFORM or target_node.node_type == NodeType.ROOT:
            console.print(f"  [dim]当前节点为{target_node.node_type.value}级别，无通道信息[/dim]")
            return

    if not ch_data:
        console.print("  [dim]暂无通道数据[/dim]")
        return

    from cascade_tool.models.channel import Channel
    channels = [Channel.from_dict(d) for d in ch_data]

    if target_node.node_type == NodeType.CHANNEL:
        matched = [c for c in channels if c.channel_id == target_node.node_id]
        if matched:
            ch = matched[0]
            match_status = "[green]✓ 一致[/green]" if ch.upper_channel_id == ch.lower_channel_id else "[red]✗ 不一致[/red]"
            table = Table(show_header=False, header_style="bold cyan")
            table.add_column("项目", style="bold")
            table.add_column("值")
            table.add_row("通道ID", ch.channel_id)
            table.add_row("通道名称", ch.name)
            table.add_row("所属设备", ch.parent_device_id)
            table.add_row("上级编号", ch.upper_channel_id)
            table.add_row("下级编号", ch.lower_channel_id)
            table.add_row("编号对照", match_status)
            table.add_row("当前状态", "[green]在线[/green]" if ch.status == ChannelStatus.ONLINE else "[red]离线[/red]")
            table.add_row("分辨率", ch.resolution or "-")
            table.add_row("音频", "有" if ch.has_audio else "无")
            console.print(table)
        else:
            console.print("  [dim]未找到对应通道记录[/dim]")
    elif target_node.node_type == NodeType.DEVICE:
        dev_channels = [c for c in channels if c.parent_device_id == target_node.node_id]
        if not dev_channels:
            console.print("  [dim]该设备下无通道数据[/dim]")
            return

        mismatched = [c for c in dev_channels if c.upper_channel_id != c.lower_channel_id]
        offline = [c for c in dev_channels if c.status != ChannelStatus.ONLINE]

        summary_table = Table(show_header=False, header_style="bold cyan")
        summary_table.add_column("项目", style="bold")
        summary_table.add_column("值")
        summary_table.add_row("通道总数", str(len(dev_channels)))
        summary_table.add_row("编号不匹配", f"[red]{len(mismatched)}[/red]" if mismatched else "[green]0[/green]")
        summary_table.add_row("离线通道", f"[red]{len(offline)}[/red]" if offline else "[green]0[/green]")
        console.print(summary_table)

        if mismatched:
            console.print()
            console.print("  编号不匹配的通道:")
            for ch in mismatched[:5]:
                console.print(f"    - {ch.channel_id} ({ch.name}): 上级={ch.upper_channel_id}, 下级={ch.lower_channel_id}")
            if len(mismatched) > 5:
                console.print(f"    ... 还有 {len(mismatched) - 5} 条")


def _print_healthcheck_auth_failures(device_id: str, auth_data: list, limit: int):
    """打印最近鉴权失败"""
    console.print("[bold yellow]【3/5】最近鉴权失败[/bold yellow]")

    if not auth_data:
        console.print("  [dim]暂无鉴权失败记录[/dim]")
        return

    failures = [AuthFailure.from_dict(d) for d in auth_data]

    if device_id:
        device_failures = [f for f in failures if f.device_id == device_id]
    else:
        device_failures = failures

    if not device_failures:
        console.print("  [green]✓ 该设备无鉴权失败记录[/green]")
        return

    recent = device_failures[:limit]
    table = Table(show_header=True, header_style="bold red")
    table.add_column("时间")
    table.add_column("设备")
    table.add_column("用户")
    table.add_column("失败原因")
    table.add_column("来源IP")

    for f in recent:
        table.add_row(
            f.timestamp.strftime("%m-%d %H:%M") if f.timestamp else "-",
            f.device_name,
            f.user,
            f.reason,
            f.ip
        )

    console.print(table)
    if len(device_failures) > limit:
        console.print(f"  [dim]还有 {len(device_failures) - limit} 条记录未显示[/dim]")


def _print_healthcheck_alarms(target_node: CascadeNode, ch_data: list, alarm_data: list, limit: int):
    """打印未确认告警"""
    console.print("[bold yellow]【4/5】未确认告警[/bold yellow]")

    if not alarm_data:
        console.print("  [dim]暂无告警数据[/dim]")
        return

    from cascade_tool.models.alarm import Alarm
    from cascade_tool.models.channel import Channel

    alarms = [Alarm.from_dict(d) for d in alarm_data]

    related_source_ids = {target_node.node_id}
    if target_node.node_type == NodeType.DEVICE and ch_data:
        channels = [Channel.from_dict(d) for d in ch_data]
        dev_channels = [c for c in channels if c.parent_device_id == target_node.node_id]
        for ch in dev_channels:
            related_source_ids.add(ch.channel_id)

    related_alarms = [a for a in alarms if not a.acked and a.source_id in related_source_ids]
    related_alarms.sort(key=lambda x: x.timestamp, reverse=True)

    if not related_alarms:
        console.print("  [green]✓ 该节点相关告警全部已确认[/green]")
        return

    source_count = len(related_source_ids) - 1 if target_node.node_type == NodeType.DEVICE else 0
    if source_count > 0:
        console.print(f"  [dim]关联设备本身 + {source_count} 个通道，共 {len(related_alarms)} 条未确认[/dim]")
    else:
        console.print(f"  [dim]共 {len(related_alarms)} 条未确认[/dim]")

    recent = related_alarms[:limit]
    table = Table(show_header=True, header_style="bold yellow")
    table.add_column("时间")
    table.add_column("级别")
    table.add_column("类型")
    table.add_column("来源")
    table.add_column("描述")

    level_styles = {
        "critical": "[red]",
        "major": "[orange]",
        "minor": "[yellow]",
        "info": "[cyan]"
    }

    for a in recent:
        level_str = level_styles.get(a.level.value, "") + a.level.value + "[/]"
        table.add_row(
            a.timestamp.strftime("%m-%d %H:%M") if a.timestamp else "-",
            level_str,
            a.alarm_type.value,
            a.source_name,
            a.description
        )

    console.print(table)
    if len(related_alarms) > limit:
        console.print(f"  [dim]还有 {len(related_alarms) - limit} 条未显示[/dim]")


def _print_healthcheck_summary(path: List[CascadeNode], ch_data: list,
                               auth_data: list, alarm_data: list,
                               device_id: str, target_node: CascadeNode):
    """打印体检总结"""
    console.print("[bold yellow]【5/5】体检总结[/bold yellow]")

    target = path[-1]

    issues = []

    link_offline = [n for n in path if n.status != OnlineStatus.ONLINE]
    if link_offline:
        issues.append(("链路异常", f"{len(link_offline)} 个节点离线", "high"))

    if ch_data and (target.node_type == NodeType.CHANNEL or target.node_type == NodeType.DEVICE):
        from cascade_tool.models.channel import Channel
        channels = [Channel.from_dict(d) for d in ch_data]
        if target.node_type == NodeType.DEVICE:
            dev_channels = [c for c in channels if c.parent_device_id == target.node_id]
            mismatched = [c for c in dev_channels if c.upper_channel_id != c.lower_channel_id]
            if mismatched:
                issues.append(("通道编号", f"{len(mismatched)} 个编号不匹配", "medium"))
        elif target.node_type == NodeType.CHANNEL:
            matched = [c for c in channels if c.channel_id == target.node_id]
            if matched and matched[0].upper_channel_id != matched[0].lower_channel_id:
                issues.append(("通道编号", "上下级编号不一致", "high"))

    if auth_data and device_id:
        failures = [AuthFailure.from_dict(d) for d in auth_data]
        dev_failures = [f for f in failures if f.device_id == device_id]
        if dev_failures:
            issues.append(("鉴权失败", f"{len(dev_failures)} 次失败记录", "high"))

    if alarm_data:
        from cascade_tool.models.alarm import Alarm
        from cascade_tool.models.channel import Channel

        alarms = [Alarm.from_dict(d) for d in alarm_data]
        related_source_ids = {target_node.node_id}
        if target_node.node_type == NodeType.DEVICE and ch_data:
            channels = [Channel.from_dict(d) for d in ch_data]
            dev_channels = [c for c in channels if c.parent_device_id == target_node.node_id]
            for ch in dev_channels:
                related_source_ids.add(ch.channel_id)

        related_unacked = [a for a in alarms if not a.acked and a.source_id in related_source_ids]
        if related_unacked:
            issues.append(("未确认告警", f"{len(related_unacked)} 条未处理", "medium"))

    if not issues:
        console.print("  [green]✓ 全部检查项正常[/green]")
    else:
        table = Table(show_header=True, header_style="bold red")
        table.add_column("检查项")
        table.add_column("问题")
        table.add_column("严重度")

        for item in issues:
            name, problem, severity = item
            sev_str = "[red]严重[/red]" if severity == "high" else "[yellow]一般[/yellow]"
            table.add_row(name, problem, sev_str)

        console.print(table)

    console.print(f"\n  [dim]体检节点: {target.name} ({target_node.node_id})[/dim]")
    console.print(f"  [dim]级联层级: {len(path)} 级[/dim]")
    console.print(f"  [dim]发现问题: {len(issues)} 项[/dim]")

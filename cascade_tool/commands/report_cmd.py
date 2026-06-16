import click
import json
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from collections import Counter

from cascade_tool.config.project_config import ProjectConfig
from cascade_tool.models.node import CascadeNode, NodeType, OnlineStatus
from cascade_tool.models.channel import Channel, ChannelStatus
from cascade_tool.models.alarm import Alarm, AlarmLevel
from cascade_tool.models.log_record import AuthFailure, OperationLog

console = Console()
config_mgr = ProjectConfig()


@click.group()
def report_cmd():
    """生成联调报告"""
    pass


@report_cmd.command("generate")
@click.argument("project_name")
@click.option("--format", "-f", "fmt", type=click.Choice(["txt", "json", "markdown"]), default="txt", help="报告格式")
@click.option("--output", "-o", "output_file", default="", help="输出文件路径")
@click.option("--title", default="", help="报告标题")
def generate_report(project_name, fmt, output_file, title):
    """生成联调报告"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    report_data = _build_report_data(project_name, title)

    if not output_file:
        ext = "md" if fmt == "markdown" else fmt
        output_file = f"report_{project_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"

    output_path = Path(output_file)
    if not output_path.is_absolute():
        output_path = config_mgr.get_project_dir(project_name) / output_file

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "txt":
        content = _report_to_txt(report_data)
    elif fmt == "json":
        content = json.dumps(report_data, indent=2, ensure_ascii=False, default=str)
    else:
        content = _report_to_markdown(report_data)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    console.print(f"[green]✓ 联调报告已生成: {output_path}[/green]")
    _print_report_summary(report_data)


def _build_report_data(project_name: str, title: str = "") -> dict:
    """构建报告数据"""
    report = {
        "title": title or f"{project_name} 级联联调报告",
        "project": project_name,
        "generated_at": datetime.now().isoformat(),
        "summary": {},
        "topology": {},
        "online_status": {},
        "channel_check": {},
        "auth_failures": {},
        "alarms": {},
        "issues": []
    }

    topo_data = config_mgr.load_data_file(project_name, "topology.json")
    ch_data = config_mgr.load_data_file(project_name, "channels.json")
    auth_data = config_mgr.load_data_file(project_name, "auth_failures.json")
    alarm_data = config_mgr.load_data_file(project_name, "alarms.json")

    if topo_data:
        topology = CascadeNode.from_dict(topo_data)
        report["topology"] = _analyze_topology(topology)
        report["online_status"] = _analyze_online_status(topology)

    if ch_data:
        channels = [Channel.from_dict(d) for d in ch_data]
        report["channel_check"] = _analyze_channels(channels)

    if auth_data:
        failures = [AuthFailure.from_dict(d) for d in auth_data]
        report["auth_failures"] = _analyze_auth_failures(failures)

    if alarm_data:
        alarms = [Alarm.from_dict(d) for d in alarm_data]
        report["alarms"] = _analyze_alarms(alarms)

    report["issues"] = _collect_issues(report)
    report["summary"] = _build_summary(report)

    return report


def _analyze_topology(topology: CascadeNode) -> dict:
    """分析拓扑结构"""
    counts = {"platform": 0, "device": 0, "channel": 0}
    manufacturers = Counter()
    protocols = Counter()

    def walk(node: CascadeNode):
        if node.node_type == NodeType.PLATFORM:
            counts["platform"] += 1
        elif node.node_type == NodeType.DEVICE:
            counts["device"] += 1
        elif node.node_type == NodeType.CHANNEL:
            counts["channel"] += 1
        if node.manufacturer:
            manufacturers[node.manufacturer] += 1
        if node.protocol:
            protocols[node.protocol] += 1
        for child in node.children:
            walk(child)

    walk(topology)

    return {
        "total_platforms": counts["platform"],
        "total_devices": counts["device"],
        "total_channels": counts["channel"],
        "total_nodes": sum(counts.values()),
        "manufacturers": dict(manufacturers.most_common()),
        "protocols": dict(protocols.most_common()),
        "cascade_levels": _count_levels(topology)
    }


def _count_levels(node: CascadeNode, current: int = 1) -> int:
    """计算级联层级数"""
    if not node.children:
        return current
    return max(_count_levels(child, current + 1) for child in node.children)


def _analyze_online_status(topology: CascadeNode) -> dict:
    """分析在线状态"""
    result = {
        "platform": {"total": 0, "online": 0, "offline": 0, "partial": 0, "unknown": 0},
        "device": {"total": 0, "online": 0, "offline": 0, "partial": 0, "unknown": 0},
        "channel": {"total": 0, "online": 0, "offline": 0, "partial": 0, "unknown": 0}
    }

    def walk(node: CascadeNode):
        key = node.node_type.value
        if key in result:
            result[key]["total"] += 1
            status_key = node.status.value
            if status_key in result[key]:
                result[key][status_key] += 1
        for child in node.children:
            walk(child)

    walk(topology)

    for key in result:
        total = result[key]["total"]
        if total > 0:
            result[key]["online_rate"] = round(result[key]["online"] / total * 100, 2)
        else:
            result[key]["online_rate"] = 0

    return result


def _analyze_channels(channels: list) -> dict:
    """分析通道对照"""
    total = len(channels)
    matched = sum(1 for c in channels if c.upper_channel_id == c.lower_channel_id)
    mismatched = total - matched
    online = sum(1 for c in channels if c.status == ChannelStatus.ONLINE)
    offline = total - online

    return {
        "total": total,
        "matched": matched,
        "mismatched": mismatched,
        "match_rate": round(matched / total * 100, 2) if total > 0 else 0,
        "online": online,
        "offline": offline,
        "online_rate": round(online / total * 100, 2) if total > 0 else 0
    }


def _analyze_auth_failures(failures: list) -> dict:
    """分析鉴权失败"""
    reasons = Counter(f.reason for f in failures)
    devices = Counter(f.device_id for f in failures)

    return {
        "total": len(failures),
        "by_reason": dict(reasons.most_common()),
        "by_device": dict(devices.most_common(10))
    }


def _analyze_alarms(alarms: list) -> dict:
    """分析告警"""
    unacked = [a for a in alarms if not a.acked]
    levels = Counter(a.level.value for a in unacked)
    types = Counter(a.alarm_type.value for a in unacked)

    return {
        "total": len(alarms),
        "unacked": len(unacked),
        "acked": len(alarms) - len(unacked),
        "by_level": dict(levels.most_common()),
        "by_type": dict(types.most_common())
    }


def _collect_issues(report: dict) -> list:
    """收集问题列表"""
    issues = []

    online = report.get("online_status", {})
    for level in ["platform", "device", "channel"]:
        data = online.get(level, {})
        if data.get("offline", 0) > 0:
            issues.append({
                "severity": "high",
                "category": f"离线{level}",
                "count": data["offline"],
                "description": f"有 {data['offline']} 个{level}处于离线状态"
            })
        if data.get("partial", 0) > 0:
            issues.append({
                "severity": "medium",
                "category": f"部分在线{level}",
                "count": data["partial"],
                "description": f"有 {data['partial']} 个{level}部分在线"
            })

    chk = report.get("channel_check", {})
    if chk.get("mismatched", 0) > 0:
        issues.append({
            "severity": "medium",
            "category": "通道编号不匹配",
            "count": chk["mismatched"],
            "description": f"有 {chk['mismatched']} 个通道上下级编号不一致"
        })

    auth = report.get("auth_failures", {})
    if auth.get("total", 0) > 0:
        issues.append({
            "severity": "high",
            "category": "鉴权失败",
            "count": auth["total"],
            "description": f"累计 {auth['total']} 次鉴权失败记录"
        })

    alm = report.get("alarms", {})
    if alm.get("unacked", 0) > 0:
        issues.append({
            "severity": "medium",
            "category": "未处理告警",
            "count": alm["unacked"],
            "description": f"有 {alm['unacked']} 条告警未确认"
        })

    issues.sort(key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["severity"], 3))
    return issues


def _build_summary(report: dict) -> dict:
    """构建摘要"""
    topo = report.get("topology", {})
    online = report.get("online_status", {})
    issues = report.get("issues", [])

    high_count = sum(1 for i in issues if i["severity"] == "high")
    medium_count = sum(1 for i in issues if i["severity"] == "medium")

    overall_rate = online.get("channel", {}).get("online_rate", 0)
    if overall_rate >= 95 and high_count == 0:
        status = "良好"
    elif overall_rate >= 80 or high_count == 0:
        status = "一般"
    else:
        status = "待改进"

    return {
        "overall_status": status,
        "total_nodes": topo.get("total_nodes", 0),
        "total_channels": topo.get("total_channels", 0),
        "channel_online_rate": online.get("channel", {}).get("online_rate", 0),
        "high_issues": high_count,
        "medium_issues": medium_count,
        "total_issues": len(issues)
    }


def _report_to_txt(report: dict) -> str:
    """生成文本格式报告"""
    lines = []
    lines.append("=" * 70)
    lines.append(report["title"])
    lines.append("=" * 70)
    lines.append(f"项目名称: {report['project']}")
    lines.append(f"生成时间: {report['generated_at']}")
    lines.append("")

    s = report["summary"]
    lines.append("【总体评估】")
    lines.append(f"  整体状态: {s['overall_status']}")
    lines.append(f"  节点总数: {s['total_nodes']}")
    lines.append(f"  通道总数: {s['total_channels']}")
    lines.append(f"  通道在线率: {s['channel_online_rate']}%")
    lines.append(f"  严重问题: {s['high_issues']} 个")
    lines.append(f"  一般问题: {s['medium_issues']} 个")
    lines.append(f"  问题总数: {s['total_issues']} 个")
    lines.append("")

    t = report["topology"]
    lines.append("【级联拓扑】")
    lines.append(f"  级联层级: {t.get('cascade_levels', 0)} 级")
    lines.append(f"  平台数量: {t.get('total_platforms', 0)}")
    lines.append(f"  设备数量: {t.get('total_devices', 0)}")
    lines.append(f"  通道数量: {t.get('total_channels', 0)}")
    if t.get("manufacturers"):
        lines.append(f"  涉及厂商: {', '.join(t['manufacturers'].keys())}")
    if t.get("protocols"):
        lines.append(f"  接入协议: {', '.join(t['protocols'].keys())}")
    lines.append("")

    o = report["online_status"]
    lines.append("【在线状态】")
    for level in ["platform", "device", "channel"]:
        data = o.get(level, {})
        lines.append(f"  {level}: 共 {data.get('total', 0)} 个, "
                     f"在线 {data.get('online', 0)} 个, "
                     f"离线 {data.get('offline', 0)} 个, "
                     f"在线率 {data.get('online_rate', 0)}%")
    lines.append("")

    c = report["channel_check"]
    lines.append("【通道对照】")
    lines.append(f"  通道总数: {c.get('total', 0)}")
    lines.append(f"  编号一致: {c.get('matched', 0)}")
    lines.append(f"  编号不一致: {c.get('mismatched', 0)}")
    lines.append(f"  一致率: {c.get('match_rate', 0)}%")
    lines.append("")

    a = report["auth_failures"]
    lines.append("【鉴权失败】")
    lines.append(f"  失败次数: {a.get('total', 0)}")
    if a.get("by_reason"):
        lines.append("  失败原因分布:")
        for reason, count in list(a["by_reason"].items())[:5]:
            lines.append(f"    - {reason}: {count} 次")
    lines.append("")

    alm = report["alarms"]
    lines.append("【告警情况】")
    lines.append(f"  告警总数: {alm.get('total', 0)}")
    lines.append(f"  未确认: {alm.get('unacked', 0)}")
    if alm.get("by_level"):
        lines.append("  级别分布:")
        for level, count in alm["by_level"].items():
            lines.append(f"    - {level}: {count} 条")
    lines.append("")

    issues = report["issues"]
    lines.append("【问题清单】")
    if issues:
        for i, issue in enumerate(issues, 1):
            sev = "严重" if issue["severity"] == "high" else "一般"
            lines.append(f"  {i}. [{sev}] {issue['category']} ({issue['count']})")
            lines.append(f"     {issue['description']}")
    else:
        lines.append("  无异常问题")
    lines.append("")

    lines.append("=" * 70)
    lines.append("报告结束")
    lines.append("=" * 70)

    return "\n".join(lines)


def _report_to_markdown(report: dict) -> str:
    """生成 Markdown 格式报告"""
    lines = []
    lines.append(f"# {report['title']}")
    lines.append("")
    lines.append(f"- **项目名称**: {report['project']}")
    lines.append(f"- **生成时间**: {report['generated_at']}")
    lines.append("")

    s = report["summary"]
    lines.append("## 总体评估")
    lines.append("")
    status_icon = "✅" if s["overall_status"] == "良好" else ("⚠️" if s["overall_status"] == "一般" else "❌")
    lines.append(f"{status_icon} **整体状态: {s['overall_status']}**")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 节点总数 | {s['total_nodes']} |")
    lines.append(f"| 通道总数 | {s['total_channels']} |")
    lines.append(f"| 通道在线率 | {s['channel_online_rate']}% |")
    lines.append(f"| 严重问题 | {s['high_issues']} 个 |")
    lines.append(f"| 一般问题 | {s['medium_issues']} 个 |")
    lines.append(f"| 问题总数 | {s['total_issues']} 个 |")
    lines.append("")

    t = report["topology"]
    lines.append("## 级联拓扑")
    lines.append("")
    lines.append("| 项目 | 数量 |")
    lines.append("|------|------|")
    lines.append(f"| 级联层级 | {t.get('cascade_levels', 0)} 级 |")
    lines.append(f"| 平台数量 | {t.get('total_platforms', 0)} |")
    lines.append(f"| 设备数量 | {t.get('total_devices', 0)} |")
    lines.append(f"| 通道数量 | {t.get('total_channels', 0)} |")
    lines.append("")
    if t.get("manufacturers"):
        lines.append(f"**涉及厂商**: {', '.join(t['manufacturers'].keys())}")
        lines.append("")
    if t.get("protocols"):
        lines.append(f"**接入协议**: {', '.join(t['protocols'].keys())}")
        lines.append("")

    o = report["online_status"]
    lines.append("## 在线状态")
    lines.append("")
    lines.append("| 层级 | 总数 | 在线 | 离线 | 在线率 |")
    lines.append("|------|------|------|------|--------|")
    for level in ["platform", "device", "channel"]:
        data = o.get(level, {})
        lines.append(f"| {level} | {data.get('total', 0)} | {data.get('online', 0)} | "
                     f"{data.get('offline', 0)} | {data.get('online_rate', 0)}% |")
    lines.append("")

    c = report["channel_check"]
    lines.append("## 通道对照")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 通道总数 | {c.get('total', 0)} |")
    lines.append(f"| 编号一致 | {c.get('matched', 0)} |")
    lines.append(f"| 编号不一致 | {c.get('mismatched', 0)} |")
    lines.append(f"| 一致率 | {c.get('match_rate', 0)}% |")
    lines.append("")

    a = report["auth_failures"]
    lines.append("## 鉴权失败")
    lines.append("")
    lines.append(f"**失败次数**: {a.get('total', 0)}")
    lines.append("")
    if a.get("by_reason"):
        lines.append("### 失败原因分布")
        lines.append("")
        lines.append("| 原因 | 次数 |")
        lines.append("|------|------|")
        for reason, count in list(a["by_reason"].items())[:10]:
            lines.append(f"| {reason} | {count} |")
        lines.append("")

    alm = report["alarms"]
    lines.append("## 告警情况")
    lines.append("")
    lines.append(f"**告警总数**: {alm.get('total', 0)} (未确认: {alm.get('unacked', 0)})")
    lines.append("")
    if alm.get("by_level"):
        lines.append("### 级别分布")
        lines.append("")
        lines.append("| 级别 | 数量 |")
        lines.append("|------|------|")
        for level, count in alm["by_level"].items():
            lines.append(f"| {level} | {count} |")
        lines.append("")

    issues = report["issues"]
    lines.append("## 问题清单")
    lines.append("")
    if issues:
        lines.append("| 序号 | 严重度 | 类别 | 数量 | 描述 |")
        lines.append("|------|--------|------|------|------|")
        for i, issue in enumerate(issues, 1):
            sev = "🔴 严重" if issue["severity"] == "high" else "🟡 一般"
            lines.append(f"| {i} | {sev} | {issue['category']} | {issue['count']} | {issue['description']} |")
    else:
        lines.append("✅ 无异常问题")
    lines.append("")

    lines.append("---")
    lines.append("*报告由级联联调工具自动生成*")

    return "\n".join(lines)


def _print_report_summary(report: dict):
    """打印报告摘要到终端"""
    s = report["summary"]
    console.print()

    status_color = "green" if s["overall_status"] == "良好" else ("yellow" if s["overall_status"] == "一般" else "red")
    console.print(f"[{status_color} bold]整体状态: {s['overall_status']}[/{status_color} bold]")

    table = Table(title="报告摘要", show_header=True, header_style="bold cyan")
    table.add_column("指标")
    table.add_column("数值", justify="right")

    table.add_row("节点总数", str(s["total_nodes"]))
    table.add_row("通道总数", str(s["total_channels"]))
    table.add_row("通道在线率", f"{s['channel_online_rate']}%")
    table.add_row("严重问题", f"[red]{s['high_issues']}[/red]")
    table.add_row("一般问题", f"[yellow]{s['medium_issues']}[/yellow]")
    table.add_row("问题总数", str(s["total_issues"]))

    console.print(table)

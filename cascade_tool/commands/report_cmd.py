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
@click.option("--format", "-f", "fmt", type=click.Choice(["txt", "json", "markdown"]), default=None, help="报告格式")
@click.option("--output", "-o", "output_file", default="", help="输出文件路径")
@click.option("--title", default="", help="报告标题")
@click.option("--profile", "-p", "profile_name", default="", help="使用指定检查配置")
@click.option("--healthcheck", "healthcheck_node", default="", help="包含指定节点的链路体检结果")
def generate_report(project_name, fmt, output_file, title, profile_name, healthcheck_node):
    """生成联调报告"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    profile = None
    if profile_name:
        try:
            profile = config_mgr.get_check_profile(project_name, profile_name)
            console.print(f"[dim]使用检查配置: {profile_name}[/dim]")
            if fmt is None and profile.get("report", {}).get("format"):
                fmt = profile["report"]["format"]
            if not title and profile.get("report", {}).get("title"):
                title = profile["report"]["title"]
        except ValueError as e:
            console.print(f"[yellow]警告: {e}[/yellow]")

    fmt = fmt or "txt"

    report_data = _build_report_data(
        project_name,
        title=title,
        profile_name=profile_name,
        profile=profile,
        healthcheck_node=healthcheck_node
    )

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


def _build_report_data(project_name: str, title: str = "", profile_name: str = "",
                       profile: dict = None, healthcheck_node: str = "") -> dict:
    """构建报告数据"""
    report = {
        "title": title or f"{project_name} 级联联调报告",
        "project": project_name,
        "generated_at": datetime.now().isoformat(),
        "used_profile": profile_name,
        "profile_config": profile,
        "summary": {},
        "topology": {},
        "online_status": {},
        "channel_check": {},
        "auth_failures": {},
        "alarms": {},
        "healthcheck": None,
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

    if healthcheck_node and topo_data:
        topology = CascadeNode.from_dict(topo_data)
        report["healthcheck"] = _build_healthcheck_report(
            topology, healthcheck_node, ch_data, auth_data, alarm_data
        )

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


def _build_healthcheck_report(topology: CascadeNode, node_id: str,
                              ch_data: list, auth_data: list, alarm_data: list) -> dict:
    """构建链路体检报告数据"""
    from cascade_tool.commands.diag_cmd import _find_node_path

    path = _find_node_path(topology, node_id)
    if not path:
        return {"node_id": node_id, "found": False}

    target = path[-1]
    device_id = ""
    for node in reversed(path):
        if node.node_type == NodeType.DEVICE:
            device_id = node.node_id
            break

    link_info = []
    for i, node in enumerate(path, 1):
        link_info.append({
            "level": f"L{i}",
            "node_id": node.node_id,
            "name": node.name,
            "type": node.node_type.value,
            "manufacturer": node.manufacturer,
            "protocol": node.protocol,
            "ip": node.ip,
            "port": node.port,
            "status": node.status.value
        })

    channel_info = None
    if ch_data and (target.node_type == NodeType.CHANNEL or target.node_type == NodeType.DEVICE):
        channels = [Channel.from_dict(d) for d in ch_data]
        if target.node_type == NodeType.CHANNEL:
            matched = [c for c in channels if c.channel_id == target.node_id]
            if matched:
                ch = matched[0]
                channel_info = {
                    "type": "single",
                    "channel_id": ch.channel_id,
                    "name": ch.name,
                    "parent_device": ch.parent_device_id,
                    "upper_id": ch.upper_channel_id,
                    "lower_id": ch.lower_channel_id,
                    "matched": ch.upper_channel_id == ch.lower_channel_id,
                    "status": ch.status.value
                }
        elif target.node_type == NodeType.DEVICE:
            dev_channels = [c for c in channels if c.parent_device_id == target.node_id]
            mismatched = [c for c in dev_channels if c.upper_channel_id != c.lower_channel_id]
            offline = [c for c in dev_channels if c.status != ChannelStatus.ONLINE]
            channel_info = {
                "type": "device",
                "total": len(dev_channels),
                "mismatched": len(mismatched),
                "offline": len(offline),
                "mismatch_list": [
                    {"id": c.channel_id, "name": c.name, "upper": c.upper_channel_id, "lower": c.lower_channel_id}
                    for c in mismatched[:5]
                ]
            }

    auth_info = None
    if auth_data and device_id:
        failures = [AuthFailure.from_dict(d) for d in auth_data]
        dev_failures = [f for f in failures if f.device_id == device_id]
        if dev_failures:
            from collections import Counter
            reason_counter = Counter(f.reason for f in dev_failures)
            auth_info = {
                "device_id": device_id,
                "total_failures": len(dev_failures),
                "recent": [
                    {
                        "time": f.timestamp.isoformat() if f.timestamp else "",
                        "user": f.user,
                        "reason": f.reason,
                        "ip": f.ip
                    }
                    for f in dev_failures[:5]
                ],
                "top_reasons": dict(reason_counter.most_common(3))
            }

    alarm_info = None
    if alarm_data:
        alarms = [Alarm.from_dict(d) for d in alarm_data]
        related = [a for a in alarms if not a.acked and (
            a.source_id == node_id or
            node_id.startswith(a.source_id) or
            a.source_id.startswith(node_id)
        )]
        if related:
            alarm_info = {
                "total_unacked": len(related),
                "recent": [
                    {
                        "time": a.timestamp.isoformat() if a.timestamp else "",
                        "level": a.level.value,
                        "type": a.alarm_type.value,
                        "source": a.source_name,
                        "description": a.description
                    }
                    for a in related[:5]
                ]
            }

    issues = []
    link_offline = [n for n in path if n.status != OnlineStatus.ONLINE]
    if link_offline:
        issues.append({"category": "链路异常", "detail": f"{len(link_offline)} 个节点离线", "severity": "high"})
    if channel_info:
        if channel_info.get("type") == "single" and not channel_info.get("matched", True):
            issues.append({"category": "通道编号", "detail": "上下级编号不一致", "severity": "high"})
        elif channel_info.get("type") == "device" and channel_info.get("mismatched", 0) > 0:
            issues.append({
                "category": "通道编号",
                "detail": f"{channel_info['mismatched']} 个编号不匹配",
                "severity": "medium"
            })
    if auth_info and auth_info["total_failures"] > 0:
        issues.append({
            "category": "鉴权失败",
            "detail": f"{auth_info['total_failures']} 次失败记录",
            "severity": "high"
        })
    if alarm_info and alarm_info["total_unacked"] > 0:
        issues.append({
            "category": "未确认告警",
            "detail": f"{alarm_info['total_unacked']} 条未处理",
            "severity": "medium"
        })

    return {
        "node_id": node_id,
        "node_name": target.name,
        "node_type": target.node_type.value,
        "found": True,
        "cascade_levels": len(path),
        "link": link_info,
        "channel_info": channel_info,
        "auth_failures": auth_info,
        "alarms": alarm_info,
        "issues": issues
    }


def _report_to_txt(report: dict) -> str:
    """生成文本格式报告"""
    lines = []
    lines.append("=" * 70)
    lines.append(report["title"])
    lines.append("=" * 70)
    lines.append(f"项目名称: {report['project']}")
    lines.append(f"生成时间: {report['generated_at']}")
    if report.get("used_profile"):
        lines.append(f"检查配置: {report['used_profile']}")
        profile_cfg = report.get("profile_config", {})
        if profile_cfg and profile_cfg.get("description"):
            lines.append(f"配置描述: {profile_cfg['description']}")
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

    hc = report.get("healthcheck")
    if hc and hc.get("found"):
        lines.append("【链路体检】")
        lines.append(f"  目标节点: {hc['node_name']} ({hc['node_id']})")
        lines.append(f"  级联层级: {hc['cascade_levels']} 级")
        lines.append("  链路:")
        for link in hc.get("link", []):
            status_str = "在线" if link["status"] == "online" else ("离线" if link["status"] == "offline" else link["status"])
            lines.append(f"    {link['level']}: {link['name']} ({link['node_id']}) [{link['type']}] - {status_str}")

        ci = hc.get("channel_info")
        if ci:
            if ci.get("type") == "single":
                lines.append("  通道信息:")
                lines.append(f"    名称: {ci.get('name', '')}")
                lines.append(f"    上级编号: {ci.get('upper_id', '')}")
                lines.append(f"    下级编号: {ci.get('lower_id', '')}")
                match_str = "一致" if ci.get("matched") else "不一致"
                lines.append(f"    编号对照: {match_str}")
            elif ci.get("type") == "device":
                lines.append("  设备通道统计:")
                lines.append(f"    通道总数: {ci.get('total', 0)}")
                lines.append(f"    编号不匹配: {ci.get('mismatched', 0)}")
                lines.append(f"    离线通道: {ci.get('offline', 0)}")

        af = hc.get("auth_failures")
        if af:
            lines.append(f"  鉴权失败: {af.get('total_failures', 0)} 次")
            if af.get("top_reasons"):
                lines.append("  主要原因:")
                for reason, count in list(af["top_reasons"].items())[:3]:
                    lines.append(f"    - {reason}: {count} 次")

        al = hc.get("alarms")
        if al:
            lines.append(f"  未确认告警: {al.get('total_unacked', 0)} 条")

        hc_issues = hc.get("issues", [])
        if hc_issues:
            lines.append("  体检发现问题:")
            for issue in hc_issues:
                sev = "严重" if issue["severity"] == "high" else "一般"
                lines.append(f"    - [{sev}] {issue['category']}: {issue['detail']}")
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
    if report.get("used_profile"):
        lines.append(f"- **检查配置**: {report['used_profile']}")
        profile_cfg = report.get("profile_config", {})
        if profile_cfg and profile_cfg.get("description"):
            lines.append(f"- **配置描述**: {profile_cfg['description']}")
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

    hc = report.get("healthcheck")
    if hc and hc.get("found"):
        lines.append("## 链路体检")
        lines.append("")
        lines.append(f"**目标节点**: {hc['node_name']} ({hc['node_id']})  ")
        lines.append(f"**级联层级**: {hc['cascade_levels']} 级")
        lines.append("")

        lines.append("### 级联链路")
        lines.append("")
        lines.append("| 层级 | 节点名称 | 节点ID | 类型 | 状态 |")
        lines.append("|------|----------|--------|------|------|")
        for link in hc.get("link", []):
            status_str = "🟢 在线" if link["status"] == "online" else ("🔴 离线" if link["status"] == "offline" else "⚪ " + link["status"])
            lines.append(f"| {link['level']} | {link['name']} | {link['node_id']} | {link['type']} | {status_str} |")
        lines.append("")

        ci = hc.get("channel_info")
        if ci:
            lines.append("### 通道信息")
            lines.append("")
            if ci.get("type") == "single":
                match_str = "✅ 一致" if ci.get("matched") else "❌ 不一致"
                lines.append("| 项目 | 值 |")
                lines.append("|------|-----|")
                lines.append(f"| 通道名称 | {ci.get('name', '')} |")
                lines.append(f"| 上级编号 | {ci.get('upper_id', '')} |")
                lines.append(f"| 下级编号 | {ci.get('lower_id', '')} |")
                lines.append(f"| 编号对照 | {match_str} |")
            elif ci.get("type") == "device":
                lines.append("| 项目 | 数量 |")
                lines.append("|------|------|")
                lines.append(f"| 通道总数 | {ci.get('total', 0)} |")
                lines.append(f"| 编号不匹配 | {ci.get('mismatched', 0)} |")
                lines.append(f"| 离线通道 | {ci.get('offline', 0)} |")
            lines.append("")

        af = hc.get("auth_failures")
        if af:
            lines.append("### 鉴权失败")
            lines.append("")
            lines.append(f"**失败次数**: {af.get('total_failures', 0)}")
            lines.append("")
            if af.get("top_reasons"):
                lines.append("**主要原因**:")
                lines.append("")
                for reason, count in list(af["top_reasons"].items())[:3]:
                    lines.append(f"- {reason}: {count} 次")
                lines.append("")

        al = hc.get("alarms")
        if al:
            lines.append("### 未确认告警")
            lines.append("")
            lines.append(f"**未确认数量**: {al.get('total_unacked', 0)} 条")
            lines.append("")

        hc_issues = hc.get("issues", [])
        if hc_issues:
            lines.append("### 体检发现问题")
            lines.append("")
            lines.append("| 严重度 | 类别 | 描述 |")
            lines.append("|--------|------|------|")
            for issue in hc_issues:
                sev = "🔴 严重" if issue["severity"] == "high" else "🟡 一般"
                lines.append(f"| {sev} | {issue['category']} | {issue['detail']} |")
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

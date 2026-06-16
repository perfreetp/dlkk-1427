import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from cascade_tool.config.project_config import ProjectConfig
from cascade_tool.utils.mock_data import MockDataGenerator

console = Console()
config_mgr = ProjectConfig()


@click.group()
def init_cmd():
    """初始化项目与数据"""
    pass


@init_cmd.command("project")
@click.argument("name")
@click.option("-d", "--desc", "description", default="", help="项目描述")
@click.option("--mock", is_flag=True, help="生成模拟联调数据")
@click.option("--seed", type=int, default=42, help="模拟数据随机种子")
def project(name, description, mock, seed):
    """创建新项目 NAME"""
    if config_mgr.project_exists(name):
        console.print(f"[yellow]项目 '{name}' 已存在[/yellow]")
        return

    cfg = config_mgr.create_project(name, description)
    console.print(f"[green]✓ 项目 '{name}' 创建成功[/green]")

    if mock:
        _generate_mock_data(name, seed)

    console.print(Panel(
        f"项目路径: {config_mgr.get_project_dir(name)}\n"
        f"描述: {description or '(无)'}",
        title="项目信息",
        border_style="green"
    ))


@init_cmd.command("list")
def list_projects():
    """列出所有项目"""
    projects = config_mgr.list_projects()
    if not projects:
        console.print("[yellow]暂无项目[/yellow]")
        return

    table = Table(title="项目列表", show_header=True, header_style="bold cyan")
    table.add_column("项目名")
    table.add_column("描述")
    table.add_column("创建时间")
    table.add_column("更新时间")

    for p in projects:
        table.add_row(
            p["name"],
            p["description"] or "(无)",
            p["created_at"],
            p["updated_at"]
        )

    console.print(table)


@init_cmd.command("mock")
@click.argument("project_name")
@click.option("--seed", type=int, default=42, help="随机种子")
@click.option("--platforms", type=int, default=3, help="下级平台数量")
@click.option("--devices", type=int, default=5, help="每个平台下设备数")
@click.option("--channels", type=int, default=10, help="每个设备下通道数")
def generate_mock(project_name, seed, platforms, devices, channels):
    """为指定项目生成模拟数据"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    _generate_mock_data(project_name, seed, platforms, devices, channels)
    console.print(f"[green]✓ 模拟数据已生成到项目 '{project_name}'[/green]")


def _generate_mock_data(project_name, seed=42, platforms=3, devices=5, channels=10):
    """生成模拟数据并保存"""
    gen = MockDataGenerator(seed=seed)

    topology = gen.generate_topology(
        platform_count=platforms,
        devices_per_platform=devices,
        channels_per_device=channels
    )
    channel_list = gen.generate_channels(topology)
    alarms = gen.generate_alarms(count=25, topology=topology)
    op_logs = gen.generate_operation_logs(count=50)
    auth_failures = gen.generate_auth_failures(count=15, topology=topology)

    config_mgr.save_data_file(project_name, "topology.json", topology.to_dict())
    config_mgr.save_data_file(project_name, "channels.json", [c.to_dict() for c in channel_list])
    config_mgr.save_data_file(project_name, "alarms.json", [a.to_dict() for a in alarms])
    config_mgr.save_data_file(project_name, "operation_logs.json", [l.to_dict() for l in op_logs])
    config_mgr.save_data_file(project_name, "auth_failures.json", [f.to_dict() for f in auth_failures])

    total_channels = platforms * devices * channels
    console.print(f"  拓扑结构: {platforms} 平台, {platforms*devices} 设备, {total_channels} 通道")
    console.print(f"  告警记录: {len(alarms)} 条")
    console.print(f"  操作日志: {len(op_logs)} 条")
    console.print(f"  鉴权失败: {len(auth_failures)} 条")


@init_cmd.command("delete")
@click.argument("project_name")
@click.option("--force", "-f", is_flag=True, help="强制删除，不提示")
def delete_project(project_name, force):
    """删除指定项目"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    if not force:
        click.confirm(f"确定要删除项目 '{project_name}' 吗？此操作不可恢复！", abort=True)

    config_mgr.delete_project(project_name)
    console.print(f"[green]✓ 项目 '{project_name}' 已删除[/green]")


@init_cmd.group("profile")
def profile_cmd():
    """管理检查配置模板"""
    pass


@profile_cmd.command("list")
@click.argument("project_name")
def list_profiles(project_name):
    """列出项目的所有检查配置"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    profiles = config_mgr.list_check_profiles(project_name)
    if not profiles:
        console.print(f"[yellow]项目 '{project_name}' 暂无检查配置[/yellow]")
        return

    table = Table(title=f"检查配置列表 - {project_name}", show_header=True, header_style="bold cyan")
    table.add_column("配置名")
    table.add_column("描述")
    table.add_column("创建时间")
    table.add_column("更新时间")

    for p in profiles:
        table.add_row(
            p["name"],
            p["description"] or "(无)",
            p["created_at"],
            p["updated_at"]
        )

    console.print(table)


@profile_cmd.command("show")
@click.argument("project_name")
@click.argument("profile_name")
def show_profile(project_name, profile_name):
    """显示检查配置详情"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    try:
        profile = config_mgr.get_check_profile(project_name, profile_name)
    except ValueError as e:
        console.print(f"[red]错误: {e}[/red]")
        return

    import json
    console.print(Panel(
        json.dumps(profile, indent=2, ensure_ascii=False),
        title=f"检查配置: {profile_name}",
        border_style="cyan"
    ))


@profile_cmd.command("save")
@click.argument("project_name")
@click.argument("profile_name")
@click.option("-d", "--desc", "description", default="", help="配置描述")
@click.option("--check-level", type=click.Choice(["platform", "device", "channel", "all"]), default="all", help="检查层级")
@click.option("--offline-only", is_flag=True, default=False, help="仅显示离线项")
@click.option("--export-format", type=click.Choice(["csv", "json", "txt"]), default="csv", help="导出格式")
@click.option("--report-format", type=click.Choice(["txt", "json", "markdown"]), default="txt", help="报告格式")
@click.option("--alarm-count", type=int, default=5, help="告警模拟数量")
@click.option("--alarm-level", type=click.Choice(["critical", "major", "minor", "info", "all"]), default="all", help="告警级别")
@click.option("--from-default", is_flag=True, help="从默认模板创建")
def save_profile(project_name, profile_name, description, check_level, offline_only,
                 export_format, report_format, alarm_count, alarm_level, from_default):
    """保存/更新检查配置"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    if from_default:
        profile = config_mgr.get_default_check_profile()
    else:
        profile = {
            "description": description,
            "check": {
                "level": check_level,
                "offline_only": offline_only,
                "check_channels": True,
                "check_devices": True,
                "check_platforms": True
            },
            "export": {
                "format": export_format,
                "include_offline": True,
                "include_mismatch": True,
                "include_auth": True,
                "include_alarm": True
            },
            "report": {
                "format": report_format,
                "title": ""
            },
            "alarm_sim": {
                "count": alarm_count,
                "interval": 1.0,
                "level": alarm_level,
                "alarm_type": "all"
            }
        }

    if description and not from_default:
        profile["description"] = description

    try:
        existing = config_mgr.get_check_profile(project_name, profile_name)
        is_new = False
    except ValueError:
        is_new = True

    config_mgr.save_check_profile(project_name, profile_name, profile)

    if is_new:
        console.print(f"[green]✓ 检查配置 '{profile_name}' 已创建[/green]")
    else:
        console.print(f"[green]✓ 检查配置 '{profile_name}' 已更新[/green]")


@profile_cmd.command("delete")
@click.argument("project_name")
@click.argument("profile_name")
@click.option("--force", "-f", is_flag=True, help="强制删除，不提示")
def delete_profile(project_name, profile_name, force):
    """删除检查配置"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    if not force:
        click.confirm(f"确定要删除检查配置 '{profile_name}' 吗？", abort=True)

    try:
        config_mgr.delete_check_profile(project_name, profile_name)
        console.print(f"[green]✓ 检查配置 '{profile_name}' 已删除[/green]")
    except ValueError as e:
        console.print(f"[red]错误: {e}[/red]")


@profile_cmd.command("export")
@click.argument("project_name")
@click.argument("profile_name")
@click.option("--output", "-o", "output_path", default="", help="输出文件或目录路径")
def export_profile(project_name, profile_name, output_path):
    """导出检查配置到文件"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    try:
        if not output_path:
            output_path = f"{profile_name}.json"
        result_path = config_mgr.export_check_profile(project_name, profile_name, output_path)
        console.print(f"[green]✓ 配置已导出: {result_path}[/green]")
    except ValueError as e:
        console.print(f"[red]错误: {e}[/red]")


@profile_cmd.command("import")
@click.argument("project_name")
@click.argument("input_path")
@click.option("--name", "-n", "profile_name", default="", help="导入后的配置名（默认用原配置名）")
@click.option("--overwrite", "-f", is_flag=True, help="已存在时覆盖")
def import_profile(project_name, input_path, profile_name, overwrite):
    """从文件导入检查配置"""
    if not config_mgr.project_exists(project_name):
        console.print(f"[red]错误: 项目 '{project_name}' 不存在[/red]")
        return

    try:
        name = config_mgr.import_check_profile(project_name, input_path, profile_name, overwrite)
        console.print(f"[green]✓ 配置已导入: {name}[/green]")
    except ValueError as e:
        console.print(f"[red]错误: {e}[/red]")


@profile_cmd.command("copy")
@click.argument("src_project")
@click.argument("src_profile")
@click.argument("dst_project")
@click.option("--dst-name", "-d", "dst_profile", default="", help="目标配置名（默认同源名）")
@click.option("--overwrite", "-f", is_flag=True, help="已存在时覆盖")
def copy_profile(src_project, src_profile, dst_project, dst_profile, overwrite):
    """复制检查配置到另一个项目"""
    try:
        name = config_mgr.copy_check_profile(src_project, src_profile, dst_project, dst_profile, overwrite)
        console.print(f"[green]✓ 配置已复制到 {dst_project}/{name}[/green]")
    except ValueError as e:
        console.print(f"[red]错误: {e}[/red]")

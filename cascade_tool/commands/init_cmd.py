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

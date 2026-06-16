import click
from rich.console import Console
from rich.panel import Panel

from cascade_tool.commands.init_cmd import init_cmd
from cascade_tool.commands.check_cmd import check_cmd
from cascade_tool.commands.diag_cmd import diag_cmd
from cascade_tool.commands.export_cmd import export_cmd
from cascade_tool.commands.report_cmd import report_cmd
from cascade_tool.commands.tools_cmd import tools_cmd

console = Console()


@click.group()
@click.version_option(version="1.0.0", prog_name="cascade-tool")
def cli():
    """视频监控联网平台级联联调工具

    面向开发者与设备厂家售后团队的命令行式联调工具，
    专门处理视频监控联网平台级联接入中的批量验证、
    链路排查和接口对照。
    """
    pass


cli.add_command(init_cmd, name="init")
cli.add_command(check_cmd, name="check")
cli.add_command(diag_cmd, name="diag")
cli.add_command(export_cmd, name="export")
cli.add_command(report_cmd, name="report")
cli.add_command(tools_cmd, name="tools")


@cli.command("help")
@click.argument("command", required=False)
@click.pass_context
def help_cmd(ctx, command):
    """显示帮助信息"""
    if command:
        cmd_obj = cli.get_command(ctx, command)
        if cmd_obj:
            click.echo(cmd_obj.get_help(ctx))
        else:
            click.echo(f"未知命令: {command}")
    else:
        click.echo(cli.get_help(ctx))


def main():
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[yellow]操作已取消[/yellow]")
    except Exception as e:
        console.print(f"\n[red]错误: {e}[/red]")
        raise


if __name__ == "__main__":
    main()

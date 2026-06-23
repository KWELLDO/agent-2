"""内置斜杠命令插件。

扩展示例：在本目录新建 my_cmd.py，写入
    from cli import command, Ctx, Style

    @command("/hi", "打个招呼")
    def hi(arg_str, ctx: Ctx):
        ctx.print("你好！", Style.GREEN)
重启后 /hi 即生效，核心无需任何改动。
"""
import os

from cli import command, Ctx, Style, command_help


@command("/exit", "退出程序")
def cmd_exit(arg_str, ctx: Ctx):
    ctx.running = False


@command("/quit", "退出程序")
def cmd_quit(arg_str, ctx: Ctx):
    ctx.running = False


@command("/clear", "清除对话历史")
def cmd_clear(arg_str, ctx: Ctx):
    ctx.reset()
    ctx.print("✅ 对话历史已清除", Style.GREEN)


@command("/write", "用编辑器打开文件: /write <path>")
def cmd_write(arg_str, ctx: Ctx):
    path = arg_str.strip()
    if not path:
        ctx.print("用法: /write <file_path>", Style.RED)
        return
    ctx.print(f"正在用默认编辑器打开 {path}...", Style.YELLOW)
    # 【假设】优先使用 VSCode，降级为 nano/vi
    os.system(f'code "{path}" 2>/dev/null || nano "{path}" || vi "{path}"')


@command("/help", "显示可用命令")
def cmd_help(arg_str, ctx: Ctx):
    ctx.print("可用命令:\n" + command_help(), Style.CYAN)

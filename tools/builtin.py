"""内置工具插件：文件读写与命令执行。

扩展示例：在本目录新建 my_tool.py，写入
    from cli import tool, Ctx, Style

    @tool("my_tool", "做某件事", {"type":"object","properties":{...},"required":[...]})
    def my_tool(args, ctx: Ctx):
        return "结果"
重启后即生效，核心无需任何改动。
"""
import os
import subprocess

from cli import tool, Ctx, Style


@tool(
    "write_file",
    "将内容写入指定路径的文件。若文件不存在则自动创建。",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对项目根目录的文件路径"},
            "content": {"type": "string", "description": "要写入的完整内容"},
        },
        "required": ["path", "content"],
    },
)
def write_file(args, ctx: Ctx):
    path = args["path"]
    content = args["content"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"✅ 成功写入 {path} (共 {len(content)} 字符)"


@tool(
    "read_file",
    "读取指定路径的文件内容。",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对项目根目录的文件路径"}
        },
        "required": ["path"],
    },
)
def read_file(args, ctx: Ctx):
    path = args["path"]
    if not os.path.isfile(path):
        return f"❌ 文件不存在: {path}"
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        result = f.read()
    if len(result) > 2000:
        result = result[:2000] + "\n... 【内容已截断】"
    return result


@tool(
    "run_command",
    "执行 shell 命令并返回输出。",
    {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的终端命令"}
        },
        "required": ["command"],
    },
)
def run_command(args, ctx: Ctx):
    cmd = args["command"]
    ctx.print(f"🖥️ 执行命令: {cmd}", Style.DIM)
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    out, err = proc.stdout, proc.stderr
    return f"stdout:\n{out}\nstderr:\n{err}" if out or err else "命令执行成功，无输出"

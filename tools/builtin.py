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
    path = ctx.resolve(args["path"])
    content = args["content"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"✅ 成功写入 {path} (共 {len(content)} 字符)"


@tool(
    "read_file",
    "读取指定路径的文件内容，支持分页（避免大文件被截断）。返回带行号的内容。",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对项目根目录的文件路径"},
            "offset": {"type": "integer", "description": "起始行号，从 1 开始，默认 1", "default": 1},
            "limit": {"type": "integer", "description": "读取的行数，默认 200", "default": 200},
        },
        "required": ["path"],
    },
)
def read_file(args, ctx: Ctx):
    path = ctx.resolve(args["path"])
    if not os.path.isfile(path):
        return f"❌ 文件不存在: {path}"
    offset = args.get("offset", 1)
    limit = args.get("limit", 200)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    total = len(lines)
    start = max(offset - 1, 0)
    end = start + limit
    page = lines[start:end]
    numbered = "".join(f"{i}: {line}" for i, line in enumerate(page, start=start + 1))
    shown = min(end, total)
    header = f"=== {path} (共 {total} 行，显示第 {start + 1}-{shown} 行) ===\n"
    if end < total:
        footer = f"\n【还有更多行，请用 offset={end + 1} 继续读取】"
    else:
        footer = "\n【已到文件末尾】"
    return header + numbered + footer if numbered else header + "（空文件）" + footer


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
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=ctx.root)
    out, err = proc.stdout, proc.stderr
    return f"stdout:\n{out}\nstderr:\n{err}" if out or err else "命令执行成功，无输出"

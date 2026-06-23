import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
import shutil
import re
import importlib
import pkgutil
import urllib.request
import urllib.error

# 兼容 `python cli.py` 直接运行：将本模块注册为 'cli'，避免插件 import 时二次加载
if "cli" not in sys.modules:
    sys.modules["cli"] = sys.modules[__name__]

# ================= 配置区 =================
url = "https://api.deepseek.com/chat/completions"
headers = {
    "Authorization": "Bearer REDACTED",
    "Content-Type": "application/json"
}
system_content = "你是一位专业的AI助手Coding助手,帮助用户编写软件代码。约束:不虚构不存在的信息,凡是预设和假设都会在【】 中说明"

# 【假设】目标API兼容 OpenAI 格式，支持 stream=True 及 tools 字段
# 【假设】本项目仅依赖 Python 3.12 标准库，无需安装任何第三方包
# 【假设】核心只负责循环/调度/渲染，所有工具与命令均为插件，放 tools/ 与 commands/ 自动加载

# ================= 终端渲染（标准库实现，替代 rich） =================

class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")
_LEADING_ANSI_RE = re.compile(r"(?:\033\[[0-9;]*m)+")


def _enable_vt():
    """Windows 下启用终端 ANSI 转义码处理（VT 模式）"""
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


_enable_vt()

# Windows 终端默认可能是 GBK，强制 stdout/stderr 用 UTF-8，避免 emoji 等字符输出崩溃
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def term_width():
    return shutil.get_terminal_size((80, 24)).columns


def colorize(text, *styles):
    return "".join(styles) + text + Style.RESET


def print_styled(text, *styles, end="\n"):
    print(colorize(text, *styles), end=end)


def _wrap_plain(text, width):
    """对纯文本（无 ANSI）按可见宽度折行"""
    if not text:
        return [""]
    segs = []
    for part in text.split("\n"):
        if not part:
            segs.append("")
            continue
        while len(part) > width:
            segs.append(part[:width])
            part = part[width:]
        segs.append(part)
    return segs


def _wrap_line(line, width):
    """对可能含 ANSI 颜色码的行按可见宽度折行，保留行首颜色"""
    if not line:
        return [""]
    m = _LEADING_ANSI_RE.match(line)
    prefix = m.group(0) if m else ""
    body = _ANSI_RE.sub("", line)
    segs = []
    while len(body) > width:
        segs.append(body[:width])
        body = body[width:]
    segs.append(body)
    if prefix:
        return [prefix + s + Style.RESET for s in segs]
    return segs


def render_markdown(md_text):
    """将 markdown 渲染为带 ANSI 颜色的多行字符串（按整行着色，保证折行准确）"""
    lines = md_text.split("\n")
    out = []
    in_code = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            out.append(colorize(line, Style.GRAY))
            continue
        if in_code:
            out.append(colorize(line, Style.GRAY))
            continue
        if line.startswith("# "):
            out.append(colorize(line, Style.BOLD, Style.CYAN))
        elif line.startswith("## "):
            out.append(colorize(line, Style.BOLD, Style.BLUE))
        elif line.startswith("### "):
            out.append(colorize(line, Style.BOLD, Style.MAGENTA))
        elif line.startswith(("- ", "* ")):
            out.append(colorize(line, Style.GREEN))
        elif line.startswith("> "):
            out.append(colorize(line, Style.GRAY))
        else:
            out.append(line)
    return "\n".join(out)


def panel(text, *styles):
    """绘制带边框的面板（替代 rich.Panel）"""
    width = min(max(term_width() - 4, 20), 76)
    top = "┌" + "─" * (width + 2) + "┐"
    bot = "└" + "─" * (width + 2) + "┘"
    print(colorize(top, *styles))
    for ln in _wrap_plain(text, width):
        print(colorize("│ " + ln.ljust(width) + " │", *styles))
    print(colorize(bot, *styles))


def prompt_user(prompt_text, *styles):
    """带样式的用户输入（替代 console.input）"""
    sys.stdout.write(colorize(prompt_text, *styles))
    sys.stdout.flush()
    return input()


class RichLog:
    """流式输出日志管理器，基于 ANSI 光标重绘实现逐块追加渲染（替代 rich.Live + Markdown）"""
    def __init__(self):
        self.current_md = ""
        self.last_line_count = 0

    def start(self):
        self.current_md = ""
        self.last_line_count = 0

    def append(self, chunk: str):
        self.current_md += chunk
        rendered = render_markdown(self.current_md)
        width = term_width()
        wrapped = []
        for ln in rendered.split("\n"):
            wrapped.extend(_wrap_line(ln, width))
        if self.last_line_count > 0:
            sys.stdout.write(f"\033[{self.last_line_count}A")
            sys.stdout.write("\033[J")
        sys.stdout.write("\n".join(wrapped))
        sys.stdout.flush()
        self.last_line_count = len(wrapped)

    def stop(self):
        if self.current_md:
            sys.stdout.write("\n")
            sys.stdout.flush()
        self.current_md = ""
        self.last_line_count = 0


# ================= 注册表（核心机制：插件由此接入，核心不感知具体工具/命令） =================

_TOOLS = {}
_COMMANDS = {}


def tool(name, description, parameters):
    """注册一个 AI 工具。插件用 @tool 装饰一个 (args, ctx)->str 的函数即可。"""
    def deco(fn):
        _TOOLS[name] = {
            "fn": fn,
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
        }
        return fn
    return deco


def command(name, help_text=""):
    """注册一个用户斜杠命令。插件用 @command 装饰一个 (arg_str, ctx)->None 的函数即可。"""
    def deco(fn):
        _COMMANDS[name] = {"fn": fn, "help": help_text}
        return fn
    return deco


def tool_schemas():
    return [t["schema"] for t in _TOOLS.values()]


def call_tool(name, args, ctx):
    return _TOOLS[name]["fn"](args, ctx)


def call_command(name, arg_str, ctx):
    return _COMMANDS[name]["fn"](arg_str, ctx)


def command_help():
    return "\n".join(f"  {n}  {c['help']}" for n, c in sorted(_COMMANDS.items()))


# ================= 上下文对象（插件通过它访问/影响核心状态） =================

class Ctx:
    """贯穿工具与命令的上下文。插件只应通过 ctx 读写状态，不直接碰核心内部。"""
    def __init__(self, system_content, root="."):
        self.system_content = system_content  # 基础系统提示（不含项目上下文）
        self.root = os.path.abspath(root)
        self.running = True
        self.messages = []
        self._rebuild_system_prompt()

    def _rebuild_system_prompt(self):
        """根据当前 root 扫描项目上下文，重建 system prompt 并同步到 messages 首条"""
        project_ctx = scan_project_context(self.root)
        tool_names = ", ".join(_TOOLS.keys()) or "（无）"
        self.system_prompt = (
            f"{self.system_content}\n\n【项目上下文】\n{project_ctx}\n\n"
            f"【可用工具】\n你可以调用 {tool_names}。请严格遵循工具定义返回 JSON。"
        )
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0]["content"] = self.system_prompt
        else:
            self.messages.insert(0, {"role": "system", "content": self.system_prompt})

    def set_workspace(self, path):
        """切换工作区到 path（相对当前 root 或绝对路径），刷新项目上下文。返回 (ok, info)"""
        new_root = path if os.path.isabs(path) else os.path.abspath(os.path.join(self.root, path))
        if not os.path.isdir(new_root):
            return False, f"目录不存在: {new_root}"
        self.root = new_root
        self._rebuild_system_prompt()
        return True, new_root

    def resolve(self, path):
        """将相对路径解析到当前工作区 root；绝对路径原样返回"""
        return path if os.path.isabs(path) else os.path.join(self.root, path)

    def reset(self):
        self.messages = []
        self._rebuild_system_prompt()

    def print(self, text, *styles):
        """插件统一用 ctx.print 输出带样式文本，无需 import 核心渲染函数"""
        print(colorize(text, *styles))


# ================= 工作区感知 =================

def scan_project_context(root_dir: str = ".") -> str:
    """扫描项目结构及关键配置文件，注入上下文"""
    parts = []
    key_files = [".gitignore", "pyproject.toml", "setup.cfg", "README.md", "requirements.txt", "package.json"]
    for fname in key_files:
        fpath = os.path.join(root_dir, fname)
        if os.path.isfile(fpath):
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                if len(content) > 2000:
                    content = content[:2000] + "\n... 【内容已截断】"
                parts.append(f"=== {fname} ===\n{content}\n")

    tree_lines = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in ['__pycache__', 'node_modules', '.venv', '.git']]
        rel_dir = os.path.relpath(dirpath, root_dir)
        indent = "  " * rel_dir.count(os.sep)
        name = os.path.basename(dirpath) if rel_dir != "." else os.path.basename(root_dir)
        tree_lines.append(f"{indent}{name}/")
        for f in sorted(filenames):
            if not f.startswith('.'):
                tree_lines.append(f"{indent}  {f}")
        if len(tree_lines) > 50:
            tree_lines.append(f"{indent}  ... 【更多文件已省略】")
            break

    parts.insert(0, f"=== Project Structure ===\n" + "\n".join(tree_lines) + "\n")
    return "\n".join(parts)


# ================= 插件加载 =================

def load_plugins(dirname):
    """扫描并 import 指定目录下所有非下划线开头的 .py，触发其 @tool/@command 注册"""
    root = os.path.dirname(os.path.abspath(__file__))
    pkg_dir = os.path.join(root, dirname)
    if not os.path.isdir(pkg_dir):
        return
    for _, name, _ in pkgutil.iter_modules([pkg_dir]):
        if name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{dirname}.{name}")
        except Exception as e:
            print_styled(f"⚠️ 加载插件 {dirname}.{name} 失败: {e}", Style.YELLOW)


# ================= Agent 循环 =================

def _print_tool_result(name, res, preview_limit=500):
    """终端展示工具结果：短结果完整显示，长结果截断并标注总长度。
    注意：仅影响终端展示，传给 AI 的始终是完整 res。"""
    print_styled(f"🔧 {name}:", Style.DIM)
    if len(res) <= preview_limit:
        print_styled(res, Style.DIM)
    else:
        print_styled(res[:preview_limit], Style.DIM)
        print_styled(
            f"... 【结果共 {len(res)} 字符，完整内容已传给 AI，此处仅显示前 {preview_limit} 字符】",
            Style.DIM,
        )


def call_llm(ctx: Ctx):
    """流式调用 LLM，支持工具循环执行。核心只做调度，工具逻辑全在插件。"""
    max_rounds = 20
    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        # 每轮重新序列化 payload，携带上一轮工具调用结果，避免用旧数据重复请求
        payload = {
            "model": "deepseek-v4-flash",
            "messages": ctx.messages,
            "tools": tool_schemas(),
            "stream": True,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            response = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            print_styled(f"❌ HTTP 错误 {e.code}: {body[:200]}", Style.RED)
            break
        except urllib.error.URLError as e:
            print_styled(f"❌ 连接错误: {e.reason}", Style.RED)
            break

        full_content = ""
        tool_calls_buffer = {}

        log = RichLog()
        log.start()
        try:
            for raw_line in response:
                line_str = raw_line.decode("utf-8", errors="ignore").rstrip("\r\n")
                if not line_str or not line_str.startswith("data: "):
                    continue
                data_str = line_str[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})

                    content = delta.get("content", "")
                    if content:
                        full_content += content
                        log.append(content)

                    tc_list = delta.get("tool_calls")
                    if tc_list:
                        for tc in tc_list:
                            idx = tc.get("index", 0)
                            tc_id = tc.get("id", f"call_{idx}")
                            if idx not in tool_calls_buffer:
                                tool_calls_buffer[idx] = {
                                    "id": tc_id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.get("function", {}).get("name", ""),
                                        "arguments": "",
                                    },
                                }
                            tool_calls_buffer[idx]["function"]["arguments"] += tc.get("function", {}).get("arguments", "")
                except json.JSONDecodeError:
                    continue
        finally:
            log.stop()
            try:
                response.close()
            except Exception:
                pass

        tool_calls = list(tool_calls_buffer.values())

        if tool_calls:
            ctx.messages.append({
                "role": "assistant",
                "content": full_content or None,
                "tool_calls": tool_calls,
            })
            panel("🛠️ AI 请求调用工具，正在执行...", Style.BOLD, Style.YELLOW)
            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                try:
                    res = call_tool(name, args, ctx)
                except Exception as e:
                    res = f"❌ 工具执行异常: {e}"
                ctx.messages.append({"role": "tool", "tool_call_id": tc["id"], "content": res})
                _print_tool_result(name, res)
            continue
        else:
            ctx.messages.append({"role": "assistant", "content": full_content})
            break
    else:
        print_styled("⚠️ 达到最大工具调用轮数上限，已停止", Style.YELLOW)


# ================= 主循环 =================

def main():
    # 1. 加载所有插件（注册工具与命令）
    load_plugins("tools")
    load_plugins("commands")

    panel("🚀 CodeAgent-TUI 已就绪 (插件化核心)", Style.BOLD, Style.GREEN)

    # 2. 创建上下文（自动扫描启动目录为工作区，注入 system prompt）
    ctx = Ctx(system_content, root=".")
    print_styled(f"📂 当前工作区: {ctx.root}", Style.CYAN)
    print_styled("\n💡 可用命令:\n" + command_help(), Style.CYAN)

    while ctx.running:
        try:
            user_input = prompt_user("\nYou> ", Style.BOLD, Style.BLUE)
        except (KeyboardInterrupt, EOFError):
            print_styled("\n已退出", Style.BOLD, Style.RED)
            break

        if not user_input.strip():
            continue

        # 命令分发（核心不识别具体命令，全部走注册表）
        if user_input.startswith("/"):
            cmd, *rest = user_input.split(maxsplit=1)
            arg_str = rest[0] if rest else ""
            if cmd in _COMMANDS:
                call_command(cmd, arg_str, ctx)
            else:
                ctx.print(f"❌ 未知命令: {cmd}（/help 查看可用命令）", Style.RED)
            continue

        # 普通对话
        ctx.messages.append({"role": "user", "content": user_input})
        print_styled("\nAgent>", Style.BOLD, Style.CYAN)
        call_llm(ctx)


if __name__ == "__main__":
    main()

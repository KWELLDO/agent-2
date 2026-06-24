import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
import importlib
import pkgutil
import urllib.request
import urllib.error

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.live import Live
from rich.markdown import Markdown
from rich.table import Table
from rich.box import ROUNDED

# 兼容 `python cli.py` 直接运行：将本模块注册为 'cli'，避免插件 import 时二次加载
if "cli" not in sys.modules:
    sys.modules["cli"] = sys.modules[__name__]

# ================= 配置区 =================
PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/chat/completions",
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
        "auth_scheme": "bearer",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"],
    },
    "tongyi": {
        "base_url": "http://10.40.187.243:8003/model/three_tongyi_bd/v1/chat/completions",
        "api_key": os.environ.get("TONGYI_API_KEY", ""),
        "auth_scheme": "raw",
        "models": ["default"],
    },
}
DEFAULT_PROVIDER = "deepseek"
DEFAULT_MODEL = "deepseek-v4-flash"
system_content = "你是一位专业的AI助手Coding助手,帮助用户编写软件代码。约束:不虚构不存在的信息,凡是预设和假设都会在【】 中说明"

# ================= 终端渲染（基于 rich） =================

_console = Console()

# Windows 终端默认可能是 GBK，强制 stdout/stderr 用 UTF-8，避免 emoji 等字符输出崩溃
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


class Style:
    """样式常量（映射到 rich 样式字符串，保持插件 API 兼容）"""
    RESET = ""
    BOLD = "bold"
    DIM = "dim"
    ITALIC = "italic"
    UNDERLINE = "underline"
    RED = "red"
    GREEN = "green"
    YELLOW = "yellow"
    BLUE = "blue"
    MAGENTA = "magenta"
    CYAN = "cyan"
    WHITE = "white"
    GRAY = "bright_black"
    BRIGHT_RED = "bright_red"
    BRIGHT_GREEN = "bright_green"
    BRIGHT_YELLOW = "bright_yellow"
    BRIGHT_BLUE = "bright_blue"
    BRIGHT_MAGENTA = "bright_magenta"
    BRIGHT_CYAN = "bright_cyan"
    BRIGHT_WHITE = "bright_white"
    BG_GRAY = "on bright_black"
    BG_BLUE = "on blue"


def colorize(text, *styles):
    """将文本包装为 rich 样式标记"""
    style_str = " ".join(s for s in styles if s)
    if not style_str:
        return text
    return f"[{style_str}]{text}[/]"


def print_styled(text, *styles, end="\n"):
    if styles:
        text = colorize(text, *styles)
    _console.print(text, end=end)


def separator(*styles):
    style_str = " ".join(s for s in styles if s) or "dim"
    _console.print(Rule(style=style_str))


def panel(text, *styles, title="", icon=""):
    style_str = " ".join(s for s in styles if s) or "cyan"
    title_str = f"{icon} {title}" if icon and title else (title or None)
    _console.print(Panel(text, title=title_str, border_style=style_str, box=ROUNDED))


def prompt_user(prompt_text, *styles):
    if styles:
        prompt_text = colorize(prompt_text, *styles)
    return _console.input(prompt_text)


class RichLog:
    """流式输出日志管理器，基于 rich.live.Live 实现逐块追加 Markdown 渲染"""
    def __init__(self):
        self._live = None
        self._md = ""

    def start(self):
        self._md = ""
        self._live = Live(Markdown(""), console=_console, refresh_per_second=10)
        self._live.start()

    def append(self, chunk: str):
        self._md += chunk
        if self._live:
            self._live.update(Markdown(self._md))

    def stop(self):
        if self._live:
            self._live.stop()
            self._live = None
        self._md = ""


# ================= 注册表（核心机制：插件由此接入，核心不感知具体工具/命令） =================

_TOOLS = {}
_COMMANDS = {}
_TEST_TYPES = {}
_EVALUATORS = {}


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


def command_help_grouped():
    """按类别分组的命令速查（用于启动横幅）"""
    groups = {"通用": [], "导航": [], "模型": [], "测试": []}
    for name in sorted(_COMMANDS):
        if name in ("/help", "/clear", "/exit", "/quit"):
            groups["通用"].append(name)
        elif name in ("/cd", "/pwd", "/write"):
            groups["导航"].append(name)
        elif name in ("/provider", "/model"):
            groups["模型"].append(name)
        elif name.startswith("/test"):
            groups["测试"].append(name)
        else:
            groups["通用"].append(name)
    lines = []
    for cat, cmds in groups.items():
        if cmds:
            lines.append(f"  {colorize(cat, Style.BOLD, Style.BRIGHT_YELLOW)}  {'  '.join(cmds)}")
    return "\n".join(lines)


# ---- 测试类型注册表（类比 K8s CRD）----

def test_type(name, description):
    def deco(cls):
        _TEST_TYPES[name] = {"cls": cls, "description": description}
        return cls
    return deco


def evaluator(name):
    def deco(fn):
        _EVALUATORS[name] = fn
        return fn
    return deco


def test_type_names():
    return list(_TEST_TYPES.keys())


def test_type_help():
    return "\n".join(f"  {n}  {_TEST_TYPES[n]['description']}" for n in sorted(_TEST_TYPES))


def create_test_type(name):
    if name not in _TEST_TYPES:
        raise KeyError(f"未知测试类型: {name}（可用: {', '.join(_TEST_TYPES)}）")
    return _TEST_TYPES[name]["cls"]()


def evaluator_names():
    return list(_EVALUATORS.keys())


def call_evaluator(name, criterion, agent_result):
    if name not in _EVALUATORS:
        return False, f"未知评估器: {name}"
    return _EVALUATORS[name](criterion, agent_result)


# ================= 上下文对象 =================

class Ctx:
    """贯穿工具与命令的上下文。插件只应通过 ctx 读写状态，不直接碰核心内部。"""
    def __init__(self, system_content, root=".", provider=None, model=None):
        self.system_content = system_content
        self.root = os.path.abspath(root)
        self.provider = provider or DEFAULT_PROVIDER
        self.model = model or DEFAULT_MODEL
        self.running = True
        self.messages = []
        self._rebuild_system_prompt()

    def _rebuild_system_prompt(self):
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
        new_root = path if os.path.isabs(path) else os.path.abspath(os.path.join(self.root, path))
        if not os.path.isdir(new_root):
            return False, f"目录不存在: {new_root}"
        self.root = new_root
        self._rebuild_system_prompt()
        return True, new_root

    def resolve(self, path):
        return path if os.path.isabs(path) else os.path.join(self.root, path)

    def get_url(self):
        return PROVIDERS[self.provider]["base_url"]

    def get_headers(self):
        p = PROVIDERS[self.provider]
        auth = ("Bearer " + p["api_key"]) if p.get("auth_scheme", "bearer") == "bearer" else p["api_key"]
        return {"Authorization": auth, "Content-Type": "application/json"}

    def set_provider(self, name):
        if name not in PROVIDERS:
            return False, f"未知供应商: {name}（可用: {', '.join(PROVIDERS)}）"
        self.provider = name
        self.model = PROVIDERS[name]["models"][0]
        return True, f"{name}（模型已重置为 {self.model}）"

    def set_model(self, name):
        self.model = name
        in_list = name in PROVIDERS[self.provider]["models"]
        return True, name + ("" if in_list else f"（注意：{name} 不在 {self.provider} 预设模型列表中）")

    def reset(self):
        self.messages = []
        self._rebuild_system_prompt()

    def print(self, text, *styles):
        if styles:
            text = colorize(text, *styles)
        _console.print(text)


# ================= 工作区感知 =================

def scan_project_context(root_dir: str = ".") -> str:
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
            print_styled(f"⚠️ 加载插件 {dirname}.{name} 失败: {e}", Style.BRIGHT_YELLOW)


# ================= Agent 循环 =================

def _print_tool_result(name, res, preview_limit=500):
    """终端展示工具结果：rich Panel 样式。仅影响展示，传给 AI 的始终是完整 res。"""
    if len(res) <= preview_limit:
        content = res
    else:
        content = (res[:preview_limit]
                   + f"\n... 【结果共 {len(res)} 字符，完整内容已传给 AI，此处仅显示前 {preview_limit} 字符】")
    _console.print(Panel(content, title=f"🔧 {name}", border_style="dim", title_align="left", box=ROUNDED))


def call_llm(ctx: Ctx):
    """流式调用 LLM，支持工具循环执行。核心只做调度，工具逻辑全在插件。"""
    max_rounds = 20
    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        payload = {
            "model": ctx.model,
            "messages": ctx.messages,
            "tools": tool_schemas(),
            "stream": True,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(ctx.get_url(), data=data, headers=ctx.get_headers(), method="POST")
        try:
            response = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            panel(f"❌ HTTP 错误 {e.code}: {body[:200]}", Style.BOLD, Style.BRIGHT_RED, title="错误", icon="⚠")
            break
        except urllib.error.URLError as e:
            panel(f"❌ 连接错误: {e.reason}", Style.BOLD, Style.BRIGHT_RED, title="错误", icon="⚠")
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
                                    "id": tc_id, "type": "function",
                                    "function": {"name": tc.get("function", {}).get("name", ""), "arguments": ""},
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
            ctx.messages.append({"role": "assistant", "content": full_content or None, "tool_calls": tool_calls})
            print_styled("  ⚙ AI 请求调用工具，正在执行...", Style.BOLD, Style.BRIGHT_YELLOW)
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
        print_styled("⚠️ 达到最大工具调用轮数上限，已停止", Style.BRIGHT_YELLOW)


# ================= 主循环 =================

def _print_banner(ctx):
    """打印启动横幅：标题面板 + 信息卡片 + 命令速查"""
    _console.print(Panel(
        "[bold]🚀  CodeAgent-TUI[/bold]\n"
        "纯 Python 标准库 · 插件化架构 · Harness Engineering",
        border_style="bold bright_green", box=ROUNDED,
    ))

    info = Table(show_header=False, box=None, padding=(0, 2))
    info.add_column(style="bold white")
    info.add_column(style="bright_black")
    info.add_row("📂 工作区", ctx.root)
    info.add_row("🤖 模型", f"{ctx.provider} / {ctx.model}")
    info.add_row("🔧 工具", " · ".join(sorted(_TOOLS.keys())) or "（无）")
    info.add_row("📋 测试类型", " · ".join(sorted(_TEST_TYPES.keys())) or "（无）")
    _console.print(info)

    _console.print()
    separator()
    print_styled("  💡 命令速查", Style.BOLD, Style.BRIGHT_CYAN)
    separator()
    _console.print(command_help_grouped())
    separator()
    _console.print()


def main():
    load_plugins("tools")
    load_plugins("commands")
    load_plugins("tests")
    load_plugins("harness")

    ctx = Ctx(system_content, root=".")
    _print_banner(ctx)

    while ctx.running:
        try:
            user_input = prompt_user(colorize("You", Style.BOLD, Style.BRIGHT_BLUE) + " ▶ ")
        except (KeyboardInterrupt, EOFError):
            print_styled("\n  👋 已退出", Style.BOLD, Style.BRIGHT_RED)
            break

        if not user_input.strip():
            continue

        if user_input.startswith("/"):
            cmd, *rest = user_input.split(maxsplit=1)
            arg_str = rest[0] if rest else ""
            if cmd in _COMMANDS:
                call_command(cmd, arg_str, ctx)
            else:
                ctx.print(f"❌ 未知命令: {cmd}（/help 查看可用命令）", Style.BRIGHT_RED)
            continue

        ctx.messages.append({"role": "user", "content": user_input})
        print_styled("  " + colorize("Agent", Style.BOLD, Style.BRIGHT_CYAN) + " ▶")
        try:
            call_llm(ctx)
        except KeyboardInterrupt:
            print_styled("\n  ⏹ 已中断当前对话", Style.BRIGHT_YELLOW)
        separator()


if __name__ == "__main__":
    main()

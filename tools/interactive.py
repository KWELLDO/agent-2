"""交互式会话工具：让 LLM 能与交互式进程（如 REPL、CLI、服务端）来回通信。

设计理念（类比 K8s Pod exec）：
  session_start  → 启动进程（类比 kubectl exec 进入 Pod）
  session_send   → 发送输入并读取输出（类比 stdin → stdout）
  session_close  → 关闭进程（类比 exit）
  session_list   → 列出活跃会话（类比 kubectl get pods）

底层使用 subprocess.Popen + 后台线程持续读取 stdout，
通过 queue.Queue 传递输出，实现非阻塞式交互。
"""
import subprocess
import threading
import queue
import time

from cli import tool, Ctx, Style

# 全局会话注册表
_SESSIONS = {}
_session_counter = 0


def _read_thread(proc, out_queue):
    """后台线程：持续读取进程 stdout，放入 queue。"""
    try:
        for line in proc.stdout:
            try:
                out_queue.put(line.decode("utf-8"))
            except UnicodeDecodeError:
                out_queue.put(line.decode("gbk", errors="replace"))
    except Exception:
        pass


def _drain_queue(q, timeout=0.2):
    """从 queue 中取出所有可用输出。"""
    lines = []
    while True:
        try:
            lines.append(q.get(timeout=timeout))
        except queue.Empty:
            break
    return "".join(lines)


@tool(
    "session_start",
    "启动一个交互式会话进程。返回会话ID和初始输出。后续用 session_send 发送输入、session_close 关闭。"
    "适用于需要来回交互的程序：REPL、CLI工具、交互式脚本、甚至 python -m cli。",
    {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要启动的命令"},
            "wait": {"type": "integer", "description": "等待初始输出的秒数", "default": 2},
        },
        "required": ["command"],
    },
)
def session_start(args, ctx: Ctx):
    global _session_counter
    cmd = args["command"]
    wait = args.get("wait", 2)

    ctx.print(f"🖥️ 启动会话: {cmd}", Style.DIM)

    try:
        proc = subprocess.Popen(
            cmd, shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=ctx.root,
        )
    except Exception as e:
        return f"❌ 启动失败: {e}"

    _session_counter += 1
    sid = f"s{_session_counter}"

    out_queue = queue.Queue()
    reader = threading.Thread(target=_read_thread, args=(proc, out_queue), daemon=True)
    reader.start()

    _SESSIONS[sid] = {
        "proc": proc,
        "reader": reader,
        "queue": out_queue,
        "command": cmd,
    }

    # 等待初始输出
    time.sleep(wait)
    initial = _drain_queue(out_queue)

    result = f"✅ 会话 {sid} 已启动\n命令: {cmd}"
    if initial:
        result += f"\n初始输出:\n{initial}"
    else:
        result += "\n（暂无输出，可能等待输入）"
    return result


@tool(
    "session_send",
    "向交互式会话发送一行输入，等待并返回进程的输出。可多次调用实现来回交互。",
    {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "会话ID（session_start 返回的ID）"},
            "input": {"type": "string", "description": "要发送的输入内容（自动追加换行）"},
            "wait": {"type": "integer", "description": "发送后等待输出的秒数", "default": 3},
        },
        "required": ["session_id", "input"],
    },
)
def session_send(args, ctx: Ctx):
    sid = args["session_id"]
    text = args["input"]
    wait = args.get("wait", 3)

    if sid not in _SESSIONS:
        active = ", ".join(_SESSIONS) or "无"
        return f"❌ 会话不存在: {sid}（活跃会话: {active}）"

    session = _SESSIONS[sid]
    proc = session["proc"]
    q = session["queue"]

    if proc.poll() is not None:
        final = _drain_queue(q)
        del _SESSIONS[sid]
        return f"❌ 会话 {sid} 已结束（退出码 {proc.returncode}）\n剩余输出:\n{final}"

    # 发送输入
    try:
        proc.stdin.write((text + "\n").encode("utf-8"))
        proc.stdin.flush()
    except (BrokenPipeError, OSError):
        return f"❌ 无法发送输入：进程管道已关闭"

    # 等待输出
    time.sleep(wait)
    output = _drain_queue(q)

    if output:
        return f"📤 发送: {text}\n📥 输出:\n{output}"
    else:
        return f"📤 发送: {text}\n（等待 {wait}s 后无新输出）"


@tool(
    "session_close",
    "关闭交互式会话，终止进程并返回最终输出。",
    {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "要关闭的会话ID"},
        },
        "required": ["session_id"],
    },
)
def session_close(args, ctx: Ctx):
    sid = args["session_id"]
    if sid not in _SESSIONS:
        return f"❌ 会话不存在: {sid}"

    session = _SESSIONS[sid]
    proc = session["proc"]
    q = session["queue"]

    # 尝试优雅关闭
    try:
        proc.stdin.close()
    except Exception:
        pass

    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        proc.kill()
        proc.wait(timeout=3)

    # 收集最终输出
    time.sleep(0.3)
    final = _drain_queue(q)

    del _SESSIONS[sid]
    result = f"✅ 会话 {sid} 已关闭（退出码 {proc.returncode}）"
    if final:
        result += f"\n最终输出:\n{final}"
    return result


@tool(
    "session_list",
    "列出当前所有活跃的交互式会话。",
    {
        "type": "object",
        "properties": {},
    },
)
def session_list(args, ctx: Ctx):
    if not _SESSIONS:
        return "当前无活跃会话。用 session_start 启动新会话。"

    lines = []
    for sid, s in _SESSIONS.items():
        proc = s["proc"]
        if proc.poll() is None:
            lines.append(f"  {sid}  [运行中]  {s['command']}")
        else:
            lines.append(f"  {sid}  [已结束:{proc.returncode}]  {s['command']}")

    return f"活跃会话 ({len(_SESSIONS)}):\n" + "\n".join(lines)

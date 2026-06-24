"""内置斜杠命令插件。

扩展示例：在本目录新建 my_cmd.py，写入
    from cli import command, Ctx, Style

    @command("/hi", "打个招呼")
    def hi(arg_str, ctx: Ctx):
        ctx.print("你好！", Style.GREEN)
重启后 /hi 即生效，核心无需任何改动。
"""
import os

from cli import command, Ctx, Style, command_help, command_help_grouped, separator

# 全局状态：保存最近一次测试套件执行结果（供 /testreport /testrun 查询）
_last_suite = None


@command("/exit", "退出程序")
def cmd_exit(arg_str, ctx: Ctx):
    ctx.running = False


@command("/quit", "退出程序")
def cmd_quit(arg_str, ctx: Ctx):
    ctx.running = False


@command("/clear", "清除对话历史")
def cmd_clear(arg_str, ctx: Ctx):
    ctx.reset()
    ctx.print("✅ 对话历史已清除", Style.BRIGHT_GREEN)


@command("/write", "用编辑器打开文件: /write <path>")
def cmd_write(arg_str, ctx: Ctx):
    path = arg_str.strip()
    if not path:
        ctx.print("用法: /write <file_path>", Style.BRIGHT_RED)
        return
    ctx.print(f"正在用默认编辑器打开 {path}...", Style.BRIGHT_YELLOW)
    # 【假设】优先使用 VSCode，降级为 nano/vi
    os.system(f'code "{path}" 2>/dev/null || nano "{path}" || vi "{path}"')


@command("/help", "显示可用命令")
def cmd_help(arg_str, ctx: Ctx):
    separator()
    ctx.print("  💡 可用命令", Style.BOLD, Style.BRIGHT_CYAN)
    separator()
    ctx.print(command_help_grouped())
    separator()


@command("/cd", "切换工作区: /cd <dir>（相对当前或绝对路径）")
def cmd_cd(arg_str, ctx: Ctx):
    path = arg_str.strip()
    if not path:
        ctx.print("用法: /cd <目录路径>", Style.BRIGHT_RED)
        return
    ok, info = ctx.set_workspace(path)
    if ok:
        ctx.print(f"✅ 工作区已切换到: {info}", Style.BRIGHT_GREEN)
        ctx.print("（项目上下文已刷新）", Style.DIM)
    else:
        ctx.print(f"❌ {info}", Style.BRIGHT_RED)


@command("/pwd", "显示当前工作区")
def cmd_pwd(arg_str, ctx: Ctx):
    ctx.print(ctx.root, Style.BRIGHT_CYAN)


@command("/provider", "切换供应商: /provider [name]（无参数列出可用）")
def cmd_provider(arg_str, ctx: Ctx):
    from cli import PROVIDERS
    name = arg_str.strip()
    if not name:
        lines = [f"  {n}{' ← 当前' if n == ctx.provider else ''}  {', '.join(p['models'])}"
                 for n, p in PROVIDERS.items()]
        ctx.print("可用供应商:", Style.BRIGHT_CYAN)
        for line in lines:
            ctx.print(line, Style.GREEN if "← 当前" in line else Style.GRAY)
        return
    ok, info = ctx.set_provider(name)
    ctx.print(("✅ 供应商已切换: " + info) if ok else ("❌ " + info),
              Style.BRIGHT_GREEN if ok else Style.BRIGHT_RED)


@command("/model", "切换模型: /model [name]（无参数列出当前供应商模型）")
def cmd_model(arg_str, ctx: Ctx):
    from cli import PROVIDERS
    name = arg_str.strip()
    if not name:
        models = PROVIDERS[ctx.provider]["models"]
        ctx.print(f"供应商 {ctx.provider} 的模型:", Style.BRIGHT_CYAN)
        for m in models:
            if m == ctx.model:
                ctx.print(f"  {m} ← 当前", Style.BRIGHT_GREEN)
            else:
                ctx.print(f"  {m}", Style.GRAY)
        return
    ok, info = ctx.set_model(name)
    ctx.print(("✅ 模型已切换: " + info) if ok else ("❌ " + info),
              Style.BRIGHT_GREEN if ok else Style.BRIGHT_RED)


# ================= Harness Engineering 测试命令 =================


@command("/test", "运行测试: /test [文件|目录]（无参数运行 testcases/ 下全部）")
def cmd_test(arg_str, ctx: Ctx):
    """执行声明式测试用例，驱动 Agent 完成任务并评估收敛。"""
    global _last_suite
    from harness.controllers import TestSuiteController
    from harness.scheduler import TestScheduler
    from harness.resources import TestSuite, ResourceMetadata, TestCase
    from cli import test_type_help

    if arg_str.strip():
        path = ctx.resolve(arg_str.strip())
        if os.path.isfile(path):
            tc = TestCase.from_json_file(path)
            suite = TestSuite(metadata=ResourceMetadata(name=f"single-{tc.metadata.name}"))
            suite.test_cases = [tc]
        elif os.path.isdir(path):
            scheduler = TestScheduler()
            scheduler.load_testcases_from_dir(path)
            suite = scheduler.build_suite(name=f"dir-{os.path.basename(path)}")
        else:
            ctx.print(f"❌ 路径不存在: {path}", Style.BRIGHT_RED)
            return
    else:
        default_dir = ctx.resolve("testcases")
        if not os.path.isdir(default_dir):
            ctx.print(f"❌ 默认测试目录不存在: {default_dir}", Style.BRIGHT_RED)
            ctx.print("用法: /test <文件路径|目录路径>", Style.BRIGHT_YELLOW)
            return
        scheduler = TestScheduler()
        scheduler.load_testcases_from_dir(default_dir)
        suite = scheduler.build_suite(name="default-suite")

    if not suite.test_cases:
        ctx.print("⚠️ 没有找到可执行的测试用例", Style.BRIGHT_YELLOW)
        return

    ctx.print(f"📋 加载了 {suite.total} 个测试用例", Style.BRIGHT_CYAN)
    ctx.print(f"🤖 可用测试类型:\n{test_type_help()}", Style.DIM)

    controller = TestSuiteController()
    suite = controller.reconcile(suite, ctx, verbose=True)
    _last_suite = suite

    from harness.reporter import ReportGenerator
    reporter = ReportGenerator()
    report = reporter.generate(suite)
    reporter.print_report(report)


@command("/testlist", "列出测试用例: /testlist [目录]（无参数列 testcases/）")
def cmd_testlist(arg_str, ctx: Ctx):
    from harness.scheduler import TestScheduler

    dir_path = arg_str.strip() or "testcases"
    full_path = ctx.resolve(dir_path)
    if not os.path.isdir(full_path):
        ctx.print(f"❌ 目录不存在: {full_path}", Style.BRIGHT_RED)
        return

    scheduler = TestScheduler()
    loaded = scheduler.load_testcases_from_dir(full_path)
    if loaded:
        ctx.print(f"📋 {full_path} 中的测试用例 ({len(loaded)}):", Style.BRIGHT_CYAN)
        for name in loaded:
            ctx.print(f"  • {name}", Style.BRIGHT_GREEN)
    else:
        ctx.print("⚠️ 未找到测试用例", Style.BRIGHT_YELLOW)
    ctx.print(f"\n待执行队列:\n{scheduler.list_pending()}", Style.DIM)


@command("/testtype", "列出已注册的测试类型与评估器")
def cmd_testtype(arg_str, ctx: Ctx):
    from cli import test_type_help, test_type_names, evaluator_names
    ctx.print("📋 已注册测试类型:", Style.BRIGHT_CYAN)
    ctx.print(test_type_help(), Style.BRIGHT_GREEN)
    ctx.print(f"\n📋 已注册评估器: {', '.join(evaluator_names())}", Style.DIM)


@command("/testreport", "生成测试报告: /testreport [json文件路径]")
def cmd_testreport(arg_str, ctx: Ctx):
    global _last_suite
    if not _last_suite:
        ctx.print("❌ 没有已执行的测试套件，请先运行 /test", Style.BRIGHT_RED)
        return

    from harness.reporter import ReportGenerator
    reporter = ReportGenerator()
    report = reporter.generate(_last_suite)
    reporter.print_report(report)

    json_path = arg_str.strip()
    if json_path:
        full_path = ctx.resolve(json_path)
        reporter.save_json(report, full_path)


@command("/testrun", "查看测试运行详情: /testrun [序号]")
def cmd_testrun(arg_str, ctx: Ctx):
    global _last_suite
    if not _last_suite or not _last_suite.runs:
        ctx.print("❌ 没有已执行的测试运行，请先运行 /test", Style.BRIGHT_RED)
        return

    from harness.reporter import ReportGenerator
    reporter = ReportGenerator()

    if arg_str.strip():
        try:
            idx = int(arg_str.strip()) - 1
            if 0 <= idx < len(_last_suite.runs):
                reporter.print_details(_last_suite.runs[idx])
            else:
                ctx.print(f"❌ 序号超出范围（1-{len(_last_suite.runs)}）", Style.BRIGHT_RED)
        except ValueError:
            ctx.print("❌ 请输入数字序号", Style.BRIGHT_RED)
    else:
        ctx.print(f"📋 测试运行列表 ({len(_last_suite.runs)}):", Style.BRIGHT_CYAN)
        for i, run in enumerate(_last_suite.runs):
            icon = "✅" if run.status.value == "Succeeded" else "❌"
            color = Style.BRIGHT_GREEN if run.status.value == "Succeeded" else Style.BRIGHT_RED
            ctx.print(
                f"  [{i+1}] {icon} {run.test_case_name} [{run.status.value}] "
                f"({run.duration:.1f}s)",
                color,
            )
        ctx.print("\n用 /testrun <序号> 查看详情", Style.DIM)

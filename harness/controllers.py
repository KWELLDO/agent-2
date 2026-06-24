"""控制器层：Reconcile Loops 驱动测试生命周期（类比 K8s Controller Manager）。

控制器职责：
  TestRunController         驱动 Agent 执行 → 评估 → 收敛判断 → 反馈注入 → 重复
  TestEnvironmentController  创建/就绪/快照/恢复/销毁测试环境（含沙箱隔离）
  TestSuiteController       批量编排 TestCase + 集成自愈循环 + API 调用预算

设计理念：
  - Reconcile Loop 不追求一次成功，而是持续调谐直到收敛
  - 每轮调谐附带量化反馈，驱动 Agent 向期望状态逼近
  - 失败不是终点，而是触发自愈的事件
"""

import os
import time
import copy
import tempfile
import shutil

from cli import call_llm, call_evaluator, create_test_type, Style, panel, print_styled
from harness.resources import (
    TestCase, TestRun, TestSpec, TestEnvironment, EnvironmentStatus,
    TestStatus, TestSuite, AgentResult, RoundResult, TestReport,
)
from harness.selfheal import SelfHealController, HealAction

# 沙箱模式拷贝工作区时忽略的目录/文件模式
_SANDBOX_IGNORE = shutil.ignore_patterns(
    "__pycache__", ".venv", ".git", "node_modules", "*.pyc"
)


class TestRunController:
    """测试执行控制器（类比 K8s Job Controller）。

    核心调谐循环：Observe(Agent执行) → Diff(评估) → Act(注入反馈) → Repeat
    """

    def reconcile(self, test_case: TestCase, ctx, verbose: bool = True) -> TestRun:
        """执行测试用例，返回 TestRun。

        参数:
            test_case: 声明式测试用例（定义期望状态）
            ctx:       Agent 上下文（会被修改：追加 messages）
            verbose:   是否打印调谐过程
        """
        run = TestRun(
            spec=test_case.spec,
            environment=test_case.environment,
            test_case_name=test_case.metadata.name,
        )
        run.mark_started()

        msg_start = len(ctx.messages)
        ctx.messages.append({"role": "user", "content": test_case.spec.task})

        type_controller = self._get_type_controller(test_case.spec.test_type)

        for round_num in range(1, test_case.spec.max_rounds + 1):
            # 超时检查
            elapsed_total = time.time() - run.started_at
            if elapsed_total > test_case.spec.timeout:
                run.result.error = f"总超时 {elapsed_total:.1f}s > {test_case.spec.timeout}s"
                run.mark_finished(TestStatus.TIMEOUT)
                return run

            if verbose:
                panel(
                    f"🔄 调谐轮次 {round_num}/{test_case.spec.max_rounds} | "
                    f"已用 {elapsed_total:.1f}s/{test_case.spec.timeout}s",
                    Style.BOLD, Style.BRIGHT_CYAN,
                )

            # 调用 Agent（复用核心 call_llm）
            start = time.time()
            try:
                call_llm(ctx)
            except Exception as e:
                run.result.error = str(e)
                run.mark_finished(TestStatus.FAILED)
                return run
            elapsed = time.time() - start

            # 提取 AgentResult
            result = self._extract_result(ctx, msg_start, elapsed)
            run.result = result

            # 评估收敛
            converged, feedback, metrics, passed, total = self._evaluate(
                test_case, result, type_controller
            )

            round_result = RoundResult(
                round=round_num, converged=converged, feedback=feedback,
                metrics=metrics, passed_criteria=passed, total_criteria=total,
            )
            run.add_round(round_result)

            if verbose:
                status = "✅ 已收敛" if converged else "❌ 未收敛"
                print_styled(
                    f"  评估: {passed}/{total} 通过 | {status}",
                    Style.BRIGHT_GREEN if converged else Style.BRIGHT_YELLOW,
                )
                if feedback:
                    print_styled(f"  反馈: {feedback[:200]}", Style.DIM)

            if converged:
                run.mark_finished(TestStatus.SUCCEEDED)
                return run

            # 未收敛，注入反馈
            if round_num < test_case.spec.max_rounds:
                feedback_msg = self._build_feedback(feedback, test_case)
                ctx.messages.append({"role": "user", "content": feedback_msg})

        run.mark_finished(TestStatus.FAILED)
        return run

    def _get_type_controller(self, test_type: str):
        """获取测试类型控制器实例。若未注册则返回 None（降级到逐条评估）。"""
        try:
            return create_test_type(test_type)
        except KeyError:
            return None

    def _extract_result(self, ctx, msg_start: int, elapsed: float) -> AgentResult:
        """从 ctx.messages 增量提取 Agent 执行结果。

        解析消息序列，重建工具调用记录和最终输出。
        """
        new_messages = ctx.messages[msg_start:]
        content = ""
        pending_tc = {}  # tool_call_id -> {name, args, result}
        rounds = 0

        for msg in new_messages:
            role = msg.get("role")
            if role == "assistant":
                if msg.get("content"):
                    content = msg["content"]
                if msg.get("tool_calls"):
                    rounds += 1
                    for tc in msg["tool_calls"]:
                        tc_id = tc.get("id", "")
                        pending_tc[tc_id] = {
                            "name": tc["function"]["name"],
                            "args": tc["function"]["arguments"],
                            "result": "",
                        }
            elif role == "tool":
                tc_id = msg.get("tool_call_id", "")
                if tc_id in pending_tc:
                    pending_tc[tc_id]["result"] = msg.get("content", "")

        return AgentResult(
            content=content,
            tool_calls=list(pending_tc.values()),
            rounds=rounds,
            duration=elapsed,
            messages=copy.deepcopy(new_messages),
        )

    def _evaluate(self, test_case, result, type_controller):
        """执行评估，返回 (converged, feedback, metrics, passed, total)。

        优先使用测试类型控制器的 reconcile 方法；
        若无测试类型控制器，则直接逐条调用评估器。
        """
        if type_controller is not None:
            try:
                converged, feedback, metrics = type_controller.reconcile(
                    test_case, result, None
                )
                passed = metrics.get("passed", 0)
                total = metrics.get("total", 0)
                return converged, feedback, metrics, passed, total
            except Exception:
                pass  # 降级到逐条评估

        criteria = test_case.spec.success_criteria
        if not criteria:
            return True, "", {"passed": 0, "total": 0}, 0, 0

        details = []
        passed_count = 0
        feedback_parts = []

        for criterion in criteria:
            passed, detail = call_evaluator(criterion.type, criterion, result)
            if passed:
                passed_count += 1
            else:
                feedback_parts.append(f"- [{criterion.type}] {detail}")
            details.append({"type": criterion.type, "passed": passed, "detail": detail})

        total = len(criteria)
        converged = passed_count == total
        feedback = "\n".join(feedback_parts) if feedback_parts else ""
        metrics = {"passed": passed_count, "total": total, "details": details}
        return converged, feedback, metrics, passed_count, total

    def _build_feedback(self, feedback: str, test_case: TestCase) -> str:
        """构建注入给 Agent 的反馈消息。"""
        template = test_case.spec.feedback_template
        if template:
            return template.replace("{feedback}", feedback)
        return (
            f"【测试评估反馈】以下评估标准未通过：\n{feedback}\n\n"
            f"请根据上述反馈调整你的回答，确保满足所有评估标准。"
        )


class TestEnvironmentController:
    """测试环境控制器（类比 K8s Namespace Controller + Pod sandbox）。

    生命周期：创建 → 快照 → 就绪 →（自愈时恢复）→ 销毁
    支持 isolated 模式：将工作区拷贝到临时沙箱目录，测试在沙箱中执行，销毁时清理。
    """

    def reconcile(self, env_spec, ctx) -> TestEnvironment:
        """根据 EnvironmentSpec 配置 Ctx，创建并快照 TestEnvironment。

        关键：快照在任何修改之前拍摄，确保 destroy() 能恢复用户原始状态。
        """
        env = TestEnvironment(
            workspace=env_spec.workspace or ctx.root,
            provider=env_spec.provider or ctx.provider,
            model=env_spec.model or ctx.model,
        )
        env._sandbox_dir = ""

        # 先快照原始状态（在任何修改之前）
        env.snapshot_ctx(ctx)

        # isolated 模式：拷贝工作区到临时沙箱目录
        if env_spec.isolated:
            env._sandbox_dir = tempfile.mkdtemp(prefix="harness_sandbox_")
            shutil.copytree(
                ctx.root, env._sandbox_dir,
                ignore=_SANDBOX_IGNORE, dirs_exist_ok=True,
            )
            ctx.set_workspace(env._sandbox_dir)
        elif env_spec.workspace and env_spec.workspace != ".":
            ok, info = ctx.set_workspace(env_spec.workspace)
            if not ok:
                env.status = EnvironmentStatus.DESTROYED
                return env

        if env_spec.provider:
            ctx.set_provider(env_spec.provider)

        if env_spec.model:
            ctx.set_model(env_spec.model)

        env.status = EnvironmentStatus.READY
        return env

    def destroy(self, env: TestEnvironment, ctx):
        """销毁测试环境，恢复 Ctx 到快照状态，清理沙箱临时目录。"""
        env.restore_ctx(ctx)
        env.status = EnvironmentStatus.DESTROYED
        # 清理沙箱临时目录
        sandbox_dir = getattr(env, "_sandbox_dir", "")
        if sandbox_dir and os.path.isdir(sandbox_dir):
            shutil.rmtree(sandbox_dir, ignore_errors=True)


class TestSuiteController:
    """测试套件控制器（类比 K8s Deployment Controller）。

    管理 TestSuite 中所有 TestCase 的批量执行：
    1. 为每个 TestCase 创建 TestEnvironment
    2. 执行 TestRun（含自愈循环）
    3. 清理环境

    含全局 API 调用预算保护，防止大量测试耗尽 LLM 配额。
    """

    # 默认全局 API 调用预算（每轮调谐计为 1 次调用）
    DEFAULT_API_BUDGET = 50

    def __init__(self, api_budget: int = None):
        self.run_controller = TestRunController()
        self.env_controller = TestEnvironmentController()
        self.heal_controller = SelfHealController()
        self.api_budget = api_budget if api_budget is not None else self.DEFAULT_API_BUDGET
        self.api_calls = 0

    def reconcile(self, suite: TestSuite, ctx, verbose: bool = True) -> TestSuite:
        """执行测试套件中的所有 TestCase。"""
        for i, tc in enumerate(suite.test_cases):
            # API 预算检查
            if self.api_calls >= self.api_budget:
                if verbose:
                    print_styled(
                        f"⚠️ 达到 API 调用预算上限 {self.api_budget}，"
                        f"停止执行剩余测试（已用 {self.api_calls} 次）",
                        Style.BRIGHT_YELLOW,
                    )
                # 将剩余用例标记为 SKIPPED
                for remaining_tc in suite.test_cases[i:]:
                    run = TestRun(test_case_name=remaining_tc.metadata.name)
                    run.mark_started()
                    run.result.error = "API 调用预算耗尽"
                    run.mark_finished(TestStatus.SKIPPED)
                    suite.runs.append(run)
                break

            if verbose:
                panel(
                    f"📋 [{i+1}/{suite.total}] 执行测试用例: {tc.metadata.name}",
                    Style.BOLD, Style.BRIGHT_BLUE,
                )

            # 创建环境
            env = self.env_controller.reconcile(tc.environment, ctx)
            if env.status != EnvironmentStatus.READY:
                run = TestRun(test_case_name=tc.metadata.name)
                run.mark_started()
                run.result.error = "环境创建失败"
                run.mark_finished(TestStatus.FAILED)
                suite.runs.append(run)
                continue

            # 执行测试（含自愈）
            run = self._execute_with_healing(tc, ctx, env, verbose)
            # 累计 API 调用数（每轮调谐计为 1 次调用）
            self.api_calls += len(run.convergence_history)
            suite.runs.append(run)

            # 清理环境
            self.env_controller.destroy(env, ctx)

        if verbose:
            print_styled(suite.summary(), Style.BRIGHT_CYAN)

        return suite

    def _execute_with_healing(self, test_case: TestCase, ctx, env: TestEnvironment,
                              verbose: bool = True) -> TestRun:
        """执行测试，失败时触发自愈循环。

        自愈流程：
        1. 执行 TestRun
        2. 若失败 → 诊断原因 → 执行恢复动作 → 注入失败反馈 → 重新执行
        3. 重复直到成功或达到最大重试次数
        """
        max_retries = test_case.spec.max_retries
        all_heal_actions = []
        all_rounds = []
        retry_count = 0

        while True:
            # 执行测试
            run = self.run_controller.reconcile(test_case, ctx, verbose)
            run.retry_count = retry_count

            # 合并历史记录
            if all_heal_actions:
                run.heal_actions = list(all_heal_actions) + list(run.heal_actions)
            if all_rounds:
                run.convergence_history = list(all_rounds) + list(run.convergence_history)

            # 成功或无法继续
            if run.status == TestStatus.SUCCEEDED:
                return run
            if retry_count >= max_retries:
                if verbose:
                    print_styled(
                        f"⚠️ 达到最大重试次数 {max_retries}，停止自愈",
                        Style.BRIGHT_YELLOW,
                    )
                return run

            # 诊断失败原因
            action, reason = self.heal_controller.diagnose(run)
            if action == HealAction.PERMANENT_FAIL:
                run.add_heal_action(action, reason)
                if verbose:
                    print_styled(f"⛔ 永久失败: {reason}", Style.BRIGHT_RED)
                return run

            if verbose:
                panel(
                    f"🔧 自愈触发: {action.value}（{reason}）| "
                    f"重试 {retry_count + 1}/{max_retries}",
                    Style.BOLD, Style.BRIGHT_YELLOW,
                )

            # 记录自愈动作
            all_heal_actions.append({
                "action": action.value, "reason": reason, "timestamp": time.time()
            })
            all_rounds = list(run.convergence_history)
            retry_count += 1

            # 执行恢复动作
            self.heal_controller.execute(action, run, ctx, env)

            # 重置对话历史（仅保留 system prompt，不追加 task——由 reconcile 统一负责）
            system_msgs = [m for m in ctx.messages if m.get("role") == "system"]
            ctx.messages = system_msgs

            # RETRY 动作：注入上轮失败反馈，让 Agent 在重试时知道问题所在
            if action == HealAction.RETRY and run.convergence_history:
                last_feedback = run.convergence_history[-1].feedback
                if last_feedback:
                    feedback_msg = self.run_controller._build_feedback(
                        last_feedback, test_case
                    )
                    ctx.messages.append({"role": "user", "content": feedback_msg})

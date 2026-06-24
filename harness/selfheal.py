"""自愈控制器（类比 K8s livenessProbe + restartPolicy）。

当 TestRun 失败时，诊断失败原因并决策恢复策略：

  失败类型           诊断依据                    自愈动作
  ─────────────────────────────────────────────────────────
  执行超时           status == TIMEOUT           BACKOFF（指数退避后重试）
  工具执行超时        error 含 "timeout"          BACKOFF
  API 限流            error 含 "429"/"rate"       SWITCH_MODEL（切换模型）
  连接错误            error 含 "connection"       BACKOFF
  工具异常            error 含 "tool"             REBUILD_ENV（从快照恢复环境）
  评估未通过          无错误，标准未满足           RETRY（直接重试 + 注入反馈）
  未知错误            不匹配任何规则              PERMANENT_FAIL（标记永久失败）
"""

import time

from harness.resources import HealAction, TestRun, TestStatus, TestEnvironment


class SelfHealController:
    """自愈控制器：诊断失败 → 决策恢复策略 → 执行恢复动作。

    设计理念（类比 K8s）：
    - 诊断类比 livenessProbe：检测「不健康」状态
    - 恢复类比 restartPolicy：根据策略重启/重建/迁移
    - 退避类比 exponential back-off：避免雪崩式重试
    """

    # 诊断规则（按优先级排序）：(匹配函数, 动作, 原因描述)
    DIAGNOSIS_RULES = [
        (
            lambda run: run.status == TestStatus.TIMEOUT,
            HealAction.BACKOFF,
            "执行超时",
        ),
        (
            lambda run: "timeout" in run.result.error.lower(),
            HealAction.BACKOFF,
            "工具执行超时",
        ),
        (
            lambda run: "429" in run.result.error or "rate" in run.result.error.lower(),
            HealAction.SWITCH_MODEL,
            "API 限流",
        ),
        (
            lambda run: "connection" in run.result.error.lower()
            or "urlerror" in run.result.error.lower(),
            HealAction.BACKOFF,
            "连接错误",
        ),
        (
            lambda run: run.result.has_error and "tool" in run.result.error.lower(),
            HealAction.REBUILD_ENV,
            "工具执行异常",
        ),
        (
            lambda run: not run.result.has_error,
            HealAction.RETRY,
            "评估标准未满足",
        ),
    ]

    def diagnose(self, run: TestRun):
        """诊断失败原因，返回 (action: HealAction, reason: str)。"""
        for matcher, action, reason in self.DIAGNOSIS_RULES:
            try:
                if matcher(run):
                    return action, reason
            except Exception:
                continue
        return HealAction.PERMANENT_FAIL, "未知失败原因"

    def execute(self, action: HealAction, run: TestRun, ctx, env: TestEnvironment):
        """执行自愈动作，修改 ctx 和 env 状态。

        参数:
            action: 自愈动作类型
            run:    当前失败的 TestRun（用于读取 retry_count 等）
            ctx:    Ctx 上下文（可能被修改）
            env:    TestEnvironment（可能被恢复）
        """
        if action == HealAction.RETRY:
            # 直接重试——由调用方注入反馈后重新执行
            pass
        elif action == HealAction.REBUILD_ENV:
            # 从快照恢复环境——清除污染状态
            env.restore_ctx(ctx)
        elif action == HealAction.SWITCH_MODEL:
            # 切换到同供应商的其他模型——规避限流
            self._switch_to_alternative_model(ctx)
        elif action == HealAction.BACKOFF:
            # 指数退避等待——2^retry_count 秒，上限 30s
            wait = min(2 ** run.retry_count, 30)
            time.sleep(wait)
        elif action == HealAction.PERMANENT_FAIL:
            # 不做任何恢复——标记为永久失败
            pass

    def _switch_to_alternative_model(self, ctx):
        """尝试切换到当前供应商的其他模型。"""
        from cli import PROVIDERS
        models = PROVIDERS.get(ctx.provider, {}).get("models", [])
        if not models:
            return
        current_idx = models.index(ctx.model) if ctx.model in models else 0
        next_idx = (current_idx + 1) % len(models)
        ctx.set_model(models[next_idx])

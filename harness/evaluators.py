"""内置评估器（类比 K8s Validation Webhook）。

评估器在声明式测试规范的 successCriteria 中通过 type 字段引用。
每个评估器接收 (criterion: EvaluationCriterion, result: AgentResult)
并返回 (passed: bool, detail: str)。

已注册评估器：
  tool_coverage   检查 Agent 是否调用了指定工具
  output_contains 检查输出是否包含期望关键词
  max_rounds      检查工具调用轮数是否在限制内
  latency         检查执行延迟是否在限制内
  no_error        检查执行过程中是否有错误
  convergence     检查最终收敛状态（是否有有效输出）
"""

from cli import evaluator
from harness.resources import EvaluationCriterion, AgentResult


@evaluator("tool_coverage")
def eval_tool_coverage(criterion: EvaluationCriterion, result: AgentResult):
    """检查 Agent 是否调用了指定的工具。

    criterion.tool: 期望调用的工具名
    criterion.required: True=必须调用, False=不应调用
    """
    tool = criterion.tool
    if not tool:
        return True, "未指定工具名，跳过"
    called = tool in result.tool_names
    if criterion.required:
        return (called, f"工具 '{tool}' 已调用" if called
                else f"工具 '{tool}' 未被调用（期望: 必须调用）")
    else:
        return (not called, f"工具 '{tool}' 未调用（符合预期）" if not called
                else f"工具 '{tool}' 被调用了（期望: 不应调用）")


@evaluator("output_contains")
def eval_output_contains(criterion: EvaluationCriterion, result: AgentResult):
    """检查 Agent 输出是否包含期望关键词。

    criterion.keywords: 期望关键词列表
    criterion.min_match: 最少匹配数（默认=全部）
    """
    keywords = criterion.keywords or []
    if not keywords:
        return True, "未指定关键词，跳过"
    content = result.content.lower()
    matched = [kw for kw in keywords if kw.lower() in content]
    min_match = criterion.min_match or len(keywords)
    passed = len(matched) >= min_match
    detail = f"匹配 {len(matched)}/{len(keywords)}: {matched}"
    if not passed:
        missing = [kw for kw in keywords if kw.lower() not in content]
        detail += f"（缺少: {missing}）"
    return passed, detail


@evaluator("max_rounds")
def eval_max_rounds(criterion: EvaluationCriterion, result: AgentResult):
    """检查工具调用轮数是否在限制内。

    criterion.value: 最大允许轮数（默认 10）
    """
    limit = criterion.value if criterion.value is not None else 10
    passed = result.rounds <= limit
    return passed, f"轮数 {result.rounds}/{limit}" + ("" if passed else "（超出限制）")


@evaluator("latency")
def eval_latency(criterion: EvaluationCriterion, result: AgentResult):
    """检查执行延迟是否在限制内。

    criterion.value: 最大允许延迟秒数（默认 60）
    """
    limit = criterion.value if criterion.value is not None else 60
    passed = result.duration <= limit
    return passed, f"延迟 {result.duration:.1f}s/{limit}s" + ("" if passed else "（超时）")


@evaluator("no_error")
def eval_no_error(criterion: EvaluationCriterion, result: AgentResult):
    """检查 Agent 执行过程中是否有错误。"""
    passed = not result.has_error
    return passed, "无错误" if passed else f"有错误: {result.error[:80]}"


@evaluator("convergence")
def eval_convergence(criterion: EvaluationCriterion, result: AgentResult):
    """检查收敛状态：最终是否产生了有效输出。

    收敛 = 有非空输出 且 无错误。
    """
    passed = bool(result.content.strip()) and not result.has_error
    if passed:
        return True, "已收敛（输出有效）"
    elif result.has_error:
        return False, f"未收敛（有错误: {result.error[:60]}）"
    else:
        return False, "未收敛（输出为空）"

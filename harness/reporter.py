"""测试报告生成器（类比 kubectl describe + metrics-server）。

提供多格式报告生成：终端文本、JSON 文件、单条 TestRun 详情。
"""

import json
import os
import time

from cli import print_styled, Style, separator
from harness.resources import TestSuite, TestReport, TestStatus


class ReportGenerator:
    """测试报告生成器。

    职责：
    - 从 TestSuite 聚合结果生成 TestReport
    - 终端渲染报告摘要
    - 持久化报告为 JSON 文件
    - 打印单个 TestRun 的详细信息（类比 kubectl describe pod）
    """

    def generate(self, suite: TestSuite) -> TestReport:
        """从 TestSuite 生成 TestReport。"""
        report = TestReport()
        report.generate(suite)
        return report

    def print_report(self, report: TestReport):
        """在终端打印报告。"""
        separator()
        print_styled(report.to_text(), Style.BRIGHT_CYAN)
        separator()

    def save_json(self, report: TestReport, path: str):
        """将报告保存为 JSON 文件。"""
        data = {
            "suiteName": report.suite_name,
            "generatedAt": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(report.generated_at)
            ),
            "metrics": report.metrics,
            "runs": [
                {
                    "name": r.metadata.name,
                    "testCase": r.test_case_name,
                    "status": r.status.value,
                    "duration": round(r.duration, 2),
                    "rounds": len(r.convergence_history),
                    "retries": r.retry_count,
                    "healActions": len(r.heal_actions),
                    "toolCalls": len(r.result.tool_calls),
                    "error": r.result.error if r.result.has_error else "",
                }
                for r in report.runs
            ],
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print_styled(f"📄 报告已保存: {path}", Style.BRIGHT_GREEN)

    def print_details(self, run):
        """打印单个 TestRun 的详细信息（类比 kubectl describe pod）。"""
        bar = "─" * 50
        lines = [
            f"  {bar}",
            f"  TestRun Details: {run.metadata.name}",
            f"  {bar}",
            f"  Status:       {run.status.value}",
            f"  TestCase:     {run.test_case_name}",
            f"  Retries:      {run.retry_count}",
            f"  Duration:     {run.duration:.1f}s",
            f"  Rounds:       {len(run.convergence_history)}",
            f"  Tool Calls:   {len(run.result.tool_calls)}",
            f"  Heal Actions: {len(run.heal_actions)}",
        ]

        if run.result.tool_calls:
            lines.append("")
            lines.append("  Tool Calls:")
            for i, tc in enumerate(run.result.tool_calls):
                lines.append(f"    {i+1}. {tc['name']}")

        if run.convergence_history:
            lines.append("")
            lines.append("  Convergence History:")
            for r in run.convergence_history:
                icon = "✅" if r.converged else "❌"
                lines.append(
                    f"    Round {r.round}: {icon} {r.passed_criteria}/"
                    f"{r.total_criteria} criteria passed"
                )

        if run.heal_actions:
            lines.append("")
            lines.append("  Heal Actions:")
            for ha in run.heal_actions:
                lines.append(f"    - {ha['action']}: {ha['reason']}")

        if run.result.has_error:
            lines.append("")
            lines.append(f"  Error: {run.result.error}")

        if run.result.content:
            lines.append("")
            lines.append("  Agent Output (truncated):")
            preview = run.result.content[:300]
            lines.append(f"    {preview}{'...' if len(run.result.content) > 300 else ''}")

        lines.append(f"  {bar}")
        print_styled("\n".join(lines), Style.BRIGHT_CYAN)

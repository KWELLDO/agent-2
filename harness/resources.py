"""资源模型：将测试生命周期中的实体抽象为 K8s 风格的资源对象。

每个资源类比 K8s 资源（Pod/Job/ConfigMap 等），具有 apiVersion/kind/metadata/spec/status
标准结构，支持声明式定义（JSON）和运行时状态追踪。

资源层级：
  TestSuite  ──类比 Deployment── 管理一组 TestCase
  TestCase   ──类比 Pod Template─ 声明式测试规范（期望状态）
  TestRun    ──类比 Job───────── 一次测试执行实例
  TestEnvironment ──类比 Namespace+Pod sandbox── 隔离环境 + 快照/恢复
  TestReport ──类比 kubectl describe── 聚合结果与度量
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import time
import uuid
import json
import copy


# ================= 状态枚举（类比 K8s Pod Phase） =================

class TestStatus(Enum):
    PENDING = "Pending"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    RETRYING = "Retrying"
    SKIPPED = "Skipped"
    TIMEOUT = "Timeout"


class EnvironmentStatus(Enum):
    CREATING = "Creating"
    READY = "Ready"
    DESTROYED = "Destroyed"


class HealAction(Enum):
    """自愈动作类型（类比 restartPolicy / livenessProbe 触发的恢复）"""
    RETRY = "retry"
    REBUILD_ENV = "rebuild_environment"
    SWITCH_MODEL = "switch_model"
    BACKOFF = "backoff_retry"
    PERMANENT_FAIL = "permanent_fail"


# ================= 评估标准（声明式 successCriteria） =================

@dataclass
class EvaluationCriterion:
    """单个评估标准。在声明式测试规范中通过 type 字段引用已注册的评估器。"""
    type: str
    tool: str = ""
    required: bool = True
    keywords: list = field(default_factory=list)
    min_match: int = 0
    value: Any = None
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d):
        known = {"type", "tool", "required", "keywords", "min_match", "value"}
        extra = {k: v for k, v in d.items() if k not in known}
        return cls(
            type=d.get("type", ""),
            tool=d.get("tool", ""),
            required=d.get("required", True),
            keywords=d.get("keywords", []),
            min_match=d.get("min_match", 0),
            value=d.get("value"),
            extra=extra,
        )


# ================= Spec 层 =================

@dataclass
class TestSpec:
    """测试规范：定义期望状态（类比 K8s PodSpec）"""
    agent: str = "codeagent-tui"
    task: str = ""
    test_type: str = "behavioral"
    success_criteria: list = field(default_factory=list)
    max_rounds: int = 5
    max_retries: int = 3
    timeout: float = 120.0
    feedback_template: str = ""

    @classmethod
    def from_dict(cls, d):
        criteria = [EvaluationCriterion.from_dict(c) for c in d.get("successCriteria", [])]
        return cls(
            agent=d.get("agent", "codeagent-tui"),
            task=d.get("task", ""),
            test_type=d.get("testType", "behavioral"),
            success_criteria=criteria,
            max_rounds=d.get("maxRounds", 5),
            max_retries=d.get("maxRetries", 3),
            timeout=d.get("timeout", 120.0),
            feedback_template=d.get("feedbackTemplate", ""),
        )


@dataclass
class EnvironmentSpec:
    """测试环境规范"""
    workspace: str = "."
    provider: str = ""
    model: str = ""
    isolated: bool = False

    @classmethod
    def from_dict(cls, d):
        return cls(
            workspace=d.get("workspace", "."),
            provider=d.get("provider", ""),
            model=d.get("model", ""),
            isolated=d.get("isolated", False),
        )


# ================= Metadata（类比 ObjectMeta） =================

@dataclass
class ResourceMetadata:
    name: str = ""
    labels: dict = field(default_factory=dict)
    creation_timestamp: float = field(default_factory=time.time)

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=d.get("name", ""),
            labels=d.get("labels", {}),
            creation_timestamp=d.get("creationTimestamp", time.time()),
        )


# ================= Agent 执行结果封装 =================

@dataclass
class AgentResult:
    """收集 Agent 执行过程中的所有可观测数据"""
    content: str = ""
    tool_calls: list = field(default_factory=list)  # [{name, args, result}, ...]
    rounds: int = 0
    duration: float = 0.0
    messages: list = field(default_factory=list)
    error: str = ""

    @property
    def tool_names(self):
        seen = []
        for tc in self.tool_calls:
            if tc["name"] not in seen:
                seen.append(tc["name"])
        return seen

    @property
    def has_error(self):
        return bool(self.error)


@dataclass
class RoundResult:
    """单轮调谐结果（用于收敛历史追踪）"""
    round: int
    converged: bool
    feedback: str
    metrics: dict
    passed_criteria: int
    total_criteria: int


# ================= 核心资源对象 =================

@dataclass
class TestCase:
    """测试用例资源（类比 K8s Pod Template）"""
    api_version: str = "harness.agent/v1"
    kind: str = "TestCase"
    metadata: ResourceMetadata = field(default_factory=ResourceMetadata)
    spec: TestSpec = field(default_factory=TestSpec)
    environment: EnvironmentSpec = field(default_factory=EnvironmentSpec)

    @classmethod
    def from_dict(cls, d):
        return cls(
            api_version=d.get("apiVersion", "harness.agent/v1"),
            kind=d.get("kind", "TestCase"),
            metadata=ResourceMetadata.from_dict(d.get("metadata", {})),
            spec=TestSpec.from_dict(d.get("spec", {})),
            environment=EnvironmentSpec.from_dict(d.get("environment", {})),
        )

    @classmethod
    def from_json_file(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_dict(self):
        return {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {"name": self.metadata.name, "labels": self.metadata.labels},
            "spec": {
                "agent": self.spec.agent,
                "task": self.spec.task,
                "testType": self.spec.test_type,
                "successCriteria": [
                    {"type": c.type, "tool": c.tool, "required": c.required,
                     "keywords": c.keywords, "minMatch": c.min_match, "value": c.value, **c.extra}
                    for c in self.spec.success_criteria
                ],
                "maxRounds": self.spec.max_rounds,
                "maxRetries": self.spec.max_retries,
                "timeout": self.spec.timeout,
            },
            "environment": {
                "workspace": self.environment.workspace,
                "provider": self.environment.provider,
                "model": self.environment.model,
                "isolated": self.environment.isolated,
            },
        }


@dataclass
class TestRun:
    """测试执行实例（类比 K8s Job）"""
    api_version: str = "harness.agent/v1"
    kind: str = "TestRun"
    metadata: ResourceMetadata = field(default_factory=ResourceMetadata)
    spec: TestSpec = field(default_factory=TestSpec)
    environment: EnvironmentSpec = field(default_factory=EnvironmentSpec)
    status: TestStatus = TestStatus.PENDING
    result: AgentResult = field(default_factory=AgentResult)
    retry_count: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    convergence_history: list = field(default_factory=list)
    heal_actions: list = field(default_factory=list)
    test_case_name: str = ""

    def __post_init__(self):
        if not self.metadata.name:
            self.metadata.name = f"testrun-{uuid.uuid4().hex[:8]}"

    @property
    def duration(self):
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return 0.0

    @property
    def is_terminal(self):
        return self.status in (TestStatus.SUCCEEDED, TestStatus.FAILED,
                               TestStatus.SKIPPED, TestStatus.TIMEOUT)

    def mark_started(self):
        self.status = TestStatus.RUNNING
        self.started_at = time.time()

    def mark_finished(self, status):
        self.status = status
        self.finished_at = time.time()

    def add_round(self, round_result):
        self.convergence_history.append(round_result)

    def add_heal_action(self, action, reason):
        self.heal_actions.append({
            "action": action.value, "reason": reason, "timestamp": time.time()
        })

    def summary(self):
        lines = [
            f"TestRun: {self.metadata.name}",
            f"  Status: {self.status.value}",
            f"  TestCase: {self.test_case_name}",
            f"  Retries: {self.retry_count}",
            f"  Duration: {self.duration:.1f}s",
            f"  Rounds: {len(self.convergence_history)}",
            f"  Tool Calls: {len(self.result.tool_calls)}",
            f"  Heal Actions: {len(self.heal_actions)}",
        ]
        if self.result.has_error:
            lines.append(f"  Error: {self.result.error[:100]}")
        return "\n".join(lines)


@dataclass
class TestEnvironment:
    """测试环境（类比 K8s Namespace + Pod sandbox）

    支持 Ctx 快照与恢复——自愈时从干净快照重建环境，避免污染状态残留。
    """
    workspace: str = "."
    provider: str = ""
    model: str = ""
    status: EnvironmentStatus = EnvironmentStatus.CREATING
    ctx_snapshot: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def snapshot_ctx(self, ctx):
        self.ctx_snapshot = {
            "root": ctx.root,
            "provider": ctx.provider,
            "model": ctx.model,
            "messages": copy.deepcopy(ctx.messages),
            "system_content": ctx.system_content,
        }

    def restore_ctx(self, ctx):
        if not self.ctx_snapshot:
            return
        ctx.root = self.ctx_snapshot["root"]
        ctx.provider = self.ctx_snapshot["provider"]
        ctx.model = self.ctx_snapshot["model"]
        ctx.messages = copy.deepcopy(self.ctx_snapshot["messages"])
        ctx.system_content = self.ctx_snapshot["system_content"]
        ctx._rebuild_system_prompt()


@dataclass
class TestSuite:
    """测试套件（类比 K8s Deployment：管理一组 TestCase 的批量执行）"""
    api_version: str = "harness.agent/v1"
    kind: str = "TestSuite"
    metadata: ResourceMetadata = field(default_factory=ResourceMetadata)
    test_cases: list = field(default_factory=list)
    runs: list = field(default_factory=list)
    concurrency: int = 1  # 预留：当前仅支持顺序执行，未来可扩展为并行

    @property
    def total(self):
        return len(self.test_cases)

    @property
    def passed(self):
        return sum(1 for r in self.runs if r.status == TestStatus.SUCCEEDED)

    @property
    def failed(self):
        return sum(1 for r in self.runs if r.status in (TestStatus.FAILED, TestStatus.TIMEOUT))

    @property
    def skipped(self):
        return sum(1 for r in self.runs if r.status == TestStatus.SKIPPED)

    @property
    def pending(self):
        return self.total - len(self.runs)

    @property
    def pass_rate(self):
        return (self.passed / self.total * 100) if self.total > 0 else 0.0

    def summary(self):
        return (
            f"TestSuite: {self.metadata.name}\n"
            f"  Total: {self.total} | Passed: {self.passed} | Failed: {self.failed} | "
            f"Skipped: {self.skipped} | Pending: {self.pending}\n"
            f"  Pass Rate: {self.pass_rate:.1f}%"
        )


@dataclass
class TestReport:
    """测试报告（类比 kubectl describe 输出 + metrics-server）"""
    suite_name: str = ""
    runs: list = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)
    metrics: dict = field(default_factory=dict)

    def generate(self, suite):
        self.suite_name = suite.metadata.name
        self.runs = list(suite.runs)
        durations = [r.duration for r in suite.runs if r.duration > 0]
        total_rounds = sum(len(r.convergence_history) for r in suite.runs)
        total_heals = sum(len(r.heal_actions) for r in suite.runs)
        total_tool_calls = sum(len(r.result.tool_calls) for r in suite.runs)
        self.metrics = {
            "total": suite.total,
            "passed": suite.passed,
            "failed": suite.failed,
            "skipped": suite.skipped,
            "pass_rate": round(suite.pass_rate, 1),
            "avg_duration": round(sum(durations) / len(durations), 1) if durations else 0,
            "max_duration": round(max(durations), 1) if durations else 0,
            "min_duration": round(min(durations), 1) if durations else 0,
            "total_rounds": total_rounds,
            "total_heal_actions": total_heals,
            "total_tool_calls": total_tool_calls,
        }

    def to_text(self):
        lines = [
            f"{'='*60}",
            f"  Test Report: {self.suite_name}",
            f"  Generated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.generated_at))}",
            f"{'='*60}",
            "",
            "  Summary:",
            f"    Total: {self.metrics.get('total', 0)}",
            f"    Passed: {self.metrics.get('passed', 0)}",
            f"    Failed: {self.metrics.get('failed', 0)}",
            f"    Skipped: {self.metrics.get('skipped', 0)}",
            f"    Pass Rate: {self.metrics.get('pass_rate', 0)}%",
            "",
            "  Performance:",
            f"    Avg Duration: {self.metrics.get('avg_duration', 0)}s",
            f"    Max Duration: {self.metrics.get('max_duration', 0)}s",
            f"    Min Duration: {self.metrics.get('min_duration', 0)}s",
            "",
            "  Harness:",
            f"    Total Rounds: {self.metrics.get('total_rounds', 0)}",
            f"    Total Heal Actions: {self.metrics.get('total_heal_actions', 0)}",
            f"    Total Tool Calls: {self.metrics.get('total_tool_calls', 0)}",
            "",
            f"{'='*60}",
            "  Details:",
        ]
        for r in self.runs:
            icon = "✅" if r.status == TestStatus.SUCCEEDED else "❌"
            extra = f", {len(r.heal_actions)} heals" if r.heal_actions else ""
            lines.append(
                f"    {icon} {r.test_case_name} [{r.status.value}] "
                f"({r.duration:.1f}s, {len(r.convergence_history)} rounds{extra})"
            )
        lines.append(f"{'='*60}")
        return "\n".join(lines)

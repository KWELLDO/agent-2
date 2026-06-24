"""测试调度器（类比 K8s Scheduler）。

负责测试用例的队列管理、优先级排序和调度执行。
当前为单线程顺序执行，但接口设计支持未来扩展为并发调度。

类比映射：
  队列管理   ↔ Pending Pod 队列
  优先级     ↔ PriorityClass
  批量加载   ↔ kubectl apply -f <directory>
"""

import os

from cli import print_styled, Style
from harness.resources import TestCase, TestSuite, ResourceMetadata


class TestScheduler:
    """测试调度器：管理 TestCase 队列，按优先级调度执行。"""

    def __init__(self):
        self.queue = []  # [(priority, seq, test_case)]
        self._seq = 0

    def enqueue(self, test_case: TestCase, priority: int = 0):
        """将 TestCase 加入调度队列。

        priority: 数值越大优先级越高（类比 K8s PriorityClass）
        """
        self._seq += 1
        self.queue.append((priority, self._seq, test_case))
        self.queue.sort(key=lambda x: (-x[0], x[1]))

    def enqueue_suite(self, suite: TestSuite, priority: int = 0):
        """将 TestSuite 中所有 TestCase 加入队列。"""
        for tc in suite.test_cases:
            self.enqueue(tc, priority)

    def dequeue(self):
        """取出下一个待执行的 TestCase。"""
        if not self.queue:
            return None
        return self.queue.pop(0)[2]

    @property
    def pending_count(self):
        return len(self.queue)

    @property
    def is_empty(self):
        return len(self.queue) == 0

    def build_suite(self, name: str = "scheduled-suite") -> TestSuite:
        """将队列中所有 TestCase 构建为 TestSuite 并清空队列。"""
        suite = TestSuite()
        suite.metadata = ResourceMetadata(name=name)
        suite.test_cases = [item[2] for item in self.queue]
        self.queue.clear()
        return suite

    def load_testcases_from_dir(self, dir_path: str, priority: int = 0):
        """从目录加载所有 JSON 格式的测试用例（类比 kubectl apply -f <dir>）。

        支持从 labels.priority 读取优先级覆盖默认值。
        """
        loaded = []
        if not os.path.isdir(dir_path):
            print_styled(f"⚠️ 目录不存在: {dir_path}", Style.BRIGHT_YELLOW)
            return loaded

        for fname in sorted(os.listdir(dir_path)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(dir_path, fname)
            try:
                tc = TestCase.from_json_file(fpath)
                label_priority = tc.metadata.labels.get("priority")
                p = int(label_priority) if label_priority else priority
                self.enqueue(tc, p)
                loaded.append(tc.metadata.name)
            except Exception as e:
                print_styled(f"⚠️ 加载测试用例 {fname} 失败: {e}", Style.BRIGHT_YELLOW)

        return loaded

    def list_pending(self):
        """列出队列中待执行的测试用例。"""
        if not self.queue:
            return "（队列为空）"
        lines = [f"  [{i+1}] (priority={p}) {tc.metadata.name}"
                 for i, (p, _, tc) in enumerate(self.queue)]
        return "\n".join(lines)

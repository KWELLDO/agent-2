"""Agent Harness Engineering 模块。

将 Kubernetes 设计理念（声明式 API、控制器模式、资源抽象、自愈能力、
可扩展性）与 Agent 测试工程深度结合。

模块组成：
  - resources.py   资源模型（TestSuite/TestCase/TestRun/TestEnvironment/TestReport）
  - evaluators.py  内置评估器（类比 Validation Webhook）
  - controllers.py 控制器 Reconcile Loops（类比 K8s Controller Manager）
  - selfheal.py    自愈控制器（类比 livenessProbe + restartPolicy）
  - scheduler.py   测试调度器（类比 K8s Scheduler）
  - reporter.py    测试报告生成（类比 kubectl describe / metrics-server）
"""

# Changelog

本项目变更记录。格式参考 [Keep a Changelog](https://keepachangelog.com/)。

## [Unreleased]

### Added
- **Agent Harness Engineering 模块**：将 Kubernetes 设计理念（声明式 API、控制器模式、资源抽象、自愈能力、可扩展性）与 Agent 测试工程深度结合。
  - 新增 `harness/` 模块：`resources.py`（资源模型 TestSuite/TestCase/TestRun/TestEnvironment/TestReport）、`evaluators.py`（6 种内置评估器：tool_coverage/output_contains/max_rounds/latency/no_error/convergence）、`controllers.py`（Reconcile Loop 控制器：TestRunController/TestEnvironmentController/TestSuiteController）、`selfheal.py`（自愈控制器：诊断失败原因 + 决策恢复策略）、`scheduler.py`（测试调度器：优先级队列 + 批量加载）、`reporter.py`（报告生成器：终端渲染 + JSON 持久化 + 详情查看）。
  - 新增 `tests/` 测试类型插件目录：`builtin.py` 注册 4 种测试类型（behavioral 行为测试 / performance 性能测试 / safety 安全测试 / regression 回归测试），通过 `@test_type` 装饰器注册，扩展方式与 `@tool`/`@command` 一致。
  - 新增 `testcases/` 声明式测试用例目录：4 个 JSON 格式示例测试用例（behavioral-test / safety-test / performance-test / regression-test），定义期望状态与评估标准。
  - 核心注册表扩展：`cli.py` 新增 `_TEST_TYPES`/`_EVALUATORS` 注册表与 `@test_type`/`@evaluator` 装饰器，`main()` 启动时自动加载 `tests/` 与 `harness/` 插件目录。
  - 新增测试命令：`/test [文件|目录]` 运行声明式测试、`/testlist [目录]` 列出测试用例、`/testtype` 列出已注册测试类型与评估器、`/testreport [json路径]` 生成测试报告、`/testrun [序号]` 查看测试运行详情。
- **供应商与模型切换**：新增 `/provider [name]`、`/model [name]` 命令在运行中切换 LLM 供应商与模型；配置区改为 `PROVIDERS` 表（含 base_url/api_key/auth_scheme/models），预置 deepseek（bearer 鉴权）与 tongyi（raw 鉴权）；`Ctx` 持有 provider/model，`call_llm` 改用 `ctx.get_url()/get_headers()/ctx.model`；切换供应商时模型自动重置为该供应商首选。启动时显示当前供应商/模型。
- **工作区切换**：新增 `/cd <dir>` 命令切换工作区（支持相对当前目录或绝对路径），切换后自动重新扫描项目上下文并刷新 system prompt；新增 `/pwd` 查看当前工作区。启动时显示当前工作区。运行中不再锁定启动目录。
- **工具路径统一基于工作区**：`write_file`/`read_file` 改用 `ctx.resolve(path)` 解析路径（相对 `ctx.root`，绝对路径原样），`run_command` 以 `ctx.root` 为 `cwd` 执行。`/cd` 切换后工具立即在新工作区生效，`ctx.root` 不再是摆设。

### Fixed
- **工具调用终端预览不再硬截断**：原先 `🔧 工具名: ...` 仅显示结果前 80 字符且把换行替换为空格，长结果看不全。现改为短结果（≤500 字符）完整显示、长结果截断到前 500 字符并标注总长度，并明确提示「完整内容已传给 AI」。仅影响终端展示，传给 AI 的始终是完整结果。（`cli.py`）
- **`read_file` 不再硬截断 2000 字符**：原先读取超过 2000 字符的文件会被截断，导致 AI 收到不完整内容、影响后续推理。现改为分页读取：新增 `offset`（起始行号，默认 1）与 `limit`（行数，默认 200）参数，返回带行号的内容、总行数与翻页提示，AI 可分段读取完整大文件。（`tools/builtin.py`）

## [v0.1.0] - 2026-06-18

### Added
- 插件化 CLI 编程助手首版发布。
- 纯 Python 3.12 标准库实现，零第三方依赖。
- 单文件核心（`cli.py`）+ `tools/`、`commands/` 插件目录自动加载，核心不感知具体工具/命令，扩展只需新建带 `@tool`/`@command` 的 `.py`。
- 流式输出：基于 urllib SSE 解析 + ANSI 光标重绘实时渲染 Markdown。
- 工作区感知：启动时扫描目录树与关键配置文件注入上下文。
- Agent 工具调用循环（含 `max_rounds` 防失控保护）。
- 内置工具：`write_file`、`read_file`、`run_command`。
- 内置斜杠命令：`/exit`、`/quit`、`/clear`、`/write`、`/help`。
- 接入 DeepSeek `deepseek-v4-flash`。
- 虚拟环境（`.venv`）与 `run.ps1` 启动脚本。

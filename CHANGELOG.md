# Changelog

本项目变更记录。格式参考 [Keep a Changelog](https://keepachangelog.com/)。

## [Unreleased]

### Added
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

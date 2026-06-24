# CodeAgent-TUI

终端 AI 编程助手 —— 纯 Python 3.12，插件化架构，声明式测试运行时。

## 快速开始

```powershell
# 创建虚拟环境
py -3.12 -m venv .venv

# 安装依赖
.venv\Scripts\pip install -r requirements.txt

# 运行
.venv\Scripts\python.exe cli.py
# 或
powershell -ExecutionPolicy Bypass -File run.ps1
```

## 架构

```
cli.py           核心引擎（~520 行）：配置、渲染、注册表、Agent 循环
tools/           工具插件（AI 可调用的函数）
commands/        斜杠命令插件（用户交互）
tests/           测试类型 CRD + Operator
harness/         Agent Harness Engineering 测试运行时
testcases/       声明式测试用例（JSON）
```

## 核心特性

- **插件化**：`@tool` / `@command` 装饰器注册，核心零耦合，新增功能不需改核心
- **流式输出**：SSE 解析 + Rich 终端实时 Markdown 渲染
- **多供应商**：`/provider` `/model` 运行中热切换（预置 DeepSeek + 通义）
- **工作区感知**：`/cd` 切换工作目录，自动扫描项目上下文
- **工具调用循环**：Agent 自主选择工具、多轮执行、防失控保护（max 20 轮）

## 内置命令

| 命令 | 说明 |
|---|---|
| `/help` | 显示所有命令 |
| `/exit` `/quit` | 退出 |
| `/clear` | 清除对话历史 |
| `/cd <dir>` | 切换工作区 |
| `/pwd` | 显示当前工作区 |
| `/provider [name]` | 切换 LLM 供应商 |
| `/model [name]` | 切换模型 |
| `/test [path]` | 运行声明式测试 |
| `/testlist` | 列出测试用例 |
| `/testtype` | 列出测试类型与评估器 |
| `/testreport` | 生成测试报告 |
| `/testrun <n>` | 查看测试运行详情 |

## 内置工具

| 工具 | 说明 |
|---|---|
| `read_file` | 读取文件（支持分页） |
| `write_file` | 写入文件（自动创建目录） |
| `run_command` | 执行命令（工作区为 cwd） |
| `session_start` | 启动交互式会话（REPL/CLI） |
| `session_send` | 向交互式会话发送输入 |
| `session_close` | 关闭会话 |
| `session_list` | 列出活跃会话 |

## Agent Harness Engineering

将 Kubernetes 声明式设计移植到 AI Agent 测试的完整运行时。核心理念：

> Agent 是非确定性系统，不追求一次成功，而是持续调谐直到收敛。

### 声明式测试用例

```json
{
  "apiVersion": "harness.agent/v1",
  "kind": "TestCase",
  "metadata": { "name": "read-file-accuracy" },
  "spec": {
    "task": "读取 cli.py 前 10 行，总结文件用途",
    "testType": "behavioral",
    "successCriteria": [
      { "type": "tool_coverage", "tool": "read_file", "required": true },
      { "type": "output_contains", "keywords": ["import", "cli"], "minMatch": 1 },
      { "type": "convergence" }
    ],
    "maxRounds": 3,
    "maxRetries": 2,
    "timeout": 60
  }
}
```

### 执行模型

```
TestCase → Scheduler (priority queue) → SuiteController (batch + API budget)
  → EnvController (snapshot/sandbox) → RunController (reconcile loop)
    → Agent 执行 → Evaluators 评估 → 收敛? → 反馈注入 → 下一轮
    → 失败? → SelfHeal 诊断 → 退避/切模型/重建环境/重试
  → ReportGenerator (terminal + JSON)
```

### 评估器

| 评估器 | 检查内容 |
|---|---|
| `tool_coverage` | Agent 是否调用了指定工具 |
| `output_contains` | 输出是否包含期望关键词 |
| `max_rounds` | 工具调用轮数 ≤ 限制 |
| `latency` | 执行延迟 ≤ 限制 |
| `no_error` | 执行过程无错误 |
| `convergence` | 最终产生有效输出 |

### 测试类型

| 类型 | 收敛条件 |
|---|---|
| `behavioral` | 所有标准必须通过 |
| `performance` | 关键指标必须达标，其余建议性 |
| `safety` | 安全标准全通过 + 危险模式扫描 |
| `regression` | 行为不退化 + 输出质量基线 |

### 自愈策略

| 失败类型 | 自愈动作 |
|---|---|
| 执行超时 | 指数退避后重试 |
| API 限流 (429) | 切换模型 |
| 连接错误 | 指数退避 |
| 工具异常 | 从快照重建环境 |
| 评估未通过 | 注入失败反馈重试 |
| 未知错误 | 标记永久失败 |

## 配置

编辑 `cli.py` 中的 `PROVIDERS` 字典：

```python
PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/chat/completions",
        "api_key": "sk-xxx",
        "auth_scheme": "bearer",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
    },
}
```

## 版本

- **v0.4.0** — Agent Harness Engineering 测试运行时
- **v0.3.0** — 供应商/模型运行时切换
- **v0.2.0** — 工作区切换与工具信息完整性
- **v0.1.0** — 插件化 CLI 编程助手首版

## 依赖

- Python ≥ 3.12
- [rich](https://github.com/Textualize/rich) ≥ 13.0（终端渲染）

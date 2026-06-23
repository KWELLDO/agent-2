# CodeAgent-TUI 启动脚本
# 使用项目内 .venv (Python 3.12) 运行 cli.py；若虚拟环境不存在则自动创建。
$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "未检测到虚拟环境，正在使用 Python 3.12 创建 .venv ..." -ForegroundColor Yellow
    py -3.12 -m venv (Join-Path $root ".venv")
    if (-not (Test-Path $venvPython)) {
        Write-Host "虚拟环境创建失败，请确认已安装 Python 3.12 (可通过 py -3.12 --version 验证)" -ForegroundColor Red
        exit 1
    }
    Write-Host "虚拟环境创建完成。" -ForegroundColor Green
}

Push-Location $root
try {
    & $venvPython -m cli
} finally {
    Pop-Location
}

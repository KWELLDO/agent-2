# CodeAgent-TUI 启动脚本
# 使用项目内 .venv (Python 3.12) 运行 cli.py；若虚拟环境不存在则自动创建并安装依赖。
$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$venvPip = Join-Path $root ".venv\Scripts\pip.exe"

# 1. 确保虚拟环境存在
if (-not (Test-Path $venvPython)) {
    Write-Host "未检测到虚拟环境，正在使用 Python 3.12 创建 .venv ..." -ForegroundColor Yellow
    py -3.12 -m venv (Join-Path $root ".venv")
    if (-not (Test-Path $venvPython)) {
        Write-Host "虚拟环境创建失败，请确认已安装 Python 3.12 (可通过 py -3.12 --version 验证)" -ForegroundColor Red
        exit 1
    }
    Write-Host "虚拟环境创建完成。" -ForegroundColor Green
}

# 2. 确保依赖已安装（检查 rich 是否可用）
& $venvPython -c "import rich" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "正在安装依赖 (rich) ..." -ForegroundColor Yellow
    & $venvPip install -r (Join-Path $root "requirements.txt") --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "依赖安装失败，请手动运行: .venv\Scripts\pip install -r requirements.txt" -ForegroundColor Red
        exit 1
    }
    Write-Host "依赖安装完成。" -ForegroundColor Green
}

# 3. 启动
Push-Location $root
try {
    & $venvPython -m cli
} finally {
    Pop-Location
}

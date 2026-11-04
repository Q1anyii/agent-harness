# agent-harness 后端环境一键构建脚本
# 用法：powershell -ExecutionPolicy Bypass -File .\setup.ps1
# 作用：创建/复用项目 .venv 并安装 requirements.txt 依赖；
#       将 pip 的临时目录固定到 .venv\pip-tmp，避免 pip 临时文件散落项目根目录。
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root ".venv"
$pipTmp = Join-Path $venv "pip-tmp"

New-Item -ItemType Directory -Force -Path $pipTmp | Out-Null
$env:TEMP = $pipTmp
$env:TMP = $pipTmp

$py = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
    Write-Host "[setup] 创建虚拟环境 .venv ..."
    python -m venv $venv
}

Write-Host "[setup] 安装依赖 (requirements.txt) ..."
& $py -m pip install -r (Join-Path $root "requirements.txt")
Write-Host "[setup] 完成。pip 临时目录位于 .venv\pip-tmp"

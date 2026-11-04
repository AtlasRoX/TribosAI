# Start Tribos (backend on 8001, web app on 3000) so that it keeps running.
#
# Each server runs under scripts/supervise.py, which restarts it if it ever stops and keeps console Ctrl+C away from
# it. The supervisors are created through WMI (Win32_Process.Create), so they belong to no terminal, editor or agent
# session: closing whatever ran this script does not stop them. Run it again to restart both; run
# scripts/stop-tribos.ps1 to stop them. Logs: logs/backend.log and logs/web.log.
#
# Known issue: a supervisor started this way can be terminated a few minutes later (no exit is logged), leaving its
# server running but unsupervised. Running the supervisors as Windows scheduled tasks would avoid that; it needs your
# permission, since a scheduled task keeps running on its own.
#
#   powershell -ExecutionPolicy Bypass -File scripts\start-tribos.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start-tribos.ps1 -BackendOnly   # keep the web app (and open pages)

param([switch]$BackendOnly)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

& (Join-Path $PSScriptRoot "stop-tribos.ps1") -BackendOnly:$BackendOnly

function Start-Detached([string]$commandLine, [string]$directory) {
    $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $commandLine; CurrentDirectory = $directory
    }
    if ($result.ReturnValue -ne 0) { throw "Could not start: $commandLine (code $($result.ReturnValue))" }
}

$python = Join-Path $root ".venv\Scripts\python.exe"
$supervise = Join-Path $PSScriptRoot "supervise.py"
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
Start-Detached "`"$python`" `"$supervise`" --name backend --log `"$logs\backend.log`" --cwd `"$root`" -- `"$python`" -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8001" $root
if (-not $BackendOnly) { Start-Detached "`"$python`" `"$supervise`" --name web --log `"$logs\web.log`" --cwd `"$root\web`" -- `"$npm`" run dev" (Join-Path $root "web") }

function Wait-Url([string]$url, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try { Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 | Out-Null; return $true } catch { Start-Sleep -Seconds 1 }
    }
    return $false
}

$backend = Wait-Url "http://127.0.0.1:8001/api/health" 90
$web = Wait-Url "http://localhost:3000/" 180
"Backend  http://127.0.0.1:8001  " + $(if ($backend) { "up" } else { "NOT UP - see logs\backend.log" })
"Web app  http://localhost:3000   " + $(if ($web) { "up" } else { "NOT UP - see logs\web.log" })

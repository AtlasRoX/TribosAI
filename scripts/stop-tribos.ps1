# Stop Tribos: first the supervisors (the "Tribos-*" scheduled tasks and any scripts/supervise.py process, so they do
# not restart the servers), then whatever still listens on the backend (8001, and a leftover 8000) and web (3000)
# ports. -BackendOnly leaves the web app running.
param([switch]$BackendOnly)

$names = if ($BackendOnly) { @("backend") } else { @("backend", "web") }
foreach ($n in $names) {
    $task = Get-ScheduledTask -TaskName "Tribos-$n" -ErrorAction SilentlyContinue
    if ($task -and $task.State -eq "Running") {
        Stop-ScheduledTask -TaskName "Tribos-$n" -ErrorAction SilentlyContinue
        "Stopped task Tribos-$n"
    }
}
$pattern = if ($BackendOnly) { 'supervise\.py.*--name backend' } else { 'supervise\.py' }
$supervisors = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match $pattern }
foreach ($s in $supervisors) {
    Stop-Process -Id $s.ProcessId -Force -ErrorAction SilentlyContinue
    "Stopped supervisor (pid $($s.ProcessId))"
}
$ports = if ($BackendOnly) { @(8000, 8001) } else { @(3000, 8000, 8001) }
$listeners = Get-NetTCPConnection -LocalPort $ports -State Listen -ErrorAction SilentlyContinue
foreach ($l in $listeners) {
    Stop-Process -Id $l.OwningProcess -Force -ErrorAction SilentlyContinue
    "Stopped port $($l.LocalPort) (pid $($l.OwningProcess))"
}
Start-Sleep -Seconds 1

param(
    [Parameter(Mandatory=$true)][string]$SupabaseUrl,
    [Parameter(Mandatory=$true)][string]$SupabaseKey,
    [string]$TaskName = "DPD-Email-Scheduler"
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Worker = Join-Path $RootDir "scripts\email_scheduler_worker.py"
$LogDir = Join-Path $RootDir "logs"
$Runner = Join-Path $RootDir "scripts\run_scheduler_worker_windows.cmd"

if (!(Test-Path $Worker)) {
    throw "Worker script not found: $Worker"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Python = Join-Path $RootDir "venv\Scripts\python.exe"
if (!(Test-Path $Python)) {
    $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $Python) {
    throw "Python not found. Install Python or create venv."
}

$cmdContent = @"
@echo off
set SUPABASE_URL=$SupabaseUrl
set SUPABASE_KEY=$SupabaseKey
""$Python"" ""$Worker"" --once >> ""$LogDir\email_scheduler.out.log"" 2>> ""$LogDir\email_scheduler.err.log""
"@
Set-Content -Path $Runner -Value $cmdContent -Encoding ASCII

schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
schtasks /Create /SC MINUTE /MO 1 /TN $TaskName /TR "\"$Runner\"" /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null

Write-Host "Installed Scheduled Task: $TaskName"
Write-Host "Task status: schtasks /Query /TN $TaskName /V /FO LIST"
Write-Host "Logs: $LogDir\email_scheduler.out.log"

param([Parameter(Mandatory=$true)][string]$Cohort,
      [Parameter(Mandatory=$true)][int]$HostPid,
      [Parameter(Mandatory=$true)][string]$HostStartedUtc,
      [Parameter(Mandatory=$true)][int]$Game)
$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path -LiteralPath $Cohort).Path
$taskExpectedStart=([datetime]$HostStartedUtc).ToUniversalTime()
# Only the owned process identity is watched. No model calls, private packets,
# game choices, lifecycle mutations, or automatic restarts occur here.
while ($true) {
    $taskProcess=Get-Process -Id $HostPid -ErrorAction SilentlyContinue
    $taskAlive=$taskProcess -and $taskProcess.StartTime.ToUniversalTime() -eq $taskExpectedStart
    if (-not $taskAlive) { break }
    Start-Sleep -Seconds 3
}
$taskLaunchPath=Join-Path $taskRoot 'host_runtime/launch.json'
if (Test-Path -LiteralPath $taskLaunchPath) {
    $taskLaunch=Get-Content -LiteralPath $taskLaunchPath -Raw | ConvertFrom-Json
    if ($taskLaunch.pid -ne $HostPid -or ([datetime]$taskLaunch.process_started_utc).ToUniversalTime() -ne $taskExpectedStart) {
        return # A newer launch owns monitoring now; do not publish stale attention.
    }
}
. (Join-Path $PSScriptRoot 'python_runtime.ps1')
$taskPython=Resolve-EdhPython
$env:PYTHONPATH=Join-Path (Split-Path -Parent $PSScriptRoot) 'src'
& $taskPython -m edh_gauntlet.host_watch --cohort $taskRoot --game $Game
if ($LASTEXITCODE -ne 0) { throw 'Host watcher could not publish its attention record.' }
# One overwritten metadata record is the entire monitoring output. A supervisor
# can await this process exit instead of waking a model every few minutes.

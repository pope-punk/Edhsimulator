param([Parameter(Mandatory=$true)][string]$Cohort,[Parameter(Mandatory=$true)][int]$Game,[Parameter(Mandatory=$true)][int]$Accepted,[switch]$UserResume,[switch]$DecisionLimitResume,[switch]$ClaimCompletionRecovery,[switch]$RestoreUnusedTransports,[switch]$PlannerValidationRecovery,[switch]$UnansweredDecisionRecovery,[string]$BaselineTelemetry,[switch]$BoundedMemoryRecovery,[string]$ComboTelemetry,[string]$CapacityTelemetry,[string]$DiagnosticPauseTelemetry,[string]$ReservationTelemetry,[switch]$ConcurrentBackground,[switch]$SeatRoleLanes,[int]$MaxDecisions=10000,[ValidateRange(64,4096)][int]$TimingEvents=512)
$ErrorActionPreference='Stop'
$taskRepoRoot=Split-Path -Parent $PSScriptRoot
$taskRoot=(Resolve-Path -LiteralPath $Cohort).Path
$taskDirectory=Join-Path $taskRoot 'host_runtime'
if ($MaxDecisions -le $Accepted) { throw 'Decision cap must exceed the stopped accepted count.' }
$taskLaunchPath=Join-Path $taskDirectory 'launch.json'
$taskPrevious=Get-Content -LiteralPath $taskLaunchPath -Raw | ConvertFrom-Json
$taskProcess=Get-Process -Id $taskPrevious.pid -ErrorAction SilentlyContinue
if ($taskProcess -and $taskProcess.StartTime.ToUniversalTime() -eq ([datetime]$taskPrevious.process_started_utc).ToUniversalTime()) { throw 'The previous host is still running.' }
$taskEvidence=Join-Path $taskDirectory ('stopped_{0}_{1}.json' -f $Game,$Accepted)
if (Test-Path -LiteralPath $taskEvidence) {
    if (Test-Path -LiteralPath (Join-Path $taskDirectory ('recovery_{0}_{1}.json' -f $Game,$Accepted))) { throw 'Previous recovery passed preflight; reconcile instead of repeating it.' }
    if ($DiagnosticPauseTelemetry -and (Get-Content -LiteralPath (Join-Path $taskDirectory 'stderr.log') -Raw).Trim() -eq 'This recovery is limited to the diagnosed checkpoint-capacity failure.') {
        $taskEvidence=Join-Path $taskDirectory ('diagnostic_preflight_retry_{0}_{1}.json' -f $Game,$Accepted)
    } elseif ($ReservationTelemetry -and (Get-Content -LiteralPath (Join-Path $taskDirectory 'stderr.log') -Raw).Trim() -eq 'Reservation recovery requires complete telemetry for the exact stopped process and prefix.') {
        $taskEvidence=Join-Path $taskDirectory ('reservation_preflight_retry_{0}_{1}.json' -f $Game,$Accepted)
    } elseif ($RestoreUnusedTransports -and $ClaimCompletionRecovery) {
        $taskEvidence=Join-Path $taskDirectory ('unused_transport_launch_{0}_{1}.json' -f $Game,$Accepted)
    } else { throw 'This recovery was already attempted; reconcile before retrying.' }
    if (Test-Path -LiteralPath $taskEvidence) { throw 'This explicit preflight reconciliation was already attempted.' }
}
$taskPriorStderr=if ($taskPrevious.stderr_file) { $taskPrevious.stderr_file } else { 'stderr.log' }
@{previous_launch=$taskPrevious;stderr=(Get-Content -LiteralPath (Join-Path $taskDirectory $taskPriorStderr) -Raw);checked_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $taskEvidence -Encoding utf8
$env:PYTHONPATH=Join-Path $taskRepoRoot 'src'
$env:PYTHONUTF8='1'
. (Join-Path $PSScriptRoot 'python_runtime.ps1')
$taskPython=Resolve-EdhPython
$taskArgs=@('tools/resume_stopped_host.py','--cohort',('"'+$taskRoot+'"'),'--game',$Game,'--accepted',$Accepted,'--max-decisions',$MaxDecisions,'--timing-events',$TimingEvents)
if ($BaselineTelemetry) { $taskArgs+=@('--baseline-telemetry',('"'+(Resolve-Path -LiteralPath $BaselineTelemetry).Path+'"')) }
if ($CapacityTelemetry) { $taskArgs+=@('--capacity-telemetry',('"'+(Resolve-Path -LiteralPath $CapacityTelemetry).Path+'"')) }
if ($ReservationTelemetry) { $taskArgs+=@('--reservation-telemetry',('"'+(Resolve-Path -LiteralPath $ReservationTelemetry).Path+'"')) }
if ($DiagnosticPauseTelemetry) { $taskArgs+=@('--diagnostic-pause-telemetry',('"'+(Resolve-Path -LiteralPath $DiagnosticPauseTelemetry).Path+'"')) }
if ($ComboTelemetry) { $taskArgs+=@('--combo-telemetry',('"'+(Resolve-Path -LiteralPath $ComboTelemetry).Path+'"')) }
if ($ConcurrentBackground) { $taskArgs+='--concurrent-background' }
if ($SeatRoleLanes) { $taskArgs+='--seat-role-lanes' }
if ($UserResume) { $taskArgs+='--user-resume' }
if ($DecisionLimitResume) { $taskArgs+='--decision-limit-resume' }
if ($ClaimCompletionRecovery) { $taskArgs+='--claim-completion-recovery' }
if ($RestoreUnusedTransports) { $taskArgs+='--restore-unused-transports' }
if ($PlannerValidationRecovery) { $taskArgs+='--planner-validation-recovery' }
if ($UnansweredDecisionRecovery) { $taskArgs+='--unanswered-decision-recovery' }
if ($BoundedMemoryRecovery) { $taskArgs+='--bounded-memory-recovery' }
$taskAttention=Join-Path $taskRoot 'HOST_ATTENTION.json'
if (Test-Path -LiteralPath $taskAttention) { Remove-Item -LiteralPath $taskAttention }
$taskProcess=Start-Process -FilePath $taskPython -ArgumentList $taskArgs -WorkingDirectory $taskRepoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskDirectory 'stdout.log') -RedirectStandardError (Join-Path $taskDirectory 'stderr.log') -PassThru
$taskLaunch=@{game=$Game;pid=$taskProcess.Id;process_started_utc=$taskProcess.StartTime.ToUniversalTime().ToString('o');max_decisions=$MaxDecisions;timing_events=$TimingEvents;context_tokens=64000;approval_policy='never';resumed_at_decision=$Accepted;launched_utc=[DateTime]::UtcNow.ToString('o')}
$taskLaunch | ConvertTo-Json | Set-Content -LiteralPath $taskLaunchPath -Encoding utf8
$taskWatcherArgs=@('-NoProfile','-File',('"'+(Join-Path $PSScriptRoot 'watch_host_game.ps1')+'"'),
    '-Cohort',('"'+$taskRoot+'"'),'-HostPid',$taskProcess.Id,
    '-HostStartedUtc',$taskLaunch.process_started_utc,'-Game',$Game)
$taskWatcher=Start-Process -FilePath (Get-Process -Id $PID).Path -ArgumentList $taskWatcherArgs -WorkingDirectory $taskRepoRoot -WindowStyle Hidden -RedirectStandardError (Join-Path $taskDirectory 'watcher_stderr.log') -PassThru
$taskLaunch.watcher_pid=$taskWatcher.Id
$taskLaunch | ConvertTo-Json | Set-Content -LiteralPath $taskLaunchPath -Encoding utf8
$taskLaunch | ConvertTo-Json -Compress

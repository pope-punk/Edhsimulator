param([Parameter(Mandatory=$true)][string]$Cohort,[int]$MaxDecisions=10000,[int]$ContextTokens=64000,[ValidateRange(64,4096)][int]$TimingEvents=512)
$ErrorActionPreference='Stop'
$taskRepoRoot=Split-Path -Parent $PSScriptRoot
$taskCohortRoot=(Resolve-Path -LiteralPath $Cohort).Path
$taskNext=Get-Content -LiteralPath (Join-Path $taskCohortRoot 'NEXT_ACTION.json') -Raw | ConvertFrom-Json
if ($taskNext.next_action.kind -ne 'dispatch_pilot') { throw 'Follow NEXT_ACTION lifecycle before launching gameplay.' }
$taskGame=[int]$taskNext.next_action.game
$taskGameDirectory=Join-Path $taskCohortRoot ('game_{0:D2}' -f $taskGame)
$taskConfig=Get-Content -LiteralPath (Join-Path $taskGameDirectory 'game_config.json') -Raw | ConvertFrom-Json
if ($taskConfig.planning_contract -ne 4) { throw 'The fresh software host requires contract 4.' }
$taskTape=Join-Path $taskGameDirectory 'decisions.jsonl'
if ((Test-Path -LiteralPath $taskTape) -and (Get-Item -LiteralPath $taskTape).Length -gt 0) { throw 'This launcher only starts fresh games.' }
$taskHostDirectory=Join-Path $taskCohortRoot 'host_runtime'
New-Item -ItemType Directory -Path $taskHostDirectory -Force | Out-Null
if (Test-Path -LiteralPath (Join-Path $taskCohortRoot 'HOST_PAUSED.json')) { throw 'Resolve the explicit host pause before launching.' }
if (Test-Path -LiteralPath (Join-Path $taskHostDirectory 'sessions.json')) { throw 'Existing seat sessions require explicit lifecycle reconciliation.' }
$taskLaunchPath=Join-Path $taskHostDirectory 'launch.json'
if (Test-Path -LiteralPath $taskLaunchPath) {
    $taskPrevious=Get-Content -LiteralPath $taskLaunchPath -Raw | ConvertFrom-Json
    $taskPreviousProcess=Get-Process -Id $taskPrevious.pid -ErrorAction SilentlyContinue
    if ($taskPreviousProcess -and $taskPreviousProcess.StartTime.ToUniversalTime() -eq ([datetime]$taskPrevious.process_started_utc).ToUniversalTime()) { throw 'The previously launched host is still running.' }
}
. (Join-Path $PSScriptRoot 'python_runtime.ps1')
$taskPython=Resolve-EdhPython
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Configure an available Python 3.10+ executable.' }
$env:PYTHONPATH=Join-Path $taskRepoRoot 'src'
$env:PYTHONUTF8='1'
$taskAttentionPath=Join-Path $taskCohortRoot 'HOST_ATTENTION.json'
if (Test-Path -LiteralPath $taskAttentionPath) { Remove-Item -LiteralPath $taskAttentionPath }
$taskArguments=@('-m','edh_gauntlet.host_runtime','--cohort',('"'+$taskCohortRoot+'"'),'--max-decisions',$MaxDecisions,'--context-tokens',$ContextTokens,'--timing-events',$TimingEvents)
$taskProcess=Start-Process -FilePath $taskPython -ArgumentList $taskArguments -WorkingDirectory $taskRepoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskHostDirectory 'stdout.log') -RedirectStandardError (Join-Path $taskHostDirectory 'stderr.log') -PassThru
$taskLaunch=@{game=$taskGame;pid=$taskProcess.Id;process_started_utc=$taskProcess.StartTime.ToUniversalTime().ToString('o');max_decisions=$MaxDecisions;context_tokens=$ContextTokens;timing_events=$TimingEvents;approval_policy='never';launched_utc=[DateTime]::UtcNow.ToString('o')}
$taskLaunch | ConvertTo-Json | Set-Content -LiteralPath $taskLaunchPath -Encoding utf8
$taskWatcherArguments=@('-NoProfile','-File',('"'+(Join-Path $PSScriptRoot 'watch_host_game.ps1')+'"'),
    '-Cohort',('"'+$taskCohortRoot+'"'),'-HostPid',$taskProcess.Id,
    '-HostStartedUtc',$taskLaunch.process_started_utc,'-Game',$taskGame)
$taskWatcher=Start-Process -FilePath (Get-Process -Id $PID).Path -ArgumentList $taskWatcherArguments -WorkingDirectory $taskRepoRoot -WindowStyle Hidden -RedirectStandardError (Join-Path $taskHostDirectory 'watcher_stderr.log') -PassThru
$taskLaunch.watcher_pid=$taskWatcher.Id
$taskLaunch | ConvertTo-Json | Set-Content -LiteralPath $taskLaunchPath -Encoding utf8
$taskLaunch | ConvertTo-Json -Compress

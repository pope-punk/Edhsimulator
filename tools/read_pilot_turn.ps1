param(
    [Parameter(Mandatory=$true)][string]$Cohort,
    [Parameter(Mandatory=$true)][string]$Actor,
    [Parameter(Mandatory=$true)][string]$Path
)
$ErrorActionPreference = 'Stop'
$started = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
$cohortPath = (Resolve-Path -LiteralPath $Cohort).Path
$action = (Get-Content -LiteralPath (Join-Path $cohortPath 'NEXT_ACTION.json') -Raw -Encoding UTF8 | ConvertFrom-Json).next_action
$projectPath = Split-Path -Parent $cohortPath
$segmentPath = Join-Path $projectPath 'timing_segment.json'
$logPath = $null
$accepted = $null
if (Test-Path -LiteralPath $segmentPath) {
    $segment = Get-Content -LiteralPath $segmentPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $tapePath = Join-Path $cohortPath ('game_{0:00}/decisions.jsonl' -f [int]$segment.game)
    $accepted = @(Get-Content -LiteralPath $tapePath -Encoding UTF8 | Where-Object { $_.Trim() }).Count
    if ($accepted -ge $segment.target_accepted) {
        @{state='segment_complete'; accepted=$accepted; target=$segment.target_accepted} | ConvertTo-Json -Compress
        return
    }
    $probePath = Join-Path $projectPath $segment.name
    [void][IO.Directory]::CreateDirectory($probePath)
    $logPath = Join-Path $probePath 'events.jsonl'
}
if ($action.kind -ne 'dispatch_pilot' -or $action.actor -cne $Actor) {
    throw 'This seat does not own the pending delivery. Return control without opening a private file.'
}
$deliveryPath = [IO.Path]::GetFullPath($Path)
if (!$action.dispatch.turn -or $deliveryPath -ne [IO.Path]::GetFullPath($action.dispatch.turn)) {
    throw 'Stale or foreign delivery path. Obtain the current own-seat route.'
}
$meta = @{actor=$Actor; decision_id=$action.decision_id; delivery_id=$action.dispatch.delivery_id; accepted_before=$accepted}
function Write-TimingEvent([string]$EventName, [hashtable]$Extra) {
    if (!$logPath) { return }
    $entry = @{event=$EventName; epoch=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0; invocation=$started}
    foreach ($key in $meta.Keys) { $entry[$key]=$meta[$key] }
    foreach ($key in $Extra.Keys) { $entry[$key]=$Extra[$key] }
    [IO.File]::AppendAllText($logPath, (($entry | ConvertTo-Json -Compress) + "`n"), [Text.UTF8Encoding]::new($false))
}
Write-TimingEvent 'prepared_read_start' @{}
$success = $false
$bytes = 0
try {
    $body = [IO.File]::ReadAllText($deliveryPath, [Text.Encoding]::UTF8)
    $bytes = [Text.Encoding]::UTF8.GetByteCount($body)
    Write-Output $body
    $success = $true
} finally {
    Write-TimingEvent 'prepared_read_end' @{seconds=([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0-$started); success=$success; output_bytes=$bytes}
}

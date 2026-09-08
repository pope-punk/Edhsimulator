function Resolve-EdhPython {
    $taskCandidates = @()
    if ($env:EDH_PYTHON) { $taskCandidates += $env:EDH_PYTHON }
    else {
        foreach ($taskName in @('python', 'python3')) {
            $taskCommand = Get-Command $taskName -ErrorAction SilentlyContinue
            if ($taskCommand -and $taskCommand.Source) { $taskCandidates += $taskCommand.Source }
        }
    }
    foreach ($taskCandidate in $taskCandidates) {
        if ((Test-Path -LiteralPath $taskCandidate -PathType Leaf) -and (Get-Item -LiteralPath $taskCandidate).Length -gt 0) {
            & $taskCandidate -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
            if ($LASTEXITCODE -eq 0) { return $taskCandidate }
        }
    }
    throw 'Python 3.10+ is required. Activate a Python environment or set EDH_PYTHON to its executable.'
}

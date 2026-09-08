$ErrorActionPreference='Stop'
$taskProjectRoot = $PSScriptRoot
$env:PYTHONPATH = Join-Path $taskProjectRoot 'src'
$env:PYTHONUTF8 = '1'
. (Join-Path $taskProjectRoot 'tools/python_runtime.ps1')
$taskPython = Resolve-EdhPython
& $taskPython -m edh_gauntlet @args
exit $LASTEXITCODE

@echo off
set "PYTHONPATH=%~dp0src"
set "PYTHONUTF8=1"
python -c "import sys; assert sys.version_info >= (3,10)" >nul 2>nul
if errorlevel 1 (
  set "PYTHON_EXE=%LOCALAPPDATA%\Programs\GIMP 3\bin\python.exe"
) else (
  set "PYTHON_EXE=python"
)
if not exist "%PYTHON_EXE%" if not "%PYTHON_EXE%"=="python" (
  echo Python 3.10+ is required. Install Python or make it available as python. 1>&2
  exit /b 1
)
"%PYTHON_EXE%" -m edh_gauntlet %*
exit /b %ERRORLEVEL%

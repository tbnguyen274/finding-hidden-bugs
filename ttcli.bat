@echo off
setlocal
REM Simple wrapper for Windows CMD

if not exist "%~dp0ttcli.py" (
  echo ttcli.py not found next to this script.
  exit /b 1
)

REM If no args: show a tiny menu (judge/submit)
if "%~1"=="" goto :menu

goto :run

:menu
echo Select mode:
echo   1^) judge   ^(right terminal^)
echo   2^) submit  ^(left terminal, interactive^)
set /p TTCLI_MODE=Enter 1 or 2:

if /I "%TTCLI_MODE%"=="1" (
  set TTCLI_ARGS=judge
  goto :run_menu
)

if /I "%TTCLI_MODE%"=="2" (
  set TTCLI_ARGS=repl
  goto :run_menu
)

echo Invalid choice.
exit /b 2

:run_menu
call :run_py %TTCLI_ARGS%
exit /b %errorlevel%

:run
REM Allow 'ttcli submit ...' as an alias for python's 'submit' subcommand.
REM Also allow 'ttcli submit' (no args) to mean interactive repl.
if /I "%~1"=="submit" (
  if "%~2"=="" (
    call :run_py repl
    exit /b %errorlevel%
  )
)

call :run_py %*
exit /b %errorlevel%

:run_py
REM Prefer py -3; fallback to python
py -3 "%~dp0ttcli.py" %*
if %errorlevel% neq 0 (
  python "%~dp0ttcli.py" %*
)
exit /b %errorlevel%

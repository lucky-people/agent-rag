@echo off
rem ============================================================
rem  Zhizu Advisor Launcher (thin shell -> start.py)
rem  Real logic lives in start.py: preflight checks, grouped
rem  startup, health polling, status summary, PID tracking.
rem  NOTE: Keep this file pure ASCII. Chinese chars in .bat are
rem  mis-parsed by cmd.exe (GBK) and cause garbled-window errors.
rem  Usage:
rem    start.bat              start all services
rem    start.bat --status     show port / middleware status
rem    start.bat --stop       stop all services started by this launcher
rem ============================================================
cd /d "%~dp0"

rem ---- Pick Python: ZHIZU_PYTHON env > common conda path > system python ----
set "PYTHON=%ZHIZU_PYTHON%"
if "%PYTHON%"=="" if exist "C:\Users\31077\anaconda3\envs\lang_env\python.exe" set "PYTHON=C:\Users\31077\anaconda3\envs\lang_env\python.exe"
if "%PYTHON%"=="" set "PYTHON=python"

"%PYTHON%" start.py %*
pause

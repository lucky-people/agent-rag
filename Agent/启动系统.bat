@echo off
rem ============================================================
rem  Zhizu Advisor Launcher (Merged: A2A Agents + RAG Legal QA)
rem  Starts 4 MCP servers + 4 A2A servers + Web frontend.
rem  Legal QA is lazy-loaded inside web_server.py (needs MySQL/Redis/Milvus).
rem  NOTE: Keep this file pure ASCII. Chinese chars in .bat are
rem  mis-parsed by cmd.exe (GBK) and cause garbled-window errors.
rem ============================================================
cd /d "%~dp0"

rem ---- Pick Python: ZHIZU_PYTHON env > common conda path > system python ----
set "PYTHON=%ZHIZU_PYTHON%"
if "%PYTHON%"=="" if exist "C:\Users\31077\anaconda3\envs\lang_env\python.exe" set "PYTHON=C:\Users\31077\anaconda3\envs\lang_env\python.exe"
if "%PYTHON%"=="" set "PYTHON=python"

echo ============================================================
echo   Zhizu Advisor - One-click start
echo   4 MCP servers + 4 A2A servers + Web frontend
echo   Python: %PYTHON%
echo ============================================================
echo.

echo [1/3] Starting 4 MCP servers ...
start "MCP-House-8004"    cmd /k "%PYTHON%" -m mcp_server.mcp_house_server
start "MCP-Poi-8005"      cmd /k "%PYTHON%" -m mcp_server.mcp_poi_server
start "MCP-Metro-8006"    cmd /k "%PYTHON%" -m mcp_server.mcp_metro_server
start "MCP-Recom-8007"    cmd /k "%PYTHON%" -m mcp_server.mcp_recommend_server
echo.

echo [2/3] Starting 4 A2A servers ...
start "A2A-House-5006"    cmd /k "%PYTHON%" -m a2a_server.house_server
start "A2A-Poi-5007"      cmd /k "%PYTHON%" -m a2a_server.poi_server
start "A2A-Metro-5008"    cmd /k "%PYTHON%" -m a2a_server.metro_server
start "A2A-Recom-5009"    cmd /k "%PYTHON%" -m a2a_server.recommend_server
echo.

echo [3/3] Starting Web frontend ...
echo Waiting, browser opens http://localhost:8501
echo Closing this window stops the frontend only.
echo.
"%PYTHON%" -m web_server

pause

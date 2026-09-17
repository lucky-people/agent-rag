#!/usr/bin/env bash
# ============================================================
#  Zhizu Advisor Launcher (Linux/macOS)
#  Starts 4 MCP servers + 5 A2A servers + Web frontend.
#  Usage:
#    ./start.sh                # 使用系统默认 python3
#    ZHIZU_PYTHON=~/miniconda3/envs/lang_env/bin/python ./start.sh
# ============================================================
set -e
cd "$(dirname "$0")"

# Pick Python: ZHIZU_PYTHON env > python3
PYTHON="${ZHIZU_PYTHON:-python3}"

echo "============================================================"
echo "  Zhizu Advisor - One-click start"
echo "  4 MCP servers + 5 A2A servers + Web frontend"
echo "  Python: $PYTHON"
echo "============================================================"
echo

echo "[1/3] Starting 4 MCP servers ..."
"$PYTHON" -m mcp_server.mcp_house_server &
"$PYTHON" -m mcp_server.mcp_poi_server &
"$PYTHON" -m mcp_server.mcp_metro_server &
"$PYTHON" -m mcp_server.mcp_recommend_server &
echo

echo "[2/3] Starting 5 A2A servers ..."
"$PYTHON" -m a2a_server.house_server &
"$PYTHON" -m a2a_server.poi_server &
"$PYTHON" -m a2a_server.metro_server &
"$PYTHON" -m a2a_server.recommend_server &
"$PYTHON" -m a2a_server.legal_agent_server &
echo

echo "[3/3] Starting Web frontend ..."
echo "Browser opens http://localhost:8501"
echo "Press Ctrl+C to stop the frontend only."
echo
"$PYTHON" -m web_server

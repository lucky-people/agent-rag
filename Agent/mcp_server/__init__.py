#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_server 包标识文件。
作用：使 mcp_server 成为"正规包"，避免与 lang_env site-packages 中
已安装的同名 PyPI 包（mcp_server-0.1.4）冲突，确保
`python -m mcp_server.mcp_xxx` 解析到本项目目录下的 MCP 服务器。
"""

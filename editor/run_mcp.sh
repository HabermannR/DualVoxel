#!/bin/sh
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python -u mcp_server.py

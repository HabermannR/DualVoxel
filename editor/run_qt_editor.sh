#!/bin/sh
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python qt_editor.py "$@"

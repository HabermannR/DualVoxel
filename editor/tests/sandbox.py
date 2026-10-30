"""Tests leave the user's own editor alone: import this before anything imports live_link or builds a window.

An EditorWindow starts its assistant link (on by default) and writes live_link.LINK_FILE, then removes it on
close; with the real file that cuts off the editor the user has open. And the window reads and writes the
user's QSettings (layout, Tools > Assistant link). Here the link file is a temporary one for the whole run,
and every window gets fresh settings of its own in a temporary file, with the link off.
"""
import os
import sys
import tempfile
from pathlib import Path

LINK_FILE = Path(tempfile.mkdtemp()) / "live_link.json"
os.environ["DUALVOXEL_LINK_FILE"] = str(LINK_FILE)  # for live_link and for an MCP server a test starts
if "live_link" in sys.modules:  # imported before this: LINK_FILE is read once at import
    sys.modules["live_link"].LINK_FILE = LINK_FILE

# editor.local.json: a temporary copy, so a test that saves keys leaves the user's file alone
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))
import local_config  # noqa: E402
_config = Path(tempfile.mkdtemp()) / "editor.local.json"
if local_config.CONFIG.exists():
    _config.write_text(local_config.CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
local_config.CONFIG = _config

try:
    from PySide6 import QtCore
except ImportError:
    QtCore = None

if QtCore is not None and not getattr(QtCore.QSettings, "private", False):
    class PrivateSettings(QtCore.QSettings):
        """The editor's own settings ("VoxelPipeline", "QtEditor") in a new temporary file; others as asked."""
        private = True

        def __init__(self, *args, **kwargs):
            if "VoxelPipeline" in args:
                super().__init__(str(Path(tempfile.mkdtemp()) / "settings.ini"), QtCore.QSettings.Format.IniFormat)
                self.setValue("assistant_link", False)
            else:
                super().__init__(*args, **kwargs)

    QtCore.QSettings = PrivateSettings

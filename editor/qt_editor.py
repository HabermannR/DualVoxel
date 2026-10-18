"""
DualVoxel, the Qt voxel editor: three 2D slice views, a VTK 3D edit view and the
renderer, each a movable dock over one two-byte model.

    .venv\\Scripts\\python.exe qt_editor.py [model.vx2 | model.vox] [--smoke screenshot.png]
"""
import argparse
import sys
import time
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from qtui.window import EditorWindow

SMOKE_SAMPLES = 64
SMOKE_TIMEOUT = 120.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model", nargs="?", help="a .vx2 or .vox to open")
    parser.add_argument("--smoke", type=Path, help="open, wait for the render to settle, save a screenshot, quit")
    args = parser.parse_args()

    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    window = EditorWindow()
    if args.model:
        window.open_path(args.model)
    window.show()

    if args.smoke:
        started = time.perf_counter()

        def check():
            done = window.render_view.samples >= SMOKE_SAMPLES
            failed = window.render_view.message.startswith("Renderer unavailable")
            if not (done or failed or time.perf_counter() - started > SMOKE_TIMEOUT):
                return
            timer.stop()
            screen = window.screen().grabWindow(window.winId())
            screen.save(str(args.smoke))
            print(f"smoke: saved {args.smoke} ({window.render_view.samples} samples)")
            window.close()

        timer = QtCore.QTimer(interval=500, timeout=check)
        timer.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

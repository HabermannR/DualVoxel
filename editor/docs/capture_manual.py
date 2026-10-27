"""Screenshots for the guide (guide.md), from the live editor and its renderer.

    ..\\.venv\\Scripts\\python.exe capture_manual.py [--scenes]

--scenes retakes only the project's figures (scene, scene_render, transform); --gas only the gas
figure (from assets/heart_cozy.vx2, skipped where that model is not). Shows the window on the desktop (it stays on top while it captures), waits for
the render to settle and writes `figures/current_*.png`. Each dock is cut from
one grab of the window, so the VTK views come out as they are on screen. Every
PNG records 96 dpi per logical pixel. Nothing is saved to the model or the project.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EDITOR = HERE.parent
ROOT = EDITOR.parent
FIGURES = HERE / "figures"
sys.path.insert(0, str(EDITOR))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

SETTLED = 160  # samples before a render counts as settled
TIMEOUT = 240.0


def wait(ms: int) -> None:
    QTest.qWait(ms)


def settle(window, samples: int = SETTLED) -> None:
    started = time.perf_counter()
    while window.render_view.samples < samples and time.perf_counter() - started < TIMEOUT:
        if window.render_view.message.startswith("Renderer unavailable"):
            raise RuntimeError(window.render_view.message)
        wait(250)
    wait(150)


def trimmed(image: QtGui.QImage, ratio: float) -> QtGui.QImage:
    """Without the empty rows at the bottom of a dock (the colour of its last row), keeping a small margin."""
    import numpy as np
    image = image.convertToFormat(QtGui.QImage.Format.Format_RGB32)
    pixels = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())
    pixels = pixels[:, :image.width() * 4]
    differs = np.nonzero((pixels != pixels[-1]).any(axis=1))[0]
    if len(differs) == 0:
        return image
    return image.copy(0, 0, image.width(), min(image.height(), int(differs[-1]) + 1 + round(10 * ratio)))


def save(image: QtGui.QImage, name: str, ratio: float) -> None:
    """Save with the logical pixel density: one logical pixel is 1/96 inch."""
    dots = round(96 * ratio / 0.0254)
    image.setDotsPerMeterX(dots)
    image.setDotsPerMeterY(dots)
    path = FIGURES / f"current_{name}.png"
    image.save(str(path))
    print(f"  {path.name}: {image.width()}x{image.height()}")


class Shooter:
    def __init__(self, window):
        self.window = window

    def grab(self) -> tuple[QtGui.QImage, float]:
        w = self.window
        w.raise_()
        w.activateWindow()
        wait(120)
        pixmap = w.screen().grabWindow(w.winId())
        return pixmap.toImage(), pixmap.devicePixelRatio() or w.devicePixelRatioF()

    def whole(self, name: str) -> None:
        image, ratio = self.grab()
        save(image, name, ratio)

    def widget(self, widget: QtWidgets.QWidget, name: str, margin: int = 0, trim: bool = False) -> None:
        """A widget's rectangle cut from the window grab (with `margin` logical pixels around it)."""
        image, ratio = self.grab()
        top_left = widget.mapTo(self.window, QtCore.QPoint(0, 0))
        rect = QtCore.QRect(top_left, widget.size()).adjusted(-margin, -margin, margin, margin)
        rect = rect.intersected(self.window.rect())
        scaled = QtCore.QRect(round(rect.x() * ratio), round(rect.y() * ratio), round(rect.width() * ratio),
                              round(rect.height() * ratio))
        cut = image.copy(scaled)
        save(trimmed(cut, ratio) if trim else cut, name, ratio)

    def dock(self, title: str, name: str) -> None:
        """A dock with its tab, without the empty space below its controls."""
        dock = self.window.docks[title]
        dock.setAsCurrentTab()
        wait(200)
        self.widget(dock.dockAreaWidget(), name, trim=True)


def material_id(name: str) -> int:
    table = json.loads((ROOT / "palette" / "materials.json").read_text(encoding="utf-8"))
    return next(m["id"] for m in table["materials"] if m["name"] == name)


def main() -> None:
    FIGURES.mkdir(exist_ok=True)
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    from qtui.window import EditorWindow
    QtCore.QSettings("VoxelPipeline", "QtEditor")  # the user's layout is left alone: a private one below
    window = EditorWindow()
    window.settings = QtCore.QSettings(str(Path(tempfile.mkdtemp()) / "layout.ini"),
                                       QtCore.QSettings.Format.IniFormat)
    window.closeEvent = lambda event: event.accept()  # never ask to save
    window.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
    window.open_path(ROOT / "assets" / "alchemist.vx2")
    window.resize(1600, 960)
    window.move(40, 40)
    window.show()
    shoot = Shooter(window)
    doc, view, brush = window.doc, window.edit_view, window.edit_view.brush
    print("waiting for the render…")
    settle(window)

    from qtui.window import LAYOUT_VERSION

    def focus(titles, width, height):
        """Only these docks, in a window of this size (restored by `whole_layout`)."""
        for title, dock in window.docks.items():
            dock.toggleView(title in titles)
        window.resize(width, height)
        wait(500)

    def whole_layout():
        window.dock_manager.restoreState(window.default_layout, LAYOUT_VERSION)
        window.resize(1600, 960)
        wait(500)

    def hover_floor(point):
        renderer = view.plotter.renderer
        renderer.SetWorldPoint(*point, 1)
        renderer.WorldToDisplay()
        view.update_hover(tuple(int(round(v)) for v in renderer.GetDisplayPoint()[:2]))
        view.plotter.render()
        wait(150)

    def reframe_render():
        window.render_view.engine.reframe(window.render_view.camera)
        window.render_view._moved()
        settle(window)

    def scenes():
        """A project: the Project dock and the Scene view with an instance selected (its yellow box), the
        whole scene in the Render dock, and the Transform dock."""
        whole_layout()
        window.open_path(ROOT / "assets" / "meadow.project.json")
        wait(800)
        scenes = window.scenes
        project = scenes.project_doc
        project.select(next(i for i in project.scene.instances if i.name == "bush-1"))
        wait(300)
        focus({"Scene", "Project"}, 1300, 760)
        scenes.scene_view.frame()
        wait(300)
        shoot.whole("scene")
        focus({"Render"}, 1000, 640)
        scenes._render_scene(True)  # as while the Scene tab is in use
        wait(300)
        reframe_render()
        shoot.widget(window.render_view, "scene_render")
        focus({"Transform"}, 640, 700)
        shoot.dock("Transform", "transform")
        whole_layout()

    def gas():
        """Gas at night: the cozy heart's mist, smoke, flame and beating haze, lit by its lanterns and fire."""
        model = ROOT / "assets" / "heart_cozy.vx2"
        if not model.exists():
            print("no", model.name, "here: the gas figure stays as it is")
            return
        whole_layout()
        window.open_path(model)
        wait(800)
        window.light_panel.choose("Night")
        focus({"Render"}, 900, 1100)
        camera = window.render_view.camera
        window.render_view.engine.reframe(camera)
        camera.yaw += 0.35  # from the front left, where the fire shows past the grave
        camera.pitch = 0.42
        camera.zoom(1.2)
        window.render_view._moved()
        settle(window, 1024)
        shoot.widget(window.render_view, "gas")
        window.light_panel.choose("Golden hour")

    if "--scenes" in sys.argv[1:]:  # only the project's figures
        scenes()
        window.close()
        print("done")
        return
    if "--gas" in sys.argv[1:]:  # only the gas figure
        gas()
        window.close()
        print("done")
        return

    # the whole desktop, with a sphere brush's preview on the floor in the 3D view
    view.frame()
    brush.set(kind="voxel", size=5, round=True, volume=True)
    doc.set_tool("attach")
    hover_floor((4.5, 4.5, 0.0))
    settle(window)
    shoot.whole("desktop")

    # the 3D edit view and the render, each on its own
    focus({"3D edit"}, 1000, 760)
    view.frame()
    hover_floor((4.5, 4.5, 0.0))
    shoot.widget(view, "edit_view")
    focus({"Render"}, 1000, 760)
    reframe_render()
    shoot.widget(window.render_view, "render")
    for preset in ("Golden hour", "Day", "Overcast", "Night"):
        window.light_panel.choose(preset)
        settle(window)
        shoot.widget(window.render_view, "light_" + preset.lower().replace(" ", "_"))
    window.light_panel.choose("Golden hour")
    focus({"Render"}, 1450, 580)  # the cover's band: wide and low
    reframe_render()
    shoot.widget(window.render_view, "cover")

    # the material editor, tall enough for every field
    focus({"Material editor"}, 640, 780)
    for name, shot in (("polished metal", "material_editor_metal"), ("glass", "material_editor_glass"),
                       ("skin", "material_editor_skin")):
        doc.set_material(material_id(name))
        wait(200)
        shoot.dock("Material editor", shot)
    focus({"Light"}, 640, 600)
    shoot.dock("Light", "light_dock")
    focus({"Render setup"}, 640, 420)
    shoot.dock("Render setup", "render_setup_dock")
    focus({"Export"}, 640, 600)
    shoot.dock("Export", "export_dock")
    whole_layout()

    # the Brush dock, plain and sculpting
    shoot.dock("Brush", "brush_dock")
    window.brush_panel.kind_buttons["smooth"].click()
    shoot.dock("Brush", "brush_sculpt")
    brush.set(kind="voxel", size=5, round=True, volume=False)

    # a slice with the brush's footprint under the cursor
    top = window.slices["Top"]
    window.docks["Top"].setAsCurrentTab()
    top.depth_box.setValue(10)
    wait(150)
    top.canvas.hover = (16, 14)
    top.canvas.update()
    wait(150)
    shoot.widget(top, "slice_top")

    # colours and materials
    doc.set_material(0)
    shoot.dock("Colours", "colours")
    shoot.dock("Materials", "materials")

    scenes()
    gas()
    window.close()
    print("done")


if __name__ == "__main__":
    main()

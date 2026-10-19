"""The slice views keep the 'Behind' ghost between refreshes and reread only the columns an edit touched."""
import os
import sys
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))


def expected_pixels(view):
    """The slice as SliceView.refresh drew it before the cache: the whole stack read on every refresh."""
    from qtui.edit_view import PROTECTED_RGB, PROTECTED_TINT
    from qtui.slice_view import BACKGROUND, GHOST
    doc = view.doc
    key_plane, lookup = doc.display_planes()
    stack = np.moveaxis(doc.model.colour.transpose(2, 1, 0), view.d, -1)
    keys = np.moveaxis(key_plane.transpose(2, 1, 0), view.d, -1)
    depth = min(view.depth_box.value(), stack.shape[2] - 1)
    layer = stack[:, :, depth]
    rgb = lookup[keys[:, :, depth]].astype(np.float32)
    empty = layer == 0
    protected = doc.protected()
    if protected is not None:
        hit = np.moveaxis(protected.transpose(2, 1, 0), view.d, -1)[:, :, depth] & ~empty
        rgb[hit] = rgb[hit] * (1 - PROTECTED_TINT) + PROTECTED_RGB * PROTECTED_TINT
    rgb[empty] = BACKGROUND
    if view.ghost_box.isChecked():
        behind = slice(depth + 1, None) if view.behind > 0 else slice(depth - 1, None, -1) if depth else slice(0, 0)
        rest, rest_keys = stack[:, :, behind], keys[:, :, behind]
        if rest.shape[2]:
            hit = rest > 0
            first = np.take_along_axis(rest_keys, hit.argmax(axis=2)[..., None], axis=2)[..., 0]
            show = empty & hit.any(axis=2)
            rgb[show] = BACKGROUND * (1 - GHOST) + lookup[first[show]] * GHOST
    img = rgb.astype(np.uint8).transpose(1, 0, 2)
    if view.flip_v:
        img = img[::-1]
    if view.flip_u:
        img = img[:, ::-1]
    return img


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs a native Qt window")
class SliceGhostTests(unittest.TestCase):
    def test_edits_show_as_a_whole_reread_would(self):
        from PySide6 import QtWidgets
        from qtui.document import Document
        from qtui.slice_view import SLICES, SliceView
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)  # noqa: F841
        doc = Document()
        doc.new(40, 32, 24, ground=3)
        views = [SliceView(doc, name) for name in SLICES]
        rng = np.random.default_rng(7)

        def check(what):
            for view in views:
                view.refresh()
                np.testing.assert_array_equal(view._pixels, expected_pixels(view), err_msg=f"{view.name}: {what}")

        def blob():
            lo = rng.integers(0, (40, 32, 24))
            pts = lo + rng.integers(-3, 4, size=(30, 3))
            return pts

        check("new")
        scanned = []  # the (u, v) columns each refresh reads
        for view in views:
            view._pack = lambda stack, pack=view._pack: (scanned.append(stack.shape[:2]), pack(stack))[1]
        doc.set_voxels([(3, 30, 0), (4, 31, 1)], colour=5)  # only those columns are read again
        check("two voxels")
        self.assertEqual(scanned, [(2, 2)] * 3)
        scanned.clear()
        for view in views:  # another layer reads none
            view.depth_box.setValue(view.depth_box.value() - 3)
        check("other layers")
        self.assertEqual(scanned, [])

        for step in range(60):
            kind = step % 6
            if kind == 0:
                doc.set_voxels(blob(), colour=int(rng.integers(1, 200)))
            elif kind == 1:
                doc.set_voxels(blob(), colour=0)  # erase
            elif kind == 2:
                pts = blob()
                doc.set_voxel_values(pts, rng.integers(0, 50, len(pts)), rng.integers(0, 5, len(pts)))
            elif kind == 3:
                doc.begin_stroke()  # a stroke of several writes between two refreshes
                for _ in range(3):
                    doc.set_voxels(blob(), colour=int(rng.integers(1, 200)))
                doc.end_stroke()
            elif kind == 4:
                doc.undo() if step % 12 == 4 else doc.model._edit(  # not through the edit log
                    lambda c, m: c.__setitem__((slice(0, 12), slice(5, 9), slice(10, 20)), 9))
                doc.changed.emit()
            else:
                view = views[step % 3]
                view.depth_box.setValue(int(rng.integers(0, view.depth_box.maximum() + 1)))
            if step == 20:
                doc.set_show_materials(True)
            if step == 35:
                doc.set_protected(np.clip(blob(), 0, (39, 31, 23)))
            if step == 50:
                views[1].ghost_box.setChecked(False)
            check(f"step {step}")

        doc.new(30, 20, 10, ground=1)  # another size
        check("another model")

"""The 3D edit view meshes the model in chunks and remeshes only the chunks an edit touches."""
import os
import sys
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs a native Qt window")
class EditViewChunkTests(unittest.TestCase):
    def test_an_edit_remeshes_only_the_chunks_it_touches(self):
        from PySide6 import QtWidgets
        from PySide6.QtTest import QTest
        from qtui.document import Document
        from qtui.edit_view import CHUNK, EditView, voxel_faces
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)  # noqa: F841
        doc = Document()
        doc.new(96, 64, 40, ground=2)  # 3 x 2 x 2 chunks of 32
        view = EditView(doc)
        view.resize(600, 600)
        view.show()
        QTest.qWait(200)
        remeshed = []
        remesh = view._remesh
        view._remesh = lambda chunks: (remeshed.append(set(chunks)), remesh(chunks))

        def settled():
            QTest.qWait(80)  # the view's debounced refresh
            seen = list(remeshed)
            remeshed.clear()
            return seen

        def shown():
            """Every chunk's faces together, as (voxel, normal) rows."""
            rows = [np.hstack(faces[3:5]) for _, faces, *_ in view.chunks.values()]
            return np.unique(np.concatenate(rows), axis=0)

        def whole():
            key, lookup = doc.display_planes()
            return np.unique(np.hstack(voxel_faces(doc.model.colour, lookup, key)[3:5]), axis=0)

        self.assertEqual(set(view.chunks), {(x, y, 0) for x in range(3) for y in range(2)})  # the ground
        np.testing.assert_array_equal(shown(), whole())

        # a voxel inside a chunk: that chunk; on a chunk's side: the chunk beside it too
        doc.set_voxels([(40, 10, 5)], colour=3)
        self.assertEqual(settled(), [{(1, 0, 0)}])
        doc.set_voxels([(31, 10, 5)], colour=3)
        self.assertEqual(settled(), [{(0, 0, 0), (1, 0, 0)}])
        doc.set_voxels([(70, 40, 35)], colour=4)  # a chunk that had no voxels gets an actor
        self.assertEqual(settled(), [{(2, 1, 1)}])
        self.assertIn((2, 1, 1), view.chunks)
        np.testing.assert_array_equal(shown(), whole())

        # undo comes back through the same comparison
        doc.undo()
        self.assertEqual(settled(), [{(2, 1, 1)}])
        self.assertNotIn((2, 1, 1), view.chunks)

        # a click picks the face across the chunks and remeshes only where the brush wrote
        renderer = view.plotter.renderer
        renderer.SetWorldPoint(31.5, 10.5, 6, 1)  # the top of (31, 10, 5)
        renderer.WorldToDisplay()
        pos = tuple(int(round(v)) for v in renderer.GetDisplayPoint()[:2])
        self.assertEqual(view._pick(pos), ((31, 10, 5), (31, 10, 6)))
        view.brush.set(kind="voxel", size=1, mirror=(False, False, False))
        view.click(pos, "erase")
        self.assertEqual(doc.voxel(31, 10, 5), 0)
        self.assertEqual(settled(), [{(0, 0, 0), (1, 0, 0)}])  # the brush wrote x 31, beside x 32's chunk
        np.testing.assert_array_equal(shown(), whole())
        # a mirrored brush writes far apart: the chunks of each side, not those between
        self.assertEqual(view._chunks_near([(5, 5, 5), (90, 5, 5)]), {(0, 0, 0), (2, 0, 0)})

        # shown otherwise (materials): every chunk
        doc.set_show_materials(True)
        self.assertEqual(settled()[0], {(x, y, z) for x in range(3) for y in range(2) for z in range(2)})
        np.testing.assert_array_equal(shown(), whole())
        self.assertEqual(CHUNK, 32)
        view.close()


if __name__ == "__main__":
    unittest.main()

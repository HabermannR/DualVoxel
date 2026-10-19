"""Undo keeps only the box of voxels a step changed: a one-voxel edit on the largest model is a few bytes,
and undo and redo bring back exactly what was there."""
import sys
import unittest
from pathlib import Path

import numpy as np

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
from core.model import Model  # noqa: E402
from qtui.document import Document  # noqa: E402


def filled(model: Model, seed: int = 7) -> None:
    """Random solid voxels, so a step that kept whole planes would not pack small."""
    rng = np.random.default_rng(seed)
    model.colour[:] = rng.integers(0, 8, model.colour.shape, dtype=np.uint8)
    model.material[:] = np.where(model.colour > 0, rng.integers(0, 4, model.colour.shape, dtype=np.uint8), 0)


class UndoTests(unittest.TestCase):
    def test_one_voxel_on_a_256_model_is_a_tiny_step(self):
        model = Model()
        model.new(256, 256, 256)
        filled(model)
        before = model.colour.copy(), model.material.copy()
        old = int(model.colour[200, 100, 50])
        self.assertEqual(model.paint_box([50, 100, 200], [50, 100, 200], old % 7 + 1, 1), 1)
        after = model.colour.copy(), model.material.copy()
        step = model.undo_stack[-1]
        self.assertEqual(step.box, (slice(200, 201), slice(100, 101), slice(50, 51)))
        self.assertLess(model.history_size(), 16)  # both planes of one voxel; the whole would be 33 MB
        self.assertTrue(model.undo())
        np.testing.assert_array_equal(model.colour, before[0])
        np.testing.assert_array_equal(model.material, before[1])
        self.assertTrue(model.redo())
        np.testing.assert_array_equal(model.colour, after[0])
        np.testing.assert_array_equal(model.material, after[1])
        self.assertIs(model.undo_stack[-1], step)  # the same step moves between the stacks
        self.assertFalse(model.redo())

    def test_a_stroke_is_one_step_of_its_box(self):
        doc = Document()
        doc.new(64, 64, 64)
        filled(doc.model)
        doc.model.colour[5, 4, [3, 10]] = doc.model.colour[5, 20, 10] = 5  # so each write below changes it
        before = doc.model.colour.copy(), doc.model.material.copy()
        doc.begin_stroke()
        doc.set_voxels([[3, 4, 5], [10, 4, 5]], 2, 0)
        doc.set_voxels([[10, 20, 5]], 0)
        doc.end_stroke()
        after = doc.model.colour.copy(), doc.model.material.copy()
        self.assertEqual(len(doc.model.undo_stack), 1)
        self.assertEqual(doc.model.undo_stack[0].box, (slice(5, 6), slice(4, 21), slice(3, 11)))
        doc.undo()
        np.testing.assert_array_equal(doc.model.colour, before[0])
        np.testing.assert_array_equal(doc.model.material, before[1])
        doc.redo()
        np.testing.assert_array_equal(doc.model.colour, after[0])
        np.testing.assert_array_equal(doc.model.material, after[1])

    def test_the_history_keeps_to_its_bytes(self):
        model = Model()
        model.new(64, 64, 64)
        filled(model)
        model.history_bytes = 200_000
        states = [model.colour.copy()]
        for i in range(12):  # each step changes most of the model: random voxels pack to about 100 KB
            model.replace_colour(i % 7 + 1, (i + 3) % 7 + 1)
            states.append(model.colour.copy())
        self.assertLessEqual(model.history_size(), 200_000)
        self.assertGreater(len(model.undo_stack), 0)
        undone = 0
        while model.undo():
            undone += 1
            np.testing.assert_array_equal(model.colour, states[-1 - undone])
        self.assertLess(undone, 12)  # the oldest steps were let go

    def test_the_newest_step_stays_however_large(self):
        model = Model()
        model.new(32, 32, 32)
        filled(model)
        model.history_bytes = 1
        before = model.colour.copy()
        model.erase_box([0, 0, 0], [31, 31, 31])
        model.paint_box([0, 0, 0], [31, 31, 31], 3)
        self.assertEqual(len(model.undo_stack), 1)
        model.undo()
        self.assertFalse(model.colour.any())
        self.assertFalse(np.array_equal(model.colour, before))

    def test_new_and_open_clear_the_history(self):
        model = Model()
        model.new(16, 16, 16)
        model.paint_box([0, 0, 0], [3, 3, 3], 2)
        model.undo()
        model.new(8, 8, 8)
        self.assertEqual((model.undo_stack, model.redo_stack), ([], []))
        model.paint_box([0, 0, 0], [3, 3, 3], 2)
        model._replace(np.zeros((4, 4, 4), np.uint8), np.zeros((4, 4, 4), np.uint8))  # another size
        self.assertFalse(model.undo())


if __name__ == "__main__":
    unittest.main()

"""palette/material_source.py on a copy of the palette and the assets: the material authoring loop."""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[1]
ROOT = EDITOR.parent
sys.path.insert(0, str(EDITOR))
import core.model  # noqa: E402,F401  (puts pipeline/ and palette/ on the path)
import material_source as ms  # noqa: E402
import vx2  # noqa: E402


class MaterialSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "vp"
        (self.root / "palette").mkdir(parents=True)
        (self.root / "assets").mkdir()
        for name in ("build_materials.py", "colors.json", "materials.json"):
            shutil.copy(ROOT / "palette" / name, self.root / "palette" / name)
        for path in (ROOT / "assets").glob("*.vx2"):
            shutil.copy(path, self.root / "assets" / path.name)
        self.source = self.root / "palette" / "build_materials.py"
        self.table = json.loads((self.root / "palette" / "materials.json").read_text(encoding="utf-8"))["materials"]

    def tearDown(self):
        vx2.ROOT = ROOT
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unchanged_table_leaves_the_source_alone(self):
        before = self.source.read_text(encoding="utf-8")
        report = ms.save_table(copy.deepcopy(self.table), self.root)
        self.assertEqual((report["changed"], report["added"]), ([], []))
        self.assertEqual(self.source.read_text(encoding="utf-8"), before)

    def test_edit_and_add_rewrite_only_their_rows_and_models_still_open(self):
        before = self.source.read_text(encoding="utf-8").splitlines()
        table = copy.deepcopy(self.table)
        table[4]["roughness"] = 0.3
        table.append(dict(copy.deepcopy(table[10]), id=len(table), name="ember", light="fire", note="coals"))
        report = ms.save_table(table, self.root)
        self.assertEqual((report["changed"], report["added"]), ([4], [len(self.table)]))
        after = self.source.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(after), len(before) + 1)  # one new row; the edited row and LIGHTS in place
        written = json.loads((self.root / "palette" / "materials.json").read_text(encoding="utf-8"))["materials"]
        self.assertEqual((written[4]["roughness"], written[-1]["name"], written[-1]["light"]), (0.3, "ember", "fire"))
        vx2.ROOT = self.root
        for path in (self.root / "assets").glob("*.vx2"):
            vx2.read(path)  # stamped with the new tables
        again = ms.save_table(written, self.root)
        self.assertEqual((again["changed"], again["added"], again["lights"]), ([], [], False))

    def test_materials_are_never_removed(self):
        with self.assertRaises(ValueError):
            ms.write_source(copy.deepcopy(self.table[:-1]), self.source)


if __name__ == "__main__":
    unittest.main()

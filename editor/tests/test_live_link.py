"""The live link: the MCP server's edits on the model open in the window, with the user's protection and undo
steps respected; and the render's light presets."""
import asyncio
import base64
import io
import os
import sys
import threading
import time
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
from sandbox import LINK_FILE as LINK  # noqa: E402  never the link file of an editor the user has open

import numpy as np  # noqa: E402

from core.lights import PRESETS, preset_name  # noqa: E402
from core.model import Model  # noqa: E402
from live_link import SharedEditor  # noqa: E402

SKIP_GPU = os.environ.get("SKIP_GPU") == "1"


class LightPresetTests(unittest.TestCase):
    def test_names_in_any_spelling(self):
        self.assertEqual(preset_name("golden_hour"), "Golden hour")
        self.assertEqual(preset_name(" OVERCAST "), "Overcast")
        with self.assertRaises(ValueError):
            preset_name("dusk")
        self.assertEqual(set(PRESETS), {"Golden hour", "Day", "Noon", "Overcast", "Night"})


class SharedEditorTests(unittest.TestCase):
    def setUp(self):
        self.model = Model()
        self.model.new(8, 8, 8)
        self.locked = np.zeros((8, 8, 8), dtype=bool)
        self.shared = SharedEditor(lambda: self.model, lambda model: self.locked if self.locked.any() else None)

    def test_user_protection_holds_and_cannot_be_cleared(self):
        self.model.paint_box([0, 0, 0], [7, 7, 0], 54)  # the user's floor
        self.locked[0, 2:4, 2:4] = True  # planes are (z, y, x)
        self.shared.handle("erase_box", {"start": [0, 0, 0], "end": [7, 7, 7]})
        self.assertEqual(int((self.model.colour > 0).sum()), 4)
        self.shared.handle("clear_protection", {})
        self.shared.handle("erase_box", {"start": [0, 0, 0], "end": [7, 7, 7]})
        self.assertEqual(int((self.model.colour > 0).sum()), 4)
        self.assertEqual(self.shared.handle("info", {})["user_protected"]["voxels"], 4)

    def test_undo_takes_back_only_the_assistants_steps(self):
        self.shared.handle("paint_box", {"start": [1, 1, 1], "end": [2, 2, 2], "colour": 54})
        self.model.paint_box([5, 5, 5], [5, 5, 5], 60)  # then the user edits
        with self.assertRaises(ValueError):
            self.shared.handle("undo", {})
        self.model.undo()  # the user undoes theirs; the assistant's step is on top again
        self.shared.handle("undo", {})
        self.assertEqual(int((self.model.colour > 0).sum()), 0)
        self.shared.handle("redo", {})
        self.assertEqual(int((self.model.colour > 0).sum()), 8)
        with self.assertRaises(ValueError):
            self.shared.handle("redo", {})

    def test_follows_the_window_to_another_model(self):
        self.shared.handle("protect_box", {"start": [0, 0, 0], "end": [1, 1, 1]})
        other = Model()
        other.new(4, 4, 4)
        self.model = other
        info = self.shared.handle("info", {})
        self.assertEqual(info["size"], [4, 4, 4])
        self.assertEqual(info["protected_voxels"], 0)

    def test_unknown_requests_are_refused(self):
        with self.assertRaises(ValueError):
            self.shared.handle("save_model", {"name": "x"})


@unittest.skipIf(os.environ.get("SKIP_QT"), "needs Qt")
class LinkTests(unittest.TestCase):
    """The window's AssistantLink and the MCP server, over the real socket, with Qt's loop on this thread."""

    @classmethod
    def setUpClass(cls):
        from PySide6 import QtWidgets
        from qtui.assistant_link import AssistantLink
        from qtui.document import Document
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        cls.doc = Document()
        cls.link = AssistantLink(cls.doc)
        cls.link.start()

    @classmethod
    def tearDownClass(cls):
        cls.link.stop()

    def run_beside_qt(self, work):
        """Run work() on a thread while Qt's events are handled here; return its result or raise its error."""
        outcome = {}

        def run():
            try:
                outcome["result"] = work()
            except BaseException as error:
                outcome["error"] = error
        thread = threading.Thread(target=run)
        thread.start()
        while thread.is_alive():
            self.app.processEvents()
            time.sleep(0.002)
        self.app.processEvents()
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("result")

    def test_a_wrong_token_is_turned_away(self):
        import json
        import socket
        port = json.loads(LINK.read_text())["port"]

        def knock():
            with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
                s.sendall(b'{"op": "info", "args": {}}\n')
                return s.makefile("rb").readline()
        self.assertIn(b"token", self.run_beside_qt(knock))

    def test_client_edits_the_window_model_and_waits_for_a_stroke(self):
        from live_link import LiveClient
        self.doc.new(8, 8, 8)
        self.doc.set_protected([(0, 0, 0)])  # not solid yet: protects the empty cell
        client = self.run_beside_qt(LiveClient)
        try:
            changed = []
            self.doc.changed.connect(lambda: changed.append(1))
            result = self.run_beside_qt(lambda: client.call("paint_box", start=[0, 0, 0], end=[1, 1, 1], colour=54))
            self.assertEqual(result["changed_voxels"], 7)
            self.assertEqual(int((self.doc.model.colour > 0).sum()), 7)
            self.assertTrue(changed)
            # a request during the user's stroke waits for its end
            self.doc.begin_stroke()
            self.doc.set_voxels([(5, 5, 5)], colour=60)
            pending = threading.Thread(target=lambda: client.call("erase_box", start=[0, 0, 0], end=[7, 7, 7]))
            pending.start()
            for _ in range(50):
                self.app.processEvents()
                time.sleep(0.004)
            self.assertEqual(self.doc.model.colour[5, 5, 5], 60)  # not erased yet
            self.doc.end_stroke()
            while pending.is_alive():
                self.app.processEvents()
                time.sleep(0.002)
            self.assertEqual(int((self.doc.model.colour > 0).sum()), 0)
            # the user's stroke came after the paint: undo refuses, then takes back the erase
            undone = self.run_beside_qt(lambda: client.call("undo"))
            self.assertEqual(undone["voxels"], 8)
            with self.assertRaises(ValueError):
                self.run_beside_qt(lambda: client.call("undo"))
            picture = self.run_beside_qt(client.model)
            np.testing.assert_array_equal(picture.colour, self.doc.model.colour)
            # what the user points at
            self.doc.set_colour(60)
            self.doc.pick(1, 1, 1)
            state = self.run_beside_qt(lambda: client.call("user_state"))
            self.assertEqual(state["picked"]["voxel"], [1, 1, 1])
            self.assertEqual(state["colour"]["slot"], 54)  # the pick took the voxel's colour
            with self.assertRaises(ValueError):  # no Render dock here
                self.run_beside_qt(lambda: client.call("view_state"))
            grid = self.run_beside_qt(lambda: client.call("read_slice", axis="z", depth=1))
            self.assertEqual(len(grid["grid"]), 2)
        finally:
            client.close()

    def test_open_model_in_the_window_asks_before_dropping_edits(self):
        from unittest import mock
        from PySide6 import QtWidgets
        from core.model import ROOT as PIPELINE
        alchemist = PIPELINE / "assets" / "alchemist.vx2"
        self.link.open_path = None
        with self.assertRaises(ValueError):
            self.shared_open(alchemist)
        self.link.open_path = self.doc.open
        try:
            self.doc.new(4, 4, 4)  # nothing edited: opens without asking
            with mock.patch.object(QtWidgets.QMessageBox, "question") as asked:
                info = self.shared_open(alchemist)
                asked.assert_not_called()
            self.assertEqual(self.doc.model.path, alchemist)
            self.assertGreater(info["voxels"], 0)
            self.doc.set_voxels([(0, 0, 0)], colour=60)  # an edit: the user is asked, and may say no
            no, yes = QtWidgets.QMessageBox.StandardButton.No, QtWidgets.QMessageBox.StandardButton.Yes
            with mock.patch.object(QtWidgets.QMessageBox, "question", return_value=no):
                with self.assertRaises(ValueError):
                    self.shared_open(PIPELINE / "assets" / "skeleton.vx2")
            self.assertEqual(self.doc.model.path, alchemist)
            with mock.patch.object(QtWidgets.QMessageBox, "question", return_value=yes):
                self.shared_open(PIPELINE / "assets" / "skeleton.vx2")
            self.assertEqual(self.doc.model.path.name, "skeleton.vx2")
            with self.assertRaises(ValueError):
                self.shared_open(PIPELINE / "assets" / "no_such_model.vx2")
        finally:
            self.link.open_path = None

    def test_project_tools_work_on_the_window_project(self):
        from core.model import ROOT as PIPELINE
        from qtui.project_document import ProjectDocument
        pdoc = ProjectDocument(self.doc)
        changes = []
        pdoc.changed.connect(lambda: changes.append(1))
        self.link.project = lambda: pdoc
        try:
            handle = self.link.shared.handle
            made = handle("add_instance", {"part": str(PIPELINE / "assets" / "skeleton.vx2"), "position": [0, 0, 0]})
            self.assertIs(pdoc.instance, pdoc.scene.instances[0])  # selected in the window
            handle("move_instance", {"name": made["name"], "by": [3, 0, 0]})
            self.assertEqual(pdoc.instance.position, (3, 0, 0))
            self.assertTrue(pdoc.undo())  # each change is one step of the scene's undo
            self.assertEqual(pdoc.scene.instances[0].position, (0, 0, 0))
            info = handle("project_info", {})
            self.assertEqual(info["parts"]["skeleton"]["instances"], 1)
            handle("remove_instance", {"name": made["name"]})
            self.assertFalse(pdoc.scene.instances)
            self.assertTrue(changes)
        finally:
            self.link.project = None
        with self.assertRaises(ValueError):
            self.link.shared.handle("project_info", {})

    def test_open_a_project_in_the_window(self):
        from core.model import ROOT as PIPELINE
        from qtui.project_document import ProjectDocument
        pdoc = ProjectDocument(self.doc)
        self.doc.new(4, 4, 4)
        self.link.project = lambda: pdoc
        self.link.open_path = pdoc.open_project  # the model shown stays: only the project changes
        try:
            self.shared_open(PIPELINE / "assets" / "meadow.project.json")
            info = self.link.shared.handle("project_info", {})
            self.assertEqual(info["parts"]["ground"]["instances"], 1)
            self.link.open_path = lambda path: None  # the window failed (and said why)
            with self.assertRaises(ValueError):
                self.shared_open(PIPELINE / "assets" / "meadow.project.json")
        finally:
            self.link.project = None
            self.link.open_path = None

    def shared_open(self, path):
        return self.link.shared.handle("open_model", {"path": str(path)})

    def test_mcp_server_connects_to_the_editor(self):
        from PIL import Image
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        self.doc.new(6, 6, 6)

        async def session():
            params = StdioServerParameters(command=sys.executable, args=[str(EDITOR / "mcp_server.py")],
                                           cwd=str(EDITOR), env={**os.environ, "DUALVOXEL_LINK_FILE": str(LINK)})
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    await client.initialize()
                    self.assertEqual(len((await client.list_tools()).tools), 52)
                    hello = await client.call_tool("connect_editor", {})
                    self.assertFalse(hello.isError, hello.content)
                    painted = await client.call_tool("paint_box", {"start": [0, 0, 0], "end": [5, 5, 0], "colour": 54})
                    self.assertFalse(painted.isError, painted.content)
                    refused = await client.call_tool("save_model", {"name": "_never"})
                    self.assertTrue(refused.isError)
                    shown = await client.call_tool("preview", {})
                    image = [c for c in shown.content if c.type == "image"][0]
                    Image.open(io.BytesIO(base64.b64decode(image.data))).load()
                    if not SKIP_GPU:
                        rendered = await client.call_tool("render", {"width": 64, "height": 64, "samples": 4,
                                                                     "light": "Overcast"})
                        self.assertFalse(rendered.isError, rendered.content)
                    self.assertFalse((await client.call_tool("disconnect_editor", {})).isError)
        self.run_beside_qt(lambda: asyncio.run(session()))
        self.assertEqual(int((self.doc.model.colour > 0).sum()), 36)


if __name__ == "__main__":
    unittest.main()

"""The window's side of the live link (live_link.py): the MCP server edits the model open here.

A QTcpServer on 127.0.0.1 at a free port; the port and a random token go into
live_link.LINK_FILE while the link is on (Tools > Assistant link, on by default,
remembered). A client must say hello with the token before anything else.
Requests run on the GUI thread between the user's own events; one that arrives
during a stroke waits until the stroke ends, so a stroke stays one undo step.
The status bar shows whether an assistant is connected and what it last did.
"""
from __future__ import annotations

import json
import secrets
from collections import deque

from PySide6 import QtCore, QtNetwork

from live_link import SharedEditor, new_token, remove_link, write_link
from project_ops import ProjectOps

WAIT_MS = 40  # how often a request waiting for the user's stroke looks again
PROJECT_OPS = ("project_info", "add_part", "add_instance", "move_instance", "remove_instance")


class AssistantLink(QtCore.QObject):
    status_changed = QtCore.Signal(str)  # a short line for the status bar
    acted = QtCore.Signal(str)           # what the assistant just did

    def __init__(self, doc, render_view=None, open_path=None, parent=None, project=None):
        """open_path: the window's own Open (a model, a MagicaVoxel scene or a project), for open_model;
        project: gives the window's ProjectDocument, for the parts and instances tools."""
        super().__init__()
        self.doc = doc
        self.render_view = render_view
        self.open_path = open_path
        self.parent = parent
        self.project = project
        ops = ProjectOps(self._project_doc)
        self.shared = SharedEditor(lambda: doc.model, doc.protected,
                                   {"user_state": self.user_state, "view_state": self.view_state,
                                    "open_model": self.open_model,
                                    **{name: getattr(ops, name) for name in PROJECT_OPS}})
        self.pointer = ""        # what the mouse was last over, as the status bar said it
        self.last_drawn = None   # the first voxel of the user's last stroke in the 3D view
        doc.hover_changed.connect(lambda text: setattr(self, "pointer", text) if text else None)
        doc.focus_changed.connect(lambda x, y, z: setattr(self, "last_drawn", [x, y, z]))
        doc.reset.connect(self._model_reset)
        self.server = None
        self.token = None
        self.clients = {}  # socket -> {"buffer": bytes, "hello": bool}
        self.queue = deque()

    @property
    def active(self) -> bool:
        return self.server is not None

    def start(self) -> None:
        if self.server is not None:
            return
        self.server = QtNetwork.QTcpServer(self)
        if not self.server.listen(QtNetwork.QHostAddress.SpecialAddress.LocalHost, 0):
            error = self.server.errorString()
            self.server = None
            self.status_changed.emit(f"Assistant link: off ({error})")
            return
        self.server.newConnection.connect(self._accept)
        self.token = new_token()
        write_link(self.server.serverPort(), self.token)
        self._report()

    def stop(self) -> None:
        if self.server is None:
            return
        for socket in list(self.clients):
            socket.disconnectFromHost()
        self.server.close()
        self.server.deleteLater()
        self.server = None
        remove_link(self.token)
        self.token = None
        self._report()

    def _report(self) -> None:
        if self.server is None:
            text = "Assistant link: off"
        else:
            connected = sum(1 for c in self.clients.values() if c["hello"])
            text = "Assistant: connected" if connected else "Assistant link: waiting"
        self.status_changed.emit(text)

    def _model_reset(self) -> None:
        self.shared.forget()
        self.last_drawn = None

    # --- what only the window knows ----------------------------------------------------------------
    def user_state(self) -> dict:
        """What the user has chosen and points at: the current colour, material and mode, the voxel last
        picked (Alt + left), where their last stroke began, and what the mouse was last over."""
        doc, model = self.doc, self.doc.model
        picked = doc.picked
        return {"colour": {"slot": doc.colour, "hex": model.by_id[doc.colour]["hex"]},
                "material": {"id": doc.material, "name": model.material_info(doc.material)["name"]},
                "mode": doc.tool, "picked": {"voxel": list(picked), "says": doc.describe(*picked)} if picked else None,
                "last_drawn": self.last_drawn, "pointer": self.pointer,
                "model": str(model.path.name) if model.path else "new model", "size": list(doc.size)}

    def view_state(self) -> dict:
        """The Render dock's camera (world units) and light, so the assistant can render what the user sees."""
        view = self.render_view
        if view is None or view.engine is None or not view.engine.framed:
            raise ValueError("The Render dock has not shown this model yet (open it, or resume it with F9).")
        camera = view.camera
        return {"eye": camera.pos.tolist(), "forward": camera.fwd.tolist(), "right": camera.right.tolist(),
                "up": camera.up.tolist(), "aspect": view.width() / max(1, view.height()),
                "light": {"golden": view.golden, "custom": view.custom_light, "sun": view.sun, "sky": view.sky}}

    def _project_doc(self):
        if self.project is None:
            raise ValueError("This window has no projects (parts and instances).")
        return self.project()

    def open_model(self, path) -> dict:
        """Open a file in the window, as File > Open does. When the model shown has edits since it was
        opened, the user is asked first: the assistant never throws their work away unasked."""
        from pathlib import Path
        from PySide6 import QtWidgets
        if self.open_path is None:
            raise ValueError("This window does not open files for the assistant.")
        path = Path(path)
        if not path.is_file() or not (path.suffix in (".vx2", ".vox") or path.name.endswith(".project.json")):
            raise ValueError(f"No .vx2, .vox or .project.json at {path}.")
        model = self.doc.model
        if model.undo_stack:
            shown = model.path.name if model.path else "the new model"
            answer = QtWidgets.QMessageBox.question(
                self.parent, "Assistant: open a file",
                f"The assistant wants to open {path.name} here. {shown} has edits; unsaved ones are lost. Open it?")
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                raise ValueError(f"The user kept {shown} open (it has edits): ask them to save it, or to open "
                                 f"{path.name} themselves.")
        def opened():  # a project opens into the project, not always the model shown
            project = self.project().project if self.project is not None else None
            return self.doc.model, self.doc.model.path, self.doc.model.version, project
        before = opened()
        self.open_path(str(path))
        if opened() == before:
            raise ValueError(f"The editor could not open {path.name} (the window says why).")
        self.acted.emit(f"Assistant opened {path.name}")
        return self.shared.handle("info", {})

    # --- sockets ---------------------------------------------------------------------------------
    def _accept(self) -> None:
        while self.server is not None and self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.clients[socket] = {"buffer": b"", "hello": False}
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(lambda s=socket: self._gone(s))

    def _gone(self, socket) -> None:
        self.clients.pop(socket, None)
        self.queue = deque(item for item in self.queue if item[0] is not socket)
        socket.deleteLater()
        self._report()

    def _read(self, socket) -> None:
        client = self.clients.get(socket)
        if client is None:
            return
        client["buffer"] += bytes(socket.readAll())
        *lines, client["buffer"] = client["buffer"].split(b"\n")
        self.queue.extend((socket, line) for line in lines if line.strip())
        self._pump()

    def _pump(self) -> None:
        while self.queue:
            if self.doc._before is not None:  # the user is in the middle of a stroke
                QtCore.QTimer.singleShot(WAIT_MS, self._pump)
                return
            socket, line = self.queue.popleft()
            if socket not in self.clients:
                continue
            answer = self._answer(socket, line)
            socket.write(json.dumps(answer).encode("utf-8") + b"\n")
            if not self.clients[socket]["hello"]:
                socket.disconnectFromHost()  # after the answer, which says why

    # --- requests --------------------------------------------------------------------------------
    def _answer(self, socket, line: bytes) -> dict:
        try:
            request = json.loads(line)
            op, args = request["op"], request.get("args") or {}
        except (ValueError, KeyError, TypeError):
            return {"error": "Send one JSON object per line: {\"op\": ..., \"args\": {...}}."}
        client = self.clients[socket]
        if not client["hello"]:
            if op != "hello" or not secrets.compare_digest(str(args.get("token")), self.token):
                return {"error": "Say hello with the token from the link file first."}
            client["hello"] = True
            self._report()
            self.acted.emit("Assistant connected: it now edits this model")
            return {"result": {"editor": "DualVoxel", **self.shared.handle("info", {})}}
        version = self.doc.model.version
        try:
            result = self.shared.handle(op, args)
        except Exception as error:  # the assistant's mistake, told back to it; the window goes on
            return {"error": str(error)}
        if self.doc.model.version != version:
            self.doc.changed.emit()
            changed = result.get("changed_voxels") if isinstance(result, dict) else None
            self.acted.emit(f"Assistant: {op}" + (f", {changed} voxels" if changed is not None else ""))
        elif op in PROJECT_OPS and op != "project_info":
            self.acted.emit(f"Assistant: {op} {result.get('name') or result.get('part') or result.get('removed') or ''}")
        return {"result": result}

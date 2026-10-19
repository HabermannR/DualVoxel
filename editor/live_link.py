"""The live link between the MCP server and the open editor, without Qt (the window's side is qtui/assistant_link.py).

The editor listens on 127.0.0.1 at a free port and writes the port and a random
token to LINK_FILE (in the user's own local app data) while it runs. The MCP
server's connect_editor reads the file, connects and says hello with the token;
from then on its edits change the model open in the window, where the user sees
them and can keep editing. One JSON object per line each way: a request
{"op": name, "args": {...}}, an answer {"result": ...} or {"error": "..."}.

On the editor's side a SharedEditor does the work: the headless API's edits on
the window's model, with two rules for sharing it. Voxels the user protected
(the Protect mode) are kept like the assistant's own protected boxes, and
clear_protection never lifts them. undo and redo only take back the
assistant's own steps: when the last step is the user's, they refuse.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import socket
import tempfile
import threading
import zlib
from pathlib import Path

import numpy as np

from headless_api import VoxelEditor, synchronized
from core.model import Model

LINK_FILE = Path(os.environ.get("DUALVOXEL_LINK_FILE")  # tests use their own
                 or Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "DualVoxel" / "live_link.json")
TIMEOUT = 60  # seconds an answer may take (a big model's copy, an editor busy with a dialog)


# --- the link file -------------------------------------------------------------------------
def new_token() -> str:
    return secrets.token_hex(16)


def write_link(port: int, token: str) -> None:
    LINK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LINK_FILE.write_text(json.dumps({"port": port, "token": token, "pid": os.getpid()}), encoding="utf-8")


def remove_link(token: str) -> None:
    """Remove the link file if it is still this editor's (a second editor may have written its own)."""
    try:
        if json.loads(LINK_FILE.read_text(encoding="utf-8")).get("token") == token:
            LINK_FILE.unlink()
    except (OSError, ValueError):
        pass


def read_link() -> dict:
    try:
        return json.loads(LINK_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ConnectionError("No editor is open with the assistant link on (Tools > Assistant link).") from None


# --- the model as data ---------------------------------------------------------------------
def pack(array: np.ndarray) -> str:
    return base64.b64encode(zlib.compress(np.ascontiguousarray(array).tobytes(), 1)).decode("ascii")


def unpack(text: str, shape) -> np.ndarray:
    return np.frombuffer(zlib.decompress(base64.b64decode(text)), dtype=np.uint8).reshape(shape).copy()


# --- the editor's side ---------------------------------------------------------------------
class SharedEditor(VoxelEditor):
    """The headless edits on the model open in the window. `current` gives that model (it changes when the
    user opens another or edits another part of a project); `locked` gives the user's protected voxels
    for a model (a bool plane, z y x) or None."""

    EDITS = ("paint_box", "erase_box", "shape_slice", "set_material_box", "set_material_for_colour",
             "replace_colour", "fill_shape", "draw_line", "set_voxels", "mirror", "copy_box", "protect_box",
             "clear_protection", "speckle", "noise_terrain", "erode_surface", "scatter", "place_model",
             "resize_model", "fit_model", "shift_model", "rotate_model", "flip_model")
    QUESTIONS = ("info", "materials", "read_slice", "voxels_in_box")

    def __init__(self, current, locked, window=None):
        """window: {op name: callable} for questions only the window can answer (what the user points at,
        the Render dock's camera and light)."""
        self._current, self._user_locked = current, locked
        self._window = window or {}
        super().__init__(current())
        self._mine, self._undone = [], []  # the undo / redo entries of the assistant's own steps

    def _bind(self) -> None:
        """Follow the window to another model: the assistant's protected boxes and steps were the last one's."""
        model = self._current()
        if model is self.model:
            self._follow()  # the user's own resizes, turns and their undo since
        if model is not self.model or self._protected.shape != model.colour.shape:
            self.model = model
            self._unprotect_all()
            self._mine, self._undone = [], []

    def _locked(self):
        locked = self._user_locked(self.model)
        return locked if locked is not None and locked.shape == self.model.colour.shape else None

    @synchronized
    def info(self):
        info = super().info()
        locked = self._locked()
        solid = np.argwhere(locked) if locked is not None else np.zeros((0, 3), int)
        info["user_protected"] = {"voxels": len(solid), "bounds": [solid.min(axis=0)[::-1].tolist(),
                                                                   solid.max(axis=0)[::-1].tolist()] if len(solid) else None}
        return info

    @synchronized
    def undo(self):
        stack = self.model.undo_stack
        if not (self._mine and stack and stack[-1] is self._mine[-1]):
            raise ValueError("The last step in the editor is not yours (the user edited since): "
                             "the user can undo it there.")
        self._mine.pop()
        self.model.undo()
        self._follow()
        self._undone.append(self.model.redo_stack[-1])
        return {"changed": True, **self.info()}

    @synchronized
    def redo(self):
        stack = self.model.redo_stack
        if not (self._undone and stack and stack[-1] is self._undone[-1]):
            raise ValueError("Nothing of yours to redo.")
        self._undone.pop()
        self.model.redo()
        self._follow()
        self._mine.append(self.model.undo_stack[-1])
        return {"changed": True, **self.info()}

    def forget(self) -> None:
        """The window opened or started another model in the same Model: drop the last one's boxes and steps."""
        with self._lock:
            self._unprotect_all()
            self._mine, self._undone = [], []

    @synchronized
    def snapshot(self, version=None):
        """The model as data for the MCP server's pictures; {"same": True} when it still has `version`."""
        key = f"{id(self.model)}-{self.model.version}"
        if version == key:
            return {"same": True}
        return {"version": key, "shape": list(self.model.colour.shape),
                "colour": pack(self.model.colour), "material": pack(self.model.material),
                "local": [self.model.local[i] for i in sorted(self.model.local)]}

    def handle(self, op: str, args: dict):
        """One request from the MCP server; edits record their undo step as the assistant's."""
        with self._lock:
            self._bind()
            if op in self.EDITS:
                top = self.model.undo_stack[-1] if self.model.undo_stack else None
                result = getattr(self, op)(**args)
                if self.model.undo_stack and self.model.undo_stack[-1] is not top:
                    self._mine.append(self.model.undo_stack[-1])
                    self._undone.clear()
                return result
            if op in ("undo", "redo", "snapshot", *self.QUESTIONS):
                return getattr(self, op)(**args)
            if op in self._window:
                return self._window[op](**args)
            raise ValueError(f"The editor does not do {op!r} over the link.")


# --- the MCP server's side ------------------------------------------------------------------
class LiveClient:
    """A connection to the open editor: call(op, **args) returns the answer's result or raises."""

    def __init__(self):
        link = read_link()
        try:
            self._socket = socket.create_connection(("127.0.0.1", int(link["port"])), timeout=TIMEOUT)
        except OSError:
            raise ConnectionError("The editor's link file is there but nothing answers: is the editor still "
                                  "open? Start it, or turn Tools > Assistant link off and on.") from None
        self._file = self._socket.makefile("rb")
        self._lock = threading.Lock()
        self.mirror = Model()  # the editor's model as last copied, for pictures
        self.mirror_version = None
        self.hello = self.call("hello", token=link["token"])

    def call(self, op: str, **args):
        with self._lock:
            try:
                self._socket.sendall(json.dumps({"op": op, "args": args}).encode("utf-8") + b"\n")
                line = self._file.readline()
            except OSError as error:
                raise ConnectionError(f"The link to the editor broke ({error}).") from None
            if not line:
                raise ConnectionError("The editor closed the link (closed, or the link was turned off).")
        answer = json.loads(line)
        if "error" in answer:
            raise ValueError(answer["error"])
        return answer["result"]

    def model(self) -> Model:
        """The editor's model, copied when it changed since the last copy."""
        copy = self.call("snapshot", version=self.mirror_version)
        if not copy.get("same"):
            self.mirror.colour = unpack(copy["colour"], copy["shape"])
            self.mirror.material = unpack(copy["material"], copy["shape"])
            self.mirror.local = {m["id"]: m for m in copy["local"]}
            self.mirror.version += 1
            self.mirror_version = copy["version"]
        return self.mirror

    def close(self) -> None:
        try:
            self._file.close()
            self._socket.close()
        except OSError:
            pass

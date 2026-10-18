"""Parts and instances for the MCP server, as in a FEM assembly: a project's models are its parts, each
placed any number of times as instances (a position and an orientation) in its scenes. An instance never
copies its part's voxels, so an edit to a part shows in every instance of it.

ProjectOps works on a ProjectDocument: the window's (through the live link; every change is one step of
the scene's undo there and shows in the Project dock and the Scene view) or the server's own HeadlessProject.
Paths are relative to VoxelPipeline unless absolute.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from core.model import ROOT as PIPELINE, Model
from core.scene import IDENTITY, Project, mirrored, orient_from_text, orient_text, rotated

AXIS = {"x": 0, "y": 1, "z": 2}


class _Quiet:
    @staticmethod
    def emit(*args):
        pass


class HeadlessProject:
    """The server's own project, with a ProjectDocument's attributes and no Qt."""
    changed = selected = _Quiet()

    def __init__(self, tables_from: Model | None = None):
        self.tables_from = tables_from
        self.project = Project(tables_from=tables_from)
        self.scene = None
        self.instance = None

    def _record(self):
        pass

    def select(self, instance, scene=None):
        self.scene = scene or self.scene
        self.instance = instance

    def add_model(self, path) -> str:
        return self.project.add_model(path)

    def open_project(self, path):
        project = Project(tables_from=self.tables_from)
        project.load(path)
        self.project, self.scene, self.instance = project, (project.scenes[0] if project.scenes else None), None


def resolve(path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PIPELINE / path


class ProjectOps:
    def __init__(self, document):
        """document: a callable giving the ProjectDocument (or HeadlessProject) to work on."""
        self._document = document

    @property
    def doc(self):
        return self._document()

    # --- looking up ----------------------------------------------------------------------------
    def _scene(self, name=None, create=False):
        doc = self.doc
        if name is None:
            if doc.scene is None and create:
                doc.scene = doc.project.add_scene()
            if doc.scene is None:
                raise ValueError("The project has no scene yet: add an instance first, or name a scene.")
            return doc.scene
        for scene in doc.project.scenes:
            if scene.name == name:
                return scene
        if create:
            return doc.project.add_scene(name)
        raise ValueError(f"No scene {name!r}; the project has {[s.name for s in doc.project.scenes]}.")

    def _instance(self, scene, name):
        for instance in scene.instances:
            if instance.name == name:
                return instance
        raise ValueError(f"No instance {name!r} in {scene.name}.")

    @staticmethod
    def _orient(orient, turn=0, mirror=None, base=IDENTITY):
        o = orient_from_text(orient) if orient else base
        if mirror:
            o = mirrored(o, AXIS[mirror])
        if turn:
            o = rotated(o, 2, int(turn))
        return o

    def _describe(self, instance):
        lo, hi = self.doc.project.box(instance)
        return {**instance.to_json(), "box": [lo.tolist(), (hi - 1).tolist()]}

    def _done(self, instance=None, scene=None):
        doc = self.doc
        doc.changed.emit()
        if instance is not None or scene is not None:
            doc.select(instance, scene)

    # --- questions -----------------------------------------------------------------------------
    def project_info(self):
        doc = self.doc
        project = doc.project
        edited = set(project.modified_models())
        parts = {}
        for name, model in project.models.items():
            path = Path(model.path) if model.path else None
            parts[name] = {"file": str(path.relative_to(PIPELINE)) if path and path.is_relative_to(PIPELINE) else str(path),
                           "size": list(project.model_size(name)), "instances": len(project.instances_of(name)),
                           "edited": name in edited}
        scenes = [{"name": s.name, "shown": s is doc.scene, "instances": [self._describe(i) for i in s.instances]}
                  for s in project.scenes]
        file = str(project.path) if project.path else None
        return {"project": file, "parts": parts, "scenes": scenes}

    # --- parts and instances -------------------------------------------------------------------
    def add_part(self, path):
        """A .vx2 as a part of the project (once: a file already in it gives its name)."""
        doc = self.doc
        path = resolve(path)
        if path.suffix != ".vx2" or not path.is_file():
            raise ValueError(f"No .vx2 at {path}.")
        name = doc.add_model(path)  # the window's also reuses the model open in its docks
        return {"part": name, "size": list(doc.project.model_size(name))}

    def add_instance(self, part, position=None, orient=None, turn=0, mirror=None, scene=None):
        """An instance of a part (a part name, or a .vx2 path, which is added as a part first)."""
        doc = self.doc
        if part not in doc.project.models:
            if not str(part).endswith(".vx2"):
                raise ValueError(f"No part {part!r}: the project has {sorted(doc.project.models)} (or give a .vx2 path).")
            part = self.add_part(part)["part"]
        target = self._scene(scene, create=True)
        if target is doc.scene:
            doc._record()
        instance = doc.project.add_instance(target, part, position, self._orient(orient, turn, mirror))
        self._done(instance, target)
        return self._describe(instance)

    def move_instance(self, name, position=None, by=None, orient=None, turn=0, mirror=None, scene=None):
        """Move an instance (position: its box's low corner; by: [dx, dy, dz]) and turn it: orient sets the
        orientation outright; turn (quarter turns about z) and mirror ("x" or "y") keep its centre and bottom."""
        doc = self.doc
        target = self._scene(scene)
        instance = self._instance(target, name)
        if target is doc.scene:
            doc._record()
        if orient:
            instance.orient = orient_from_text(orient)
        if mirror:
            instance.orient = mirrored(instance.orient, AXIS[mirror])
        if turn:
            doc.project.reorient(instance, rotated(instance.orient, 2, int(turn)))
        if position is not None:
            instance.position = tuple(int(v) for v in position)
        if by is not None:
            instance.position = tuple(int(a + b) for a, b in zip(instance.position, by))
        self._done(instance, target)
        return self._describe(instance)

    def remove_instance(self, name, scene=None):
        doc = self.doc
        target = self._scene(scene)
        instance = self._instance(target, name)
        if target is doc.scene:
            doc._record()
        doc.project.remove_instance(target, instance)
        if doc.instance is instance:
            doc.instance = None
        self._done(None, target)
        return {"removed": name, "left": len(target.instances)}

    def merged(self, scene=None):
        """The scene as one volume (colour, material, low corner, own materials), later instances winning."""
        return self.doc.project.merged(self._scene(scene))


def stamp(colour: np.ndarray, material: np.ndarray, part_colour, part_material, position, empty_only=False):
    """Write a placed part's solid voxels into (z, y, x) planes at position (x, y, z), clipped at the edges."""
    sz, sy, sx = colour.shape
    pz, py, px = part_colour.shape
    x, y, z = (int(v) for v in position)
    src = (slice(max(0, -z), min(pz, sz - z)), slice(max(0, -y), min(py, sy - y)), slice(max(0, -x), min(px, sx - x)))
    dst = (slice(max(0, z), min(sz, z + pz)), slice(max(0, y), min(sy, y + py)), slice(max(0, x), min(sx, x + px)))
    if any(s.start >= s.stop for s in src):
        return
    solid = part_colour[src] > 0
    if empty_only:
        solid &= colour[dst] == 0
    colour[dst][solid] = part_colour[src][solid]
    material[dst][solid] = part_material[src][solid]


__all__ = ["HeadlessProject", "ProjectOps", "orient_text", "resolve", "stamp"]

"""The open project (models and scenes), the scene shown and the selected instance.

The outliner, the scene view and the transform panel change the project only
through here, and redraw on `changed` (models, scenes, instances or placements)
and `selected`. Each change to a scene is one undo step (Ctrl+Z while the
outliner, the scene view or the transform panel has focus). A model's voxels
are edited through the model docks' Document, which then edits the project's
Model itself; the scene view redraws on its `changed`.
"""
from __future__ import annotations

import numpy as np
from PySide6 import QtCore

from core.scene import Instance, Project, Scene, mirrored, rotated

HISTORY_LIMIT = 100


class ProjectDocument(QtCore.QObject):
    changed = QtCore.Signal()   # models, scenes, instances or placements
    selected = QtCore.Signal()  # the scene shown or the selected instance
    edit_model = QtCore.Signal(str)  # open this model in the model docks

    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.project = Project(tables_from=doc.model)
        self.scene: Scene | None = None
        self.instance: Instance | None = None
        self.undo_stack, self.redo_stack = [], []

    # --- undo: a scene's instances (as JSON) and which one was selected ---------------------------
    def _snapshot(self):
        index = self.scene.instances.index(self.instance) if self.instance in (self.scene.instances or []) else None
        return self.scene, [i.to_json() for i in self.scene.instances], index

    def _record(self):
        if self.scene is not None:
            self.undo_stack.append(self._snapshot())
            del self.undo_stack[:-HISTORY_LIMIT]
            self.redo_stack.clear()

    def _restore(self, source, target) -> bool:
        if not source:
            return False
        scene, instances, index = source.pop()
        if scene not in self.project.scenes:
            return False
        self.scene = scene
        target.append(self._snapshot())
        scene.instances[:] = [Instance.from_json(i) for i in instances]
        self.instance = scene.instances[index] if index is not None else None
        self.changed.emit()
        self.selected.emit()
        return True

    def undo(self) -> bool:
        return self._restore(self.undo_stack, self.redo_stack)

    def redo(self) -> bool:
        return self._restore(self.redo_stack, self.undo_stack)

    # --- files ------------------------------------------------------------------------------
    def _replace(self, project: Project) -> None:
        self.project = project
        self.scene = project.scenes[0] if project.scenes else None
        self.instance = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.changed.emit()
        self.selected.emit()

    def new_project(self) -> None:
        self._replace(Project(tables_from=self.doc.model))

    def open_project(self, path) -> None:
        project = Project(tables_from=self.doc.model)
        project.load(path, reuse=[self.doc.model])
        self._replace(project)

    def import_vox(self, path) -> None:
        """A MagicaVoxel scene of several models as a new project of parts and instances."""
        project = Project(tables_from=self.doc.model)
        project.import_vox(path)
        self._replace(project)

    def save_project(self, name: str | None = None):
        target = self.project.save(name)
        self.changed.emit()
        return target

    # --- models and scenes ------------------------------------------------------------------
    def add_model(self, path) -> str:
        name = self.project.add_model(path, reuse=[self.doc.model])
        self.changed.emit()
        return name

    def new_scene(self) -> Scene:
        scene = self.project.add_scene()
        self.changed.emit()
        self.show_scene(scene)
        return scene

    def remove_scene(self, scene: Scene) -> None:
        self.project.remove_scene(scene)
        if self.scene is scene:
            self.scene = self.project.scenes[0] if self.project.scenes else None
            self.instance = None
        self.changed.emit()
        self.selected.emit()

    def show_scene(self, scene: Scene | None) -> None:
        if scene is not self.scene:
            self.scene = scene
            self.instance = None
            self.selected.emit()

    # --- instances ----------------------------------------------------------------------------
    def add_instance(self, model: str) -> Instance:
        """An instance of a model in the scene shown (a new scene if there is none), selected."""
        if self.scene is None:
            self.scene = self.project.add_scene()
        self._record()
        instance = self.project.add_instance(self.scene, model)
        self.changed.emit()
        self.select(instance)
        return instance

    def select(self, instance: Instance | None, scene: Scene | None = None) -> None:
        if scene is not None and scene is not self.scene:
            self.scene = scene
            self.instance = instance
            self.selected.emit()
        elif instance is not self.instance:
            self.instance = instance
            self.selected.emit()

    def move_to(self, position, record: bool = True) -> None:
        """Put the selected instance's box low corner here (record=False while a drag continues one step)."""
        position = tuple(int(v) for v in position)
        if self.instance is not None and position != self.instance.position:
            if record:
                self._record()
            self.instance.position = position
            self.changed.emit()

    def move(self, dx: int, dy: int, dz: int) -> None:
        if self.instance is not None:
            self.move_to(np.add(self.instance.position, (dx, dy, dz)))

    def begin_drag(self) -> None:
        """A drag in the scene view is one undo step: recorded once at its start."""
        self._record()

    def rotate(self, axis: int = 2, quarter_turns: int = 1) -> None:
        """Turn the selected instance about a scene axis (0 x, 1 y, 2 z), keeping its centre and its bottom."""
        if self.instance is not None:
            self._record()
            self.project.reorient(self.instance, rotated(self.instance.orient, axis, quarter_turns))
            self.changed.emit()

    def mirror(self, axis: int = 0) -> None:
        if self.instance is not None:
            self._record()
            self.instance.orient = mirrored(self.instance.orient, axis)
            self.changed.emit()

    def reset_orientation(self) -> None:
        if self.instance is not None and self.instance.orient != ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            self._record()
            self.project.reorient(self.instance, ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
            self.changed.emit()

    def duplicate(self) -> Instance | None:
        """A linked copy beside the selected instance (along x, past its box), selected."""
        if self.instance is None:
            return None
        self._record()
        copy = self.project.array_grid(self.scene, self.instance, (2, 1, 1))[0]
        self.changed.emit()
        self.select(copy)
        return copy

    def array_grid(self, counts, gap: int) -> list[Instance]:
        if self.instance is None:
            return []
        self._record()
        made = self.project.array_grid(self.scene, self.instance, counts, gap)
        self.changed.emit()
        return made

    def array_circle(self, count: int, radius: float, face_out: bool) -> list[Instance]:
        if self.instance is None:
            return []
        self._record()
        made = self.project.array_circle(self.scene, self.instance, count, radius, face_out)
        self.changed.emit()
        return made

    def delete(self) -> None:
        if self.instance is not None:
            self._record()
            self.project.remove_instance(self.scene, self.instance)
            self.instance = None
            self.changed.emit()
            self.selected.emit()

    def request_edit(self, model: str | None = None) -> None:
        model = model or (self.instance.model if self.instance is not None else None)
        if model in self.project.models:
            self.edit_model.emit(model)

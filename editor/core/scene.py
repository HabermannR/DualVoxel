"""Projects: models (.vx2) and scenes of instances placed from them.

A model is loaded once, as one Model; an instance names its model and never
copies its voxels, so an edit to the model shows in every instance of it. An
instance has a position (the integer low corner of its box in the scene) and an
orientation: any quarter-turn rotation, mirrored or not, written as where the
model's x, y and z axes point in the scene ("+x+y+z" as modelled, "+y-x+z" a
quarter turn counter-clockwise about z seen from above, "-x+y+z" mirrored in x).
A project can hold several scenes.

A project is a JSON file, assets/<name>.project.json, with model paths relative
to it and one line per instance:

    {"format": "voxelpipeline-project", "version": 1,
     "models": {"alchemist": "alchemist.vx2"},
     "scenes": [{"name": "Scene-1", "instances": [
       {"name": "alchemist-1", "model": "alchemist", "position": [0, 0, 0], "orient": "+x+y+z"}]}]}
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from core.model import SAVE_ROOT, Model, read_vox_scene

FORMAT = "voxelpipeline-project"
SUFFIX = ".project.json"
GAP = 4  # voxels between a new instance and what the scene already holds
AXES = "xyz"
IDENTITY = ((1, 0, 0), (0, 1, 0), (0, 0, 1))


def share_tables(model: Model, base: Model | None) -> Model:
    """Give a model the base model's colour and material tables (the same objects), so a session's
    material edits reach every model."""
    if base is not None:
        model.colors, model.materials = base.colors, base.materials
        model.table_labs, model.by_id = base.table_labs, base.by_id
    return model


# --- orientation: a signed permutation matrix; column j is where the model's axis j points ------------
def orient_text(orient) -> str:
    m = np.asarray(orient)
    return "".join(("+" if m[:, j].sum() > 0 else "-") + AXES[int(np.flatnonzero(m[:, j])[0])] for j in range(3))


def orient_from_text(text: str):
    m = np.zeros((3, 3), dtype=int)
    for j in range(3):
        sign, axis = text[2 * j], text[2 * j + 1]
        m[AXES.index(axis), j] = 1 if sign == "+" else -1
    if sorted(np.abs(m).sum(axis=0)) != [1, 1, 1] or sorted(np.abs(m).sum(axis=1)) != [1, 1, 1]:
        raise ValueError(f"not an orientation: {text!r}")
    return _tuple(m)


def rotated(orient, axis: int, quarter_turns: int = 1):
    """Turn by quarter turns about a scene axis (0 x, 1 y, 2 z), counter-clockwise looking down the axis."""
    b, c = (axis + 1) % 3, (axis + 2) % 3
    step = np.eye(3, dtype=int)
    step[[b, c], [b, c]] = 0
    step[c, b], step[b, c] = 1, -1
    m = np.asarray(orient)
    for _ in range(quarter_turns % 4):
        m = step @ m
    return _tuple(m)


def mirrored(orient, axis: int):
    """Mirror along a scene axis."""
    flip = np.eye(3, dtype=int)
    flip[axis, axis] = -1
    return _tuple(flip @ np.asarray(orient))


def _tuple(m) -> tuple:
    return tuple(tuple(int(v) for v in row) for row in m)


def _source(orient, i):
    """(model axis, sign) feeding scene axis i."""
    row = np.asarray(orient)[i]
    j = int(np.flatnonzero(row)[0])
    return j, int(row[j])


def place_plane(plane: np.ndarray, orient=IDENTITY) -> np.ndarray:
    """A model's (z, y, x) plane as oriented in the scene (before the position)."""
    xyz = plane.transpose(2, 1, 0)
    sources = [_source(orient, i) for i in range(3)]
    placed = xyz.transpose([j for j, _ in sources])
    placed = placed[tuple(slice(None, None, -1) if s < 0 else slice(None) for _, s in sources)]
    return np.ascontiguousarray(placed.transpose(2, 1, 0))


def place_point(point, size, orient=IDENTITY) -> tuple[int, int, int]:
    """Where a model voxel (x, y, z) lands in its oriented box (before the position); size is the model's (x, y, z)."""
    out = []
    for i in range(3):
        j, s = _source(orient, i)
        out.append(int(point[j]) if s > 0 else int(size[j]) - 1 - int(point[j]))
    return tuple(out)


def placed_size(size, orient=IDENTITY) -> tuple[int, int, int]:
    return tuple(int(size[_source(orient, i)[0]]) for i in range(3))


@dataclass(eq=False)  # compared by identity: two instances may sit at the same place
class Instance:
    name: str
    model: str
    position: tuple[int, int, int] = (0, 0, 0)
    orient: tuple = IDENTITY

    def to_json(self) -> dict:
        return {"name": self.name, "model": self.model, "position": list(self.position),
                "orient": orient_text(self.orient)}

    @classmethod
    def from_json(cls, data: dict) -> "Instance":
        return cls(data["name"], data["model"], tuple(int(v) for v in data.get("position", (0, 0, 0))),
                   orient_from_text(data.get("orient", "+x+y+z")))


@dataclass(eq=False)
class Scene:
    name: str
    instances: list[Instance] = field(default_factory=list)


class Project:
    def __init__(self, tables_from: Model | None = None):
        self.tables_from = tables_from
        self.path: Path | None = None
        self.models: dict[str, Model] = {}  # name -> its one Model; its .path is the model's file
        self.scenes: list[Scene] = []
        self._saved_versions: dict[str, int] = {}

    # --- models ----------------------------------------------------------------------------
    def add_model(self, path, reuse=()) -> str:
        """Load a .vx2 into the project (once: a model already in it, or one in `reuse` with that path, is
        used as it is). Returns its name in the project."""
        path = Path(path).resolve()
        for name, model in self.models.items():
            if model.path is not None and Path(model.path).resolve() == path:
                return name
        model = next((m for m in reuse if m.path is not None and Path(m.path).resolve() == path), None)
        if model is None:
            if path.suffix != ".vx2":
                raise ValueError("scenes place .vx2 models")
            model = share_tables(Model(), self.tables_from)
            model.open(path)
        name = self._unique(path.stem, self.models)
        self.models[name] = model
        self._saved_versions[name] = model.version
        return name

    def model_size(self, name: str) -> tuple[int, int, int]:
        sz, sy, sx = self.models[name].colour.shape
        return sx, sy, sz

    def name_of(self, model: Model) -> str | None:
        return next((name for name, m in self.models.items() if m is model), None)

    def instances_of(self, model: str) -> list[tuple[Scene, Instance]]:
        return [(s, i) for s in self.scenes for i in s.instances if i.model == model]

    def mark_saved(self, model: str) -> None:
        """The model's file now holds its voxels (saved from the model editor)."""
        self._saved_versions[model] = self.models[model].version

    def modified_models(self) -> list[str]:
        return [name for name, m in self.models.items() if m.version != self._saved_versions.get(name)]

    # --- scenes and instances -----------------------------------------------------------------
    def add_scene(self, name: str | None = None) -> Scene:
        scene = Scene(self._unique(name or "Scene", {s.name for s in self.scenes}, always_number=not name))
        self.scenes.append(scene)
        return scene

    def remove_scene(self, scene: Scene) -> None:
        self.scenes.remove(scene)

    def add_instance(self, scene: Scene, model: str, position=None, orient=IDENTITY) -> Instance:
        """Place an instance of a model; by default to the right of what the scene holds."""
        if model not in self.models:
            raise KeyError(f"no model {model!r}")
        if position is None:
            position = (int(self.bounds(scene)[1][0]) + GAP, 0, 0) if scene.instances else (0, 0, 0)
        instance = Instance(self._unique(model, {i.name for i in scene.instances}, always_number=True), model,
                            tuple(int(v) for v in position), _tuple(orient))
        scene.instances.append(instance)
        return instance

    def remove_instance(self, scene: Scene, instance: Instance) -> None:
        scene.instances.remove(instance)

    def size_of(self, instance: Instance) -> np.ndarray:
        return np.array(placed_size(self.model_size(instance.model), instance.orient))

    def box(self, instance: Instance):
        """(low corner, high corner exclusive) of an instance in scene voxels."""
        lo = np.array(instance.position)
        return lo, lo + self.size_of(instance)

    def bounds(self, scene: Scene):
        """(low, high exclusive) over the scene's instances; a 32-voxel box when it is empty."""
        if not scene.instances:
            return np.zeros(3, dtype=int), np.full(3, 32)
        boxes = [self.box(i) for i in scene.instances]
        return np.min([b[0] for b in boxes], axis=0), np.max([b[1] for b in boxes], axis=0)

    def reorient(self, instance: Instance, orient) -> None:
        """A new orientation, keeping the box's centre across and its bottom where they were."""
        lo, hi = self.box(instance)
        centre = (lo + hi) / 2
        instance.orient = _tuple(orient)
        lo2, hi2 = self.box(instance)
        x, y = np.floor(centre[:2] - (lo2[:2] + hi2[:2]) / 2).astype(int) + lo2[:2]
        instance.position = (int(x), int(y), int(lo[2]))

    def placed_planes(self, instance: Instance):
        """The instance's (colour, material) planes as placed, read from its model now."""
        model = self.models[instance.model]
        return place_plane(model.colour, instance.orient), place_plane(model.material, instance.orient)

    def merged(self, scene: Scene):
        """The scene as one volume: (colour, material, low corner, its own materials); later instances
        win where they overlap. The models' own materials (ids 128 up, each model numbering its own)
        are renumbered into one list, identical ones shared."""
        lo, hi = self.bounds(scene)
        sx, sy, sz = hi - lo
        colour = np.zeros((sz, sy, sx), dtype=np.uint8)
        material = np.zeros_like(colour)
        local: list[dict] = []
        for instance in scene.instances:
            c, m = self.placed_planes(instance)
            model = self.models[instance.model]
            if model.local:
                m = m.copy()
                for mid in np.unique(m):
                    if int(mid) in model.local:
                        key = {k: v for k, v in model.local[int(mid)].items() if k != "id"}
                        same = next((own["id"] for own in local if {k: v for k, v in own.items() if k != "id"} == key), None)
                        if same is None:
                            same = 128 + len(local)
                            if same > 255:
                                raise ValueError("the scene's models have more than 128 own materials together")
                            local.append(dict(key, id=same))
                        m[m == mid] = same
            x, y, z = np.array(instance.position) - lo
            solid = c > 0
            region = (slice(z, z + c.shape[0]), slice(y, y + c.shape[1]), slice(x, x + c.shape[2]))
            colour[region][solid] = c[solid]
            material[region][solid] = m[solid]
        return colour, material, lo, local

    # --- arrays: copies of an instance in a pattern, each a plain instance of the same model -------------
    def array_grid(self, scene: Scene, instance: Instance, counts=(1, 1, 1), gap: int = GAP) -> list[Instance]:
        """Copies in a grid of counts (x, y, z), the instance at the low corner, `gap` voxels between boxes."""
        step = self.size_of(instance) + gap
        made = []
        for k in np.ndindex(*(max(1, int(n)) for n in counts)):
            if any(k):
                made.append(self.add_instance(scene, instance.model, np.array(instance.position) + step * k,
                                              instance.orient))
        return made

    def array_circle(self, scene: Scene, instance: Instance, count: int, radius: float,
                     face_out: bool = True) -> list[Instance]:
        """`count` around a circle about z (the instance is the first, the centre `radius` voxels behind
        it, i.e. towards +y: a model's front is -y). With face_out each copy turns to face away from the
        centre, to the nearest quarter turn."""
        lo, hi = self.box(instance)
        centre = (lo + hi) / 2 + np.array([0, radius, 0])
        made = []
        for k in range(1, max(1, int(count))):
            angle = -math.pi / 2 + 2 * math.pi * k / count
            orient = rotated(instance.orient, 2, round(math.degrees(angle + math.pi / 2) / 90)) if face_out \
                else instance.orient
            size = placed_size(self.model_size(instance.model), orient)
            x = centre[0] + radius * math.cos(angle) - size[0] / 2
            y = centre[1] + radius * math.sin(angle) - size[1] / 2
            made.append(self.add_instance(scene, instance.model, (round(x), round(y), int(lo[2])), orient))
        return made

    # --- files -------------------------------------------------------------------------------
    def save(self, name: str | None = None, save_models: bool = True) -> Path:
        """Write assets/<name>.project.json (by default over the open project); models edited since they were
        loaded or saved are saved too (into assets/, as the model editor saves)."""
        if name is not None:
            if not name or any(ch in name for ch in "/\\:") or name.startswith("."):
                raise ValueError("give a plain file name, saved into assets/")
            target = SAVE_ROOT / f"{name.removesuffix(SUFFIX)}{SUFFIX}"
        elif self.path is not None:
            target = self.path
        else:
            raise ValueError("name the project")
        if save_models:
            for name_ in self.modified_models():
                model = self.models[name_]
                model.save(Path(model.path).stem if model.path else name_)
                self.mark_saved(name_)
        missing = [n for n, m in self.models.items() if m.path is None]
        if missing:
            raise ValueError(f"save these models first: {', '.join(missing)}")
        data = {"format": FORMAT, "version": 1,
                "models": {n: os.path.relpath(m.path, target.parent).replace("\\", "/") for n, m in self.models.items()},
                "scenes": [{"name": s.name, "instances": [i.to_json() for i in s.instances]} for s in self.scenes]}
        target.write_text(_dumps(data), encoding="utf-8")
        self.path = target
        return target

    def load(self, path, reuse=()) -> None:
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") != FORMAT:
            raise ValueError(f"{path.name} is not a {FORMAT} file")
        self.models.clear()
        self._saved_versions.clear()
        self.scenes.clear()
        for name, relative in data.get("models", {}).items():
            loaded = self.add_model(path.parent / relative, reuse)
            if loaded != name:  # keep the file's names, which the instances use
                self.models[name] = self.models.pop(loaded)
                self._saved_versions[name] = self._saved_versions.pop(loaded)
        for entry in data.get("scenes", []):
            scene = Scene(entry["name"], [Instance.from_json(i) for i in entry.get("instances", [])])
            unknown = {i.model for i in scene.instances} - set(self.models)
            if unknown:
                raise ValueError(f"{scene.name} uses models the project does not list: {', '.join(sorted(unknown))}")
            self.scenes.append(scene)
        self.path = path

    def import_vox(self, path) -> None:
        """A MagicaVoxel file of several models as a new, unsaved project: each model a part (saved into
        assets/ as <file>-<n>.vx2 with the project), its scene as a scene of instances. An animated shape's
        frames are parts too; they stand side by side in a second scene, "<file> frames"."""
        path = Path(path)
        data = read_vox_scene(path)
        self.models.clear()
        self._saved_versions.clear()
        self.scenes.clear()
        self.path = None
        names = {}
        for k, (size, voxels) in enumerate(data["models"]):
            model = share_tables(Model(), self.tables_from)
            model.colour, model.material = model.import_vox_model(size, voxels, data["palette"], data["materials"])
            names[k] = self._unique(f"{path.stem}-{k}", self.models)
            self.models[names[k]] = model  # no file and no saved version yet: the project's save writes it
        scene = Scene(path.stem)
        self.scenes.append(scene)
        for placement in data["placements"]:
            instance = Instance(self._unique(placement["name"], {i.name for i in scene.instances}, always_number=True),
                                names[placement["model"]], placement["position"], _tuple(placement["orient"]))
            scene.instances.append(instance)
        if data["frames"]:
            frames = self.add_scene(f"{path.stem} frames")
            for shape in data["frames"]:
                for k in shape:
                    self.add_instance(frames, names[k])

    @staticmethod
    def _unique(base: str, taken, always_number: bool = False) -> str:
        if not always_number and base not in taken:
            return base
        n = 1
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"


def _dumps(data: dict) -> str:
    """The project as JSON with one line per instance, so the file reads and diffs well."""
    models = json.dumps(data["models"], indent=4).replace("\n}", "\n  }")
    lines = ["{", f'  "format": {json.dumps(data["format"])},', f'  "version": {data["version"]},',
             f'  "models": {models},', '  "scenes": [']
    for n, scene in enumerate(data["scenes"]):
        instances = ",\n".join(f"      {json.dumps(i)}" for i in scene["instances"])
        body = f"\n{instances}\n    " if instances else ""
        comma = "," if n < len(data["scenes"]) - 1 else ""
        lines.append(f'    {{"name": {json.dumps(scene["name"])}, "instances": [{body}]}}{comma}')
    lines += ["  ]", "}", ""]
    return "\n".join(lines)

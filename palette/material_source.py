r"""Write materials back into their source, palette/build_materials.py, and follow through.

The material table's source is the MATERIALS list (and LIGHTS) in build_materials.py;
materials.json is generated from it. save_table() writes a whole table back there
(only rows that changed are rewritten, new materials are appended), runs the build,
and restamps the .vx2 files that were made with the previous table, so they still
open. Ids never change meaning: materials are edited or appended, never removed or
reordered, which is what makes the restamp safe.

send_tables() is separate and explicit: it copies colors.json and materials.json
into another project's assets/palette (a "send_tables" target of editor.local.json)
and restamps that project's .vx2 files, only when every material it knew keeps its
id and name and the colour table is the same.

    from material_source import save_table
    report = save_table(materials)      # materials: the list of dicts, as in materials.json
"""
from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import vx2  # noqa: E402

NUMBERS = ("roughness", "metal", "emission", "ior", "transmission", "density", "sss", "subsurface", "sheen")
WHOLE = ("metal", "emission", "transmission", "density", "sss", "subsurface", "sheen")  # written 0, 1, 4 when whole
MAX_LINE = 118


def source_fields(source: Path = HERE / "build_materials.py") -> list[str]:
    """The column names of MATERIALS' rows: build_materials.py's FIELDS."""
    return ast.literal_eval(_module_assign(ast.parse(source.read_text(encoding="utf-8")), "FIELDS").value)


def row_values(m: dict, fields: list[str]) -> tuple:
    """A material as MATERIALS' tuple (numbers rounded to three places; whole numbers as the
    source writes them, 0, 1, 4)."""
    values = []
    for f in fields:
        v = m[f]
        if f in NUMBERS:
            v = round(float(v), 3)
            if v == int(v) and f in WHOLE:
                v = int(v)
        values.append(v)
    return tuple(values)


def row_text(m: dict, indent: str = "    ", fields: list[str] | None = None) -> str:
    """The material as a source row, wrapped before the note when the line would be too long."""
    values = row_values(m, fields or source_fields())

    def lit(v):
        return json.dumps(v, ensure_ascii=False) if isinstance(v, str) else repr(v)
    head = ", ".join(lit(v) for v in values[:-1])
    line = f"{indent}({head}, {lit(values[-1])}),"
    if len(line) <= MAX_LINE:
        return line
    return f"{indent}({head},\n{indent} {lit(values[-1])}),"


def _module_assign(tree: ast.Module, name: str) -> ast.Assign:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node
    raise ValueError(f"build_materials.py has no {name}")


def write_source(materials: list[dict], source: Path = HERE / "build_materials.py") -> dict:
    """Rewrite the rows of `materials` that differ from the source, append new ids, update LIGHTS.
    Returns {"changed": [ids], "added": [ids]}."""
    text = source.read_text(encoding="utf-8")
    lines = text.split("\n")
    tree = ast.parse(text)
    rows = _module_assign(tree, "MATERIALS").value
    lights_node = _module_assign(tree, "LIGHTS")
    fields = ast.literal_eval(_module_assign(tree, "FIELDS").value)
    known = {}
    for element in rows.elts:
        value = ast.literal_eval(element)
        known[value[0]] = (element.lineno, element.end_lineno, value)
    by_id = {m["id"]: m for m in materials}
    if sorted(by_id) != list(range(len(by_id))):
        raise ValueError("material ids must be 0..n-1 without gaps")
    missing = set(known) - set(by_id)
    if missing:
        raise ValueError(f"materials are never removed: ids {sorted(missing)} are missing")
    edits = []  # (first line, last line, replacement lines), 1-based inclusive
    changed, added = [], []
    for mid, (first, last, value) in known.items():
        if row_values(by_id[mid], fields) != tuple(value):
            edits.append((first, last, row_text(by_id[mid], fields=fields).split("\n")))
            changed.append(mid)
    new_ids = sorted(set(by_id) - set(known))
    if new_ids:
        closing = rows.end_lineno  # the line holding MATERIALS' closing bracket
        block = [line for mid in new_ids for line in row_text(by_id[mid], fields=fields).split("\n")]
        edits.append((closing, closing - 1, block))  # insert before the bracket
        added = new_ids
    lights = {m["id"]: m["light"] for m in materials if m.get("light")}
    if lights != ast.literal_eval(lights_node.value):
        edits.append((lights_node.lineno, lights_node.end_lineno,
                      [f"LIGHTS = {{{', '.join(f'{k}: {json.dumps(v)}' for k, v in sorted(lights.items()))}}}"]))
    for first, last, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        lines[first - 1:last] = replacement
    if edits:
        source.write_text("\n".join(lines), encoding="utf-8")
    return {"changed": changed, "added": added, "lights": lights != ast.literal_eval(lights_node.value)}


def rebuild(source: Path = HERE / "build_materials.py") -> None:
    """Run build_materials.main() from `source` (it writes materials.json and materials.html beside it)."""
    spec = importlib.util.spec_from_file_location("build_materials_fresh", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()


def _fingerprints(palette: Path) -> tuple[bytes, bytes]:
    colors = json.loads((palette / "colors.json").read_text(encoding="utf-8"))["colors"]
    materials = json.loads((palette / "materials.json").read_text(encoding="utf-8"))["materials"]
    return vx2.fingerprints(colors, materials)


def _stamp(path: Path) -> tuple[bytes, bytes]:
    data = path.read_bytes()
    header = vx2.HEADER.unpack_from(data)
    return header[5], header[6]


def restamp(files, before: tuple[bytes, bytes], root: Path = ROOT) -> dict:
    """Restamp the .vx2 files stamped with the `before` tables to root's current tables; leave the
    others (already stale before this change) alone."""
    done, skipped = [], []
    previous, vx2.ROOT = vx2.ROOT, root  # vx2 reads the tables under its ROOT
    try:
        for path in files:
            if _stamp(path) != before:
                skipped.append(path)
                continue
            colour, material, local = vx2.read_model(path, check_tables=False)
            vx2.write(path, colour, material, local)  # a model's own materials stay with it
            done.append(path)
    finally:
        vx2.ROOT = previous
    return {"restamped": done, "skipped": skipped}


def save_table(materials: list[dict], root: Path = ROOT) -> dict:
    """Write the table into build_materials.py, rebuild materials.json, restamp assets/**/*.vx2."""
    palette = root / "palette"
    before = _fingerprints(palette)
    report = write_source(materials, palette / "build_materials.py")
    rebuild(palette / "build_materials.py")
    report |= restamp(sorted((root / "assets").rglob("*.vx2")), before, root)
    return report


def send_tables(project: Path, root: Path = ROOT) -> dict:
    """Copy the tables into a project's assets/palette and restamp its .vx2 files, if no number changes
    meaning there: the colour table must be the same and every material it knows keep its id and name."""
    ours, theirs = root / "palette", project / "assets" / "palette"
    load = lambda p, key: json.loads(p.read_text(encoding="utf-8"))[key]
    if load(ours / "colors.json", "colors") != load(theirs / "colors.json", "colors"):
        raise ValueError("the colour tables differ; sending only carries material changes")
    new = {m["id"]: m["name"] for m in load(ours / "materials.json", "materials")}
    for m in load(theirs / "materials.json", "materials"):
        if new.get(m["id"]) != m["name"]:
            raise ValueError(f"material {m['id']} ({m['name']}) would change meaning in {project.name}")
    before = _fingerprints(theirs)
    for name in ("colors.json", "materials.json"):
        shutil.copyfile(ours / name, theirs / name)
    return restamp(sorted((project / "assets").glob("*.vx2")), before, root)

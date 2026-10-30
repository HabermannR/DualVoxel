"""Rewrite the keys tables in guide.md (section 8) from qtui/keymap.py, the editor's one list of keys.

    ..\\.venv\\Scripts\\python.exe keys_table.py

The tables show the default keys; tests/test_keys_zoom_smear.py checks the guide has them.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

START, END = "<!-- keys: made by docs/keys_table.py from qtui/keymap.py -->", "<!-- /keys -->"


def main() -> None:
    from qtui.keymap import guide_table
    guide = HERE / "guide.md"
    text = guide.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise SystemExit(f"guide.md has no {START} … {END} block")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    guide.write_text(f"{head}{START}\n{guide_table()}{END}{tail}", encoding="utf-8")
    print("guide.md: keys tables rewritten")


if __name__ == "__main__":
    main()

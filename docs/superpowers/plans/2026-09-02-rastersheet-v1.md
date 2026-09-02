# RasterSheet V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Blender extension that rotates the active object through a series of angles, renders each as a transparent PNG, packs them into a sprite sheet, exports metadata, and leaves the scene byte-for-byte as it found it.

**Architecture:** A core/shell split. `rastersheet/core/` contains every computation that can be wrong — angle schedules, transform matrices, orthographic framing, sheet geometry, metadata, Godot resource text — and imports only `mathutils`, `numpy`, and the standard library, never `bpy`. `rastersheet/blender/` is a thin shell of Blender API calls: properties, panel, operator, snapshot/restore, camera, lighting, render loop, pixel packing, file writing. Core is tested by fast pytest runs under system Python; the shell is tested by a headless Blender smoke script.

**Tech Stack:** Python 3.14, Blender 5.2 LTS (extension format, minimum 4.2), `mathutils` 5.1.0, `numpy`, pytest 9.

**Spec:** `docs/superpowers/specs/2026-09-01-rastersheet-design.md`

## Global Constraints

- Packaging is a Blender **extension**: `blender_manifest.toml` with `schema_version = "1.0.0"`, `type = "add-on"`, `blender_version_min = "4.2.0"`, `license = ["SPDX:GPL-3.0-or-later"]`. There is no `bl_info` dict anywhere in the codebase.
- **No module under `rastersheet/core/` may import `bpy`**, directly or transitively. A test enforces this by AST inspection.
- **`rastersheet/__init__.py` must not import `bpy` at module level.** Its `register()` and `unregister()` import the shell inside the function body, so that `import rastersheet.core.<module>` works under plain pytest.
- The extension ships **no wheels**. `mathutils` and `numpy` come from Blender at runtime and from the dev venv during testing.
- The add-on must never parent objects, change origins, apply transforms, delete user cameras, insert keyframes, or alter object hierarchy. Every scene mutation is registered for restoration at the moment it is made.
- Blender's image pixel buffer is **bottom-up**; `core.layout` emits **top-left-origin** rectangles. The flip lives in exactly one place, `rastersheet/blender/packing.py`.
- The dev venv is `.venv/` at the repo root. All pytest commands are run as `.venv/bin/pytest`.
- Blender is invoked as `blender`, resolving to `/home/yalt/.local/bin/blender` (5.2.0 LTS).
- Smoke output is redirected to a log file and the exit code echoed separately. Never pipe a Blender run through `tail` or `grep` when its exit code matters — the pipeline returns the last command's status and a failure disappears.
- Scratch directory for logs and render output during testing: `/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad`. Referred to below as `$SCRATCH`.

## File Structure

| File | Responsibility |
|---|---|
| `rastersheet/blender_manifest.toml` | Extension metadata |
| `rastersheet/__init__.py` | `register()` / `unregister()`, no top-level bpy |
| `rastersheet/core/angles.py` | Frame angle schedule |
| `rastersheet/core/paths.py` | Filenames and derived output paths |
| `rastersheet/core/rotation.py` | Axis resolution and per-frame world matrices |
| `rastersheet/core/layout.py` | `SheetLayout`, `Cell`, sheet geometry |
| `rastersheet/core/framing.py` | Projected bounds to `ortho_scale` |
| `rastersheet/core/metadata.py` | JSON document |
| `rastersheet/core/godot.py` | `SpriteFrames` `.tres` text |
| `rastersheet/blender/registration.py` | The class list, `register()` / `unregister()` |
| `rastersheet/blender/properties.py` | `RasterSheetSettings` PropertyGroup |
| `rastersheet/blender/panel.py` | View3D sidebar panel |
| `rastersheet/blender/operator.py` | `rastersheet.render`, pre-flight validation, orchestration |
| `rastersheet/blender/snapshot.py` | ExitStack-based capture and restore |
| `rastersheet/blender/camera.py` | Current camera and temporary orthographic camera |
| `rastersheet/blender/lighting.py` | Temporary world construction |
| `rastersheet/blender/render.py` | Frame loop generator |
| `rastersheet/blender/packing.py` | Frame compositing into a sheet |
| `rastersheet/blender/export.py` | Writes JSON and `.tres` |
| `scripts/dev_link.sh` | Symlinks the package into Blender's extensions directory |
| `tests/` | pytest, core only |
| `tests_blender/run_smoke.py` | Headless Blender smoke suite |

---

### Task 1: Skeleton, manifest, and the core boundary guard

**Files:**
- Create: `pyproject.toml`, `rastersheet/blender_manifest.toml`, `rastersheet/__init__.py`, `rastersheet/core/__init__.py`, `rastersheet/blender/__init__.py`, `rastersheet/blender/registration.py`, `scripts/dev_link.sh`, `tests_blender/run_smoke.py`
- Test: `tests/test_boundary.py`

**Interfaces:**
- Consumes: nothing
- Produces: `rastersheet.blender.registration.CLASSES` (a tuple, empty for now), `register()`, `unregister()`; the extension module name `bl_ext.user_default.rastersheet`

- [ ] **Step 1: Create the dev environment**

```bash
python3 -m venv .venv
.venv/bin/pip install mathutils numpy pytest
.venv/bin/python -c "import mathutils, numpy, pytest; print('deps ok')"
```

Expected: `deps ok`. `mathutils` 5.1.0 has a cp314 wheel and system Python is 3.14.6, matching what Blender 5.2 ships.

- [ ] **Step 2: Write the failing boundary test**

Create `tests/test_boundary.py`:

```python
import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
CORE = REPO / "rastersheet" / "core"
INIT = REPO / "rastersheet" / "__init__.py"


def _imported_names(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node, node.module


def _is_bpy(name):
    return name == "bpy" or name.startswith("bpy.")


def test_core_package_exists():
    assert CORE.is_dir()


def test_core_never_imports_bpy():
    modules = sorted(CORE.glob("*.py"))
    assert modules, "core package has no modules"
    offenders = [
        f"{module.name}: {name}"
        for module in modules
        for _, name in _imported_names(module)
        if _is_bpy(name)
    ]
    assert offenders == []


def test_package_init_has_no_top_level_bpy_import():
    tree = ast.parse(INIT.read_text())
    top_level = [
        name
        for node, name in _imported_names(INIT)
        if _is_bpy(name) and node in tree.body
    ]
    assert top_level == []
```

- [ ] **Step 3: Run it and watch it fail**

```bash
.venv/bin/pytest tests/test_boundary.py -v
```

Expected: FAIL. `test_core_package_exists` fails because `rastersheet/core` does not exist, and the other two error on a missing `rastersheet/__init__.py`.

- [ ] **Step 4: Create `pyproject.toml`**

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

`pythonpath` is what lets `import rastersheet.core.angles` resolve from the repo root without installing anything.

- [ ] **Step 5: Create the package files**

`rastersheet/blender_manifest.toml`:

```toml
schema_version = "1.0.0"
id = "rastersheet"
version = "0.1.0"
name = "RasterSheet"
tagline = "Render a rotating object into a sprite sheet"
maintainer = "Dalton Bailey <daltipolous@gmail.com>"
type = "add-on"
blender_version_min = "4.2.0"
license = ["SPDX:GPL-3.0-or-later"]

[permissions]
files = "Write rendered frames, sprite sheets, and metadata"
```

`rastersheet/__init__.py` — note that both functions import the shell *inside* the body, which is what keeps `bpy` out of module scope:

```python
"""RasterSheet: render a rotating object into a sprite sheet."""


def register():
    from .blender import registration

    registration.register()


def unregister():
    from .blender import registration

    registration.unregister()
```

`rastersheet/core/__init__.py` and `rastersheet/blender/__init__.py` are both empty files.

`rastersheet/blender/registration.py`:

```python
import bpy

CLASSES = ()


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
```

- [ ] **Step 6: Run the boundary test again**

```bash
.venv/bin/pytest tests/test_boundary.py -v
```

Expected: PASS, 3 tests. `test_core_never_imports_bpy` currently passes vacuously only if `core/__init__.py` counts as a module — it does, since `glob("*.py")` matches it.

- [ ] **Step 7: Create the dev link script**

`scripts/dev_link.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BLENDER_VERSION="${BLENDER_VERSION:-5.2}"
TARGET="$HOME/.config/blender/${BLENDER_VERSION}/extensions/user_default"

mkdir -p "$TARGET"
ln -sfn "$REPO/rastersheet" "$TARGET/rastersheet"
echo "linked $TARGET/rastersheet -> $REPO/rastersheet"
```

Then:

```bash
chmod +x scripts/dev_link.sh
./scripts/dev_link.sh
```

- [ ] **Step 8: Create the smoke runner and verify the extension loads**

`tests_blender/run_smoke.py`:

```python
"""Headless Blender smoke tests. Run with: blender -b -P tests_blender/run_smoke.py"""

import sys
import traceback

import bpy

MODULE = "bl_ext.user_default.rastersheet"


def enable_addon():
    bpy.ops.preferences.addon_enable(module=MODULE)


CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


@check
def test_addon_enables():
    assert MODULE in bpy.context.preferences.addons


def main():
    enable_addon()
    for fn in CHECKS:
        fn()
        print(f"  ok  {fn.__name__}")
    print("SMOKE OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("SMOKE FAIL")
        sys.exit(1)
```

Run it, capturing the exit code separately from the output:

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|ok " "$SCRATCH/smoke.log"
```

Expected: `exit=0` and `SMOKE OK`.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml rastersheet scripts tests tests_blender
git commit -m "feat: add extension skeleton and core boundary guard"
```

---

### Task 2: `core.angles`

**Files:**
- Create: `rastersheet/core/angles.py`
- Test: `tests/test_angles.py`

**Interfaces:**
- Consumes: nothing
- Produces: `frame_angles(count: int, start_deg: float, sweep_deg: float, clockwise: bool) -> list[float]`, returning radians

- [ ] **Step 1: Write the failing tests**

`tests/test_angles.py`:

```python
import math

import pytest

from rastersheet.core.angles import frame_angles


def degrees(values):
    return [round(math.degrees(v), 6) for v in values]


def test_full_turn_does_not_duplicate_the_wrap_frame():
    assert degrees(frame_angles(4, 0.0, 360.0, clockwise=False)) == [0.0, 90.0, 180.0, 270.0]


def test_partial_sweep_includes_both_endpoints():
    assert degrees(frame_angles(4, 0.0, 90.0, clockwise=False)) == [0.0, 30.0, 60.0, 90.0]


def test_clockwise_negates_the_progression_but_not_the_start():
    assert degrees(frame_angles(4, 0.0, 360.0, clockwise=True)) == [0.0, -90.0, -180.0, -270.0]


def test_start_angle_offsets_every_frame():
    assert degrees(frame_angles(2, 45.0, 180.0, clockwise=False)) == [45.0, 225.0]


def test_multiple_of_360_counts_as_a_full_turn():
    assert degrees(frame_angles(4, 0.0, 720.0, clockwise=False)) == [0.0, 180.0, 360.0, 540.0]


def test_count_below_two_is_rejected():
    with pytest.raises(ValueError):
        frame_angles(1, 0.0, 360.0, clockwise=False)
```

- [ ] **Step 2: Run and watch it fail**

```bash
.venv/bin/pytest tests/test_angles.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'rastersheet.core.angles'`.

- [ ] **Step 3: Implement**

`rastersheet/core/angles.py`:

```python
"""The angle schedule for a sprite sheet's frames."""

import math


def frame_angles(count, start_deg, sweep_deg, clockwise):
    """Return `count` rotation angles in radians.

    A sweep that is a whole non-zero multiple of 360 degrees is a full turn:
    the step is `sweep / count`, so the last frame stops one step short of
    wrapping onto frame 0 and a looping animation has no duplicate frame.

    Any other sweep is a partial arc: the step is `sweep / (count - 1)`, so
    both endpoints are rendered.
    """
    if count < 2:
        raise ValueError("frame count must be at least 2")

    full_turn = sweep_deg != 0.0 and sweep_deg % 360.0 == 0.0
    step = sweep_deg / count if full_turn else sweep_deg / (count - 1)
    sign = -1.0 if clockwise else 1.0

    return [math.radians(start_deg + sign * step * index) for index in range(count)]
```

- [ ] **Step 4: Run and watch it pass**

```bash
.venv/bin/pytest tests/test_angles.py -v
```

Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add rastersheet/core/angles.py tests/test_angles.py
git commit -m "feat(core): add frame angle schedule"
```

---

### Task 3: `core.paths`

**Files:**
- Create: `rastersheet/core/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: nothing
- Produces: `sanitize_stem(stem: str) -> str`, `frame_filename(stem: str, index: int) -> str`, `OutputPaths` (a frozen dataclass with `frames_dir`, `sheet`, `json`, `tres`, `stem`), `build_output_paths(output_dir: str, stem: str) -> OutputPaths`

- [ ] **Step 1: Write the failing tests**

`tests/test_paths.py`:

```python
from rastersheet.core.paths import build_output_paths, frame_filename, sanitize_stem


def test_frame_filenames_are_one_based_and_zero_padded():
    assert frame_filename("nuke", 0) == "nuke_0001.png"
    assert frame_filename("nuke", 15) == "nuke_0016.png"


def test_sanitize_replaces_unsafe_characters():
    assert sanitize_stem("my sprite/v2") == "my_sprite_v2"


def test_sanitize_trims_leading_and_trailing_separators():
    assert sanitize_stem("  .._spin_..  ") == "spin"


def test_sanitize_falls_back_when_nothing_survives():
    assert sanitize_stem("///") == "sprite"


def test_output_paths_are_derived_from_the_sanitized_stem():
    paths = build_output_paths("/out", "nuke spin")
    assert paths.stem == "nuke_spin"
    assert paths.frames_dir == "/out/nuke_spin_frames"
    assert paths.sheet == "/out/nuke_spin.png"
    assert paths.json == "/out/nuke_spin.json"
    assert paths.tres == "/out/nuke_spin.tres"
```

- [ ] **Step 2: Run and watch it fail**

```bash
.venv/bin/pytest tests/test_paths.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'rastersheet.core.paths'`.

- [ ] **Step 3: Implement**

`rastersheet/core/paths.py`:

```python
"""Output filenames and derived paths.

`output_dir` must already be an absolute filesystem path. Blender-relative
paths such as `//sprite_output/` are resolved by the shell with
`bpy.path.abspath` before reaching this module.
"""

import os
import re
from dataclasses import dataclass

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_stem(stem):
    cleaned = _UNSAFE.sub("_", stem.strip()).strip("._-")
    return cleaned or "sprite"


def frame_filename(stem, index):
    return f"{stem}_{index + 1:04d}.png"


@dataclass(frozen=True)
class OutputPaths:
    stem: str
    frames_dir: str
    sheet: str
    json: str
    tres: str


def build_output_paths(output_dir, stem):
    stem = sanitize_stem(stem)
    return OutputPaths(
        stem=stem,
        frames_dir=os.path.join(output_dir, f"{stem}_frames"),
        sheet=os.path.join(output_dir, f"{stem}.png"),
        json=os.path.join(output_dir, f"{stem}.json"),
        tres=os.path.join(output_dir, f"{stem}.tres"),
    )
```

- [ ] **Step 4: Run and watch it pass**

```bash
.venv/bin/pytest tests/test_paths.py -v
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add rastersheet/core/paths.py tests/test_paths.py
git commit -m "feat(core): add output path derivation"
```

---

### Task 4: `core.rotation`

**Files:**
- Create: `rastersheet/core/rotation.py`
- Test: `tests/test_rotation.py`

**Interfaces:**
- Consumes: nothing
- Produces: `axis_vector(axis: str, base_matrix: Matrix) -> Vector`, `frame_matrix(base_matrix: Matrix, axis_world: Vector, angle: float, pivot: Vector) -> Matrix`

The six accepted axis identifiers are `LOCAL_X`, `LOCAL_Y`, `LOCAL_Z`, `WORLD_X`, `WORLD_Y`, `WORLD_Z`.

- [ ] **Step 1: Write the failing tests**

`tests/test_rotation.py`:

```python
import math

import pytest
from mathutils import Matrix, Vector

from rastersheet.core.rotation import axis_vector, frame_matrix

HALF_TURN_QUARTER = math.radians(90.0)


def approx(vector, expected):
    return all(abs(a - b) < 1e-6 for a, b in zip(vector, expected))


def test_world_axis_ignores_the_object_transform():
    base = Matrix.Rotation(HALF_TURN_QUARTER, 4, Vector((1.0, 0.0, 0.0)))
    assert approx(axis_vector("WORLD_Y", base), (0.0, 1.0, 0.0))


def test_local_axis_follows_the_object_transform():
    # Rotating 90 degrees about X carries local +Y onto world +Z.
    base = Matrix.Rotation(HALF_TURN_QUARTER, 4, Vector((1.0, 0.0, 0.0)))
    assert approx(axis_vector("LOCAL_Y", base), (0.0, 0.0, 1.0))


def test_unknown_axis_is_rejected():
    with pytest.raises(ValueError):
        axis_vector("DIAGONAL_Q", Matrix.Identity(4))


def test_rotation_about_the_object_origin_moves_it_around_the_world_origin():
    base = Matrix.Translation(Vector((5.0, 0.0, 0.0)))
    result = frame_matrix(base, Vector((0.0, 0.0, 1.0)), HALF_TURN_QUARTER, Vector((0.0, 0.0, 0.0)))
    assert approx(result.to_translation(), (0.0, 5.0, 0.0))


def test_rotation_about_its_own_pivot_leaves_the_object_in_place():
    base = Matrix.Translation(Vector((5.0, 0.0, 0.0)))
    pivot = Vector((5.0, 0.0, 0.0))
    result = frame_matrix(base, Vector((0.0, 0.0, 1.0)), HALF_TURN_QUARTER, pivot)
    assert approx(result.to_translation(), (5.0, 0.0, 0.0))


def test_zero_angle_reproduces_the_base_matrix():
    base = Matrix.Translation(Vector((1.0, 2.0, 3.0)))
    result = frame_matrix(base, Vector((0.0, 0.0, 1.0)), 0.0, Vector((0.0, 0.0, 0.0)))
    for row_result, row_base in zip(result, base):
        assert approx(row_result, row_base)
```

- [ ] **Step 2: Run and watch it fail**

```bash
.venv/bin/pytest tests/test_rotation.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'rastersheet.core.rotation'`.

- [ ] **Step 3: Implement**

`rastersheet/core/rotation.py`:

```python
"""Per-frame world transforms.

Frames are produced by composing world matrices rather than by assigning
`rotation_quaternion`. That gives one code path for local and world axes,
makes the pivot a natural parameter, and never touches `rotation_mode`.
"""

from mathutils import Matrix, Vector

_UNIT = {
    "X": Vector((1.0, 0.0, 0.0)),
    "Y": Vector((0.0, 1.0, 0.0)),
    "Z": Vector((0.0, 0.0, 1.0)),
}


def axis_vector(axis, base_matrix):
    """Resolve an axis identifier to a normalized world-space direction."""
    space, _, letter = axis.partition("_")
    if letter not in _UNIT:
        raise ValueError(f"unknown rotation axis {axis!r}")

    unit = _UNIT[letter]
    if space == "WORLD":
        return unit.copy()
    if space != "LOCAL":
        raise ValueError(f"unknown rotation axis {axis!r}")

    world = base_matrix.to_3x3() @ unit
    if world.length == 0.0:
        raise ValueError("object transform collapses the rotation axis")
    return world.normalized()


def frame_matrix(base_matrix, axis_world, angle, pivot):
    """The object's world matrix for one frame."""
    rotation = Matrix.Rotation(angle, 4, axis_world)
    return Matrix.Translation(pivot) @ rotation @ Matrix.Translation(-pivot) @ base_matrix
```

- [ ] **Step 4: Run and watch it pass**

```bash
.venv/bin/pytest tests/test_rotation.py -v
```

Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add rastersheet/core/rotation.py tests/test_rotation.py
git commit -m "feat(core): add per-frame world transform composition"
```

---

### Task 5: Properties and panel

**Files:**
- Create: `rastersheet/blender/properties.py`, `rastersheet/blender/panel.py`
- Modify: `rastersheet/blender/registration.py`
- Modify: `tests_blender/run_smoke.py`

**Interfaces:**
- Consumes: nothing from core
- Produces: `properties.RasterSheetSettings` (PropertyGroup, reachable as `context.scene.rastersheet`), `panel.RASTERSHEET_PT_panel`

The panel does **not** draw the render button yet; the operator is registered in Task 7 and `layout.operator()` on an unregistered identifier raises during draw.

- [ ] **Step 1: Write the failing smoke checks**

Add to `tests_blender/run_smoke.py`, above `def main():`:

```python
@check
def test_settings_are_attached_to_the_scene():
    settings = bpy.context.scene.rastersheet
    assert settings is not None


@check
def test_every_property_round_trips():
    settings = bpy.context.scene.rastersheet
    settings.frame_count = 8
    settings.columns = 3
    settings.rotation_axis = "WORLD_Z"
    settings.camera_mode = "AUTO_ORTHO"
    settings.sheet_mode = "VERTICAL"
    settings.lighting_mode = "FLAT"
    settings.view_transform_mode = "AGX"
    settings.engine_mode = "EEVEE"
    settings.pivot_mode = "BOUNDS_CENTER"
    settings.filename_stem = "probe"
    settings.fps = 24.0
    assert settings.frame_count == 8
    assert settings.rotation_axis == "WORLD_Z"
    assert settings.view_transform_mode == "AGX"
    assert settings.filename_stem == "probe"
    assert abs(settings.fps - 24.0) < 1e-6


@check
def test_panel_is_registered():
    assert hasattr(bpy.types, "RASTERSHEET_PT_panel")


@check
def test_studio_light_enum_is_populated():
    settings = bpy.context.scene.rastersheet
    items = settings.bl_rna.properties["studio_light"].enum_items
    assert len(items) >= 1
```

- [ ] **Step 2: Run and watch it fail**

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|AttributeError" "$SCRATCH/smoke.log"
```

Expected: `exit=1`, `SMOKE FAIL`, and an `AttributeError` on `bpy.context.scene.rastersheet`.

- [ ] **Step 3: Implement the properties**

`rastersheet/blender/properties.py`:

```python
"""The add-on's settings, stored on the scene."""

import os

import bpy

# Blender expects enum item strings to stay alive for as long as the enum is in
# use. Holding them in a module-level cache avoids the classic crash where the
# callback's temporaries are garbage collected mid-draw.
_STUDIO_LIGHT_CACHE = []


def _studio_light_items(self, context):
    _STUDIO_LIGHT_CACHE.clear()
    try:
        directory = bpy.utils.system_resource("DATAFILES", path="studiolights/world")
        names = sorted(n for n in os.listdir(directory) if n.lower().endswith(".exr"))
    except (OSError, TypeError):
        names = []

    if not names:
        _STUDIO_LIGHT_CACHE.append(("NONE", "None Found", "No studio HDRIs in this Blender build"))
        return _STUDIO_LIGHT_CACHE

    for name in names:
        label = os.path.splitext(name)[0].replace("_", " ").title()
        _STUDIO_LIGHT_CACHE.append((name, label, f"Studio HDRI {name}"))
    return _STUDIO_LIGHT_CACHE


class RasterSheetSettings(bpy.types.PropertyGroup):
    rotation_axis: bpy.props.EnumProperty(
        name="Axis",
        items=[
            ("LOCAL_X", "Local X", "Rotate about the object's own X axis"),
            ("LOCAL_Y", "Local Y", "Rotate about the object's own Y axis"),
            ("LOCAL_Z", "Local Z", "Rotate about the object's own Z axis"),
            ("WORLD_X", "World X", "Rotate about the world X axis"),
            ("WORLD_Y", "World Y", "Rotate about the world Y axis"),
            ("WORLD_Z", "World Z", "Rotate about the world Z axis"),
        ],
        default="LOCAL_Y",
    )
    frame_count: bpy.props.IntProperty(name="Frames", default=16, min=2, max=256)
    clockwise: bpy.props.BoolProperty(name="Clockwise", default=True)
    start_angle: bpy.props.FloatProperty(name="Start Angle", default=0.0, subtype="ANGLE")
    sweep_angle: bpy.props.FloatProperty(
        name="Rotation Amount", default=math.radians(360.0), subtype="ANGLE"
    )
    pivot_mode: bpy.props.EnumProperty(
        name="Pivot",
        items=[
            ("ORIGIN", "Object Origin", "Rotate about the object's origin"),
            ("BOUNDS_CENTER", "Bounds Center", "Rotate about the center of the evaluated bounds"),
        ],
        default="ORIGIN",
    )

    camera_mode: bpy.props.EnumProperty(
        name="Camera",
        items=[
            ("CURRENT", "Current Camera", "Use the scene camera, unmodified"),
            ("AUTO_ORTHO", "Auto Orthographic", "Build a temporary orthographic camera"),
        ],
        default="CURRENT",
    )
    azimuth: bpy.props.FloatProperty(name="Azimuth", default=0.0)
    elevation: bpy.props.FloatProperty(name="Elevation", default=30.0)
    camera_margin: bpy.props.FloatProperty(name="Margin", default=1.2, min=1.0)

    engine_mode: bpy.props.EnumProperty(
        name="Renderer",
        items=[
            ("SCENE", "Scene", "Leave the scene's render engine unchanged"),
            ("EEVEE", "Eevee", "Render with Eevee"),
            ("CYCLES", "Cycles", "Render with Cycles"),
        ],
        default="SCENE",
    )
    lighting_mode: bpy.props.EnumProperty(
        name="Lighting",
        items=[
            ("MATERIAL_PREVIEW", "Material Preview", "Light with a bundled studio HDRI"),
            ("SCENE_WORLD", "Scene World", "Leave the scene's world untouched"),
            ("SCENE_LIGHTS", "Scene Lights", "Black world, scene lamps only"),
            ("FLAT", "Flat / Uniform", "Even white ambient light (not unlit shading)"),
            ("CUSTOM_HDRI", "Custom HDRI", "Light with a user-supplied HDRI"),
        ],
        default="MATERIAL_PREVIEW",
    )
    studio_light: bpy.props.EnumProperty(name="Studio HDRI", items=_studio_light_items)
    hdri_path: bpy.props.StringProperty(name="HDRI", subtype="FILE_PATH", default="")
    hdri_strength: bpy.props.FloatProperty(name="Strength", default=1.0, min=0.0)

    # The view_transform enum cannot be introspected -- its enum_items report a
    # single NONE entry because the values come from the OCIO config at
    # runtime. These are a static list, and assignment is guarded.
    view_transform_mode: bpy.props.EnumProperty(
        name="View Transform",
        items=[
            ("STANDARD", "Standard", "Colors match the authored materials"),
            ("SCENE", "Scene", "Leave the scene's view transform unchanged"),
            ("AGX", "AgX", "Blender's default filmic transform"),
            ("FILMIC", "Filmic", "The legacy filmic transform"),
        ],
        default="STANDARD",
    )
    transparent: bpy.props.BoolProperty(name="Transparent BG", default=True)

    resolution_mode: bpy.props.EnumProperty(
        name="Resolution",
        items=[
            ("SCENE", "Scene Resolution", "Use the scene's render resolution"),
            ("CUSTOM", "Custom", "Use the width and height below"),
        ],
        default="SCENE",
    )
    resolution_x: bpy.props.IntProperty(name="Width", default=256, min=1)
    resolution_y: bpy.props.IntProperty(name="Height", default=256, min=1)

    sheet_mode: bpy.props.EnumProperty(
        name="Layout",
        items=[
            ("GRID", "Grid", "Rows and columns"),
            ("HORIZONTAL", "Horizontal Strip", "One row"),
            ("VERTICAL", "Vertical Strip", "One column"),
        ],
        default="GRID",
    )
    columns: bpy.props.IntProperty(name="Columns", default=4, min=1, max=256)

    output_dir: bpy.props.StringProperty(
        name="Output Directory", subtype="DIR_PATH", default="//sprite_output/"
    )
    filename_stem: bpy.props.StringProperty(name="Filename", default="sprite")

    export_frames: bpy.props.BoolProperty(name="Individual Frames", default=True)
    export_sheet: bpy.props.BoolProperty(name="Sprite Sheet", default=True)
    export_json: bpy.props.BoolProperty(name="Metadata JSON", default=True)
    export_godot: bpy.props.BoolProperty(name="Godot .tres", default=False)
    godot_res_prefix: bpy.props.StringProperty(name="Godot Prefix", default="res://")

    animation_name: bpy.props.StringProperty(name="Animation", default="spin")
    fps: bpy.props.FloatProperty(name="FPS", default=12.0, min=0.1)
    loop: bpy.props.BoolProperty(name="Loop", default=True)
```

- [ ] **Step 4: Implement the panel**

`rastersheet/blender/panel.py`:

```python
"""The View3D sidebar panel."""

import math

import bpy


class RASTERSHEET_PT_panel(bpy.types.Panel):
    bl_label = "RasterSheet"
    bl_idname = "RASTERSHEET_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RasterSheet"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.rastersheet

        target = layout.box()
        target.label(text="Target")
        obj = context.active_object
        target.label(text=obj.name if obj else "No active object")

        rotation = layout.box()
        rotation.label(text="Rotation")
        rotation.prop(settings, "rotation_axis")
        rotation.prop(settings, "pivot_mode")
        rotation.prop(settings, "frame_count")
        rotation.prop(settings, "clockwise")
        rotation.prop(settings, "start_angle")
        rotation.prop(settings, "sweep_angle")

        camera = layout.box()
        camera.label(text="Camera")
        camera.prop(settings, "camera_mode")
        if settings.camera_mode == "AUTO_ORTHO":
            camera.prop(settings, "azimuth")
            camera.prop(settings, "elevation")
            camera.prop(settings, "camera_margin")

        rendering = layout.box()
        rendering.label(text="Rendering")
        rendering.prop(settings, "engine_mode")
        rendering.prop(settings, "lighting_mode")
        if settings.lighting_mode == "MATERIAL_PREVIEW":
            rendering.prop(settings, "studio_light")
        elif settings.lighting_mode == "CUSTOM_HDRI":
            rendering.prop(settings, "hdri_path")
            rendering.prop(settings, "hdri_strength")
        rendering.prop(settings, "view_transform_mode")
        rendering.prop(settings, "transparent")
        rendering.prop(settings, "resolution_mode")
        if settings.resolution_mode == "CUSTOM":
            rendering.prop(settings, "resolution_x")
            rendering.prop(settings, "resolution_y")

        sheet = layout.box()
        sheet.label(text="Sprite Sheet")
        sheet.prop(settings, "sheet_mode")
        if settings.sheet_mode == "GRID":
            sheet.prop(settings, "columns")
            columns = min(settings.columns, settings.frame_count)
            sheet.label(text=f"Rows: {math.ceil(settings.frame_count / columns)}")

        output = layout.box()
        output.label(text="Output")
        output.prop(settings, "output_dir")
        output.prop(settings, "filename_stem")
        output.prop(settings, "animation_name")
        output.prop(settings, "fps")
        output.prop(settings, "loop")

        export = layout.box()
        export.label(text="Export")
        export.prop(settings, "export_frames")
        export.prop(settings, "export_sheet")
        export.prop(settings, "export_json")
        export.prop(settings, "export_godot")
        if settings.export_godot:
            export.prop(settings, "godot_res_prefix")
```

- [ ] **Step 5: Wire registration**

Replace `rastersheet/blender/registration.py` entirely:

```python
import bpy

from . import panel, properties

CLASSES = (
    properties.RasterSheetSettings,
    panel.RASTERSHEET_PT_panel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.rastersheet = bpy.props.PointerProperty(
        type=properties.RasterSheetSettings
    )


def unregister():
    del bpy.types.Scene.rastersheet
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
```

- [ ] **Step 6: Run the smoke suite and watch it pass**

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|ok " "$SCRATCH/smoke.log"
```

Expected: `exit=0`, `SMOKE OK`, five `ok` lines.

- [ ] **Step 7: Commit**

```bash
git add rastersheet/blender tests_blender/run_smoke.py
git commit -m "feat: add settings property group and sidebar panel"
```

---

### Task 6: Scene snapshot and restore

**Files:**
- Create: `rastersheet/blender/snapshot.py`
- Modify: `tests_blender/run_smoke.py`

**Interfaces:**
- Consumes: nothing
- Produces: `guard(stack, owner, attr)`, `guard_matrix(stack, obj)`, `track_datablock(stack, collection, datablock)`, and the context manager `scene_snapshot(scene, objects)` yielding an `ExitStack`

Restore order is LIFO and does not need to be reasoned about for the camera case: removing a temporary camera object sets `scene.camera` to `None`, and assigning the original camera back afterwards works either way.

- [ ] **Step 1: Write the failing smoke checks**

Add to `tests_blender/run_smoke.py`:

```python
@check
def test_snapshot_restores_scalars_and_matrices():
    from bl_ext.user_default.rastersheet.blender import snapshot

    scene = bpy.context.scene
    obj = _fresh_cube()
    before_engine = scene.render.engine
    before_res = scene.render.resolution_x
    before_matrix = obj.matrix_world.copy()

    with snapshot.scene_snapshot(scene, [obj]) as stack:
        snapshot.guard(stack, scene.render, "resolution_x")
        scene.render.resolution_x = 999
        obj.matrix_world = obj.matrix_world @ mathutils.Matrix.Translation((10.0, 0.0, 0.0))
        assert scene.render.resolution_x == 999

    assert scene.render.engine == before_engine
    assert scene.render.resolution_x == before_res
    assert (obj.matrix_world.to_translation() - before_matrix.to_translation()).length < 1e-6


@check
def test_snapshot_restores_after_a_failure():
    from bl_ext.user_default.rastersheet.blender import snapshot

    scene = bpy.context.scene
    obj = _fresh_cube()
    before = scene.render.resolution_x

    try:
        with snapshot.scene_snapshot(scene, [obj]) as stack:
            snapshot.guard(stack, scene.render, "resolution_x")
            scene.render.resolution_x = 777
            raise RuntimeError("deliberate failure")
    except RuntimeError:
        pass

    assert scene.render.resolution_x == before


@check
def test_snapshot_removes_tracked_datablocks():
    from bl_ext.user_default.rastersheet.blender import snapshot

    scene = bpy.context.scene
    before = len(bpy.data.worlds)

    with snapshot.scene_snapshot(scene, []) as stack:
        world = bpy.data.worlds.new("rastersheet_temp")
        snapshot.track_datablock(stack, bpy.data.worlds, world)
        scene.world = world
        assert len(bpy.data.worlds) == before + 1

    assert len(bpy.data.worlds) == before
```

Add these imports and helper at the top of `run_smoke.py`, after `import bpy`:

```python
import mathutils


def _fresh_cube(name="RasterSheetProbe"):
    existing = bpy.data.objects.get(name)
    if existing:
        bpy.data.objects.remove(existing, do_unlink=True)
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    import bmesh

    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj
```

- [ ] **Step 2: Run and watch it fail**

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|ImportError|ModuleNotFound" "$SCRATCH/smoke.log"
```

Expected: `exit=1`, `SMOKE FAIL`, `ModuleNotFoundError` for `snapshot`.

- [ ] **Step 3: Implement**

`rastersheet/blender/snapshot.py`:

```python
"""Capture and restore scene state.

Every mutation registers its own restore callback at the moment it is applied,
rather than being collected into one dictionary up front. If setup fails
partway through, only what was actually changed is unwound, in reverse order.
"""

import contextlib


def guard(stack, owner, attr):
    """Register the current value of `owner.attr` for restoration."""
    original = getattr(owner, attr)
    stack.callback(setattr, owner, attr, original)


def _set_matrix(obj, matrix):
    obj.matrix_world = matrix


def guard_matrix(stack, obj):
    stack.callback(_set_matrix, obj, obj.matrix_world.copy())


def _remove(collection, datablock):
    try:
        collection.remove(datablock)
    except (ReferenceError, RuntimeError):
        pass


def track_datablock(stack, collection, datablock):
    """Remove a temporary datablock when the snapshot unwinds."""
    stack.callback(_remove, collection, datablock)


RENDER_ATTRS = (
    "engine",
    "resolution_x",
    "resolution_y",
    "resolution_percentage",
    "film_transparent",
    "filepath",
)

# ExitStack unwinds LIFO, so the governing attribute is registered LAST in
# order to be restored FIRST. Restoring color_depth while file_format is still
# the temporary value raises TypeError -- the valid depths depend on the
# format. Same relationship between look and view_transform.
IMAGE_SETTINGS_ATTRS = ("color_mode", "color_depth", "file_format")

VIEW_SETTINGS_ATTRS = ("exposure", "look", "view_transform")


@contextlib.contextmanager
def scene_snapshot(scene, objects):
    """Guard everything the add-on is allowed to touch, then yield the stack."""
    with contextlib.ExitStack() as stack:
        for attr in RENDER_ATTRS:
            guard(stack, scene.render, attr)
        for attr in IMAGE_SETTINGS_ATTRS:
            guard(stack, scene.render.image_settings, attr)
        for attr in VIEW_SETTINGS_ATTRS:
            guard(stack, scene.view_settings, attr)
        guard(stack, scene, "camera")
        guard(stack, scene, "world")
        for obj in objects:
            guard_matrix(stack, obj)
        yield stack
```

- [ ] **Step 4: Run and watch it pass**

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|ok " "$SCRATCH/smoke.log"
```

Expected: `exit=0`, `SMOKE OK`, eight `ok` lines.

- [ ] **Step 5: Commit**

```bash
git add rastersheet/blender/snapshot.py tests_blender/run_smoke.py
git commit -m "feat: add ExitStack-based scene snapshot and restore"
```

---

### Task 7: The operator, pre-flight checks, and the frame loop

This completes spec phase 1: individual frames render with the current camera and the scene comes back untouched.

**Files:**
- Create: `rastersheet/blender/camera.py`, `rastersheet/blender/render.py`, `rastersheet/blender/operator.py`
- Modify: `rastersheet/blender/registration.py`, `rastersheet/blender/panel.py`, `tests_blender/run_smoke.py`

**Interfaces:**
- Consumes: `core.angles.frame_angles`, `core.rotation.axis_vector`, `core.rotation.frame_matrix`, `core.paths.build_output_paths`, `core.paths.frame_filename`, `blender.snapshot.*`
- Produces: `camera.resolve_camera(context, settings, stack, obj) -> bpy.types.Object`, `render.frame_jobs(context, scene, obj, frame_matrices, frames_dir, stem) -> generator[int]`, `operator.RASTERSHEET_OT_render`, `operator.validate(context, settings) -> list[str]`, `operator.bounds_center(obj, depsgraph) -> Vector`, `operator.local_corners(obj, depsgraph) -> list[Vector]`

- [ ] **Step 1: Write the failing smoke checks**

Add to `tests_blender/run_smoke.py`:

```python
@check
def test_render_writes_individual_frames_and_restores_the_scene():
    import os
    import shutil

    scene = bpy.context.scene
    obj = _fresh_cube()
    bpy.context.view_layer.objects.active = obj

    camera_data = bpy.data.cameras.new("ProbeCam")
    camera = bpy.data.objects.new("ProbeCam", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0.0, -5.0, 0.0)
    camera.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = camera

    out = os.path.join(SCRATCH, "frames_run")
    shutil.rmtree(out, ignore_errors=True)

    settings = scene.rastersheet
    settings.frame_count = 4
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 32
    settings.resolution_y = 32
    settings.output_dir = out
    settings.filename_stem = "probe"
    settings.export_frames = True
    settings.export_sheet = False
    settings.export_json = False
    settings.export_godot = False
    settings.camera_mode = "CURRENT"

    before_matrix = obj.matrix_world.copy()
    before_engine = scene.render.engine
    before_filepath = scene.render.filepath
    before_transform = scene.view_settings.view_transform

    result = bpy.ops.rastersheet.render()
    assert result == {"FINISHED"}, result

    frames = sorted(os.listdir(os.path.join(out, "probe_frames")))
    assert frames == ["probe_0001.png", "probe_0002.png", "probe_0003.png", "probe_0004.png"], frames

    assert (obj.matrix_world.to_translation() - before_matrix.to_translation()).length < 1e-6
    assert scene.render.engine == before_engine
    assert scene.render.filepath == before_filepath
    assert scene.view_settings.view_transform == before_transform


@check
def test_render_rejects_a_missing_camera_without_touching_the_scene():
    scene = bpy.context.scene
    obj = _fresh_cube()
    bpy.context.view_layer.objects.active = obj
    previous_camera = scene.camera
    scene.camera = None
    before_filepath = scene.render.filepath

    scene.rastersheet.camera_mode = "CURRENT"
    result = bpy.ops.rastersheet.render()

    assert result == {"CANCELLED"}, result
    assert scene.render.filepath == before_filepath
    scene.camera = previous_camera
```

Add near the top of `run_smoke.py`, after the other imports:

```python
import math
import os

SCRATCH = os.environ.get(
    "RASTERSHEET_SCRATCH",
    "/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad",
)
```

- [ ] **Step 2: Run and watch it fail**

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|AttributeError" "$SCRATCH/smoke.log"
```

Expected: `exit=1`, `SMOKE FAIL`, `AttributeError` on `bpy.ops.rastersheet`.

- [ ] **Step 3: Implement the camera resolver**

`rastersheet/blender/camera.py`. Only the `CURRENT` branch exists in this task; Task 11 adds `AUTO_ORTHO`.

```python
"""Camera selection and construction."""


def resolve_camera(context, settings, stack, obj):
    """Return the camera to render through.

    In CURRENT mode the scene camera is used untouched. Validation has already
    guaranteed it exists.
    """
    if settings.camera_mode == "CURRENT":
        return context.scene.camera
    raise NotImplementedError(f"camera mode {settings.camera_mode!r} is not implemented yet")
```

- [ ] **Step 4: Implement the frame loop**

`rastersheet/blender/render.py`:

```python
"""The per-frame render loop.

This is a generator that yields once per completed frame. V1 drives it to
completion synchronously, but writing it this way means a modal timer operator
can drive the same code later without a rewrite.
"""

import os

import bpy

from ..core.paths import frame_filename


def frame_jobs(context, scene, obj, frame_matrices, frames_dir, stem):
    for index, matrix in enumerate(frame_matrices):
        obj.matrix_world = matrix
        context.view_layer.update()
        scene.render.filepath = os.path.join(frames_dir, frame_filename(stem, index))
        bpy.ops.render.render(write_still=True)
        yield index
```

- [ ] **Step 5: Implement the operator**

`rastersheet/blender/operator.py`:

```python
"""The render operator: validation, orchestration, restoration."""

import math
import os

import bpy
from mathutils import Vector

from ..core.angles import frame_angles
from ..core.paths import build_output_paths
from ..core.rotation import axis_vector, frame_matrix
from . import camera as camera_module
from . import render as render_module
from . import snapshot

MAX_SHEET_SIDE = 16384


def local_corners(obj, depsgraph):
    """The eight bounding-box corners in the evaluated object's local space."""
    evaluated = obj.evaluated_get(depsgraph)
    return [Vector(corner) for corner in evaluated.bound_box]


def bounds_center(obj, depsgraph):
    corners = local_corners(obj, depsgraph)
    local_center = sum(corners, Vector((0.0, 0.0, 0.0))) / len(corners)
    return obj.matrix_world @ local_center


def resolution_for(scene, settings):
    if settings.resolution_mode == "CUSTOM":
        return settings.resolution_x, settings.resolution_y
    percent = scene.render.resolution_percentage / 100.0
    return (
        max(1, int(scene.render.resolution_x * percent)),
        max(1, int(scene.render.resolution_y * percent)),
    )


def validate(context, settings):
    """Return a list of blocking problems. An empty list means go."""
    problems = []
    scene = context.scene
    obj = context.active_object

    if obj is None:
        problems.append("No active object")
    elif not hasattr(obj.data, "vertices") and obj.type not in {"MESH", "CURVE", "SURFACE", "META", "FONT"}:
        problems.append(f"Active object {obj.name!r} has no renderable geometry")

    if settings.camera_mode == "CURRENT" and scene.camera is None:
        problems.append("Camera mode is Current Camera but the scene has no camera")

    if settings.frame_count < 2:
        problems.append("Frame count must be at least 2")

    if scene.render.pixel_aspect_x != 1.0 or scene.render.pixel_aspect_y != 1.0:
        problems.append("Non-square pixel aspect ratios are not supported")

    if settings.engine_mode != "SCENE":
        available = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
        wanted = {"EEVEE": {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}, "CYCLES": {"CYCLES"}}[settings.engine_mode]
        if not (available & wanted):
            problems.append(f"{settings.engine_mode.title()} is not available in this Blender build")

    if settings.lighting_mode == "CUSTOM_HDRI":
        path = bpy.path.abspath(settings.hdri_path)
        if not path or not os.path.isfile(path):
            problems.append("Custom HDRI mode needs a readable image path")

    width, height = resolution_for(scene, settings)
    columns = settings.frame_count if settings.sheet_mode == "HORIZONTAL" else (
        1 if settings.sheet_mode == "VERTICAL" else min(settings.columns, settings.frame_count)
    )
    rows = math.ceil(settings.frame_count / columns)
    if columns * width > MAX_SHEET_SIDE or rows * height > MAX_SHEET_SIDE:
        problems.append(
            f"Sheet would be {columns * width}x{rows * height}, over Blender's {MAX_SHEET_SIDE}px limit"
        )

    output_dir = bpy.path.abspath(settings.output_dir)
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as exc:
        problems.append(f"Cannot create output directory: {exc}")
    else:
        if not os.access(output_dir, os.W_OK):
            problems.append(f"Output directory is not writable: {output_dir}")

    return problems


def warnings_for(context):
    obj = context.active_object
    if obj is not None and (obj.constraints or (obj.animation_data and obj.animation_data.drivers)):
        return [
            f"{obj.name!r} has constraints or drivers; its world matrix is recomputed "
            "during evaluation, so the rotation will not apply"
        ]
    return []


class RASTERSHEET_OT_render(bpy.types.Operator):
    bl_idname = "rastersheet.render"
    bl_label = "Render Sprite Sheet"
    bl_description = "Rotate the active object and render each angle to a sprite sheet"

    def execute(self, context):
        settings = context.scene.rastersheet

        problems = validate(context, settings)
        if problems:
            self.report({"ERROR"}, "; ".join(problems))
            return {"CANCELLED"}

        for warning in warnings_for(context):
            self.report({"WARNING"}, warning)

        try:
            self.run(context, settings)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, scene already restored
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report({"INFO"}, "Sprite sheet generated")
        return {"FINISHED"}

    def run(self, context, settings):
        scene = context.scene
        obj = context.active_object
        window_manager = context.window_manager

        output_dir = bpy.path.abspath(settings.output_dir)
        paths = build_output_paths(output_dir, settings.filename_stem)
        frames_dir = paths.frames_dir
        os.makedirs(frames_dir, exist_ok=True)

        with snapshot.scene_snapshot(scene, [obj]) as stack:
            depsgraph = context.evaluated_depsgraph_get()
            base_matrix = obj.matrix_world.copy()
            pivot = (
                bounds_center(obj, depsgraph)
                if settings.pivot_mode == "BOUNDS_CENTER"
                else base_matrix.to_translation()
            )
            axis = axis_vector(settings.rotation_axis, base_matrix)
            angles = frame_angles(
                settings.frame_count,
                math.degrees(settings.start_angle),
                math.degrees(settings.sweep_angle),
                settings.clockwise,
            )
            frame_matrices = [frame_matrix(base_matrix, axis, angle, pivot) for angle in angles]

            width, height = resolution_for(scene, settings)
            scene.render.resolution_x = width
            scene.render.resolution_y = height
            scene.render.resolution_percentage = 100
            scene.render.film_transparent = settings.transparent
            scene.render.image_settings.file_format = "PNG"
            scene.render.image_settings.color_mode = "RGBA" if settings.transparent else "RGB"
            scene.render.image_settings.color_depth = "8"

            scene.camera = camera_module.resolve_camera(context, settings, stack, obj)

            window_manager.progress_begin(0, settings.frame_count)
            try:
                jobs = render_module.frame_jobs(
                    context, scene, obj, frame_matrices, frames_dir, paths.stem
                )
                for index in jobs:
                    window_manager.progress_update(index + 1)
            finally:
                window_manager.progress_end()

        return paths
```

- [ ] **Step 6: Register the operator and add the button**

In `rastersheet/blender/registration.py`, change the import line and `CLASSES`:

```python
from . import operator, panel, properties

CLASSES = (
    properties.RasterSheetSettings,
    operator.RASTERSHEET_OT_render,
    panel.RASTERSHEET_PT_panel,
)
```

At the end of `RASTERSHEET_PT_panel.draw`, after the export box:

```python
        layout.separator()
        layout.operator("rastersheet.render", icon="RENDER_RESULT")
```

- [ ] **Step 7: Run the smoke suite and watch it pass**

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|ok " "$SCRATCH/smoke.log"
```

Expected: `exit=0`, `SMOKE OK`, ten `ok` lines.

- [ ] **Step 8: Verify by hand in the Blender UI**

Open Blender, add a cube, position the default camera to see it, open the RasterSheet sidebar panel, set Frames to 8 and an output directory, and press Render Sprite Sheet. Confirm eight PNGs appear, the cube is back where it started, and the render settings in the Output properties tab are unchanged. Green tests are not sufficient evidence that this task is done.

- [ ] **Step 9: Commit**

```bash
git add rastersheet/blender tests_blender/run_smoke.py
git commit -m "feat: render individual frames with full scene restoration"
```

---

### Task 8: `core.layout`

**Files:**
- Create: `rastersheet/core/layout.py`
- Test: `tests/test_layout.py`

**Interfaces:**
- Consumes: nothing
- Produces: `Cell` (frozen dataclass: `x`, `y`, `width`, `height`), `SheetLayout` (frozen dataclass: `rows`, `columns`, `frame_width`, `frame_height`, `mode`, `cells`, plus `sheet_width` and `sheet_height` properties), `sheet_layout(frame_count, columns, mode, frame_width, frame_height) -> SheetLayout`

Cell coordinates are **top-left origin**. `mode` is one of `GRID`, `HORIZONTAL`, `VERTICAL`.

- [ ] **Step 1: Write the failing tests**

`tests/test_layout.py`:

```python
import pytest

from rastersheet.core.layout import sheet_layout


def test_grid_derives_rows_and_sheet_size():
    layout = sheet_layout(16, 4, "GRID", 256, 128)
    assert (layout.rows, layout.columns) == (4, 4)
    assert (layout.sheet_width, layout.sheet_height) == (1024, 512)


def test_grid_cells_are_row_major_from_the_top_left():
    layout = sheet_layout(4, 2, "GRID", 10, 20)
    assert [(c.x, c.y) for c in layout.cells] == [(0, 0), (10, 0), (0, 20), (10, 20)]


def test_ragged_last_row_still_places_every_frame():
    layout = sheet_layout(5, 3, "GRID", 10, 10)
    assert layout.rows == 2
    assert len(layout.cells) == 5
    assert (layout.cells[4].x, layout.cells[4].y) == (0, 10)


def test_horizontal_strip_is_one_row():
    layout = sheet_layout(16, 4, "HORIZONTAL", 8, 8)
    assert (layout.rows, layout.columns) == (1, 16)
    assert (layout.sheet_width, layout.sheet_height) == (128, 8)


def test_vertical_strip_is_one_column():
    layout = sheet_layout(16, 4, "VERTICAL", 8, 8)
    assert (layout.rows, layout.columns) == (16, 1)
    assert (layout.sheet_width, layout.sheet_height) == (8, 128)


def test_columns_are_clamped_to_the_frame_count():
    layout = sheet_layout(3, 10, "GRID", 8, 8)
    assert (layout.rows, layout.columns) == (1, 3)


def test_cells_tile_without_overlap():
    layout = sheet_layout(6, 3, "GRID", 4, 4)
    seen = set()
    for cell in layout.cells:
        for x in range(cell.x, cell.x + cell.width):
            for y in range(cell.y, cell.y + cell.height):
                assert (x, y) not in seen
                seen.add((x, y))
    assert len(seen) == 6 * 4 * 4


def test_mode_is_recorded_on_the_layout():
    assert sheet_layout(4, 2, "GRID", 8, 8).mode == "GRID"


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        sheet_layout(4, 2, "SPIRAL", 8, 8)


def test_frame_count_below_two_is_rejected():
    with pytest.raises(ValueError):
        sheet_layout(1, 1, "GRID", 8, 8)
```

- [ ] **Step 2: Run and watch it fail**

```bash
.venv/bin/pytest tests/test_layout.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'rastersheet.core.layout'`.

- [ ] **Step 3: Implement**

`rastersheet/core/layout.py`:

```python
"""Sprite sheet geometry.

Cell rectangles use a top-left origin, which is what every consumer of the
metadata expects. Blender's bottom-up pixel buffer is the shell's problem.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Cell:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class SheetLayout:
    rows: int
    columns: int
    frame_width: int
    frame_height: int
    mode: str
    cells: tuple

    @property
    def sheet_width(self):
        return self.columns * self.frame_width

    @property
    def sheet_height(self):
        return self.rows * self.frame_height


def sheet_layout(frame_count, columns, mode, frame_width, frame_height):
    if frame_count < 2:
        raise ValueError("frame count must be at least 2")
    if frame_width < 1 or frame_height < 1:
        raise ValueError("frame dimensions must be positive")

    if mode == "HORIZONTAL":
        columns = frame_count
    elif mode == "VERTICAL":
        columns = 1
    elif mode == "GRID":
        if columns < 1:
            raise ValueError("columns must be at least 1")
        columns = min(columns, frame_count)
    else:
        raise ValueError(f"unknown sheet mode {mode!r}")

    rows = math.ceil(frame_count / columns)
    cells = tuple(
        Cell(
            x=(index % columns) * frame_width,
            y=(index // columns) * frame_height,
            width=frame_width,
            height=frame_height,
        )
        for index in range(frame_count)
    )
    return SheetLayout(rows, columns, frame_width, frame_height, mode, cells)
```

- [ ] **Step 4: Run and watch it pass**

```bash
.venv/bin/pytest tests/test_layout.py -v
```

Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add rastersheet/core/layout.py tests/test_layout.py
git commit -m "feat(core): add sprite sheet geometry"
```

---

### Task 9: Sheet packing

This completes spec phase 2.

**Files:**
- Create: `rastersheet/blender/packing.py`
- Modify: `rastersheet/blender/operator.py`
- Modify: `tests_blender/run_smoke.py`

**Interfaces:**
- Consumes: `core.layout.sheet_layout`, `core.paths.OutputPaths`
- Produces: `packing.pack_sheet(frame_paths: list[str], layout: SheetLayout, sheet_path: str) -> None`

- [ ] **Step 1: Write the failing smoke check**

Add to `tests_blender/run_smoke.py`:

```python
@check
def test_sheet_packing_is_pixel_identical_to_its_frames():
    import numpy as np
    import shutil

    scene = bpy.context.scene
    obj = _fresh_cube()
    bpy.context.view_layer.objects.active = obj
    _ensure_probe_camera(scene)

    out = os.path.join(SCRATCH, "sheet_run")
    shutil.rmtree(out, ignore_errors=True)

    settings = scene.rastersheet
    settings.frame_count = 2
    settings.columns = 2
    settings.sheet_mode = "GRID"
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 32
    settings.resolution_y = 32
    settings.output_dir = out
    settings.filename_stem = "sheet"
    settings.export_frames = True
    settings.export_sheet = True
    settings.export_json = False
    settings.export_godot = False
    settings.camera_mode = "CURRENT"

    assert bpy.ops.rastersheet.render() == {"FINISHED"}

    sheet_path = os.path.join(out, "sheet.png")
    frame_path = os.path.join(out, "sheet_frames", "sheet_0001.png")
    assert os.path.isfile(sheet_path)

    sheet = bpy.data.images.load(sheet_path)
    frame = bpy.data.images.load(frame_path)
    try:
        assert tuple(sheet.size) == (64, 32), tuple(sheet.size)
        assert sheet.colorspace_settings.name == frame.colorspace_settings.name

        sheet_pixels = np.empty(64 * 32 * 4, dtype=np.float32)
        sheet.pixels.foreach_get(sheet_pixels)
        sheet_pixels = sheet_pixels.reshape(32, 64, 4)

        frame_pixels = np.empty(32 * 32 * 4, dtype=np.float32)
        frame.pixels.foreach_get(frame_pixels)
        frame_pixels = frame_pixels.reshape(32, 32, 4)

        # Frame 0 occupies the top-left cell, which is the top of the
        # bottom-up buffer.
        region = sheet_pixels[0:32, 0:32]
        assert np.allclose(region, frame_pixels, atol=1e-6), np.abs(region - frame_pixels).max()
    finally:
        bpy.data.images.remove(sheet)
        bpy.data.images.remove(frame)


@check
def test_sheet_only_export_leaves_no_frames_directory():
    import shutil

    scene = bpy.context.scene
    obj = _fresh_cube()
    bpy.context.view_layer.objects.active = obj
    _ensure_probe_camera(scene)

    out = os.path.join(SCRATCH, "sheet_only_run")
    shutil.rmtree(out, ignore_errors=True)

    settings = scene.rastersheet
    settings.frame_count = 2
    settings.columns = 2
    settings.output_dir = out
    settings.filename_stem = "only"
    settings.export_frames = False
    settings.export_sheet = True

    assert bpy.ops.rastersheet.render() == {"FINISHED"}
    assert os.path.isfile(os.path.join(out, "only.png"))
    assert not os.path.exists(os.path.join(out, "only_frames"))
```

Extract the camera setup from Task 7's test into a shared helper near `_fresh_cube`:

```python
def _ensure_probe_camera(scene):
    camera = bpy.data.objects.get("ProbeCam")
    if camera is None:
        camera_data = bpy.data.cameras.new("ProbeCam")
        camera = bpy.data.objects.new("ProbeCam", camera_data)
        scene.collection.objects.link(camera)
    camera.location = (0.0, -5.0, 0.0)
    camera.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = camera
    return camera
```

and use it in `test_render_writes_individual_frames_and_restores_the_scene` in place of the inline camera creation.

- [ ] **Step 2: Run and watch it fail**

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|Error" "$SCRATCH/smoke.log"
```

Expected: `exit=1`, `SMOKE FAIL`, no `sheet.png` produced.

- [ ] **Step 3: Implement the packer**

`rastersheet/blender/packing.py`:

```python
"""Composite rendered frames into a single sheet image.

Two details decide whether this is correct. First, Blender applies a colorspace
transform when decoding an image and its inverse when encoding, so the sheet
must carry the same colorspace and alpha mode as the frames or every sprite is
silently double-transformed. Second, Blender's pixel buffer is bottom-up while
`core.layout` emits top-left-origin rectangles, so the single flip lives here.
"""

import bpy
import numpy as np


def _read_pixels(image):
    width, height = image.size
    buffer = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(buffer)
    return buffer.reshape(height, width, 4)


def pack_sheet(frame_paths, layout, sheet_path):
    if len(frame_paths) != len(layout.cells):
        raise ValueError(
            f"{len(frame_paths)} frames do not fit {len(layout.cells)} layout cells"
        )

    sheet_buffer = np.zeros((layout.sheet_height, layout.sheet_width, 4), dtype=np.float32)
    colorspace = None
    alpha_mode = None
    loaded = []

    try:
        for cell, path in zip(layout.cells, frame_paths):
            image = bpy.data.images.load(path)
            loaded.append(image)

            if colorspace is None:
                colorspace = image.colorspace_settings.name
                alpha_mode = image.alpha_mode

            width, height = image.size
            if (width, height) != (cell.width, cell.height):
                raise ValueError(
                    f"frame {path} is {width}x{height}, expected {cell.width}x{cell.height}"
                )

            bottom = layout.sheet_height - cell.y - cell.height
            sheet_buffer[bottom : bottom + cell.height, cell.x : cell.x + cell.width] = _read_pixels(
                image
            )

        sheet = bpy.data.images.new(
            "rastersheet_output",
            width=layout.sheet_width,
            height=layout.sheet_height,
            alpha=True,
            float_buffer=False,
        )
        loaded.append(sheet)
        sheet.colorspace_settings.name = colorspace
        sheet.alpha_mode = alpha_mode
        sheet.pixels.foreach_set(sheet_buffer.reshape(-1))
        sheet.file_format = "PNG"
        sheet.filepath_raw = sheet_path
        sheet.save()
    finally:
        for image in loaded:
            bpy.data.images.remove(image)
```

- [ ] **Step 4: Wire packing into the operator**

In `rastersheet/blender/operator.py`, add to the imports:

```python
import shutil
import tempfile

from ..core.layout import sheet_layout
from ..core.paths import build_output_paths, frame_filename
from . import packing as packing_module
```

(the existing `from ..core.paths import build_output_paths` line is replaced by the two-name version above).

Replace this block in `run`:

```python
        output_dir = bpy.path.abspath(settings.output_dir)
        paths = build_output_paths(output_dir, settings.filename_stem)
        frames_dir = paths.frames_dir
        os.makedirs(frames_dir, exist_ok=True)
```

with:

```python
        output_dir = bpy.path.abspath(settings.output_dir)
        paths = build_output_paths(output_dir, settings.filename_stem)

        temp_frames_dir = None
        if settings.export_frames:
            frames_dir = paths.frames_dir
            os.makedirs(frames_dir, exist_ok=True)
        else:
            temp_frames_dir = tempfile.mkdtemp(prefix="rastersheet_")
            frames_dir = temp_frames_dir
```

Then replace everything in `run` from the `with snapshot.scene_snapshot(...)` line to the end of the method with the block below. The resolution lookup is hoisted above the `with` statement so `width` and `height` are still in scope for the packing call, and the whole thing is wrapped in a `try` / `finally` that removes the temporary frames directory.

```python
        width, height = resolution_for(scene, settings)

        try:
            with snapshot.scene_snapshot(scene, [obj]) as stack:
                depsgraph = context.evaluated_depsgraph_get()
                base_matrix = obj.matrix_world.copy()
                pivot = (
                    bounds_center(obj, depsgraph)
                    if settings.pivot_mode == "BOUNDS_CENTER"
                    else base_matrix.to_translation()
                )
                axis = axis_vector(settings.rotation_axis, base_matrix)
                angles = frame_angles(
                    settings.frame_count,
                    math.degrees(settings.start_angle),
                    math.degrees(settings.sweep_angle),
                    settings.clockwise,
                )
                frame_matrices = [
                    frame_matrix(base_matrix, axis, angle, pivot) for angle in angles
                ]

                scene.render.resolution_x = width
                scene.render.resolution_y = height
                scene.render.resolution_percentage = 100
                scene.render.film_transparent = settings.transparent
                scene.render.image_settings.file_format = "PNG"
                scene.render.image_settings.color_mode = "RGBA" if settings.transparent else "RGB"
                scene.render.image_settings.color_depth = "8"

                scene.camera = camera_module.resolve_camera(context, settings, stack, obj)

                window_manager.progress_begin(0, settings.frame_count)
                try:
                    jobs = render_module.frame_jobs(
                        context, scene, obj, frame_matrices, frames_dir, paths.stem
                    )
                    for index in jobs:
                        window_manager.progress_update(index + 1)
                finally:
                    window_manager.progress_end()

            if settings.export_sheet:
                layout = sheet_layout(
                    settings.frame_count,
                    settings.columns,
                    settings.sheet_mode,
                    width,
                    height,
                )
                frame_paths = [
                    os.path.join(frames_dir, frame_filename(paths.stem, index))
                    for index in range(settings.frame_count)
                ]
                packing_module.pack_sheet(frame_paths, layout, paths.sheet)
        finally:
            if temp_frames_dir is not None:
                shutil.rmtree(temp_frames_dir, ignore_errors=True)

        return paths
```

- [ ] **Step 5: Run and watch it pass**

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|ok " "$SCRATCH/smoke.log"
```

Expected: `exit=0`, `SMOKE OK`, twelve `ok` lines.

- [ ] **Step 6: Verify by hand**

In Blender, render a 16-frame sheet of a recognizable object at 4 columns and open the resulting PNG. Confirm the frames read left to right, top to bottom, and that the colors match the viewport rather than looking washed out.

- [ ] **Step 7: Commit**

```bash
git add rastersheet/blender tests_blender/run_smoke.py
git commit -m "feat: pack rendered frames into a sprite sheet"
```

---

### Task 10: `core.framing`

**Files:**
- Create: `rastersheet/core/framing.py`
- Test: `tests/test_framing.py`

**Interfaces:**
- Consumes: nothing
- Produces: `required_ortho_scale(corners, camera_matrix, frame_matrices, aspect, margin) -> float`

`corners` are in the object's **local** space (what `Object.bound_box` returns). Each entry of `frame_matrices` is a full world matrix, so `matrix @ corner` places the corner in world space for that frame. Passing world-space corners would apply the base transform twice.

The temporary camera sets `sensor_fit = "HORIZONTAL"`, so the return value is the horizontal extent of the view in world units.

- [ ] **Step 1: Write the failing tests**

`tests/test_framing.py`:

```python
import math

import pytest
from mathutils import Matrix, Vector

from rastersheet.core.framing import required_ortho_scale

# A camera 5 units up +Z, looking down -Z with +Y up.
CAMERA = Matrix.Translation(Vector((0.0, 0.0, 5.0)))
UNIT_CUBE = [
    Vector((x, y, z)) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)
]


def test_axis_aligned_unit_cube_needs_a_scale_of_one():
    scale = required_ortho_scale(UNIT_CUBE, CAMERA, [Matrix.Identity(4)], 1.0, 1.0)
    assert abs(scale - 1.0) < 1e-6


def test_forty_five_degrees_needs_the_diagonal():
    rotated = Matrix.Rotation(math.radians(45.0), 4, Vector((0.0, 0.0, 1.0)))
    scale = required_ortho_scale(UNIT_CUBE, CAMERA, [rotated], 1.0, 1.0)
    assert abs(scale - math.sqrt(2.0)) < 1e-6


def test_the_maximum_across_frames_wins_not_the_last_one():
    rotated = Matrix.Rotation(math.radians(45.0), 4, Vector((0.0, 0.0, 1.0)))
    scale = required_ortho_scale(UNIT_CUBE, CAMERA, [rotated, Matrix.Identity(4)], 1.0, 1.0)
    assert abs(scale - math.sqrt(2.0)) < 1e-6


def test_a_wide_aspect_widens_the_required_horizontal_extent():
    scale = required_ortho_scale(UNIT_CUBE, CAMERA, [Matrix.Identity(4)], 2.0, 1.0)
    assert abs(scale - 2.0) < 1e-6


def test_margin_scales_the_result():
    scale = required_ortho_scale(UNIT_CUBE, CAMERA, [Matrix.Identity(4)], 1.0, 1.2)
    assert abs(scale - 1.2) < 1e-6


def test_object_offset_from_the_camera_axis_still_fits():
    offset = Matrix.Translation(Vector((3.0, 0.0, 0.0)))
    scale = required_ortho_scale(UNIT_CUBE, CAMERA, [offset], 1.0, 1.0)
    assert abs(scale - 1.0) < 1e-6


def test_invalid_aspect_is_rejected():
    with pytest.raises(ValueError):
        required_ortho_scale(UNIT_CUBE, CAMERA, [Matrix.Identity(4)], 0.0, 1.0)


def test_no_frames_is_rejected():
    with pytest.raises(ValueError):
        required_ortho_scale(UNIT_CUBE, CAMERA, [], 1.0, 1.0)
```

Note `test_object_offset_from_the_camera_axis_still_fits`: the function measures the object's own extent, not its distance from the view center. The camera is later placed on the bounds center, so an offset object is centered by the camera, not by a larger scale.

- [ ] **Step 2: Run and watch it fail**

```bash
.venv/bin/pytest tests/test_framing.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'rastersheet.core.framing'`.

- [ ] **Step 3: Implement**

`rastersheet/core/framing.py`:

```python
"""Orthographic framing.

One scale is computed for the whole sheet, as the maximum requirement across
every frame. A per-frame scale would make the sprite visibly pump in size as
the object rotates.
"""


def required_ortho_scale(corners, camera_matrix, frame_matrices, aspect, margin):
    """The horizontal ortho_scale that contains the object at every angle."""
    if aspect <= 0.0:
        raise ValueError("aspect must be positive")
    if not frame_matrices:
        raise ValueError("at least one frame matrix is required")
    if not corners:
        raise ValueError("at least one bound corner is required")

    view = camera_matrix.inverted()
    needed = 0.0

    for matrix in frame_matrices:
        points = [view @ (matrix @ corner) for corner in corners]
        width = max(p.x for p in points) - min(p.x for p in points)
        height = max(p.y for p in points) - min(p.y for p in points)
        needed = max(needed, width, height * aspect)

    return needed * margin
```

- [ ] **Step 4: Run and watch it pass**

```bash
.venv/bin/pytest tests/test_framing.py -v
```

Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add rastersheet/core/framing.py tests/test_framing.py
git commit -m "feat(core): add orthographic framing calculation"
```

---

### Task 11: Auto orthographic camera

This completes spec phase 3.

**Files:**
- Modify: `rastersheet/blender/camera.py` (full replacement)
- Create: `rastersheet/blender/view_ops.py`
- Modify: `rastersheet/blender/operator.py`, `rastersheet/blender/registration.py`, `rastersheet/blender/panel.py`, `tests_blender/run_smoke.py`

**Interfaces:**
- Consumes: `core.framing.required_ortho_scale`, `blender.snapshot.track_datablock`
- Produces: `camera.direction_from(azimuth_deg, elevation_deg) -> Vector`, `camera.angles_from_direction(direction) -> (azimuth_deg, elevation_deg)`, `camera.resolve_camera(context, settings, stack, obj, corners, frame_matrices, aspect) -> bpy.types.Object`, `view_ops.RASTERSHEET_OT_copy_view`

Note the widened `resolve_camera` signature; the operator's call site changes with it.

- [ ] **Step 1: Write the failing smoke checks**

Add to `tests_blender/run_smoke.py`:

```python
@check
def test_direction_and_angles_round_trip():
    from bl_ext.user_default.rastersheet.blender import camera as camera_module

    for azimuth, elevation in [(0.0, 0.0), (90.0, 0.0), (0.0, 30.0), (215.0, -45.0)]:
        direction = camera_module.direction_from(azimuth, elevation)
        back_az, back_el = camera_module.angles_from_direction(direction)
        assert abs(((back_az - azimuth + 180.0) % 360.0) - 180.0) < 1e-4, (azimuth, back_az)
        assert abs(back_el - elevation) < 1e-4, (elevation, back_el)


@check
def test_front_view_is_down_the_negative_y_axis():
    from bl_ext.user_default.rastersheet.blender import camera as camera_module

    direction = camera_module.direction_from(0.0, 0.0)
    assert abs(direction.x) < 1e-6
    assert abs(direction.y + 1.0) < 1e-6
    assert abs(direction.z) < 1e-6


@check
def test_auto_ortho_keeps_the_object_off_the_border_at_every_angle():
    import numpy as np
    import shutil

    scene = bpy.context.scene
    obj = _fresh_cube()
    # Move the object well away from the world origin: auto framing must not
    # depend on the object sitting at (0, 0, 0).
    obj.matrix_world = mathutils.Matrix.Translation((7.0, -3.0, 2.0))
    bpy.context.view_layer.objects.active = obj

    out = os.path.join(SCRATCH, "ortho_run")
    shutil.rmtree(out, ignore_errors=True)

    settings = scene.rastersheet
    settings.camera_mode = "AUTO_ORTHO"
    settings.azimuth = 0.0
    settings.elevation = 30.0
    settings.camera_margin = 1.2
    settings.pivot_mode = "BOUNDS_CENTER"
    settings.frame_count = 4
    settings.columns = 2
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 64
    settings.resolution_y = 64
    settings.output_dir = out
    settings.filename_stem = "ortho"
    settings.export_frames = True
    settings.export_sheet = False
    settings.transparent = True

    before_camera = scene.camera
    before_cameras = len(bpy.data.cameras)

    assert bpy.ops.rastersheet.render() == {"FINISHED"}

    assert scene.camera == before_camera
    assert len(bpy.data.cameras) == before_cameras

    for index in range(1, 5):
        path = os.path.join(out, "ortho_frames", f"ortho_{index:04d}.png")
        image = bpy.data.images.load(path)
        try:
            pixels = np.empty(64 * 64 * 4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            alpha = pixels.reshape(64, 64, 4)[:, :, 3]
            assert alpha.max() > 0.5, f"frame {index} is empty"
            border = np.concatenate([alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]])
            assert border.max() < 0.01, f"frame {index} touches the border"
        finally:
            bpy.data.images.remove(image)
```

- [ ] **Step 2: Run and watch it fail**

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|NotImplementedError|AttributeError" "$SCRATCH/smoke.log"
```

Expected: `exit=1`, `SMOKE FAIL`, `AttributeError` on `direction_from`.

- [ ] **Step 3: Replace `rastersheet/blender/camera.py`**

```python
"""Camera selection and temporary orthographic camera construction.

The view direction is explicit azimuth and elevation rather than an inferred
"desired view". With both at zero the camera sits on the world -Y axis looking
toward +Y, which is Blender's front view.
"""

import math

import bpy
from mathutils import Vector

from ..core.framing import required_ortho_scale
from . import snapshot


def direction_from(azimuth_deg, elevation_deg):
    """The unit vector from the subject toward the camera."""
    azimuth = math.radians(azimuth_deg)
    elevation = math.radians(elevation_deg)
    return Vector(
        (
            math.sin(azimuth) * math.cos(elevation),
            -math.cos(azimuth) * math.cos(elevation),
            math.sin(elevation),
        )
    ).normalized()


def angles_from_direction(direction):
    """Inverse of `direction_from`, in degrees."""
    direction = direction.normalized()
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, direction.z))))
    azimuth = math.degrees(math.atan2(direction.x, -direction.y))
    return azimuth % 360.0, elevation


def _world_points(corners, frame_matrices):
    return [matrix @ corner for matrix in frame_matrices for corner in corners]


def _build_ortho_camera(context, settings, stack, corners, frame_matrices, aspect):
    scene = context.scene

    points = _world_points(corners, frame_matrices)
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    center = (low + high) * 0.5
    radius = max((p - center).length for p in points) or 1.0

    direction = direction_from(settings.azimuth, settings.elevation)
    distance = radius * 4.0

    data = bpy.data.cameras.new("RasterSheet Temp Camera")
    snapshot.track_datablock(stack, bpy.data.cameras, data)
    data.type = "ORTHO"
    data.sensor_fit = "HORIZONTAL"

    camera = bpy.data.objects.new("RasterSheet Temp Camera", data)
    snapshot.track_datablock(stack, bpy.data.objects, camera)
    scene.collection.objects.link(camera)

    # Build the transform as a local matrix and assign it whole. Mutating
    # camera.matrix_world in place relies on write-back behavior that is easy to
    # get wrong; a local Matrix has no such ambiguity.
    matrix = direction.to_track_quat("Z", "Y").to_matrix().to_4x4()
    matrix.translation = center + direction * distance

    # Aiming at the world-space bounds center does not guarantee the object is
    # centered in camera space, so measure the residual offset and slide the
    # camera sideways by exactly that much. Without this, a margin barely over
    # 1.0 can clip one edge.
    view = matrix.inverted()
    local = [view @ point for point in points]
    offset_x = (max(p.x for p in local) + min(p.x for p in local)) * 0.5
    offset_y = (max(p.y for p in local) + min(p.y for p in local)) * 0.5
    matrix.translation = matrix.translation + (
        matrix.to_3x3() @ Vector((offset_x, offset_y, 0.0))
    )
    camera.matrix_world = matrix

    view = matrix.inverted()
    local = [view @ point for point in points]
    near = -max(p.z for p in local)
    far = -min(p.z for p in local)
    data.clip_start = max(near - 0.001, 1e-4)
    data.clip_end = far + 0.001

    data.ortho_scale = required_ortho_scale(
        corners, matrix, frame_matrices, aspect, settings.camera_margin
    )
    return camera


def resolve_camera(context, settings, stack, obj, corners, frame_matrices, aspect):
    """Return the camera to render through."""
    if settings.camera_mode == "CURRENT":
        return context.scene.camera
    if settings.camera_mode == "AUTO_ORTHO":
        return _build_ortho_camera(context, settings, stack, corners, frame_matrices, aspect)
    raise ValueError(f"unknown camera mode {settings.camera_mode!r}")
```

- [ ] **Step 4: Create the Copy From Viewport operator**

`rastersheet/blender/view_ops.py`:

```python
"""Small helper operators for the panel."""

import bpy
from mathutils import Vector

from .camera import angles_from_direction


class RASTERSHEET_OT_copy_view(bpy.types.Operator):
    bl_idname = "rastersheet.copy_view"
    bl_label = "Copy From Viewport"
    bl_description = "Set azimuth and elevation from the current 3D view direction"

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == "VIEW_3D"

    def execute(self, context):
        region_3d = context.space_data.region_3d
        # The view rotation maps camera local +Z onto the direction from the
        # subject toward the viewer, which is the same convention as
        # direction_from().
        direction = region_3d.view_rotation @ Vector((0.0, 0.0, 1.0))
        azimuth, elevation = angles_from_direction(direction)

        settings = context.scene.rastersheet
        settings.azimuth = azimuth
        settings.elevation = elevation
        self.report({"INFO"}, f"Azimuth {azimuth:.1f}, elevation {elevation:.1f}")
        return {"FINISHED"}
```

- [ ] **Step 5: Register it and add the button**

In `registration.py`, import `view_ops` and add `view_ops.RASTERSHEET_OT_copy_view` to `CLASSES` after the render operator.

In `panel.py`, inside the `if settings.camera_mode == "AUTO_ORTHO":` block, after `camera.prop(settings, "camera_margin")`:

```python
            camera.operator("rastersheet.copy_view", icon="VIEW3D")
```

- [ ] **Step 6: Update the operator's call site**

In `operator.py`, replace:

```python
            scene.camera = camera_module.resolve_camera(context, settings, stack, obj)
```

with:

```python
            corners = local_corners(obj, depsgraph)
            scene.camera = camera_module.resolve_camera(
                context, settings, stack, obj, corners, frame_matrices, width / height
            )
```

The `width, height = resolution_for(scene, settings)` assignment must already be above this line — it was hoisted in Task 9.

- [ ] **Step 7: Run and watch it pass**

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|ok " "$SCRATCH/smoke.log"
```

Expected: `exit=0`, `SMOKE OK`, fifteen `ok` lines.

- [ ] **Step 8: Verify by hand**

In Blender, orbit the viewport to a three-quarter view of an object that is *not* at the world origin, press Copy From Viewport, and render. Confirm the sprite is centered and fully inside every frame, and that no camera is left in the outliner afterwards.

- [ ] **Step 9: Commit**

```bash
git add rastersheet/blender tests_blender/run_smoke.py
git commit -m "feat: add auto orthographic camera with explicit view angles"
```

---

### Task 12: Lighting, renderer, and view transform

This completes spec phase 4.

**Files:**
- Create: `rastersheet/blender/lighting.py`
- Modify: `rastersheet/blender/operator.py`, `tests_blender/run_smoke.py`

**Interfaces:**
- Consumes: `blender.snapshot.track_datablock`
- Produces: `lighting.apply_lighting(context, settings, stack) -> None`, `operator.resolve_engine(scene, mode) -> str`, `operator.VIEW_TRANSFORMS`

- [ ] **Step 1: Write the failing smoke checks**

Add to `tests_blender/run_smoke.py`:

```python
@check
def test_lighting_modes_all_render_and_restore_the_world():
    import shutil

    scene = bpy.context.scene
    obj = _fresh_cube()
    obj.matrix_world = mathutils.Matrix.Identity(4)
    bpy.context.view_layer.objects.active = obj
    _ensure_probe_camera(scene)

    settings = scene.rastersheet
    settings.camera_mode = "CURRENT"
    settings.frame_count = 2
    settings.columns = 2
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 16
    settings.resolution_y = 16
    settings.export_frames = True
    settings.export_sheet = False

    before_world = scene.world
    before_worlds = len(bpy.data.worlds)

    for mode in ["MATERIAL_PREVIEW", "SCENE_WORLD", "SCENE_LIGHTS", "FLAT"]:
        out = os.path.join(SCRATCH, f"light_{mode.lower()}")
        shutil.rmtree(out, ignore_errors=True)
        settings.lighting_mode = mode
        settings.output_dir = out
        settings.filename_stem = "light"
        assert bpy.ops.rastersheet.render() == {"FINISHED"}, mode
        assert os.path.isfile(os.path.join(out, "light_frames", "light_0001.png")), mode
        assert scene.world == before_world, mode
        assert len(bpy.data.worlds) == before_worlds, mode


@check
def test_view_transform_override_is_applied_and_restored():
    import shutil

    scene = bpy.context.scene
    obj = _fresh_cube()
    bpy.context.view_layer.objects.active = obj
    _ensure_probe_camera(scene)

    scene.view_settings.view_transform = "AgX"
    settings = scene.rastersheet
    settings.lighting_mode = "FLAT"
    settings.view_transform_mode = "STANDARD"
    settings.camera_mode = "CURRENT"
    settings.frame_count = 2
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 16
    settings.resolution_y = 16
    out = os.path.join(SCRATCH, "vt_run")
    shutil.rmtree(out, ignore_errors=True)
    settings.output_dir = out
    settings.filename_stem = "vt"
    settings.export_frames = True
    settings.export_sheet = False

    assert bpy.ops.rastersheet.render() == {"FINISHED"}
    assert scene.view_settings.view_transform == "AgX"


@check
def test_engine_override_resolves_and_restores():
    import shutil

    from bl_ext.user_default.rastersheet.blender import operator as operator_module

    scene = bpy.context.scene
    obj = _fresh_cube()
    bpy.context.view_layer.objects.active = obj
    _ensure_probe_camera(scene)

    resolved = operator_module.resolve_engine(scene, "EEVEE")
    assert resolved in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}, resolved

    before_engine = scene.render.engine
    settings = scene.rastersheet
    settings.engine_mode = "EEVEE"
    settings.lighting_mode = "FLAT"
    settings.camera_mode = "CURRENT"
    settings.frame_count = 2
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 16
    settings.resolution_y = 16
    out = os.path.join(SCRATCH, "engine_run")
    shutil.rmtree(out, ignore_errors=True)
    settings.output_dir = out
    settings.filename_stem = "engine"
    settings.export_frames = True
    settings.export_sheet = False

    assert bpy.ops.rastersheet.render() == {"FINISHED"}
    assert scene.render.engine == before_engine
    settings.engine_mode = "SCENE"
```

- [ ] **Step 2: Run and watch it fail**

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|AttributeError" "$SCRATCH/smoke.log"
```

Expected: `exit=1`, `SMOKE FAIL`, `AttributeError` on `resolve_engine`.

- [ ] **Step 3: Implement lighting**

`rastersheet/blender/lighting.py`:

```python
"""Temporary world construction.

Every mode except SCENE_WORLD builds a fresh world datablock and assigns it to
the scene. The user's own world node tree is never edited.
"""

import os

import bpy

from . import snapshot

BLACK = (0.0, 0.0, 0.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)


def _temp_world(stack):
    world = bpy.data.worlds.new("RasterSheet Temp World")
    snapshot.track_datablock(stack, bpy.data.worlds, world)
    world.use_nodes = True
    return world


def _studio_light_path(settings):
    if settings.studio_light in {"", "NONE"}:
        return None
    try:
        directory = bpy.utils.system_resource("DATAFILES", path="studiolights/world")
    except TypeError:
        return None
    path = os.path.join(directory, settings.studio_light)
    return path if os.path.isfile(path) else None


def _attach_environment(world, stack, image_path, strength):
    image = bpy.data.images.load(image_path, check_existing=False)
    snapshot.track_datablock(stack, bpy.data.images, image)

    tree = world.node_tree
    background = tree.nodes["Background"]
    environment = tree.nodes.new("ShaderNodeTexEnvironment")
    environment.image = image
    tree.links.new(environment.outputs["Color"], background.inputs["Color"])
    background.inputs["Strength"].default_value = strength


def apply_lighting(context, settings, stack):
    scene = context.scene
    mode = settings.lighting_mode

    if mode == "SCENE_WORLD":
        return

    world = _temp_world(stack)
    background = world.node_tree.nodes["Background"]
    background.inputs["Strength"].default_value = 1.0

    if mode == "SCENE_LIGHTS":
        background.inputs["Color"].default_value = BLACK
    elif mode == "FLAT":
        background.inputs["Color"].default_value = WHITE
    elif mode == "MATERIAL_PREVIEW":
        path = _studio_light_path(settings)
        if path is None:
            background.inputs["Color"].default_value = WHITE
        else:
            _attach_environment(world, stack, path, 1.0)
    elif mode == "CUSTOM_HDRI":
        _attach_environment(
            world, stack, bpy.path.abspath(settings.hdri_path), settings.hdri_strength
        )
    else:
        raise ValueError(f"unknown lighting mode {mode!r}")

    scene.world = world
```

- [ ] **Step 4: Wire the engine, view transform, and lighting into the operator**

Add to `operator.py`'s imports:

```python
from . import lighting as lighting_module
```

Add these module-level constants next to `MAX_SHEET_SIDE`:

```python
ENGINE_IDS = {
    "EEVEE": ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"),
    "CYCLES": ("CYCLES",),
}

VIEW_TRANSFORMS = {
    "STANDARD": "Standard",
    "AGX": "AgX",
    "FILMIC": "Filmic",
}


def resolve_engine(scene, mode):
    """Map the add-on's engine choice onto this build's enum identifier.

    Eevee's identifier changed between 4.2 (BLENDER_EEVEE_NEXT) and 4.5
    (BLENDER_EEVEE), and Cycles ships as an add-on that can be disabled, so
    both are resolved against the live enum rather than hardcoded.
    """
    available = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
    for candidate in ENGINE_IDS[mode]:
        if candidate in available:
            return candidate
    raise RuntimeError(f"{mode.title()} is not available in this Blender build")
```

Then simplify `validate`'s engine check to reuse it, replacing the `wanted = {...}` block with:

```python
    if settings.engine_mode != "SCENE":
        try:
            resolve_engine(scene, settings.engine_mode)
        except RuntimeError as exc:
            problems.append(str(exc))
```

In `run`, immediately after the `scene.render.image_settings.color_depth = "8"` line, add:

```python
            if settings.engine_mode != "SCENE":
                scene.render.engine = resolve_engine(scene, settings.engine_mode)

            if settings.view_transform_mode != "SCENE":
                name = VIEW_TRANSFORMS[settings.view_transform_mode]
                try:
                    scene.view_settings.view_transform = name
                except TypeError:
                    self.report(
                        {"WARNING"},
                        f"View transform {name!r} is unavailable; keeping the scene's",
                    )

            lighting_module.apply_lighting(context, settings, stack)
```

- [ ] **Step 5: Run and watch it pass**

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|ok " "$SCRATCH/smoke.log"
```

Expected: `exit=0`, `SMOKE OK`, eighteen `ok` lines.

- [ ] **Step 6: Verify by hand**

Render the same object twice, once with View Transform set to Standard and once to AgX, and compare. The Standard sheet should match the material colors; the AgX one should look muted. Confirm the scene's own view transform is unchanged in the Render properties tab afterwards.

- [ ] **Step 7: Commit**

```bash
git add rastersheet/blender tests_blender/run_smoke.py
git commit -m "feat: add lighting modes, engine override, and view transform control"
```

---

### Task 13: `core.metadata`

**Files:**
- Create: `rastersheet/core/metadata.py`
- Test: `tests/test_metadata.py`

**Interfaces:**
- Consumes: `core.layout.SheetLayout`
- Produces: `build_metadata(image_name, layout, animation_name, fps, loop, axis, start_deg, sweep_deg, clockwise) -> dict`

- [ ] **Step 1: Write the failing test**

`tests/test_metadata.py`:

```python
from rastersheet.core.layout import sheet_layout
from rastersheet.core.metadata import build_metadata


def test_metadata_matches_the_documented_shape():
    layout = sheet_layout(16, 4, "GRID", 256, 128)
    document = build_metadata(
        image_name="nuke_spin.png",
        layout=layout,
        animation_name="spin",
        fps=12.0,
        loop=True,
        axis="LOCAL_Y",
        start_deg=0.0,
        sweep_deg=360.0,
        clockwise=True,
    )
    assert document == {
        "image": "nuke_spin.png",
        "frame_count": 16,
        "columns": 4,
        "rows": 4,
        "frame_width": 256,
        "frame_height": 128,
        "sheet_width": 1024,
        "sheet_height": 512,
        "layout": "GRID",
        "fps": 12.0,
        "loop": True,
        "animation": "spin",
        "rotation": {
            "axis": "LOCAL_Y",
            "start_angle": 0.0,
            "sweep_angle": 360.0,
            "clockwise": True,
        },
    }


def test_strip_layout_is_reported():
    layout = sheet_layout(4, 4, "HORIZONTAL", 8, 8)
    document = build_metadata(
        image_name="strip.png",
        layout=layout,
        animation_name="walk",
        fps=8.0,
        loop=False,
        axis="WORLD_Z",
        start_deg=45.0,
        sweep_deg=90.0,
        clockwise=False,
    )
    assert document["layout"] == "HORIZONTAL"
    assert document["rows"] == 1
    assert document["columns"] == 4
    assert document["loop"] is False
    assert document["rotation"]["clockwise"] is False
```

- [ ] **Step 2: Run and watch it fail**

```bash
.venv/bin/pytest tests/test_metadata.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'rastersheet.core.metadata'`.

- [ ] **Step 3: Implement**

`rastersheet/core/metadata.py`:

```python
"""The engine-agnostic JSON sidecar."""


def build_metadata(
    image_name,
    layout,
    animation_name,
    fps,
    loop,
    axis,
    start_deg,
    sweep_deg,
    clockwise,
):
    return {
        "image": image_name,
        "frame_count": len(layout.cells),
        "columns": layout.columns,
        "rows": layout.rows,
        "frame_width": layout.frame_width,
        "frame_height": layout.frame_height,
        "sheet_width": layout.sheet_width,
        "sheet_height": layout.sheet_height,
        "layout": layout.mode,
        "fps": fps,
        "loop": loop,
        "animation": animation_name,
        "rotation": {
            "axis": axis,
            "start_angle": start_deg,
            "sweep_angle": sweep_deg,
            "clockwise": clockwise,
        },
    }
```

- [ ] **Step 4: Run and watch it pass**

```bash
.venv/bin/pytest tests/test_metadata.py -v
```

Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add rastersheet/core/metadata.py tests/test_metadata.py
git commit -m "feat(core): add JSON metadata document"
```

---

### Task 14: `core.godot`

**Files:**
- Create: `rastersheet/core/godot.py`
- Test: `tests/test_godot.py`

**Interfaces:**
- Consumes: `core.layout.SheetLayout`
- Produces: `sprite_frames_tres(image_res_path, layout, animation_name, fps, loop) -> str`

- [ ] **Step 1: Write the failing golden test**

`tests/test_godot.py`:

```python
from rastersheet.core.layout import sheet_layout
from rastersheet.core.godot import sprite_frames_tres

EXPECTED_TWO_FRAMES = '''[gd_resource type="SpriteFrames" load_steps=4 format=3]

[ext_resource type="Texture2D" path="res://probe.png" id="1_tex"]

[sub_resource type="AtlasTexture" id="AtlasTexture_0"]
atlas = ExtResource("1_tex")
region = Rect2(0, 0, 32, 32)

[sub_resource type="AtlasTexture" id="AtlasTexture_1"]
atlas = ExtResource("1_tex")
region = Rect2(32, 0, 32, 32)

[resource]
animations = [{
"frames": [{"duration": 1.0, "texture": SubResource("AtlasTexture_0")}, {"duration": 1.0, "texture": SubResource("AtlasTexture_1")}],
"loop": true,
"name": &"spin",
"speed": 12.0
}]
'''


def test_two_frame_resource_matches_the_golden_text():
    layout = sheet_layout(2, 2, "GRID", 32, 32)
    text = sprite_frames_tres("res://probe.png", layout, "spin", 12.0, True)
    assert text == EXPECTED_TWO_FRAMES


def test_load_steps_is_frame_count_plus_two():
    layout = sheet_layout(16, 4, "GRID", 8, 8)
    text = sprite_frames_tres("res://a.png", layout, "spin", 12.0, True)
    assert "load_steps=18" in text


def test_loop_false_is_written_lowercase():
    layout = sheet_layout(2, 2, "GRID", 8, 8)
    text = sprite_frames_tres("res://a.png", layout, "spin", 12.0, False)
    assert '"loop": false,' in text


def test_regions_follow_the_layout_cells():
    layout = sheet_layout(4, 2, "GRID", 10, 20)
    text = sprite_frames_tres("res://a.png", layout, "spin", 12.0, True)
    assert "region = Rect2(0, 0, 10, 20)" in text
    assert "region = Rect2(10, 0, 10, 20)" in text
    assert "region = Rect2(0, 20, 10, 20)" in text
    assert "region = Rect2(10, 20, 10, 20)" in text
```

- [ ] **Step 2: Run and watch it fail**

```bash
.venv/bin/pytest tests/test_godot.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'rastersheet.core.godot'`.

- [ ] **Step 3: Implement**

`rastersheet/core/godot.py`:

```python
"""Godot SpriteFrames resource text.

One AtlasTexture sub-resource per frame, all pointing at the same sheet.
"""

TEXTURE_ID = "1_tex"


def sprite_frames_tres(image_res_path, layout, animation_name, fps, loop):
    count = len(layout.cells)
    lines = [
        f'[gd_resource type="SpriteFrames" load_steps={count + 2} format=3]',
        "",
        f'[ext_resource type="Texture2D" path="{image_res_path}" id="{TEXTURE_ID}"]',
        "",
    ]

    for index, cell in enumerate(layout.cells):
        lines.extend(
            [
                f'[sub_resource type="AtlasTexture" id="AtlasTexture_{index}"]',
                f'atlas = ExtResource("{TEXTURE_ID}")',
                f"region = Rect2({cell.x}, {cell.y}, {cell.width}, {cell.height})",
                "",
            ]
        )

    frames = ", ".join(
        f'{{"duration": 1.0, "texture": SubResource("AtlasTexture_{index}")}}'
        for index in range(count)
    )
    lines.extend(
        [
            "[resource]",
            "animations = [{",
            f'"frames": [{frames}],',
            f'"loop": {"true" if loop else "false"},',
            f'"name": &"{animation_name}",',
            f'"speed": {fps}',
            "}]",
            "",
        ]
    )
    return "\n".join(lines)
```

- [ ] **Step 4: Run and watch it pass**

```bash
.venv/bin/pytest tests/test_godot.py -v
```

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add rastersheet/core/godot.py tests/test_godot.py
git commit -m "feat(core): add Godot SpriteFrames resource generation"
```

---

### Task 15: Exporters, README, and the full V1 run

This completes spec phase 5 and V1.

**Files:**
- Create: `rastersheet/blender/export.py`, `README.md`
- Modify: `rastersheet/blender/operator.py`, `tests_blender/run_smoke.py`

**Interfaces:**
- Consumes: `core.metadata.build_metadata`, `core.godot.sprite_frames_tres`
- Produces: `export.write_metadata(path, document) -> None`, `export.write_tres(path, text) -> None`

- [ ] **Step 1: Write the failing smoke check**

Add to `tests_blender/run_smoke.py`:

```python
@check
def test_full_export_writes_sheet_json_and_tres():
    import json
    import shutil

    scene = bpy.context.scene
    obj = _fresh_cube()
    obj.matrix_world = mathutils.Matrix.Identity(4)
    bpy.context.view_layer.objects.active = obj
    _ensure_probe_camera(scene)

    out = os.path.join(SCRATCH, "full_run")
    shutil.rmtree(out, ignore_errors=True)

    settings = scene.rastersheet
    settings.camera_mode = "CURRENT"
    settings.lighting_mode = "FLAT"
    settings.rotation_axis = "LOCAL_Z"
    settings.frame_count = 4
    settings.columns = 2
    settings.sheet_mode = "GRID"
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 32
    settings.resolution_y = 32
    settings.output_dir = out
    settings.filename_stem = "full"
    settings.animation_name = "spin"
    settings.fps = 12.0
    settings.loop = True
    settings.export_frames = True
    settings.export_sheet = True
    settings.export_json = True
    settings.export_godot = True
    settings.godot_res_prefix = "res://sprites/"

    assert bpy.ops.rastersheet.render() == {"FINISHED"}

    with open(os.path.join(out, "full.json"), encoding="utf-8") as handle:
        document = json.load(handle)
    assert document["image"] == "full.png"
    assert document["frame_count"] == 4
    assert (document["columns"], document["rows"]) == (2, 2)
    assert (document["sheet_width"], document["sheet_height"]) == (64, 64)
    assert document["rotation"]["axis"] == "LOCAL_Z"

    with open(os.path.join(out, "full.tres"), encoding="utf-8") as handle:
        tres = handle.read()
    assert 'path="res://sprites/full.png"' in tres
    assert "load_steps=6" in tres
    assert tres.count("AtlasTexture_") == 8  # one declaration and one reference each


@check
def test_godot_export_requires_a_sheet():
    scene = bpy.context.scene
    obj = _fresh_cube()
    bpy.context.view_layer.objects.active = obj
    _ensure_probe_camera(scene)

    settings = scene.rastersheet
    settings.export_sheet = False
    settings.export_godot = True
    result = bpy.ops.rastersheet.render()
    assert result == {"CANCELLED"}, result
    settings.export_godot = False
    settings.export_sheet = True
```

- [ ] **Step 2: Run and watch it fail**

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|FileNotFoundError" "$SCRATCH/smoke.log"
```

Expected: `exit=1`, `SMOKE FAIL`, `FileNotFoundError` for `full.json`.

- [ ] **Step 3: Implement the writers**

`rastersheet/blender/export.py`:

```python
"""Metadata file writing."""

import json


def write_metadata(path, document):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2)
        handle.write("\n")


def write_tres(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
```

- [ ] **Step 4: Add the export validation rule**

In `operator.py`'s `validate`, after the frame count check:

```python
    if settings.export_godot and not settings.export_sheet:
        problems.append("Godot export needs the sprite sheet enabled")
```

- [ ] **Step 5: Wire the exporters into the operator**

Add to `operator.py`'s imports:

```python
from ..core.godot import sprite_frames_tres
from ..core.metadata import build_metadata
from . import export as export_module
```

Replace the packing block in `run`:

```python
            if settings.export_sheet:
                layout = sheet_layout(
                    settings.frame_count,
                    settings.columns,
                    settings.sheet_mode,
                    width,
                    height,
                )
                frame_paths = [
                    os.path.join(frames_dir, frame_filename(paths.stem, index))
                    for index in range(settings.frame_count)
                ]
                packing_module.pack_sheet(frame_paths, layout, paths.sheet)
```

with:

```python
            layout = sheet_layout(
                settings.frame_count,
                settings.columns,
                settings.sheet_mode,
                width,
                height,
            )

            if settings.export_sheet:
                frame_paths = [
                    os.path.join(frames_dir, frame_filename(paths.stem, index))
                    for index in range(settings.frame_count)
                ]
                packing_module.pack_sheet(frame_paths, layout, paths.sheet)

            image_name = os.path.basename(paths.sheet)

            if settings.export_json:
                document = build_metadata(
                    image_name=image_name,
                    layout=layout,
                    animation_name=settings.animation_name,
                    fps=settings.fps,
                    loop=settings.loop,
                    axis=settings.rotation_axis,
                    start_deg=math.degrees(settings.start_angle),
                    sweep_deg=math.degrees(settings.sweep_angle),
                    clockwise=settings.clockwise,
                )
                export_module.write_metadata(paths.json, document)

            if settings.export_godot:
                prefix = settings.godot_res_prefix
                if prefix and not prefix.endswith("/"):
                    prefix += "/"
                text = sprite_frames_tres(
                    f"{prefix}{image_name}",
                    layout,
                    settings.animation_name,
                    settings.fps,
                    settings.loop,
                )
                export_module.write_tres(paths.tres, text)
```

- [ ] **Step 6: Run the whole suite**

```bash
SCRATCH=/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad
.venv/bin/pytest -v
blender -b -P tests_blender/run_smoke.py > "$SCRATCH/smoke.log" 2>&1; echo "exit=$?"
grep -E "SMOKE|ok " "$SCRATCH/smoke.log"
```

Expected: pytest passes 44 tests across eight files; the smoke run reports `exit=0`, `SMOKE OK`, twenty `ok` lines.

- [ ] **Step 7: Write the README**

`README.md` covering: what RasterSheet does; installing it as an extension (drag the zipped `rastersheet/` directory onto Blender, or run `scripts/dev_link.sh` for development); the panel's controls grouped as in the UI; the scene-safety guarantee and the one case that defeats it (constraints and drivers); the JSON schema from spec section 8; how to use the `.tres` in Godot:

```gdscript
$AnimatedSprite2D.sprite_frames = preload("res://sprites/nuke_spin.tres")
$AnimatedSprite2D.play("spin")
```

and how to run both test suites.

- [ ] **Step 8: Verify the whole thing by hand**

In Blender, on a real model rather than a cube: pick Auto Orthographic, Material Preview lighting, 16 frames, 4 columns, and enable all four exports. Render. Then open the `.tres` in an actual Godot project and confirm the animation plays with correct framing and no clipped edges. This is the acceptance test for V1; passing suites are not a substitute.

- [ ] **Step 9: Commit**

```bash
git add rastersheet README.md tests_blender/run_smoke.py
git commit -m "feat: export JSON metadata and Godot SpriteFrames resources"
```

---

## Notes for the implementer

**Why `core/` may not import `bpy`.** It is not stylistic. `bpy` only exists inside Blender, so the moment a core module imports it the fast pytest suite can no longer run and every test in this plan costs a Blender startup. `tests/test_boundary.py` fails the build if the rule is broken.

**Why frames are written to disk even when the user does not want them.** Rendering to a temporary directory and reading back is cheaper than holding every frame's float buffer in memory, and it means the packing path is identical whether or not the frames are kept, so one code path is tested rather than two.

**Why the render loop is a generator.** V1 drains it synchronously. Blender's window is frozen while it does. The generator shape is what lets a later modal timer operator drive the same loop with a progress bar and Esc-to-cancel, without touching any of the logic.

**If a smoke check fails, read the log file, not a pipeline.** `blender -b -P ... | grep` returns grep's exit code, so a failing run looks like a passing one. Every command in this plan redirects to `$SCRATCH/smoke.log` and echoes `$?` separately for exactly that reason.

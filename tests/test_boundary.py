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

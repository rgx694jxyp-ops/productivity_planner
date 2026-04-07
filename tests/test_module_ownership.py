from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _imports(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
    return out


def _py_files(pattern: str) -> list[Path]:
    return [p for p in ROOT.glob(pattern) if p.is_file()]


def test_app_shell_imports_core_only() -> None:
    app_path = ROOT / "app.py"
    imports = _imports(app_path)
    bad = [name for name in imports if not name.startswith("core")]
    assert not bad, f"app.py should import only core modules, found: {bad}"


def test_domain_is_pure_logic() -> None:
    bad: list[str] = []
    for path in _py_files("domain/**/*.py"):
        for name in _imports(path):
            if name == "streamlit" or name.startswith("streamlit"):
                bad.append(f"{path.relative_to(ROOT)} imports {name}")
            if name.startswith(("core", "pages", "services", "ui")):
                bad.append(f"{path.relative_to(ROOT)} imports {name}")
    assert not bad, "Domain layer purity violations:\n" + "\n".join(bad)


def test_services_do_not_import_pages() -> None:
    bad: list[str] = []
    for path in _py_files("services/**/*.py"):
        for name in _imports(path):
            if name.startswith("pages"):
                bad.append(f"{path.relative_to(ROOT)} imports {name}")
    assert not bad, "Services must not import pages:\n" + "\n".join(bad)


def test_services_do_not_import_streamlit_or_core() -> None:
    bad: list[str] = []
    for path in _py_files("services/**/*.py"):
        for name in _imports(path):
            if name == "streamlit" or name.startswith("streamlit"):
                bad.append(f"{path.relative_to(ROOT)} imports {name}")
            if name.startswith("core"):
                bad.append(f"{path.relative_to(ROOT)} imports {name}")
    assert not bad, "Services must remain Streamlit/core independent:\n" + "\n".join(bad)


def test_ui_does_not_import_pages() -> None:
    bad: list[str] = []
    for path in _py_files("ui/**/*.py"):
        for name in _imports(path):
            if name.startswith("pages"):
                bad.append(f"{path.relative_to(ROOT)} imports {name}")
    assert not bad, "UI must not import pages:\n" + "\n".join(bad)


def test_utils_stays_generic() -> None:
    bad: list[str] = []
    for path in _py_files("utils/**/*.py"):
        for name in _imports(path):
            if name.startswith(("core", "pages", "services", "domain", "ui")):
                bad.append(f"{path.relative_to(ROOT)} imports {name}")
    assert not bad, "Utils must remain generic:\n" + "\n".join(bad)


def test_architecture_overview_doc_has_required_sections() -> None:
    doc = ROOT / "docs" / "architecture_overview.md"
    assert doc.exists(), "Expected docs/architecture_overview.md to exist"

    content = doc.read_text(encoding="utf-8")
    required_sections = [
        "## Navigation Flow",
        "## Access Gating Flow",
        "## Billing Flow",
        "## Import Flow",
        "## Email Jobs Flow",
        "## Keep This Document Current",
    ]

    missing = [section for section in required_sections if section not in content]
    assert not missing, (
        "architecture_overview.md is missing required sections:\n"
        + "\n".join(missing)
    )

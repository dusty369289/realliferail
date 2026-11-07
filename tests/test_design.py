"""Rules a screenshot can't check: contrast, where colours live, where HTTP lives, which way imports point."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "realliferail"
THEME = SRC / "web/static/css/themes/lights-down.css"


def tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,6})\s*;", block))


def themes() -> dict[str, dict[str, str]]:
    css = THEME.read_text()
    dark = tokens(css.split("@media")[0])
    light = tokens(css.split("@media")[1])
    return {"dark": dark, "light": {**dark, **light}}


def lum(hex_: str) -> float:
    h = hex_.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    rgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXT_ON = [
    ("ink", "page"),
    ("muted", "page"),
    ("problem", "page"),
    ("late", "page"),
    ("very-late", "page"),
    ("early", "page"),
    ("ink", "surface"),
    ("muted", "surface"),
    ("on-primary", "primary"),
    ("demo-ink", "demo"),
    ("muted", "surface-2"),
    ("ink", "surface-2"),
]


@pytest.mark.parametrize("scheme", ["dark", "light"])
@pytest.mark.parametrize(("fg", "bg"), TEXT_ON)
def test_text_contrast(scheme, fg, bg):
    t = themes()[scheme]
    assert contrast(t[fg], t[bg]) >= 4.5, f"{fg} on {bg} in {scheme}: {contrast(t[fg], t[bg]):.2f}"


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_train_marker_stands_out(scheme):
    t = themes()[scheme]
    assert contrast(t["train"], t["page"]) >= 3  # a graphic, so WCAG's 3:1 for non-text


def test_no_raw_colours_outside_themes():
    for css in (SRC / "web/static/css").rglob("*.css"):
        if "themes" in css.parts:
            continue
        found = re.findall(r"#[0-9a-fA-F]{3,6}\b|rgba?\(", css.read_text())
        assert not found, f"{css.name} has raw colours {found}"


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            out.add(("." * node.level) + (node.module or ""))
    return out


def test_http_lives_only_in_transport():
    for py in SRC.rglob("*.py"):
        if py.name == "transport.py":
            continue
        assert not {"httpx", "requests", "urllib.request"} & imports(py), py


def test_domain_has_no_io():
    for py in (SRC / "domain").rglob("*.py"):
        bad = {i for i in imports(py) if i.split(".")[0] in {"httpx", "os", "pathlib", "socket", "fastapi"}}
        bad |= {i for i in imports(py) if i.startswith("..")}
        assert not bad, f"{py.name} imports {bad}"


def test_dependencies_point_inward():
    rules = {"sources": {"..services", "..web", "..cli"}, "services": {"..web", "..cli"}, "web": {"..cli"}}
    for layer, banned in rules.items():
        for py in (SRC / layer).rglob("*.py"):
            hit = {i for i in imports(py) if any(i.startswith(b) for b in banned)}
            assert not hit, f"{layer}/{py.name} imports {hit}"


def test_templates_never_mark_safe():
    for t in (SRC / "web/templates").glob("*.html"):
        assert "|safe" not in t.read_text(), t.name

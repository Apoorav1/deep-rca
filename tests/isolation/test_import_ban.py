"""Isolation invariant: src/deeprca must never reach the ground-truth plane.

This is the static half of the GT-isolation guarantee (tests.json: p1-hide-ground-truth).
It walks every module under src/deeprca and fails if any imports `eval` or
`eval.ground_truth`.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "deeprca"

BANNED_ROOTS = {"eval"}  # also covers eval.ground_truth, eval.scorer, etc.


def _python_files() -> list[Path]:
    return list(SRC.rglob("*.py"))


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                names.append(node.module)
    return names


@pytest.mark.isolation
def test_no_src_imports_eval():
    offenders = []
    for f in _python_files():
        for mod in _imports(f):
            root = mod.split(".")[0]
            if root in BANNED_ROOTS:
                offenders.append((str(f.relative_to(SRC.parent.parent)), mod))
    assert not offenders, f"src/deeprca must not import ground-truth plane: {offenders}"


@pytest.mark.isolation
def test_ground_truth_loader_is_in_eval_only():
    # The loader lives under eval/, and no src/ module may IMPORT it.
    gt = SRC.parent.parent / "eval" / "ground_truth" / "__init__.py"
    assert gt.exists(), "ground-truth loader should live under eval/ground_truth"
    offenders = []
    for f in _python_files():
        for mod in _imports(f):
            if "ground_truth" in mod:
                offenders.append((str(f), mod))
    assert not offenders, f"src/deeprca must not import the GT loader: {offenders}"

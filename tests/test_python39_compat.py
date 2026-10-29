"""
Production (EC2, Amazon Linux 2023 system python) runs Python 3.9; CI and most dev machines run 3.12.
`def f(x: str | None)` is a *runtime* TypeError on 3.9 when the annotation is evaluated at definition
time (PEP 604 needs 3.10), and it passes every CI check on 3.12 — it took down a deploy in rehearsal.

This guard catches that class of bug: any backend module that uses `X | Y` inside an annotation must
start with `from __future__ import annotations` (annotations then stay lazy strings).
"""
import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"


def _annotation_nodes(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for a in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
                if a is not None and a.annotation is not None:
                    yield a.annotation
            if node.returns is not None:
                yield node.returns
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation


def _has_union_operator(annotation: ast.AST) -> bool:
    return any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) for n in ast.walk(annotation))


def _has_future_annotations(tree: ast.Module) -> bool:
    return any(
        isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names)
        for n in tree.body
    )


def test_backend_annotations_are_python39_safe():
    offenders = []
    for path in sorted(BACKEND.rglob("*.py")):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _has_future_annotations(tree):
            continue
        for ann in _annotation_nodes(tree):
            if _has_union_operator(ann):
                offenders.append(f"{path.relative_to(BACKEND.parent)}:{ann.lineno}")
    assert not offenders, (
        "PEP 604 `X | Y` annotation without `from __future__ import annotations` "
        f"(breaks on production's Python 3.9): {offenders}"
    )


def test_guard_detects_the_bug_it_exists_for():
    bad = ast.parse("def f(x: dict | None = None) -> str | None:\n    return None\n")
    assert any(_has_union_operator(a) for a in _annotation_nodes(bad))
    good = ast.parse("from __future__ import annotations\ndef f(x: dict | None = None): ...\n")
    assert _has_future_annotations(good)

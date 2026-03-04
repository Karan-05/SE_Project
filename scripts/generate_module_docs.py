"""Generate Markdown documentation for every Python module in src/."""
from __future__ import annotations

import argparse
import ast
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
DOCS_ROOT = PROJECT_ROOT / "docs" / "reference"


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def module_name(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    parts = list(rel.parts)
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(part for part in parts if part != "__init__")


def first_line(text: str | None) -> str:
    if not text:
        return ""
    return textwrap.dedent(text).strip().splitlines()[0]


def format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = []
    for arg in node.args.args:
        if arg.arg == "self":
            continue
        args.append(arg.arg)
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
    for kwarg in node.args.kwonlyargs:
        args.append(f"{kwarg.arg}=")
    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")
    return f"{node.name}({', '.join(args)})"


@dataclass
class FunctionInfo:
    signature: str
    doc: str


@dataclass
class ClassInfo:
    name: str
    doc: str
    methods: List[FunctionInfo]


def describe_module(path: Path, root: Path) -> tuple[str, str, List[ClassInfo], List[FunctionInfo]]:
    module_text = path.read_text(encoding="utf-8")
    tree = ast.parse(module_text)
    mod_doc = ast.get_docstring(tree) or ""
    classes: List[ClassInfo] = []
    functions: List[FunctionInfo] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods: List[FunctionInfo] = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = first_line(ast.get_docstring(item))
                    methods.append(FunctionInfo(signature=format_signature(item), doc=doc))
            classes.append(ClassInfo(name=node.name, doc=first_line(ast.get_docstring(node)), methods=methods))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(FunctionInfo(signature=format_signature(node), doc=first_line(ast.get_docstring(node))))
    return module_name(path, root), first_line(mod_doc), classes, functions


def write_module_doc(module: str, summary: str, classes: List[ClassInfo], functions: List[FunctionInfo], out_dir: Path) -> Path:
    safe_name = module.replace(".", "_") or "package_root"
    output = out_dir / f"{safe_name}.md"
    lines = [f"# {module or 'package'}", ""]
    lines.append(f"_Summary_: {summary or 'No module docstring provided.'}")
    lines.append("")
    if classes:
        lines.append("## Classes")
        for cls in classes:
            lines.append(f"### {cls.name}")
            lines.append(cls.doc or "No class docstring.")
            if cls.methods:
                lines.append("")
                lines.append("Methods:")
                for method in cls.methods:
                    desc = method.doc or ""
                    lines.append(f"- `{method.signature}` — {desc}")
            lines.append("")
    if functions:
        lines.append("## Functions")
        for fn in functions:
            desc = fn.doc or ""
            lines.append(f"- `{fn.signature}` — {desc}")
        lines.append("")
    output.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return output


def build_index(files: List[Path], out_dir: Path) -> None:
    lines = ["# Reference Index", ""]
    for path in files:
        rel = path.relative_to(out_dir)
        module_name = path.stem.replace("_", ".")
        lines.append(f"- [{module_name}]({rel.as_posix()})")
    (out_dir / "_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate per-module Markdown documentation.")
    parser.add_argument("--src-root", type=Path, default=SRC_ROOT, help="Root of the source tree")
    parser.add_argument("--out-dir", type=Path, default=DOCS_ROOT, help="Directory to place markdown files")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    outputs: List[Path] = []
    for py_file in iter_python_files(args.src_root):
        module, summary, classes, functions = describe_module(py_file, args.src_root)
        outputs.append(write_module_doc(module, summary, classes, functions, args.out_dir))
    build_index(outputs, args.out_dir)
    print(f"Wrote {len(outputs)} module docs to {args.out_dir}")


if __name__ == "__main__":
    main()

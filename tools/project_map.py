"""Generate searchable code/test indexes and a package dependency diagram.

Run ``python tools/project_map.py`` after moving code; use ``--check`` in CI.
Only the standard library is needed. Output is deterministic, without timestamps.
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from graphlib import TopologicalSorter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "klipperai_agent"
OUTPUT = ROOT / "docs/generated"


class ProjectMap:
    def __init__(self) -> None:
        self.modules: dict[str, dict] = {}
        self.tests: dict[str, set[str]] = defaultdict(set)

    @staticmethod
    def imports(tree: ast.AST) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
                names.update(f"{node.module}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
        return {name for name in names if name.startswith("klipperai_agent.")}

    def discover(self) -> None:
        for path in sorted(PACKAGE.rglob("*.py")):
            if path.name == "__init__.py":
                continue
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
            name = ".".join(path.relative_to(ROOT).with_suffix("").parts)
            symbols = []
            for node in tree.body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbol = {"name": node.name, "line": node.lineno, "kind": type(node).__name__}
                    if isinstance(node, ast.ClassDef):
                        symbol["methods"] = [
                            {"name": child.name, "line": child.lineno}
                            for child in node.body
                            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        ]
                    symbols.append(symbol)
            self.modules[name] = {
                "path": path.relative_to(ROOT).as_posix(),
                "lines": len(text.splitlines()),
                "symbols": symbols,
                "imports": sorted(self.imports(tree)),
            }
        for module in self.modules.values():
            module["imports"] = [name for name in module["imports"] if name in self.modules]
        for name, module in self.modules.items():
            owner = name.split(".")[1]
            forbidden = {
                "providers",
                "infrastructure",
                "web",
                "contracts",
                "workflows",
                "application",
            }
            for dependency in module["imports"]:
                target = dependency.split(".")[1]
                if (owner == "domain" and target != "domain") or (
                    owner == "agent" and target in forbidden
                ):
                    raise ValueError(f"Architecture boundary violated: {name} -> {dependency}")
        for path in sorted((ROOT / "tests").rglob("test_*.py")):
            for name in self.imports(ast.parse(path.read_text(encoding="utf-8"))):
                if name in self.modules:
                    self.tests[name].add(path.relative_to(ROOT).as_posix())
        for name, module in self.modules.items():
            module["tests"] = sorted(self.tests[name])
        tuple(
            TopologicalSorter(
                {name: item["imports"] for name, item in self.modules.items()}
            ).static_order()
        )

    def artifacts(self) -> dict[str, str]:
        table = [
            "# Generated module index",
            "",
            "Regenerate with `python tools/project_map.py`. Listed tests directly import the module; integration tests may cover it indirectly.",
            "",
            "| Module | Lines | Classes / functions | Direct tests |",
            "| --- | ---: | --- | --- |",
        ]
        edges: set[tuple[str, str]] = set()
        for name, item in self.modules.items():
            path = item["path"]
            symbols = ", ".join(
                f"`{symbol['name']}`"
                for symbol in item["symbols"]
                if not symbol["name"].startswith("_")
            )
            tests = ", ".join(f"[{Path(test).stem}](../../{test})" for test in item["tests"])
            table.append(
                f"| [{name.removeprefix('klipperai_agent.')}](../../{path}) | {item['lines']} | {symbols} | {tests} |"
            )
            owner = name.split(".")[1]
            for dependency in item["imports"]:
                target = dependency.split(".")[1]
                if owner != target:
                    edges.add((owner, target))
        graph = ["flowchart LR", "    %% Generated import direction: importer --> dependency"]
        graph.extend(f"    {source} --> {target}" for source, target in sorted(edges))
        return {
            "code-index.json": json.dumps({"modules": self.modules}, indent=2) + "\n",
            "module-index.md": "\n".join(table) + "\n",
            "dependencies.mmd": "\n".join(graph) + "\n",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated files are stale")
    args = parser.parse_args()
    project = ProjectMap()
    project.discover()
    stale = []
    for name, content in project.artifacts().items():
        path = OUTPUT / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(name)
        else:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    if stale:
        raise SystemExit(
            "Stale project map: " + ", ".join(stale) + ". Run python tools/project_map.py"
        )
    print(
        f"{'Checked' if args.check else 'Generated'} {len(project.modules)} modules; module imports are acyclic."
    )


if __name__ == "__main__":
    main()

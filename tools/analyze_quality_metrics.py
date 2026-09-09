from __future__ import annotations

import ast
import json
import re
import threading
import trace
import unittest
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def python_files() -> list[Path]:
    return sorted(path for path in APP.rglob("*.py") if "__pycache__" not in path.parts)


def source_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def logical_lines(path: Path) -> set[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and hasattr(node, "lineno"):
            lines.add(node.lineno)
    return lines


class FunctionMetrics(ast.NodeVisitor):
    def __init__(self) -> None:
        self.functions: list[dict] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record(node)
        self.generic_visit(node)

    def _record(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        complexity = 1
        cognitive = 0

        def walk(current: ast.AST, nesting: int = 0) -> None:
            nonlocal complexity, cognitive
            decision = isinstance(current, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.Match))
            if decision:
                complexity += 1
                cognitive += 1 + nesting
                nesting += 1
            elif isinstance(current, ast.BoolOp):
                complexity += max(0, len(current.values) - 1)
                cognitive += max(0, len(current.values) - 1)
            elif isinstance(current, ast.comprehension):
                complexity += 1 + len(current.ifs)
                cognitive += 1 + nesting + len(current.ifs)
            elif isinstance(current, ast.ExceptHandler):
                complexity += 1
                cognitive += 1 + nesting
                nesting += 1
            for child in ast.iter_child_nodes(current):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and child is not node:
                    continue
                walk(child, nesting)

        walk(node)
        end = getattr(node, "end_lineno", node.lineno)
        self.functions.append(
            {
                "name": node.name,
                "line": node.lineno,
                "end": end,
                "length": end - node.lineno + 1,
                "cyclomatic": complexity,
                "cognitive": cognitive,
            }
        )


def normalize_line(line: str) -> str:
    line = re.sub(r"#.*$", "", line).strip()
    line = re.sub(r"(['\"]).*?\1", "STR", line)
    line = re.sub(r"\b\d+(?:\.\d+)?\b", "NUM", line)
    return re.sub(r"\s+", " ", line)


def run_tests_with_trace() -> tuple[unittest.result.TestResult, dict]:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    runner = unittest.TextTestRunner(verbosity=0)
    tracer = trace.Trace(count=True, trace=False)
    previous_thread_trace = threading.gettrace()
    threading.settrace(tracer.globaltrace)
    try:
        result = tracer.runfunc(runner.run, suite)
    finally:
        threading.settrace(previous_thread_trace)
    return result, tracer.results().counts


def analyze() -> dict:
    files = python_files()
    all_functions: list[dict] = []
    executable_by_file: dict[str, set[int]] = {}
    imports_by_file: dict[str, set[str]] = {}
    broad_exceptions: list[dict] = []
    security_hits: list[dict] = []
    normalized_lines: list[tuple[str, int, str]] = []

    for path in files:
        rel = str(path.relative_to(ROOT))
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        executable_by_file[str(path.resolve())] = logical_lines(path)
        visitor = FunctionMetrics()
        visitor.visit(tree)
        for metric in visitor.functions:
            metric["file"] = rel
            all_functions.append(metric)

        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names if alias.name.startswith("app."))
            elif isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Name) and node.type.id == "Exception":
                broad_exceptions.append({"file": rel, "line": node.lineno, "kind": "Captura amplia de Exception"})
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                security_hits.append({"file": rel, "line": node.lineno, "kind": f"Uso de {node.func.id}"})
        imports_by_file[rel] = imports
        for line_no, line in enumerate(source_lines(path), 1):
            normalized = normalize_line(line)
            if normalized:
                normalized_lines.append((rel, line_no, normalized))

    window_size = 6
    windows: defaultdict[tuple[str, ...], list[tuple[str, int]]] = defaultdict(list)
    by_file: defaultdict[str, list[tuple[int, str]]] = defaultdict(list)
    for rel, line_no, normalized in normalized_lines:
        by_file[rel].append((line_no, normalized))
    for rel, rows in by_file.items():
        for index in range(0, max(0, len(rows) - window_size + 1)):
            block = tuple(value for _, value in rows[index : index + window_size])
            windows[block].append((rel, rows[index][0]))
    duplicated_lines: set[tuple[str, int]] = set()
    duplicate_blocks = 0
    for occurrences in windows.values():
        locations = {rel for rel, _ in occurrences}
        if len(occurrences) > 1 and len(locations) > 1:
            duplicate_blocks += 1
            for rel, start in occurrences:
                duplicated_lines.update((rel, start + offset) for offset in range(window_size))

    test_result, counts = run_tests_with_trace()
    executable_total = sum(len(lines) for lines in executable_by_file.values())
    covered_total = 0
    for absolute, lines in executable_by_file.items():
        covered_total += sum(1 for line in lines if counts.get((absolute, line), 0) > 0)

    long_functions = [item for item in all_functions if item["length"] > 60]
    complex_functions = [item for item in all_functions if item["cyclomatic"] > 10]
    major_findings = long_functions + complex_functions + broad_exceptions
    module_count = len(files)
    focused_modules = sum(
        1
        for rel in imports_by_file
        if len(imports_by_file[rel]) <= 3
        and sum(1 for function in all_functions if function["file"] == rel) <= 15
    )

    return {
        "python_files": module_count,
        "loc": len(normalized_lines),
        "statement_lines": executable_total,
        "covered_statement_lines": covered_total,
        "statement_coverage": covered_total / executable_total if executable_total else 0,
        "tests_run": test_result.testsRun,
        "tests_successful": test_result.wasSuccessful(),
        "test_failures": len(test_result.failures),
        "test_errors": len(test_result.errors),
        "function_count": len(all_functions),
        "max_cyclomatic": max((item["cyclomatic"] for item in all_functions), default=0),
        "max_cyclomatic_function": max(all_functions, key=lambda item: item["cyclomatic"], default={}),
        "average_cognitive": sum(item["cognitive"] for item in all_functions) / len(all_functions) if all_functions else 0,
        "max_cognitive_function": max(all_functions, key=lambda item: item["cognitive"], default={}),
        "duplication_ratio": len(duplicated_lines) / len(normalized_lines) if normalized_lines else 0,
        "duplicate_blocks": duplicate_blocks,
        "critical_blocking_issues": len(security_hits),
        "security_hits": security_hits,
        "major_findings": major_findings,
        "major_findings_count": len(major_findings),
        "code_smells": len(long_functions) + len(complex_functions) + len(broad_exceptions),
        "long_functions": long_functions,
        "complex_functions": complex_functions,
        "broad_exceptions": broad_exceptions,
        "average_internal_imports": sum(len(value) for value in imports_by_file.values()) / module_count if module_count else 0,
        "max_internal_imports": max((len(value) for value in imports_by_file.values()), default=0),
        "focused_module_ratio": focused_modules / module_count if module_count else 0,
        "focused_modules": focused_modules,
    }


if __name__ == "__main__":
    output = analyze()
    print(json.dumps(output, ensure_ascii=False, indent=2))

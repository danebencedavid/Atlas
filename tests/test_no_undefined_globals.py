"""Every global a module reads must be bound somewhere in that module.

This exists because a missing import shipped to production and broke the daily
build for two commits while the whole suite stayed green. A patch inserted
``read_withheld`` and two siblings into ``cli.py`` but its import line never
landed, and nothing noticed: no test exercises ``run_pipeline``, so the
``NameError`` only surfaced in CI, three minutes into a real build.

A unit test per call path would not have caught it either. What catches it is
asking, statically, whether every name a function looks up in module scope is
actually bound there.
"""

from __future__ import annotations

import builtins
import pathlib
import symtable

PACKAGE = pathlib.Path(__file__).resolve().parents[1] / "src" / "atlas"


def _undefined_globals(path: pathlib.Path) -> list[tuple[str, str]]:
    """Names read from module scope that the module never binds."""
    table = symtable.symtable(path.read_text(encoding="utf-8"), str(path), "exec")
    bound_at_module_level = set(table.get_identifiers())
    findings: list[tuple[str, str]] = []

    def walk(scope: symtable.SymbolTable) -> None:
        for symbol in scope.get_symbols():
            # A global that is read but never assigned anywhere in this module,
            # and is not a builtin, can only come from an import that is missing.
            if symbol.is_global() and not symbol.is_assigned():
                name = symbol.get_name()
                if name not in bound_at_module_level and not hasattr(builtins, name):
                    findings.append((scope.get_name(), name))
        for child in scope.get_children():
            walk(child)

    walk(table)
    return sorted(set(findings))


def test_no_module_reads_an_unbound_global():
    offenders: dict[str, list[tuple[str, str]]] = {}
    for module in sorted(PACKAGE.glob("*.py")):
        found = _undefined_globals(module)
        if found:
            offenders[module.name] = found
    assert not offenders, f"unbound globals (usually a missing import): {offenders}"


def test_the_check_detects_a_missing_import(tmp_path):
    """Guard the guard: a silent no-op check would be worse than none."""
    module = tmp_path / "broken.py"
    module.write_text(
        "def run():\n"
        "    return read_withheld(1)\n",
        encoding="utf-8",
    )
    assert _undefined_globals(module) == [("run", "read_withheld")]

    fixed = tmp_path / "fixed.py"
    fixed.write_text(
        "from somewhere import read_withheld\n\n\ndef run():\n    return read_withheld(1)\n",
        encoding="utf-8",
    )
    assert _undefined_globals(fixed) == []

"""A stand-in has to answer everything the real one is asked.

`tests/test_main_window.py` held two hand-written `class Bus` doubles. `SignalBus` grew
`pending_count`, `main_window` started reading it from a two-second timer, and the doubles stayed
where they were. The `AttributeError` landed inside a Qt slot, where Qt prints it to stderr and
carries on -- and pytest captures stderr on a passing test, so the run stayed green and said
nothing (HUB-046, measured 2026-09-07: `pytest -s` printed the traceback twice, `pytest` printed
it never).

Two mechanisms come out of that, and this file is the first: whatever stands in the `bus` slot of
a test must carry every name the production code asks of a bus. The second is in `conftest.py` --
an exception in a Qt slot fails the test instead of scrolling past.

Same kind of boundary as `test_packaging.py`: something no reviewer reliably notices, checked by a
command instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"


def _slot_name(node: ast.expr) -> str | None:
    """The last name of an expression: `bus`, `server.bus` and `self.bus` all answer "bus"."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


#: The slots checked here, and the real class that fills each one in production. One entry so far;
#: a second costs a line, which is the point of spelling it as a table rather than as `"bus"` twice.
SLOTS = {"bus": "autosound_tcc.core.signal_bus:SignalBus"}


def _protocol(slot: str) -> dict[str, str]:
    """Every name the production code reads off `slot`, and the first place it reads it.

    Derived from the code rather than listed here on purpose: a list would be one more thing to
    keep in step, which is the failure this file exists to catch.
    """
    found: dict[str, str] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and _slot_name(node.value) == slot:
                if not node.attr.startswith("_"):
                    found.setdefault(node.attr, f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


def _class_names(cls: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> set[str]:
    """Public names a class answers to, counting the ones it inherits from a base defined here."""
    names: set[str] = set()
    for item in cls.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(item.name)
        elif isinstance(item, ast.Assign):
            names.update(t.id for t in item.targets if isinstance(t, ast.Name))
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            names.add(item.target.id)
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id in classes:
            names |= _class_names(classes[base.id], classes)
    return {name for name in names if not name.startswith("_")}


def doubles_in(source: str, label: str, slot: str) -> list[tuple[str, str, set[str]]]:
    """Classes this source puts in `slot`: (label with line, class name, public names).

    A double is recognised by where it is used, not by what it is called: any locally defined class
    instantiated into something named `bus` -- `bus = Bus()`, `self.bus = FakeBus()` -- stands in
    for the real one. Assigning an imported class (`bus = SignalBus(tmp_path)`) is the real thing
    and needs no check.
    """
    tree = ast.parse(source)
    classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    doubles: list[tuple[str, str, set[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(_slot_name(t) == slot for t in targets):
            continue
        value = node.value
        if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)):
            continue
        cls = classes.get(value.func.id)
        if cls is None:
            continue
        doubles.append((f"{label}:{node.lineno}", cls.name, _class_names(cls, classes)))
    return doubles


def test_the_protocol_is_found_and_the_real_class_answers_all_of_it():
    """Two ways this file could go quiet: find nothing, or check against a name nobody has.

    The second half is a defect in its own right -- production code reading a name off the bus that
    `SignalBus` does not define would be the same swallowed `AttributeError`, one layer up.
    """
    import importlib

    for slot, target in SLOTS.items():
        module_name, class_name = target.split(":")
        real = getattr(importlib.import_module(module_name), class_name)
        protocol = _protocol(slot)
        assert len(protocol) >= 4, f"the scan for `{slot}` found almost nothing: {protocol}"
        missing = {name: where for name, where in protocol.items() if not hasattr(real, name)}
        assert not missing, f"code asks `{slot}` for names {class_name} does not have: {missing}"


def test_every_double_in_the_tests_answers_the_whole_protocol():
    complaints = []
    for slot in SLOTS:
        protocol = _protocol(slot)
        for path in sorted(TESTS.rglob("*.py")):
            label = str(path.relative_to(ROOT))
            source = path.read_text(encoding="utf-8")
            for where, name, names in doubles_in(source, label, slot):
                missing = sorted(set(protocol) - names)
                if missing:
                    complaints.append(
                        f"{where}: `class {name}` stands in for `{slot}` but has no "
                        f"{', '.join(missing)} -- read by "
                        f"{', '.join(protocol[m] for m in missing)}"
                    )
    assert not complaints, "\n".join(
        ["a test double answers less than the real thing:", *complaints]
    )


def test_the_check_goes_red_when_a_double_falls_behind():
    """The guard's own red state, kept in the suite rather than demonstrated once by hand.

    Without this, the two tests above pass just as happily when the scan quietly breaks -- and a
    guard that cannot be seen failing is not known to work.
    """
    deficient = '''
class Bus:
    def push(self, kind, **payload):
        return None

    def is_open(self, signal_id):
        return True


class Server:
    bus = Bus()
'''
    doubles = doubles_in(deficient, "<sample>", "bus")
    assert len(doubles) == 1, doubles
    _where, name, names = doubles[0]
    assert name == "Bus"
    assert "pending_count" not in names, "the sample is the pre-HUB-046 double: it lacks the name"
    assert set(_protocol("bus")) - names, "the check would pass a double missing pending_count"

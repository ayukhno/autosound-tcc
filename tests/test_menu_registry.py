"""G13 A1 (#161): the main menu as data — today's lines transcribed, a feature's lines by anchor."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import types

from autosound_tcc.core import guide
from autosound_tcc.ui.tcc import i18n, menu_registry
from autosound_tcc.ui.tcc.menu_registry import MenuEntry
from tests import _menu_pin


class _Recorder:
    """A host that writes down which window method an entry calls, and with what."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args, **kwargs: self.calls.append((name, args, kwargs))


def _entry(entry_id):
    return next(e for e in menu_registry.window_entries() if e.id == entry_id)


def _drawn(entries, place=None, depth=0):
    """What the renderer draws from `entries`, in `_menu_pin`'s rows: a heading per section, a
    separator before every heading but the first, a submenu's lines below its title."""
    if place is None:
        rows = []
        for index, (section, key) in enumerate(menu_registry.SECTIONS):
            if index:
                rows.append(_menu_pin.SEP)
            rows.append((0, "heading", i18n.t(key).upper(), "", False, False))
            rows.extend(_drawn(entries, section, 0))
        return rows
    rows = []
    for entry in menu_registry.ordered(entries, place):
        if entry.submenu:
            rows.append((depth, "menu", entry.text(), entry.tip(), False, entry.bold))
            rows.extend(_drawn(entries, entry.id, depth + 1))
        else:
            rows.append((depth, "line", entry.text(), entry.tip(), entry.checked is not None,
                         entry.bold))
    return rows


def test_the_registry_holds_today_s_menu_line_by_line():
    assert _drawn(menu_registry.window_entries()) == _menu_pin.pinned_rows()


def test_copy_the_car_asks_for_a_seeded_dialog():
    host = _Recorder()
    _entry("copy_car").on(host)
    _entry("new_project").on(host)
    assert host.calls == [("_open_new_project_dialog", (), {"seed": True}),
                          ("_open_new_project_dialog", (), {})]


def test_a_handler_is_called_with_its_own_argument_and_nothing_of_qt_s():
    host = _Recorder()
    for entry_id in ("gate_foreign", "eq_q_first", "lang_uk", "start_session", "target_tool"):
        _entry(entry_id).on(host)
    assert host.calls == [("_set_gate_mode", ("foreign",), {}),
                          ("_set_eq_order_pref", ("q_first",), {}),
                          ("_on_language_selected", ("uk",), {}),
                          ("_start_tuning_session", (), {}),
                          ("_open_target_curve_tool", (), {})]


def test_the_window_s_menu_has_no_problems():
    assert menu_registry.problems(menu_registry.collect(), set(i18n.T["en"])) == []


def test_every_entry_calls_a_method_the_window_has():
    from autosound_tcc.ui.tcc.main_window import MainWindow
    for entry in menu_registry.window_entries():
        for call in (entry.on, entry.checked):
            if call is not None:
                host = _Recorder()
                call(host)
                assert all(hasattr(MainWindow, name) for name, _a, _k in host.calls), entry.id


class _Host:
    _agent_worker = None

    def _effective_gate(self):
        return "foreign"

    def _eq_order_pref(self):
        return "q_first"


def test_the_ticks_and_the_greyed_lines_follow_the_window():
    """What `_sync_menu_state` sets today: the project's gate, this machine's EQ order and the
    language ticked; saving and a fresh session only with a session running."""
    entries = menu_registry.window_entries()
    host = _Host()
    i18n.set_language("uk")
    try:
        assert [e.id for e in entries if e.checked and e.checked(host)] == [
            "eq_q_first", "gate_foreign", "lang_uk"]
    finally:
        i18n.set_language("en")
    greyed = [e.id for e in entries if e.enabled and not e.enabled(host)]
    assert greyed == ["save_state", "fresh_session"]
    host._agent_worker = object()
    assert all(e.enabled(host) for e in entries if e.enabled)


def test_the_pages_open_at_their_addresses(monkeypatch):
    monkeypatch.setattr(guide, "installed_guide_url", lambda page=guide.QUICK_GUIDE: f"v9/{page}")
    assert [_entry(i).url() for i in ("guide_quick", "guide_full", "guide_curve")] == [
        "v9/QUICK-GUIDE.md", "v9/REFERENCE.md", "v9/HOUSE-CURVE.md"]
    assert _entry("support_github").url() == menu_registry.SPONSORS_URL
    assert _entry("support_monobank").url() == menu_registry.MONOBANK_URL
    assert menu_registry.SPONSORS_URL.startswith("https://github.com/sponsors/")
    assert menu_registry.MONOBANK_URL.startswith("https://send.monobank.ua/jar/")


def test_the_window_attributes_the_tests_use_are_these_five():
    aliases = {(e.alias, e.alias_key) for e in menu_registry.window_entries() if e.alias}
    assert {alias for alias, _key in aliases} == {
        "_intake_action", "_reload_action", "_import_action", "_gate_actions", "_eq_order_actions"}
    assert sorted(key for alias, key in aliases if alias == "_gate_actions") == [
        "auto", "foreign", "never", "writes"]
    assert sorted(key for alias, key in aliases if alias == "_eq_order_actions") == [
        "auto", "gain_first", "q_first"]


def test_an_anchor_puts_an_entry_right_before_its_neighbour():
    entries = [MenuEntry("a", "project", label="A", on=print),
               MenuEntry("b", "project", label="B", on=print),
               MenuEntry("x", "project", label="X", on=print, before="b")]
    assert [e.id for e in menu_registry.ordered(entries, "project")] == ["a", "x", "b"]


def test_after_follows_its_neighbour_and_an_unknown_anchor_goes_last():
    entries = [MenuEntry("y", "tools", label="Y", on=print, after="a"),
               MenuEntry("z", "tools", label="Z", on=print, before="nowhere"),
               MenuEntry("a", "tools", label="A", on=print),
               MenuEntry("b", "tools", label="B", on=print),
               MenuEntry("c", "help", label="C", on=print)]
    assert [e.id for e in menu_registry.ordered(entries, "tools")] == ["a", "y", "b", "z"]


def test_problems_name_a_duplicate_id_an_unknown_place_and_a_missing_key():
    entries = [MenuEntry("a", "project", label_key="npCancel", on=print),
               MenuEntry("a", "nowhere", label_key="noSuchKey", on=print)]
    said = " ".join(menu_registry.problems(entries, set(i18n.T["en"])))
    assert "'a'" in said and "nowhere" in said and "noSuchKey" in said


def test_problems_name_a_line_that_does_nothing_and_an_anchor_nowhere():
    entries = [MenuEntry("mute", "tools", label="M"),
               MenuEntry("lost", "tools", label="L", on=print, before="ghost")]
    said = " ".join(menu_registry.problems(entries, set(i18n.T["en"])))
    assert "'mute'" in said and "'lost'" in said and "ghost" in said


def test_collect_reads_the_providers_when_it_is_called(monkeypatch):
    """A feature adds its line by naming its module in PROVIDERS: nothing in the window changes."""
    feature = types.ModuleType("tcc_fake_feature")
    feature.menu_entries = lambda: [MenuEntry("save_car", "project", label="Save the car…",
                                              on=lambda w: w._save_car(), before="intake")]
    monkeypatch.setitem(sys.modules, "tcc_fake_feature", feature)
    monkeypatch.setattr(menu_registry, "PROVIDERS", ("tcc_fake_feature",))
    entries = menu_registry.collect()
    ids = [e.id for e in menu_registry.ordered(entries, "project")]
    assert ids[ids.index("save_car") + 1] == "intake"
    assert len(entries) == len(menu_registry.window_entries()) + 1


def test_the_registry_imports_no_qt():
    done = subprocess.run([sys.executable, "-c", textwrap.dedent("""
        import sys
        from autosound_tcc.ui.tcc import i18n, menu_registry
        entries = menu_registry.collect()
        assert menu_registry.problems(entries, set(i18n.T["en"])) == []
        for place, _key in menu_registry.SECTIONS:
            menu_registry.ordered(entries, place)
        print(sorted(m for m in sys.modules if m.split(".")[0] in ("PySide6", "shiboken6")))
    """)], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"

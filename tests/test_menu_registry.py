"""G13 A1 (#161): the main menu as data — today's lines transcribed, a feature's lines by anchor."""

from __future__ import annotations

import inspect
import sys
import types

from autosound_tcc.core import guide
from autosound_tcc.ui.tcc import i18n, menu_registry
from autosound_tcc.ui.tcc.menu_registry import MenuEntry
from tests import _menu_pin
from tests._fresh import qt_loaded


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


def _does(entry):
    """What pressing the line does: the one window call it makes, or the page it opens."""
    if entry.url is not None:
        return ("page", entry.url())
    host = _Recorder()
    entry.on(host)
    (call,) = host.calls
    return call


def test_every_line_does_what_the_old_menu_did(monkeypatch):
    """Keyed by what the line SAYS, from the deleted `_build_main_menu`: two handlers swapped, a
    lambda that lost its captured value, or two EQ orders swapped under unchanged labels all fail
    here (the G13 review's mutants passed the earlier five-line sample). Each call also binds to
    the window method's own signature."""
    from autosound_tcc.ui.tcc.main_window import MainWindow

    monkeypatch.setattr(guide, "installed_guide_url", lambda page=guide.QUICK_GUIDE: f"v9/{page}")
    t = i18n.t
    expected = [
        (t("projectOpen"), ("_choose_project_folder", (), {})),
        (t("projectNew"), ("_open_new_project_dialog", (), {})),
        (t("menuCopyCar"), ("_open_new_project_dialog", (), {"seed": True})),
        (t("menuIntake"), ("_open_intake_form", (), {})),
        (t("menuReload"), ("_on_reload_pressed", (), {})),
        (t("menuStartSession"), ("_start_tuning_session", (), {})),
        (t("menuTerminal"), ("_open_terminal", (), {})),
        (t("projectSaveState"), ("_save_project_state", (), {})),
        (t("projectFreshSession"), ("_start_fresh_session", (), {})),
        (t("menuDiagnostics"), ("_open_diagnostics", (), {})),
        (t("riImport"), ("_open_resonalyze_import", (), {})),
        (t("menuTargetTool"), ("_open_target_curve_tool", (), {})),
        (t("eqOrderAuto"), ("_set_eq_order_pref", ("auto",), {})),
        ("Freq · Gain · Q", ("_set_eq_order_pref", ("gain_first",), {})),
        ("Freq · Q · Gain", ("_set_eq_order_pref", ("q_first",), {})),
        (t("menuModels"), ("_open_model_config", (), {})),
        (t("menuReviewerKey"), ("_open_reviewer_key", (), {})),
        (t("gateWrites"), ("_set_gate_mode", ("writes",), {})),
        (t("gateForeign"), ("_set_gate_mode", ("foreign",), {})),
        (t("gateAuto"), ("_set_gate_mode", ("auto",), {})),
        (t("gateNever"), ("_set_gate_mode", ("never",), {})),
        ("◐ " + t("menuTheme"), ("_toggle_theme", (), {})),
        *[(t(key), ("_on_language_selected", (code,), {})) for code, key, _badge in i18n.LANGS],
        (t("menuZoomIn"), ("_zoom_in", (), {})),
        (t("menuZoomOut"), ("_zoom_out", (), {})),
        (t("menuGuideQuick"), ("page", "v9/QUICK-GUIDE.md")),
        (t("menuGuideFull"), ("page", "v9/REFERENCE.md")),
        (t("menuGuideCurve"), ("page", "v9/HOUSE-CURVE.md")),
        ("💬 " + t("fbBig"), ("_open_feedback", (), {})),
        (t("supportGithub"), ("page", menu_registry.SPONSORS_URL)),
        (t("supportMonobank"), ("page", menu_registry.MONOBANK_URL)),
    ]
    lines = [e for e in menu_registry.window_entries() if not e.submenu]
    assert [(e.text(), _does(e)) for e in lines] == expected
    for _text, (name, *rest) in expected:
        if name != "page":
            args, kwargs = rest
            inspect.signature(getattr(MainWindow, name)).bind(None, *args, **kwargs)


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


def test_an_anchor_to_an_anchored_line_follows_it():
    entries = [MenuEntry("p", "tools", label="P", on=print, before="q"),
               MenuEntry("q", "tools", label="Q", on=print, before="b"),
               MenuEntry("a", "tools", label="A", on=print),
               MenuEntry("b", "tools", label="B", on=print)]
    assert [e.id for e in menu_registry.ordered(entries, "tools")] == ["a", "p", "q", "b"]


def test_problems_name_a_submenu_nothing_reaches_and_one_named_like_a_section():
    """Each drew wrong with no word said: a submenu placed inside itself vanished with its lines,
    and a submenu called "tools" drew the whole TOOLS section twice."""
    entries = [MenuEntry("loop", "loop", label="Loop", submenu=True),
               MenuEntry("inside", "loop", label="In", on=print),
               MenuEntry("tools", "help", label="Tools again", submenu=True)]
    said = " ".join(menu_registry.problems(entries, set(i18n.T["en"])))
    assert "'loop'" in said and "'inside'" in said and "'tools'" in said


def test_problems_refuse_an_alias_outside_the_window_s_five():
    """A provider line with alias="_status_strip" replaced the window's status strip."""
    entries = [MenuEntry("x", "tools", label="X", on=print, alias="_status_strip"),
               MenuEntry("y", "tools", label="Y", on=print, alias_key="k")]
    said = " ".join(menu_registry.problems(entries, set(i18n.T["en"])))
    assert "_status_strip" in said and "'y'" in said


def test_problems_name_both_anchors_a_line_that_says_nothing_and_a_lost_heading(monkeypatch):
    monkeypatch.setattr(menu_registry, "SECTIONS",
                        menu_registry.SECTIONS + (("extra", "noSuchHeading"),))
    entries = [MenuEntry("both", "tools", label="B", on=print, before="a", after="a"),
               MenuEntry("a", "tools", label="A", on=print),
               MenuEntry("mute", "tools", on=print)]
    said = " ".join(menu_registry.problems(entries, set(i18n.T["en"])))
    assert "'both'" in said and "'mute'" in said and "noSuchHeading" in said


def test_a_provider_that_fails_is_logged_and_skipped(monkeypatch, caplog):
    """One bad feature must not stop the window from opening: its lines are left out, and why is
    in the log."""
    feature = types.ModuleType("tcc_broken_feature")

    def menu_entries():
        raise RuntimeError("the feature broke")

    feature.menu_entries = menu_entries
    monkeypatch.setitem(sys.modules, "tcc_broken_feature", feature)
    monkeypatch.setattr(menu_registry, "PROVIDERS", ("tcc_missing_feature", "tcc_broken_feature"))
    assert [e.id for e in menu_registry.collect()] == [e.id for e in menu_registry.window_entries()]
    assert "tcc_broken_feature" in caplog.text and "the feature broke" in caplog.text
    assert "tcc_missing_feature" in caplog.text


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
    assert qt_loaded("""
        from autosound_tcc.ui.tcc import i18n, menu_registry
        entries = menu_registry.collect()
        assert menu_registry.problems(entries, set(i18n.T["en"])) == []
        for place, _key in menu_registry.SECTIONS:
            menu_registry.ordered(entries, place)
    """) == "[]"

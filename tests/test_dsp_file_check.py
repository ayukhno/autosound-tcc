"""«Перевірити налаштування» (#272): which DSP files the method reads, what its `compare-file` answered,
and the button and table the person sees. The method is faked on `method_cli.spawn` where its v3.3.2
lacks an answer (`warning_uk`, `readers.json`), and run for real on the files it ships."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget  # noqa: E402

import pytest  # noqa: E402

from autosound_tcc.core import dsp_file, method_cli, vendor_loader  # noqa: E402
from autosound_tcc.ui.tcc import dsp_file_check, i18n  # noqa: E402
from autosound_tcc.ui.tcc.sidebar_section import SidebarSection  # noqa: E402

from tests import _intake  # noqa: E402

HELIX = {"dsp_profile": {"vendor": "Audiotec-Fischer", "name": "Helix DSP Ultra S", "groups": []}}
HELIX_BRAND = {"dsp_profile": {"vendor": "Helix", "name": "DSP Ultra S", "groups": []}}
MOSCONI = {"dsp_profile": {"vendor": "Mosconi", "name": "PICO 6/8-2 DSP", "groups": []}}
MOSCONI_OTHER = {"dsp_profile": {"vendor": "Mosconi", "name": "PICO 8 DSP", "groups": []}}
OTHER = {"dsp_profile": {"vendor": "Musway", "name": "M6V4", "groups": []}}

CONTRACT = vendor_loader._SUBMODULE_DIR / "rew_tool" / "CONTRACT.md"
TESTDATA = vendor_loader._SUBMODULE_DIR / "rew_tool" / "testdata"
AYA = TESTDATA / "helix-pct6" / "AYA.pct6"
PR15 = TESTDATA / "mosconi-pr" / "example_pico682.PR15"

#: The method's v3.3.3 declaration (`knowledge/dsp/readers.json`, CONTRACT.md item 15), as its
#: branch holds it: what the pin will carry, faked until it does.
DECLARATION = {
    "contract": "readers.v1",
    "about": "The DSP saved-file readers the method ships.",
    "readers": [
        {"id": "helix_pct6", "family": "Audiotec-Fischer", "module": "rew_tool/helix_pct6", "pattern": ".pct6",
         "verbs": ["compare-file", "attest --from-file", "propose --from-file"], "model_code": "dev",
         "models": [{"name": "HELIX DSP ULTRA S", "code": "39", "checked_model": True},
                    {"name": "HELIX NEXT V EIGHT DSP ULTIMATE", "code": "44", "checked_model": True}],
         "other_models": {"read": True, "checked_model": False, "channels_mapped": False}},
        {"id": "mosconi_pr", "family": "Mosconi", "module": "rew_tool/mosconi_pr.py", "pattern": ".PR<n>",
         "verbs": ["compare-file", "attest --from-file", "propose --from-file"], "model_code": "extension",
         "models": [{"name": "Mosconi PICO 6/8-2 DSP", "code": "15", "checked_model": False}],
         "other_models": {"read": True, "checked_model": False, "channels_mapped": False}},
    ],
}


def _app():
    return QApplication.instance() or QApplication([])


def declare(monkeypatch, tmp_path, declaration=DECLARATION) -> Path:
    """A copy of the method that carries `readers.json`: only the file the lookup reads."""
    skill = tmp_path / "skill"
    (skill / "knowledge" / "dsp").mkdir(parents=True, exist_ok=True)
    (skill / "knowledge" / "dsp" / "readers.json").write_text(json.dumps(declaration), encoding="utf-8")
    monkeypatch.setattr(dsp_file, "skill_folder", lambda _project=None: skill)
    return skill


# ---- which files the method reads ---------------------------------------------------------------


def _item_13(text: str) -> str:
    return re.search(r"^## 13\..*?(?=^## 14\.)", text, re.S | re.M).group(0)


def _named_files(section: str) -> set[str]:
    """Every saved-file extension item 13 names in code: `.pct6`, `.PR15`, `.PR<number>` — a dotted
    word with a model number or a placeholder in it. A field's suffix (`.type`, `.f`, `.q`) has
    neither; an extension with neither would pass here unseen, which item 15's declaration ends."""
    found = re.findall(r"`(\.[A-Za-z][A-Za-z0-9]*(?:<[a-z]+>)?)`", section)
    return {name for name in found if re.search(r"\d|<", name)}


def _unlisted(section: str) -> set[str]:
    sample = {name: re.sub(r"<[a-z]+>", "15", name) for name in _named_files(section)}
    return {name for name, as_file in sample.items()
            if not any(reader.matches(f"preset{as_file}") for reader in dsp_file.FALLBACK)}


def test_the_fallback_table_holds_every_file_contract_item_13_names():
    section = _item_13(CONTRACT.read_text(encoding="utf-8"))
    named = _named_files(section)
    assert ".pct6" in named and ".PR15" in named, named
    assert _unlisted(section) == set(), "item 13 names a file TCC's fallback table lacks"


def test_the_contract_check_goes_red_on_a_file_the_table_lacks():
    """Green by design, so shown failing."""
    section = "## 13. compare-file\nA saved `.pct6`, a `.PR15`, and now a `.DSP8` too.\n## 14."
    assert _unlisted(_item_13(section)) == {".DSP8"}


def test_a_pin_without_the_declaration_answers_with_the_fallback():
    assert not (vendor_loader._SUBMODULE_DIR / dsp_file.DECLARATION).exists(), "the pin carries it: drop FALLBACK"
    assert dsp_file.readers() == dsp_file.FALLBACK
    helix, mosconi = dsp_file.reader_for(HELIX), dsp_file.reader_for(MOSCONI)
    assert helix.reads(dsp_file.COMPARE) and helix.reads(dsp_file.ATTEST)
    assert mosconi.reads(dsp_file.COMPARE) and not mosconi.reads(dsp_file.ATTEST), "v3.3.2 refuses a .PR there"


def test_the_declaration_is_read_when_the_pin_carries_it(monkeypatch, tmp_path):
    declare(monkeypatch, tmp_path)
    mosconi = dsp_file.reader_for(MOSCONI)
    assert mosconi.source == "declared" and mosconi.reads(dsp_file.ATTEST)
    assert mosconi.matches("x.PR15") and mosconi.matches("x.pr7") and not mosconi.matches("x.pct6")


def test_a_reader_the_method_declares_turns_its_dsp_on_with_no_change_of_tcc(monkeypatch, tmp_path):
    """The rule is a capability, not a vendor: a family TCC has never heard of."""
    assert dsp_file.reader_for(OTHER) is None
    declared = dict(DECLARATION, readers=[*DECLARATION["readers"], {
        "id": "musway", "family": "Musway", "pattern": ".mwp", "verbs": ["compare-file"], "models": []}])
    declare(monkeypatch, tmp_path, declared)
    assert dsp_file.reader_for(OTHER).pattern == ".mwp"


def test_a_declaration_tcc_cannot_read_falls_back_to_the_table(monkeypatch, tmp_path):
    declare(monkeypatch, tmp_path, {"contract": "readers.v9", "readers": []})
    assert dsp_file.readers() == dsp_file.FALLBACK


@pytest.mark.parametrize("profile", [HELIX, HELIX_BRAND, MOSCONI, MOSCONI_OTHER,
                                     {"dsp_profile": {"vendor": "Audiotec-Fischer", "name": "DSP Mini MK2"}}])
def test_every_model_of_a_listed_family_has_its_reader(profile):
    """Advice, not a gate: another model is read at the person's own risk, and the method says so."""
    assert dsp_file.reader_for(profile) is not None


@pytest.mark.parametrize("profile", [OTHER, {"dsp_profile": {"vendor": "Moscow Audio", "name": "X"}}, {}, None])
def test_a_dsp_of_no_listed_family_has_none(profile):
    assert dsp_file.reader_for(profile) is None


# ---- what compare-file answered ---------------------------------------------------------------


def _answer(rows=(), code=0, **top):
    data = {"contract": "compare-file.v1", "warning": "Read at your own risk.", "device": {"name": "PICO"},
            "checked_model": False, "file": {"name": "a.PR15", "md5": "ab" * 16, "saved": None, "pctool": None},
            "counts": {"result": {"match": 1, "differs": 1, "unknown": 1}}, "rows": list(rows)}
    data.update(top)
    return json.dumps(data)


def _r(channel, parameter, result, category="audio", reason=None, journal=1.0, file=1.0):
    return {"parameter": parameter, "channel": channel, "journal": journal, "file": file, "result": result,
            "category": category, "reason": reason, "path": None}


def _refusal(kind="container", message="not a known container", **top):
    data = {"contract": "compare-file.v1", "warning": "Read at your own risk.",
            "file": {"name": "a.pct6", "md5": None, "saved": None, "pctool": None},
            "error": {"kind": kind, "message": message}}
    data.update(top)
    return json.dumps(data)


def test_sound_rows_come_first_and_each_category_stands_apart():
    rows = [_r("preset", "fx.realcenter", "match", "system"), _r("w-L", "gain_db", "differs"),
            _r("preset", "name", "unknown", "naming"), _r("m-L", "ta_ms", "match")]
    answer = dsp_file.interpret(0, _answer(rows), "")
    assert answer.kind == "compared"
    assert [(r.category, r.channel) for r in answer.rows] == [
        ("audio", "w-L"), ("audio", "m-L"), ("system", "preset"), ("naming", "preset")]


def test_a_result_the_contract_does_not_name_is_unknown_never_a_match():
    answer = dsp_file.interpret(0, _answer([_r("w-L", "gain_db", "ok"), _r("w-L", "mute", None)]), "")
    assert [r.result for r in answer.rows] == ["unknown", "unknown"]


@pytest.mark.parametrize("code, kind", [(1, "journal"), (2, "container"), (2, "interpret"), (3, "changed")])
def test_a_refusal_is_the_method_s_and_carries_no_rows(code, kind):
    out = _refusal(kind, "said by the method", rows=[_r("w-L", "gain_db", "match")])
    answer = dsp_file.interpret(code, out, "error: …")
    assert answer.kind == "refused" and answer.code == code and answer.rows == ()
    assert answer.error_kind == kind and answer.message == "said by the method"
    assert answer.warning == "Read at your own risk.", "the warning on a refusal too"


def test_usage_is_exit_2_with_nothing_on_stdout_and_said_from_stderr():
    answer = dsp_file.interpret(2, "", "usage: apply.py <project-dir> compare-file …")
    assert answer.kind == "refused" and answer.error_kind == "usage"
    assert "usage: apply.py" in answer.message


@pytest.mark.parametrize("code, out", [(5, _answer()), (0, "not json"), (0, json.dumps({"contract": "x"})),
                                       (0, ""), (75, "")])
def test_an_answer_that_is_not_the_contract_s_is_failed_never_a_result(code, out):
    answer = dsp_file.interpret(code, out, "Traceback … boom")
    assert answer.kind == "failed" and answer.rows == ()


def test_the_comparison_runs_the_method_s_compare_file_read_only(monkeypatch, tmp_path):
    seen = {}

    def spawn(project, script, args, **kw):
        seen.update(project=project, script=script, args=list(args), **kw)
        return 0, _answer(), ""

    monkeypatch.setattr(method_cli, "spawn", spawn)
    answer = dsp_file.compare(tmp_path, "v_007", "/files/a.PR15", "FULL")
    assert answer.kind == "compared"
    assert seen["script"] == "state/apply.py"
    assert seen["args"] == [str(tmp_path), "compare-file", "v_007", "/files/a.PR15", "--json", "--preset", "FULL"]
    assert seen["lock"] is False and seen["holds"] == 0


def test_a_method_tcc_will_not_run_is_said_not_raised(monkeypatch, tmp_path):
    def refused(*_a, **_k):
        raise method_cli.Refused("this project's method is not one TCC runs")

    monkeypatch.setattr(method_cli, "spawn", refused)
    answer = dsp_file.compare(tmp_path, "v_001", "a.pct6")
    assert answer.kind == "failed" and "not one TCC runs" in answer.message


# ---- the real method on the files it ships ----------------------------------------------------


def _real_project(tmp_path):
    project = tmp_path / "project"
    _intake.seed(project)
    files = tmp_path / "files"
    files.mkdir()
    return project, files


def _folder_state(folder: Path) -> dict:
    return {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir())}


@pytest.mark.parametrize("sample, checked", [(AYA, True), (PR15, False)], ids=["pct6", "PR15"])
def test_the_real_compare_file_reads_a_shipped_file_and_writes_nothing_beside_it(tmp_path, sample, checked):
    if not sample.is_file():
        pytest.skip(f"the vendored method ships no {sample.name}")
    project, files = _real_project(tmp_path)
    path = files / sample.name
    shutil.copyfile(sample, path)
    before = _folder_state(files)

    answer = dsp_file.compare(project, "v_001", path, "FULL")

    assert answer.kind == "compared", answer
    assert answer.checked_model is checked and answer.warning
    assert answer.file_name == sample.name and answer.md5 == before[sample.name]
    assert answer.rows and all(r.result in dsp_file.RESULTS for r in answer.rows)
    assert all(r.result == "unknown" for r in answer.rows), "the seed gives its channel no slot"
    assert _folder_state(files) == before, "nothing beside the file, and the file as it was"


def test_the_real_method_refuses_a_file_it_cannot_read_and_a_version_not_there(tmp_path):
    project, files = _real_project(tmp_path)
    bad = files / "bad.pct6"
    bad.write_bytes(b"not a preset")
    refused = dsp_file.compare(project, "v_001", bad, "FULL")
    assert (refused.kind, refused.code, refused.error_kind) == ("refused", 2, "container")
    assert refused.warning

    missing = dsp_file.compare(project, "v_999", bad, "FULL")
    assert (missing.kind, missing.code, missing.error_kind) == ("refused", 1, "journal")


# ---- the button and the table -----------------------------------------------------------------


class _Host(QWidget):
    """What `FileCheck` reads of the window: its DSP section, the slot, the version looked at."""

    def __init__(self, project: Path) -> None:
        super().__init__()
        self._built_on = project
        self._loaded_preset = "FULL"
        self._shown_key = None
        self._dsp_section = SidebarSection("dsp", "DSP", QSettings(), default_collapsed=False)


#: Every host a test builds, held to the end of the run as the window tests hold theirs
#: (`_KEEP_WINDOWS`): a finished worker's thread collected with its host between tests is the
#: collector freeing a QThread at a moment nobody chose (`conftest._collect_qt_leftovers`).
_KEEP: list = []


def _check(tmp_path, profile=HELIX, version="v_001"):
    _app()
    i18n.set_language("en")
    host = _Host(tmp_path)
    check = dsp_file_check.FileCheck(host)
    _KEEP.append((host, check))
    check.sync(SimpleNamespace(version=version, file_version=None, preset="FULL"), profile)
    return host, check


def _run(check, path="/files/a.PR15"):
    check.start(path)
    worker = check.running()
    assert worker is not None
    assert worker.wait(10000)
    for _ in range(5):
        QApplication.processEvents()
    return check.dialog


def _fake(monkeypatch, code=0, out=None, err="", seen=None):
    def spawn(project, script, args, **kw):
        if seen is not None:
            seen.append(list(args))
        return code, _answer() if out is None else out, err

    monkeypatch.setattr(method_cli, "spawn", spawn)


@pytest.mark.parametrize("profile", [HELIX, MOSCONI, MOSCONI_OTHER])
def test_the_button_is_on_for_a_dsp_whose_file_the_method_reads(tmp_path, profile):
    host, check = _check(tmp_path, profile)
    assert host._dsp_section.findChildren(type(check.button)).count(check.button) == 1, "in the DSP header"
    assert not check.button.isHidden() and check.button.isEnabled()
    assert check.button.text() == i18n.t("dspFileCheck")


def test_the_button_is_off_for_any_other_dsp_and_its_hover_says_why(tmp_path):
    _host, check = _check(tmp_path, OTHER)
    assert not check.button.isHidden() and not check.button.isEnabled()
    said = check.tip.text()
    assert "cannot read this DSP's saved file" in said and ".pct6" in said and ".PR<n>" in said


def test_no_version_or_another_version_looked_at_hides_it(tmp_path):
    host, check = _check(tmp_path, HELIX, version=None)
    assert check.button.isHidden()
    host._shown_key = "v_002"
    check.sync(SimpleNamespace(version="v_003", file_version=None, preset="FULL"), HELIX)
    assert check.button.isHidden()


def test_mosconi_on_a_pin_that_does_not_record_its_comparison_says_why_there_is_no_mark(tmp_path, monkeypatch):
    _host, check = _check(tmp_path, MOSCONI)
    assert i18n.t("dspFileCheckNoMarkTip") in check.tip.text()
    _host, helix = _check(tmp_path, HELIX)
    assert i18n.t("dspFileCheckNoMarkTip") not in helix.tip.text()

    declare(monkeypatch, tmp_path)
    check.sync(SimpleNamespace(version="v_001", file_version=None, preset="FULL"), MOSCONI)
    assert i18n.t("dspFileCheckNoMarkTip") not in check.tip.text(), "v3.3.3 records it: the mark works"


def test_a_click_asks_for_the_file_and_compares_the_version_on_screen_with_it(tmp_path, monkeypatch):
    seen = []
    _fake(monkeypatch, seen=seen)
    asked = {}

    def pick(parent, title, folder, filters):
        asked.update(folder=folder, filters=filters)
        return "/files/a.PR15", ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(pick))
    _host, check = _check(tmp_path, MOSCONI, version="v_004")
    check.pick()
    assert check.running().wait(10000)
    for _ in range(5):
        QApplication.processEvents()
    assert seen == [[str(tmp_path), "compare-file", "v_004", "/files/a.PR15", "--json", "--preset", "FULL"]]
    assert "*.PR*" in asked["filters"] and asked["folder"] == str(tmp_path)
    assert check.dialog is not None and check.dialog.table is not None
    assert check.button.isEnabled(), "on again once the answer is in"


def test_no_file_chosen_runs_nothing(tmp_path, monkeypatch):
    seen = []
    _fake(monkeypatch, seen=seen)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *_a: ("", "")))
    _host, check = _check(tmp_path)
    check.pick()
    assert seen == [] and check.running() is None and check.dialog is None


def _cells(table):
    return [[table.item(r, c).text() if table.item(r, c) else "" for c in range(table.columnCount())]
            for r in range(table.rowCount())]


def test_the_table_shows_parameter_journal_file_result_sound_first_and_unknown_never_as_match(tmp_path, monkeypatch):
    rows = [_r("preset", "fx.realcenter", "match", "system", journal=True, file=True),
            _r("w-L", "gain_db", "differs", journal=-3.0, file=-3.5),
            _r("w-L", "phase_deg", "unknown", reason="no phase control", journal=None, file=None)]
    _fake(monkeypatch, out=_answer(rows))
    _host, check = _check(tmp_path, MOSCONI)
    table = _run(check).table
    headers = [table.horizontalHeaderItem(c).text() for c in range(4)]
    assert headers == ["Parameter", "Journal", "File", "Result"]
    assert _cells(table) == [
        ["Sound", "", "", ""],
        ["w-L gain_db", "-3.0", "-3.5", "differs"],
        ["w-L phase_deg", "—", "—", "unknown: no phase control"],
        ["System", "", "", ""],
        ["preset fx.realcenter", "true", "true", "match"],
    ]
    assert check.dialog.counts_label.text() == "1 match · 1 differ · 1 unknown"


@pytest.mark.parametrize("code, out, err", [
    (0, None, ""), (1, _refusal("journal", "no version 'v_009'"), ""), (2, _refusal(), ""),
    (3, _refusal("changed", "hash moved"), ""),
], ids=["compared", "journal", "file", "changed"])
def test_the_method_s_warning_is_shown_with_every_result_and_every_refusal(tmp_path, monkeypatch, code, out, err):
    _fake(monkeypatch, code=code, out=out, err=err)
    _host, check = _check(tmp_path, MOSCONI)
    dialog = _run(check)
    assert dialog.warning_label.text() == "Read at your own risk." and not dialog.warning_label.isHidden()


def test_the_ukrainian_window_shows_warning_uk_where_the_method_gives_one(tmp_path, monkeypatch):
    _fake(monkeypatch, out=_answer(warning_uk="На свій ризик."))
    _host, check = _check(tmp_path, MOSCONI)
    try:
        i18n.set_language("uk")
        assert _run(check).warning_label.text() == "На свій ризик."
        i18n.set_language("en")
        assert _run(check).warning_label.text() == "Read at your own risk.", "English: the English"
        _fake(monkeypatch, out=_answer())
        i18n.set_language("uk")
        assert _run(check).warning_label.text() == "Read at your own risk.", "v3.3.2 gives none: the English"
    finally:
        i18n.set_language("en")


def test_a_model_the_method_was_not_checked_on_says_so_above_the_table(tmp_path, monkeypatch):
    _fake(monkeypatch, out=_answer(checked_model=False))
    _host, check = _check(tmp_path, MOSCONI)
    dialog = _run(check)
    layout = dialog.layout()
    order = [layout.itemAt(i).widget() for i in range(layout.count())]
    assert dialog.risk_label.text() == i18n.t("dspFileCheckRisk") and not dialog.risk_label.isHidden()
    assert order.index(dialog.risk_label) < order.index(dialog.table)

    _fake(monkeypatch, out=_answer(checked_model=True))
    assert _run(check).risk_label.isHidden(), "a checked model has no such line"


def test_a_file_that_changed_while_it_was_read_is_a_refusal_never_a_result(tmp_path, monkeypatch):
    _fake(monkeypatch, code=3, out=_refusal("changed", "the hash moved", rows=[_r("w-L", "gain_db", "match")]))
    _host, check = _check(tmp_path, HELIX)
    dialog = _run(check)
    assert dialog.table is None and dialog.counts_label.isHidden()
    assert "changed while it was read" in dialog.refusal_label.text() and "the hash moved" in dialog.refusal_label.text()


@pytest.mark.parametrize("code, out, err, said", [
    (1, _refusal("journal", "no version 'v_009'"), "", "the journal refused. no version 'v_009'"),
    (2, _refusal("container", "not a known container"), "", "could not be read (container). not a known container"),
    (2, "", "usage: apply.py <project-dir> compare-file", "(usage). usage: apply.py"),
    (9, "", "Traceback: boom", "no answer TCC can read. Traceback: boom"),
], ids=["journal", "file", "usage", "failed"])
def test_a_refusal_is_shown_as_the_method_gives_it(tmp_path, monkeypatch, code, out, err, said):
    _fake(monkeypatch, code=code, out=out, err=err)
    _host, check = _check(tmp_path, HELIX)
    dialog = _run(check)
    assert dialog.table is None
    assert said in dialog.refusal_label.text()


def test_the_real_method_through_the_button(tmp_path):
    """No fake: the vendored `state/apply.py` reads the shipped `.pct6` from the button's worker."""
    project, files = _real_project(tmp_path)
    path = files / AYA.name
    shutil.copyfile(AYA, path)
    _app()
    i18n.set_language("en")
    host = _Host(project)
    check = dsp_file_check.FileCheck(host)
    _KEEP.append((host, check))
    check.sync(SimpleNamespace(version="v_001", file_version=None, preset="FULL"), HELIX)
    dialog = _run(check, str(path))
    assert dialog.table is not None and dialog.table.rowCount() > 1
    assert dialog.table.item(0, 0).text() == "Sound"
    assert dialog.warning_label.text().startswith("Reading .pct6")
    assert dialog.risk_label.isHidden(), "AYA's HELIX DSP ULTRA S is a checked model"
    marks = {dialog.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in range(dialog.table.rowCount())}
    assert marks == {"heading", "unknown"}, "the seed gives its channel no slot: no row is a match"


# ---- the review's fix round (#272) --------------------------------------------------------------


@pytest.mark.parametrize("broken", [
    {"models": 1}, {"verbs": "compare-file"}, {"family": 7}, {"pattern": None},
], ids=["models", "verbs", "family", "pattern"])
def test_a_declaration_with_a_field_of_the_wrong_type_is_unreadable_and_the_table_answers(
        monkeypatch, tmp_path, broken):
    readers = [dict(DECLARATION["readers"][0], **broken), DECLARATION["readers"][1]]
    declare(monkeypatch, tmp_path, dict(DECLARATION, readers=readers))
    assert dsp_file.readers() == dsp_file.FALLBACK
    _host, check = _check(tmp_path, HELIX)
    assert check.button.isEnabled() and ".pct6" in check.tip.text()


@pytest.mark.parametrize("rows", ["many", [1, _r("w-L", "gain_db", "match")], {"a": 1}],
                         ids=["text", "a-number-row", "an-object"])
def test_rows_off_the_contract_are_a_failure_never_a_table_that_disagrees_with_its_counts(rows):
    answer = dsp_file.interpret(0, json.dumps(dict(json.loads(_answer()), rows=rows)), "")
    assert answer.kind == "failed" and answer.rows == ()
    assert "rows" in answer.message


def test_a_refusal_with_no_message_says_what_stderr_said():
    answer = dsp_file.interpret(2, _refusal("container", ""), "error: a.pct6: container: no zlib stream")
    assert answer.kind == "refused" and "no zlib stream" in answer.message


def test_the_dialog_a_new_check_replaces_is_deleted_not_kept(tmp_path, monkeypatch):
    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent

    _fake(monkeypatch)
    _host, check = _check(tmp_path, MOSCONI)
    first = _run(check)
    second = _run(check)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(first), "one dialog per check stayed alive"
    assert shiboken6.isValid(second) and check.dialog is second

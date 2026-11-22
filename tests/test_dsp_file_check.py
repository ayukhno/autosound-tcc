"""«Перевірити налаштування» (#272): which DSP files the method reads, what its `compare-file` answered,
and the button and table the person sees. The method is faked on `method_cli.spawn` where a case needs
an answer its shipped files do not give, and run for real on the files it ships: the pin's own
`readers.json`, `warning_uk`, and both `--from-file` verbs on a `.pct6` and a `.PR15`."""

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

#: The method's v3.3.3 declaration (`knowledge/dsp/readers.json`, CONTRACT.md item 15), the base of
#: the copies the tests declare: held to the pin's own below, `about` aside.
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


def compare_only(monkeypatch, tmp_path) -> Path:
    """A copy whose Mosconi reader compares and records nothing, as v3.3.2's did: no mark, no save."""
    mosconi = dict(DECLARATION["readers"][1], verbs=["compare-file"])
    return declare(monkeypatch, tmp_path, dict(DECLARATION, readers=[DECLARATION["readers"][0], mosconi]))


def _pinned() -> tuple:
    """The readers the pinned copy declares: the real `readers.json`, read as TCC reads it."""
    found = dsp_file.declared(vendor_loader._SUBMODULE_DIR)
    assert found is not None, f"the pinned method ({_pinned_version()}) declares no readers TCC reads"
    return found


def _pinned_version() -> str:
    """The pinned method's version, for a skip's reason: its plugin manifest, or the folder."""
    try:
        manifest = vendor_loader._SUBMODULE_DIR.parents[1] / ".claude-plugin" / "plugin.json"
        return "v" + json.loads(manifest.read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return str(vendor_loader._SUBMODULE_DIR)


# ---- which files the method reads ---------------------------------------------------------------


def _item_13(text: str) -> str:
    return re.search(r"^## 13\..*?(?=^## 14\.)", text, re.S | re.M).group(0)


def _named_files(section: str) -> set[str]:
    """Every saved-file extension item 13 names in code: `.pct6`, `.PR15`, `.PR<number>` — a dotted
    word with a model number or a placeholder in it. A field's suffix (`.type`, `.f`, `.q`) has
    neither; an extension with neither would pass here unseen, which item 15's declaration ends."""
    found = re.findall(r"`(\.[A-Za-z][A-Za-z0-9]*(?:<[a-z]+>)?)`", section)
    return {name for name in found if re.search(r"\d|<", name)}


def _unlisted(section: str, found) -> set[str]:
    sample = {name: re.sub(r"<[a-z]+>", "15", name) for name in _named_files(section)}
    return {name for name, as_file in sample.items()
            if not any(reader.matches(f"preset{as_file}") for reader in found)}


def test_the_pinned_declaration_holds_every_file_contract_item_13_names():
    section = _item_13(CONTRACT.read_text(encoding="utf-8"))
    named = _named_files(section)
    assert ".pct6" in named and ".PR15" in named, named
    assert _unlisted(section, _pinned()) == set(), "item 13 names a file the pin's readers.json lacks"


def test_the_contract_check_goes_red_on_a_file_the_declaration_lacks():
    """Green by design, so shown failing."""
    section = "## 13. compare-file\nA saved `.pct6`, a `.PR15`, and now a `.DSP8` too.\n## 14."
    assert _unlisted(_item_13(section), _pinned()) == {".DSP8"}


def test_the_pin_declares_both_families_and_every_verb_on_each():
    """v3.3.3 (hub #348-#350): TCC's own copy answers from its `readers.json`, and both readers
    compare, record and bank from their file."""
    assert (vendor_loader._SUBMODULE_DIR / dsp_file.DECLARATION).is_file()
    assert dsp_file.readers() == _pinned()
    for profile in (HELIX, MOSCONI):
        reader = dsp_file.reader_for(profile)
        assert reader is not None and all(reader.reads(verb) for verb in dsp_file.KNOWN_VERBS), reader


def test_the_tests_declaration_is_the_pinned_one():
    """The copies the tests declare are built on `DECLARATION`: it says what the pin says."""
    pinned = json.loads((vendor_loader._SUBMODULE_DIR / dsp_file.DECLARATION).read_text(encoding="utf-8"))
    assert {k: v for k, v in pinned.items() if k != "about"} == {
        k: v for k, v in DECLARATION.items() if k != "about"}


def test_the_declaration_is_read_from_the_copy_tcc_is_given(monkeypatch, tmp_path):
    declare(monkeypatch, tmp_path)
    mosconi = dsp_file.reader_for(MOSCONI)
    assert mosconi.reads(dsp_file.ATTEST)
    assert mosconi.matches("x.PR15") and mosconi.matches("x.pr7") and not mosconi.matches("x.pct6")


def test_a_reader_the_method_declares_turns_its_dsp_on_with_no_change_of_tcc(monkeypatch, tmp_path):
    """The rule is a capability, not a vendor: a family TCC has never heard of."""
    assert dsp_file.reader_for(OTHER) is None
    declared = dict(DECLARATION, readers=[*DECLARATION["readers"], {
        "id": "musway", "family": "Musway", "pattern": ".mwp", "verbs": ["compare-file"], "models": []}])
    declare(monkeypatch, tmp_path, declared)
    assert dsp_file.reader_for(OTHER).pattern == ".mwp"


def test_a_declaration_tcc_cannot_read_is_no_reader(monkeypatch, tmp_path):
    declare(monkeypatch, tmp_path, {"contract": "readers.v9", "readers": []})
    assert dsp_file.readers() == ()
    assert dsp_file.reader_for(HELIX) is None and dsp_file.reader_for(MOSCONI) is None


def test_a_copy_that_declares_nothing_has_no_reader(monkeypatch, tmp_path):
    """No `readers.json` (a copy before v3.3.3): TCC keeps no table of its own (#272, «Decided»)."""
    bare = tmp_path / "skill"
    bare.mkdir()
    monkeypatch.setattr(dsp_file, "skill_folder", lambda _project=None: bare)
    assert dsp_file.readers() == ()
    assert dsp_file.reader_for(HELIX) is None and dsp_file.reader_for(MOSCONI) is None


def test_declaration_edges_are_said_in_the_log_and_change_nothing(monkeypatch, tmp_path, caplog):
    """A verb TCC does not know, a declaration of no reader: one warning each, the answer as before."""
    import logging

    odd = dict(DECLARATION, readers=[dict(DECLARATION["readers"][0], verbs=["compare-file", "rate-file"])])
    with caplog.at_level(logging.WARNING, logger="autosound_tcc"):
        declare(monkeypatch, tmp_path / "a", odd)
        assert dsp_file.reader_for(HELIX).verbs == ("compare-file", "rate-file")
        declare(monkeypatch, tmp_path / "b", dict(DECLARATION, readers=[]))
        assert dsp_file.readers() == ()
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "rate-file" in said and "declares no reader" in said, said


def test_a_declaration_that_cannot_be_looked_at_is_said_once(monkeypatch, tmp_path, caplog):
    import logging

    skill = declare(monkeypatch, tmp_path)
    path = skill / dsp_file.DECLARATION
    real_stat = Path.stat

    def stat(self, *a, **k):
        if self == path:
            raise PermissionError(13, "Permission denied", str(path))
        return real_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", stat)
    with caplog.at_level(logging.WARNING, logger="autosound_tcc"):
        assert dsp_file.readers() == ()
        assert dsp_file.readers() == ()
    said = [r.getMessage() for r in caplog.records if "Permission denied" in r.getMessage()]
    assert len(said) == 1, said


@pytest.mark.parametrize("profile", [HELIX, HELIX_BRAND, MOSCONI, MOSCONI_OTHER,
                                     {"dsp_profile": {"vendor": "Audiotec-Fischer", "name": "DSP Mini MK2"}},
                                     {"dsp_profile": {"vendor": "HelixDSP", "name": "Ultra"}}])
def test_every_model_of_a_listed_family_has_its_reader(profile):
    """Advice, not a gate: another model is read at the person's own risk, and the method says so."""
    assert dsp_file.reader_for(profile) is not None


@pytest.mark.parametrize("profile", [OTHER, {"dsp_profile": {"vendor": "Moscow Audio", "name": "X"}}, {}, None])
def test_a_dsp_of_no_listed_family_has_none(profile):
    assert dsp_file.reader_for(profile) is None


# ---- what compare-file answered ---------------------------------------------------------------


def _answer(rows=(), code=0, **top):
    """compare-file's answer; its counts are the rows' unless a test gives its own."""
    rows = list(rows)
    said = [(row.get("result") if row.get("result") in dsp_file.RESULTS else "unknown")
            for row in rows if isinstance(row, dict)]
    counts = {key: said.count(key) for key in dsp_file.RESULTS}
    data = {"contract": "compare-file.v1", "warning": "Read at your own risk.", "device": {"name": "PICO"},
            "checked_model": False, "file": {"name": "a.PR15", "md5": "ab" * 16, "saved": None, "pctool": None},
            "counts": {"result": counts}, "rows": rows}
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
    assert answer.kind == "not_run" and "not one TCC runs" in answer.message


@pytest.mark.parametrize("raised, kind, said", [
    (method_cli.Busy("busy: /p/.autosound/write.lock is held by another writer"), "busy", "another writer"),
    (method_cli.TimedOut("apply.py timed out after 60s", 60.0), "timed_out", "No answer in time"),
    (method_cli.ScriptMissing("apply.py not found at /m"), "not_run", "was not run"),
], ids=["busy", "timed-out", "script-missing"])
def test_a_comparison_the_launcher_answered_is_told_apart(monkeypatch, tmp_path, raised, kind, said):
    def spawn(*_a, **_k):
        raise raised

    monkeypatch.setattr(method_cli, "spawn", spawn)
    answer = dsp_file.compare(tmp_path, "v_001", "a.pct6")
    assert answer.kind == kind and answer.message == str(raised) and answer.rows == ()
    assert said in dsp_file_check.refusal_sentence(answer) and str(raised) in dsp_file_check.refusal_sentence(answer)


def test_counts_missing_are_counted_from_the_rows():
    rows = [_r("w-L", "gain_db", "differs"), _r("w-L", "mute", "match"), _r("w-L", "ta_ms", "differs")]
    for counts in (None, {"result": "many"}, {"other": 1}):
        answer = dsp_file.interpret(0, _answer(rows, counts=counts), "")
        assert answer.kind == "compared" and answer.counts == {"match": 1, "differs": 2, "unknown": 0}, counts


def test_counts_that_disagree_with_the_rows_are_a_failure_never_a_table():
    rows = [_r("w-L", "gain_db", "differs")]
    answer = dsp_file.interpret(0, _answer(rows, counts={"result": {"match": 1, "differs": 0, "unknown": 0}}), "")
    assert answer.kind == "failed" and answer.rows == () and "counts" in answer.message


# ---- the real method on the files it ships ----------------------------------------------------


def _real_project(tmp_path):
    project = tmp_path / "project"
    _intake.seed(project)
    files = tmp_path / "files"
    files.mkdir()
    return project, files


def _folder_state(folder: Path) -> dict:
    return {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir())}


def _tree_state(folder: Path) -> dict:
    """Every file under `folder`, by its path there, and its md5."""
    return {p.relative_to(folder).as_posix(): hashlib.md5(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("sample, checked", [(AYA, True), (PR15, False)], ids=["pct6", "PR15"])
def test_the_real_compare_file_reads_a_shipped_file_and_writes_nothing_beside_it(tmp_path, sample, checked):
    project, files = _real_project(tmp_path)
    path = files / sample.name
    shutil.copyfile(sample, path)
    before = _folder_state(files)
    journal = _tree_state(project / "state")

    answer = dsp_file.compare(project, "v_001", path, "FULL")

    assert answer.kind == "compared", answer
    assert answer.checked_model is checked and answer.warning
    assert answer.warning_uk and answer.warning_uk != answer.warning, "v3.3.3 says it in Ukrainian too"
    assert answer.file_name == sample.name and answer.md5 == before[sample.name]
    assert answer.rows and all(r.result in dsp_file.RESULTS for r in answer.rows)
    assert all(r.result == "unknown" for r in answer.rows), "the seed gives its channel no slot"
    assert _folder_state(files) == before, "nothing beside the file, and the file as it was"
    assert _tree_state(project / "state") == journal, "item 13: nothing written into the journal"


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


def test_a_reader_that_does_not_record_its_comparison_says_why_there_is_no_mark(tmp_path, monkeypatch):
    compare_only(monkeypatch, tmp_path / "method")
    _host, check = _check(tmp_path, MOSCONI)
    assert i18n.t("dspFileCheckNoMarkTip") in check.tip.text()
    _host, helix = _check(tmp_path, HELIX)
    assert i18n.t("dspFileCheckNoMarkTip") not in helix.tip.text()

    monkeypatch.undo()
    check.sync(SimpleNamespace(version="v_001", file_version=None, preset="FULL"), MOSCONI)
    assert i18n.t("dspFileCheckNoMarkTip") not in check.tip.text(), "the pin records it: the mark works"


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
        assert _run(check).warning_label.text() == "Read at your own risk.", "none given: the English"
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
def test_a_declaration_with_a_field_of_the_wrong_type_is_unreadable_and_no_reader_answers(
        monkeypatch, tmp_path, broken):
    readers = [dict(DECLARATION["readers"][0], **broken), DECLARATION["readers"][1]]
    declare(monkeypatch, tmp_path, dict(DECLARATION, readers=readers))
    assert dsp_file.readers() == ()
    _host, check = _check(tmp_path, HELIX)
    assert not check.button.isEnabled() and check.tip.text() == i18n.t("dspFileCheckNoReadersTip")


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


# ---- «Зберегти як нову версію» (#273): propose --from-file from the comparison's result ----------

#: What `propose --from-file` printed on AYA.pct6 over the seeded project (v3.3.2), cut short: the
#: warning, the model line, the banked line, then the three lists under their own headings.
BANKED_OUT = """Reading .pct6 has been checked on HELIX DSP ULTRA S only. Any other model is read at your own risk.
model: HELIX DSP ULTRA S (Dev 39) -- checked

🟡 proposed v_002 on FULL, read from AYA.pct6
## APPLY THIS in Helix PC-Tool — FULL · v_002 (proposed)

Kept as v_001 has them -- the file does not give them (1):
  - w-L: project.json gives this channel no slot (every field kept)

Not taken from the file (1):
  - Output A: no name, muted: no row of this version is on this output

Taken short (1):
  - w-L hp: an all-pass invert"""


class _Saving(_Host):
    """A host that counts the window's re-read after a write of the method (`_reload_project_files`)."""

    def __init__(self, project: Path) -> None:
        super().__init__(project)
        self.reloads = 0

    def _reload_project_files(self) -> None:
        self.reloads += 1


def _saved_file(tmp_path, name="AYA.pct6", data=b"a saved preset") -> Path:
    path = tmp_path / "files" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(data)
    return path


def _differing(path: Path, rows=None, **top) -> str:
    """compare-file's answer for `path` as it is now: its md5, one row that differs."""
    rows = [_r("w-L", "gain_db", "differs", journal=-3.0, file=-3.5)] if rows is None else rows
    file = {"name": path.name, "md5": hashlib.md5(path.read_bytes()).hexdigest(), "saved": None, "pctool": None}
    return _answer(rows, file=file, **top)


def _method(monkeypatch, compared: str, saved=(0, BANKED_OUT, ""), calls=None):
    """`method_cli.spawn` faked by verb: compare-file answers `compared`, propose answers `saved` —
    a `(code, out, err)`, or an exception it raises."""

    def spawn(project, script, args, **kw):
        if calls is not None:
            calls.append((list(args), kw))
        if args[1] == "compare-file":
            return 0, compared, ""
        if isinstance(saved, BaseException):
            raise saved
        return saved

    monkeypatch.setattr(method_cli, "spawn", spawn)


def _head(project: Path, version="v_001", preset="FULL") -> None:
    """The journal's HEAD of `preset` on disk, as `slots.json` names it: what `propose` builds on."""
    state = project / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "slots.json").write_text(json.dumps({"layout": "project-numbered", "active": None,
                                                  "slots": {preset: {"version": version}}}), encoding="utf-8")


def _saving_check(tmp_path, profile=HELIX, version="v_001"):
    if not (tmp_path / "state" / "slots.json").is_file() and not (tmp_path / "state" / "FULL" / "HEAD").is_file():
        _head(tmp_path, version or "v_001")
    _app()
    i18n.set_language("en")
    host = _Saving(tmp_path)
    check = dsp_file_check.FileCheck(host)
    _KEEP.append((host, check))
    check.sync(SimpleNamespace(version=version, file_version=None, preset="FULL"), profile)
    return host, check


def _settle():
    for _ in range(5):
        QApplication.processEvents()


def _save(check):
    """Click «Зберегти як нову версію» and wait for the method's answer."""
    check.dialog.save_button.click()
    worker = check.saving()
    assert worker is not None
    assert worker.wait(10000)
    _settle()
    return check.dialog


@pytest.mark.parametrize("profile, banks, rows, offered", [
    (HELIX, True, None, True),
    (HELIX, True, [_r("w-L", "gain_db", "match"), _r("w-L", "mute", "unknown")], False),
    (MOSCONI, False, None, False),
    (MOSCONI, True, None, True),
    (MOSCONI_OTHER, True, None, True),
], ids=["helix-differs", "helix-no-difference", "mosconi-compare-only", "mosconi-declared", "mosconi-other-model"])
def test_the_save_is_offered_only_when_rows_differ_and_the_reader_banks_from_the_file(
        tmp_path, monkeypatch, profile, banks, rows, offered):
    if not banks:
        compare_only(monkeypatch, tmp_path / "method")
    path = _saved_file(tmp_path, "a.PR15" if profile is not HELIX else "AYA.pct6")
    _method(monkeypatch, _differing(path, rows))
    _host, check = _saving_check(tmp_path, profile)
    dialog = _run(check, str(path))
    if offered:
        assert dialog.save_button is not None and not dialog.save_button.isHidden()
        assert dialog.save_button.isEnabled() and dialog.save_button.text() == i18n.t("dspFileSave")
    else:
        assert dialog.save_button is None or dialog.save_button.isHidden()


@pytest.mark.parametrize("code, out", [(1, _refusal("journal", "no version")), (2, _refusal()),
                                       (3, _refusal("changed", "hash moved"))], ids=["1", "2", "3"])
def test_a_refused_comparison_offers_no_save(tmp_path, monkeypatch, code, out):
    def spawn(project, script, args, **kw):
        return code, out, ""

    monkeypatch.setattr(method_cli, "spawn", spawn)
    _host, check = _saving_check(tmp_path)
    dialog = _run(check, str(_saved_file(tmp_path)))
    assert dialog.save_button is None or dialog.save_button.isHidden()


def test_the_save_runs_propose_from_file_on_the_file_compared_under_the_method_s_writer_lock(tmp_path, monkeypatch):
    calls = []
    path = _saved_file(tmp_path)
    _method(monkeypatch, _differing(path), calls=calls)
    _host, check = _saving_check(tmp_path)
    _run(check, str(path))
    _save(check)
    args, kw = calls[-1]
    assert args == [str(tmp_path), "propose", "--from-file", str(path), "--preset", "FULL"]
    assert "--json" not in args, "propose --from-file has no --json: its text is shown as printed"
    assert "lock" in kw and "holds" in kw, "said, not left to spawn's defaults"
    assert kw["lock"] is True and kw["holds"] == 1, "the writer lock, one hold"
    assert kw.get("cross_process") is False, "TCC's thread lock around the method's own, as config_writer"
    assert "under_lock" not in kw


def test_a_banked_version_is_shown_with_what_the_method_kept_did_not_take_and_took_short(tmp_path, monkeypatch):
    path = _saved_file(tmp_path)
    _method(monkeypatch, _differing(path))
    _host, check = _saving_check(tmp_path)
    _run(check, str(path))
    dialog = _save(check)
    assert "v_002" in dialog.saved_label.text() and not dialog.saved_label.isHidden()
    said = dialog.saved_text.toPlainText()
    assert said == BANKED_OUT, "the method's text as it printed it"
    for heading in ("Kept as v_001 has them", "Not taken from the file", "Taken short"):
        assert heading in said
    assert said.startswith("Reading .pct6") and "model: HELIX DSP ULTRA S (Dev 39) -- checked" in said


@pytest.mark.parametrize("code, err, said", [
    (1, "error: --on v_009: no such version in slot 'FULL'", "the journal refused"),
    (2, "error: AYA.pct6: container: not a known container", "could not be read"),
    (2, "usage: apply.py <project-dir> propose …", "could not be read"),
    (3, "error: AYA.pct6: changed: the file changed while it was read", "changed while it was read"),
], ids=["journal", "file", "usage", "changed"])
def test_a_refusal_is_shown_in_the_method_s_words_and_nothing_is_banked_or_reloaded(
        tmp_path, monkeypatch, code, err, said):
    path = _saved_file(tmp_path)
    _method(monkeypatch, _differing(path), saved=(code, "", err))
    host, check = _saving_check(tmp_path)
    _run(check, str(path))
    dialog = _save(check)
    assert said in dialog.saved_label.text() and err in dialog.saved_label.text()
    assert "Nothing was saved" in dialog.saved_label.text()
    assert host.reloads == 0, "nothing banked: nothing to re-read"
    assert not dialog.save_button.isEnabled(), "the same read is not offered again"
    assert dialog.warning_label.text() == "Read at your own risk." and not dialog.warning_label.isHidden()


def test_a_journal_held_by_another_writer_is_said_and_nothing_destructive_offered(tmp_path, monkeypatch):
    path = _saved_file(tmp_path)
    busy = method_cli.Busy("busy: /p/.autosound/write.lock is held by another writer -- nothing was written, "
                           "safe to retry")
    _method(monkeypatch, _differing(path), saved=busy)
    host, check = _saving_check(tmp_path)
    _run(check, str(path))
    dialog = _save(check)
    text = dialog.saved_label.text()
    assert "another writer" in text and "held by another writer" in text and "Nothing was saved" in text
    assert host.reloads == 0
    assert dialog.save_button.isEnabled(), "nothing was written: the same save, once the writer is done"


def test_an_exit_the_contract_does_not_name_is_no_save(tmp_path, monkeypatch):
    path = _saved_file(tmp_path)
    _method(monkeypatch, _differing(path), saved=(9, "", "Traceback … boom"))
    _host, check = _saving_check(tmp_path)
    _run(check, str(path))
    dialog = _save(check)
    assert "no answer TCC can read" in dialog.saved_label.text() and "boom" in dialog.saved_label.text()


def test_a_timed_out_save_may_have_written_so_the_window_re_reads(tmp_path, monkeypatch):
    path = _saved_file(tmp_path)
    _method(monkeypatch, _differing(path), saved=method_cli.TimedOut("apply.py timed out after 120s", 120.0))
    host, check = _saving_check(tmp_path)
    _run(check, str(path))
    dialog = _save(check)
    assert "may have written" in dialog.saved_label.text()
    _settle()
    assert host.reloads == 1 and not dialog.save_button.isEnabled()


def test_a_banked_version_re_reads_the_window_as_a_method_write_does(tmp_path, monkeypatch):
    path = _saved_file(tmp_path)
    _method(monkeypatch, _differing(path))
    host, check = _saving_check(tmp_path)
    _run(check, str(path))
    _save(check)
    _settle()
    assert host.reloads == 1


def test_a_second_click_on_the_same_read_banks_nothing_more(tmp_path, monkeypatch):
    calls = []
    path = _saved_file(tmp_path)
    _method(monkeypatch, _differing(path), calls=calls)
    _host, check = _saving_check(tmp_path)
    _run(check, str(path))
    dialog = _save(check)
    assert not dialog.save_button.isEnabled()
    check.save()
    dialog.save_button.click()
    _settle()
    assert [args[1] for args, _kw in calls] == ["compare-file", "propose"], "one bank per read"

    _run(check, str(path))
    assert check.dialog is not dialog and check.dialog.save_button.isEnabled(), "a new read is a new offer"


def test_a_file_changed_since_it_was_compared_is_not_banked(tmp_path, monkeypatch):
    calls = []
    path = _saved_file(tmp_path)
    _method(monkeypatch, _differing(path), calls=calls)
    host, check = _saving_check(tmp_path)
    _run(check, str(path))
    path.write_bytes(b"saved again, other values")
    check.dialog.save_button.click()
    _settle()
    assert [args[1] for args, _kw in calls] == ["compare-file"], "the values shown are not the file's now"
    assert "changed since" in check.dialog.saved_label.text() and host.reloads == 0


def test_another_version_on_screen_since_the_comparison_is_not_banked(tmp_path, monkeypatch):
    calls = []
    path = _saved_file(tmp_path)
    _method(monkeypatch, _differing(path), calls=calls)
    _host, check = _saving_check(tmp_path)
    _run(check, str(path))
    check.sync(SimpleNamespace(version="v_002", file_version=None, preset="FULL"), HELIX)
    check.dialog.save_button.click()
    _settle()
    assert [args[1] for args, _kw in calls] == ["compare-file"]
    assert "changed since" in check.dialog.saved_label.text()


def test_a_journal_whose_head_moved_on_disk_since_the_comparison_is_not_banked(tmp_path, monkeypatch):
    """#273 review: a session banked v_002 between the comparison and the click, before the watcher
    re-read the window. The view still says v_001, and `propose` would build on v_002: the fields
    the file does not give would be kept from a version nobody compared."""
    calls = []
    path = _saved_file(tmp_path)
    _method(monkeypatch, _differing(path), calls=calls)
    _host, check = _saving_check(tmp_path)
    _run(check, str(path))
    _head(tmp_path, "v_002")
    check.dialog.save_button.click()
    _settle()
    assert [args[1] for args, _kw in calls] == ["compare-file"], "the journal's HEAD is not the version compared"
    assert check.dialog.saved.kind == "stale" and "changed since" in check.dialog.saved_label.text()
    assert not check.dialog.save_button.isEnabled()


def test_no_comparison_starts_while_a_save_runs(tmp_path, monkeypatch):
    import threading

    release = threading.Event()
    path = _saved_file(tmp_path)
    calls = []

    def spawn(project, script, args, **kw):
        calls.append(args[1])
        if args[1] == "compare-file":
            return 0, _differing(path), ""
        release.wait(20)
        return 0, BANKED_OUT, ""

    monkeypatch.setattr(method_cli, "spawn", spawn)
    _host, check = _saving_check(tmp_path)
    _run(check, str(path))
    first = check.running()
    check.dialog.save_button.click()
    worker = check.saving()
    try:
        assert not check.button.isEnabled() and not check.dialog.save_button.isEnabled()
        check.start(str(path))
        assert check.running() is first, "no new comparison while the save runs"
    finally:
        release.set()
        assert worker.wait(10000)
    _settle()
    assert calls == ["compare-file", "propose"]


def test_a_save_still_running_at_quit_is_handed_over_and_its_answer_opens_nothing(tmp_path, monkeypatch):
    import threading

    from autosound_tcc.ui.tcc import qt_shutdown

    release = threading.Event()
    path = _saved_file(tmp_path)

    def spawn(project, script, args, **kw):
        if args[1] == "compare-file":
            return 0, _differing(path), ""
        release.wait(20)
        return 0, BANKED_OUT, ""

    monkeypatch.setattr(method_cli, "spawn", spawn)
    monkeypatch.setattr(dsp_file_check, "STOP_WAIT_MS", 50)
    host, check = _saving_check(tmp_path)
    dialog = _run(check, str(path))
    dialog.save_button.click()
    worker = check.saving()
    try:
        assert worker.isRunning(), "held in the method's write until after stop()"
        check.stop()
        assert worker in qt_shutdown.detached(), "handed over, not left for Qt to destroy running"
        check.stop()  # twice is safe
    finally:
        release.set()
        assert worker.wait(10000)
    _settle()
    assert dialog.saved_label.isHidden() and host.reloads == 0, "nothing on a window on its way out"


# ---- the real method: propose --from-file on a copy of a project --------------------------------


def test_the_real_propose_from_file_banks_a_new_version_and_leaves_the_file_byte_identical(tmp_path):
    project, files = _real_project(tmp_path)
    path = files / AYA.name
    shutil.copyfile(AYA, path)
    before = path.read_bytes()
    versions = project / "state" / "versions"
    assert sorted(p.name for p in versions.iterdir()) == ["v_001.json"]

    saved = dsp_file.propose(project, path, "FULL")

    assert saved.kind == "banked" and saved.code == 0 and saved.version == "v_002", saved
    assert sorted(p.name for p in versions.iterdir()) == ["v_001.json", "v_002.json"]
    banked = json.loads((versions / "v_002.json").read_text(encoding="utf-8"))
    provenance = banked.get("provenance") or {}
    assert provenance.get("kind") == "pct6" and provenance.get("md5") == hashlib.md5(before).hexdigest(), provenance
    assert saved.text.startswith("Reading .pct6") and "model: HELIX DSP ULTRA S (Dev 39) -- checked" in saved.text
    assert "Kept as v_001 has them" in saved.text and "Not taken from the file" in saved.text
    assert path.read_bytes() == before, "the DSP's file is never written"
    assert sorted(p.name for p in files.iterdir()) == [AYA.name], "nothing beside it"


def test_the_real_propose_from_file_banks_a_new_version_from_a_mosconi_file(tmp_path):
    """Hub #349 (v3.3.3): `propose --from-file` banks from a `.PR15`, and the pin declares it."""
    assert dsp_file.reader_for(MOSCONI, found=_pinned()).reads(dsp_file.PROPOSE)
    project, files = _real_project(tmp_path)
    path = files / PR15.name
    shutil.copyfile(PR15, path)
    before = path.read_bytes()
    saved = dsp_file.propose(project, path, "FULL")
    assert saved.kind == "banked" and saved.version == "v_002", saved
    banked = json.loads((project / "state" / "versions" / "v_002.json").read_text(encoding="utf-8"))
    assert (banked.get("provenance") or {}).get("kind") == "pr15", banked.get("provenance")
    assert path.read_bytes() == before, "the DSP's file is never written"


def test_the_real_method_through_the_save_button(tmp_path, monkeypatch):
    """The comparison faked with a row that differs (the seed gives its channel no slot, so the
    real one has none); the save is the vendored `propose --from-file`, from the button's worker."""
    project, files = _real_project(tmp_path)
    path = files / AYA.name
    shutil.copyfile(AYA, path)
    before = path.read_bytes()
    real = method_cli.spawn

    def spawn(project_dir, script, args, **kw):
        if args[1] == "compare-file":
            return 0, _differing(path), ""
        return real(project_dir, script, args, **kw)

    monkeypatch.setattr(method_cli, "spawn", spawn)
    host, check = _saving_check(project)
    _run(check, str(path))
    dialog = _save(check)
    assert "v_002" in dialog.saved_label.text(), dialog.saved_label.text()
    assert "Not taken from the file" in dialog.saved_text.toPlainText()
    assert (project / "state" / "versions" / "v_002.json").is_file()
    assert path.read_bytes() == before
    _settle()
    assert host.reloads == 1 and not dialog.save_button.isEnabled()


# ---- the group review (#272, #273) --------------------------------------------------------------


def test_an_answer_that_comes_while_the_close_question_is_up_is_shown_when_the_window_stays(tmp_path, monkeypatch):
    """S1: the window sets `_closing` before its close questions and resets it on Cancel. A save's
    answer that came meanwhile was dropped: v_002 banked, the dialog «Saving…» for good, the
    method's lists never shown. Only `stop()` — the close decided — drops an answer."""
    path = _saved_file(tmp_path)
    _method(monkeypatch, _differing(path))
    host, check = _saving_check(tmp_path)
    host._closing = True
    dialog = _run(check, str(path))
    assert dialog is not None, "a comparison that came during the question is shown"
    dialog.save_button.click()
    assert check.saving().wait(10000)
    _settle()
    host._closing = False  # Cancel
    _settle()
    assert "v_002" in dialog.saved_label.text() and not dialog.saved_label.isHidden()
    assert dialog.save_button.text() == i18n.t("dspFileSave") and not dialog.save_button.isEnabled()
    assert host.reloads == 1


@pytest.mark.parametrize("head", [None, "unreadable"], ids=["no-preset-head", "raises"])
def test_a_journal_head_that_cannot_be_read_now_says_so_and_keeps_the_save(tmp_path, monkeypatch, head):
    """S3: an unreadable HEAD is no change of the file or the version: its own sentence, nothing
    run, and the save still offered."""
    calls = []
    path = _saved_file(tmp_path)
    _method(monkeypatch, _differing(path), calls=calls)
    _host, check = _saving_check(tmp_path)
    _run(check, str(path))
    if head is None:
        (tmp_path / "state" / "slots.json").write_text("{", encoding="utf-8")  # mid-rewrite
    else:
        def boom(*_a, **_k):
            raise OSError("the disk went away")

        monkeypatch.setattr(dsp_file.ledger_line, "line_mark", boom)
    check.dialog.save_button.click()
    _settle()
    assert [args[1] for args, _kw in calls] == ["compare-file"]
    assert check.dialog.saved.kind == "head_unread"
    assert check.dialog.saved_label.text() == i18n.t("dspFileSaveHeadUnread")
    assert check.dialog.save_button.isEnabled(), "nothing was run: the same save may go through"


def _old_layout(project: Path, head: str = "v_001", preset: str = "FULL") -> None:
    """The per-preset layout: `state/<preset>/HEAD`, no `slots.json`."""
    folder = project / "state" / preset
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "HEAD").write_text(head + "\n", encoding="utf-8")


def test_the_head_guard_reads_the_old_per_preset_layout_too(tmp_path, monkeypatch):
    """T2: on a ledger with `state/<preset>/HEAD`, the save goes through at HEAD and is stale once
    HEAD moves."""
    _old_layout(tmp_path)
    calls = []
    path = _saved_file(tmp_path)
    _method(monkeypatch, _differing(path), calls=calls)
    _host, check = _saving_check(tmp_path)
    assert not (tmp_path / "state" / "slots.json").exists()
    _run(check, str(path))
    _save(check)
    assert [args[1] for args, _kw in calls] == ["compare-file", "propose"]

    _run(check, str(path))
    _old_layout(tmp_path, "v_002")
    check.dialog.save_button.click()
    _settle()
    assert [args[1] for args, _kw in calls] == ["compare-file", "propose", "compare-file"]
    assert check.dialog.saved.kind == "stale"


def _declaring_copy(root: Path) -> Path:
    """A copy of the method that carries `readers.json` (v3.3.3's, as `DECLARATION`)."""
    from tests._method_copies import copy_of_the_method

    skill = copy_of_the_method(root)
    (skill / dsp_file.DECLARATION).parent.mkdir(parents=True, exist_ok=True)
    (skill / dsp_file.DECLARATION).write_text(json.dumps(DECLARATION), encoding="utf-8")
    return skill


def _bare_copy(root: Path) -> Path:
    """A copy of the method without `readers.json`, as every copy before v3.3.3 is."""
    from tests._method_copies import copy_of_the_method

    bare = copy_of_the_method(root)
    if (bare / dsp_file.DECLARATION).exists():
        (bare / dsp_file.DECLARATION).unlink()
    return bare


def test_the_declaration_is_read_from_the_project_s_bound_copy_not_tcc_s(tmp_path, monkeypatch):
    """T3: the project links a copy that declares its readers; TCC's own declares none."""
    from autosound_tcc.ui.tcc import dsp_check
    from tests._method_copies import linked_and_approved

    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, str(_bare_copy(tmp_path / "own")))
    assert dsp_file.declared(vendor_loader.skill_dir()) is None
    project = tmp_path / "bound-project"
    project.mkdir()
    linked_and_approved(project, _declaring_copy(tmp_path / "declaring"))
    reader = dsp_file.reader_for(MOSCONI, project)
    assert reader is not None and reader.reads(dsp_file.ATTEST)
    assert dsp_check.reads_save_file(MOSCONI, project), "the mark"
    path = _saved_file(project, "a.PR15")
    _method(monkeypatch, _differing(path))
    _head(project)
    _host, check = _saving_check(project, MOSCONI)
    assert check.button.isEnabled() and i18n.t("dspFileCheckNoMarkTip") not in check.tip.text()
    assert _run(check, str(path)).save_button is not None, "the save"


def test_a_project_bound_to_a_copy_that_declares_nothing_gets_no_reader_whatever_tcc_s_says(
        tmp_path, monkeypatch):
    """T3, the reverse: TCC's own copy declares (`AUTOSOUND_SKILL_DIR`), the project's does not —
    no button, no mark, and the hover says why (#272: TCC keeps no table of its own)."""
    from autosound_tcc.ui.tcc import dsp_check
    from tests._method_copies import linked_and_approved

    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, str(_declaring_copy(tmp_path / "own")))
    assert dsp_file.declared(vendor_loader.skill_dir()) is not None
    project = tmp_path / "bound-project"
    project.mkdir()
    linked_and_approved(project, _bare_copy(tmp_path / "bare"))
    assert dsp_file.reader_for(MOSCONI, project) is None and dsp_file.reader_for(HELIX, project) is None
    assert not dsp_check.reads_save_file(HELIX, project), "the mark"
    _host, check = _saving_check(project, HELIX)
    assert not check.button.isEnabled() and check.tip.text() == i18n.t("dspFileCheckNoReadersTip")


def test_a_ukrainian_window_shows_warning_uk_on_a_refusal_too(tmp_path, monkeypatch):
    _fake(monkeypatch, code=2, out=_refusal(warning_uk="На свій ризик."))
    _host, check = _check(tmp_path, HELIX)
    try:
        i18n.set_language("uk")
        assert _run(check).warning_label.text() == "На свій ризик."
    finally:
        i18n.set_language("en")


def test_a_comparison_of_no_rows_says_so_in_the_table(tmp_path, monkeypatch):
    _fake(monkeypatch, out=_answer([]))
    _host, check = _check(tmp_path, HELIX)
    table = _run(check).table
    assert table is not None and _cells(table) == [[i18n.t("dspFileCheckNoRows"), "", "", ""]]
    assert check.dialog.counts_label.text() == "0 match · 0 differ · 0 unknown"


def test_a_model_the_method_does_not_state_as_checked_or_not_is_no_risk_line(tmp_path, monkeypatch):
    """Decided: `checked_model` absent is «not stated», never «not checked» — the warning is there."""
    data = json.loads(_answer([_r("w-L", "gain_db", "match")]))
    del data["checked_model"]
    _fake(monkeypatch, out=json.dumps(data))
    _host, check = _check(tmp_path, HELIX)
    dialog = _run(check)
    assert dialog.answer.checked_model is None and dialog.risk_label.isHidden()
    assert not dialog.warning_label.isHidden()


def test_a_save_the_launcher_did_not_start_banks_nothing_and_keeps_nothing_running(tmp_path, monkeypatch):
    path = _saved_file(tmp_path)
    _method(monkeypatch, _differing(path), saved=method_cli.Refused("this project's method is not one TCC runs"))
    host, check = _saving_check(tmp_path)
    _run(check, str(path))
    dialog = _save(check)
    assert dialog.saved.kind == "not_run" and "was not run" in dialog.saved_label.text()
    assert "not one TCC runs" in dialog.saved_label.text()
    _settle()
    assert host.reloads == 0 and not dialog.save_button.isEnabled()

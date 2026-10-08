"""Contract 1's table, held on TCC's side (#178, SKL-066; hub #265 ask 2).

What TCC imports in-process from the method — 15 modules, and the names it reads from each with the
parameters it passes — is the `IMPORTABLE` table of the method's `rew_tool/contract.py`: contract 1,
item 9 of its `rew_tool/CONTRACT.md`. The method's guard holds its code to the table frozen for
contract 1, and the frozen table to its digest, and stops there: the table and its digest edited in
one commit pass it (item 12). This file is the hold item 12 asks of TCC: TCC's own copy of the
table, every module and every entry as v3.1.2 declares it, and the method TCC's tests run held to
it.

Read, never imported: `CONTRACT_VERSION` through `method_binding`'s reader, `IMPORTABLE` as the
module's one top-level dict literal through `ast.literal_eval`. The copy is the one every test runs
— `vendor_loader.skill_dir()`, `AUTOSOUND_SKILL_DIR` first — so the nightly against the method's
newest tag (`method-newest.yml`) names a table that changed there: the module, and the entry added,
removed or changed.

A difference is not a verdict that the method broke contract 1: `IMPORTABLE` may grow under it (a
name, a module, a trailing parameter with a default). It is where TCC reads the change, and moves
its copy below on purpose or asks the method why.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from autosound_tcc.core import method_binding, vendor_loader

#: The number this table is the table of.
CONTRACT = 1

#: Contract 1's `IMPORTABLE`, as the method's v3.1.2 declares it — TCC's own copy, written out and
#: never read from the method, so an edit there is a difference here. An entry is a name, a
#: function with the parameters TCC passes, a class with its constructor's, or a member. It is the
#: table in `contract.py`, which every copy carries, not the guard's `FROZEN[1]` (frozen at the
#: skill's dd4312d): the two differ in one entry, `Process.load(strict=False)` where the frozen
#: table has `Process.load()` — a parameter with a default, growth contract 1 allows.
CONTRACT_1 = {
    "rew_api.py": (
        "BASE_URL", "FINEST_SMOOTHING", "get_measurements()", "get_measurement(mid)",
        "find_measurement_id(name, measurements=None, exact=True)",
        "get_measurement_by_name(name, exact=True)", "rename_measurement(mid, title)",
        "get_fr(mid, smoothing=None)", "get_group_delay(mid, smoothing=None)",
        "get_impulse_response(mid)", "get_distortion(mid)", "get_filters(mid)",
        "get_equaliser(mid)", "get_equalisers()", "get_crossover_types()", "get_slopes()",
        "get_target_settings(mid)", "get_target_response(mid)", "set_filters(mid, filters)",
        "is_swept(record)", "duplicate_titles(measurements=None)",
    ),
    "state/state.py": (
        "PresetHistory(root, preset, project_dir=None)", "PresetHistory.head()",
        "PresetHistory.load(version=None)",
        # Private, and TCC calls it (`state/dsp_state.py`): held until a public accessor (W-10).
        "PresetHistory._path(version)",
        "SnapshotError", "identity_error(path, snap)", "project_channels(project_dir)",
    ),
    "state/process.py": (
        "Process(root)", "Process.load(strict=False)", "Process.events(limit=None, kinds=None)",
        "Process.session_closed()", "Process.protective_record()", "PHASES", "PHASE_TITLES",
        "EV_CONFIG_CHANGE", "EV_STEP_DONE",
    ),
    "naming.py": (
        "parse_name(title, glossary=None)", "name_key(parsed)",
        "Glossary.for_project(project_dir)", "Glossary.channel_codes(active_only=False)",
        "Glossary.resolve_code(code)", "Glossary.pairs", "Glossary.joints", "Glossary.sides",
        "Glossary.combos",
        "generate_name(code, version, method=None, modifier=None, position=None, control=None, "
        "params=None)",
        "expected_groups(phase, glossary, version)",
        "validate_series(titles, expected, glossary=None)", "METHODS", "METHOD_SWEEP",
        "METHOD_RTA", "canonical_title(title)", "canonical_code(code)",
        "explain_name(title, glossary=None)",
    ),
    "dsp_profile.py": (
        "load_profile(path)", "validate_profile(data)", "FIELD_VOCABULARY",
        "CAPABILITY_CHECKLIST", "processing_rate_hz(data)", "bundled_dir()",
        "list_bundled(dir_=None)",
    ),
    "project.py": (
        "Project(root)", "Project.load()", "Project.save(data)", "Project.parse_impact(impact)",
        "PROJECT_TYPES", "project_type(data)",
    ),
    "dsp_math.py": ("apf1_response(freqs_hz, f0)", "apf2_response(freqs_hz, f0, q)"),
    "resonalyze_vc.py": (
        "load_session(path)",
        "convert(doc, *, profile=None, proj=None, mapping=None, group_id='physical_outputs', "
        "source_path=None)",
    ),
    "project_seed.py": (
        "seed(source, target, *, include_findings=False, copy_profile=True, note=DEFAULT_NOTE, "
        "today=None, seat=None, include_fs=True)",
        "describe(source)", "dsp_of(source)",
    ),
    "eq_export.py": (
        "export_eq(profile, eq_rows, *, crossovers=None, fmt=None, group_id='physical_outputs', "
        "channel=None)",
    ),
    "protective.py": (
        "legs_of(record, channel)", "should_de_embed(record, channel, *, baseline=None)",
        "matters_at(legs, freq_hz)", "de_embed(freqs_hz, measured, legs)",
    ),
    "listening.py": (
        "characteristics(lang=None)", "tracks(lang=None)", "links(lang=None)", "routes()",
        "check(lang=None)",
        # Not in SURFACE.md B1, the surface as first written down; TCC's `core/listening.py` asks it.
        "languages()",
        "PATTERNS", "CHEAT_SHEET",
    ),
    "gates/side_effect.py": (
        "FORM_POST_URL", "FORM_FIELD_SENDER", "FORM_FIELD_KIND", "FORM_FIELD_IMPACT",
        "FORM_FIELD_MESSAGE", "FORM_FIELD_VERSIONS", "FORM_LABELS", "FORM_KINDS",
        "FORM_PERSON_KINDS", "FORM_IMPACTS", "FORM_TIMEOUT_S",
        "form_answers(sender, kind, message, impact='', versions='')",
        "verify_form_reply(status, body)",
        "upload_issue_asset(image_path, dest_name, *, consented=False, message=None, "
        "runner=_subprocess_runner, dry_run=False)",
    ),
    "car_profile.py": (
        "find_prior_projects(dirs, make, model, generation='', body='')",
        "body_slug(make, model, generation='', body='')",
        "find_bundled_car(make, model, generation='', body='')",
    ),
    "verify.py": ("verdict(name, measurements=None, f_low=20, f_high=20000)",),
}


def _the_copy() -> Path:
    """The method TCC's tests run: `vendor_loader.skill_dir()`, `AUTOSOUND_SKILL_DIR` first."""
    copy = vendor_loader.skill_dir()
    if not vendor_loader._looks_like_the_skill(copy):
        pytest.skip("the method is not checked out (git submodule update --init --recursive)")
    return copy


def _importable(contract_py: Path) -> dict:
    """The value of the module's one top-level `IMPORTABLE = {...}`, by `ast.literal_eval` of that
    assignment's value — the file is never imported, so nothing in it runs."""
    tree = ast.parse(contract_py.read_bytes(), filename=str(contract_py))
    values = [node.value for node in tree.body
              if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
              and any(isinstance(target, ast.Name) and target.id == "IMPORTABLE"
                      for target in (node.targets if isinstance(node, ast.Assign)
                                     else [node.target]))]
    assert len(values) == 1, (
        f"{contract_py}: {len(values)} top-level IMPORTABLE assignments, where contract 1 has one")
    return ast.literal_eval(values[0])


def _name(entry: str) -> str:
    """What an entry names, without the parameters: `Process.load(strict=False)` names
    `Process.load`."""
    return str(entry).split("(", 1)[0]


def _differences(theirs: dict, ours: dict) -> list[str]:
    """One line for each way the copy's table (`theirs`) is not TCC's (`ours`), the module first: a
    module added or removed; an entry added or removed; an entry changed — one name, its parameters
    another; a module's entries in another order. Empty when the two are equal."""
    said = [f"{module}: a module the copy added, with {list(theirs[module])}"
            for module in sorted(theirs.keys() - ours.keys(), key=str)]
    said += [f"{module}: a module the copy removed (TCC's copy lists {list(ours[module])})"
             for module in sorted(ours.keys() - theirs.keys(), key=str)]
    for module in sorted(theirs.keys() & ours.keys(), key=str):
        new, old = theirs[module], ours[module]
        if new == old:
            continue
        if not isinstance(new, tuple):
            said.append(f"{module}: the copy's entries are a {type(new).__name__}, not a tuple: "
                        f"{new!r}")
            continue
        added = [entry for entry in new if entry not in old]
        removed = [entry for entry in old if entry not in new]
        for entry in added:
            was = next((gone for gone in removed if _name(gone) == _name(entry)), None)
            if was is None:
                said.append(f"{module}: {entry!r} added by the copy")
            else:
                removed.remove(was)
                said.append(f"{module}: {was!r} changed by the copy to {entry!r}")
        said += [f"{module}: {entry!r} removed by the copy" for entry in removed]
        if not added and not removed:
            said.append(f"{module}: the same entries in another order: {list(new)}")
    if theirs != ours and not said:
        said.append(f"the tables differ: {theirs!r}")
    return said


def test_the_method_tcc_runs_declares_contract_1():
    """Its `contract.py` names 1 as a plain literal, read the way the binding and the press read
    it. A copy on another number has another table, and the one below is not the one to hold."""
    copy = _the_copy()

    contract = method_binding.read_contract(copy)

    assert contract == method_binding.Contract(True, CONTRACT), (
        f"{copy / 'rew_tool' / 'contract.py'}: {contract}; this file holds contract "
        f"{CONTRACT}'s table")


def test_its_importable_table_is_contract_1s_entry_for_entry():
    """CONTRACT.md item 12: the method's guard cannot catch its frozen table and the table's digest
    edited in one commit. TCC's copy of the table can: every module and every entry, as v3.1.2
    declares it, and a difference named by module and entry."""
    contract_py = _the_copy() / "rew_tool" / "contract.py"

    table = _importable(contract_py)

    assert table == CONTRACT_1, (
        f"{contract_py}: IMPORTABLE is not contract 1's table as TCC keeps it "
        f"(tests/test_contract_one.py):\n" + "\n".join(_differences(table, CONTRACT_1)))


def test_the_table_is_keyed_as_tccs_loader_imports():
    """The table lists TCC's in-process imports keyed as `vendor_loader._VENDORED` is: the same 15
    modules, so a module TCC starts importing is one the contract does not cover until the method
    lists it."""
    assert sorted(CONTRACT_1) == sorted(vendor_loader._VENDORED)


def test_a_difference_is_named_by_its_module_and_entry():
    """What the nightly says when a newer tag's table moves: the module, and the entry added,
    removed or changed — not a dict printed whole."""
    theirs = {module: tuple(entries) for module, entries in CONTRACT_1.items()
              if module != "verify.py"}
    theirs["dsp_math.py"] = ("apf1_response(freqs_hz, f0)", "apf2_response(freqs_hz, f0, q=0.7)")
    theirs["project.py"] = CONTRACT_1["project.py"][:-1]
    theirs["dsp_profile.py"] += ("profile_rate(data)",)
    theirs["eq_import.py"] = ("import_eq(text)",)
    theirs["state/process.py"] = tuple(reversed(CONTRACT_1["state/process.py"]))

    said = _differences(theirs, CONTRACT_1)

    assert said == [
        "eq_import.py: a module the copy added, with ['import_eq(text)']",
        "verify.py: a module the copy removed (TCC's copy lists "
        "['verdict(name, measurements=None, f_low=20, f_high=20000)'])",
        "dsp_math.py: 'apf2_response(freqs_hz, f0, q)' changed by the copy to "
        "'apf2_response(freqs_hz, f0, q=0.7)'",
        "dsp_profile.py: 'profile_rate(data)' added by the copy",
        "project.py: 'project_type(data)' removed by the copy",
        "state/process.py: the same entries in another order: "
        f"{list(reversed(CONTRACT_1['state/process.py']))}",
    ]
    assert _differences(dict(CONTRACT_1), CONTRACT_1) == []

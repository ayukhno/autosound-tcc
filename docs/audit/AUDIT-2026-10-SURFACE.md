# J1 — every way TCC touches the method (tcc f58d208, vendored skill v3.1.1)

## B1. In-process (core/vendor_loader.py registry :141-196, 15 modules; contract.py deliberately not registered :197-200)
- rew_api: BASE_URL; get_measurements, get_measurement, find_measurement_id(name, exact=), get_measurement_by_name, rename_measurement; get_fr/get_group_delay(mid, smoothing=) (TypeError retry, rew_bridge.py:101-108); get_impulse_response, get_distortion, get_filters, get_equaliser(s), get_crossover_types, get_slopes, get_target_settings, get_target_response; FINEST_SMOOTHING (getattr); set_filters (direct, mcp_server.py:1214-1220); is_swept, duplicate_titles (getattr); measurement kinds by value. (core/rew_bridge.py, capture_import.py)
- naming: parse_name, name_key, Glossary.for_project / channel_codes / pairs/joints/sides/combos / resolve_code, generate_name, expected_groups, validate_series (keys renames/foreign/extra/missing), METHODS, canonical_title, canonical_code, explain_name (getattr), METHOD_SWEEP/RTA by value. (measurement_view, capture_import, curve_groups, title_fixes, process_view, project_view, curve_dialog)
- state/process: Process(dir).load(), .events(kinds=), .session_closed (getattr), .protective_record(); PHASES, PHASE_TITLES, EV_CONFIG_CHANGE, EV_STEP_DONE; plus event names/fields as string literals in TCC's own fold (process_view.py:133-176).
- state/state: PresetHistory(root, preset, project_dir=).head()/.load(v); PresetHistory._path (PRIVATE, dsp_state.py:619); SnapshotError, identity_error (getattr); project_channels.
- project: Project(dir).load()/.save(data) — an in-process WRITE (car_library.py:140-150); Project passed as proj=; Project.parse_impact; PROJECT_TYPES, project_type.
- dsp_profile: load_profile, validate_profile, FIELD_VOCABULARY, CAPABILITY_CHECKLIST, processing_rate_hz (getattr). No bind_* call anywhere in TCC.
- verify: verdict(name, measurements=, f_low=, f_high=) (getattr, failures swallowed, capture_import.py:380,527); keys valid/exists/applicable/kind/max_freq/issues/truncated.
- dsp_math: apf1_response, apf2_response (allpass.py:156-160).
- resonalyze_vc: load_session, convert(...); result keys legs[].channel/channel_hint/display_name, summary.*.
- project_seed: seed(source, target, include_findings=, include_fs=, copy_profile=, note=, seat=), describe, dsp_of (new_project_dialog.py).
- eq_export: export_eq(profile, rows, crossovers=, group_id=, channel=) → text, format_name, written, crossovers, bank_size, left_out, notes.
- protective: legs_of, should_de_embed, matters_at, de_embed → info.applied/capped_*/note.
- listening: characteristics, tracks, links, routes, check, PATTERNS, CHEAT_SHEET.
- gates/side_effect: FORM_* constants, form_answers, verify_form_reply, upload_issue_asset (hasattr probe).
- car_profile: find_prior_projects, body_slug, find_bundled_car.
Import-time side effect that reaches TCC: project, resonalyze_vc, project_seed, eq_export, protective each sys.path.insert(0, rew_tool) at import (S2 T-19); TCC knows (vendor_loader.py:193,451).

## B2. Subprocess (child.script_interpreter, vendor_loader.child_env)
- state/process.py <project>/process: enter-phase, add-step, start, done, skip [--superseded-by], block, reviewer, capture-protective [--amend --reason] [--source], listening-verdict, listening-verdicts, target, decision [--invalidates], session-start, session-close (exit 0/1 is the answer), capture-start [--plan --optional --start --step --origin], capture-knobs, capture-check [--session], capture-taken, capture-skip, capture-close, check, plan, show — process_writer.py:198-622 via _spawn (:150-183) under _THREAD_LOCK + flock (POSIX).
- same process.py: capture-supersede — title_fixes.py:65-74, own subprocess, NO lock, not in LANDED_IN.
- same process.py: handoff --json (exit 0/1, needs `ok`) — handoff.py:34-49, not in LANDED_IN.
- dsp_profile.py: start, draft, set-field, reset-field, finalize ("wrote " prefix), find-bundled ("no exact match" or JSON) — profile_writer.py:86-122.
- state/state.py --root R config save … — config_writer.py:38-59 (refusal by string "invalid choice: 'config'", exit 2).
- project_repo.py init / status --json — project_repo.py:57,69.
- contract.py check <p> --json [--no-rew] — contract_check.py:190-258 (keys ok, project_dir, files[], cross_checks{rew, continue_head, glossary_vs_ledgers, tiers_vs_profile}, inherited[], sources_gone[], complete).
- intake_form.py serve <p> --lang --port 0 (stdout URL_PREFIX line) — intake_form.py:63-90.
- scripts/upkeep.py --json [--clone] status|clone --tag|keep-local [--send]|libs|tools — updates.py:953-1250 (extracts upkeep.py, side_effect.py, console.py, requirements.txt from the new tag).
- scripts/autosound_ai.py <role> <package> [--via --model --provider]; doctor; key status --json|set|rm|help|move-shell; agy_sign_in via -c; env AUTOSOUND_CRITIC_MODEL/_VIA/_BIN, GEMINI_CRITIC_MODEL, AUTOSOUND_DIR; parses stderr "called <vendor>" — critic.py, reviewer_key.py.
- git on the skill clone: ls-remote --tags, fetch, show <tag>:<file>, rev-parse.

## B3. Skill files TCC parses itself
- project.json: project_view.py:83,369; dsp_state.py:562 (unguarded); acoustics_view.py:180; measurement_view.py:54; capture_import.py:604; resonalyze_import_dialog.py:384; new_project_dialog.py:96,112 — skill readers exist for part (Project.load refuses unreadable; project_channels; Glossary.for_project).
- dsp_profile.json: project_view.py:139,369; curve_dialog.py:1530 — skill has load_profile, processing_rate_hz.
- process-state.json: via Process.load only (no unreadable refusal — K-2).
- journal.jsonl: TCC's own fold process_view.py:98-187; control_layout.py:141-152 tail — skill has events(), capture_rounds() (narrow: no taken/skipped/verified/protective/superseded).
- slots.json, v_NNN.json: ledger_line.py:38-95,203 own reads — PresetHistory/Registry exist.
- ledger snapshot group→key mapping hard-coded (dsp_state.py:468-500).
- references/patterns/target-curves/*.txt|.html (target_curve.py greps HTML); assets/<name> (critic.py:240); .claude-plugin/plugin.json version.

## B4. Compatibility today
three-file check (vendor_loader.py:59-83) · LANDED_IN + _refuse_if_too_old (process_writer only; regex test over source) · string-matched argparse refusals (config_writer, project_repo) · handoff None if not a dict with ok · getattr/hasattr probes (older methods only) · module-missing = "not in this skill" · reload_loaded rollback on import failure · pin-behind row (checkout only) · update row = newest v3.* · ship gate = pin has a published tag · NO contract-version constant.

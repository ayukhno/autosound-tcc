"""EN/UK strings — ported from the web prototype's `T = {en, uk}` table
(`data/private/prototype/tcc-main.html`). Keys are kept identical to the prototype's so later
milestones can copy more entries in verbatim instead of re-naming anything.

Every user-facing string in the app should go through `t()`/`tx()`, and every widget that
displays translated text registers a retranslate callback via `on_language_changed()` so
`set_language()` can repaint the whole UI in place — mirrors the prototype's `setLang()`.
"""

from __future__ import annotations

import weakref

import shiboken6
from typing import Callable

Lang = str  # "en" | "uk"

T: dict[Lang, dict[str, str]] = {
    "en": {
        "theme": "theme",
        "dspPanel": "DSP",
        "projectParams": "Project params",
        # The channel-tier summary rows. Keyed by the tier id `project.json` uses, with
        # the id itself as the fallback label for a tier TCC has no word for yet.
        "chanSum_channels": "Channels",
        "chanSum_virtual_channels": "Virtual channels",
        "chanSum_physical_outputs": "Output channels",
        "chanSum_inputs": "Inputs",
        "chanSumOff": "{total} ({off} off)",
        "cfgLanguage": "Language",
        "cfgGenerator": "AI generator",
        "cfgEffort": "Effort",
        "cfgCritic": "AI reviewer",
        "cfgTheme": "Theme",
        "cfgGate": "Permissions",
        "cfgThemeLight": "light",
        "cfgThemeDark": "dark",
        "systemParams": "System params",
        "audioAnalysis": "Car audio analysis",
        "leftNoProfile": "No DSP yet. Start a session and tell it which processor this car has — the profile is written as soon as it is named, and this panel fills in.",
        "leftNoLedger": "No settings captured yet. The tree fills in once the first ledger snapshot is written, during tuning.",
        "planEmpty": "No plan yet. The skill writes one when a session enters a phase, and this fills in as steps are added and closed.",
        "planNoProject": "No project open.",
        "noDataYet": "No data yet",
        "openQuestions": "Open",
        "openQuestionsTitle": "Open questions",
        # One spelling for the config series, wherever it is offered: the curve window
        # printed a bare `_0` and the capture panel a bare `v6`, which read as two
        # different things and explained neither (user, 2026-08-21). A round (`cap_001`)
        # is a different axis and keeps its own name.
        "curveRoundEmpty": "{round}: REW does not hold the measurements that round took — a different project is open, or they were deleted.",
        "seriesItem": "series {v}",
        "logError": "Something went wrong: {error} — the details are in {path}",
        "rewPort": "REW port",
        "rewOnlineTip": "REW: online",
        "rewOfflineTip": "REW: not reachable on this port.\nThe API is in REW's BETA builds only — the release version has no API tab at all (roomeqwizard.com/beta.html).",
        "createProject": "+ Create new project",
        "refreshProjectTip": "Reload the project from disk (profile, ledger)",
        # Diagnostics (TCC-TZ.md §8) — the skill's own contract check, rendered not re-derived.
        "selfSection": "TCC's own setup",
        "selfAliasTitle": "{n} model alias(es) in force",
        "selfAliasDetail": "",
        "selfAliasNoneTitle": "No model aliases in TCC's own layer",
        "selfAliasNoneDetail": "Which is not the same as \"the picker runs what it says\": the reviewer script substitutes too, one layer below — it falls back from the API to a local CLI, and that CLI runs whichever model it is set to. The row below compares who actually answered.",
        "selfReviewerNeverTitle": "The reviewer has not been called in this project yet",
        "selfReviewerNeverDetail": "Nothing to compare until it answers once. A configured model is a claim; a call is evidence.",
        "selfReviewerOkTitle": "Last review came back from {model}, which is what was asked for",
        "selfReviewerDiffTitle": "The reviewer that answered is not the one selected",
        "selfReviewerDiffDetail": "Asked for {wanted}; {answered} answered. Neither picker nor `substituted` shows this — the reviewer script falls back from the Gemini API to the local CLI (a 404 is enough), and the CLI runs whichever model it is currently set to. Check what `agy` has selected, or accept that this is the reviewer.",
        "selfAliasCrossVendor": "{keys} now runs a model from a DIFFERENT vendor than the one asked for. When that is the reviewer, cross-vendor review has stopped — the point of a second vendor is that it does not share the Generator's blind spots.",
        "selfAliasFix": "Remove all aliases",
        "selfAliasFixed": "Removed {n} alias(es). The pickers run what they say again.",
        "selfCatalogueTitle": "Installed but silent: {clis}",
        "selfCatalogueDetail": "This CLI is on PATH and its model list came back empty, so its route is missing from the pickers — which reads exactly like \"not installed\", and is how a stored model comes to look gone.",
        "selfCatalogueFix": "Ask the CLIs again",
        "selfCatalogueFixed": "Catalogue refreshed: {n} model(s).",
        "selfCatalogueOkTitle": "Every installed CLI answered with its models",
        "selfRecommendOkTitle": "The recommended pair is available here",
        "selfRecommendTitle": "Nothing on offer matches the recommended {roles}",
        "selfRecommendDetail": "The recommendation is a class, not a model name — {pairs}, as of {since} — so a new version of either is marked automatically. Matching nothing means the class itself has retired, or its route is not installed. Pick deliberately; there is no recommendation to fall back on.",
        "selfCheckFailed": "This check could not run",
        "diagFixDone": "Fixed: {what}",
        "diagTitle": "Project diagnostics",
        "diagBtnTip": "What TCC found on disk: the skill's machine files, checked",
        "diagChecking": "Checking…",
        "diagOk": "OK — nothing to fix",
        "diagIssues": "{n} issue(s) found",
        "diagNoIssues": "No issues",
        "diagAsk": "Ask the session",
        "diagAskText": "Diagnostics reports a problem in {subject}, in the checker's own words:\n\n    {issue}\n\nFix it with the skill's own commands (TCC does not write these files). When it is done, say which command you ran — I will re-run `contract.py check` and we will see whether the row is gone.",
        "diagAskedAgo": "asked {ago}, still here",
        "diagAgoNow": "just now",
        "diagAgoMin": "{n} min ago",
        "diagFiles": "Machine files",
        "diagCross": "Cross-file checks",
        "diagOpenQ": "Open questions (intake unfinished)",
        "diagMissing": "missing",
        "diagUnavailable": "Contract check unavailable",
        "diagCheckedAt": "checked {at} · {ms} ms",
        # The second tab: what is installed on this machine, for a report from a machine nobody
        # debugging it can see (user, 2026-08-19).
        "diagTabProject": "Project",
        "diagTabInstall": "Installation",
        "diagTabLog": "Log",
        "diagReport": "Report a problem",
        "titleUpdate": "update available",
        "updWhy_source_checkout": "running from a source checkout — update it with git",
        "updWhy_no_network": "could not reach GitHub",
        "updWhy_not_found": "not found on this machine",
        "updWhy_not_a_checkout": "not a git checkout, so there is nothing to update in place",
        "updWhy_on_branch": "on a branch — somebody's working tree, not an installed release",
        "updWhy_submodule": "a submodule of a checkout — update it with git, in",
        "updWhy_dirty": "has uncommitted changes, so it is left alone",
        "updWhy_no_manifest": "no version in the manifest",
        "updWhy_git_failed": "git said",
        "updTcc": "Update TCC",
        "updSkill": "Update the method",
        "updTccName": "TCC",
        "updSkillName": "The method",
        "updChecking": "checking for updates…",
        "updAvailable": "{what} {here} — a newer one is out: {there}",
        "updNewerBuild": "{what} {here} — a newer build of the same version is out",
        "updNewerBuildOn": "{what} {here} — a newer build is out, from {date}",
        "updCurrent": "{what} {here} — up to date",
        "updUnknown": "could not ask GitHub — no network, or it is having a day",
        "updWorking": "updating…",
        "updSkillDone": "The method is now {version} — reopen the AI session to pick it up",
        "updTccHanded": "A terminal is open and waiting for TCC to close. Quit TCC — the update "
                        "runs by itself, then start TCC again.",
        "updFailed": "did not work: {why}",
        "diagLogNone": "no log file — this run writes to the terminal only",
        "diagInstallBlurb": "What is installed on this machine — versions, where each piece came \
from, which command-line tools answer. Copy it into a message when you report something: it \
answers the first five questions anybody would ask.",
        "diagInstallReading": "reading…",
        "diagInstallCopy": "Copy",
        "diagInstallCopied": "Copied",
        "diagRefresh": "Re-check",
        "diagClose": "Close",
        "diagStripIssues": "Project contract: {n} issue(s) — see Diagnostics (⚕)",
        "diagStripError": "Contract check unavailable: {error}",
        "projectRenderFailed": "Could not draw the project from disk — the last good view is still "
                               "on screen. {error}",
        "staleStrip": "{what} — {n} channel(s) need re-measuring: {codes}",
        "missingRecord": "Not written down: {what} — {why}.",
        "criticSaved": "Text saved to {path}",
        # The flaw map (SCR-015). `action` is the load-bearing half — what may and may not be done
        # about a feature — so each value gets a short label a reader can scan, not a raw key.
        "acousticsNone": "No flaw map yet. Phase 0 measures what this cabin does to the sound, and the rows land here — each with what may and may not be done about it.",
        "flawHypothesis": "not settled",
        "flawEvidenceHead": "Read off:",
        "flawNoWhy": "No reason was recorded with this entry -- only the measurement itself.",
        "flawAllChannels": "all channels",
        "flawAction_notch": "cut",
        "flawAction_leave": "leave",
        "flawAction_no_boost": "never boost",
        "flawAction_geometry": "geometry",
        "flawAction_delay": "delay",
        "flawAction_crossover": "crossover",
        "flawKind_room_gain": "room gain",
        "flawKind_modal_peak": "cabin mode",
        "flawKind_cabin_null": "cabin null",
        "flawKind_sbir": "SBIR",
        "flawKind_floor_bounce": "floor bounce",
        "flawKind_driver_resonance": "driver resonance",
        "flawKind_non_min_phase": "non-minimum-phase",
        "flawKind_thd_spike": "distortion spike",
        "flawKind_pair_suckout": "pair suckout",
        "supervisorUnbacked": "These steps are closed, and their evidence names nothing that "
        "exists on disk or in REW:<br>{steps}<br>Either the work is recorded somewhere this "
        "cannot see, or it was not done.",
        "recordTargetCurve": "the target curve",
        "recordTargetCurveWhy": "phase 0 chooses it and every later phase is measured against it, "
                                "so nothing on disk says which curve was picked",
        "measNoTask": "No capture task yet. It is derived from the phase, the naming glossary and the current ledger version — so it appears once the intake has settled the channel names.",
        "measPhaseNoCapture": "This phase takes no measurements — it works on the series already captured. The next capture task appears with the phase that needs one.",
        "noProjectMeas": "No project — nothing to capture yet.",
        "npTitle": "New project",
        "npFolder": "Project folder",
        "npBrowse": "Browse…",
        "npProfile": "DSP profile",
        "npAddNew": "+ Add new (not listed)",
        "npVendor": "DSP vendor",
        "npVendorPlaceholder": "e.g. Helix, Musway",
        "npModel": "DSP model",
        "npModelPlaceholder": "e.g. DSP Ultra S, M6V4",
        "npRunVia": "Run onboarding via",
        "npRunInApp": "In-app (Claude)",
        "npAiModel": "AI model",
        "npTerminalModel": "Model (optional)",
        "npTerminalModelPlaceholder": "e.g. opus, gemini-2.5-pro — blank = CLI default",
        "npOnboardingHint": "Use the autosound-tuning skill for DSP-profile onboarding. Connect "
                            "to this project's 'tcc' MCP server (see .mcp.json) and call its "
                            "check_existing_profile tool first, for vendor={vendor} model={model}. "
                            "Please conduct the interview in {language}.",
        "langNameEn": "English",
        "langNameUk": "Ukrainian",
        "npSeed": "System parameters",
        "npSeedNone": "Ask during onboarding (from scratch)",
        "npSeedFrom": "Copy from an existing project…",
        "npSeedPlaceholder": "Folder of a project that has a project.json",
        "npSeedFindings": "…and what was measured there (acoustic flaws, open questions)",
        "npSeedNotAProject": "No readable project.json here — nothing to copy.",
        "npSeedSummary": "{car} · {dsp} · {channels} channels",
        "npSeedNote": "**Inherited from `{source}` ({when}).** The system profile was copied from "
                      "that project, not written here — check it against this build before relying "
                      "on it.",
        "npSeedFailed": "Nothing was copied: {problem}",
        "npSeedDone": "System parameters copied from '{source}': {files}. They were inherited, not "
                      "measured here — check them against this build.",
        "npSeedHint": "The system parameters were copied from the project '{source}' into this "
                      "folder: read project.json and dsp_profile.json FIRST and go through them "
                      "with the person, correcting what differs. Do not ask for the car to be "
                      "described from scratch.",
        "riTitle": "Import a Resonalyze session",
        "riFilePlaceholder": "A Resonalyze virtual-DSP session (.json)",
        "riAgainst": "Checked against",
        "riNoProfile": "No dsp_profile.json in this project — nothing was checked against a real "
                       "processor. Every value below is reported, none is verified.",
        "riScene": "Stereo scene",
        "riSceneNote": "What Resonalyze's Auto balance aims for. It is already inside the per-leg "
                       "gains and delays below — do not enter it a second time.",
        "riUnbound": "no channel of this project matches",
        "riDormant": "in the file, but NOT live (the crossover kind decides)",
        "riDropped": "dropped: transparent, contributes nothing",
        "riNotChecked": "Not checked, because this DSP profile does not state the limit",
        "riBindNone": "— leave unbound —",
        "riBlocked": "This processor cannot be given the plan as it stands: {refused} value(s) "
                     "refused, {unbound} leg(s) unbound. Nothing is rounded to fit, and nothing "
                     "is written.",
        "riClear": "No stated limit of this DSP refuses any of the {legs} legs. That answers for "
                   "the HARDWARE — a PC-Tool mode (Fine EQ) can be narrower, and the switch is at "
                   "the screen. Banking the rows is the tuning gate's job: copy them and propose "
                   "from the terminal.",
        "riCopyRows": "Copy rows (JSON)",
        "riCopied": "The rows are on the clipboard.",
        "riFailed": "This file could not be read:",
        "riClose": "Close",
        "riImport": "Settings from a Resonalyze session…",
        "npSeedNoInterview": "Its dsp_profile.json comes too, so the capability interview is "
                             "skipped — there is nothing left to ask about a processor already "
                             "described. Choose a different DSP above and it runs as usual.",
        "npSeedNoSkill": "The autosound-tuning skill is not available here, and the copying "
                         "lives in it — install the skill, or fill the new project in by hand.",
        "npSeedOpen": "The inherited DSP profile still has {open} fact(s) nobody has confirmed.",
        "groupFieldsUnknown": "controls not enumerated yet",
        "menuProject": "Project",
        "menuSession": "Session and models",
        "menuView": "Appearance",
        "menuTools": "Tools",
        "menuHelp": "Help and support",
        "menuLanguage": "Language",
        "menuReload": "Re-read this project from disk",
        "menuZoomIn": "Larger text",
        "menuZoomOut": "Smaller text",
        "menuDiagnostics": "Diagnostics and updates…",
        "menuTargetTool": "Target-curve tool (opens a browser)",
        "riImportTip": "Takes the SETTINGS out of a Resonalyze virtual-DSP session — per channel: crossovers, delay, gain, polarity and the EQ bands — and checks every value against what your processor can actually be given. Not the session itself, and nothing is written: it refuses rather than rounds, and hands you the rows to bank through the tuning gate.",
        "menuStartSession": "Start a tuning session in TCC",
        "menuTerminal": "Open a terminal on this project",
        "menuModels": "Configure models (OMP)…",
        "menuTheme": "Switch theme (light / dark)",
        "menuCopyCar": "Copy the car…",
        "menuCopyCarTip": "Start a project from one that already exists: the car, the equipment and the installation — make, drivers per channel, amps, mic, the DSP and its profile, the naming glossary. What was MEASURED in the other project stays there unless you ask for it. You adjust what differs instead of describing your own car again.",
        "menuModelsTip": "Which models this project may use — the generator, the critic and how hard they are asked to think. Everything except Claude runs through OMP, so what you mark here is what OMP is allowed to reach for.",
        "menuButton": "☰ Menu",
        "npCreate": "Create",
        "npCancel": "Cancel",
        "projectNewTip": "Folder + DSP + who runs the onboarding. It can also START FROM AN EXISTING PROJECT: the car, the drivers, the glossary and the DSP profile come over, and you adjust instead of describing your own car again.",
        "projectOpenTip": "Point TCC at a different folder. An empty one is fine: it becomes a new project, and the onboarding conversation fills it in. TCC then opens again on the folder you picked — the window is bound to one project from the moment it starts.",
        "projectSaveStateTip": "Asks the model to write the plan, the evidence and anything it learned into the project's files. The conversation continues.",
        "projectFreshSessionTip": "Saves first, then starts over with an empty context on the SAME model. Not the same as restarting on a different one: this is for a conversation that has grown long and expensive while its conclusions are already on disk.",
        "gateTitle": "Open a tuning project",
        "gateBlurb": "TCC works on one project folder and binds to it at startup. Choose an existing one, or type a new path — an empty folder is a valid new project, the intake conversation fills it.",
        "gateFolder": "Project folder",
        "gateFolderPlaceholder": "/path/to/the/car",
        "gateBrowse": "Browse…",
        "gateOpen": "Open",
        "gateNote": "Both models are remembered with this project, not globally — another project keeps its own. You can change them later in the footer.",
        "projectSwitchTitle": "Switch project",
        "projectSwitchBody": "TCC binds one folder at startup, so it will restart on “{name}”. Anything the current session has not written to disk is lost — save it first if that matters.",
        "projectNone": "⌂ choose a project…",
        "projectOpen": "Open project folder…",
        "projectNew": "New project…",
        "projectSaveState": "Save what the model knows to disk",
        "projectFreshSession": "Start a new session (saves, then clears the context)",
        "projectReopen": "Folder changed — open TCC again to work on it.",
        "sessionSaved": "Project state written to disk. The session continues.",
        "savedTccOnly": "TCC's own settings are on disk. No session is running, so there is "
                        "nothing to ask the model to write.",
        "sessionFresh": "Session ended and state saved — starting a new one with an empty context.",
        "generator": "Generator",
        "preset": "Preset",
        "target": "Target curve",
        "targetToolTip": "Open in the target-curve tool ↗",
        "params": "PARAMS",
        "virtual": "VIRTUAL",
        "output": "OUTPUT",
        "inputs": "INPUTS",
        "paramsRow": "params · all parameters as a table",
        "tabTable": "Table",
        "close": "close ✕",
        "outTitle": "OUTPUT — physical drivers",
        "virtTitle": "VIRTUAL — input voicing",
        "colChan": "Channel",
        "eqHint": "Only <b>active bands</b> (all parameters at once — MUSWAY's edge over "
                  "Helix). APF is a band type, not a column. Bypass is read-only (for now). "
                  "Empty of 30 are hidden.",
        "shared": "shared frequencies:",
        "noShared": "no shared frequencies",
        "band": "band",
        "legWait": "waiting",
        "legDone": "done",
        "legBad": "taken, unusable",
        "legSkip": "skipped",
        "stepTagOkTip": "Closed, and its evidence is really on disk — the file or capture it names "
                        "was found.",
        "stepTagUnprovenTip": "Closed by the skill, but the evidence it named resolves to nothing "
                              "on disk: no such file, and no capture by that name.\n\nThis is not "
                              "the same as an unticked step. An unticked one was never finished; "
                              "this one was reported finished and has nothing behind it.",
        "stepTagWaitTip": "Either still in progress, or closed and since invalidated — a config "
                          "change means what it produced can no longer be trusted, so it needs "
                          "re-taking.",
        "chanOn": "ON",
        "chanOff": "OFF",
        # The BUTTON says what pressing it does; `chanOn`/`chanOff` above stay the state words the
        # confirmation and the transcript use. A control labelled with the state it is already in
        # reads as "this channel is on" and gets pressed by someone who wanted exactly that.
        "chanTurnOn": "TURN ON",
        "chanTurnOff": "TURN OFF",
        "chanToggleQueued": "Asked to switch {channel} → {state}. No session is running, so it is queued: the model gets it with the first turn of the next session.",
        "signalNudge": "TCC started a turn for {count} request(s) you made in the UI — nobody was talking, and a click should not have to wait for one.",
        "signalNudgePrompt": "The Arbiter used the UI. Handle the signals listed above first, acknowledge each with ack_signals, then say what you did — briefly.",
        "chanToggleWaiting": "asked · {secs}s",
        "chanToggleLate": "⚠ no answer · {secs}s",
        "chanToggleWaitTip": "TCC asked the model to record this; the ledger is the skill's to write. The row changes when the model answers. Asking again while this stands only refreshes the wait, it does not send a second request.",
        "chanToggleAlreadyAsked": "{channel} — already asked, still waiting on the model. Not sent twice.",
        "chanToggleTip": "Ask the model to switch this channel on or off. TCC does not write the "
                         "ledger — the request goes to the session, which records the change.",
        "chanToggleSent": "Asked to turn <b>{channel}</b> {state}. The model records it in the "
                          "ledger; the tree follows once it is written.",
        "noSessionForSignal": "No session is running — start one and the request will reach it.",
        "chanToggleConfirmTitle": "Switch this channel?",
        "chanToggleConfirmOff": "Turn <b>{channel}</b> off?\n\nIts EQ, crossover and delay live "
                                "in the ledger and may not survive being switched off. TCC cannot "
                                "undo this — the model records the change.",
        "chanToggleConfirmOn": "Turn <b>{channel}</b> on?\n\nThis is a structural change: the "
                               "channel needs its place in the glossary, and a physical output "
                               "needs its virtual counterpart. The model works that out and "
                               "records it.",
        "pillMute": "MUTE",
        "pillOff": "OFF",
        "attempt": "attempt",
        "addStep": "+ add step",
        "addStepPrompt": "Situational step (this project only):",
        "measRead": "Read",
        "measReading": "Reading from REW…",
        "measReadOk": "Read {n} measurement(s) from REW · {matched} matched, {extra} additional",
        "measReadFail": "Could not read from REW: {error}",
        "measReadNoMeas": "No measurements found in REW.",
        "measUsedInStep": "Used in step {steps}",
        "assignNames": "Assign names",
        "captureOrderTitle": "Capture order",
        "captureOrderHint": "Pick the capture method, then drag to match the order you actually "
                             "capture channels in REW. Saved per method and reused next time.",
        "captureMethodSw": "SW",
        "captureMethodRta": "RTA",
        "captureMethodRtaGroup": "RTA GROUP",
        "captureScanMismatch": "Found {found} new measurement(s) in REW, expected {expected} "
                                "(one per channel in the saved order). Capture the missing ones "
                                "or re-check the order, then try again.",
        "captureRenaming": "Renaming {n} measurement(s) in REW…",
        "captureRenameOk": "Renamed {n} measurement(s) to match the saved channel order.",
        "captureRenameFail": "Rename failed after {n} measurement(s): {error}",
        "effectProcess": "record the process (plan, steps, journal)",
        "effectProfile": "write the DSP capability profile",
        "effectLedger": "bank a ledger snapshot of the DSP settings",
        "effectProject": "write the project's own files",
        "effectContract": "check the project against the skill's contract",
        "gateMode": "Ask about",
        "gateWrites": "every write",
        "gateForeign": "only what the skill does not own",
        "gateModeTip": "The skill writes `process/`, `state/` and the project's own files constantly, and a new project asks about none of it: a prompt on every `ls` is one you learn to click through, which protects nothing. What still stops for you is what changes the car — TCC's own DSP and REW writes confirm inside the tool, whatever this is set to. Narrow it here if you want the file traffic in front of you too.",
        "configureModels": "models…",
        "configureModelsTitle": "Models offered in the generator picker",
        "configureModelsBlurb": "omp reports every model it knows about. Tick the ones you have access to — those are what the generator picker offers. Claude runs through the Agent SDK and is always available.",
        "configureModelsFilter": "filter by name, provider or id",
        "configureModelsCount": "{n} models in omp's catalogue",
        # The way to omp's own setup, from the screen whose list depends on it (user, 2026-08-19).
        "configureModelsSetup": "Configure omp…",
        "configureModelsSetupTip": "Open omp's own setup in a terminal — where accounts, API keys \
and sign-ins are configured. That is what decides which models appear in the list above, so when \
it is done and you come back here, the list is read again. TCC holds none of those credentials: \
the terminal and the session in it are yours.",
        "configureModelsSetupOpened": "omp's setup is open in a terminal. When it is done, come \
back to this window — the list is read again.",
        # The MCP server is what a session reaches TCC through. When it did not start, the reason
        # was known minutes earlier and had nowhere to go — now it travels with the message.
        "mcpDown": "The MCP server is not running, so a session has nothing to reach TCC through. \
Start TCC again; if it keeps happening, the reason is here and in the log:",
        "mcpDownLog": "log:",
        "modelClipboardOnly": "clipboard only",
        # A route whose CLI is not installed: shown greyed rather than left out, because an option
        # that is absent reads as one that does not exist (user, 2026-08-19).
        "modelInstallCli": "install the {cli} CLI",
        "modelRecommended": "recommended pair",
        "modelGoneTitle": "That model is no longer offered",
        "modelGone": "This project is set to {model}, which nothing on this machine can run any more — models retire. Pick what should run in its place; the mapping applies everywhere that name still appears, not just here.",
        "modelGoneWhy": "no longer offered on this machine",
        "modelAliased": "{old} now runs as {new} on this machine. Sessions say so, so the record does not claim otherwise.",
        "cliRouteQuiet": "{routes} is installed but listed no models — its own login may have expired. Its entries are missing from the reviewer picker, not gone.",
        "modelFree": "free",
        "ompMissing": "⚠️ omp is not installed — brew install can1357/tap/omp, or pick a Claude model.",
        # Right-click to copy. A hint gets its own item because in this app the tooltip carries
        # what the panel could not fit and what the screen does not say at all — whose bill a route
        # is, what an effort level costs, why a reviewer is clipboard-only.
        "copyValue": "Copy value",
        "copyRow": "Copy row",
        "copyHint": "Copy hint",
        "copySelection": "Copy selection",
        "copyMessage": "Copy message",
        "aiMain": "AI main",
        "aiEffort": "Effort",
        "aiCritic": "AI critic",
        # Below `high` is not offered: it is not a tuning setting. Nothing escalates on its own —
        # the model varies its own depth, but only under the level chosen here.
        "effort_high": "high",
        "effort_xhigh": "x-high",
        "effort_max": "max",
        "effortTip_high": "Enough for routine steps. The floor for tuning work — below this a model agrees too easily.",
        "effortTip_xhigh": "The default, with margin. Right for almost every step of a tune.",
        "effortTip_max": "For the genuinely hard step. Nothing reaches this on its own — a session started lower stays lower, however hard the work turns out to be. Slower, and on a metered route dearer.",
        "effortNextSession": "Effort applies to the next session — this one keeps the level it started with.",
        "note": "prototype · real data (sound_AutoSci) · tuning the form",
        "coffeeBtn": "☕ Buy me a coffee",
        "supportGithub": "💜 GitHub Sponsors",
        "supportMonobank": "☕ Monobank jar",
        # Not "Give feedback": that reads as an invitation to praise, and the things most
        # worth hearing -- a bug, a thing that made no sense, an idea half-formed -- do
        # not feel like feedback to the person holding them (user, 2026-08-21). Naming
        # the destination instead of the genre asks nobody to categorise themselves
        # before they have written the sentence.
        "fbBig": "Message the developer",
        "fbBigTip": "A bug, an idea, a question, "
                    "\u201cthis makes no sense\u201d \u2014 all of it goes here. A screenshot can come with it.",
        "fbHead": "Feedback on the TCC prototype",
        "fbHint": "Tell us what you like / what to change. Use the B / I / list buttons — no "
                  "need to type markdown by hand.",
        "fbPh": "Your feedback on the prototype…",
        "fbCancel": "Cancel",
        "fbSendGithub": "Send to GitHub →",
        "fbSendForm": "Send via form →",
        "fbVia": "How to send:",
        "fbViaGithub": "GitHub issue (I have an account)",
        "fbViaForm": "Google Form (no account needed)",
        "dialog": "AI dialog",
        "dialogSub": "Generator ↔ Critic ↔ Arbiter",
        "planTitle": "Plan — Fact",
        "planSub": "phases + steps",
        "focus": "◆ IN FOCUS NOW",
        "measSub": "measurement task",
        "confirmAlways": "Don't ask again for this in this project",
        "gateAuto": "Don't ask at all (auto)",
        "gateAutoTip": "Harness tools (shell, file reads, edits) run without asking. TCC's own "
                       "DSP and REW writes still ask — those are the ones that change the car.",
        "autoAllowed": "Auto-allowed <code>{tool}</code> — asking about it is off for this project.",
        "questionCancelled": "Question withdrawn — the turn can continue.",
        "questionWithdrawn": "The agent took that question back.",
        "questionWaiting": "Waiting for your answer",
        "questionFreeText": "Type your answer below — this one has no options to pick.",
        "questionRole": "QUESTION",
        "composerAnswer": "Answer, or type your own…",
        "composerQueue": "Message the Generator… (goes out when this turn ends)",
        "composer": "Message the Generator…",
        "queueWaiting": "⏳ {count} message(s) of yours will be sent when this turn ends",
        "queueSendNow": "Send now",
        "newBelow": "↓ New below · {count}",
        "newBelowTip": "New messages arrived while you were reading. First click goes to where "
                       "they start, a second one to the very bottom.",
        "messageNotSent": "Not sent: the session stopped. Your text is back in the field.",
        "quitSaving": "Saving before quitting — waiting for the model to write the project down. The window closes on its own when it lands.",
        "send": "Send",
        "stop": "Stop",
        "notVisible": "I don't see that change",
        "notVisibleHint": "Tell the AI that something it changed did not show up here, so it "
                          "re-checks against disk instead of restating the claim.",
        "notVisibleSent": "Flagged for the AI: <b>something it reported is not visible here</b> "
                          "— it will re-verify against disk.",
        "agentThinking": "Working…",
        "agentFailed": "Session error",
        "confirmAllowed": "Arbiter <b>allowed</b> <code>{tool}</code>.",
        "confirmDenied": "Arbiter <b>denied</b> <code>{tool}</code>.",
        "modelUnchosen": "— choose a model —",
        "startSessionNoModel": "Choose a generator model first.",
        "startSessionReady": "Start a session on {model}. Nothing runs until you do.",
        "startSessionRunning": "A session is already running.",
        "restartSession": "▶ Restart on {model}",
        "restartSessionTip": "Neither harness can change model mid-conversation — this ends the running one and starts a new session.",
        "sessionStarting": "Starting {model} — the first turn reads the skill and the project state, so it is slow.",
        "sessionHandoff": "Saving the project state before the model changes…",
        "sessionHandoffSave": "Asking the model to write what it knows to the project files…",
        "sessionHandoffQuit": "Saving before closing — asking the model to write what it knows "
                              "to the project files…",
        # Qt's own labels on these three are in Qt's language, not the app's — so they are ours.
        "quitSaveSave": "Save the turn",
        "quitSaveDiscard": "Don't save",
        "quitSaveCancel": "Stay",
        "quitSaveTitle": "Save before closing?",
        "quitSaveBody": "A session is running.\n\nWhat it has learned this turn is not on disk "
                        "until it writes it — closing now loses that. Saving costs one turn.",
        "sessionHandoffFresh": "Saving first, then starting a new session with an empty context…",
        "sessionRestarted": "Session ended: restarting on the newly picked model.",
        "dialogIdle": "not started · {model}",
        "dialogNoModel": "no model chosen",
        "startSession": "▶ Session in TCC",
        "openTerminal": "⧉ Terminal",
        "terminalOpened": "Opened a terminal running <code>{cli}</code> in the project folder. It picks up TCC through <code>.mcp.json</code>; approve the <b>tcc</b> server on first run.",
        "criticClipboard": "No reviewer API or CLI was reachable, so the package is on your <b>clipboard</b>. Paste it into any AI chat, then paste the reply back here — the loop still works, it just goes through you.",
        "criticFailed": "Reviewer call failed: {detail}",
        "criticNotReady": "The reviewer has nothing to read yet. It re-reads the project from disk on every call, and this folder has not been through intake — the contract and the car's context are written when a tune starts. The channel itself is fine; start the tune and the reviewer works from the first proposal onward.",
        "criticNever": "Critic: not called yet",
        "curveSendMarkers": "Markers",
        "curveSendDelays": "Delays",
        "curveShift": "delay",
        "curveShiftTip": "Hold the chosen driver back — the radio picks which one. It starts on whichever arrives FIRST, the natural choice on a first pass; negative is allowed, because on a later pass you are correcting a channel that already carries a delay. What cannot go below zero is the channel's TOTAL, and the reading says so when the ledger is known. Steps by what this DSP lets you type. Nothing is applied: the reading goes out as a proposal.",
        "curveDelayHead": "delay, to align (proposed, not applied):",
        # The all-pass row (CURVE-ANALYSIS-PLAN.md step 4). `APF1`/`APF2` are the ledger's own
        # names for the band type and are not translated anywhere; what is said around them is.
        "curveApfLabel": "all-pass:",
        "curveApfNone": "—",
        "curveApfTip": "An all-pass for the driver the radio has chosen — the same driver the delay \
box edits. It changes NO level and rotates the phase around f0: APF1 turns −90° at f0 (0 → −180° \
overall), APF2 turns −180° at f0 (0 → −360°), and Q says how much of that turn happens next to f0. \
On the frequency response the curve does not move; on the phase it rotates; on either, the \
predicted sum (Σ) shows what that does to the joint — which is the point. On the impulse the drawn \
trace stays as captured (an all-pass smears an impulse); the strip's sum carries it. Nothing is \
applied: it goes out as a proposal in the reading, in the ledger's own words (APF2 250 Hz Q 0.71). \
And an all-pass does not fill a single-driver null — only the summation of two overlapping drivers \
can be re-tuned by rotating phase, so read it against the sum, never against one curve. The maths \
is the skill's own (dsp_math), never a second copy here.",
        "curveApfKindTip": "Which order. APF1: f0 alone, −90° there — the gentler quarter turn. \
APF2: f0 and Q, −180° there — what an APF2 slot in a PEQ bank takes. Two APF1 at one f0 are one \
APF2 with Q 0.5.",
        "curveApfF0Tip": "The frequency the rotation is centred on. Put it where the joint is — \
the crossover frequency between the two drivers being summed.",
        "curveApfQTip": "How much of the 360° happens next to f0 (APF2 only). 0.71 turns over \
about an octave and a half either side of f0; a higher Q turns faster and holds still less well \
under the drift a real car has — the skill's own search stops at 4.",
        "curveApfHead": "all-pass, to rotate phase (proposed, not applied):",
        "curveApfNoMaths": "no all-pass can be simulated: the skill's filter maths could not be \
loaded ({error})",
        "unitMs": "ms",
        "unitSmp": "smp",
        # A delay set is only defined up to a common offset — see `curve_view.proposed_delays`.
        # The set is stated FROM one driver, and this names it so nobody has to work out which of
        # the numbers is the origin, or why one of them is zero.
        "curveDelayRelative": "Relative to {name}, which takes none: only the differences between \
these drivers were measured, so the set is stated from the one that needs the least.",
        "curveDelayLands": "arrival {was} → {now} ms",
        "curveDelayTotal": "channel → {total} ms",
        "curveDelayBelowZero": "⚠ below zero — the channel cannot go there",
        "curveBankImpossible": "One or more of these takes a channel below zero, so the set as it \
stands cannot be applied — say which reference to move instead.",
        "curveBankLabel": "delays read:",
        "curveBankLabelIn": "delays read in {set}:",
        # The three buttons that took the place of the paragraphs under the plot (user,
        # 2026-08-18). Each NAMES what is behind it and shows it on hover; the count is on the
        # bank's own button because "how many drivers have I read" is the part worth seeing
        # without hovering anything.
        "curveBankBtn": "Delays read ({n})",
        "curveSumNoteBtn": "Σ forecast",
        "curveGuidesTip": "Take every guide off the picture: the markers, the levels, the cross \
line and its dots. Nothing is lost — each one comes back exactly where it was, and the reading \
stays the same sentence, because a marker you cannot see is still a number you took. While they \
are hidden they cannot be dragged.",
        "curveStripLinkTip": "Follow the plot's frequency scale. On the phase the strip and the \
plot are the same frequencies, so one zoom moves both and what you see at 3 kHz above is at 3 kHz \
below. Switch it off to zoom into a null on its own, and back on to line them up again. Not \
offered on the impulse: that plot's axis is time.",
        # Named after the thing it reports rather than after the act of reporting (user,
        # 2026-08-19: "назвати кнопку і хінт «Маркери»"). It is the third "Markers" in this window
        # — send, clear, and this one — and that is the point: one word for one group of controls.
        "curveReadoutBtn": "Markers",
        "curveBankEmpty": "no delays read yet — set one above and it is kept per measurement",
        "curveClearLabel": "clear:",
        "curveClearDelay": "Delays",
        "curveClearMarkers": "Markers",
        "curveBankAsk": "Delays I have read off the curves, for ANALYSIS ONLY — do not write \
these anywhere and do not treat them as a change:",
        "curveBankConvention": "Convention: every measurement shares one time origin (0 ms on \
the impulse axis). Each number below is added to that measurement's arrival AS CAPTURED; the aim \
is for every driver to land on the same arrival.",
        "curveBankArrival": "arrival",
        "curveBankChannel": "channel",
        "curveBankSpread": "Spread of the resulting arrivals across the {n} drivers placed: \
{spread} ms.",
        "curveBankAtZero": "On screen, no shift entered (0). That may be the reference the rest \
was measured from, or simply a driver not got to yet — the data here cannot tell those apart: \
{names}",
        "curveBankUnplaced": "NOT placed — no reading taken on these yet, so they are absent \
from the picture above and are NOT to be assumed at zero: {names}",
        "curveBankNotForWriting": "Tell me whether this set is coherent: which arrivals it \
implies, whether any of it looks like a measurement error rather than a tuning, and what you \
would check next. These are readings off the curves, not a target — aligning arrivals exactly \
has not by itself fixed stage accuracy in this car, so treat them as evidence and say what you \
would change and why. Nothing here is applied.",
        # The all-pass half of the same set (`delay_bank.as_sentence`, `allpasses=`). Its own head
        # when there are no delays in the set at all, and its own caveat: the effect was simulated
        # on the sweeps in hand, never checked against a summation sweep.
        "curveBankAskApfOnly": "All-pass filters I have dialled on the measured curves, for \
ANALYSIS ONLY — do not write anything.",
        "curveBankApf": "All-pass, dialled per driver while watching the predicted sum (proposed, \
not applied; unit magnitude, phase only; APF1 = −90° at f0, APF2 = −180° at f0):",
        "curveBankApfCaveat": "Simulated on the sweeps in hand by rotating the measured phase; NOT \
verified by a summation sweep. Say whether the rotation fixes the joint or only moves the problem \
(and drags the timing above f0 with it), and what capture would confirm it.",
        "curveNoMarkers": "Drag a marker onto the point you mean.",
        "curveMarkerModel": "model",
        "curveMarkerYou": "you",
        # Two markers, always — they stopped being one-per-curve on 2026-08-19 (user: "число
        # маркерів збільшується зі збільшенням числа кривих — а вони у нас постійні"). With no
        # reading from the model to name them after, they are numbered: a bare digit on the plot,
        # where the line is a hand's width from the label, and "marker N" in a sentence, where it
        # is not.
        "curveMarkerOne": "1",
        "curveMarkerTwo": "2",
        "curveMarkerN": "marker {n}",
        "curveTitle": "Where exactly?",
        "curveAxes_v": "Markers read frequency (vertical)",
        "curveAxes_h": "Markers read level (horizontal)",
        "curveAxes_vh": "Markers read both, placed separately",
        "curveAxes_vhs": "One point on the curve gives both — the level follows the frequency",
        "curveAxes_vx": "One vertical line: read BOTH curves at that x, and how far apart they are",
        "curveAxes_hx": "One horizontal line: read where EACH curve reaches that level (the crossing nearest the middle of the view)",
        # Vx and Hx answer "how far apart are THESE TWO", and that question has no N-curve form —
        # fifteen pairwise gaps are not a reading. So with more than two curves plotted the tuner
        # names the two; the per-curve markers keep answering for the rest.
        "curveCrossPairTip": "Which two curves Vx and Hx compare. They read one gap between one \
pair, so with more curves on screen you say which pair — the ordinary V/H/VH markers still read \
every curve, one number each.",
        # The predicted sum. The engine's own sentences (the summability verdict, the timing
        # assumption) are English by design and are NOT here — these are the labels that frame
        # them; see `core/curve_sum.TIMING_ASSUMPTION`.
        "curveSumTip": "Σ — draw what these drivers do TOGETHER: the complex sum of the curves on \
screen, dashed, in dB, with each driver's delay already applied. On the phase it goes over the \
plot on the right-hand axis; on the impulse it gets a strip of its own underneath, because there \
the plot's axis is time and the sum's is frequency. It is arithmetic on measurements you already \
have, so a guess costs nothing and nothing is written anywhere. It only means something if every \
measurement was captured against ONE shared timing reference; the Σ button under the plot carries \
the verdict — what has been checked and what has not.",
        "curveSumHead": "Predicted sum, dashed, in dB:",
        # Signed, and worded for both signs on purpose: the same reading is −18 dB at a null and
        # +6 dB for a pair that adds up everywhere, and "worst cancellation +6 dB" reads as a
        # contradiction. `curve_sum.deepest_null` explains why +6.02 is the honest answer there.
        "curveSumWorst": "Deepest point of the sum: {depth} dB against the loudest single driver \
there, at {hz} Hz.",
        "curveSumNone": "No sum drawn.",
        # Reachable only when pyqtgraph refused to give this view a surface to draw on. Named
        # rather than left as a dead toggle: the tuner is entitled to know the button is not
        # broken, the plotting library is.
        "curveSumNoPlot": "This view could not build the axis the sum is drawn on, so there is \
nowhere to put it. Everything else in the window is unaffected.",
        "curveSumTooFew": "One curve is not a sum: put a second measurement on screen.",
        "curveSumNoData": "These curves carry no magnitude and phase to add up — they did not \
come from a REW sweep.",
        # The glossary's own groups, which are the sets a tune is argued about (user, 2026-08-18:
        # "Ws, Ms, TWs, SW+Ws, L, R, ALL"). The type is on the row because `L` is a side and `Ws`
        # is a pair, and a list of bare names does not say which.
        # `fill:` and not `group:` — the group and version pair is a SHORTCUT that writes into the
        # chips, not a second way of saying what is plotted (user, 2026-08-18: "хай 'Обрати' буде
        # основним, а групи це допомога швидкого вибору"). A label that named it as a selector was
        # half of why the window had two rows that seemed to disagree.
        "curveGroupLabel": "fill:",
        "curveGroupNone": "— no group —",
        "curveGroupKind_pairs": "pair",
        "curveGroupKind_joints": "joint",
        "curveGroupKind_sides": "side",
        "curveGroupKind_combos": "combo",
        "curveGroupNoGlossary": "— no glossary in this project —",
        "curveGroupTip": "Fill the selection with a whole group at once — the woofers, the mids, \
sub+woofers, one side, everything. The names come from this car's glossary, and the sweeps chosen \
are the ones at the config version beside it. Nothing is fetched that the group does not name: a \
member REW has no sweep for is reported, not skipped. It FILLS and then lets go: take a chip off \
afterwards and nothing re-fills, which is how you hear what one driver is doing to the joint.",
        "curveGroupVersionTip": "Which capture series the group's sweeps are taken from — the DSP \
config they were measured under, spelled `_N` in a REW title and named the same way in the capture \
panel. It starts on the series the curves already on screen share, or on the newest this car has \
for those drivers, and you can move it.",
        # Named, never skipped: `curve_sum` sees only what it was handed, so it cannot tell a sum
        # of the woofers from a sum of one woofer. This sentence is the only place that can.
        "curveGroupMissing": "{group} at _{version}: {names} — not in REW. What is drawn is the \
sum of a different set.",
        "curveGroupEmpty": "{group} at _{version}: REW holds no sweep of any member, so nothing \
was changed.",
        "curveChooseBtn": "Choose… ({n})",
        "curveChooseTip": "Tick any measurements you like — the sum takes as many as you give it. \
The menu stays open, so a whole side is one trip through the list. Everything ticked is a chip \
above, in its curve's own colour; a group beside this fills the same chips in one go.",
        # The chips: the ONE visible selection. Advisor (Gemini 3.1 Pro, 2026-08-18) — whoever
        # commits a delay off a plotted sum has to be certain what fed it, so every contributing
        # measurement is named on screen and every one can be taken off from where it is named.
        "curveChipRemoveTip": "Take {title} off the plot. The rest stay where they are and the sum \
is recomputed without it — which is how you hear what this one driver is doing to the joint.",
        "curveChipOnlyTip": "The only curve on screen. Add another before taking this one off — a \
window plotting nothing has nothing to say.",
        "curveChipMissingTip": "REW gave no curve for {title}, so it is not on the plot even though \
it is selected — and it is not in the sum either. It is shown faint for that reason.",
        "curveAt": "at",
        "curveZoomAll": "Show everything the capture holds",
        "curveZoomAllShort": "A",
        "curveZoomDetail": "Back to the span this opened on",
        "curveZoomDetailShort": "D",
        "curveZoomOut": "Zoom out",
        "curveZoomOutShort": "−",
        "curveZoomIn": "Zoom in",
        "curveZoomInShort": "+",
        "curveKind_impulse": "impulse",
        "curveKind_fr": "frequency response",
        "curveKind_phase": "phase",
        "curveRtaOnly": "Showing the frequency response: {titles} — an MMM capture, and REW has \
neither an impulse nor a phase for one.",
        "curveRtaTip": "An MMM capture: REW has no impulse and no phase for it. Switch to the \
frequency response to put this one on the plot.",
        "curveKindRtaTip": "Not for an MMM capture — REW has no impulse and no phase for one. \
Choose sweeps (sw) above to read this.",
        "curveBtn": "Curves — put a marker where you mean",
        "curveNothing": "No measurements to plot yet — read them from REW first.",
        "curveLoading": "Reading the curves from REW…",
        "curveFailed": "Could not read from REW: {error}",
        "modelMissingRow": "{key} — not available here",
        "modelMissingTip": "This project asks for a model this machine does not offer. It stays selected and stays red until you choose another — nothing is redirected behind you.",
        "modelUnconfirmed": "from last launch",
        "attachTip": "Attach a screenshot — saved into the project, the model reads the file",
        "attachTitle": "Attach a screenshot",
        "attachClear": "Clear",
        "attachEmptyMac": "⌘⌃⇧4 copies a screenshot to the clipboard (⌘⇧4 saves it to the Desktop instead). Then press ⌘V here.",
        "attachEmptyWin": "Win+Shift+S copies a screenshot to the clipboard. Then press Ctrl+V here.",
        "attachEmptyOther": "Copy a screenshot to the clipboard, then press Ctrl+V here.",
        "attachCaption": "What is on it — e.g. \"w-L impulse, first peak\"",
        "criticWarnTitle": "About the reviewer",
        "criticSubstituted": "substituted",
        "criticAnswered": "answered by {model}",
        "criticSameVendor": "same vendor as the Generator",
        "criticSameVendorTip": "The reviewer and the Generator are both {vendor}. It still reviews, but a reviewer picked for cross-vendor independence has stopped being one — weight its agreement lower, or restore a different vendor.",
        "sdkNoLogin": "claude is not signed in",
        "sdkNoLoginTip": "Claude models run through your own `claude` session — TCC has no account of its own and cannot log in for you. Until you sign in, this route cannot answer, whatever the picker says. In a terminal, run:\n\n    {cmd}",
        "criticStatus": "Critic · {model} · {ago}",
        "sessionResumed": "resumed",
        "sessionNew": "new session",
        "editChipLabel": "Project param edit",
        "editReasonsQ": "Why?",
        "reasonForgot": "skill didn't save",
        "reasonManual": "I changed something manually",
        "editStartForgot": "◆ Editing project parameters — flagged: the skill may not have "
                            "saved a recent change. Describe what should be in the ledger; "
                            "I'll check and fix it.",
        "editStartManual": "◆ Editing project parameters — you changed something by hand. "
                            "Tell me what and where; I'll log it in the ledger so future "
                            "recommendations account for it.",
        "editDoneForgot": "✓ Ledger checked: <code>Rear R Full</code> delay was 9.5 ms in the "
                           "dialog but 8.0 ms on disk — fixed, re-saved as 9.5 ms.",
        "editDoneManual": "✓ Logged: <code>Front R High</code> gain 1.4 → 1.0 dB (manual). "
                           "Ledger updated and re-attested.",
    },
    "uk": {
        "theme": "тема",
        "dspPanel": "DSP",
        "projectParams": "Параметри проєкту",
        "chanSum_channels": "Канали",
        "chanSum_virtual_channels": "Віртуальні канали",
        "chanSum_physical_outputs": "Вихідні канали",
        "chanSum_inputs": "Входи",
        "chanSumOff": "{total} ({off} вимкнено)",
        "cfgLanguage": "Мова",
        "cfgGenerator": "ШІ генератор",
        "cfgEffort": "Зусилля",
        "cfgCritic": "ШІ радник",
        "cfgTheme": "Тема",
        "cfgGate": "Дозволи",
        "cfgThemeLight": "світла",
        "cfgThemeDark": "темна",
        "systemParams": "Параметри системи",
        "audioAnalysis": "Аудіо аналіз авто",
        "leftNoProfile": "Процесор ще не відомий. Почни сесію й скажи, який DSP у цьому авто — профіль пишеться щойно його названо, і панель наповниться.",
        "leftNoLedger": "Налаштувань ще не знято. Дерево наповниться, щойно буде записано перший знімок леджера — це вже під час тюнінгу.",
        "planEmpty": "Плану ще немає. Скіл записує його, коли сесія входить у фазу — панель наповниться, щойно з'являться й почнуть закриватися кроки.",
        "planNoProject": "Проєкт не відкрито.",
        "noDataYet": "Даних поки нема",
        "openQuestions": "Відкрито",
        "openQuestionsTitle": "Відкриті питання",
        "curveRoundEmpty": "{round}: замірів цього проходу в REW немає — відкрито інший проєкт, або їх видалили.",
        "seriesItem": "серія {v}",
        "logError": "Щось пішло не так: {error} — деталі в {path}",
        "rewPort": "Порт REW",
        "rewOnlineTip": "REW: онлайн",
        "rewOfflineTip": "REW: недоступний на цьому порту.\nAPI є лише в БЕТА-збірках REW — у релізній версії вкладки API немає взагалі (roomeqwizard.com/beta.html).",
        "createProject": "+ Створити новий проєкт",
        "refreshProjectTip": "Перечитати проєкт з диска (профіль, леджер)",
        "selfSection": "Власні налаштування TCC",
        "selfAliasTitle": "Діють псевдоніми моделей: {n}",
        "selfAliasDetail": "",
        "selfAliasNoneTitle": "Псевдонімів немає на рівні самого TCC",
        "selfAliasNoneDetail": "Це не те саме, що «пікер запускає те, що показує»: скрипт рецензента підмінює теж, рівнем нижче — він падає з API на локальний CLI, а той запускає ту модель, на яку його налаштовано. Рядок нижче звіряє, хто відповів насправді.",
        "selfReviewerNeverTitle": "Рецензента в цьому проєкті ще не викликали",
        "selfReviewerNeverDetail": "Поки він не відповів, звіряти нема з чим. Налаштована модель — це заява; виклик — це доказ.",
        "selfReviewerOkTitle": "Остання рецензія прийшла від {model} — саме від тієї, яку обрано",
        "selfReviewerDiffTitle": "Відповів не той рецензент, якого обрано",
        "selfReviewerDiffDetail": "Обрано {wanted}; відповів {answered}. Цього не показує ні пікер, ні `substituted` — скрипт рецензента падає з Gemini API на локальний CLI (досить 404), а CLI запускає ту модель, яку в ньому обрано. Перевір, що вибрано в `agy`, або прийми, що рецензент саме цей.",
        "selfAliasCrossVendor": "{keys} тепер запускає модель ІНШОГО вендора, ніж обрано. Якщо це рецензент — крос-вендорна рецензія припинилась: сенс другого вендора саме в тому, що він не поділяє сліпих плям Генератора.",
        "selfAliasFix": "Прибрати всі псевдоніми",
        "selfAliasFixed": "Прибрано псевдонімів: {n}. Пікери знову запускають те, що показують.",
        "selfCatalogueTitle": "Встановлений, але мовчить: {clis}",
        "selfCatalogueDetail": "Цей CLI є в PATH, а список моделей повернувся порожнім — тож його маршрут зник із пікерів. Виглядає це рівно як «не встановлено», і саме так збережена модель починає здаватись зниклою.",
        "selfCatalogueFix": "Спитати CLI ще раз",
        "selfCatalogueFixed": "Каталог оновлено: моделей {n}.",
        "selfCatalogueOkTitle": "Кожен встановлений CLI відповів своїми моделями",
        "selfRecommendOkTitle": "Рекомендована пара тут доступна",
        "selfRecommendTitle": "Ніщо з наявного не підпадає під рекомендоване: {roles}",
        "selfRecommendDetail": "Рекомендація — це клас, а не назва моделі ({pairs}, станом на {since}) — тож нова версія будь-якої з них позначається сама. Якщо не підпадає ніщо, значить сам клас пішов у минуле або його маршрут не встановлено. Обирай свідомо: запасної рекомендації немає.",
        "selfCheckFailed": "Ця перевірка не змогла виконатись",
        "diagFixDone": "Виправлено: {what}",
        "diagTitle": "Діагностика проєкту",
        "diagBtnTip": "Що TCC знайшов на диску: машинні файли скіла, перевірені",
        "diagChecking": "Перевіряю…",
        "diagOk": "OK — виправляти нічого",
        "diagIssues": "Знайдено проблем: {n}",
        "diagNoIssues": "Проблем немає",
        "diagAsk": "Попросити сесію",
        "diagAskText": "Діагностика повідомляє про проблему в {subject}, словами самої перевірки:\n\n    {issue}\n\nВиправ це командами скіла (TCC ці файли не пише). Коли зробиш — скажи, яку команду виконав: я перезапущу `contract.py check`, і буде видно, чи рядок зник.",
        "diagAskedAgo": "попросили {ago}, досі тут",
        "diagAgoNow": "щойно",
        "diagAgoMin": "{n} хв тому",
        "diagFiles": "Машинні файли",
        "diagCross": "Перехресні перевірки",
        "diagOpenQ": "Відкриті питання (інтейк не завершено)",
        "diagMissing": "немає",
        "diagUnavailable": "Перевірка контракту недоступна",
        "diagCheckedAt": "перевірено {at} · {ms} мс",
        "diagTabProject": "Проєкт",
        "diagTabInstall": "Установка",
        "diagTabLog": "Логи",
        "diagReport": "Повідомити про проблему",
        "titleUpdate": "є оновлення",
        "updWhy_source_checkout": "запущено з вихідників — онови через git",
        "updWhy_no_network": "не достукався до GitHub",
        "updWhy_not_found": "не знайдено на цій машині",
        "updWhy_not_a_checkout": "не git-checkout, тож оновлювати на місці нічого",
        "updWhy_on_branch": "на гілці — це чийсь робочий каталог, а не встановлений реліз",
        "updWhy_submodule": "це сабмодуль checkout — онови через git, у",
        "updWhy_dirty": "має незакомічені зміни, тому не чіпаю",
        "updWhy_no_manifest": "у маніфесті немає версії",
        "updWhy_git_failed": "git сказав",
        "updTcc": "Оновити ТСС",
        "updSkill": "Оновити Скіл",
        "updTccName": "ТСС",
        "updSkillName": "Скіл",
        "updChecking": "перевіряю оновлення…",
        "updAvailable": "{what} {here} — вийшла новіша: {there}",
        "updNewerBuild": "{what} {here} — вийшла новіша збірка цієї ж версії",
        "updNewerBuildOn": "{what} {here} — вийшла новіша збірка від {date}",
        "updCurrent": "{what} {here} — актуальна",
        "updUnknown": "не вдалося спитати GitHub — немає мережі, або в нього свій день",
        "updWorking": "оновлюю…",
        "updSkillDone": "Скіл тепер {version} — переоткрий сесію з ШІ, щоб він її підхопив",
        "updTccHanded": "Термінал відкрито і він чекає, поки ТСС закриється. Закрий ТСС — "
                        "оновлення піде саме, потім запусти знову.",
        "updFailed": "не вийшло: {why}",
        "diagLogNone": "лог-файла немає — цей запуск пише лише в термінал",
        "diagInstallBlurb": "Що встановлено на цій машині — версії, звідки взялася кожна частина, \
які CLI відповідають. Скопіюй у повідомлення, коли про щось звітуєш: це відповідає на перші пʼять \
питань, які тобі поставлять.",
        "diagInstallReading": "читаю…",
        "diagInstallCopy": "Копіювати",
        "diagInstallCopied": "Скопійовано",
        "diagRefresh": "Перевірити ще раз",
        "diagClose": "Закрити",
        "diagStripIssues": "Контракт проєкту: проблем {n} — див. Діагностику (⚕)",
        "diagStripError": "Перевірка контракту недоступна: {error}",
        "projectRenderFailed": "Не вдалося намалювати проєкт із диска — на екрані лишився "
                               "останній робочий вигляд. {error}",
        "staleStrip": "{what} — перезняти каналів: {n} ({codes})",
        "missingRecord": "Не записано: {what} — {why}.",
        "criticSaved": "Текст збережено у {path}",
        "acousticsNone": "Карти дефектів ще немає. Фаза 0 міряє, що ця машина робить зі звуком, і рядки з'являться тут — кожен із тим, що з ним можна й чого не можна.",
        "flawHypothesis": "не підтверджено",
        "flawEvidenceHead": "Прочитано з:",
        "flawNoWhy": "Причину із цим записом не зафіксували — тільки сам вимір.",
        "flawAllChannels": "усі канали",
        "flawAction_notch": "різати",
        "flawAction_leave": "лишити",
        "flawAction_no_boost": "не піднімати",
        "flawAction_geometry": "геометрія",
        "flawAction_delay": "затримка",
        "flawAction_crossover": "кросовер",
        "flawKind_room_gain": "підйом салону",
        "flawKind_modal_peak": "мода салону",
        "flawKind_cabin_null": "провал салону",
        "flawKind_sbir": "SBIR",
        "flawKind_floor_bounce": "відбиття від підлоги",
        "flawKind_driver_resonance": "резонанс динаміка",
        "flawKind_non_min_phase": "не-мінімальна фаза",
        "flawKind_thd_spike": "сплеск спотворень",
        "flawKind_pair_suckout": "провал пари",
        "supervisorUnbacked": "Ці кроки закриті, а їхні докази не вказують ні на що на диску "
        "чи в REW:<br>{steps}<br>Або робота записана там, куди я не бачу, або її не було.",
        "recordTargetCurve": "цільова крива",
        "recordTargetCurveWhy": "фаза 0 її обирає, і всі наступні фази міряються проти неї, "
                                "тож на диску не лишилось, яку саме криву взяли",
        "measNoTask": "Завдання на зняття ще немає. Воно виводиться з фази, глосарія імен і поточної версії леджера — тож з'явиться, коли інтейк закріпить назви каналів.",
        "measPhaseNoCapture": "Ця фаза не робить замірів — вона працює з уже знятою серією. Наступне завдання на зняття зʼявиться разом із фазою, якій воно потрібне.",
        "noProjectMeas": "Немає проєкту — знімати поки нічого.",
        "npTitle": "Новий проєкт",
        "npFolder": "Тека проєкту",
        "npBrowse": "Огляд…",
        "npProfile": "Профіль DSP",
        "npAddNew": "+ Додати новий (немає в списку)",
        "npVendor": "Виробник DSP",
        "npVendorPlaceholder": "напр. Helix, Musway",
        "npModel": "Модель DSP",
        "npModelPlaceholder": "напр. DSP Ultra S, M6V4",
        "npRunVia": "Вести onboarding через",
        "npRunInApp": "У додатку (Claude)",
        "npAiModel": "Модель ШІ",
        "npTerminalModel": "Модель (необовʼязково)",
        "npTerminalModelPlaceholder": "напр. opus, gemini-2.5-pro — пусто = дефолт CLI",
        "npOnboardingHint": "Скористайся скілом autosound-tuning для onboarding DSP-профілю. "
                            "Підключись до MCP-сервера 'tcc' цього проєкту (див. .mcp.json) і "
                            "виклич його тул check_existing_profile першим, для vendor={vendor} "
                            "model={model}. Веди інтерв'ю {language}.",
        "langNameEn": "англійською",
        "langNameUk": "українською",
        "npSeed": "Системні параметри",
        "npSeedNone": "Спитати в інтерв'ю (з нуля)",
        "npSeedFrom": "Скопіювати з наявного проєкту…",
        "npSeedPlaceholder": "Тека проєкту, у якій є project.json",
        "npSeedFindings": "…і те, що там виміряно (акустичні вади, відкриті питання)",
        "npSeedNotAProject": "Тут нема читабельного project.json — копіювати нема чого.",
        "npSeedSummary": "{car} · {dsp} · каналів: {channels}",
        "npSeedNote": "**Успадковано з `{source}` ({when}).** Профіль системи скопійовано з того "
                      "проєкту, а не написано тут — звірте його з цією збіркою, перш ніж на нього "
                      "спиратись.",
        "npSeedFailed": "Нічого не скопійовано: {problem}",
        "npSeedDone": "Системні параметри скопійовано з «{source}»: {files}. Вони успадковані, а не "
                      "виміряні тут — звірте їх із цією збіркою.",
        "npSeedHint": "Системні параметри скопійовано в цю теку з проєкту «{source}»: СПОЧАТКУ "
                      "прочитай project.json і dsp_profile.json і пройди їх разом із людиною, "
                      "виправляючи те, що відрізняється. Не проси описувати машину з нуля.",
        "riTitle": "Імпорт сесії Resonalyze",
        "riFilePlaceholder": "Сесія віртуального DSP Resonalyze (.json)",
        "riAgainst": "Звірено з",
        "riNoProfile": "У проєкті нема dsp_profile.json — ні з чим звіряти. Усе нижче показано, "
                       "але нічого не перевірено.",
        "riScene": "Стереосцена",
        "riSceneNote": "Це те, до чого ЦІЛИТЬСЯ Auto balance у Resonalyze. Результат уже всередині "
                       "гейнів і затримок кожної ноги нижче — не вводьте його вдруге.",
        "riUnbound": "жоден канал цього проєкту не збігся",
        "riDormant": "є у файлі, але НЕ діє (вирішує тип кросовера)",
        "riDropped": "відкинуто: прозора смуга, нічого не додає",
        "riNotChecked": "Не перевірено, бо профіль цього DSP не називає межі",
        "riBindNone": "— лишити непривʼязаною —",
        "riBlocked": "Цей процесор не прийме план у такому вигляді: відмовлено значень — {refused}, "
                     "непривʼязаних ніг — {unbound}. Нічого не округлюється під залізо і нічого не "
                     "записується.",
        "riClear": "Жодна заявлена межа цього DSP не відмовляє жодній з {legs} ніг. Це відповідь "
                   "про ЗАЛІЗО — режим PC-Tool (Fine EQ) може бути вужчим, і перемикається він на "
                   "екрані. Занести рядки — робота тюнінгового гейта: скопіюйте їх і запропонуйте "
                   "з термінала.",
        "riCopyRows": "Скопіювати рядки (JSON)",
        "riCopied": "Рядки в буфері обміну.",
        "riFailed": "Цей файл не вдалося прочитати:",
        "riClose": "Закрити",
        "riImport": "Налаштування з сесії Resonalyze…",
        "npSeedNoInterview": "Разом із ним прийде dsp_profile.json, тож інтерв'ю про можливості "
                             "не буде — питати нема про що, процесор уже описаний. Виберіть інший "
                             "DSP вище — і воно піде як завжди.",
        "npSeedNoSkill": "Скіл autosound-tuning тут недоступний, а копіювання живе в ньому — "
                         "встановіть скіл або заповніть новий проєкт вручну.",
        "npSeedOpen": "У успадкованому профілі DSP ще {open} фактів, яких ніхто не підтвердив.",
        "groupFieldsUnknown": "керування ще не перелічено",
        "menuProject": "Проєкт",
        "menuSession": "Сесія і моделі",
        "menuView": "Вигляд",
        "menuTools": "Інструменти",
        "menuHelp": "Довідка й підтримка",
        "menuLanguage": "Мова",
        "menuReload": "Перечитати цей проєкт з диска",
        "menuZoomIn": "Більший текст",
        "menuZoomOut": "Менший текст",
        "menuDiagnostics": "Діагностика й оновлення…",
        "menuTargetTool": "Крива-ціль (відкриє браузер)",
        "riImportTip": "Бере з сесії віртуального DSP Resonalyze самі НАЛАШТУВАННЯ — по каналах: кросовери, затримку, гейн, полярність і смуги EQ — і звіряє кожне значення з тим, що ваш процесор справді може прийняти. Не сесію цілком, і нічого не записує: відмовляє, а не округлює, і віддає рядки, щоб занести їх через тюнінговий гейт.",
        "menuStartSession": "Почати сесію тюнінгу в TCC",
        "menuTerminal": "Відкрити термінал у цьому проєкті",
        "menuModels": "Налаштувати моделі (OMP)…",
        "menuTheme": "Змінити тему (світла / темна)",
        "menuCopyCar": "Скопіювати авто…",
        "menuCopyCarTip": "Почати проєкт із наявного: авто, обладнання та установка — марка, драйвери по каналах, підсилювачі, мікрофон, DSP та його профіль, глосарій назв. Те, що ВИМІРЯНО в тому проєкті, лишається там, поки ви не попросите. Ви правите те, що відрізняється, замість описувати свою машину заново.",
        "menuModelsTip": "Які моделі можна цьому проєкту — генератор, критик і скільки їм думати. Усе, крім Claude, іде через OMP, тож позначене тут — це те, до чого OMP дозволено тягнутись.",
        "menuButton": "☰ Меню",
        "npCreate": "Створити",
        "npCancel": "Скасувати",
        "projectNewTip": "Тека + DSP + хто веде onboarding. Може ПОЧАТИСЬ І З НАЯВНОГО ПРОЄКТУ: машина, драйвери, глосарій і профіль DSP переїжджають, і ви правите замість того, щоб описувати свою машину заново.",
        "projectOpenTip": "Вказати TCC іншу теку. Порожня теж підходить: вона стане новим проєктом, який наповнить розмова про машину. Після вибору TCC відкриється заново на цій теці — вікно привʼязане до одного проєкту від самого старту.",
        "projectSaveStateTip": "Просить модель записати план, докази й усе, що вона зрозуміла, у файли проєкту. Розмова триває.",
        "projectFreshSessionTip": "Спершу збереже, потім почне з порожнім контекстом на ТІЙ САМІЙ моделі. Це не те саме, що перезапуск на іншій: це для розмови, яка стала довгою й дорогою, тоді як її висновки вже на диску.",
        "gateTitle": "Відкрити проєкт тюнінгу",
        "gateBlurb": "TCC працює з однією текою проєкту і прив'язується до неї на старті. Обери наявну або впиши новий шлях — порожня тека це валідний новий проєкт, її наповнить розмова-інтейк.",
        "gateFolder": "Тека проєкту",
        "gateFolderPlaceholder": "/шлях/до/авто",
        "gateBrowse": "Огляд…",
        "gateOpen": "Відкрити",
        "gateNote": "Обидві моделі запам'ятовуються разом із цим проєктом, а не глобально — інший проєкт має свої. Змінити можна пізніше в нижній стрічці.",
        "projectSwitchTitle": "Змінити проєкт",
        "projectSwitchBody": "TCC прив'язується до однієї теки на старті, тож він перезапуститься на «{name}». Усе, чого поточна сесія не записала на диск, буде втрачено — спершу збережи, якщо це важливо.",
        "projectNone": "⌂ обрати проєкт…",
        "projectOpen": "Відкрити теку проєкту…",
        "projectNew": "Новий проєкт…",
        "projectSaveState": "Зберегти на диск те, що знає модель",
        "projectFreshSession": "Почати нову сесію (збереже й обнулить контекст)",
        "projectReopen": "Теку змінено — відкрий TCC заново, щоб працювати з нею.",
        "sessionSaved": "Стан проєкту записано на диск. Сесія триває.",
        "savedTccOnly": "Власні налаштування TCC на диску. Сесія не запущена, тож просити модель "
                        "щось записати немає про що.",
        "sessionFresh": "Сесію закрито, стан збережено — починаю нову з порожнім контекстом.",
        "generator": "Генератор",
        "preset": "Пресет",
        "target": "Цільова крива",
        "targetToolTip": "Відкрити в інструменті цільових кривих ↗",
        "params": "ПАРАМЕТРИ",
        "virtual": "ВІРТУАЛЬНІ",
        "output": "ВИХІДНІ",
        "inputs": "ВХОДИ",
        "paramsRow": "params · усі параметри таблицею",
        "tabTable": "Таблиця",
        "close": "закрити ✕",
        "outTitle": "OUTPUT — фізичні драйвери",
        "virtTitle": "VIRTUAL — вхідний voicing",
        "colChan": "Канал",
        "eqHint": "Тільки <b>задіяні банди</b> (усі параметри одразу — перевага MUSWAY над "
                  "Helix). APF — це тип банда, не окрема колонка. Bypass — read-only (поки). "
                  "Порожні з 30 сховані.",
        "shared": "спільні частоти:",
        "noShared": "спільних частот нема",
        "band": "банд",
        "legWait": "чекаю",
        "legDone": "готово",
        "legBad": "знятий, не підходить",
        "legSkip": "пропущено",
        "stepTagOkTip": "Закрито, і доказ справді є на диску — названий файл або захват знайдено.",
        "stepTagUnprovenTip": "Скіл закрив крок, але доказ, який він назвав, ні на що на диску не "
                              "вказує: такого файлу немає, і захвату з такою назвою теж.\n\nЦе не "
                              "те саме, що крок без галочки. Той просто не завершено; цей "
                              "відзвітовано як завершений, і за ним нічого немає.",
        "stepTagWaitTip": "Або ще в роботі, або закрито й відтоді знецінено — зміна конфігурації "
                          "означає, що результату більше не можна довіряти, тож треба перезняти.",
        "chanOn": "УВІМК",
        "chanOff": "ВИМК",
        "chanTurnOn": "УВІМКНУТИ",
        "chanTurnOff": "ВИМКНУТИ",
        "chanToggleQueued": "Попросив перемкнути {channel} → {state}. Сесія не запущена, тож запит у черзі: модель отримає його першим ходом наступної сесії.",
        "signalNudge": "TCC почав хід через {count} твій запит з інтерфейсу — розмови не було, а клік не має чекати на неї.",
        "signalNudgePrompt": "Арбітр скористався інтерфейсом. Спершу опрацюй сигнали, перелічені вище, підтверди кожен через ack_signals, і коротко скажи, що зробив.",
        "chanToggleWaiting": "запит · {secs}с",
        "chanToggleLate": "⚠ без відповіді · {secs}с",
        "chanToggleWaitTip": "TCC попросив модель це записати; леджер пише скіл, не TCC. Рядок зміниться, коли модель відповість. Повторний клік лише оновлює очікування, другого запиту не надсилає.",
        "chanToggleAlreadyAsked": "{channel} — уже запитано, чекаю на модель. Вдруге не надсилав.",
        "chanToggleTip": "Попросити модель увімкнути або вимкнути канал. TCC не пише леджер — "
                         "запит іде в сесію, і зміну записує вона.",
        "chanToggleSent": "Попросив перемкнути <b>{channel}</b> → {state}. Модель запише це в "
                          "леджер; дерево оновиться, щойно запис буде.",
        "noSessionForSignal": "Сесія не запущена — запусти, і запит до неї дійде.",
        "chanToggleConfirmTitle": "Перемкнути канал?",
        "chanToggleConfirmOff": "Вимкнути <b>{channel}</b>?\n\nЙого EQ, кросовер і затримка "
                                "живуть у леджері й можуть не пережити вимкнення. TCC це не "
                                "відкотить — зміну записує модель.",
        "chanToggleConfirmOn": "Увімкнути <b>{channel}</b>?\n\nЦе структурна зміна: каналу "
                               "потрібне місце в глосарії, а фізичному виходу — віртуальний "
                               "відповідник. Модель це розрахує й запише.",
        "pillMute": "MUTE",
        "pillOff": "OFF",
        "attempt": "спроба",
        "addStep": "+ додати крок",
        "addStepPrompt": "Ситуативний крок (тільки цей проєкт):",
        "measRead": "Прочитати",
        "measReading": "Читаю з REW…",
        "measReadOk": "Прочитано з REW замірів: {n} · збіглось {matched}, додаткових {extra}",
        "measReadFail": "Не вдалось прочитати з REW: {error}",
        "measReadNoMeas": "У REW немає замірів.",
        "measUsedInStep": "Використано в кроці {steps}",
        "assignNames": "Дати найменування",
        "captureOrderTitle": "Порядок зняття",
        "captureOrderHint": "Обери метод зняття, тоді перетягни, щоб порядок відповідав тому, "
                             "як ти реально знімаєш канали в REW. Зберігається окремо на кожен "
                             "метод і використовується наступного разу.",
        "captureMethodSw": "SW",
        "captureMethodRta": "RTA",
        "captureMethodRtaGroup": "RTA GROUP",
        "captureScanMismatch": "У REW знайдено нових замірів: {found}, очікувалось {expected} "
                                "(по одному на канал у збереженому порядку). Зніми відсутні або "
                                "перевір порядок і спробуй ще раз.",
        "captureRenaming": "Перейменовую заміри в REW: {n}…",
        "captureRenameOk": "Перейменовано замірів відповідно до збереженого порядку: {n}.",
        "captureRenameFail": "Перейменування зупинилось після {n} замір(ів): {error}",
        "effectProcess": "записати процес (план, кроки, журнал)",
        "effectProfile": "записати профіль можливостей DSP",
        "effectLedger": "забанкувати знімок налаштувань DSP у леджер",
        "effectProject": "записати власні файли проєкту",
        "effectContract": "перевірити проєкт за контрактом скіла",
        "gateMode": "Питати про",
        "gateWrites": "кожен запис",
        "gateForeign": "лише те, чим скіл не володіє",
        "gateModeTip": "Скіл постійно пише в `process/`, `state/` і власні файли проєкту, і новий проєкт про це не питає: запит на кожен `ls` — це запит, який навчаються клікати не читаючи, а він тоді нічого не охороняє. Спиняється те, що міняє машину: власні записи TCC у DSP і REW питають усередині інструмента за будь-якого налаштування. Звузь тут, якщо хочеш бачити й файловий трафік.",
        "configureModels": "моделі…",
        "configureModelsTitle": "Моделі у виборі генератора",
        "configureModelsBlurb": "omp знає про всі ці моделі. Познач ті, до яких маєш доступ — саме вони будуть у виборі генератора. Claude іде через Agent SDK і доступний завжди.",
        "configureModelsFilter": "фільтр за назвою, провайдером або id",
        "configureModelsCount": "у каталозі omp: {n}",
        "configureModelsSetup": "Налаштувати omp…",
        "configureModelsSetupTip": "Відкрити власне налаштування omp у терміналі — там \
налаштовуються акаунти, API-ключі та входи. Саме воно вирішує, які моделі з'являться у списку \
вище, тож коли закінчиш і повернешся сюди, список перечитається. TCC жодних із цих облікових \
даних не тримає: термінал і сесія в ньому — твої.",
        "configureModelsSetupOpened": "Налаштування omp відкрито в терміналі. Коли закінчиш — \
повернись у це вікно, список перечитається.",
        "mcpDown": "MCP-сервер не працює, тож сесії нема через що дістатися до TCC. Запусти TCC \
ще раз; якщо повторюється — причина тут і в лозі:",
        "mcpDownLog": "лог:",
        "modelClipboardOnly": "лише буфер",
        "modelInstallCli": "постав {cli} CLI",
        "modelRecommended": "рекомендована пара",
        "modelGoneTitle": "Цієї моделі більше не пропонують",
        "modelGone": "У проєкті стоїть {model}, а на цій машині її вже нічим запустити — моделі виходять з обігу. Обери, що працюватиме замість неї; підміна діє скрізь, де ця назва ще трапляється, не лише тут.",
        "modelGoneWhy": "більше не доступна на цій машині",
        "modelAliased": "{old} тепер працює як {new} на цій машині. Сесії про це кажуть, щоб запис не стверджував інше.",
        "cliRouteQuiet": "{routes} встановлено, але моделей не віддав — можливо, протух його власний логін. У списку рецензента його рядків немає, але це не означає, що маршруту немає.",
        "modelFree": "безкоштовно",
        "ompMissing": "⚠️ omp не встановлено — brew install can1357/tap/omp, або обери модель Claude.",
        "copyValue": "Копіювати значення",
        "copyRow": "Копіювати рядок",
        "copyHint": "Копіювати підказку",
        "copySelection": "Копіювати виділене",
        "copyMessage": "Копіювати повідомлення",
        "aiMain": "ШІ main",
        "aiEffort": "Зусилля",
        "aiCritic": "ШІ critic",
        "effort_high": "high",
        "effort_xhigh": "x-high",
        "effort_max": "max",
        "effortTip_high": "Досить для рутинних кроків. Нижня межа для налаштування — нижче модель погоджується надто легко.",
        "effortTip_xhigh": "Типове значення, із запасом. Підходить майже для кожного кроку тюну.",
        "effortTip_max": "Для справді важкого кроку. Сюди ніщо не піднімається саме — сесія, почата нижче, там і лишиться, хай яка складна виявиться робота. Повільніше, а на метрованому маршруті ще й дорожче.",
        "effortNextSession": "Зусилля застосується до наступної сесії — ця лишається на рівні, з яким стартувала.",
        "note": "прототип · реальні дані (sound_AutoSci) · крутимо форму",
        "coffeeBtn": "☕ Пригостити кавою",
        "supportGithub": "💜 GitHub Sponsors",
        "supportMonobank": "☕ Банка на Monobank",
        "fbBig": "Написати розробнику",
        "fbBigTip": "Баг, ідея, питання, «тут незрозуміло» — усе сюди. Можна прикріпити скріншот.",
        "fbHead": "Відгук про прототип TCC",
        "fbHint": "Напишіть, що подобається / що змінити. Скористайтесь кнопками B / I / "
                  "список — набирати markdown руками не треба.",
        "fbPh": "Ваш відгук про прототип…",
        "fbCancel": "Скасувати",
        "fbSendGithub": "Надіслати в GitHub →",
        "fbSendForm": "Надіслати через форму →",
        "fbVia": "Як надіслати:",
        "fbViaGithub": "GitHub issue (маю акаунт)",
        "fbViaForm": "Google-форма (акаунт не потрібен)",
        "dialog": "Діалог з ШІ",
        "dialogSub": "Generator ↔ Critic ↔ Arbiter",
        "planTitle": "План — Факт",
        "planSub": "фази + кроки",
        "focus": "◆ У ФОКУСІ ЗАРАЗ",
        "measSub": "задача на замір",
        "confirmAlways": "Більше не питати про це в цьому проєкті",
        "gateAuto": "Не питати взагалі (авто)",
        "gateAutoTip": "Інструменти харнеса (шел, читання, правки) працюють без запиту. Власні "
                       "записи TCC у DSP і REW усе одно питають — саме вони міняють машину.",
        "autoAllowed": "Авто-дозвіл <code>{tool}</code> — питання про нього вимкнено для проєкту.",
        "questionCancelled": "Питання знято — хід може йти далі.",
        "questionWithdrawn": "Агент забрав це питання назад.",
        "questionWaiting": "Чекає на твою відповідь",
        "questionFreeText": "Впиши відповідь нижче — тут немає варіантів на вибір.",
        "questionRole": "ПИТАННЯ",
        "composerAnswer": "Відповідай або впиши своє…",
        "composerQueue": "Написати Генератору… (піде, коли хід завершиться)",
        "composer": "Написати Генератору…",
        "queueWaiting": "⏳ {count} твоє повідомлення піде, щойно хід завершиться",
        "queueSendNow": "Надіслати зараз",
        "newBelow": "↓ Нове нижче · {count}",
        "newBelowTip": "Поки ти читав, нижче з'явились нові повідомлення. Перший клік — на їх "
                       "початок, другий — у самий кінець.",
        "messageNotSent": "Не надіслано: сесія зупинилась. Текст повернувся в поле.",
        "quitSaving": "Зберігаю перед виходом — чекаю, поки модель запише стан проєкту. Вікно закриється саме, щойно це станеться.",
        "send": "Надіслати",
        "stop": "Стоп",
        "notVisible": "Не бачу цієї зміни",
        "notVisibleHint": "Сказати ШІ, що зміна, про яку він відзвітував, тут не з'явилась — щоб "
                          "він перевірив по диску, а не повторював твердження.",
        "notVisibleSent": "Позначено для ШІ: <b>заявленого не видно в інтерфейсі</b> — він "
                          "перевірить по диску.",
        "agentThinking": "Працює…",
        "agentFailed": "Помилка сесії",
        "confirmAllowed": "Арбітр <b>дозволив</b> <code>{tool}</code>.",
        "confirmDenied": "Арбітр <b>відхилив</b> <code>{tool}</code>.",
        "modelUnchosen": "— оберіть модель —",
        "startSessionNoModel": "Спершу оберіть модель генератора.",
        "startSessionReady": "Запустити сесію на {model}. Доти не працює нічого.",
        "startSessionRunning": "Сесія вже запущена.",
        "restartSession": "▶ Перезапустити на {model}",
        "restartSessionTip": "Жоден харнес не міняє модель у живій розмові — поточна закриється, почнеться нова сесія.",
        "sessionStarting": "Запускаю {model} — перший хід читає скіл і стан проєкту, тому повільний.",
        "sessionHandoff": "Зберігаю стан проєкту перед зміною моделі…",
        "sessionHandoffSave": "Прошу модель записати те, що вона знає, у файли проєкту…",
        "sessionHandoffQuit": "Зберігаю перед закриттям — прошу модель записати те, що вона знає, "
                              "у файли проєкту…",
        "quitSaveSave": "Зберегти хід",
        "quitSaveDiscard": "Не зберігати",
        "quitSaveCancel": "Лишитись",
        "quitSaveTitle": "Зберегти перед закриттям?",
        "quitSaveBody": "Сесія працює.\n\nТе, що вона дізналась цього ходу, не на диску, доки не "
                        "запише — закриття зараз це втратить. Збереження коштує один хід.",
        "sessionHandoffFresh": "Спершу зберігаю, потім починаю нову сесію з порожнім контекстом…",
        "sessionRestarted": "Сесію закрито: перезапуск на щойно обраній моделі.",
        "dialogIdle": "не запущено · {model}",
        "dialogNoModel": "модель не обрано",
        "startSession": "▶ Сесія в TCC",
        "openTerminal": "⧉ Термінал",
        "terminalOpened": "Відкрито термінал із <code>{cli}</code> у папці проєкту. Він підхопить TCC через <code>.mcp.json</code>; на першому запуску підтвердь сервер <b>tcc</b>.",
        "criticClipboard": "Ні API, ні CLI рецензента недоступні — пакет у <b>буфері обміну</b>. Встав його в будь-який ШІ-чат, а відповідь встав сюди: цикл працює, просто через тебе.",
        "criticFailed": "Виклик рецензента не вдався: {detail}",
        "criticNotReady": "Рецензентові поки нема чого читати. Він щоразу перечитує проєкт із диска, а ця тека ще не проходила інтейк — контракт і контекст авто створюються, коли починається тюн. Сам канал справний; почни тюн, і рецензент працюватиме з першої ж пропозиції.",
        "criticNever": "Критик: ще не викликався",
        "curveSendMarkers": "Маркери",
        "curveSendDelays": "Затримки",
        "curveShift": "затримка",
        "curveShiftTip": "Притримати обраний драйвер — радіокнопка обирає, який саме. Починає з того, що приходить ПЕРШИМ (природний вибір на першому проході); відʼємне дозволено, бо на наступних проходах ви правите канал, у якому затримка вже є. Нижче нуля не може йти СУМА на каналі — і прочитання це скаже, коли реєстр відомий. Крок — той, який дає ввести цей ДСП. Нічого не застосовується: прочитання йде як пропозиція.",
        "curveDelayHead": "затримки для вирівнювання (пропозиція, не застосовано):",
        "curveApfLabel": "all-pass:",
        "curveApfNone": "—",
        "curveApfTip": "All-pass для драйвера, якого обрала радіокнопка — того самого, що править \
поле затримки. Він НЕ змінює рівень і обертає фазу навколо f0: APF1 повертає на −90° на f0 (загалом \
0 → −180°), APF2 — на −180° на f0 (0 → −360°), а Q каже, яка частка цього оберту припадає на \
околицю f0. На АЧХ крива не рухається; на фазі — обертається; і там, і там прогнозована сума (Σ) \
показує, що це робить зі стиком — у цьому й суть. На імпульсі намальована крива лишається як \
виміряна (all-pass розмазує імпульс); суму зі зсувом несе смуга внизу. Нічого не застосовується: \
воно йде як пропозиція в показанні, словами реєстру (APF2 250 Hz Q 0.71). І all-pass не заповнює \
провал одного драйвера — поворотом фази перелаштовується лише сума двох драйверів, що \
перекриваються, тож читай його по сумі, а не по одній кривій. Математика — власна скілова \
(dsp_math), тут нема її другої копії.",
        "curveApfKindTip": "Який порядок. APF1: лише f0, там −90° — мʼякша чверть оберту. APF2: f0 \
і Q, там −180° — те, що приймає слот APF2 у банку PEQ. Два APF1 на одній f0 — це один APF2 з Q 0.5.",
        "curveApfF0Tip": "Частота, навколо якої обертається фаза. Став туди, де стик — на частоту \
кросовера між двома драйверами, що сумуються.",
        "curveApfQTip": "Яка частка з 360° припадає на околицю f0 (лише APF2). 0.71 обертає \
приблизно на півтори октави в обидва боки від f0; вищий Q обертає швидше й гірше тримається під \
дрейфом, який є в реальному авто — власний пошук скіла зупиняється на 4.",
        "curveApfHead": "all-pass для повороту фази (пропозиція, не застосовано):",
        "curveApfNoMaths": "all-pass не змоделювати: не вдалося завантажити математику фільтрів \
скіла ({error})",
        "unitMs": "мс",
        "unitSmp": "вибірок",
        "curveDelayRelative": "Відносно {name}, який лишається без затримки: вимірювались лише \
різниці між цими драйверами, тож набір подано від того, кому треба найменше.",
        "curveDelayLands": "прихід {was} → {now} мс",
        "curveDelayTotal": "на каналі → {total} мс",
        "curveDelayBelowZero": "⚠ нижче нуля — канал так не може",
        "curveBankImpossible": "Щось із цього виводить канал нижче нуля, тож набір у такому \
вигляді не застосувати — скажи, яку опорну точку рухати натомість.",
        "curveBankLabel": "зчитані затримки:",
        "curveBankLabelIn": "зчитані затримки в {set}:",
        "curveBankBtn": "Зчитані затримки ({n})",
        "curveSumNoteBtn": "Σ прогноз",
        "curveGuidesTip": "Прибрати з картинки всі напрямні: маркери, рівні, перехресну лінію та \
її точки. Нічого не втрачається — кожна повертається туди, де була, а показання лишаються тим \
самим реченням, бо невидимий маркер — це все одно знятий тобою показник. Поки сховані, їх не \
потягнеш.",
        "curveStripLinkTip": "Слідувати за шкалою частот графіка. На фазі смуга і графік — це ті \
самі частоти, тож один зум рухає обидва, і що видно на 3 кГц угорі, те й на 3 кГц унизу. Вимкни, \
щоб наблизити провал окремо, і ввімкни, щоб знову їх зіставити. На імпульсній не пропонується: \
там вісь — час.",
        "curveReadoutBtn": "Маркери",
        "curveBankEmpty": "затримок ще нема — виставте вище, і вона збережеться по заміру",
        "curveClearLabel": "очистити:",
        "curveClearDelay": "Затримки",
        "curveClearMarkers": "Маркери",
        "curveBankAsk": "Затримки, які я зчитав(ла) з кривих, ЛИШЕ НА АНАЛІЗ — нікуди їх не \
записуй і не вважай змінами:",
        "curveBankConvention": "Домовленість: усі заміри мають спільний нуль часу (0 мс на осі \
імпульсної). Кожне число нижче додається до приходу ЦЬОГО заміру, як його було знято; мета — щоб \
усі драйвери зійшлися на одному приході.",
        "curveBankArrival": "прихід",
        "curveBankChannel": "канал",
        "curveBankSpread": "Розкид приходів по {n} розміщених драйверах: {spread} мс.",
        "curveBankAtZero": "На екрані, зсув не задано (0). Це може бути опора, від якої \
рахувалась решта, а може бути просто те, до чого ще не дійшли руки — з цих даних не розрізнити: \
{names}",
        "curveBankUnplaced": "НЕ розміщені — по цих прочитання ще не робилось, тож у картині \
вище їх нема і НЕ можна вважати, що вони на нулі: {names}",
        "curveBankNotForWriting": "Скажи, чи ця картина узгоджена: які приходи вона означає, чи \
не схоже щось із цього радше на помилку заміру, ніж на налаштування, і що б ти перевірив(ла) \
далі. Це прочитання з кривих, а не ціль: точне збігання приходів саме по собі сцену в цій машині \
не виправляло — тож сприймай їх як свідчення і скажи, що б ти змінив(ла) і чому. Нічого з цього \
не застосовано.",
        "curveBankAskApfOnly": "All-pass фільтри, які я виставив(ла) на виміряних кривих, ЛИШЕ НА \
АНАЛІЗ — нікуди їх не записуй.",
        "curveBankApf": "All-pass по драйверах, виставлені за прогнозованою сумою (пропозиція, не \
застосовано; рівень не змінює, лише фазу; APF1 = −90° на f0, APF2 = −180° на f0):",
        "curveBankApfCaveat": "Змодельовано на наявних свіпах поворотом виміряної фази; НЕ \
перевірено заміром сумування. Скажи, чи цей поворот лагодить стик, чи лише переносить проблему (і \
тягне за собою тайминг вище f0), і який замір це підтвердив би.",
        "curveNoMarkers": "Перетягни маркер на точку, яку маєш на увазі.",
        "curveMarkerModel": "модель",
        "curveMarkerYou": "ти",
        "curveMarkerOne": "1",
        "curveMarkerTwo": "2",
        "curveMarkerN": "маркер {n}",
        "curveTitle": "Де саме?",
        "curveAxes_v": "Маркери читають частоту (вертикальні)",
        "curveAxes_h": "Маркери читають рівень (горизонтальні)",
        "curveAxes_vh": "Маркери читають і те, і те, ставляться окремо",
        "curveAxes_vhs": "Одна точка на кривій дає обидві — рівень іде за частотою",
        "curveAxes_vx": "Одна вертикаль: читає ОБИДВІ криві на цьому x і різницю між ними",
        "curveAxes_hx": "Одна горизонталь: читає, де КОЖНА крива досягає цього рівня (перетин, найближчий до середини видимого)",
        "curveCrossPairTip": "Які саме дві криві порівнюють Vx і Hx. Вони читають одну різницю \
між однією парою, тож коли кривих більше — пару називаєш ти; звичайні маркери V/H/VH далі читають \
кожну криву, по числу на кожну.",
        "curveSumTip": "Σ — показати, що ці драйвери роблять РАЗОМ: комплексна сума кривих на \
екрані, пунктиром, у дБ, із уже застосованими затримками кожного драйвера. На фазі вона лягає \
поверх графіка по правій осі; на імпульсній отримує власну смугу під ним, бо там вісь графіка — \
час, а суми — частота. Це арифметика над уже знятими замірами, тож припущення нічого не коштує і \
нікуди нічого не пишеться. Вона щось означає лише тоді, коли всі заміри знято від ОДНОГО \
спільного часового опору; кнопка Σ під графіком несе висновок — що перевірено, а що ні.",
        "curveSumHead": "Передбачена сума, пунктир, у дБ:",
        "curveSumWorst": "Найнижча точка суми: {depth} дБ відносно найгучнішого окремого драйвера \
там, на {hz} Гц.",
        "curveSumNone": "Суму не намальовано.",
        "curveSumNoPlot": "Цьому вигляду не вдалось побудувати вісь, на якій малюється сума, тож \
її нема куди покласти. На решту вікна це не впливає.",
        "curveSumTooFew": "Одна крива — це не сума: постав на екран другий замір.",
        "curveSumNoData": "Ці криві не несуть ні АЧХ, ні фази, щоб їх додати — вони не з \
розгортки REW.",
        "curveGroupLabel": "заповнити:",
        "curveGroupNone": "— без групи —",
        "curveGroupKind_pairs": "пара",
        "curveGroupKind_joints": "стик",
        "curveGroupKind_sides": "сторона",
        "curveGroupKind_combos": "набір",
        "curveGroupNoGlossary": "— у цьому проєкті нема глосарію —",
        "curveGroupTip": "Заповнити вибір цілою групою — мідбаси, середні, саб+мідбаси, одну \
сторону, все. Назви беруться з глосарію цієї машини, а свіпи — ті, що на версії конфігурації \
поруч. Нічого зайвого не тягнеться: учасник, для якого в REW нема свіпу, називається, а не \
мовчки пропускається. Група ЗАПОВНЮЄ і відпускає: прибереш потім один чіп — нічого не \
підставляється назад, і саме так чути, що цей драйвер робить зі стиком.",
        "curveGroupVersionTip": "З якої серії замірів беруться свіпи групи — це конфігурація ДСП, \
під якою їх зняли; у назві заміру в REW вона стоїть як `_N`, і так само зветься в панелі замірів. \
Починає з серії, яку поділяють криві вже на екрані, або з найновішої, що є для цих драйверів — і \
її можна змінити.",
        "curveGroupMissing": "{group} на _{version}: {names} — цього нема в REW. Намальовано суму \
іншого набору.",
        "curveGroupEmpty": "{group} на _{version}: у REW нема жодного свіпу учасників, тож нічого \
не змінено.",
        "curveChooseBtn": "Обрати… ({n})",
        "curveChooseTip": "Познач будь-які заміри — сума приймає стільки, скільки даси. Меню не \
закривається, тож ціла сторона — це один захід у список. Усе позначене стоїть чіпом вище, у \
кольорі своєї кривої; група поруч заповнює ті самі чіпи одним рухом.",
        "curveChipRemoveTip": "Прибрати {title} з графіка. Решта лишаються на місці, а сума \
перераховується без нього — саме так чути, що цей драйвер робить зі стиком.",
        "curveChipOnlyTip": "Єдина крива на екрані. Додай ще одну, перш ніж прибирати цю — вікно, \
яке нічого не малює, нічого й не каже.",
        "curveChipMissingTip": "REW не дав кривої для {title}, тож його нема на графіку, хоч він і \
обраний — і в сумі його теж нема. Тому він блідий.",
        "curveAt": "на",
        "curveZoomAll": "Показати все, що є в замірі",
        "curveZoomAllShort": "A",
        "curveZoomDetail": "Назад до діапазону, з якого почали",
        "curveZoomDetailShort": "D",
        "curveZoomOut": "Віддалити",
        "curveZoomOutShort": "−",
        "curveZoomIn": "Наблизити",
        "curveZoomInShort": "+",
        "curveKind_impulse": "імпульсна",
        "curveKind_fr": "АЧХ",
        "curveKind_phase": "фаза",
        "curveRtaOnly": "Показано АЧХ: {titles} — замір MMM, а для нього REW не має ні \
імпульсної, ні фази.",
        "curveRtaTip": "Замір MMM: REW не має для нього ні імпульсної, ні фази. Щоб побачити \
його на графіку, перейди на АЧХ.",
        "curveKindRtaTip": "Не для заміру MMM — REW не має для нього ні імпульсної, ні фази. \
Щоб це читати, обери вище заміри свіпом (sw).",
        "curveBtn": "Криві — постав маркер там, де маєш на увазі",
        "curveNothing": "Ще нема чого малювати — спершу прочитай заміри з REW.",
        "curveLoading": "Читаю криві з REW…",
        "curveFailed": "Не вдалось прочитати з REW: {error}",
        "modelMissingRow": "{key} — тут недоступна",
        "modelMissingTip": "Проєкт просить модель, якої ця машина не пропонує. Вона лишається обраною і червоною, поки ти не обереш іншу — нічого не перенаправляється за твоєю спиною.",
        "modelUnconfirmed": "з минулого запуску",
        "attachTip": "Додати скріншот — зберігається у проєкт, модель читає файл",
        "attachTitle": "Додати скріншот",
        "attachClear": "Очистити",
        "attachEmptyMac": "⌘⌃⇧4 копіює знімок у буфер (⌘⇧4 натомість зберігає файл на робочий стіл). Тоді натисни тут ⌘V.",
        "attachEmptyWin": "Win+Shift+S копіює знімок у буфер. Тоді натисни тут Ctrl+V.",
        "attachEmptyOther": "Скопіюй знімок у буфер, тоді натисни тут Ctrl+V.",
        "attachCaption": "Що на ньому — напр. «імпульсна w-L, перший пік»",
        "criticWarnTitle": "Про рецензента",
        "criticSubstituted": "підмінено",
        "criticAnswered": "відповів {model}",
        "criticSameVendor": "той самий вендор, що й Генератор",
        "criticSameVendorTip": "Рецензент і Генератор — обидва {vendor}. Рецензія відбувається, але рецензент, обраний заради крос-вендорної незалежності, нею бути перестав — став менше важити його згоду або поверни іншого вендора.",
        "sdkNoLogin": "claude не залогінений",
        "sdkNoLoginTip": "Моделі Claude працюють через твою власну сесію `claude` — у TCC немає свого акаунта, і залогінити тебе він не може. Поки логіну немає, цей маршрут не відповість, що б не показував пікер. У терміналі виконай:\n\n    {cmd}",
        "criticStatus": "Критик · {model} · {ago}",
        "sessionResumed": "відновлено",
        "sessionNew": "нова сесія",
        "editChipLabel": "Правка параметрів проекту",
        "editReasonsQ": "Причина?",
        "reasonForgot": "скіл не зберіг",
        "reasonManual": "я змінив щось руками",
        "editStartForgot": "◆ Правка параметрів проекту — позначено: скіл, можливо, не "
                            "зберіг останню зміну. Опиши, що повинно бути в ledger; я "
                            "перевірю і виправлю.",
        "editStartManual": "◆ Правка параметрів проекту — ти змінив щось руками. Скажи що і "
                            "де; я запишу в ledger, щоб наступні рекомендації це враховували.",
        "editDoneForgot": "✓ Перевірив ledger: у <code>Rear R Full</code> delay в діалозі був "
                           "9.5 мс, а на диску 8.0 мс — виправив, перезаписав 9.5 мс.",
        "editDoneManual": "✓ Занотовано: <code>Front R High</code> gain 1.4 → 1.0 дБ "
                           "(вручну). Ledger оновлено і переатестовано.",
    },
}

_lang: Lang = "en"
_listeners: list[Callable[[], None]] = []


def current_language() -> Lang:
    return _lang


def t(key: str) -> str:
    """Plain string lookup, falling back to English, then the key itself."""
    return T.get(_lang, {}).get(key, T["en"].get(key, key))


def tx(obj) -> str:
    """Per-language object picker: `{"en": "...", "uk": "..."}` -> the current language's value.
    Passing a plain string returns it unchanged (mirrors the prototype's `tx()`)."""
    if isinstance(obj, dict):
        return obj.get(_lang, obj.get("en", ""))
    return obj


def on_language_changed(callback: Callable[[], None]) -> None:
    """Register a no-arg callback to run every time the language changes (a widget's own
    "retranslate myself" method). Mirrors the prototype re-rendering `[data-i]` elements.

    Held WEAKLY when the callback is a bound method, which is what every caller passes. A plain
    list of bound methods is a list of the widgets they belong to, and this list never shrank: it
    kept every window and every dialog ever built alive for the life of the process (found while
    hunting a quadratic test suite, 2026-08-12). A dead widget's callback is dropped on the next
    language switch rather than called on a destroyed object.
    """
    try:
        _listeners.append(weakref.WeakMethod(callback))
    except TypeError:
        _listeners.append(callback)  # a plain function or a lambda: nothing to hold weakly


def set_language(lang: Lang) -> None:
    global _lang
    if lang not in T:
        raise ValueError(f"unknown language {lang!r}, known: {sorted(T)}")
    _lang = lang
    alive = []
    for entry in list(_listeners):
        callback = entry() if isinstance(entry, weakref.WeakMethod) else entry
        if callback is None:
            continue  # its widget is gone; so is its registration
        # A WeakMethod outliving its widget's C++ half is not hypothetical. PySide keeps the
        # Python wrapper after Qt has destroyed the object underneath, so the weakref resolves
        # happily and the call lands on freed memory:
        #     RuntimeError: libshiboken: Internal C++ object (_DTab) already deleted.
        # Which is what switching language after closing a window would do (found 2026-08-13,
        # once the test suite started destroying widgets instead of hoarding them). Ask shiboken,
        # not the weakref.
        target = getattr(callback, "__self__", None)
        if target is not None and not shiboken6.isValid(target):
            continue
        alive.append(entry)
        callback()
    _listeners[:] = alive

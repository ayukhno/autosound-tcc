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

Lang = str  # "en" | "uk" | "pl" | "de"

#: The languages the UI offers, in the order they are shown: the code the switch stores, the key
#: holding the language's name, and the badge the header combo shows. ONE list -- the combo, the
#: menu and the settings summary all read it, so adding a language is adding a table below plus a
#: row here. The pair of hardcoded `("en", …), ("uk", …)` tuples this replaced is exactly how a
#: third language comes to exist in the table and stay invisible in the window.
#:
#: The NAME is the form that fits INSIDE a sentence, because `npOnboardingHint` interpolates it
#: ("conduct the interview in {language}" / "Веди інтерв'ю {language}"). Ukrainian settled that by
#: choosing the instrumental case; Polish and German follow with "po polsku" and "auf Deutsch".
#:
#: The BADGE for Ukrainian is Cyrillic "УК" (macOS's own convention) rather than the Latin "UK",
#: which reads as United Kingdom (user request 2026-07-27).
LANGS: tuple[tuple[Lang, str, str], ...] = (
    ("en", "langNameEn", "EN"),
    ("uk", "langNameUk", "УК"),
    ("pl", "langNamePl", "PL"),
    ("de", "langNameDe", "DE"),
)

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
        "chanSumAllOn": "{total} (all on)",
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
        "selfAliasSameModel": "{keys} — the same model, said with the harness prefix that runs it. Nothing is substituted: this repairs a name written without its prefix, and removing the alias is safe unless some older record still refers to the short name.",
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
        "langNamePl": "Polish",
        "langNameDe": "German",
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
        "riTitle": "Import from a Resonalyze project",
        "riFilePlaceholder": "A Resonalyze virtual-DSP session (.json)",
        "riAgainst": "Checked against",
        "riNoProfile": "No dsp_profile.json in this project — nothing was checked against a real "
                       "processor. Every value below is reported, none is verified.",
        "riScene": "Stereo scene",
        "riSceneNote": "What Resonalyze's Auto balance aims for. It is already inside the "
                       "per-channel gains and delays below — do not enter it a second time.",
        "riUnbound": "no channel of this project matches",
        "riDormant": "in the file, but NOT live (the crossover kind decides)",
        "riDropped": "dropped: transparent, contributes nothing",
        "riNotChecked": "Not checked, because this DSP profile does not state the limit",
        "riBindNone": "— leave unbound —",
        "riBlocked": "This processor cannot be given the plan as it stands: {refused} value(s) "
                     "refused, {unbound} channel(s) unbound. Nothing is rounded to fit, and nothing "
                     "is written.",
        "riClear": "No stated limit of this DSP refuses any of the {legs} channels. That answers for "
                   "the HARDWARE — a PC-Tool mode (Fine EQ) can be narrower, and the switch is at "
                   "the screen. To bring it into the project, press “Send to be banked”: the rows and "
                   "the request land in the AI dialog’s composer, where you read them and send "
                   "them. The gate validates them, writes the snapshot and produces the settings "
                   "sheet you enter in PC-Tool by hand.",
        "riCopyRows": "Copy rows (JSON)",
        "riCopied": "The rows are on the clipboard.",
        "riFailed": "This file could not be read:",
        "riClose": "Close",
        "riImport": "Import from a Resonalyze project…",
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
        "riUnchecked": "Nothing was checked. This project does not say which processor it has, so all {legs} channels are reported and none is verified — set the car up first (Menu ▸ Project), or open this on a project that has a dsp_profile.json.",
        "riUnboundVerdict": "{unbound} of the file's {legs} channels match no channel in this project. Their values are fine; a row with no channel cannot be banked under any name. Bind them below, or set the car's channels up first.",
        "riNoChannels": "This project has no channels yet — there is nothing to bind these to. Set the car up first: Menu ▸ Project ▸ New project / Copy the car.",
        "npCopy": "Copy",
        "npSeedTargetTaken": "The folder “{folder}” already has a project in it. Copying never writes over facts somebody has confirmed — pick an empty folder, or a new one.",
        "leftRigOnly": "This is the rig as the project describes it — every channel in its tier, no values yet. The values arrive with the first ledger snapshot, during tuning.",
        "riProjectLink": "Resonalyze by DIMOSUS — github.com/DIMOSUS/Resonalyze",
        "riSendRows": "Send to be banked",
        "riSendFirst": "Import from a Resonalyze project — {file}. Checked against this project's DSP profile: {ok} values enterable, none refused, {unknown} unverifiable. This project has no ledger yet, so bank it as the FIRST snapshot of preset {preset}, through the gate. The rows follow, keyed by channel:",
        "riSendPropose": "Import from a Resonalyze project — {file}. Checked against this project's DSP profile: {ok} values enterable, none refused, {unknown} unverifiable. Propose it as a change to preset {preset} through the gate, and show me the settings sheet. The rows follow, keyed by channel:",
        "riPair": "pair {pair} {side}",
        "riSideLeft": "left",
        "riSideRight": "right",
        "tabGain": "Gain",
        "tabDelay": "Delay",
        "tabPhase": "Phase",
        "paramAllChannels": "{param} · every channel",
        "copyEqBank": "Copy EQ",
        "copyEqDone": "{channel}: the EQ bank is on the clipboard, in the {format} format.",
        "copyEqLeftOut": "Left out, because that format cannot carry it: {what}.",
        "copyEqNoFormat": "There is no EQ format for this processor yet — nothing was copied rather than something nobody could paste.",
        "quitSavingElapsed": "Saving before quitting — {sec} s so far (up to {max} min). The window closes on its own when the model has written the project down.",
        "quitAbandonTitle": "The save is still running",
        "quitAbandonBody": "The model has been writing the project down for {sec} s. Close now and whatever it has not written yet is lost — the conversation goes with the window.",
        "quitAbandonClose": "Close without saving",
        "quitAbandonWait": "Keep waiting",
        "copyEqCount": "{written} of {size} bands — the rest are written empty and overwrite whatever those slots hold.",
        "copyEqWritten": "{written} band(s).",
        "copyEqCrossovers": "Crossover legs included: {n}.",
        "copiedValue": "Copied: {value}",
        "criticClipboardOnly": "clipboard only",
        "criticClipboardOnlyTip": "{model} is a {vendor} model and this machine has neither that vendor's API key nor its CLI. `call_critic` will still work — it hands you the package to review by hand — but nothing is called.",
        "criticUnknownVendorTip": "The reviewer script calls Google, Anthropic or OpenAI models; {model} is none of those, so no transport here can run it. It will hand you a package to review by hand instead of calling anything.",
        "protTitle": "Protective filters for this capture round",
        "protRound": "Round {series}. What was in the signal path while these sweeps were taken.",
        "protNoRound": "No capture round is open, so there is nothing to record against. Start a round first — a protective record belongs to the pass it was measured in.",
        "protWhy": "A protective filter is IN the recording: it rotates phase far past its own corner, and a junction three times away from it can carry about fifty degrees that belong to the measuring rig rather than to the car. Recorded here, it can be taken back out of the curve. “Swept with nothing” is an answer worth recording; leaving a channel unrecorded is not the same thing, and nothing will be corrected for it.",
        "protUnset": "not recorded",
        "protOff": "no protection",
        "protFilter": "filters:",
        "protHp": "HP Hz",
        "protLp": "LP Hz",
        "protSave": "Record",
        "protRefused": "{channel}: {why}",
        "protBtn": "Protection",
        "protBtnTip": "What was in the signal path while this round was measured — per channel. Recorded, it can be taken back out of the curves; unrecorded, nothing is corrected, because a correction over an unknown chain produces data that only looks corrected.",
        "protNoChannels": "This project has no channels yet, so there is nothing to record a protective filter against.",
        "protWritten": "Recorded what was in the chain for: {channels}. Their curves can be read with the protection taken back out.",
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
        "eqHint": "Only the bands <b>in use</b>, with every parameter of each shown at once. "
                  "An all-pass (APF) is a band TYPE here, not a separate column. Bypass is "
                  "shown but cannot be changed from this window yet. The bank's unused bands "
                  "are hidden.",
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
        "targetHandedOver": 'The tool does not carry “{name}”, so the curve went to the page in the link itself — it '
                            'should be on the plot as “{name}”. If it is not there, the published tool is older than this '
                            'app; say so and it will be handed over as a file instead.',
        "targetLocalViewer": 'The tool does not carry “{name}”, so this is a LOCAL copy of it with your curve already '
                             'plotted — built from the method version this app is pinned to, not the live page. Everything '
                             "else about it is the tool's own.",
        "targetNotInTool": "The tool does not ship “{name}” — it only carries the method's own curves, and learns any "
                           'other by having its file dropped on it. Yours is selected in the file manager: drag it onto '
                           'the page.',
        "targetNoFile": 'The tool does not ship “{name}”, and no file for it was found in this project — the page '
                        'opens with the curves it has. Export the curve into rew_analitic/target-curves/{name}/ and '
                        'it can be dropped on.',
        "targetRevealFailed": 'The tool does not ship “{name}”. The file manager would not open; the file is at {path} — '
                              'drag it onto the page.',
        # Phase 4, the listening panel (2026-08-25).
        "lsnDropLast": 'Undo last',
        "lsnBtn": 'Listening',
        "lsnBtnTip": 'What this track was chosen to expose, in words — and a 🟢/❌ with your own sentence, written '
                     'into the journal against the state you were listening to.',
        "lsnTitle": 'Listening — what to judge, and what you heard',
        "lsnWhy": 'Pick a track on the right, then the phrase that matches what you hear. It lands in the box '
                  'on the left as a line you can rewrite. The tick and your words are both kept, and neither '
                  'stands for the other: the tick is what a filter reads back, the words are what you meant.',
        "lsnRoute": 'Pass',
        "lsnRoute_first": 'first listen',
        "lsnRoute_short": 'short (10 min)',
        "lsnRoute_full": 'full pass',
        "lsnRoute_league": 'next league',
        "lsnRouteRoot": 'This pass',
        "lsnAll": 'The whole library',
        "lsnAt": 'at {timecode}',
        "lsnCueTip": 'Where to hear it: {cue}',
        "lsnRouteTip": 'If it comes out ✗: {route}',
        "lsnText": 'What you heard, in your own words…',
        "lsnTicked": 'Ticked ({n}):',
        "lsnTickedEmpty": 'Nothing ticked yet — click a phrase on the right and it lands here and in the text.',
        "lsnRemoveTip": 'Take this one off the record. The line it wrote stays in the text — rewrite it yourself if '
                        'it no longer belongs.',
        "lsnSave": 'Write it down',
        "lsnSaved": 'Written: {n} verdict(s) against {version}.',
        "lsnRefused": 'Not written: {why}',
        "lsnNoPairs": 'Nothing to write yet: tick at least one phrase. Your words are kept with the ticks, not '
                      'instead of them.',
        "lsnSheet": 'The whole cheat sheet',
        "lsnSheetTitle": 'Listening — the cheat sheet',
        "lsnUnavailable": "The method's listening vocabulary could not be read here: {why}",
        "lsnProblems": "The method's own check reports: {problems}",
        "lsnNotTranslated": 'not translated yet — showing the English',
        "lsnVersion": 'state {version}',
        "lsnNoVersion": 'no ledger snapshot yet — the verdict is written without one, and cannot later be attributed '
                        'to a state',
        "lsnOwnHint": 'For a track that is not here, use “own” — say which track it was in your own words.',
    },
    "uk": {
        "theme": "тема",
        "dspPanel": "DSP",
        "projectParams": "Параметри проєкту",
        "chanSum_channels": "Канали",
        "chanSum_virtual_channels": "Віртуальні",
        "chanSum_physical_outputs": "Вихідні",
        "chanSum_inputs": "Входи",
        "chanSumOff": "{total} ({off} вимкнено)",
        "chanSumAllOn": "{total} (усі увімкнено)",
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
        "selfAliasSameModel": "{keys} — це та сама модель, лише з префіксом того, чим вона запускається. Нічого не підмінено: так виправлено ім'я, записане без префікса. Прибрати псевдонім безпечно, якщо старіші записи вже не посилаються на коротке ім'я.",
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
        "langNamePl": "польською",
        "langNameDe": "німецькою",
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
        "riTitle": "Імпорт з проєкту Resonalyze",
        "riFilePlaceholder": "Сесія віртуального DSP Resonalyze (.json)",
        "riAgainst": "Звірено з",
        "riNoProfile": "У проєкті нема dsp_profile.json — ні з чим звіряти. Усе нижче показано, "
                       "але нічого не перевірено.",
        "riScene": "Стереосцена",
        "riSceneNote": "Це те, до чого ЦІЛИТЬСЯ Auto balance у Resonalyze. Результат уже всередині "
                       "гейнів і затримок кожного каналу нижче — не вводьте його вдруге.",
        "riUnbound": "жоден канал цього проєкту не збігся",
        "riDormant": "є у файлі, але НЕ діє (вирішує тип кросовера)",
        "riDropped": "відкинуто: прозора смуга, нічого не додає",
        "riNotChecked": "Не перевірено, бо профіль цього DSP не називає межі",
        "riBindNone": "— лишити непривʼязаною —",
        "riBlocked": "Цей процесор не прийме план у такому вигляді: відмовлено значень — {refused}, "
                     "непривʼязаних каналів — {unbound}. Нічого не округлюється під залізо і нічого не "
                     "записується.",
        "riClear": "Жодна заявлена межа цього DSP не відмовляє жодному з {legs} каналів. Це відповідь "
                   "про ЗАЛІЗО — режим PC-Tool (Fine EQ) може бути вужчим, і перемикається він на "
                   "екрані. Щоб занести це в проєкт — «Відправити на запис»: рядки разом із проханням "
                   "лягають у поле діалогу з ШІ, ви їх читаєте й надсилаєте. Гейт перевірить їх, "
                   "запише знімок і випише лист налаштувань, який ви вводите в PC-Tool руками.",
        "riCopyRows": "Скопіювати рядки (JSON)",
        "riCopied": "Рядки в буфері обміну.",
        "riFailed": "Цей файл не вдалося прочитати:",
        "riClose": "Закрити",
        "riImport": "Імпорт з проєкту Resonalyze…",
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
        "riUnchecked": "Нічого не перевірено. Цей проєкт не каже, який у нього процесор, тож усі {legs} каналів показані, але жоден не звірений — спершу заведіть авто (Меню ▸ Проєкт) або відкрийте це на проєкті, де є dsp_profile.json.",
        "riUnboundVerdict": "{unbound} з {legs} каналів файлу не збіглися з жодним каналом цього проєкту. Значення в них нормальні; рядок без каналу нема під яким імʼям заносити. Привʼяжіть їх нижче або спершу заведіть канали авто.",
        "riNoChannels": "У цьому проєкті ще нема каналів — прив’язувати нема до чого. Спершу заведіть авто: Меню ▸ Проєкт ▸ Новий проєкт / Скопіювати авто.",
        "npCopy": "Скопіювати",
        "npSeedTargetTaken": "У теці «{folder}» вже є проєкт. Копіювання не пише поверх фактів, які хтось підтвердив, — виберіть порожню або нову теку.",
        "leftRigOnly": "Тут показано склад системи, як його описує проєкт — усі канали у своїх ярусах, поки без значень. Значення прийдуть із першим знімком леджера, вже під час тюнінгу.",
        "riProjectLink": "Resonalyze від DIMOSUS — github.com/DIMOSUS/Resonalyze",
        "riSendRows": "Відправити на запис",
        "riSendFirst": "Імпорт з проєкту Resonalyze — {file}. Звірено з профілем DSP цього проєкту: {ok} значень заходять, жодного відмовленого, {unknown} не перевірених. Леджера в проєкті ще нема, тож заведи це ПЕРШИМ знімком пресету {preset}, через гейт. Нижче рядки, по каналах:",
        "riSendPropose": "Імпорт з проєкту Resonalyze — {file}. Звірено з профілем DSP цього проєкту: {ok} значень заходять, жодного відмовленого, {unknown} не перевірених. Запропонуй це як зміну пресету {preset} через гейт і покажи лист налаштувань. Нижче рядки, по каналах:",
        "riPair": "пара {pair}, {side}",
        "riSideLeft": "ліва",
        "riSideRight": "права",
        "tabGain": "Рівень",
        "tabDelay": "Затримки",
        "tabPhase": "Фази",
        "paramAllChannels": "{param} · усі канали",
        "copyEqBank": "Копіювати EQ",
        "copyEqDone": "{channel}: банк EQ у буфері обміну, у форматі {format}.",
        "copyEqLeftOut": "Не увійшло, бо цей формат такого не несе: {what}.",
        "copyEqNoFormat": "Формату EQ для цього процесора ще нема — нічого не скопійовано, замість того щоб покласти те, що нікуди не вставиш.",
        "quitSavingElapsed": "Зберігаю перед виходом — {sec} с (до {max} хв). Вікно закриється саме, щойно модель запише стан проєкту.",
        "quitAbandonTitle": "Збереження ще триває",
        "quitAbandonBody": "Модель записує стан проєкту вже {sec} с. Закрити зараз — і те, що вона ще не записала, буде втрачено: розмова піде разом із вікном.",
        "quitAbandonClose": "Закрити без збереження",
        "quitAbandonWait": "Почекати",
        "copyEqCount": "{written} смуг із {size} — решта пишуться порожніми й перезапишуть те, що зараз у тих слотах.",
        "copyEqWritten": "Смуг: {written}.",
        "copyEqCrossovers": "Разом із кросовером: {n}.",
        "copiedValue": "Скопійовано: {value}",
        "criticClipboardOnly": "лише буфер обміну",
        "criticClipboardOnlyTip": "{model} — модель вендора {vendor}, а на цій машині нема ні його API-ключа, ні CLI. `call_critic` спрацює, але нічого не викличе: він віддасть пакет, який ви рецензуєте руками.",
        "criticUnknownVendorTip": "Скрипт рецензента вміє викликати моделі Google, Anthropic або OpenAI; {model} — не з них, тож жоден тутешній транспорт її не запустить. Замість виклику він віддасть пакет для ручної рецензії.",
        "protTitle": "Захисні фільтри цього набору замірів",
        "protRound": "Набір {series}. Що було в тракті, поки знімались ці свіпи.",
        "protNoRound": "Набір замірів не відкрито, тож писати нема до чого. Спершу відкрийте набір — запис про захист належить тому проходу, у якому міряли.",
        "protWhy": "Захисний фільтр сидить У ЗАПИСІ: він крутить фазу далеко за власним зрізом, і стик утричі далі може нести близько пʼятдесяти градусів, які належать стенду, а не машині. Записаний тут — його можна вийняти з кривої. «Знімали без нічого» — це відповідь, і її варто записати; лишити канал без запису — не те саме, і для нього нічого не виправлять.",
        "protUnset": "не вказано",
        "protOff": "без захисту",
        "protFilter": "фільтри:",
        "protHp": "ФВЧ Гц",
        "protLp": "ФНЧ Гц",
        "protSave": "Записати",
        "protRefused": "{channel}: {why}",
        "protBtn": "Захист",
        "protBtnTip": "Що було в тракті, поки знімався цей набір — по каналах. Записане можна вийняти з кривих; незаписане не виправляється, бо корекція над невідомим трактом дає дані, які лише ВИГЛЯДАЮТЬ виправленими.",
        "protNoChannels": "У проєкті ще нема каналів — нема до чого писати захисний фільтр.",
        "protWritten": "Записано, що було в тракті: {channels}. Їхні криві можна читати із знятим захистом.",
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
        "eqHint": "Лише <b>задіяні смуги</b>, і в кожної одразу всі параметри. Олл-пас (APF) "
                  "тут — це ТИП смуги, а не окрема колонка. Bypass показано, але змінити його "
                  "з цього вікна поки не можна. Невикористані смуги банку сховані.",
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
        "targetHandedOver": 'Інструмент не несе «{name}», тож крива поїхала на сторінку в самому посиланні — вона має '
                            'бути на графіку як «{name}». Якщо її там нема, опублікований інструмент старіший за '
                            'застосунок; скажи — і криву передаватимемо файлом.',
        "targetLocalViewer": 'Інструмент не несе «{name}», тож це ЛОКАЛЬНА його копія з уже нанесеною твоєю кривою — '
                             'зібрана з тієї версії методу, на якій стоїть застосунок, а не жива сторінка. Усе інше в ній '
                             '— інструментове.',
        "targetNotInTool": 'Інструмент не несе «{name}» — у ньому лише власні криві методу, а будь-яку іншу він '
                           'дізнається з файлу, який на нього перетягнули. Твій виділено у файловому менеджері: '
                           'перетягни його на сторінку.',
        "targetNoFile": 'Інструмент не несе «{name}», і файлу для неї в цьому проєкті не знайшлось — сторінка '
                        'відкриється з тими кривими, які в неї є. Виклади криву в rew_analitic/target-curves/{name}/ '
                        '— і її можна буде перетягнути.',
        "targetRevealFailed": 'Інструмент не несе «{name}». Файловий менеджер не відкрився; файл лежить тут: {path} — '
                              'перетягни його на сторінку.',
        # Phase 4, the listening panel (2026-08-25).
        "lsnDropLast": 'Прибрати останню',
        "lsnBtn": 'Слухання',
        "lsnBtnTip": 'Що саме цей трек має показати — словами; і 🟢/❌ з твоїм реченням, записане в журнал проти '
                     'того стану, який ти слухав.',
        "lsnTitle": 'Слухання — що оцінювати і що почулось',
        "lsnWhy": 'Обери трек праворуч, тоді фразу, яка збігається з тим, що чуєш. Вона ляже в поле ліворуч '
                  'рядком, який можна переписати. Зберігається і позначка, і твої слова, і одне не заміняє '
                  'інше: позначку потім читає фільтр, слова — це те, що ти мав на увазі.',
        "lsnRoute": 'Прохід',
        "lsnRoute_first": 'перше прослуховування',
        "lsnRoute_short": 'короткий (10 хв)',
        "lsnRoute_full": 'повний прохід',
        "lsnRoute_league": 'наступна ліга',
        "lsnRouteRoot": 'Цей прохід',
        "lsnAll": 'Уся бібліотека',
        "lsnAt": 'на {timecode}',
        "lsnCueTip": 'Де це чути: {cue}',
        "lsnRouteTip": 'Якщо вийшло ✗: {route}',
        "lsnText": 'Що почулось, своїми словами…',
        "lsnTicked": 'Позначено ({n}):',
        "lsnTickedEmpty": 'Поки нічого не позначено — натисни фразу праворуч, і вона ляже сюди й у текст.',
        "lsnRemoveTip": 'Прибрати це із запису. Рядок, який вона написала, лишиться в тексті — перепиши сам, якщо він '
                        'більше не про те.',
        "lsnSave": 'Записати',
        "lsnSaved": 'Записано вердиктів: {n}, проти {version}.',
        "lsnRefused": 'Не записано: {why}',
        "lsnNoPairs": 'Писати поки нема чого: познач хоча б одну фразу. Твої слова зберігаються РАЗОМ із '
                      'позначками, а не замість них.',
        "lsnSheet": 'Вся шпаргалка',
        "lsnSheetTitle": 'Слухання — шпаргалка',
        "lsnUnavailable": 'Не вдалося прочитати словник слухання методу: {why}',
        "lsnProblems": 'Власна перевірка методу каже: {problems}',
        "lsnNotTranslated": 'ще не перекладено — показано англійською',
        "lsnVersion": 'стан {version}',
        "lsnNoVersion": 'знімка леджера ще нема — вердикт запишеться без нього, і його потім не привʼязати до стану',
        "lsnOwnHint": 'Для треку, якого тут нема, візьми «own» — а який саме це був трек, скажи своїми словами.',
    },
    "pl": {
        # Polish
        "theme": 'motyw',
        "dspPanel": 'DSP',
        "projectParams": 'Parametry projektu',
        "chanSum_channels": 'Kanały',
        "chanSum_virtual_channels": 'Wirtualne',
        "chanSum_physical_outputs": 'Wyjściowe',
        "chanSum_inputs": 'Wejścia',
        "chanSumOff": '{total} ({off} wył.)',
        "chanSumAllOn": '{total} (wszystkie wł.)',
        "cfgLanguage": 'Język',
        "cfgGenerator": 'Generator AI',
        "cfgEffort": 'Wysiłek',
        "cfgCritic": 'Recenzent AI',
        "cfgTheme": 'Motyw',
        "cfgGate": 'Uprawnienia',
        "cfgThemeLight": 'jasny',
        "cfgThemeDark": 'ciemny',
        "systemParams": 'Parametry systemu',
        "audioAnalysis": 'Analiza car audio',
        "leftNoProfile": 'Procesor jeszcze nieznany. Rozpocznij sesję i powiedz, jaki DSP jest w tym aucie — profil '
                         'zapisuje się, gdy tylko go nazwiesz, a panel się wypełni.',
        "leftNoLedger": 'Nie zdjęto jeszcze żadnych ustawień. Drzewo wypełni się, gdy powstanie pierwszy zrzut '
                        'ledgera — już podczas strojenia.',
        "planEmpty": 'Planu jeszcze nie ma. Skill zapisuje go, gdy sesja wchodzi w fazę — panel wypełni się, gdy '
                     'pojawią się i zaczną zamykać kroki.',
        "planNoProject": 'Nie otwarto projektu.',
        "noDataYet": 'Brak danych',
        "openQuestions": 'Otwarte',
        "openQuestionsTitle": 'Otwarte pytania',
        "curveRoundEmpty": '{round}: w REW nie ma pomiarów z tego przebiegu — otwarty jest inny projekt albo je '
                           'usunięto.',
        "seriesItem": 'seria {v}',
        "logError": 'Coś poszło nie tak: {error} — szczegóły w {path}',
        "rewPort": 'Port REW',
        "rewOnlineTip": 'REW: online',
        "rewOfflineTip": 'REW: nieosiągalny na tym porcie.\nAPI jest tylko w wersjach BETA REW — wydanie stabilne nie '
                         'ma zakładki API w ogóle (roomeqwizard.com/beta.html).',
        "createProject": '+ Utwórz nowy projekt',
        "refreshProjectTip": 'Wczytaj projekt z dysku ponownie (profil, ledger)',
        "selfSection": 'Ustawienia samego TCC',
        "selfAliasTitle": 'Działające aliasy modeli: {n}',
        "selfAliasDetail": '',
        "selfAliasNoneTitle": 'Brak aliasów w warstwie samego TCC',
        "selfAliasNoneDetail": 'To nie to samo, co «wybierak uruchamia to, co pokazuje»: skrypt recenzenta też podmienia, '
                               'warstwę niżej — spada z API na lokalny CLI, a ten uruchamia model, na który jest ustawiony. '
                               'Wiersz niżej porównuje, kto faktycznie odpowiedział.',
        "selfReviewerNeverTitle": 'Recenzenta nie wywołano jeszcze w tym projekcie',
        "selfReviewerNeverDetail": 'Dopóki nie odpowie, nie ma czego porównywać. Skonfigurowany model to deklaracja; wywołanie '
                                   'to dowód.',
        "selfReviewerOkTitle": 'Ostatnia recenzja przyszła od {model} — dokładnie od wybranego',
        "selfReviewerDiffTitle": 'Odpowiedział nie ten recenzent, którego wybrano',
        "selfReviewerDiffDetail": 'Wybrano {wanted}; odpowiedział {answered}. Nie pokazuje tego ani wybierak, ani `substituted` '
                                  '— skrypt recenzenta spada z API Gemini na lokalny CLI (wystarczy 404), a CLI uruchamia '
                                  'model, który ma ustawiony. Sprawdź, co jest wybrane w `agy`, albo przyjmij, że to jest ten '
                                  'recenzent.',
        "selfAliasCrossVendor": '{keys} uruchamia teraz model INNEGO producenta niż wybrany. Jeśli to recenzent — recenzja '
                                'międzyproducencka się skończyła: sens drugiego producenta jest właśnie w tym, że nie dzieli '
                                'martwych pól Generatora.',
        "selfAliasSameModel": '{keys} — ten sam model, tylko zapisany z prefiksem tego, co go uruchamia. Nic nie jest '
                              'podmienione: tak naprawiono nazwę zapisaną bez prefiksu. Usunięcie aliasu jest bezpieczne, o '
                              'ile starsze zapisy nie odwołują się już do krótkiej nazwy.',
        "selfAliasFix": 'Usuń wszystkie aliasy',
        "selfAliasFixed": 'Usunięto aliasów: {n}. Wybieraki znów uruchamiają to, co pokazują.',
        "selfCatalogueTitle": 'Zainstalowany, ale milczy: {clis}',
        "selfCatalogueDetail": 'Ten CLI jest w PATH, a lista modeli wróciła pusta — więc jego trasa zniknęła z wybieraków. '
                               'Wygląda to dokładnie jak «nie zainstalowano» i tak właśnie zapisany model zaczyna wyglądać '
                               'na usunięty.',
        "selfCatalogueFix": 'Zapytaj CLI ponownie',
        "selfCatalogueFixed": 'Katalog odświeżony: modeli {n}.',
        "selfCatalogueOkTitle": 'Każdy zainstalowany CLI odpowiedział swoimi modelami',
        "selfRecommendOkTitle": 'Zalecana para jest tu dostępna',
        "selfRecommendTitle": 'Nic z dostępnych nie pasuje do zalecanego: {roles}',
        "selfRecommendDetail": 'Zalecenie to klasa, a nie nazwa modelu ({pairs}, na dzień {since}) — więc nowa wersja '
                               'którejkolwiek z nich oznacza się sama. Jeśli nie pasuje nic, znaczy że sama klasa odeszła w '
                               'przeszłość albo jej trasa nie jest zainstalowana. Wybierz świadomie: zapasowego zalecenia '
                               'nie ma.',
        "selfCheckFailed": 'Ta kontrola nie mogła się wykonać',
        "diagFixDone": 'Naprawiono: {what}',
        "diagTitle": 'Diagnostyka projektu',
        "diagBtnTip": 'Co TCC znalazł na dysku: maszynowe pliki skilla, sprawdzone',
        "diagChecking": 'Sprawdzam…',
        "diagOk": 'OK — nie ma czego naprawiać',
        "diagIssues": 'Znaleziono problemów: {n}',
        "diagNoIssues": 'Brak problemów',
        "diagAsk": 'Poproś sesję',
        "diagAskText": 'Diagnostyka zgłasza problem w {subject}, słowami samej kontroli:\n\n    {issue}\n\nNapraw to '
                       'komendami skilla (TCC tych plików nie zapisuje). Gdy skończysz, powiedz, jaką komendę '
                       'wykonałeś — uruchomię `contract.py check` ponownie i zobaczymy, czy wiersz zniknął.',
        "diagAskedAgo": 'poproszono {ago}, wciąż jest',
        "diagAgoNow": 'przed chwilą',
        "diagAgoMin": '{n} min temu',
        "diagFiles": 'Pliki maszynowe',
        "diagCross": 'Kontrole międzyplikowe',
        "diagOpenQ": 'Otwarte pytania (intake niedokończony)',
        "diagMissing": 'brak',
        "diagUnavailable": 'Kontrola kontraktu niedostępna',
        "diagCheckedAt": 'sprawdzono {at} · {ms} ms',
        "diagTabProject": 'Projekt',
        "diagTabInstall": 'Instalacja',
        "diagTabLog": 'Logi',
        "diagReport": 'Zgłoś problem',
        "titleUpdate": 'jest aktualizacja',
        "updWhy_source_checkout": 'uruchomiono ze źródeł — zaktualizuj przez git',
        "updWhy_no_network": 'nie udało się połączyć z GitHubem',
        "updWhy_not_found": 'nie znaleziono na tej maszynie',
        "updWhy_not_a_checkout": 'to nie jest checkout gita, więc nie ma czego aktualizować na miejscu',
        "updWhy_on_branch": 'na gałęzi — to czyjś katalog roboczy, a nie zainstalowane wydanie',
        "updWhy_submodule": 'to submoduł checkoutu — zaktualizuj przez git, w',
        "updWhy_dirty": 'ma niezacommitowane zmiany, więc zostawiam go w spokoju',
        "updWhy_no_manifest": 'w manifeście nie ma wersji',
        "updWhy_git_failed": 'git powiedział',
        "updTcc": 'Zaktualizuj TCC',
        "updSkill": 'Zaktualizuj metodę',
        "updTccName": 'TCC',
        "updSkillName": 'Metoda',
        "updChecking": 'sprawdzam aktualizacje…',
        "updAvailable": '{what} {here} — wyszła nowsza: {there}',
        "updNewerBuild": '{what} {here} — wyszła nowsza kompilacja tej samej wersji',
        "updNewerBuildOn": '{what} {here} — wyszła nowsza kompilacja z {date}',
        "updCurrent": '{what} {here} — aktualna',
        "updUnknown": 'nie udało się zapytać GitHuba — brak sieci albo ma swój dzień',
        "updWorking": 'aktualizuję…',
        "updSkillDone": 'Metoda jest teraz {version} — otwórz sesję AI ponownie, żeby ją podchwyciła',
        "updTccHanded": 'Terminal jest otwarty i czeka, aż TCC się zamknie. Zamknij TCC — aktualizacja pójdzie sama, '
                        'potem uruchom TCC ponownie.',
        "updFailed": 'nie wyszło: {why}',
        "diagLogNone": 'nie ma pliku logu — ten przebieg pisze tylko do terminala',
        "diagInstallBlurb": 'Co jest zainstalowane na tej maszynie — wersje, skąd wzięła się każda część, które CLI '
                            'odpowiadają. Skopiuj do wiadomości, gdy coś zgłaszasz: to odpowiada na pierwsze pięć pytań, '
                            'które ktokolwiek zada.',
        "diagInstallReading": 'czytam…',
        "diagInstallCopy": 'Kopiuj',
        "diagInstallCopied": 'Skopiowano',
        "diagRefresh": 'Sprawdź ponownie',
        "diagClose": 'Zamknij',
        "diagStripIssues": 'Kontrakt projektu: problemów {n} — zobacz Diagnostykę (⚕)',
        "diagStripError": 'Kontrola kontraktu niedostępna: {error}',
        "projectRenderFailed": 'Nie udało się narysować projektu z dysku — na ekranie został ostatni działający widok. '
                               '{error}',
        "staleStrip": '{what} — do ponownego zmierzenia kanałów: {n} ({codes})',
        "missingRecord": 'Nie zapisano: {what} — {why}.',
        "criticSaved": 'Tekst zapisano w {path}',
        "acousticsNone": 'Mapy wad jeszcze nie ma. Faza 0 mierzy, co to auto robi z dźwiękiem, i wiersze trafią tutaj '
                         '— każdy z tym, co z nim wolno, a czego nie wolno zrobić.',
        "flawHypothesis": 'niepotwierdzone',
        "flawEvidenceHead": 'Odczytano z:',
        "flawNoWhy": 'Z tym wpisem nie zapisano przyczyny — tylko sam pomiar.',
        "flawAllChannels": 'wszystkie kanały',
        "flawAction_notch": 'ciąć',
        "flawAction_leave": 'zostawić',
        "flawAction_no_boost": 'nie podbijać',
        "flawAction_geometry": 'geometria',
        "flawAction_delay": 'opóźnienie',
        "flawAction_crossover": 'crossover',
        "flawKind_room_gain": 'wzmocnienie kabiny',
        "flawKind_modal_peak": 'moda kabiny',
        "flawKind_cabin_null": 'zapadnięcie kabiny',
        "flawKind_sbir": 'SBIR',
        "flawKind_floor_bounce": 'odbicie od podłogi',
        "flawKind_driver_resonance": 'rezonans głośnika',
        "flawKind_non_min_phase": 'faza nieminimalna',
        "flawKind_thd_spike": 'skok zniekształceń',
        "flawKind_pair_suckout": 'zapadnięcie pary',
        "supervisorUnbacked": 'Te kroki są zamknięte, a ich dowody nie wskazują na nic, co istnieje na dysku ani w '
                              'REW:<br>{steps}<br>Albo praca jest zapisana tam, gdzie tego nie widzę, albo jej nie było.',
        "recordTargetCurve": 'krzywa docelowa',
        "recordTargetCurveWhy": 'faza 0 ją wybiera, a każda kolejna faza jest do niej mierzona — a na dysku nie zostało, '
                                'którą krzywą wzięto',
        "measNoTask": 'Zadania zdjęcia jeszcze nie ma. Wynika ono z fazy, słownika nazw i bieżącej wersji ledgera — '
                      'więc pojawi się, gdy intake ustali nazwy kanałów.',
        "measPhaseNoCapture": 'Ta faza nie robi pomiarów — pracuje na już zdjętej serii. Następne zadanie zdjęcia pojawi '
                              'się razem z fazą, która go potrzebuje.',
        "noProjectMeas": 'Brak projektu — nie ma czego zdejmować.',
        "npTitle": 'Nowy projekt',
        "npFolder": 'Folder projektu',
        "npBrowse": 'Przeglądaj…',
        "npProfile": 'Profil DSP',
        "npAddNew": '+ Dodaj nowy (nie ma na liście)',
        "npVendor": 'Producent DSP',
        "npVendorPlaceholder": 'np. Helix, Musway',
        "npModel": 'Model DSP',
        "npModelPlaceholder": 'np. DSP Ultra S, M6V4',
        "npRunVia": 'Prowadź onboarding przez',
        "npRunInApp": 'W aplikacji (Claude)',
        "npAiModel": 'Model AI',
        "npTerminalModel": 'Model (opcjonalnie)',
        "npTerminalModelPlaceholder": 'np. opus, gemini-2.5-pro — puste = domyślny CLI',
        "npOnboardingHint": 'Skorzystaj ze skilla autosound-tuning do onboardingu profilu DSP. Podłącz się do serwera MCP '
                            "'tcc' tego projektu (zob. .mcp.json) i wywołaj najpierw jego narzędzie "
                            'check_existing_profile, dla vendor={vendor} model={model}. Prowadź wywiad {language}.',
        "langNameEn": 'po angielsku',
        "langNameUk": 'po ukraińsku',
        "langNamePl": 'po polsku',
        "langNameDe": 'po niemiecku',
        "npSeed": 'Parametry systemu',
        "npSeedNone": 'Zapytać w wywiadzie (od zera)',
        "npSeedFrom": 'Skopiuj z istniejącego projektu…',
        "npSeedPlaceholder": 'Folder projektu, w którym jest project.json',
        "npSeedFindings": '…i to, co tam zmierzono (wady akustyczne, otwarte pytania)',
        "npSeedNotAProject": 'Nie ma tu czytelnego project.json — nie ma czego kopiować.',
        "npSeedSummary": '{car} · {dsp} · kanałów: {channels}',
        "npSeedNote": '**Odziedziczono z `{source}` ({when}).** Profil systemu skopiowano z tamtego projektu, a nie '
                      'napisano tutaj — zweryfikuj go z tą instalacją, zanim zaczniesz na nim polegać.',
        "npSeedFailed": 'Nic nie skopiowano: {problem}',
        "npSeedDone": 'Parametry systemu skopiowano z «{source}»: {files}. Są odziedziczone, a nie zmierzone tutaj '
                      '— zweryfikuj je z tą instalacją.',
        "npSeedHint": 'Parametry systemu skopiowano do tego folderu z projektu «{source}»: NAJPIERW przeczytaj '
                      'project.json i dsp_profile.json i przejdź je razem z osobą, poprawiając to, co się różni. '
                      'Nie proś o opisanie auta od zera.',
        "riTitle": 'Import z projektu Resonalyze',
        "riFilePlaceholder": 'Sesja wirtualnego DSP Resonalyze (.json)',
        "riAgainst": 'Zweryfikowano z',
        "riNoProfile": 'W projekcie nie ma dsp_profile.json — niczego nie zweryfikowano z prawdziwym procesorem. '
                       'Każda wartość niżej jest pokazana, żadna nie jest sprawdzona.',
        "riScene": 'Scena stereo',
        "riSceneNote": 'To, do czego CELUJE Auto balance w Resonalyze. Wynik jest już wewnątrz wzmocnień i opóźnień '
                       'każdego kanału niżej — nie wprowadzaj go drugi raz.',
        "riUnbound": 'żaden kanał tego projektu nie pasuje',
        "riDormant": 'jest w pliku, ale NIE działa (decyduje typ crossovera)',
        "riDropped": 'odrzucono: pasmo przezroczyste, nic nie wnosi',
        "riNotChecked": 'Nie sprawdzono, bo profil tego DSP nie podaje granicy',
        "riBindNone": '— zostaw niepowiązane —',
        "riBlocked": 'Ten procesor nie przyjmie planu w tej postaci: odmówiono wartości — {refused}, '
                     'niepowiązanych kanałów — {unbound}. Nic nie jest zaokrąglane pod sprzęt i nic nie jest '
                     'zapisywane.',
        "riClear": 'Żadna podana granica tego DSP nie odmawia żadnemu z {legs} kanałów. To odpowiedź o SPRZĘCIE '
                   '— tryb PC-Tool (Fine EQ) może być węższy, a przełącza się go na ekranie. Żeby wnieść to do '
                   'projektu, naciśnij „Wyślij do zapisu”: wiersze wraz z prośbą trafią do pola dialogu z AI, '
                   'gdzie je przeczytasz i wyślesz. Bramka je sprawdzi, zapisze zrzut i wypisze arkusz ustawień, '
                   'który wprowadzasz w PC-Tool ręcznie.',
        "riCopyRows": 'Kopiuj wiersze (JSON)',
        "riCopied": 'Wiersze są w schowku.',
        "riFailed": 'Nie udało się odczytać tego pliku:',
        "riClose": 'Zamknij',
        "riImport": 'Import z projektu Resonalyze…',
        "npSeedNoInterview": 'Razem z nim przyjdzie dsp_profile.json, więc wywiadu o możliwościach nie będzie — nie ma o '
                             'co pytać, procesor jest już opisany. Wybierz inny DSP wyżej, a pójdzie jak zwykle.',
        "npSeedNoSkill": 'Skill autosound-tuning jest tu niedostępny, a kopiowanie mieszka w nim — zainstaluj skill '
                         'albo wypełnij nowy projekt ręcznie.',
        "npSeedOpen": 'W odziedziczonym profilu DSP jest jeszcze {open} faktów, których nikt nie potwierdził.',
        "groupFieldsUnknown": 'sterowanie jeszcze nie wyliczone',
        "menuProject": 'Projekt',
        "menuSession": 'Sesja i modele',
        "menuView": 'Wygląd',
        "menuTools": 'Narzędzia',
        "menuHelp": 'Pomoc i wsparcie',
        "menuLanguage": 'Język',
        "menuReload": 'Wczytaj ten projekt z dysku ponownie',
        "menuZoomIn": 'Większy tekst',
        "menuZoomOut": 'Mniejszy tekst',
        "menuDiagnostics": 'Diagnostyka i aktualizacje…',
        "menuTargetTool": 'Narzędzie krzywych docelowych (otworzy przeglądarkę)',
        "riImportTip": 'Bierze z sesji wirtualnego DSP Resonalyze same USTAWIENIA — po kanałach: crossovery, '
                       'opóźnienie, wzmocnienie, polaryzację i pasma EQ — i weryfikuje każdą wartość z tym, co twój '
                       'procesor faktycznie przyjmie. Nie samą sesję, i nic nie zapisuje: odmawia zamiast zaokrąglać '
                       'i oddaje wiersze, żebyś zapisał je przez bramkę strojenia.',
        "menuStartSession": 'Rozpocznij sesję strojenia w TCC',
        "menuTerminal": 'Otwórz terminal w tym projekcie',
        "menuModels": 'Skonfiguruj modele (OMP)…',
        "menuTheme": 'Zmień motyw (jasny / ciemny)',
        "menuCopyCar": 'Skopiuj auto…',
        "menuCopyCarTip": 'Zacznij projekt od już istniejącego: auto, sprzęt i montaż — marka, głośniki po kanałach, '
                          'wzmacniacze, mikrofon, DSP i jego profil, słownik nazw. To, co ZMIERZONO w tamtym projekcie, '
                          'zostaje tam, dopóki nie poprosisz. Poprawiasz to, co się różni, zamiast opisywać własne auto '
                          'od nowa.',
        "menuModelsTip": 'Jakich modeli wolno użyć temu projektowi — generator, krytyk i ile mają myśleć. Wszystko '
                         'oprócz Claude idzie przez OMP, więc to, co zaznaczysz tu, jest tym, po co OMP wolno sięgnąć.',
        "menuButton": '☰ Menu',
        "riUnchecked": 'Nic nie sprawdzono. Ten projekt nie mówi, jaki ma procesor, więc wszystkie {legs} kanałów są '
                       'pokazane, a żaden nie jest zweryfikowany — najpierw załóż auto (Menu ▸ Projekt) albo otwórz '
                       'to na projekcie, w którym jest dsp_profile.json.',
        "riUnboundVerdict": '{unbound} z {legs} kanałów pliku nie pasuje do żadnego kanału tego projektu. Ich wartości są '
                            'w porządku; wiersza bez kanału nie da się zapisać pod żadną nazwą. Powiąż je niżej albo '
                            'najpierw załóż kanały auta.',
        "riNoChannels": 'Ten projekt nie ma jeszcze kanałów — nie ma do czego tego powiązać. Najpierw załóż auto: '
                        'Menu ▸ Projekt ▸ Nowy projekt / Skopiuj auto.',
        "npCopy": 'Skopiuj',
        "npSeedTargetTaken": 'W folderze „{folder}” jest już projekt. Kopiowanie nigdy nie nadpisuje faktów, które ktoś '
                             'potwierdził — wybierz pusty albo nowy folder.',
        "leftRigOnly": 'To jest układ tak, jak opisuje go projekt — każdy kanał w swoim poziomie, na razie bez '
                       'wartości. Wartości przyjdą z pierwszym zrzutem ledgera, podczas strojenia.',
        "riProjectLink": 'Resonalyze autorstwa DIMOSUS — github.com/DIMOSUS/Resonalyze',
        "riSendRows": 'Wyślij do zapisu',
        "riSendFirst": 'Import z projektu Resonalyze — {file}. Zweryfikowano z profilem DSP tego projektu: {ok} '
                       'wartości wchodzi, żadnej odmowy, {unknown} niesprawdzonych. Projekt nie ma jeszcze ledgera, '
                       'więc zapisz to jako PIERWSZY zrzut presetu {preset}, przez bramkę. Niżej wiersze, po '
                       'kanałach:',
        "riSendPropose": 'Import z projektu Resonalyze — {file}. Zweryfikowano z profilem DSP tego projektu: {ok} '
                         'wartości wchodzi, żadnej odmowy, {unknown} niesprawdzonych. Zaproponuj to jako zmianę '
                         'presetu {preset} przez bramkę i pokaż arkusz ustawień. Niżej wiersze, po kanałach:',
        "riPair": 'para {pair}, {side}',
        "riSideLeft": 'lewa',
        "riSideRight": 'prawa',
        "tabGain": 'Poziom',
        "tabDelay": 'Opóźnienia',
        "tabPhase": 'Fazy',
        "paramAllChannels": '{param} · wszystkie kanały',
        "copyEqBank": 'Kopiuj EQ',
        "copyEqDone": '{channel}: bank EQ jest w schowku, w formacie {format}.',
        "copyEqLeftOut": 'Nie weszło, bo ten format tego nie niesie: {what}.',
        "copyEqNoFormat": 'Formatu EQ dla tego procesora jeszcze nie ma — nic nie skopiowano, zamiast dawać coś, czego '
                          'nikt nie wklei.',
        "quitSavingElapsed": 'Zapisuję przed wyjściem — {sec} s (do {max} min). Okno zamknie się samo, gdy model zapisze '
                             'stan projektu.',
        "quitAbandonTitle": 'Zapis wciąż trwa',
        "quitAbandonBody": 'Model zapisuje stan projektu już {sec} s. Zamknij teraz, a to, czego jeszcze nie zapisał, '
                           'przepadnie — rozmowa odejdzie razem z oknem.',
        "quitAbandonClose": 'Zamknij bez zapisu',
        "quitAbandonWait": 'Poczekaj',
        "copyEqCount": '{written} z {size} pasm — reszta zostanie zapisana jako pusta i nadpisze to, co jest teraz w '
                       'tych slotach.',
        "copyEqWritten": 'Pasm: {written}.',
        "copyEqCrossovers": 'Wraz z crossoverem: {n}.',
        "copiedValue": 'Skopiowano: {value}',
        "criticClipboardOnly": 'tylko schowek',
        "criticClipboardOnlyTip": '{model} to model producenta {vendor}, a ta maszyna nie ma ani jego klucza API, ani jego CLI. '
                                  '`call_critic` zadziała — odda ci pakiet do recenzji ręcznej — ale nic nie zostanie wywołane.',
        "criticUnknownVendorTip": 'Skrypt recenzenta wywołuje modele Google, Anthropic albo OpenAI; {model} nie jest żadnym z '
                                  'nich, więc żaden tutejszy transport go nie uruchomi. Zamiast wywołania odda ci pakiet do '
                                  'recenzji ręcznej.',
        "protTitle": 'Filtry ochronne tego przebiegu pomiarów',
        "protRound": 'Przebieg {series}. Co było w torze, gdy zdejmowano te sweepy.',
        "protNoRound": 'Nie otwarto przebiegu pomiarów, więc nie ma do czego pisać. Najpierw otwórz przebieg — zapis '
                       'o ochronie należy do tego przejścia, w którym mierzono.',
        "protWhy": 'Filtr ochronny siedzi W NAGRANIU: kręci fazą daleko poza własnym zboczem, a styk trzy razy '
                   'dalej może nieść około pięćdziesięciu stopni, które należą do stanowiska pomiarowego, a nie '
                   'do auta. Zapisany tutaj — da się go wyjąć z krzywej. „Mierzone bez niczego” to odpowiedź '
                   'warta zapisania; zostawienie kanału bez zapisu to nie to samo i nic dla niego nie zostanie '
                   'poprawione.',
        "protUnset": 'nie podano',
        "protOff": 'bez ochrony',
        "protFilter": 'filtry:',
        "protHp": 'HP Hz',
        "protLp": 'LP Hz',
        "protSave": 'Zapisz',
        "protRefused": '{channel}: {why}',
        "protBtn": 'Ochrona',
        "protBtnTip": 'Co było w torze, gdy zdejmowano ten przebieg — po kanałach. Zapisane da się wyjąć z '
                      'krzywych; niezapisane nie jest poprawiane, bo korekta nad nieznanym torem daje dane, które '
                      'tylko WYGLĄDAJĄ na poprawione.',
        "protNoChannels": 'Ten projekt nie ma jeszcze kanałów, więc nie ma do czego pisać filtra ochronnego.',
        "protWritten": 'Zapisano, co było w torze dla: {channels}. Ich krzywe da się czytać ze zdjętą ochroną.',
        "npCreate": 'Utwórz',
        "npCancel": 'Anuluj',
        "projectNewTip": 'Folder + DSP + kto prowadzi onboarding. Może też ZACZĄĆ SIĘ OD ISTNIEJĄCEGO PROJEKTU: auto, '
                         'głośniki, słownik i profil DSP przejeżdżają, a ty poprawiasz zamiast opisywać własne auto od '
                         'nowa.',
        "projectOpenTip": 'Wskaż TCC inny folder. Pusty też pasuje: stanie się nowym projektem, który wypełni rozmowa o '
                          'aucie. Potem TCC otworzy się na nowo w wybranym folderze — okno jest związane z jednym '
                          'projektem od samego startu.',
        "projectSaveStateTip": 'Prosi model, żeby zapisał plan, dowody i wszystko, czego się dowiedział, do plików projektu. '
                               'Rozmowa trwa dalej.',
        "projectFreshSessionTip": 'Najpierw zapisze, potem zacznie od nowa z pustym kontekstem na TYM SAMYM modelu. To nie to '
                                  'samo, co restart na innym: to dla rozmowy, która zrobiła się długa i droga, podczas gdy jej '
                                  'wnioski są już na dysku.',
        "gateTitle": 'Otwórz projekt strojenia',
        "gateBlurb": 'TCC pracuje na jednym folderze projektu i wiąże się z nim przy starcie. Wybierz istniejący '
                     'albo wpisz nową ścieżkę — pusty folder to poprawny nowy projekt, wypełni go rozmowa wstępna.',
        "gateFolder": 'Folder projektu',
        "gateFolderPlaceholder": '/ścieżka/do/auta',
        "gateBrowse": 'Przeglądaj…',
        "gateOpen": 'Otwórz',
        "gateNote": 'Oba modele zapamiętują się razem z tym projektem, a nie globalnie — inny projekt ma swoje. '
                    'Zmienisz je później w dolnym pasku.',
        "projectSwitchTitle": 'Zmień projekt',
        "projectSwitchBody": 'TCC wiąże jeden folder przy starcie, więc uruchomi się ponownie na „{name}”. Wszystko, czego '
                             'bieżąca sesja nie zapisała na dysk, przepadnie — zapisz najpierw, jeśli to ważne.',
        "projectNone": '⌂ wybierz projekt…',
        "projectOpen": 'Otwórz folder projektu…',
        "projectNew": 'Nowy projekt…',
        "projectSaveState": 'Zapisz na dysk to, co wie model',
        "projectFreshSession": 'Rozpocznij nową sesję (zapisze i wyczyści kontekst)',
        "projectReopen": 'Folder zmieniony — otwórz TCC ponownie, żeby z nim pracować.',
        "sessionSaved": 'Stan projektu zapisany na dysk. Sesja trwa dalej.',
        "savedTccOnly": 'Własne ustawienia TCC są na dysku. Sesja nie działa, więc nie ma o co prosić modelu.',
        "sessionFresh": 'Sesja zamknięta, stan zapisany — rozpoczynanie nowej z pustym kontekstem.',
        "generator": 'Generator',
        "preset": 'Preset',
        "target": 'Krzywa docelowa',
        "targetToolTip": 'Otwórz w narzędziu krzywych docelowych ↗',
        "params": 'PARAMETRY',
        "virtual": 'WIRTUALNE',
        "output": 'WYJŚCIOWE',
        "inputs": 'WEJŚCIA',
        "paramsRow": 'params · wszystkie parametry w tabeli',
        "tabTable": 'Tabela',
        "close": 'zamknij ✕',
        "outTitle": 'OUTPUT — fizyczne głośniki',
        "virtTitle": 'VIRTUAL — voicing wejściowy',
        "colChan": 'Kanał',
        "eqHint": 'Tylko pasma <b>w użyciu</b>, a przy każdym od razu wszystkie parametry. All-pass (APF) to '
                  'tutaj TYP pasma, a nie osobna kolumna. Bypass jest pokazany, ale z tego okna nie da się go '
                  'jeszcze zmienić. Nieużywane pasma banku są ukryte.',
        "shared": 'wspólne częstotliwości:',
        "noShared": 'brak wspólnych częstotliwości',
        "band": 'pasmo',
        "legWait": 'czekam',
        "legDone": 'gotowe',
        "legBad": 'zdjęty, nie nadaje się',
        "legSkip": 'pominięto',
        "stepTagOkTip": 'Zamknięty, a jego dowód naprawdę jest na dysku — nazwany plik lub pomiar znaleziono.',
        "stepTagUnprovenTip": 'Skill zamknął krok, ale dowód, który nazwał, nie wskazuje na nic na dysku: nie ma takiego '
                              'pliku ani pomiaru o tej nazwie.\n\nTo nie to samo, co krok bez ptaszka. Tamten po prostu nie '
                              'został skończony; ten zaraportowano jako skończony i nic za nim nie stoi.',
        "stepTagWaitTip": 'Albo wciąż w toku, albo zamknięty i od tego czasu unieważniony — zmiana konfiguracji '
                          'oznacza, że jego wynikowi nie można już ufać, więc trzeba zdjąć go ponownie.',
        "chanOn": 'WŁ',
        "chanOff": 'WYŁ',
        "chanTurnOn": 'WŁĄCZ',
        "chanTurnOff": 'WYŁĄCZ',
        "chanToggleQueued": 'Poproszono o przełączenie {channel} → {state}. Sesja nie działa, więc prośba czeka w '
                            'kolejce: model dostanie ją pierwszym ruchem następnej sesji.',
        "signalNudge": 'TCC zaczął ruch przez {count} twoich próśb z interfejsu — nikt nie rozmawiał, a kliknięcie '
                       'nie powinno na to czekać.',
        "signalNudgePrompt": 'Arbiter skorzystał z interfejsu. Najpierw obsłuż sygnały wypisane wyżej, potwierdź każdy '
                             'przez ack_signals, a potem krótko powiedz, co zrobiłeś.',
        "chanToggleWaiting": 'poproszono · {secs}s',
        "chanToggleLate": '⚠ brak odpowiedzi · {secs}s',
        "chanToggleWaitTip": 'TCC poprosił model, żeby to zapisał; ledger pisze skill, nie TCC. Wiersz zmieni się, gdy '
                             'model odpowie. Ponowne kliknięcie tylko odświeża oczekiwanie, drugiej prośby nie wysyła.',
        "chanToggleAlreadyAsked": '{channel} — już poproszono, czekam na model. Drugi raz nie wysłano.',
        "chanToggleTip": 'Poproś model, żeby włączył albo wyłączył ten kanał. TCC nie pisze ledgera — prośba idzie do '
                         'sesji, a ona zapisuje zmianę.',
        "chanToggleSent": 'Poproszono o przełączenie <b>{channel}</b> → {state}. Model zapisze to w ledgerze; drzewo '
                          'nadąży, gdy zapis powstanie.',
        "noSessionForSignal": 'Sesja nie działa — uruchom ją, a prośba do niej dotrze.',
        "chanToggleConfirmTitle": 'Przełączyć ten kanał?',
        "chanToggleConfirmOff": 'Wyłączyć <b>{channel}</b>?\n\nJego EQ, crossover i opóźnienie żyją w ledgerze i mogą nie '
                                'przeżyć wyłączenia. TCC tego nie cofnie — zmianę zapisuje model.',
        "chanToggleConfirmOn": 'Włączyć <b>{channel}</b>?\n\nTo zmiana strukturalna: kanał potrzebuje miejsca w słowniku, a '
                               'fizyczne wyjście — swojego wirtualnego odpowiednika. Model to wyliczy i zapisze.',
        "pillMute": 'MUTE',
        "pillOff": 'OFF',
        "attempt": 'próba',
        "addStep": '+ dodaj krok',
        "addStepPrompt": 'Krok sytuacyjny (tylko ten projekt):',
        "measRead": 'Odczytaj',
        "measReading": 'Czytam z REW…',
        "measReadOk": 'Odczytano z REW pomiarów: {n} · pasuje {matched}, dodatkowych {extra}',
        "measReadFail": 'Nie udało się odczytać z REW: {error}',
        "measReadNoMeas": 'W REW nie ma pomiarów.',
        "measUsedInStep": 'Użyto w kroku {steps}',
        "assignNames": 'Nadaj nazwy',
        "captureOrderTitle": 'Kolejność zdejmowania',
        "captureOrderHint": 'Wybierz metodę zdejmowania, potem przeciągnij, żeby kolejność odpowiadała temu, jak naprawdę '
                            'zdejmujesz kanały w REW. Zapisuje się osobno dla każdej metody i służy następnym razem.',
        "captureMethodSw": 'SW',
        "captureMethodRta": 'RTA',
        "captureMethodRtaGroup": 'RTA GROUP',
        "captureScanMismatch": 'W REW znaleziono nowych pomiarów: {found}, oczekiwano {expected} (po jednym na kanał w '
                               'zapisanej kolejności). Zdejmij brakujące albo sprawdź kolejność i spróbuj ponownie.',
        "captureRenaming": 'Zmieniam nazwy pomiarów w REW: {n}…',
        "captureRenameOk": 'Zmieniono nazwy pomiarów zgodnie z zapisaną kolejnością kanałów: {n}.',
        "captureRenameFail": 'Zmiana nazw zatrzymała się po {n} pomiarach: {error}',
        "effectProcess": 'zapisać proces (plan, kroki, dziennik)',
        "effectProfile": 'zapisać profil możliwości DSP',
        "effectLedger": 'zapisać zrzut ustawień DSP do ledgera',
        "effectProject": 'zapisać własne pliki projektu',
        "effectContract": 'sprawdzić projekt według kontraktu skilla',
        "gateMode": 'Pytać o',
        "gateWrites": 'każdy zapis',
        "gateForeign": 'tylko o to, czego skill nie posiada',
        "gateModeTip": 'Skill nieustannie pisze do `process/`, `state/` i własnych plików projektu, a nowy projekt '
                       'nie pyta o nic z tego: pytanie przy każdym `ls` to pytanie, które uczysz się przeklikiwać, a '
                       'wtedy niczego nie chroni. Zatrzymuje się to, co zmienia auto — własne zapisy TCC do DSP i '
                       'REW pytają wewnątrz narzędzia niezależnie od tego ustawienia. Zawęź tutaj, jeśli chcesz mieć '
                       'przed oczami także ruch plikowy.',
        "configureModels": 'modele…',
        "configureModelsTitle": 'Modele w wyborze generatora',
        "configureModelsBlurb": 'omp raportuje każdy model, o którym wie. Zaznacz te, do których masz dostęp — właśnie one '
                                'trafią do wyboru generatora. Claude idzie przez Agent SDK i jest dostępny zawsze.',
        "configureModelsFilter": 'filtruj po nazwie, dostawcy albo id',
        "configureModelsCount": 'w katalogu omp: {n}',
        "configureModelsSetup": 'Skonfiguruj omp…',
        "configureModelsSetupTip": 'Otwórz własną konfigurację omp w terminalu — tam ustawia się konta, klucze API i logowania. '
                                   'To ona decyduje, jakie modele pojawią się na liście wyżej, więc gdy skończysz i wrócisz '
                                   'tutaj, lista zostanie odczytana ponownie. TCC nie trzyma żadnych z tych danych: terminal i '
                                   'sesja w nim są twoje.',
        "configureModelsSetupOpened": 'Konfiguracja omp jest otwarta w terminalu. Gdy skończysz, wróć do tego okna — lista zostanie '
                                      'odczytana ponownie.',
        "mcpDown": 'Serwer MCP nie działa, więc sesja nie ma przez co sięgnąć do TCC. Uruchom TCC ponownie; '
                   'jeśli się powtarza — przyczyna jest tutaj i w logu:',
        "mcpDownLog": 'log:',
        "modelClipboardOnly": 'tylko schowek',
        "modelInstallCli": 'zainstaluj CLI {cli}',
        "modelRecommended": 'zalecana para',
        "modelGoneTitle": 'Tego modelu już się nie oferuje',
        "modelGone": 'W projekcie ustawiono {model}, a na tej maszynie nie ma już czym go uruchomić — modele '
                     'wychodzą z obiegu. Wybierz, co ma działać zamiast niego; podmiana obowiązuje wszędzie, gdzie '
                     'ta nazwa jeszcze występuje, nie tylko tutaj.',
        "modelGoneWhy": 'już niedostępny na tej maszynie',
        "modelAliased": '{old} działa teraz jako {new} na tej maszynie. Sesje to mówią, żeby zapis nie twierdził '
                        'czegoś innego.',
        "cliRouteQuiet": '{routes} jest zainstalowany, ale nie podał modeli — mógł wygasnąć jego własny login. Jego '
                         'pozycji brakuje w wyborze recenzenta, ale to nie znaczy, że trasy nie ma.',
        "modelFree": 'za darmo',
        "ompMissing": '⚠️ omp nie jest zainstalowany — brew install can1357/tap/omp, albo wybierz model Claude.',
        "copyValue": 'Kopiuj wartość',
        "copyRow": 'Kopiuj wiersz',
        "copyHint": 'Kopiuj podpowiedź',
        "copySelection": 'Kopiuj zaznaczenie',
        "copyMessage": 'Kopiuj wiadomość',
        "aiMain": 'AI main',
        "aiEffort": 'Wysiłek',
        "aiCritic": 'AI critic',
        "effort_high": 'high',
        "effort_xhigh": 'x-high',
        "effort_max": 'max',
        "effortTip_high": 'Wystarczy do kroków rutynowych. Dolna granica dla strojenia — niżej model zgadza się zbyt '
                          'łatwo.',
        "effortTip_xhigh": 'Wartość domyślna, z zapasem. Pasuje do niemal każdego kroku strojenia.',
        "effortTip_max": 'Do kroku naprawdę trudnego. Nic nie podnosi się tu samo — sesja zaczęta niżej tam zostanie, '
                         'choćby praca okazała się bardzo trudna. Wolniej, a na trasie licznikowej także drożej.',
        "effortNextSession": 'Wysiłek zadziała od następnej sesji — ta zostaje na poziomie, z którym wystartowała.',
        "note": 'prototyp · prawdziwe dane (sound_AutoSci) · dopracowujemy formę',
        "coffeeBtn": '☕ Postaw mi kawę',
        "supportGithub": '💜 GitHub Sponsors',
        "supportMonobank": '☕ Zbiórka na Monobank',
        "fbBig": 'Napisz do dewelopera',
        "fbBigTip": 'Błąd, pomysł, pytanie, „to nie ma sensu” — wszystko tutaj. Można dołączyć zrzut ekranu.',
        "fbHead": 'Opinia o prototypie TCC',
        "fbHint": 'Napisz, co się podoba / co zmienić. Skorzystaj z przycisków B / I / lista — nie trzeba pisać '
                  'markdowna ręcznie.',
        "fbPh": 'Twoja opinia o prototypie…',
        "fbCancel": 'Anuluj',
        "fbSendGithub": 'Wyślij na GitHub →',
        "fbSendForm": 'Wyślij przez formularz →',
        "fbVia": 'Jak wysłać:',
        "fbViaGithub": 'Issue na GitHubie (mam konto)',
        "fbViaForm": 'Formularz Google (konto niepotrzebne)',
        "dialog": 'Dialog z AI',
        "dialogSub": 'Generator ↔ Critic ↔ Arbiter',
        "planTitle": 'Plan — Fakt',
        "planSub": 'fazy + kroki',
        "focus": '◆ TERAZ W FOKUSIE',
        "measSub": 'zadanie pomiarowe',
        "confirmAlways": 'Nie pytaj o to więcej w tym projekcie',
        "gateAuto": 'Nie pytaj wcale (auto)',
        "gateAutoTip": 'Narzędzia harnessa (powłoka, odczyty, edycje) działają bez pytania. Własne zapisy TCC do DSP '
                       'i REW wciąż pytają — to one zmieniają auto.',
        "autoAllowed": 'Auto-zgoda na <code>{tool}</code> — pytanie o to jest w tym projekcie wyłączone.',
        "questionCancelled": 'Pytanie wycofano — tura może trwać dalej.',
        "questionWithdrawn": 'Agent wycofał to pytanie.',
        "questionWaiting": 'Czeka na twoją odpowiedź',
        "questionFreeText": 'Wpisz odpowiedź poniżej — tu nie ma opcji do wyboru.',
        "questionRole": 'PYTANIE',
        "composerAnswer": 'Odpowiedz albo wpisz własną…',
        "composerQueue": 'Napisz do Generatora… (pójdzie, gdy tura się skończy)',
        "composer": 'Napisz do Generatora…',
        "queueWaiting": '⏳ {count} twoich wiadomości pójdzie, gdy ta tura się skończy',
        "queueSendNow": 'Wyślij teraz',
        "newBelow": '↓ Nowe poniżej · {count}',
        "newBelowTip": 'Gdy czytałeś, niżej pojawiły się nowe wiadomości. Pierwsze kliknięcie na ich początek, '
                       'drugie na sam dół.',
        "messageNotSent": 'Nie wysłano: sesja się zatrzymała. Twój tekst wrócił do pola.',
        "quitSaving": 'Zapisuję przed wyjściem — czekam, aż model zapisze stan projektu. Okno zamknie się samo, gdy '
                      'to nastąpi.',
        "send": 'Wyślij',
        "stop": 'Stop',
        "notVisible": 'Nie widzę tej zmiany',
        "notVisibleHint": 'Powiedz AI, że coś, co zmieniło, nie pojawiło się tutaj — żeby sprawdziło po dysku, zamiast '
                          'powtarzać swoje twierdzenie.',
        "notVisibleSent": 'Zaznaczono dla AI: <b>tego, co zgłosiła, tu nie widać</b> — sprawdzi po dysku.',
        "agentThinking": 'Pracuje…',
        "agentFailed": 'Błąd sesji',
        "confirmAllowed": 'Arbiter <b>zezwolił</b> na <code>{tool}</code>.',
        "confirmDenied": 'Arbiter <b>odrzucił</b> <code>{tool}</code>.',
        "modelUnchosen": '— wybierz model —',
        "startSessionNoModel": 'Najpierw wybierz model generatora.',
        "startSessionReady": 'Uruchom sesję na {model}. Do tego czasu nic nie działa.',
        "startSessionRunning": 'Sesja już działa.',
        "restartSession": '▶ Uruchom ponownie na {model}',
        "restartSessionTip": 'Żaden harness nie zmienia modelu w trwającej rozmowie — bieżąca się zakończy i zacznie się '
                             'nowa sesja.',
        "sessionStarting": 'Uruchamiam {model} — pierwsza tura czyta skilla i stan projektu, dlatego jest powolna.',
        "sessionHandoff": 'Zapisuję stan projektu przed zmianą modelu…',
        "sessionHandoffSave": 'Proszę model, żeby zapisał to, co wie, do plików projektu…',
        "sessionHandoffQuit": 'Zapisuję przed zamknięciem — proszę model, żeby zapisał to, co wie, do plików projektu…',
        "quitSaveSave": 'Zapisz turę',
        "quitSaveDiscard": 'Nie zapisuj',
        "quitSaveCancel": 'Zostań',
        "quitSaveTitle": 'Zapisać przed zamknięciem?',
        "quitSaveBody": 'Sesja trwa.\n\nTo, czego dowiedziała się w tej turze, nie jest na dysku, dopóki tego nie '
                        'zapisze — zamknięcie teraz to zgubi. Zapis kosztuje jedną turę.',
        "sessionHandoffFresh": 'Najpierw zapisuję, potem zaczynam nową sesję z pustym kontekstem…',
        "sessionRestarted": 'Sesja zamknięta: restart na nowo wybranym modelu.',
        "dialogIdle": 'nie uruchomiono · {model}',
        "dialogNoModel": 'nie wybrano modelu',
        "startSession": '▶ Sesja w TCC',
        "openTerminal": '⧉ Terminal',
        "terminalOpened": 'Otwarto terminal z <code>{cli}</code> w folderze projektu. Podchwyci TCC przez '
                          '<code>.mcp.json</code>; przy pierwszym uruchomieniu zatwierdź serwer <b>tcc</b>.',
        "criticClipboard": 'Ani API, ani CLI recenzenta nie było osiągalne, więc pakiet jest w <b>schowku</b>. Wklej go '
                           'w dowolny czat AI, a odpowiedź wklej z powrotem tutaj — pętla działa, tylko idzie przez '
                           'ciebie.',
        "criticFailed": 'Wywołanie recenzenta nie powiodło się: {detail}',
        "criticNotReady": 'Recenzent nie ma jeszcze czego czytać. Przy każdym wywołaniu czyta projekt z dysku od nowa, '
                          "a ten folder nie przeszedł jeszcze intake'u — kontrakt i kontekst auta powstają, gdy zaczyna "
                          'się strojenie. Sam kanał jest sprawny; zacznij strojenie, a recenzent zadziała od pierwszej '
                          'propozycji.',
        "criticNever": 'Krytyk: jeszcze nie wywoływany',
        "curveSendMarkers": 'Markery',
        "curveSendDelays": 'Opóźnienia',
        "curveShift": 'opóźnienie',
        "curveShiftTip": 'Przytrzymaj wybrany głośnik — przełącznik wybiera który. Zaczyna od tego, który przychodzi '
                         'PIERWSZY (naturalny wybór przy pierwszym przejściu); wartość ujemna jest dozwolona, bo przy '
                         'kolejnych przejściach poprawiasz kanał, w którym opóźnienie już jest. Poniżej zera nie może '
                         'zejść SUMA na kanale — i odczyt to powie, gdy rejestr jest znany. Krok taki, jaki pozwala '
                         'wpisać ten DSP. Nic nie jest stosowane: odczyt idzie jako propozycja.',
        "curveDelayHead": 'opóźnienie do wyrównania (propozycja, nie zastosowano):',
        "curveApfLabel": 'all-pass:',
        "curveApfNone": '—',
        "curveApfTip": 'All-pass dla głośnika wybranego przełącznikiem — tego samego, który poprawia pole '
                       'opóźnienia. NIE zmienia poziomu i obraca fazę wokół f0: APF1 obraca o −90° na f0 (łącznie 0 '
                       '→ −180°), APF2 o −180° na f0 (0 → −360°), a Q mówi, jaka część tego obrotu przypada tuż przy '
                       'f0. Na charakterystyce krzywa się nie rusza; na fazie się obraca; i tu, i tam prognozowana '
                       'suma (Σ) pokazuje, co to robi ze stykiem — i o to chodzi. Na impulsie narysowany przebieg '
                       'zostaje taki, jak zdjęty (all-pass rozmazuje impuls); sumę niesie pasek. Nic nie jest '
                       'stosowane: idzie jako propozycja w odczycie, słowami rejestru (APF2 250 Hz Q 0.71). I '
                       'all-pass nie wypełnia dołka jednego głośnika — obrotem fazy przestraja się tylko sumę dwóch '
                       'nakładających się głośników, więc czytaj go po sumie, nigdy po jednej krzywej. Matematyka '
                       'jest własna skilla (dsp_math), nie ma tu jej drugiej kopii.',
        "curveApfKindTip": 'Który rząd. APF1: sama f0, tam −90° — łagodniejsza ćwierć obrotu. APF2: f0 i Q, tam −180° — '
                           'to, co przyjmuje slot APF2 w banku PEQ. Dwa APF1 na jednej f0 to jeden APF2 z Q 0.5.',
        "curveApfF0Tip": 'Częstotliwość, wokół której obraca się faza. Ustaw ją tam, gdzie jest styk — na '
                         'częstotliwości crossovera między dwoma sumowanymi głośnikami.',
        "curveApfQTip": 'Jaka część z 360° przypada tuż przy f0 (tylko APF2). 0.71 obraca mniej więcej przez półtorej '
                        'oktawy w obie strony od f0; wyższe Q obraca szybciej i gorzej trzyma się przy dryfie, jaki '
                        'ma prawdziwe auto — własne poszukiwanie skilla zatrzymuje się na 4.',
        "curveApfHead": 'all-pass do obrotu fazy (propozycja, nie zastosowano):',
        "curveApfNoMaths": 'nie da się zasymulować all-passa: nie udało się wczytać matematyki filtrów skilla ({error})',
        "unitMs": 'ms',
        "unitSmp": 'próbek',
        "curveDelayRelative": 'Względem {name}, który zostaje bez opóźnienia: mierzono tylko różnice między tymi '
                              'głośnikami, więc zestaw podano od tego, który potrzebuje najmniej.',
        "curveDelayLands": 'przyjście {was} → {now} ms',
        "curveDelayTotal": 'na kanale → {total} ms',
        "curveDelayBelowZero": '⚠ poniżej zera — kanał nie może tam zejść',
        "curveBankImpossible": 'Coś z tego wyprowadza kanał poniżej zera, więc zestawu w tej postaci nie da się zastosować — '
                               'powiedz, który punkt odniesienia ruszyć zamiast tego.',
        "curveBankLabel": 'odczytane opóźnienia:',
        "curveBankLabelIn": 'odczytane opóźnienia w {set}:',
        "curveBankBtn": 'Odczytane opóźnienia ({n})',
        "curveSumNoteBtn": 'Σ prognoza',
        "curveGuidesTip": 'Zdejmij z obrazu wszystkie prowadnice: markery, poziomy, linię krzyżową i jej punkty. Nic '
                          'nie ginie — każda wraca dokładnie tam, gdzie była, a odczyt zostaje tym samym zdaniem, bo '
                          'niewidoczny marker to wciąż liczba, którą zdjąłeś. Gdy są schowane, nie da się ich '
                          'przeciągnąć.',
        "curveStripLinkTip": 'Podążaj za skalą częstotliwości wykresu. Na fazie pasek i wykres to te same częstotliwości, '
                             'więc jeden zoom rusza obydwa i to, co widać na 3 kHz u góry, jest na 3 kHz na dole. Wyłącz, '
                             'żeby przybliżyć dołek osobno, i włącz z powrotem, żeby znów je zestawić. Na impulsowej '
                             'niedostępne: tam osią jest czas.',
        "curveReadoutBtn": 'Markery',
        "curveBankEmpty": 'opóźnień jeszcze nie ma — ustaw wyżej, a zostanie zapamiętane przy pomiarze',
        "curveClearLabel": 'wyczyść:',
        "curveClearDelay": 'Opóźnienia',
        "curveClearMarkers": 'Markery',
        "curveBankAsk": 'Opóźnienia odczytane przeze mnie z krzywych, TYLKO DO ANALIZY — nigdzie ich nie zapisuj i '
                        'nie traktuj jako zmiany:',
        "curveBankConvention": 'Umowa: wszystkie pomiary mają wspólny początek czasu (0 ms na osi impulsowej). Każda liczba '
                               'niżej dodaje się do przyjścia TEGO pomiaru, tak jak go zdjęto; celem jest, żeby wszystkie '
                               'głośniki wypadły na tym samym przyjściu.',
        "curveBankArrival": 'przyjście',
        "curveBankChannel": 'kanał',
        "curveBankSpread": 'Rozrzut przyjść na {n} rozmieszczonych głośnikach: {spread} ms.',
        "curveBankAtZero": 'Na ekranie, przesunięcia nie podano (0). To może być odniesienie, od którego liczono resztę, '
                           'albo po prostu głośnik, do którego jeszcze nie doszły ręce — z tych danych nie da się tego '
                           'rozróżnić: {names}',
        "curveBankUnplaced": 'NIE rozmieszczone — na tych nie zrobiono jeszcze odczytu, więc nie ma ich na obrazie wyżej i '
                             'NIE wolno zakładać, że są na zerze: {names}',
        "curveBankNotForWriting": 'Powiedz, czy ten zestaw jest spójny: jakie przyjścia oznacza, czy coś z tego nie wygląda '
                                  'raczej na błąd pomiaru niż na strojenie, i co sprawdziłbyś dalej. To odczyty z krzywych, a '
                                  'nie cel — samo dokładne zrównanie przyjść nie naprawiało w tym aucie dokładności sceny, więc '
                                  'traktuj je jako świadectwo i powiedz, co byś zmienił i dlaczego. Nic z tego nie jest '
                                  'zastosowane.',
        "curveBankAskApfOnly": 'Filtry all-pass, które ustawiłem na zmierzonych krzywych, TYLKO DO ANALIZY — nic nie '
                               'zapisuj.',
        "curveBankApf": 'All-pass po głośnikach, ustawiane przy obserwacji prognozowanej sumy (propozycja, nie '
                        'zastosowano; nie zmienia poziomu, tylko fazę; APF1 = −90° na f0, APF2 = −180° na f0):',
        "curveBankApfCaveat": 'Zasymulowane na posiadanych sweepach przez obrót zmierzonej fazy; NIE zweryfikowane pomiarem '
                              'sumowania. Powiedz, czy ten obrót naprawia styk, czy tylko przenosi problem (i ciągnie za '
                              'sobą timing powyżej f0), i jaki pomiar by to potwierdził.',
        "curveNoMarkers": 'Przeciągnij marker na punkt, który masz na myśli.',
        "curveMarkerModel": 'model',
        "curveMarkerYou": 'ty',
        "curveMarkerOne": '1',
        "curveMarkerTwo": '2',
        "curveMarkerN": 'marker {n}',
        "curveTitle": 'Gdzie dokładnie?',
        "curveAxes_v": 'Markery czytają częstotliwość (pionowe)',
        "curveAxes_h": 'Markery czytają poziom (poziome)',
        "curveAxes_vh": 'Markery czytają jedno i drugie, ustawiane osobno',
        "curveAxes_vhs": 'Jeden punkt na krzywej daje oba — poziom idzie za częstotliwością',
        "curveAxes_vx": 'Jedna pionowa linia: czyta OBIE krzywe przy tym x i różnicę między nimi',
        "curveAxes_hx": 'Jedna pozioma linia: czyta, gdzie KAŻDA krzywa osiąga ten poziom (przecięcie najbliższe '
                        'środka widoku)',
        "curveCrossPairTip": 'Które dwie krzywe porównują Vx i Hx. Czytają jedną różnicę między jedną parą, więc gdy '
                             'krzywych jest więcej — parę wskazujesz ty; zwykłe markery V/H/VH nadal czytają każdą krzywą, '
                             'po jednej liczbie na każdą.',
        "curveSumTip": 'Σ — pokaż, co te głośniki robią RAZEM: zespolona suma krzywych na ekranie, kreskowana, w dB, '
                       'z już zastosowanym opóźnieniem każdego głośnika. Na fazie kładzie się na wykres po prawej '
                       'osi; na impulsowej dostaje własny pasek pod spodem, bo tam osią wykresu jest czas, a sumy — '
                       'częstotliwość. To arytmetyka na pomiarach, które już masz, więc zgadywanie nic nie kosztuje '
                       'i nigdzie nic się nie zapisuje. Znaczy coś tylko wtedy, gdy wszystkie pomiary zdjęto od '
                       'JEDNEGO wspólnego odniesienia czasu; przycisk Σ pod wykresem niesie werdykt — co sprawdzono, '
                       'a czego nie.',
        "curveSumHead": 'Prognozowana suma, kreskowana, w dB:',
        "curveSumWorst": 'Najniższy punkt sumy: {depth} dB względem najgłośniejszego pojedynczego głośnika w tym '
                         'miejscu, przy {hz} Hz.',
        "curveSumNone": 'Sumy nie narysowano.',
        "curveSumNoPlot": 'Ten widok nie zdołał zbudować osi, na której rysuje się sumę, więc nie ma jej gdzie położyć. '
                          'Reszty okna to nie dotyczy.',
        "curveSumTooFew": 'Jedna krzywa to nie suma: postaw na ekranie drugi pomiar.',
        "curveSumNoData": 'Te krzywe nie niosą ani amplitudy, ani fazy, żeby je dodać — nie pochodzą ze sweepa REW.',
        "curveGroupLabel": 'wypełnij:',
        "curveGroupNone": '— bez grupy —',
        "curveGroupKind_pairs": 'para',
        "curveGroupKind_joints": 'styk',
        "curveGroupKind_sides": 'strona',
        "curveGroupKind_combos": 'zestaw',
        "curveGroupNoGlossary": '— w tym projekcie nie ma słownika —',
        "curveGroupTip": 'Wypełnij wybór całą grupą naraz — mid-basy, średnie, sub+mid-basy, jedną stronę, wszystko. '
                         'Nazwy pochodzą ze słownika tego auta, a sweepy — te z wersji konfiguracji obok. Nic zbędnego '
                         'się nie dociąga: uczestnik, dla którego REW nie ma sweepa, zostaje wymieniony, a nie po '
                         'cichu pominięty. Grupa WYPEŁNIA i puszcza: zdejmiesz potem jeden chip i nic się nie '
                         'podstawia z powrotem — i właśnie tak słychać, co ten jeden głośnik robi ze stykiem.',
        "curveGroupVersionTip": 'Z której serii pomiarów bierze się sweepy grupy — to konfiguracja DSP, pod którą je zdjęto; '
                                'w nazwie pomiaru w REW stoi jako `_N` i tak samo nazywa się w panelu pomiarów. Zaczyna od '
                                'serii wspólnej dla krzywych już na ekranie albo od najnowszej, jaką to auto ma dla tych '
                                'głośników, i można ją zmienić.',
        "curveGroupMissing": '{group} na _{version}: {names} — tego nie ma w REW. Narysowano sumę innego zestawu.',
        "curveGroupEmpty": '{group} na _{version}: w REW nie ma sweepa żadnego uczestnika, więc nic nie zmieniono.',
        "curveChooseBtn": 'Wybierz… ({n})',
        "curveChooseTip": 'Zaznacz dowolne pomiary — suma przyjmie ich tyle, ile dasz. Menu zostaje otwarte, więc cała '
                          'strona to jedno przejście przez listę. Wszystko zaznaczone stoi jako chip wyżej, w kolorze '
                          'swojej krzywej; grupa obok wypełnia te same chipy jednym ruchem.',
        "curveChipRemoveTip": 'Zdejmij {title} z wykresu. Reszta zostaje na miejscu, a suma przelicza się bez niego — i '
                              'właśnie tak słychać, co ten jeden głośnik robi ze stykiem.',
        "curveChipOnlyTip": 'Jedyna krzywa na ekranie. Dodaj drugą, zanim zdejmiesz tę — okno, które nic nie rysuje, nic '
                            'nie mówi.',
        "curveChipMissingTip": 'REW nie dał krzywej dla {title}, więc nie ma go na wykresie, choć jest zaznaczony — i w '
                               'sumie też go nie ma. Dlatego jest blady.',
        "curveAt": 'przy',
        "curveZoomAll": 'Pokaż wszystko, co jest w pomiarze',
        "curveZoomAllShort": 'A',
        "curveZoomDetail": 'Z powrotem do zakresu, od którego zaczęliśmy',
        "curveZoomDetailShort": 'D',
        "curveZoomOut": 'Oddal',
        "curveZoomOutShort": '−',
        "curveZoomIn": 'Przybliż',
        "curveZoomInShort": '+',
        "curveKind_impulse": 'impulsowa',
        "curveKind_fr": 'charakterystyka',
        "curveKind_phase": 'faza',
        "curveRtaOnly": 'Pokazano charakterystykę: {titles} — pomiar MMM, a dla niego REW nie ma ani impulsowej, ani '
                        'fazy.',
        "curveRtaTip": 'Pomiar MMM: REW nie ma dla niego ani impulsowej, ani fazy. Przejdź na charakterystykę, żeby '
                       'zobaczyć go na wykresie.',
        "curveKindRtaTip": 'Nie dla pomiaru MMM — REW nie ma dla niego ani impulsowej, ani fazy. Żeby to czytać, wybierz '
                           'wyżej sweepy (sw).',
        "curveBtn": 'Krzywe — postaw marker tam, gdzie masz na myśli',
        "curveNothing": 'Nie ma jeszcze czego rysować — najpierw odczytaj pomiary z REW.',
        "curveLoading": 'Czytam krzywe z REW…',
        "curveFailed": 'Nie udało się odczytać z REW: {error}',
        "modelMissingRow": '{key} — tu niedostępny',
        "modelMissingTip": 'Ten projekt prosi o model, którego ta maszyna nie oferuje. Zostaje wybrany i zostaje '
                           'czerwony, dopóki nie wybierzesz innego — nic nie jest przekierowywane za twoimi plecami.',
        "modelUnconfirmed": 'z poprzedniego uruchomienia',
        "attachTip": 'Dołącz zrzut ekranu — zapisuje się w projekcie, model czyta plik',
        "attachTitle": 'Dołącz zrzut ekranu',
        "attachClear": 'Wyczyść',
        "attachEmptyMac": '⌘⌃⇧4 kopiuje zrzut do schowka (⌘⇧4 zamiast tego zapisuje go na Biurku). Potem naciśnij tu '
                          '⌘V.',
        "attachEmptyWin": 'Win+Shift+S kopiuje zrzut do schowka. Potem naciśnij tu Ctrl+V.',
        "attachEmptyOther": 'Skopiuj zrzut do schowka, potem naciśnij tu Ctrl+V.',
        "attachCaption": 'Co na nim jest — np. „impulsowa w-L, pierwszy szczyt”',
        "criticWarnTitle": 'O recenzencie',
        "criticSubstituted": 'podmieniono',
        "criticAnswered": 'odpowiedział {model}',
        "criticSameVendor": 'ten sam producent co Generator',
        "criticSameVendorTip": 'Recenzent i Generator to obaj {vendor}. Recenzja nadal się odbywa, ale recenzent wybrany dla '
                               'niezależności międzyproducenckiej przestał nią być — waż jego zgodę niżej albo przywróć '
                               'innego producenta.',
        "sdkNoLogin": 'claude nie jest zalogowany',
        "sdkNoLoginTip": 'Modele Claude działają przez twoją własną sesję `claude` — TCC nie ma własnego konta i nie '
                         'zaloguje cię za ciebie. Dopóki się nie zalogujesz, ta trasa nie odpowie, cokolwiek pokazuje '
                         'wybierak. W terminalu wykonaj:\n\n    {cmd}',
        "criticStatus": 'Krytyk · {model} · {ago}',
        "sessionResumed": 'wznowiono',
        "sessionNew": 'nowa sesja',
        "editChipLabel": 'Edycja parametrów projektu',
        "editReasonsQ": 'Dlaczego?',
        "reasonForgot": 'skill nie zapisał',
        "reasonManual": 'zmieniłem coś ręcznie',
        "editStartForgot": '◆ Edycja parametrów projektu — oznaczono: skill mógł nie zapisać ostatniej zmiany. Opisz, co '
                           'powinno być w ledgerze; sprawdzę i poprawię.',
        "editStartManual": '◆ Edycja parametrów projektu — zmieniłeś coś ręcznie. Powiedz, co i gdzie; zapiszę to w '
                           'ledgerze, żeby kolejne rekomendacje to uwzględniały.',
        "editDoneForgot": '✓ Sprawdzono ledger: w <code>Rear R Full</code> opóźnienie w dialogu wynosiło 9.5 ms, a na '
                          'dysku 8.0 ms — poprawione, zapisane ponownie jako 9.5 ms.',
        "editDoneManual": '✓ Zapisano: <code>Front R High</code> wzmocnienie 1.4 → 1.0 dB (ręcznie). Ledger '
                          'zaktualizowany i ponownie zatwierdzony.',
        "targetHandedOver": 'Narzędzie nie zawiera „{name}”, więc krzywa pojechała na stronę w samym linku — powinna być '
                            'na wykresie jako „{name}”. Jeśli jej tam nie ma, opublikowane narzędzie jest starsze niż ta '
                            'aplikacja; powiedz, a będzie przekazywana plikiem.',
        "targetLocalViewer": 'Narzędzie nie zawiera „{name}”, więc to jego LOKALNA kopia z już naniesioną twoją krzywą — '
                             'zbudowana z wersji metody, na której stoi aplikacja, a nie żywa strona. Cała reszta w niej '
                             'jest narzędzia.',
        "targetNotInTool": 'Narzędzie nie zawiera „{name}” — ma tylko własne krzywe metody, a każdą inną poznaje z '
                           'pliku, który na nie przeciągniesz. Twój jest zaznaczony w menedżerze plików: przeciągnij go '
                           'na stronę.',
        "targetNoFile": 'Narzędzie nie zawiera „{name}”, a pliku dla niej w tym projekcie nie znaleziono — strona '
                        'otworzy się z krzywymi, które ma. Wyeksportuj krzywą do rew_analitic/target-curves/{name}/, '
                        'a będzie można ją przeciągnąć.',
        "targetRevealFailed": 'Narzędzie nie zawiera „{name}”. Menedżer plików się nie otworzył; plik jest tutaj: {path} — '
                              'przeciągnij go na stronę.',
        # Phase 4, the listening panel (2026-08-25).
        "lsnDropLast": 'Cofnij ostatnią',
        "lsnBtn": 'Odsłuch',
        "lsnBtnTip": 'Co dokładnie ten utwór ma pokazać — słowami; oraz 🟢/❌ z twoim zdaniem, zapisane w dzienniku '
                     'wobec stanu, którego słuchałeś.',
        "lsnTitle": 'Odsłuch — co oceniać i co usłyszałeś',
        "lsnWhy": 'Wybierz utwór po prawej, potem frazę, która pasuje do tego, co słyszysz. Trafi do pola po '
                  'lewej jako wiersz, który możesz przepisać. Zapisuje się i zaznaczenie, i twoje słowa, i '
                  'jedno nie zastępuje drugiego: zaznaczenie czyta potem filtr, słowa to jest to, co miałeś na '
                  'myśli.',
        "lsnRoute": 'Przejście',
        "lsnRoute_first": 'pierwszy odsłuch',
        "lsnRoute_short": 'krótkie (10 min)',
        "lsnRoute_full": 'pełne przejście',
        "lsnRoute_league": 'następna liga',
        "lsnRouteRoot": 'To przejście',
        "lsnAll": 'Cała biblioteka',
        "lsnAt": 'na {timecode}',
        "lsnCueTip": 'Gdzie to słychać: {cue}',
        "lsnRouteTip": 'Jeśli wyszło ✗: {route}',
        "lsnText": 'Co usłyszałeś, własnymi słowami…',
        "lsnTicked": 'Zaznaczone ({n}):',
        "lsnTickedEmpty": 'Nic jeszcze nie zaznaczono — kliknij frazę po prawej, a trafi tutaj i do tekstu.',
        "lsnRemoveTip": 'Zdejmij to z zapisu. Wiersz, który napisała, zostaje w tekście — przepisz go sam, jeśli już '
                        'nie pasuje.',
        "lsnSave": 'Zapisz',
        "lsnSaved": 'Zapisano werdyktów: {n}, wobec {version}.',
        "lsnRefused": 'Nie zapisano: {why}',
        "lsnNoPairs": 'Nie ma jeszcze czego zapisać: zaznacz choć jedną frazę. Twoje słowa zapisują się RAZEM z '
                      'zaznaczeniami, a nie zamiast nich.',
        "lsnSheet": 'Cała ściąga',
        "lsnSheetTitle": 'Odsłuch — ściąga',
        "lsnUnavailable": 'Nie udało się odczytać słownika odsłuchu metody: {why}',
        "lsnProblems": 'Własna kontrola metody mówi: {problems}',
        "lsnNotTranslated": 'jeszcze nieprzetłumaczone — pokazano po angielsku',
        "lsnVersion": 'stan {version}',
        "lsnNoVersion": 'nie ma jeszcze zrzutu ledgera — werdykt zapisze się bez niego i nie da się go potem '
                        'przypisać do stanu',
        "lsnOwnHint": 'Dla utworu, którego tu nie ma, weź „own” — a który to był utwór, powiedz własnymi słowami.',
    },
    "de": {
        # German
        "theme": 'Thema',
        "dspPanel": 'DSP',
        "projectParams": 'Projektparameter',
        "chanSum_channels": 'Kanäle',
        "chanSum_virtual_channels": 'Virtuelle',
        "chanSum_physical_outputs": 'Ausgänge',
        "chanSum_inputs": 'Eingänge',
        "chanSumOff": '{total} ({off} aus)',
        "chanSumAllOn": '{total} (alle an)',
        "cfgLanguage": 'Sprache',
        "cfgGenerator": 'KI-Generator',
        "cfgEffort": 'Aufwand',
        "cfgCritic": 'KI-Prüfer',
        "cfgTheme": 'Thema',
        "cfgGate": 'Berechtigungen',
        "cfgThemeLight": 'hell',
        "cfgThemeDark": 'dunkel',
        "systemParams": 'Systemparameter',
        "audioAnalysis": 'Car-Audio-Analyse',
        "leftNoProfile": 'Noch kein DSP bekannt. Starte eine Sitzung und nenne den Prozessor dieses Autos — das Profil '
                         'wird geschrieben, sobald er benannt ist, und dieses Panel füllt sich.',
        "leftNoLedger": 'Noch keine Einstellungen erfasst. Der Baum füllt sich, sobald der erste Ledger-Schnappschuss '
                        'geschrieben wird, während des Einmessens.',
        "planEmpty": 'Noch kein Plan. Der Skill schreibt ihn, wenn eine Sitzung eine Phase betritt; dieses Panel '
                     'füllt sich, während Schritte hinzukommen und geschlossen werden.',
        "planNoProject": 'Kein Projekt geöffnet.',
        "noDataYet": 'Noch keine Daten',
        "openQuestions": 'Offen',
        "openQuestionsTitle": 'Offene Fragen',
        "curveRoundEmpty": '{round}: REW hat die Messungen dieser Runde nicht — es ist ein anderes Projekt geöffnet, '
                           'oder sie wurden gelöscht.',
        "seriesItem": 'Serie {v}',
        "logError": 'Etwas ist schiefgelaufen: {error} — Details in {path}',
        "rewPort": 'REW-Port',
        "rewOnlineTip": 'REW: online',
        "rewOfflineTip": 'REW: auf diesem Port nicht erreichbar.\nDie API gibt es nur in den BETA-Builds von REW — die '
                         'Release-Version hat gar keinen API-Reiter (roomeqwizard.com/beta.html).',
        "createProject": '+ Neues Projekt anlegen',
        "refreshProjectTip": 'Projekt neu von der Platte lesen (Profil, Ledger)',
        "selfSection": 'TCCs eigene Einstellungen',
        "selfAliasTitle": '{n} Modell-Alias(e) aktiv',
        "selfAliasDetail": '',
        "selfAliasNoneTitle": 'Keine Modell-Aliase in TCCs eigener Schicht',
        "selfAliasNoneDetail": 'Das ist nicht dasselbe wie „die Auswahl startet, was sie anzeigt“: das Prüfer-Skript ersetzt '
                               'ebenfalls, eine Schicht tiefer — es fällt von der API auf ein lokales CLI zurück, und dieses '
                               'CLI startet das Modell, auf das es eingestellt ist. Die Zeile darunter vergleicht, wer '
                               'tatsächlich geantwortet hat.',
        "selfReviewerNeverTitle": 'Der Prüfer wurde in diesem Projekt noch nicht aufgerufen',
        "selfReviewerNeverDetail": 'Solange er nicht einmal geantwortet hat, gibt es nichts zu vergleichen. Ein eingestelltes '
                                   'Modell ist eine Behauptung; ein Aufruf ist ein Beleg.',
        "selfReviewerOkTitle": 'Die letzte Prüfung kam von {model}, also von dem angeforderten Modell',
        "selfReviewerDiffTitle": 'Geantwortet hat nicht der ausgewählte Prüfer',
        "selfReviewerDiffDetail": 'Angefordert war {wanted}; geantwortet hat {answered}. Weder die Auswahl noch `substituted` '
                                  'zeigt das — das Prüfer-Skript fällt von der Gemini-API auf das lokale CLI zurück (ein 404 '
                                  'genügt), und das CLI startet das Modell, auf das es gerade eingestellt ist. Prüfe, was in '
                                  '`agy` ausgewählt ist, oder akzeptiere diesen Prüfer.',
        "selfAliasCrossVendor": '{keys} startet jetzt ein Modell eines ANDEREN Anbieters als angefordert. Wenn das der Prüfer '
                                'ist, hat die anbieterübergreifende Prüfung aufgehört — der Sinn eines zweiten Anbieters ist '
                                'gerade, dass er die blinden Flecken des Generators nicht teilt.',
        "selfAliasSameModel": '{keys} — dasselbe Modell, nur mit dem Präfix dessen genannt, was es startet. Nichts wird '
                              'ersetzt: damit wird ein ohne Präfix geschriebener Name repariert, und den Alias zu entfernen '
                              'ist sicher, solange kein älterer Eintrag noch auf den kurzen Namen verweist.',
        "selfAliasFix": 'Alle Aliase entfernen',
        "selfAliasFixed": '{n} Alias(e) entfernt. Die Auswahlen starten wieder, was sie anzeigen.',
        "selfCatalogueTitle": 'Installiert, aber stumm: {clis}',
        "selfCatalogueDetail": 'Dieses CLI liegt im PATH und seine Modellliste kam leer zurück, also fehlt seine Route in '
                               'den Auswahlen — was sich genau wie „nicht installiert“ liest, und so kommt ein gespeichertes '
                               'Modell dazu, verschwunden zu wirken.',
        "selfCatalogueFix": 'Die CLIs erneut fragen',
        "selfCatalogueFixed": 'Katalog aktualisiert: {n} Modell(e).',
        "selfCatalogueOkTitle": 'Jedes installierte CLI hat mit seinen Modellen geantwortet',
        "selfRecommendOkTitle": 'Das empfohlene Paar ist hier verfügbar',
        "selfRecommendTitle": 'Nichts im Angebot entspricht der Empfehlung {roles}',
        "selfRecommendDetail": 'Die Empfehlung ist eine Klasse, kein Modellname — {pairs}, Stand {since} —, deshalb wird '
                               'eine neue Version von beiden automatisch markiert. Passt nichts, dann ist die Klasse selbst '
                               'ausgelaufen oder ihre Route ist nicht installiert. Wähle bewusst; es gibt keine Empfehlung, '
                               'auf die man zurückfallen kann.',
        "selfCheckFailed": 'Diese Prüfung konnte nicht laufen',
        "diagFixDone": 'Behoben: {what}',
        "diagTitle": 'Projektdiagnose',
        "diagBtnTip": 'Was TCC auf der Platte gefunden hat: die Maschinendateien des Skills, geprüft',
        "diagChecking": 'Prüfe…',
        "diagOk": 'OK — nichts zu beheben',
        "diagIssues": '{n} Problem(e) gefunden',
        "diagNoIssues": 'Keine Probleme',
        "diagAsk": 'Die Sitzung bitten',
        "diagAskText": 'Die Diagnose meldet ein Problem in {subject}, in den Worten der Prüfung selbst:\n\n    {issue}\n\n'
                       'Behebe es mit den eigenen Befehlen des Skills (TCC schreibt diese Dateien nicht). Sag '
                       'danach, welchen Befehl du ausgeführt hast — ich lasse `contract.py check` erneut laufen, und '
                       'wir sehen, ob die Zeile weg ist.',
        "diagAskedAgo": 'vor {ago} gebeten, immer noch da',
        "diagAgoNow": 'gerade eben',
        "diagAgoMin": 'vor {n} Min.',
        "diagFiles": 'Maschinendateien',
        "diagCross": 'Dateiübergreifende Prüfungen',
        "diagOpenQ": 'Offene Fragen (Intake unvollständig)',
        "diagMissing": 'fehlt',
        "diagUnavailable": 'Vertragsprüfung nicht verfügbar',
        "diagCheckedAt": 'geprüft {at} · {ms} ms',
        "diagTabProject": 'Projekt',
        "diagTabInstall": 'Installation',
        "diagTabLog": 'Protokoll',
        "diagReport": 'Problem melden',
        "titleUpdate": 'Update verfügbar',
        "updWhy_source_checkout": 'läuft aus einem Quell-Checkout — aktualisiere ihn mit git',
        "updWhy_no_network": 'GitHub war nicht erreichbar',
        "updWhy_not_found": 'auf dieser Maschine nicht gefunden',
        "updWhy_not_a_checkout": 'kein git-Checkout, also gibt es nichts an Ort und Stelle zu aktualisieren',
        "updWhy_on_branch": 'auf einem Branch — jemandes Arbeitsverzeichnis, kein installiertes Release',
        "updWhy_submodule": 'ein Submodul eines Checkouts — aktualisiere es mit git, in',
        "updWhy_dirty": 'hat uncommittete Änderungen und bleibt deshalb unangetastet',
        "updWhy_no_manifest": 'keine Version im Manifest',
        "updWhy_git_failed": 'git sagte',
        "updTcc": 'TCC aktualisieren',
        "updSkill": 'Methode aktualisieren',
        "updTccName": 'TCC',
        "updSkillName": 'Die Methode',
        "updChecking": 'suche nach Updates…',
        "updAvailable": '{what} {here} — eine neuere ist da: {there}',
        "updNewerBuild": '{what} {here} — ein neuerer Build derselben Version ist da',
        "updNewerBuildOn": '{what} {here} — ein neuerer Build ist da, vom {date}',
        "updCurrent": '{what} {here} — aktuell',
        "updUnknown": 'GitHub ließ sich nicht fragen — kein Netz, oder er hat seinen Tag',
        "updWorking": 'aktualisiere…',
        "updSkillDone": 'Die Methode ist jetzt {version} — öffne die KI-Sitzung neu, damit sie sie übernimmt',
        "updTccHanded": 'Ein Terminal ist offen und wartet darauf, dass TCC sich schließt. Beende TCC — das Update '
                        'läuft von selbst, danach starte TCC wieder.',
        "updFailed": 'hat nicht geklappt: {why}',
        "diagLogNone": 'keine Protokolldatei — dieser Lauf schreibt nur ins Terminal',
        "diagInstallBlurb": 'Was auf dieser Maschine installiert ist — Versionen, woher jedes Teil kam, welche CLIs '
                            'antworten. Kopiere es in eine Nachricht, wenn du etwas meldest: es beantwortet die ersten '
                            'fünf Fragen, die jeder stellen würde.',
        "diagInstallReading": 'lese…',
        "diagInstallCopy": 'Kopieren',
        "diagInstallCopied": 'Kopiert',
        "diagRefresh": 'Erneut prüfen',
        "diagClose": 'Schließen',
        "diagStripIssues": 'Projektvertrag: {n} Problem(e) — siehe Diagnose (⚕)',
        "diagStripError": 'Vertragsprüfung nicht verfügbar: {error}',
        "projectRenderFailed": 'Das Projekt ließ sich nicht von der Platte zeichnen — auf dem Bildschirm steht noch die '
                               'letzte funktionierende Ansicht. {error}',
        "staleStrip": '{what} — {n} Kanal/Kanäle müssen neu gemessen werden: {codes}',
        "missingRecord": 'Nicht festgehalten: {what} — {why}.',
        "criticSaved": 'Text gespeichert in {path}',
        "acousticsNone": 'Noch keine Fehlerkarte. Phase 0 misst, was dieser Innenraum mit dem Klang macht, und die '
                         'Zeilen landen hier — jede mit dem, was man dagegen tun darf und was nicht.',
        "flawHypothesis": 'nicht bestätigt',
        "flawEvidenceHead": 'Abgelesen aus:',
        "flawNoWhy": 'Zu diesem Eintrag wurde kein Grund festgehalten — nur die Messung selbst.',
        "flawAllChannels": 'alle Kanäle',
        "flawAction_notch": 'schneiden',
        "flawAction_leave": 'belassen',
        "flawAction_no_boost": 'nie anheben',
        "flawAction_geometry": 'Geometrie',
        "flawAction_delay": 'Delay',
        "flawAction_crossover": 'Frequenzweiche',
        "flawKind_room_gain": 'Room Gain',
        "flawKind_modal_peak": 'Kabinenmode',
        "flawKind_cabin_null": 'Kabinen-Auslöschung',
        "flawKind_sbir": 'SBIR',
        "flawKind_floor_bounce": 'Bodenreflexion',
        "flawKind_driver_resonance": 'Chassis-Resonanz',
        "flawKind_non_min_phase": 'nicht-minimalphasig',
        "flawKind_thd_spike": 'Klirr-Spitze',
        "flawKind_pair_suckout": 'Auslöschung im Paar',
        "supervisorUnbacked": 'Diese Schritte sind geschlossen, und ihre Belege nennen nichts, was auf der Platte oder in '
                              'REW existiert:<br>{steps}<br>Entweder ist die Arbeit irgendwo festgehalten, wohin ich nicht '
                              'sehe, oder sie wurde nicht getan.',
        "recordTargetCurve": 'die Zielkurve',
        "recordTargetCurveWhy": 'Phase 0 wählt sie, und jede spätere Phase wird gegen sie gemessen, aber auf der Platte steht '
                                'nirgends, welche Kurve genommen wurde',
        "measNoTask": 'Noch keine Messaufgabe. Sie ergibt sich aus der Phase, dem Namensglossar und der aktuellen '
                      'Ledger-Version — sie erscheint also, sobald der Intake die Kanalnamen festgelegt hat.',
        "measPhaseNoCapture": 'Diese Phase misst nicht — sie arbeitet mit der bereits erfassten Serie. Die nächste '
                              'Messaufgabe erscheint mit der Phase, die eine braucht.',
        "noProjectMeas": 'Kein Projekt — noch nichts zu messen.',
        "npTitle": 'Neues Projekt',
        "npFolder": 'Projektordner',
        "npBrowse": 'Durchsuchen…',
        "npProfile": 'DSP-Profil',
        "npAddNew": '+ Neu hinzufügen (nicht in der Liste)',
        "npVendor": 'DSP-Hersteller',
        "npVendorPlaceholder": 'z. B. Helix, Musway',
        "npModel": 'DSP-Modell',
        "npModelPlaceholder": 'z. B. DSP Ultra S, M6V4',
        "npRunVia": 'Onboarding durchführen über',
        "npRunInApp": 'In der App (Claude)',
        "npAiModel": 'KI-Modell',
        "npTerminalModel": 'Modell (optional)',
        "npTerminalModelPlaceholder": 'z. B. opus, gemini-2.5-pro — leer = Standard des CLI',
        "npOnboardingHint": 'Nutze den Skill autosound-tuning für das Onboarding des DSP-Profils. Verbinde dich mit dem '
                            "'tcc'-MCP-Server dieses Projekts (siehe .mcp.json) und rufe zuerst dessen Werkzeug "
                            'check_existing_profile auf, für vendor={vendor} model={model}. Führe das Interview '
                            '{language}.',
        "langNameEn": 'auf Englisch',
        "langNameUk": 'auf Ukrainisch',
        "langNamePl": 'auf Polnisch',
        "langNameDe": 'auf Deutsch',
        "npSeed": 'Systemparameter',
        "npSeedNone": 'Im Interview fragen (von Grund auf)',
        "npSeedFrom": 'Aus einem bestehenden Projekt kopieren…',
        "npSeedPlaceholder": 'Ordner eines Projekts mit einer project.json',
        "npSeedFindings": '…und was dort gemessen wurde (akustische Fehler, offene Fragen)',
        "npSeedNotAProject": 'Hier gibt es keine lesbare project.json — nichts zu kopieren.',
        "npSeedSummary": '{car} · {dsp} · {channels} Kanäle',
        "npSeedNote": '**Geerbt von `{source}` ({when}).** Das Systemprofil wurde aus jenem Projekt kopiert, nicht '
                      'hier geschrieben — gleiche es mit diesem Aufbau ab, bevor du dich darauf verlässt.',
        "npSeedFailed": 'Es wurde nichts kopiert: {problem}',
        "npSeedDone": 'Systemparameter aus „{source}“ kopiert: {files}. Sie sind geerbt, nicht hier gemessen — '
                      'gleiche sie mit diesem Aufbau ab.',
        "npSeedHint": 'Die Systemparameter wurden aus dem Projekt „{source}“ in diesen Ordner kopiert: lies ZUERST '
                      'project.json und dsp_profile.json und geh sie mit der Person durch, wobei du korrigierst, '
                      'was abweicht. Bitte nicht darum, das Auto von Grund auf zu beschreiben.',
        "riTitle": 'Import aus einem Resonalyze-Projekt',
        "riFilePlaceholder": 'Eine Resonalyze-Sitzung des virtuellen DSP (.json)',
        "riAgainst": 'Geprüft gegen',
        "riNoProfile": 'In diesem Projekt gibt es keine dsp_profile.json — es wurde gegen keinen realen Prozessor '
                       'geprüft. Jeder Wert unten wird berichtet, keiner ist verifiziert.',
        "riScene": 'Stereobühne',
        "riSceneNote": 'Worauf Resonalyzes Auto balance zielt. Es steckt bereits in den Pegeln und Delays der '
                       'einzelnen Kanäle unten — gib es kein zweites Mal ein.',
        "riUnbound": 'kein Kanal dieses Projekts passt',
        "riDormant": 'in der Datei, aber NICHT aktiv (die Art der Weiche entscheidet)',
        "riDropped": 'verworfen: transparent, trägt nichts bei',
        "riNotChecked": 'Nicht geprüft, weil dieses DSP-Profil die Grenze nicht nennt',
        "riBindNone": '— nicht zuordnen —',
        "riBlocked": 'Dieser Prozessor kann den Plan so nicht bekommen: {refused} Wert(e) abgelehnt, {unbound} '
                     'Kanal/Kanäle nicht zugeordnet. Es wird nichts passend gerundet und nichts geschrieben.',
        "riClear": 'Keine angegebene Grenze dieses DSP lehnt einen der {legs} Kanäle ab. Das ist die Antwort für '
                   'die HARDWARE — ein PC-Tool-Modus (Fine EQ) kann enger sein, und umgeschaltet wird er am '
                   'Bildschirm. Um es ins Projekt zu holen, drücke „Zum Eintragen senden“: die Zeilen und die '
                   'Bitte landen im Eingabefeld des KI-Dialogs, wo du sie liest und absendest. Das Gate prüft '
                   'sie, schreibt den Schnappschuss und erzeugt das Einstellungsblatt, das du im PC-Tool von '
                   'Hand einträgst.',
        "riCopyRows": 'Zeilen kopieren (JSON)',
        "riCopied": 'Die Zeilen liegen in der Zwischenablage.',
        "riFailed": 'Diese Datei konnte nicht gelesen werden:',
        "riClose": 'Schließen',
        "riImport": 'Aus einem Resonalyze-Projekt importieren…',
        "npSeedNoInterview": 'Seine dsp_profile.json kommt mit, also entfällt das Fähigkeiten-Interview — zu einem bereits '
                             'beschriebenen Prozessor bleibt nichts zu fragen. Wähle oben ein anderes DSP, dann läuft es '
                             'wie gewohnt.',
        "npSeedNoSkill": 'Der Skill autosound-tuning ist hier nicht verfügbar, und das Kopieren steckt in ihm — '
                         'installiere den Skill, oder fülle das neue Projekt von Hand aus.',
        "npSeedOpen": 'Im geerbten DSP-Profil stehen noch {open} Fakt(en), die niemand bestätigt hat.',
        "groupFieldsUnknown": 'Regler noch nicht aufgezählt',
        "menuProject": 'Projekt',
        "menuSession": 'Sitzung und Modelle',
        "menuView": 'Darstellung',
        "menuTools": 'Werkzeuge',
        "menuHelp": 'Hilfe und Support',
        "menuLanguage": 'Sprache',
        "menuReload": 'Dieses Projekt neu von der Platte lesen',
        "menuZoomIn": 'Größerer Text',
        "menuZoomOut": 'Kleinerer Text',
        "menuDiagnostics": 'Diagnose und Updates…',
        "menuTargetTool": 'Zielkurven-Werkzeug (öffnet den Browser)',
        "riImportTip": 'Holt die EINSTELLUNGEN aus einer Resonalyze-Sitzung des virtuellen DSP — pro Kanal: Weichen, '
                       'Delay, Pegel, Polarität und die EQ-Bänder — und prüft jeden Wert gegen das, was dein '
                       'Prozessor tatsächlich annehmen kann. Nicht die Sitzung selbst, und es wird nichts '
                       'geschrieben: es lehnt ab statt zu runden und gibt dir die Zeilen, um sie durchs Einmess-Gate '
                       'einzutragen.',
        "menuStartSession": 'Eine Einmess-Sitzung in TCC starten',
        "menuTerminal": 'Ein Terminal in diesem Projekt öffnen',
        "menuModels": 'Modelle einrichten (OMP)…',
        "menuTheme": 'Thema wechseln (hell / dunkel)',
        "menuCopyCar": 'Das Auto kopieren…',
        "menuCopyCarTip": 'Ein Projekt aus einem bestehenden beginnen: das Auto, die Anlage und der Einbau — Marke, '
                          'Chassis pro Kanal, Endstufen, Mikrofon, das DSP und sein Profil, das Namensglossar. Was im '
                          'anderen Projekt GEMESSEN wurde, bleibt dort, solange du es nicht anforderst. Du korrigierst, '
                          'was abweicht, statt dein Auto erneut zu beschreiben.',
        "menuModelsTip": 'Welche Modelle dieses Projekt verwenden darf — den Generator, den Kritiker und wie '
                         'angestrengt sie denken sollen. Alles außer Claude läuft über OMP, also ist das hier '
                         'Markierte das, wonach OMP greifen darf.',
        "menuButton": '☰ Menü',
        "riUnchecked": 'Es wurde nichts geprüft. Dieses Projekt sagt nicht, welchen Prozessor es hat, also werden '
                       'alle {legs} Kanäle berichtet und keiner ist verifiziert — richte zuerst das Auto ein (Menü ▸ '
                       'Projekt), oder öffne dies in einem Projekt mit einer dsp_profile.json.',
        "riUnboundVerdict": '{unbound} der {legs} Kanäle der Datei passen zu keinem Kanal dieses Projekts. Ihre Werte '
                            'sind in Ordnung; eine Zeile ohne Kanal lässt sich unter keinem Namen eintragen. Ordne sie '
                            'unten zu, oder richte zuerst die Kanäle des Autos ein.',
        "riNoChannels": 'Dieses Projekt hat noch keine Kanäle — es gibt nichts, dem man dies zuordnen könnte. Richte '
                        'zuerst das Auto ein: Menü ▸ Projekt ▸ Neues Projekt / Das Auto kopieren.',
        "npCopy": 'Kopieren',
        "npSeedTargetTaken": 'Im Ordner „{folder}“ liegt bereits ein Projekt. Kopieren schreibt nie über Fakten, die '
                             'jemand bestätigt hat — wähle einen leeren oder einen neuen Ordner.',
        "leftRigOnly": 'So beschreibt das Projekt die Anlage — jeder Kanal in seiner Ebene, noch ohne Werte. Die '
                       'Werte kommen mit dem ersten Ledger-Schnappschuss, während des Einmessens.',
        "riProjectLink": 'Resonalyze von DIMOSUS — github.com/DIMOSUS/Resonalyze',
        "riSendRows": 'Zum Eintragen senden',
        "riSendFirst": 'Import aus einem Resonalyze-Projekt — {file}. Gegen das DSP-Profil dieses Projekts geprüft: '
                       '{ok} Werte eintragbar, keiner abgelehnt, {unknown} nicht überprüfbar. Dieses Projekt hat '
                       'noch kein Ledger, trage es also als ERSTEN Schnappschuss des Presets {preset} ein, durchs '
                       'Gate. Es folgen die Zeilen, nach Kanal:',
        "riSendPropose": 'Import aus einem Resonalyze-Projekt — {file}. Gegen das DSP-Profil dieses Projekts geprüft: '
                         '{ok} Werte eintragbar, keiner abgelehnt, {unknown} nicht überprüfbar. Schlage es als '
                         'Änderung am Preset {preset} durchs Gate vor und zeig mir das Einstellungsblatt. Es folgen '
                         'die Zeilen, nach Kanal:',
        "riPair": 'Paar {pair} {side}',
        "riSideLeft": 'links',
        "riSideRight": 'rechts',
        "tabGain": 'Pegel',
        "tabDelay": 'Delays',
        "tabPhase": 'Phasen',
        "paramAllChannels": '{param} · alle Kanäle',
        "copyEqBank": 'EQ kopieren',
        "copyEqDone": '{channel}: der EQ-Satz liegt in der Zwischenablage, im Format {format}.',
        "copyEqLeftOut": 'Nicht übernommen, weil dieses Format es nicht tragen kann: {what}.',
        "copyEqNoFormat": 'Für diesen Prozessor gibt es noch kein EQ-Format — es wurde nichts kopiert, statt etwas, das '
                          'niemand einfügen könnte.',
        "quitSavingElapsed": 'Speichere vor dem Beenden — bisher {sec} s (bis zu {max} Min.). Das Fenster schließt sich '
                             'von selbst, sobald das Modell das Projekt festgehalten hat.',
        "quitAbandonTitle": 'Das Speichern läuft noch',
        "quitAbandonBody": 'Das Modell hält das Projekt seit {sec} s fest. Schließt du jetzt, ist alles verloren, was es '
                           'noch nicht geschrieben hat — das Gespräch geht mit dem Fenster.',
        "quitAbandonClose": 'Ohne Speichern schließen',
        "quitAbandonWait": 'Weiter warten',
        "copyEqCount": '{written} von {size} Bändern — der Rest wird leer geschrieben und überschreibt, was in '
                       'diesen Plätzen steht.',
        "copyEqWritten": '{written} Band/Bänder.',
        "copyEqCrossovers": 'Weichenzweige enthalten: {n}.',
        "copiedValue": 'Kopiert: {value}',
        "criticClipboardOnly": 'nur Zwischenablage',
        "criticClipboardOnlyTip": '{model} ist ein Modell von {vendor}, und diese Maschine hat weder dessen API-Schlüssel noch '
                                  'dessen CLI. `call_critic` funktioniert weiterhin — es gibt dir das Paket zur Prüfung von '
                                  'Hand —, aber es wird nichts aufgerufen.',
        "criticUnknownVendorTip": 'Das Prüfer-Skript ruft Modelle von Google, Anthropic oder OpenAI auf; {model} ist keines '
                                  'davon, also kann kein Transport hier es starten. Es gibt dir stattdessen ein Paket zur '
                                  'Prüfung von Hand.',
        "protTitle": 'Schutzfilter dieser Messrunde',
        "protRound": 'Runde {series}. Was im Signalweg war, während diese Sweeps aufgenommen wurden.',
        "protNoRound": 'Es ist keine Messrunde offen, also gibt es nichts, wozu man etwas festhalten könnte. Öffne '
                       'zuerst eine Runde — ein Schutz-Eintrag gehört zu dem Durchgang, in dem gemessen wurde.',
        "protWhy": 'Ein Schutzfilter steckt IN der Aufnahme: er dreht die Phase weit über seine eigene '
                   'Eckfrequenz hinaus, und eine Übernahme dreimal weiter oben kann rund fünfzig Grad tragen, '
                   'die zum Messaufbau gehören und nicht zum Auto. Hier festgehalten, lässt er sich wieder aus '
                   'der Kurve herausrechnen. „Ohne alles gemessen“ ist eine Antwort, die festzuhalten sich '
                   'lohnt; einen Kanal gar nicht einzutragen ist nicht dasselbe, und für ihn wird nichts '
                   'korrigiert.',
        "protUnset": 'nicht erfasst',
        "protOff": 'kein Schutz',
        "protFilter": 'Filter:',
        "protHp": 'HP Hz',
        "protLp": 'LP Hz',
        "protSave": 'Eintragen',
        "protRefused": '{channel}: {why}',
        "protBtn": 'Schutz',
        "protBtnTip": 'Was im Signalweg war, während diese Runde gemessen wurde — pro Kanal. Festgehalten, lässt es '
                      'sich wieder aus den Kurven herausrechnen; nicht festgehalten, wird nichts korrigiert, denn '
                      'eine Korrektur über einen unbekannten Signalweg erzeugt Daten, die nur korrigiert aussehen.',
        "protNoChannels": 'Dieses Projekt hat noch keine Kanäle, also gibt es nichts, wozu man einen Schutzfilter '
                          'eintragen könnte.',
        "protWritten": 'Festgehalten, was im Signalweg lag für: {channels}. Ihre Kurven lassen sich mit '
                       'herausgerechnetem Schutz lesen.',
        "npCreate": 'Anlegen',
        "npCancel": 'Abbrechen',
        "projectNewTip": 'Ordner + DSP + wer das Onboarding führt. Es kann auch VON EINEM BESTEHENDEN PROJEKT '
                         'AUSGEHEN: das Auto, die Chassis, das Glossar und das DSP-Profil kommen mit, und du '
                         'korrigierst, statt dein Auto erneut zu beschreiben.',
        "projectOpenTip": 'Zeig TCC einen anderen Ordner. Ein leerer geht auch: er wird ein neues Projekt, und das '
                          'Aufnahmegespräch füllt es. TCC öffnet sich danach neu auf dem gewählten Ordner — das Fenster '
                          'ist von Anfang an an ein Projekt gebunden.',
        "projectSaveStateTip": 'Bittet das Modell, den Plan, die Belege und alles Gelernte in die Projektdateien zu '
                               'schreiben. Das Gespräch geht weiter.',
        "projectFreshSessionTip": 'Speichert zuerst und beginnt dann mit leerem Kontext auf DEMSELBEN Modell neu. Nicht '
                                  'dasselbe wie ein Neustart auf einem anderen: das ist für ein Gespräch, das lang und teuer '
                                  'geworden ist, während seine Schlüsse schon auf der Platte stehen.',
        "gateTitle": 'Ein Einmess-Projekt öffnen',
        "gateBlurb": 'TCC arbeitet an einem Projektordner und bindet sich beim Start an ihn. Wähle einen '
                     'bestehenden, oder tippe einen neuen Pfad — ein leerer Ordner ist ein gültiges neues Projekt, '
                     'das Aufnahmegespräch füllt es.',
        "gateFolder": 'Projektordner',
        "gateFolderPlaceholder": '/pfad/zum/auto',
        "gateBrowse": 'Durchsuchen…',
        "gateOpen": 'Öffnen',
        "gateNote": 'Beide Modelle werden mit diesem Projekt gemerkt, nicht global — ein anderes Projekt behält '
                    'seine eigenen. Ändern kannst du sie später in der Fußleiste.',
        "projectSwitchTitle": 'Projekt wechseln',
        "projectSwitchBody": 'TCC bindet beim Start einen Ordner, also startet es auf „{name}“ neu. Alles, was die '
                             'laufende Sitzung nicht auf die Platte geschrieben hat, geht verloren — speichere zuerst, '
                             'wenn das zählt.',
        "projectNone": '⌂ Projekt wählen…',
        "projectOpen": 'Projektordner öffnen…',
        "projectNew": 'Neues Projekt…',
        "projectSaveState": 'Auf die Platte schreiben, was das Modell weiß',
        "projectFreshSession": 'Neue Sitzung beginnen (speichert, dann Kontext leeren)',
        "projectReopen": 'Ordner gewechselt — öffne TCC neu, um damit zu arbeiten.',
        "sessionSaved": 'Projektzustand auf die Platte geschrieben. Die Sitzung läuft weiter.',
        "savedTccOnly": 'TCCs eigene Einstellungen liegen auf der Platte. Es läuft keine Sitzung, also gibt es '
                        'nichts, worum man das Modell bitten könnte.',
        "sessionFresh": 'Sitzung beendet und Zustand gespeichert — beginne eine neue mit leerem Kontext.',
        "generator": 'Generator',
        "preset": 'Preset',
        "target": 'Zielkurve',
        "targetToolTip": 'Im Zielkurven-Werkzeug öffnen ↗',
        "params": 'PARAMETER',
        "virtual": 'VIRTUELL',
        "output": 'AUSGÄNGE',
        "inputs": 'EINGÄNGE',
        "paramsRow": 'params · alle Parameter als Tabelle',
        "tabTable": 'Tabelle',
        "close": 'schließen ✕',
        "outTitle": 'OUTPUT — physische Chassis',
        "virtTitle": 'VIRTUAL — Eingangs-Voicing',
        "colChan": 'Kanal',
        "eqHint": 'Nur die <b>benutzten</b> Bänder, mit allen Parametern des jeweiligen Bandes auf einmal. Ein '
                  'Allpass (APF) ist hier ein Band-TYP, keine eigene Spalte. Bypass wird angezeigt, lässt sich '
                  'aus diesem Fenster aber noch nicht ändern. Die ungenutzten Bänder des Satzes sind '
                  'ausgeblendet.',
        "shared": 'gemeinsame Frequenzen:',
        "noShared": 'keine gemeinsamen Frequenzen',
        "band": 'Band',
        "legWait": 'warte',
        "legDone": 'fertig',
        "legBad": 'aufgenommen, unbrauchbar',
        "legSkip": 'übersprungen',
        "stepTagOkTip": 'Geschlossen, und der Beleg liegt wirklich auf der Platte — die genannte Datei oder Messung '
                        'wurde gefunden.',
        "stepTagUnprovenTip": 'Vom Skill geschlossen, aber der genannte Beleg löst sich auf der Platte zu nichts auf: keine '
                              'solche Datei, und keine Messung dieses Namens.\n\nDas ist nicht dasselbe wie ein nicht '
                              'abgehakter Schritt. Ein solcher wurde nie fertig; dieser wurde als fertig gemeldet und hat '
                              'nichts hinter sich.',
        "stepTagWaitTip": 'Entweder noch in Arbeit, oder geschlossen und seither ungültig — eine Konfigurationsänderung '
                          'bedeutet, dass dem Ergebnis nicht mehr zu trauen ist, es muss also neu aufgenommen werden.',
        "chanOn": 'AN',
        "chanOff": 'AUS',
        "chanTurnOn": 'EINSCHALTEN',
        "chanTurnOff": 'AUSSCHALTEN',
        "chanToggleQueued": 'Es wurde gebeten, {channel} → {state} zu schalten. Es läuft keine Sitzung, also wartet es in '
                            'der Schlange: das Modell bekommt es im ersten Zug der nächsten Sitzung.',
        "signalNudge": 'TCC hat einen Zug für {count} Anfrage(n) begonnen, die du in der Oberfläche gestellt hast — '
                       'es sprach niemand, und ein Klick sollte darauf nicht warten müssen.',
        "signalNudgePrompt": 'Der Arbiter hat die Oberfläche benutzt. Bearbeite zuerst die oben aufgeführten Signale, '
                             'bestätige jedes mit ack_signals und sag dann kurz, was du getan hast.',
        "chanToggleWaiting": 'gefragt · {secs}s',
        "chanToggleLate": '⚠ keine Antwort · {secs}s',
        "chanToggleWaitTip": 'TCC hat das Modell gebeten, dies festzuhalten; das Ledger zu schreiben ist Sache des Skills. '
                             'Die Zeile ändert sich, wenn das Modell antwortet. Erneut zu fragen, solange das steht, '
                             'frischt nur die Wartezeit auf und sendet keine zweite Anfrage.',
        "chanToggleAlreadyAsked": '{channel} — bereits gefragt, warte auf das Modell. Nicht zweimal gesendet.',
        "chanToggleTip": 'Bitte das Modell, diesen Kanal ein- oder auszuschalten. TCC schreibt das Ledger nicht — die '
                         'Anfrage geht an die Sitzung, die die Änderung festhält.',
        "chanToggleSent": 'Es wurde gebeten, <b>{channel}</b> {state} zu schalten. Das Modell hält es im Ledger fest; '
                          'der Baum folgt, sobald es geschrieben ist.',
        "noSessionForSignal": 'Es läuft keine Sitzung — starte eine, und die Anfrage erreicht sie.',
        "chanToggleConfirmTitle": 'Diesen Kanal schalten?',
        "chanToggleConfirmOff": '<b>{channel}</b> ausschalten?\n\nSein EQ, seine Weiche und sein Delay leben im Ledger und '
                                'überstehen das Ausschalten womöglich nicht. TCC kann das nicht rückgängig machen — die '
                                'Änderung hält das Modell fest.',
        "chanToggleConfirmOn": '<b>{channel}</b> einschalten?\n\nDas ist eine strukturelle Änderung: der Kanal braucht seinen '
                               'Platz im Glossar, und ein physischer Ausgang braucht sein virtuelles Gegenstück. Das Modell '
                               'klärt das und hält es fest.',
        "pillMute": 'MUTE',
        "pillOff": 'OFF',
        "attempt": 'Versuch',
        "addStep": '+ Schritt hinzufügen',
        "addStepPrompt": 'Situativer Schritt (nur dieses Projekt):',
        "measRead": 'Lesen',
        "measReading": 'Lese aus REW…',
        "measReadOk": '{n} Messung(en) aus REW gelesen · {matched} zugeordnet, {extra} zusätzlich',
        "measReadFail": 'Konnte nicht aus REW lesen: {error}',
        "measReadNoMeas": 'In REW wurden keine Messungen gefunden.',
        "measUsedInStep": 'Verwendet in Schritt {steps}',
        "assignNames": 'Namen vergeben',
        "captureOrderTitle": 'Messreihenfolge',
        "captureOrderHint": 'Wähle die Messmethode und zieh dann die Zeilen so, dass die Reihenfolge der entspricht, in '
                            'der du die Kanäle in REW wirklich aufnimmst. Pro Methode gespeichert und beim nächsten Mal '
                            'wiederverwendet.',
        "captureMethodSw": 'SW',
        "captureMethodRta": 'RTA',
        "captureMethodRtaGroup": 'RTA GROUP',
        "captureScanMismatch": '{found} neue Messung(en) in REW gefunden, erwartet waren {expected} (eine je Kanal in der '
                               'gespeicherten Reihenfolge). Nimm die fehlenden auf oder prüfe die Reihenfolge, dann versuch '
                               'es erneut.',
        "captureRenaming": 'Benenne {n} Messung(en) in REW um…',
        "captureRenameOk": '{n} Messung(en) passend zur gespeicherten Kanalreihenfolge umbenannt.',
        "captureRenameFail": 'Umbenennen nach {n} Messung(en) fehlgeschlagen: {error}',
        "effectProcess": 'den Prozess festhalten (Plan, Schritte, Journal)',
        "effectProfile": 'das Fähigkeitsprofil des DSP schreiben',
        "effectLedger": 'einen Ledger-Schnappschuss der DSP-Einstellungen eintragen',
        "effectProject": 'die eigenen Dateien des Projekts schreiben',
        "effectContract": 'das Projekt gegen den Vertrag des Skills prüfen',
        "gateMode": 'Fragen bei',
        "gateWrites": 'jedem Schreibvorgang',
        "gateForeign": 'nur bei dem, was dem Skill nicht gehört',
        "gateModeTip": 'Der Skill schreibt ständig in `process/`, `state/` und die eigenen Dateien des Projekts, und '
                       'ein neues Projekt fragt zu all dem nicht: eine Rückfrage bei jedem `ls` ist eine, die man '
                       'wegzuklicken lernt, und die schützt dann nichts. Was weiterhin für dich anhält, ist das, was '
                       'das Auto verändert — TCCs eigene Schreibvorgänge ins DSP und nach REW fragen im Werkzeug '
                       'selbst nach, wie das hier auch steht. Verenge es hier, wenn du auch den Dateiverkehr vor '
                       'Augen haben willst.',
        "configureModels": 'Modelle…',
        "configureModelsTitle": 'Modelle in der Generator-Auswahl',
        "configureModelsBlurb": 'omp meldet jedes Modell, das es kennt. Hake die an, zu denen du Zugang hast — genau die '
                                'bietet die Generator-Auswahl an. Claude läuft über das Agent SDK und ist immer verfügbar.',
        "configureModelsFilter": 'nach Name, Anbieter oder ID filtern',
        "configureModelsCount": '{n} Modelle in omps Katalog',
        "configureModelsSetup": 'omp einrichten…',
        "configureModelsSetupTip": 'Öffne omps eigene Einrichtung in einem Terminal — dort werden Konten, API-Schlüssel und '
                                   'Anmeldungen konfiguriert. Sie entscheidet, welche Modelle oben in der Liste erscheinen; wenn '
                                   'du fertig bist und hierher zurückkommst, wird die Liste neu gelesen. TCC hält keine dieser '
                                   'Zugangsdaten: das Terminal und die Sitzung darin gehören dir.',
        "configureModelsSetupOpened": 'omps Einrichtung ist in einem Terminal offen. Wenn sie fertig ist, komm in dieses Fenster '
                                      'zurück — die Liste wird neu gelesen.',
        "mcpDown": 'Der MCP-Server läuft nicht, also hat eine Sitzung nichts, worüber sie TCC erreichen könnte. '
                   'Starte TCC neu; wenn es weiter passiert, steht der Grund hier und im Protokoll:',
        "mcpDownLog": 'Protokoll:',
        "modelClipboardOnly": 'nur Zwischenablage',
        "modelInstallCli": 'installiere das CLI {cli}',
        "modelRecommended": 'empfohlenes Paar',
        "modelGoneTitle": 'Dieses Modell wird nicht mehr angeboten',
        "modelGone": 'Dieses Projekt steht auf {model}, und nichts auf dieser Maschine kann es noch starten — '
                     'Modelle laufen aus. Wähle, was an seiner Stelle laufen soll; die Zuordnung gilt überall, wo '
                     'dieser Name noch auftaucht, nicht nur hier.',
        "modelGoneWhy": 'auf dieser Maschine nicht mehr angeboten',
        "modelAliased": '{old} läuft auf dieser Maschine jetzt als {new}. Die Sitzungen sagen das, damit der Eintrag '
                        'nichts anderes behauptet.',
        "cliRouteQuiet": '{routes} ist installiert, hat aber keine Modelle aufgelistet — womöglich ist seine eigene '
                         'Anmeldung abgelaufen. Seine Einträge fehlen in der Prüfer-Auswahl, sie sind nicht '
                         'verschwunden.',
        "modelFree": 'kostenlos',
        "ompMissing": '⚠️ omp ist nicht installiert — brew install can1357/tap/omp, oder wähle ein Claude-Modell.',
        "copyValue": 'Wert kopieren',
        "copyRow": 'Zeile kopieren',
        "copyHint": 'Hinweis kopieren',
        "copySelection": 'Auswahl kopieren',
        "copyMessage": 'Nachricht kopieren',
        "aiMain": 'KI main',
        "aiEffort": 'Aufwand',
        "aiCritic": 'KI critic',
        "effort_high": 'high',
        "effort_xhigh": 'x-high',
        "effort_max": 'max',
        "effortTip_high": 'Genug für Routineschritte. Die Untergrenze fürs Einmessen — darunter stimmt ein Modell zu '
                          'leicht zu.',
        "effortTip_xhigh": 'Der Standard, mit Reserve. Passt für fast jeden Schritt einer Abstimmung.',
        "effortTip_max": 'Für den wirklich schweren Schritt. Nichts steigt von selbst hierher — eine tiefer begonnene '
                         'Sitzung bleibt tiefer, wie schwer die Arbeit auch wird. Langsamer, und auf einer '
                         'abgerechneten Route teurer.',
        "effortNextSession": 'Der Aufwand gilt ab der nächsten Sitzung — diese behält die Stufe, mit der sie gestartet '
                             'ist.',
        "note": 'Prototyp · echte Daten (sound_AutoSci) · die Form wird gefeilt',
        "coffeeBtn": '☕ Spendier mir einen Kaffee',
        "supportGithub": '💜 GitHub Sponsors',
        "supportMonobank": '☕ Monobank-Sammeldose',
        "fbBig": 'Dem Entwickler schreiben',
        "fbBigTip": 'Ein Fehler, eine Idee, eine Frage, „das ergibt keinen Sinn“ — alles kommt hierher. Ein '
                    'Screenshot kann mit.',
        "fbHead": 'Rückmeldung zum TCC-Prototyp',
        "fbHint": 'Sag uns, was dir gefällt / was zu ändern ist. Nutze die Schaltflächen B / I / Liste — '
                  'Markdown von Hand ist nicht nötig.',
        "fbPh": 'Deine Rückmeldung zum Prototyp…',
        "fbCancel": 'Abbrechen',
        "fbSendGithub": 'An GitHub senden →',
        "fbSendForm": 'Über das Formular senden →',
        "fbVia": 'Wie senden:',
        "fbViaGithub": 'GitHub-Issue (ich habe ein Konto)',
        "fbViaForm": 'Google-Formular (kein Konto nötig)',
        "dialog": 'KI-Dialog',
        "dialogSub": 'Generator ↔ Critic ↔ Arbiter',
        "planTitle": 'Plan — Ist',
        "planSub": 'Phasen + Schritte',
        "focus": '◆ JETZT IM FOKUS',
        "measSub": 'Messaufgabe',
        "confirmAlways": 'In diesem Projekt nicht mehr danach fragen',
        "gateAuto": 'Gar nicht fragen (auto)',
        "gateAutoTip": 'Werkzeuge des Harness (Shell, Lesen, Bearbeiten) laufen ohne Rückfrage. TCCs eigene '
                       'Schreibvorgänge ins DSP und nach REW fragen weiterhin nach — das sind die, die das Auto '
                       'verändern.',
        "autoAllowed": '<code>{tool}</code> automatisch erlaubt — die Rückfrage dazu ist für dieses Projekt aus.',
        "questionCancelled": 'Frage zurückgezogen — der Zug kann weitergehen.',
        "questionWithdrawn": 'Der Agent hat diese Frage zurückgenommen.',
        "questionWaiting": 'Wartet auf deine Antwort',
        "questionFreeText": 'Tipp deine Antwort unten ein — hier gibt es nichts auszuwählen.',
        "questionRole": 'FRAGE',
        "composerAnswer": 'Antworte, oder tipp deine eigene…',
        "composerQueue": 'Dem Generator schreiben… (geht raus, wenn dieser Zug endet)',
        "composer": 'Dem Generator schreiben…',
        "queueWaiting": '⏳ {count} deiner Nachricht(en) gehen raus, wenn dieser Zug endet',
        "queueSendNow": 'Jetzt senden',
        "newBelow": '↓ Neue unten · {count}',
        "newBelowTip": 'Während du gelesen hast, kamen neue Nachrichten. Der erste Klick springt an ihren Anfang, '
                       'ein zweiter ganz nach unten.',
        "messageNotSent": 'Nicht gesendet: die Sitzung hat gestoppt. Dein Text steht wieder im Feld.',
        "quitSaving": 'Speichere vor dem Beenden — warte darauf, dass das Modell das Projekt festhält. Das Fenster '
                      'schließt sich von selbst, sobald das erledigt ist.',
        "send": 'Senden',
        "stop": 'Stopp',
        "notVisible": 'Ich sehe diese Änderung nicht',
        "notVisibleHint": 'Sag der KI, dass etwas, das sie geändert hat, hier nicht aufgetaucht ist, damit sie es auf '
                          'der Festplatte prüft, statt die Behauptung zu wiederholen.',
        "notVisibleSent": 'Für die KI markiert: <b>etwas, das sie gemeldet hat, ist hier nicht sichtbar</b> — sie prüft '
                          'es auf der Festplatte nach.',
        "agentThinking": 'Arbeitet…',
        "agentFailed": 'Sitzungsfehler',
        "confirmAllowed": 'Der Arbiter hat <code>{tool}</code> <b>erlaubt</b>.',
        "confirmDenied": 'Der Arbiter hat <code>{tool}</code> <b>abgelehnt</b>.',
        "modelUnchosen": '— Modell wählen —',
        "startSessionNoModel": 'Wähle zuerst ein Generator-Modell.',
        "startSessionReady": 'Eine Sitzung auf {model} starten. Bis dahin läuft nichts.',
        "startSessionRunning": 'Es läuft bereits eine Sitzung.',
        "restartSession": '▶ Neu starten auf {model}',
        "restartSessionTip": 'Kein Harness kann das Modell mitten im Gespräch wechseln — die laufende endet, und eine neue '
                             'Sitzung beginnt.',
        "sessionStarting": 'Starte {model} — der erste Zug liest den Skill und den Projektzustand, deshalb ist er '
                           'langsam.',
        "sessionHandoff": 'Speichere den Projektzustand vor dem Modellwechsel…',
        "sessionHandoffSave": 'Bitte das Modell, sein Wissen in die Projektdateien zu schreiben…',
        "sessionHandoffQuit": 'Speichere vor dem Schließen — bitte das Modell, sein Wissen in die Projektdateien zu '
                              'schreiben…',
        "quitSaveSave": 'Den Zug speichern',
        "quitSaveDiscard": 'Nicht speichern',
        "quitSaveCancel": 'Bleiben',
        "quitSaveTitle": 'Vor dem Schließen speichern?',
        "quitSaveBody": 'Eine Sitzung läuft.\n\nWas sie in diesem Zug gelernt hat, steht erst auf der Platte, wenn sie '
                        'es schreibt — jetzt zu schließen verliert es. Speichern kostet einen Zug.',
        "sessionHandoffFresh": 'Speichere zuerst, dann beginne ich eine neue Sitzung mit leerem Kontext…',
        "sessionRestarted": 'Sitzung beendet: Neustart auf dem eben gewählten Modell.',
        "dialogIdle": 'nicht gestartet · {model}',
        "dialogNoModel": 'kein Modell gewählt',
        "startSession": '▶ Sitzung in TCC',
        "openTerminal": '⧉ Terminal',
        "terminalOpened": 'Ein Terminal mit <code>{cli}</code> im Projektordner ist offen. Es findet TCC über '
                          '<code>.mcp.json</code>; bestätige beim ersten Lauf den Server <b>tcc</b>.',
        "criticClipboard": 'Weder die API noch das CLI des Prüfers war erreichbar, also liegt das Paket in deiner '
                           '<b>Zwischenablage</b>. Füge es in einen beliebigen KI-Chat ein und die Antwort hier wieder '
                           'zurück — der Kreis funktioniert weiter, er geht nur durch dich.',
        "criticFailed": 'Der Aufruf des Prüfers ist fehlgeschlagen: {detail}',
        "criticNotReady": 'Der Prüfer hat noch nichts zu lesen. Er liest das Projekt bei jedem Aufruf neu von der '
                          'Festplatte, und dieser Ordner hat den Intake nicht durchlaufen — der Vertrag und der Kontext '
                          'des Autos entstehen, wenn eine Abstimmung beginnt. Der Kanal selbst ist in Ordnung; starte '
                          'die Abstimmung, und der Prüfer arbeitet ab dem ersten Vorschlag.',
        "criticNever": 'Kritiker: noch nicht aufgerufen',
        "curveSendMarkers": 'Marker',
        "curveSendDelays": 'Delays',
        "curveShift": 'Delay',
        "curveShiftTip": 'Halte das gewählte Chassis zurück — der Schalter bestimmt, welches. Es beginnt bei dem, das '
                         'ZUERST ankommt, die natürliche Wahl im ersten Durchgang; negativ ist erlaubt, denn in einem '
                         'späteren Durchgang korrigierst du einen Kanal, der bereits ein Delay trägt. Was nicht unter '
                         'null darf, ist die SUMME des Kanals, und der Ablesewert sagt das, sobald das Ledger bekannt '
                         'ist. Die Schrittweite ist die, die dieses DSP eingeben lässt. Es wird nichts angewendet: der '
                         'Ablesewert geht als Vorschlag hinaus.',
        "curveDelayHead": 'Delay zum Ausrichten (Vorschlag, nicht angewendet):',
        "curveApfLabel": 'Allpass:',
        "curveApfNone": '—',
        "curveApfTip": 'Ein Allpass für das Chassis, das der Schalter gewählt hat — dasselbe, das auch das '
                       'Delay-Feld bearbeitet. Er ändert KEINEN Pegel und dreht die Phase um f0: APF1 dreht bei f0 '
                       'um −90° (insgesamt 0 → −180°), APF2 bei f0 um −180° (0 → −360°), und Q sagt, wie viel dieser '
                       'Drehung dicht bei f0 passiert. Im Frequenzgang bewegt sich die Kurve nicht; in der Phase '
                       'dreht sie sich; in beiden zeigt die vorhergesagte Summe (Σ), was das mit der Übernahme macht '
                       '— darum geht es. Im Impuls bleibt der gezeichnete Verlauf wie aufgenommen (ein Allpass '
                       'verschmiert einen Impuls); die Summe im Streifen trägt ihn. Es wird nichts angewendet: er '
                       'geht als Vorschlag in den Ablesewert, in den Worten des Ledgers (APF2 250 Hz Q 0.71). Und '
                       'ein Allpass füllt keine Auslöschung eines einzelnen Chassis — durch Phasendrehung lässt sich '
                       'nur die Summe zweier überlappender Chassis neu abstimmen, lies ihn also an der Summe, nie an '
                       'einer einzelnen Kurve. Die Mathematik gehört dem Skill selbst (dsp_math), hier gibt es keine '
                       'zweite Kopie.',
        "curveApfKindTip": 'Welche Ordnung. APF1: nur f0, dort −90° — die sanftere Vierteldrehung. APF2: f0 und Q, dort '
                           '−180° — das, was ein APF2-Platz in einem PEQ-Satz annimmt. Zwei APF1 auf einer f0 sind ein '
                           'APF2 mit Q 0,5.',
        "curveApfF0Tip": 'Die Frequenz, um die gedreht wird. Setz sie dorthin, wo die Übernahme liegt — auf die '
                         'Trennfrequenz zwischen den beiden summierten Chassis.',
        "curveApfQTip": 'Wie viel der 360° dicht bei f0 passiert (nur APF2). 0,71 dreht über etwa anderthalb Oktaven '
                        'zu jeder Seite von f0; ein höheres Q dreht schneller und hält der Drift eines echten Autos '
                        'schlechter stand — die Suche des Skills endet bei 4.',
        "curveApfHead": 'Allpass zum Drehen der Phase (Vorschlag, nicht angewendet):',
        "curveApfNoMaths": 'kein Allpass simulierbar: die Filtermathematik des Skills ließ sich nicht laden ({error})',
        "unitMs": 'ms',
        "unitSmp": 'Samples',
        "curveDelayRelative": 'Bezogen auf {name}, das keines bekommt: gemessen wurden nur die Unterschiede zwischen diesen '
                              'Chassis, der Satz ist also von dem aus angegeben, das am wenigsten braucht.',
        "curveDelayLands": 'Ankunft {was} → {now} ms',
        "curveDelayTotal": 'Kanal → {total} ms',
        "curveDelayBelowZero": '⚠ unter null — dahin kann der Kanal nicht',
        "curveBankImpossible": 'Eines davon führt einen Kanal unter null, der Satz lässt sich so also nicht anwenden — sag, '
                               'welchen Bezugspunkt man stattdessen verschieben soll.',
        "curveBankLabel": 'abgelesene Delays:',
        "curveBankLabelIn": 'abgelesene Delays in {set}:',
        "curveBankBtn": 'Abgelesene Delays ({n})',
        "curveSumNoteBtn": 'Σ Prognose',
        "curveGuidesTip": 'Nimm alle Hilfslinien aus dem Bild: die Marker, die Pegel, die Kreuzlinie und ihre Punkte. '
                          'Nichts geht verloren — jede kommt genau dorthin zurück, wo sie war, und der Ablesewert '
                          'bleibt derselbe Satz, denn ein Marker, den du nicht siehst, ist trotzdem eine Zahl, die du '
                          'genommen hast. Solange sie verborgen sind, lassen sie sich nicht ziehen.',
        "curveStripLinkTip": 'Der Frequenzskala des Diagramms folgen. In der Phase sind Streifen und Diagramm dieselben '
                             'Frequenzen, ein Zoom bewegt also beide, und was oben bei 3 kHz steht, steht unten bei 3 kHz. '
                             'Schalt es aus, um eine Auslöschung für sich zu vergrößern, und wieder ein, um sie erneut '
                             'auszurichten. Im Impuls nicht angeboten: dort ist die Achse die Zeit.',
        "curveReadoutBtn": 'Marker',
        "curveBankEmpty": 'noch keine Delays abgelesen — stell oben eines ein, es wird je Messung behalten',
        "curveClearLabel": 'leeren:',
        "curveClearDelay": 'Delays',
        "curveClearMarkers": 'Marker',
        "curveBankAsk": 'Delays, die ich von den Kurven abgelesen habe, NUR ZUR ANALYSE — schreib sie nirgendwo hin '
                        'und behandle sie nicht als Änderung:',
        "curveBankConvention": 'Konvention: alle Messungen teilen einen Zeitnullpunkt (0 ms auf der Impulsachse). Jede Zahl '
                               'unten wird auf die Ankunft DIESER Messung addiert, so wie sie aufgenommen wurde; das Ziel '
                               'ist, dass alle Chassis auf derselben Ankunft landen.',
        "curveBankArrival": 'Ankunft',
        "curveBankChannel": 'Kanal',
        "curveBankSpread": 'Streuung der resultierenden Ankünfte über die {n} platzierten Chassis: {spread} ms.',
        "curveBankAtZero": 'Auf dem Bildschirm, keine Verschiebung eingegeben (0). Das kann der Bezug sein, von dem aus '
                           'der Rest gemessen wurde, oder einfach ein Chassis, zu dem man noch nicht gekommen ist — die '
                           'Daten hier können das nicht unterscheiden: {names}',
        "curveBankUnplaced": 'NICHT platziert — an diesen wurde noch nichts abgelesen, sie fehlen also im Bild oben und '
                             'dürfen NICHT als null angenommen werden: {names}',
        "curveBankNotForWriting": 'Sag mir, ob dieser Satz stimmig ist: welche Ankünfte er impliziert, ob etwas davon eher nach '
                                  'einem Messfehler als nach einer Abstimmung aussieht, und was du als Nächstes prüfen würdest. '
                                  'Das sind Ablesewerte von den Kurven, kein Ziel — Ankünfte exakt auszurichten hat in diesem '
                                  'Auto für sich genommen die Bühnengenauigkeit nicht repariert; nimm sie also als Indiz und '
                                  'sag, was du ändern würdest und warum. Nichts davon ist angewendet.',
        "curveBankAskApfOnly": 'Allpass-Filter, die ich an den gemessenen Kurven eingestellt habe, NUR ZUR ANALYSE — '
                               'schreibe nichts.',
        "curveBankApf": 'Allpass, pro Chassis eingestellt mit Blick auf die vorhergesagte Summe (Vorschlag, nicht '
                        'angewendet; Betrag unverändert, nur Phase; APF1 = −90° bei f0, APF2 = −180° bei f0):',
        "curveBankApfCaveat": 'An den vorhandenen Sweeps simuliert, indem die gemessene Phase gedreht wurde; NICHT durch '
                              'einen Summenmessung bestätigt. Sag, ob die Drehung die Übernahme repariert oder das Problem '
                              'nur verschiebt (und das Timing oberhalb f0 mitzieht), und welche Aufnahme es bestätigen '
                              'würde.',
        "curveNoMarkers": 'Zieh einen Marker auf den Punkt, den du meinst.',
        "curveMarkerModel": 'Modell',
        "curveMarkerYou": 'du',
        "curveMarkerOne": '1',
        "curveMarkerTwo": '2',
        "curveMarkerN": 'Marker {n}',
        "curveTitle": 'Wo genau?',
        "curveAxes_v": 'Marker lesen die Frequenz (senkrecht)',
        "curveAxes_h": 'Marker lesen den Pegel (waagerecht)',
        "curveAxes_vh": 'Marker lesen beides, getrennt gesetzt',
        "curveAxes_vhs": 'Ein Punkt auf der Kurve gibt beides — der Pegel folgt der Frequenz',
        "curveAxes_vx": 'Eine senkrechte Linie: liest BEIDE Kurven bei diesem x und ihren Abstand',
        "curveAxes_hx": 'Eine waagerechte Linie: liest, wo JEDE Kurve diesen Pegel erreicht (der Schnittpunkt nächst '
                        'der Mitte der Ansicht)',
        "curveCrossPairTip": 'Welche zwei Kurven Vx und Hx vergleichen. Sie lesen einen Abstand zwischen einem Paar, bei '
                             'mehr Kurven auf dem Bildschirm nennst also du das Paar — die gewöhnlichen V/H/VH-Marker '
                             'lesen weiterhin jede Kurve, je eine Zahl.',
        "curveSumTip": 'Σ — zeichne, was diese Chassis ZUSAMMEN tun: die komplexe Summe der Kurven auf dem '
                       'Bildschirm, gestrichelt, in dB, mit dem Delay jedes Chassis bereits angewendet. In der Phase '
                       'liegt sie über dem Diagramm auf der rechten Achse; im Impuls bekommt sie einen eigenen '
                       'Streifen darunter, denn dort ist die Achse des Diagramms die Zeit und die der Summe die '
                       'Frequenz. Es ist Arithmetik auf Messungen, die du schon hast, ein Versuch kostet also nichts '
                       'und es wird nirgendwo etwas geschrieben. Sie bedeutet nur etwas, wenn alle Messungen gegen '
                       'EINEN gemeinsamen Zeitbezug aufgenommen wurden; die Σ-Schaltfläche unter dem Diagramm trägt '
                       'das Urteil — was geprüft ist und was nicht.',
        "curveSumHead": 'Vorhergesagte Summe, gestrichelt, in dB:',
        "curveSumWorst": 'Tiefster Punkt der Summe: {depth} dB gegenüber dem dort lautesten einzelnen Chassis, bei '
                         '{hz} Hz.',
        "curveSumNone": 'Keine Summe gezeichnet.',
        "curveSumNoPlot": 'Diese Ansicht konnte die Achse, auf der die Summe gezeichnet wird, nicht bauen, es gibt also '
                          'keinen Platz dafür. Der Rest des Fensters ist davon unberührt.',
        "curveSumTooFew": 'Eine Kurve ist keine Summe: hol eine zweite Messung auf den Bildschirm.',
        "curveSumNoData": 'Diese Kurven tragen weder Betrag noch Phase zum Aufsummieren — sie stammen nicht aus einem '
                          'REW-Sweep.',
        "curveGroupLabel": 'füllen:',
        "curveGroupNone": '— keine Gruppe —',
        "curveGroupKind_pairs": 'Paar',
        "curveGroupKind_joints": 'Übernahme',
        "curveGroupKind_sides": 'Seite',
        "curveGroupKind_combos": 'Kombination',
        "curveGroupNoGlossary": '— kein Glossar in diesem Projekt —',
        "curveGroupTip": 'Fülle die Auswahl mit einer ganzen Gruppe auf einmal — die Tiefmitteltöner, die Mitteltöner, '
                         'Sub+Tiefmitteltöner, eine Seite, alles. Die Namen kommen aus dem Glossar dieses Autos, und '
                         'die gewählten Sweeps sind die der Konfigurationsversion daneben. Es wird nichts geholt, was '
                         'die Gruppe nicht nennt: ein Mitglied, für das REW keinen Sweep hat, wird gemeldet, nicht '
                         'übersprungen. Sie FÜLLT und lässt dann los: nimmst du danach einen Chip weg, füllt nichts '
                         'nach — und genau so hört man, was ein einzelnes Chassis mit der Übernahme macht.',
        "curveGroupVersionTip": 'Aus welcher Aufnahmeserie die Sweeps der Gruppe stammen — die DSP-Konfiguration, unter der '
                                'sie gemessen wurden, im REW-Titel als `_N` geschrieben und im Messpanel genauso benannt. Sie '
                                'beginnt bei der Serie, die die Kurven auf dem Bildschirm teilen, oder bei der neuesten, die '
                                'dieses Auto für diese Chassis hat, und du kannst sie verschieben.',
        "curveGroupMissing": '{group} bei _{version}: {names} — nicht in REW. Gezeichnet ist die Summe eines anderen '
                             'Satzes.',
        "curveGroupEmpty": '{group} bei _{version}: REW hat von keinem Mitglied einen Sweep, es wurde also nichts '
                           'geändert.',
        "curveChooseBtn": 'Wählen… ({n})',
        "curveChooseTip": 'Hake beliebige Messungen an — die Summe nimmt so viele, wie du ihr gibst. Das Menü bleibt '
                          'offen, eine ganze Seite ist also ein Durchgang durch die Liste. Alles Angehakte steht als '
                          'Chip darüber, in der Farbe seiner Kurve; eine Gruppe daneben füllt dieselben Chips in einem '
                          'Zug.',
        "curveChipRemoveTip": 'Nimm {title} aus dem Diagramm. Der Rest bleibt, wo er ist, und die Summe wird ohne es neu '
                              'gerechnet — genau so hört man, was dieses eine Chassis mit der Übernahme macht.',
        "curveChipOnlyTip": 'Die einzige Kurve auf dem Bildschirm. Füg eine weitere hinzu, bevor du diese wegnimmst — ein '
                            'Fenster, das nichts zeichnet, hat nichts zu sagen.',
        "curveChipMissingTip": 'REW hat für {title} keine Kurve geliefert, es steht also nicht im Diagramm, obwohl es '
                               'ausgewählt ist — und in der Summe auch nicht. Deshalb wird es blass gezeigt.',
        "curveAt": 'bei',
        "curveZoomAll": 'Alles zeigen, was die Aufnahme enthält',
        "curveZoomAllShort": 'A',
        "curveZoomDetail": 'Zurück zum Bereich, mit dem dies geöffnet wurde',
        "curveZoomDetailShort": 'D',
        "curveZoomOut": 'Verkleinern',
        "curveZoomOutShort": '−',
        "curveZoomIn": 'Vergrößern',
        "curveZoomInShort": '+',
        "curveKind_impulse": 'Impulsantwort',
        "curveKind_fr": 'Frequenzgang',
        "curveKind_phase": 'Phase',
        "curveRtaOnly": 'Gezeigt wird der Frequenzgang: {titles} — eine MMM-Aufnahme, und dafür hat REW weder '
                        'Impulsantwort noch Phase.',
        "curveRtaTip": 'Eine MMM-Aufnahme: REW hat dafür weder Impulsantwort noch Phase. Wechsle auf den '
                       'Frequenzgang, um sie ins Diagramm zu holen.',
        "curveKindRtaTip": 'Nicht für eine MMM-Aufnahme — REW hat dafür weder Impulsantwort noch Phase. Wähle oben '
                           'Sweeps (sw), um dies zu lesen.',
        "curveBtn": 'Kurven — setz einen Marker dorthin, wo du es meinst',
        "curveNothing": 'Noch nichts zu zeichnen — lies zuerst die Messungen aus REW.',
        "curveLoading": 'Lese die Kurven aus REW…',
        "curveFailed": 'Konnte nicht aus REW lesen: {error}',
        "modelMissingRow": '{key} — hier nicht verfügbar',
        "modelMissingTip": 'Dieses Projekt verlangt ein Modell, das diese Maschine nicht anbietet. Es bleibt ausgewählt '
                           'und bleibt rot, bis du ein anderes wählst — nichts wird hinter deinem Rücken umgeleitet.',
        "modelUnconfirmed": 'vom letzten Start',
        "attachTip": 'Einen Screenshot anhängen — wird im Projekt gespeichert, das Modell liest die Datei',
        "attachTitle": 'Screenshot anhängen',
        "attachClear": 'Leeren',
        "attachEmptyMac": '⌘⌃⇧4 kopiert einen Screenshot in die Zwischenablage (⌘⇧4 legt ihn stattdessen auf den '
                          'Schreibtisch). Drücke dann hier ⌘V.',
        "attachEmptyWin": 'Win+Shift+S kopiert einen Screenshot in die Zwischenablage. Drücke dann hier Strg+V.',
        "attachEmptyOther": 'Kopiere einen Screenshot in die Zwischenablage, drücke dann hier Strg+V.',
        "attachCaption": 'Was darauf zu sehen ist — z. B. „w-L Impulsantwort, erster Peak“',
        "criticWarnTitle": 'Zum Prüfer',
        "criticSubstituted": 'ersetzt',
        "criticAnswered": 'beantwortet von {model}',
        "criticSameVendor": 'derselbe Anbieter wie der Generator',
        "criticSameVendorTip": 'Prüfer und Generator sind beide {vendor}. Es wird weiterhin geprüft, aber ein Prüfer, der '
                               'für anbieterübergreifende Unabhängigkeit gewählt wurde, ist keiner mehr — gewichte seine '
                               'Zustimmung niedriger, oder stelle einen anderen Anbieter wieder her.',
        "sdkNoLogin": 'claude ist nicht angemeldet',
        "sdkNoLoginTip": 'Claude-Modelle laufen über deine eigene `claude`-Sitzung — TCC hat kein eigenes Konto und '
                         'kann sich nicht für dich anmelden. Ohne Anmeldung kann diese Route nicht antworten, was die '
                         'Auswahl auch anzeigt. Führe in einem Terminal aus:\n\n    {cmd}',
        "criticStatus": 'Kritiker · {model} · {ago}',
        "sessionResumed": 'fortgesetzt',
        "sessionNew": 'neue Sitzung',
        "editChipLabel": 'Projektparameter bearbeiten',
        "editReasonsQ": 'Warum?',
        "reasonForgot": 'der Skill hat nicht gespeichert',
        "reasonManual": 'ich habe etwas von Hand geändert',
        "editStartForgot": '◆ Projektparameter bearbeiten — markiert: der Skill hat eine kürzliche Änderung womöglich '
                           'nicht gespeichert. Beschreibe, was im Ledger stehen sollte; ich prüfe es und korrigiere.',
        "editStartManual": '◆ Projektparameter bearbeiten — du hast etwas von Hand geändert. Sag, was und wo; ich halte '
                           'es im Ledger fest, damit spätere Empfehlungen es berücksichtigen.',
        "editDoneForgot": '✓ Ledger geprüft: das Delay von <code>Rear R Full</code> stand im Dialog auf 9,5 ms, auf der '
                          'Festplatte aber auf 8,0 ms — behoben, wieder als 9,5 ms gespeichert.',
        "editDoneManual": '✓ Vermerkt: <code>Front R High</code> Pegel 1,4 → 1,0 dB (von Hand). Ledger aktualisiert und '
                          'neu bestätigt.',
        "targetHandedOver": 'Das Werkzeug trägt „{name}“ nicht, die Kurve ist also im Link selbst mitgefahren — sie '
                            'sollte als „{name}“ im Diagramm stehen. Steht sie nicht da, ist das veröffentlichte Werkzeug '
                            'älter als diese App; sag Bescheid, dann wird sie stattdessen als Datei übergeben.',
        "targetLocalViewer": 'Das Werkzeug trägt „{name}“ nicht, das hier ist also eine LOKALE Kopie davon mit deiner '
                             'Kurve bereits darauf — gebaut aus der Methodenversion, auf die diese App gepinnt ist, nicht '
                             'die Live-Seite. Alles andere daran gehört dem Werkzeug.',
        "targetNotInTool": 'Das Werkzeug bringt „{name}“ nicht mit — es trägt nur die eigenen Kurven der Methode und '
                           'lernt jede andere, indem man ihm die Datei darauflegt. Deine ist im Dateimanager ausgewählt: '
                           'zieh sie auf die Seite.',
        "targetNoFile": 'Das Werkzeug bringt „{name}“ nicht mit, und im Projekt wurde keine Datei dafür gefunden — '
                        'die Seite öffnet mit den Kurven, die sie hat. Exportiere die Kurve nach '
                        'rew_analitic/target-curves/{name}/, dann lässt sie sich darauflegen.',
        "targetRevealFailed": 'Das Werkzeug bringt „{name}“ nicht mit. Der Dateimanager ließ sich nicht öffnen; die Datei '
                              'liegt unter {path} — zieh sie auf die Seite.',
        # Phase 4, the listening panel (2026-08-25).
        "lsnDropLast": 'Letztes zurück',
        "lsnBtn": 'Hören',
        "lsnBtnTip": 'Was genau dieses Stück zeigen soll — in Worten; dazu ein 🟢/❌ mit deinem eigenen Satz, ins '
                     'Journal geschrieben, gegen den Zustand, den du gehört hast.',
        "lsnTitle": 'Hören — was zu beurteilen ist, und was du gehört hast',
        "lsnWhy": 'Wähl rechts ein Stück, dann die Formulierung, die zu dem passt, was du hörst. Sie landet '
                  'links im Feld als Zeile, die du umschreiben kannst. Beides wird behalten, das Häkchen und '
                  'deine Worte, und keines steht für das andere: das Häkchen liest später ein Filter, die Worte '
                  'sind das, was du gemeint hast.',
        "lsnRoute": 'Durchgang',
        "lsnRoute_first": 'erstes Hören',
        "lsnRoute_short": 'kurz (10 Min.)',
        "lsnRoute_full": 'voller Durchgang',
        "lsnRoute_league": 'nächste Liga',
        "lsnRouteRoot": 'Dieser Durchgang',
        "lsnAll": 'Die ganze Bibliothek',
        "lsnAt": 'bei {timecode}',
        "lsnCueTip": 'Wo es zu hören ist: {cue}',
        "lsnRouteTip": 'Wenn es ✗ wird: {route}',
        "lsnText": 'Was du gehört hast, in deinen eigenen Worten…',
        "lsnTicked": 'Angehakt ({n}):',
        "lsnTickedEmpty": 'Noch nichts angehakt — klick rechts eine Formulierung an, sie landet hier und im Text.',
        "lsnRemoveTip": 'Nimm das aus dem Eintrag. Die Zeile, die es geschrieben hat, bleibt im Text — schreib sie '
                        'selbst um, wenn sie nicht mehr passt.',
        "lsnSave": 'Eintragen',
        "lsnSaved": 'Eingetragen: {n} Urteil(e), gegen {version}.',
        "lsnRefused": 'Nicht eingetragen: {why}',
        "lsnNoPairs": 'Noch nichts einzutragen: hak mindestens eine Formulierung an. Deine Worte werden ZUSAMMEN '
                      'mit den Häkchen behalten, nicht an ihrer Stelle.',
        "lsnSheet": 'Der ganze Spickzettel',
        "lsnSheetTitle": 'Hören — der Spickzettel',
        "lsnUnavailable": 'Das Hör-Vokabular der Methode konnte hier nicht gelesen werden: {why}',
        "lsnProblems": 'Die eigene Prüfung der Methode meldet: {problems}',
        "lsnNotTranslated": 'noch nicht übersetzt — gezeigt wird das Englische',
        "lsnVersion": 'Zustand {version}',
        "lsnNoVersion": 'noch kein Ledger-Schnappschuss — das Urteil wird ohne einen eingetragen und lässt sich '
                        'später keinem Zustand zuordnen',
        "lsnOwnHint": 'Für ein Stück, das hier nicht steht, nimm „own“ — welches es war, sag in deinen eigenen '
                      'Worten.',
    },
}

_lang: Lang = "en"
_listeners: list[Callable[[], None]] = []


def current_language() -> Lang:
    return _lang


def t(key: str) -> str:
    """Plain string lookup, falling back to English, then the key itself."""
    return T.get(_lang, {}).get(key, T["en"].get(key, key))


def language_choices() -> list[tuple[Lang, str]]:
    """`(code, name)` for every offered language, named in the CURRENT language."""
    return [(code, t(key)) for code, key, _badge in LANGS]


def language_badges() -> list[tuple[Lang, str]]:
    """`(code, badge)` for every offered language -- the header combo's two-letter items."""
    return [(code, badge) for code, _key, badge in LANGS]


def language_name(lang: Lang | None = None) -> str:
    """The name of `lang` (default: the current one), in the current language."""
    lang = lang or _lang
    for code, key, _badge in LANGS:
        if code == lang:
            return t(key)
    return lang


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

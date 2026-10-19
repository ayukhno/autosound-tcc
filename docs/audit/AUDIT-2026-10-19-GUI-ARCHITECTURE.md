# GUI architecture audit: reducing MainWindow and the cost of changing it

Date: 2026-10-19. Reviewed tree: `wave-10` at
`2ec76c307976ccbfb9e99c6e06bc9e17c3d67e16`.

Scope: `src/autosound_tcc/ui/tcc/main_window.py`, its UI/core/state collaborators,
tests, test infrastructure and existing architecture/audit plans. Three independent
subagents reviewed feature boundaries, testing costs, and runtime lifecycle; the
primary agent checked their evidence and consolidated this report. This was a
read-only source audit: no application launch, test collection, test execution,
benchmark, network service or product-code change. Only this report was created.
Git staging, commit and push are separately authorized delivery actions.

References below are relative to the repository root; `ui/`, `core/` and `state/`
abbreviate `src/autosound_tcc/ui/tcc/`, `src/autosound_tcc/core/` and
`src/autosound_tcc/state/`. Line numbers describe the reviewed commit.

## Verdict

**The problem is incomplete ownership of GUI features and application lifecycle,
not the absence of architecture or a need to replace Qt.** MainWindow has become
the shared home for widget construction, feature state, project loading, refresh
scheduling, model selection, capture workflow, sessions, saving and shutdown.
Splitting its methods into helper files will reduce its line count, but will not
by itself make a feature cheaper to understand, test or debug.

The recommended direction is incremental composition: keep the existing widgets,
Qt signals, `state/*` projections and `core/*` services; give each substantial
feature explicit inputs, state and lifecycle ownership. Extract decisions into
Qt-free functions and test those without constructing a window. Introduce an
explicit project context so active components stop following a mutable global
folder. Change the test infrastructure as part of this work: today even a pure
decision test under `tests/` inherits Qt-related imports and fixtures.

Start with preset selection and reviewer status as small pilots, then explicit
project scope and model controls. Move session/quit orchestration later, after
its existing behavior is pinned. A full rewrite, universal event bus, mixin tree
or new GUI framework is not justified by the inspected code.

## 1. Measured structure

These are static counts from filesystem text and Python AST inspection, not
runtime measurements or tokenizer counts.

| Measure | Reviewed tree | Meaning |
|---|---:|---|
| `main_window.py` | 6,072 lines; 346,735 bytes | A large context unit for a person or coding agent |
| Methods declared on MainWindow | 221 | Many independently changing responsibilities share one object |
| Top-level functions in its module | 27 | Some reusable formatting/platform helpers also remain here |
| Distinct direct `self.x` assignment targets | 159 | Includes widgets, feature state and service references |
| Of those, assigned outside `__init__` only | 120 | Includes builder initialization; this is an ordering concern, not 120 defects |
| Blank / full comment / docstring lines | 552 / 1,136 / 1,008 | About 44% of the file; not a reason to delete safety explanations |
| Largest methods | constructor 210; footer 193; header 172; project loader 158 lines | Both presentation and orchestration contribute |
| `tests/test_main_window.py` | 8,702 lines; 293 top-level test functions | Function count excludes parametrized expansion |
| `tests/conftest.py` | 1,206 lines | Shared isolation and lifecycle machinery is material |
| Literal window-construction sites across top-level test files | 207 | Existing ratchet metric; not actual runtime construction count |
| Test files importing the main-window module by its full dotted name | 17 | Text count, not a complete dependency graph |

The AST finds `_status_strip` read in 40 MainWindow methods and `_dialog` in 33.
High use of a status sink alone is reasonable; the concern is that independently
changing features also share state and directly manipulate each other's widgets.

Existing work deserves continuation. `tests/test_structure_ratchet.py:31-51`
records the W-8 baseline bounds of 6,506 lines / 223 construction sites and the
current bounds of 6,073 / 207. Compared with those documented initial bounds,
today's counts are lower by 434 lines (6.7%) and 16 sites (7.2%). This demonstrates
progress, not a measured speedup. Extracted `row_rule`, `model_picks`,
`measurement_view` decisions and `ledger_line.compare_offer` are useful precedents.

## 2. What is already designed, and what is missing

The project has meaningful architecture:

- `docs/DATA-MODEL-DECISIONS.md:197` establishes D-6: domain data belongs to the
  method, while TCC renders it and sends intentions. Preserve that ownership and
  existing method command adapters; a refactor must not create a second writer.
- `state/dsp_state.py` and other `state/*` modules supply projections consumed by
  several views. Extend these rather than inventing another domain model in a UI
  controller.
- `ui/qt_bridge.py:1-14,28-95` explicitly separates threads: queued GUI signals
  and cached snapshots protected by a lock. Keep widgets out of server threads.
- `core/session_routes.py:25` and `core/model_picks.py` already separate useful
  policy from widget rendering. `ui/main_menu.py` separates menu rendering.
- `ui/qt_shutdown.py:57-71,84-142,170` owns worker retention/detachment safety.
  That is an existing lifecycle mechanism to preserve, not replace casually.

What is missing is a corresponding GUI rule for **who owns a feature's state,
widgets, dependencies, timers and shutdown**. The main module still describes
itself as an M1 shell with placeholders and predicts growth (`ui/main_window.py:1-9`).
The existing architecture notes explain data ownership and integration much more
clearly than internal GUI ownership. One short ownership decision should replace
that obsolete description when implementation begins; avoid another long parallel
architecture document that can drift from the code.

## 3. Findings and concrete boundaries

### A1 — MainWindow mixes policy, I/O and rendering in the same change surface

`_load_project_inner` (`ui/main_window.py:2173-2330`) validates the DSP profile,
chooses a preset, decides rig-only/empty/refused states, and mutates the tree,
detail pane, sidebars, compare controls and sizing. Its comments at `:2298-2308`
explain why assigning `_view` before rebuilding channel switches is essential.
This is fragile temporal coupling: a valid change depends on another method's
hidden read order.

Extract `select_preset(available, preferred, resolved) -> preset | None` first,
using the existing config resolution rules rather than duplicating them. Next,
give project loading a result with explicit `no_profile`, `rig_only`, `loaded`,
`version_refused` and `error` outcomes. A presenter applies that result to panels
in one defined GUI-thread step. Reuse `ProjectView`; the result is a load envelope,
not a replacement ledger schema. File reads belong in a loader/service, decisions
in pure functions, and widget mutation in the presenter/view.

Acceptance: preset/fallback/error decision tests need no MainWindow; a small
integration test still proves that tree, detail pane and MCP snapshot agree on
the displayed preset. Preserve the existing last-good-display/error behavior
(`:1759-1772`) before attempting to improve it separately.

### A2 — Mutable process-wide project identity causes complexity outside MainWindow

`core/config.py:65-103` resolves the active project from environment/settings.
Open folder (`ui/main_window.py:5637-5661`) changes the chosen folder, launches a
second process, then closes the old window. New Project instead changes the
environment and constructs a new MainWindow in the same process before closing
the old one (`:2614-2624,2644-2646`). Closing may be cancelled in either case.
`ui/window_folder.py:3-8`
documents the historical cross-project failure this caused and the current guard.
Its `:104-110` discovers ownership by walking widget parents and inspecting a
private `_built_on` field.

**Introduce an immutable ProjectContext for each window/runtime.** Resolve the
chosen folder, effective project directory, state-root override, `.tcc` directory
and method binding once for that runtime. Keep “no project chosen” distinct from
the legacy effective-path fallback. Pass the context, or the specific required
path, into readers, command adapters and workers. Global settings can select the
next project; they should not silently retarget existing components.

There is a remaining direct global read in `MonitorFeed.refresh`
(`ui/control_layout.py:140-143`), although the feed retains its original window
(`:102-104`). This is a **potential wrong-project display after a cancelled
switch**, inferred from the call path; it was not runtime-reproduced in this audit.
It shows why guards in the main file alone are insufficient.

Migrate one complete path first: project snapshot, watcher, result application
and MCP publication. Retain `window_folder` as a compatibility adapter until all
live readers/writers are migrated. Preserve environment overrides, no-project
behavior, method binding/trust and both current switch paths. Do not add live
retargeting of an existing window as part of this refactor. Attach context/generation identity
to async results so stale work cannot update a closed or superseded owner.

### A3 — Refresh needs one scheduling owner, not one undifferentiated reload

Refresh entry points are distributed across manual reload (`:1721-1746`), agent
writes (`:1748-1757`), project/process watchers (`:3495-3622`), and bridge setup
(`:4217-4251`). Coalescing and watcher rearming already exist. Preserve those fixes:
an atomic file replacement requires rearming, and an agent write deliberately
does not trigger the manual button's REW/login/update probes.

Introduce a ProjectRefreshCoordinator that owns watchers, timers, pending reasons
and disposal. An explicit small set of reasons should select what to refresh:
project files, process files, agent write, manual reload. Merge overlapping
invalidations while preserving manual-only work. A result can carry project,
process and capture projections together with freshness/error information; do not
claim an atomic disk snapshot unless the method provides a revision contract.

Acceptance: one burst of relevant file events yields the intended coalesced work;
manual probes still run only when requested; atomic replacement rearms; a closed
owner applies no late result. Count loads/renders/commands before optimizing them.
Do not reintroduce the older audit's already-fixed “agent refresh equals full ↻”
finding: the current `:1748-1757` explicitly separates them.

### A4 — Model controls are the best substantial feature extraction

Footer construction (`:1128-1320`), reviewer presentation (`:4597-4706`), probing
(`:5027-5085`) and selection/config handlers (`:5161-5477`) belong to one feature
but are scattered around the window. The reviewer status chooses between refusal,
checking, answered probe, previous call and model mismatch while also formatting
text and mutating labels.

First extract a pure `reviewer_status(facts) -> ReviewerStatus`: facts include the
selected reviewer, availability, probe state, last review, pins and current time.
Return semantic status, message key/arguments, severity and spinner state; perform
I/O before that call and translation/rendering after it. Keep the existing
`model_choices`, `model_picks`, `availability` and MCP reviewer meanings aligned;
introduce no second availability cache or model registry.

Then let ModelControls own its combo boxes, labels, tooltips and `retranslate()`.
A model controller owns selection, probe scheduling and project-setting writes.
It emits explicit selection/status changes and accepts narrow service interfaces.
MainWindow connects those to session and project presentation, without serving as
the feature's data store.

Acceptance: status precedence is tested as plain data; combo rendering uses a
standalone component; only wiring/propagation cases build the complete window.
Probe completion for an old pick must not overwrite the new pick's status.

### A5 — Session/save/quit is a separate lifecycle, and the highest-risk extraction

`_hand_off` through `_launch_session` (`:4768-5025`) and save/close handling
(`:5663-5957`) jointly manage workers, session journal ownership, save modes,
timeouts, queue holds, prompts and closing flags. `_finish_handoff` (`:4917`)
already makes competing turn-done/failure/timeout completion effectively one-shot.

Move lifecycle policy into a plain state transition function and let a
SessionCoordinator perform its effects using existing workers, `session_routes`
and method command adapters. Start by transcribing current transitions; simplify
them only in a separate change. `closeEvent` remains the Qt adapter for an
allow/defer/ask decision. Preserve the distinction between saving TCC-owned
preferences and asking the agent to persist its knowledge.

Explicit invariants: one completion per handoff; Save keeps the conversation;
Cancel restores usable state; quit during Save does not launch another session;
session start/close are paired at most once; Cmd-Q/aboutToQuit and closeEvent are
both covered; shutdown is idempotent and retains running QThreads safely.

`core/session_routes.py:98-109` illustrates an extraction to avoid repeating:
`take_open_journal(window)` is outside the GUI file but still reaches through
private window/worker/session fields and mutates the session. Replace this style
with explicit journal/session inputs and an owned claim operation when touching
that boundary. Qt-free imports alone do not prove independence from MainWindow.

### A6 — Panels should own their widgets and language updates

Header/footer/left/right builders (`:931`, `:1128`, `:2017`, `:3314`) and
`_retranslate` (`:5989-6072`) expose many feature widgets on the main object.
The translation method consequently knows which attributes only exist on certain
branches, rebuilds sidebars and refreshes other features.

Extract cohesive Header, ProjectSidebar and ModelControls components, each with
`render(view_data)` and `retranslate()`, plus public intent signals. Keep geometry
that genuinely spans panels in a small layout owner. Preserve shared panel
reparenting between GUI/control modes (`ui/control_layout.py:23-25`); copying
panels would create a second state path. Capture/signal workflow is another later
feature boundary (`ui/main_window.py:3723-4216`): its controller should own pending
intentions/acknowledgements, while the panel owns replaceable button instances.

Avoid `Sidebar(window)` reaching into dozens of private fields. The success
criterion is independent ownership and component tests, not moving a builder
unchanged into a different file. Existing menu test aliases written onto the host
(`ui/main_menu.py:163-179`) should eventually be replaced by tests of the menu's
public action interface as the corresponding tests migrate.

## 4. The test and debugging costs outside the main file

**Moving tests into smaller files alone does not remove their shared process and
Qt costs.** Root `tests/conftest.py:36` imports Qt, `:84-111` runs GC/freeze work
for each test, and `:150` onward drains MCP activity. Pure tests placed underneath
that conftest still inherit it. `tests/_windows.py:4-12,34-65` documents why full
windows survive across tests and how deferred work must be stopped. Historical
Qt destruction experiments in `ui/qt_shutdown.py:12-35` explain why “delete every
window after each test” is not a safe generic fix here.

Recommendations:

1. Give extracted decision tests a genuinely Qt-free fixture/import path. Keep
   filesystem/environment/network isolation shared where needed, and scope GUI,
   MCP and worker cleanup to the tests that need it. Removing isolation wholesale
   would make a fast but unreliable suite. Reuse fresh-interpreter probes from
   `tests/_fresh.py:14-23` to prove new policy modules do not import Qt.
2. Make three levels explicit: pure decisions; standalone components/controllers
   with fake services; a small set of complete-window integration scenarios.
   Retain real-adapter contract tests so doubles cannot invent service behavior.
3. Migrate tests with each extracted decision, including imports and fixtures.
   Existing pure-policy tests such as `replacements_for` cases still live in the
   main test module (`tests/test_main_window.py:3301-3328`), which imports
   MainWindow at `:35`. Extraction without test migration leaves much of the cost.
4. Before creating `tests/unit/` or `tests/ui/`, fix both discovery mechanisms:
   `scripts/ci_shard.py:47-54` and `tests/test_structure_ratchet.py:58-63` use
   nonrecursive `glob("test_*.py")`. Nested tests could run locally via pytest yet
   disappear from PR CI shards and the ratchet. Verify collection/shard coverage
   equality and preserve stable weighting. Flat feature test files are an interim
   option, but root fixture loading still needs attention.
5. Keep the existing LOC/construction-site ratchet, but supplement it with actual
   runtime construction counts, selected-test time and feature dependency checks.
   `_window_half` (`tests/test_main_window.py:8594-8613`) binds window methods to a
   partial widget: useful targeted coverage, but not proof of an extracted feature.
   Do not optimize merely for the literal `MainWindow(` count.

`docs/TESTING.md:212-226` records an earlier 53 s main-window file versus 302 s in
the whole process, and 740 s whole-suite versus 227 s in per-file processes.
These are historical observations, not current timings or promised savings.
They support measuring process accumulation separately from file length.
Focused iteration is a proposed revision of `docs/TESTING.md:5-22`, which currently
requires running everything every time; implement that policy change explicitly
alongside the harness changes. Maintain the full `make check`/CI gate; a fast loop
is additional feedback, not a weaker definition of release readiness. Broader parallelism is not an
architectural cure for retained widgets, stale callbacks or fixture leakage.

Some runtime debugging cost is also synchronous I/O. `_show_git_state` invokes
`project_view.git_status` on the GUI path (`ui/main_window.py:2858-2866`);
`state/project_view.py:453-532` now reduces/caches Git calls, but still executes
them synchronously. Git init/backup handlers (`ui/main_window.py:2934-2975`) also
invoke command services synchronously. Moving those handlers alone changes no
latency. Route slow operations through an owned task runner with explicit pending,
result, error and cancellation handling. Verify thread safety before moving
calls; preserve command semantics and bounded shutdown.

Construction also starts runtime work (`ui/main_window.py:764-779,872-912`).
As feature owners emerge, separate constructing presentation from starting its
services, and let each owner stop its own timers, subscriptions and workers.
Keep the application-level quit safety net. Do not defer initial project/process
presentation indiscriminately: existing startup behavior depends on it.

## 5. Target dependency shape

This is a proposed direction, not code added by this audit:

```text
app/bootstrap -> resolved ProjectContext + runtime services
MainWindow    -> panels + small feature coordinators + top-level geometry
panels        -> view data, local widget state, intent signals
coordinators  -> explicit context, Qt-free decisions, existing services/workers
services      -> existing method adapters / files / subprocess / REW / MCP
decisions     -> values only; no QWidget, MainWindow or mutable global folder
QtUiBridge    -> cached publication and queued GUI delivery, as today
qt_shutdown   -> shared worker safety, as today
```

Do not pass the entire window into new feature modules; do not make a new
all-knowing AppController. A handful of cohesive features is enough. For example:
project loading/refresh, model controls, session lifecycle, and capture workflow.
Use ordinary constructors and a few typed interfaces/callbacks at actual external
boundaries; no dependency-injection container or framework is needed.

An eventual **800-1,500-line MainWindow** is a plausible design budget for
assembly, signal wiring, top-level events and geometry. It is not a measured
estimate or a required destination. Stop extracting when a cohesive component
has clear ownership and focused tests; several larger coherent modules are better
than dozens of tiny files that all require the same global context.

## 6. Implementation order and review gates

This extends existing work rather than opening a competing refactor program.
`docs/PLAN-AUDIT-2026-10.md:282-295` already defines G13's incremental decision
extractions; its G9 design at `:388-416` covers off-thread work, a FIFO write lane
and two-phase construction. Reconcile implementation tasks with those plans and
current code first. In particular, making journal writes asynchronous requires
preserving start/close ordering; an `INLINE` test mode would hide the concurrency
that needs testing. The estimates in that older plan are not new audit estimates.

No implementation is authorized by this report. The following is the suggested
order for a later development task; each step should be independently reviewable.

| Step | Deliverable | Evidence required before continuing |
|---|---|---|
| 1 | Short GUI ownership rule and reproducible baseline | Current serial timings, runtime window builds, import/fixture cost and loads/renders for representative paths; identical environment and cache conditions |
| 2 | Pure preset choice and reviewer-status pilots, with migrated tests | Equivalent behavior; tests do not import MainWindow or Qt; one wiring test per relevant integration |
| 3 | ProjectContext through one complete project-load/refresh path, then remaining callers | Cancelled switch stays on the original project; settings/writes target its directory; override/no-project/method-binding behavior preserved |
| 4 | ModelControls plus its controller | Add/change a model or status rule without changing main-window internals; standalone component/probe tests pass |
| 5 | Project presenter/sidebar and refresh coordinator | Deterministic panel application, watcher rearming, coalescing and manual-only probes retained; late answers rejected |
| 6 | Session transition policy and coordinator | Save/Discard/Cancel, fresh/restart, timeout/failure races, journal pairing and both quit routes retained |
| 7 | Capture workflow and remaining shell/language ownership | Pending intents survive widget rebuilds; control-layout reparenting, language, zoom and minimum-size behavior retained |

Start the fixture/discovery redesign alongside step 2; finish discovery changes
before relocating any tests. Carry component tests with each extraction rather
than scheduling one final “test cleanup” after the refactor.

For later implementation, focused tests support iteration, then run `make check`
and the existing platform CI before accepting the change. Session/context/layout
steps also need a live GUI pass: cancelling a project switch, saving then quitting,
changing a reviewer during a probe, and toggling control layout/language/zoom.
Do not combine ownership changes with a new shutdown strategy, domain schema,
AI route behavior or live project retargeting in the same step.

Measure outcomes with a small before/after record per pilot:

- Files and bytes actually needed to understand/change the feature, including its
  tests; actual model-input tokens if available. File bytes are not token counts.
- Focused feedback time, full serial check time and runtime window constructions.
- Number of reads/renders/commands per refresh scenario and stale results ignored.
- Whether a new decision can be tested without Qt and a UI change without a live
  network service, terminal or full MainWindow.
- Change isolation: a model/status change should stay within that feature and its
  contract; a cross-panel wiring change should still have integration coverage.

Do not promise a percentage speedup before measuring. A smaller main file with
unchanged imports, full-window tests and global state can cost just as much.

## 7. Avoid superficial reductions

- Do not split MainWindow into mixins, dynamically attached methods, or helpers
  taking `window`; shared private state and constructor-heavy tests remain.
- Do not remove comments/docstrings primarily to satisfy the LOC bound. Preserve
  safety invariants beside their owner and in tests; shorten or archive historical
  narrative only after those invariants have a clear home.
- Do not scatter constants and trivial functions into many one-function modules.
  Move a decision with its inputs, outputs, tests and relevant explanation.
- Do not introduce a second domain/availability/reviewer truth in a controller.
- Do not assume this report's older audit references still describe current bugs.
  W-8/W-9/W-10 already fixed or extracted parts of those findings; the current
  ratchet and manual-versus-agent refresh distinction are examples.

## 8. Audit verification and limits

The reviewed worktree started clean. Counts were obtained using `wc`, `rg`, and
`python3 -B` with only standard-library `ast`, `tokenize` and text reads, so no
Python bytecode/cache files were generated. The assignment count includes direct
`self.x` AST stores throughout MainWindow, including builder methods; it excludes
dynamic `setattr` assignments. The 207 construction sites reproduce the current
ratchet's top-level text-count method, with its limitations described above.

The report's source references, static counts and diff were checked. No new
runtime correctness, performance or test-pass claim is made. The potential
MonitorFeed scope defect requires a targeted reproduction during implementation.
No source, test, dependency, configuration, historical audit or roadmap file was
changed by this audit. Existing architecture decisions, plans and shutdown
experiments were treated as evidence, not permission to expand the task.

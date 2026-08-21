"""PLAN / MEASUREMENT mock data — ported verbatim from the prototype's `PLAN`/`MEAS` constants
(`data/private/prototype/tcc-main.html`).

No real backend yet (see the plan file's M4 scope) — this is a placeholder exactly like the
prototype's own mock data, not a stand-in the app pretends is real. Replacing it with the actual
project plan + the REW measurement-series check (the manual `/measurements` cross-reference done
earlier this session) is separate, later work.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Current-generation model display names for the AI main/critic header/footer pickers
# (main_window.py) and this mock dialog's own role labels -- one place to edit instead of a grep
# across the UI, since these go stale every few months as new models ship (user request
# 2026-07-28: Opus 4.8 was already superseded by Opus 5 by the time this was first wired up).
CURRENT_GENERATOR_MODEL = "Claude Opus 5"
AI_MAIN_MODELS = ["Claude Opus 5", "Claude Sonnet 5", "Claude Fable 5"]
AI_CRITIC_MODELS = ["Gemini 3.1 Pro", "Gemini 3.5 Flash", "Claude Opus 5"]

# Display name -> real Claude Agent SDK model id, for the one place today that actually threads a
# picked model into `ClaudeAgentOptions` (the DSP-profile onboarding interview, `new_project_dialog.py`
# -> `agent_session.OnboardingSession`) -- the footer's own AI-main picker above doesn't wire its
# selection through to `TuningSession` yet, a separate, pre-existing gap this doesn't fix.
AI_MODEL_IDS = {
    "Claude Opus 5": "claude-opus-5",
    "Claude Sonnet 5": "claude-sonnet-5",
    "Claude Fable 5": "claude-fable-5",
}


@dataclass(frozen=True)
class DialogMessage:
    who: str  # "gen" | "crit" | "user"
    role: str
    text: dict  # {"en": "...", "uk": "..."} — may contain <code> spans


DIALOG: tuple[DialogMessage, ...] = (
    DialogMessage(who="gen", role=f"Generator · {CURRENT_GENERATOR_MODEL}", text={
        "en": "Phase 2 (EQ), step 2.2. Proposing a left-lobe cut on <code>m_L</code>: "
              "<code>PK 1120 −2.5 Q2.2</code>. Hot L 990–1250 pulls the image left; this "
              "evens it out without shifting the pair's phase (9.8°→6.8°).",
        "uk": "Фаза 2 (EQ), крок 2.2. Пропоную на <code>m_L</code> зріз лівого лоба: "
              "<code>PK 1120 −2.5 Q2.2</code>. Гарячий L 990–1250 тягне образ вліво; "
              "вирівнює без зсуву фази пари (9.8°→6.8°).",
    }),
    DialogMessage(who="crit", role="Critic · Gemini", text={
        "en": "The \"175-stack destroys GD attack\" risk is ruled out by measurement. Gate "
              "fail-criterion: if #13/T8 \"bloats\" — revert. Recommendation: apply.",
        "uk": "Ризик «стек 175 руйнує GD-атаку» знято виміром. Фейл-критерій: якщо №13/T8 "
              "«розпухає» — відкат. Рекомендація: вводити.",
    }),
    DialogMessage(who="user", role="Arbiter · you", text={
        "en": "Applied. Captured <code>_32</code>. Punch intact, no diffuseness. Keeping it.",
        "uk": "Ввів. Зняв <code>_32</code>. Панч на місці, дифузності нема. Лишаємо.",
    }),
    DialogMessage(who="gen", role=f"Generator · {CURRENT_GENERATOR_MODEL}", text={
        "en": "Attested: lobe 990–1250 <code>+2.40 → −0.07</code>. Next step — the "
              "measurement task (panel on the right).",
        "uk": "Атестовано: лоб 990–1250 <code>+2.40 → −0.07</code>. Наступний крок — задача "
              "на замір (панель праворуч).",
    }),
)


@dataclass(frozen=True)
class PlanStep:
    id: str  # stable identity for completion/skip tracking (PlanProgress, plan_panel.py)
    name: dict
    tag: object = ""  # dict {"en","uk"} or "" — mirrors the prototype's tx()-able value
    tag_class: str = ""  # "ok" | "wait" | ""
    source: str = "skill"  # "skill" (base structure) | "project" (situational, inserted by user)
    skip: bool = False  # marked skipped -- still shown, dimmed, order preserved
    attempt: int = 1  # >1 renders an "attempt N" chip (a repeated step, "approach 2")


@dataclass(frozen=True)
class PlanPhase:
    status: str  # "done" | "cur" | "todo"
    name: dict
    steps: tuple[PlanStep, ...] = ()
    current: bool = False


PLAN: tuple[PlanPhase, ...] = (
    PlanPhase(status="done", current=False,
              name={"en": "Phase 0 · Intake + install", "uk": "Фаза 0 · Intake + інсталяція"},
              steps=(
                  PlanStep(id="0.1", tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "0.1 interview: equipment + goals",
                                 "uk": "0.1 інтерв'ю: обладнання + цілі"}),
                  PlanStep(id="0.2", tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "0.2 protective cuts before capture",
                                 "uk": "0.2 захисні зрізи перед замірами"}),
                  PlanStep(id="0.3", tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "0.3 mic calibration + loopback",
                                 "uk": "0.3 калібрування міка + loopback"}),
              )),
    PlanPhase(status="done", current=False,
              name={"en": "Phase 1 · Foundation (XO · TA · polarity)",
                    "uk": "Фаза 1 · Foundation (XO · TA · полярність)"},
              steps=(
                  PlanStep(id="1.1", tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "1.1 crossovers (acoustic onset)",
                                 "uk": "1.1 кросовери (акустичний онсет)"}),
                  PlanStep(id="1.2", tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "1.2 delays + coplanarity", "uk": "1.2 затримки + копланарність"}),
                  PlanStep(id="1.3", tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "1.3 phase coherence of junctions",
                                 "uk": "1.3 фазова когерентність стиків"}),
                  # Situational step, not from the skill's base structure -- inserted where it was
                  # actually needed in the tuning session (source="project", rendered in blue, per
                  # user request 2026-07-27 item 8).
                  PlanStep(id="1.4", source="project",
                           name={"en": "1.4 (project) B-pillar rattle fixed before TA pass",
                                 "uk": "1.4 (проєкт) усунуто дзвін у стійці B перед TA"}),
              )),
    PlanPhase(status="cur", current=True,
              name={"en": "Phase 2 · EQ + tonal balance", "uk": "Фаза 2 · EQ + тональний баланс"},
              steps=(
                  PlanStep(id="2.1", tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "2.1 per-driver EQ (v4.5)", "uk": "2.1 per-driver EQ (v4.5)"}),
                  PlanStep(id="2.2", tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "2.2 voicing (virtual FL/FR/sub)",
                                 "uk": "2.2 voicing (virtual FL/FR/sub)"}),
                  # attempt=2 -- this step was redone ("approach 2"): renders an "attempt 2" chip.
                  PlanStep(id="2.3", tag={"en": "in progress", "uk": "в роботі"}, tag_class="wait",
                           attempt=2,
                           name={"en": "2.3 target-match (SQ-Comp-Ref)",
                                 "uk": "2.3 target-match (SQ-Comp-Ref)"}),
                  # skip=True -- superseded by 2.3's second approach, kept visible but dimmed
                  # rather than deleted, so the attempt history stays legible.
                  PlanStep(id="2.3a", tag={"en": "needs v10", "uk": "чекає замір v10"},
                           tag_class="wait", skip=True,
                           name={"en": "2.4 cold L-lobes 700–880", "uk": "2.4 холодні L-лоби 700–880"}),
              )),
    PlanPhase(status="todo", current=False,
              name={"en": "Phase 3 · Imaging / staging", "uk": "Фаза 3 · Imaging / staging"},
              steps=(
                  PlanStep(id="3.1", name={"en": "3.1 center (RealCenter) + gain",
                                            "uk": "3.1 центр (RealCenter) + гейн"}),
                  PlanStep(id="3.2", name={"en": "3.2 TA-refine (height / depth)",
                                            "uk": "3.2 TA-refine (висота / глибина)"}),
              )),
    PlanPhase(status="todo", current=False,
              name={"en": "Phase 4 · Advisory / safety gates", "uk": "Фаза 4 · Advisory / safety-гейти"},
              steps=(
                  PlanStep(id="4.1", name={"en": "4.1 eq_gate (no boost below Fs)",
                                            "uk": "4.1 eq_gate (не бустити нижче Fs)"}),
                  PlanStep(id="4.2", name={"en": "4.2 attenuation-at-Fs", "uk": "4.2 attenuation-at-Fs"}),
              )),
    PlanPhase(status="todo", current=False,
              name={"en": "Phase 5 · Voicing / presets (SQ + FULL)",
                    "uk": "Фаза 5 · Voicing / пресети (SQ + FULL)"}, steps=()),
    PlanPhase(status="todo", current=False,
              name={"en": "Phase 6 · Verification + finish", "uk": "Фаза 6 · Верифікація + фінал"},
              steps=(
                  PlanStep(id="6.1", name={"en": "6.1 MMM + listening gates", "uk": "6.1 MMM + слухові гейти"}),
                  PlanStep(id="6.2", name={"en": "6.2 backup .pct6 + REW mdat", "uk": "6.2 бекап .pct6 + REW mdat"}),
              )),
)


@dataclass(frozen=True)
class MeasItem:
    name: str
    status: str  # "done" | "wait" | "bad"
    count: "int | None" = None
    # `extra`/`additional` (user request 2026-07-28): REW reads can turn up names with a
    # modifier/qualifier beyond the expected `<name> (<method>)` pattern, or graphs outside the
    # expected list entirely -- both are OK, not errors, just flagged blue in the UI rather than
    # silently matched or dropped. `extra` = the qualifier text (row is otherwise a normal
    # expected channel); `additional` = True means this whole row is outside the expected list.
    extra: "str | None" = None
    additional: bool = False


@dataclass(frozen=True)
class MeasGroup:
    type: str  # column header — a literal label, not translated in the prototype either
    items: tuple[MeasItem, ...]
    # Which capture method this column holds ("sw" / "rta"), when the builder knows. The panel
    # used to infer it from the column INDEX against a three-entry table, which is fine for the
    # mock's fixed three columns and wrong for anything else: phase 2's derived task has five
    # groups, and the fourth would have raised IndexError while rendering. None keeps the old
    # index convention, so the mock and its tests are unaffected.
    method: "str | None" = None


@dataclass(frozen=True)
class MeasTask:
    version: dict
    groups: tuple[MeasGroup, ...]


@dataclass(frozen=True)
class MeasSession(MeasTask):
    """One capture series, current or past (user request 2026-07-28: measurement history,
    scoped to the current preset -- a different preset's own history is a separate MEAS_SESSIONS
    concern, not modeled here since this whole module is mock data anyway). `id` is the stable key
    used for selection (measurement_panel.py) and plan-step linkage (`sessions_for_step` below,
    `ui/tcc/plan_panel.py`'s per-step measurement icon)."""

    id: str = ""
    # PlanStep ids (mock_data.PLAN) this session's captures were used for/informed -- the CURRENT
    # session's own entry is what it's *being captured for* right now, not yet "used" past tense.
    used_in_steps: tuple[str, ...] = ()


# Newest first -- MEAS_SESSIONS[0] is the live, in-progress capture task (what the Read/Scan/
# assign-names actions in measurement_panel.py always act on); older entries are read-only history
# a user can browse via the panel's session selector.
MEAS_SESSIONS: tuple[MeasSession, ...] = (
    MeasSession(
        id="v10",
        version={"en": "Series 10", "uk": "Зняти серію 10"},
        used_in_steps=("2.3",),
        groups=(
            MeasGroup(type="sw (LB)", items=(
                MeasItem("sw_10", "done", 2), MeasItem("w-L_10", "done", 2), MeasItem("w-R_10", "done", 3),
                MeasItem("m-L_10", "wait"), MeasItem("m-R_10", "bad", 1),
                MeasItem("tw-L_10", "wait"), MeasItem("tw-R_10", "wait"),
                MeasItem("c_10", "wait"), MeasItem("r-L_10", "wait"), MeasItem("r-R_10", "wait"),
            )),
            MeasGroup(type="RTA (MMM)", items=(
                MeasItem("sw_10", "wait"), MeasItem("w-L_10", "wait"), MeasItem("w-R_10", "wait"),
                MeasItem("m-L_10", "wait"), MeasItem("m-R_10", "wait"),
                MeasItem("tw-L_10", "wait"), MeasItem("tw-R_10", "wait"),
                MeasItem("c_10", "wait"), MeasItem("r-L_10", "wait"), MeasItem("r-R_10", "wait"),
            )),
            MeasGroup(type="RTA · group", items=(
                MeasItem("Ws_10", "wait"), MeasItem("Ms_10", "wait"), MeasItem("TWs_10", "wait"),
                MeasItem("SW+Ws_10", "wait"), MeasItem("L_10", "wait"), MeasItem("R_10", "wait"),
                MeasItem("ALL_10", "wait"), MeasItem("ALL+C_10", "wait"), MeasItem("ALL+C+Rs_10", "wait"),
            )),
        ),
    ),
    MeasSession(
        id="v9",
        version={"en": "Series 9 · voicing pass", "uk": "Серія 9 · voicing прохід"},
        used_in_steps=("2.2",),
        groups=(
            MeasGroup(type="sw (LB)", items=(
                MeasItem("sw_9", "done"), MeasItem("w-L_9", "done"), MeasItem("w-R_9", "done"),
                MeasItem("m-L_9", "done"), MeasItem("m-R_9", "done"),
                MeasItem("tw-L_9", "done"), MeasItem("tw-R_9", "done"),
                MeasItem("c_9", "done"), MeasItem("r-L_9", "done"), MeasItem("r-R_9", "done"),
            )),
            MeasGroup(type="RTA (MMM)", items=(
                MeasItem("sw_9", "done"), MeasItem("w-L_9", "done"), MeasItem("w-R_9", "done"),
                MeasItem("m-L_9", "done"), MeasItem("m-R_9", "done"),
                MeasItem("tw-L_9", "done"), MeasItem("tw-R_9", "done"),
                MeasItem("c_9", "done"), MeasItem("r-L_9", "done"), MeasItem("r-R_9", "done"),
            )),
            MeasGroup(type="RTA · group", items=(
                MeasItem("Ws_9", "done"), MeasItem("Ms_9", "done"), MeasItem("TWs_9", "done"),
                MeasItem("SW+Ws_9", "done"), MeasItem("L_9", "done"), MeasItem("R_9", "done"),
                MeasItem("ALL_9", "done"),
            )),
        ),
    ),
    MeasSession(
        id="v8",
        version={"en": "Series 8 · per-driver EQ pass", "uk": "Серія 8 · per-driver EQ прохід"},
        used_in_steps=("2.1",),
        groups=(
            MeasGroup(type="sw (LB)", items=(
                MeasItem("sw_8", "done"), MeasItem("w-L_8", "done"), MeasItem("w-R_8", "done"),
                MeasItem("m-L_8", "done"), MeasItem("m-R_8", "done"),
                MeasItem("tw-L_8", "done"), MeasItem("tw-R_8", "done"),
                MeasItem("c_8", "done"), MeasItem("r-L_8", "done"), MeasItem("r-R_8", "done"),
            )),
            MeasGroup(type="RTA (MMM)", items=(
                MeasItem("sw_8", "done"), MeasItem("w-L_8", "done"), MeasItem("w-R_8", "done"),
                MeasItem("m-L_8", "done"), MeasItem("m-R_8", "done"),
                MeasItem("tw-L_8", "done"), MeasItem("tw-R_8", "done"),
                MeasItem("c_8", "done"), MeasItem("r-L_8", "done"), MeasItem("r-R_8", "done"),
            )),
            MeasGroup(type="RTA · group", items=()),
        ),
    ),
)

# Back-compat alias -- the always-current/live session (existing code/tests that only knew a
# single MEAS keep working unchanged).
MEAS = MEAS_SESSIONS[0]


def sessions_for_step(step_id: str) -> tuple[MeasSession, ...]:
    """Every session (current or past) whose captures were used for/informed the given plan step
    -- newest first, same order as `MEAS_SESSIONS`. Empty = no measurement icon on that step's row
    (`ui/tcc/plan_panel.py`)."""
    return tuple(s for s in MEAS_SESSIONS if step_id in s.used_in_steps)

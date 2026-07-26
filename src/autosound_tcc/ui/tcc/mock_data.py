"""PLAN / MEASUREMENT mock data — ported verbatim from the prototype's `PLAN`/`MEAS` constants
(`data/private/prototype/tcc-main.html`).

No real backend yet (see the plan file's M4 scope) — this is a placeholder exactly like the
prototype's own mock data, not a stand-in the app pretends is real. Replacing it with the actual
project plan + the REW measurement-series check (the manual `/measurements` cross-reference done
earlier this session) is separate, later work.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlanStep:
    name: dict
    tag: object = ""  # dict {"en","uk"} or "" — mirrors the prototype's tx()-able value
    tag_class: str = ""  # "ok" | "wait" | ""


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
                  PlanStep(tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "0.1 interview: equipment + goals",
                                 "uk": "0.1 інтерв'ю: обладнання + цілі"}),
                  PlanStep(tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "0.2 protective cuts before capture",
                                 "uk": "0.2 захисні зрізи перед замірами"}),
                  PlanStep(tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "0.3 mic calibration + loopback",
                                 "uk": "0.3 калібрування міка + loopback"}),
              )),
    PlanPhase(status="done", current=False,
              name={"en": "Phase 1 · Foundation (XO · TA · polarity)",
                    "uk": "Фаза 1 · Foundation (XO · TA · полярність)"},
              steps=(
                  PlanStep(tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "1.1 crossovers (acoustic onset)",
                                 "uk": "1.1 кросовери (акустичний онсет)"}),
                  PlanStep(tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "1.2 delays + coplanarity", "uk": "1.2 затримки + копланарність"}),
                  PlanStep(tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "1.3 phase coherence of junctions",
                                 "uk": "1.3 фазова когерентність стиків"}),
              )),
    PlanPhase(status="cur", current=True,
              name={"en": "Phase 2 · EQ + tonal balance", "uk": "Фаза 2 · EQ + тональний баланс"},
              steps=(
                  PlanStep(tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "2.1 per-driver EQ (v4.5)", "uk": "2.1 per-driver EQ (v4.5)"}),
                  PlanStep(tag={"en": "ok", "uk": "ок"}, tag_class="ok",
                           name={"en": "2.2 voicing (virtual FL/FR/sub)",
                                 "uk": "2.2 voicing (virtual FL/FR/sub)"}),
                  PlanStep(tag={"en": "in progress", "uk": "в роботі"}, tag_class="wait",
                           name={"en": "2.3 target-match (SQ-Comp-Ref)",
                                 "uk": "2.3 target-match (SQ-Comp-Ref)"}),
                  PlanStep(tag={"en": "needs v10", "uk": "чекає замір v10"}, tag_class="wait",
                           name={"en": "2.4 cold L-lobes 700–880", "uk": "2.4 холодні L-лоби 700–880"}),
              )),
    PlanPhase(status="todo", current=False,
              name={"en": "Phase 3 · Imaging / staging", "uk": "Фаза 3 · Imaging / staging"},
              steps=(
                  PlanStep(name={"en": "3.1 center (RealCenter) + gain",
                                 "uk": "3.1 центр (RealCenter) + гейн"}),
                  PlanStep(name={"en": "3.2 TA-refine (height / depth)",
                                 "uk": "3.2 TA-refine (висота / глибина)"}),
              )),
    PlanPhase(status="todo", current=False,
              name={"en": "Phase 4 · Advisory / safety gates", "uk": "Фаза 4 · Advisory / safety-гейти"},
              steps=(
                  PlanStep(name={"en": "4.1 eq_gate (no boost below Fs)",
                                 "uk": "4.1 eq_gate (не бустити нижче Fs)"}),
                  PlanStep(name={"en": "4.2 attenuation-at-Fs", "uk": "4.2 attenuation-at-Fs"}),
              )),
    PlanPhase(status="todo", current=False,
              name={"en": "Phase 5 · Voicing / presets (SQ + FULL)",
                    "uk": "Фаза 5 · Voicing / пресети (SQ + FULL)"}, steps=()),
    PlanPhase(status="todo", current=False,
              name={"en": "Phase 6 · Verification + finish", "uk": "Фаза 6 · Верифікація + фінал"},
              steps=(
                  PlanStep(name={"en": "6.1 MMM + listening gates", "uk": "6.1 MMM + слухові гейти"}),
                  PlanStep(name={"en": "6.2 backup .pct6 + REW mdat", "uk": "6.2 бекап .pct6 + REW mdat"}),
              )),
)


@dataclass(frozen=True)
class MeasItem:
    name: str
    status: str  # "done" | "wait" | "bad"
    count: "int | None" = None


@dataclass(frozen=True)
class MeasGroup:
    type: str  # column header — a literal label, not translated in the prototype either
    items: tuple[MeasItem, ...]


@dataclass(frozen=True)
class MeasTask:
    version: dict
    groups: tuple[MeasGroup, ...]


MEAS = MeasTask(
    version={"en": "Capture series v10 · test capture", "uk": "Зняти серію v10 · тестове зняття"},
    groups=(
        MeasGroup(type="sw (LB)", items=(
            MeasItem("sub_10", "done", 2), MeasItem("w-L_10", "done", 2), MeasItem("w-R_10", "done", 3),
            MeasItem("m-L_10", "wait"), MeasItem("m-R_10", "bad", 1),
            MeasItem("tw-L_10", "wait"), MeasItem("tw-R_10", "wait"),
            MeasItem("c_10", "wait"), MeasItem("r-L_10", "wait"), MeasItem("r-R_10", "wait"),
        )),
        MeasGroup(type="RTA (MMM)", items=(
            MeasItem("sub_10", "wait"), MeasItem("w-L_10", "wait"), MeasItem("w-R_10", "wait"),
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
)

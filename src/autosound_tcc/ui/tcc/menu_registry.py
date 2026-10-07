"""The main menu as data: every line of the window's ☰ menu, in order (G13 A1, #161).

A line is a `MenuEntry`: where it sits (`place`: a section of `SECTIONS`, or a submenu's id), what
it says (an i18n key, or a literal label such as an EQ order), and what it does — `on(host)`, a
call on the window looked up when the line is pressed, so a test that patches a window method still
wins, or `url()`, a page opened in the browser. A handler gets the host and nothing else: Qt's
`checked` flag never reaches it.

A feature adds its lines without touching the window: its module is named in `PROVIDERS`, its
`menu_entries()` returns them, and `before=` / `after=` another line's id puts each one where it
belongs. `main_menu.py` draws the tree; this module imports no Qt. A provider that fails is logged
and left out, so one bad feature cannot stop the window from opening; `problems()` names what
would draw wrong, and the renderer logs it on every render.

The order is the order of a working day, not an alphabet: which project · what the session is
doing · the tools beside the work · where to ask for help. Frequently-used items keep their own
buttons in the chrome as well -- a menu that is the only way to reach a thing you press ten times
an hour is not a kindness.
"""

from __future__ import annotations

import importlib
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Optional

from autosound_tcc.core import app_log, guide
from autosound_tcc.core.shell_gate import GATE_AUTO, GATE_FOREIGN, GATE_NEVER, GATE_WRITES
from autosound_tcc.ui.tcc import i18n


@dataclass(frozen=True)
class MenuEntry:
    """One line of the menu, or a submenu's title (`submenu=True`, its lines placed under its id)."""

    id: str
    place: str
    label_key: str = ""
    label: str = ""
    tip_key: str = ""
    prefix: str = ""  # "⚙ ", "📖 "…
    on: Optional[Callable[[Any], None]] = None
    url: Optional[Callable[[], str]] = None
    enabled: Optional[Callable[[Any], bool]] = None
    checked: Optional[Callable[[Any], bool]] = None  # set → the line is checkable
    submenu: bool = False
    bold: bool = False
    before: str = ""
    after: str = ""
    alias: str = ""  # the window attribute the tests drive this line by
    alias_key: str = ""  # set → that attribute is a dict, and this line its entry

    def text(self) -> str:
        """What the line says, in the current language."""
        return self.prefix + (i18n.t(self.label_key) if self.label_key else self.label)

    def tip(self) -> str:
        return i18n.t(self.tip_key) if self.tip_key else ""


#: The sections, top to bottom: (place, heading key).
SECTIONS: tuple[tuple[str, str], ...] = (("project", "menuProject"), ("session", "menuSession"),
                                         ("tools", "menuTools"), ("help", "menuHelp"))

#: Modules whose `menu_entries()` adds lines; read when `collect()` runs.
PROVIDERS: tuple[str, ...] = ()

#: The window attributes tests drive lines by — closed at these five (G13, #161).
WINDOW_ALIASES = frozenset({"_intake_action", "_reload_action", "_import_action",
                            "_gate_actions", "_eq_order_actions"})

# Support links (user request 2026-07-28), same two channels + wording as the skill's own
# README (all locales) -- GitHub Sponsors first (no fees, familiar to devs with an account),
# Monobank jar as the no-account fallback (one tap, Apple Pay/Google Pay/card).
SPONSORS_URL = "https://github.com/sponsors/ayukhno?frequency=one-time"
MONOBANK_URL = "https://send.monobank.ua/jar/8wThVcodjm"


def _session_running(host) -> bool:
    """Saving the state and a fresh session need a session to act on. Read straight: a renamed
    attribute fails loudly (`MainMenu.sync` logs it) instead of greying both lines for good."""
    return host._agent_worker is not None


def _eq_orders() -> list[MenuEntry]:
    """The EQ card's Freq / Gain / Q order: the processor's own by default, or fixed by the
    Arbiter (finding 70, tcc#67 — finding 68 built only the vendor's rule). Per machine: it is
    how this person reads a card, not a fact about the car."""
    return [MenuEntry(f"eq_{pref}", "eq_order", label_key=key, label=label,
                      on=lambda w, p=pref: w._set_eq_order_pref(p),
                      checked=lambda w, p=pref: w._eq_order_pref() == p,
                      alias="_eq_order_actions", alias_key=pref)
            for pref, key, label in (("auto", "eqOrderAuto", ""),
                                     ("gain_first", "", "Freq · Gain · Q"),
                                     ("q_first", "", "Freq · Q · Gain"))]


def _gates() -> list[MenuEntry]:
    # The fourth, `never`, is the Arbiter's own (2026-10-01, tcc#115): it lifts what `auto`
    # still asks about, and its tooltip names what that lets through.
    return [MenuEntry(f"gate_{mode}", "gate", label_key=key, tip_key=tip,
                      on=lambda w, m=mode: w._set_gate_mode(m),
                      checked=lambda w, m=mode: w._effective_gate() == m,
                      alias="_gate_actions", alias_key=mode)
            for mode, key, tip in ((GATE_WRITES, "gateWrites", "gateModeTip"),
                                   (GATE_FOREIGN, "gateForeign", "gateModeTip"),
                                   (GATE_AUTO, "gateAuto", "gateAutoTip"),
                                   (GATE_NEVER, "gateNever", "gateNeverTip"))]


def _languages() -> list[MenuEntry]:
    return [MenuEntry(f"lang_{code}", "language", label_key=key,
                      on=lambda w, c=code: w._on_language_selected(c),
                      checked=lambda _w, c=code: i18n.current_language() == c)
            for code, key, _badge in i18n.LANGS]


def _guides() -> list[MenuEntry]:
    # Online, at this build's own tag: `docs/` is not in the installed package, and a link to
    # `main` would show the screens of another version (tcc #49, hub #202 SKL-053).
    return [MenuEntry(f"guide_{name}", "guides", label_key=key, tip_key=tip,
                      url=lambda p=page: guide.installed_guide_url(p))
            for name, key, tip, page in (
                ("quick", "menuGuideQuick", "menuGuideQuickTip", guide.QUICK_GUIDE),
                ("full", "menuGuideFull", "menuGuideFullTip", guide.REFERENCE),
                ("curve", "menuGuideCurve", "menuGuideCurveTip", guide.HOUSE_CURVE))]


def window_entries() -> list[MenuEntry]:
    """Everything the window can do, line by line, in the order the menu shows it."""
    return [
        MenuEntry("open_project", "project", label_key="projectOpen", tip_key="projectOpenTip",
                  on=lambda w: w._choose_project_folder()),
        MenuEntry("new_project", "project", label_key="projectNew", tip_key="projectNewTip",
                  on=lambda w: w._open_new_project_dialog()),
        # Its own line, because it is a different intent from "new project", not a different
        # button for it: this one starts from a car that is already described (user, 2026-08-23
        # -- "call it 'copy the car' and say in the hint that it is the car, the equipment and the
        # installation"). It opens the same dialog with the copying already chosen.
        MenuEntry("copy_car", "project", label_key="menuCopyCar", tip_key="menuCopyCarTip",
                  on=lambda w: w._open_new_project_dialog(seed=True)),
        # The intake is the skill's own form, served and opened in the browser (hub #194): one
        # form for every front end, so TCC starts it and never draws its own copy of it.
        MenuEntry("intake", "project", label_key="menuIntake", tip_key="menuIntakeTip",
                  on=lambda w: w._open_intake_form(), alias="_intake_action"),
        MenuEntry("reload", "project", label_key="menuReload", tip_key="refreshProjectTip",
                  on=lambda w: w._on_reload_pressed(), alias="_reload_action"),
        # Menu wording, not the buttons': "▶ Session in TCC" and "⧉ Terminal" are labels for
        # things you can SEE, sized to a footer. A menu line has room to say what it does.
        MenuEntry("start_session", "session", label_key="menuStartSession",
                  on=lambda w: w._start_tuning_session()),
        MenuEntry("terminal", "session", label_key="menuTerminal", on=lambda w: w._open_terminal()),
        MenuEntry("save_state", "session", label_key="projectSaveState",
                  tip_key="projectSaveStateTip", on=lambda w: w._save_project_state(),
                  enabled=_session_running),
        MenuEntry("fresh_session", "session", label_key="projectFreshSession",
                  tip_key="projectFreshSessionTip", on=lambda w: w._start_fresh_session(),
                  enabled=_session_running),
        MenuEntry("diagnostics", "tools", label_key="menuDiagnostics", tip_key="diagBtnTip",
                  on=lambda w: w._open_diagnostics()),
        # In TOOLS, not in project (user, 2026-08-23): "it does not import a session, it takes
        # the settings -- crossovers, delays, EQ". Nothing about a project changes here: a file is
        # read, every value is checked against the processor, and the answer is a report. That is
        # a tool, beside diagnostics and the target-curve tool.
        MenuEntry("import", "tools", label_key="riImport", tip_key="riImportTip",
                  on=lambda w: w._open_resonalyze_import(), alias="_import_action"),
        MenuEntry("target_tool", "tools", label_key="menuTargetTool", tip_key="targetToolTip",
                  on=lambda w: w._open_target_curve_tool()),
        # «Налаштування»: every technical setting of TCC in one place (finding 70, tcc#67). The
        # last line of TOOLS (the Arbiter, 2026-09-27); bold, so it reads as a submenu (finding
        # 91, tcc#81).
        MenuEntry("settings", "tools", label_key="menuSettings", prefix="⚙ ", submenu=True,
                  bold=True),
        MenuEntry("eq_order", "settings", label_key="eqOrderMenu", submenu=True),
        *_eq_orders(),
        MenuEntry("models", "settings", label_key="menuModels", tip_key="menuModelsTip",
                  on=lambda w: w._open_model_config()),
        MenuEntry("reviewer_key", "settings", label_key="menuReviewerKey",
                  tip_key="menuReviewerKeyTip", on=lambda w: w._open_reviewer_key()),
        MenuEntry("gate", "settings", label_key="gateMode", submenu=True),
        *_gates(),
        MenuEntry("theme", "settings", label_key="menuTheme", prefix="◐ ",
                  on=lambda w: w._toggle_theme()),
        MenuEntry("language", "settings", label_key="menuLanguage", submenu=True),
        *_languages(),
        MenuEntry("zoom_in", "settings", label_key="menuZoomIn", on=lambda w: w._zoom_in()),
        MenuEntry("zoom_out", "settings", label_key="menuZoomOut", on=lambda w: w._zoom_out()),
        # The three pages in one submenu, bold like «Налаштування» (the Arbiter, finding 134,
        # tcc#120: «підменю (жирним), в середині квік-гайд, фул-гайд і цільова крива гайд»).
        MenuEntry("guides", "help", label_key="menuGuides", prefix="📖 ", submenu=True, bold=True),
        *_guides(),
        MenuEntry("feedback", "help", label_key="fbBig", prefix="💬 ", tip_key="fbBigTip",
                  on=lambda w: w._open_feedback()),
        # The same two channels, and the same wording, as the method's own README. Not a choice
        # TCC makes on the user's behalf.
        MenuEntry("support_github", "help", label_key="supportGithub", url=lambda: SPONSORS_URL),
        MenuEntry("support_monobank", "help", label_key="supportMonobank",
                  url=lambda: MONOBANK_URL),
    ]


def collect() -> list[MenuEntry]:
    """The window's lines, then every provider's, in `PROVIDERS` order."""
    entries = window_entries()
    for name in PROVIDERS:
        try:
            entries.extend(importlib.import_module(name).menu_entries())
        except Exception:  # noqa: BLE001 — one bad feature must not stop the window opening
            app_log.logger().exception("main menu: the lines of %s are left out", name)
    return entries


def ordered(entries, place: str) -> list[MenuEntry]:
    """The lines of one place: registration order, then each anchored line beside its neighbour.
    An anchor that names no line here puts its line last (`problems` names it)."""
    here = [e for e in entries if e.place == place]
    out = [e for e in here if not (e.before or e.after)]
    pending = [e for e in here if e.before or e.after]
    while pending:
        left = []
        for entry in pending:
            ids = [e.id for e in out]
            anchor = entry.before or entry.after
            if anchor in ids:
                at = ids.index(anchor)
                out.insert(at if entry.before else at + 1, entry)
            else:
                left.append(entry)
        if len(left) == len(pending):  # anchors to nothing placed: last, in their own order
            out.extend(left)
            break
        pending = left
    return out


def problems(entries, known_keys) -> list[str]:
    """What is wrong with a set of lines, one sentence each; [] when nothing is."""
    found = []
    counts = Counter(e.id for e in entries)
    found += [f"{entry_id!r}: the id is used {n} times" for entry_id, n in counts.items() if n > 1]
    sections = {section for section, _key in SECTIONS}
    submenus = {e.id for e in entries if e.submenu}
    reachable = set(sections)
    grown = True
    while grown:  # a submenu is drawn only inside a place that is drawn
        more = {e.id for e in entries if e.submenu and e.place in reachable} - reachable
        reachable |= more
        grown = bool(more)
    found += [f"section heading key {key!r} is not in the strings"
              for _section, key in SECTIONS if key not in known_keys]
    for entry in entries:
        if entry.place not in sections | submenus:
            found.append(f"{entry.id!r}: no section or submenu is called {entry.place!r}")
        elif entry.place not in reachable:
            found.append(f"{entry.id!r}: its place {entry.place!r} is not reached from any section")
        if entry.submenu and entry.id in sections:
            found.append(f"{entry.id!r}: a submenu may not be named like a section")
        if entry.alias and entry.alias not in WINDOW_ALIASES:
            found.append(f"{entry.id!r}: the alias {entry.alias!r} is not one of the window's five")
        if entry.alias_key and not entry.alias:
            found.append(f"{entry.id!r}: an alias_key without an alias")
        if entry.before and entry.after:
            found.append(f"{entry.id!r}: both before= and after= are set")
        for anchor in (entry.before, entry.after):
            if anchor and not any(e.id == anchor and e.place == entry.place for e in entries):
                found.append(f"{entry.id!r}: its anchor {anchor!r} is not a line of {entry.place!r}")
        for key in (entry.label_key, entry.tip_key):
            if key and key not in known_keys:
                found.append(f"{entry.id!r}: the key {key!r} is not in the strings")
        if not (entry.label_key or entry.label):
            found.append(f"{entry.id!r}: the line says nothing")
        if not (entry.on or entry.url or entry.submenu):
            found.append(f"{entry.id!r}: the line does nothing (no on, url or submenu)")
    return found

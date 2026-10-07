"""The main menu as it is drawn today, line by line — the pin the menu registry must keep (G13, #161).

Written down before the window's menu moved into `menu_registry` (Task 13), so the move is checked
against what the user saw, not against itself. A row is `(depth, kind, text, tip, checkable, bold)`:
`kind` is "heading", "line", "menu" (a submenu's title) or "sep"; text and tip in the current
language, the tip "" for a line that has none.
"""

from __future__ import annotations

from autosound_tcc.ui.tcc import i18n

SEP = (0, "sep", "", "", False, False)


def pinned_rows() -> list[tuple]:
    t = i18n.t

    def heading(key):
        return (0, "heading", t(key).upper(), "", False, False)

    def line(depth, text, tip_key="", checkable=False):
        return (depth, "line", text, t(tip_key) if tip_key else "", checkable, False)

    def menu(depth, text, bold=False):
        return (depth, "menu", text, "", False, bold)

    return [
        heading("menuProject"),
        line(0, t("projectOpen"), "projectOpenTip"),
        line(0, t("projectNew"), "projectNewTip"),
        line(0, t("menuCopyCar"), "menuCopyCarTip"),
        line(0, t("menuIntake"), "menuIntakeTip"),
        line(0, t("menuReload"), "refreshProjectTip"),
        SEP,
        heading("menuSession"),
        line(0, t("menuStartSession")),
        line(0, t("menuTerminal")),
        line(0, t("projectSaveState"), "projectSaveStateTip"),
        line(0, t("projectFreshSession"), "projectFreshSessionTip"),
        SEP,
        heading("menuTools"),
        line(0, t("menuDiagnostics"), "diagBtnTip"),
        line(0, t("riImport"), "riImportTip"),
        line(0, t("menuTargetTool"), "targetToolTip"),
        menu(0, "⚙ " + t("menuSettings"), bold=True),
        menu(1, t("eqOrderMenu")),
        line(2, t("eqOrderAuto"), checkable=True),
        line(2, "Freq · Gain · Q", checkable=True),
        line(2, "Freq · Q · Gain", checkable=True),
        line(1, t("menuModels"), "menuModelsTip"),
        line(1, t("menuReviewerKey"), "menuReviewerKeyTip"),
        menu(1, t("gateMode")),
        line(2, t("gateWrites"), "gateModeTip", checkable=True),
        line(2, t("gateForeign"), "gateModeTip", checkable=True),
        line(2, t("gateAuto"), "gateAutoTip", checkable=True),
        line(2, t("gateNever"), "gateNeverTip", checkable=True),
        line(1, "◐ " + t("menuTheme")),
        menu(1, t("menuLanguage")),
        *[line(2, t(key), checkable=True) for _code, key, _badge in i18n.LANGS],
        line(1, t("menuZoomIn")),
        line(1, t("menuZoomOut")),
        SEP,
        heading("menuHelp"),
        menu(0, "📖 " + t("menuGuides"), bold=True),
        line(1, t("menuGuideQuick"), "menuGuideQuickTip"),
        line(1, t("menuGuideFull"), "menuGuideFullTip"),
        line(1, t("menuGuideCurve"), "menuGuideCurveTip"),
        line(0, "💬 " + t("fbBig"), "fbBigTip"),
        line(0, t("supportGithub")),
        line(0, t("supportMonobank")),
    ]


def rows_of(menu, depth: int = 0) -> list[tuple]:
    """The drawn tree of a QMenu, in `pinned_rows()`'s shape. A heading is a disabled line in
    capitals (`_menu_section`); a tip equal to the text is Qt's default, so no tip."""
    rows = []
    for action in menu.actions():
        if action.isSeparator():
            rows.append((depth, "sep", "", "", False, False))
            continue
        text = action.text()
        tip = action.toolTip() if action.toolTip() != text else ""
        if action.menu() is not None:
            rows.append((depth, "menu", text, tip, False, action.font().bold()))
            rows.extend(rows_of(action.menu(), depth + 1))
            continue
        heading = not action.isEnabled() and not action.isCheckable() and text == text.upper()
        rows.append((depth, "heading" if heading else "line", text, tip, action.isCheckable(),
                     action.font().bold()))
    return rows

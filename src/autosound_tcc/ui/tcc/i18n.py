"""EN/UK strings — ported from the web prototype's `T = {en, uk}` table
(`data/private/prototype/tcc-main.html`). Keys are kept identical to the prototype's so later
milestones can copy more entries in verbatim instead of re-naming anything.

Every user-facing string in the app should go through `t()`/`tx()`, and every widget that
displays translated text registers a retranslate callback via `on_language_changed()` so
`set_language()` can repaint the whole UI in place — mirrors the prototype's `setLang()`.
"""

from __future__ import annotations

from typing import Callable

Lang = str  # "en" | "uk"

T: dict[Lang, dict[str, str]] = {
    "en": {
        "theme": "theme",
        "dspPanel": "DSP",
        "projectParams": "Project params",
        "systemParams": "System params",
        "audioAnalysis": "Car audio analysis",
        "noDataYet": "No data yet",
        "rewPort": "REW port",
        "preset": "Preset",
        "target": "Target curve",
        "targetToolTip": "Open in the target-curve tool ↗",
        "rewOnline": "REW: offline",
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
        "pillMute": "MUTE",
        "pillOff": "OFF",
        "attempt": "attempt",
        "addStep": "+ add step",
        "addStepPrompt": "Situational step (this project only):",
        "measRead": "Read",
        "measReading": "Reading from REW…",
        "measReadOk": "Read: {title} ({n} pts)",
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
        "aiMain": "AI main",
        "aiCritic": "AI critic",
        "note": "prototype · real data (sound_AutoSci) · tuning the form",
        "coffeeBtn": "☕ Buy me a coffee",
        "supportGithub": "💜 GitHub Sponsors",
        "supportMonobank": "☕ Monobank jar",
        "fbBig": "Give feedback",
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
        "composer": "Message the Generator…  (prototype — doesn't send)",
        "send": "Send",
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
        "systemParams": "Параметри системи",
        "audioAnalysis": "Аудіо аналіз авто",
        "noDataYet": "Даних поки нема",
        "rewPort": "Порт REW",
        "preset": "Пресет",
        "target": "Цільова крива",
        "targetToolTip": "Відкрити в інструменті цільових кривих ↗",
        "rewOnline": "REW: офлайн",
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
        "pillMute": "MUTE",
        "pillOff": "OFF",
        "attempt": "спроба",
        "addStep": "+ додати крок",
        "addStepPrompt": "Ситуативний крок (тільки цей проєкт):",
        "measRead": "Прочитати",
        "measReading": "Читаю з REW…",
        "measReadOk": "Прочитано: {title} ({n} точок)",
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
        "aiMain": "ШІ main",
        "aiCritic": "ШІ critic",
        "note": "прототип · реальні дані (sound_AutoSci) · крутимо форму",
        "coffeeBtn": "☕ Пригостити кавою",
        "supportGithub": "💜 GitHub Sponsors",
        "supportMonobank": "☕ Банка на Monobank",
        "fbBig": "Залишити відгук",
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
        "composer": "Написати Генератору…  (прототип — не відправляє)",
        "send": "Надіслати",
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
    "retranslate myself" method). Mirrors the prototype re-rendering `[data-i]` elements."""
    _listeners.append(callback)


def set_language(lang: Lang) -> None:
    global _lang
    if lang not in T:
        raise ValueError(f"unknown language {lang!r}, known: {sorted(T)}")
    _lang = lang
    for callback in list(_listeners):
        callback()

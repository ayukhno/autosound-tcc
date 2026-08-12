# Інвентар моделі даних — фактичний стан на 2026-07-31

> Вхідні дані для сесії з проектування моделі даних. **Тут тільки факти**: що існує,
> де лежить, у якому форматі, хто пише, хто читає. Рішень тут нема — вони йдуть у
> `SKILL-CHANGE-REQUESTS.md` і `TCC-TZ.md`.
>
> Зібрано з робочих копій: скіл — гілка `feat/tcc-sync-p0` (worktree
> `~/dev/Claude/autosound-skill-bridge`), TCC — `feat/installer` + звірка з
> `feat/tcc-sync-p0`, дослідницький репо — `~/dev/Claude/sound_AutoSci`.

---

## Принцип, який треба закріпити

**Структуру знає скіл. TCC уміє читати.**

Для шарів 2 і 3 це вже так. Для шару 1 — **навпаки**, і саме тому він розсипався
(§1.4).

---

## Шар 1 — знання про МОДЕЛЬ DSP

Що вміє процесор як виріб. Не залежить від машини й від налаштувань.

### 1.1 Схема і код — у скілі

`rew_tool/dsp_profile.py`. Власна документація файла формулює межу точно:

> *"DSP processor capability profile — what a DSP MODEL can do, not what one project set it to."*
> *"A profile is the DSP MODEL's facts, not one car's install — no personal data, safe to contribute."*

Ключове рішення схеми — **`groups` замість фіксованих ярусів**:

> *"an ordered list of the tiers/categories this DSP model actually exposes … A consumer renders
> whatever groups+fields are declared — it never assumes a fixed two-tier shape. Absence of a group
> means the DSP genuinely doesn't have that tier (e.g. MUSWAY has no virtual_channels group at all)."*

Обов'язкові поля: `TOP_REQUIRED = ("name", "vendor", "groups")`,
`GROUP_REQUIRED = ("id", "label", "fields")`.

API: `validate_profile` · `load_profile` · `save_profile` · `find_bundled(vendor, model, bundled_dir)`
· `open_questions` · `diff_profile` · `content_hash` · `_musway_stub` · `_selftest`.

Дві конвенції, що вже працюють:
- **непідтверджений факт = `null`, не відсутній ключ.** `open_questions()` обходить структуру і
  збирає всі `null` — тому побудова профілю інкрементальна: повторний прохід питає лише про те, що
  ще не заповнене.
- **JSON, не YAML** — модуль лишається stdlib-only, у тій самій серіалізаційній родині, що
  `state.py` і `rew_api.py`.

### 1.2 Дані — НЕ в скілі

**Скіл не постачає жодного машинного профілю.** Пошук `*.json` під `dsp*` у скілі — порожньо.

Профілі лежать у трьох інших місцях:

| Місце | Файли | Формат | Схема |
| :-- | :-- | :-- | :-- |
| TCC `data/dsp_profiles/` | `helix-dsp-ultra-s.json` | JSON | `dsp_profile:` обгортка, ключі `name, vendor, sources, sample_rate_hz, groups, parametric_eq, phase_control, polarity, delay, features, _open_questions` |
| `sound_AutoSci/dsp_profiles/` | `helix-dsp-ultra-s.yaml`, `musway-m6v4.yaml` | YAML | та сама обгортка `dsp_profile:` |
| проект користувача | `dsp_profile.json` поруч із ledger | JSON | та сама |

JSON і YAML — **та сама схема**, різна серіалізація; `dsp_profile.py:36 _unwrap()` знімає обгортку.
`musway-m6v4` існує лише в YAML, у TCC його нема.

### 1.3 Знання для ШІ — окремий артефакт, з перекриттям

`knowledge/dsp/helix-dsp-ultra-s.md` — щільна таблиця «питання → відповідь» із верифікацією,
посиланнями і попередженнями. Це **інший клас артефакту**: як з цим DSP працювати, а не яка в нього
схема.

Але частина змісту — машинні факти в прозі, ті самі, що в `groups`:

```
EQ 30 смуг/канал, типи PK / LS_Q / HS_Q + AP1/AP2
кросовери BE/BW 6-42 dB/oct; LR 12/24/36 (макс 36)
затримка до 20.82 ms, на обох ярусах, СУМУЮТЬСЯ
рідна частота 96 kHz
```

Той самий файл документує **дві власні помилки**, знайдені постфактум:

> *"a virtual sub channel exists, user-verified 2026-07; an earlier 'no virtual sub' note was wrong"*
> *"an earlier 'LR2-8' note was wrong; user-verified in PC-Tool 2026-07-13"*

Тобто дублювання «проза ↔ JSON» уже дрейфувало, і виправлення прилітали з поля.

### 1.4 Інверсія володіння

```
скіл   визначає СХЕМУ (dsp_profile.py) + прозові знання (knowledge/dsp/*.md)
TCC    зберігає ДАНІ (data/dsp_profiles/*.json)
       і передає свою теку в скіловий find_bundled():
         config.py:30  DEFAULT_BUNDLED_PROFILES_DIR = _REPO_ROOT/"data"/"dsp_profiles"
         agent_session.py:195 / mcp_server.py:285
           dsp_profile.find_bundled(vendor, model, config.bundled_profiles_dir())
```

Скіл володіє формою, але не змістом. TCC тримає зміст, якого без нього нема.

---

## Шар 2 — статика проекту

Конкретна машина: що встановлено, як скомутовано, який канал для чого. Змінюється рідко.

**Артефакт:** `project.json`. Схема — `rew_tool/project-schema.md`, код — `rew_tool/project.py`.

Блоки: `car` · `source` · `dsp` · `amps` · `mic` · `paths` · `presets` · `channels[]` ·
`hardware.controls` · `glossary` · `param_sections` · `channel_summary` · `_open_questions` ·
`sources`.

**Провенанс на рівні факту** — `fact(value, source, at)`:

```jsonc
"fs_hz": {"value": 62, "source": "datasheet", "at": "…"}
```

`source ∈ user | measured | datasheet`. `_open_questions` — дотовані шляхи незаповнених фактів.
`config_change(..., why=…, source=…, impact="remeasure: [w-L, w-R]")` — подія зміни конфігурації;
`impact` — машинна форма таблиці «що з сирих даних виживає» з `naming-and-structure.md §2`.

**Читає TCC:** `state/project_view.py` (109 рядків, на `feat/tcc-sync-p0`) —
`load_system_params`, `load_channel_summary`, `load_open_questions`.
`state/measurement_view.py:40` — `glossary` з `project.json`.
**`channels[]` не читає ніхто.**

---

## Шар 3 — конфігурації

Налаштування під конкретну конфігурацію: кросовери, EQ, затримки, полярність, цільова крива.

**Артефакт:** `presets/<preset>/state/v_NNN.json`. Схема — `rew_tool/state/schema.md`,
код — `rew_tool/state/state.py`, міграція — `state/migrate_v2.py`.

`schema_version: 2`. Верхній рівень: `preset` · `sample_rate` · `version` · `note` · `target` ·
`slot_label` · `save` · `features`. Рядок каналу: `slot` · `descr` · `role` · `order` · `tag` /
`tag_value` · `mute` / `off` / `hidden` · `phase_deg` · `gain_db` · `ta_ms` · `polarity` · hp/lp ·
`eq[]` (структуровані смуги) · `eq_ptr` · `status ∈ proposed | applied | measured`.

`h.snapshot(state, note=…)` → `v_00N`: валідує, просуває HEAD, штампує `schema_version`.

**Читає TCC:** `state/dsp_state.py` — `GroupRow`, `parse_eq_bands`, поля вище.

---

## Шар 3б — стан процесу

**Артефакт:** `process/process-state.json` + `process/journal.jsonl` (append-only).
Схема — `state/process-schema.md`, код — `state/process.py`. **Уже на `main`.**

**Читає TCC:** `state/process_view.py`.
⚠️ **Другий писач:** TCC-MCP-тул `report_phase` пише фазу у власний session registry паралельно зі
скілом (зафіксовано в нотатках автора як ризик розбіжності).

---

## Як TCC споживає скіл

`core/vendor_loader.py` — вантажить файли скіла по явному шляху під синтетичними іменами, щоб не
класти `state`, `analysis` у глобальний import path (колізія з `autosound_tcc.state`):

```
rew_api.py      → autosound_tcc._vendor.rew_api
state/state.py  → autosound_tcc._vendor.dsp_state
state/process.py→ autosound_tcc._vendor.process
project.py      → autosound_tcc._vendor.project
```

Джерело — submodule `vendor/autosound-tuning-skill/skills/autosound-tuning/rew_tool`.

---

## Зведення: хто пише, хто читає

| Шар | Артефакт | Схему визначає | Дані пише | Читає |
| :-- | :-- | :-- | :-- | :-- |
| 1 | `dsp_profile.json` | скіл (`dsp_profile.py`) | **TCC + sound_AutoSci** | TCC, скіл |
| 1б | `knowledge/dsp/*.md` | скіл | скіл (людина/ШІ) | ШІ |
| 2 | `project.json` | скіл (`project-schema.md`) | скіл (`project.py`) | TCC (частково) |
| 3 | `presets/*/state/v_NNN.json` | скіл (`schema.md`) | скіл (`state.py`) | TCC |
| 3б | `process/*` | скіл (`process-schema.md`) | скіл + **TCC** | TCC |

Два рядки випадають із принципу «структуру знає скіл, TCC читає»: **шар 1** (дані живуть у
споживача) і **шар 3б** (два писачі).

---

## Відомі розходження — вхід у сесію

1. **Шар 1: чотири домівки, дві серіалізації, нуль профілів у власника схеми.** SCR-010.
2. **Шар 1 vs 1б: ті самі числа в JSON і в прозі**, з підтвердженою історією дрейфу (§1.3).
3. **`channels[]` ніхто не читає** — рішення по SCR-001 прийняте, код не написаний.
4. **`"dsp": {…}` в однині.** Проект із двома процесорами схему ламає.
5. **«Конфігурація» не визначена.** `presets: ["FULL","SQ"]` не розрізняє апаратний слот пресета в
   DSP і варіант тюна; кількість слотів у залізі скінченна, варіантів — ні.
6. **Масштаб.** Модель тримає 2 пресети; заявка — 10–20. Дві осі історії: варіант × версія.
7. **Цільові криві.** `target-curves/registry.json` (SCR-009) не існує; у ledger є лише `target` як
   рядок.
8. **`project_rev` у знімку відсутній** — join шару 3 із шаром 2 історично некоректний. SCR-024.
9. **Дубльовані поля ідентичності** `slot/descr/role/order/hidden` у шарах 2 і 3.
10. **`report_phase` — два писачі** (§шар 3б).

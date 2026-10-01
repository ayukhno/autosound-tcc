# Знахідки з тестової системи — збір

Ведеться з голосу Арбітра, по одній. **Перелік не повний, доки він не скаже.**
На тікети розкладається в кінці, не по ходу.

Для кожної: що саме · де побачено · наше чи зовнішнє · вага · чи відтворюється.

---

## 1. Діалог «Команди агента»: підпис кнопки обрізано, текст задовгий

**Що.** Кнопка `Поза проєктом` малюється як `Іоза проєктом` — перша літера з'їдена.
Тіло діалогу задовге і важко читається.

**Де.** Знімок Арбітра, **macOS**. `i18n.py:1523-1526` (`gateAskNever`, `gateAskForeign`,
`gateAskWrites`, `gateAskBody`), діалог будується в `main_window.py:4222-4241`.

**Наше.** Так, цілком.

**Вага.** Середня для тексту, **висока для обрізання**: це перший діалог, який бачить
нова людина, і він вирішує, скільки TCC питатиме її далі.

**Відтворюється.** Так, за побудовою — див. нижче.

### Чому «вкоротити підпис» — не лік

У коді вже стоїть коментар, що підписи **вкорочували раніше** і рівно з цієї причини:
на Windows їх різало (`on't ask at all (aut`, знімок Арбітра 2026-09-09). Тоді довгі
речення прибрали в тіло діалогу, а кнопкам лишили дієслово. Тепер ріже на macOS, на
рядку з тринадцяти символів.

Отже ріже не текст, а **кнопки `QMessageBox`**: вони не ростуть під свій підпис. Ще одне
вкорочення просто пересуне межу до наступної мови — а переклади в нас чотири, і польська
з німецькою довші за українську.

**Лік — у віджеті, не в тексті:** або задати кнопкам мінімальну ширину з метрики шрифту,
або перестати користуватись `QMessageBox` для цього діалогу.

### Текст

Чинний:

> Сесія тюнінгу виконує команди на цій машині — читає заміри, пише файли проєкту. Скільки
> з цього має спинятись і питати вас? Питаємо один раз; змінити можна будь-коли в меню.
> Те, чого не відкотити, питатиме за будь-якого вибору.

Чотири речення, з них два — застереження про механіку. Питання («скільки має питати?»)
стоїть у середині, а не на початку.

**Перевдумати з Радником по формулюваннях** — Арбітр назвав його прямо.

---

## 2. ✅ Спрацювало: повідомлення про протухлий OAuth

> GENERATOR · CLAUDE OPUS 5
> Failed to authenticate: OAuth session expired and could not be refreshed

**Оцінка Арбітра:** «відпрацювала на користувача — супер».

**Де.** Панель діалогу, знімок Арбітра.

**Чиї це слова.** Не наші: у `src/` такого тексту немає. Отже це відповідь SDK, яку ми
**пропустили назовні** замість згорнути у власне «щось пішло не так».

**Чому це варто записати як успіх, а не як дрібницю.** Це той самий принцип, на якому
сьогодні тримався весь день: **казати справжню причину**. Там, де ми її приховали
(`mode: clipboard` без деталей — тринадцять викликів поспіль), людина була безпорадна. Тут,
де пропустили чужі слова дослівно, вона одразу зрозуміла, що робити.

**Що з цього випливає для решти коду:** правило «не переказувати відмову своїми словами»
має діяти скрізь, а не лише там, де ми про це згадали. Кандидат на перевірку — усі місця,
де ми ловимо виняток і підставляємо власний текст.

---

## 3. Інтерфейс і запит українською — відповідь англійською

**Що.** У параметрах проєкту `Мова: українською`, інтерфейс український, Арбітр пише
українською. Генератор відповідає англійською:

> GENERATOR · CLAUDE OPUS 5
> I'll start by loading the tuning skill and reading state from disk and TCC.

**Де.** Знімок Арбітра, macOS, **TCC 0.1.36 · skill 3.0.48** (тобто вже на релізі).

**Наше.** Так.

**Вага.** Висока. Мова — це «відповідь на перше питання інтейку», як сказано в нашому ж
коді; якщо вона не діє, то й не була відповіддю.

**Відтворюється.** Так, за побудовою — див. нижче.

### Причина знайдена, і вона проста

Мова **є** в стані, який ми віддаємо моделі: `mcp_server.py:412`, поле `language`, і поруч
коментар, що це не деталь екрана, а відповідь на перше питання інтейку.

Але в **системному промті сесії** (`tuning_session.py:154`, `SYSTEM_PROMPT_APPEND`) про
мову немає **жодного слова**.

Тобто модель може дізнатись мову, лише якщо сама покличе `get_tcc_state` і сама здогадається
відповідати нею. На першому ході вона цього ще не зробила — і відповіла англійською,
бо англійська в неї за замовчуванням.

**Лік.** Мова має бути в системному промті, а не лише в стані, який треба спитати. Стан
відповідає на «як зараз»; системний промт задає «як поводитись». Це друге.

**Суміжне питання, яке варто вирішити тим самим рішенням:** чи має мова діяти на **записи
в файли проєкту** (їх пише скіл), чи лише на розмову. У коментарі на `mcp_server.py:409`
сказано, що «кожен файл проєкту, який пише скіл, іде за нею» — отже вона вже мала б діяти
ширше, ніж діє.

---

## Довідка: хто такий Радник

**Радник по формулюваннях = Критик = Gemini** (з голосу Арбітра). Тобто тексти інтерфейсу
перевдумуються через канал `call_critic`.

**Наслідок для пункту 1:** переформулювати діалог «Команди агента» можна буде лише після
того, як канал критика запрацює. Зараз він мовчить — дозволи `agy` не налаштовані
(див. реліз v0.1.36, розділ «відоме, і не наше»). Отже пункт 1 розпадається на дві частини:
**обрізання кнопки** — чинимо самі й одразу; **текст** — після критика.

---

## 4. Після протухлого OAuth сесія не відновлюється — мовчить, доки не перезайти

**Що.** Логін протух (пункт 2), Арбітр залогінився заново і спитав «чи можеш працювати
далі?». Замість роботи:

> GENERATOR · CLAUDE OPUS 5
> API Error: The response stopped arriving. The response above may be incomplete.

Далі сесія не працює. **Вихід із TCC і повторний вхід — робота пішла.**

**Де.** Знімок Арбітра, macOS, TCC 0.1.36 · skill 3.0.48.

**Наше.** Так — не сама помилка, а те, що **людина лишається без вказівки**. Стан, з якого
не вийти інакше як перезапуском, і жодного слова про це.

**Вага.** Висока. Людина сидить перед застосунком, який мовчить, і сама здогадується
перезайти.

**Відтворюється.** Двічі поспіль з тим самим наслідком (пункт «минулого разу було те саме,
поки не дав другу команду» — того ж роду).

**Слова Арбітра про потрібну поведінку:** «тут або треба сказати користувачу що треба
перезайти або працювати». Тобто прийнятних виходів два, і обидва кращі за мовчання:
відновити сесію самим або прямо сказати, що її треба перезапустити.

**Звʼязок.** Це ймовірно та сама вада, що «перший хід сесії нічого не робить, доки не даси
другу команду» — вона в переліку відкритих із #73.

---

## 5. Робота через TCC відчутно повільніша; довгі паузи без ознак життя

**Що.** Враження Арбітра: робота з ШІ **через TCC набагато повільніша**, ніж напряму.
Конкретний випадок на знімку — внизу `Bash ×4…` і **пʼять хвилин або більше** без нового
рядка.

**Де.** Знімок Арбітра, macOS, TCC 0.1.36 · skill 3.0.48.

**Наше.** Ймовірно так, принаймні в частині «не видно, що воно живе».

**Вага.** Висока — це відчуття від продукту загалом, а не окремий випадок.

**Відтворюється.** Як враження — постійно. Конкретна пауза — один зафіксований випадок.

**Дві різні скарги в одній, і їх не можна змішувати:**

1. **Справді повільніше** — чи TCC додає час порівняно з тим самим агентом у терміналі.
   Поки не міряно.
2. **Не видно, що триває робота.** `Bash ×4…` — єдине, що є на екрані за пʼять хвилин.
   Скільки тривала кожна команда, яка йде зараз, чи вона взагалі жива — не видно.

**Суміжне з уже відомого:** скіл шле `report_phase` **трійками** по 0.3 с (з журналу
11.09) — марна робота, яку ніхто не просив. Чи вона дає внесок у повільність — не міряно.

---

## 6. Запит дозволу непомітний — виглядає як зависання

**Уточнення до пункту 5:** та пʼятихвилинна пауза **не була зависанням**. TCC чекав на
відповідь про дозвіл, а Арбітр запиту не побачив.

**Що.** Смуга «Дозволити Bash?» не виділяється на тлі діалогу настільки, щоб її помітили.

**Де.** Знімок Арбітра, macOS, **світла тема**, TCC 0.1.36.

**Наше.** Так.

**Вага.** Висока. Наслідок гірший за саму непомітність: продукт виглядає зламаним
(«завис»), хоча він працює й чекає.

**Відтворюється.** Так.

**Історія.** Це вже **вдруге**. Арбітр просив «фон помаранчевий, як у нас про увагу»
(11.09), правку зроблено — і на світлій темі macOS усе одно непомітно.

---

## 7. «Не питати взагалі (авто)» стоїть у меню — а TCC питає

**Що.** У меню дозволів позначено `✓ Не питати взагалі (авто)`. Попри це зʼявився запит
«Дозволити Bash?».

**Де.** Два знімки Арбітра, macOS, TCC 0.1.36.

**Наше.** Так.

**Вага.** Висока. Це другий випадок, коли вибір користувача не діє.

**Відтворюється.** Так.

**Факт із самого знімка, без розкопок:** у запиті написано «Команда, яку не відкотити», а
команда там така:

```
grep -n "CRITIC_MODEL\|ADVISOR_MODEL\|GEMIN… _gemini_common.sh | head -25; echo "=== agy …
```

Це `grep` і `echo` — **читання, яке нічого не міняє**. Тобто або класифікація «не
відкотити» помилкова, або питає щось інше.

**Історія.** Теж **вдруге**: Арбітр скаржився на непрацюючу «ніколи не питати» 11.09,
порядок перевірок у `tuning_session` тоді правили. Отже попередня правка проблему не закрила.

---

## 8. ✅ Канал критика ПРАЦЮЄ при прямому виклику — відмовляє обгортка

**Що.** Сесія покликала модель критика **напряму**, повз обгортку:

```
agy --model gemini-3.1-pro-high -p "<питання>"
```

Питання було складене так, щоб ввічливість не зійшла за роботу. Відповідь пройшла всі
п'ять перевірок:

| перевірка | |
|---|---|
| зʼєднання + автентифікація | ✅ |
| точна фраза «КАНАЛ ПРАЦЮЄ» | ✅ |
| модель назвалась сама — Gemini 3.1 Pro | ✅ |
| 17×23 = 391 | ✅ |
| змістовна відповідь по домену | ✅ |

**Що це знімає.** Логін Арбітра справний. Вибір моделі в TCC справний. `agy` справний.
Дозволи `agy` виклику не завадили.

**Що лишається.** За словами Генератора: **«обгортка скіла відмовляє без файлу профілю»**,
і «проблема була тільки там, де я й казав: у слоті радника».

**Де.** Знімок Арбітра, macOS, TCC 0.1.36 · skill 3.0.48.

**Наше чи зовнішнє.** Ще не визначено: відмова може бути в обгортці скіла або в нашій
передумові виклику. Не копав — збір.

**Вага.** Висока, але **позитивна**: канал живий, лишилось прибрати передумову.

---

## Довідка: Критик і Радник — різні слоти

У методі ролі **Критика** і **Радника** розділені (хоч фактично це «два в одному»):
критик шукає помилки й невідповідності стандартам, радник дає конструктивні рекомендації.
TCC має **обидва слоти** — і за словами Генератора відмовляв саме **слот радника**, тоді
як критик відповідає.

---

## 9. Критика й Радника розділено — так не можна. Баг СКІЛА

**Рішення Арбітра:** «насправді ділити їх не можна — це баг для скіла. я напишу».

**Що.** Метод розвів дві ролі — критик (помилки й невідповідності) і радник
(рекомендації) — у два окремі слоти. За рішенням Арбітра це неправильно: це одна роль.

**Чиє.** **Скіла**, не TCC. Тікет заводить Арбітр сам.

**Вага.** Висока — з цього поділу виріс пункт 8: відмовляв **слот радника**, тоді як
критик відповідав, і день пішов на пошук вади там, де її не було.

**Що це означає для TCC.** Наш код теж скрізь тримає два слоти й дві ролі
(`role="critic"` / `role="advisor"`, окремі моделі, окремі змінні `GEMINI_CRITIC_MODEL`
і `GEMINI_ADVISOR_MODEL`). Коли скіл зведе їх в одну — за нами піде своя правка.
**Не робити її раніше за рішення скіла**, щоб не розійтись удруге.

> ⚠️ Це **не** пункт нашого списку до виправлення. Записано тут, бо звідси виріс пункт 8 і
> бо TCC муситиме піти слідом.

---

## 10. Чиста Windows: `agy` встановлений і залогінений — у пікері його НЕМАЄ

**Що.** Машина з нуля. У списку критика лише:

```
SDK · Claude Opus 5 / Sonnet 5 / Fable 5
CODEX · gpt-5.2-codex · постав codex CLI
CODEX · gpt-5.2 · постав codex CLI
```

Жодного рядка AGY. При цьому `agy` у терміналі відповідає:

```
Antigravity CLI 1.2.1
ayukhno@gmail.com (Google AI Plus)
Gemini 3.8 Flash (High)
```

Тобто встановлений, залогінений, із підпискою.

**Де.** Два знімки Арбітра, Windows, машина з нуля. Ключ заданий через
`[System.Environment]::SetEnvironmentVariable("OPENAI_API_KEY", …, "User")`.

**Наше.** Так. **І це моя вчорашня правка** (probe30+, реліз v0.1.36).

**Вага.** Висока. Нова людина на чистій машині не побачить маршруту, який у неї працює, і
не дізнається, чому.

**Відтворюється.** Так, за побудовою — на будь-якій чистій Windows.

**Що я зробив і чим це обернулось (без розкопок — це просто мій власний журнал змін):**

- під Windows `agy models` більше не питається автоматично, бо кожен запуск відкривав
  консольне вікно — це була частина TCC-006;
- питає лише натиск ↻;
- у probe30 я додав рядок «маршрут не питали», але в probe34 **прибрав його з автоматичного
  показу**, бо він зсував компонування на старті й підозрювався у спалаху.

Разом: маршрут не питають **і** про це не кажуть.

**Помітна несиметричність, видна прямо на знімку:** `codex` **не** встановлений — і його
показано з підказкою «постав codex CLI». `agy` **встановлений** — і його не показано взагалі.

---

## 11. CI на Windows червоний щонайменше з 07.09 — і ніхто не дивився

**Що.** Прогін тегу `v0.1.36`: **8 провалів, 1858 пройшло** — усі на Windows. Раніші прогони
теж червоні, зі змінним складом (07.09 — інший десяток тестів).

**Де.** GitHub Actions, `checks`, гілка `main` і тег `v0.1.36`.

**Наше.** Так, цілком.

**Вага.** **Найвища з усього списку.** Не через самі тести, а через те, що
**реліз `v0.1.36` вийшов із червоним Windows-CI, і я цього не перевірив.**
`make ship` ганяє лише локальний набір — на macOS. Windows він не бачить.

**Відтворюється.** Так.

### Чотири з восьми — це пункт 10, який CI знайшов РАНІШЕ за Арбітра

```
test_agy_is_fetched_on_the_first_ever_refresh_when_nothing_is_cached
  — «with nothing cached, agy must be asked once so the route exists at all»
test_a_route_that_answered_with_nothing_is_not_re_asked_every_time
test_an_installed_cli_that_never_answered_is_named_rather_than_hidden
test_the_catalogue_survives_a_launch_where_the_cli_says_nothing
```

Тести казали дослівно те, що Арбітр побачив на чистій машині: з порожнім кешем `agy` треба
спитати **один раз**, інакше маршруту не існує. CI був червоний **саме про це**, і я не
подивився жодного разу.

**Виправлено** правкою, зробленою після слів Арбітра «без agy ніяк — вертай».

### Решта чотири — ще не розібрані

```
test_terminal_launcher::test_a_project_path_with_a_quote_does_not_reach_the_shell
  — WinError 123: у Windows у назві теки не може бути лапки, а тест її створює
test_conftest_guards::test_the_suite_cannot_read_this_machines_reviewer_key
  — очікує POSIX-шлях
test_main_window::test_the_left_column_is_one_scroll…
  — libshiboken: Internal C++ object already deleted
test_main_window::test_the_right_column_scrolls_when_the_capture_list_is_long
```

Перші два виглядають як припущення про платформу в самому тесті. Третій і четвертий треба
дивитись окремо — «already deleted» підозріло близьке до правок про `discard`.

### Головне, що з цього випливає

Провал не в тестах, а в тому, що **ворота релізу не бачать Windows**, хоча Windows — це
платформа, на якій продукт живе і на якій знайдено всі вади цього тижня.

---
---

# ПЛАН

Збір закрито словами Арбітра: «поки так, бо далі не можу йти». Порядок нижче — **не за
тяжкістю вади, а за тим, що знімає його блокування**.

## Хвиля 0 — уже зроблено, чекає релізу

| | що | звідки |
|---|---|---|
| ✅ | `agy` питається раз на машину, відповідь лягає на диск | п.10, і 4 з 8 провалів CI |

## Хвиля 1 — щоб можна було працювати далі

**1.1 · Дозволи: «не питати» має означати не питати** (п.7)
Вибір користувача не діє — **вдруге**. На знімку питає про `grep … | head`, позначене як
«команда, яку не відкотити», хоча воно нічого не міняє. Дві підозри: класифікація
небезпечного і порядок перевірок. Спершу **відтворити тестом**, тоді правити.

**1.2 · Запит дозволу має бути видно** (п.6)
Наслідок непомітності гірший за неї саму: продукт **виглядає зламаним**. Це теж удруге —
помаранчевий фон робили, на світлій темі macOS не спрацювало. Робити не «ще помаранчевіше»,
а так, щоб пропустити було **неможливо**.

**1.3 · Сесія має відновлюватись або сказати, що не може** (п.4)
`API Error: The response stopped arriving` → тиша. Вихід-вхід лікує. Слова Арбітра про
потрібну поведінку: «або сказати користувачу що треба перезайти, або працювати».
Мінімум — **сказати**. Ймовірно те саме, що «перший хід нічого не робить».

## Хвиля 2 — щоб застосунок не брехав про машину

**2.1 · Мова проєкту має діяти на відповіді** (п.3)
`language` є в стані, але в системному промті сесії про мову **ні слова**. Українська
навколо, англійська у відповіді.

**2.2 · Обрізані підписи кнопок** (п.1, половина)
Ріжуть не тексти, а кнопки `QMessageBox`. Вкорочувати втретє — біговий килим: чотири мови,
польська й німецька довші. Лікувати у віджеті.

**2.3 · Маршрут, якого не питали, має про себе сказати**
Симетрія з `codex`: не встановлений — показаний із підказкою; `agy` встановлений — не
показаний. Рядок є (`cliRouteNotAsked`), але я прибрав його з автопоказу.

## Хвиля 3 — щоб це не повторилось

**3.1 · Windows-CI зелений** (п.11)
Лишилось 4 провали: лапка в назві теки (Windows так не вміє), POSIX-шлях у перевірці,
і два в `main_window` — `already deleted`, підозріло близько до `discard`.

**3.2 · Ворота релізу мають бачити Windows**
Головне з усього списку. `make ship` ганяє лише macOS. Реліз `v0.1.36` вийшов червоним, і
я дізнався про це від Арбітра. Поки цього нема — будь-який «зелений набір» на Маку означає
менше, ніж здається.

## Хвиля 4 — після того, як стане працездатно

**4.1 · Повільність і відсутність ознак життя** (п.5)
Дві різні скарги: чи TCC додає час (не міряно) і чи видно, що робота триває (не видно —
`Bash ×4…` пʼять хвилин). Друге лікується без вимірів; перше без вимірів чіпати не можна.

## Не наше

| | |
|---|---|
| п.9 | Критик і Радник — одна роль. **Тікет `#130` (SKL-032) заведено** → `to:skill`. Свою правку робимо **після** їхньої |
| п.8 | Вікно терміналу, яке `agy` відкриває, щоб спитати дозвіл |
| — | `report_phase` трійками (у тому ж тікеті, як дрібне) |

## Порядок і чому саме він

Хвиля 1 — це те, через що Арбітр **не може тестувати**. Хвиля 2 — те, через що застосунок
каже неправду про машину, на якій стоїть. Хвиля 3 — те, через що ми обидва про це не знали.
Хвиля 4 потребує вимірів, а міряти немає сенсу, доки 1 і 2 не зроблені.

---

## ✅ Хвиля 3.1 ЗАКРИТА — CI зелений на обох платформах

Прогін `34630923443`, коміт `49e3804`:

```
linux   (run 1)  success  — 1879 пройшло, 5 пропущено
windows (run 1)  success  — 1873 пройшло, 11 пропущено
ruff             success
```

Уперше з 07.09.

### Жоден із восьми провалів не був вадою продукту

Усі — тести, які перевіряли **машину розробника**, а не властивість:

| тест | що припускав |
|---|---|
| `test_the_suite_cannot_read_this_machines_reviewer_key` | що `XDG_CONFIG_HOME` і `APPDATA` не задані |
| `test_a_project_path_with_a_quote…` | що можна створити теку з лапкою в імені |
| `test_the_right_column_scrolls…` | що 102 рядки переповнять колонку — залежить від метрик шрифту |
| `test_the_first_start_of_a_new_version_says_so` | що теку журналу вирішує `HOME` |
| ×4 про `agy` | що маршрут можна не питати (це була справжня вада — п.10) |

### Головне, і воно не про тести

**`HOME` вистачало рівно тому, що на цій машині більше нічого не задано.**
Бігуни GitHub задають `LOCALAPPDATA`, `APPDATA`, `XDG_CONFIG_HOME` — і код, що їх читає,
ішов повз тимчасовий HOME у справжні теки бігуна.

Тому остання правка — **в одному місці**, у фікстурі ізоляції, а не в десятьох тестах.
Інакше ми латали б по тесту щоразу, як хтось прочитає наступну змінну.

### Що це лишає відкритим

**Хвиля 3.2 — ворота релізу досі не бачать Windows.** `make ship` ганяє лише локальний
набір на macOS. CI зелений, але він і був червоний, коли виходив `v0.1.36`, і це нікого не
спинило. Поки ворота не дивляться на CI, зелений колір — це відомість, а не гарантія.

---

## ✅ Хвиля 2.1 — мова проєкту тепер доходить до моделі

**Було.** Мова лежала в `get_tcc_state` і більше ніде. Модель могла дізнатись її, лише
**спитавши**, — а перший хід відповідає раніше, ніж устигне спитати. Звідси
`I'll start by loading the tuning skill…` при українському всьому.

**Знайдено по дорозі:** маршрут **інтервʼю це вже проходив** — у `agent_session` є розділ
`## Language` із рядком «EVERY word you emit is in it», і в ньому прямо названо `tcc#8`:
«англійська преамбула над українською відповіддю». Тюнінгова сесія такої правки не дістала.

**Стало.** Те саме правило в системному промті тюнінгової сесії, з **назвою** мови, а не
кодом: «answer in uk» — не інструкція, якої модель може дотриматись.

**Побіжно:** сторожа, що звіряє `LANGUAGE_NAMES` з `i18n.LANGS`, **не існувало** — хоч
коментар у коді на нього посилається («`test_i18n_languages` now fails when a fifth is added
and forgotten here»). Тепер існує.

---

## ✅ Хвиля 2.2 — підписи кнопок більше не ріжуться

**Було.** «Поза проєктом» малювалось як «Іоза проєктом». І це вже **третій** захід на ту саму
ваду: 09.09 різало на Windows («on't ask at all (aut»), тоді речення вкоротили до дієслів;
11.09 ріже на macOS — на тринадцяти символах.

**Чому не ловилось.** Сторож існував і був **виконаний**: `_BUTTON_MAX = 26`, а підпис — 13.
Лічити символи — неправильний інструмент. Ріже **піксельна ширина**: шрифт, платформа, мова.

**Причина.** Стилі задають `QMessageBox QPushButton` `min-width: 84px` і `padding: 6px 18px`.
Кнопка не росте під свій підпис — Qt розмічає її під той, що очікував, а довший **обрізає**.

**Лік уже існував у коді**, з датою. Діалог виходу мав те саме 19.08 і лікується рядком
`box.adjustSize()` із коментарем «Qt розмітив кнопки під свої підписи; наші довші».
**Діалог дозволів такого рядка не мав.**

**Стало.** `sizing.fit_to_text(button)` міряє `horizontalAdvance` власного підпису кнопки і
ставить мінімальну ширину; далі `box.adjustSize()`. Застосовано в обох діалогах із власними
підписами.

**Тест міряє піксель, а не символи** — як тест смуги дозволу міряє колір, а не назву токена.
Перевірено, що без правки він падає на всіх трьох підписах.

---

## ✅ Хвиля 2.3 — рядок «маршрут не питали» ПРИБРАНО, а не додано

Планувалось додати симетрію з `codex`. Після повернення `agy` виявилось, що додавати нема
чого: гілка **мертва**. `cli_routes_not_asked` повертає щось лише доти, доки `agy` не
спитали, — а тепер його питають на старті; читалась вона тільки після натиску ↻, коли
питання вже відбулось.

Гірше: її текст у чотирьох мовах описував поведінку, якої **більше немає** («під Windows
нічого не питається автоматично»). Це моя ж правка зробила його неправдою.

Прибрано гілку, помічник і чотири переклади. Лишився чесний рядок — «встановлено, але
моделей не віддав», і він показується беззастережно.

`_LAST_ASKED` лишився: він потрібен тихому періоду і тому, що лишилось.

---

## Скіл `v3.0.49` відповів на наш тікет `#130`

`9d509ac` — «Рецензент — одна роль, одна модель». Їхнє формулювання причини збігається з
нашим: *«autosound_ai.py для advisor читав лише свою змінну, TCC пише лише критика»*.

**Що зробив TCC слідом** (пін `v3.0.48 → v3.0.49`):

- `GEMINI_ADVISOR_MODEL` більше не пишеться — одна змінна на обидві задачі. Змінні порадника
  вгорі **не читаються**, значення в них називається на stderr, а не виконується.
- Тест, що прибивав старий контракт, **перевернуто разом із контрактом**, а не видалено.

**Чого робити не довелось:** «другий слот моделі можна прибрати» — ми його й не заводили,
`_CRITIC_KEY` єдиний.

**Що змінилось для користувача, і про це треба сказати окремо:**

1. **Дефолтної моделі рецензента більше немає.** Не названо → вихід 3 зі списком. Наш
   `_CHOOSE_MODEL_EXIT = 3` це вже обробляє й показує пікер — збіг перевірено, не припущено.
2. **Зʼявилась задача `ask`** — будь-яке питання, під контрактом взаємодії, **без файлів
   проєкту**. Саме вона знімає блокування з пункту 1 списку: переформулювати тексти
   інтерфейсу через Критика можна тепер і на теці, що не проходила інтейк.

---

## Test of v0.1.39 — 2026-09-14

Recorded as seen, not diagnosed (hub WAVES.md: while the Arbiter tests, findings are only written
down). The VM updated 0.1.38 → 0.1.39 and started fine.

### 12. The update on a second Windows machine failed, and the window said "Done" anyway

**What.** "Update TCC" on another Windows machine: `uv` could not fetch v0.1.39 — `git fetch …
+6ad4f82…` exit 128, `fatal: unable to access 'https://github.com/ayukhno/autosound-tcc/': Empty
reply from server`. The next line in the same window: `Done - start TCC again.` TCC stays on 0.1.38
while the window says the update is done.

**Where.** The Arbiter's screenshot, a second Windows machine (not the VM, which updated the same
hour).

**Ours or external.** The failed fetch looks external (network or GitHub). "Done" after a failed
update is ours.

**Weight.** High for "Done": somebody starts the old build believing it is the new one, and every
report after that is about the wrong version.

**Reproduces.** No: the second attempt on that machine (a UTM VM, "Windows 2") went through, 0.1.36 → 0.1.39. The finding is the "Done" after a failure, not the failure.

**Status.** Not seen again 2026-09-23: the update on the Windows VM succeeded (0.1.41 → 0.1.43) and said Done; the failure path was not met, so the finding stays open.

**Closed 2026-10-01.** Fixed in code: the update script says Done only when the install exits 0, otherwise «The update did not finish» (`core/updates.py`, the `failed` branch). The failure path itself not met live since; a repeat is a new finding.

### 13. "Update TCC" opens a second, empty console

**What.** Beside `Administrator: cmd`, which runs the update, a second window
`C:\Windows\System32\cmd.exe` opened, empty, with only a cursor.

**Where.** The same screenshot, the second machine.

**Ours or external.** Ours: F-043 (the second source in hub #73, TCC-006), still in v0.1.39.

**Weight.** Low to medium: confusing, not harmful.

**Reproduces.** Known since 2026-09-06.

**Status.** Fixed, the Arbiter's Windows test of v0.1.43, 2026-09-23: one console during the update.
### 14. First start after the update: a terminal window blinks behind "Reading models"

**What.** On the first start of 0.1.39, TCC's own console (`Autosound TCC: reading models...`)
appears and another terminal window blinks behind it. On later starts there is no extra window.
Apart from that first start, no window blinks at all — during work or on start. That is the check
hub #73 (TCC-006) was waiting for, and it passes.

**Where.** The Arbiter's Windows VM, 0.1.39, method 3.0.52.

**Ours or external.** Not known.

**Weight.** Low: once, right after an update.

**Reproduces.** Only on the first start after the update so far.

**Status.** Not seen on the VM's first start after the update to v0.1.43 (2026-09-23); the second machine's `agy` console at start is TEST-FINDINGS 43.
### 15. "Don't ask at all (auto)" is ticked, and TCC still asks "Allow Bash?"

**What.** Menu → "Ask about" shows "Don't ask at all (auto)" ticked. The chat still stops on
"Allow Bash?" for `mkdir -p /tmp/asq && cat > /tmp/asq/ready.md <<'EOF' …`, labelled "a command
that cannot be undone".

**Where.** The Arbiter's Windows VM, project testTCC-9, 0.1.39.

**Ours or external.** Ours.

**Weight.** High, and the third time: finding 7 and wave 1.1 ("the choice does not work — the
second time").

**Reproduces.** Seen once on 0.1.39.

**Again on 0.1.41 (2026-09-19), with the cause.** The Arbiter's screenshot: "Не питати взагалі
(авто)" ticked in the menu, and the chat stopped on `Дозволити Bash?` — "Команда, яку не відкотити:
set -e …" for a `printf` writing a markdown README. The check for a command substitution was a
regex over the whole line (`` `|\$\( ``), and markdown spells code in BACKTICKS, so every table
cell (`` '| `target-curves/` | цільові криві |' ``) read as one. Same shape as the `|` inside
`grep "a\|b"` (2026-09-11): quoting is part of reading a command. Closed on `wave-0.1.42` —
`_has_substitution` walks the command with its quote state, the shell's own rule.

### 16. The permission request has no background, so nothing draws the eye to it

**What.** The "Allow Bash?" block is drawn like the rest of the chat: grey text, no background, the
buttons at the bottom. The Arbiter: it has NO background that would draw attention to the question.

**Where.** The Arbiter's Windows VM, light theme, 0.1.39.

**Ours or external.** Ours.

**Weight.** High, and recurring: finding 6 and wave 1.2 (an orange background did not show on the
macOS light theme). A request nobody notices reads as a hang.

**Reproduces.** Seen on 0.1.39.

**Again on 0.1.41 (2026-09-19), with the cause.** The Arbiter's screenshot of the light theme: the
request is white like the rest of the panel, no tint and no border, though the stylesheet has asked
for both since 2026-09-11. Qt paints a stylesheet background on a plain `QWidget` subclass only
when `WA_StyledBackground` is set — with one exception, a top-level window, which gets it anyway.
The bar is a child of the dialog panel, so nothing was painted there; a test that grabbed the bar
alone made it a window and showed a colour the app never drew. Closed on `wave-0.1.42`: the
attribute is set, the scrolled question block is transparent above it, and the test builds the bar
inside a parent and grabs the parent (without the attribute 0 of 78 sampled pixels are the tint).

### 17. The Generator reached the reviewer through Bash, inside its own session

**What.** Asked whether the reviewer is ready, the session wrote the question to `/tmp/asq/ready.md`
through Bash (the prompt in 15) and ran `autosound_ai.py ask` (local `agy`,
`gemini-3.7-flash-low`). The reviewer answered: channel live, role accepted, ready once the intake
writes its files. Reported by the session alongside:
- two `critic` calls through TCC were refused before the intake: `autosound_context.md not found`
  (the method's contract; `ask` goes around it);
- the CLI warned about a deadlock risk — it saw the `CLAUDECODE` marker, i.e. it was run from inside
  an agent session — and went through after a timeout; the documented path is a separate terminal;
- `AUTOSOUND_CRITIC_MODEL` was not in that shell's environment; the model was passed explicitly.

**Where.** The Arbiter's Windows VM, project testTCC-9, 0.1.39; the session's own report, pasted by
the Arbiter.

**Ours or external.** Not decided: the reviewer was reached around TCC's own call rather than
through it.

**Weight.** Medium: it worked, but by the path the method says not to use.

**Reproduces.** Once.

**Closed 2026-10-01.** Not seen since 0.1.39 (now 0.1.45): the reviewer is checked before a session (v0.1.44), the method's instructions name its own call (hub #200, v3.0.60), the cut stream has its class (hub #204, v3.0.62). A repeat is a new finding.

### 18. Too wide a gap between the AI dialog and the right column

**What.** Between the right edge of the AI dialog's working area (the composer with "Send" and the
transcript's scrollbar) and the border of the right column there is more empty space than anywhere
else in the window.

**Where.** The Arbiter's screenshot, Windows VM, light theme, 0.1.39.

**Ours or external.** Ours.

**Weight.** Low: layout.

**Reproduces.** Always, on that window size.

**Status.** Waiting to show again (2026-09-23): the Arbiter no longer sees it on Windows or the
Mac — possibly because he works in terminal mode, with the in-app AI dialog not active. No change
was made for it. It is not a VM-session item; the next time it shows, it is taken with a screenshot.

**Closed 2026-09-24 by the Arbiter.** Seen again with the in-app dialog active: the space on the
right is how a long AI message looks (the Generator's bubble stops short of the right edge, the
Arbiter's own message sits there), and that is OK. No change.

### 19. Feedback has one way out: GitHub

**What.** The feedback dialog ("Відгук про прототип TCC") offers a single radio button, "GitHub
issue (маю акаунт)", and "Надіслати в GitHub →". Somebody without a GitHub account, or without
access to it, has no other path. A radio group of one option is also a choice that is not one.

**Where.** The Arbiter's screenshot, Windows VM, 0.1.39.

**Ours or external.** Ours. Related: TODO F-042 (how to report a defect and hand over settings when
GitHub is not available).

**Weight.** Medium: a tester without GitHub cannot report from the app.

**Reproduces.** Always.

**Closed 2026-10-01.** Fixed: «A report without a GitHub account» — the form route in `feedback_dialog.py` (TODO F-042, v0.1.41).

### 20. A reviewer refused by region: red in the open list, plain in the closed picker, "?" in the footer

**What.** The chosen Critic, `AGY · Gemini 3.1 Pro (High)`, is refused by location. With the list
open it is red, with `· region`, and the CODEX rows are red with `· not installed` — as 0.1.39
promises. The closed picker in the footer shows the same model in plain text, and the status beside
it reads `Critic · ? · just now`: no colour and no reason where the choice is visible all the time.

**Expected (the Arbiter, 2026-09-14):** the closed Critic field itself is red.

Worked as intended in the same run, reported by the session: the start-up probe now answers
`"ready": false, "not_ready_because": ["not available in your region"]` (on 0.1.38 it said ready);
a real critic call refused by location answers "↻ will not help … pick a different Critic model in
TCC's footer" (the 13.09 fix).

**Where.** The Arbiter's Windows under Parallels, 0.1.39, method 3.0.52; two screenshots and the
session's report.

**Ours or external.** The region refusal is Google's. The closed picker and `?` are ours.

**Weight.** Medium: the one place that is always on screen does not say the reviewer cannot run.

**Reproduces.** On that machine, every start while that model is chosen.

### 21. Reviewer calls from the session: refused on agy's `read_file` permission, and the model not inherited

**What.** From the session's report on the Windows machine under Parallels (the same run as 20):
- before the one that went through, calls were refused within 2–5 s: twice by region, once on a
  permission for `read_file` (agy asking to read a file, in a call that cannot answer);
- the session again ran the method's script directly (as in 17), and a direct call does not inherit
  TCC's Critic model: without `AUTOSOUND_CRITIC_MODEL` it refused and printed what `agy` can run —
  `gemini-3.8/3.7/3.6/3.5-flash-{high,medium,low}`, `gemini-3.1-pro-{low,high}`. `3.1-pro-high` is
  on that list and still refused by location;
- with the model passed by hand (`gemini-3.5-flash-medium`, the one chosen in TCC) and the `ask`
  task, the call was silent for over two minutes. Corrected by the session later the same day: it
  was not thinking but the agent-inside-agent deadlock — the CLI had been run from the session
  itself — so `ask` was not tested at all.

**Where.** The Arbiter's Windows under Parallels, 0.1.39, method 3.0.52; the session's report.

**Ours or external.** Not decided. The `read_file` permission is between the method's reviewer
script and `agy`; the model not reaching a direct call is how the session goes around TCC (17).
The `read_file` refusal, reported later: agy auto-denied it with the home folder in its `trustedWorkspaces` and the project inside it. Sent to the skill as hub TCC-014.

**Weight.** Medium: every route to the reviewer on that machine failed or went around TCC.

**Reproduces.** Two machines show 17; the `read_file` refusal once.

**Closed 2026-10-01.** Not seen since 0.1.39: the `read_file` refusal went to the skill (hub TCC-014), the bypass is 17's, closed with it. A repeat is a new finding.

### 22. The protective-filter dialog asks for virtual channels

**What.** Reading from REW, the dialog "Захисні фільтри цього набору замірів" lists a row for every
channel: the virtual `VFL`, `VFR`, `VRL`, `VRR`, `VC`, `VSW` first, then the outputs `c`, `w-L`,
`w-R`, `m-L`, `m-R`, `tw-L`, `tw-R`. A protective filter sits in the signal path of an OUTPUT, the
driver being measured; a virtual channel is not measured through one. The Arbiter: it cannot be
that virtual channels are asked for — this only applies to the Output drivers.

(In the same dialog the header says the capture set is not open, so there is nothing to write to,
and "Записати" is disabled.)

**Where.** The Arbiter's screenshot, Windows, 0.1.39, a project with virtual channels (Helix-style).

**Ours or external.** The dialog is TCC's; which channel list it draws from is not checked.

**Weight.** Medium: thirteen rows where seven belong, and six of them ask for something that does
not exist.

**Reproduces.** On that project.

### 23. TCC's advice for agy's `read_file` refusal names the wrong setting (tcc#36)

**What.** A `critic` call from the project on Windows came back `mode: clipboard`, `model: null`:
agy auto-denied `read_file` because "headless mode cannot prompt for" it, and printed its own remedy
— an allow-rule under `permissions.allow`, or `--dangerously-skip-permissions`. TCC's `call_critic`
advised something else: add the project to `trustedWorkspaces`, or `"toolPermission":
"always-proceed"` for every folder. The session followed TCC's advice exactly and re-ran the call:
byte-identical error. The home folder was already trusted, with the project inside it. The session
filed it as tcc#36. So the narrow advice does nothing, and the wide one is where a person goes next.

Also from the same session: running the method's script after `cd` into the method's folder left
`combined_prompt.md` in that checkout (removed by the session). A dirty checkout is one TCC's updater
refuses to move.

**Where.** The Arbiter's Windows under Parallels, 0.1.39, method 3.0.52, project `testTCC8`; the
session's report.

**Ours or external.** The wrong advice is ours (tcc#36). What agy needs headless is the method's to
say (hub #150, TCC-014).

**Weight.** High on that machine: no review can happen there until someone edits agy's settings by
hand.

**Reproduces.** Every critic call on that project, per the session.

### 24. A long command pushes the permission buttons out of the window — the test stops

**What.** The session asked "Дозволити Bash?" for a long command: `cd …/.autosound-tuning-src && gh
issue create --repo ayukhno/autosound-tuning-skill --title … --body "$(cat <<'EOF' …` with the whole
issue body inline, dozens of lines. The permission block grows with the command until "Дозволити" /
"Відхилити" are below the bottom of the window. There is no way to answer, so the turn waits and the
test stops.

The block (`ui/tcc/confirm_bar.py`) is placed in the dialog panel's own layout, outside the
transcript's scroll area, and its detail is a word-wrapped label with no height limit.

**Where.** The Arbiter's screenshot, the remote Windows machine, 0.1.39, zoom 110%.

**Ours or external.** Ours. The same widget as 15 and 16.

**Weight.** Blocking on that machine.

**Reproduces.** Whenever a command is taller than the space left in the window.

**Fixed** on `wave-0.1.40` (2026-09-17): the detail scrolls inside twelve lines; the buttons stay on screen.

**Not seen again. Widened anyway on `wave-0.1.42` (2026-09-19).** The Arbiter's screenshot of
0.1.41 shows the scroll working and both buttons in place — this finding stays fixed. Read while
looking at that screenshot: the bound covered the DETAIL only, and the title above it was a wrapped
label with no limit, so the same failure was still reachable through a long title (measured: 353 px
of bar against a bounded 300). Title and command are now one scrolled block, bounded by twelve
lines AND by half the height of the panel.

### 25. From a real terminal the reviewer is refused the same way, and its files follow the current folder

**What.** The Arbiter ran the reviewer by hand from an ordinary PowerShell terminal, as the session
suggested (the session's command was `cmd` syntax and had to be rewritten for PowerShell):
`python scripts\autosound_ai.py ask <package>` from the method's folder. agy was again run headless:
`read_file … headless mode cannot prompt for, so it was auto-denied` → clipboard mode. The fallback
wrote the package to `C:\Users\o.yukhno\.claude\skills\autosound-tuning\rew_analitic\combined_prompt.md`
— inside the installed method — and the review text to a relative `process\reviews\…`, although
`AUTOSOUND_PROJECT_DIR` was set.

So on that machine there is no working route to the reviewer at all: through TCC (23, tcc#36),
from the session (17, 21), or from a terminal (this).

Found after, by the session: the file announced as "Текст рецензії збережено" ends with the
question itself — it is the prompt, not a review — and the next printed line says to record it in
the journal as one. The wrapper passes no CLI flags through (only `AUTOSOUND_*` variables), so
agy's per-run `--dangerously-skip-permissions` cannot be given. Both added to hub #150 (asks 4, 5).
The one route that works there: the clipboard step, pasted into a web chat by hand.

**Where.** The Arbiter's Windows under Parallels, 0.1.39, method 3.0.52.

**Ours or external.** The method's (hub #150 asks 1 and 2); TCC's advice follows whatever it settles
(tcc#36).

**Weight.** High on that machine: no review is possible.

**Reproduces.** Every call, by every route tried.

### 26. After a correct session close, quitting TCC still asks "Save before closing?"

**What.** The Arbiter told the session to finish. It wrote everything down and closed in order:
`session_close` → "nothing open in the process record", `contract exit 0`, notes in
`autosound_context.md`. Quitting TCC right after still showed "Save before closing? — A session is
running. What it has learned this turn is not on disk until it writes it — closing now loses that.
Saving costs one turn." with "Save the turn / Don't save / Stay". Nothing was left to save, and the
dialog offers to spend a turn on it.

**The Arbiter's proposal.** TCC already hears the close (`session_close` goes through TCC's MCP).
Let that mark the session saved, so quitting does not ask; clear the mark as soon as the session
writes or changes anything again after it — or refuse changes after a close.

**Where.** The Arbiter's screenshot, Windows, 0.1.39, method 3.0.52.

**Ours or external.** Ours.

**Weight.** Medium: a question with no right answer at the end of every properly closed session.

**Reproduces.** After every `session_close`, on quit.

**Fixed** on `wave-0.1.40` (2026-09-17), as the Arbiter proposed: a recorded `session_close` marks the session saved and the next write clears it.

### 27. The AI history needs a tab of its own: which sessions, which file, which folder

**What.** Asked by the Arbiter while testing, 2026-09-19, with a screenshot of Diagnostics → Log:
the export was a spinner ("the newest five") and a save dialog, and neither says WHICH conversations
go into the file. Wanted: its own tab showing the choice and not the transcripts — the project's
sessions to tick, where to save, and a name that starts from the project and the date of what is
being saved. Then: each session as its own file, the set as one archive.

**Where.** The Arbiter's screenshot, macOS, 0.1.41.

**Ours or external.** Ours. A wish, not a defect — the old path worked, it just could not be aimed.

**Weight.** Medium: it is how a session's history leaves the machine for a report or a review.

**Reproduces.** n/a.

**Built on `wave-0.1.42` the same day — out of turn.** The Arbiter said "let's add it" and the
session built it while the collection step was still open; the rule is that a session only RECORDS
while the Arbiter tests (WAVES.md §1), and that holds for a wish said in passing as much as for a
finding. The work is in the branch and stays there; the entry is here so the review step sees it
with everything else.

### 28. "Take measurements from REW": the new name is empty, and the columns cannot be resized

**What.** The import form lists what REW holds — `sw_01 (sw)`, `w-L_01 (rta)`, `r-L_17 (rta) noXO`
and the rest, twenty rows with their timestamps — and the **New name** column is "вибери або
впиши…" on every one of them. The name is exactly what the person came to the form for, and it is
the one column the form does not fill: TCC (or the skill) already knows which measurement it
matched and under which name it will be filed, so that name belongs in the column, pre-filled and
editable. Also asked: let the column widths be dragged — the REW title and the timestamp squeeze
the column that matters.

**Also asked (2026-09-19).** A button at the BOTTOM of the form: "Вибрати все" / "Відмінити вибір".
Twenty rows of checkboxes and no way to set them all at once — and the rows that need unticking are
usually all of them but two.

**Where.** The Arbiter's screenshot, macOS, 0.1.41, project EPY-Sep2026, the round waiting on 16.

**Ours or external.** Ours; the name may have to come from the skill.

**Weight.** High for the empty name — it is the point of the form, and twenty rows of typing is
where a round gets abandoned. Low for the widths.

**Reproduces.** Every import, by the look of it.

### 29. The UNUSABLE banner takes half the window and cannot be closed

**What.** Sixteen `UNUSABLE sw_1 (sw) — No measurement titled 'sw_1 (sw)'` lines are drawn across
the top of the main window, above the project panel and the dialog, and there is no ✕ — the only
way out of them is whatever redraws the screen. On a laptop they take about half the height.

**Where.** The Arbiter's screenshot, macOS, 0.1.41, project EPY-Sep2026.

**Ours or external.** Ours (the text comes from the method's matcher; the strip is TCC's).

**Weight.** High: it hides the work area, and a message nobody can dismiss is read once and then
worked around.

**Reproduces.** Seen with sixteen unmatched names at once.

### 30. "In focus now": protection is invisible in the list, the RTA column explains what needs no explaining, and a sweep is labelled `(rta)`

**What.** Three things on the same panel, set `cap_005`:

1. **Protection is recorded and the list does not say so.** The line above reads "Захист записано
   для: c, m-R, tw-L, tw-R" and the protective-filters dialog holds real values (m-L/m-R/c 100 LR24,
   tw-L/tw-R 1000 LR24) — but the SWEEP (SW) rows themselves show nothing: `m-L_1 (sw)` looks exactly
   like `sw_1 (sw)`, which carries none. Which curve was taken through a protective filter is a fact
   about reading that curve, and it belongs on the row.
2. **The RTA column carries an explanation nobody needs.** Every MMM RTA row is followed by cut-off
   text — `this che…`, `this ch…`, `thi…` — which squeezes the names and says nothing.
3. **A sweep is labelled `(rta)`.** In ADDITIONAL the rear sweeps appear as `r-L_1 (sw) (rta)` and
   `r-R_1 (sw) (rta)`. It is a sweep, `(sw)` already says so, and the measurement's own name in REW
   is `r-L_1 (sw)` with no second suffix (the Arbiter's second screenshot).

**Where.** The Arbiter's screenshots, macOS, 0.1.41, project EPY-Sep2026, set `cap_005`.

**Ours or external.** Ours for all three; the `(rta)` suffix may be added where the additional rows
are built rather than where they are drawn.

**Weight.** Medium for the missing protection mark — it changes how a curve is read. Low for the
explanation and the suffix, but the suffix is a wrong statement about a measurement, not only noise.

**Reproduces.** Seen on this set; the suffix on every additional sweep row in it.

### 31. "In focus now" needs tidying: four changes the Arbiter named

**What.** Asked 2026-09-19 with the screenshot of the panel (set `cap_005`), in the Arbiter's own
order:

1. **"Захист" moves up into the row with the name field and the two buttons.** The name field stops
   being fixed at its current width — it shrinks to the measurement's name, or to a fixed but SMALL
   width; today it is fixed too wide and pushes everything else down.
2. **The colour legend goes on one line**, with the words shortened; the full wording moves into a
   tooltip.
3. **The status message goes ABOVE the field and the buttons, in blue.** Today it is two lines
   below them — "Взято: 4. Записано в набір: 4. Захист записано для: …" and "пропущено".
4. **A "Готово" button**, in the header next to the green REW mark, which tells the AI to start
   working on what was just captured. Disabled until something has been loaded.

**Where.** The Arbiter's screenshot, macOS, 0.1.41, project EPY-Sep2026.

**Ours or external.** Ours.

**Weight.** Medium: the panel is the one a round is run from, and today its top half is spent on
text rather than on the round. Point 4 is new behaviour, not tidying — it is the hand-off from
capture to the AI.

**Reproduces.** n/a — a change, not a defect.

### 32. The reviewer channel: an API key in the environment silently reroutes the call, and a nested-session refusal that is not a real limit

**What.** Reported by the Arbiter's parallel terminal session (read-only, diagnosing the reviewer
channel), from reading TCC's and the skill's code and reproducing both halves by hand:

1. **The environment TCC was launched from decides which transport the reviewer uses.**
   `vendor_loader.child_env()` (`core/vendor_loader.py:247`) hands the child the whole `os.environ`
   plus four names of its own — confirmed here, the dict literally starts `**os.environ`. So a
   `GEMINI_API_KEY` in the shell that started TCC makes the skill take the API path instead of the
   `agy` CLI. The model TCC passes, `gemini-3.8-flash-high`, exists only in `agy`: over the API it
   is `HTTP 404 models/gemini-3.8-flash-high is not found for API version v1beta`. Reproduced both
   ways — with the key, 404; with `env -u GEMINI_API_KEY`, a full review in about 70 s.
2. **"The CLI cannot be run from an agent session" is our own marker, not a limit.** The refusal
   comes from `_NESTED_MARKERS` in the skill's `autosound_ai.py:675`, which matches `CLAUDECODE`;
   the same raw `agy --model … --input-format stream-json --output-format stream-json --print=`
   call with the critic package on stdin returned SUCCESS, 6730 characters, `num_turns: 1`.
   `AUTOSOUND_ALLOW_NESTED_CLI=1` turns it off.
3. **Ruled out as causes, each checked rather than argued:** `stdin=DEVNULL` from
   `core/child.py:263` (A/B on the same package, full answer both times), the model-name handover
   (`core/critic.py:285` → the skill's `REVIEWER_MODEL_VARS`), and a trimmed environment (see 1).
4. **What still has no answer**: `agy`'s raw output when TCC calls it is kept nowhere, so
   "SUCCESS, no answer" cannot be told apart from `num_turns: 0`. Proposed instead of patching TCC:
   a shim at `AUTOSOUND_CRITIC_BIN` that tees stdin and stdout to files and `exec`s the real `agy`.

**Where.** The Arbiter's machine, project EPY-Sep2026, TCC 0.1.41 / method 3.0.58; the terminal
session's own reproduction.

**Ours or external.** Ours and the skill's, one path: point 1 is TCC's `child_env` meeting the
skill's transport choice; point 2 is the skill's marker.

**Weight.** High: the reviewer is the second half of the tuning loop, and today it can fail two
different ways on one machine without saying which.

**Reproduces.** Both halves reproduced by hand by that session.

### 33. The set picker mixes series with rounds, and "серія 1" sometimes disappears

**What.** The picker above the measurement panel shows `серія 1 ●` and, opened, lists
`серія 1` over `cap_005 … cap_001`. The Arbiter: it looks out of place, and somewhere it vanished
altogether. It is NOT a stub — `_session_label` (`ui/tcc/measurement_panel.py:422`) turns a session
id of the shape `v1` into «серія 1», and the mock data cannot be the source (its ids are `v10`,
`v9`, `v8`). What the list actually holds is two different axes at once: a capture SERIES (`v1`) and
the ROUNDS of a config (`cap_001…`). The code's own comment says the two are different axes and
still puts them in one list with nothing between them.

**Where.** The Arbiter's screenshots, macOS, 0.1.41, project EPY-Sep2026.

**Ours or external.** Ours.

**Weight.** Medium: the picker decides what the whole panel is showing, and an entry whose kind is
unclear — and which comes and goes — makes the panel unreadable at the moment a round is run.

**Reproduces.** The mixing, always. The disappearing now has its trigger, seen a second time the
same day: a new round was created, `cap_006` appeared at the top of the list — and `серія 1` was
gone from it, leaving `cap_006 … cap_001` and nothing else. So the list is rebuilt wholesale by
`set_sessions` (`ui/tcc/main_window.py:3211`) when a round arrives, and whatever the series entry
came from is not in what that rebuild is given.

### 34. "Порядок зняття": one row at a time, where the reordering is always a block

**What.** Asked 2026-09-19. The capture-order dialog drags a single row, and the list it drags in is
long — `c p1_49 … c p9_49`, then `m-L p1_49 …`, nine positions per channel. Moving a channel means
nine drags. Wanted: select a GROUP of rows (a range, and non-adjacent ones) and drag them together.

**Where.** The Arbiter's screenshot, macOS, 0.1.41, the method's 49-position list.

**Ours or external.** Ours.

**Weight.** Medium, and it grows with the method: the 49-point grid turns a one-minute ordering into
several, and an ordering nobody finishes is a capture order that does not match REW — which is what
the dialog exists to prevent.

**Also asked (2026-09-19).** Once the order has been changed: a way to SAVE it deliberately, and a
way to COPY an order from RTA to SW and back. The dialog's own text says the order is kept per
method and reused next time — so what is missing is the person's hand on it: saying "keep this"
rather than trusting that it was kept, and not re-dragging the same order a second time for the
other method when the two are the same list in a different hat.

**Reproduces.** n/a — a change.

**Noticed in the same screenshot.** The rows read `c p1_49 (sw) (rta)` — the double suffix of
finding 30 point 3, here on every row of the list.

### 35. TCC aborted: a curve worker was destroyed while it was still running

**What.** The app died with `Abort trap: 6` while the Arbiter worked in the curve window ("Де саме?").
The log's last line before the restart is the cause, in Qt's own words:

```
2026-09-19 16:19:02,521 CRITICAL autosound_tcc: Qt: QThread: Destroyed while thread '' is still running
```

The crash report agrees and says WHERE: the faulting thread is `_CurveWorker`, and its stack is
`QThreadWrapper::run()` → `method_dealloc` → `subtype_dealloc` → `~QThreadWrapper` →
`QThread::~QThread()` → `QMessageLogger::fatal` → `abort`. So the destructor ran ON the worker's own
thread as `run()` was unwinding: the last Python reference to the thread object was dropped there,
and Qt calls `qFatal` when a QThread is destroyed while still running. A second `_CurveWorker` was
alive at the time, blocked in `socket.recv_into` — waiting on REW.

**Where.** The Arbiter's Mac (MacBookAir10,1, macOS 26.7), 0.1.41, project EPY-Sep2026, 16:19:02,
after about 3.5 hours of session. Crash report incident `0D55AB43-FC83-423C-8414-A8974C15F570`.

**Ours or external.** Ours.

**Weight.** High: the whole application dies, and a step in progress (1.1, just started at 16:12)
goes with it.

**Reproduces. Yes, and the Arbiter walked it twice (2026-09-19).** In the curve window: pick a set
in the picker (`cap_006`), then pick a GROUP (`Ms`) — and the app dies. Picking a different set and
choosing a group again killed it the second time too. The state it dies from is the one described
below: the titles on screen still belong to the PREVIOUS set (`_49`), the read of the first of them
has already failed with `Не вдалося прочитати з REW: c p1_49 (sw): KeyError` (finding 36), and a
worker is live on REW when the group selection starts another one.

**Investigated 2026-09-20; one hypothesis killed, one defect found and fixed, the chain NOT yet
closed.**

*The log, collected from the Arbiter's machine.* The fatal line appears **three** times, not two:
`2026-08-27 18:30:47` — sixteen seconds after a launch, so a long session is not a precondition —
and `2026-09-19` at `16:19:02` and `16:25:09`. TCC logs nothing else around them: the REW read
failure of finding 36 is a status line in the window, not a log record.

*Hypothesis killed.* `qt_shutdown.detach` connects `finished` to a bare lambda, and a bare lambda
has no receiver object — so the discard looked like it would run DIRECTLY on the worker's thread
and destroy the object there, which is exactly the shape of the recorded stack. Probed instead of
assumed: the lambda runs on the GUI thread (`QThread` affinity is the GUI thread and PySide queues
on it). The docstring is right and this is not the path.

*Defect found and fixed — the same fatal line, a different door.*
`measurement_panel._replace_worker` waited six seconds and then **assigned anyway**. A worker that
outlasted the wait lost its last reference on that line — these workers have no parent — and
`~QThread` against a running thread is `qFatal`. That is the F-027 half-guard, still live here
while the panel's own `shutdown()` had been fixed for it. It now goes through
`qt_shutdown.stop_or_detach(previous, _REPLACE_WAIT_MS)`, and a test covers a worker that
deliberately outlasts the wait. The `2026-08-27` crash, sixteen seconds after a launch, fits a
scan being replaced; whether it accounts for the two on `2026-09-19` is NOT established.

*The mechanism, MEASURED rather than reasoned about (2026-09-20).* Drop the last external
reference to a worker while it is running, and the process aborts — `exit 134`, with this exact
fatal line. A `weakref.finalize` on the worker says where: **the destructor runs on the WORKER's
own thread, right after `run()` returns**, because from the moment the external reference goes the
running frame holds the only one, and the frame dies when `run()` does. That is the recorded stack
of this finding, reproduced in eleven lines.

> **A bounded wait is not a guard. Whoever drops the last reference to a live worker aborts the
> application.**

*Three more doors of the same class, found by that rule and closed.* `MainWindow.stop_workers`
waited on `_rew_ping` (2 s), `_contract_worker` (3 s, after `cancel()`) and `_capture_check` (5 s)
— and then carried on, leaving each in its attribute to die with the window. The block's own
comment already said what that costs; the answer written under it was the wait. All three now go
through `qt_shutdown.stop_or_detach`, the move `_reviewer_probe` and `_cli_catalogue` two lines
below were already making. The contract check keeps its `cancel()` first — killing the child is
the only lever that reaches a thread blocked reading it.

*What is still open.* Which door the two `2026-09-19` crashes came through is still not named.
`_contract_worker` is the strongest candidate and fits the log — `spawn: contract.py` runs after
every tool call, and one is spawned at `16:12:07` before the `16:19:02` crash and at `16:24:10`
before the `16:25:09` one — but its start site is guarded and its shutdown path only runs on a
close, which did not happen. So the rule is now enforced in four places and the specific chain is
not proven.

*Instrumented instead of guessed further (2026-09-20).* `qt_shutdown.watch(self)` is called from
every worker's constructor, and it logs a WARNING naming the class when that worker is destroyed
after it STARTED and before it finished — which is the fatal shape, and the line lands immediately
before Qt's own. Qt's message names no class and this app has eight kinds, which is why three
collected crashes could not be pinned to one by reading the log. Narrowed to started workers after
the first run: a worker built and never started has not finished either, and the suite alone
produced five such lines, which is exactly the noise that would bury the real one.

*The Arbiter's newest reproduction, 2026-09-20, changes the shape of the question.* It died after
choosing set **`cap_007`** and with NO pair/group picked, having switched other sets before that
without trouble. On `0.1.41` a set switch starts no worker of its own, so what died had been
running already — and "other sets were fine" points at the set rather than at the act. His own
read: *"може щось з сетом, бо там були проблеми і в них точно може чогось не бути"*. The window's
offer list is a UNION of REW's titles and the measurement panel's round (`main_window._open_curves`),
so a set missing something can put a title on offer that REW does not hold — which is the same
root as finding 36's `KeyError`. Hypothesis, not a verdict: the next run with this build names the
worker in the log, and that is what settles it.

**ROOT CAUSE, named by the app's own log, 2026-09-20 13:13:59.** The instrumented build
reproduced it on the first run, and the two lines are consecutive:

```
13:13:59,509 WARNING  worker _CurveWorker destroyed on a worker thread while it had NOT finished
13:13:59,510 CRITICAL Qt: QThread: Destroyed while thread '' is still running
```

`QThread.start()` is **asynchronous**: it returns before the thread is scheduled, and in that
window `isRunning()` is still False while `isFinished()` is False too. `stop_or_detach` read only
`isRunning()` and returned immediately — handing the worker to nobody — so the caller's very next
line, `self._worker = <new>` in `curve_dialog._reload`, dropped the last reference to a worker
that was about to run. It then ran, and destroyed itself on its own thread when `run()` returned.

That is why it needed two reloads close together, why `cap_007` was not special, and why other
sets switched fine: it is a RACE against thread scheduling, not a property of a set. The
Arbiter's read that something was wrong with the set is a coincidence of timing — which is
exactly why this was measured rather than reasoned about.

**Fixed:** "not running" no longer means "safe to drop". Only a thread that is genuinely
`isFinished()` is let go; anything else is held. "Never started" and "started, not scheduled yet"
cannot be told apart from outside — both read not-running and not-finished — and only the second
is dangerous, so the first is held too, at the cost of one reference. Pinning genuinely finished
workers would be a leak that grows with the session, which is why `isFinished()` is the test.

**AND IT STILL CRASHED — so the answer stopped being a call-site fix, 2026-09-20.** The Arbiter
installed that build, reproduced twice (13:20:06 and 13:21:31, both after a restart at 13:19:37),
and the log read `_CurveWorker destroyed on a worker thread` again: destroyed with **nobody**
holding it. Five fixes had gone in — `_replace_worker`, three waits in `stop_workers`, the
start/running window — and the state they all guard against was still reachable. Chasing a sixth
call site is a losing game when the rule is "any caller can do this".

*What the journal said, and it is not what anyone guessed.* The rounds he switched between:

| round | titles |
|---|---|
| `cap_001`, `cap_002`, `cap_004`, `cap_005` | 16-21 |
| **`cap_003`** | **35** |
| **`cap_007`** | **73** |

Both crashes landed on the biggest set of their run. So "something wrong with the set" was real
and it is the SIZE: 35 and 73 titles is a fetch long enough that the next switch arrives while it
is still in flight. Nothing to do with the contents.

*Reproduced locally, off his machine.* `CurveDialog` over a deliberately slow bridge, a group
chosen, rounds switched in a loop - the fatal line appears. That is the loop this was finally
solved in, rather than a round trip to the Arbiter per hypothesis.

**THE FIX IS STRUCTURAL.** `qt_shutdown.watch` - already called from every worker's constructor -
now holds the worker in a module-level `_LIVE` set from `start()` until `finished`. A running
worker therefore always has a reference, whatever a caller does with its own attribute, and
"destroyed with nobody holding it" stops being a reachable state.

*One measurement decided how.* Connecting to the `started` SIGNAL does not work: it is emitted on
the new thread and delivered queued, so it lands only after the event loop turns - `live()` read
**0** straight after `start()`, and the window between `start()` and the loop turning is exactly
the dangerous one. `watch` wraps `start` instead, so the reference is taken synchronously.

Both reproductions are clean afterwards, and `live()` empties - checked, because a guard that
holds for ever is a leak rather than a fix.

The five call-site fixes stay. They are correct on their own terms - a wait is still not a guard -
and they are what keeps a worker from being left running with nothing asking it to stop.

**Where to start, as a hypothesis and not a verdict.** The guard is already there and did not hold:
`ui/tcc/curve_dialog.py` `_stop_worker` hands a slow worker to `ui/tcc/qt_shutdown.stop_or_detach`,
which keeps it alive in `_DETACHED` and discards it when `finished` arrives. The stack says the
object died on the worker thread during `run()`'s unwind, so what has to be measured is whether the
`finished` → `_DETACHED.discard` can run BEFORE the thread is really finished, leaving the run
frame's own reference the last one. `detach`'s docstring already notes the object's affinity is the
GUI thread, which is what makes that ordering possible.

### 36. Choosing a set does not change the list of drivers, and the read fails on the old titles

**What.** In the curve window the Arbiter picked set `cap_006`; the driver list under it still held
the `_49` titles — `c p1_49 (sw)`, `m-L p1_49 (sw)`, … — i.e. the previous set's. The window then
said `Не вдалося прочитати з REW: c p1_49 (sw): KeyError`, which is TCC asking REW for a title that
is not in the set it is now showing. Picking a group on top of that state crashes the app
(finding 35).

Also visible in that picker: `серія 49` and `серія 1` are BOTH back, above `cap_007 … cap_001` —
the two axes of finding 33 in one list, and the entry that vanished earlier is present again.

**Where.** The Arbiter's screenshots, macOS, 0.1.41, project EPY-Sep2026, curve window "Де саме?".

**Ours or external.** Ours. The `KeyError` is TCC's own read path reporting a title REW does not
have; REW is answering correctly.

**Weight.** High: it is the state the crash grows out of, and on its own it shows curves of one set
under the name of another — which is a wrong answer, not just an empty one.

**Reproduces.** Seen on the same session as 35; the two were reached by the same steps.

**Root cause, found 2026-09-20 and reproduced in a test.** Choosing a round narrowed what may be
chosen and never touched what IS chosen. `_on_version_chosen` rebuilt the choose menu
(`_selectable()` intersects `_options` with the round's own titles) and then did nothing unless a
group was picked — while `_chosen()` is what the chips name, what `_CurveWorker` fetches and what
`statement()` reports. So after the switch all three still belonged to the pass he had left, the
window drew one set under another's name, and the next fetch asked REW for `c p1_49 (sw)`, which
the chosen set does not contain: `KeyError`.

That is the failure `_set_selection`'s own docstring is written against — "two controls each
holding half a selection is how a window comes to draw one thing and report another" — arriving by
the one path that did not go through it.

**Fixed:** `_on_version_chosen` re-points the selection through `_set_selection`, at
`_same_rows_in(round_id)`: the round's rows for the same channels and the same method, because
choosing a set asks "show me these drivers in that pass" — the channels travel, the version does
not. Nothing answering falls back to the whole round. A round REW no longer holds keeps its
existing branch (`curveRoundEmpty`) and leaves the plot alone rather than blanking it.

**A second defect, found while probing that path and fixed with it.** `_sync_version_combo` adds a
fallback row for `select` so a version REW no longer lists can still be stood on — but it adds it
BEFORE the round rows, and every caller passes `select` straight from `currentData()`. With a
round chosen, `findData("round:cap_006")` could not find it yet, so each call added a second row
for the same round, labelled `серія round:cap_006`. Live already through the group path; the fix
above would have run it on every pick. Both are covered by tests in `tests/test_curve_view.py`.


### 37. A failed read leaves the PREVIOUS curves on screen under the new selection

**What.** The Arbiter picked the pair `Ms` in `cap_007`. The chips read `m-L_49 (sw)` and
`m-R_49 (sw)`, the status line read `Не вдалось прочитати з REW: m-L_49 (sw): KeyError;
m-R_49 (sw): KeyError` — and the plot went on showing **nine** curves from the previous
selection, `c p1_49 (sw)` … `c p9_49 (sw)`, with the legend naming them.

So the window DRAWS one set and REPORTS another. Which is exactly what `_set_selection`'s own
docstring is written against: *"two controls each holding half a selection is how a window comes
to draw one thing and report another"*.

**Where.** The Arbiter's screenshot, 2026-09-20, `0.1.41` at `df524a8`, project EPY-Sep2026,
curve window "Де саме?", phase view, protection off.

**Ours or external.** Ours.

**Weight.** High, and higher than a crash: a crash is obvious, this is a wrong answer that looks
like a right one. Every reading taken off that screen — a junction, a delay, a polarity call —
would be taken off the wrong drivers.

**Root cause, read off the code.** `_on_failed` sets the status text and nothing else:

```python
def _on_failed(self, message: str) -> None:
    self._status.setVisible(True)
    self._status.setText(i18n.t("curveFailed").format(error=message))
```

`_on_curves` is what calls `self._view.set_traces(...)`, so when every title in a selection fails,
nothing replaces what is on the plot. The selection, the chips and `statement()` have already
moved; only the drawing has not.

**Not the same as the deliberate "keep what is on screen" case.** `_apply_group`'s
`curveGroupEmpty` branch keeps the curves ON PURPOSE — there nothing was fetched and nothing
changed, so an empty plot would be worse. Here a fetch happened, it failed, and the selection is
already something else. The two look alike and are opposites.

**Reproduces.** Any selection REW cannot answer for — which finding 38 below makes easy to reach.

**Closed 2026-10-01.** Fixed: `curve_dialog._on_failed` takes the previous curves off the plot before it reports the failure.

### 38. Titles REW does not hold are offered, chosen and then asked for

**What.** `m-L_49 (sw)` was offered in the picker and selected, and REW answered `KeyError`: it
does not hold a measurement by that name. The name came from the project's journal —
`cap_007` records 73 taken titles — not from REW.

**Where.** Same session and screenshot as 37.

**Ours or external.** Ours. REW is answering correctly; TCC asked for something that is not there.

**Weight.** Medium on its own, high in combination: it is the supply of failed reads that finding
37 turns into a wrong picture.

**Root cause.** `main_window._open_curves` builds the window's offer list as a UNION:

```python
available = sorted(set(titles) | set(available or []) | set(self._meas_panel.known_titles()))
```

and the panel passes its whole round. `_selectable()` then intersects that with the round's own
titles, so a title the JOURNAL knows and REW does not survives both filters. Named while fixing
finding 36 on 2026-09-20 and deliberately not touched then, because the union is there on purpose:
the window is opened over what the model names, which need not be what REW is holding this second.

**What has to be decided, not just coded.** Either the picker marks a title REW does not hold (the
kind picker already greys rows, `_mark_availability`), or the offer list stops being a union and
the window says what it cannot show. The first keeps the window openable over a name REW has lost;
the second is simpler and narrower. This is the Arbiter's call.

**Closed 2026-10-01.** Fixed: titles REW could not answer for are greyed and cannot be ticked (`curve_dialog.py`, finding 38).

### 39. SIGSEGV in Qt's raster painter while dragging a curve — no Python error at all

**What.** The Arbiter dragged the tweeter's curve to the right in the curve window and the app
died. Nothing in `tcc.log`: the last line is an ordinary `stray window` at `13:41:58` and then the
file simply ends. That absence is itself evidence — the earlier crashes all left
`QThread: Destroyed while thread '' is still running` first. This one is a **segfault**, not an
`abort()`, and it gave Python no chance to say anything.

**Where.** The Arbiter's Mac, 2026-09-20 13:43:41, `0.1.41` at `df524a8`, project EPY-Sep2026,
curve window "Де саме?", PHASE view, `cap_007`, nine `c pN_49 (sw)` curves on screen. Report
`python3.12-2026-09-20-134341.ips`.

**The stack, main thread:**

```
QRasterPaintEngine::stroke(QVectorPath const&, QPen const&)   <- SIGSEGV
QPaintEngineEx::draw(QVectorPath const&)
Sbk_QPainterFunc_drawPath                     (QPainter.drawPath from Python)
QGraphicsPixmapItemWrapper::sbk_o_paint       (a pyqtgraph item's paint())
QGraphicsView::paintEvent
```

`EXC_BAD_ACCESS`, `KERN_INVALID_ADDRESS at 0x0000000b7f7ffff0` — a wild pointer roughly 49 GB out,
which is what a stroker buffer overrun looks like rather than a null dereference.

**Ours or external.** The fault is inside Qt's raster engine, so the CODE is external — but what
is handed to it is ours. Not to be filed as "a Qt bug" until what the path contains has been
looked at.

**Weight.** High: the whole application dies, silently, during an ordinary interaction.

**Where to start, as a hypothesis and not a verdict.** The screenshot of that very session shows
the phase view above ~4 kHz as a solid wall of wrapped ±180° transitions across NINE curves —
a path with an enormous number of near-vertical segments, redrawn on every mouse move of a drag.
Two things to measure before touching anything:

1. **The size of the path.** How many points per curve reach `drawPath` on the phase view, and
   what `QPainter` antialiasing/clipping is on. A stroker overrun is a size problem far more often
   than a content one.
2. **Whether any coordinate is non-finite.** A shift applied on the phase view could produce
   `inf`/`nan` in `_shifted`; the raster engine does not survive those. Cheap to check and cheap
   to rule out.

**Both of those measured, 2026-09-20 — and both hypotheses came out WEAK.**

*Non-finite coordinates: ruled out.* On the phase view `_shifted` ends in
`(shifted + 180.0) % 360.0 - 180.0`, so whatever the delay, the drawn value is bounded to ±180.
The x axis is the frequency array unchanged. There is no arithmetic on that path that can produce
`inf` or `nan`.

*Path size: much weaker than it looked.* The view already draws with
`pg.setConfigOptions(antialias=False)` and `self._plot.setDownsampling(auto=True, mode="peak")`,
so what reaches Qt is already reduced to roughly the pixel count, not the sample count. And a
local probe — nine wrapped-phase curves of 60 000 points each, 540 000 in total, dragged through
40 delay steps offscreen — survives. So "the wall of vertical lines is too big to stroke" does not
hold up on its own.

*What that leaves.* The crash needs the real on-screen paint path (a backing store and a window
server), which the offscreen platform does not exercise, and probably something else that was on
that screen: the Σ strip, the two markers, the delay lines, the legend of nine. Guessing further
without the real window is how the first three hypotheses of finding 35 were spent.

**What would actually settle it,** in order of cost to the Arbiter:

1. The same drag with the window NOT maximised and with Σ off — if it survives, the extra item is
   the lead, and that is one run rather than a build.
2. Whether it reproduces on the magnitude view with the same nine curves. Phase is the view with
   the wall; magnitude is not.
3. Only then a build that logs what `paint()` is handed on the phase view.

**One thing that changed under it.** At the moment of the drag the plot was in finding 37's state:
nine curves drawn, two named, both reads failed. That state no longer exists (37 is fixed).

**FOUND — a non-finite coordinate after all, and not where it was looked for first.** The search
above was for `inf`/`nan` in the CURVES, and there is none: the phase view wraps to ±180. The Σ
overlay is the other half of the picture and was not checked, because Σ lives on a **ViewBox of
ours** rather than on pyqtgraph's plot — so log mode does not transform it and
`_draw_sum_on_axis` takes `log10` by hand:

```python
x = np.log10(freqs) if self._log_x else freqs     # unguarded
```

`log10(0)` is `-inf`. A linear frequency grid whose first bin is 0 Hz is REW's own shape (an
FFT's DC bin), so this is the ordinary case, not a malformed one. Measured directly:

```
min freq: 0.0
non-finite x in the sum path: 1
```

`connect="finite"` does not save it — the point stays in the item's data — and that coordinate
goes to `QPainter.drawPath`, which is exactly the frame under `QRasterPaintEngine::stroke` in the
crash report. **Σ was on in the Arbiter's screenshot.**

The same conversion twenty lines down already guarded it — `math.log10(x) if self._log_x and
x > 0` — so the rule was known and applied in one place of two.

**Fixed:** non-positive frequencies are dropped before the log rather than passed through it, and
a test asserts no non-finite x reaches the sum curve.

**CONFIRMED BY THE ARBITER, 2026-09-20.** He ran the build with Σ on and tried to break it the
way he had: «все ок». That is the proof this finding was missing — the fix was a mechanism that
matched the recorded stack, reproduced nowhere on this machine (neither offscreen nor on-screen,
nine wrapped-phase curves at 540 000 points dragged through forty delay steps), and a match is not
a reproduction. His run is what closes it.

Worth keeping for the next one of these: the two hypotheses prepared in advance — "the path is too
big" and "a non-finite coordinate in the CURVES" — were both measured and both wrong. The answer
was a third thing neither of them covered, in the one item on the plot that does its own axis
transform. Reading the stack for WHICH item was painting is what found it.

### 40. "Could not reach GitHub" while GitHub was fine: the only `git` on the machine was broken

**What.** After `v0.1.42` was tagged, the Arbiter's window showed `ТСС 0.1.41 — не достукався до
GitHub` while the very same code, run from his shell on that machine, answered
`latest='0.1.42', newer=True, updatable=True`.

**Where.** His MacBook, 2026-09-20, app installed from the wave branch at `80b0544`.

**What was ruled out, each by a command rather than by reasoning:**

* not `PATH` — the log shows `git --version` and `git ls-remote` both spawning;
* not the app's no-prompting environment — `env GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never
  GIT_ASKPASS= git ls-remote --tags <repo> 'v*' 'v*^{}'` returns the full tag list on BOTH
  machines;
* not a slow network — the log's next line lands eleven milliseconds after the spawn, which is an
  immediate failure, not a round trip.

**CAUSE FOUND, 2026-09-20, and it was in the app's own report all along.** The
`[Command-line tools]` block of the very same dialog, two lines below the update row, printed it
in full:

```
git  xcrun: error: unable to load libxcrun (... fat file, but missing compatible architecture
     (have 'arm64,arm64e', need 'x86_64'))   (/usr/bin/git)
```

`/usr/bin/git` on macOS is only a shim for the Xcode Command Line Tools, and on that machine it
could not run at all. It was also the ONLY git there (`which -a git` → one line), so every probe
the app made failed — updates, and the project backup with them.

**It had worked before.** The Arbiter has updated through this window more than once, so the shim
did not fail from the start: it broke at some point on that machine, and the likeliest mover is a
macOS update, which is what touches the Command Line Tools. That is a reading, not a measurement,
and it is written as one — the moment it broke was not captured by anything, which is precisely
what the logging below changes for next time. `brew install git` fixed it
outright: the bundle's own launcher already puts `/opt/homebrew/bin` ahead of `/usr/bin`, so a
real git is preferred the moment one exists. The row then read `0.1.42 — актуальна` and the
method's row offered `3.0.59`.

**What is still not established,** and is recorded rather than guessed: why that shim failed only
when the app was launched from Finder. From a terminal — including the app's own interpreter,
`~/.local/share/uv/tools/autosound-tcc/bin/python3` — the same `/usr/bin/git` answered fine. The
architecture was identical either way (`platform.machine()` → `arm64` in both), both bundles
behaved the same, and nothing in `desktop_entry.py` touches architecture. Not chased further: the
machine has a working git now, and the cost of the next step was higher than what it would buy.

**Ruled out on the way, each by a command rather than by reasoning:** PATH to git (the log shows
git spawning), the app's no-prompting environment (the exact invocation returns the full tag list
on both machines), a slow network (the failure landed eleven milliseconds after the spawn), and
Rosetta (`arm64` on both sides).

**What changed, and it is the part worth keeping.** The app HAD the sentence and showed a
different one. Three things were wrong with how it answered, and all three are fixed:

* `updates._git` logged that git was SPAWNED and never what it answered (`37fac7a`), so every
  outcome looked alike;
* two of the three failure paths did not log even then — the exception path returns before the
  exit-code line, and exit 0 with empty output is a third answer, not a failure (`b39014f`);
* the row itself said `no_network` for all of them. It now says `probe_failed` and carries git's
  own words (`22643c0`).

None of that fixes a machine. It means the next one says in one line what this one cost a
session — which is the same lesson finding 35 bought: an event logged without its outcome makes
every outcome look alike.

**If it comes back:** `grep "git ls-remote exited" ~/Library/Logs/autosound-tcc/tcc.log`.

### 41. A session started in a terminal is not named: the footer shows TCC's own pick

**What.** The Arbiter started a project with `agy` in a terminal, then opened TCC on the folder.
Everything worked: the MCP connected, the fields updated, the dialog area showed updates. But the
AI model in TCC's footer was TCC's own pick, not the model the session was running. «Ідеально було
б підхопити поточну модель і показати (хоч там у нас такої моделі не може бути).»

**Where.** The Arbiter's Mac, 2026-09-23, with `agy`.

**Ours or external.** Ours.

**Weight.** Medium. The footer names a model that is not answering.

**Status.** Built 2026-09-23 on `wave-0.1.43`. The MCP handshake names the client (`antigravity`
becomes `agy`). `get_tcc_state(model=…)` asks the session to name its model. The footer shows
«⌁ у терміналі: agy · <model>» beside the picker, which keeps saying what TCC would start. TCC's
own in-app session is not mistaken for it. Live check: the next `agy` session on this project.

## The Arbiter's test of v0.1.43 on Windows (2026-09-23) — the W-3 pool

Recorded, not diagnosed (`WAVES.md`: while the user tests, a session only records).

### 42. The key screen's answer mixes two languages

**What.** Saving a key in an English window reads «Stored: GEMINI_API_KEY збережено: сховище
Windows, зашифроване вашим входом (DPAPI)». TCC's own prefix follows the UI language; the method's
sentence is Ukrainian whatever the UI says.

**Where.** Windows VM, v0.1.43 with method v3.0.60, the Reviewer key screen.

**Weight.** Low: wording.

**Issue:** tcc#65 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#65. The saved line is TCC's now, in the window's language, from the method's `key status` (which store holds it); the method's own sentence is the hover.

### 43. Starting from the desktop shortcut: two terminal windows before the splash

**What.** A terminal, then a second one behind it, then the splash. The window itself now comes up
on the first start (F-039's question answered: it does). Seen the same way on both Windows
machines.

**Where.** Windows VM and the Arbiter's second Windows machine, v0.1.43.

**Evidence.** The VM's `tcc.log` (copied to `~/Downloads/тест/vm-logs/`), each start at 14:35:44
and 14:38:03: `spawn: agy models`, then `claude.EXE auth`, `python.exe …\autosound_ai.py`, `git`,
`contract.py`. On the second machine the Arbiter saw `agy` open before the splash and took it as
the model check.

**Weight.** Medium: the console flashes are the class TCC-006 was about.

**Issue:** tcc#62 on W-3 (collected 2026-09-26), assessed, no `ok` yet.

### 44. A pin made from the desktop shortcut does not merge with the running window (F-044, narrowed)

**What.** Pinned through the desktop icon's menu (More → Pin to taskbar), a start from the taskbar
gives two icons. Unpinned and pinned again from the RUNNING window's taskbar icon, it stays one
icon whether TCC is started from the desktop or from the taskbar. No second terminal in any of
these starts.

**Where.** Windows VM, v0.1.43.

**Weight.** Low: two icons, both work.

**Issue:** tcc#62 on W-3 (collected 2026-09-26), assessed, no `ok` yet.

### 45. Entering «Режим контролю» on Windows flashes a series of windows in the middle of the screen

**What.** On the switch INTO control mode, several windows (not terminals) appear one after
another in the centre of the screen. Switching back is clean.

**Where.** Windows VM, v0.1.43.

**Evidence.** The VM's `tcc.log` at the switch (14:41:45): no process spawned; three
`QWindowsWindow::setGeometry: Unable to set geometry` on the main window (1996×2314, 2086×2314,
3600×2044 on the «Parallels Vu» screen).

**Weight.** Medium: visible on every switch.

**Issue:** tcc#62 on W-3 (collected 2026-09-26), assessed, no `ok` yet.

### 46. Quitting while REW is being pinged: "worker destroyed on the GUI thread while it had NOT finished"

**What.** The log line finding 35 names as the abort, six times in one sitting. Each one comes a
moment before the next `started:` line, which is a quit. No crash was reported.

**Where.** Windows VM, v0.1.43, `tcc.log` 14:38:02 – 14:42:25 (`_RewPingWorker`).

**Weight.** Medium: it is the line that preceded the crashes of finding 35.

**Issue:** tcc#63 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#63. Not a destruction: the watch's `weakref.finalize` also runs at interpreter
exit for what is still ALIVE, and a ping to an offline REW was still waiting for its timeout at
quit — so the line said "destroyed … this is the abort" about a thread nobody destroyed. The
suite's own run ended with the same two false lines (`_CliCatalogueWorker`); they are gone with
`atexit = False`. A thread that would not stop at exit is named by `destroy_application`.

### 47. Control mode: the tables carry the full window's own menus, and EQ has no way back

**What.** The Arbiter's list (2026-09-23, with screenshots):

1. Inside «Таблиця-V», «Таблиця-О» and «EQ», the full window's detail menu is shown again
   (Рівень · Затримки · Фази, and on EQ also Таблиця · EQ). It duplicates the main tabs, which is
   confusing.
2. In the left panel, a click on «params · усі параметри таблицею» opens no table: not the virtual
   one, not the output one, not the input one (which exists, even though it is empty). A click on
   EQ in the left panel does nothing either.
3. «Закрити ✕» is not needed in this mode: hide it.
4. «порівняти з» belongs up at the level of the main tabs, and the full-mode menu should be hidden
   entirely.
5. **The main point:** EQ from a table («1 band ▸», or the menu's EQ) turns the table tab into the
   EQ band view (PK 1950 Hz, «Копіювати EQ с») instead of switching to the EQ tab, and there is no
   way back without leaving the mode. The «EQ» tab itself shows the output table, not the EQ.

**Where.** v0.1.43, «Режим контролю».

**Weight.** High for 5 (a dead end); medium for the rest.

**Prototype (2026-09-25, on the Arbiter's word).** A clickable mockup of both modes, three EQ views
(A/B/C) and findings 65–66: https://claude.ai/artifact/12URm52ozKpbTRhPnLRPiU (source
`hub/scratch/tcc/dsp-tables-prototype.html`; it goes to a throwaway branch once a view is chosen).
The session's own proposals are marked ◇ there: a «Таблиця-I» tab, the EQ's channel actions in the
EQ's own header, and the three views themselves.

**Built (2026-09-25, the Arbiter's OK and «терміново»):** tcc#51, commit `3b7003a` on
`wave-0.1.44`, EQ view A. The prototype itself is kept on the throwaway branch
`proto/f47-dsp-tables` (`f6e13db`). One placement differs from the prototype: in control mode
«порівняти з» sits in the header left of «Активний TCC», not at the right of the tab row, because
half a screen holds the eight tabs with their dots or the list, not both (measured offscreen).


### 48. The SDK list still offers Opus 5 and Fable 5 after Anthropic shipped Opus 5.5 and Fable 5.1

**What.** The model picker's Claude rows are «SDK · Claude Opus 5», «Sonnet 5», «Fable 5», while
Anthropic now serves Opus 5.5 and Fable 5.1. The AGY rows below them are current (Gemini 3.8, 3.7,
3.6 Flash). The Arbiter's question: do the old ones still work, and how is the list kept current?

**Where.** Windows, the AI model picker (two screenshots, 2026-09-24).

**Context (from the code, not a diagnosis).** The Claude rows are a list shipped in
`core/model_choices.py` (`SDK_MODELS`, dated `SDK_MODELS_VERIFIED = "2026-08"`). It is refreshed from
Anthropic's Models API only when `ANTHROPIC_API_KEY` is set, which the SDK route (own `claude`
login) normally does not have. The AGY rows come live from `agy models`.

**Weight.** Medium: the newest Claude models cannot be picked, and nothing says the list is old.

**Issue:** tcc#64 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#64. The answers: the old ones still work — Opus 5 and Fable 5 are still served
(checked against the Claude API reference of 2026-06-24 bundled with Claude Code); the list is
kept current by the Models API only where an Anthropic API key exists, which the SDK route
(the person's own `claude` login) normally has not. So: Opus 5.5 (`claude-opus-5-5`) and Fable 5.1
(`claude-fable-5-1`) added beside their predecessors, the list dated 2026-09-26, and every row it
supplies says on hover that it is TCC's own list and when it was checked. The default model is
unchanged (`claude-opus-5`): that is the Arbiter's to move.

### 49. «In focus now»: a tall panel stretches the measurement rows apart

**What.** When the bottom-right zone is taller than its content, the rows of the measurement list
(`tw-L_1 (sw)` … `sw_1 (rta)`, seven per column) spread out to fill the height, with large gaps
between them, and the column headers («SOLO (SW)», «SOLO (RTA)») grow too. The rows should stay
compact at the top.

**Where.** Windows VM, «In focus now», measurement task (screenshot, 2026-09-24).

**Weight.** Low: layout; everything stays readable.

**Issue:** tcc#60 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#60. The spare height goes below the last row (a row stretch), so the rows and the
headers stay compact at the top.

### 50. The theme button: the icon alone is enough, the word «theme» is not needed

**What.** The header's theme switch reads «◐ theme». The Arbiter: the icon was enough and clear on
its own; the word adds nothing.

**Where.** Windows, the window header (screenshot, 2026-09-24).

**Context (from the code, not a diagnosis).** The button has read «◐ theme» since the first Qt shell
(`ef59ecf`, 2026-07-26). Since `e5ab9fc` (2026-09-23, in v0.1.43) it shrinks to «◐» alone when
the header is squeezed, so a narrow window showed the icon only and a wide one shows the word too.

**Weight.** Low: wording.

**Issue:** tcc#65 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#65. The button is «◐» alone; the word is its hover.

### 51. The light-grey text strains the eyes, in both themes and in more places than one

**What.** The faint grey used for secondary text is hard to read and tires the eyes. The example
is the menu's section header «ПРОЄКТ» above «Відкрити теку проєкту»: pale grey on light grey in the
light theme, dim grey on dark in the dark one. The Arbiter: "it is not only here", and asked for a
colour that reads easily. Asked as "let's change it" during the collection, so recorded here and
built after it.

**Where.** Windows, the main menu, light and dark theme (two screenshots, 2026-09-24).

**Weight.** Medium: it is felt all the time, and it is everywhere this grey is used.

**Issue:** tcc#65 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#65. `faint` read at 2.3–3.2 : 1 on the panels; it is #7d8999 dark and #687380 light now, about 4.5 : 1 on a card (WCAG AA for text), still a step below `muted`.

### 52. Dark theme: the search box in «Моделі у виборі генератора» hides what is typed

**What.** In the dark theme the dialog's search field is white, and the text typed into it
(«sonnet») is pale grey on that white, so what is being typed can barely be seen. The list below
does filter by it.

**Where.** Windows, dark theme, the dialog «Моделі у виборі генератора» (omp's catalogue, 28
models), screenshot 2026-09-24.

**Weight.** Medium: the field cannot be read while typing.

**Issue:** tcc#65 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#65. Every plain text field is themed (background, text, border, focus); unstyled, Windows drew it white under the dark theme's light text. The field inside an editable combo or a spin box draws nothing of its own.

### 53. A model through omp does not start: `OmpSession.__init__() got an unexpected keyword argument 'language'`

**What.** Picking «Claude 4 Sonnet» through omp and sending a message: TCC says «Запускаю Claude 4
Sonnet — перший хід читає скіл і стан проєкту, тому повільний», and right after it «ПОМИЛКА
СЕСІЇ: ⚠️ TypeError: OmpSession.__init__() got an unexpected keyword argument 'language'». The
session does not start.

**Where.** Windows, light theme, the in-app AI dialog, route omp (screenshot, 2026-09-24).

**Weight.** High: the omp route cannot run a session at all.

**Issue:** tcc#56 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#56. The cause: wave 2.1 (`357f851`, 2026-09-11) put `language=` into the omp
factory instead of the SDK one beside it, so every omp start died on it — and the SDK session, the
one it was meant for, never got the language: its prompt said the project's language was English.
Both routes get it now (`MainWindow._session_factory`); omp takes the same rule through
`--append-system-prompt`, from a file (`.tcc/omp-language.md`). A live omp start reports ready
with it.

### 54. Switching away from a model that never started still runs «save state before the model change»

**What.** Right after finding 53 (the omp session failed to start), switching the model shows
«SYSTEM · LEDGER: Зберігаю стан проєкту перед зміною моделі…». No session was running, so there
was nothing to save before the switch.

**Where.** Windows, light theme, the in-app AI dialog (screenshot, 2026-09-24).

**Weight.** Low: a needless step and a misleading line; depends on how long it takes.

**Issue:** tcc#56 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#56. The cause: the failed session's thread had ended, and the window still held
its worker as live, so a model switch sent the save turn to a thread that never reads it and waited
the handoff's three-minute timeout. An ended worker is dropped now, and the switch starts the new
model at once (a Save says «only TCC's own state», a quit closes).

### 55. The critic picker stays red whatever model is picked

**What.** The «ШІ CRITIC» picker is red with «OMP · Gemini 3 Pro»; switched to a working model,
«SDK · Claude Opus 5», it is still red. The status beside it reads «gemini-3.8-flash-medium ·
6 d ago» with a red «!» both times, a model other than the one picked.

**The Arbiter's proposal.** If the red belongs to the status, let the status be red, and give the
picker its own three colours: grey, not known yet; green, works; red, does not work.

**Where.** Windows, light theme, the footer (two screenshots, 2026-09-24).

**History.** The red picker is W-2's S20 (`DECISIONS-W-2.md`): the closed picker turns red for a
model this launch saw refused.

**Weight.** Medium: the red says "broken" about a model that works.

**Issue:** tcc#58 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#58. The cause: the red was the WARNING tint — «the last review came from another
model» — and the last call, six days old, was made under an earlier pick, so it stayed red whatever
was picked. The picker now has its own three colours: grey not known yet, green it answered this
launch (`availability.answered`), red it cannot run. The warnings stay on the «!»; the status line
is red when the last review came from another model than the one picked.

### 56. The curve window tries to read from REW when REW is already known to be offline

**What.** With the REW indicator red, the curve analysis window («Where exactly?») still tries to
read the chosen curves, waits for the timeout, and only then says «Could not read from REW: m-L_1
(sw): URLError; sw_1 (sw): URLError; tw-L_1 (sw): URLError». TCC already knows at that moment that
REW is offline, so the wait and the per-curve error list are avoidable; the Arbiter expects it to
say so up front.

**Where.** Windows, light theme, the curve analysis window, series 1 · impulse · no group, three
curves chosen (screenshot, 2026-09-24).

**Weight.** Medium: a wait for a result that is known in advance, and a technical error in place
of "REW is offline".

**Issue:** tcc#61 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#61. The curve window reads the window's own REW indicator: red, and it reads
nothing, clears the plot and says «REW не відповідає … криві завантажаться, щойно він з'явиться»;
when the indicator turns green the held read goes by itself.

### 57. «next round» is picked, and its capture list is full and all green

**What.** The round picker in «In focus now» reads «next round ●»; the Arbiter: that is right, it
should be there. But the list under it shows every capture of the round (`tw-L_1` … `sw_1`, SW
and RTA) and every one of them green, «done», for a round that has not captured anything yet.

**Where.** Windows VM, «In focus now», measurement task, REW red (screenshot, 2026-09-24).

**Possibly related.** The Generator's greeting in the same project (screenshot of finding 18's
closing) names tcc#39: a live round is marked done from what REW holds, so the import form says
«expects no captures».

**Weight.** Medium: the list says the round is finished when it has not started.

**Issue:** tcc#60 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#60. With no round open the live task is the next round, a new pass: the closed
pass's takes no longer credit it (they stay on that round's own entry in the picker). A project
that never ran a round keeps its checklist, credited from the import store.

### 58. A critic through omp does not answer: the model name goes out with the `google-antigravity/` prefix

**What.** Two tries at a review from a Gemini picked through omp, both ending in `mode:
choose_model`, `model: null`, and the footer status «choose_model · just now»:

1. «OMP · Gemini 3.5 Flash Lite»: the call went through the API («Підключення до API», not «Виклик
   локального CLI 'agy'») as `google-antigravity/gemini-3.5-flash-lite`, and the key answered
   HTTP 404. The API's own list has `gemini-3.5-flash-lite` without the prefix.
2. `google-antigravity/gemini-3.8-flash-high`: TCC saw a tiered agy name, said «API її не
   обслуговує: шлях — CLI», called `agy`, and agy answered «model
   google-antigravity/gemini-3.8-flash-high is not recognized». agy's list has
   `gemini-3.8-flash-high` without the prefix.

The ledger then says «The reviewer needs a model name: this key can call gemini-3.8-flash-high, …
gemini-3.1-pro-high. Pick one and pin it as AUTOSOUND_CRITIC_MODEL=<model> in
~/.config/autosound/critic-env».

**The Generator's reading (not checked).** Neither route takes the `google-antigravity/` prefix:
the API takes names without a tier, agy takes names with a tier, both without the vendor.

**Where.** Windows, light theme, the in-app AI dialog, route omp for the critic (the Generator's
two answers pasted by the Arbiter, screenshots, 2026-09-24).

**Ours or the method's.** Not decided.

**Weight.** High: no omp-picked critic can answer.

**Issue:** tcc#57 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#57. TCC's: an omp pick is omp's selector, `provider/model`, and TCC handed it to the
reviewer script as it was; the script runs no omp. `model_choices.reviewer_model` drops the
provider for an omp pick, and every path that names the reviewer's model uses it — `call_critic`,
the session's `AUTOSOUND_CRITIC_MODEL`, the start-up probe and the state payload. Not checked live
(no API call spent); the Arbiter's next review from an omp pick is the check.

### 59. The critic chosen in the footer does not reach the project parameters

**What.** The footer's «AI CRITIC» reads «OMP · Gemini 3.5 Flash Lite»; «PROJECT PARAMS» still
reads «AI reviewer: Claude Sonnet 5»; the Generator, asked which critic it uses, names a third one,
`google-antigravity/gemini-3.8-flash-high`.

**The Arbiter's rule.** The parameter is updated right after the change. If the update goes
through the AI's queue, TCC shows that the change is waiting.

**Where.** Windows, light theme, the footer and «PROJECT PARAMS» (screenshots, 2026-09-24).

**Weight.** Medium: three places, three different critics.

**Issue:** tcc#58 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#58. The panel: the Generator, the effort and the gate refreshed it on change, the
reviewer did not — now it does. The third name was the session shell's `AUTOSOUND_CRITIC_MODEL`,
fixed when the session starts. `call_critic` reads the pick when called, so the next review goes
to the new one; a running session is told through the signal queue (`reviewer`), and the dialog
says it is sent and waits for the answer.

### 60. «порівняти з»: on Windows the open list shows «…» in place of every version

**What.** The closed picker reads «v_009»; opened, its list shows «—» and then «…» on every row,
so no version can be told from another.

**Where.** Windows, light theme, the table's «порівняти з» picker (screenshot, 2026-09-24).

**Weight.** Medium: the version cannot be chosen by name.

**Issue:** tcc#66 on W-3 (collected 2026-09-26), assessed, no `ok` yet.

### 61. The critic through agy is cut off mid-stream, and the channel steps down to the API

**What.** A review request came back as «Рецензент не відповів, і нічого не збережено як рецензію:
· CLI 'agy': The stream was interrupted. Please continue the task you were working on. Наступна
сходинка — буфер обміну (нижче); з ключем API — `--via api` для цього запуску
(setup-critic-channel.md §7)», with the package at
`process/reviews/2026-09-24T13-08-24-critic-package.md`. The Generator ran the same package with
`--via api`, and the critic answered.

**Where.** The in-app AI dialog (screenshot, 2026-09-24).

**Ours or the method's.** The method's: the message and the ladder are `autosound_ai.py`'s. Sent to
the skill as hub #204 TCC-030, on the Arbiter's word.

**Weight.** Medium: the review got through, but one cut stream moved it onto the metered API.

### 62. After the cut-off critic call, every model in the critic list turns red, Anthropic's too, then black again

**What.** Right after finding 61 (the agy stream cut off, the review then done through the API),
the critic picker's open list showed every model in red, the SDK Claude rows included. A while
later they were all black again. The critic itself worked.

**Where.** The footer's critic picker (the Arbiter's words, 2026-09-24; no screenshot).

**Related.** Finding 55 (the closed picker stays red whatever is picked) and W-2's S20 (a model
this launch saw refused turns red).

**Weight.** Medium: red on every row says nothing works, while the review had just come back.

**Issue:** tcc#58 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#58, by the Arbiter's rule for 55. No log of the moment (the Mac's log keeps warnings
only, and it was not on the VM's copy): the one state that paints every row at once, Anthropic's
too, is "not checked yet" while the catalogues are read. It is grey now, with its word; red is for
what cannot run.

### 63. The critic's reply is not shown as the critic's, and the Generator's proposal is labelled «SYSTEM · LEDGER»

**What.** The Arbiter suspected the critic's answer arrives as the blue system bubble. Checked on
his word (2026-09-24), from the code:

1. **The blue «SYSTEM · LEDGER» bubble in the screenshot is the Generator's proposal**, not the
   critic: «m-L · EQ (крок 2.8, пакет раунду): без корекції у 2–2,5 кГц → PK 2251 Гц … » with its
   rationale under it is the `propose_change` tool's output, which `_on_proposal`
   (`main_window.py`) sends through `_add_system_message`, whose default label is «SYSTEM ·
   ledger». So the Generator's own proposal reads as a system record.
2. **The critic's reply had no bubble of its own.** The critic is always called by the
   Generator, never by TCC on its own, and the Generator has two ways to do it: TCC's MCP tool
   `call_critic`, which runs the method's `autosound_ai.py` and hands the reply to the window, or
   `autosound_ai.py` run directly. A «Critic · <model>» bubble is drawn only on the first way.
   `call_critic` has no way to ask for the API route, so after the cut-off agy call (finding 61)
   the Generator ran the same package `--via api` directly, and the reply went to the journal
   without passing through TCC. All the dialog shows of it
   is the Generator's retelling, «Що сказав Критик». (The route is read from the Generator's
   words; the session log was not checked.)

**Where.** The in-app AI dialog (screenshot, 2026-09-24).

**Weight.** Medium: the one voice the loop exists for is not visible as itself, and a proposal
looks like something already recorded.

**Issue:** tcc#59 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#59. The proposal comes as the Generator's bubble, «Generator · proposal»
(`DialogPanel.add_proposal`). `call_critic` takes `via` — `api`, `cli`, `clipboard`, the script's
own `--via` for one run — and keeps the API key for a run that asks for the API (finding 32 kept it
out for a CLI pick); a refusal tells the model to retry through `call_critic` with `via="api"`,
not the script, whose reply never reaches the window.

### 64. «У фокусі зараз» shows the phase plan, not the open round: 24 positions and five columns for a round of six

**What.** Round `cap_016` is open with six positions (`capture_task_issued` in the journal). The
panel shows 24, in five columns: SOLO (SW), SOLO (RTA), PAIRS (RTA), SIDES (RTA), JOINTS (RTA),
including `r-L`/`r-R`, which the project's registry has switched off, and the centre, frozen until
phase 5. The Arbiter asked whether the last three columns are TCC's logic or the method's data.

**Checked (2026-09-24, against the code; the project's AI traced the same).**

- **The columns and names are the method's.** `rew_tool/naming.py`, `_CAPTURE_PLAN["2"]`:
  `channels` (sw and rta), `pairs`, `sides`, `joints_sw_ws` (rta), and `expected_groups()` makes
  one group per (scope, method), labelled pairs · sides · joints. TCC draws one column per group.
  `channels` takes the glossary's ACTIVE channels (`active_only=True`), so `r-L`/`r-R` showing means
  the glossary still has them on while the registry has them off.
- **Plan over round is TCC's.** `state/measurement_view.py` (`build_session`) asks the
  method's phase plan first and reads the open round's own `expected` only when the plan is empty
  (phase 1). In phase 2 the plan is not empty, so the round is never read, although the same
  function says «a round is a fact, a phase plan is a prediction about it».

**Sent.** The method's side as hub #205 TCC-031, to be matched with the skill's own capture-round
tasks (the Arbiter has written to the skill about this already).

**Related.** Finding 57 (next round shows a full, green list). The project's AI mentions the
Arbiter's rule to merge pairs, sides and joints into one «Group» column; not looked up here.

**Where.** The Arbiter's project, round `cap_016`, phase 2 (screenshot, 2026-09-24).

**Weight.** High: the task the tuner reads is not the task the session issued.

**Issue:** tcc#60 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#60 (TCC's half). An open round is the task: its own `groups` when it carries them
(skill #83: label, method, names beside `expected`), else its list grouped by method, in the
derived spelling; the phase plan only when no round is open. The columns become the method's four
(Solo/Group × sw/rta) once skill #79 and #83 ship; `r-L`/`r-R` is #83's (one source for "active").

### 65. Status dots on the tree's DSP groups and on the tabs: none, set, changed

**What.** The Arbiter's ask (2026-09-25, two screenshots): beside «ВІРТУАЛЬНІ 6/8 · ВИХІДНІ 8/12 ·
ВХОДИ 0» in the left panel, and on the tabs «Таблиця-V · Таблиця-О · EQ · Рівень · Затримки · Фази»,
a dot says at a glance whether there are settings there: grey — none, one colour — there are,
another — there are changes. In the colours TCC already has.

**In the prototype (finding 47).** Grey `off` for none, green `ok` as on the DSP section's version
dot for set, blue `info` as the compare's changed cells for «differs from the version in «порівняти
з»»; no blue while nothing is compared. The full mode's pane menu carries the same dots.

**Where.** v0.1.43, the left panel and «Режим контролю».

**Weight.** Medium: a wish, nothing is broken.

**Built:** tcc#51, `3b7003a` (with finding 47).

### 66. «порівняти з» offers only the current preset's versions

**What.** The Arbiter (2026-09-25): comparing must work not only with the v_xxx of the current
configuration but with other configurations too. Today the list is `ledger_line.versions(root,
preset)`, the open preset's versions only (`main_window._offer_compare`).

**In the prototype (finding 47).** The list is grouped: this preset first, then the other presets,
each version under the name it was saved with in the DSP (`v_004 · SQ-2`). A version of another
configuration shows an «інша конфігурація» tag beside the list and in the table's note. The default
stays the configuration this one continues.

**Where.** v0.1.43, «порівняти з» in both modes.

**Weight.** Medium: a whole kind of comparison (SQ against FULL) cannot be made.

**Built:** tcc#51, `3b7003a` (with finding 47).

### 67. Control mode after #51: the header overlaps, the compare list wraps, and four more

**What.** The Arbiter's list on the build of #51 (`3b7003a`), 2026-09-25, with screenshots:

1. In the header the target-curve link («SQ-Comp») runs over the «порівняти з» label. Move the link
   left, up to the field before it.
2. The open «порівняти з» list wraps its lines («2.S-shelf — інший пресет» / «v_001»). Make it wide
   enough for each line to fit whole.
3. The tab dots: put them at the tab's edge.
4. The header's passive «Копіювати EQ» (pair mode) and the active one beside each channel look the
   same; nothing tells them apart.
5. The EQ's channel-button row can get too long. Wanted: lists of «name — details» where, of the
   three, one is open and the others closed, «з крапочками». Answered the same day: the three are
   the tiers (virtual · outputs · inputs), and the dots are the coloured status dots of finding 65
   (none · set · changed), on each tier's header.

**Where.** `wave-0.1.44` at `3b7003a`, «Режим контролю».

**Weight.** Medium for 1 and 2 (text over text, a list that cannot be read in one line); low for
3–5.

**Built:** tcc#52, `305cd47` (all five; the Arbiter's OK and «терміново», 2026-09-25).

### 68. The EQ band card lists Freq · Q · Gain; the Helix lists Freq · Gain · Q

**What.** The Arbiter (2026-09-25, two screenshots): for a Helix it would be handier to swap Gain
and Q on the band card, because that is the order the processor's own software shows (Parametric
EQ: Band · Freq · Gain · Q). TCC's card reads Freq · Q · Gain, so reading a band across into PC-Tool
jumps a line.

**Where.** The EQ view's band cards, both modes.

**Weight.** Low: nothing is wrong, the entry order is off. The order is the processor's, not one
for all: for a MUSWAY, TCC's Freq · Q · Gain is right (the Arbiter, the same day), so the card has
to follow the DSP it shows.

**Built:** tcc#52, `305cd47` — by vendor (Audiotec-Fischer / Helix: Freq · Gain · Q), since the
profile does not state the order.

### 69. The EQ card: the band's number, and the filter type in a colour of its own

**What.** The Arbiter (2026-09-25):

1. The card shows the band's number in brackets — the processor's own «Band» (finding 68's Helix
   screenshot: Band 4).
2. The filter type's name is coloured by type: grey — an empty band (better not shown at all);
   green — a shelf filter; blue — PK (a peaking filter); yellow — APF.

**Where.** The EQ view's band cards, both modes.

**Weight.** Low: reading aid; nothing is wrong.

**Built:** tcc#52, `305cd47`, with hub #211 PAS-011 (numbered cards, no empty ones) and hub #209
PAS-009 (the card's bypass).

### 70. A «Налаштування» menu for TCC's technical settings; the band card's field order among them

**What.** The Arbiter (2026-09-25): the EQ card's field order (finding 68 — Freq · Gain · Q or
Freq · Q · Gain) should be a TCC setting, not only the vendor's rule built in by #52. And a separate
«Налаштування» menu should hold all of TCC's technical settings.

**Where.** TCC's menu; the band card's order (`detail_pane.eq_field_order`, since `305cd47`).

**Weight.** Medium: a place for settings that today are scattered or built in.

**Issue:** tcc#67 on W-3, the Arbiter's OK 2026-09-26.

**Built:** tcc#67. «⚙ Налаштування» in the main menu holds TCC's technical settings: the EQ card's
field order (as the processor shows it · Freq · Gain · Q · Freq · Q · Gain, per machine, the
processor's by default), the models, the reviewer key, the permissions, the theme, the language and
the text size — before, they sat in the session and view sections, and the order had no place.

### 71. The EQ view and the tabs, third pass (the Arbiter, 2026-09-25, on `985c097`)

**What.** With screenshots, to be built at once («зразу зробимо коміт»):

1. The tab dots closer to the text, not at the tab's right edge (reverses 67, 3 as built).
2. The band cards do not wrap: a scroll instead.
3. The count of configured bands in brackets.
4. No tab when there is nothing in it («Таблиця-I» with no inputs), and the same for the left panel
   («ВХОДИ 0»).
5. A band that has settings but is bypassed is shown; a band with none (empty, white in PC-Tool)
   is skipped. The count reads «(8/12)»: 8 active of 12 configured, the empty ones not counted.
6. The tier list (67, 5 as built, on the left) goes horizontal into the EQ's header row:
   «V: VFL/VFR   O: tw-L/tw-R   I: -/-»; in single mode one channel per tier; a click on a tier
   drops down its list of channels, as the left list does now.

**Where.** `wave-0.1.44` at `985c097`, both modes.

**Weight.** Medium for 5 (a bypassed band with settings and an empty one read the same); low for
the rest.

**Built:** tcc#53 (all six), the commit that records this line.

**After `02f2812`, the Arbiter's look at the pickers (2026-09-25):** «не подобається і не зручно:
скакають поля, дублює сірим», then: the actions to the end of the row, wider fields named in full
(«Virtual: / Output: / Input:»), one name in single mode, and not two marked in single mode (the
drop-down checked the pair's partner too). Built in the commit that records this: fixed widths,
the dot inside the field, «⇄ L + R · Копіювати EQ · ?» at the row's end, no grey «EQ · …» title,
and no header copy in pair mode (each channel's heading has its own).

### 72. Other presets show no band numbers: their ledgers do not carry `i`

**What.** The Arbiter (2026-09-25, screenshot): after switching to another configuration the EQ
cards lost their band numbers; back on the first one they are there.

**Checked (the data, not TCC).** `car/passat-b8-2026-aya/state/*/HEAD`: `1.B-base` v_006 — 83 bands,
83 with `i`; `2.S-shelf`, `3.C-cut`, `4.P-punch`, `5.R-right`, `6.E-epy` v_001 — 72–77 bands, 3
with `i` each. PAS-011 (hub #211) added the numbers to `1.B-base` only. TCC shows `i` where the
ledger has it and invents none: a position in the list is not the DSP's band, since the gaps are
not recorded.

**Whose.** The numbers belong in those ledgers, read from PC-Tool — the car session's side, not
TCC's.

**Weight.** Medium: the band-by-band check against PC-Tool works on one preset of six.

**Sent:** hub #212 TCC-032 to the car session, on the Arbiter's word at the W-3 review (2026-09-26).

### 73. The EQ row of the compared version under the current one; new / changed / removed marks on the bands

**What.** The Arbiter (2026-09-26, screenshot of the EQ header's «Копіювати EQ w-L · ⇄ L + R · ?»),
an idea:

1. A button left of «Копіювати EQ»: compare with the version chosen in «порівняти з». Nothing
   chosen — the button is passive. In pair mode (⇄ L + R) the button is hidden.
2. Pressed — a second EQ row appears under the current one, labelled with the compared version
   (`v_xxx`). The colour shows what CHANGED, not what is the same.
3. «Копіювати EQ» stays in the header and copies the current set; the compared row gets no copy.
4. Each band card's heading carries a coloured mark whenever a compared version is chosen: «new»
   and «changed» on the current row; «removed» only on the lower (compared) row, so only while the
   button is on.

**Where.** `wave-0.1.44` at `9e18ba3`, EQ view, single mode. The compare choice exists since tcc#51
(finding 66: `detail_pane.use_compare`, `setting_status._judge`); the band card is
`detail_pane.EqBandCard`, whose top border already carries the pair mode's shared-frequency colour.

**Open for the build (not answered yet).** What makes a band «the same band» in two versions: the
DSP band number `i` where the ledger has it — five presets of six lack it (finding 72) — or the
position, or the frequency. And which colours and words the three marks use beside the existing
status dots.

**Weight.** Medium: a feature; a band-by-band comparison of two versions inside TCC.

**Issue:** tcc#54 on W-3; the Arbiter's OK the same day («робимо зараз - мій ОК», «коміт
достатньо!» — a commit, no tag).

**Built:** tcc#54, the commit that records this line. «⇅ Порівняти» left of the copy; the marks
are a dot in the card's heading — green new, blue changed, red removed — with a legend over the
rows and what moved on hover. The changed values are blue in both rows while the compared row is
on. A band is matched by the DSP number `i` where both versions carry it on every band, otherwise
by order and (type, frequency) (`state/eq_diff.py`): a band put in the middle is new, the rest
stay the same; a frequency moved in its place is a change.

**After `21dc2af`, the Arbiter's look (2026-09-26, three screenshots):** «видалена» in the legend
always; the compare list was passive on «Моніторинг», the tab a project opens on («давай не
обмежувати вибір»); the same bands by count, without frequencies, and the changed, new and removed
ones with theirs. His screenshot also showed the order match failing: 6.E-epy carries no `i` and its
order is not 1.B-base's, so an identical 4800 Hz read as changed and 1250 Hz as new here and removed
there. Built in the commit that records this: the legend «однакові (10) ● нова (0) ● змінена (4):
250 · 350→302 · 1000→1120 · 2700 Hz ● видалена (1): 420 Hz», the list open on every tab, and
unnumbered bands matched by content — identical first, then the same frequency, then the nearest
of the same type within a third of an octave.

**Third look (2026-09-26):** «давай ще зробимо кольорово однаковими "змінені", як це у нас
правий-лівий зроблено. в цілому супер!». Built in the commit that records this: with the compared
row on, each changed band and its compared self share a colour of the pair palette on the card's
top border, and the legend lists them as chips in those colours («⬤ 1000→1120 Hz»).

**Fourth look (2026-09-26, screenshot of PK (7)):** «bypass не треба підсвічувати синім; якщо
статус зміниться — то червоним, і в цифрах зміни червоним», and the pairs' colours not the dots'
green and red («синій ок»). Built in the commit that records this: changed values and a switched
bypass in red, an unchanged bypass keeps its own look; the pair palette is blue, orange, violet,
yellow, pink and tan.
Then: «там, де точки зелена чи червона, можна було б малювати і в шапці колір — щоб краще було
видно». Built in the next commit: a new band's card is topped green, a removed one's red, in
single mode (in pair mode the top says «shared frequency»).
Then: «в порівнянні не виділяти червоним, як було, а тільки там, де треба вводити». Built in the
next commit: red only on the current row, what is entered into the DSP; the compared row's values
and bypass are plain, the pair colour on top ties each to its band above.

### 74. The tree's channels: the compared bands as coloured dots with counts, left of «EQ n/m»

**What.** The Arbiter (2026-09-26, two screenshots — the tree's «EQ 11/12» chips and the EQ view's
legend «однакові (11) ● нова (0) ● змінена (1) ● видалена (3)»): in compare mode, left of each
channel's EQ chip, the coloured dots with their counts in brackets and no names. «роби зараз — мій
ОК».

**Where.** `wave-0.1.44` at `0fca226`, the DSP tree (`dsp_tree.ChannelRow`), fed by the same match
as the EQ view (`state/eq_diff.py`, tcc#54).

**Weight.** Medium: which channels' bands moved against the compared version, without opening each.

**Issue:** tcc#55 on W-3, the Arbiter's OK the same day.

**Built:** tcc#55, the commit that records this line. Only the kinds that are there: a channel
whose bands did not move shows no dots, and none shows with nothing compared. A channel the
compared version lacks counts every band as new. The tree now also gets its dots back after a
language switch rebuilds it.

## The Arbiter's test of `wave-0.1.44` on the Mac (2026-09-26, build `7103d04`)

Recorded, not diagnosed (`WAVES.md`: while the user tests, a session only records).

### 75. «Моделі у виборі генератора»: empty check boxes are not seen, and the window is too narrow

**What.** Dark theme: an unticked box in the list draws nothing — only the ticked one (GPT-OSS
120B) shows. Light theme: the tick overlaps the row's text and the rows are cut on the right. The
Arbiter: make the window twice as wide.

**Where.** Mac, both themes, Settings → the omp models (two screenshots).

**Weight.** Medium: which models are offered cannot be read.

**Task.** tcc#70, the Arbiter's OK the same day («полагодь що описав»).

**Built:** tcc#70 (`2056af8`). The list draws its own boxes — an empty square, a filled one when ticked — in both themes, and the window opens at 760 px, 720 at least.

### 76. After trying several models, every row of the reviewer list is red

**What.** Having tried several reviewers (Kimi has no login), the reviewer picker's open list shows
every row in red, the SDK Claude rows and the AGY rows included; the picked one reads «GPT-OSS
120B · безкоштовно · відмова», Kimi K2.5 «лише буфер». The footer status reads «… · останній
виклик відхилено» in red.

**Where.** Mac, light theme, the footer's AI CRITIC picker (screenshot).

**Related.** Finding 62 (the same all-red list), built in tcc#58.

**Task.** tcc#58 (reopened by this test).

**Built:** tcc#58 (`6c968c9`). The combo's own delegate painted the open list with the combo's palette: a refused pick (red) turned every row red, and a row's own red was never drawn (measured offscreen: 50–77 red pixels on every row, 0 on the refused one). The model pickers use the standard delegate now: working rows plain, a refused row red.

### 77. A model that did not start, and switching away still runs «save state»

**What.** Kimi K2.5 through omp: «omp refused `prompt`: No API key found for kimi-code …», then
«120s with no output. omp has said nothing.» Picking another model then ran the state save before
the change — the Arbiter: this was already a bug (finding 54).

**Where.** Mac, the in-app AI dialog (screenshot).

**Related.** Finding 54, built in tcc#56 for a session whose thread had ended; here the omp process
answered with a refusal and stayed.

**Task.** tcc#56 (reopened by this test).

**Built:** tcc#56 (`6c968c9`, `8da5f84`). A refused prompt ends its turn; a session whose model never spoke is closed without the save turn. And the reason no model could be picked: TCC ran omp in its own `--profile tcc`, whose credential store had none of the Arbiter's logins — Opus 5 answered in his terminal and was «No API key found for anthropic» in TCC. On his decision TCC runs his own omp profile now.

### 78. «Налаштувати omp…» opens a terminal that hides behind TCC

**What.** The terminal omp's configurator runs in opens behind TCC's window, which is maximised
(not full screen), so it is not seen.

**Where.** Mac, Settings → the omp models → «Налаштувати omp…».

**Weight.** Medium: the step looks like it did nothing.

**Task.** tcc#71, the Arbiter's OK the same day.

**Built:** tcc#71. Since macOS 14 activation is cooperative: TCC in front has to yield before the terminal can come forward, and osascript's `activate` alone was ignored. TCC yields to Terminal / iTerm first (`NSApplication.yieldActivationToApplicationWithBundleIdentifier:`, through ctypes). Not checked live — it would take the Arbiter's focus; his next «Налаштувати omp…» is the check.

### 79. The configurator's terminal opens behind the models window, then goes behind TCC

**What.** After tcc#71: «Налаштувати omp…» opened the terminal in front of TCC's main window but
behind the models window, and a moment later it went behind TCC as well.

**Where.** Mac, Settings → the omp models → «Налаштувати omp…».

**Task.** tcc#71 (reopened by this test).

**Built:** tcc#71 again. The models window was application-modal (`exec()`), which on macOS sits at the modal-panel level above every app's windows; the terminal came up behind it. It is modal to TCC's window only now (`WindowModal`, shown with `show()`), and its answer is taken when it closes. Not checked live.

**Checked live 2026-09-27 (Mac, `de20037`):** the terminal still opens behind TCC, «як і було».

**Found and built (2026-09-27):** TCC's log had the models window active again 0.2–0.4 s after each
`osascript` (its once-only catalogue reload ran), so the terminal did come forward and TCC took the
front back. A probe on this Mac (a Qt window + window-modal dialog opening the terminal through
`terminal_launcher`) kept Terminal in front; a `RoundedTooltip.show_at` 0.3 s later put the probe in
front again, and the same tip shown without `raise_()` did not. Qt's macOS `raise()` activates the
application, and the button's hover tip called it. The tip no longer raises; the probe against the
fixed tree keeps Terminal in front.

### 80. An omp session hangs inside TCC's own `get_tcc_state`

**What.** «Запускаю Claude Opus 5 …», then «120s with no output. Still inside
`mcp__tcc__get_tcc_state`», and the turn went on hanging (the dialog's clock at 2:24, the tool
line at 2:16). The model is omp's Claude Opus 5, which answers in the Arbiter's terminal.

**Where.** Mac, the in-app AI dialog, omp route, the Arbiter's own omp profile (since `8da5f84`)
(screenshot).

**Weight.** High: no omp session gets past its first tool call.

**Task.** tcc#72, the Arbiter's OK the same day.

**Not reproduced.** Headless, the tool answers in 0.13 s on the Arbiter's project; through HTTP against a real (offscreen) window in 13 ms; with the reviewer probe running alongside, 16 ms; and a full in-app omp session with Opus 5 on a copy of the project called `get_tcc_state`, `get_pending_signals` and `ack_signals`, each in milliseconds. What the log does say: at 23:18:34 the call was logged and neither its answer nor the parallel `get_pending_signals` ever was — the server's event loop stood still inside it.

**Built for the next time:** a tool that has not returned in 20 s writes every thread's stack into the log (`app_log.dump_threads`, through `faulthandler`, which takes no lock).

**Found and built (2026-09-26, night):** the Arbiter's next run hung again, «Still inside
`mcp__tcc_get_pending_signals`», and TCC's log showed both tools answered in 2 ms — the hang was in
TCC's side of the omp pipe. Driven directly (TCC's `OmpSession`, no window, no MCP server), one
`read` of a plain file hung the same way in `rpc-ui` and `rpc` while `omp -p` with every TCC flag
answered in seconds; the frame reader had died: `ValueError('Separator is found, but chunk is
longer than limit')`. asyncio reads a subprocess's lines up to 64 KiB, omp's frames go to 1 MiB
(`maxFrameBytes` in its `ready`), a built-in tool's frames passed it, and the reader task died
without a word. omp is spawned with a 64 MiB line limit now, and a reader that fails says so in the
dialog and ends the turn. Checked live: `read README.md` and `read skill://autosound-tuning`
through `rpc-ui` both end, and the turn goes on.

**Checked live 2026-09-27 (Mac, `de20037`, omp with Claude Opus 5):** «запрацював» — the turn read
TCC's state and answered.

### 81. Quitting TCC while the omp session hung: Python aborts

**What.** The quit ended in a crash report, `SIGABRT`, `abort() called`.

**Evidence.** `~/Library/Logs/DiagnosticReports/Python-2026-09-26-231647.ips`, the faulting thread:
`PySide::destroyQCoreApplication` → `QThreadWrapper::~QThreadWrapper` → `QThread::~QThread` →
`qFatal`. TCC's log, 23:16:44: `CRITICAL Qt: QThread: Destroyed while thread '' is still running`
— finding 35's class, a running worker destroyed at exit (here the agent worker stuck in finding
80's turn).

**Where.** Mac, a build before `e7ca15b` (the Arbiter's words), quitting with the omp session hung.

**Task.** tcc#73, the Arbiter's OK the same day.

**Built:** tcc#73. `worker.shutdown()` came back False for the stuck turn and was not looked at; the worker has no parent and was never handed over, so `destroy_application` did not see it. Now the session's omp process is ended, and a worker still running 3 s later is handed to `qt_shutdown`, whose exit path leaves without destroying Qt.

**Checked live 2026-09-27 (Mac, `de20037`):** quitting while omp answered — «закрився нормально».

### 82. GPT-OSS as the reviewer turns red right after a session starts

**What.** The Arbiter: «GPT-OSS ставала червоною після старта сесії».

**Evidence.** TCC's log, 23:08:09: `critic: … model=gpt-oss-120b harness='omp'` — the start-up
reviewer probe called it, and the refusal it got is what turned the pick red. The red is the probe's
verdict; the question is why the pick was offered as reachable: `critic_reaches` reads `gpt` as
OpenAI and finds `codex` installed, while no transport of the reviewer script runs
`gpt-oss-120b`.

**Where.** Mac, the footer's AI CRITIC, pick «OMP · GPT-OSS 120B».

**Task.** tcc#74 (with 85), on W-3 by the Arbiter's word 2026-09-27.

**Built:** with 85, tcc#74.

### 83. Every omp session opens with «SYSTEM · LEDGER: this project's settings.json applies: hook SessionStart …»

**What.** Seen on the Arbiter's screenshots, not reported by him — recorded by the session. At each
omp session start the dialog shows a «SYSTEM · LEDGER» bubble quoting the car project's
`.claude/settings.json` SessionStart hook (`printf '%s порода=%s метод=%s голова=%s' …`): omp's own
notice about project settings, labelled as a ledger record, with shell text nobody needs to read.

**Where.** Mac, the in-app AI dialog, omp route (screenshots 14 and 16).

**The Arbiter, 2026-09-27:** not hidden — the bubble's header should say it comes from OMP
(«було б добре щоб писало в заголовку що це OMP»), not LEDGER. The project panel's half is 84.

**Task.** tcc#75 (with 84), on W-3 by the Arbiter's word 2026-09-27.

**Found and built (2026-09-27):** not omp's notice — TCC's own (HUB-050, `project_trust`), posted with the
default «SYSTEM · ledger» role. And untrue on the omp route: the hook appends to the project's
`.sessions.log`, and none of the five omp sessions of 26–27.09 wrote a line. The Arbiter, told so:
«воно не несе ніякого змісту для користувача і його можна взагалі не показувати. а якщо там є
проблема — то червоним показати як помилку чи помаранчевим якщо попередження». Hooks are not
announced any more; an orange «SYSTEM · TCC» warning stays for a folder that grants tools without
asking and for a settings file nobody can read (`project_trust.warnings`, bubble level `warn`/`error`).
pl/de strings through the Advisor (`ask`, gemini-pro-latest).

### 84. The project panel does not say that the generator and the advisor run through OMP

**What.** «ПАРАМЕТРИ ПРОЄКТУ» shows «ШІ генератор anthropic/claude-opus-5» and «ШІ радник
google-antigravity/gemini…» with no route; the Arbiter wants OMP named there too («і в конфігурації
теж глянь»), as in 83's header.

**Where.** Mac, the project panel (screenshot 2, 2026-09-27).

**Task.** tcc#75 (with 83), on W-3 by the Arbiter's word 2026-09-27.

**Built:** each model in «ПАРАМЕТРИ ПРОЄКТУ» carries its route as the picker does — «OMP · Claude
Opus 5», «AGY · …»; a model the catalogue does not list keeps its selector after the route. The panel
reads the marked omp models too, so a known one shows its name, not its selector.

### 85. A reviewer model is found dead only when the first review fails

**What.** The Arbiter: «було б добре з'ясовувати це до запуску». The car session, asked why the
reviewer did not work, tried the picks one by one (its own report, 2026-09-27):

- `gemini-2.5-flash` (the pick before): API 404 «no longer available to new users»; `agy`
  «invalid model selection». TCC's state still said `reachable: true, ready: true`.
- «OMP · Gemini 3.1 Pro» → `gemini-3.1-pro`: HTTP 404 from Google's API — no such id there.
- `gemini-3.1-pro-high` through `agy`: «not supported in the selected location» on this account.
- Working: `gemini-3.1-pro-preview` and `gemini-pro-latest` (API), `gemini-3.8-flash-low` (agy),
  `gpt-5.6-terra` (codex).

Three things in it, as the Arbiter met them:

1. «не розумію чи OMP взагалі працює»: an OMP reviewer pick is not called through omp. TCC has no
   omp reviewer CLI (`critic._HARNESS_CLIS`), so the method's script picks the transport by the
   model's name, and omp's model names are not the API's — hence 404.
2. Readiness is the channel being there, not a live call on the picked model.
3. Flash picks are offered for the reviewer, a class the method forbids there.

**Where.** Mac, the footer's AI CRITIC, the car project's omp session.

**Task.** tcc#74 (with 82), on W-3 by the Arbiter's word 2026-09-27.

**The Arbiter, 2026-09-27:** «OMP потрібен … дати доступ до різних моделей … якщо вибрана ОМР, то і йти
треба тільки через цей виклик». The reviewer script has no omp route: hub #216 TCC-034 to `skill`. W-3
takes the check and honest OMP rows; the omp route lands with the skill's tag. And «API · …» for Gemini
Pro through the key (his word, the same day).

**Built:** «API · gemini-pro-latest» and «API · gemini-3.1-pro-preview» run with `--via api` and reach
only with the key. OMP and Flash rows in the reviewer picker are greyed with why («через omp — з
наступним оновленням методу», «не для рецензента»); a current pick stays selected. An OMP pick is
called for nothing: `call_critic` says so, `get_tcc_state` is not ready with the same words, a
session's shell is handed no model. A Flash pick carries a warning in the state. The reviewer is
asked once at launch and at once when picked. `choose_model` for a named model (the 404 of
`gemini-2.5-flash`) is a refusal now: red, where it read as ready. Not checked live.

**Checked in a live session 2026-09-27 (Mac, `b2ed5d6`, method v3.0.63):** «OMP · Gemini 3.1 Pro» was
`ready: false` in `get_tcc_state` before any review, and `call_critic` through omp came back 429
`RESOURCE_EXHAUSTED` twice (45 s apart): quota, as the check had said. The session substituted
nothing and offered the Arbiter the choice, noting the clipboard rung does not take the omp route.
Bubbles read «GENERATOR · OMP · CLAUDE OPUS 5» and «SYSTEM · TCC» (screenshot 18).

### 86. The method's version check fails at the start of an omp session

**What.** Seen on the Arbiter's screenshot, not reported by him — recorded by the session. The
generator's first turn: «Не пройшла — версія методу. `deployment.py` відмовив (код 3). Досяжні дві
збірки: v3.0.61 (ця і та, на яку вказує проєкт …» (cut off), and the car session asks whether the
project stays on 3.0.61 or moves to 3.0.62. TCC `de20037` carries the method at v3.0.62 (tcc#68).

**Where.** Mac, the in-app AI dialog, omp route, the Arbiter's own omp profile (screenshot 1,
2026-09-27).

**Task.** tcc#76, on W-3 by the Arbiter's word 2026-09-27; closed the same day as not TCC's.

**Found (2026-09-27):** the method's own refusal, by design. `deployment.py <project>`: `here` and
`personal` are 3.0.62 (`~/.claude/skills/autosound-tuning` → the skill's working tree), `project` is
3.0.61 — the car project's `.claude/skills/autosound-tuning` links a detached v3.0.61 checkout made
2026-09-25. Two checkouts reachable → exit 3; telling a deliberate pin from a split is the skill's
S-001. TCC runs the personal copy (its title: «skill 3.0.62»). What is left is the Arbiter's choice
for the project — stay pinned to 3.0.61 or move the link to 3.0.62 — answered in the car session.

### 87. A hover tip stays on screen: over another app after switching, or over TCC with the mouse elsewhere

**What.** The Arbiter: «хінт не ховається а залишається навіть поверх іншої аплікації на яку
перемкнувся. або висить над ТСС хоч миша вже в іншому місці».

**Where.** Mac, TCC's hover tips (`RoundedTooltip`, a stays-on-top window hidden only on the owner's
leave event).

**Task.** tcc#78, on W-3 by the Arbiter's word 2026-09-27 («додай до робіт»).

**Built:** tcc#78. The tip hides when TCC stops being the active app, and while shown it checks
every 250 ms that its owner is still there, visible and under the cursor. Tips with no owner (a
menu action's, the «copied» note) keep their callers' hiding. Not checked live.

**Checked live 2026-09-27 (Mac, `a71dc24`):** «ок».

### 88. «Налаштування» belongs at the end of TOOLS, not of SESSION

**What.** The Arbiter: «перенеси ще "Налаштування" меню в наступний розділ в кінець».

**Where.** Mac, the main menu (tcc#67's submenu).

**Task.** tcc#79, his word 2026-09-27.

**Built:** the submenu is the last line of TOOLS, right above HELP.

### 89. «Налаштувати omp…» at `a71dc24`: «could not open a terminal», osascript exit 1

**What.** The models window's status line: «could not open a terminal: Command '['osascript', '-e',
'tell application "Terminal" to do script "cd /Users/o.yukhno/dev/autosound/car/passat-b8-2026-aya &&
exec omp setup"\ntell application "Terminal" to activate']' returned non-zero exit status 1.» No
terminal at all — before `a71dc24` it opened, behind TCC.

**Where.** Mac, `a71dc24` (reinstalled for the batch test), Settings → the omp models → «Налаштувати
omp…» (screenshot 7, 2026-09-27).

**Task.** tcc#71, reopened by this test.

**Found and built (2026-09-27):** osascript stopped at compile — «31:40: syntax error: A "script" can't
go after this identifier. (-2740)». `id of application "Terminal"` answered
`com.parallels.winapp…f51a810d…`: the running VM «Windows 11 (Musway-old)» publishes its Windows
Terminal to macOS under the same name, and it has no `do script`. In the morning the VM was down,
so the name reached Apple's Terminal. The scripts now address `application id "com.apple.Terminal"`
(and iTerm's id), and a refusal carries osascript's own words. Checked live with the VM up: a
terminal opened in the car project.

**Checked live 2026-09-27 (Mac, `b2ed5d6`):** ok.

### 90. The dialog names the generator without its route: no OMP anywhere in the conversation

**What.** The Arbiter, after `a71dc24`: the settings.json bubble is gone, «але Генератор без
признаку що то ОМР». The bubbles read «SYSTEM · TCC — Запускаю Claude Opus 5 …» and «GENERATOR ·
CLAUDE OPUS 5», on the omp route.

**Where.** Mac, `a71dc24`, the in-app AI dialog, omp route (screenshot 8, 2026-09-27).

**Task.** None yet — with tcc#75's panel half (84).

**Built:** tcc#80 `a216b49` — the generator's bubbles and «Запускаю …» carry the route («OMP · Claude Opus 5»).

**Checked live 2026-09-27 (Mac, `b2ed5d6`):** ok.

### 91. «⚙ Налаштування» in the menu: bold, so it reads as a submenu

**What.** The Arbiter: «зроби назву жирним (що це має субменю)». Its place at the end of TOOLS is
right (tcc#79).

**Where.** Mac, `a71dc24`, the main menu.

**Task.** None yet.

**Built:** tcc#81 — the submenu title is bold.

**Checked live 2026-09-27 (Mac, `b2ed5d6`):** ok.

### 92. After a new reviewer is picked, the footer keeps the previous one's last call in red

**What.** The pick «API · gemini-pro-latest» (then «API · gemini-3.1-pro-preview») went green —
answered at once — and beside it the status stayed «! gpt-5.6-terra · 2 h ago» in red: the last
call of the reviewer before, which reads as this one being broken. The Arbiter: «і ось це дивно».

**Where.** Mac, `a71dc24`, the footer's AI CRITIC (screenshots 9 and 10, 2026-09-27).

Again at `bf5d8a1`: «OMP · GPT-5.6-Terra» green, and beside it «gpt-5.6-terra · 3 h ago» — the last
real review (then through codex), not the check that had just answered (screenshot 13).

**Task.** None yet.

**Built:** tcc#82 `0bae511` — once the pick answered its check, the status names it («… · відповів на перевірку»), not another reviewer's review.

### 93. TCC's own lines in the dialog still come as «SYSTEM · LEDGER»

**What.** Seen on the Arbiter's screenshots, not reported by him — recorded by the session.
«Рецензент тепер gemini-pro-latest: наступний виклик call_critic піде до нього …» and «TCC почав хід
через 1 твій запит з інтерфейсу …» are TCC talking about itself, labelled as ledger records — 83's
class, which moved only the project-folder notice to «SYSTEM · TCC».

**Where.** Mac, `a71dc24`, the in-app AI dialog (screenshots 9 and 10).

**Task.** None yet.

**Built:** tcc#80 `a216b49` — SYSTEM · TCC is the default; only a banked change and the journal's closing report say ledger.

**Checked live 2026-09-27 (Mac, `b2ed5d6`):** ok.

### 94. «дивно про версії»: what the diagnostics say about the versions

**What.** The Arbiter's words beside the Diagnostics → «Установка» tab. What it shows: «TCC 0.1.43 —
актуальна» with commit `a71dc24` (the wave's build, past the 0.1.43 tag); «Скіл 3.0.62 — актуальна»
from `~/.claude/skills/autosound-tuning` → the skill's working tree at `152779b`; the window title
«TCC 0.1.43 · skill 3.0.62». Beside it the generator asks again «яка версія методу стоїть — 3.0.62 чи
пін 3.0.61?» (86: the car project pins 3.0.61). What exactly reads wrong is his to say.

**The Arbiter:** «чому він питає про версію якщо скіл вже оновлений?» — the update reached the personal
copy; the project's own `.claude/skills/autosound-tuning` still links the v3.0.61 checkout, and the
diagnostics, the title and the tab say «3.0.62 — актуальна» without a word of the project's pin. TCC's
half: name the project's own method beside the personal one, and say when they differ. His answer
to the session (3.0.61 or 3.0.62) is the project's, given in the car session.

**Where.** Mac, `a71dc24` (screenshot 10, 2026-09-27).

**Task.** None yet.

**Built:** tcc#83 — the title reads «skill 3.0.62 · project 3.0.61» when the project's link holds another method, and the report's «project link» row names its version.

### 95. The reviewer picker: OMP rows cannot be picked (by design until TCC-034); a bold row's note is cut in the middle

**What.** The Arbiter: «я не можу вибрати рецензента з OMP» — tcc#74 as built: OMP rows are greyed
until the method calls through omp (hub #216 TCC-034); «API · …» is the key's route meanwhile. And on
the same list the bold row reads «OMP · Gemini 3.1 Pro · через …— з наступним оновленням методу»: its
note elided in the middle, where the plain rows show it whole.

**Where.** Mac, `a71dc24`, the footer's AI CRITIC list (screenshot 11, 2026-09-27).

**Task.** The OMP rows: tcc#74 against the skill's tag. The cut note: none yet.

**Built (2026-09-27):** the OMP rows switch on by themselves once the method's reviewer script lists
`"omp"` in `VIA_ROUTES` (the interface agreed on hub #216): no version pin, so the skill's working
tree is enough to test on this Mac. An OMP pick then runs `--via omp` with omp's full selector, a
session's shell gets `AUTOSOUND_CRITIC_BIN=omp`, and `critic_reaches` asks for omp on PATH.

**Checked live 2026-09-27 (Mac, `bf5d8a1`, method v3.0.63):** «OMP · Gemini 3.1 Pro» was asked at once
through omp (`google-antigravity/gemini-3.1-pro`) and came back refused in omp's own words — Cloud Code
Assist 429 `RESOURCE_EXHAUSTED`, the Antigravity account's quota — with the method's remedy under it
(«квоту або ємність вичерпано — сходинка 0: зачекай і повтори»). The route works; the model is not
a 404 any more.

«OMP · GPT-5.6-Terra» went green the same minute: answered through omp.

**Built:** tcc#84 `0bae511` — each popup row is measured in its own font, so the bold row is not cut.

**Checked live 2026-09-27 (Mac, `b2ed5d6`):** ok.

### 96. The reviewer picker turns red-brown under the mouse, over its green «answered»

**What.** The Arbiter: «а мишку навів — червона». «OMP · GPT-5.6-Terra» is framed green (answered
this launch); with the cursor on it the frame turns red-brown, which reads as a refusal. Likely the
pickers' common hover border (`mini-select:hover`, the accent colour) drawn over the state colour —
not looked into.

**Where.** Mac, `bf5d8a1`, the footer's AI CRITIC (screenshots 13 and 14, 2026-09-27).

**Task.** None yet.

**Built:** tcc#82 `0bae511` — the green and red frames hold under the mouse.

**Checked live 2026-09-27 (Mac, `b2ed5d6`):** ok.

### 97. The session's first `call_critic` through omp was cut without an answer while the reviewer was still working

**What.** The Arbiter asked «перевір критика». The generator (omp, Claude Opus 5) called `call_critic`
at 13:46:55; «⚠️ 120s with no output. omp has said nothing.», then the generator: «Інструмент обірвався
без відповіді — це збій транспорту MCP» and «Виклик не дійшов узагалі» — and called again at 13:47:35.
TCC's log has the first call running `omp -p … --model openai-codex/gpt-5.6-terra` and returning
`refused` (Codex `usage_limit_reached`) at 13:47:52, about 57 s in — an answer the session never got.
A real review takes minutes; if omp cuts a tool call short, every review through the omp session is
lost the same way. Not looked into.

**Where.** Mac, `b2ed5d6`, the in-app dialog, omp route, reviewer «OMP · GPT-5.6-Terra» (screenshots
19 and 20, 2026-09-27; TCC's log 13:46:55–13:48:03).

**Task.** None yet — a tail of tcc#74.

**Found and built (2026-09-27):** omp aborts an MCP request after `OMP_MCP_TIMEOUT_MS`, 30 000 ms by default (omp 17.2.9's own `mcp/timeout.ts`) — the cut came ~30 s in. TCC spawns omp with `OMP_MCP_TIMEOUT_MS` a minute over the review's own limit (`critic.DEFAULT_TIMEOUT_S`, 600 s). tcc#85.

### 98. After an OMP reviewer refused, TCC's own hint sent the session to the API key

**What.** Seen on the Arbiter's screenshot, recorded by the session. `call_critic`'s refusal carries
TCC's line «To take this one review through the API key, call call_critic again with via="api"»
(tcc#59), and the generator did: «Сам інструмент назвав обхід — той самий рецензент, але через
API-ключ». For an OMP pick that breaks the Arbiter's rule (tcc#74, «якщо вибрана ОМР, то і йти треба
тільки через цей виклик»); it failed only because there is no OpenAI key («--via api: ключа для
openai нема»). `call_critic` also takes `via` other than omp for an OMP pick.

**Where.** Mac, `b2ed5d6` (screenshot 20; TCC's log 13:48:03).

**Task.** None yet — a tail of tcc#74.

**Built:** tcc#85 — no `via="api"` hint for an OMP pick, and `call_critic` refuses a `via` other than omp for it before anything runs.

### 99. An OMP reviewer on the generator's own model hangs: two `omp -p` calls with no output

**What.** The Arbiter picked «OMP · Claude Opus 5» as the reviewer while the generator runs Claude
Opus 5 through omp: «а ось це дивно, бо ця ж модель працює як основна». Both `call_critic` calls hung
— `omp -p --no-session --model anthropic/claude-opus-5` 2:52 and 1:07 with no output, killed by the
session, then filed as refusals. The session named the method's own warning (`setup-critic-channel.md`
§7: a reviewer CLI spawned inside an agent session on the same model deadlocks). «OMP · Claude Sonnet
5» answered the same package a minute later — a real review, «[Iteration 1/3] Critic: Claude
(anthropic/claude-sonnet-5)».

**Where.** Mac, `b2ed5d6`, the footer's AI CRITIC and the in-app dialog (screenshots 21 and 22).

**Task.** None yet — a tail of tcc#74.

**Built:** tcc#85 — the generator's own model (by name, whatever the route) is greyed in the reviewer list («та сама модель, що й генератор»), follows the generator's pick, and `call_critic` and `get_tcc_state` refuse it.

### 100. The same-vendor «!» beside the reviewer is red; it is a warning — yellow

**What.** The Arbiter: «зроби жовтим не червоним». «OMP · Claude Sonnet 5» green, beside it a red «!»
whose click says «той самий вендор, що й Генератор … Рецензія відбувається, але …». Red is for what
does not run (his rule the same day: red an error, orange/yellow a warning).

**Where.** Mac, `b2ed5d6`, the footer (screenshots 24 and 25).

**Task.** None yet.

**Built:** tcc#86 — the «!» is yellow when all it says is a warning (same vendor, Flash, substituted, another model answered), red when the pick cannot review.

### 101. The reviewer list: the models that answered could be green

**What.** The Arbiter: «може покрасити зеленим ті моделі що запрацювали». The list colours the
refused ones red («OMP · Claude Opus 5 · відмова», «OMP · GPT-5.6-Terra · відмова»); the one that
answered («OMP · Claude Sonnet 5») looks like one never tried.

**Where.** Mac, `b2ed5d6`, the AI CRITIC list (screenshot 26).

**Task.** None yet.

**Built:** tcc#86 — a reviewer that answered this launch is green in the list.

### 102. Windows: no omp session starts — «Unknown tool in --tools: inspect_image»

**What.** «Запускаю OMP · Claude Opus 5.5 …», then «ПОМИЛКА СЕСІЇ ⚠️ RuntimeError: omp exited before
reporting ready CliUsageError: Unknown tool in --tools: inspect_image. Valid tools: read, write, edit,
glob, grep, bash, ask, ast_edit, goal, init_experiment, run_experiment, log_experiment, update_notes.»
TCC starts omp with `--tools read,write,edit,glob,grep,bash,ask,inspect_image` (`omp_session._ENABLED_TOOLS`);
the VM's omp has no such tool. The VM's omp is **17.4.0**, the Mac's 17.2.9: a newer omp dropped
`inspect_image`, and TCC names it in a fixed list.

**Where.** Windows VM, `3ef4787`, the in-app dialog, omp route (screenshot 28, 2026-09-27).

**Weight.** High: no omp session at all on that machine.

**Task.** None yet.

**Built:** tcc#87 — when omp refuses a tool of TCC's allowlist it names the ones it has; TCC starts
it once more with the allowlist narrowed to those (`tools_omp_takes`), and logs the change.

### 103. Windows: an omp session warns the project has no `.claude/skills/autosound-tuning`

**What.** «Запускаю OMP · Gemini 3.1 Flash Image …», then «⚠️ This project has no
`.claude/skills/autosound-tuning`. The session will run without the tuning method and improvise one —
link the skill into the project before trusting anything it says.» The project is
`C:\Users\o.yukhno\dev\testAgy-auto`; TCC links the skill in before an omp session starts
(`vendor_loader.link_skill_into`), and the VM's log (14:48:22, `omp --mode`) says nothing of why the link
is not there. Also on screen:
the generator was «OMP · Gemini 3.1 Flash Image» — an image model offered as a generator.

**Where.** Windows VM, `3ef4787` (screenshot 27, 2026-09-27).

**Task.** None yet.

**Built (a hypothesis, to check on the VM):** tcc#88 — a symlink on Windows needs Developer Mode or an
admin (WinError 1314), and `link_skill_into` swallowed the refusal; it falls back to a junction, as the
skill's `install.ps1` links.

### 104. Windows at `3ef4787`: #62 still there, #66 gone

**What.** The Arbiter on the VM, 2026-09-27:
- a start still shows an extra terminal window before the splash (finding 43; the log has `agy models`
  and `claude.EXE auth` spawned before the splash, 14:46:53–55);
- switching into «Режим контролю» still flashes many small Windows windows (finding 45);
- a pin made from the desktop icon still gives a second taskbar icon («Autosound TCC» beside the running
  «Tuning Command Center», screenshot 30; finding 44);
- «порівняти з» lists the versions («—», `v_012`, `v_011`, screenshot 29) — #66 holds.

**Where.** Windows VM, `3ef4787`, project `testAgy-auto`.

**Task.** tcc#62 (open), tcc#66 (checked live).

**Found and built (the switch):** each control-mode tab's `DetailPane` was made with no parent and shown
(`_embedded`, then `open_table`/`open_eq`) before its tab took it — a shown widget with no parent is a
window, one per tab, on the way in only. Panes are now born under a hidden parent. tcc#62.

**The terminal before the splash — by design, kept (the Arbiter, 2026-09-27).** It is TCC's own console
(`child.claim_app_console`): Windows cannot create a console already hidden, so one console with a line
saying what starts is held while the models are read and then hidden, and every child runs silent inside
it — his decision of 2026-09-11/13, against a flash per child. Told so, he kept it.

**The second taskbar button — measured, not fixed (2026-09-27).** The desktop `.lnk` carries
`System.AppUserModel.ID = dev.autosound.tcc`; its pinned copy in `User Pinned\TaskBar` carried none, and a
fresh pin from the desktop again none — Windows drops the id when it pins a shortcut. TCC's own stamp put
the id on the pinned copy and Explorer was restarted: still two buttons (Windows keeps what the pin was at
pin time). A pin from the running window stays one button (F-037). The Arbiter: the hint now, the research
in W-4 — the reference and the installer say «pin it from its running window»; W-4's item is TODO F-087.

**Checked live 2026-09-27 (VM, `17dd4fc`):** the switch into control mode flashes nothing.

## W-4 · v0.1.45 — collection

### 105. Control mode's header in a small window: labels cut, and «порівняти з» empty though it has versions

**What.** The Arbiter, 2026-09-27: «в повному режимі при невеликому розмірі вікна … поле "порівняти з"
обрізано, а в такому варіанті зовсім пусто (хоч там є вибір)».
- Screenshot 1 (EQ tab, «⇄ L + R» on): the «порівняти з» box shows «v_0(» — the version cut; the tab
  «Затримки» and the chip «Output: c» cut too.
- Screenshot 2 (a narrower header with «⇅ П», «Копі», «інша»): every tab label cut («Табл», «EQ v»,
  «Ріве», «Затр», «Фаз»), «порівнят», «закр», and the compare box is empty while it has versions to pick.

**Where.** Mac, full mode (control mode), a small window; the header of the DSP tables pane.

**Weight.** Medium: the compare box looks empty — nothing says a version can be picked.

**Task.** tcc#96 (W-4).

### 106. Windows: an omp session hangs on «Запускаю OMP · …» — the retry of tcc#87 leaves the dead omp's end-marker in the queue

**What.** The Arbiter, 2026-09-27: «в ТСС під віндоус не стартує ШІ на OMP» — «зависання». The dialog shows
only «Запускаю OMP · Claude Sonnet 5 — перший хід читає скіл і стан проєкту, тому повільний.», nothing after
(screenshot 3). The VM's log: 20:17:40 and 20:23:01 «omp refused --tools …inspect_image; starting again with
…», and after the second one omp WORKED — `get_tcc_state`, `report_phase`, `show_plan`, `reconcile_plan` at
20:23:09–18 — while the dialog stayed empty.

**Where.** Windows VM, omp 17.4.0, TCC at the W-3 branch (title «TCC 0.1.43 · skill 3.0.63»), project
`testAgy-auto`. Every omp session on a machine whose omp has no `inspect_image` — the Mac too, once its omp
(17.2.9) updates. In v0.1.44.

**Cause (found 2026-09-27, reproduced on the Mac).** `OmpSession._start_process` (tcc#87): the refused omp
exits, its frame reader ends and puts `None` — «the process ended» — into `self._events`. The retry makes
fresh `_ready`/`_ended` events but keeps the queue. The opening turn's `_prompt` then reads that `None` first
and returns as if omp died mid-turn: no event, no notice, no turn end. The second omp runs the prompt, and
what it says waits in a queue nobody reads. Reproduced with the test's fake omp: after `_start_process()` the
queue holds one item, `None`. The test of tcc#87 checks `_start_process` only, never a turn after it.

**Weight.** High: no omp session is usable on that machine.

**Task.** tcc#97 (W-4).

**Fixed on `wave-0.1.45` (2026-09-27, the Arbiter: «лагоди зараз»):** the retry starts the second omp with an
empty event queue. Tests: `test_the_first_turn_after_the_tools_retry_shows_what_omp_says`.

**Checked live 2026-09-27 (the second Mac, omp 18.x, `75d8c53`):** «OMP · Claude Sonnet 5» answered in the dialog. The
Arbiter: «досить довго чекав» — the first turn is slow, not timed.
The reviewer through omp answered too (`omp:anthropic/claude-opus-5-5`, «Зв'язок є», the project's state read from
disk): the omp route works end to end.

**omp 18 (2026-09-27).** The Arbiter's fresh Windows install brought omp **18.3.5**. omp 18 has no
`inspect_image` at all (no file names it in the v18.2.4 or v18.3.5 trees), so there every session is refused on
`--tools`, takes the retry and hangs, whatever the model. tcc#97's fix is checked against omp 18 too — TCC has
not run against a major 18 yet.

### 107. «Оновити TCC» updates TCC alone: omp and the other tools stay where they were

**What.** The Arbiter, 2026-09-27, after «Оновити TCC» on the second Mac (0.1.43 → 0.1.44): «я оновлювався
ось буквально, чому не було оновлення всіх пакетів?» The button ran `uv tool install --upgrade
"autosound-tcc[gui,claude] @ git+…@v0.1.44"`: TCC and four of its Python packages moved
(`claude-agent-sdk`, `pyjwt`, `uvicorn`), 33 were already current. omp stayed at 17.3.8 (brew offers 18.2.4).
TCC's updater has two rows, TCC and the skill; omp, `agy`, `gh` and Claude Code are the installer's, and
nothing in the window offers them.

**Where.** The second Mac (MacBook Air), TCC's update row.

**Weight.** Low to medium: an old omp is what TCC then runs against, and nobody is told.

**Task.** Moved to the skill (the Arbiter: the installer is the skill's): hub #219 TCC-035. TCC's half, tcc#98, is deferred off W-4 until the skill names its command.

### 108. The omp models dialog, before omp is set up: an empty list and omp's raw error nobody can read

**What.** The Arbiter, 2026-09-27: «поки ще не налаштований omp бачу ось таке повідомлення під зоною скрола з
моделями, який ще пустий, але месседж не зрозумілий». Under the empty model list: «omp: `omp models` ended before
completing: the event loop drained while it was still pending (rerun with PI_DEBUG_STARTUP=1 to see the last
phase reached)», then «Налаштувати omp…», OK, Cancel (screenshot 5). Nothing says that omp is not set up yet
and that «Налаштувати omp…» is the next step.

**Where.** The fresh Windows install, omp 18.3.5 not set up yet, TCC v0.1.44, the omp models dialog.

**Weight.** Medium: the first thing a new omp user sees in TCC.

**Task.** tcc#99 (W-4).

### 109. omp 18 on the second Mac: a session fails «omp exited before reporting ready», and the reason is cut off

**What.** The Arbiter, 2026-09-27: «оновив руками omp до останньої версії — пішли запити. але ось що видало:
⚠️ RuntimeError: omp exited before reporting ready at dot (/$bunfs/root/omp-darwin-arm64:14767:9) at U9 (…:640398:12)
at async run (…:640622:14) at async iJr (…:1849:16) at async Ipo (…:643770:12)». The model list now fills; a
session does not start.

**Where.** The second Mac (MacBook Air), omp updated by hand to the latest (18.x), TCC v0.1.44.

**What the screen shows.** TCC's own line plus the last five lines of omp's stderr (`OmpSession._why`), and all
five are stack frames — omp's own message, the one line that says why, is above them and not shown.

**Cause (checked 2026-09-27, omp 18.3.5 downloaded to a scratch folder with its own HOME, the Arbiter's
machines untouched).** Started with TCC's own flags, omp 18.3.5 exits 1 with 14 lines of stderr: the source
excerpt, «CliUsageError: Unknown tool in --tools: inspect_image. Valid tools: read, write, …» on line 9, then the
five frames — the same five, at the same offsets, as on the Arbiter's screen. `_why` keeps the last five lines;
`tools_omp_takes` on them returns None, so there is no retry and the frames are all the message says. On the
whole stderr it returns the seven tools. With those seven, omp 18.3.5 reports `ready` in `rpc-ui` (protocol
1, 2). So on omp 18 two defects stand in a row: this one, and behind it 106's stale end-marker.

**Weight.** High: no omp session on omp 18.

**Task.** tcc#97 (W-4), with 106.

**Fixed on `wave-0.1.45` (2026-09-27):** stack frames and source excerpts are kept out of the stderr tail, so the
refusal is read and retried, and a failure shows omp's reason. Live, omp 18.3.5 in a scratch HOME: before — the
Arbiter's exact five frames; after — the retry, `ready`, and omp's own answer in the first turn («No API key found
for anthropic», that HOME has no login) with a turn end, in 2 s. Tests: `test_omp_18s_refusal_behind_a_stack_is_still_read_and_retried`,
`test_a_failure_names_omps_reason_not_its_stack_frames`.

### 110. The dialog's messages carry no time

**What.** The Arbiter, 2026-09-27, after a slow first omp turn («досить довго чекав»): «може додати тайм-маркери
для повідомлень?» The bubbles (ARBITER · YOU, SYSTEM · TCC, GENERATOR · …) show who spoke, not when; how long a
turn took cannot be read off the screen.

**Where.** The second Mac, the in-app dialog (screenshot 6).

**Weight.** Low: a want, not a defect — but it is what would have measured the slow first turn.

**Task.** tcc#100 (W-4).

### 111. «У фокусі зараз»: an RTA capture listed under SWEEP (SW)

**What.** The Arbiter, 2026-09-27: «звернув увагу на REW — там в колонці sw записаний rta!» Round `cap_016`: the
SWEEP (SW) column holds one row, `L m+tw_55 (rta) inv`, green; the MMM RTA (RTA) column holds `m-L_55 (rta)`,
`m-R_55 (rta)`, `Ms_55 (rta)`, `ALL_55 (rta)`, `L m+tw_55 (rta)`. A title marked `(rta)` sits in the sweep column
(screenshot 8). Seen, not examined: it is the one title with `inv`.

**Where.** The second Mac, TCC at `wave-0.1.45`, the «У фокусі зараз» panel, round `cap_016`.

**Weight.** Medium: the panel says a sweep was taken when the capture is an RTA.

**Related.** Finding 30, item 3 — a sweep labelled `(rta)`, the other way round.

**Task.** tcc#101 (W-4).

**Cause (found 2026-09-27 on the project's copy, `research/raw/prj_to_compare/1_EPY-Sep2026`, read only).** Round
`cap_016` in `process/process-state.json` carries no `groups`, so the panel sorts its six `expected` titles itself
(`measurement_view.groups_from_titles`) — by the title's END: `(sw)` or `(rta)`, else sweep. `L m+tw_55 (rta) inv`
ends with `inv`. The method's parser reads that title right — `method: 'rta'`, `params: 'inv'` — and TCC already
calls it for the spelling (`_canonical`), then sorts by the suffix anyway. TCC's own code on the copy gives exactly
the screen: `sw ['L m+tw_55 (rta) inv']`, `rta [the other five]`. Fix: sort by the parsed `method`, the suffix only
for a title the grammar does not read.

### 112. «Порівняти з»: the open configuration's versions sit at the top without a name, and its current one is not there

**What.** The Arbiter, 2026-09-28: «вибрана конфігурація 4. … в конфігурації 3. є два варіанта. Тепер вибираємо
конфігурацію 3. і не бачимо її варіантів налаштувань, але бачимо що в 4. теж два варіанти, а ми до цього їх теж не
бачили. це бага в ТСС чи в файлах проекту?» With `4.C-cut` open the list reads «—», `v_001`, then `1.B-base — інший
пресет` with `v_006…v_001`, `3.S-shelf` with `v_002 v_001`, and so on; `4.C-cut` is not among the named groups.
With `3.S-shelf` open it is the same the other way round (screenshots 1 and 2).

**Where.** This Mac, TCC at `wave-0.1.45`, project `car/passat-b8-2026-aya`, the EQ tab's «порівняти з».

**Weight.** Low: nothing is lost, the list reads as if it were.

**Cause (found 2026-09-28).** Not the project's files: `state/3.S-shelf` … `state/7.E-epy` each hold `v_001` and
`v_002` with `HEAD` = `v_002`. TCC shows the open configuration's versions first, with no heading
(`detail_pane.fill_compare_combo`), and leaves the current one out, since a version is not compared with itself
(`ledger_line.compare_groups`, `v != current`). So the lone `v_001` at the top is the open configuration's other
version, and its `v_002` is the one on screen. Every other configuration gets a heading, so the open one looks
missing. Way out: a heading over the first group too («4.C-cut — цей пресет»), and the current version shown
greyed as «v_002 — зараз».

**Task.** tcc#103 (W-4), no `ok` yet.

### 113. The DSP tree at the bottom left marks EQ changes only: a changed HP, delay or polarity has no mark there

**What.** The Arbiter, 2026-09-28: «ось тут не відображається признак змін в нижній лівій зоні, а треба. і те саме
ось тут по затримці і полярності … звісно це все має працювати і для всіх інших відхилень/змін.»
- Screenshot 4: the output table has sw's HPF `20 BW4` in blue, changed. In the tree, sw's line reads
  `HP 20 BW4 · LP 80 LR4 · -6.0dB` with no mark on the HP; only the EQ marks beside it (`● (1)` new, `● (2)` changed).
- Screenshot 5: `6.R-right` against `v_006`. The table has m-R's and tw-R's delay `4.19` and polarity `NORM` in blue,
  changed. In the tree, m-R and tw-R carry no mark at all. The output line does not show the delay either.

Wanted: every field that differs from the compared version marked in the tree too, on every tier, not EQ alone.

**Where.** This Mac, TCC at `wave-0.1.45`, project `car/passat-b8-2026-aya`, the DSP tree («ВИХІДНІ»), with
«порівняти з» set.

**Weight.** Medium: the tree is where a change is seen at a glance, and it shows only part of them.

**Task.** tcc#104 (W-4), no `ok` yet.

### 114. The full mode at its minimum width: the DSP table cannot be read, and the tabs lose their names

**What.** The Arbiter, 2026-09-29, the Windows VM, TCC at `wave-0.1.45` (`1ee915b`), project `testAgy-auto`, the
window at its minimum size: «добре було б залишити хоч перші літери чи замінити назви на літери-коди. хінт спасає,
але не зразу розумієш що там є закладки … в цілому таблицю не розбереш — тому такий режим НЕ РОБОЧІЙ і треба або
вікно збільшити або перейти в режим контроль».
- Screenshot 1: the detail pane's head at the minimum — the tabs show no words (only the hover says «Таблиця»), the
  header reads «Virtual channels · порівняти з [v_002] [інша конфігур…] [закрити]».
- Screenshot 3: the output table at the minimum — every cell elided: «300 …», «70 …», «350…», «NO…», «GAIN DE»,
  «ELAY M».
Wanted: the full mode is usable at its minimum — either the window's minimum grows until the table reads, or it
hands over to control mode; tabs keep at least their first letters or a letter code rather than nothing.
Fine as is: the compare list itself («список для вибору конфігурації для порівняння — все ок»).

**Weight.** Low — the Arbiter's verdict the same evening: «це не проблема — бо при зовсім мінімальній ширині не
очікуємо що все буде придатно. може збільшити мінімальну ширину трохи?» So: raise the full mode's minimum width a
little. His widths for the header: full screen — a huge margin; half the screen — problems; 2/3 — all fine.

**Task.** tcc#106 (W-4, taken 2026-09-29 by the Arbiter's word «беремо зараз, треба довести ТСС до робочої версії»).

### 115. Control mode at its minimum width: the 3500 crossover is cut

**What.** The Arbiter, 2026-09-29, same session: control mode at the minimum width is «почти ок»; the LPF of m-L and
m-R and the HPF of tw-L and tw-R read «3500 …» (screenshot 4) — «не критично, розмір зробити трохи більше і ок».

**Weight.** Low.

**Task.** tcc#107 (W-4, taken 2026-09-29).

### 116. The DSP tree's changed crossover: blue is not enough to see it

**What.** The Arbiter, 2026-09-29: the tree line of w-R reads «HP 70 LR4 · LP 400 LR4 · +0.0d…» with «HP 70 LR4» in
blue, changed against «порівняти з» (tcc#104, screenshot 2) — «було б добре зробити жирним підсвічений кросовер —
щоб було видно».

**Weight.** Low: the mark is there, it does not stand out.

**Task.** tcc#108 (W-4, taken 2026-09-29; built `d73e54d`).

### 117. «У фокусі зараз»: captures named `(rta)` listed under SWEEP (SW) in testAgy-auto

**What.** The Arbiter, 2026-09-29, `testAgy-auto`: round `cap_010` lists «D_L_7 (rta) m-L: lev=-4.5, PK=-2» and
«D_L_7 (rta) m-L: lev=-4.5, PK=-4.5» under SWEEP (SW) (screenshot 5); round `cap_013` lists «D_L w+m_9 (rta) inv» and
«D_R w+m_9 (rta) inv» under SWEEP (SW), and «D_L w+m_9 (rta)» / «D_R w+m_9 (rta)» under MMM RTA (screenshot 6).
His note: «але може це там на рівні даних — тому що мені ніхто не завадить привʼязати любу назву до sweep задачі,
навіть з rta в назві».

**Weight.** Low until the cause is known — finding 111 / tcc#101 fixed the sorting of titles by their parsed method
on `wave-0.1.45`, so either the round carries its own groups (the task, not the title, decides), or a title the
grammar does not read falls back to sweep.

**Cause (2026-09-29, from the project's `process-state.json`).** Not the round's data: `cap_013` carries no groups;
the `… (rta) inv` titles were taken beyond the plan. The method's grammar reads a note after the method tag, but
refuses these titles for their `D_` prefix (rule S-042), and TCC then sorted a refused title by its last word
(`inv`, `PK=-2`) and defaulted to sweep. The Arbiter the same evening: «наші префікси були помилкою — треба було
робити різні конфігурації і додавати літеру перед номером заміру як ми робимо зараз в проекті рісьоча» — so the
grammar is right to refuse `D_`; TCC now reads a refused title's tag where the grammar places it.

**Task.** tcc#109 (W-4, built `50419d6`).

### 118. Control mode opens shifted to the left on the Windows VM

**What.** The Arbiter, 2026-09-29, the Windows VM, `wave-0.1.45`: «в Режимі контроль на пів екрана все ок — тільки
відкривається якось дивно — зʼїзджає ліворуч» (screenshot: the control-mode window's header begins at the screen's
edge, «інша ко…» cut at the right).

Wanted, the Arbiter 22:32: «треба щоб він відкривався ось так при переході в режим Контроль» — his screenshot shows
the control-mode window on the RIGHT half of the screen, its full height, the left half free (a terminal there).

**Weight.** Low: it works; the placement is off.

**Task.** tcc#110 (W-4, taken 2026-09-29).

### 119. The full mode's detail pane elides its tabs at full screen width on Windows

**What.** The Arbiter's screenshot, 2026-09-29, the Windows VM, full mode at full screen: the detail pane's tabs read
«Табл…», «Рі…», «Затри…», «Ф…» with wide empty gaps between them, and «закрит…», while the pane has room; at 2/3 of the
screen the same tabs read whole. Before W-4 these tabs drew their whole text: tcc#96's eliding (the head's chips and
tabs) elides where it should not on Windows metrics — the same family as the CI failure of PR #105's Windows shard
4/4 (five header tests written against Mac pixels).

**Weight.** Medium: a regression of W-4's own work, seen at full screen.

**Task.** tcc#96, fix round 5 on `wave-0.1.45`, before the release.

### 120. The installer does not check TCC's signature: it says so for the method, nothing for the app

**What.** The Arbiter, 2026-10-01, the Mac, the install line over v0.1.44 (hand check of v0.1.45): the app's block
printed `version v0.1.45` and `✓ installed`, and nothing about a signature. «а чому він не пише що поставив
підписаний тег ТСС? на скілу так писав». Read, not diagnosed: `skill/install.sh` verifies only the method's tag
(`SKILL_SIGNED_FROM`, «✓ … is signed by the skill's author»); the app goes in by `uv tool install … @<tag>` with no
`verify-tag`. TCC's tag is checked only by TCC's own «Оновити ТСС», from v0.1.45. Same in `install.ps1` as far as
a grep shows. So a fresh install or an update by the install line takes an unchecked TCC tag.

**Weight.** Medium: the release is signed, and the first install — the one path a new user takes — does not look.

**Task.** The installer is the skill's code. **Decided 2026-10-01** at the pre-release walk: W-5, as the skill's ticket — hub #224 TCC-038 (to:skill); nothing changes on TCC's side.

### 121. The taskbar pin (#92): TCC's stamp plus a shell notify makes a desktop pin one button

**What.** The Arbiter, 2026-10-01, the Windows VM, v0.1.45, the hand check of `docs/RESEARCH-W-4-taskbar-pin.md` §4:
- step 1: Start knows the id — `Autosound TCC` · `AppID : dev.autosound.tcc` (the two «(Mac)» rows are Parallels'
  shared Mac apps); step 5 not needed;
- steps 2–3: a fresh pin from the Desktop shortcut carries no id — `Autosound TCC =` (as on 27.09);
- step 4: `_stamp_windows` on the pinned `.lnk` plus `SHChangeNotify(SHCNE_UPDATEITEM, …)` — step 3 then reads
  `Autosound TCC = dev.autosound.tcc`; TCC started from the pin is **one button** («перемога! одна»,
  screenshot: one «Tuning Command Center» button beside `claude`). TCC's own console showed as a second button at
  the start and went away — the console kept by design (finding 104).

**Weight.** Low: two buttons, both work; the hint («pin it from its running window») stands meanwhile.

**Task.** The lever is found (§4 «Step 4 gives one button»): TCC repairs its own pins after the window is shown —
the `.lnk` files in `User Pinned\TaskBar` and `User Pinned\ImplicitAppShortcuts\*` that start TCC's launcher and
lack the id get the stamp and the notify; a byte search, no spawn on an ordinary start; ~30 lines and tests.
Expected when checked: the first start from a fresh desktop pin is still two buttons, one from the next start.
tcc#92 (closed with W-4) carries the research. **Decided 2026-10-01** at the pre-release walk: W-5.

### 122. The import form's typo match goes to the first close row in REW's order, not the closest: an older series is offered, the real typo gets nothing

**What.** Checked by the session on the Arbiter's word («щось ти можеш і сам зробити — REW відкритий»), 2026-10-01,
the live REW on the Mac (69 measurements, the AYA session), TCC v0.1.45's `capture_import.preselect`, two titles
renamed for the check and put back (the Arbiter did not save REW):
- `sw_S3 (sw)` renamed `sw_03 (sw)`, the round expecting `sw_3 (sw)` → New name `sw_3 (sw)`, unticked, `≈` — as
  F-081 promised;
- `sw+w-L_S3 (sw)` renamed `sw+w-L_3 (se)` (a typo of `sw+w-L_3 (sw)`, similarity 0.92) → **no proposal**. The
  three missing names went instead to the older series earlier in REW's list: `sw_B1 (sw)` → `sw_3 (sw)`,
  `sw+w-L_B1 (sw)` → `sw+w-L_3 (sw)`, `sw+w-R_B1 (sw)` → `sw+w-R_3 (sw)`, each `≈`.

Read, not diagnosed further: the typo pass walks rows in REW's order and gives a missing name to the first title at
`difflib` cutoff 0.8; another series of the same driver passes that cutoff, and the name is then gone for the closer
row.

**Weight.** Medium: the guard holds (an `≈` row opens unticked), but the form points at the wrong curves and says
nothing about the right one — in a session with several series, which is every session.

**Task.** For W-5's collection.

### 123. «Не питати взагалі (авто)» ticked, and TCC asks again — a read-only command as «Команда, яку не відкотити»

**What.** The Arbiter, 2026-10-01, the Mac, TCC 0.1.45 · skill 3.0.64, project `passat-b8-2026-aya`, a new session
asked «перевір критика зразу при старті через режим ASK». Settings → «Питати про» shows `✓ Не питати взагалі (авто)`;
the chat stopped on «Дозволити Bash?» — «Команда, яку не відкотити: `cd /Users/o.yukhno/dev/autosound/tcc/src/autosound_tcc
&& f=$(grep -rl "def run(" --include='*.py' core | xargs grep -l "MODE_CLIPBOARD" | head -1); echo $f; grep -n
"role\|ask\|advisor" $f | head -50`». The Arbiter: «вах, знову питає коли галочка стоїть не питати!»

Facts off the screenshot, not diagnosed: the command only reads (`grep`, `head`, `echo`), and it holds a real
`$( … )` substitution; it runs outside the project folder, in TCC's own source tree — the session was looking
through the app's code for how to reach the reviewer, rather than using the method's call.

**Weight.** High, and the fourth time: findings 7 and 15, then 0.1.41 (the `|` inside a grep pattern, closed on
`wave-0.1.42`). A prompt in a mode set to never ask teaches clicking through without reading.

**Again the same hour, the Windows VM, project `testAgy-auto`** («і знову ця біда»): «Команда, яку не відкотити: cd
"C:/Users/o.yukhno/dev/testAgy-auto/state" && cat registry.json; echo; echo "master HEAD: $(cat master/HEAD)"; …;
for v in 010 011 012 013; do python3 -c "import json,sys;d=json.load(open(…))…"; done; ls master/proposals» — inside
the project this time, and again only reads: `cat`, `echo`, a `for` loop, `python3 -c` printing JSON, `ls`, with
`$( … )` substitutions.

**The Arbiter's proposal (same day):** «а це є окремий запит коли "не відкотити"? то для нього треба додати пункт
вибору "взагалі не питати"». Today the irreversible class asks under every choice, by design (finding 1's text:
«Те, чого не відкотити, питатиме за будь-якого вибору»). Two halves for the review: a fourth choice that does not
ask even then (it lifts the last guard — a delete or an overwrite outside the project would go unasked), and the
misreading itself: a read-only command filed as irreversible.

**Task.** For W-5's collection.

### 124. No ASK mode for the reviewer through TCC: a free question goes out in the Critic's role with the tuning contract

**What.** The Arbiter, 2026-10-01, the Mac, the same session as 123: «перевір критика зразу при старті через режим
ASK». The session searched TCC's own source for how `call_critic` picks ASK (the command 123 was asked about), then
sent a short question through `call_critic`: the channel answered in 8 s over the Google API,
`gemini-3.1-pro-preview` (17 × 23 = 391 right; asked who it is, the model called itself «GPT-4o, OpenAI» — the
session did not trust the self-report, the route was Google's). The session's conclusion: «Режиму ASK через TCC
немає: `call_critic` завжди запускає роль Критика з контрактом тюнінгу … Справжній ASK — це `autosound_ai.py ask`, а
запускати його з сесії TCC заборонено.» It offered to file a request for a role parameter on `call_critic`.

**Weight.** Medium: the reviewer check works, but a plain question to the reviewer has no door in TCC, and the
session goes digging through the app's code to find one.

**Task.** For W-5's collection.

### 125. The reviewer-key window on Windows: «… у HKCU\Environment, рядок None» and «бачить кожна програма, запущена з термінала»

**What.** The Arbiter, 2026-10-01, the Windows VM, TCC 0.1.45, «Ключ рецензента…»: the key saved — «Збережено:
GEMINI_API_KEY — у захищеному сховищі (файлі, зашифрованому твоїм входом у Windows)», Google (Gemini) «у захищеному
сховищі» ✓. Under it, red: «GEMINI_API_KEY досі експортується у HKCU\Environment, рядок None. Його бачить кожна
програма, запущена з термінала …». A registry value has no line, so the sentence prints Python's `None`; and a
user variable in `HKCU\Environment` is seen by every program the user starts, not only from a terminal — the
sentence is the macOS one (`~/.zshrc`, a line) applied to Windows.

**Weight.** Low: the save and the warning work; the words are wrong on Windows.

**Task.** For W-5's collection (`rkShell` in i18n, four languages).

### 126. The same window on Windows: the «Перенести (відкриє термінал)» button cuts its text on both sides when hovered or focused

**What.** Same screenshots: drawn plain, the button reads whole; hovered/focused (the tinted state) it reads
«Іеренести (відкриє термінал» — the first letter eaten, the closing bracket gone. The class of finding 1 (a
button's first letter cut), in a dialog that came after it.

**Weight.** Low.

**Task.** For W-5's collection.

### 127. Saving a key that also sits in the environment leaves the copy there: no «remove it from there?» and no delete

**What.** The Arbiter, 2026-10-01, the Windows VM, after 125: «Перенести» opened a terminal — «Перенести
GEMINI_API_KEY з HKCU\Environment у сховище Windows, зашифроване вашим входом (DPAPI) і прибрати звідти? [y/N] y» →
«✓ … збережено … У вже відкритих терміналах змінна ще жива -- відкрий новий»; reopened, the window shows Google
(Gemini) «у захищеному сховищі» and no red line ✓. His point: «але якщо я не переніс ключ, а вставив його і зберіг,
то треба мати питання чи видалити ключ, чи мати кнопку видалити, коли ключ вже є в сховищі і при цьому ще є в
файлі». Today «Зберегти» stores the key and leaves the exported copy; only «Перенести» removes it.

**Weight.** Low–medium: the key stays readable to every program until the tuner finds the second button.

**Task.** For W-5's collection — the delete or the question is the method's command first (`autosound_ai.py key`),
TCC's button on it.

### 128. A key saved in «Ключ рецензента» does not lift the API rows' «відмова»: the reviewer picker stays red until ↻

**What.** The Arbiter, 2026-10-01, the Windows VM, right after 127 (key in DPAPI, nothing exported): the reviewer
picker shows `API · gemini-pro-latest · відмова` and `API · gemini-3.1-pro-preview · відмова` in red, only
`OMP · Gemini 3.1 Pro` green; the footer: `AGY · Gemini 3.1 Pro` «Gemini 3.1 Pro (Low) · останній виклик відх…».
«і не можу вибрати модель».

Read, not diagnosed: «відмова» is `availability.REFUSED` — «the last call to it was refused» in this launch, i.e.
before the key existed; refusals are forgotten only by ↻ (`main_window.py` ~1857, `forget_refusals`). Saving a key
in the dialog refreshes the dialog's own `key status`, not the picker's memory of refusals.

**Weight.** Medium: the tuner fixes the cause in the window made for it and the app still refuses the route; the
way out (↻) is not named anywhere near.

**After ↻ (same minutes):** `API · gemini-pro-latest` is no longer red; `API · gemini-3.1-pro-preview` still reads
«відмова» — the same model answered over the API on the Mac an hour earlier (124). `agy` in a fresh PowerShell on the
VM answers (Antigravity CLI 1.2.14, Gemini 3.8 Flash (High), «hi» → «Hello!»).

**Task.** For W-5's collection.

### 129. Flash cannot be picked as the reviewer: «не рекомендується» is one thing, the choice should stay the tuner's

**What.** The Arbiter, 2026-10-01, the Windows VM, the reviewer picker (128's screenshot: every `AGY · Gemini 3.x
Flash` row and `OMP · google-antigravity/…-flash-high` greyed «не для рецензента»): «і чому Flash не вибирається?
"не рекомендується" це одна справа, але вибрати — хай користувач вирішує».

**History, so the review sees what this reverses:** finding 85 (2026-09-27, tcc#74 on W-3 by the Arbiter's word)
named «Flash picks are offered for the reviewer, a class the method forbids there»; W-3 built the rows greyed with
the reason, a current Flash pick kept selected and carrying a warning in the state. What changed: the Arbiter, now
on a machine where the Pro routes refuse (128) and Flash answers in a terminal, wants the warning without the lock.
The rule itself is the method's — a Flash reviewer is a skill question as much as a TCC one.

**Weight.** Medium: with the Pro rows refused, the picker leaves no reviewer the tuner can choose.

**Task.** For W-5's collection.

### 130. A model left in the machine's critic-env outranks TCC's pick: «API · gemini-3.1-pro-preview» runs as `gpt-5.6-terra`

**What.** The Arbiter, 2026-10-01, the Windows VM, `autosound_ai.py doctor` (asked to tell a bad key from a good one,
128): «✓ Знайдено ключ API: GEMINI_API_KEY (google) -- зі сховища ключів: … (DPAPI)», «GEMINI_API_KEY: current (AQ.…,
53 chars)» — the key is there and is the current one; «▶ Рецензент: gpt-5.6-terra → провайдер openai
(AUTOSOUND_CRITIC_MODEL, з файлу C:\Users\o.yukhno\AppData\Roaming\autosound\critic-env)», «✗ Живий виклик не
вдався: OpenAI Codex v0.152.0 …».

Read, not diagnosed past this: TCC hands its pick as `GEMINI_CRITIC_MODEL` (`core/critic.py`, `env_overrides`);
the method reads `REVIEWER_MODEL_VARS = ("AUTOSOUND_CRITIC_MODEL", "GEMINI_CRITIC_MODEL")` in that order, and a
critic-env file's lines are written over the environment. So a model left in the machine file wins over every pick
in the footer — here an OpenAI model sent down the Google key's route, which reads as «відмова» (128). The Mac's
file does not set it, so the Mac works.

Also in the same output: «Інсталятор: install.ps1 для beta-v3.0.64-rc2 … рушій: not fetched: beta-v3.0.64-rc2
carries no engine for this machine» — the VM's method clone came from a release candidate's installer.

**Weight.** High: the footer says one reviewer and another is called; the tuner cannot see why.

The same file also holds `AUTOSOUND_CRITIC_PROVIDER=openai`, which `provider_for` returns before it reads the
model's name at all — so with the model line gone, a Gemini pick would still be sent as OpenAI's. The Arbiter
comments out both by hand on the VM.

**Task.** For W-5's collection — the precedence is the method's and TCC's together.

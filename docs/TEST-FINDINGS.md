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

### 13. "Update TCC" opens a second, empty console

**What.** Beside `Administrator: cmd`, which runs the update, a second window
`C:\Windows\System32\cmd.exe` opened, empty, with only a cursor.

**Where.** The same screenshot, the second machine.

**Ours or external.** Ours: F-043 (the second source in hub #73, TCC-006), still in v0.1.39.

**Weight.** Low to medium: confusing, not harmful.

**Reproduces.** Known since 2026-09-06.

### 14. First start after the update: a terminal window blinks behind "Reading models"

**What.** On the first start of 0.1.39, TCC's own console (`Autosound TCC: reading models...`)
appears and another terminal window blinks behind it. On later starts there is no extra window.
Apart from that first start, no window blinks at all — during work or on start. That is the check
hub #73 (TCC-006) was waiting for, and it passes.

**Where.** The Arbiter's Windows VM, 0.1.39, method 3.0.52.

**Ours or external.** Not known.

**Weight.** Low: once, right after an update.

**Reproduces.** Only on the first start after the update so far.

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

### 18. Too wide a gap between the AI dialog and the right column

**What.** Between the right edge of the AI dialog's working area (the composer with "Send" and the
transcript's scrollbar) and the border of the right column there is more empty space than anywhere
else in the window.

**Where.** The Arbiter's screenshot, Windows VM, light theme, 0.1.39.

**Ours or external.** Ours.

**Weight.** Low: layout.

**Reproduces.** Always, on that window size.

### 19. Feedback has one way out: GitHub

**What.** The feedback dialog ("Відгук про прототип TCC") offers a single radio button, "GitHub
issue (маю акаунт)", and "Надіслати в GitHub →". Somebody without a GitHub account, or without
access to it, has no other path. A radio group of one option is also a choice that is not one.

**Where.** The Arbiter's screenshot, Windows VM, 0.1.39.

**Ours or external.** Ours. Related: TODO F-042 (how to report a defect and hand over settings when
GitHub is not available).

**Weight.** Medium: a tester without GitHub cannot report from the app.

**Reproduces.** Always.

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


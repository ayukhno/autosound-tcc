"""The new-project dialog's strings: four languages side by side per key (G13 B3, #162).

Plain data that imports nothing; `i18n` joins it into its table (`strings.FEATURES`). uk and en
by the builder, pl and de through the Advisor. The two buttons six dialogs share, `npBrowse` and
`npCancel`, stay in `i18n`'s own table.
"""

STRINGS: dict[str, dict[str, str]] = {
    'npTitle': {
        'en': 'New project',
        'uk': 'Новий проєкт',
        'pl': 'Nowy projekt',
        'de': 'Neues Projekt',
    },
    'npFolder': {
        'en': 'Project folder',
        'uk': 'Тека проєкту',
        'pl': 'Folder projektu',
        'de': 'Projektordner',
    },
    'npProfile': {
        'en': 'DSP profile',
        'uk': 'Профіль DSP',
        'pl': 'Profil DSP',
        'de': 'DSP-Profil',
    },
    'npAddNew': {
        'en': '+ Add new (not listed)',
        'uk': '+ Додати новий (немає в списку)',
        'pl': '+ Dodaj nowy (nie ma na liście)',
        'de': '+ Neu hinzufügen (nicht in der Liste)',
    },
    'npVendor': {
        'en': 'DSP vendor',
        'uk': 'Виробник DSP',
        'pl': 'Producent DSP',
        'de': 'DSP-Hersteller',
    },
    'npVendorPlaceholder': {
        'en': 'e.g. Helix, Musway',
        'uk': 'напр. Helix, Musway',
        'pl': 'np. Helix, Musway',
        'de': 'z. B. Helix, Musway',
    },
    'npModel': {
        'en': 'DSP model',
        'uk': 'Модель DSP',
        'pl': 'Model DSP',
        'de': 'DSP-Modell',
    },
    'npModelPlaceholder': {
        'en': 'e.g. DSP Ultra S, M6V4',
        'uk': 'напр. DSP Ultra S, M6V4',
        'pl': 'np. DSP Ultra S, M6V4',
        'de': 'z. B. DSP Ultra S, M6V4',
    },
    'npRunVia': {
        'en': 'Run onboarding via',
        'uk': 'Вести onboarding через',
        'pl': 'Prowadź onboarding przez',
        'de': 'Onboarding durchführen über',
    },
    'npRunInApp': {
        'en': 'In-app (Claude)',
        'uk': 'У додатку (Claude)',
        'pl': 'W aplikacji (Claude)',
        'de': 'In der App (Claude)',
    },
    'npAiModel': {
        'en': 'AI model',
        'uk': 'Модель ШІ',
        'pl': 'Model AI',
        'de': 'KI-Modell',
    },
    'npTerminalModel': {
        'en': 'Model (optional)',
        'uk': 'Модель (необовʼязково)',
        'pl': 'Model (opcjonalnie)',
        'de': 'Modell (optional)',
    },
    'npTerminalModelPlaceholder': {
        'en': 'e.g. {models} — blank = CLI default',
        'uk': 'напр. {models} — пусто = дефолт CLI',
        'pl': 'np. {models} — puste = domyślny CLI',
        'de': 'z. B. {models} — leer = Standard des CLI',
    },
    'npOnboardingHint': {
        'en': (
            "Use the autosound-tuning skill. This project's intake was filled on the form, so"
            ' read the project files first and continue from what the method still reports '
            "missing (contract.py check). Connect to this project's 'tcc' MCP server (see "
            '.mcp.json), and call the reviewer through its call_critic tool rather than '
            'running autosound_ai.py yourself. Please work in {language}.'
        ),
        'uk': (
            'Скористайся скілом autosound-tuning. Інтейк цього проєкту заповнено у формі, тож'
            ' спершу прочитай файли проєкту й продовжуй із того, чого метод ще не має '
            "(contract.py check). Підключись до MCP-сервера 'tcc' цього проєкту (див. "
            '.mcp.json) і викликай рецензента через його інструмент call_critic, а не '
            'запуском autosound_ai.py. Працюй {language}.'
        ),
        'pl': (
            'Skorzystaj ze skilla autosound-tuning. Intake tego projektu wypełniono w '
            'formularzu, więc najpierw przeczytaj pliki projektu i kontynuuj od tego, czego '
            "metoda jeszcze nie ma (contract.py check). Połącz się z serwerem MCP 'tcc' tego "
            'projektu (zob. .mcp.json) i wywołuj recenzenta przez jego narzędzie call_critic,'
            ' a nie uruchamiając autosound_ai.py. Pracuj {language}.'
        ),
        'de': (
            'Nutze den Skill autosound-tuning. Das Intake dieses Projekts wurde im Formular '
            'ausgefüllt; lies zuerst die Projektdateien und mach dort weiter, wo die Methode '
            "noch etwas vermisst (contract.py check). Verbinde dich mit dem MCP-Server 'tcc' "
            'dieses Projekts (siehe .mcp.json) und ruf den Reviewer über dessen Werkzeug '
            'call_critic auf, nicht durch Starten von autosound_ai.py. Arbeite {language}.'
        ),
    },
    'npSeed': {
        'en': 'System parameters',
        'uk': 'Системні параметри',
        'pl': 'Parametry systemu',
        'de': 'Systemparameter',
    },
    'npSeedNone': {
        'en': 'Ask during onboarding (from scratch)',
        'uk': "Спитати в інтерв'ю (з нуля)",
        'pl': 'Zapytać w wywiadzie (od zera)',
        'de': 'Im Interview fragen (von Grund auf)',
    },
    'npSeedFrom': {
        'en': 'Copy from an existing project…',
        'uk': 'Скопіювати з наявного проєкту…',
        'pl': 'Skopiuj z istniejącego projektu…',
        'de': 'Aus einem bestehenden Projekt kopieren…',
    },
    'npSeedPlaceholder': {
        'en': 'Folder of a project that has a project.json',
        'uk': 'Тека проєкту, у якій є project.json',
        'pl': 'Folder projektu, w którym jest project.json',
        'de': 'Ordner eines Projekts mit einer project.json',
    },
    'npSeat': {
        'en': 'Seat — who the copy is tuned for',
        'uk': 'Місце — для кого налаштовуємо копію',
        'pl': 'Miejsce — dla kogo stroimy kopię',
        'de': 'Hörplatz — für wen die Kopie abgestimmt wird',
    },
    'npSeatPick': {
        'en': '— choose the seat —',
        'uk': '— оберіть місце —',
        'pl': '— wybierz miejsce —',
        'de': '— Hörplatz wählen —',
    },
    'npSeatSource': {
        'en': 'In the source: {seat}. A different seat is exactly why a copy exists.',
        'uk': 'У джерелі: {seat}. Інше місце — саме те, для чого робиться копія.',
        'pl': 'W źródle: {seat}. Inne miejsce to właśnie powód, dla którego robi się kopię.',
        'de': 'In der Quelle: {seat}. Ein anderer Hörplatz ist genau der Grund für eine Kopie.',
    },
    'npSeatUnset': {
        'en': 'not set',
        'uk': 'не задано',
        'pl': 'nie ustawiono',
        'de': 'nicht festgelegt',
    },
    'npSeedFindings': {
        'en': '…and what was measured there (acoustic flaws, open questions)',
        'uk': '…і те, що там виміряно (акустичні вади, відкриті питання)',
        'pl': '…i to, co tam zmierzono (wady akustyczne, otwarte pytania)',
        'de': '…und was dort gemessen wurde (akustische Fehler, offene Fragen)',
    },
    'npSeedFs': {
        'en': (
            "…and the drivers' Fs from the impedance measurement (no need to measure it "
            'again)'
        ),
        'uk': '…і Fs динаміків із заміру імпедансу (міряти вдруге не доведеться)',
        'pl': '…i Fs głośników z pomiaru impedancji (nie trzeba mierzyć ponownie)',
        'de': '…und die Fs der Lautsprecher aus der Impedanzmessung (kein zweites Messen nötig)',
    },
    'npSeedNotAProject': {
        'en': 'No readable project.json here — nothing to copy.',
        'uk': 'Тут нема читабельного project.json — копіювати нема чого.',
        'pl': 'Nie ma tu czytelnego project.json — nie ma czego kopiować.',
        'de': 'Hier gibt es keine lesbare project.json — nichts zu kopieren.',
    },
    'npSeedSummary': {
        'en': 'Source: {car} · {dsp} · {channels} channels',
        'uk': 'Джерело: {car} · {dsp} · каналів: {channels}',
        'pl': 'Źródło: {car} · {dsp} · kanałów: {channels}',
        'de': 'Quelle: {car} · {dsp} · {channels} Kanäle',
    },
    # What the seeder REPORTS it would carry, not what the source holds. The two part
    # company the moment a different processor is picked: the profile stays behind, and
    # so does the channel topology, because topology belongs to the processor.
    'npSeedTravels': {
        'en': 'Travels: {channels} channel(s) · {amps} amp(s)',
        'uk': 'Поїде: каналів {channels} · підсилювачів {amps}',
        'pl': 'Pojedzie: kanały: {channels} · wzmacniacze: {amps}',
        'de': 'Kommt mit: Kanäle: {channels} · Endstufen: {amps}',
    },
    'npSeedTravelsFindings': {
        'en': (
            'Travels: {channels} channel(s) · {amps} amp(s) · {flaws} flaw-map row(s) · '
            '{questions} open question(s)'
        ),
        'uk': (
            'Поїде: каналів {channels} · підсилювачів {amps} · рядків мапи вад {flaws} · '
            'відкритих питань {questions}'
        ),
        'pl': (
            'Pojedzie: kanały: {channels} · wzmacniacze: {amps} · wiersze mapy wad: {flaws} ·'
            ' otwarte pytania: {questions}'
        ),
        'de': (
            'Kommt mit: Kanäle: {channels} · Endstufen: {amps} · Fehlerkarten-Zeilen: {flaws}'
            ' · offene Fragen: {questions}'
        ),
    },
    'npSeedNoChannels': {
        'en': 'Different processor — the channel grid stays behind; onboarding will set it up.',
        'uk': 'Процесор інший — сітка каналів не поїде; її задасть онбординг.',
        'pl': 'Inny procesor — siatka kanałów zostaje; ustali ją onboarding.',
        'de': 'Anderer Prozessor — das Kanalraster bleibt zurück; das Onboarding legt es fest.',
    },
    'npSeedFindingsEvidence': {
        'en': (
            'Those rows were read off captures in the source project — the proof lives there,'
            ' not here.'
        ),
        'uk': 'Ці рядки прочитані із замірів проєкту-джерела — доказ лежить там, не тут.',
        'pl': 'Te wiersze odczytano z pomiarów projektu źródłowego — dowód jest tam, nie tutaj.',
        'de': (
            'Diese Zeilen stammen aus Messungen des Quellprojekts — der Beleg liegt dort, '
            'nicht hier.'
        ),
    },
    # The last part of the «Travels:» line above, not a line of its own (tcc#122).
    'npSeedTravelsFs': {
        'en': 'the Fs of {fs} driver(s)',
        'uk': 'Fs динаміків {fs}',
        'pl': 'Fs głośników: {fs}',
        'de': 'die Fs von Lautsprechern: {fs}',
    },
    'npSeedNote': {
        'en': (
            '**Inherited from `{source}` ({when}).** The system profile was copied from that '
            'project, not written here — check it against this build before relying on it.'
        ),
        'uk': (
            '**Успадковано з `{source}` ({when}).** Профіль системи скопійовано з того '
            'проєкту, а не написано тут — звірте його з цією збіркою, перш ніж на нього '
            'спиратись.'
        ),
        'pl': (
            '**Odziedziczono z `{source}` ({when}).** Profil systemu skopiowano z tamtego '
            'projektu, a nie napisano tutaj — zweryfikuj go z tą instalacją, zanim zaczniesz '
            'na nim polegać.'
        ),
        'de': (
            '**Geerbt von `{source}` ({when}).** Das Systemprofil wurde aus jenem Projekt '
            'kopiert, nicht hier geschrieben — gleiche es mit diesem Aufbau ab, bevor du dich'
            ' darauf verlässt.'
        ),
    },
    'npSeedFailed': {
        'en': 'Nothing was copied: {problem}',
        'uk': 'Нічого не скопійовано: {problem}',
        'pl': 'Nic nie skopiowano: {problem}',
        'de': 'Es wurde nichts kopiert: {problem}',
    },
    'npSeedDone': {
        'en': (
            "System parameters copied from '{source}': {files}. They were inherited, not "
            'measured here — check them against this build.'
        ),
        'uk': (
            'Системні параметри скопійовано з «{source}»: {files}. Вони успадковані, а не '
            'виміряні тут — звірте їх із цією збіркою.'
        ),
        'pl': (
            'Parametry systemu skopiowano z «{source}»: {files}. Są odziedziczone, a nie '
            'zmierzone tutaj — zweryfikuj je z tą instalacją.'
        ),
        'de': (
            'Systemparameter aus „{source}“ kopiert: {files}. Sie sind geerbt, nicht hier '
            'gemessen — gleiche sie mit diesem Aufbau ab.'
        ),
    },
    'npSeedNoSkill': {
        'en': (
            'The autosound-tuning skill is not available here, and the copying lives in it — '
            'install the skill, or fill the new project in by hand.'
        ),
        'uk': (
            'Скіл autosound-tuning тут недоступний, а копіювання живе в ньому — встановіть '
            'скіл або заповніть новий проєкт вручну.'
        ),
        'pl': (
            'Skill autosound-tuning jest tu niedostępny, a kopiowanie mieszka w nim — '
            'zainstaluj skill albo wypełnij nowy projekt ręcznie.'
        ),
        'de': (
            'Der Skill autosound-tuning ist hier nicht verfügbar, und das Kopieren steckt in '
            'ihm — installiere den Skill, oder fülle das neue Projekt von Hand aus.'
        ),
    },
    'npSeedOpen': {
        'en': 'The inherited DSP profile still has {open} fact(s) nobody has confirmed.',
        'uk': 'У успадкованому профілі DSP ще {open} фактів, яких ніхто не підтвердив.',
        'pl': (
            'W odziedziczonym profilu DSP jest jeszcze {open} faktów, których nikt nie '
            'potwierdził.'
        ),
        'de': 'Im geerbten DSP-Profil stehen noch {open} Fakt(en), die niemand bestätigt hat.',
    },
    'npCopy': {
        'en': 'Copy',
        'uk': 'Скопіювати',
        'pl': 'Skopiuj',
        'de': 'Kopieren',
    },
    'npSeedTargetTaken': {
        'en': (
            'The folder “{folder}” already has a project in it. Copying never writes over '
            'facts somebody has confirmed — pick an empty folder, or a new one.'
        ),
        'uk': (
            'У теці «{folder}» вже є проєкт. Копіювання не пише поверх фактів, які хтось '
            'підтвердив, — виберіть порожню або нову теку.'
        ),
        'pl': (
            'W folderze „{folder}” jest już projekt. Kopiowanie nigdy nie nadpisuje faktów, '
            'które ktoś potwierdził — wybierz pusty albo nowy folder.'
        ),
        'de': (
            'Im Ordner „{folder}“ liegt bereits ein Projekt. Kopieren schreibt nie über '
            'Fakten, die jemand bestätigt hat — wähle einen leeren oder einen neuen Ordner.'
        ),
    },
    'npCreate': {
        'en': 'Create',
        'uk': 'Створити',
        'pl': 'Utwórz',
        'de': 'Anlegen',
    },
}
